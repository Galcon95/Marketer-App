"""The public demo's "Try as guest" (core/guest.py): POST /guest, open without a sign-in.

    POST /guest  sign the visitor in as the shared guest account; answers the session's tokens (never the password)

If nobody has used the guest account for 15 minutes (core/guest.py IDLE), the demo starts afresh first: the guest gets
a new password, and its project loses everything visitors made (posts, ads with their pictures, campaign kits,
chats, discussion analyses, the Substack name). Its books and their summaries stay. While a visitor is active, the
next one joins them instead, so nobody loses their work halfway.

Each visitor's IP address may start the demo starts_per_ip_per_day times a day ([guest] in limits.toml; the server's
own address is exempt, for local testing). The addresses are kept only in memory, as salted hashes, and forgotten the
next day (UTC): an IP address is personal data. Behind Render's proxy the visitor's address is the last entry of
X-Forwarded-For (the one the proxy added; earlier entries come from the visitor and could be made up).
"""

import hashlib
import ipaddress
import logging
import secrets
import threading
import time
from collections import deque
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, HTTPException, Request

from app.core import ad_images, alarm, audit, guest
from app.core import state as db
from app.core.limits import LIMITS
from app.core.schemas import GuestSession
from app.db import records

logger = logging.getLogger(__name__)

router = APIRouter()

STARTS_PER_MINUTE = 30  # "Try as guest" for all visitors together: each one asks Supabase up to three times
_starts: deque[float] = deque()
_starts_lock = threading.Lock()

_SALT = secrets.token_bytes(16)  # new on every server start: the hashes cannot be traced back to an address
_per_visitor: dict[str, int] = {}  # hashed IP address → starts today
_per_visitor_day: list[str] = [""]  # the UTC day _per_visitor counts


@router.post("/guest", response_model=GuestSession)
def try_as_guest(request: Request):
    """Sign the visitor in as the demo's guest, after starting the demo afresh if nobody used it for 15 minutes.

    Raises:
        HTTPException: 404 if this server has no demo (GUEST_EMAIL, SUPABASE_URL or SUPABASE_SECRET_KEY missing);
            429 after this visitor's starts for today or too many starts in a minute; 503 if Supabase or the database
            refuses.
    """
    if not guest.configured():
        raise HTTPException(404, "There is no guest demo on this server.")
    if not alarm.demo_on():  # switched off in Telegram (/demo_off) or by the alarm
        raise HTTPException(503, "The demo is paused right now. Please try again later.")
    visitor = _visitor(request)
    _check_visitor(visitor)
    _count_start()
    with guest.lock:
        try:
            if guest.idle() or not guest.has_password():
                guest.new_password()  # whoever knew the old one (a visitor could have changed it) is locked out
            if guest.idle():
                cleared = reset(guest.user_id())
                logger.info("Guest demo started afresh (%d things deleted)", cleared)
                audit.record("guest.reset", detail=f"{cleared} things deleted", user_id=_guest_id())
            session = guest.sign_in()
        except guest.GuestError as e:
            logger.error("Try as guest failed: %s", e)
            raise HTTPException(503, "The guest demo cannot start right now, please try again later.") from e
        except OSError as e:  # DatabaseError while resetting
            logger.error("Could not reset the guest demo: %s", e)
            raise HTTPException(503, "The guest demo cannot start right now, please try again later.") from e
        guest.seen()
    _count_visitor(visitor)
    audit.record("guest.started", user_id=_guest_id())
    return GuestSession(access_token=session["access_token"], refresh_token=session["refresh_token"],
                        expires_in=session.get("expires_in", 3600))


def _guest_id() -> str:
    """The guest's user id for the audit log ("" if it cannot be looked up: the log must not break the demo)."""
    try:
        return guest.user_id()
    except guest.GuestError:
        return ""


def client_ip(request: Request) -> str:
    """The visitor's IP address: the last X-Forwarded-For entry (added by the proxy in front of the server, e.g.
    Render's), else the connection's own address."""
    forwarded = request.headers.get("x-forwarded-for", "")
    if forwarded.strip():
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else ""


