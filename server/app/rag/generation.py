"""Asset generation with LangGraph + LangChain: the R-A-G of the RAG pipeline.

    START ─(reply?)──► plan_query ─► retrieve ─► generate ─► check_style ─(AI clichés & humanize ≥ 60?)─► rewrite ─► finalize ─► END
          ─(grounded?)────────────► retrieve ─► generate ─► check_style ──────────────────────────────────────────► finalize ─► END
          └─────────────────────────────────────► generate     (zero-shot: same path from generate on, without excerpts)

    plan_query               for replies: the LLM turns the post + the user's angle into a search query
    retrieve  (Retrieval)    the brief (or planned query) is the query; vectorstore.search finds the k best chunks
    generate  (Augmentation) ChatPromptTemplate: instructions (type, platform, length, tone, audience),
                             request (brief, or the post + angle), book background and numbered excerpts
              (Generation)   ChatOpenAI (via OpenRouter) writes the asset and cites excerpts as [n]
    check_style              finds AI-typical clichés ("Imagine a world", "Dive into", emoji piles, ...) and, for
                             video scripts and YouTube pages, missing section headings: then generate runs once more
    rewrite                  at humanize ≥ 60: rephrases just those parts once, keeping facts, quotes and markers
    finalize                 turns the [n] markers into citations and records the clichés that remain

The "humanize" setting (0-100) adds style guidance to the prompt (see core/style.py) and raises the
temperature slightly, so higher values read less like typical AI marketing copy.

The book summaries (summary.py) of the excerpts' sources are added as background. Only the excerpts
the model actually cites become the asset's citations, renumbered [1], [2], ... in order (the GUI
copies the text without the markers). The prompts are Markdown files: prompts/generation_grounded.md,
generation_zero_shot.md, generation_plan_query.md, and the tables generation_asset_types.md and
generation_format_examples.md (core/prompt_files.py). Runs are traced in LangSmith when LANGSMITH_TRACING=true and
LANGSMITH_API_KEY are set (LangChain/LangGraph pick these up automatically).
Retrieval, prompt context and citations live in retrieval.py; the model and its configuration in
core/llm.py and core/config.py.
"""

import logging
import re
from functools import cache
from typing import TypedDict

from langchain_core.messages import AIMessage
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

from app.core import prompt_files
from app.core import prompts, style, tracing
from app.core import state as db
from app.core.config import LLM_MODEL
from app.core.guard import quote_untrusted
from app.core.logs import current_request_id
from app.core.llm import (
    TEMPERATURES, GenerationError, chat_model, is_configured, model_failure, structured, tokens_used,
)
from app.core.schemas import Asset, AssetType, Chunk, Citation, GenerateRequest, Length
from app.core.style import (
    PLATFORM_POST, PLATFORM_REPLY, PLATFORM_VIDEO, REWRITE_FROM, REWRITE_PROMPT, TONES, find_ai_tells,
    style_guidance, temperature_for,
)
from app.db import records
from app.rag import vectorstore
from app.rag.retrieval import format_background, format_context, keep_cited, retrieve_chunks

logger = logging.getLogger(__name__)

# What to write, per asset type; {size} is filled from SIZES by the chosen length, {platform} from
# PLATFORM_POST / PLATFORM_REPLY (inserted into the system prompt).
ASSET_INSTRUCTIONS: dict[AssetType, str] = prompt_files.table("generation_asset_types")

# One worked example per complex format, appended to the instructions: one example shows the layout better than a
# paragraph of rules. A made-up book, so the model takes the structure from it, not the content.
FORMAT_EXAMPLES: dict[AssetType, str] = prompt_files.table("generation_format_examples")

# Headings the complex formats must contain (checked after generation; a draft without them is written once more).
REQUIRED_SECTIONS: dict[AssetType, list[str]] = {
    "video_script": ["HOOK", "SCENE 1", "Visual:", "Voice-over:", "On-screen text:", "CTA", "CAPTION"],
    "youtube_video": ["Title options:", "Description:", "Chapters:", "Tags:"],
}

# The {size} per asset type and length (short, standard, long).
SIZES: dict[str, tuple[str, str, str]] = {
    "blurb": ("50-80", "120-180", "220-300"),
    "youtube_video": ("80-120", "150-250", "300-400"),
    "newsletter": ("120-160", "220-280", "380-450"),
    "ad_copy": ("8-15", "15-30", "30-50"),
    "lead_magnet": ("3", "5", "8"),
    "persona": ("100-150", "200-300", "350-450"),
}
LENGTH_INDEX: dict[Length, int] = {"short": 0, "standard": 1, "long": 2}




