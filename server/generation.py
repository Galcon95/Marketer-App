"""Asset generation with LangGraph + LangChain: the R-A-G of the RAG pipeline.

    START ─(reply?)──► plan_query ─► retrieve ─► generate ─► check_style ─(AI clichés & humanize ≥ 60?)─► rewrite ─► finalize ─► END
          ─(grounded?)────────────► retrieve ─► generate ─► check_style ──────────────────────────────────────────► finalize ─► END
          └─────────────────────────────────────► generate     (zero-shot: same path from generate on, without excerpts)

    plan_query               for replies: the LLM turns the post + the user's angle into a search query
    retrieve  (Retrieval)    the brief (or planned query) is the query; vectorstore.search finds the k best chunks
    generate  (Augmentation) ChatPromptTemplate: instructions (type, platform, length, tone, audience),
                             request (brief, or the post + angle), book background and numbered excerpts
              (Generation)   ChatOpenAI (via OpenRouter) writes the asset and cites excerpts as [n]
    check_style              finds AI-typical clichés ("Imagine a world", "Dive into", emoji piles, ...)
    rewrite                  at humanize ≥ 60: rephrases just those parts once, keeping facts, quotes and markers
    finalize                 turns the [n] markers into citations and records the clichés that remain

The "humanize" setting (0-100) adds style guidance to the prompt (see HUMAN_LEVELS) and raises the
temperature slightly, so higher values read less like typical AI marketing copy.

The book summaries (summary.py) of the excerpts' sources are added as background. Only the excerpts
the model actually cites become the asset's citations, renumbered [1], [2], ... in order (the GUI
copies the text without the markers). Runs are traced in LangSmith when LANGSMITH_TRACING=true and
LANGSMITH_API_KEY are set (LangChain/LangGraph pick these up automatically).

Configuration: OPENROUTER_API_KEY (or OPENAI_API_KEY, see vectorstore.py); LLM_MODEL optional
(default "openai/gpt-4o-mini" via OpenRouter, "gpt-4o-mini" via OpenAI).
"""

import logging
import os
import re
from functools import cache
from typing import TypedDict

from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from langgraph.graph import END, START, StateGraph
from pydantic import BaseModel, Field

import dummy_data as db
import usage
import vectorstore
from schemas import AssetType, Chunk, Citation, GenerateRequest, Length, Platform, Tone

logger = logging.getLogger(__name__)

LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini" if vectorstore.PROVIDER == "openrouter" else "gpt-4o-mini")
LLM_TEMPERATURE = 0.7  # some creativity for marketing copy; facts are constrained by the prompt

