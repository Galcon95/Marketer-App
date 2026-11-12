"""The author's own Facebook Page through Meta's Graph API: read posts and comments, publish a post, reply to a comment.

    page_info()                      the Page: name, followers, link
    list_posts(limit, after)         the Page's feed (its own posts and visitors' posts), newest first
    list_comments(post_id, ...)      a post's comments and replies, newest first
    recent_threads(posts)            the latest posts that have comments, with them (answered = the Page replied)
    open_items(posts)                what waits for an answer: visitors' unanswered comments and visitor posts
    publish_post(message, link)      a new post on the Page                      (writes)
    reply_to_comment(id, message)    a reply as the Page under a comment         (writes)
    comment_on_post(id, message)     a comment as the Page under a (visitor's) post (writes)

Only the Page in FACEBOOK_PAGE_ID, with its Page access token FACEBOOK_PAGE_TOKEN (server/.env; a Page token made from a
long-lived user token does not expire). The token goes in the Authorization header, never in a URL, and is never
logged; with FACEBOOK_APP_SECRET set every request also carries an appsecret_proof. The writing functions only run on
the author's decision (a button in the app, or "make it so" in Telegram): nothing here posts by itself.

Visitor posts are found in the Page's feed by their author (the visitor_posts edge needs more permissions than the
Page token has). Facebook keeps replies one level deep: a reply to a reply lands under the top comment, so a comment
counts as answered when the Page wrote in its thread at or after it.

Comments and visitor posts are other people's text: whoever passes them to a model quotes them as untrusted data
(guard.py).
Plain HTTP (httpx) next to the LangChain stack; no model call here.

Errors are FacebookError with the HTTP status the API should answer: 503 not configured / token invalid or missing a
permission, 404 unknown post or comment, 429 Facebook's rate limit, 502 any other Graph error, 504 timeout.
"""

import hashlib
import hmac
import logging
import re
from typing import Any

import httpx

from app.core import config
from app.core.schemas import (
    FacebookComment, FacebookComments, FacebookInboxItem, FacebookPage, FacebookPost, FacebookPosts, FacebookPublished,
    FacebookThread,
)

logger = logging.getLogger(__name__)

TIMEOUT = 20  # seconds per Graph request
MAX_MESSAGE = 63206  # Facebook's limit for a post or comment
MAX_LIMIT = 100  # items per request
_ID = re.compile(r"^\d+(_\d+)?$")  # Graph object ids: "123" or "123_456"

POST_FIELDS = "id,message,created_time,from{id,name},permalink_url,full_picture,comments.summary(true).limit(0)"
COMMENT_FIELDS = "id,message,created_time,from{id,name},parent{id},comment_count,permalink_url"

# Graph error codes → our status (https://developers.facebook.com/docs/graph-api/guides/error-handling)
_TOKEN_CODES = {102, 190}  # session or token invalid / expired
_PERMISSION_CODES = {3, 10} | set(range(200, 300))  # app or token lacks a permission
_RATE_CODES = {4, 17, 32, 613, 80001}  # app, user or Page rate limit
_NOT_FOUND_CODES = {100, 803}  # unknown object or bad parameter


class FacebookError(Exception):
    """A Facebook request failed; status_code is the HTTP status the API should return."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


def is_configured() -> bool:
    """True if a Page and its token are set in the configuration."""
    return bool(config.FACEBOOK_PAGE_ID and config.FACEBOOK_PAGE_TOKEN)


def page_info() -> FacebookPage:
    """The configured Page's name, followers and link."""
    data = _request("GET", config.FACEBOOK_PAGE_ID, {"fields": "id,name,followers_count,fan_count,link"})
    return FacebookPage(id=data["id"], name=data.get("name", ""),
                        followers=data.get("followers_count", data.get("fan_count")), link=data.get("link"))


def list_posts(limit: int = 10, after: str | None = None) -> FacebookPosts:
    """The Page's feed, newest first: its own posts and posts visitors wrote on it, with comment counts.

    Args:
        limit: Posts per page (1-100).
        after: The `after` of the previous page, for the next one.
    """
    data = _request("GET", f"{config.FACEBOOK_PAGE_ID}/feed", _paging(limit, after, fields=POST_FIELDS))
    return FacebookPosts(items=[_post(p) for p in data.get("data", [])], after=_after(data))


def list_comments(post_id: str, limit: int = 25, after: str | None = None) -> FacebookComments:
    """A post's comments including replies to comments, newest first.

    Args:
        post_id: The post ("<page id>_<post id>").
        limit: Comments per page (1-100).
        after: The `after` of the previous page, for the next one.
    """
    _check_id(post_id, "post")
    params = _paging(limit, after, fields=COMMENT_FIELDS, filter="stream", order="reverse_chronological")
    data = _request("GET", f"{post_id}/comments", params)
    return FacebookComments(items=[_comment(c, post_id) for c in data.get("data", [])], after=_after(data))


