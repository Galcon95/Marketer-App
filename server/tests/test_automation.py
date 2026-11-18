"""The marketing agent's schedule (agents/automation.py) and its API (api/automation.py): the clock (times of day,
intervals, days of the week, time zones, daylight saving time), saving, the last run, and the routes."""

from datetime import UTC, datetime, timedelta

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from pydantic import ValidationError

from app.agents import automation, page_inbox_worker
from app.api import automation as automation_api
from app.core import config
from app.core.schemas import AutomationSchedule, AutomationSettings
from app.db import records
from tests.conftest import OWNER, STRANGER, sign_in


@pytest.fixture(autouse=True)
def fresh_state(monkeypatch):
    """No cached settings or in-memory runs from other tests; the inbox works for OWNER; no worker."""
    monkeypatch.setattr(automation, "_cache", {})
    monkeypatch.setattr(automation, "_ran", {})
    monkeypatch.setattr(automation, "inbox_owner", lambda: OWNER.id)
    monkeypatch.setattr(page_inbox_worker, "_worker", None)


def _utc(*args) -> datetime:
    return datetime(*args, tzinfo=UTC)


def _settings(**kwargs) -> AutomationSettings:
    return AutomationSettings(user_id=OWNER.id, **{"times": ["09:00", "18:00"], "timezone": "Europe/Berlin", **kwargs})


# ---------- validation ----------
@pytest.mark.parametrize("kwargs", [
    {"times": ["9:00"]}, {"times": ["24:00"]}, {"times": []}, {"every_minutes": 10}, {"days": []}, {"days": [7]},
    {"times": ["09:00"], "timezone": "Mars/Olympus"},
])
def test_invalid_schedules_are_refused(kwargs):
    with pytest.raises(ValidationError):
        AutomationSchedule(**kwargs)


def test_times_and_days_are_sorted_without_duplicates():
    schedule = AutomationSchedule(times=["18:00", "09:00", "18:00"], days=[4, 0, 4])
    assert schedule.times == ["09:00", "18:00"] and schedule.days == [0, 4]


def test_manual_needs_no_time():
    assert AutomationSchedule(mode="manual").mode == "manual"


# ---------- the clock ----------
def test_next_time_of_day_in_the_users_time_zone():
    s = _settings()  # Berlin is UTC+1 in November
    assert automation.next_time(s, _utc(2026, 11, 17, 7, 0)) == _utc(2026, 11, 17, 8, 0)  # 09:00 Berlin
    assert automation.next_time(s, _utc(2026, 11, 17, 8, 0)) == _utc(2026, 11, 17, 17, 0)  # strictly after: 18:00
    assert automation.next_time(s, _utc(2026, 11, 17, 20, 0)) == _utc(2026, 11, 18, 8, 0)  # tomorrow 09:00


def test_only_on_the_chosen_days():
    s = _settings(times=["09:00"], days=[0, 1, 2, 3, 4])  # Mon–Fri
    friday_evening = _utc(2026, 11, 20, 20, 0)
    assert automation.next_time(s, friday_evening) == _utc(2026, 11, 23, 8, 0)  # Monday


def test_daylight_saving_time_is_followed():
    s = _settings(times=["09:00"])  # Berlin: UTC+2 until 25 Oct 2026, then UTC+1
    assert automation.next_time(s, _utc(2026, 10, 24, 12, 0)) == _utc(2026, 10, 25, 8, 0)
    assert automation.next_time(s, _utc(2026, 10, 23, 12, 0)) == _utc(2026, 10, 24, 7, 0)


def test_every_n_minutes():
    s = _settings(times=[], every_minutes=180)
    assert automation.next_time(s, _utc(2026, 11, 17, 10, 0)) == _utc(2026, 11, 17, 13, 0)


def test_every_n_minutes_skips_to_the_next_allowed_day():
    s = _settings(times=[], every_minutes=120, days=[0])  # Mondays only
    tuesday = _utc(2026, 11, 17, 10, 0)
    assert automation.next_time(s, tuesday) == _utc(2026, 11, 22, 23, 0)  # Monday 00:00 Berlin


def test_manual_never_runs_on_its_own():
    assert automation.next_time(_settings(mode="manual"), _utc(2026, 11, 17)) is None


def test_due_counts_from_the_later_of_last_run_and_save():
    s = _settings(saved_at=_utc(2026, 11, 17, 10, 0), last_run_at=_utc(2026, 11, 16, 17, 0))
    assert not automation.is_due(s, _utc(2026, 11, 17, 16, 59))
    assert automation.is_due(s, _utc(2026, 11, 17, 17, 0))  # 18:00 Berlin


def test_a_missed_run_is_made_up_once():
    s = _settings(last_run_at=_utc(2026, 11, 14, 17, 0))  # server off for days
    now = _utc(2026, 11, 17, 12, 0)
    assert automation.is_due(s, now)
    assert not automation.is_due(s.model_copy(update={"last_run_at": now}), now + timedelta(minutes=5))


