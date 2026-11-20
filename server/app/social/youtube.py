"""A YouTube channel through the YouTube Data API v3: read the comments under its videos, reply to a comment.

    channel_info()                    the channel: name, subscribers, link
    recent_threads(comments)          the latest comment threads on the channel's videos, grouped by video
                                      (answered = the channel replied)
    open_items(comments)              what waits for an answer: viewers' comments the channel has not answered
    list_replies(comment_id)          all replies under a top comment
    recent_videos(limit)              the channel's latest uploads with title, description and comment count
    video_transcript(video_id)        what is said in one of the channel's videos, from its captions
    reply_to_comment(id, message)     a reply as the channel under a comment          (writes)
    comment_on_video(id, message)     a new top comment as the channel under a video  (writes)

Which channel: the one set with `as_channel(channel)` for the current request (a user's own channel, connected with
Google sign-in). There is no channel in server/.env: without `as_channel` every call answers 503. The access token
(short-lived, made from the user's refresh token by the connection code) goes in the Authorization header, never in a
URL, and is never logged. reply_to_comment and comment_on_video only run on the author's decision: nothing here
posts by itself.

YouTube threads are two levels deep: a top comment and the replies under it (a reply to a reply also hangs under the
top comment). A comment counts as answered when the channel wrote in its thread at or after it.

Quota: the API gives a project 10,000 units a day. Reading costs 1 unit per request (recent_threads: one for the
threads, one for the video titles, one more for each thread with more replies than YouTube includes; recent_videos:
three); a reply or a new comment costs 50; video_transcript 250 (50 to list the captions, 200 to download one).

Comments are other people's text: whoever passes them to a model quotes them as untrusted data (guard.py).
Plain HTTP (httpx) next to the LangChain stack; no model call here.

Errors are YouTubeError with the HTTP status the API should answer: 503 not connected / token invalid or missing a
permission, 404 unknown video or comment, 429 quota or rate limit, 502 any other API error, 504 timeout.
"""

import logging
import re
from collections.abc import Iterator
from contextlib import contextmanager
from contextvars import ContextVar
from dataclasses import dataclass, field
from typing import Any

import httpx

from app.core.schemas import (YouTubeChannel, YouTubeComment, YouTubeInboxItem, YouTubePublished, YouTubeThread,
                              YouTubeUpload, YouTubeVideo)

logger = logging.getLogger(__name__)

API_URL = "https://www.googleapis.com/youtube/v3/"
TIMEOUT = 20  # seconds per request
MAX_MESSAGE = 10000  # YouTube's limit for a comment
MAX_LIMIT = 100  # items per request (videos: 50)
_ID = re.compile(r"^[A-Za-z0-9_-]{10,64}(\.[A-Za-z0-9_-]{5,64})?$")  # a comment id, or "<top comment>.<reply>"
_VIDEO_ID = re.compile(r"^[A-Za-z0-9_-]{11}$")

# `reason` of an API error → our status (https://developers.google.com/youtube/v3/docs/errors)
_QUOTA_REASONS = {"quotaExceeded", "dailyLimitExceeded"}
_RATE_REASONS = {"rateLimitExceeded", "userRateLimitExceeded"}
_PERMISSION_REASONS = {"forbidden", "insufficientPermissions", "channelForbidden"}


@dataclass(frozen=True)
class ChannelAccess:
    """A channel and an access token for it (never shown in logs or reprs)."""

    channel_id: str
    token: str = field(repr=False)


_channel: ContextVar[ChannelAccess | None] = ContextVar("youtube_channel", default=None)


@contextmanager
def as_channel(channel: ChannelAccess) -> Iterator[ChannelAccess]:
    """Every call in the block works on this channel."""
    reset = _channel.set(channel)
    try:
        yield channel
    finally:
        _channel.reset(reset)


