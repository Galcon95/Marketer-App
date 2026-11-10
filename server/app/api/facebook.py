"""The author's own Facebook Page (social/facebook.py): connection status and publishing a generated post.

    GET  /facebook/status                    is the Page connected? its name and followers
    GET  /facebook/comments                  the latest posts that have comments, with them (for the agent)
    POST /assets/{id}/publish/facebook       publish a generated post on the Page (on the author's click)
    POST /discussions/{id}/reply/facebook    post an analysis's reply as the Page under the comment (on the click)

Admin only: the Page in server/.env belongs to the app's administrator (DEFAULT_CLIENT_OWNER), so no other user may
publish to it. An asset is published once, a reply posted once; the id, link and time are saved with it.
"""

from fastapi import APIRouter, Depends, HTTPException, Query

from app.api.deps import admin_only, owned_asset, owned_discussion
from app.core import state as db
from app.core.schemas import Asset, DiscussionAnalysis, FacebookStatus, FacebookThread
from app.db import records
from app.social import facebook

router = APIRouter(dependencies=[Depends(admin_only)])

# Asset types that are posts for a Page: reader questions always, social posts written for Facebook.
PUBLISHABLE = {"reader_question", "social_post"}


@router.get("/facebook/status", response_model=FacebookStatus)
def status():
    """Whether the Facebook Page is configured and reachable, with its name and followers.

    Never fails: a missing configuration or an unreachable Page is reported in the answer (connected false, error).
    """
    if not facebook.is_configured():
        return FacebookStatus(connected=False)
    try:
        return FacebookStatus(connected=True, page=facebook.page_info())
    except facebook.FacebookError as e:
        return FacebookStatus(connected=False, error=str(e))


@router.post("/assets/{asset_id}/publish/facebook", response_model=Asset)
def publish(asset: Asset = Depends(owned_asset)):
    """Publish the asset's text (without citation markers) as a post on the author's Facebook Page.

    Args:
        asset_id: Id of the asset (path parameter): a reader question, or a social post written for Facebook.

    Returns:
        The asset with published_id, published_url and published_at set.

    Raises:
        HTTPException: 403 for anyone but the administrator; 404 when no asset of the user has this id; 409 if it
            was published already; 422 if it is not a Facebook post or its text is empty or too long; 503 if
            Facebook is not connected or the token is invalid; 429, 502 or 504 if Facebook fails; 500 if it was
            published but the record could not be saved.
    """
    if asset.asset_type not in PUBLISHABLE or asset.platform != "facebook":
        raise HTTPException(422, "Only reader questions and social posts written for Facebook can be published to "
                                 "the Page.")
    if asset.published_id:
        raise HTTPException(409, f"Already published: {asset.published_url}")
    try:
        post = facebook.publish_post(facebook.publishable_text(asset.text))
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


@router.get("/facebook/comments", response_model=list[FacebookThread])
def comments(posts: int = Query(default=10, ge=1, le=25)):
    """The latest posts on the Page that have comments, each with its comments, newest first. A comment is
    `answered` when the Page has replied under it. The comments are other people's text: shown to the author, and
    given to the agent only through POST /discussions (guard, quoted as data).

    Args:
        posts: How many of the latest posts to look at (1-25, default 10).

    Raises:
        HTTPException: 403 for anyone but the administrator; 503 if Facebook is not connected or the token is
            invalid; 429, 502 or 504 if Facebook fails.
    """
    try:
        return facebook.recent_threads(posts)
    except facebook.FacebookError as e:
        raise HTTPException(e.status_code, str(e)) from e


@router.post("/discussions/{discussion_id}/reply/facebook", response_model=DiscussionAnalysis)
def reply(analysis: DiscussionAnalysis = Depends(owned_discussion)):
    """Post the analysis's reply (as the author edited it, without citation markers) as the Page under the comment it
    answers.

    Args:
        discussion_id: Id of an analysis made from a comment on the Page (path parameter).

    Returns:
        The analysis with replied_id, replied_url and replied_at set.

    Raises:
        HTTPException: 403 for anyone but the administrator; 404 when no analysis of the user has this id; 409 if the
            reply was posted already; 422 if the analysis is not about a comment on the Page or has no reply; 503 if
            Facebook is not connected or the token is invalid; 404, 429, 502 or 504 if Facebook fails (404: the
            comment was deleted); 500 if it was posted but the record could not be saved.
    """
    if not analysis.facebook_comment_id:
        raise HTTPException(422, "This analysis is not about a comment on your Facebook Page.")
    if analysis.replied_id:
        raise HTTPException(409, f"Already replied: {analysis.replied_url}")
    text = facebook.publishable_text(analysis.reply)
    if not text:
        raise HTTPException(422, "There is no reply to post.")
    try:
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
