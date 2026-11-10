"""Discussion Relevance Agent (Market Intelligence): is a discussion from another platform a good opportunity for
the author to contribute from one book, and if so, a reply grounded in that book.

    START ─► research ─(tool calls?)─► research_tools ─┐
                ▲  │                                    │
                └──┼────────────────────────────────────┘
                   └─(no tool calls, or a limit)─► assess ─(contribute)─► draft ─► check ─────────► finalize ─► END
                                                      │                         │  ▲               ▲
                                                      │      (AI clichés and    ▼  │               │
                                                      │       humanize ≥ 60)   rewrite             │
                                                      └──(more_context / skip)─────────────────────┘

    research        the agent: the chat model with the tools bound (discussion_tools.py: get_book_profile,
                    search_book_material) decides what to call. It reads the book's profile, searches the book for
                    each point of the discussion, and stops by answering without tool calls: short research notes
                    that link the discussion's points to passage numbers. This is a loop (unlike the chat's one tool
                    round), with hard limits: at most MAX_ROUNDS model calls and MAX_TOOL_CALLS tool calls; at a
                    limit the research ends without a further model call
    research_tools  runs the requested calls (chat_tools.run_tool_calls: results quoted as data, errors returned to the
                    model) and adds their results to the messages
    assess          structured output (Assessment): contribute, more_context or skip, with the reason. Without any
                    passage found, "contribute" is overruled in code to "skip": a reply must be grounded in the book
    draft           only for contribute: structured output (DraftReply), a reply for the platform written from the
                    numbered passages only, plus the advice whether to name the book
    check           pure code: the platform's hard character limit and AI clichés (style.find_ai_tells). Not
                    platforms.check_platform_fit, whose hashtag and word advice is for posts, not replies
    rewrite         like the generator's humanizer: when check found AI clichés and the "how human" setting is at
                    least style.REWRITE_FROM, the model rephrases just those parts once (style.REWRITE_PROMPT), keeping
                    facts and [n] markers; then check runs again on the new text
    finalize        the [n] markers of the reason and the reply become one list of citations, numbered in order of
                    first use across both texts (retrieval.keep_cited)

"Own Page" mode (DiscussionRequest.facebook_comment_id set: a reader's comment on the author's Facebook Page): the same
graph, but the assess prompt knows that answering readers there is welcome (SITUATION) and the draft is written as the
author in the first person, where naming the book is natural (ROLE).

The tone (DiscussionRequest.tone, style.TONES) is added to the reply rules of the draft prompt. The "how human"
setting (DiscussionRequest.humanize, 0-100) works as in the generator: style guidance in the draft
prompt (style.style_guidance), the draft's temperature (style.temperature_for) and the rewrite step.

The pasted discussion is someone else's text: it reaches the model only inside a <post> block (guard.quote_untrusted)
under guard.UNTRUSTED_RULE; the passages come as <passage> blocks. Checking the discussion with the guard and saving the
result is up to the caller (api/discussions.py). Runs are traced in LangSmith as "analyze_discussion" when tracing is on.

The API-facing models (DiscussionRequest, DiscussionAnalysis, ...) are in core/schemas.py. Assessment and DraftReply
below are what the chat model fills in with structured output; their Field descriptions are part of the prompt.
"""

import logging
from functools import cache
from typing import TypedDict

from langchain_core.messages import AIMessage, BaseMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field, model_validator

from app.core import prompt_files
from app.agents.discussion_tools import MAX_PASSAGES, SEARCH_K, Research, make_tools, start_research
from app.core import prompts, tracing
from app.core import state as db
from app.core.config import LLM_MODEL
from app.core.guard import check_output, injection_note, quote_untrusted, scan_third_party
from app.core.llm import TEMPERATURES, GenerationError, chat_model, is_configured, model_failure, structured, tokens_used
from app.core.logs import current_request_id
from app.core.platforms import PLATFORM_RULES, _publishable
from app.core.schemas import (
    BookMention, Citation, DiscussionAnalysis, DiscussionPlatform, DiscussionRequest, Recommendation, ToolCallRecord,
)
from app.core.style import (
    PLATFORM_REPLY, REWRITE_FROM, REWRITE_PROMPT, TONES, find_ai_tells, style_guidance, temperature_for,
)
from app.rag import vectorstore
from app.rag.chat_tools import run_tool_calls
from app.rag.retrieval import format_context, keep_cited, source_name

logger = logging.getLogger(__name__)

