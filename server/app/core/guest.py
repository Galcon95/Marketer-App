"""The public demo's shared guest account (GUEST_EMAIL): who it is, when it was last used, and its sign-in.

"Try as guest" (POST /guest, api/guest.py) signs a visitor in as this account without them typing anything. The
password lives only in this server's memory: the server sets a new random one through Supabase's admin API (with
SUPABASE_SECRET_KEY) whenever it starts the demo afresh, or when the old one stopped working (a visitor could
change it), then signs in itself and hands the browser only the session's tokens.

What the guest may not do: api/deps.py no_guest; its limits: [guest] in limits.toml.

Sessions: the browser renews a Supabase session on its own (refresh token), so without a check a visitor would stay
signed in as the guest for good. Each "Try as guest" registers its session (the access token's session_id, the same
after every refresh); auth.current_user lets a guest request through only for a session younger than [guest]
session_minutes, else 401, and the app then signs the visitor out. When the demo starts afresh, all earlier
sessions end.

A server restart (a deploy, Render restarting the free server) must not throw the visitors out: on 2026-11-27 two
deploys during a test ended everyone's session, and their next "Try as guest" used up their starts. So a session
this server does not know is still accepted if it began before the server started: its sign-in time comes from the
token itself (Supabase's `amr` claim, the same after every refresh), it must be younger than session_minutes and
newer than the demo's last fresh start (kept here, and read from the audit log after a restart). A session that
began while this server runs must have been registered by "Try as guest", so a sign-in with the guest's password from
elsewhere is still refused. For the same reason the demo is not started afresh right after a restart while a session
could still be running (the last "Try as guest" in the audit log is less than session_minutes ago).
"""

import logging
import secrets
import threading
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

import httpx
import jwt

from app.core.config import GUEST_EMAIL, SUPABASE_SECRET_KEY, SUPABASE_URL
from app.core.limits import LIMITS
from app.core.schemas import Project

logger = logging.getLogger(__name__)

IDLE = timedelta(minutes=15)  # the guest's work is kept for the next visitor while someone used it this recently
TIMEOUT = 15  # seconds for one request to Supabase Auth
# A sign-in time in the token has whole seconds and is set just after the fresh start is logged: a session that began
# this long before the logged fresh start still counts as after it (earlier visitors were quiet for IDLE anyway).
RESET_GRACE = timedelta(seconds=60)

_last_active: datetime | None = None  # when the guest last sent a request (None: not since this server started)
_password: str | None = None  # the guest's current password (None: not set since this server started)
_user_id: str | None = None  # the guest's Supabase user id, once known
_sessions: dict[str, datetime] = {}  # session id → when "Try as guest" started it
_server_started = datetime.now(timezone.utc)  # sessions that began earlier are not in _sessions (see the docstring)
_reset_at: list[datetime | None] = [None]  # the demo's last fresh start ([None]: not known yet, read from the log)
_reset_known: list[bool] = [False]
lock = threading.Lock()  # one "Try as guest" at a time: two must not reset or set the password together


class GuestError(Exception):
    """Supabase Auth refused or could not be reached; the demo cannot start right now."""


def is_guest(user_id: str, email: str) -> bool:
    """True for the guest: its email (any case), or its user id once known, so a visitor who managed to change the
    account's email is still the guest. False for everyone if GUEST_EMAIL is not set."""
    return bool(GUEST_EMAIL) and (email.lower() == GUEST_EMAIL or (_user_id is not None and user_id == _user_id))


def remember(projects: Iterable[Project]) -> None:
    """Learn the guest's user id on startup, from its project (named after GUEST_EMAIL when it was created; no user
    can rename a project), so the guest is known by its id before anyone presses "Try as guest"."""
    global _user_id
    if GUEST_EMAIL and _user_id is None:
        _user_id = next((p.owner_id for p in projects if p.owner_id and p.name.lower() == GUEST_EMAIL), None)


def configured() -> bool:
    """True if the demo can run here: a guest account is named and the server can manage it."""
    return bool(GUEST_EMAIL and SUPABASE_URL and SUPABASE_SECRET_KEY)


def seen(now: datetime | None = None) -> None:
    """Note that the guest just sent a request (auth.current_user calls it for every guest request)."""
    global _last_active
    _last_active = now or datetime.now(timezone.utc)


def idle(now: datetime | None = None) -> bool:
    """True if nobody has used the guest account for IDLE. Right after a restart (no request seen yet): only if the
    last "Try as guest" is longer ago than a session lasts, so a restart does not wipe a visitor's work."""
    now = now or datetime.now(timezone.utc)
    if _last_active is not None:
        return now - _last_active >= IDLE
    latest = _latest_event("guest.started")
    return latest is None or now - latest >= timedelta(minutes=LIMITS.guest.session_minutes)


def _latest_event(action: str) -> datetime | None:
    """When the audit log last recorded this action (None: never, or the log cannot be read: then the demo behaves
    as before the restart-proof sessions, which is safe)."""
    from app.db import records  # here, not at the top: the database layer is not needed to import this module
    try:
        _, latest = records.count_audit_events(action)
    except Exception as e:  # noqa: BLE001 (any database error: the demo must still start)
        logger.warning("Guest demo: the audit log cannot be read (%s)", e)
        return None
    return latest.replace(tzinfo=timezone.utc) if latest is not None and latest.tzinfo is None else latest