GROUNDED_PROMPT = prompt_files.chat_prompt("generation_grounded")  # prompts/generation_grounded.md
ZERO_SHOT_PROMPT = prompt_files.chat_prompt("generation_zero_shot")  # prompts/generation_zero_shot.md
PLAN_QUERY_PROMPT = prompt_files.chat_prompt("generation_plan_query")  # prompts/generation_plan_query.md


class GeneratedText(BaseModel):
    """Structured output of a grounded generation call: the text plus the excerpts it is based on.

    Short formats (posts, replies) often come back without inline [n] markers; the separate
    used_sources list makes sure their sources are still known.
    """

    text: str = Field(min_length=1, description="The asset text, with [n] citation markers after statements that "
                                                "use an excerpt.")
    used_sources: list[int] = Field(description="Numbers of all source excerpts the text draws on (facts, ideas or quotes).")


class SearchQuery(BaseModel):
    """Structured output of the query planning step (replies)."""

    query: str = Field(min_length=3, max_length=300, description="One search query of at most 25 words naming the "
                                                                 "topics, claims or questions the reply should address.")


class GenerationState(TypedDict, total=False):
    """State passed through the LangGraph graph.

    Inputs: project_id, req (the GenerateRequest). Set by plan_query or retrieve: query, context.
    Set by generate/rewrite: draft, used, tokens. Set by check_style: ai_tells. Set by finalize: text, citations.
    """

    project_id: str
    req: GenerateRequest
    query: str  # what is searched in the books: the brief, or for replies the planned query
    context: list[tuple[Chunk, float]]  # retrieved chunks with similarity, best first
    draft: str  # the model's text with its original [n] excerpt numbers
    used: list[int]  # excerpt numbers the model reported as used (structured output)
    ai_tells: list[str]  # AI-typical phrases found in the draft (check_style) / final text (finalize)
    missing_sections: list[str]  # required headings the draft lacks (check_style; video_script, youtube_video)
    attempts: int  # drafts checked so far; a draft without its required headings is written once more
    rewritten: bool  # True after the rewrite step ran (it runs at most once)
    text: str  # the generated asset text, citation markers renumbered
    citations: list[Citation]  # the cited chunks, in marker order
    tokens: int  # LLM tokens used (prompt + completion), from the model's usage metadata


# Version of this feature's prompts, e.g. "generation@3f9a1c2e"; changes by itself when a prompt changes (core/prompts.py).
PROMPT_VERSION = prompts.register("generation", GROUNDED_PROMPT, ZERO_SHOT_PROMPT, PLAN_QUERY_PROMPT, ASSET_INSTRUCTIONS,
                                 FORMAT_EXAMPLES, GeneratedText, SearchQuery, {"plan_query": TEMPERATURES["plan_query"]}, REWRITE_PROMPT, style.PLATFORM_POST, style.PLATFORM_REPLY,
                                 style.PLATFORM_VIDEO, style.TONES, style.HUMAN_LEVELS, style.AI_TELLS)


# ---------- Public API ----------
def create_asset(project_id: str, req: GenerateRequest) -> Asset:
    """Generate an asset (generate_asset), store it in the project and save it to disk.

    Used by POST /generate and the chat tool draft_social_post (chat_tools.py).

    Raises:
        GenerationError: As generate_asset.
        OSError: If the generated asset cannot be saved (it is then not stored in memory either).
    """
    result = generate_asset(project_id, req)
    asset = Asset(
        id=db.new_id("ast"),
        project_id=project_id,
        asset_type=req.asset_type,
        grounded=req.grounded,
        brief=req.brief,
        text=result["text"],
        citations=result.get("citations", []),
        created_at=db.now(),
        tokens=result.get("tokens", 0),
        tone=req.tone,
        length=req.length,
        audience=req.audience,
        platform=("facebook" if req.asset_type == "reader_question"
                  else req.platform if req.asset_type in ("social_post", "social_reply", "video_script") else None),
        source_ids=req.source_ids or [],
        reply_to=req.reply_to,
        search_query=result.get("query", ""),
        humanize=req.humanize,
        ai_tells=result.get("ai_tells", []),
        model=LLM_MODEL,
        prompt_version=PROMPT_VERSION,
    )
    records.save_assets([asset])  # first in the database: if that fails, the asset is not kept anywhere
    db.assets[asset.id] = asset
    return asset