MAX_ROUNDS = 4  # model calls in the research loop
MAX_TOOL_CALLS = 6  # tool calls in the whole research
MAX_RESULT_CHARS = 12000  # a tool result is cut to this length for the model (4 passages of ~500 tokens fit)

# How to write the reply, per platform. The social platforms use the generator's reply rules (style.PLATFORM_REPLY).
REPLY_RULES: dict[DiscussionPlatform, str] = {**PLATFORM_REPLY, **prompt_files.table("discussion_reply_rules")}

RESEARCH_PROMPT = prompt_files.chat_prompt("discussion_research")  # prompts/discussion_research.md

# Where the discussion is: elsewhere (the author joins as a knowledgeable person) or on the author's own Facebook Page
# (a reader's comment, answered as the author). Filled into the assess and draft prompts.
# (prompts/discussion_situation.md; a non-empty situation ends with a line break before "Decide ...")
SITUATION = {mode: text + "\n" if text else "" for mode, text in prompt_files.table("discussion_situation").items()}
ROLE = prompt_files.table("discussion_role")  # prompts/discussion_role.md

ASSESS_PROMPT = prompt_files.chat_prompt("discussion_assess")  # prompts/discussion_assess.md

DRAFT_PROMPT = prompt_files.chat_prompt("discussion_draft")  # prompts/discussion_draft.md


class Assessment(BaseModel):
    """Your assessment of whether the author should join this discussion with material from their book."""

    recommendation: Recommendation = Field(
        description="'contribute' if the book's passages can add something useful to what is being discussed; "
                    "'more_context' if the pasted text is too short or unclear to judge (e.g. replies without the "
                    "question they answer); 'skip' if the book has nothing useful to add or a reply would only be "
                    "advertising.")
    reason: str = Field(min_length=1, description="2-4 sentences for the author: what the discussion is about and "
                                                  "how the book's passages connect to it, or why they do not. Put [n] "
                                                  "after a statement that uses passage n.")
    missing_context: str = Field(default="", description="Only for 'more_context': what the author should copy in "
                                                         "addition (e.g. the original post). Otherwise empty.")
    used_sources: list[int] = Field(default=[], description="Numbers of all passages the reason draws on.")

    @model_validator(mode="after")
    def _context_only_when_needed(self) -> "Assessment":
        """Ask for missing context with 'more_context' and drop it otherwise, so the GUI shows it only then."""
        if self.recommendation == "more_context" and not self.missing_context.strip():
            raise ValueError("missing_context must say what the author should add.")
        if self.recommendation != "more_context":
            self.missing_context = ""
        return self


class DraftReply(BaseModel):
    """A reply the author can post in the discussion, written from the book's passages."""

    reply: str = Field(min_length=1, description="The reply in plain text, in the discussion's language, as a "
                                                 "person taking part: answer what was asked, add the book's idea or "
                                                 "example, with [n] right after each statement that uses passage n. "
                                                 "No sales pitch.")
    used_sources: list[int] = Field(min_length=1, description="Numbers of all passages the reply draws on.")
    mention_book: bool = Field(description="True if naming the book would genuinely help the readers (e.g. someone "
                                           "asked for reading); False if it would look like advertising.")
    mention_reason: str = Field(min_length=1, description="One sentence for the author: why to name the book, or why "
                                                          "not.")


class DiscussionState(TypedDict, total=False):
    """State of the Discussion Relevance Agent's graph."""

    project_id: str
    discussion: str  # the pasted text, already checked by the guard
    platform: DiscussionPlatform
    angle: str  # what the author would like to bring in; "" = nothing particular
    humanize: int  # how human the reply should sound (0-100)
    tone: str  # the reply's tone (schemas.Tone)
    own_page: bool  # a reader's comment on the author's own Facebook Page: answered as the author
    research: Research  # the book and every passage found, numbered for citations
    messages: list[BaseMessage]  # the research prompt, the model's tool calls and their results
    tool_calls: list[ToolCallRecord]  # every tool call of the run, for the GUI
    rounds: int  # model calls made in the research loop
    research_stop: str  # why the research ended: "done" (the model stopped) or "limit"
    notes: str  # the model's research notes ("" if the research ended at a limit)
    assessment: Assessment
    draft: DraftReply  # only for contribute
    platform_issues: list[str]  # problems of the draft for the platform
    injection_findings: list[str]  # high-risk findings of the discussion's injection scan (for the prompt note)
    output_issues: list[str]  # what the output guard found in the draft
    ai_tells: list[str]  # AI clichés found in the draft by the last check
    rewritten: bool  # the rewrite step ran (it runs at most once)
    reason: str  # final texts, with [n] renumbered to match citations
    suggested_reply: str
    citations: list[Citation]
    tokens: int


