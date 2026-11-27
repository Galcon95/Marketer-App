"""Tests of the red button (core/alarm.py): the spending spike switches the guest demo off and alerts the admin, a
changed guest email does the same, used-up budgets and many refused starts alert, each kind at most once an hour,
the switches survive a restart, and the Telegram commands /demo_off, /demo_on, /freeze, /unfreeze, /demo_status.
Alarms are collected by the `alarms` fixture (conftest.py) instead of being sent."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI, Request
from fastapi.testclient import TestClient

from app.agents import page_inbox_worker as worker
from app.api import deps, health, knowledge, projects, sources
from app.core import accounts, alarm, auth, config, guest
from app.core.auth import User
from app.core.limits import LIMITS
from app.core.schemas import UsageRecord
from app.db import records
from tests.conftest import OWNER, STRANGER, sign_in

GUEST = User(id="user-guest", email="guest@demo.example")
NOW = datetime.now(timezone.utc)

pytestmark = pytest.mark.usefixtures("offline")


@pytest.fixture(autouse=True)
def guest_account(monkeypatch):
    monkeypatch.setattr(guest, "GUEST_EMAIL", "guest@demo.example")
    guest.forget()
    yield
    guest.forget()


# ---------- the spike ----------

def test_a_spike_switches_the_demo_off_and_alerts(alarms):
    alarm.cost(0.60, STRANGER.id, now=100.0)
    assert alarm.demo_on() and alarms == []
    alarm.cost(0.50, STRANGER.id, now=200.0)  # $1.10 within 10 minutes
    assert not alarm.demo_on()
    assert records.load_switches() == {"demo": False}  # kept over a restart
    assert len(alarms) == 1 and "$1.10" in alarms[0] and "switched the guest demo off" in alarms[0]


def test_costs_older_than_the_window_do_not_count(alarms):
    alarm.cost(0.60, STRANGER.id, now=0.0)
    alarm.cost(0.50, STRANGER.id, now=LIMITS.alarm.spike_minutes * 60 + 1.0)
    assert alarm.demo_on() and alarms == []


def test_the_guests_share_is_told(alarms):
    guest.remember([accounts.client_of(GUEST)])
    alarm.cost(0.70, GUEST.id, now=1.0)
    alarm.cost(0.40, STRANGER.id, now=2.0)
    assert "(the guest demo: $0.70)" in alarms[0]
    assert alarm.recent(now=3.0) == (pytest.approx(1.10), pytest.approx(0.70), 0)


def test_each_kind_is_sent_at_most_once_an_hour(alarms):
    for second in range(5):
        alarm.cost(0.60, STRANGER.id, now=float(second))
    assert len(alarms) == 1
    alarm.budget("The guest demo used up the daily budget of $0.50.")
    assert len(alarms) == 2  # another kind


# ---------- the guest account taken over ----------

def test_a_changed_guest_email_switches_the_demo_off(alarms, monkeypatch):
    guest.remember([accounts.client_of(GUEST)])
    monkeypatch.setattr(auth, "verify_token", lambda token: User(id=GUEST.id, email="thief@example.com"))
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer t")]})
    with pytest.raises(auth.HTTPException) as paused:
        auth.current_user(request)
    assert paused.value.status_code == 503
    assert not alarm.demo_on() and "changed the guest account's email" in alarms[0]


# ---------- what the switches do ----------

def test_a_paused_demo_refuses_try_as_guest_and_guest_requests(monkeypatch):
    import server
    alarm.set_switch("demo", False, "test")
    monkeypatch.setattr(guest, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(guest, "SUPABASE_SECRET_KEY", "sb_secret_test")
    response = TestClient(server.app).post("/guest")
    assert response.status_code == 503 and "paused" in response.json()["detail"]
    monkeypatch.setattr(auth, "verify_token", lambda token: GUEST)
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer t")]})
    with pytest.raises(auth.HTTPException):
        auth.current_user(request)
    monkeypatch.setattr(auth, "verify_token", lambda token: STRANGER)
    assert auth.current_user(request) == STRANGER  # everyone else goes on


@pytest.fixture
def app():
    deps._llm_calls.clear()
    app = FastAPI()
    for module in (projects, sources, knowledge, health):
        app.include_router(module.router)
    yield app
    deps._llm_calls.clear()


def search_as(app: FastAPI, user: User):
    sign_in(app, user)
    client = TestClient(app)
    project = client.get("/me").json()["project"]["id"]
    return client.post(f"/projects/{project}/search", json={"query": "garden cities"})


def test_freeze_stops_everyone_but_the_admin(app, monkeypatch):
    monkeypatch.setattr(accounts, "DEFAULT_CLIENT_OWNER", OWNER.email)
    alarm.set_switch("freeze", True, "test")
    frozen = search_as(app, STRANGER)
    assert frozen.status_code == 503 and "paused by its administrator" in frozen.json()["detail"]
    assert search_as(app, OWNER).status_code == 503  # the admin passes the limits (503 = no API key in tests)
    assert "paused" not in search_as(app, OWNER).text
    alarm.set_switch("freeze", False, "test")
    assert "paused" not in search_as(app, STRANGER).text


def spend(cost: float, user_id: str) -> None:
    records.add_usage(UsageRecord(
        timestamp=NOW, operation="ask/answer", kind="chat", model="m", input_tokens=1, output_tokens=1,
        input_cost=cost, output_cost=0.0, cost=cost, cost_source="estimate", project_id=None, user_id=user_id))


def test_a_used_up_budget_alerts(app, alarms):
    spend(1.20, STRANGER.id)
    assert search_as(app, STRANGER).status_code == 429
    assert any("stranger@example.com used up the daily budget of $1.00" in a for a in alarms)


def test_many_refused_starts_alert(alarms):
    for second in range(LIMITS.alarm.refusals_per_hour):
        alarm.refused(now=float(second))
    assert alarms == []
    alarm.refused(now=30.0)
    assert len(alarms) == 1 and "21 refusals in the last hour" in alarms[0]


def test_the_switches_survive_a_restart():
    alarm.set_switch("demo", False, "test")
    alarm.set_switch("freeze", True, "test")
    alarm.reset()  # as after a restart: memory forgets, the database keeps
    assert alarm.demo_on() and not alarm.frozen()
    alarm.load()
    assert not alarm.demo_on() and alarm.frozen()


def test_setting_a_switch_twice_changes_nothing():
    assert alarm.set_switch("demo", False, "test") is True
    assert alarm.set_switch("demo", False, "test") is False


def test_alarms_go_to_telegram_when_it_is_configured(monkeypatch):
    sent = []
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", 42)
    from app.social import telegram
    monkeypatch.setattr(telegram, "send_message", lambda text, **_: sent.append(text) or 1)
    alarm._send("🚨 test")
    assert sent == ["🚨 test"]
    monkeypatch.setattr(telegram, "send_message", lambda text, **_: (_ for _ in ()).throw(RuntimeError("down")))
    alarm._send("🚨 test")  # a failed send is only logged


# ---------- Telegram commands ----------

def test_the_red_button_commands():
    assert "Guest demo switched off" in worker.red_button("/demo_off") and not alarm.demo_on()
    assert "already off" in worker.red_button("/demo_off")
    assert "switched on again" in worker.red_button("/demo_on") and alarm.demo_on()
    assert "Frozen" in worker.red_button("/freeze") and alarm.frozen()
    assert "allowed for everyone again" in worker.red_button("/unfreeze") and not alarm.frozen()


def test_guests_counts_sessions_starts_and_refusals_per_period():
    from datetime import timedelta
    from app.core.schemas import AuditEvent
    for days_old, action in [(0, "guest.reset"), (0, "guest.started"), (0, "guest.started"), (0, "guest.refused"),
                             (3, "guest.reset"), (3, "guest.started"), (20, "guest.reset"), (20, "guest.started")]:
        records.add_audit_event(AuditEvent(at=NOW - timedelta(days=days_old, minutes=5), action=action))
    text = worker.red_button("/guests")
    assert "Last 24 hours: 1 · 2 · 1" in text
    assert "Last 7 days: 2 · 3 · 1" in text
    assert "Last 30 days: 3 · 4 · 1" in text and "Total: 3 · 4 · 1" in text
    assert "Last start: " in text and "never" not in text
    assert "Guest sessions: 1 in 24 hours, 2 in 7 days" in worker.red_button("/demo_status")


def test_guests_without_any_visit():
    assert "Total: 0 · 0 · 0" in worker.red_button("/guests") and "Last start: never" in worker.red_button("/guests")


def test_demo_status_tells_the_state_and_todays_spending(monkeypatch):
    spend(0.30, STRANGER.id)
    monkeypatch.setattr(guest, "configured", lambda: False)  # no Supabase in tests: without the guest's line
    alarm.set_switch("demo", False, "test")
    status = worker.red_button("/demo_status")
    assert "Guest demo: OFF · Freeze: off" in status
    assert "Whole app today: $0.30 of $20.00" in status


def test_the_commands_are_in_the_bots_menu():
    names = {f"/{name}" for name, _ in worker.COMMANDS}
    assert set(worker.RED_BUTTON) <= names


def test_a_sending_only_server_starts_no_worker(monkeypatch):
    monkeypatch.setattr(config, "TELEGRAM_POLLING", False)
    monkeypatch.setattr(config, "TELEGRAM_BOT_TOKEN", "123:abc")
    monkeypatch.setattr(config, "TELEGRAM_CHAT_ID", 42)
    assert worker.start_if_configured() is None
