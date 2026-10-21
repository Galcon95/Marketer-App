"""Knowledge Hub (RAG): book summaries, ask your book, semantic search and claim verification."""

import re

from fastapi import APIRouter, HTTPException

from app.api.deps import get_project_or_404, get_source_or_404, retrieve
from app.core import state as db
from app.core.llm import GenerationError
from app.core.schemas import (
    AskRequest, AskResponse, BookSummary, SearchHit, SearchRequest, SearchResponse, VerifyItem, VerifyRequest,
    VerifyResponse,
)
from app.rag import qa, summary

router = APIRouter()


# Minimum similarity for a claim to count as verified by a source chunk (cosine similarity, 0-1).
VERIFY_MIN_SCORE = 0.5


@router.get("/sources/{source_id}/summary", response_model=BookSummary)
def get_summary(source_id: str):
    """Return the saved summary of a book.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.

    Raises:
        HTTPException: 404 if the source is unknown or has no summary yet.
    """
    get_source_or_404(source_id)
    found = db.summaries.get(source_id)
    if found is None:
        raise HTTPException(404, "No summary yet")
    return found


@router.post("/sources/{source_id}/summary", response_model=BookSummary, status_code=201)
def create_summary(source_id: str):
    """Create (or recreate) the summary of a processed book: chapter summaries + book overview.

    Runs the LangGraph map-reduce in summary.py over all of the book's chunks, which takes some
    seconds (one model call per chapter, in parallel, plus one to combine). The result is saved and
    then used as background in grounded generation.

    Args:
        source_id: Id of the source (path parameter). 404 if unknown.

    Returns:
        The new summary.

    Raises:
        HTTPException: 409 if the book is not processed ("ready"); 503 if no API key is configured;
            502 if a model call fails.
    """
    source = get_source_or_404(source_id)
    if source.status != "ready":
        raise HTTPException(409, f"'{source.filename}' must be processed (status ready) before it can be summarized")
    try:
        return summary.summarize_source(source)
    except GenerationError as e:
        raise HTTPException(e.status_code, str(e)) from e
    except OSError as e:
        raise HTTPException(500, "The summary was created but could not be saved") from e


@router.post("/projects/{project_id}/ask", response_model=AskResponse)
def ask(project_id: str, body: AskRequest):
    """Answer a question from the project's books, NotebookLM-style.

    Runs the LangGraph in qa.py: the k passages most similar to the question are retrieved, and the
    LLM writes an answer from those passages only (plus the book summary as background), citing
    them as [n]. Says so when the passages do not answer the question.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: The question, number of passages k and optional source filter.

    Returns:
        The answer with its cited passages, all retrieved passages and token usage.

    Raises:
        HTTPException: 409 if there is nothing to search; 503 if no API key is configured;
            502 if retrieval or the model call fails.
    """
    get_project_or_404(project_id)
    try:
        return qa.answer_question(project_id, body.question, body.k, body.source_ids)
    except GenerationError as e:
        raise HTTPException(e.status_code, str(e)) from e


@router.post("/projects/{project_id}/search", response_model=SearchResponse)
def search(project_id: str, body: SearchRequest):
    """Find the passages of a project's sources that best match a query (semantic vector search).

    The query is embedded and compared with the chunk vectors in Chroma; scores are cosine
    similarities (about 0-1, higher is better).

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: Query text, number of hits k and optional source filter.

    Returns:
        The query and up to k hits, best first.

    Raises:
        HTTPException: 503 if no embedding API key is configured, 502 if the search fails.
    """
    get_project_or_404(project_id)
    hits = [SearchHit(chunk=c, score=score) for c, score in retrieve(project_id, body.query, body.k, body.source_ids)]
    return SearchResponse(query=body.query, hits=hits)


# ---------- Verification ----------
@router.post("/projects/{project_id}/verify", response_model=VerifyResponse)
def verify(project_id: str, body: VerifyRequest):
    """Check each claim (sentence) of a text against the project's sources.

    Splits the text into sentences and searches the best-matching chunk for each one. A sentence
    counts as verified when that chunk's similarity reaches VERIFY_MIN_SCORE. This finds claims that
    are backed by a similar passage; it does not judge whether the claim is logically entailed.

    Args:
        project_id: Id of the project (path parameter). 404 if unknown.
        body: The text to verify.

    Returns:
        One VerifyItem per sentence, in text order.

    Raises:
        HTTPException: 503 if no embedding API key is configured, 502 if the search fails.
    """
    get_project_or_404(project_id)
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", body.text.replace("\n", " ")) if s.strip()]
    items = []
    for sentence in sentences:
        best = retrieve(project_id, sentence, k=1, operation="verify")
        if best and best[0][1] >= VERIFY_MIN_SCORE:
            items.append(VerifyItem(claim=sentence, status="verified", chunk_id=best[0][0].id, score=best[0][1]))
        else:
            items.append(VerifyItem(claim=sentence, status="not_found"))
    return VerifyResponse(items=items)
