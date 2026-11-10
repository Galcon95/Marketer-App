"""Facebook API (api/facebook.py) and the "Question for my readers" format: admin only, status, publishing a
generated post once, the Page's comments, replying to a comment as the Page once, and how both are recorded. The
Facebook client is faked; nothing is posted."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import facebook as fb_api
from app.core import accounts
from app.core import state as db
from app.core.schemas import (
    Asset, DiscussionAnalysis, DiscussionRequest, FacebookComment, FacebookPage, FacebookPost, FacebookPublished,
    FacebookThread, GenerateRequest, Source,
)
from app.db import records
from app.rag import generation
from app.social import facebook
from tests.conftest import OWNER, STRANGER, sign_in

PROJECT = db.DEFAULT_PROJECT_ID
NOW = datetime(2026, 11, 10, tzinfo=timezone.utc)


def _asset(asset_id="ast_q1", asset_type="reader_question", platform="facebook", **extra) -> Asset:
    return Asset(id=asset_id, project_id=PROJECT, asset_type=asset_type, grounded=True, brief="b", platform=platform,
                 text="Machines may run cities one day [1]. Who should answer for their mistakes [2] ?", citations=[],
                 created_at=NOW, **extra)


@pytest.fixture
def published(monkeypatch):
    """Admin = OWNER, Facebook configured; publish_post is recorded instead of sent."""
    monkeypatch.setattr(accounts, "DEFAULT_CLIENT_OWNER", OWNER.email)
    monkeypatch.setattr(facebook, "is_configured", lambda: True)
    monkeypatch.setattr(db, "assets", {})
    sent: list[str] = []

    def fake_publish(message, link=None):
        sent.append(message)
        return FacebookPublished(id="123_456", url="https://www.facebook.com/123_456")

    monkeypatch.setattr(facebook, "publish_post", fake_publish)
    return sent


def _client(user=OWNER) -> TestClient:
    app = FastAPI()
    app.include_router(fb_api.router)
    sign_in(app, user)
    return TestClient(app)


def _store(asset: Asset) -> None:
    records.save_assets([asset])
    db.assets[asset.id] = asset


# ---------- publishing ----------
def test_publish_sends_the_text_without_markers_and_records_the_post(published):
    _store(_asset())
    r = _client().post("/assets/ast_q1/publish/facebook")
    assert r.status_code == 200, r.text
    assert published == ["Machines may run cities one day. Who should answer for their mistakes?"]
    body = r.json()
    assert body["published_id"] == "123_456" and body["published_url"] == "https://www.facebook.com/123_456"
    assert body["published_at"]
    assert records.load_assets()["ast_q1"].published_id == "123_456"  # saved in the database


def test_publish_twice_is_refused(published):
    _store(_asset())
    client = _client()
    assert client.post("/assets/ast_q1/publish/facebook").status_code == 200
    r = client.post("/assets/ast_q1/publish/facebook")
    assert r.status_code == 409 and len(published) == 1


@pytest.mark.parametrize("asset_type,platform", [("blurb", None), ("social_post", "linkedin"),
                                                 ("social_reply", "facebook")])
def test_only_facebook_posts_can_be_published(published, asset_type, platform):
    _store(_asset(asset_type=asset_type, platform=platform))
    assert _client().post("/assets/ast_q1/publish/facebook").status_code == 422
    assert published == []


def test_a_facebook_social_post_can_be_published(published):
    _store(_asset(asset_type="social_post"))
    assert _client().post("/assets/ast_q1/publish/facebook").status_code == 200


def test_facebook_errors_keep_their_status_and_nothing_is_recorded(published, monkeypatch):
    def failing(message, link=None):
        raise facebook.FacebookError(503, "The Facebook Page token is invalid or expired")

    monkeypatch.setattr(facebook, "publish_post", failing)
    _store(_asset())
    r = _client().post("/assets/ast_q1/publish/facebook")
    assert r.status_code == 503 and "expired" in r.json()["detail"]
    assert db.assets["ast_q1"].published_id == ""


def test_publish_is_for_the_admin_only(published):
    _store(_asset())
    assert _client(STRANGER).post("/assets/ast_q1/publish/facebook").status_code == 403
    assert _client(STRANGER).get("/facebook/status").status_code == 403
    assert published == []


def test_unknown_asset_is_404(published):
    assert _client().post("/assets/ast_nope/publish/facebook").status_code == 404


# ---------- status ----------
def test_status_not_configured(published, monkeypatch):
    monkeypatch.setattr(facebook, "is_configured", lambda: False)
    assert _client().get("/facebook/status").json() == {"connected": False, "page": None, "error": ""}


def test_status_connected_and_unreachable(published, monkeypatch):
    monkeypatch.setattr(facebook, "page_info", lambda: FacebookPage(id="1", name="HAIC", followers=3))
    body = _client().get("/facebook/status").json()
    assert body["connected"] and body["page"]["name"] == "HAIC"

    def expired():
        raise facebook.FacebookError(503, "token expired")

    monkeypatch.setattr(facebook, "page_info", expired)
    body = _client().get("/facebook/status").json()
    assert not body["connected"] and body["error"] == "token expired"


# ---------- the format ----------
def test_publishable_text_matches_the_clients_clean_text():
    assert facebook.publishable_text("A claim [1] , and more [12].\nNext [3]!") == "A claim, and more.\nNext!"


def test_reader_question_instructions_are_for_facebook_and_end_with_a_question():
    text = generation.build_instructions(GenerateRequest(asset_type="reader_question", brief="AI and accountability"))
    assert "Facebook Page" in text and "End with the question" in text
    assert "first person" in text and "never refer to the book in the third person" in text
    assert "{" not in text  # nothing left unfilled


# ---------- comments on the Page and "Reply as Page" ----------

def _analysis(comment_id="111_8", reply="Thanks! In chapter 3 I argue that people decide [1].", **extra):
    return DiscussionAnalysis(id="dsc_fb1", project_id=PROJECT, source_id="src_book", discussion="Comment",
                              platform="facebook", recommendation="contribute", reason="Fits.", reply=reply,
                              suggested_reply=reply, facebook_comment_id=comment_id, created_at=NOW, updated_at=NOW,
                              **extra)


@pytest.fixture
def replied(published, monkeypatch):
    """publish fixture plus a recorded reply_to_comment; the analysis's book exists so it can be saved."""
    records.add_source(Source(id="src_book", project_id=PROJECT, filename="b.pdf", kind="document", size_bytes=1,
                              status="ready", progress=100, chunk_count=1, created_at=NOW))
    sent: list[tuple[str, str]] = []

    def fake_reply(comment_id, message):
        sent.append((comment_id, message))
        return FacebookPublished(id=f"{comment_id}_99", url=f"https://www.facebook.com/{comment_id}_99")

    monkeypatch.setattr(facebook, "reply_to_comment", fake_reply)
    return sent


