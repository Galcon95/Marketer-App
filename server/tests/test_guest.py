"""Tests of the public demo's shared guest account (GUEST_EMAIL, core/guest.py): what it may not do (no_guest in
api/deps.py, and the MCP servers), its own limits ([guest] in limits.toml), GET /me telling the app it is the guest,
and "Try as guest" (POST /guest, api/guest.py) with a fake Supabase: the session without the password, the fresh start
after 15 quiet minutes (books stay), joining an active visitor, a changed password. Every other user keeps all of it."""

import json
from datetime import datetime, timedelta, timezone

import anyio
import httpx
import pytest
from fastapi import FastAPI, HTTPException, Request
from fastapi.testclient import TestClient

import server
from app.api import deps, health, knowledge, projects, sources
from app.api import guest as guest_api
from app.core import accounts, ad_images, auth, guest, mcp_auth
from app.core import state as db
from app.core.auth import User
from app.core.schemas import AdImage, Asset, BookSummary, Conversation, DiscussionAnalysis, Source, UsageRecord
from app.db import records
from tests.conftest import OWNER, STRANGER, sign_in
from tests.test_routes_need_sign_in import OPEN

PROJECT = db.DEFAULT_PROJECT_ID

GUEST = User(id="user-guest", email="Guest@Demo.example")  # the email's case does not matter
NOW = datetime.now(timezone.utc)
DEMO = "Not available in the demo"

pytestmark = pytest.mark.usefixtures("offline")  # nothing here may reach a model, Facebook or Google

# What the guest may not do: change the library, create API keys, connect or post to Facebook or YouTube, run the agent.
BLOCKED = [
    ("POST", "/projects/x/sources"), ("POST", "/sources/x/ingest"), ("DELETE", "/sources/x"),
    ("PUT", "/sources/x/cover"),
    ("POST", "/api-keys"), ("DELETE", "/api-keys/x"),
    ("POST", "/facebook/connect"), ("POST", "/facebook/connect/pages/x"), ("DELETE", "/facebook/connection"),
    ("POST", "/assets/x/publish/facebook"), ("POST", "/ad-images/x/publish/facebook"),
    ("POST", "/discussions/x/reply/facebook"),
    ("POST", "/youtube/connect"), ("DELETE", "/youtube/connection"), ("POST", "/discussions/x/reply/youtube"),
    ("PUT", "/automation"), ("POST", "/automation/run"), ("PUT", "/automation/paused"),
    ("POST", "/sources/x/summary"),  # would cost money and replace a demo book's summary for good
]


@pytest.fixture(autouse=True)
def guest_email(monkeypatch):
    monkeypatch.setattr(guest, "GUEST_EMAIL", "guest@demo.example")
    deps._llm_calls.clear()
    yield
    deps._llm_calls.clear()


@pytest.fixture
def app_as():
    """The whole app (server.py), signed in as the given user; the overrides are removed afterwards."""
    def make(user: User) -> TestClient:
        sign_in(server.app, user)
        return TestClient(server.app)
    yield make
    server.app.dependency_overrides.clear()


def test_only_the_guest_email_is_the_guest(monkeypatch):
    assert accounts.is_guest(GUEST)
    assert not accounts.is_guest(OWNER) and not accounts.is_guest(STRANGER)
    monkeypatch.setattr(guest, "GUEST_EMAIL", "")
    assert not accounts.is_guest(GUEST)  # without GUEST_EMAIL there is no guest


def test_the_blocked_routes_exist():
    """A renamed route would silently drop out of the list below."""
    from tests.test_routes_need_sign_in import API_ROUTES
    known = set(API_ROUTES)
    for method, path in BLOCKED:
        assert any(m == method and _matches(p, path) for m, p in known), f"{method} {path} is not a route"


def _matches(pattern: str, path: str) -> bool:
    parts, wanted = pattern.split("/"), path.split("/")
    return len(parts) == len(wanted) and all(p == w or p.startswith("{") for p, w in zip(parts, wanted))