# What to write, per asset type; {size} is filled from SIZES by the chosen length, {platform} from
# PLATFORM_POST / PLATFORM_REPLY (inserted into the system prompt).
ASSET_INSTRUCTIONS: dict[AssetType, str] = {
    "blurb": "a back-cover blurb / product description of {size} words: a hook in the first sentence, "
             "what the book is about and why it matters, and a closing line that makes people want to read it.",
    "social_post": "one social media post {platform}.",
    "social_reply": "a reply to the social media post given below, {platform}. Respond to the post's actual point "
                    "first, then add the book's perspective; sound like a person taking part in the conversation, "
                    "not like an advertisement. Mention the book (title and author) naturally at most once. "
                    "Use hashtags only if they are usual for this platform's replies.",
    "video_script": "a script for a short vertical video {platform}, 30-60 seconds long, about the book. "
                    "Structure it as: HOOK (first 3 seconds, spoken), then 3-5 numbered SCENES, each with "
                    "\"Visual:\" (what is shown), \"Voice-over:\" (what is said) and \"On-screen text:\" (a few words), "
                    "then a CTA (call to action), then a caption with fitting hashtags. Use plain labels (HOOK, "
                    "SCENE 1, ..., CTA, CAPTION) without emojis; keep the on-screen text calm, without exclamation marks.",
    "youtube_video": "the YouTube page for a video about the book, in exactly these four sections with these "
                     "headings: \"Title options:\" with 3 numbered titles (each under 70 characters, curiosity without "
                     "clickbait); \"Description:\" of {size} words whose first two lines work as the preview; "
                     "\"Chapters:\" with 3-6 timestamps (e.g. \"0:00 Intro\") for a 6-10 minute video; "
                     "\"Tags:\" with 10-15 comma-separated tags.",
    "newsletter": "a newsletter section of {size} words: a subject line on the first line "
                  "(\"Subject: ...\"), then an engaging introduction to the book and a call to action.",
    "ad_copy": "three short ad variants. Each has a headline (max 8 words) and a body of {size} words.",
    "lead_magnet": "a lead magnet outline: a compelling title, a one-sentence promise, "
                   "and {size} bullet points of what the reader will get.",
    "persona": "an audience persona for this book of {size} words: name and short description, demographics, "
               "goals, pain points, where to reach them, and why this book appeals to them.",
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

# Social posts and replies: the platform decides length and style.
PLATFORM_POST: dict[Platform, str] = {
    "x": "for X (Twitter): at most 280 characters in total, a strong hook, 1-2 fitting hashtags",
    "linkedin": "for LinkedIn: 80-200 words, a strong first line, short paragraphs, professional and thoughtful, "
                "3-5 hashtags at the end",
    "instagram": "for Instagram: an engaging caption with line breaks and a few emojis, ending with 5-10 hashtags; "
                 "after the caption add one line starting with \"Image idea:\" that describes a fitting picture",
    "facebook": "for Facebook: conversational, 40-120 words, ending with a question that invites comments, "
                "0-2 hashtags",
    "tiktok": "as a TikTok caption: at most 150 characters, casual, a hook first, 3-5 hashtags",
    "youtube": "as a YouTube community post: 30-100 words, personal, ending with a question or a poll idea",
}
PLATFORM_REPLY: dict[Platform, str] = {
    "x": "on X (Twitter), at most 280 characters in total",
    "linkedin": "as a LinkedIn comment of 40-120 words, professional and constructive",
    "instagram": "as an Instagram comment of 1-3 short sentences, warm; an emoji is fine",
    "facebook": "as a Facebook comment of 30-100 words, conversational",
    "tiktok": "as a TikTok comment of at most 150 characters, casual",
    "youtube": "as a YouTube comment of 20-80 words, friendly and on topic",
}
# Short video scripts: where the video is published.
PLATFORM_VIDEO: dict[Platform, str] = {
    "x": "for X (Twitter) video",
    "linkedin": "for LinkedIn video (professional, subtitled because most people watch muted)",
    "instagram": "for Instagram Reels",
    "facebook": "for Facebook Reels",
    "tiktok": "for TikTok (fast cuts, trend-aware, casual)",
    "youtube": "for YouTube Shorts",
}
TONES: dict[Tone, str] = {
    "neutral": "",
    "inspiring": "inspiring and hopeful",
    "friendly": "warm and friendly",
    "professional": "professional and credible",
    "punchy": "punchy, bold and energetic",
    "literary": "elegant and literary",
}

# Style guidance per "humanize" level (lower bound → text added to the system prompt).
HUMAN_LEVELS: list[tuple[int, str]] = [
    (0, "Style: polished, persuasive marketing copy is fine."),
    (25, "Style: clear and engaging; avoid the most worn-out marketing clichés."),
    (50, "Style: write like a thoughtful human copywriter, not like an AI: vary sentence length, use contractions "
         "and concrete details, at most one exclamation mark, no clichés, no rhetorical-question opener, no "
         "'not just X, but Y', no lists of three adjectives."),
    (75, "Style: sound like a real person writing it themselves, e.g. a reader who loved the book: plain everyday "
         "words, first person where it fits, a genuine opinion, short and specific, slightly informal is fine. "
         "No marketing clichés, no hype words, no exclamation-mark chains, emojis and hashtags only as many as "
         "the platform strictly needs, no em dashes."),
]

# Phrases and patterns that make text sound AI-generated ("AI slop"); avoided in the prompt from
# humanize 50 on, detected after generation, and rewritten from humanize 60 on.
AI_TELLS: list[str] = [
    "imagine a world", "in today's fast-paced world", "in a world where", "dive into", "delve into", "unlock",
    "unleash", "embark on", "journey", "game-changer", "game changer", "revolutionary", "transformative",
    "groundbreaking", "join the movement", "are you ready", "ready to explore", "look no further",
    "harmonious", "vibrant", "tapestry", "elevate", "embrace", "testament to", "a must-read", "timeless",
    "discover how", "the future is", "let's dive", "buckle up", "not just", "seamlessly", "synergy",
]
REWRITE_FROM = 60  # humanize level from which found AI clichés are rewritten (one extra model call)

GROUNDED_SYSTEM = (
    "You are an expert book marketer. Write {instructions}\n\n"
    "Use ONLY facts from the numbered source excerpts. Cite every excerpt you use with its number in "
    "square brackets, e.g. [2], right after the sentence that uses it; always add these markers, also in "
    "short texts: they are removed before publishing and do not count toward any length limit. Quote memorable lines verbatim "
    "in quotation marks when they help. Never invent facts, names, numbers, quotes or titles; refer to "
    "a book only by the source name in the excerpt headers (or the brief). If the excerpts do not cover "
    "something, leave it out. The book background (a summary of the whole book, if given) helps you "
    "understand what the book is about overall; specific facts and quotes must come from the excerpts "
    "and be cited. Reply with the asset text only. Write plain text that can be pasted anywhere: "
    "no Markdown (no ** or #).\n\n{style}"
)
ZERO_SHOT_SYSTEM = (
    "You are an expert book marketer. Write {instructions}\n\n"
    "Base it on the request only. Reply with the asset text only. Write plain text that can be pasted "
    "anywhere: no Markdown (no ** or #).\n\n{style}"
)

GROUNDED_PROMPT = ChatPromptTemplate.from_messages([
    ("system", GROUNDED_SYSTEM),
    ("human", "{request}\n\nBook background:\n{background}\n\nSource excerpts:\n\n{context}"),
])
ZERO_SHOT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", ZERO_SHOT_SYSTEM),
    ("human", "{request}"),
])
PLAN_QUERY_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You help find passages in a book that are useful for replying to a social media post. Read the post and "
     "the user's angle, then write ONE search query of at most 25 words that names the topics, claims or "
     "questions the reply should address. Reply with the query only."),
    ("human", "{request}"),
])