def _last_reset() -> datetime | None:
    """The demo's last fresh start: noted by end_sessions, or after a restart read once from the audit log."""
    if not _reset_known[0]:
        _reset_at[0], _reset_known[0] = _latest_event("guest.reset"), True
    return _reset_at[0]


def start_session(access_token: str, now: datetime | None = None) -> None:
    """Register the session of a "Try as guest" (read from the token Supabase just gave this server; a token without
    a session id registers nothing, and its requests are then refused)."""
    try:
        session_id = jwt.decode(access_token, options={"verify_signature": False}).get("session_id")
    except jwt.PyJWTError:
        return
    if session_id:
        _sessions[session_id] = now or datetime.now(timezone.utc)


def end_sessions(now: datetime | None = None) -> None:
    """End every guest session (the demo starts afresh: earlier visitors' work is gone, and so are they)."""
    _sessions.clear()
    _reset_at[0], _reset_known[0] = now or datetime.now(timezone.utc), True


def session_ok(session_id: str, signed_in_at: datetime | None = None, now: datetime | None = None) -> bool:
    """True if a guest request's session is younger than [guest] session_minutes and may go on: started by "Try as
    guest" on this server, or (`signed_in_at`, from the token) begun before this server started and after the demo's
    last fresh start (see the module docstring)."""
    now = now or datetime.now(timezone.utc)
    limit = timedelta(minutes=LIMITS.guest.session_minutes)
    for old in [s for s, at in _sessions.items() if now - at >= limit]:
        _sessions.pop(old, None)
    if not session_id:
        return False
    if session_id in _sessions:
        return True
    if signed_in_at is None or signed_in_at >= _server_started or now - signed_in_at >= limit:
        return False
    reset = _last_reset()
    if reset is not None and signed_in_at < reset - RESET_GRACE:
        return False
    _sessions[session_id] = signed_in_at  # known from now on (and ended with the others at the next fresh start)
    return True


def _client() -> httpx.Client:
    return httpx.Client(base_url=f"{SUPABASE_URL}/auth/v1", timeout=TIMEOUT,
                        headers={"apikey": SUPABASE_SECRET_KEY, "Authorization": f"Bearer {SUPABASE_SECRET_KEY}"})


def _check(response: httpx.Response, action: str) -> None:
    if response.is_error:
        raise GuestError(f"Supabase Auth refused to {action} ({response.status_code}): {response.text[:200]}")


def user_id() -> str:
    """The guest's Supabase user id (looked up once among the project's users, then remembered).

    Raises:
        GuestError: If Supabase cannot be asked, or no user has GUEST_EMAIL.
    """
    global _user_id
    if _user_id:
        return _user_id
    try:
        with _client() as client:
            for page in range(1, 21):  # 50 users a page; far more than this app has
                response = client.get("/admin/users", params={"page": page, "per_page": 50})
                _check(response, "list the users")
                users = response.json().get("users", [])
                match = next((u for u in users if (u.get("email") or "").lower() == GUEST_EMAIL), None)
                if match:
                    _user_id = match["id"]
                    return _user_id
                if len(users) < 50:
                    break
    except httpx.HTTPError as e:
        raise GuestError(f"Supabase Auth cannot be reached: {e}") from e
    raise GuestError(f"There is no user {GUEST_EMAIL} in Supabase (Authentication → Users).")


def new_password() -> None:
    """Give the guest a new random password (it never leaves this server). Its email is set back to GUEST_EMAIL (a
    visitor could have changed it) and confirmed at the same time, in case "Auto Confirm User" was not ticked when
    the account was made (nobody can open that mailbox).

    Raises:
        GuestError: If Supabase refuses or cannot be reached.
    """
    global _password
    password = secrets.token_urlsafe(24)
    try:
        with _client() as client:
            _check(client.put(f"/admin/users/{user_id()}", json={"password": password, "email": GUEST_EMAIL,
                                                                 "email_confirm": True}),
                   "set the guest's password")
    except httpx.HTTPError as e:
        raise GuestError(f"Supabase Auth cannot be reached: {e}") from e
    _password = password


def has_password() -> bool:
    return _password is not None


def sign_in() -> dict:
    """Sign in as the guest with the current password; a password that stopped working is replaced once.

    Returns:
        The session: access_token, refresh_token, expires_in, expires_at, token_type, user (as Supabase sends them).

    Raises:
        GuestError: If Supabase refuses or cannot be reached.
    """
    if _password is None:
        new_password()
    for attempt in range(2):
        try:
            with _client() as client:
                response = client.post("/token", params={"grant_type": "password"},
                                       json={"email": GUEST_EMAIL, "password": _password})
        except httpx.HTTPError as e:
            raise GuestError(f"Supabase Auth cannot be reached: {e}") from e
        if response.status_code == 400 and attempt == 0:  # "Invalid login credentials": someone changed it
            new_password()
            continue
        _check(response, "sign the guest in")
        return response.json()
    raise GuestError("The guest cannot sign in.")  # not reached: the second attempt returns or raises


def forget() -> None:
    """Forget everything about the guest (tests)."""
    global _last_active, _password, _user_id
    _last_active = _password = _user_id = None
    _sessions.clear()
    _reset_at[0], _reset_known[0] = None, False