@pytest.mark.parametrize(("method", "path"), BLOCKED, ids=lambda v: v)
def test_the_guest_cannot(app_as, method, path):
    response = app_as(GUEST).request(method, path)
    assert response.status_code == 403
    assert DEMO in response.json()["detail"]


@pytest.mark.parametrize(("method", "path"), BLOCKED, ids=lambda v: v)
def test_everyone_else_is_not_stopped_by_the_demo_rule(app_as, method, path):
    response = app_as(STRANGER).request(method, path)
    assert DEMO not in response.text  # 404, 409 or 422 here (no such id, no body), but never the demo's 403


def test_the_guest_can_still_use_the_app(app_as):
    client = app_as(GUEST)
    me = client.get("/me")
    assert me.status_code == 200 and me.json()["guest"] is True and me.json()["admin"] is False
    assert client.get(f"/projects/{me.json()['project']['id']}/sources").status_code == 200
    assert client.get("/api-keys").json() == []


def test_me_says_no_guest_for_everyone_else(app_as):
    assert app_as(STRANGER).get("/me").json()["guest"] is False


# ---------- The guest's own limits ----------

@pytest.fixture
def limits_app():
    app = FastAPI()
    for module in (projects, sources, knowledge, health):
        app.include_router(module.router)
    return app


def spend(cost: float, user_id: str) -> None:
    records.add_usage(UsageRecord(
        timestamp=NOW, operation="ask/answer", kind="chat", model="m", input_tokens=1, output_tokens=1,
        input_cost=cost, output_cost=0.0, cost=cost, cost_source="estimate", project_id=None, user_id=user_id))


def search_as(app: FastAPI, user: User):
    sign_in(app, user)
    client = TestClient(app)
    project = client.get("/me").json()["project"]["id"]
    return client.post(f"/projects/{project}/search", json={"query": "garden cities"})


def test_the_guest_has_the_smaller_daily_budget(limits_app):
    spend(0.55, GUEST.id)
    spend(0.55, STRANGER.id)
    blocked = search_as(limits_app, GUEST)
    assert blocked.status_code == 429
    assert "The demo's daily budget of $0.50" in blocked.json()["detail"]
    assert search_as(limits_app, STRANGER).status_code == 503  # under $1.00: passed the limits; no API key in tests


def test_the_guest_has_fewer_requests_per_minute(limits_app):
    statuses = [search_as(limits_app, GUEST).status_code for _ in range(deps.LIMITS.guest.model_requests_per_minute)]
    assert set(statuses) == {503}
    assert search_as(limits_app, GUEST).status_code == 429
    assert deps.LIMITS.guest.model_requests_per_minute < deps.LIMITS.per_user.model_requests_per_minute


# ---------- The MCP servers ----------

@pytest.mark.parametrize(("user", "allowed"), [(GUEST, False), (OWNER, True)])
def test_the_mcp_servers_refuse_the_guests_sign_in(monkeypatch, user, allowed):
    monkeypatch.setattr(mcp_auth, "verify_token", lambda token: user)
    if allowed:
        assert anyio.run(mcp_auth.authenticate, "Bearer token") == user
    else:
        with pytest.raises(HTTPException) as refused:
            anyio.run(mcp_auth.authenticate, "Bearer token")
        assert refused.value.status_code == 403 and DEMO in refused.value.detail


# ---------- "Try as guest" (POST /guest) ----------