def recent_threads(posts: int = 10) -> list[FacebookThread]:
    """The Page's latest posts that have comments, each with its comments (up to MAX_LIMIT, newest first). A comment
    is `answered` when the Page has replied under it. One request for the posts, one per post with comments.

    Args:
        posts: How many of the latest posts to look at (1-25).
    """
    threads = []
    for post in list_posts(limit=max(1, min(posts, 25))).items:
        if not post.comment_count:
            continue
        comments = _mark_answered(list_comments(post.id, limit=MAX_LIMIT).items)
        threads.append(FacebookThread(post=post, comments=comments))
    return threads


def open_items(posts: int = 10) -> list[FacebookInboxItem]:
    """What on the Page waits for an answer, oldest first: visitors' comments the Page has not answered in their
    thread, and visitor posts the Page has not commented on. Items without text (a sticker, a photo) are left out.

    Args:
        posts: How many of the latest posts to look at (1-25).
    """
    items = []
    for post in list_posts(limit=max(1, min(posts, 25))).items:
        comments = _mark_answered(list_comments(post.id, limit=MAX_LIMIT).items) if post.comment_count else []
        page_commented = any(c.from_page and not c.parent_id for c in comments)
        if not post.from_page and post.message.strip() and not page_commented:
            items.append(FacebookInboxItem(
                kind="visitor_post", id=post.id, reply_to=post.id, post=post, message=post.message,
                author=post.author, created_time=post.created_time, permalink_url=post.permalink_url))
        for c in comments:
            if not c.from_page and not c.answered and c.message.strip():
                items.append(FacebookInboxItem(
                    kind="comment", id=c.id, reply_to=c.parent_id or c.id, post=post, message=c.message,
                    author=c.author, created_time=c.created_time, permalink_url=c.permalink_url))
    return sorted(items, key=lambda i: i.created_time)


def publish_post(message: str, link: str | None = None) -> FacebookPublished:
    """Publish a text post (optionally with a link preview) on the Page. Only on the author's click.

    Raises:
        ValueError: If the message is empty or too long, or the link is not an http(s) URL.
    """
    body: dict[str, Any] = {"message": _check_message(message)}
    if link:
        link = link.strip()
        if not re.match(r"^https?://\S+$", link):
            raise ValueError("The link must be an http(s) URL.")
        body["link"] = link
    data = _request("POST", f"{config.FACEBOOK_PAGE_ID}/feed", data=body)
    return FacebookPublished(id=data["id"], url=f"https://www.facebook.com/{data['id']}")


def reply_to_comment(comment_id: str, message: str) -> FacebookPublished:
    """Reply as the Page under a comment. Only on the author's click.

    Raises:
        ValueError: If the comment id is invalid or the message is empty or too long.
    """
    _check_id(comment_id, "comment")
    data = _request("POST", f"{comment_id}/comments", data={"message": _check_message(message)})
    return FacebookPublished(id=data["id"], url=f"https://www.facebook.com/{data['id']}")


def comment_on_post(post_id: str, message: str) -> FacebookPublished:
    """Comment as the Page under a post (a visitor's post on the Page). Only on the author's decision.

    Raises:
        ValueError: If the post id is invalid or the message is empty or too long.
    """
    _check_id(post_id, "post")
    data = _request("POST", f"{post_id}/comments", data={"message": _check_message(message)})
    return FacebookPublished(id=data["id"], url=f"https://www.facebook.com/{data['id']}")


def publishable_text(text: str) -> str:
    """A generated text as it is posted: the [n] citation markers removed, no space left before punctuation (like
    cleanText in the client)."""
    text = re.sub(r"[ \t]*\[\d+\]", "", text)
    return re.sub(r"[ \t]+([.,;:!?])", r"\1", text).strip()


# ---------- helpers ----------
def _client() -> httpx.Client:
    """The HTTP client for Graph requests (tests replace it with one on a fake transport)."""
    return httpx.Client(base_url=f"https://graph.facebook.com/{config.FACEBOOK_GRAPH_VERSION}/", timeout=TIMEOUT)


