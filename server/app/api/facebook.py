"""The user's own Facebook Page (social/facebook.py): connecting it, its status, publishing a generated post and
replying to comments.

    GET    /facebook/status                    is a Page connected? its name and followers, where it comes from
    POST   /facebook/connect                   start Facebook Login: the URL to send the browser to
    GET    /facebook/oauth/callback            Facebook sends the browser back here (no sign-in token: signed state)
    GET    /facebook/connect/pages             after a login with several Pages: the Pages to choose from
    POST   /facebook/connect/pages/{page_id}   connect one of them
    DELETE /facebook/connection                forget the user's Page
    GET    /facebook/comments                  the latest posts that have comments, with them (for the agent)
    POST   /assets/{id}/publish/facebook       publish a generated post on the Page (on the author's click)
    POST   /ad-images/{id}/publish/facebook    post an ad picture with a caption on the Page (on the click)
    POST   /discussions/{id}/reply/facebook    post an analysis's reply as the Page under the comment (on the click)

Every user works on their own Page, connected with Facebook Login (social/page_connections.py); the admin without one
works on the Page in server/.env. Nobody else ever reaches the admin's Page: without a Page of their own, reading and
posting answer 503. An asset is published once, a reply posted once; the id, link and time are saved with it.
"""

import logging
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import RedirectResponse

from app.api.deps import owned_ad_image, owned_asset, owned_discussion
from app.core import ad_images
from app.core import state as db
from app.core.auth import User, current_user
from app.core.guard import output_blocked, scan_third_party
from app.core.schemas import (AdImage, AdImagePublishRequest, Asset, DiscussionAnalysis, FacebookConnectRequest, FacebookLoginUrl, FacebookPageChoice,
                              FacebookStatus, FacebookThread)
from app.db import records
from app.social import facebook, page_connections
from app.social.page_connections import LoginError

logger = logging.getLogger(__name__)

router = APIRouter()
callback_router = APIRouter()  # included without sign-in: Facebook redirects the browser, the state names the user


def page_of(user: User = Depends(current_user)) -> facebook.PageAccess:
    """FastAPI dependency: the Page this user works on (their own; the admin's from server/.env for the admin).

    Raises:
        HTTPException: 503 if the user has no Page (connect one first) or the database cannot be read.
    """
    try:
        page, _ = page_connections.page_for(user)
    except OSError as e:  # DatabaseError
        raise HTTPException(503, "Your Facebook connection cannot be read right now, please try again.") from e
    if not page:
        raise HTTPException(503, "No Facebook Page connected: connect yours under Integrations → Facebook Page.")
    return page

# Asset types that are posts for a Page: reader questions always, social posts written for Facebook.
PUBLISHABLE = {"reader_question", "social_post"}


@router.get("/facebook/status", response_model=FacebookStatus)
def status(user: User = Depends(current_user)):
    """Whether the user has a Facebook Page and it is reachable, with its name and followers; `source` says whether
    the user connected it ("user") or it is the admin's Page in server/.env ("server"); `login_available` whether the
    user can connect one.

    Never fails: no Page or an unreachable one is reported in the answer (connected false, error).
    """
    login = page_connections.login_available()
    try:
        page, source = page_connections.page_for(user)
    except OSError:  # DatabaseError
        return FacebookStatus(connected=False, error="Your Facebook connection cannot be read right now.",
                              login_available=login)
    if not page:
        return FacebookStatus(connected=False, login_available=login)
    try:
        with facebook.as_page(page):
            return FacebookStatus(connected=True, page=facebook.page_info(), source=source, login_available=login)
    except facebook.FacebookError as e:
        return FacebookStatus(connected=False, error=str(e), source=source, login_available=login)


@router.post("/facebook/connect", response_model=FacebookLoginUrl)
def connect(body: FacebookConnectRequest, user: User = Depends(current_user)):
    """Start Facebook Login: the URL of Facebook's dialog, where the user picks their Page and allows the app to read
    and post on it. Facebook then sends the browser to GET /facebook/oauth/callback.

    Raises:
        HTTPException: 503 if Facebook Login is not set up on the server; 422 if return_to is not the client's origin.
    """
    if not page_connections.login_available():
        raise HTTPException(503, "Facebook Login is not set up on the server (FACEBOOK_APP_ID, FACEBOOK_APP_SECRET, "
                                 "TOKEN_ENCRYPTION_KEY in server/.env).")
    try:
        return FacebookLoginUrl(url=page_connections.login_url(user.id, body.return_to))
    except LoginError as e:
        raise HTTPException(422, str(e)) from e


