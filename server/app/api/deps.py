"""Shared helpers of the API routers: the ownership checks (authorization: a user only reaches their own project
and what belongs to it), vector search with HTTP errors, input checks (guardrails) and the rate limit of the
endpoints that call the language model."""

import logging
import threading
import time
from collections import defaultdict, deque

from fastapi import Depends, HTTPException, Request

from app.core import accounts, guard
from app.core import state as db
from app.core.auth import User, current_user
from app.core.llm import model_failure
from app.core.schemas import Asset, Chunk, Conversation, Project, Source
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


# ---------- Authorization: a user may only use their own project and what belongs to it ----------
# Anything of another user answers 404 exactly like an unknown id, so nobody can find out which ids exist.

def owned_project(project_id: str, user: User = Depends(current_user)) -> Project:
    """FastAPI dependency for routes with {project_id}: the project, if it belongs to the signed-in user.

    Raises:
        HTTPException: 404 if the project is unknown or not the user's.
    """
    project = db.projects.get(project_id)
    if project is None or not accounts.owns(user, project):
        raise HTTPException(404, f"Project '{project_id}' not found")
    return project


def owned_source(source_id: str, user: User = Depends(current_user)) -> Source:
    """FastAPI dependency for routes with {source_id}: the source, if its project belongs to the signed-in user.

    Raises:
        HTTPException: 404 if the source is unknown or not the user's.
    """
    source = db.sources.get(source_id)
    if source is None or not _owns_project(user, source.project_id):
        raise HTTPException(404, f"Source '{source_id}' not found")
    return source


def owned_asset(asset_id: str, user: User = Depends(current_user)) -> Asset:
    """FastAPI dependency for routes with {asset_id}: the asset, if its project belongs to the signed-in user.

    Raises:
        HTTPException: 404 if the asset is unknown or not the user's.
    """
    asset = db.assets.get(asset_id)
    if asset is None or not _owns_project(user, asset.project_id):
        raise HTTPException(404, f"Asset '{asset_id}' not found")
    return asset


def owned_conversation(conversation_id: str, user: User = Depends(current_user)) -> Conversation:
    """FastAPI dependency for routes with {conversation_id}: the conversation, if its project belongs to the
    signed-in user.

    Raises:
        HTTPException: 404 if the conversation is unknown or not the user's.
    """
    conversation = db.conversations.get(conversation_id)
    if conversation is None or not _owns_project(user, conversation.project_id):
        raise HTTPException(404, f"Conversation '{conversation_id}' not found")
    return conversation


def admin_only(user: User = Depends(current_user)) -> User:
    """FastAPI dependency for app-wide endpoints (usage and costs of all users, MCP console): the admin only
    (DEFAULT_CLIENT_OWNER, accounts.is_admin).

    Raises:
        HTTPException: 403 for every other user.
    """
    if not accounts.is_admin(user):
        raise HTTPException(403, "Only the app's administrator can use this.")
    return user


def check_sources(project_id: str, source_ids: list[str] | None) -> None:
    """Check that the books a request names (e.g. a book filter) belong to the project; call it after owned_project.

    Raises:
        HTTPException: 404 for a source that is unknown or belongs to another project.
    """
    for source_id in source_ids or []:
        source = db.sources.get(source_id)
        if source is None or source.project_id != project_id:
            raise HTTPException(404, f"Source '{source_id}' not found")


def _owns_project(user: User, project_id: str) -> bool:
    """True if the project with this id exists and belongs to the user."""
    project = db.projects.get(project_id)
    return project is not None and accounts.owns(user, project)


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