def test_reply_as_page_posts_the_reply_once(replied):
    records.save_discussion(_analysis())
    client = _client()
    r = client.post("/discussions/dsc_fb1/reply/facebook")
    assert r.status_code == 200, r.text
    assert replied == [("111_8", "Thanks! In chapter 3 I argue that people decide.")]
    assert r.json()["replied_url"] == "https://www.facebook.com/111_8_99"
    assert records.get_discussion("dsc_fb1").replied_id == "111_8_99"
    assert client.post("/discussions/dsc_fb1/reply/facebook").status_code == 409
    assert len(replied) == 1


@pytest.mark.parametrize("extra", [{"comment_id": ""}, {"reply": "  "}], ids=["not-a-page-comment", "no-reply"])
def test_reply_needs_a_page_comment_and_a_reply(replied, extra):
    records.save_discussion(_analysis(**extra))
    assert _client().post("/discussions/dsc_fb1/reply/facebook").status_code == 422
    assert replied == []


def test_reply_is_for_the_admin_only(replied):
    records.save_discussion(_analysis())
    assert _client(STRANGER).post("/discussions/dsc_fb1/reply/facebook").status_code == 403
    assert _client(STRANGER).get("/facebook/comments").status_code == 403
    assert replied == []


def test_comments_route_returns_threads(published, monkeypatch):
    post = FacebookPost(id="1_2", message="Who is accountable?", created_time=NOW, comment_count=1)
    comment = FacebookComment(id="2_3", post_id="1_2", message="The mayor!", created_time=NOW, author="Ana")
    monkeypatch.setattr(facebook, "recent_threads", lambda posts: [
        FacebookThread(post=post, comments=[comment])])
    body = _client().get("/facebook/comments?posts=5").json()
    assert body[0]["post"]["message"] == "Who is accountable?" and body[0]["comments"][0]["author"] == "Ana"
    assert _client().get("/facebook/comments?posts=99").status_code == 422


def test_a_page_comment_request_is_always_facebook():
    req = DiscussionRequest(source_id="b", discussion="x", platform="reddit", facebook_comment_id="111_8")
    assert req.platform == "facebook"
    with pytest.raises(ValueError):
        DiscussionRequest(source_id="b", discussion="x", facebook_comment_id="../me")
