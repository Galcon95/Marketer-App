"""Page inbox worker (agents/page_inbox_worker.py): how the author's Telegram texts and buttons reach the graph, /next,
the schedule and error handling. Telegram, Facebook and the graph's public functions are faked; the graph itself is
tested in test_page_inbox.py."""

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.agents import page_inbox_worker as worker_module
from app.core import config
from app.core.schemas import FacebookInboxItem, FacebookPost, TelegramUpdate

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
                        decided=set(), resume_result="posted", start_error=None, open_error=None)
    monkeypatch.setattr(worker_module.telegram, "send_message",
                        lambda text, buttons=None, reply_to=None: e.said.append((text, reply_to)) or 1)
    monkeypatch.setattr(worker_module.telegram, "answer_button", lambda cid, text=None: e.answered.append(text))
    monkeypatch.setattr(worker_module.telegram, "remove_buttons", lambda mid: e.removed.append(mid))

    def open_items(posts):
        if e.open_error:
            raise e.open_error
        return e.open

    monkeypatch.setattr(worker_module.facebook, "open_items", open_items)
    monkeypatch.setattr(inbox, "waiting_run", lambda: e.waiting)
    monkeypatch.setattr(inbox, "is_open", lambda item: item.id not in e.decided)

    def start(item):
        if e.start_error:
            raise e.start_error
        e.started.append(item.id)
        e.waiting = ("thread", 101)
        return "thread"

    def resume(thread_id, message_id, decision, feedback=""):
        e.resumed.append((thread_id, message_id, decision, feedback))
        e.waiting = None if e.resume_result != "waiting" else ("thread", 102)
        return e.resume_result

    monkeypatch.setattr(inbox, "start", start)
    monkeypatch.setattr(inbox, "resume", resume)
    e.worker = worker_module.InboxWorker(interval_minutes=30)
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
    assert env.started == [] and env.said == [("Nothing new on your Page.", None)]


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
def test_tick_proposes_after_the_interval_only(env):
    env.worker.last_scan = 1000.0
    env.worker.tick(1000.0 + 29 * 60)
    assert env.started == []
    env.worker.tick(1000.0 + 30 * 60)
    assert env.started == ["222_9"]
    assert env.said == []  # the schedule does not announce itself


def test_tick_waits_while_a_proposal_waits(env):
    env.waiting = ("thread", 101)
    env.worker.tick(10_000_000.0)
    assert env.started == []


def test_interval_zero_means_only_next(env):
    env.worker.interval = 0
    env.worker.tick(10_000_000.0)
    assert env.started == []


def test_the_schedule_reports_an_error_once(env):
    env.open_error = worker_module.facebook.FacebookError(503, "token expired")
    for now in (1e7, 2e7, 3e7):
        env.worker.tick(now)
    assert len(env.said) == 1 and "token expired" in env.said[0][0]


# ---------- start on server startup ----------
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
    monkeypatch.setattr(config, "FACEBOOK_INBOX_INTERVAL", 15)
    monkeypatch.setattr(inbox, "inbox_books", lambda: ("prj", ["src_1"]))
    started = []
    monkeypatch.setattr(worker_module.InboxWorker, "start", lambda self: started.append(self))
    worker = worker_module.start_if_configured()
    assert started == [worker] and worker.interval == 15 * 60
