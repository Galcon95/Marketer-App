"""Tests of the limits (limits.toml, limits.py) and their enforcement: reading and checking the file, the cost
budgets per user (day, month) and for the whole app, requests per minute per user, books per library, and that every
model call in the usage log knows the user who caused it."""

from datetime import datetime, timedelta, timezone

import pytest
from fastapi import BackgroundTasks, Depends, FastAPI
from fastapi.testclient import TestClient

from app.api import deps, health, knowledge, projects, sources
from app.core import limits, logs, usage
from app.core import state as db
from app.core.limits import AppWide, Limits, LimitsError, PerUser
from app.core.schemas import Source, UsageRecord
from app.db import records
from tests.conftest import OWNER, STRANGER, sign_in

pytestmark = pytest.mark.usefixtures("offline")  # requests that pass every limit end at "no API key" (503)

PROJECT = db.DEFAULT_PROJECT_ID
SEARCH = f"/projects/{PROJECT}/search"
NOW = datetime.now(timezone.utc)


# ---------- Reading limits.toml ----------

def test_the_shipped_file_has_the_agreed_limits():
    assert limits.load() == Limits(
        per_user=PerUser(model_requests_per_minute=20, cost_per_day_usd=1.0, cost_per_month_usd=10.0, max_books=20,
                         max_upload_mb=50, max_server_upload_mb=500, max_api_keys=10),
        app=AppWide(cost_per_day_usd=20.0))


def test_missing_file_or_values_keep_the_defaults(tmp_path):
    assert limits.load(tmp_path / "missing.toml", environ={}) == Limits(per_user=PerUser(), app=AppWide())
    path = tmp_path / "limits.toml"
    path.write_text("[per_user]\ncost_per_day_usd = 0.5\n", encoding="utf-8")
    loaded = limits.load(path, environ={})
    assert loaded.per_user.cost_per_day_usd == 0.5 and loaded.per_user.max_books == PerUser().max_books


def test_environment_variables_override_the_file(tmp_path):
    path = tmp_path / "limits.toml"
    path.write_text("[per_user]\ncost_per_day_usd = 0.5\n", encoding="utf-8")
    loaded = limits.load(path, environ={"LIMIT_PER_USER_COST_PER_DAY_USD": "2", "LIMIT_APP_COST_PER_DAY_USD": "5.5"})
    assert (loaded.per_user.cost_per_day_usd, loaded.app.cost_per_day_usd) == (2.0, 5.5)


@pytest.mark.parametrize("text", [
    "[per_user]\ncost_per_day_usd = 0\n",  # no "unlimited"
    "[per_user]\ncost_per_day_usd = -1\n",
    '[per_user]\ncost_per_day_usd = "lots"\n',
    "[per_user]\nmax_books = 2.5\n",  # a whole number
    "[per_user]\nmax_books = true\n",
    "[per_user]\ncost_per_dai_usd = 1\n",  # typo: unknown name
    "[per-user]\ncost_per_day_usd = 1\n",  # typo: unknown section
    "[per_user\n",  # not TOML
])
def test_invalid_files_stop_the_server(tmp_path, text):
    path = tmp_path / "limits.toml"
    path.write_text(text, encoding="utf-8")
    with pytest.raises(LimitsError):
        limits.load(path, environ={})


def test_an_invalid_environment_variable_stops_the_server(tmp_path):
    with pytest.raises(LimitsError, match="LIMIT_PER_USER_MAX_BOOKS"):
        limits.load(tmp_path / "missing.toml", environ={"LIMIT_PER_USER_MAX_BOOKS": "0"})


# ---------- Enforcement ----------

@pytest.fixture
def app():
    """The project, sources, knowledge and health routers; fresh rate limit counters."""
    deps._llm_calls.clear()
    app = FastAPI()
    for module in (projects, sources, knowledge, health):
        app.include_router(module.router)
    yield app
    deps._llm_calls.clear()


def client_for(app: FastAPI, user) -> TestClient:
    sign_in(app, user)
    return TestClient(app)


def spend(cost: float, user_id: str | None, when: datetime = NOW, project_id: str | None = PROJECT) -> None:
    """Pretend a model call of `cost` USD was made (added to the usage log)."""
    records.add_usage(UsageRecord(
        timestamp=when, operation="ask/answer", kind="chat", model="m", input_tokens=1, output_tokens=1,
        input_cost=cost, output_cost=0.0, cost=cost, cost_source="estimate", project_id=project_id, user_id=user_id))


def search(client: TestClient, project: str = PROJECT):
    return client.post(f"/projects/{project}/search", json={"query": "garden cities"})


def test_under_every_limit_the_request_goes_through(app):
    spend(0.50, OWNER.id)
    assert search(client_for(app, OWNER)).status_code == 503  # passed the limits; no API key in tests


