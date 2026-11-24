"""The author's own Substack (social/substack.py, api/substack.py): which addresses are accepted, how the RSS feed
becomes posts, the safety limits of the download, and the API (set, read, forget, only for the owner). The feed is
faked with an httpx MockTransport; nothing leaves the machine."""

import httpx
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import substack as substack_api
from app.core import state as db
from app.db import records
from app.social import substack
from tests.conftest import STRANGER, sign_in

PROJECT = db.DEFAULT_PROJECT_ID
NAME = "peterschmidt983145"

FEED = b"""<?xml version="1.0" encoding="UTF-8"?>
<rss xmlns:content="http://purl.org/rss/1.0/modules/content/" version="2.0">
<channel><title>Peter Schmidt</title>
<item><title><![CDATA[Where the people go?]]></title>
<description><![CDATA[Life in a Civilization Where Industry No Longer Needs Mass Labor]]></description>
<link>https://peterschmidt983145.substack.com/p/where-the-people-go</link>
<pubDate>Sun, 27 Sep 2026 03:59:16 GMT</pubDate>
<content:encoded><![CDATA[<p>When machines do the work, <b>where</b> do people go?</p><script>alert(1)</script><p>A&amp;B.</p>]]></content:encoded>
</item>
<item><title>A Future Too Large to Build Alone</title>
<description>Why long-term survival points toward humans and AI together.</description>
<link>https://peterschmidt983145.substack.com/p/a-future-too-large-to-build-alone</link>
<pubDate>Sun, 27 Sep 2026 14:27:30 GMT</pubDate>
<content:encoded><![CDATA[<p>""" + b"word " * 200 + b"""</p>]]></content:encoded>
</item>
<item><title>Not a post</title><link>javascript:alert(1)</link></item>
</channel></rss>"""


# ---------- addresses ----------
@pytest.mark.parametrize("address", [
    NAME, f"{NAME}.substack.com", f"https://{NAME}.substack.com/", f"https://{NAME}.substack.com/p/where-the-people-go",
    f"https://substack.com/@{NAME}", f"https://open.substack.com/pub/{NAME}/p/x", f"  HTTPS://{NAME.upper()}.SUBSTACK.COM  ",
])
def test_publication_addresses_give_the_name(address):
    assert substack.publication_name(address) == NAME


@pytest.mark.parametrize("address", ["https://example.com", "substack.com", "www.substack.com", "no spaces here",
                                     "https://substack.com/@name/note/c-1", "-dash.substack.com", "under_score.substack.com"])
def test_other_addresses_are_refused(address):
    with pytest.raises(ValueError):
        substack.publication_name(address)


# ---------- the feed ----------
def test_the_feed_becomes_posts_newest_first_as_plain_text():
    posts = substack.parse_feed(FEED)
    assert [p.title for p in posts] == ["A Future Too Large to Build Alone", "Where the people go?"]  # by date
    people = posts[1]
    assert people.url == "https://peterschmidt983145.substack.com/p/where-the-people-go"
    assert people.subtitle == "Life in a Civilization Where Industry No Longer Needs Mass Labor"
    assert people.excerpt == "When machines do the work, where do people go? A&B."  # no tags, no script
    assert people.published_at.isoformat() == "2026-09-27T03:59:16+00:00"
    assert len(posts[0].excerpt) <= substack.EXCERPT_CHARS + 1 and posts[0].excerpt.endswith("…")


def test_no_rss_is_a_502():
    with pytest.raises(substack.SubstackError) as e:
        substack.parse_feed(b"<html><body>not a feed")
    assert e.value.status_code == 502


@pytest.fixture
def feed(monkeypatch):
    """The feed's web server, faked: `feed.answer(request)` returns the response; requests are in `feed.requests`."""
    class Fake:
        requests: list[httpx.Request] = []
        answer = staticmethod(lambda request: httpx.Response(200, content=FEED))

    fake = Fake()
    fake.requests = []

    def handler(request):
        fake.requests.append(request)
        return fake.answer(request)
    monkeypatch.setattr(substack, "_client", lambda: httpx.Client(transport=httpx.MockTransport(handler),
                                                                   follow_redirects=False))
    monkeypatch.setattr(substack, "_cache", {})
    return fake


