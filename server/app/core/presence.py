"""Who is using the app right now: each signed-in user's last request, for the admin's /online in Telegram.

    auth.current_user ─► seen(user_id, email)      every signed-in request (the guest too)
    /online           ─► recent(now)               users active in the last day, newest first

Kept only in memory, never saved: a restart starts empty, and an entry is forgotten after a day. The guest is one
shared account, so it shows here as one user; how many visitors share it, guest.open_sessions tells.

The email goes to the admin's Telegram, a service outside the app, so only a masked form leaves the server
(masked(): "pe…@example.com"): enough for the admin to recognise a colleague, not a full address.
"""

import threading
from datetime import datetime, timedelta, timezone
from typing import NamedTuple

KEEP = timedelta(days=1)  # how long a user's last request is remembered


class Presence(NamedTuple):
    user_id: str
    email: str
    last_seen: datetime


_last: dict[str, Presence] = {}
_lock = threading.Lock()
SINCE = datetime.now(timezone.utc)  # this server's start: nothing older is known


def seen(user_id: str, email: str, now: datetime | None = None) -> None:
    """Note a signed-in user's request."""
    with _lock:
        _last[user_id] = Presence(user_id, email, now or datetime.now(timezone.utc))


def recent(now: datetime | None = None) -> list[Presence]:
    """The users seen within KEEP, the most recent first (older entries are forgotten here)."""
    now = now or datetime.now(timezone.utc)
    with _lock:
        for user_id in [u for u, p in _last.items() if now - p.last_seen >= KEEP]:
            del _last[user_id]
        return sorted(_last.values(), key=lambda p: p.last_seen, reverse=True)


def masked(email: str) -> str:
    """"peter@example.com" → "pe…@example.com" (an address without "@" keeps only its first two characters)."""
    name, at, domain = email.partition("@")
    return f"{name[:2]}…{at}{domain}" if name else "(no email)"


def forget() -> None:
    """Forget everyone (tests)."""
    with _lock:
        _last.clear()