class FakeSupabase:
    """Supabase Auth's admin and sign-in endpoints, for the guest only. `password` is the guest's real password."""

    def __init__(self):
        self.password = "set-in-the-dashboard"
        self.calls: list[str] = []
        self.down = False

    def handle(self, request: httpx.Request) -> httpx.Response:
        if self.down:
            raise httpx.ConnectError("no network")
        self.calls.append(f"{request.method} {request.url.path}")
        assert request.headers["apikey"] == "sb_secret_test"
        if request.method == "GET" and request.url.path == "/auth/v1/admin/users":
            return httpx.Response(200, json={"users": [{"id": "someone", "email": "owner@example.com"},
                                                       {"id": GUEST.id, "email": "guest@demo.example"}]})
        if request.method == "PUT" and request.url.path == f"/auth/v1/admin/users/{GUEST.id}":
            body = json.loads(request.content)
            assert body["email_confirm"] is True  # also confirms an account made without "Auto Confirm User"
            assert body["email"] == "guest@demo.example"  # sets back an email a visitor may have changed
            self.password = body["password"]
            return httpx.Response(200, json={"id": GUEST.id})
        if request.method == "POST" and request.url.path == "/auth/v1/token":
            body = json.loads(request.content)
            if body["email"] != "guest@demo.example" or body["password"] != self.password:
                return httpx.Response(400, json={"error": "invalid_grant"})
            return httpx.Response(200, json={"access_token": "access", "refresh_token": "refresh", "expires_in": 3600,
                                             "user": {"id": GUEST.id}})
        return httpx.Response(404)


@pytest.fixture
def supabase(monkeypatch):
    fake = FakeSupabase()
    monkeypatch.setattr(guest, "SUPABASE_URL", "https://example.supabase.co")
    monkeypatch.setattr(guest, "SUPABASE_SECRET_KEY", "sb_secret_test")
    monkeypatch.setattr(guest, "_client", lambda: httpx.Client(
        base_url="https://example.supabase.co/auth/v1", transport=httpx.MockTransport(fake.handle),
        headers={"apikey": "sb_secret_test", "Authorization": "Bearer sb_secret_test"}))
    guest.forget()
    guest_api._starts.clear()
    guest_api._per_visitor.clear()
    yield fake
    guest.forget()
    guest_api._starts.clear()
    guest_api._per_visitor.clear()


def _picture(project_id: str) -> AdImage:
    return AdImage(id="img_guest", project_id=project_id, asset_id="ast_guest", source_id="src_demo", format="square",
                   headline="", scene="s", model="m", prompt_version="1", created_at=NOW)


@pytest.fixture
def guest_project(monkeypatch):
    """The guest's project with one book (with summary), and in it what visitors made: a post with a picture, a chat,
    a discussion analysis and a Substack name. OWNER's default project has a post too."""
    monkeypatch.setattr(db, "sources", {})
    monkeypatch.setattr(db, "summaries", {})
    monkeypatch.setattr(db, "assets", {})
    monkeypatch.setattr(db, "conversations", {})
    project = accounts.client_of(GUEST).model_copy(update={"substack": "someblog"})
    records.save_project(project)
    db.projects[project.id] = project
    book = Source(id="src_demo", project_id=project.id, filename="demo.pdf", kind="document", size_bytes=1,
                  status="ready", progress=100, chunk_count=0, created_at=NOW)
    db.sources["src_demo"] = book
    records.add_source(book)
    db.summaries["src_demo"] = BookSummary(source_id="src_demo", summary="s", themes=[], chapters=[], model="m",
                                           tokens=0, created_at=NOW)
    for asset_id, project_id in (("ast_guest", project.id), ("ast_owner", PROJECT)):
        asset = Asset(id=asset_id, project_id=project_id, asset_type="blurb", grounded=False, brief="b", text="t",
                      citations=[], created_at=NOW)
        db.assets[asset_id] = asset
        records.save_assets([asset])
    records.save_ad_image(_picture(project.id))
    chat = Conversation(id="cnv_guest", project_id=project.id, title="q", created_at=NOW, updated_at=NOW)
    db.conversations["cnv_guest"] = chat
    records.save_conversation(chat)
    records.save_discussion(DiscussionAnalysis(id="dsc_guest", project_id=project.id, source_id="src_demo",
                                               discussion="d", recommendation="skip", reason="r", created_at=NOW,
                                               updated_at=NOW))
    return project


def try_as_guest(ip: str | None = None) -> httpx.Response:
    """POST /guest, from a visitor's address as Render's proxy reports it (None: the test client, which is exempt)."""
    headers = {"X-Forwarded-For": ip} if ip else {}
    return TestClient(server.app).post("/guest", headers=headers)


