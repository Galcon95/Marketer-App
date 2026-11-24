"""The author's own Substack publication, read from its public RSS feed (https://<name>.substack.com/feed): the latest
posts with title, date, link, subtitle and the start of the text. Substack has no API for reading or posting; the feed
needs no login.

    publication_name(address)   "name" from "name", "name.substack.com", a link to it or to a post, or the profile
                                link substack.com/@name (a profile's publication has the same name)
    latest_posts(name, limit)   the newest posts (cached for CACHE_SECONDS)

Safety: only https://<name>.substack.com is requested (the name is checked), at most MAX_FEED_BYTES are read, a
publication on its own domain may redirect (at most MAX_REDIRECTS, https only), and the XML is parsed without entities
from the outside (Python's expat does not load them; its limits stop entity expansion attacks). The texts are the
author's own posts but come from the web: they are cleaned (guard.clean_text) and HTML is removed.

Plain HTTP (httpx) next to the LangChain stack; no model call here. Errors are SubstackError with the HTTP status the API
should answer: 404 no such publication, 502 feed unreadable or Substack failing, 504 timeout.
"""

import html
import logging
import re
import threading
import time
import xml.etree.ElementTree as ET
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime

import httpx

from app.core.guard import clean_text
from app.core.schemas import SubstackPost

logger = logging.getLogger(__name__)

TIMEOUT = 15  # seconds for the feed
MAX_FEED_BYTES = 3_000_000
MAX_REDIRECTS = 3
CACHE_SECONDS = 600  # a feed is read again after 10 minutes
MAX_POSTS = 20
EXCERPT_CHARS = 300
USER_AGENT = "Mozilla/5.0 (compatible; marketer-app feed reader)"
CONTENT = "{http://purl.org/rss/1.0/modules/content/}encoded"
_NAME = re.compile(r"^[a-z0-9][a-z0-9-]{0,62}$")  # a publication's name: its subdomain on substack.com

_lock = threading.Lock()
_cache: dict[str, tuple[float, list[SubstackPost]]] = {}


class SubstackError(Exception):
    """The feed cannot be read; carries the HTTP status the API should return."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


def publication_name(address: str) -> str:
    """The publication's name from what the author typed.

    Raises:
        ValueError: If it is no Substack publication address (e.g. a custom domain or a note link).
    """
    text = address.strip().lower()
    text = re.sub(r"^https?://", "", text).split("?")[0].split("#")[0].strip("/")
    if match := re.match(r"^(?:www\.)?substack\.com/@([a-z0-9][a-z0-9-]*)$", text):
        name = match.group(1)
    elif match := re.match(r"^open\.substack\.com/pub/([a-z0-9][a-z0-9-]*)(/.*)?$", text):
        name = match.group(1)
    else:
        name = text.split("/")[0].removesuffix(".substack.com")
    if not _NAME.match(name) or name in ("www", "open", "substack"):
        raise ValueError("Give your Substack publication's address, e.g. yourname.substack.com (or your profile link "
                         "substack.com/@yourname).")
    return name


def feed_url(name: str) -> str:
    return f"https://{name}.substack.com/feed"


def latest_posts(name: str, limit: int = 10) -> list[SubstackPost]:
    """The publication's newest posts, newest first.

    Raises:
        ValueError: If the name is not a publication name.
        SubstackError: 404 if there is no such publication, 502 if the feed cannot be read, 504 on a timeout.
    """
    if not _NAME.match(name):
        raise ValueError("Not a Substack publication name.")
    now = time.monotonic()
    with _lock:
        cached = _cache.get(name)
    if cached and now - cached[0] < CACHE_SECONDS:
        return cached[1][:limit]
    posts = parse_feed(_download(feed_url(name)))[:MAX_POSTS]
    with _lock:
        _cache[name] = (now, posts)
    return posts[:limit]


def parse_feed(data: bytes) -> list[SubstackPost]:
    """The posts of an RSS feed, newest first.

    Raises:
        SubstackError: 502 if it is no RSS feed.
    """
    try:
        root = ET.fromstring(data)
    except ET.ParseError as e:
        raise SubstackError(502, "The Substack feed could not be read.") from e
    posts = []
    for item in root.findall("./channel/item"):
        url = (item.findtext("link") or "").strip()
        if not url.startswith("https://"):
            continue
        body = _plain(item.findtext(CONTENT) or "")
        posts.append(SubstackPost(
            title=clean_text(item.findtext("title") or "").strip() or "(untitled)", url=url,
            published_at=_date(item.findtext("pubDate")), subtitle=_plain(item.findtext("description") or ""),
            excerpt=body[:EXCERPT_CHARS].rstrip() + ("…" if len(body) > EXCERPT_CHARS else "")))
    epoch = datetime.min.replace(tzinfo=timezone.utc)
    return sorted(posts, key=lambda p: p.published_at or epoch, reverse=True)


# ---------- helpers ----------
def _client() -> httpx.Client:
    """The HTTP client for the feed (tests replace it with one on a fake transport)."""
    return httpx.Client(timeout=TIMEOUT, follow_redirects=False, headers={"User-Agent": USER_AGENT})


def _download(url: str) -> bytes:
    """The feed's bytes (redirects followed by hand: https only, at most MAX_REDIRECTS, at most MAX_FEED_BYTES)."""
    try:
        with _client() as client:
            for _ in range(MAX_REDIRECTS + 1):
                with client.stream("GET", url) as response:
                    if response.is_redirect:
                        target = response.headers.get("location", "")
                        url = str(response.url.join(target))
                        if not url.startswith("https://"):
                            raise SubstackError(502, "The Substack feed redirects somewhere unsafe.")
                        continue
                    if response.status_code == 404:
                        raise SubstackError(404, "There is no Substack publication at this address.")
                    if not response.is_success:
                        logger.warning("Substack feed answered HTTP %s", response.status_code)
                        raise SubstackError(502, f"Substack answered with HTTP {response.status_code}.")
                    data = b""
                    for chunk in response.iter_bytes():
                        data += chunk
                        if len(data) > MAX_FEED_BYTES:
                            raise SubstackError(502, "The Substack feed is too large.")
                    return data
    except httpx.TimeoutException as e:
        raise SubstackError(504, "Substack did not answer in time. Try again.") from e
    except httpx.HTTPError as e:
        logger.warning("Substack feed failed: %s", type(e).__name__)
        raise SubstackError(502, "Could not reach Substack. Try again.") from e
    raise SubstackError(502, "The Substack feed redirects too often.")


def _plain(markup: str) -> str:
    """Text from HTML: tags removed, entities decoded, whitespace collapsed, cleaned."""
    text = re.sub(r"<(script|style)\b.*?</\1>", " ", markup, flags=re.S | re.I)
    text = re.sub(r"<[^>]+>", " ", text)
    return re.sub(r"\s+", " ", clean_text(html.unescape(text))).strip()


def _date(value: str | None) -> datetime | None:
    try:
        return parsedate_to_datetime(value) if value else None
    except (TypeError, ValueError):
        return None
