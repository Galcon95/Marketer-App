"""Every user's own Facebook Page: the encrypted token (secret_box.py), the signed Facebook Login state, the login
flow (page_connections.py, api/facebook.py) and that each user works on their own Page only. Facebook is faked."""

from datetime import datetime, timezone
from urllib.parse import parse_qs, urlparse

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import facebook as fb_api
from app.core import accounts, config, secret_box
from app.core import state as db
from app.core.schemas import Asset, FacebookPage, FacebookPublished
from app.db import records
from app.social import facebook, page_connections
from tests.conftest import OWNER, STRANGER, sign_in

APP = "http://localhost:3000"
NOW = datetime(2026, 11, 16, tzinfo=timezone.utc)


@pytest.fixture(autouse=True)
def login_setup(monkeypatch):
    """Facebook Login set up (app id and secret, an encryption key); the admin's Page in server/.env; no state kept
    from other tests."""
    monkeypatch.setattr(config, "FACEBOOK_APP_ID", "42")
    monkeypatch.setattr(config, "FACEBOOK_APP_SECRET", "app-secret")
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setattr(config, "CLIENT_ORIGINS", [APP])
    monkeypatch.setattr(config, "FACEBOOK_PAGE_ID", "999")
    monkeypatch.setattr(config, "FACEBOOK_PAGE_TOKEN", "admin-token")
    monkeypatch.setattr(accounts, "DEFAULT_CLIENT_OWNER", OWNER.email)
    monkeypatch.setattr(page_connections, "_used_states", {})
    monkeypatch.setattr(page_connections, "_waiting", {})


@pytest.fixture
def graph(monkeypatch):
    """Fake Graph: the code exchange and the user's Pages (set `pages` to change them); the calls are recorded."""
    calls: list[tuple[str, str | None, dict]] = []
    pages = [{"id": "555", "name": "Stranger's Book", "access_token": "page-token-555"}]

    def fake(method, path, token, params=None, data=None, from_env=False):
        calls.append((path, token, dict(params or {})))
        if path == "oauth/access_token":
            return {"access_token": "long-user" if params.get("grant_type") else "short-user"}
        if path == "me/accounts":
            return {"data": pages}
        raise AssertionError(path)

    monkeypatch.setattr(facebook, "graph_request", fake)
    return calls, pages


def _client(user=OWNER) -> TestClient:
    app = FastAPI()
    app.include_router(fb_api.router)
    app.include_router(fb_api.callback_router)
    sign_in(app, user)
    return TestClient(app, follow_redirects=False)


def _state(user=STRANGER) -> str:
    url = _client(user).post("/facebook/connect", json={"return_to": APP}).json()["url"]
    return parse_qs(urlparse(url).query)["state"][0]


# ---------- secret_box ----------
def test_tokens_are_encrypted_and_only_readable_with_the_key(monkeypatch):
    sealed = secret_box.encrypt("page-token")
    assert "page-token" not in sealed and secret_box.decrypt(sealed) == "page-token"
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    with pytest.raises(secret_box.SecretError):
        secret_box.decrypt(sealed)
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY", "not-a-key")
    assert not secret_box.is_configured()
    with pytest.raises(secret_box.SecretError):
        secret_box.encrypt("x")


# ---------- the state ----------
def test_state_names_the_user_and_works_once():
    state = page_connections.make_state("user-1", APP)
    assert page_connections.read_state(state) == ("user-1", APP)
    with pytest.raises(page_connections.LoginError, match="already used"):
        page_connections.read_state(state)


@pytest.mark.parametrize("change", ["forged", "expired", "foreign-origin", "garbage"])
def test_a_bad_state_is_refused(monkeypatch, change):
    state = page_connections.make_state("user-1", APP)
    if change == "forged":  # another user id with the old signature
        other = page_connections.make_state("user-2", APP)
        state = other.split(".")[0] + "." + state.split(".")[1]
    elif change == "expired":
        monkeypatch.setattr(page_connections.time, "time", lambda: 10**12)
    elif change == "foreign-origin":
        monkeypatch.setattr(config, "CLIENT_ORIGINS", ["https://other.example"])
    else:
        state = "not-a-state"
    with pytest.raises(page_connections.LoginError):
        page_connections.read_state(state)


# ---------- starting the login ----------
def test_login_url_asks_facebook_for_the_page_permissions():
    r = _client(STRANGER).post("/facebook/connect", json={"return_to": APP + "/"})
    assert r.status_code == 200, r.text
    url = urlparse(r.json()["url"])
    query = parse_qs(url.query)
    assert url.netloc == "www.facebook.com" and url.path.endswith("/dialog/oauth")
    assert query["client_id"] == ["42"] and query["redirect_uri"] == ["http://localhost:8000/facebook/oauth/callback"]
    assert "pages_manage_posts" in query["scope"][0] and query["state"][0]


def test_login_needs_setup_and_an_allowed_origin(monkeypatch):
    assert _client().post("/facebook/connect", json={"return_to": "https://evil.example"}).status_code == 422
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY", "")
    assert _client().post("/facebook/connect", json={"return_to": APP}).status_code == 503
    assert _client(STRANGER).get("/facebook/status").json()["login_available"] is False


# ---------- the callback ----------
def test_one_page_is_connected_with_its_token_encrypted(graph):
    calls, _ = graph
    r = _client(STRANGER).get("/facebook/oauth/callback", params={"state": _state(), "code": "abc"})
    assert r.status_code == 303 and r.headers["location"] == f"{APP}/?facebook=connected"
    saved = records.get_facebook_connection(STRANGER.id)
    assert (saved.page_id, saved.page_name) == ("555", "Stranger's Book")
    assert "page-token-555" not in saved.token and secret_box.decrypt(saved.token) == "page-token-555"
    assert [c[0] for c in calls] == ["oauth/access_token", "oauth/access_token", "me/accounts"]
    assert calls[0][2]["code"] == "abc" and calls[2][1] == "long-user"  # Pages read with the long-lived user token