def test_the_visitor_gets_a_session_but_never_the_password(supabase):
    response = try_as_guest()
    assert response.status_code == 200
    assert response.json() == {"access_token": "access", "refresh_token": "refresh", "expires_in": 3600}
    assert supabase.password != "set-in-the-dashboard"  # the server set its own
    assert supabase.password not in response.text
    assert not guest.idle()


def test_after_15_quiet_minutes_the_demo_starts_afresh(supabase, guest_project, monkeypatch):
    deleted: list[list[str]] = []
    monkeypatch.setattr(ad_images, "delete_files", deleted.append)
    assert try_as_guest().status_code == 200
    assert "ast_guest" not in db.assets and "cnv_guest" not in db.conversations
    assert records.get_ad_image("img_guest") is None and records.get_discussion("dsc_guest") is None
    assert db.projects[guest_project.id].substack == ""
    assert deleted == [[ad_images.image_path(_picture(guest_project.id))]]
    assert "src_demo" in db.sources and "src_demo" in db.summaries  # the books stay
    assert "ast_owner" in db.assets  # nobody else's things are touched


def test_while_a_visitor_is_active_the_next_one_joins_them(supabase, guest_project):
    assert try_as_guest().status_code == 200  # the first visitor: afresh
    db.assets["ast_new"] = db.assets["ast_owner"].model_copy(update={"id": "ast_new", "project_id": guest_project.id})
    password, calls = supabase.password, len(supabase.calls)
    guest.seen()  # the first visitor is still working
    assert try_as_guest().status_code == 200
    assert "ast_new" in db.assets  # their work stays
    assert supabase.password == password and supabase.calls[calls:] == ["POST /auth/v1/token"]


def test_the_demo_starts_afresh_once_the_guest_was_quiet_for_15_minutes(supabase, guest_project):
    assert try_as_guest().status_code == 200
    db.assets["ast_new"] = db.assets["ast_owner"].model_copy(update={"id": "ast_new", "project_id": guest_project.id})
    guest.seen(datetime.now(timezone.utc) - guest.IDLE - timedelta(seconds=1))
    assert try_as_guest().status_code == 200
    assert "ast_new" not in db.assets


def test_a_password_changed_by_a_visitor_is_replaced(supabase):
    assert try_as_guest().status_code == 200
    guest.seen()
    supabase.password = "changed-by-a-visitor"
    assert try_as_guest().status_code == 200
    assert supabase.password != "changed-by-a-visitor"


def test_no_demo_without_the_settings(supabase, monkeypatch):
    monkeypatch.setattr(guest, "GUEST_EMAIL", "")
    assert try_as_guest().status_code == 404
    assert supabase.calls == []


def test_supabase_down_answers_503(supabase):
    supabase.down = True
    response = try_as_guest()
    assert response.status_code == 503 and "cannot start right now" in response.json()["detail"]


def test_a_missing_guest_user_answers_503(supabase, monkeypatch):
    monkeypatch.setattr(guest, "GUEST_EMAIL", "nobody@demo.example")
    assert try_as_guest().status_code == 503


def test_too_many_starts_a_minute_are_refused(supabase, monkeypatch):
    monkeypatch.setattr(guest_api, "STARTS_PER_MINUTE", 2)
    assert [try_as_guest().status_code for _ in range(3)] == [200, 200, 429]


def _token(session_id: str) -> str:
    """An access token as Supabase gives it, with only what start_session reads (not signed)."""
    import jwt
    return jwt.encode({"sub": GUEST.id, "session_id": session_id}, "test-secret-of-32-bytes-at-least!!", "HS256")


def _guest_request(monkeypatch, session_id: str):
    monkeypatch.setattr(auth, "verify_token", lambda token: GUEST.model_copy(update={"session_id": session_id}))
    return lambda: auth.current_user(Request({"type": "http", "headers": [(b"authorization", b"Bearer t")]}))