def test_latest_posts_reads_the_feed_once_then_from_the_cache(feed):
    assert [p.title for p in substack.latest_posts(NAME)][0] == "A Future Too Large to Build Alone"
    assert str(feed.requests[0].url) == f"https://{NAME}.substack.com/feed"
    assert len(substack.latest_posts(NAME, limit=1)) == 1 and len(feed.requests) == 1


def test_a_redirect_to_a_custom_domain_is_followed_but_only_https(feed):
    feed.answer = lambda r: (httpx.Response(301, headers={"location": "https://books.example.org/feed"})
                             if r.url.host.endswith("substack.com") else httpx.Response(200, content=FEED))
    assert len(substack.latest_posts(NAME)) == 2 and feed.requests[-1].url.host == "books.example.org"
    substack._cache.clear()
    feed.answer = lambda r: httpx.Response(302, headers={"location": "http://127.0.0.1/feed"})
    with pytest.raises(substack.SubstackError) as e:
        substack.latest_posts(NAME)
    assert e.value.status_code == 502


def test_endless_redirects_unknown_publications_and_huge_feeds_are_errors(feed, monkeypatch):
    feed.answer = lambda r: httpx.Response(301, headers={"location": f"https://{NAME}.substack.com/feed"})
    with pytest.raises(substack.SubstackError):
        substack.latest_posts(NAME)
    feed.answer = lambda r: httpx.Response(404)
    with pytest.raises(substack.SubstackError) as e:
        substack.latest_posts(NAME)
    assert e.value.status_code == 404
    monkeypatch.setattr(substack, "MAX_FEED_BYTES", 100)
    feed.answer = lambda r: httpx.Response(200, content=FEED)
    with pytest.raises(substack.SubstackError) as e:
        substack.latest_posts(NAME)
    assert "too large" in str(e.value)


# ---------- API ----------
@pytest.fixture
def client(monkeypatch):
    calls = []

    def latest(name, limit=10):
        calls.append(name)
        if name == "nobody":
            raise substack.SubstackError(404, "There is no Substack publication at this address.")
        return substack.parse_feed(FEED)
    monkeypatch.setattr(substack, "latest_posts", latest)
    app = FastAPI()
    app.include_router(substack_api.router)
    sign_in(app)
    with TestClient(app) as test_client:
        test_client.calls = calls
        yield test_client


def test_without_a_publication_the_feed_is_empty(client):
    assert client.get(f"/projects/{PROJECT}/substack").json() == {"publication": "", "url": "", "posts": []}
    assert client.calls == []


def test_setting_the_publication_saves_it_and_returns_its_posts(client):
    r = client.put(f"/projects/{PROJECT}/substack", json={"address": f"https://substack.com/@{NAME}"})
    assert r.status_code == 200, r.text
    assert r.json()["publication"] == NAME and r.json()["url"] == f"https://{NAME}.substack.com"
    assert len(r.json()["posts"]) == 2
    assert db.projects[PROJECT].substack == NAME and records.load_projects()[PROJECT].substack == NAME
    assert client.get(f"/projects/{PROJECT}/substack").json()["publication"] == NAME
    assert client.delete(f"/projects/{PROJECT}/substack").status_code == 204
    assert records.load_projects()[PROJECT].substack == ""


def test_a_wrong_address_or_a_missing_publication_is_refused_and_nothing_saved(client):
    assert client.put(f"/projects/{PROJECT}/substack", json={"address": "https://example.com"}).status_code == 422
    r = client.put(f"/projects/{PROJECT}/substack", json={"address": "nobody.substack.com"})
    assert r.status_code == 422 and "nobody.substack.com" in r.json()["detail"]
    assert db.projects[PROJECT].substack == ""


def test_another_user_reaches_no_ones_substack(client):
    sign_in(client.app, STRANGER)
    assert client.get(f"/projects/{PROJECT}/substack").status_code == 404
    assert client.put(f"/projects/{PROJECT}/substack", json={"address": NAME}).status_code == 404
    assert client.delete(f"/projects/{PROJECT}/substack").status_code == 404
