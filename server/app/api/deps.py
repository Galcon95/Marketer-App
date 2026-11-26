"""Shared helpers of the API routers: the ownership checks (authorization: a user only reaches their own project
and what belongs to it), vector search with HTTP errors, input checks (guardrails) and the rate limit of the
endpoints that call a model, with the cost budgets (limits.toml)."""

import logging
import threading
import time
from collections import defaultdict, deque
from datetime import datetime, timedelta, timezone

from fastapi import Depends, HTTPException

from app.core import accounts, alarm, guard, usage
from app.core import state as db
from app.core.auth import User, current_user
from app.core.limits import LIMITS
from app.core.llm import model_failure
from app.core.schemas import AdImage, Asset, Chunk, Conversation, DiscussionAnalysis, Project, Source
from app.db import records
from app.rag import vectorstore
from app.rag.retrieval import retrieve_chunks

logger = logging.getLogger(__name__)

# Requests per minute of the endpoints that call a model, per user (sliding window; limits.toml).
LLM_RATE_WINDOW = 60  # seconds
_llm_calls: dict[str, deque[float]] = defaultdict(deque)  # user id → times of their recent requests
_llm_calls_lock = threading.Lock()  # sync endpoints run in a thread pool


def llm_limits(user: User = Depends(current_user)) -> None:
    """FastAPI dependency for endpoints that call a model (chat or embeddings), protecting against runaway costs (a
    script, a stuck button, a stolen account), with the limits of limits.toml. In this order:
      - the user's cost budget for today and this month (UTC) and the app's budget for today;
      - at most model_requests_per_minute requests per user (blocked requests count too).
    A call's cost is known only after it, so one request can go a little over a budget; the next one is blocked.
    The demo's guest (accounts.is_guest) has the [guest] limits instead of the per_user ones.

    Raises:
        HTTPException: 429 with a Retry-After header (seconds) when a limit is reached; 503 when the costs so far
            cannot be read from the database.
    """
    if alarm.frozen() and not accounts.is_admin(user):  # /freeze in Telegram: everyone but the admin stops
        raise HTTPException(503, "The app is paused by its administrator right now. Please try again later.")
    guest = accounts.is_guest(user)
    limits = LIMITS.guest if guest else LIMITS.per_user
    whose = "The demo's" if guest else "Your"
    now = datetime.now(timezone.utc)
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    month = today.replace(day=1)
    tomorrow, next_month = today + timedelta(days=1), (month + timedelta(days=32)).replace(day=1)
    projects = [p.id for p in db.projects.values() if accounts.owns(user, p)]
    try:
        user_today, user_month, app_today = usage.spending(user.id, projects, now)
    except OSError as e:  # DatabaseError: without knowing the costs, no model call (fail closed)
        logger.error("Could not check the budgets: %s", e)
        raise HTTPException(503, "The usage budget cannot be checked right now, please try again.") from e
    if user_month >= limits.cost_per_month_usd:
        alarm.budget(f"{_who(user, guest)} used up the monthly budget of ${limits.cost_per_month_usd:.2f}.")
        raise _budget_used(f"{whose} monthly budget of ${limits.cost_per_month_usd:.2f} is used up. "
                           "It renews on the 1st of next month (UTC).", next_month - now)
    if user_today >= limits.cost_per_day_usd:
        alarm.budget(f"{_who(user, guest)} used up the daily budget of ${limits.cost_per_day_usd:.2f}.")
        raise _budget_used(f"{whose} daily budget of ${limits.cost_per_day_usd:.2f} is used up. "
                           "It renews at midnight UTC.", tomorrow - now)
    if app_today >= LIMITS.app.cost_per_day_usd:
        logger.warning("The app's daily budget of $%.2f is used up", LIMITS.app.cost_per_day_usd)
        alarm.budget(f"🚨 The app's daily budget of ${LIMITS.app.cost_per_day_usd:.2f} is used up: model calls are "
                     "stopped for everyone until midnight UTC.")
        raise _budget_used("The app's daily budget is used up. It renews at midnight UTC.", tomorrow - now)

    clock = time.monotonic()
    with _llm_calls_lock:
        calls = _llm_calls[user.id]
        while calls and clock - calls[0] > LLM_RATE_WINDOW:
            calls.popleft()
        if len(calls) >= limits.model_requests_per_minute:
            wait = int(LLM_RATE_WINDOW - (clock - calls[0])) + 1
            raise HTTPException(429, f"Too many requests: at most {limits.model_requests_per_minute} model requests "
                                     f"per minute. Try again in {wait} seconds.", headers={"Retry-After": str(wait)})
        calls.append(clock)