def test_a_guest_session_ends_after_its_time(monkeypatch):
    guest.forget()
    started = datetime.now(timezone.utc) - timedelta(minutes=59)
    guest.start_session(_token("sess-1"), now=started)
    request = _guest_request(monkeypatch, "sess-1")
    assert request().id == GUEST.id  # within the hour: the browser's renewed token still works
    guest.start_session(_token("sess-1"), now=started - timedelta(minutes=2))  # now 61 minutes old
    with pytest.raises(HTTPException) as ended:
        request()
    assert ended.value.status_code == 401 and "guest session has ended" in ended.value.detail


def test_an_unknown_guest_session_is_refused(monkeypatch):
    guest.forget()  # e.g. a session from before a server restart, or one made with a stolen password
    with pytest.raises(HTTPException) as refused:
        _guest_request(monkeypatch, "sess-old")()
    assert refused.value.status_code == 401
    with pytest.raises(HTTPException):
        _guest_request(monkeypatch, "")()  # a token without a session id


def test_a_fresh_start_ends_the_earlier_guest_sessions(monkeypatch):
    guest.forget()
    guest.start_session(_token("sess-1"))
    guest.end_sessions()
    guest.start_session(_token("sess-2"))
    assert not guest.session_ok("sess-1") and guest.session_ok("sess-2")


# ---------- Sessions survive a server restart ----------
def _restarted(monkeypatch, minutes_ago: int = 1, last_reset: datetime | None = None):
    """As if this server started `minutes_ago`, with the demo's last fresh start (from the audit log) `last_reset`."""
    guest.forget()
    monkeypatch.setattr(guest, "_server_started", datetime.now(timezone.utc) - timedelta(minutes=minutes_ago))
    monkeypatch.setattr(guest, "_latest_event", lambda action: last_reset if action == "guest.reset" else None)


def test_a_session_from_before_a_restart_goes_on(monkeypatch):
    _restarted(monkeypatch, last_reset=datetime.now(timezone.utc) - timedelta(minutes=30))
    signed_in = datetime.now(timezone.utc) - timedelta(minutes=10)
    assert guest.session_ok("sess-1", signed_in)
    assert guest.session_ok("sess-1")  # known from now on, also without the time


def test_a_session_from_before_a_restart_still_ends_after_its_time(monkeypatch):
    _restarted(monkeypatch)
    assert not guest.session_ok("sess-1", datetime.now(timezone.utc) - timedelta(minutes=61))


def test_a_session_from_before_the_last_fresh_start_stays_ended(monkeypatch):
    _restarted(monkeypatch, last_reset=datetime.now(timezone.utc) - timedelta(minutes=5))
    assert not guest.session_ok("sess-1", datetime.now(timezone.utc) - timedelta(minutes=20))
    # the visitor whose "Try as guest" started that fresh start signed in a moment after it was logged
    assert guest.session_ok("sess-2", datetime.now(timezone.utc) - timedelta(minutes=5, seconds=1))


def test_a_session_begun_while_the_server_runs_must_be_registered(monkeypatch):
    """A sign-in with the guest's password from elsewhere (not through "Try as guest") is still refused."""
    _restarted(monkeypatch, minutes_ago=30)
    assert not guest.session_ok("sess-1", datetime.now(timezone.utc) - timedelta(minutes=5))
    assert not guest.session_ok("sess-2", None)  # a token without a sign-in time


def test_a_restart_does_not_sign_the_guest_out(monkeypatch):
    _restarted(monkeypatch)
    started = datetime.now(timezone.utc) - timedelta(minutes=10)
    monkeypatch.setattr(auth, "verify_token", lambda token: GUEST.model_copy(
        update={"session_id": "sess-1", "signed_in_at": started}))
    assert auth.current_user(Request({"type": "http", "headers": [(b"authorization", b"Bearer t")]})).id == GUEST.id


def test_the_sign_in_time_comes_from_the_tokens_amr():
    assert auth.signed_in_at({"amr": [{"method": "password", "timestamp": 1764250000}]}) == datetime(
        2025, 11, 27, 13, 26, 40, tzinfo=timezone.utc)
    assert auth.signed_in_at({"amr": [{"method": "password", "timestamp": 10}, {"method": "otp", "timestamp": 20}]}) \
        == datetime.fromtimestamp(20, timezone.utc)
    assert auth.signed_in_at({}) is None and auth.signed_in_at({"amr": [{"method": "x"}, "y"]}) is None


