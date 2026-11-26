"""Every user's own Facebook Page: connecting it with Facebook Login, and which Page a user works on.

    page_for(user)                  → (PageAccess, source): the user's connected Page ("user"); for the admin without
                                      one, the Page in server/.env ("server"); else (None, "")
    login_available()               the server is set up for Facebook Login (app id + secret, TOKEN_ENCRYPTION_KEY)
    login_url(user_id, return_to)   the Facebook Login dialog, with a signed, single-use `state`
    finish_login(code, state)       after Facebook sent the browser back: exchange the code, find the user's Pages;
                                    one Page is connected at once, several wait for the user's choice (choices())
    choose(user_id, page_id)        connect one of the waiting Pages
    disconnect(user_id)             forget the user's Page (its token is deleted)

Facebook Login (OAuth 2.0 code flow): the dialog asks the user for the Page permissions below; Facebook sends the
browser to PUBLIC_API_URL/facebook/oauth/callback with a one-time code; the server exchanges it (with the app secret,
server to server) for a user token, makes it long-lived and reads the Pages the user manages with their Page tokens.
A Page token made from a long-lived user token does not expire. Only the chosen Page's token is kept, encrypted
(secret_box.py); the user token is dropped right away, the tokens of the other Pages after the choice or 10 minutes.

The `state` names the user and where the browser goes back to (one of CLIENT_ORIGINS), expires after 10 minutes, is
signed with a key derived from TOKEN_ENCRYPTION_KEY and works once: a forged or replayed callback is refused.

While the Meta app is in development mode, only people with a role in the app (admin, developer, tester) can grant
these permissions; for everyone else Meta must review the app first (App Review).
"""

import base64
import hmac
import json
import logging
import secrets
import threading
import time
from dataclasses import dataclass, field
from typing import Literal
from urllib.parse import urlencode

from app.core import accounts, audit, config, secret_box
from app.core import state as db
from app.core.auth import User
from app.core.schemas import FacebookConnection, FacebookPageChoice
from app.db import records
from app.social import facebook
from app.social.facebook import FacebookError, PageAccess

logger = logging.getLogger(__name__)

# What the app may do with the user's Page: list it, read its posts and comments, post, reply to comments.
SCOPES = ["pages_show_list", "pages_read_engagement", "pages_read_user_content", "pages_manage_posts",
          "pages_manage_engagement"]
STATE_TTL = 600  # seconds a login may take; also how long several Pages wait for the user's choice

Source = Literal["user", "server", ""]

_lock = threading.Lock()
_used_states: dict[str, float] = {}  # nonce → expiry: each state works once
_waiting: dict[str, tuple[float, list["PageChoice"]]] = {}  # user id → (expiry, Pages to choose from)


@dataclass(frozen=True)
class PageChoice:
    """A Page the user manages, with its token (kept in memory until the user chose)."""

    id: str
    name: str
    token: str = field(repr=False)


class LoginError(Exception):
    """Facebook Login could not connect a Page; the message is for the user."""


def redirect_uri() -> str:
    """Where Facebook sends the browser back to; must be a Valid OAuth Redirect URI of the Meta app."""
    return f"{config.PUBLIC_API_URL}/facebook/oauth/callback"


def login_available() -> bool:
    """True if users can connect their Page: app id and secret set, and a key to encrypt the tokens with."""
    return bool(config.FACEBOOK_APP_ID and config.FACEBOOK_APP_SECRET) and secret_box.is_configured()


# ---------- which Page a user works on ----------
def user_page(user_id: str) -> PageAccess | None:
    """The Page the user connected, or None (none, or its token can no longer be decrypted).

    Raises:
        DatabaseError: If the database cannot be read.
    """
    connection = records.get_facebook_connection(user_id)
    if not connection:
        return None
    try:
        return PageAccess(connection.page_id, secret_box.decrypt(connection.token))
    except secret_box.SecretError:
        logger.warning("The saved Facebook Page token of a user cannot be decrypted (key changed?)")
        return None


def page_for(user: User) -> tuple[PageAccess | None, Source]:
    """The Page this user works on: their own connected Page; for the admin without one, the Page in server/.env.
    Nobody else ever gets the admin's Page.

    Raises:
        DatabaseError: If the database cannot be read.
    """
    own = user_page(user.id)
    if own:
        return own, "user"
    if accounts.is_admin(user):
        env = facebook.env_page()
        if env:
            return env, "server"
    return None, ""


def page_name(user_id: str) -> str:
    """Name of the user's connected Page as saved ("" if none)."""
    connection = records.get_facebook_connection(user_id)
    return connection.page_name if connection else ""


# ---------- Facebook Login ----------
def login_url(user_id: str, return_to: str) -> str:
    """The Facebook Login dialog for this user.

    Args:
        user_id: The signed-in user.
        return_to: The client's origin, where the browser goes back to (one of CLIENT_ORIGINS).

    Raises:
        LoginError: If Facebook Login is not set up or return_to is not an allowed origin.
    """
    if not login_available():
        raise LoginError("Facebook Login is not set up on the server (FACEBOOK_APP_ID, FACEBOOK_APP_SECRET, "
                         "TOKEN_ENCRYPTION_KEY).")
    return_to = return_to.rstrip("/")
    if return_to not in config.CLIENT_ORIGINS:
        raise LoginError("Unknown address to return to.")
    query = urlencode({"client_id": config.FACEBOOK_APP_ID, "redirect_uri": redirect_uri(),
                       "state": make_state(user_id, return_to), "scope": ",".join(SCOPES), "response_type": "code"})
    return f"https://www.facebook.com/{config.FACEBOOK_GRAPH_VERSION}/dialog/oauth?{query}"


