"""Facebook Page client (social/facebook.py): requests it sends, how Graph answers become posts and comments, input
checks and error mapping. The Graph API is faked with an httpx MockTransport; nothing leaves the machine."""

import hashlib
import hmac
import json

import httpx
import pytest

from app.core import config
from app.social import facebook as fb

PAGE = "1343718638826573"
TOKEN = "page-token-123"
POST = f"{PAGE}_111"


@pytest.fixture
def graph(monkeypatch):
    """Configure a Page and route Graph requests to a fake. Set `graph.answer` (dict, or (status, dict)); the requests
    sent are in `graph.requests`."""
    monkeypatch.setattr(config, "FACEBOOK_PAGE_ID", PAGE)
    monkeypatch.setattr(config, "FACEBOOK_PAGE_TOKEN", TOKEN)
    monkeypatch.setattr(config, "FACEBOOK_APP_SECRET", "")
    monkeypatch.setattr(config, "FACEBOOK_GRAPH_VERSION", "v27.0")

    class Fake:
        answer: object = {}
        requests: list[httpx.Request] = []
        error: Exception | None = None

    fake = Fake()
    fake.requests = []

    def handler(request: httpx.Request) -> httpx.Response:
        fake.requests.append(request)
        if fake.error:
            raise fake.error
        status, body = fake.answer if isinstance(fake.answer, tuple) else (200, fake.answer)
        return httpx.Response(status, json=body)

    monkeypatch.setattr(fb, "_client", lambda: httpx.Client(
        base_url="https://graph.facebook.com/v27.0/", transport=httpx.MockTransport(handler)))
    return fake


def _form(request: httpx.Request) -> dict[str, str]:
    return dict(httpx.QueryParams(request.content.decode()))


# ---------- configuration and token handling ----------
def test_not_configured_is_503_without_a_request(monkeypatch):
    monkeypatch.setattr(config, "FACEBOOK_PAGE_ID", "")
    monkeypatch.setattr(config, "FACEBOOK_PAGE_TOKEN", "")
    assert not fb.is_configured()
    with pytest.raises(fb.FacebookError) as e:
        fb.list_posts()
    assert e.value.status_code == 503


def test_token_goes_in_the_header_not_the_url(graph):
    graph.answer = {"data": []}
    fb.list_posts()
    request = graph.requests[0]
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(request.url)
    assert "appsecret_proof" not in request.url.params


def test_appsecret_proof_when_the_secret_is_set(graph, monkeypatch):
    monkeypatch.setattr(config, "FACEBOOK_APP_SECRET", "s3cret")
    graph.answer = {"data": []}
    fb.list_posts()
    expected = hmac.new(b"s3cret", TOKEN.encode(), hashlib.sha256).hexdigest()
    assert graph.requests[0].url.params["appsecret_proof"] == expected


# ---------- reading ----------
def test_page_info(graph):
    graph.answer = {"id": PAGE, "name": "The Human-AI Civilization - HAIC", "followers_count": 3,
                    "link": "https://www.facebook.com/haic"}
    page = fb.page_info()
    assert (page.name, page.followers) == ("The Human-AI Civilization - HAIC", 3)
    assert graph.requests[0].url.path == f"/v27.0/{PAGE}"


def test_list_posts_parses_posts_and_paging(graph):
    graph.answer = {
        "data": [
            {"id": POST, "message": "Volume I: https://a.co/x", "created_time": "2026-09-30T10:00:00+0000",
             "permalink_url": "https://www.facebook.com/p/111", "comments": {"data": [], "summary": {"total_count": 4}}},
            {"id": f"{PAGE}_222", "created_time": "2026-10-09T08:00:00+0000", "full_picture": "https://img/x.jpg"},
        ],
        "paging": {"cursors": {"before": "B", "after": "A1"}, "next": "https://graph.facebook.com/...next"},
    }
    result = fb.list_posts(limit=2)
    first, second = result.items
    assert first.comment_count == 4 and first.message.startswith("Volume I")
    assert second.message == "" and second.picture == "https://img/x.jpg" and second.comment_count == 0
    assert result.after == "A1"
    params = graph.requests[0].url.params
    assert graph.requests[0].url.path == f"/v27.0/{PAGE}/feed" and params["limit"] == "2"


