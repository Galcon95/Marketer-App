"""Retrieval helpers shared by generation and Q&A: vector search, prompt context and citations.

    retrieve_chunks     the k chunks most similar to a query (Chroma, see vectorstore.py)
    format_context      numbered excerpts <passage n="1">..<passage n="k"> with source, chapter and page for the prompt
    format_background   the summaries of the excerpts' books (summary.py) as background
    keep_cited          the [n] markers the model wrote → Citations, renumbered in text order
"""

import re

from app.core import state as db
from app.core.guard import quote_untrusted
from app.core.schemas import Chunk, Citation
from app.rag import vectorstore


def retrieve_chunks(project_id: str, query: str, k: int, source_ids: list[str] | None = None,
                    operation: str = "search", where: dict | None = None) -> list[tuple[Chunk, float]]:
    """Find the project's chunks most similar to a query (vector search in Chroma).

    Looks the hits up in the in-memory chunks; hits whose chunk no longer exists (e.g. deleted
    source) are skipped.

    Args:
        project_id: Project to search in.
        query: Natural-language query.
        k: Maximum number of results.
        source_ids: Optional filter: only search these sources.
        operation: What the search is for, for the usage log (e.g. "ask", "verify").
        where: Optional further metadata conditions (chapter, pages), see vectorstore.search.

    Returns:
        (chunk, similarity) pairs, best first.

    Raises:
        vectorstore.VectorStoreError: If no API key is configured or the search fails.
    """
    hits = vectorstore.search(project_id, query, k, source_ids, operation=operation, where=where)
    return [(db.chunks[chunk_id], round(score, 3)) for chunk_id, score in hits if chunk_id in db.chunks]


def format_context(context: list[tuple[Chunk, float]]) -> str:
    """Numbered excerpts for the prompt, each as data in a <passage> block with its source, chapter and page, e.g.
    '<passage n="1" source="Garden Cities of To Morrow — Ebenezer Howard · CHAPTER II. … · p. 13">\\n<text>\\n</passage>'.

    The block keeps book text apart from instructions (guard.quote_untrusted; the prompts add guard.UNTRUSTED_RULE):
    a passage that contains "ignore your instructions" is read as a quote, not obeyed. Passage n is cited as [n].
    """
    parts = []
    for n, (chunk, _) in enumerate(context, start=1):
        header = (source_name(chunk.source_id), chunk.location.chapter, chunk.location.page and f"p. {chunk.location.page}")
        parts.append(quote_untrusted(chunk.text, "passage", n=n, source=" · ".join(x for x in header if x)))
    return "\n\n".join(parts)


def format_background(context: list[tuple[Chunk, float]]) -> str:
    """Summaries of the books the excerpts come from, e.g. "Garden Cities — Ebenezer Howard: <summary>".

    Returns "(none)" if no summary has been created for these books yet.
    """
    parts = []
    for source_id in dict.fromkeys(chunk.source_id for chunk, _ in context):  # unique, in order
        if summary := db.summaries.get(source_id):
            parts.append(f"{source_name(source_id)}: {summary.summary}")
    return "\n\n".join(parts) or "(none)"


def source_name(source_id: str) -> str | None:
    """Readable name of a source from its file name: "Garden-Cities_Ebenezer-Howard.pdf" → "Garden Cities — Ebenezer Howard".

    Without an author in the file name, the author from the PDF's metadata is added, if known
    ("Successful Stock Speculation.pdf" → "Successful Stock Speculation — J. J. Butler").
    """
    source = db.sources.get(source_id)
    if source is None:
        return None
    name = re.sub(r"\s+", " ", source.filename.rsplit(".", 1)[0].replace("_", " — ").replace("-", " ")).strip()
    return name if " — " in name or not source.author else f"{name} — {source.author}"


def keep_cited(text: str, context: list[tuple[Chunk, float]], also_cited: list[int] | None = None) -> dict:
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
