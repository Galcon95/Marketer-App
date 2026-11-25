"""YouTube channel client (social/youtube.py): requests it sends, how API answers become videos and comments, input
checks and error mapping. The YouTube Data API is faked with an httpx MockTransport; nothing leaves the machine."""

import json

import httpx
import pytest

from app.social import youtube as yt

CHANNEL = "UCabcdefghijklmnopqrstuv"
VIEWER = "UCviewer000000000000000"
TOKEN = "access-token-123"
VIDEO = "dQw4w9WgXcQ"
TOP = "UgxKREWxIgDrw8w2e_Z4AaABAg"


@pytest.fixture
def api():
    """Work on a channel and route API requests to a fake. Set `api.answers[path]` (dict, or (status, dict)); the
    requests sent are in `api.requests`."""

    class Fake:
        answers: dict[str, object] = {}
        requests: list[httpx.Request] = []
        error: Exception | None = None

    fake = Fake()
    fake.answers, fake.requests = {}, []

    def handler(request: httpx.Request) -> httpx.Response:
        fake.requests.append(request)
        if fake.error:
            raise fake.error
        answer = fake.answers.get(request.url.path.rsplit("/", 1)[-1], {})
        status, body = answer if isinstance(answer, tuple) else (200, answer)
        return httpx.Response(status, json=body)

    original = yt._client
    yt._client = lambda: httpx.Client(base_url=yt.API_URL, transport=httpx.MockTransport(handler))
    try:
        with yt.as_channel(yt.ChannelAccess(CHANNEL, TOKEN)):
            yield fake
    finally:
        yt._client = original


def _raw(comment_id, text, at, author=VIEWER, name="Ann", parent=None):
    snippet = {"textOriginal": text, "textDisplay": text, "publishedAt": at, "authorDisplayName": name,
               "authorChannelId": {"value": author}, "videoId": VIDEO}
    if parent:
        snippet["parentId"] = parent
    return {"id": comment_id, "snippet": snippet}


def _thread(top, replies=(), total=None, video=VIDEO):
    item = {"id": top["id"], "snippet": {"videoId": video, "topLevelComment": top,
                                         "totalReplyCount": len(replies) if total is None else total}}
    if replies:
        item["replies"] = {"comments": list(replies)}
    return item


def _error(status, reason, message="nope"):
    return status, {"error": {"code": status, "message": message, "errors": [{"reason": reason}]}}


# ---------- connection and token handling ----------
def test_without_a_channel_is_503_without_a_request():
    assert not yt.is_configured()
    with pytest.raises(yt.YouTubeError) as e:
        yt.channel_info()
    assert e.value.status_code == 503


def test_token_goes_in_the_header_not_the_url(api):
    api.answers["commentThreads"] = {"items": []}
    yt.recent_threads()
    request = api.requests[0]
    assert request.headers["Authorization"] == f"Bearer {TOKEN}"
    assert TOKEN not in str(request.url)


def test_the_token_is_not_in_the_repr():
    assert TOKEN not in repr(yt.ChannelAccess(CHANNEL, TOKEN))


def test_as_channel_ends_with_the_block():
    with yt.as_channel(yt.ChannelAccess(CHANNEL, TOKEN)):
        assert yt.is_configured()
    assert not yt.is_configured()


# ---------- reading ----------
def test_channel_info(api):
    api.answers["channels"] = {"items": [{"id": CHANNEL, "snippet": {"title": "HAIC", "customUrl": "@haic"},
                                          "statistics": {"subscriberCount": "12", "hiddenSubscriberCount": False}}]}
    channel = yt.channel_info()
    assert (channel.name, channel.subscribers, channel.link) == ("HAIC", 12, "https://www.youtube.com/@haic")
    assert api.requests[0].url.params["id"] == CHANNEL


def test_channel_info_hidden_subscribers_and_no_handle(api):
    api.answers["channels"] = {"items": [{"id": CHANNEL, "snippet": {"title": "HAIC"},
                                          "statistics": {"subscriberCount": "12", "hiddenSubscriberCount": True}}]}
    channel = yt.channel_info()
    assert channel.subscribers is None and channel.link == f"https://www.youtube.com/channel/{CHANNEL}"