def _request(method: str, path: str, params: dict[str, Any] | None = None,
             data: dict[str, Any] | None = None) -> dict[str, Any]:
    """One Graph request with the Page token; the JSON answer, or FacebookError."""
    if not is_configured():
        raise FacebookError(503, "Facebook is not connected: set FACEBOOK_PAGE_ID and FACEBOOK_PAGE_TOKEN in "
                                 "server/.env and restart the server.")
    token = config.FACEBOOK_PAGE_TOKEN
    params = dict(params or {})
    if config.FACEBOOK_APP_SECRET:
        params["appsecret_proof"] = hmac.new(config.FACEBOOK_APP_SECRET.encode(), token.encode(),
                                             hashlib.sha256).hexdigest()
    try:
        with _client() as client:
            response = client.request(method, path, params=params, data=data,
                                      headers={"Authorization": f"Bearer {token}"})
    except httpx.TimeoutException as e:
        raise FacebookError(504, "Facebook did not answer in time. Try again.") from e
    except httpx.HTTPError as e:  # no str(e): keep request details out of messages
        logger.warning("Facebook request %s /%s failed: %s", method, path, type(e).__name__)
        raise FacebookError(502, "Could not reach Facebook. Try again.") from e
    try:
        body = response.json()
    except ValueError:
        body = {}
    if response.is_success and "error" not in body:
        return body
    raise _error(body.get("error") or {}, response.status_code, method, path)


def _error(error: dict[str, Any], http_status: int, method: str, path: str) -> FacebookError:
    """FacebookError for a Graph error answer, with a status and a message the author can act on."""
    code, message = error.get("code"), error.get("message") or f"HTTP {http_status}"
    logger.warning("Facebook %s /%s: Graph error %s (%s): %s", method, path, code, error.get("type"), message)
    if code in _TOKEN_CODES:
        return FacebookError(503, "The Facebook Page token is invalid or expired: create a new one (see "
                                  "server/.env.example) and restart the server.")
    if code in _PERMISSION_CODES:
        return FacebookError(503, f"The Facebook token lacks a permission for this: {message}")
    if code in _RATE_CODES:
        return FacebookError(429, "Facebook's rate limit is reached. Try again in a few minutes.")
    if code in _NOT_FOUND_CODES:
        return FacebookError(404, f"Facebook could not find this post or comment: {message}")
    return FacebookError(502, f"Facebook answered with an error: {message}")


def _paging(limit: int, after: str | None, **params: Any) -> dict[str, Any]:
    """Query parameters for one page of a list."""
    params["limit"] = max(1, min(limit, MAX_LIMIT))
    if after:
        params["after"] = after
    return params


def _after(data: dict[str, Any]) -> str | None:
    """The cursor of the next page, or None when this is the last one."""
    paging = data.get("paging") or {}
    return (paging.get("cursors") or {}).get("after") if paging.get("next") else None


def _post(p: dict[str, Any]) -> FacebookPost:
    """A Graph post as FacebookPost. Without `from` (Facebook left it out) the post counts as the Page's own, so an
    unknown author is never treated as a visitor waiting for an answer."""
    author = p.get("from") or {}
    return FacebookPost(
        id=p["id"], message=p.get("message", ""), created_time=p["created_time"],
        permalink_url=p.get("permalink_url"), picture=p.get("full_picture"),
        comment_count=((p.get("comments") or {}).get("summary") or {}).get("total_count", 0),
        author=author.get("name"), from_page=not author or author.get("id") == config.FACEBOOK_PAGE_ID,
    )


def _comment(c: dict[str, Any], post_id: str) -> FacebookComment:
    """A Graph comment as FacebookComment; `author` is None when Facebook leaves out who wrote it."""
    author = c.get("from") or {}
    return FacebookComment(
        id=c["id"], post_id=post_id, message=c.get("message", ""), created_time=c["created_time"],
        author=author.get("name"), from_page=author.get("id") == config.FACEBOOK_PAGE_ID,
        parent_id=(c.get("parent") or {}).get("id"), reply_count=c.get("comment_count", 0),
        permalink_url=c.get("permalink_url"),
    )


def _mark_answered(comments: list[FacebookComment]) -> list[FacebookComment]:
    """The comments with `answered` set: a visitor's comment is answered when the Page wrote in its thread (a reply
    under the top comment) at or after it. Replies to replies land under the top comment, so a visitor's follow-up
    after the Page's reply is open again."""
    page_replies: dict[str, list] = {}
    for c in comments:
        if c.from_page and c.parent_id:
            page_replies.setdefault(c.parent_id, []).append(c.created_time)
    return [c.model_copy(update={"answered": not c.from_page and any(
        t >= c.created_time for t in page_replies.get(c.parent_id or c.id, []))}) for c in comments]


def _check_id(value: str, what: str) -> None:
    """Reject anything but a Graph id, so no other path can be built from it."""
    if not _ID.match(value or ""):
        raise ValueError(f"Invalid Facebook {what} id.")


def _check_message(message: str) -> str:
    """The message stripped; ValueError if it is empty or longer than Facebook allows."""
    message = (message or "").strip()
    if not message:
        raise ValueError("The text is empty.")
    if len(message) > MAX_MESSAGE:
        raise ValueError(f"The text is too long for Facebook (at most {MAX_MESSAGE:,} characters).")
    return message