REWRITE_PROMPT = ChatPromptTemplate.from_messages([
    ("system",
     "You edit marketing text so that it sounds like a real person wrote it, not an AI. Rephrase or remove these "
     "AI-typical phrases and patterns: {tells}. Keep the meaning, the facts, any quotes, the format and roughly "
     "the length. Keep every citation marker like [2] exactly as it is, attached to the statement it supports. "
     "Reply with the edited text only.\n\n{style}"),
    ("human", "{text}"),
])


class GeneratedText(BaseModel):
    """Structured output of a grounded generation call: the text plus the excerpts it is based on.

    Short formats (posts, replies) often come back without inline [n] markers; the separate
    used_sources list makes sure their sources are still known.
    """

    text: str = Field(description="The asset text, with [n] citation markers after statements that use an excerpt.")
    used_sources: list[int] = Field(description="Numbers of all source excerpts the text draws on (facts, ideas or quotes).")


class GenerationError(Exception):
    """Generation failed; status_code is the HTTP status the API should return (502 or 503)."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


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
    rewritten: bool  # True after the rewrite step ran (it runs at most once)
    text: str  # the generated asset text, citation markers renumbered
    citations: list[Citation]  # the cited chunks, in marker order
    tokens: int  # LLM tokens used (prompt + completion), from the model's usage metadata


# ---------- Public API ----------
def is_configured() -> bool:
    """True if an API key for the chat model is set (the same key as for embeddings)."""
    return vectorstore.is_configured()


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
        GenerationError: 503 if no API key is configured, 502 if retrieval or the model call fails.
    """
    if not is_configured():
        raise GenerationError(503, "No API key set. Add OPENROUTER_API_KEY (or OPENAI_API_KEY) and restart the server.")
    mode = "grounded" if req.grounded else "zero-shot"
    try:
        state = _graph().invoke(
            {"project_id": project_id, "req": req},
            config={"run_name": f"generate_{req.asset_type}", "tags": [mode, req.asset_type],
                    "metadata": {"project_id": project_id, "llm_model": LLM_MODEL, "operation": f"generate_{req.asset_type}"}},
        )
    except GenerationError:
        raise
    except vectorstore.VectorStoreError as e:
        raise GenerationError(502, str(e)) from e
    except Exception as e:
        logger.exception("Generation failed")
        raise GenerationError(502, f"The language model call failed: {e}") from e
    return state