def test_a_restart_does_not_start_the_demo_afresh_while_a_session_may_run(monkeypatch):
    guest.forget()
    now = datetime.now(timezone.utc)
    monkeypatch.setattr(guest, "_latest_event", lambda action: now - timedelta(minutes=20))
    assert not guest.idle(now)  # someone pressed "Try as guest" 20 minutes ago: their hour is not over
    monkeypatch.setattr(guest, "_latest_event", lambda action: now - timedelta(minutes=61))
    assert guest.idle(now)
    monkeypatch.setattr(guest, "_latest_event", lambda action: None)
    assert guest.idle(now)  # never started (or the log cannot be read)


def test_the_last_events_are_read_from_the_audit_log():
    from app.core import audit
    audit.record("guest.reset", detail="0 things deleted")
    latest = guest._latest_event("guest.reset")
    assert latest is not None and latest.tzinfo is not None
    assert datetime.now(timezone.utc) - latest < timedelta(minutes=1)


def test_a_fresh_start_is_remembered_without_the_log(monkeypatch):
    guest.forget()
    monkeypatch.setattr(guest, "_latest_event", lambda action: pytest.fail("the log is not needed"))
    guest.end_sessions()
    assert guest._last_reset() is not None


def test_try_as_guest_registers_its_session(supabase, monkeypatch):
    guest.forget()
    monkeypatch.setattr(guest, "start_session", lambda token: started.append(token))
    started = []
    assert try_as_guest().status_code == 200 and started == ["access"]


def test_other_users_have_no_session_limit(monkeypatch):
    guest.forget()
    monkeypatch.setattr(auth, "verify_token", lambda token: STRANGER)
    assert auth.current_user(Request({"type": "http", "headers": [(b"authorization", b"Bearer t")]})) == STRANGER


def test_every_signed_in_guest_request_counts_as_activity(monkeypatch):
    guest.forget()
    guest.start_session(_token("sess-1"))
    monkeypatch.setattr(auth, "verify_token", lambda token: GUEST.model_copy(update={"session_id": "sess-1"}))
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer t")]})
    assert auth.current_user(request).id == GUEST.id
    assert not guest.idle()
    guest.forget()
    monkeypatch.setattr(auth, "verify_token", lambda token: STRANGER)
    auth.current_user(request)
    assert guest.idle()  # other users do not keep the demo from starting afresh


# ---------- Protection against abuse ----------

def test_each_address_may_start_the_demo_twice_a_day(supabase):
    assert [try_as_guest("203.0.113.7").status_code for _ in range(3)] == [200, 200, 429]
    refused = try_as_guest("203.0.113.7")
    assert "already tried the demo today" in refused.json()["detail"]
    assert 0 < int(refused.headers["Retry-After"]) <= 24 * 3600 + 1
    assert try_as_guest("198.51.100.4").status_code == 200  # another visitor


def test_only_the_address_the_proxy_added_counts(supabase):
    """Entries before the last one come from the visitor and could be made up to get more starts."""
    assert try_as_guest("10.0.0.1, 203.0.113.7").status_code == 200
    assert try_as_guest("10.0.0.2, 203.0.113.7").status_code == 200
    assert try_as_guest("10.0.0.3, 203.0.113.7").status_code == 429


def test_cloudflares_header_tells_visitors_behind_one_proxy_apart(supabase):
    """On Render the last X-Forwarded-For entry can be a proxy that many visitors share (seen on 2026-11-27)."""
    def from_home(address: str) -> int:
        return TestClient(server.app).post("/guest", headers={
            "CF-Connecting-IP": address, "X-Forwarded-For": f"{address}, 172.68.0.1"}).status_code
    assert [from_home("203.0.113.7") for _ in range(3)] == [200, 200, 429]
    assert [from_home("198.51.100.4") for _ in range(2)] == [200, 200]  # same proxy, another home
    assert TestClient(server.app).post("/guest", headers={"True-Client-IP": "192.0.2.9"}).status_code == 200


