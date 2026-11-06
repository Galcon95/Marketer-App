"""Tests of authorization: a user only reaches their own project (client) and what belongs to it. Another user's
project, book, asset or chat answers 404 like an unknown id, before any file, vector store or model is touched.
Also: GET /me creates a new user's project (named after their email), the default project goes to
DEFAULT_CLIENT_OWNER, and the app-wide endpoints are for that admin only."""

from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import assets, campaigns, deps, health, knowledge, mcp_console, projects, sources
from app.core import accounts
from app.core import state as db
from app.core.schemas import Asset, BookSummary, Conversation, Source
from app.db import records
from tests.conftest import OWNER, STRANGER, sign_in

PROJECT = db.DEFAULT_PROJECT_ID
NOW = datetime.now(timezone.utc)


# If an ownership check were missing, a test request must not reach the real library or cost money.
pytestmark = pytest.mark.usefixtures("offline")


@pytest.fixture
def app(monkeypatch):
    """All API routers, with one book (src_a, with summary), one asset and one chat in OWNER's default project."""
    deps._llm_calls.clear()
    monkeypatch.setattr(db, "sources", {"src_a": Source(
        id="src_a", project_id=PROJECT, filename="a.pdf", kind="document", size_bytes=1, status="ready",
        progress=100, chunk_count=0, created_at=NOW)})
    monkeypatch.setattr(db, "chunks", {})
    monkeypatch.setattr(db, "summaries", {"src_a": BookSummary(
        source_id="src_a", summary="s", themes=[], chapters=[], model="m", tokens=0, created_at=NOW)})
    monkeypatch.setattr(db, "assets", {"ast_a": Asset(
        id="ast_a", project_id=PROJECT, asset_type="blurb", grounded=False, brief="b", text="t", citations=[],
        created_at=NOW)})
    monkeypatch.setattr(db, "conversations", {"cnv_a": Conversation(
        id="cnv_a", project_id=PROJECT, title="q", created_at=NOW, updated_at=NOW)})
    app = FastAPI()
    for module in (health, projects, sources, knowledge, assets, campaigns, mcp_console):
        app.include_router(module.router)
    yield app
    deps._llm_calls.clear()


def client_for(app: FastAPI, user) -> TestClient:
    sign_in(app, user)
    return TestClient(app)


# Every route that names one of OWNER's things, with a valid body, so only the ownership check can reject it.
OWNER_ROUTES = [
    ("get", f"/projects/{PROJECT}", None),
    ("get", f"/projects/{PROJECT}/sources", None),
    ("get", f"/projects/{PROJECT}/assets", None),
    ("get", f"/projects/{PROJECT}/conversations", None),
    ("post", f"/projects/{PROJECT}/search", {"query": "garden cities"}),
    ("post", f"/projects/{PROJECT}/verify", {"text": "Garden cities are green."}),
    ("post", f"/projects/{PROJECT}/ask", {"question": "What is a garden city?"}),
    ("post", f"/projects/{PROJECT}/generate", {"asset_type": "blurb", "brief": "A blurb"}),
    ("post", f"/projects/{PROJECT}/campaigns", {"title": "T", "premise": "P"}),
    ("get", "/sources/src_a", None),
    ("get", "/sources/src_a/chunks", None),
    ("get", "/sources/src_a/file", None),
    ("get", "/sources/src_a/cover", None),
    ("get", "/sources/src_a/summary", None),
    ("post", "/sources/src_a/summary", None),
    ("post", "/sources/src_a/ingest", None),
    ("get", "/sources/src_a/deletion", None),
    ("delete", "/sources/src_a", None),
    ("get", "/assets/ast_a", None),
    ("patch", "/assets/ast_a", {"text": "Rewritten by a stranger"}),
    ("delete", "/assets/ast_a", None),
    ("get", "/conversations/cnv_a", None),
    ("delete", "/conversations/cnv_a", None),
]


@pytest.mark.parametrize(("method", "path", "body"), OWNER_ROUTES, ids=[f"{m} {p}" for m, p, _ in OWNER_ROUTES])
def test_another_user_gets_404_for_everything_of_the_owner(app, method, path, body):
    stranger = client_for(app, STRANGER)
    response = stranger.request(method, path, json=body)
    assert response.status_code == 404
    # Nothing was changed or deleted.
    assert set(db.sources) == {"src_a"} and set(db.assets) == {"ast_a"} and set(db.conversations) == {"cnv_a"}
    assert db.assets["ast_a"].text == "t"