def retrieve_chunks(project_id: str, query: str, k: int, source_ids: list[str] | None = None,
                    operation: str = "search") -> list[tuple[Chunk, float]]:
    """Find the project's chunks most similar to a query (vector search in Chroma).

    Looks the hits up in the in-memory chunks; hits whose chunk no longer exists (e.g. deleted
    source) are skipped.

    Args:
        project_id: Project to search in.
        query: Natural-language query.
        k: Maximum number of results.
        source_ids: Optional filter: only search these sources.
        operation: What the search is for, for the usage log (e.g. "ask", "verify").

    Returns:
        (chunk, similarity) pairs, best first.

    Raises:
        vectorstore.VectorStoreError: If no API key is configured or the search fails.
    """
    hits = vectorstore.search(project_id, query, k, source_ids, operation=operation)
    return [(db.chunks[chunk_id], round(score, 3)) for chunk_id, score in hits if chunk_id in db.chunks]


def health() -> tuple[bool, str]:
    """Status of the language model for GET /health: (ok, detail with model, provider and LangSmith tracing)."""
    tracing = "LangSmith tracing on" if _tracing_enabled() else "LangSmith tracing off"
    if not is_configured():
        return False, f"{LLM_MODEL} · no API key · {tracing}"
    return True, f"{LLM_MODEL} via {vectorstore.PROVIDER} · {tracing}"


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
    else:
        text = template.format(size=SIZES[req.asset_type][LENGTH_INDEX[req.length]])
    if TONES[req.tone]:
        text += f" Tone: {TONES[req.tone]}."
    if req.audience.strip():
        text += f" Target audience: {req.audience.strip()}."
    return text


def style_guidance(humanize: int) -> str:
    """Style guidance for a "humanize" level (0-100), plus the list of AI clichés to avoid from level 50 on."""
    guidance = next(text for bound, text in reversed(HUMAN_LEVELS) if humanize >= bound)
    if humanize >= 50:
        guidance += " Never use these AI-typical phrases: " + ", ".join(f'"{t}"' for t in AI_TELLS) + "."
    return guidance


def find_ai_tells(text: str, emojis_expected: bool = False) -> list[str]:
    """AI-typical phrases and patterns in a text: listed clichés, many exclamation marks, emojis or em dashes.

    Args:
        text: The text to check.
        emojis_expected: Skip the emoji count for formats where emojis are normal (see emojis_are_normal).
    """
    lower = text.lower()
    found = [t for t in AI_TELLS if re.search(rf"\b{re.escape(t)}\b", lower)]
    if text.count("!") > 2:
        found.append("many exclamation marks")
    if not emojis_expected and len(re.findall(r"[\U0001F300-\U0001FAFF\u2600-\u27BF]", text)) > 3:
        found.append("many emojis")
    if text.count("—") > 2:
        found.append("many em dashes")
    return found


