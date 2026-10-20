"""Asset generation with LangGraph + LangChain: the R-A-G of the RAG pipeline.

    START ─(grounded?)─► retrieve ─► generate ─► END        grounded (RAG): brief → top-k chunks → LLM
          └────────────────────────► generate ─► END        zero-shot: brief → LLM

    retrieve  (Retrieval)     the brief is the query; vectorstore.search finds the k most similar chunks
    generate  (Augmentation)  ChatPromptTemplate puts instructions, brief and numbered excerpts together
              (Generation)    ChatOpenAI (via OpenRouter) writes the asset and cites excerpts as [n]

The book summaries (summary.py) of the excerpts' sources are added as background. Only the excerpts
the model actually cites become the asset's citations, renumbered [1], [2], ...
in order. Runs are traced in LangSmith when LANGSMITH_TRACING=true and LANGSMITH_API_KEY are set
(LangChain/LangGraph pick these up automatically; LANGSMITH_PROJECT names the project).

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

import dummy_data as db
import usage
import vectorstore
from schemas import AssetType, Chunk, Citation

logger = logging.getLogger(__name__)

LLM_MODEL = os.getenv("LLM_MODEL", "openai/gpt-4o-mini" if vectorstore.PROVIDER == "openrouter" else "gpt-4o-mini")
LLM_TEMPERATURE = 0.7  # some creativity for marketing copy; facts are constrained by the prompt

# What to write, per asset type (inserted into the system prompt).
ASSET_INSTRUCTIONS: dict[AssetType, str] = {
    "blurb": "a back-cover blurb / product description of 120-180 words: a hook in the first sentence, "
             "what the book is about and why it matters, and a closing line that makes people want to read it.",
    "social_post": "one social media post of at most 280 characters, with a strong hook and 1-3 fitting hashtags.",
    "newsletter": "a newsletter section of about 250 words: a subject line on the first line "
                  "(\"Subject: ...\"), then an engaging introduction to the book and a call to action.",
    "ad_copy": "three short ad variants. Each has a headline (max 8 words) and a body of one or two sentences.",
    "lead_magnet": "a lead magnet outline: a compelling title, a one-sentence promise, "
                   "and 5 bullet points of what the reader will get.",
    "persona": "an audience persona for this book: name and short description, demographics, "
               "goals, pain points, where to reach them, and why this book appeals to them.",
}

GROUNDED_SYSTEM = (
    "You are an expert book marketer. Write {instructions}\n\n"
    "Use ONLY facts from the numbered source excerpts. Cite every excerpt you use with its number in "
    "square brackets, e.g. [2], right after the sentence that uses it. Quote memorable lines verbatim "
    "in quotation marks when they help. Never invent facts, names, numbers, quotes or titles; refer to "
    "a book only by the source name in the excerpt headers (or the brief). If the excerpts do not cover "
    "something, leave it out. The book background (a summary of the whole book, if given) helps you "
    "understand what the book is about overall; specific facts and quotes must come from the excerpts "
    "and be cited. Reply with the asset text only."
)
ZERO_SHOT_SYSTEM = (
    "You are an expert book marketer. Write {instructions}\n\n"
    "Base it on the brief only. Reply with the asset text only."
)

GROUNDED_PROMPT = ChatPromptTemplate.from_messages([
    ("system", GROUNDED_SYSTEM),
    ("human", "Brief: {brief}\n\nBook background:\n{background}\n\nSource excerpts:\n\n{context}"),
])
ZERO_SHOT_PROMPT = ChatPromptTemplate.from_messages([
    ("system", ZERO_SHOT_SYSTEM),
    ("human", "Brief: {brief}"),
])


class GenerationError(Exception):
    """Generation failed; status_code is the HTTP status the API should return (502 or 503)."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


class GenerationState(TypedDict, total=False):
    """State passed through the LangGraph graph.

    Inputs: project_id, asset_type, brief, grounded, k. Set by retrieve: context.
    Set by generate: text, citations, tokens.
    """

    project_id: str
    asset_type: AssetType
    brief: str
    grounded: bool
    k: int
    context: list[tuple[Chunk, float]]  # retrieved chunks with similarity, best first
    text: str  # the generated asset text, citation markers renumbered
    citations: list[Citation]  # the cited chunks, in marker order
    tokens: int  # LLM tokens used (prompt + completion), from the model's usage metadata


# ---------- Public API ----------
def is_configured() -> bool:
    """True if an API key for the chat model is set (the same key as for embeddings)."""
    return vectorstore.is_configured()


