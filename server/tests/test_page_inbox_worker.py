"""Page inbox worker (agents/page_inbox_worker.py): how the author's Telegram texts and buttons reach the graph, /next,
the schedule and error handling. Telegram, Facebook and the graph's public functions are faked; the graph itself is
tested in test_page_inbox.py."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.agents import page_inbox_worker as worker_module
from app.core import config
from app.core.schemas import FacebookInboxItem, FacebookPost, TelegramUpdate, YouTubeInboxItem, YouTubeUpload, YouTubeVideo

inbox = worker_module.inbox
NOW = datetime(2026, 11, 12, tzinfo=timezone.utc)


def _item(id="222_9"):
    post = FacebookPost(id="111_222", created_time=NOW)
    return FacebookInboxItem(kind="comment", id=id, reply_to=id, post=post, message="Hi", created_time=NOW)


def _text(text, reply_to=None):
    return TelegramUpdate(update_id=1, kind="text", text=text, message_id=500, reply_to_message_id=reply_to, date=NOW)


def _button(data, message_id=101):
    return TelegramUpdate(update_id=1, kind="button", text=data, message_id=message_id, callback_id="cb", date=NOW)


@pytest.fixture
def env(monkeypatch):
    """A worker with fakes: `env.waiting` is the waiting run (thread id, message id) or None; `env.open` the Page's
    open items; what the worker did is recorded."""
    e = SimpleNamespace(said=[], answered=[], removed=[], started=[], resumed=[], waiting=None, open=[_item()],
                        decided=set(), resume_result="posted", start_error=None, open_error=None, withdrawn=[],
                        channel=None, youtube_open=[], youtube_error=None, due=False, ran=[])
    # phase 2: no post to engage under unless a test sets env.engage_post
    e.engage_post, e.engaged, e.engage_waiting, e.posted_today = None, [], None, 0
    eng = worker_module.engagement
    monkeypatch.setattr(eng, "pick_post", lambda settings: e.engage_post)
    e.engage_video = None  # phase 2 on YouTube: no video unless a test sets env.engage_video
    monkeypatch.setattr(eng, "pick_video", lambda settings: e.engage_video)
    e.youtube_posted_today = 0
    monkeypatch.setattr(eng, "posted_today", lambda user_id, timezone, platform="facebook":
                        e.youtube_posted_today if platform == "youtube" else e.posted_today)
    monkeypatch.setattr(eng, "waiting_run", lambda: e.engage_waiting)

    def engage_start(post, test=False, humanize=80):
        e.humanized.append(humanize)
        e.engaged.append(post.id)
        e.engage_waiting = (f"eng:{post.id}:run1", 201)
        return e.engage_waiting[0]

    monkeypatch.setattr(eng, "start", engage_start)
    # phase 3: no topic for a book post unless a test sets env.post_topic
    e.post_topic, e.book_posted, e.post_waiting, e.tests, e.humanized = None, [], None, [], []
    bp = worker_module.book_post
    monkeypatch.setattr(bp, "next_topic", lambda settings: e.post_topic)
    monkeypatch.setattr(bp, "waiting_run", lambda: e.post_waiting)

    def post_start(topic, settings):
        e.book_posted.append(topic.key)
        e.tests.append(settings.test_mode)
        e.humanized.append(settings.humanize)
        e.post_waiting = (f"post:{topic.key}:run1", 301)
        return e.post_waiting[0]

    monkeypatch.setattr(bp, "start", post_start)
    monkeypatch.setattr(worker_module.automation, "inbox_due", lambda now: e.due)
    monkeypatch.setattr(worker_module.automation, "inbox_ran", lambda now: e.ran.append(now))
    monkeypatch.setattr(worker_module.telegram, "send_message",
                        lambda text, buttons=None, reply_to=None: e.said.append((text, reply_to)) or 1)
    monkeypatch.setattr(worker_module.telegram, "answer_button", lambda cid, text=None: e.answered.append(text))
    monkeypatch.setattr(worker_module.telegram, "remove_buttons", lambda mid: e.removed.append(mid))

    def open_items(posts):
        if e.open_error:
            raise e.open_error
        return e.open

    monkeypatch.setattr(worker_module.facebook, "open_items", open_items)
    monkeypatch.setattr(worker_module.facebook, "is_configured", lambda: True)

    def channel_for_inbox():
        if e.youtube_error:
            raise e.youtube_error
        return e.channel

    def youtube_open_items(comments):
        assert worker_module.youtube.is_configured()  # read inside as_channel
        return e.youtube_open

    monkeypatch.setattr(inbox, "channel_for_inbox", channel_for_inbox)
    monkeypatch.setattr(worker_module.youtube, "open_items", youtube_open_items)
    monkeypatch.setattr(inbox, "waiting_run", lambda: e.waiting)
    monkeypatch.setattr(inbox, "is_open", lambda item: item.id not in e.decided)

    def start(item, test=False, humanize=80):
        e.humanized.append(humanize)
        e.tests.append(test)
        if e.start_error:
            raise e.start_error
        e.started.append(item.id)
        e.waiting = ("thread", 101)
        return "thread"

    def resume(thread_id, message_id, decision, feedback=""):
        e.resumed.append((thread_id, message_id, decision, feedback))
        e.waiting = None if e.resume_result != "waiting" else ("thread", 102)
        return e.resume_result

    def withdraw(thread_id, message_id):
        e.withdrawn.append((thread_id, message_id))
        e.waiting = None
        return True

    monkeypatch.setattr(inbox, "start", start)
    monkeypatch.setattr(inbox, "resume", resume)
    monkeypatch.setattr(inbox, "withdraw", withdraw)
    monkeypatch.setattr(inbox, "item_of", lambda thread_id: "222_9")  # the waiting run is about the default item
    e.worker = worker_module.InboxWorker()
    return e


# ---------- commands ----------
@pytest.mark.parametrize("command", ["/start", "/help", "/help@haic_marketer_bot"])
def test_help(env, command):
    env.worker.handle(_text(command))
    assert "Make it so" in env.said[0][0] and "/next" in env.said[0][0]


def test_next_proposes_the_oldest_open_item(env):
    env.open = [_item("222_1"), _item("222_2")]
    env.decided = {"222_1"}  # skipped earlier
    env.worker.handle(_text("/next"))
    assert env.started == ["222_2"]
    assert env.said == [("Drafting a reply…", None)]


def test_next_with_nothing_new(env):
    env.open = []
    env.worker.handle(_text("/next"))
    assert env.started == [] and env.said == [("Nothing new on your Page or channel.", None)]


def test_next_while_a_proposal_waits(env):
    env.waiting = ("thread", 101)
    env.worker.handle(_text("/next"))
    assert env.started == []
    assert env.said == [("A proposal is still waiting for your answer (above).", 101)]


@pytest.mark.parametrize("error", [
    lambda: worker_module.facebook.FacebookError(503, "token expired"),
    lambda: inbox.InboxConfigError("Set FACEBOOK_INBOX_BOOKS"),
    lambda: worker_module.GenerationError(502, "model down"),
])
def test_next_reports_errors(env, error):
    env.start_error = error()
    env.worker.handle(_text("/next"))
    assert env.said[-1][0].startswith("Could not prepare the next reply:")


# ---------- answers ----------
def test_make_it_so_button_resumes_and_proposes_the_next(env):
    env.waiting = ("thread", 101)
    env.open = [_item("222_1"), _item("222_2")]
    env.decided = {"222_1"}  # the one just posted
    env.worker.handle(_button("go"))
    assert env.answered == ["Posting…"]
    assert env.resumed == [("thread", 101, "approve", "")]
    assert env.started == ["222_2"]  # straight on to the next


def test_skip_button(env):
    env.waiting = ("thread", 101)
    env.open = []
    env.worker.handle(_button("skip"))
    assert env.resumed == [("thread", 101, "skip", "")]
    assert env.said == []  # the graph says "Skipped"; nothing new: the worker stays quiet


@pytest.mark.parametrize("waiting,data,message_id", [
    (None, "go", 101),                 # nothing waits (decided, or lost in a restart)
    (("thread", 102), "go", 101),      # an older proposal
    (("thread", 101), "test:go", 101),  # an unknown button
])
def test_buttons_that_do_not_count(env, waiting, data, message_id):
    env.waiting = waiting
    env.worker.handle(_button(data, message_id))
    assert env.resumed == []
    assert env.answered == ["This proposal is already decided."] and env.removed == [message_id]


@pytest.mark.parametrize("text,decision,feedback", [
    ("Make it so!", "approve", ""), ("skip", "skip", ""), ("Mention volume 2", "feedback", "Mention volume 2")])
def test_text_answers(env, text, decision, feedback):
    env.waiting = ("thread", 101)
    env.resume_result = "waiting" if decision == "feedback" else "posted"
    env.worker.handle(_text(text))
    assert env.resumed == [("thread", 101, decision, feedback)]


def test_feedback_does_not_propose_the_next(env):
    env.waiting = ("thread", 101)
    env.resume_result = "waiting"
    env.worker.handle(_text("shorter please"))
    assert env.said == [("Rewriting…", None)] and env.started == []


def test_text_without_a_waiting_proposal(env):
    env.worker.handle(_text("make it so"))
    assert env.resumed == [] and "Send /next" in env.said[0][0]


def test_reply_to_an_older_proposal_is_refused(env):
    env.waiting = ("thread", 102)
    env.worker.handle(_text("make it so", reply_to=101))
    assert env.resumed == [] and env.said == [("That proposal is no longer current; answer the latest one.", 102)]


def test_reply_to_the_current_proposal_counts(env):
    env.waiting = ("thread", 101)
    env.worker.handle(_text("make it so", reply_to=101))
    assert env.resumed == [("thread", 101, "approve", "")]


def test_a_stale_result_is_told(env):
    env.waiting = ("thread", 101)
    env.resume_result = "stale"
    env.worker.handle(_text("make it so"))
    assert env.said == [("This proposal is already decided.", None)] and env.started == []


def test_a_failing_revision_keeps_the_proposal(env, monkeypatch):
    env.waiting = ("thread", 101)

    def broken(*args, **kwargs):
        raise worker_module.GenerationError(504, "The model timed out.")

    monkeypatch.setattr(inbox, "resume", broken)
    env.worker.handle(_text("shorter"))
    assert "The proposal above still waits" in env.said[-1][0]


def test_an_unexpected_error_never_ends_the_loop(env, monkeypatch):
    monkeypatch.setattr(inbox, "parse_answer", lambda text: 1 / 0)
    env.waiting = ("thread", 101)
    env.worker.handle(_text("make it so"))  # no exception
    assert "Something went wrong" in env.said[-1][0]


# ---------- schedule ----------
def test_tick_proposes_only_when_the_schedule_is_due(env):
    env.worker.tick(NOW)
    assert env.started == [] and env.ran == []
    env.due = True
    env.worker.tick(NOW)
    assert env.started == ["222_9"] and env.ran == [NOW]
    assert env.said == []  # the schedule does not announce itself


def test_tick_waits_while_a_proposal_waits(env):
    env.waiting = ("thread", 101)
    env.due = True
    env.worker.tick(NOW)
    assert env.started == [] and env.ran == [NOW]  # the run counts: it looked, nothing to propose


def test_the_schedule_reports_an_error_once(env):
    env.open_error = worker_module.facebook.FacebookError(503, "token expired")
    env.due = True
    for _ in range(3):
        env.worker.tick(NOW)
    assert len(env.said) == 1 and "token expired" in env.said[0][0]


def test_run_now_from_the_app_answers_like_next(env):
    env.worker.request_run()
    env.worker.tick(NOW)
    assert env.started == ["222_9"] and env.ran == [NOW]
    assert env.said == [("Run started from the app.", None), ("Drafting a reply…", None)]
    env.worker.tick(NOW)  # asked once, runs once
    assert env.started == ["222_9"]


def test_status_tells_the_schedule(env, monkeypatch):
    monkeypatch.setattr(worker_module.automation, "inbox_owner", lambda: "user_1")
    monkeypatch.setattr(worker_module.automation, "schedule_of", lambda user_id, fresh=False: _settings())
    env.worker.handle(_text("/status"))
    text = env.said[0][0]
    assert "every day at 09:00, 18:00 (Europe/Berlin)" in text and "Next run:" in text


def test_status_without_inbox_books(env, monkeypatch):
    monkeypatch.setattr(worker_module.automation, "inbox_owner", lambda: None)
    env.worker.handle(_text("/status"))
    assert "FACEBOOK_INBOX_BOOKS" in env.said[0][0]


def _settings():
    from app.core.schemas import AutomationSettings
    return AutomationSettings(user_id="user_1", times=["09:00", "18:00"], timezone="Europe/Berlin", saved_at=NOW)


# ---------- start on server startup ----------
def test_started_without_a_facebook_page_for_youtube_alone(monkeypatch):
    monkeypatch.setattr(worker_module.telegram, "is_configured", lambda: True)
    monkeypatch.setattr(worker_module.facebook, "is_configured", lambda: False)
    monkeypatch.setattr(config, "FACEBOOK_INBOX_BOOKS", ["src_1"])
    monkeypatch.setattr(inbox, "inbox_books", lambda: ("prj", ["src_1"]))
    started = []
    monkeypatch.setattr(worker_module.InboxWorker, "start", lambda self: started.append(self))
    assert worker_module.start_if_configured() is not None and len(started) == 1


def test_not_started_without_configuration(monkeypatch):
    monkeypatch.setattr(config, "FACEBOOK_INBOX_BOOKS", [])
    started = []
    monkeypatch.setattr(worker_module.InboxWorker, "start", lambda self: started.append(self))
    assert worker_module.start_if_configured() is None
    assert started == []


def test_started_when_everything_is_configured(monkeypatch):
    monkeypatch.setattr(worker_module.telegram, "is_configured", lambda: True)
    monkeypatch.setattr(worker_module.facebook, "is_configured", lambda: True)
    monkeypatch.setattr(config, "FACEBOOK_INBOX_BOOKS", ["src_1"])
    monkeypatch.setattr(inbox, "inbox_books", lambda: ("prj", ["src_1"]))
    started = []
    monkeypatch.setattr(worker_module.InboxWorker, "start", lambda self: started.append(self))
    worker = worker_module.start_if_configured()
    assert started == [worker] and worker_module.is_running()
    worker_module.stop()
    assert not worker_module.is_running()


# ---------- a waiting proposal answered elsewhere ----------
def test_a_waiting_proposal_answered_elsewhere_is_taken_back_and_the_next_proposed(env):
    env.waiting = ("thread", 101)
    env.open = [_item("222_12")]  # the waiting item (222_9) is no longer open on the Page; a newer one is
    env.due = True
    env.worker.tick(NOW)
    assert env.withdrawn == [("thread", 101)] and env.started == ["222_12"]


def test_next_takes_back_an_answered_proposal_too(env):
    env.waiting = ("thread", 101)
    env.open = []
    env.worker.handle(_text("/next"))
    assert env.withdrawn == [("thread", 101)] and env.said == [("Nothing new on your Page or channel.", None)]


# ---------- YouTube comments in the same inbox ----------
def _video_item(id="UgxCOMMENT0000000001", minute=0):
    return YouTubeInboxItem(id=id, reply_to=id, video=YouTubeVideo(id="vid00000001", title="V", url="https://y/v"),
                            message="Nice video", created_time=NOW.replace(minute=minute))


def test_youtube_and_facebook_items_are_proposed_oldest_first(env):
    env.channel = worker_module.youtube.ChannelAccess("UCx", "tok")
    env.open = [_item("222_9")]  # created at NOW (minute 0)
    env.youtube_open = [_video_item(minute=0)]
    env.open[0] = env.open[0].model_copy(update={"created_time": NOW.replace(minute=5)})
    env.worker.handle(_text("/next"))
    assert env.started == ["UgxCOMMENT0000000001"]  # the older one, from YouTube


def test_without_a_connected_channel_only_facebook_is_read(env):
    env.youtube_open = [_video_item()]  # would be proposed if the channel were read
    env.worker.handle(_text("/next"))
    assert env.started == ["222_9"]


def test_a_youtube_error_is_reported_and_facebook_still_proposed(env):
    env.youtube_error = worker_module.youtube.YouTubeError(503, "connect it again")
    env.worker.handle(_text("/next"))
    assert any("YouTube channel" in text and "connect it again" in text for text, _ in env.said)
    assert env.started == ["222_9"]


def test_a_waiting_proposal_is_kept_when_a_source_cannot_be_read(env):
    env.waiting = ("thread", 101)
    env.open = []  # the waiting item seems answered on the Page ...
    env.youtube_error = worker_module.youtube.YouTubeError(502, "Could not reach YouTube.")  # ... but YouTube failed
    env.worker.handle(_text("/next"))
    assert env.withdrawn == [] and env.started == []


def test_no_facebook_page_reads_only_youtube(env, monkeypatch):
    monkeypatch.setattr(worker_module.facebook, "is_configured", lambda: False)
    monkeypatch.setattr(worker_module.facebook, "open_items", lambda posts: pytest.fail("no Page to read"))
    env.channel = worker_module.youtube.ChannelAccess("UCx", "tok")
    env.youtube_open = [_video_item()]
    env.worker.handle(_text("/next"))
    assert env.started == ["UgxCOMMENT0000000001"]


# ---------- cycles ----------
@pytest.fixture
def cycles(env, monkeypatch):
    """The env worker, working for OWNER; `inbox.start` gives each run its own thread id."""
    from app.db import records
    from tests.conftest import OWNER
    monkeypatch.setattr(worker_module.automation, "inbox_owner", lambda: OWNER.id)
    monkeypatch.setattr(worker_module.automation, "_cache", {})  # each test has a fresh database
    monkeypatch.setattr(worker_module.automation, "_ran", {})
    monkeypatch.setattr(inbox, "posted_url", lambda thread_id: f"https://facebook.com/{thread_id}")
    count = iter(range(1, 100))

    def start(item, test=False, humanize=80):
        env.tests.append(test)
        env.humanized.append(humanize)
        thread = f"{item.id}:run{next(count)}"
        env.started.append(item.id)
        env.decided.add(item.id)  # no longer open once it has a run
        env.waiting = (thread, 100 + len(env.started))
        return thread

    monkeypatch.setattr(inbox, "start", start)
    env.saved = lambda: records.list_cycles(OWNER.id)
    return env


def test_a_cycle_proposes_one_item_after_the_other_and_ends_with_a_summary(cycles):
    cycles.open = [_item("222_1"), _item("222_2")]
    cycles.worker.handle(_text("/next"))
    assert cycles.started == ["222_1"] and cycles.worker.cycle is not None
    cycles.worker.handle(_button("go", message_id=101))  # posted → the next item
    assert cycles.started == ["222_1", "222_2"]
    cycles.resume_result = "skipped"
    cycles.worker.handle(_button("skip", message_id=102))
    assert cycles.worker.cycle is None
    assert ("Cycle done: 1 posted, 1 skipped.", None) in cycles.said
    [saved] = cycles.saved()
    assert saved.status == "done" and saved.trigger == "telegram"
    assert [(e.item_id, e.outcome) for e in saved.entries] == [("222_1", "posted"), ("222_2", "skipped")]
    assert saved.entries[0].url == "https://facebook.com/222_1:run1" and saved.entries[1].url == ""


def test_feedback_counts_as_a_revision(cycles):
    cycles.worker.handle(_text("/next"))
    cycles.resume_result = "waiting"
    cycles.worker.handle(_text("shorter please"))
    [saved] = cycles.saved()
    assert saved.status == "running" and saved.entries[0].revisions == 1


def test_a_quiet_scheduled_cycle_is_not_logged(cycles):
    cycles.open = []
    cycles.due = True
    cycles.worker.tick(NOW)
    assert cycles.worker.cycle is None and cycles.saved() == [] and cycles.said == []


def test_a_new_start_while_a_proposal_waits_continues_the_cycle(cycles):
    cycles.worker.handle(_text("/next"))
    first = cycles.worker.cycle
    cycles.due = True
    cycles.worker.tick(NOW)  # the comment is still open: the proposal keeps waiting
    assert cycles.worker.cycle is first and len(first.record.entries) == 1


def test_a_proposal_answered_elsewhere_is_logged_as_answered(cycles, monkeypatch):
    cycles.open = [_item("222_1")]
    cycles.worker.handle(_text("/next"))
    cycles.open = [_item("222_2")]  # 222_1 was answered on Facebook meanwhile
    monkeypatch.setattr(inbox, "item_of", lambda thread_id: thread_id.split(":")[0])
    cycles.due = True
    cycles.worker.tick(NOW)
    entries = cycles.worker.cycle.record.entries
    assert [(e.item_id, e.outcome) for e in entries] == [("222_1", "answered"), ("222_2", "waiting")]


def test_an_error_ends_the_cycle_and_is_logged_once(cycles):
    cycles.open_error = worker_module.facebook.FacebookError(503, "token expired")
    cycles.due = True
    for _ in range(3):
        cycles.worker.tick(NOW)
    [saved] = cycles.saved()
    assert saved.status == "error" and "token expired" in saved.note
    assert cycles.worker.cycle is None


def test_pause_and_resume(cycles):
    from tests.conftest import OWNER
    cycles.worker.handle(_text("/pause"))
    assert "Paused" in cycles.said[-1][0]
    assert worker_module.automation.schedule_of(OWNER.id, fresh=True).paused
    cycles.worker.handle(_text("/status"))
    assert "PAUSED" in cycles.said[-1][0]
    cycles.worker.handle(_text("/resume"))
    assert cycles.said[-1][0].startswith("Resumed.")
    assert not worker_module.automation.schedule_of(OWNER.id, fresh=True).paused


def _restored(monkeypatch, waiting: int):
    for agent in (worker_module.inbox, worker_module.engagement, worker_module.book_post):
        monkeypatch.setattr(agent, "restore", lambda: 0)
    monkeypatch.setattr(worker_module.inbox, "restore", lambda: waiting)
    return worker_module._restore()


def test_a_cycle_without_a_waiting_proposal_is_marked_interrupted_on_start(cycles, monkeypatch):
    cycles.worker.handle(_text("/next"))
    cycles.waiting = None  # the proposal was not kept
    assert _restored(monkeypatch, waiting=0) is None
    [saved] = cycles.saved()
    assert saved.status == "interrupted" and saved.ended_at is not None


def test_the_cycle_of_a_restored_proposal_goes_on_after_a_restart(cycles, monkeypatch):
    cycles.open = [_item("222_1"), _item("222_2")]
    cycles.worker.handle(_text("/next"))  # 222_1 waits; then the server restarts
    restarted = worker_module.InboxWorker()
    restarted.cycle = _restored(monkeypatch, waiting=1)
    assert restarted.cycle is not None and restarted.cycle.record.status == "running"
    restarted.handle(_button("go", message_id=101))  # the old button still works
    assert cycles.started == ["222_1", "222_2"]
    [saved] = cycles.saved()
    assert [(e.item_id, e.outcome) for e in saved.entries] == [("222_1", "posted"), ("222_2", "waiting")]
    assert saved.status == "running"


# ---------- help and the command menu ----------
def test_help_lists_every_command(env):
    env.worker.handle(_text("/help"))
    text = env.said[0][0]
    for name, _ in worker_module.COMMANDS:
        assert f"/{name} – " in text
    assert "Agent Workspace" in text


def test_start_sets_the_command_menu_and_survives_a_failure(monkeypatch):
    menus = []
    monkeypatch.setattr(worker_module.threading.Thread, "start", lambda self: None)
    monkeypatch.setattr(worker_module.telegram, "set_commands", lambda commands: menus.append(commands))
    worker_module.InboxWorker().start()
    assert menus == [worker_module.COMMANDS]

    def fail(commands):
        raise worker_module.telegram.TelegramError(502, "Bad Request")

    monkeypatch.setattr(worker_module.telegram, "set_commands", fail)
    worker_module.InboxWorker().start()  # no exception: the commands work without the menu


# ---------- phase 2: a question under an own post ----------
def _own_post(id="111_7"):
    return FacebookPost(id=id, message="Cities should grow in rings.", created_time=NOW)


@pytest.fixture
def engage(cycles, monkeypatch):
    """No open comments; an own post without comments; the engagement run answers like the inbox fake."""
    cycles.open = []
    cycles.engage_post = _own_post()
    eng = worker_module.engagement

    def resume(thread_id, message_id, decision, feedback=""):
        cycles.resumed.append((thread_id, message_id, decision, feedback))
        result = {"approve": "posted", "skip": "skipped"}.get(decision, "waiting")
        if result != "waiting":
            cycles.engage_waiting = None
        return result

    monkeypatch.setattr(eng, "resume", resume)
    monkeypatch.setattr(eng, "posted_url", lambda thread_id: "https://www.facebook.com/111_7_c")
    return cycles


def test_no_comments_leads_to_a_question_under_an_own_post(engage):
    engage.worker.handle(_text("/next"))
    assert engage.engaged == ["111_7"]
    assert ("Drafting a question for your post…", None) in engage.said
    engage.worker.handle(_button("go", message_id=201))
    assert engage.resumed == [("eng:111_7:run1", 201, "approve", "")]
    assert ("Cycle done: 1 posted.", None) in engage.said
    [saved] = engage.saved()
    assert [(e.kind, e.item_id, e.outcome, e.url) for e in saved.entries] == [
        ("comment", "111_7", "posted", "https://www.facebook.com/111_7_c")]


def _own_video(id="vid00000001"):
    return YouTubeUpload(id=id, title="Why cities sprawl", url=f"https://www.youtube.com/watch?v={id}",
                         published_at=NOW, comment_count=0)


def test_after_the_post_a_question_under_a_video_follows(engage):
    engage.engage_video = _own_video()
    engage.worker.handle(_text("/next"))
    assert engage.engaged == ["111_7"]  # Facebook first
    engage.worker.handle(_button("go", message_id=201))
    assert engage.engaged == ["111_7", "vid00000001"]  # then YouTube, in the same cycle
    engage.worker.handle(_button("skip", message_id=201))
    [saved] = engage.saved()
    assert [(e.kind, e.platform, e.item_id, e.outcome) for e in saved.entries] == [
        ("comment", "facebook", "111_7", "posted"), ("comment", "youtube", "vid00000001", "skipped")]
    assert saved.entries[1].excerpt == "Why cities sprawl"


def test_the_facebook_limit_does_not_stop_the_video_question(engage):
    engage.posted_today = 2  # Facebook's limit (2) reached
    engage.engage_video = _own_video()
    engage.worker.handle(_text("/next"))
    assert engage.engaged == ["vid00000001"]
    assert any("Facebook daily limit reached" in text for text, _ in engage.said)


def test_the_youtube_limit_stops_only_the_video_question(engage):
    engage.youtube_posted_today = 2  # YouTube's limit (2) reached
    engage.engage_video = _own_video()
    engage.worker.handle(_text("/next"))
    assert engage.engaged == ["111_7"]
    engage.worker.handle(_button("go", message_id=201))
    assert engage.engaged == ["111_7"]  # no video question after the post's


def test_without_a_post_the_question_goes_under_a_video(engage):
    engage.engage_post, engage.engage_video = None, _own_video()
    engage.worker.handle(_text("/next"))
    assert engage.engaged == ["vid00000001"]
    assert ("No post of yours from the last 14 days is waiting for a first comment.", None) in engage.said


def test_a_restored_cycle_knows_which_platforms_had_their_question(engage):
    engage.worker.handle(_text("/next"))
    from app.agents.cycle import Cycle
    [saved] = engage.saved()
    assert Cycle.of(saved).engage_tried == {"facebook"}


def test_feedback_on_the_question_goes_to_the_engagement_agent(engage):
    engage.worker.handle(_text("/next"))
    engage.worker.handle(_text("make it a yes/no question"))
    assert engage.resumed[-1][0].startswith("eng:") and engage.resumed[-1][2] == "feedback"
    assert engage.worker.cycle.record.entries[0].revisions == 1


def test_no_question_when_the_cycle_had_comments(engage):
    engage.open = [_item("222_1")]
    engage.worker.handle(_text("/next"))
    engage.resume_result = "skipped"
    engage.worker.handle(_button("skip", message_id=101))
    assert engage.engaged == []  # phase 2 only when phase 1 found nothing


def test_no_question_beyond_the_daily_limit(engage):
    engage.posted_today = 2
    engage.worker.handle(_text("/next"))
    assert engage.engaged == [] and "Facebook daily limit reached" in engage.said[-1][0]


def test_no_question_when_engagement_is_off(engage):
    from app.core.schemas import AutomationSchedule
    from tests.conftest import OWNER
    worker_module.automation.save(OWNER.id, AutomationSchedule(every_minutes=60, engage=False))
    engage.worker.handle(_text("/next"))
    assert engage.engaged == []


def test_while_a_question_waits_a_new_start_keeps_waiting(engage):
    engage.worker.handle(_text("/next"))
    engage.worker.handle(_text("/next"))
    assert engage.engaged == ["111_7"]
    assert engage.said[-1] == ("A proposal is still waiting for your answer (above).", 201)


# ---------- phase 3: a new post about the book ----------
@pytest.fixture
def post_phase(engage, monkeypatch):
    """No open comments, no post to engage under, one book topic; the book post run answers like the others."""
    from app.agents.book_post import Topic
    engage.engage_post = None
    engage.post_topic = Topic(key="src_1#0", source_id="src_1", title="The Magnet", summary="About it.")
    bp = worker_module.book_post

    def resume(thread_id, message_id, decision, feedback=""):
        engage.resumed.append((thread_id, message_id, decision, feedback))
        result = {"approve": "posted", "skip": "skipped"}.get(decision, "waiting")
        if result != "waiting":
            engage.post_waiting = None
        return result

    monkeypatch.setattr(bp, "resume", resume)
    monkeypatch.setattr(bp, "posted_url", lambda thread_id: "https://www.facebook.com/999_1")
    monkeypatch.setattr(worker_module, "source_name", lambda sid: "Volume 1")
    return engage


def test_a_cycle_ends_with_a_book_post(post_phase):
    post_phase.worker.handle(_text("/next"))
    assert post_phase.book_posted == ["src_1#0"]
    assert ("Writing a new post about your book…", None) in post_phase.said
    post_phase.worker.handle(_button("go", message_id=301))
    assert post_phase.resumed == [("post:src_1#0:run1", 301, "approve", "")]
    assert post_phase.worker.cycle is None and ("Cycle done: 1 posted.", None) in post_phase.said
    [saved] = post_phase.saved()
    assert [(e.kind, e.item_id, e.excerpt, e.url) for e in saved.entries] == [
        ("post", "src_1#0", "Volume 1 · The Magnet", "https://www.facebook.com/999_1")]


def test_the_book_post_follows_the_question(post_phase):
    post_phase.engage_post = _own_post()
    post_phase.worker.handle(_text("/next"))
    assert post_phase.engaged == ["111_7"] and post_phase.book_posted == []
    post_phase.worker.handle(_button("skip", message_id=201))
    assert post_phase.book_posted == ["src_1#0"]  # then phase 3
    post_phase.worker.handle(_button("skip", message_id=301))
    assert post_phase.worker.cycle is None and post_phase.book_posted == ["src_1#0"]  # once per cycle


def test_the_book_post_follows_the_replies(post_phase):
    post_phase.open = [_item("222_1")]
    post_phase.worker.handle(_text("/next"))
    post_phase.worker.handle(_button("go", message_id=101))
    assert post_phase.engaged == [] and post_phase.book_posted == ["src_1#0"]


def test_no_book_post_when_off_or_beyond_the_limit(post_phase):
    from app.core.schemas import AutomationSchedule
    from tests.conftest import OWNER
    post_phase.posted_today = 2
    post_phase.worker.handle(_text("/next"))
    assert post_phase.book_posted == [] and "Facebook daily limit reached" in post_phase.said[-1][0]
    post_phase.posted_today = 0
    worker_module.automation.save(OWNER.id, AutomationSchedule(every_minutes=60, book_post=False))
    post_phase.worker.handle(_text("/next"))
    assert post_phase.book_posted == []


def test_no_topics_says_how_to_get_them(post_phase):
    post_phase.post_topic = None
    post_phase.worker.handle(_text("/next"))
    assert "summarize your book" in post_phase.said[-1][0]


def test_how_human_reaches_every_agent(post_phase, monkeypatch):
    from app.core.schemas import AutomationSchedule
    from tests.conftest import OWNER
    worker_module.automation.save(OWNER.id, AutomationSchedule(every_minutes=60, humanize=35))
    post_phase.open = [_item("222_1")]
    post_phase.worker.handle(_text("/next"))
    post_phase.worker.handle(_button("go", message_id=101))
    assert post_phase.humanized == [35, 35]  # the reply, then the book post


def test_how_human_reaches_the_question(engage):
    from app.core.schemas import AutomationSchedule
    from tests.conftest import OWNER
    worker_module.automation.save(OWNER.id, AutomationSchedule(every_minutes=60, humanize=10))
    engage.worker.handle(_text("/next"))
    assert engage.engaged == ["111_7"] and engage.humanized == [10]


def test_test_mode_reaches_every_agent(post_phase):
    from app.core.schemas import AutomationSchedule
    from tests.conftest import OWNER
    worker_module.automation.save(OWNER.id, AutomationSchedule(every_minutes=60, test_mode=True))
    post_phase.open = [_item("222_1")]
    post_phase.worker.handle(_text("/next"))
    post_phase.worker.handle(_button("go", message_id=101))
    assert post_phase.tests == [True, True]  # the reply, then the book post
    post_phase.worker.handle(_text("/status"))
    assert "TEST MODE" in post_phase.said[-1][0]
