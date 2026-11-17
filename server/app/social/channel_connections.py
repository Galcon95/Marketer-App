"""Every user's own YouTube channel: connecting it with Google sign-in, and the channel a user works on.

    login_available()                the server is set up for Google sign-in (client id + secret, TOKEN_ENCRYPTION_KEY)
    login_url(user_id, return_to)    Google's sign-in page, with a signed, single-use `state`
    finish_login(code, user_id)      after Google sent the browser back: exchange the code, find the channel, save it
    channel_for(user_id)             → ChannelAccess with a fresh access token, or None (not connected)
    channel_name(user_id)            the connected channel's name as saved
    disconnect(user_id)              forget the channel (and ask Google to revoke the app's access)

Google sign-in (OAuth 2.0 code flow, "offline" access): Google asks the user for the scope below and sends the browser
to PUBLIC_API_URL/youtube/oauth/callback with a one-time code; the server exchanges it (with the client secret, server
to server) for an access token (about an hour) and a refresh token. Only the refresh token is kept, encrypted
(secret_box.py); access tokens are made from it when needed and kept in memory until shortly before they expire. If
the user picks a brand account at sign-in, the channel is that brand account's.

The `state` is the same signed, single-use, 10-minute state as Facebook Login's (page_connections.make_state), marked
"youtube", so a state for one does not work for the other.

While the Google app's publishing status is "Testing", only its test users can sign in, and Google lets their refresh
tokens expire after 7 days: the channel must then be connected again (the API says so).
"""

import logging
import threading
import time
from typing import Any
from urllib.parse import urlencode

import httpx

from app.core import config, secret_box
from app.core import state as db
from app.core.schemas import YouTubeConnection
from app.db import records
from app.social import page_connections, youtube
from app.social.page_connections import LoginError
from app.social.youtube import ChannelAccess, YouTubeError

logger = logging.getLogger(__name__)

AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
TOKEN_URL = "https://oauth2.googleapis.com/token"
REVOKE_URL = "https://oauth2.googleapis.com/revoke"
# Read and reply to comments on the channel's videos (and read the channel itself).
SCOPES = ["https://www.googleapis.com/auth/youtube.force-ssl"]
TIMEOUT = 20  # seconds per request to Google
MARGIN = 120  # seconds before expiry an access token is no longer used

_lock = threading.Lock()
_access: dict[str, tuple[float, str]] = {}  # user id → (expiry, access token)


def redirect_uri() -> str:
    """Where Google sends the browser back to; must be an authorized redirect URI of the OAuth client."""
    return f"{config.PUBLIC_API_URL}/youtube/oauth/callback"


def login_available() -> bool:
    """True if users can connect their channel: client id and secret set, and a key to encrypt the tokens with."""
    return bool(config.GOOGLE_CLIENT_ID and config.GOOGLE_CLIENT_SECRET) and secret_box.is_configured()


# ---------- Google sign-in ----------
def login_url(user_id: str, return_to: str) -> str:
    """Google's sign-in page for this user.

    Args:
        user_id: The signed-in user.
        return_to: The client's origin, where the browser goes back to (one of CLIENT_ORIGINS).

    Raises:
        LoginError: If Google sign-in is not set up or return_to is not an allowed origin.
    """
    if not login_available():
        raise LoginError("Google sign-in is not set up on the server (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, "
                         "TOKEN_ENCRYPTION_KEY).")
    return_to = return_to.rstrip("/")
    if return_to not in config.CLIENT_ORIGINS:
        raise LoginError("Unknown address to return to.")
    query = urlencode({
        "client_id": config.GOOGLE_CLIENT_ID, "redirect_uri": redirect_uri(), "response_type": "code",
        # select_account: Google always shows the account chooser, where a brand account's channel can be picked
        "scope": " ".join(SCOPES), "access_type": "offline", "prompt": "select_account consent",
        "include_granted_scopes": "true",
        "state": page_connections.make_state(user_id, return_to, purpose="youtube")})
    return f"{AUTH_URL}?{query}"


def read_state(state: str) -> tuple[str, str]:
    """The user id and return origin of a state from login_url; each state is accepted once.

    Raises:
        LoginError: If the state is malformed, forged, for Facebook, expired or used before.
    """
    try:
        return page_connections.read_state(state, purpose="youtube")
    except LoginError as e:
        raise LoginError("The Google sign-in could not be verified or expired. Start it again from the app.") from e