# Version of this feature's prompts, schemas, tool descriptions and settings (core/prompts.py).
PROMPT_VERSION = prompts.register(
    "discussion", RESEARCH_PROMPT, ASSESS_PROMPT, DRAFT_PROMPT, Assessment, DraftReply, REPLY_RULES, SITUATION, ROLE,
    [t.description for t in make_tools(Research(project_id="", source_id=""))],
    REWRITE_PROMPT, {"temperatures": {k: TEMPERATURES[k] for k in ("research", "assess")}, "rewrite_from": REWRITE_FROM,
     "max_rounds": MAX_ROUNDS, "max_tool_calls": MAX_TOOL_CALLS, "search_k": SEARCH_K, "max_passages": MAX_PASSAGES})


# ---------- Public API ----------
def analyze_discussion(project_id: str, req: DiscussionRequest) -> DiscussionAnalysis:
    """Run the Discussion Relevance Agent on a discussion for one book. Nothing is saved.

    Args:
        project_id: The client whose book to use.
        req: The book, the discussion (already checked and cleaned by the guard), URL, platform and angle.

    Returns:
        The analysis with a new id; reply = suggested_reply until the author edits it.

    Raises:
        BookNotReady: If the book is not a processed book of this client.
        GenerationError: 503 if no API key is configured; 502 if a model call or the search fails; 504 on a timeout.
    """
    if not is_configured():
        raise GenerationError(503, "No API key set. Add OPENROUTER_API_KEY (or OPENAI_API_KEY) and restart the server.")
    research = start_research(project_id, req.source_id)
    risk, findings = scan_third_party(req.discussion)
    if risk == "high":
        logger.warning("Discussion with a likely prompt injection (%s); analysed as quoted data with a security note",
                       ", ".join(f.split(":", 1)[0] for f in findings))
    try:
        with tracing.scope():
            state = _graph().invoke(
                {"project_id": project_id, "discussion": req.discussion, "platform": req.platform, "angle": req.angle,
                 "humanize": req.humanize, "tone": req.tone, "own_page": bool(req.facebook_comment_id),
                 "research": research, "injection_findings": findings if risk == "high" else []},
                config={"run_name": "analyze_discussion", "tags": ["discussion", "agent"],
                        "metadata": {"request_id": current_request_id(), "prompt_version": PROMPT_VERSION,
                                     "project_id": project_id, "source_id": req.source_id, "llm_model": LLM_MODEL,
                                     "platform": req.platform, "humanize": req.humanize, "tone": req.tone,
                                     "own_page": bool(req.facebook_comment_id)}},
            )
    except GenerationError:
        raise
    except vectorstore.VectorStoreError as e:
        raise model_failure(e, None) from e
    except Exception as e:
        logger.exception("Discussion analysis failed")
        raise model_failure(e) from e
    assessment, draft = state["assessment"], state.get("draft")
    now = db.now()
    return DiscussionAnalysis(
        id=db.new_id("dsc"), project_id=project_id, source_id=req.source_id, discussion=req.discussion, url=req.url,
        platform=req.platform, angle=req.angle, recommendation=assessment.recommendation, reason=state["reason"],
        missing_context=assessment.missing_context, suggested_reply=state.get("suggested_reply", ""),
        reply=state.get("suggested_reply", ""),
        book_mention=BookMention(suggest=draft.mention_book, reason=draft.mention_reason) if draft else None,
        citations=state["citations"], search_queries=list(research.queries), tool_calls=state.get("tool_calls", []),
        platform_issues=state.get("platform_issues", []), injection_risk=risk, injection_findings=findings,
        output_issues=state.get("output_issues", []), humanize=req.humanize, tone=req.tone,
        facebook_comment_id=req.facebook_comment_id, model=LLM_MODEL, prompt_version=PROMPT_VERSION,
        tokens=state.get("tokens", 0), created_at=now, updated_at=now)


# ---------- Graph ----------
@cache
def _graph():
    """Build and compile the LangGraph: START → research ⇄ research_tools → assess → (draft → check (⇄ rewrite) →)
    finalize → END."""
    builder = StateGraph(DiscussionState)
    builder.add_node("research", _research)
    builder.add_node("research_tools", _research_tools)
    builder.add_node("assess", _assess)
    builder.add_node("draft", _draft)
    builder.add_node("check", _check)
    builder.add_node("rewrite", _rewrite)
    builder.add_node("finalize", _finalize)
    builder.add_edge(START, "research")
    builder.add_conditional_edges("research", _after_research, {"research_tools": "research_tools", "assess": "assess"})
    builder.add_edge("research_tools", "research")
    builder.add_conditional_edges("assess", _after_assess, {"draft": "draft", "finalize": "finalize"})
    builder.add_edge("draft", "check")
    builder.add_conditional_edges("check", _after_check, {"rewrite": "rewrite", "finalize": "finalize"})
    builder.add_edge("rewrite", "check")
    builder.add_edge("finalize", END)
    return builder.compile()


