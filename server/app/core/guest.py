"""The public demo's shared guest account (GUEST_EMAIL): who it is, when it was last used, and its sign-in.

"Try as guest" (POST /guest, api/guest.py) signs a visitor in as this account without them typing anything. The
password lives only in this server's memory: the server sets a new random one through Supabase's admin API (with
SUPABASE_SECRET_KEY) whenever it starts the demo afresh, or when the old one stopped working (a visitor could
change it), then signs in itself and hands the browser only the session's tokens.

What the guest may not do: api/deps.py no_guest; its limits: [guest] in limits.toml.
"""

import secrets
import threading
from collections.abc import Iterable
from datetime import datetime, timedelta, timezone

import httpx

from app.core.config import GUEST_EMAIL, SUPABASE_SECRET_KEY, SUPABASE_URL
from app.core.schemas import Project

IDLE = timedelta(minutes=15)  # the guest's work is kept for the next visitor while someone used it this recently
TIMEOUT = 15  # seconds for one request to Supabase Auth

_last_active: datetime | None = None  # when the guest last sent a request (None: not since this server started)
_password: str | None = None  # the guest's current password (None: not set since this server started)
_user_id: str | None = None  # the guest's Supabase user id, once known
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
    """True if nobody has used the guest account for IDLE (or not since this server started)."""
    now = now or datetime.now(timezone.utc)
    return _last_active is None or now - _last_active >= IDLE


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