@callback_router.get("/facebook/oauth/callback", include_in_schema=False)
def oauth_callback(state: str = "", code: str = "", error: str = ""):
    """Facebook sends the browser here after the login dialog. Connects the Page (or keeps several for the user's
    choice) and sends the browser back to the app with ?facebook=connected|choose|cancelled|error (and a message).
    A forged, expired or replayed state is refused without a redirect to an address from the request."""
    try:
        user_id, return_to = page_connections.read_state(state)
    except LoginError as e:
        raise HTTPException(400, str(e)) from e
    if error or not code:  # the user cancelled or refused the permissions
        return _back(return_to, "cancelled")
    try:
        result = page_connections.finish_login(code, user_id)
    except LoginError as e:
        return _back(return_to, "error", str(e))
    except OSError:  # DatabaseError
        return _back(return_to, "error", "The connection could not be saved. Try again.")
    return _back(return_to, result)


def _back(return_to: str, result: str, message: str = "") -> RedirectResponse:
    """Redirect to the app (an allowed origin from the verified state) with the login's result."""
    query = urlencode({"facebook": result, **({"message": message} if message else {})})
    return RedirectResponse(f"{return_to}/?{query}", status_code=303)


@router.get("/facebook/connect/pages", response_model=list[FacebookPageChoice])
def pages_to_choose(user: User = Depends(current_user)):
    """The Pages to choose from after a login that found several (empty after 10 minutes or once one was chosen)."""
    return page_connections.choices(user.id)


@router.post("/facebook/connect/pages/{page_id}", response_model=FacebookStatus)
def choose_page(page_id: str, user: User = Depends(current_user)):
    """Connect one of the Pages found by the last login.

    Raises:
        HTTPException: 409 if no such Page is waiting (connect again); 503 if it cannot be saved.
    """
    try:
        page_connections.choose(user.id, page_id)
    except LoginError as e:
        raise HTTPException(409, str(e)) from e
    except OSError as e:  # DatabaseError
        raise HTTPException(503, "The connection could not be saved. Try again.") from e
    return status(user)


@router.delete("/facebook/connection", status_code=204)
def disconnect(user: User = Depends(current_user)):
    """Forget the user's Page: its token is deleted from the app. (Facebook still lists the app under the user's
    Business integrations until they remove it there.)

    Raises:
        HTTPException: 503 if the database cannot be written.
    """
    try:
        page_connections.disconnect(user.id)
    except OSError as e:  # DatabaseError
        raise HTTPException(503, "Could not disconnect right now, please try again.") from e


@router.post("/assets/{asset_id}/publish/facebook", response_model=Asset)
def publish(asset: Asset = Depends(owned_asset), page: facebook.PageAccess = Depends(page_of)):
    """Publish the asset's text (without citation markers) as a post on the author's Facebook Page.

    Args:
        asset_id: Id of the asset (path parameter): a reader question, or a social post written for Facebook.

    Returns:
        The asset with published_id, published_url and published_at set.

    Raises:
        HTTPException: 404 when no asset of the user has this id; 409 if it was published already; 422 if it is
            not a Facebook post or its text is empty or too long; 503 if the user has no Page or its token is
            invalid; 429, 502 or 504 if Facebook fails; 500 if it was
            published but the record could not be saved; 422 also if the text looks like a prompt injection got
            into it (output guard).
    """
    if asset.asset_type not in PUBLISHABLE or asset.platform != "facebook":
        raise HTTPException(422, "Only reader questions and social posts written for Facebook can be published to "
                                 "the Page.")
    if asset.published_id:
        raise HTTPException(409, f"Already published: {asset.published_url}")
    text = facebook.publishable_text(asset.text)
    _refuse_injection(text, "post")
    try:
        with facebook.as_page(page):
            post = facebook.publish_post(text)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except facebook.FacebookError as e:
        raise HTTPException(e.status_code, str(e)) from e
    asset = asset.model_copy(update={"published_id": post.id, "published_url": post.url, "published_at": db.now()})
    db.assets[asset.id] = asset  # before saving: even if the save fails, a second click is refused (409)
    try:
        records.save_assets([asset])
    except OSError as e:  # DatabaseError
        raise HTTPException(500, f"Published ({post.url}), but this could not be saved in the app.") from e
    return asset