def test_upload_into_another_users_project_is_rejected(app):
    stranger = client_for(app, STRANGER)
    response = stranger.post(f"/projects/{PROJECT}/sources", files={"file": ("x.pdf", b"%PDF-1.4\n", "application/pdf")})
    assert response.status_code == 404
    assert set(db.sources) == {"src_a"}


def test_the_owner_reaches_their_own_things(app):
    owner = client_for(app, OWNER)
    assert owner.get(f"/projects/{PROJECT}").json()["source_count"] == 1
    assert [s["id"] for s in owner.get(f"/projects/{PROJECT}/sources").json()] == ["src_a"]
    assert owner.get("/sources/src_a").status_code == 200
    assert owner.get("/assets/ast_a").status_code == 200
    assert owner.get("/conversations/cnv_a").status_code == 200
    assert owner.delete("/assets/ast_a").status_code == 204


@pytest.mark.parametrize(("path", "body"), [
    ("search", {"query": "garden cities", "source_ids": ["src_a"]}),
    ("ask", {"question": "What is a garden city?", "source_ids": ["src_a"]}),
    ("generate", {"asset_type": "blurb", "brief": "A blurb", "source_ids": ["src_a"]}),
    ("campaigns", {"title": "T", "premise": "P", "source_id": "src_a"}),
])
def test_another_users_book_cannot_be_used_in_your_own_project(app, path, body):
    stranger = client_for(app, STRANGER)
    own_project = stranger.get("/me").json()["project"]["id"]
    response = stranger.post(f"/projects/{own_project}/{path}", json=body)
    assert response.status_code == 404
    assert "src_a" in response.json()["detail"]


def test_continuing_another_users_chat_is_rejected(app):
    stranger = client_for(app, STRANGER)
    own_project = stranger.get("/me").json()["project"]["id"]
    response = stranger.post(f"/projects/{own_project}/ask", json={"question": "And then?", "conversation_id": "cnv_a"})
    assert response.status_code == 404


def test_project_list_shows_only_your_own(app):
    assert [p["id"] for p in client_for(app, OWNER).get("/projects").json()] == [PROJECT]
    stranger = client_for(app, STRANGER)
    stranger.get("/me")
    assert PROJECT not in [p["id"] for p in stranger.get("/projects").json()]


# ---------- GET /me: one project per user ----------

def test_a_new_user_gets_an_empty_project_named_after_their_email(app):
    stranger = client_for(app, STRANGER)
    me = stranger.get("/me").json()
    assert (me["email"], me["admin"]) == (STRANGER.email, False)
    assert me["project"]["name"] == STRANGER.email
    assert me["project"]["id"] != PROJECT and me["project"]["source_count"] == 0
    # The same project on the next call, and it is saved.
    assert stranger.get("/me").json()["project"]["id"] == me["project"]["id"]
    assert me["project"]["id"] in records.load_projects()


def test_the_default_project_goes_to_the_default_client_owner(app, monkeypatch):
    monkeypatch.setattr(accounts, "DEFAULT_CLIENT_OWNER", "admin@example.com")
    db.projects[PROJECT] = db.projects[PROJECT].model_copy(update={"owner_id": ""})  # nobody owns it yet
    admin = client_for(app, OWNER.model_copy(update={"id": "user-admin", "email": "Admin@Example.com"}))
    me = admin.get("/me").json()
    assert (me["admin"], me["project"]["id"], me["project"]["source_count"]) == (True, PROJECT, 1)
    assert records.load_projects()[PROJECT].owner_id == "user-admin"


def test_the_default_project_does_not_go_to_anyone_else(app, monkeypatch):
    monkeypatch.setattr(accounts, "DEFAULT_CLIENT_OWNER", "admin@example.com")
    db.projects[PROJECT] = db.projects[PROJECT].model_copy(update={"owner_id": ""})
    me = client_for(app, STRANGER).get("/me").json()
    assert me["project"]["id"] != PROJECT
    assert db.projects[PROJECT].owner_id == ""


# ---------- App-wide endpoints: the admin only ----------

@pytest.mark.parametrize("path", ["/usage?scope=app", "/mcp-calls"])
def test_app_wide_endpoints_are_for_the_admin_only(app, monkeypatch, path):
    monkeypatch.setattr(accounts, "DEFAULT_CLIENT_OWNER", OWNER.email)
    assert client_for(app, STRANGER).get(path).status_code == 403
    assert client_for(app, OWNER).get(path).status_code == 200