def _who(user: User, guest: bool) -> str:
    """How an alarm names a user: "The guest demo" or their email."""
    return "The guest demo" if guest else user.email or user.id


def _budget_used(message: str, until: timedelta) -> HTTPException:
    """A 429 response for a used-up budget, with Retry-After until it renews."""
    return HTTPException(429, message, headers={"Retry-After": str(int(until.total_seconds()) + 1)})


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


def owned_discussion(discussion_id: str, user: User = Depends(current_user)) -> DiscussionAnalysis:
    """FastAPI dependency for routes with {discussion_id}: the discussion analysis, if its project belongs to the
    signed-in user. Read from the database (analyses are not kept in memory).

    Raises:
        HTTPException: 404 if the analysis is unknown or not the user's; 500 if the database cannot be read.
    """
    try:
        analysis = records.get_discussion(discussion_id)
    except OSError as e:  # DatabaseError
        raise HTTPException(500, "The discussion analysis could not be loaded, please try again.") from e
    if analysis is None or not _owns_project(user, analysis.project_id):
        raise HTTPException(404, f"Discussion '{discussion_id}' not found")
    return analysis


def owned_ad_image(image_id: str, user: User = Depends(current_user)) -> AdImage:
    """FastAPI dependency for routes with {image_id}: an ad picture's record, if its project belongs to the signed-in
    user. Read from the database (pictures are not kept in memory).

    Raises:
        HTTPException: 404 if the picture is unknown or not the user's; 500 if the database cannot be read.
    """
    try:
        image = records.get_ad_image(image_id)
    except OSError as e:  # DatabaseError
        raise HTTPException(500, "The picture could not be loaded, please try again.") from e
    if image is None or not _owns_project(user, image.project_id):
        raise HTTPException(404, f"Picture '{image_id}' not found")
    return image


def admin_only(user: User = Depends(current_user)) -> User:
    """FastAPI dependency for app-wide endpoints (usage and costs of all users, MCP console): the admin only
    (DEFAULT_CLIENT_OWNER, accounts.is_admin).

    Raises:
        HTTPException: 403 for every other user.
    """
    if not accounts.is_admin(user):
        raise HTTPException(403, "Only the app's administrator can use this.")
    return user


def no_guest(user: User = Depends(current_user)) -> User:
    """FastAPI dependency for what the public demo's shared guest account (accounts.is_guest) may not do: change the
    library (upload, delete, cover, a new summary), create API keys, connect or post to Facebook or YouTube, run the
    marketing agent.
    The guest's work is reset for the next visitor; these would outlast it, reach real people or cost too much.

    Raises:
        HTTPException: 403 for the guest.
    """
    if accounts.is_guest(user):
        raise HTTPException(403, "Not available in the demo. Create your own account to use this.")
    return user


_guest_scans: dict[str, int] = {}  # UTC day → the demo guest's Reddit/Substack scans that day
_guest_scans_lock = threading.Lock()


def guest_scan_limit(user: User = Depends(current_user)) -> None:
    """FastAPI dependency for the Reddit/Substack scan: the demo's guest may scan scans_per_day times a day (all
    visitors together). Each scan uses Tavily searches, which the cost budget does not count. Everyone else: no limit.

    Raises:
        HTTPException: 429 with Retry-After until midnight UTC.
    """
    if not accounts.is_guest(user):
        return
    now = datetime.now(timezone.utc)
    today = now.date().isoformat()
    with _guest_scans_lock:
        for day in [d for d in _guest_scans if d != today]:
            del _guest_scans[day]
        if _guest_scans.get(today, 0) >= LIMITS.guest.scans_per_day:
            tomorrow = now.replace(hour=0, minute=0, second=0, microsecond=0) + timedelta(days=1)
            raise _budget_used(f"The demo's {LIMITS.guest.scans_per_day} scans for today are used up. They renew at "
                               "midnight UTC.", tomorrow - now)
        _guest_scans[today] = _guest_scans.get(today, 0) + 1


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
    """Find the project's chunks most similar to a query (vector search with pgvector).

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