class YouTubeError(Exception):
    """A YouTube request failed; status_code is the HTTP status the API should return."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


def is_configured() -> bool:
    """True if there is a channel to work on (inside as_channel)."""
    return _channel.get() is not None


def channel_info() -> YouTubeChannel:
    """The channel's name, subscribers and link."""
    data = _request("GET", "channels", {"part": "snippet,statistics", "id": _channel_id()})
    items = data.get("items") or []
    if not items:
        raise YouTubeError(404, "YouTube could not find the channel.")
    snippet, stats = items[0].get("snippet") or {}, items[0].get("statistics") or {}
    handle = snippet.get("customUrl")  # "@name"
    subscribers = None if stats.get("hiddenSubscriberCount") else _int(stats.get("subscriberCount"))
    return YouTubeChannel(
        id=items[0]["id"], name=snippet.get("title", ""), subscribers=subscribers,
        link=f"https://www.youtube.com/{handle}" if handle else f"https://www.youtube.com/channel/{items[0]['id']}")


def my_channel(token: str) -> YouTubeChannel:
    """The channel of the Google account (or brand account) a fresh access token belongs to (after Google sign-in).

    Raises:
        YouTubeError: 404 if the account has no YouTube channel.
    """
    with as_channel(ChannelAccess("", token)):
        data = _request("GET", "channels", {"part": "snippet", "mine": "true"})
    items = data.get("items") or []
    if not items:
        raise YouTubeError(404, "This Google account has no YouTube channel. If your channel belongs to a brand "
                                "account, connect again and pick the channel itself (not your personal account) "
                                "when Google asks which account to use.")
    snippet = items[0].get("snippet") or {}
    handle = snippet.get("customUrl")
    return YouTubeChannel(
        id=items[0]["id"], name=snippet.get("title", ""),
        link=f"https://www.youtube.com/{handle}" if handle else f"https://www.youtube.com/channel/{items[0]['id']}")


def recent_threads(comments: int = 50) -> list[YouTubeThread]:
    """The latest comment threads on all videos of the channel, grouped by video (the video with the newest comment
    first; within a video newest first, replies included). A comment is `answered` when the channel has replied in
    its thread at or after it.

    Args:
        comments: How many of the latest threads (top comments) to look at (1-100).
    """
    data = _request("GET", "commentThreads", {
        "part": "snippet,replies", "allThreadsRelatedToChannelId": _channel_id(), "order": "time",
        "maxResults": max(1, min(comments, MAX_LIMIT)), "textFormat": "plainText"})
    by_video: dict[str, list[YouTubeComment]] = {}
    for item in data.get("items", []):
        snippet = item.get("snippet") or {}
        top_raw = snippet.get("topLevelComment") or {}
        if not top_raw.get("id"):
            continue
        video_id = snippet.get("videoId") or (top_raw.get("snippet") or {}).get("videoId") or ""
        total = snippet.get("totalReplyCount", 0)
        replies_raw = (item.get("replies") or {}).get("comments", [])
        if total > len(replies_raw):  # YouTube includes only some of the replies: fetch them all
            replies = list_replies(top_raw["id"], video_id)
        else:
            replies = [_comment(r, video_id) for r in replies_raw]
        top = _comment(top_raw, video_id).model_copy(update={"reply_count": total})
        by_video.setdefault(video_id, []).extend(_mark_answered([top, *replies]))
    videos = _videos([v for v in by_video if v])
    return [YouTubeThread(video=videos.get(video_id) or _video(video_id, {}),
                          comments=sorted(items, key=lambda c: c.created_time, reverse=True))
            for video_id, items in by_video.items()]


def open_items(comments: int = 50) -> list[YouTubeInboxItem]:
    """What under the channel's videos waits for an answer, oldest first: viewers' comments the channel has not
    answered in their thread (recent_threads). Comments without text are left out. A follow-up inside a thread comes
    with the thread before it.

    Args:
        comments: How many of the latest comment threads to look at (1-100).
    """
    items = []
    for thread in recent_threads(comments):
        for c in thread.comments:
            if c.from_channel or c.answered or not c.message.strip():
                continue
            top = c.parent_id or c.id
            earlier = sorted((o for o in thread.comments if c.parent_id and o.id != c.id
                              and (o.id == top or o.parent_id == top) and o.created_time <= c.created_time),
                             key=lambda o: o.created_time)
            items.append(YouTubeInboxItem(
                id=c.id, reply_to=top, video=thread.video, message=c.message, author=c.author,
                created_time=c.created_time, permalink_url=c.permalink_url, thread=earlier))
    return sorted(items, key=lambda i: i.created_time)