def test_channel_not_returned_is_404(api):
    api.answers["channels"] = {"items": []}
    with pytest.raises(yt.YouTubeError) as e:
        yt.channel_info()
    assert e.value.status_code == 404


def test_recent_threads_groups_by_video_newest_first(api):
    other = "aaaaaaaaaaa"
    api.answers["commentThreads"] = {"items": [
        _thread(_raw(TOP, "Great video", "2026-11-10T10:00:00Z")),
        _thread(_raw("UgyOTHER00000000000000000", "Second video", "2026-11-09T10:00:00Z"), video=other),
        _thread(_raw("UgzOLDER00000000000000000", "Older", "2026-11-08T10:00:00Z")),
    ]}
    api.answers["videos"] = {"items": [
        {"id": VIDEO, "snippet": {"title": "Volume I", "thumbnails": {"medium": {"url": "https://img/1.jpg"}}}},
        {"id": other, "snippet": {"title": "Volume II"}}]}
    threads = yt.recent_threads(comments=3)
    assert [t.video.title for t in threads] == ["Volume I", "Volume II"]
    assert [c.message for c in threads[0].comments] == ["Great video", "Older"]
    first = threads[0].comments[0]
    assert first.author == "Ann" and not first.from_channel and first.parent_id is None
    assert first.permalink_url == f"https://www.youtube.com/watch?v={VIDEO}&lc={TOP}"
    assert threads[0].video.thumbnail == "https://img/1.jpg"
    assert threads[0].video.url == f"https://www.youtube.com/watch?v={VIDEO}"
    params = api.requests[0].url.params
    assert params["allThreadsRelatedToChannelId"] == CHANNEL and params["maxResults"] == "3"
    assert params["order"] == "time" and params["textFormat"] == "plainText"
    assert api.requests[1].url.params["id"] == f"{VIDEO},{other}"


def test_recent_threads_limit_is_clamped(api):
    api.answers["commentThreads"] = {"items": []}
    assert yt.recent_threads(comments=500) == []
    assert api.requests[0].url.params["maxResults"] == "100"
    assert len(api.requests) == 1  # no videos to look up


def test_a_video_youtube_does_not_return_keeps_its_comments(api):
    api.answers["commentThreads"] = {"items": [_thread(_raw(TOP, "Hi", "2026-11-10T10:00:00Z"))]}
    api.answers["videos"] = {"items": []}
    [thread] = yt.recent_threads()
    assert thread.video.id == VIDEO and thread.video.title == "" and len(thread.comments) == 1


def test_answered_when_the_channel_replied_after_the_comment(api):
    reply = _raw(f"{TOP}.reply1", "Thank you!", "2026-11-10T11:00:00Z", author=CHANNEL, name="HAIC", parent=TOP)
    api.answers["commentThreads"] = {"items": [
        _thread(_raw(TOP, "Great video", "2026-11-10T10:00:00Z"), [reply]),
        _thread(_raw("UgyOPEN000000000000000000", "A question", "2026-11-09T10:00:00Z")),
    ]}
    [thread] = yt.recent_threads()
    by_text = {c.message: c for c in thread.comments}
    assert by_text["Great video"].answered and by_text["Great video"].reply_count == 1
    assert not by_text["A question"].answered
    assert by_text["Thank you!"].from_channel and not by_text["Thank you!"].answered
    assert by_text["Thank you!"].parent_id == TOP


def test_a_follow_up_after_the_channels_reply_is_open_again(api):
    replies = [
        _raw(f"{TOP}.reply1", "Thank you!", "2026-11-10T11:00:00Z", author=CHANNEL, parent=TOP),
        _raw(f"{TOP}.reply2", "But what about X?", "2026-11-10T12:00:00Z", parent=TOP),
    ]
    api.answers["commentThreads"] = {"items": [_thread(_raw(TOP, "Great video", "2026-11-10T10:00:00Z"), replies)]}
    [thread] = yt.recent_threads()
    by_text = {c.message: c for c in thread.comments}
    assert by_text["Great video"].answered and not by_text["But what about X?"].answered


def test_the_channels_own_top_comment_is_not_an_answer(api):
    api.answers["commentThreads"] = {"items": [
        _thread(_raw(TOP, "Pinned: buy the book", "2026-11-10T10:00:00Z", author=CHANNEL),
                [_raw(f"{TOP}.reply1", "Where?", "2026-11-10T11:00:00Z", parent=TOP)])]}
    [thread] = yt.recent_threads()
    assert not any(c.answered for c in thread.comments)