def test_the_address_source_is_logged_once_without_the_address(supabase, monkeypatch, caplog):
    monkeypatch.setattr(guest_api, "_source_logged", [False])
    with caplog.at_level("INFO", logger="app.api.guest"):
        TestClient(server.app).post("/guest", headers={"CF-Connecting-IP": "203.0.113.7",
                                                       "X-Forwarded-For": "203.0.113.7, 172.68.0.1"})
        TestClient(server.app).post("/guest", headers={"CF-Connecting-IP": "198.51.100.4"})
    lines = [r.getMessage() for r in caplog.records if "address comes from" in r.getMessage()]
    assert lines == ["Guest demo: the visitor's address comes from cf-connecting-ip (X-Forwarded-For: 2 entries; "
                     "the same address as its first entry: yes, as its last: no)"]
    assert "203.0.113.7" not in caplog.text


def test_the_servers_own_address_is_not_limited(supabase):
    assert {try_as_guest("127.0.0.1").status_code for _ in range(4)} == {200}


def test_a_failed_start_does_not_count(supabase):
    supabase.down = True
    assert try_as_guest("203.0.113.7").status_code == 503
    supabase.down = False
    assert [try_as_guest("203.0.113.7").status_code for _ in range(2)] == [200, 200]


def test_addresses_are_kept_only_hashed_and_forgotten_the_next_day(supabase):
    assert try_as_guest("203.0.113.7").status_code == 200
    assert "203.0.113.7" not in str(guest_api._per_visitor)
    try_as_guest("203.0.113.7")
    guest_api._per_visitor_day[0] = "2000-01-01"  # as if the counts were from yesterday
    assert try_as_guest("203.0.113.7").status_code == 200


def test_the_guest_stays_the_guest_after_a_changed_email(monkeypatch):
    guest.forget()
    renamed = User(id=GUEST.id, email="someone@else.example")
    assert not accounts.is_guest(renamed)  # not known yet
    guest.remember([accounts.client_of(GUEST)])  # on startup: from its project, named after GUEST_EMAIL
    assert accounts.is_guest(renamed) and not accounts.is_guest(STRANGER)
    guest.forget()


def test_the_guest_may_scan_five_times_a_day(monkeypatch):
    deps._guest_scans.clear()
    for _ in range(deps.LIMITS.guest.scans_per_day):
        deps.guest_scan_limit(GUEST)
    with pytest.raises(HTTPException) as refused:
        deps.guest_scan_limit(GUEST)
    assert refused.value.status_code == 429 and "scans for today are used up" in refused.value.detail
    for _ in range(10):
        deps.guest_scan_limit(STRANGER)  # everyone else: no such limit
    deps._guest_scans.clear()


def test_the_scan_route_has_the_guest_limit():
    from app.api import discussions
    route = next(r for r in discussions.router.routes if r.path.endswith("/discussions/scan"))
    assert any(d.dependency is deps.guest_scan_limit for d in route.dependencies)


# ---------- Safety net: every route has a decision for the guest ----------
# Each API route is in exactly one group. A new route fails test_every_route_is_decided_for_the_guest until it is
# put into one, so nobody adds an endpoint without thinking about the public demo.
ADMIN_ONLY = {("GET", "/mcp-servers"), ("GET", "/mcp-calls"), ("POST", "/mcp-servers/{name}/call"),
              ("GET", "/audit")}
