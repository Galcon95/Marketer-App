"""Who is online (core/presence.py) and the admin's /online in Telegram (page_inbox_worker.online): every signed-in
request is noted in memory, users of the last 15 minutes are "online now", emails leave the server only masked."""

from datetime import UTC, datetime, timedelta

import pytest
from starlette.requests import Request

from app.agents import page_inbox_worker as worker
from app.core import auth, guest, presence
from tests.conftest import STRANGER

NOW = datetime(2026, 11, 27, 15, 0, tzinfo=UTC)


@pytest.fixture(autouse=True)
def fresh(monkeypatch):
    presence.forget()
    guest.forget()
    monkeypatch.setattr(presence, "SINCE", NOW - timedelta(hours=2))
    yield
    presence.forget()
    guest.forget()


def test_every_signed_in_request_is_noted(monkeypatch):
    monkeypatch.setattr(auth, "verify_token", lambda token: STRANGER)
    auth.current_user(Request({"type": "http", "headers": [(b"authorization", b"Bearer t")]}))
    assert [p.user_id for p in presence.recent()] == [STRANGER.id]


def test_recent_is_newest_first_and_forgets_after_a_day():
    presence.seen("u1", "anna@example.com", NOW - timedelta(minutes=30))
    presence.seen("u2", "bert@example.com", NOW - timedelta(minutes=2))
    presence.seen("u3", "carl@example.com", NOW - timedelta(days=1, minutes=1))
    assert [p.user_id for p in presence.recent(NOW)] == ["u2", "u1"]
    assert "u3" not in [p.user_id for p in presence.recent(NOW)]


def test_emails_are_masked():
    assert presence.masked("peter@example.com") == "pe…@example.com"
    assert presence.masked("a@b.c") == "a…@b.c"
    assert presence.masked("") == "(no email)"


def test_online_lists_who_is_here_now_and_earlier():
    presence.seen("u1", "anna@example.com", NOW - timedelta(minutes=3))
    presence.seen("u2", "bert@example.com", NOW - timedelta(hours=2))
    text = worker.online(NOW)
    now_part, earlier = text.split("Earlier (last 24 hours)")
    assert "an…@example.com: 3 min ago" in now_part and "be…" not in now_part
    assert ": 1 user" in earlier and "be…@example.com: 2 h ago" in earlier
    assert "anna@" not in text and "bert@" not in text  # never the full address
    assert "Guest demo: nobody in it" in text
    assert "Known since 27 Nov, 13:00 UTC" in text


def test_online_with_nobody():
    text = worker.online(NOW)
    assert "No signed-in user." in text and "Earlier" not in text


def test_the_guest_shows_as_its_open_sessions_not_as_a_user(monkeypatch):
    monkeypatch.setattr(guest, "GUEST_EMAIL", "guest@demo.example")
    presence.seen("guest-id", "guest@demo.example", NOW - timedelta(minutes=1))
    guest._sessions.update({"s1": NOW - timedelta(minutes=10), "s2": NOW - timedelta(minutes=40),
                            "s3": NOW - timedelta(minutes=61)})  # the third one's hour is over
    guest.seen(NOW - timedelta(minutes=1))
    text = worker.online(NOW)
    assert "Guest demo: 2 open sessions, last activity 1 min ago" in text
    assert "gu…" not in text and "No signed-in user." in text


def test_demo_status_has_the_guest_line(monkeypatch):
    monkeypatch.setattr(guest, "configured", lambda: False)
    assert "Guest demo: nobody in it (/online for everyone)" in worker.red_button("/demo_status")


def test_online_is_a_command():
    assert "online" in {name for name, _ in worker.COMMANDS} and "/online" in worker.RED_BUTTON