def list_replies(comment_id: str, video_id: str = "") -> list[YouTubeComment]:
    """The replies under a top comment (up to MAX_LIMIT).

    Args:
        comment_id: The top comment.
        video_id: The video it is under (for the replies' links).
    """
    _check_id(comment_id)
    data = _request("GET", "comments", {"part": "snippet", "parentId": _top(comment_id), "maxResults": MAX_LIMIT,
                                        "textFormat": "plainText"})
    return [_comment(r, video_id) for r in data.get("items", [])]


def recent_videos(limit: int = 10) -> list[YouTubeUpload]:
    """The channel's latest uploads, newest first, with title, description and comment count (three reads: the
    uploads playlist, its latest items, the videos). Videos YouTube does not return (private, deleted) are left out.

    Args:
        limit: How many of the latest uploads (1-50).
    """
    data = _request("GET", "channels", {"part": "contentDetails", "id": _channel_id()})
    items = data.get("items") or []
    uploads = (((items[0].get("contentDetails") or {}).get("relatedPlaylists") or {}).get("uploads")
               if items else None)
    if not uploads:
        raise YouTubeError(404, "YouTube could not find the channel's uploads.")
    data = _request("GET", "playlistItems", {"part": "contentDetails", "playlistId": uploads,
                                             "maxResults": max(1, min(limit, 50))})
    ids = [i["contentDetails"]["videoId"] for i in data.get("items", []) if (i.get("contentDetails") or {}).get(
        "videoId")]
    if not ids:
        return []
    data = _request("GET", "videos", {"part": "snippet,statistics", "id": ",".join(ids), "maxResults": 50})
    videos = []
    for v in data.get("items", []):
        snippet, stats = v.get("snippet") or {}, v.get("statistics") or {}
        if not snippet.get("publishedAt"):
            continue
        videos.append(YouTubeUpload(**_video(v["id"], snippet).model_dump(), description=snippet.get("description", ""),
                                    published_at=snippet["publishedAt"], comment_count=_int(stats.get("commentCount"))))
    return sorted(videos, key=lambda v: v.published_at, reverse=True)


def video_transcript(video_id: str, max_chars: int = 20000) -> str:
    """What is said in one of the channel's own videos, as plain text from its captions: a track the author uploaded
    is preferred over YouTube's automatic one. "" when the video has no captions. Costs 250 quota units (only the
    channel's owner may download captions).

    Raises:
        ValueError: If the video id is invalid.
        YouTubeError: If the captions cannot be listed or downloaded (e.g. YouTube refuses an automatic track).
    """
    _check_video(video_id)
    data = _request("GET", "captions", {"part": "snippet", "videoId": video_id})
    tracks = [t for t in data.get("items", []) if t.get("id")
              and (t.get("snippet") or {}).get("status", "serving") == "serving"]
    if not tracks:
        return ""
    tracks.sort(key=lambda t: (t.get("snippet") or {}).get("trackKind", "").lower() == "asr")  # uploaded first
    srt = _request("GET", f"captions/{tracks[0]['id']}", {"tfmt": "srt"}, text=True)
    return srt_text(srt)[:max_chars]


def srt_text(srt: str) -> str:
    """The spoken text of an SRT caption file: numbers, timings, markup and sound notes ("[music]") removed, lines
    joined, and the repeated lines of automatic captions (each line shown again in the next cue) dropped."""
    words: list[str] = []
    for line in srt.splitlines():
        line = re.sub(r"\s+", " ", re.sub(r"<[^>]+>|\[[^\]]*\]", "", line)).strip()
        if not line or line.isdigit() or "-->" in line:
            continue
        if words and words[-1] == line:
            continue
        words.append(line)
    return " ".join(words)


