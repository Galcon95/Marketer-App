"""The user's own YouTube channel (social/youtube.py): connecting it with Google sign-in, its status, and the comments
under its videos.

    GET    /youtube/status            is a channel connected? its name and subscribers
    POST   /youtube/connect           start Google sign-in: the URL to send the browser to
    GET    /youtube/oauth/callback    Google sends the browser back here (no sign-in token: signed state)
    DELETE /youtube/connection        forget the user's channel
    GET    /youtube/comments          the latest comments on the channel's videos, grouped by video
    POST   /discussions/{id}/reply/youtube   post an analysis's reply as the channel under the comment (on the click)

Every user works on their own channel only (social/channel_connections.py); there is no channel in server/.env. A
reply is posted once; its id, link and time are saved with the analysis.
"""

import logging
import re
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.api.deps import no_guest, owned_discussion
from app.core import audit
from app.core import state as db
from app.core.auth import User, current_user
from app.core.guard import output_blocked, scan_third_party
from app.core.schemas import (DiscussionAnalysis, FacebookConnectRequest, FacebookLoginUrl, YouTubeStatus,
                              YouTubeThread)
from app.db import records
from app.social import channel_connections, youtube
from app.social.page_connections import LoginError

logger = logging.getLogger(__name__)

router = APIRouter()
callback_router = APIRouter()  # included without sign-in: Google redirects the browser, the state names the user


def channel_of(user: User = Depends(current_user)) -> youtube.ChannelAccess:
    """FastAPI dependency: the user's own channel with a fresh access token.

    Raises:
        HTTPException: 503 if the user has no channel (connect one first), Google no longer accepts the connection
            or the database cannot be read; 502 or 504 if Google fails.
    """
    try:
        channel = channel_connections.channel_for(user.id)
    except youtube.YouTubeError as e:
        raise HTTPException(e.status_code, str(e)) from e
    except OSError as e:  # DatabaseError
        raise HTTPException(503, "Your YouTube connection cannot be read right now, please try again.") from e
    if not channel:
        raise HTTPException(503, "No YouTube channel connected: connect yours under Integrations → YouTube channel.")
    return channel


@router.get("/youtube/status", response_model=YouTubeStatus)
def status(user: User = Depends(current_user)):
    """Whether the user has connected a YouTube channel and it is reachable, with its name and subscribers;
    `login_available` whether the user can connect one.

    Never fails: no channel or an unreachable one is reported in the answer (connected false, error).
    """
    login = channel_connections.login_available()
    try:
        channel = channel_connections.channel_for(user.id)
    except youtube.YouTubeError as e:
        return YouTubeStatus(connected=False, error=str(e), login_available=login)
    except OSError:  # DatabaseError
        return YouTubeStatus(connected=False, error="Your YouTube connection cannot be read right now.",
                             login_available=login)
    if not channel:
        return YouTubeStatus(connected=False, login_available=login)
    try:
        with youtube.as_channel(channel):
            return YouTubeStatus(connected=True, channel=youtube.channel_info(), login_available=login)
    except youtube.YouTubeError as e:
        return YouTubeStatus(connected=False, error=str(e), login_available=login)


@router.post("/youtube/connect", response_model=FacebookLoginUrl, dependencies=[Depends(no_guest)])
def connect(body: FacebookConnectRequest, user: User = Depends(current_user)):
    """Start Google sign-in: the URL of Google's page, where the user picks the account (or brand account) of their
    channel and allows the app to read and answer comments. Google then sends the browser to GET
    /youtube/oauth/callback.

    Raises:
        HTTPException: 503 if Google sign-in is not set up on the server; 422 if return_to is not the client's origin.
    """
    if not channel_connections.login_available():
        raise HTTPException(503, "Google sign-in is not set up on the server (GOOGLE_CLIENT_ID, GOOGLE_CLIENT_SECRET, "
                                 "TOKEN_ENCRYPTION_KEY in server/.env).")
    try:
        return FacebookLoginUrl(url=channel_connections.login_url(user.id, body.return_to))
    except LoginError as e:
        raise HTTPException(422, str(e)) from e


@callback_router.get("/youtube/oauth/callback", include_in_schema=False)
def oauth_callback(state: str = "", code: str = "", error: str = ""):
    """Google sends the browser here after sign-in. Connects the channel and sends the browser back to the app with
    ?youtube=connected|cancelled|error (and a message). A forged, expired or replayed state is refused without a
    redirect to an address from the request."""
    try:
        user_id, return_to = channel_connections.read_state(state)
    except LoginError as e:
        raise HTTPException(400, str(e)) from e
    if error or not code:  # the user cancelled or refused the permission
        return _back(return_to, "cancelled")
    try:
        channel_connections.finish_login(code, user_id)
    except LoginError as e:
        return _back(return_to, "error", str(e))
    except youtube.YouTubeError as e:
        return _back(return_to, "error", str(e))
    except OSError:  # DatabaseError
        return _back(return_to, "error", "The connection could not be saved. Try again.")
    return _back(return_to, "connected")