def test_daily_budget_blocks_until_midnight(app):
    spend(0.60, OWNER.id)
    spend(0.45, OWNER.id)
    spend(5.00, OWNER.id, when=NOW - timedelta(days=40))  # long ago: not today, not this month
    response = search(client_for(app, OWNER))
    assert response.status_code == 429
    assert "daily budget of $1.00" in response.json()["detail"]
    assert 0 < int(response.headers["Retry-After"]) <= 24 * 3600 + 1


def test_no_model_call_when_the_costs_cannot_be_read(app, monkeypatch):
    """Fail closed: without the costs so far, a budget could be overrun, so the request stops before the model."""
    from app.db.database import DatabaseError

    def broken(*args):
        raise DatabaseError("Database error (OperationalError)")
    monkeypatch.setattr(records, "spending", broken)
    response = search(client_for(app, OWNER))
    assert response.status_code == 503 and "budget cannot be checked" in response.json()["detail"]


def test_monthly_budget_blocks(app):
    spend(10.00, OWNER.id)
    response = search(client_for(app, OWNER))
    assert response.status_code == 429
    assert "monthly budget of $10.00" in response.json()["detail"]


def test_one_users_spending_does_not_block_another(app):
    spend(5.00, OWNER.id)
    stranger = client_for(app, STRANGER)
    own = stranger.get("/me").json()["project"]["id"]
    assert search(stranger, own).status_code == 503


def test_calls_from_before_sign_in_count_for_the_owner_of_their_project(app):
    spend(1.00, None)  # an old record without user id, in the default project
    assert search(client_for(app, OWNER)).status_code == 429


def test_the_apps_daily_budget_blocks_everyone(app):
    for i in range(5):
        spend(4.00, f"user-{i}", project_id=None)  # $20 by others, none over their own budget
    response = search(client_for(app, OWNER))
    assert response.status_code == 429
    assert "app's daily budget" in response.json()["detail"]


def test_requests_per_minute_count_per_user(app, monkeypatch):
    monkeypatch.setattr(deps, "LIMITS", Limits(per_user=PerUser(model_requests_per_minute=2), app=AppWide()))
    owner = client_for(app, OWNER)
    assert [search(owner).status_code for _ in range(3)] == [503, 503, 429]
    stranger = client_for(app, STRANGER)
    own = stranger.get("/me").json()["project"]["id"]
    assert search(stranger, own).status_code == 503  # a separate counter


def test_a_full_library_rejects_another_book(app, monkeypatch):
    monkeypatch.setattr(sources, "LIMITS", Limits(per_user=PerUser(max_books=1), app=AppWide()))
    db.sources["src_a"] = Source(id="src_a", project_id=PROJECT, filename="a.pdf", kind="document", size_bytes=1,
                                 status="ready", progress=100, chunk_count=0, created_at=NOW)
    try:
        response = client_for(app, OWNER).post(f"/projects/{PROJECT}/sources",
                                               files={"file": ("b.pdf", b"%PDF-1.4\n", "application/pdf")})
    finally:
        db.sources.pop("src_a", None)
    assert response.status_code == 409
    assert "at most 1 books" in response.json()["detail"]


# ---------- Usage per user ----------

def test_usage_shows_your_own_calls_and_budget(app, monkeypatch):
    spend(0.25, OWNER.id)
    spend(0.75, STRANGER.id, project_id=None)
    report = client_for(app, OWNER).get("/usage").json()
    assert report["totals"]["cost"] == pytest.approx(0.25)
    assert [r["user_id"] for r in report["recent"]] == [OWNER.id]
    assert report["budget"] == {"spent_today": pytest.approx(0.25), "limit_today": 1.0,
                                "spent_month": pytest.approx(0.25), "limit_month": 10.0}


def test_each_model_call_is_logged_with_the_user_who_caused_it(monkeypatch):
    """The sign-in check runs in a worker thread and the call may run in a background task, after the response:
    the user still reaches the usage log (logs.set_request_user)."""
    app = FastAPI()

    def signed_in() -> None:  # like auth.current_user (a sync dependency)
        logs.set_request_user("user-ada")

    def model_call() -> None:
        usage.record_embedding("search/embed_query", "text-embedding-3-small", tokens=10)

    @app.post("/work", dependencies=[Depends(signed_in)])
    def work(background_tasks: BackgroundTasks):
        model_call()
        background_tasks.add_task(model_call)

    app.add_middleware(logs.RequestIdMiddleware)
    with TestClient(app) as client:
        client.post("/work")
    assert [r.user_id for r in records.recent_usage(10)] == ["user-ada", "user-ada"]
    assert logs.current_user_id() is None  # nothing is left over outside the request