def emojis_are_normal(req: GenerateRequest) -> bool:
    """True for formats where several emojis are normal: Instagram and TikTok posts/replies, and short video scripts."""
    if req.asset_type == "video_script":
        return True
    return req.asset_type in ("social_post", "social_reply") and req.platform in ("instagram", "tiktok")


def temperature_for(humanize: int) -> float:
    """Model temperature for a humanize level: 0.5 (polished) to 1.0 (very human), in steps of 0.1."""
    return round(0.5 + 0.5 * humanize / 100, 1)


def build_request(req: GenerateRequest) -> str:
    """The user's request for the human message: the brief, or for replies the post plus the optional angle."""
    if req.asset_type == "social_reply":
        angle = req.brief.strip() or "(none: reply as you see fit)"
        return f'Post to reply to:\n"""\n{req.reply_to.strip()}\n"""\n\nMy angle: {angle}'
    return f"Brief: {req.brief.strip()}"


# ---------- Graph ----------
@cache
def chat_model(temperature: float = LLM_TEMPERATURE) -> ChatOpenAI:
    """The chat model, via OpenRouter or OpenAI (same key and endpoint as the embeddings).

    One cached instance per temperature. usage.handler logs every call with its tokens and costs (usage.py).

    Args:
        temperature: Sampling temperature; higher = more varied wording.
    """
    return ChatOpenAI(model=LLM_MODEL, api_key=vectorstore.API_KEY, base_url=vectorstore.BASE_URL,
                      temperature=temperature, callbacks=[usage.handler])


@cache
def _graph():
    """Build and compile the LangGraph:
    START → (plan_query →) (retrieve →) generate → check_style → (rewrite →) finalize → END."""
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
    builder.add_conditional_edges("check_style", _needs_rewrite, {"rewrite": "rewrite", "finalize": "finalize"})
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
    reply: AIMessage = (PLAN_QUERY_PROMPT | chat_model()).invoke({"request": build_request(state["req"])})
    # The model sometimes labels its answer ("Search query: ..."); keep only the query itself.
    query = re.sub(r"^\s*(search\s+)?query\s*:\s*", "", str(reply.content), flags=re.IGNORECASE).strip().strip('"').strip()
    query = query or state["req"].reply_to[:500]
    return {"query": query, "tokens": tokens_used(reply)}


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
    values = {"instructions": build_instructions(req), "request": build_request(req), "style": style_guidance(req.humanize)}
    model = chat_model(temperature_for(req.humanize))
    tokens_before = state.get("tokens", 0)
    if not req.grounded:
        reply: AIMessage = (ZERO_SHOT_PROMPT | model).invoke(values)
        return {"draft": str(reply.content).strip(), "used": [], "tokens": tokens_before + tokens_used(reply)}

    context = state["context"]
    result = (GROUNDED_PROMPT | model.with_structured_output(GeneratedText, include_raw=True)).invoke(
        {**values, "background": format_background(context), "context": format_context(context)})
    parsed: GeneratedText | None = result.get("parsed")
    text = parsed.text if parsed else str(result["raw"].content)  # fall back to the raw reply if parsing failed
    return {"draft": text.strip(), "used": parsed.used_sources if parsed else [],
            "tokens": tokens_before + tokens_used(result["raw"])}


def _check_style(state: GenerationState) -> GenerationState:
    """Style check node: find AI-typical clichés in the draft (no model call)."""
    return {"ai_tells": find_ai_tells(state["draft"], emojis_are_normal(state["req"]))}