def _back(return_to: str, result: str, message: str = "") -> RedirectResponse:
    """Redirect to the app (an allowed origin from the verified state) with the sign-in's result."""
    query = urlencode({"youtube": result, **({"message": message} if message else {})})
    return RedirectResponse(f"{return_to}/?{query}", status_code=303)


@router.delete("/youtube/connection", status_code=204, dependencies=[Depends(no_guest)])
def disconnect(user: User = Depends(current_user)):
    """Forget the user's channel: its token is deleted from the app and Google is asked to revoke the access.

    Raises:
        HTTPException: 503 if the database cannot be written.
    """
    try:
        channel_connections.disconnect(user.id)
    except OSError as e:  # DatabaseError
        raise HTTPException(503, "Could not disconnect right now, please try again.") from e


@router.get("/youtube/comments", response_model=list[YouTubeThread])
def comments(comments: int = Query(default=50, ge=1, le=100),
             channel: youtube.ChannelAccess = Depends(channel_of)):
    """The latest comments on the channel's videos, grouped by video, newest first. A comment is `answered` when the
    channel has replied in its thread at or after it. The comments are other people's text: shown to the author and
    flagged by the injection scan, given to the agent only through POST /discussions (guard, quoted as data).

    Args:
        comments: How many of the latest comment threads to look at (1-100, default 50).

    Raises:
        HTTPException: 503 if the user has no channel or the access was removed; 429 (quota), 502 or 504 if
            YouTube fails.
    """
    try:
        with youtube.as_channel(channel):
            threads = youtube.recent_threads(comments)
    except youtube.YouTubeError as e:
        raise HTTPException(e.status_code, str(e)) from e
    return [_scanned(thread) for thread in threads]


def _scanned(thread: YouTubeThread) -> YouTubeThread:
    """The thread with every viewer's comment checked for prompt injection (flagged for the GUI, not removed; the
    channel's own replies are the author's and are not scanned)."""
    scanned = []
    for c in thread.comments:
        if not c.from_channel and c.message:
            risk, findings = scan_third_party(c.message)
            c = c.model_copy(update={"injection_risk": risk, "injection_findings": findings})
        scanned.append(c)
    return thread.model_copy(update={"comments": scanned})


@router.post("/discussions/{discussion_id}/reply/youtube", response_model=DiscussionAnalysis,
             dependencies=[Depends(no_guest)])
def reply(analysis: DiscussionAnalysis = Depends(owned_discussion),
          channel: youtube.ChannelAccess = Depends(channel_of)):
    """Post the analysis's reply (as the author edited it, without citation markers) as the channel under the comment
    it answers (YouTube keeps every reply under the thread's top comment).

    Args:
        discussion_id: Id of an analysis made from a comment on the channel (path parameter).

    Returns:
        The analysis with replied_id, replied_url and replied_at set.

    Raises:
        HTTPException: 404 when no analysis of the user has this id; 409 if the reply was posted already; 422 if
            the analysis is not about a comment on the channel, has no reply, or the reply looks like a prompt
            injection got into it (output guard); 503 if the user has no channel or the access was removed; 404,
            429 (quota), 502 or 504 if YouTube fails (404: the comment was deleted or comments are off); 500 if it
            was posted but the record could not be saved.
    """
    if not analysis.youtube_comment_id:
        raise HTTPException(422, "This analysis is not about a comment on your YouTube channel.")
    if analysis.replied_id:
        raise HTTPException(409, f"Already replied: {analysis.replied_url}")
    text = youtube.publishable_text(analysis.reply)
    if not text:
        raise HTTPException(422, "There is no reply to post.")
    if output_blocked(text):
        logger.warning("Refused to post a reply on YouTube: it looks like a prompt injection")
        audit.record("output.blocked", detail="a reply for YouTube")
        raise HTTPException(422, "Not posted: the reply contains text that looks like instructions to an AI (possibly "
                                 "copied from someone else's comment). Edit it and try again.")
    video = re.search(r"[?&]v=([A-Za-z0-9_-]{6,20})", analysis.url)
    try:
        with youtube.as_channel(channel):
            posted = youtube.reply_to_comment(analysis.youtube_comment_id, text, video.group(1) if video else "")
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except youtube.YouTubeError as e:
        raise HTTPException(e.status_code, str(e)) from e
    analysis = analysis.model_copy(update={"replied_id": posted.id, "replied_url": posted.url, "replied_at": db.now(),
                                           "updated_at": db.now()})
    try:
        records.save_discussion(analysis)
    except OSError as e:  # DatabaseError
        raise HTTPException(500, f"Replied ({posted.url or 'on YouTube'}), but this could not be saved in the "
                                 "app.") from e
    return analysis