def finish_login(code: str, user_id: str) -> None:
    """Exchange the code from Google for tokens, find the channel and save it (replaces one connected before).

    Raises:
        LoginError: If the exchange fails, Google gave no refresh token, or the account has no channel.
        DatabaseError: If the connection cannot be saved.
    """
    try:
        tokens = _token_request({"code": code, "client_id": config.GOOGLE_CLIENT_ID,
                                 "client_secret": config.GOOGLE_CLIENT_SECRET, "redirect_uri": redirect_uri(),
                                 "grant_type": "authorization_code"})
    except LoginError as e:
        logger.warning("Google sign-in: the code exchange failed: %s", e)
        raise LoginError("Google did not confirm the sign-in. Try again.") from e
    access, refresh = tokens.get("access_token"), tokens.get("refresh_token")
    if not access or not refresh:
        raise LoginError("Google gave no lasting access. Try again and allow the app to manage your YouTube account.")
    scope = tokens.get("scope", "")
    if scope and not set(SCOPES) <= set(scope.split()):
        raise LoginError("The app needs the permission to see and manage your YouTube comments: tick it on Google's "
                         "page and try again.")
    try:
        channel = youtube.my_channel(access)
    except YouTubeError as e:
        raise LoginError(str(e) if e.status_code == 404 else f"Your channel could not be read: {e}") from e
    records.save_youtube_connection(YouTubeConnection(
        user_id=user_id, channel_id=channel.id, channel_name=channel.name, token=secret_box.encrypt(refresh),
        connected_at=db.now()))
    with _lock:
        _access[user_id] = (time.time() + float(tokens.get("expires_in", 3600)), access)
    logger.info("A user connected the YouTube channel %s", channel.id)


# ---------- the channel a user works on ----------
def channel_for(user_id: str) -> ChannelAccess | None:
    """The user's channel with an access token that is valid for at least two minutes, or None if not connected.

    Raises:
        YouTubeError: 503 if Google no longer accepts the connection (connect again), 502/504 if Google fails.
        DatabaseError: If the database cannot be read.
    """
    connection = records.get_youtube_connection(user_id)
    if not connection:
        return None
    with _lock:
        expiry, token = _access.get(user_id, (0.0, ""))
    if expiry - MARGIN > time.time():
        return ChannelAccess(connection.channel_id, token)
    try:
        refresh = secret_box.decrypt(connection.token)
    except secret_box.SecretError:
        logger.warning("The saved YouTube refresh token of a user cannot be decrypted (key changed?)")
        return None
    try:
        tokens = _token_request({"client_id": config.GOOGLE_CLIENT_ID, "client_secret": config.GOOGLE_CLIENT_SECRET,
                                 "refresh_token": refresh, "grant_type": "refresh_token"})
    except LoginError as e:
        raise YouTubeError(503, "Google no longer accepts the connection to your YouTube channel (access removed, or "
                                "older than 7 days while the Google app is in testing): connect it again under "
                                "Integrations → YouTube channel.") from e
    token = tokens.get("access_token", "")
    if not token:
        raise YouTubeError(502, "Google answered without an access token. Try again.")
    with _lock:
        _access[user_id] = (time.time() + float(tokens.get("expires_in", 3600)), token)
    return ChannelAccess(connection.channel_id, token)


def channel_name(user_id: str) -> str:
    """Name of the user's connected channel as saved ("" if none)."""
    connection = records.get_youtube_connection(user_id)
    return connection.channel_name if connection else ""


def disconnect(user_id: str) -> None:
    """Forget the user's channel and ask Google to revoke the app's access (best effort: the connection is
    forgotten even if Google cannot be reached).

    Raises:
        DatabaseError: If the database cannot be read or written.
    """
    connection = records.get_youtube_connection(user_id)
    with _lock:
        _access.pop(user_id, None)
    records.delete_youtube_connection(user_id)
    if connection:
        try:
            refresh = secret_box.decrypt(connection.token)
            with _client() as client:
                client.post(REVOKE_URL, data={"token": refresh})
        except (secret_box.SecretError, httpx.HTTPError) as e:
            logger.warning("Could not revoke a YouTube token at Google: %s", type(e).__name__)
    logger.info("A user disconnected their YouTube channel")


# ---------- helpers ----------
def _client() -> httpx.Client:
    """The HTTP client for Google's OAuth endpoints (tests replace it with one on a fake transport)."""
    return httpx.Client(timeout=TIMEOUT)


def _token_request(data: dict[str, str]) -> dict[str, Any]:
    """One request to Google's token endpoint; the JSON answer.

    Raises:
        LoginError: If Google refuses (e.g. invalid_grant: code used, refresh token revoked or expired).
        YouTubeError: 504 on a timeout, 502 if Google cannot be reached.
    """
    try:
        with _client() as client:
            response = client.post(TOKEN_URL, data=data)
    except httpx.TimeoutException as e:
        raise YouTubeError(504, "Google did not answer in time. Try again.") from e
    except httpx.HTTPError as e:
        logger.warning("Google token request failed: %s", type(e).__name__)
        raise YouTubeError(502, "Could not reach Google. Try again.") from e
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.is_success and isinstance(body, dict) and "error" not in body:
        return body
    error = body.get("error", f"HTTP {response.status_code}") if isinstance(body, dict) else "?"
    logger.warning("Google token request refused: %s", error)
    raise LoginError(f"Google refused: {error}")