def test_last_page_has_no_after_and_limit_is_clamped(graph):
    graph.answer = {"data": [], "paging": {"cursors": {"after": "A1"}}}  # no "next": last page
    assert fb.list_posts(limit=500, after="A0").after is None
    params = graph.requests[0].url.params
    assert params["limit"] == "100" and params["after"] == "A0"


def test_list_comments_marks_page_replies_and_missing_names(graph):
    graph.answer = {"data": [
        {"id": "111_9", "message": "Thanks!", "created_time": "2026-10-10T09:00:00+0000",
         "from": {"id": PAGE, "name": "HAIC"}, "parent": {"id": "111_8"}},
        {"id": "111_8", "message": "Is the book about AI rights?", "created_time": "2026-10-10T08:00:00+0000",
         "from": {"id": "555", "name": "Ana"}, "comment_count": 1},
        {"id": "111_7", "message": "Nice", "created_time": "2026-10-09T08:00:00+0000"},
    ]}
    reply, question, anonymous = fb.list_comments(POST).items
    assert reply.from_page and reply.parent_id == "111_8" and reply.post_id == POST
    assert question.author == "Ana" and not question.from_page and question.reply_count == 1
    assert anonymous.author is None
    params = graph.requests[0].url.params
    assert params["filter"] == "stream" and params["order"] == "reverse_chronological"


@pytest.mark.parametrize("bad", ["", "abc", "1/../me", "123?x=1", "me"])
def test_invalid_ids_are_rejected_before_any_request(graph, bad):
    with pytest.raises(ValueError):
        fb.list_comments(bad)
    with pytest.raises(ValueError):
        fb.reply_to_comment(bad, "Hi")
    assert graph.requests == []


# ---------- writing ----------
def test_publish_post_with_link(graph):
    graph.answer = {"id": f"{PAGE}_333"}
    published = fb.publish_post("  A question for readers?  ", link="https://a.co/d/00VkqwD2")
    request = graph.requests[0]
    assert request.method == "POST" and request.url.path == f"/v27.0/{PAGE}/feed"
    assert _form(request) == {"message": "A question for readers?", "link": "https://a.co/d/00VkqwD2"}
    assert published.url == f"https://www.facebook.com/{PAGE}_333"


@pytest.mark.parametrize("message,link", [("", None), ("   ", None), ("x" * (fb.MAX_MESSAGE + 1), None),
                                          ("Hi", "javascript:alert(1)"), ("Hi", "a.co/x")],
                         ids=["empty", "blank", "too-long", "js-link", "no-scheme"])
def test_publish_post_rejects_bad_input(graph, message, link):
    with pytest.raises(ValueError):
        fb.publish_post(message, link=link)
    assert graph.requests == []


def test_reply_to_comment(graph):
    graph.answer = {"id": "111_8_99"}
    published = fb.reply_to_comment("111_8", "Yes, chapter 3 is about that.")
    request = graph.requests[0]
    assert request.method == "POST" and request.url.path == "/v27.0/111_8/comments"
    assert _form(request) == {"message": "Yes, chapter 3 is about that."}
    assert published.id == "111_8_99"


# ---------- errors ----------
@pytest.mark.parametrize("code,status", [(190, 503), (200, 503), (10, 503), (4, 429), (32, 429),
                                         (100, 404), (1, 502), (None, 502)])
def test_graph_errors_map_to_statuses(graph, code, status):
    graph.answer = (400, {"error": {"message": "Something", "type": "OAuthException", "code": code}})
    with pytest.raises(fb.FacebookError) as e:
        fb.list_posts()
    assert e.value.status_code == status