def test_several_pages_wait_for_the_users_choice(graph, monkeypatch):
    _, pages = graph
    pages.append({"id": "556", "name": "Second Page", "access_token": "page-token-556"})
    client = _client(STRANGER)
    r = client.get("/facebook/oauth/callback", params={"state": _state(), "code": "abc"})
    assert r.headers["location"] == f"{APP}/?facebook=choose"
    assert records.get_facebook_connection(STRANGER.id) is None
    listed = client.get("/facebook/connect/pages").json()
    assert listed == [{"id": "555", "name": "Stranger's Book"}, {"id": "556", "name": "Second Page"}]  # no tokens
    assert _client(OWNER).get("/facebook/connect/pages").json() == []  # only for the user who logged in
    monkeypatch.setattr(facebook, "page_info", lambda: FacebookPage(id="556", name="Second Page"))
    r = client.post("/facebook/connect/pages/556")
    assert r.status_code == 200 and r.json()["source"] == "user" and r.json()["page"]["name"] == "Second Page"
    assert records.get_facebook_connection(STRANGER.id).page_id == "556"
    assert client.post("/facebook/connect/pages/555").status_code == 409  # the choice is over


@pytest.mark.parametrize("params, location", [({"error": "access_denied"}, f"{APP}/?facebook=cancelled")])
def test_a_cancelled_login_goes_back_to_the_app(graph, params, location):
    r = _client().get("/facebook/oauth/callback", params={"state": _state(), **params})
    assert r.headers["location"] == location


def test_no_page_or_a_failed_exchange_is_reported(graph, monkeypatch):
    _, pages = graph
    pages.clear()
    r = _client().get("/facebook/oauth/callback", params={"state": _state(), "code": "abc"})
    assert r.headers["location"].startswith(f"{APP}/?facebook=error&message=No+Facebook+Page")

    def failing(*args, **kwargs):
        raise facebook.FacebookError(502, "bad code")

    monkeypatch.setattr(facebook, "graph_request", failing)
    r = _client().get("/facebook/oauth/callback", params={"state": _state(), "code": "abc"})
    assert "facebook=error" in r.headers["location"]


def test_a_callback_without_a_valid_state_is_refused(graph):
    r = _client().get("/facebook/oauth/callback", params={"state": "forged.state", "code": "abc"})
    assert r.status_code == 400 and "location" not in r.headers
    assert records.get_facebook_connection(STRANGER.id) is None


# ---------- each user works on their own Page ----------
def _connect(user, page_id="555", token="page-token-555"):
    records.save_facebook_connection(page_connections.FacebookConnection(
        user_id=user.id, page_id=page_id, page_name="P", token=secret_box.encrypt(token), connected_at=NOW))


@pytest.fixture
def stranger_asset(monkeypatch):
    """A reader question in the stranger's own project; publish_post records the Page it was sent to."""
    project = db.projects[db.DEFAULT_PROJECT_ID].model_copy(update={"id": "prj_s", "owner_id": STRANGER.id})
    records.save_project(project)
    monkeypatch.setitem(db.projects, project.id, project)
    monkeypatch.setattr(db, "assets", {})
    asset = Asset(id="ast_s", project_id="prj_s", asset_type="reader_question", grounded=True, brief="b",
                  platform="facebook", text="Who decides?", citations=[], created_at=NOW)
    records.save_assets([asset])
    db.assets[asset.id] = asset
    sent: list[tuple[str, str]] = []

    def fake_publish(message, link=None):
        page = facebook._current()
        sent.append((page.page_id, page.token))
        return FacebookPublished(id=f"{page.page_id}_1", url="https://www.facebook.com/x")

    monkeypatch.setattr(facebook, "publish_post", fake_publish)
    return sent


def test_a_user_publishes_on_their_own_page_never_the_admins(stranger_asset):
    assert _client(STRANGER).post("/assets/ast_s/publish/facebook").status_code == 503  # not connected yet
    _connect(STRANGER)
    r = _client(STRANGER).post("/assets/ast_s/publish/facebook")
    assert r.status_code == 200, r.text
    assert stranger_asset == [("555", "page-token-555")]


def test_the_admins_own_connection_comes_before_the_page_in_env(monkeypatch):
    user = OWNER
    assert page_connections.page_for(user)[1] == "server"
    _connect(user, "777", "owner-page-token")
    page, source = page_connections.page_for(user)
    assert source == "user" and (page.page_id, page.token) == ("777", "owner-page-token")


def test_disconnect_forgets_the_page(stranger_asset):
    _connect(STRANGER)
    client = _client(STRANGER)
    assert client.delete("/facebook/connection").status_code == 204
    assert records.get_facebook_connection(STRANGER.id) is None
    assert client.get("/facebook/status").json() == {"connected": False, "page": None, "error": "", "source": "",
                                                    "login_available": True}


def test_a_token_from_an_old_key_counts_as_not_connected(monkeypatch):
    _connect(STRANGER)
    monkeypatch.setattr(config, "TOKEN_ENCRYPTION_KEY", Fernet.generate_key().decode())
    assert page_connections.page_for(STRANGER) == (None, "")


def test_the_token_never_shows_in_a_repr():
    assert "secret-token" not in repr(facebook.PageAccess("1", "secret-token"))