def _research(state: DiscussionState) -> DiscussionState:
    """Research node: the model, with the tools bound, either calls tools or ends the research with its notes.

    The first call builds the prompt from the discussion (quoted as data). When a limit is reached (MAX_ROUNDS model
    calls or MAX_TOOL_CALLS tool calls), the research ends without another model call.
    """
    messages = state.get("messages") or RESEARCH_PROMPT.format_messages(
        max_tool_calls=MAX_TOOL_CALLS, platform=state.get("platform", "forum"), angle=_angle(state),
        discussion=_quoted_discussion(state))
    rounds, used = state.get("rounds", 0), len(state.get("tool_calls", []))
    if rounds >= MAX_ROUNDS or used >= MAX_TOOL_CALLS:
        logger.info("Discussion research stopped at a limit (%d model calls, %d tool calls)", rounds, used)
        return {"messages": messages, "research_stop": "limit", "notes": ""}
    model = chat_model(TEMPERATURES["research"]).bind_tools(make_tools(state["research"]))
    reply: AIMessage = model.invoke(messages)
    update: DiscussionState = {"messages": [*messages, reply], "rounds": rounds + 1,
                               "tokens": state.get("tokens", 0) + tokens_used(reply)}
    if not reply.tool_calls:
        update |= {"research_stop": "done", "notes": str(reply.text).strip()}
    return update


def _after_research(state: DiscussionState) -> str:
    """Run the tools if the model's last reply asks for them, else assess."""
    last = state["messages"][-1]
    return "research_tools" if isinstance(last, AIMessage) and last.tool_calls else "assess"


def _research_tools(state: DiscussionState) -> DiscussionState:
    """Research tools node: run the model's tool calls (only as many as the limit still allows)."""
    done = state.get("tool_calls", [])
    tool_messages, records = run_tool_calls(state["project_id"], state["messages"][-1].tool_calls,
                                            tools=make_tools(state["research"]),
                                            max_calls=MAX_TOOL_CALLS - len(done), max_result_chars=MAX_RESULT_CHARS)
    return {"messages": [*state["messages"], *tool_messages], "tool_calls": [*done, *records]}


def _assess(state: DiscussionState) -> DiscussionState:
    """Assess node: the recommendation and its reason (structured output). "contribute" without any passage found is
    overruled to "skip", since there would be nothing from the book to say."""
    research = state["research"]
    assessment, used = structured(ASSESS_PROMPT, {
        "book": _book(research), "platform": state.get("platform", "forum"), "angle": _angle(state),
        "situation": SITUATION[_mode(state)], "discussion": _quoted_discussion(state),
        "notes": quote_untrusted(state.get("notes") or "(none)", "background"),
        "context": format_context(research.passages) or "(none: no passage of the book is relevant enough)",
    }, Assessment, "assessment", TEMPERATURES["assess"])
    if assessment.recommendation == "contribute" and not research.passages:
        logger.info("Assessment said contribute without passages; changed to skip")
        assessment = Assessment(recommendation="skip", reason="The searches found no passage of the book that relates "
                                                              "closely enough to this discussion, so a reply could not "
                                                              "be grounded in the book.")
    return {"assessment": assessment, "tokens": state.get("tokens", 0) + used}


def _after_assess(state: DiscussionState) -> str:
    """Draft a reply only when the recommendation is to contribute."""
    return "draft" if state["assessment"].recommendation == "contribute" else "finalize"


def _draft(state: DiscussionState) -> DiscussionState:
    """Draft node: a reply for the platform from the passages only, with the advice whether to name the book."""
    research = state["research"]
    platform = state.get("platform", "forum")
    draft, used = structured(DRAFT_PROMPT, {
        "rules": _rules(state), "role": ROLE[_mode(state)], "style": style_guidance(_humanize(state)),
        "book": _book(research),
        "angle": _angle(state), "reason": state["assessment"].reason, "discussion": _quoted_discussion(state),
        "context": format_context(research.passages),
    }, DraftReply, "reply draft", temperature_for(_humanize(state)))
    return {"draft": draft, "tokens": state.get("tokens", 0) + used}


