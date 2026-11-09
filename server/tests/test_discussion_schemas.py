"""Schemas of the Discussion Relevance Agent (step 1): the API request and result, and the structured outputs the
model fills in. No model calls."""

from datetime import datetime, timezone

import pytest
from pydantic import ValidationError

from app.agents.discussion import Assessment, DraftReply
from app.core.guard import validate_input
from app.core.schemas import BookMention, DiscussionAnalysis, DiscussionRequest, DiscussionUpdate

POST = "How could AI help a city council decide where to build new housing?"


# ---------- DiscussionRequest ----------
def test_request_defaults():
    req = DiscussionRequest(source_id="src_1", discussion=POST)
    assert (req.url, req.platform, req.angle) == ("", "forum", "")


def test_request_needs_book_and_text():
    with pytest.raises(ValidationError):
        DiscussionRequest(source_id="", discussion=POST)
    with pytest.raises(ValidationError):
        DiscussionRequest(source_id="src_1", discussion="")


def test_request_takes_a_post_with_replies_up_to_8000_characters():
    DiscussionRequest(source_id="src_1", discussion="x" * 8000)
    with pytest.raises(ValidationError):
        DiscussionRequest(source_id="src_1", discussion="x" * 8001)


@pytest.mark.parametrize("url", ["https://www.reddit.com/r/urbanplanning/comments/abc", "http://forum.example.org/t/1",
                                 "  https://www.linkedin.com/feed/update/1  "])
def test_request_accepts_web_urls(url):
    assert DiscussionRequest(source_id="src_1", discussion=POST, url=url).url == url.strip()


@pytest.mark.parametrize("url", ["javascript:alert(1)", "www.reddit.com/r/x", "ftp://example.org/file"])
def test_request_rejects_other_urls(url):
    with pytest.raises(ValidationError, match="http"):
        DiscussionRequest(source_id="src_1", discussion=POST, url=url)


def test_request_rejects_unknown_platform():
    with pytest.raises(ValidationError):
        DiscussionRequest(source_id="src_1", discussion=POST, platform="myspace")


def test_guard_allows_8000_characters_for_a_discussion():
    assert validate_input("x" * 8000, "discussion").ok
    assert not validate_input("x" * 8001, "discussion").ok


# ---------- DiscussionAnalysis / DiscussionUpdate ----------
def test_analysis_minimal_skip_result():
    now = datetime.now(timezone.utc)
    result = DiscussionAnalysis(id="dsc_1", project_id="p", source_id="src_1", discussion=POST, recommendation="skip",
                                reason="The book is about gardening.", created_at=now, updated_at=now)
    assert result.suggested_reply == "" and result.book_mention is None and result.citations == []
    assert result.edited is False


def test_analysis_round_trips_through_json():
    now = datetime.now(timezone.utc)
    result = DiscussionAnalysis(id="dsc_1", project_id="p", source_id="src_1", discussion=POST,
                                recommendation="contribute", reason="Chapter 3 covers this [1].",
                                suggested_reply="One approach ... [1]", reply="One approach ... [1]",
                                book_mention=BookMention(suggest=False, reason="Nobody asked for reading."),
                                created_at=now, updated_at=now)
    assert DiscussionAnalysis.model_validate_json(result.model_dump_json()) == result


def test_update_needs_text():
    with pytest.raises(ValidationError):
        DiscussionUpdate(reply="")


# ---------- Structured outputs ----------
def test_assessment_more_context_must_say_what_is_missing():
    with pytest.raises(ValidationError, match="missing_context"):
        Assessment(recommendation="more_context", reason="Only replies were pasted.")
    ok = Assessment(recommendation="more_context", reason="Only replies were pasted.",
                    missing_context="Copy the original post.")
    assert ok.missing_context == "Copy the original post."


def test_assessment_drops_missing_context_otherwise():
    result = Assessment(recommendation="contribute", reason="Fits chapter 3 [1].", missing_context="something",
                        used_sources=[1])
    assert result.missing_context == ""


def test_assessment_rejects_unknown_recommendation():
    with pytest.raises(ValidationError):
        Assessment(recommendation="maybe", reason="Not sure.")


def test_draft_reply_must_use_passages():
    with pytest.raises(ValidationError):
        DraftReply(reply="A reply.", used_sources=[], mention_book=False, mention_reason="Not asked.")
    draft = DraftReply(reply="A reply [1].", used_sources=[1], mention_book=True, mention_reason="They asked for books.")
    assert draft.mention_book
