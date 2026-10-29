"""Shared helpers of the API routers: 404 lookups, vector search with HTTP errors, input checks (guardrails)
and the rate limit of the endpoints that call the language model."""

import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import HTTPException, Request

from app.core import guard
from app.core import state as db
from app.core.llm import model_failure
from app.core.schemas import Chunk, Project, Source
from app.rag import vectorstore
from app.rag.retrieval import retrieve_chunks

logger = logging.getLogger(__name__)

# Rate limit of the endpoints that call the language model (per client address, sliding window).
LLM_RATE_LIMIT = 20  # requests ...
LLM_RATE_WINDOW = 60  # ... per this many seconds
_llm_calls: dict[str, deque[float]] = defaultdict(deque)  # client address → times of its recent requests
_llm_calls_lock = threading.Lock()  # sync endpoints run in a thread pool


def llm_rate_limit(request: Request) -> None:
    """FastAPI dependency for endpoints that call the language model: at most LLM_RATE_LIMIT requests per
    LLM_RATE_WINDOW seconds per client address; protects against runaway costs (a script or a stuck button).

    Raises:
        HTTPException: 429 with a Retry-After header when the limit is reached.
    """
    client = request.client.host if request.client else "unknown"
    now = time.monotonic()
    with _llm_calls_lock:
        calls = _llm_calls[client]
        while calls and now - calls[0] > LLM_RATE_WINDOW:
            calls.popleft()
        if len(calls) >= LLM_RATE_LIMIT:
            wait = int(LLM_RATE_WINDOW - (now - calls[0])) + 1
            raise HTTPException(429, f"Too many requests: at most {LLM_RATE_LIMIT} model requests per minute. "
                                     f"Try again in {wait} seconds.", headers={"Retry-After": str(wait)})
        calls.append(now)


def checked_text(text: str, kind: guard.InputKind, field: str, *, check_injection: bool = True) -> str:
    """Clean and check one text field of a request (guard.py) before it is used; returns the cleaned text.

    Args:
        text: The text as sent.
        kind: Its kind, which sets the length limit (guard.MAX_LENGTH).
        field: The field's name for error messages, e.g. "brief".
        check_injection: Block likely prompt injections (for text the user writes as instructions to the
            model). Off for text that never reaches the model as instructions, e.g. a search query (only
            embedded) or outside text that is put into the prompt as quoted data.

    Raises:
        HTTPException: 422 if the text is empty or too long; 400 if it is a likely prompt injection.
    """
    checked = guard.validate_input(text, kind)
    if not checked.ok:
        problems = " ".join(p.message for p in checked.problems if p.severity == "error")
        raise HTTPException(422, f"{field}: {problems}")
    if check_injection:
        report = guard.check_prompt_injection(checked.cleaned)
        if report.risk == "high":
            logger.warning("Blocked %s (prompt injection: %s)", field, ", ".join(f.rule for f in report.findings))
            raise HTTPException(400, f"The {field} looks like an attempt to change the assistant's instructions "
                                     "and was blocked. Please rephrase it.")
    return checked.cleaned


def checked_optional(text: str, kind: guard.InputKind, field: str, *, check_injection: bool = True) -> str:
    """Like checked_text, but an empty (or blank) text is allowed and returned as ""."""
    return checked_text(text, kind, field, check_injection=check_injection) if text.strip() else ""


def get_project_or_404(project_id: str) -> Project:
    """Look up a project by id, or abort the request with 404 if it does not exist.

    Args:
        project_id: Id of the project to find.

    Returns:
        The stored Project (without computed counts).

    Raises:
        HTTPException: 404 when no project has this id.
    """
    project = db.projects.get(project_id)
    if project is None:
        raise HTTPException(404, f"Project '{project_id}' not found")
    return project


def get_source_or_404(source_id: str) -> Source:
    """Look up a source by id, or abort the request with 404 if it does not exist.

    Args:
        source_id: Id of the source to find.

    Returns:
        The stored Source.

    Raises:
        HTTPException: 404 when no source has this id.
    """
    source = db.sources.get(source_id)
    if source is None:
        raise HTTPException(404, f"Source '{source_id}' not found")
    return source


def retrieve(project_id: str, query: str, k: int, source_ids: list[str] | None = None,
             operation: str = "search") -> list[tuple[Chunk, float]]:
    """Find the project's chunks most similar to a query (vector search in Chroma).

    Wraps retrieval.retrieve_chunks and turns vector store errors into HTTP errors.

    Args:
        project_id: Project to search in.
        query: Natural-language query.
        k: Maximum number of results.
        source_ids: Optional filter: only search these sources.
        operation: What the search is for, for the usage log (e.g. "search", "verify").

    Returns:
        (chunk, similarity) pairs, best first.

    Raises:
        HTTPException: 503 if no embedding API key is configured, 502 if the search fails, 504 if the embedding
            request timed out after all retries.
    """
    try:
        return retrieve_chunks(project_id, query, k, source_ids, operation=operation)
    except vectorstore.VectorStoreError as e:
        if not vectorstore.is_configured():
            raise HTTPException(503, str(e)) from e
        failure = model_failure(e, None)
        raise HTTPException(failure.status_code, str(failure)) from e
