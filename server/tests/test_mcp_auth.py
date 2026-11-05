"""Tests of the MCP servers' sign-in check (mcp_auth.py): without a token, with a wrong or revoked key or an invalid
access token the request gets 401 before the MCP server sees it; a valid personal key or access token gets through,
and the server knows the user. Also: the app's MCP console forwards the signed-in user's token."""

from contextlib import asynccontextmanager

import pytest
from fastapi import FastAPI, HTTPException
from fastapi.testclient import TestClient
from mcp.server.mcpserver import MCPServer

from app.api import mcp_console
from app.core import accounts, api_keys, mcp_auth
from app.market import client as mcp_client
from tests.conftest import OWNER, STRANGER, sign_in

LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}
HEADERS = {"Accept": "application/json, text/event-stream"}


@pytest.fixture
def mcp(monkeypatch):
    """A small MCP server mounted behind RequireMcpAuth like in server.py.
    Access tokens: "good-token" is OWNER's, anything else is invalid (no Supabase)."""
    def verify(token: str):
        if token == "good-token":
            return OWNER
        raise HTTPException(401, "Invalid access token.")
    monkeypatch.setattr(mcp_auth, "verify_token", verify)

    server = MCPServer("test")

    @server.tool()
    def whoami() -> str:
        """A tool, so tools/list has something to list."""
        return "ok"

    @asynccontextmanager
    async def lifespan(_):
        async with server.session_manager.run():  # like server.py: a mounted app's own lifespan is not started
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/", mcp_auth.RequireMcpAuth(
        server.streamable_http_app(streamable_http_path="/mcp", stateless_http=True, json_response=True)))
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:  # the SDK accepts only localhost hosts
        yield client


def call(client: TestClient, authorization: str | None):
    headers = dict(HEADERS, **({"Authorization": authorization} if authorization else {}))
    return client.post("/mcp", json=LIST_TOOLS, headers=headers)


@pytest.mark.parametrize(("authorization", "message"), [
    (None, "An API key is needed"),
    ("Basic abc", "An API key is needed"),
    ("Bearer ", "An API key is needed"),
    ("Bearer mk_wrong", "not valid"),
    ("Bearer some-other-token", "Invalid access token"),
])
def test_requests_without_a_valid_token_get_401(mcp, authorization, message):
    client = mcp
    response = call(client, authorization)
    assert response.status_code == 401
    assert message in response.json()["detail"]
    assert response.headers["WWW-Authenticate"].startswith("Bearer")


def test_a_personal_key_gets_through(mcp):
    client = mcp
    _, key = api_keys.create(OWNER, "Claude Desktop")
    response = call(client, f"Bearer {key}")
    assert response.status_code == 200
    assert "whoami" in response.text


def test_a_revoked_key_is_refused_at_once(mcp):
    client = mcp
    record, key = api_keys.create(OWNER, "k")
    assert call(client, f"Bearer {key}").status_code == 200
    api_keys.revoke(OWNER, record.id)
    assert call(client, f"Bearer {key}").status_code == 401


def test_a_sign_in_token_gets_through(mcp):
    client = mcp
    assert call(client, "Bearer good-token").status_code == 200


def test_the_user_is_known_to_the_request(monkeypatch):
    """RequireMcpAuth stores the user in the request scope for the MCP server (user_of)."""
    _, key = api_keys.create(STRANGER, "k")
    seen = []

    async def inner(scope, receive, send):
        seen.append(mcp_auth.user_of(scope))
        await send({"type": "http.response.start", "status": 204, "headers": []})
        await send({"type": "http.response.body", "body": b""})
    app = FastAPI()
    app.mount("/", mcp_auth.RequireMcpAuth(inner))
    assert TestClient(app).post("/mcp", headers={"Authorization": f"Bearer {key}"}).status_code == 204
    assert seen == [STRANGER]


def test_the_console_forwards_the_users_token(monkeypatch):
    forwarded = []

    async def fake_status(base_url, config, authorization):
        forwarded.append(authorization)
        return {"name": config.name, "url": base_url + config.path, "audience": config.audience, "status": "active"}
    monkeypatch.setattr(mcp_client, "server_status", fake_status)
    app = FastAPI()
    app.include_router(mcp_console.router)
    sign_in(app, OWNER)
    monkeypatch.setattr(accounts, "DEFAULT_CLIENT_OWNER", OWNER.email)  # the console is for the admin
    response = TestClient(app).get("/mcp-servers", headers={"Authorization": "Bearer the-users-token"})
    assert response.status_code == 200
    assert forwarded == ["Bearer the-users-token"] * len(mcp_client.SERVERS)
