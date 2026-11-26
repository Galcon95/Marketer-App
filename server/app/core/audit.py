"""The audit log: who did what that matters for security, and when. Saved in private.audit_events (only added and
read, never changed) and written as a log line (logger "app.audit"), so an incident can be traced afterwards:
which key was created when, who connected a Page, what was posted, what was refused.

    record(action, target, detail)   note one event; the user and the request id come from the request (logs.py)
    recent(limit, user_id, prefix)   the latest events, newest first (GET /audit, the admin only)

What is recorded (ACTIONS): API keys created, revoked and refused; a Facebook Page or YouTube channel connected or
disconnected; everything written to the outside world (posts, replies, comments, by a click or by the agent after an
approval); books uploaded and deleted; requests blocked by the guard or refused for lack of rights; the guest demo's
starts, resets and refusals; the app switches.

Rules:
  - Never a secret (a key, a token) and never a text someone wrote (a post, a question): ids and short facts only.
  - record() never fails and never slows a request down much: a database error is logged, and the event is then only
    in the log.
  - Events anyone can cause without signing in or again and again (a wrong key, a blocked text, a refused guest
    start) are "noisy": at most NOISY_PER_MINUTE of them a minute are saved, the rest are only logged, so an attacker
    cannot fill the table.
"""

import logging
import threading
import time
from collections import deque
from datetime import datetime, timezone

from app.core import logs
from app.core.schemas import AuditEvent
from app.db import records

logger = logging.getLogger("app.audit")

# action → what it means. An unknown action is a programming error (record raises ValueError, also in tests).
ACTIONS = {
    "api_key.created": "a personal API key for the MCP servers was created",
    "api_key.revoked": "an API key was revoked",
    "api_key.refused": "an MCP request came with a wrong or revoked key",
    "facebook.connected": "a Facebook Page was connected",
    "facebook.disconnected": "the Facebook Page was disconnected",
    "facebook.post_published": "a post was published on the Page",
    "facebook.reply_published": "a reply or comment was published on the Page",
    "youtube.connected": "a YouTube channel was connected",
    "youtube.disconnected": "the YouTube channel was disconnected",
    "youtube.reply_published": "a reply or comment was published on the channel",
    "source.uploaded": "a book was uploaded",
    "source.deleted": "a book was deleted, with what belonged only to it",
    "input.blocked": "a text was blocked as a likely prompt injection",
    "output.blocked": "a text was not published: an injection seems to have got through",
    "access.refused": "a signed-in user asked for something only the admin (or no guest) may do",
    "guest.started": "a visitor started the guest demo",
    "guest.reset": "the guest demo was started afresh (new password, visitors' work deleted)",
    "guest.refused": "a guest start was refused (limit per address or per minute)",
    "switch.changed": "an app switch (demo, freeze) was changed",
}
NOISY = {"api_key.refused", "input.blocked", "output.blocked", "access.refused", "guest.refused"}
NOISY_PER_MINUTE = 30  # of all noisy events together; more are only logged
MAX_TEXT = 300  # target and detail are cut to this length

_lock = threading.Lock()
_noisy: deque[float] = deque()  # monotonic times of the noisy events saved in the last minute


def record(action: str, target: str = "", detail: str = "", user_id: str | None = None) -> None:
    """Note one event: a log line always, a row in the database unless it is refused as too noisy or fails.

    Args:
        action: One of ACTIONS.
        target: What it was done to (an id).
        detail: One short line, no secret and no text someone wrote.
        user_id: Who did it; default: the signed-in user of the current request, "" outside a request (the agent).

    Raises:
        ValueError: For an action that is not in ACTIONS.
    """
    if action not in ACTIONS:
        raise ValueError(f"Unknown audit action: {action}")
    event = AuditEvent(at=datetime.now(timezone.utc), action=action,
                       user_id=user_id if user_id is not None else (logs.current_user_id() or ""),
                       target=_short(target), detail=_short(detail), request_id=logs.current_request_id() or "")
    logger.info("%s user=%s target=%s %s", action, event.user_id or "-", event.target or "-", event.detail)
    if action in NOISY and not _room_for_noise():
        return
    try:
        records.add_audit_event(event)
    except OSError as e:  # DatabaseError: the event stays in the log
        logger.error("Could not save the audit event %s: %s", action, e)


def recent(limit: int = 100, user_id: str | None = None, action_prefix: str = "") -> list[AuditEvent]:
    """The latest events, newest first: everyone's (user_id None) or one user's; optionally one kind of action.

    Raises:
        DatabaseError: If the database cannot be read.
    """
    return records.recent_audit_events(limit, user_id, action_prefix)


def _room_for_noise() -> bool:
    clock = time.monotonic()
    with _lock:
        while _noisy and clock - _noisy[0] > 60:
            _noisy.popleft()
        if len(_noisy) >= NOISY_PER_MINUTE:
            return False
        _noisy.append(clock)
        return True


def _short(text: str) -> str:
    text = " ".join(str(text).split())
    return text if len(text) <= MAX_TEXT else text[:MAX_TEXT - 1] + "…"