def test_all_replies_are_fetched_when_youtube_includes_only_some(api):
    included = [_raw(f"{TOP}.reply6", "Reply 6", "2026-11-10T16:00:00Z", parent=TOP)]
    api.answers["commentThreads"] = {"items": [_thread(_raw(TOP, "Hi", "2026-11-10T10:00:00Z"), included, total=6)]}
    api.answers["comments"] = {"items": [
        _raw(f"{TOP}.reply{n}", f"Reply {n}", f"2026-11-10T1{n}:00:00Z", parent=TOP) for n in range(1, 7)]}
    [thread] = yt.recent_threads()
    assert len(thread.comments) == 7 and thread.comments[0].message == "Reply 6"
    replies_request = next(r for r in api.requests if r.url.path.endswith("/comments"))
    assert replies_request.url.params["parentId"] == TOP and replies_request.url.params["maxResults"] == "100"


def test_list_replies_of_a_reply_asks_for_its_top_comment(api):
    api.answers["comments"] = {"items": []}
    assert yt.list_replies(f"{TOP}.reply1") == []
    assert api.requests[0].url.params["parentId"] == TOP


# ---------- uploads ----------
def _uploads(api, videos):
    api.answers["channels"] = {"items": [{"id": CHANNEL, "contentDetails": {"relatedPlaylists": {"uploads": "UUx"}}}]}
    api.answers["playlistItems"] = {"items": [{"contentDetails": {"videoId": v["id"]}} for v in videos]}
    api.answers["videos"] = {"items": videos}


def _upload(video_id, at, comments="0", title="Garden cities", description="Why cities grow in rings."):
    stats = {} if comments is None else {"commentCount": comments}
    return {"id": video_id, "snippet": {"title": title, "description": description, "publishedAt": at},
            "statistics": stats}


def test_recent_videos_newest_first_with_comment_counts(api):
    _uploads(api, [_upload("aaaaaaaaaaa", "2026-11-01T10:00:00Z", "3"),
                   _upload("bbbbbbbbbbb", "2026-11-10T10:00:00Z"),
                   _upload("ccccccccccc", "2026-11-05T10:00:00Z", None)])  # comments turned off: no count
    videos = yt.recent_videos(5)
    assert [(v.id, v.comment_count) for v in videos] == [("bbbbbbbbbbb", 0), ("ccccccccccc", None),
                                                          ("aaaaaaaaaaa", 3)]
    assert videos[0].description == "Why cities grow in rings." and videos[0].url.endswith("v=bbbbbbbbbbb")
    playlist = api.requests[1]
    assert playlist.url.params["playlistId"] == "UUx" and playlist.url.params["maxResults"] == "5"
    assert api.requests[2].url.params["part"] == "snippet,statistics" and len(api.requests) == 3


def test_latest_comments_of_a_video_with_replies_newest_first(api):
    api.answers["commentThreads"] = {"items": [
        _thread(_raw(TOP, "Old question", "2026-11-01T10:00:00Z"),
                [_raw(f"{TOP}.r1", "A later reply", "2026-11-09T10:00:00Z", parent=TOP)]),
        _thread(_raw("UgyNEWER", "Newer top comment", "2026-11-05T10:00:00Z"))]}
    found = yt.latest_comments(VIDEO, 3)
    assert [c.message for c in found] == ["A later reply", "Newer top comment", "Old question"]
    params = api.requests[0].url.params
    assert params["videoId"] == VIDEO and params["order"] == "time" and params["maxResults"] == "3"
    with pytest.raises(ValueError):
        yt.latest_comments("not a video id!")


def test_recent_videos_of_a_channel_without_uploads(api):
    _uploads(api, [])
    assert yt.recent_videos() == [] and len(api.requests) == 2
    api.answers["channels"] = {"items": []}
    with pytest.raises(yt.YouTubeError) as e:
        yt.recent_videos()
    assert e.value.status_code == 404