def comment_on_video(video_id: str, message: str) -> YouTubePublished:
    """A new top comment as the channel under one of its videos. Only on the author's decision. Costs 50 quota
    units.

    Raises:
        ValueError: If the video id is invalid or the message is empty or too long.
        YouTubeError: 404 if the video is unknown or its comments are turned off.
    """
    _check_video(video_id)
    body = {"snippet": {"videoId": video_id, "topLevelComment": {"snippet": {"textOriginal": _check_message(message)}}}}
    data = _request("POST", "commentThreads", {"part": "snippet"}, json=body)
    return YouTubePublished(id=data["id"], url=_comment_url(video_id, data["id"]) or "")


def reply_to_comment(comment_id: str, message: str, video_id: str = "") -> YouTubePublished:
    """Reply as the channel under a comment (under its top comment, where YouTube keeps all replies). Only on the
    author's click. Costs 50 quota units.

    Args:
        comment_id: The comment to answer (a top comment or a reply).
        message: The reply.
        video_id: The video the comment is under (for the reply's link).

    Raises:
        ValueError: If the comment id is invalid or the message is empty or too long.
    """
    _check_id(comment_id)
    body = {"snippet": {"parentId": _top(comment_id), "textOriginal": _check_message(message)}}
    data = _request("POST", "comments", {"part": "snippet"}, json=body)
    video_id = (data.get("snippet") or {}).get("videoId") or video_id
    return YouTubePublished(id=data["id"], url=_comment_url(video_id, data["id"]) or "")


def publishable_text(text: str) -> str:
    """A generated text as it is posted: the [n] citation markers removed, no space left before punctuation (like
    facebook.publishable_text)."""
    text = re.sub(r"[ \t]*\[\d+\]", "", text)
    return re.sub(r"[ \t]+([.,;:!?])", r"\1", text).strip()


# ---------- helpers ----------
def _client() -> httpx.Client:
    """The HTTP client for API requests (tests replace it with one on a fake transport)."""
    return httpx.Client(base_url=API_URL, timeout=TIMEOUT)


def _request(method: str, path: str, params: dict[str, Any] | None = None,
             json: dict[str, Any] | None = None, text: bool = False) -> Any:
    """One API request with the channel's access token; the JSON answer (`text`: the answer as text, e.g. a caption
    file), or YouTubeError."""
    channel = _channel.get()
    if not channel:
        raise YouTubeError(503, "No YouTube channel is connected: connect yours under Integrations → YouTube channel.")
    try:
        with _client() as client:
            response = client.request(method, path, params=params, json=json,
                                      headers={"Authorization": f"Bearer {channel.token}"})
    except httpx.TimeoutException as e:
        raise YouTubeError(504, "YouTube did not answer in time. Try again.") from e
    except httpx.HTTPError as e:  # no str(e): keep request details out of messages
        logger.warning("YouTube request %s /%s failed: %s", method, path, type(e).__name__)
        raise YouTubeError(502, "Could not reach YouTube. Try again.") from e
    if text and response.is_success:
        return response.text
    try:
        body = response.json()
    except ValueError:
        body = {}
    if not isinstance(body, dict):
        body = {}
    if response.is_success and "error" not in body:
        return body
    raise _error(body.get("error"), response.status_code, method, path)


def _error(error: Any, http_status: int, method: str, path: str) -> YouTubeError:
    """YouTubeError for an API error answer, with a status and a message the author can act on."""
    error = error if isinstance(error, dict) else {}
    message = error.get("message") or f"HTTP {http_status}"
    details = error.get("errors") or [{}]
    reason = details[0].get("reason", "") if isinstance(details[0], dict) else ""
    logger.warning("YouTube %s /%s: API error %s (%s): %s", method, path, http_status, reason, message)
    if http_status == 401 or reason == "authError":
        return YouTubeError(503, "YouTube no longer accepts the connection to your channel (e.g. you removed the "
                                 "app's access): connect it again under Integrations → YouTube channel.")
    if reason in _QUOTA_REASONS:
        return YouTubeError(429, "Today's YouTube API quota is used up. It resets at midnight Pacific Time.")
    if reason in _RATE_REASONS or http_status == 429:
        return YouTubeError(429, "YouTube's rate limit is reached. Try again in a few minutes.")
    if reason == "commentsDisabled":
        return YouTubeError(404, "Comments are turned off for this video.")
    if http_status == 404 or reason.endswith("NotFound"):
        return YouTubeError(404, f"YouTube could not find this video or comment: {message}")
    if reason in _PERMISSION_REASONS or http_status == 403:
        return YouTubeError(503, f"The YouTube connection lacks a permission for this: {message}")
    return YouTubeError(502, f"YouTube answered with an error: {message}")