def make_state(user_id: str, return_to: str, purpose: str = "facebook") -> str:
    """A signed state: the user, where to return, what the login is for (a Facebook state does not work for the
    YouTube callback and back), a nonce and the expiry."""
    payload = json.dumps({"u": user_id, "r": return_to, "p": purpose, "n": secrets.token_urlsafe(16),
                          "e": int(time.time()) + STATE_TTL}, separators=(",", ":"))
    body = base64.urlsafe_b64encode(payload.encode()).decode().rstrip("=")
    return f"{body}.{secret_box.sign(body)}"


def read_state(state: str, purpose: str = "facebook") -> tuple[str, str]:
    """The user id and return origin of a state made by make_state for this purpose; each state is accepted once.

    Raises:
        LoginError: If the state is malformed, forged, for another purpose, expired or used before.
    """
    body, _, signature = (state or "").partition(".")
    try:
        valid = bool(body) and hmac.compare_digest(signature, secret_box.sign(body))
        data = json.loads(base64.urlsafe_b64decode(body + "=" * (-len(body) % 4))) if valid else None
    except (ValueError, secret_box.SecretError):
        data = None
    if not isinstance(data, dict) or data.get("r") not in config.CLIENT_ORIGINS or data.get("p") != purpose:
        raise LoginError("The Facebook Login could not be verified. Start it again from the app.")
    now = time.time()
    with _lock:
        for nonce in [n for n, expiry in _used_states.items() if expiry < now]:
            del _used_states[nonce]
        if data.get("e", 0) < now or data.get("n") in _used_states:
            raise LoginError("The Facebook Login expired or was already used. Start it again from the app.")
        _used_states[data["n"]] = data["e"]
    return data["u"], data["r"]


def finish_login(code: str, user_id: str) -> Literal["connected", "choose"]:
    """Exchange the code from Facebook for the user's Pages: connect the only one, or keep several for choose().

    Raises:
        LoginError: If the code exchange fails or the user manages no Page (or granted no access to one).
        DatabaseError: If the connection cannot be saved.
    """
    try:
        short = facebook.graph_request("GET", "oauth/access_token", None, {
            "client_id": config.FACEBOOK_APP_ID, "client_secret": config.FACEBOOK_APP_SECRET,
            "redirect_uri": redirect_uri(), "code": code})["access_token"]
        long = facebook.graph_request("GET", "oauth/access_token", None, {
            "grant_type": "fb_exchange_token", "client_id": config.FACEBOOK_APP_ID,
            "client_secret": config.FACEBOOK_APP_SECRET, "fb_exchange_token": short})["access_token"]
        data = facebook.graph_request("GET", "me/accounts", long, {"fields": "id,name,access_token", "limit": 100})
    except (FacebookError, KeyError) as e:
        logger.warning("Facebook Login: the code exchange failed: %s", e)
        raise LoginError("Facebook did not confirm the login. Try again.") from e
    pages = [PageChoice(p["id"], p.get("name", ""), p["access_token"])
             for p in data.get("data", []) if p.get("id") and p.get("access_token")]
    if not pages:
        raise LoginError("No Facebook Page found: you need to manage a Page and allow the app to use it.")
    if len(pages) == 1:
        _save(user_id, pages[0])
        return "connected"
    with _lock:
        _waiting[user_id] = (time.time() + STATE_TTL, pages)
    return "choose"


def choices(user_id: str) -> list[FacebookPageChoice]:
    """The Pages waiting for the user's choice after a login (none after 10 minutes)."""
    with _lock:
        expiry, pages = _waiting.get(user_id, (0.0, []))
    return [FacebookPageChoice(id=p.id, name=p.name) for p in pages] if expiry > time.time() else []


def choose(user_id: str, page_id: str) -> None:
    """Connect one of the Pages waiting for the user's choice; the other tokens are dropped.

    Raises:
        LoginError: If no such Page is waiting (expired: log in again).
        DatabaseError: If the connection cannot be saved.
    """
    with _lock:
        expiry, pages = _waiting.get(user_id, (0.0, []))
        page = next((p for p in pages if p.id == page_id), None) if expiry > time.time() else None
        if not page:
            raise LoginError("This Page is no longer waiting: connect again.")
        del _waiting[user_id]
    _save(user_id, page)


def disconnect(user_id: str) -> None:
    """Forget the user's Page and any Pages waiting for a choice.

    Raises:
        DatabaseError: If the database cannot be written.
    """
    with _lock:
        _waiting.pop(user_id, None)
    records.delete_facebook_connection(user_id)
    logger.info("A user disconnected their Facebook Page")
    audit.record("facebook.disconnected", user_id=user_id)


def _save(user_id: str, page: PageChoice) -> None:
    """Save the Page with its token encrypted (replaces a Page connected before)."""
    records.save_facebook_connection(FacebookConnection(
        user_id=user_id, page_id=page.id, page_name=page.name, token=secret_box.encrypt(page.token),
        connected_at=db.now()))
    logger.info("A user connected the Facebook Page %s", page.id)
    audit.record("facebook.connected", page.id, user_id=user_id)