def test_comment_on_video(api):
    api.answers["commentThreads"] = {"id": "UgzNEW"}
    posted = yt.comment_on_video(VIDEO, "  What would you change?  ")
    request = api.requests[0]
    assert request.method == "POST" and request.url.params["part"] == "snippet"
    assert json.loads(request.content) == {"snippet": {"videoId": VIDEO, "topLevelComment": {
        "snippet": {"textOriginal": "What would you change?"}}}}
    assert posted.id == "UgzNEW" and posted.url == f"https://www.youtube.com/watch?v={VIDEO}&lc=UgzNEW"


@pytest.mark.parametrize("video_id", ["", "short", "../channels", "x" * 12])
def test_comment_on_video_refuses_an_invalid_video_id(api, video_id):
    with pytest.raises(ValueError):
        yt.comment_on_video(video_id, "Hi")
    assert not api.requests


# ---------- transcripts ----------
def test_srt_text_drops_numbers_timings_markup_sound_notes_and_repeats():
    srt = """1\n00:00:00,000 --> 00:00:02,000\n<c>welcome to</c> [music] the city\n\n2\n00:00:02,000 --> 00:00:04,000\nwelcome to the city\nwhere rings of green\n\n3\n00:00:04,000 --> 00:00:06,000\nwhere rings of green\nhold the sprawl\n"""
    assert yt.srt_text(srt) == "welcome to the city where rings of green hold the sprawl"


def test_video_transcript_prefers_the_authors_own_captions(api):
    api.answers["captions"] = {"items": [
        {"id": "asr1", "snippet": {"trackKind": "asr", "status": "serving"}},
        {"id": "own1", "snippet": {"trackKind": "standard", "status": "serving"}},
        {"id": "bad1", "snippet": {"trackKind": "standard", "status": "failed"}}]}
    original = yt._client

    def client():
        c = original()
        transport = c._transport

        class Text(httpx.BaseTransport):
            def handle_request(self, request):
                if request.url.path.endswith("/captions/own1"):
                    api.requests.append(request)
                    return httpx.Response(200, text="1\n00:00:00,000 --> 00:00:01,000\nRings of green.\n")
                return transport.handle_request(request)

        return httpx.Client(base_url=yt.API_URL, transport=Text())

    yt._client = client
    try:
        assert yt.video_transcript(VIDEO) == "Rings of green."
    finally:
        yt._client = original
    listing, download = api.requests
    assert listing.url.params["videoId"] == VIDEO and download.url.params["tfmt"] == "srt"


def test_a_video_without_captions_has_no_transcript(api):
    api.answers["captions"] = {"items": []}
    assert yt.video_transcript(VIDEO) == "" and len(api.requests) == 1


def test_a_refused_caption_download_is_an_error(api):
    api.answers["captions"] = {"items": [{"id": "asr1", "snippet": {"trackKind": "asr"}}]}
    api.answers["asr1"] = (403, {"error": {"message": "forbidden", "errors": [{"reason": "forbidden"}]}})
    with pytest.raises(yt.YouTubeError):
        yt.video_transcript(VIDEO)


def test_video_transcript_refuses_an_invalid_video_id(api):
    with pytest.raises(ValueError):
        yt.video_transcript("../channels")
    assert not api.requests


# ---------- writing ----------
def test_reply_to_comment(api):
    api.answers["comments"] = {"id": f"{TOP}.new", "snippet": {"parentId": TOP}}
    posted = yt.reply_to_comment(TOP, "  Thanks for watching!  ", video_id=VIDEO)
    request = api.requests[0]
    assert request.method == "POST" and request.url.params["part"] == "snippet"
    assert json.loads(request.content) == {"snippet": {"parentId": TOP, "textOriginal": "Thanks for watching!"}}
    assert posted.id == f"{TOP}.new"
    assert posted.url == f"https://www.youtube.com/watch?v={VIDEO}&lc={TOP}.new"


def test_reply_to_a_reply_goes_under_the_top_comment(api):
    api.answers["comments"] = {"id": f"{TOP}.new", "snippet": {"parentId": TOP, "videoId": VIDEO}}
    posted = yt.reply_to_comment(f"{TOP}.reply1", "Good point")
    assert json.loads(api.requests[0].content)["snippet"]["parentId"] == TOP
    assert VIDEO in posted.url  # the video from YouTube's answer


def test_reply_without_a_video_has_no_link(api):
    api.answers["comments"] = {"id": f"{TOP}.new", "snippet": {"parentId": TOP}}
    assert yt.reply_to_comment(TOP, "Hi").url == ""