def _visitor(request: Request) -> str | None:
    """A salted hash of the visitor's address, or None for the server's own (local tests) or an unknown one."""
    address = client_ip(request)
    try:
        if not address or ipaddress.ip_address(address).is_loopback:
            return None
    except ValueError:  # not an address (e.g. "testclient")
        return None
    return hashlib.sha256(_SALT + address.encode()).hexdigest()


def _today() -> str:
    return datetime.now(timezone.utc).date().isoformat()


def _check_visitor(visitor: str | None) -> None:
    """Refuse a visitor who already started the demo starts_per_ip_per_day times today.

    Raises:
        HTTPException: 429 with Retry-After until midnight UTC.
    """
    if visitor is None:
        return
    with _starts_lock:
        if _per_visitor_day[0] != _today():  # a new day: forget yesterday's addresses
            _per_visitor.clear()
            _per_visitor_day[0] = _today()
        if _per_visitor.get(visitor, 0) < LIMITS.guest.starts_per_ip_per_day:
            return
    alarm.refused()
    audit.record("guest.refused", detail="starts per address per day", user_id="")
    now = datetime.now(timezone.utc)
    tomorrow = datetime.combine(now.date() + timedelta(days=1), datetime.min.time(), timezone.utc)
    raise HTTPException(429, "You have already tried the demo today. Come back tomorrow, or create your own "
                             "account to keep going.",
                        headers={"Retry-After": str(int((tomorrow - now).total_seconds()) + 1)})


def _count_visitor(visitor: str | None) -> None:
    """Count one successful start of this visitor (a refused or failed one does not count)."""
    if visitor is not None:
        with _starts_lock:
            _per_visitor[visitor] = _per_visitor.get(visitor, 0) + 1


def _count_start() -> None:
    """At most STARTS_PER_MINUTE starts a minute (sliding window).

    Raises:
        HTTPException: 429 with Retry-After when the limit is reached.
    """
    clock = time.monotonic()
    with _starts_lock:
        while _starts and clock - _starts[0] > 60:
            _starts.popleft()
        if len(_starts) >= STARTS_PER_MINUTE:
            wait = int(60 - (clock - _starts[0])) + 1
            alarm.refused()
            audit.record("guest.refused", detail="starts per minute", user_id="")
            raise HTTPException(429, f"Too many visitors right now. Try again in {wait} seconds.",
                                headers={"Retry-After": str(wait)})
        _starts.append(clock)


def reset(user_id: str) -> int:
    """Delete what visitors made in the guest's project (database first, then memory and the pictures' files); the
    books, their chunks and summaries stay. Nothing happens if the guest has no project yet (first sign-in).

    Returns:
        How many things were deleted (assets, chats, discussion analyses).

    Raises:
        DatabaseError: If the database refuses; what was deleted before stays deleted.
    """
    project = next((p for p in db.projects.values() if p.owner_id == user_id), None)
    if project is None:
        return 0
    asset_ids = [a.id for a in db.assets.values() if a.project_id == project.id]
    pictures = ad_images.paths_of(asset_ids)
    if asset_ids:
        records.delete_assets(asset_ids)  # their ad pictures' records go with them
    for asset_id in asset_ids:
        db.assets.pop(asset_id, None)
    ad_images.delete_files(pictures)

    chat_ids = [c.id for c in db.conversations.values() if c.project_id == project.id]
    if chat_ids:
        records.delete_conversations(chat_ids)
    for chat_id in chat_ids:
        db.conversations.pop(chat_id, None)

    discussions = records.list_discussions(project.id)
    for analysis in discussions:
        records.delete_discussion(analysis.id)

    if project.substack:
        stored = project.model_copy(update={"substack": "", "source_count": 0, "chunk_count": 0, "asset_count": 0,
                                            "token_count": 0})
        records.save_project(stored)
        db.projects[project.id] = stored
    return len(asset_ids) + len(chat_ids) + len(discussions)