def generate_asset(project_id: str, req: GenerateRequest) -> GenerationState:
    """Run the generation graph for one asset.

    Args:
        project_id: Project whose sources ground the asset.
        req: What to write: asset type, brief, grounded flag, k, tone, length, audience, platform,
            and for replies the post to reply to.

    Returns:
        The final graph state; use "text", "citations" (empty when zero-shot), "tokens" (LLM tokens
        used), "query" (what was searched in the books, missing when zero-shot) and "ai_tells"
        (AI-typical phrases that remain in the text).

    Raises:
        GenerationError: 503 if no API key is configured, 502 if retrieval or the model call fails,
            504 if the provider timed out after all retries.
    """
    if not is_configured():
        raise GenerationError(503, "No API key set. Add OPENROUTER_API_KEY (or OPENAI_API_KEY) and restart the server.")
    mode = "grounded" if req.grounded else "zero-shot"
    try:
        with tracing.scope():
            state = _graph().invoke(
                {"project_id": project_id, "req": req},
                config={"run_name": f"generate_{req.asset_type}", "tags": [mode, req.asset_type],
                        "metadata": {"request_id": current_request_id(), "prompt_version": PROMPT_VERSION,
                                     "project_id": project_id, "llm_model": LLM_MODEL, "operation": f"generate_{req.asset_type}"}},
            )
    except GenerationError:
        raise
    except vectorstore.VectorStoreError as e:
        raise model_failure(e, None) from e
    except Exception as e:
        logger.exception("Generation failed")
        raise model_failure(e) from e
    return state


def build_instructions(req: GenerateRequest) -> str:
    """The "what to write" part of the system prompt, from asset type, length/platform, tone and audience.

    Example: "one social media post for LinkedIn: 80-200 words, ... Tone: warm and friendly.
    Target audience: urban planners."
    """
    template = ASSET_INSTRUCTIONS[req.asset_type]
    if req.asset_type == "social_post":
        text = template.format(platform=PLATFORM_POST[req.platform])
    elif req.asset_type == "social_reply":
        text = template.format(platform=PLATFORM_REPLY[req.platform])
    elif req.asset_type == "video_script":
        text = template.format(platform=PLATFORM_VIDEO[req.platform])
    elif req.asset_type == "reader_question":
        text = template
    else:
        text = template.format(size=SIZES[req.asset_type][LENGTH_INDEX[req.length]])
    if TONES[req.tone]:
        text += f" Tone: {TONES[req.tone]}."
    if req.audience.strip():
        text += f" Target audience: {req.audience.strip()}."
    if example := FORMAT_EXAMPLES.get(req.asset_type):
        text += ("\n\nExample of the format only (a made-up book: take the structure and labels from it, never its "
                 f"content):\n<example>\n{example}\n</example>")
    return text


def missing_sections(asset_type: AssetType, text: str) -> list[str]:
    """The required headings (REQUIRED_SECTIONS) a text lacks, e.g. ["CTA"]; [] for formats without any.

    A heading counts at the start of a line, in any case, also with stray Markdown (** or #) around it.
    """
    return [heading for heading in REQUIRED_SECTIONS.get(asset_type, [])
            if not re.search(rf"^[\s*#]*{re.escape(heading.rstrip(':'))}\b", text, re.IGNORECASE | re.MULTILINE)]


def emojis_are_normal(req: GenerateRequest) -> bool:
    """True for formats where several emojis are normal: Instagram and TikTok posts/replies, and short video scripts."""
    if req.asset_type == "video_script":
        return True
    return req.asset_type in ("social_post", "social_reply") and req.platform in ("instagram", "tiktok")


def build_request(req: GenerateRequest) -> str:
    """The user's request for the human message: the brief, or for replies the post plus the optional angle."""
    if req.asset_type == "social_reply":
        angle = req.brief.strip() or "(none: reply as you see fit)"
        return f"Post to reply to:\n{quote_untrusted(req.reply_to, 'post')}\n\nMy angle: {angle}"
    return f"Brief: {req.brief.strip()}"


# ---------- Graph ----------
@cache
def _graph():
    """Build and compile the LangGraph:
    START → (plan_query →) (retrieve →) generate → check_style → (generate again →) (rewrite →) finalize → END."""
    builder = StateGraph(GenerationState)
    builder.add_node("plan_query", _plan_query)
    builder.add_node("retrieve", _retrieve)
    builder.add_node("generate", _generate)
    builder.add_node("check_style", _check_style)
    builder.add_node("rewrite", _rewrite)
    builder.add_node("finalize", _finalize)
    builder.add_conditional_edges(START, _route, {"plan_query": "plan_query", "retrieve": "retrieve", "generate": "generate"})
    builder.add_edge("plan_query", "retrieve")
    builder.add_edge("retrieve", "generate")
    builder.add_edge("generate", "check_style")
    builder.add_conditional_edges("check_style", _after_check,
                                  {"generate": "generate", "rewrite": "rewrite", "finalize": "finalize"})
    builder.add_edge("rewrite", "finalize")
    builder.add_edge("finalize", END)
    return builder.compile()


def _route(state: GenerationState) -> str:
    """Entry edge: grounded replies plan a search query first, other grounded requests retrieve
    directly with the brief, zero-shot ones go straight to generation."""
    req = state["req"]
    if not req.grounded:
        return "generate"
    return "plan_query" if req.asset_type == "social_reply" else "retrieve"