@pytest.mark.parametrize("comment_id", ["", "abc", "../videos", f"{TOP}/x", f"{TOP}.a.b", "x" * 200])
def test_reply_refuses_an_invalid_comment_id(api, comment_id):
    with pytest.raises(ValueError):
        yt.reply_to_comment(comment_id, "Hi")
    assert not api.requests


@pytest.mark.parametrize("message", ["", "   ", "x" * (yt.MAX_MESSAGE + 1)])
def test_reply_refuses_an_empty_or_too_long_message(api, message):
    with pytest.raises(ValueError):
        yt.reply_to_comment(TOP, message)
    assert not api.requests


def test_publishable_text_removes_citation_markers():
    assert yt.publishable_text("The book says so [1] . Really [2][3]!") == "The book says so. Really!"


# ---------- errors ----------
@pytest.mark.parametrize("answer, status, words", [
    (_error(401, "authError"), 503, "connect it again"),
    (_error(403, "quotaExceeded"), 429, "quota"),
    (_error(403, "rateLimitExceeded"), 429, "rate limit"),
    (_error(403, "commentsDisabled"), 404, "turned off"),
    (_error(404, "commentNotFound"), 404, "could not find"),
    (_error(400, "parentCommentNotFound"), 404, "could not find"),
    (_error(403, "insufficientPermissions"), 503, "permission"),
    (_error(403, "forbidden"), 503, "permission"),
    (_error(400, "processingFailure"), 502, "error"),
    ((500, {}), 502, "HTTP 500"),
    ((401, {"error": "invalid_token"}), 503, "connect it again"),
])
def test_api_errors_become_statuses(api, answer, status, words):
    api.answers["comments"] = answer
    with pytest.raises(yt.YouTubeError) as e:
        yt.reply_to_comment(TOP, "Hi")
    assert e.value.status_code == status and words in str(e.value)


def test_timeout_is_504_and_network_error_502(api):
    api.error = httpx.ReadTimeout("slow")
    with pytest.raises(yt.YouTubeError) as e:
        yt.recent_threads()
    assert e.value.status_code == 504
    api.error = httpx.ConnectError("down")
    with pytest.raises(yt.YouTubeError) as e:
        yt.recent_threads()
    assert e.value.status_code == 502


def test_error_messages_never_contain_the_token(api):
    api.error = httpx.ConnectError(f"failed with {TOKEN}")
    with pytest.raises(yt.YouTubeError) as e:
        yt.recent_threads()
    assert TOKEN not in str(e.value)


# ---------- open items (for the inbox agent) ----------
def test_open_items_are_the_unanswered_viewer_comments_oldest_first(api):
    answered_top = "UgyANSWERED000000000000"
    api.answers["commentThreads"] = {"items": [
        _thread(_raw(TOP, "Great video", "2026-11-10T10:00:00Z"), [
            _raw(f"{TOP}.reply1", "Thank you!", "2026-11-10T11:00:00Z", author=CHANNEL, parent=TOP),
            _raw(f"{TOP}.reply2", "But what about X?", "2026-11-10T12:00:00Z", parent=TOP)]),
        _thread(_raw("UgyOPEN000000000000000000", "A question", "2026-11-09T10:00:00Z")),
        _thread(_raw(answered_top, "Thanks", "2026-11-08T10:00:00Z"), [
            _raw(f"{answered_top}.reply1", "You are welcome", "2026-11-08T11:00:00Z", author=CHANNEL,
                 parent=answered_top)]),
        _thread(_raw("UgyMINE00000000000000000", "Pinned by me", "2026-11-07T10:00:00Z", author=CHANNEL)),
        _thread(_raw("UgyEMPTY0000000000000000", "  ", "2026-11-06T10:00:00Z")),
    ]}
    api.answers["videos"] = {"items": [{"id": VIDEO, "snippet": {"title": "Volume I"}}]}
    items = yt.open_items()
    assert [i.message for i in items] == ["A question", "But what about X?"]
    follow_up = items[1]
    assert follow_up.reply_to == TOP and follow_up.video.title == "Volume I"
    assert [c.message for c in follow_up.thread] == ["Great video", "Thank you!"]  # the thread before it
    assert items[0].thread == [] and items[0].reply_to == items[0].id