def _channel_id() -> str:
    """Id of the current channel ("" if there is none; _request refuses then)."""
    channel = _channel.get()
    return channel.channel_id if channel else ""


def _videos(video_ids: list[str]) -> dict[str, YouTubeVideo]:
    """The videos by id (title, link, thumbnail); 50 per request. A video YouTube does not return is left out."""
    videos: dict[str, YouTubeVideo] = {}
    for start in range(0, len(video_ids), 50):
        data = _request("GET", "videos", {"part": "snippet", "id": ",".join(video_ids[start:start + 50]),
                                          "maxResults": 50})
        for v in data.get("items", []):
            videos[v["id"]] = _video(v["id"], v.get("snippet") or {})
    return videos


def _video(video_id: str, snippet: dict[str, Any]) -> YouTubeVideo:
    """An API video snippet as YouTubeVideo."""
    thumbnails = snippet.get("thumbnails") or {}
    thumbnail = (thumbnails.get("medium") or thumbnails.get("default") or {}).get("url")
    return YouTubeVideo(id=video_id, title=snippet.get("title", ""),
                        url=f"https://www.youtube.com/watch?v={video_id}", thumbnail=thumbnail)


def _comment(c: dict[str, Any], video_id: str) -> YouTubeComment:
    """An API comment as YouTubeComment."""
    snippet = c.get("snippet") or {}
    video_id = snippet.get("videoId") or video_id
    return YouTubeComment(
        id=c["id"], video_id=video_id, message=snippet.get("textOriginal") or snippet.get("textDisplay") or "",
        created_time=snippet["publishedAt"], author=snippet.get("authorDisplayName") or None,
        from_channel=(snippet.get("authorChannelId") or {}).get("value") == _channel_id(),
        parent_id=snippet.get("parentId"), permalink_url=_comment_url(video_id, c["id"]),
    )


def _comment_url(video_id: str, comment_id: str) -> str | None:
    """The link that opens the video with this comment on top (None without the video)."""
    return f"https://www.youtube.com/watch?v={video_id}&lc={comment_id}" if video_id else None


def _mark_answered(thread: list[YouTubeComment]) -> list[YouTubeComment]:
    """One thread (a top comment and its replies) with `answered` set: a viewer's comment is answered when the
    channel replied in the thread at or after it. A viewer's follow-up after the channel's last reply is open again."""
    channel_replies = [c.created_time for c in thread if c.from_channel and c.parent_id]
    return [c.model_copy(update={"answered": not c.from_channel and any(t >= c.created_time for t in channel_replies)})
            for c in thread]


def _top(comment_id: str) -> str:
    """The top comment of a comment's thread (a reply's id starts with it)."""
    return comment_id.split(".", 1)[0]


def _int(value: Any) -> int | None:
    """The API's numbers come as strings."""
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _check_id(value: str) -> None:
    """Reject anything but a comment id."""
    if not _ID.match(value or ""):
        raise ValueError("Invalid YouTube comment id.")


def _check_video(video_id: str) -> None:
    """Reject anything but a video id."""
    if not _VIDEO_ID.match(video_id or ""):
        raise ValueError("Invalid YouTube video id.")


def _check_message(message: str) -> str:
    """The message stripped; ValueError if it is empty or longer than YouTube allows."""
    message = (message or "").strip()
    if not message:
        raise ValueError("The text is empty.")
    if len(message) > MAX_MESSAGE:
        raise ValueError(f"The text is too long for YouTube (at most {MAX_MESSAGE:,} characters).")
    return message