def test_error_in_a_200_answer_is_still_an_error(graph):
    graph.answer = {"error": {"message": "Unsupported", "code": 100}}
    with pytest.raises(fb.FacebookError) as e:
        fb.page_info()
    assert e.value.status_code == 404


def test_timeout_and_network_errors_hide_request_details(graph):
    graph.error = httpx.ReadTimeout("timed out")
    with pytest.raises(fb.FacebookError) as e:
        fb.list_posts()
    assert e.value.status_code == 504
    graph.error = httpx.ConnectError(f"failed https://graph.facebook.com/?access_token={TOKEN}")
    with pytest.raises(fb.FacebookError) as e:
        fb.list_posts()
    assert e.value.status_code == 502 and TOKEN not in str(e.value)


def test_non_json_error_answer(graph, monkeypatch):
    monkeypatch.setattr(fb, "_client", lambda: httpx.Client(
        base_url="https://graph.facebook.com/v27.0/",
        transport=httpx.MockTransport(lambda r: httpx.Response(500, text="<html>oops</html>"))))
    with pytest.raises(fb.FacebookError) as e:
        fb.list_posts()
    assert e.value.status_code == 502 and json.dumps(str(e.value))


# ---------- recent threads ----------
def test_recent_threads_skip_posts_without_comments_and_mark_answered(graph, monkeypatch):
    from app.core.schemas import FacebookComment, FacebookComments, FacebookPost, FacebookPosts
    t = "2026-11-10T08:00:00+0000"
    monkeypatch.setattr(fb, "list_posts", lambda limit=10, after=None: FacebookPosts(items=[
        FacebookPost(id=f"{PAGE}_1", created_time=t, comment_count=2),
        FacebookPost(id=f"{PAGE}_2", created_time=t, comment_count=0)]))
    asked: list[str] = []

    def comments(post_id, limit=25, after=None):
        asked.append(post_id)
        return FacebookComments(items=[
            FacebookComment(id="1_9", post_id=post_id, created_time=t, from_page=True, parent_id="1_8"),
            FacebookComment(id="1_8", post_id=post_id, created_time=t, author="Ana"),
            FacebookComment(id="1_7", post_id=post_id, created_time=t, author="Ben")])

    monkeypatch.setattr(fb, "list_comments", comments)
    threads = fb.recent_threads(posts=5)
    assert asked == [f"{PAGE}_1"] and len(threads) == 1
    answered = {c.id: c.answered for c in threads[0].comments}
    assert answered == {"1_9": False, "1_8": True, "1_7": False}


# ---------- visitor posts, comment_on_post, open_items ----------
def test_posts_know_their_author(graph):
    graph.answer = {"data": [
        {"id": f"{PAGE}_1", "created_time": "2026-11-10T08:00:00+0000", "from": {"id": PAGE, "name": "HAIC"}},
        {"id": f"{PAGE}_2", "created_time": "2026-11-10T08:00:00+0000", "from": {"id": "77", "name": "Ana"}},
        {"id": f"{PAGE}_3", "created_time": "2026-11-10T08:00:00+0000"},  # Facebook left out the author
    ]}
    own, visitor, unknown = fb.list_posts().items
    assert own.from_page and own.author == "HAIC"
    assert not visitor.from_page and visitor.author == "Ana"
    assert unknown.from_page and unknown.author is None  # never mistaken for a visitor waiting for an answer
    assert "from{id,name}" in graph.requests[0].url.params["fields"]


def test_comment_on_post(graph):
    graph.answer = {"id": f"{PAGE}_2_99"}
    published = fb.comment_on_post(f"{PAGE}_2", "  Thank you!  ")
    request = graph.requests[0]
    assert request.method == "POST" and request.url.path == f"/v27.0/{PAGE}_2/comments"
    assert _form(request) == {"message": "Thank you!"}
    assert published.id == f"{PAGE}_2_99"