def test_describe():
    assert automation.describe(_settings()) == "every day at 09:00, 18:00 (Europe/Berlin)"
    assert automation.describe(_settings(times=[], every_minutes=240, days=[0, 1, 2, 3, 4])) == \
        "Mon–Fri every 4 h (Europe/Berlin)"
    assert automation.describe(_settings(mode="manual")).startswith("manual")


# ---------- saving and the last run ----------
def test_defaults_follow_the_old_interval(monkeypatch):
    monkeypatch.setattr(config, "FACEBOOK_INBOX_INTERVAL", 30)
    s = automation.schedule_of(OWNER.id)
    assert s.mode == "scheduled" and s.every_minutes == 30 and s.saved_at is None
    monkeypatch.setattr(config, "FACEBOOK_INBOX_INTERVAL", 0)
    assert automation.schedule_of(OWNER.id, fresh=True).mode == "manual"


def test_save_keeps_the_last_run():
    automation.mark_run(OWNER.id, _utc(2026, 11, 17, 8, 0))
    saved = automation.save(OWNER.id, AutomationSchedule(times=["07:30"], timezone="Europe/Berlin"))
    assert saved.last_run_at == _utc(2026, 11, 17, 8, 0) and saved.saved_at is not None
    assert records.get_automation_settings(OWNER.id).times == ["07:30"]


def test_a_run_is_kept_in_memory_when_the_database_fails(monkeypatch):
    automation.save(OWNER.id, AutomationSchedule(every_minutes=60))

    def fail(settings):
        raise OSError("database down")

    monkeypatch.setattr(records, "save_automation_settings", fail)
    ran = datetime.now(UTC) + timedelta(hours=2)
    automation.mark_run(OWNER.id, ran)
    assert not automation.is_due(automation.schedule_of(OWNER.id), ran + timedelta(minutes=30))


def test_inbox_due_without_an_owner(monkeypatch):
    monkeypatch.setattr(automation, "inbox_owner", lambda: None)
    assert not automation.inbox_due(_utc(2030, 1, 1))


# ---------- API ----------
@pytest.fixture
def client():
    app = FastAPI()
    app.include_router(automation_api.router)
    sign_in(app)
    return app, TestClient(app)


def test_get_returns_defaults_and_why_it_does_not_run(client):
    _, c = client
    body = c.get("/automation").json()
    assert body["saved"] is False and body["active"] is False and "not running" in body["note"]


def test_put_saves_and_reports_the_next_run(client, monkeypatch):
    monkeypatch.setattr(page_inbox_worker, "_worker", object())
    _, c = client
    r = c.put("/automation", json={"mode": "scheduled", "times": ["09:00"], "days": [0, 1, 2, 3, 4, 5, 6],
                                   "timezone": "Europe/Berlin", "every_minutes": 0})
    assert r.status_code == 200
    body = r.json()
    assert body["saved"] and body["active"] and body["note"] == "" and body["next_run"]
    assert body["schedule"]["times"] == ["09:00"]


def test_put_refuses_an_invalid_schedule(client):
    _, c = client
    assert c.put("/automation", json={"mode": "scheduled", "times": [], "every_minutes": 0}).status_code == 422


def test_schedule_of_another_user_is_saved_but_not_active(client, monkeypatch):
    monkeypatch.setattr(page_inbox_worker, "_worker", object())
    app, c = client
    sign_in(app, STRANGER)
    body = c.put("/automation", json={"mode": "manual"}).json()
    assert body["saved"] and not body["active"] and "other books" in body["note"]
    assert c.post("/automation/run").status_code == 409


def test_run_now(client, monkeypatch):
    asked = []
    monkeypatch.setattr(page_inbox_worker, "_worker", type("W", (), {"request_run": lambda self: asked.append(1)})())
    _, c = client
    assert c.post("/automation/run").status_code == 202 and asked == [1]


def test_run_now_without_the_worker(client):
    _, c = client
    assert c.post("/automation/run").status_code == 409


# ---------- pause ----------
def test_a_paused_schedule_is_never_due():
    s = _settings(paused=True, last_run_at=_utc(2026, 11, 1))
    assert not automation.is_due(s, _utc(2026, 11, 17))


def test_resume_counts_from_now_and_save_keeps_the_pause():
    automation.save(OWNER.id, AutomationSchedule(every_minutes=60))
    automation.set_paused(OWNER.id, True)
    saved = automation.save(OWNER.id, AutomationSchedule(every_minutes=120))
    assert saved.paused  # saving the schedule does not resume it
    resumed = automation.set_paused(OWNER.id, False)
    assert not resumed.paused and automation.reference(resumed) == resumed.resumed_at


def test_api_pause_and_cycles(client):
    from app.agents.cycle import Cycle
    _, c = client
    body = c.put("/automation/paused", json={"paused": True}).json()
    assert body["paused"] and body["next_run"] is None
    assert c.put("/automation/paused", json={"paused": False}).json()["paused"] is False
    cycle = Cycle(OWNER.id, "app")
    cycle.finish("error", "token expired")
    [listed] = c.get("/automation/cycles").json()
    assert listed["status"] == "error" and listed["trigger"] == "app"