def _check(state: DiscussionState) -> DiscussionState:
    """Check node: the draft against the platform's hard character limit, AI clichés and the output guard
    (guard.check_output: injection patterns, links not found in the passages). No model call."""
    platform = state.get("platform", "forum")
    text = _publishable(state["draft"].reply)
    issues = []
    if (rules := PLATFORM_RULES.get(platform)) and len(text) > rules.max_chars:
        issues.append(f"Too long for {rules.label}: {len(text)} characters, the limit is {rules.max_chars}.")
    if tells := find_ai_tells(text, emojis_expected=platform in ("instagram", "tiktok")):
        issues.append("Sounds AI-written: " + ", ".join(tells) + ".")
    # Output guard: an injection in the discussion that got through, or a link the book's passages don't contain.
    research = state.get("research")
    passages = "\n".join(chunk.text for chunk, _ in research.passages) if research else ""
    return {"platform_issues": issues, "ai_tells": tells, "output_issues": check_output(text, allowed=passages)}


def _after_check(state: DiscussionState) -> str:
    """Rewrite once when AI clichés were found and the "how human" setting asks for it; else finalize."""
    if state["ai_tells"] and _humanize(state) >= REWRITE_FROM and not state.get("rewritten"):
        return "rewrite"
    return "finalize"


def _rewrite(state: DiscussionState) -> DiscussionState:
    """Rewrite node: rephrase just the found clichés (the generator's REWRITE_PROMPT), keeping facts and [n] markers.
    An empty answer keeps the draft."""
    humanize, draft = _humanize(state), state["draft"]
    reply: AIMessage = chat_model(temperature_for(humanize)).invoke(REWRITE_PROMPT.format_messages(
        tells=", ".join(f'"{t}"' for t in state["ai_tells"]), style=style_guidance(humanize), text=draft.reply))
    text = str(reply.content).strip()
    return {"draft": draft.model_copy(update={"reply": text}) if text else draft, "rewritten": True,
            "tokens": state.get("tokens", 0) + tokens_used(reply)}


_SPLIT = "\x00"  # joins reason and reply for keep_cited; never part of model text (the guard removes control characters)


def _finalize(state: DiscussionState) -> DiscussionState:
    """Finalize node: one list of citations for the reason and the reply, numbered in order of first use across both
    (reason first), with their [n] markers renumbered to match."""
    assessment, draft = state["assessment"], state.get("draft")
    reply = draft.reply.replace(_SPLIT, "").strip() if draft else ""
    text = assessment.reason.replace(_SPLIT, "").strip() + (_SPLIT + reply if draft else "")
    used = [*assessment.used_sources, *(draft.used_sources if draft else [])]
    cited = keep_cited(text, state["research"].passages, also_cited=used)
    reason, _, reply = cited["text"].partition(_SPLIT)
    return {"reason": reason.strip(), "suggested_reply": reply.strip(), "citations": cited["citations"]}


# ---------- Helpers ----------
def _quoted_discussion(state: DiscussionState) -> str:
    """The discussion as data for a prompt: a <post platform="..."> block, followed by the app's security note when
    the injection scan found a likely injection in it (guard.injection_note)."""
    return (quote_untrusted(state["discussion"], "post", platform=state.get("platform", "forum"))
            + injection_note(state.get("injection_findings", [])))


def _rules(state: DiscussionState) -> str:
    """How to write the reply: the platform's reply rules, plus the tone unless it is neutral."""
    rules = REPLY_RULES[state.get("platform", "forum")]
    tone = TONES.get(state.get("tone", "neutral"), "")
    return f"{rules}; tone: {tone}" if tone else rules


def _humanize(state: DiscussionState) -> int:
    """The run's "how human" setting (the request's default when the state has none, e.g. in tests)."""
    return state.get("humanize", DiscussionRequest.model_fields["humanize"].default)


def _mode(state: DiscussionState) -> str:
    """The prompt mode: "own_page" for a reader's comment on the author's Facebook Page, else "discussion"."""
    return "own_page" if state.get("own_page") else "discussion"


def _angle(state: DiscussionState) -> str:
    return state.get("angle") or "(nothing particular)"


def _book(research: Research) -> str:
    """The book for a prompt: "Title — Author", and its overview when a summary exists."""
    name = source_name(research.source_id) or research.source_id
    summary = db.summaries.get(research.source_id)
    return name + (f"\nWhat the book is about:\n{quote_untrusted(summary.summary, 'background')}" if summary else "")