@router.post("/ad-images/{image_id}/publish/facebook", response_model=AdImage)
def publish_picture(body: AdImagePublishRequest, image: AdImage = Depends(owned_ad_image),
                    page: facebook.PageAccess = Depends(page_of)):
    """Post an ad picture with a caption (the author's, e.g. the ad copy's text) as a photo post on the author's
    Facebook Page. Once per picture.

    Args:
        image_id: Id of the picture (path parameter).
        body: The caption; citation markers are removed like in a published post.

    Returns:
        The picture's record with published_id, published_url and published_at set.

    Raises:
        HTTPException: 404 when no picture of the user has this id or its file is missing; 409 if it was posted
            already; 422 if the caption is empty, too long or looks like a prompt injection got into it; 503 if the
            user has no Page or its token is invalid, or Storage cannot be reached; 429, 502 or 504 if Facebook
            fails; 500 if it was posted but the record could not be saved.
    """
    if image.published_id:
        raise HTTPException(409, f"Already posted: {image.published_url}")
    text = facebook.publishable_text(body.message)
    _refuse_injection(text, "caption")
    try:
        png = ad_images.picture(image)
    except OSError as e:  # FileStoreError
        raise HTTPException(503, "The file storage cannot be reached, please try again.") from e
    if png is None:
        raise HTTPException(404, "The file of this picture is missing")
    try:
        with facebook.as_page(page):
            post = facebook.publish_photo(text, png)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except facebook.FacebookError as e:
        raise HTTPException(e.status_code, str(e)) from e
    image = image.model_copy(update={"published_id": post.id, "published_url": post.url, "published_at": db.now()})
    try:
        records.save_ad_image(image)
    except OSError as e:  # DatabaseError
        raise HTTPException(500, f"Posted ({post.url}), but this could not be saved in the app.") from e
    return image


@router.get("/facebook/comments", response_model=list[FacebookThread])
def comments(posts: int = Query(default=10, ge=1, le=25), page: facebook.PageAccess = Depends(page_of)):
    """The latest posts on the Page that have comments, each with its comments, newest first. A comment is
    `answered` when the Page has replied under it. The comments are other people's text: shown to the author, and
    given to the agent only through POST /discussions (guard, quoted as data).

    Args:
        posts: How many of the latest posts to look at (1-25, default 10).

    Raises:
        HTTPException: 503 if the user has no Page or its token is invalid; 429, 502 or 504 if Facebook fails.
    """
    try:
        with facebook.as_page(page):
            threads = facebook.recent_threads(posts)
    except facebook.FacebookError as e:
        raise HTTPException(e.status_code, str(e)) from e
    return [_scanned(thread) for thread in threads]


def _scanned(thread: FacebookThread) -> FacebookThread:
    """The thread with every reader's comment checked for prompt injection (flagged for the GUI, not removed; the
    Page's own replies are the author's and are not scanned)."""
    comments = []
    for c in thread.comments:
        if not c.from_page and c.message:
            risk, findings = scan_third_party(c.message)
            c = c.model_copy(update={"injection_risk": risk, "injection_findings": findings})
        comments.append(c)
    return thread.model_copy(update={"comments": comments})


def _refuse_injection(text: str, what: str) -> None:
    """Output guard before anything is posted: refuse a text in which a prompt injection seems to have got through
    (guard.output_blocked), e.g. a reply that repeats a planted "ignore your instructions" line."""
    if output_blocked(text):
        logger.warning("Refused to post a %s on Facebook: it looks like a prompt injection", what)
        raise HTTPException(422, f"Not posted: the {what} contains text that looks like instructions to an AI "
                                 "(possibly copied from someone else's comment). Edit it and try again.")


@router.post("/discussions/{discussion_id}/reply/facebook", response_model=DiscussionAnalysis)
def reply(analysis: DiscussionAnalysis = Depends(owned_discussion), page: facebook.PageAccess = Depends(page_of)):
    """Post the analysis's reply (as the author edited it, without citation markers) as the Page under the comment it
    answers.

    Args:
        discussion_id: Id of an analysis made from a comment on the Page (path parameter).

    Returns:
        The analysis with replied_id, replied_url and replied_at set.

    Raises:
        HTTPException: 404 when no analysis of the user has this id; 409 if the reply was posted already; 422 if
            the analysis is not about a comment on the Page or has no reply; 503 if the user has no Page or its
            token is invalid; 404, 429, 502 or 504 if Facebook fails (404: the
            comment was deleted); 500 if it was posted but the record could not be saved; 422 also if the reply
            looks like a prompt injection got into it (output guard).
    """
    if not analysis.facebook_comment_id:
        raise HTTPException(422, "This analysis is not about a comment on your Facebook Page.")
    if analysis.replied_id:
        raise HTTPException(409, f"Already replied: {analysis.replied_url}")
    text = facebook.publishable_text(analysis.reply)
    if not text:
        raise HTTPException(422, "There is no reply to post.")
    _refuse_injection(text, "reply")
    try:
        with facebook.as_page(page):
            posted = facebook.reply_to_comment(analysis.facebook_comment_id, text)
    except ValueError as e:
        raise HTTPException(422, str(e)) from e
    except facebook.FacebookError as e:
        raise HTTPException(e.status_code, str(e)) from e
    analysis = analysis.model_copy(update={"replied_id": posted.id, "replied_url": posted.url, "replied_at": db.now(),
                                           "updated_at": db.now()})
    try:
        records.save_discussion(analysis)
    except OSError as e:  # DatabaseError
        raise HTTPException(500, f"Replied ({posted.url}), but this could not be saved in the app.") from e
    return analysis