@pytest.mark.parametrize("post_id,message", [("../me", "hi"), (f"{PAGE}_2", "  ")])
def test_comment_on_post_rejects_bad_input(graph, post_id, message):
    with pytest.raises(ValueError):
        fb.comment_on_post(post_id, message)
    assert graph.requests == []


def _c(id, minute, from_page=False, parent=None, message="text", author="Ana"):
    from app.core.schemas import FacebookComment
    return FacebookComment(id=id, post_id="p", message=message, created_time=f"2026-11-10T08:{minute:02d}:00+0000",
                           from_page=from_page, parent_id=parent, author=None if from_page else author)


def test_mark_answered_follows_the_thread():
    comments = fb._mark_answered([
        _c("top", 0),                                   # answered by the Page's reply at :05
        _c("page1", 5, from_page=True, parent="top"),
        _c("follow", 7, parent="top"),                  # a visitor's follow-up after the Page's reply: open again
        _c("other", 1),                                 # no Page reply in its thread
        _c("early", 2, parent="other2"),                # reply in a thread the Page answered later
        _c("page2", 9, from_page=True, parent="other2"),
    ])
    answered = {c.id: c.answered for c in comments}
    assert answered == {"top": True, "page1": False, "follow": False, "other": False, "early": True, "page2": False}


def test_open_items_finds_unanswered_comments_and_visitor_posts(graph, monkeypatch):
    from app.core.schemas import FacebookComments, FacebookPost, FacebookPosts
    t = "2026-11-10T07:00:00+0000"
    own = FacebookPost(id=f"{PAGE}_1", created_time=t, comment_count=3)
    visitor_open = FacebookPost(id=f"{PAGE}_2", created_time="2026-11-10T09:00:00+0000", message="Is volume II out?",
                                from_page=False, author="Ben")
    visitor_done = FacebookPost(id=f"{PAGE}_3", created_time=t, message="Great book", from_page=False, comment_count=1)
    visitor_photo = FacebookPost(id=f"{PAGE}_4", created_time=t, message="", from_page=False)
    monkeypatch.setattr(fb, "list_posts", lambda limit=10, after=None: FacebookPosts(
        items=[own, visitor_open, visitor_done, visitor_photo]))
    asked = []

    def comments(post_id, limit=25, after=None):
        asked.append(post_id)
        return FacebookComments(items={
            own.id: [_c("1_9", 5, from_page=True, parent="1_8"), _c("1_8", 1), _c("1_7", 3, author="Cleo"),
                     _c("1_6", 4, message=" ")],  # a sticker: no text
            visitor_done.id: [_c("3_1", 2, from_page=True)],  # the Page commented on the visitor post
        }[post_id])

    monkeypatch.setattr(fb, "list_comments", comments)
    items = fb.open_items(posts=99)
    assert asked == [own.id, visitor_done.id]  # posts without comments cost no request
    assert [(i.kind, i.id, i.reply_to, i.author) for i in items] == [
        ("comment", "1_7", "1_7", "Cleo"),           # oldest first
        ("visitor_post", visitor_open.id, visitor_open.id, "Ben"),
    ]
    assert items[0].post.id == own.id and items[1].message == "Is volume II out?"


def test_open_items_reply_goes_to_the_top_comment(graph, monkeypatch):
    from app.core.schemas import FacebookComments, FacebookPost, FacebookPosts
    post = FacebookPost(id=f"{PAGE}_1", created_time="2026-11-10T07:00:00+0000", comment_count=3)
    monkeypatch.setattr(fb, "list_posts", lambda limit=10, after=None: FacebookPosts(items=[post]))
    monkeypatch.setattr(fb, "list_comments", lambda post_id, limit=25, after=None: FacebookComments(items=[
        _c("top", 0), _c("page", 5, from_page=True, parent="top"), _c("follow", 7, parent="top")]))
    [item] = fb.open_items()
    assert item.id == "follow" and item.reply_to == "top"