# Open without a sign-in (test_routes_need_sign_in.py OPEN).
PUBLIC = OPEN  # with the API docs only when this run has them (a local server)
# Allowed for the guest: they only reach the guest's own project, its own things or its own settings (ownership checks,
# test_ownership.py), and the model calls among them are within the guest's budgets.
OWN_ONLY = {
    ("GET", "/me"), ("GET", "/projects"), ("GET", "/projects/{project_id}"), ("GET", "/usage"),
    ("GET", "/usage/export"),  # scope "app" is the admin's only (403)
    ("GET", "/api-keys"),  # always empty: the guest cannot create keys
    ("GET", "/projects/{project_id}/sources"), ("GET", "/sources/{source_id}"), ("GET", "/sources/{source_id}/chunks"),
    ("GET", "/sources/{source_id}/cover"), ("GET", "/sources/{source_id}/deletion"),
    ("GET", "/sources/{source_id}/file"), ("GET", "/sources/{source_id}/summary"),
    ("POST", "/projects/{project_id}/ask"), ("POST", "/projects/{project_id}/search"),
    ("POST", "/projects/{project_id}/verify"), ("GET", "/projects/{project_id}/conversations"),
    ("GET", "/conversations/{conversation_id}"), ("DELETE", "/conversations/{conversation_id}"),
    ("POST", "/projects/{project_id}/generate"), ("GET", "/projects/{project_id}/assets"),
    ("GET", "/projects/{project_id}/assets/export"), ("GET", "/assets/{asset_id}"), ("PATCH", "/assets/{asset_id}"),
    ("DELETE", "/assets/{asset_id}"), ("GET", "/assets/{asset_id}/images"), ("POST", "/assets/{asset_id}/images"),
    ("GET", "/ad-images/{image_id}"), ("DELETE", "/ad-images/{image_id}"),
    ("POST", "/projects/{project_id}/campaigns"), ("GET", "/projects/{project_id}/campaigns"),
    ("GET", "/projects/{project_id}/campaigns/{campaign_id}"),
    ("DELETE", "/projects/{project_id}/campaigns/{campaign_id}"),
    ("POST", "/projects/{project_id}/discussions"), ("GET", "/projects/{project_id}/discussions"),
    ("POST", "/projects/{project_id}/discussions/scan"),  # also at most [guest] scans_per_day
    ("GET", "/discussions/{discussion_id}"), ("PATCH", "/discussions/{discussion_id}"),
    ("DELETE", "/discussions/{discussion_id}"),
    ("GET", "/projects/{project_id}/substack"), ("PUT", "/projects/{project_id}/substack"),
    ("DELETE", "/projects/{project_id}/substack"),  # the guest's own Substack name, cleared by the fresh start
    ("GET", "/facebook/status"), ("GET", "/facebook/comments"), ("GET", "/facebook/connect/pages"),
    ("GET", "/youtube/status"), ("GET", "/youtube/comments"),  # the guest never has a Page or channel
    ("GET", "/automation"), ("GET", "/automation/cycles"),  # the guest's own (empty) schedule and cycles
    ("POST", "/help/ask"),  # Ask the app: reads only the manual, within the guest's budgets
}


def test_every_route_is_decided_for_the_guest():
    import re
    from tests.test_routes_need_sign_in import API_ROUTES
    blocked = {(m, re.sub(r"\{[^}]+\}", "{}", p)) for m, p in API_ROUTES
               if any(m == bm and _matches(p, bp) for bm, bp in BLOCKED)}
    decided = {(m, re.sub(r"\{[^}]+\}", "{}", p)) for m, p in ADMIN_ONLY | PUBLIC | OWN_ONLY}
    routes = {(m, re.sub(r"\{[^}]+\}", "{}", p)) for m, p in API_ROUTES}
    assert not blocked & decided, "a route is in two groups"
    assert routes - blocked - decided == set(), "routes without a decision for the guest"
    assert decided - routes == set(), "decided routes that do not exist (renamed?)"


@pytest.mark.parametrize(("method", "path"), sorted(ADMIN_ONLY), ids=lambda v: v)
def test_the_admins_routes_refuse_the_guest(app_as, method, path):
    assert app_as(GUEST).request(method, path.replace("{name}", "x")).status_code == 403


def test_the_guest_never_gets_the_admins_page(app_as, monkeypatch):
    """The admin's Page from server/.env is the admin's only (page_connections.page_of)."""
    from app.social import facebook
    monkeypatch.setattr(facebook, "env_page", lambda: pytest.fail("the guest reached the admin's Page"))
    status = app_as(GUEST).get("/facebook/status").json()
    assert status["connected"] is False
    assert app_as(GUEST).get("/facebook/comments").status_code >= 400