def _plan_query(state: GenerationState) -> GenerationState:
    """Query planning node (replies): condense the post and the user's angle into a focused search query.

    A pasted post is often long and full of things the book has nothing to say about; searching with
    a short query of its key topics finds better passages than searching with the whole post.
    """
    planned, tokens = structured(PLAN_QUERY_PROMPT, {"request": build_request(state["req"])}, SearchQuery,
                                 "search query", TEMPERATURES["plan_query"])
    return {"query": planned.query.strip(), "tokens": tokens}


def _retrieve(state: GenerationState) -> GenerationState:
    """Retrieval node: the planned query (replies) or the brief is the query; returns the k most similar chunks.

    Raises:
        GenerationError: If the project has no searchable chunks (nothing to ground on).
    """
    req = state["req"]
    query = state.get("query") or req.brief
    context = retrieve_chunks(state["project_id"], query, req.k, req.source_ids, operation=f"generate_{req.asset_type}")
    if not context:
        raise GenerationError(502, "No searchable passages found. Upload and process a book first (or check the selected book).")
    return {"query": query, "context": context}


def _generate(state: GenerationState) -> GenerationState:
    """Augmentation + generation node: fill the prompt (with the style for the humanize level), call the model.

    Grounded: the excerpts are numbered [1]..[k] in the prompt and the summaries of their books are
    added as background; structured output returns the text plus the excerpt numbers it used.
    The text keeps the model's original numbers here; finalize turns them into citations.
    The token usage of this call is added to that of plan_query (if any) as "tokens".
    """
    req = state["req"]
    request = build_request(req)
    if missing := state.get("missing_sections"):  # second attempt after the format check
        request += (f"\n\n(A first draft lacked these required section headings: {', '.join(missing)}. Use exactly "
                    "the headings of the requested format.)")
    values = {"instructions": build_instructions(req), "request": request, "style": style_guidance(req.humanize)}
    model = chat_model(temperature_for(req.humanize))
    tokens_before = state.get("tokens", 0)
    if not req.grounded:
        reply: AIMessage = (ZERO_SHOT_PROMPT | model).invoke(values)
        return {"draft": str(reply.content).strip(), "used": [], "tokens": tokens_before + tokens_used(reply)}

    context = state["context"]
    parsed, tokens = structured(
        GROUNDED_PROMPT, {**values, "background": format_background(context), "context": format_context(context)},
        GeneratedText, "asset text", temperature=temperature_for(req.humanize))
    return {"draft": parsed.text.strip(), "used": parsed.used_sources, "tokens": tokens_before + tokens}


def _check_style(state: GenerationState) -> GenerationState:
    """Check node (no model call): AI-typical clichés in the draft, and required section headings it lacks."""
    req = state["req"]
    missing = missing_sections(req.asset_type, state["draft"])
    return {"ai_tells": find_ai_tells(state["draft"], emojis_are_normal(req)), "missing_sections": missing,
            "attempts": state.get("attempts", 0) + 1}


def _after_check(state: GenerationState) -> str:
    """Edge after check_style: write the draft once more if required headings are missing; else rewrite once if
    clichés were found and humanize is at least REWRITE_FROM; else finalize."""
    if state["missing_sections"] and state["attempts"] < 2:
        logger.info("%s draft lacks %s; writing it once more", state["req"].asset_type, state["missing_sections"])
        return "generate"
    if state["ai_tells"] and state["req"].humanize >= REWRITE_FROM and not state.get("rewritten"):
        return "rewrite"
    return "finalize"


def _rewrite(state: GenerationState) -> GenerationState:
    """Rewrite node: rephrase just the found clichés, keeping facts, quotes, format and [n] markers."""
    humanize = state["req"].humanize
    reply: AIMessage = (REWRITE_PROMPT | chat_model(temperature_for(humanize))).invoke({
        "tells": ", ".join(f'"{t}"' for t in state["ai_tells"]), "style": style_guidance(humanize), "text": state["draft"],
    })
    return {"draft": str(reply.content).strip() or state["draft"], "rewritten": True,
            "tokens": state.get("tokens", 0) + tokens_used(reply)}


def _finalize(state: GenerationState) -> GenerationState:
    """Final node: turn the [n] markers (and reported sources) into citations; record the clichés that remain."""
    draft = state["draft"]
    if missing := missing_sections(state["req"].asset_type, draft):
        logger.warning("%s still lacks %s after %d drafts", state["req"].asset_type, missing, state.get("attempts", 1))
    if state["req"].grounded:
        result = keep_cited(draft, state["context"], also_cited=state.get("used", []))
    else:
        result = {"text": draft, "citations": []}
    return {**result, "ai_tells": find_ai_tells(result["text"], emojis_are_normal(state["req"]))}