def _needs_rewrite(state: GenerationState) -> str:
    """Edge after check_style: rewrite once if clichés were found and humanize is at least REWRITE_FROM."""
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
    if state["req"].grounded:
        result = keep_cited(draft, state["context"], also_cited=state.get("used", []))
    else:
        result = {"text": draft, "citations": []}
    return {**result, "ai_tells": find_ai_tells(result["text"], emojis_are_normal(state["req"]))}


def format_background(context: list[tuple[Chunk, float]]) -> str:
    """Summaries of the books the excerpts come from, e.g. "Garden Cities — Ebenezer Howard: <summary>".

    Returns "(none)" if no summary has been created for these books yet.
    """
    parts = []
    for source_id in dict.fromkeys(chunk.source_id for chunk, _ in context):  # unique, in order
        if summary := db.summaries.get(source_id):
            parts.append(f"{source_name(source_id)}: {summary.summary}")
    return "\n\n".join(parts) or "(none)"


def tokens_used(reply: AIMessage) -> int:
    """Total tokens (prompt + completion) of a model reply, 0 if the provider reported no usage."""
    return (reply.usage_metadata or {}).get("total_tokens", 0)


def format_context(context: list[tuple[Chunk, float]]) -> str:
    """Numbered excerpts for the prompt, each with its source, chapter and page, e.g.
    "[1] (Garden Cities of To Morrow — Ebenezer Howard · CHAPTER II. THE REVENUE… · p. 13)\\n<text>".
    """
    parts = []
    for n, (chunk, _) in enumerate(context, start=1):
        header = (source_name(chunk.source_id), chunk.location.chapter, chunk.location.page and f"p. {chunk.location.page}")
        parts.append(f"[{n}] ({' · '.join(x for x in header if x)})\n{chunk.text}")
    return "\n\n".join(parts)


def source_name(source_id: str) -> str | None:
    """Readable name of a source from its file name: "Garden-Cities_Ebenezer-Howard.pdf" → "Garden Cities — Ebenezer Howard"."""
    source = db.sources.get(source_id)
    if source is None:
        return None
    return re.sub(r"\s+", " ", source.filename.rsplit(".", 1)[0].replace("_", " — ").replace("-", " ")).strip()


def keep_cited(text: str, context: list[tuple[Chunk, float]], also_cited: list[int] | None = None) -> GenerationState:
    """Turn the excerpts cited as [n] into Citations and renumber the markers 1, 2, ... in the order
    they first appear in the text.

    Markers that point to no excerpt are removed. Excerpts listed in also_cited (the model's
    used_sources) but without a marker in the text are appended as further citations. If nothing is
    cited at all, no citations are kept.

    Args:
        text: The generated text with the model's [n] markers.
        context: The numbered excerpts that were in the prompt.
        also_cited: Optional further excerpt numbers the text is based on.
    """
    cited: list[int] = []  # original excerpt numbers, in order of first appearance
    for n in [*map(int, re.findall(r"\[(\d+)\]", text)), *(also_cited or [])]:
        if 1 <= n <= len(context) and n not in cited:
            cited.append(n)
    new_number = {old: new for new, old in enumerate(cited, start=1)}
    text = re.sub(r"\[(\d+)\]", lambda m: f"[{new_number[int(m.group(1))]}]" if int(m.group(1)) in new_number else "", text)
    citations = [
        Citation(chunk_id=chunk.id, source_id=chunk.source_id, location=chunk.location, quote=chunk.text[:240], score=score)
        for chunk, score in (context[n - 1] for n in cited)
    ]
    return {"text": re.sub(r"[ \t]+([.,;:!?])", r"\1", text), "citations": citations}


def _tracing_enabled() -> bool:
    """True if LangSmith tracing is switched on and has an API key (also accepts the older LANGCHAIN_* names)."""
    on = (os.getenv("LANGSMITH_TRACING") or os.getenv("LANGCHAIN_TRACING_V2") or "").lower() == "true"
    return on and bool(os.getenv("LANGSMITH_API_KEY") or os.getenv("LANGCHAIN_API_KEY"))