def generate_asset(project_id: str, asset_type: AssetType, brief: str, grounded: bool, k: int) -> tuple[str, list[Citation], int]:
    """Run the generation graph for one asset.

    Args:
        project_id: Project whose sources ground the asset.
        asset_type: Kind of asset to write.
        brief: The user's instructions; also the retrieval query when grounded.
        grounded: True = RAG over the project's sources; False = zero-shot.
        k: Number of chunks to retrieve as context.

    Returns:
        The asset text, its citations (empty when zero-shot) and the LLM tokens used.

    Raises:
        GenerationError: 503 if no API key is configured, 502 if retrieval or the model call fails.
    """
    if not is_configured():
        raise GenerationError(503, "No API key set. Add OPENROUTER_API_KEY (or OPENAI_API_KEY) and restart the server.")
    mode = "grounded" if grounded else "zero-shot"
    try:
        state = _graph().invoke(
            {"project_id": project_id, "asset_type": asset_type, "brief": brief, "grounded": grounded, "k": k},
            config={"run_name": f"generate_{asset_type}", "tags": [mode, asset_type],
                    "metadata": {"project_id": project_id, "llm_model": LLM_MODEL, "operation": f"generate_{asset_type}"}},
        )
    except GenerationError:
        raise
    except vectorstore.VectorStoreError as e:
        raise GenerationError(502, str(e)) from e
    except Exception as e:
        logger.exception("Generation failed")
        raise GenerationError(502, f"The language model call failed: {e}") from e
    return state["text"], state.get("citations", []), state.get("tokens", 0)


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


# ---------- Graph ----------
@cache
def chat_model() -> ChatOpenAI:
    """The chat model, via OpenRouter or OpenAI (same key and endpoint as the embeddings).

    usage.handler logs every call with its tokens and costs (usage.py).
    """
    return ChatOpenAI(model=LLM_MODEL, api_key=vectorstore.API_KEY, base_url=vectorstore.BASE_URL,
                      temperature=LLM_TEMPERATURE, callbacks=[usage.handler])


@cache
def _graph():
    """Build and compile the LangGraph: START → (retrieve →) generate → END."""
    builder = StateGraph(GenerationState)
    builder.add_node("retrieve", _retrieve)
    builder.add_node("generate", _generate)
    builder.add_conditional_edges(START, _route, {"retrieve": "retrieve", "generate": "generate"})
    builder.add_edge("retrieve", "generate")
    builder.add_edge("generate", END)
    return builder.compile()


def _route(state: GenerationState) -> str:
    """Entry edge: grounded requests retrieve context first, zero-shot ones go straight to generation."""
    return "retrieve" if state["grounded"] else "generate"


def _retrieve(state: GenerationState) -> GenerationState:
    """Retrieval node: the brief is the query; returns the k most similar chunks as context.

    Raises:
        GenerationError: If the project has no searchable chunks (nothing to ground on).
    """
    context = retrieve_chunks(state["project_id"], state["brief"], state["k"], operation=f"generate_{state['asset_type']}")
    if not context:
        raise GenerationError(502, "No searchable sources in this project yet. Upload and process a book first.")
    return {"context": context}


def _generate(state: GenerationState) -> GenerationState:
    """Augmentation + generation node: fill the prompt, call the model, keep the cited excerpts.

    Grounded: the excerpts are numbered [1]..[k] in the prompt; afterwards only the excerpts the
    model cited become citations, and the markers in the text are renumbered to match them. The
    summaries of the books the excerpts come from (if created) are added as background.
    The token usage of the call is returned as "tokens".
    """
    instructions = ASSET_INSTRUCTIONS[state["asset_type"]]
    if not state["grounded"]:
        reply: AIMessage = (ZERO_SHOT_PROMPT | chat_model()).invoke({"instructions": instructions, "brief": state["brief"]})
        return {"text": str(reply.content).strip(), "citations": [], "tokens": tokens_used(reply)}

    context = state["context"]
    reply = (GROUNDED_PROMPT | chat_model()).invoke({
        "instructions": instructions, "brief": state["brief"],
        "background": format_background(context), "context": format_context(context),
    })
    return {**keep_cited(str(reply.content).strip(), context), "tokens": tokens_used(reply)}


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


def keep_cited(text: str, context: list[tuple[Chunk, float]]) -> GenerationState:
    """Turn the excerpts cited as [n] into Citations and renumber the markers 1, 2, ... in the order
    they first appear in the text.

    Markers that point to no excerpt are removed. If the model cited nothing, no citations are kept.
    """
    cited: list[int] = []  # original excerpt numbers, in order of first appearance
    for n in map(int, re.findall(r"\[(\d+)\]", text)):
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
