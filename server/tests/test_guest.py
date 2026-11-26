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


def test_every_signed_in_guest_request_counts_as_activity(monkeypatch):
    guest.forget()
    monkeypatch.setattr(auth, "verify_token", lambda token: GUEST)
    request = Request({"type": "http", "headers": [(b"authorization", b"Bearer t")]})
    assert auth.current_user(request) == GUEST
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
