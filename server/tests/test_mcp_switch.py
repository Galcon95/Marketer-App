"""The MCP switch (config.mcp_servers, server.build_app, api/deps.py mcp_on): with MCP_SERVERS off the two MCP servers
are not mounted, the tool console and new API keys answer 503, and the rest of the app works as before. No model
calls."""

import pytest
from fastapi.testclient import TestClient
from starlette.routing import Mount

import server
from app.core import accounts, api_keys, auth, config
from tests.conftest import OWNER, sign_in

HEADERS = {"Accept": "application/json, text/event-stream"}
LIST_TOOLS = {"jsonrpc": "2.0", "id": 1, "method": "tools/list"}


@pytest.mark.parametrize("environ, on", [
    ({}, True),  # a local server
    ({"PUBLIC_API_URL": "https://marketer-app.onrender.com"}, False),
    ({"RENDER": "true"}, False),
    ({"RENDER": "true", "MCP_SERVERS": "true"}, True),  # asked for explicitly, e.g. for a review
    ({"MCP_SERVERS": "false"}, False),
    ({"MCP_SERVERS": "perhaps"}, False),  # unclear means off
    ({"API_DOCS": "false"}, True),  # the two switches are independent
])
def test_only_a_local_server_runs_the_mcp_servers_by_default(environ, on):
    assert config.mcp_servers(environ) is on


@pytest.fixture
def off(monkeypatch):
    """The real app with the MCP servers off, OWNER signed in as the admin (not started: no saved data, no model)."""
    monkeypatch.setattr(config, "MCP_SERVERS", False)
    monkeypatch.setattr(accounts, "DEFAULT_CLIENT_OWNER", OWNER.email)
    monkeypatch.setattr(auth, "SUPABASE_URL", "https://example.supabase.co")
    app = server.build_app(mcp=False)
    sign_in(app)
    return TestClient(app)


def test_the_servers_are_not_mounted(off):
    assert [r for r in off.app.routes if isinstance(r, Mount)] == []


@pytest.mark.parametrize("path", ["/mcp", "/guardrails/mcp", "/anything-else"])
def test_their_addresses_answer_like_any_unknown_one(off, path):
    """Also with a valid key: there is nothing behind the address."""
    _, key = api_keys.create(OWNER, "k")
    for headers in (HEADERS, {**HEADERS, "Authorization": f"Bearer {key}"}):
        assert off.post(path, json=LIST_TOOLS, headers=headers).status_code == 404


@pytest.mark.parametrize(("method", "path"), [("GET", "/mcp-servers"), ("GET", "/mcp-calls"),
                                              ("POST", "/mcp-servers/mcp-guardrails/call")])
def test_the_tool_console_is_off_even_for_the_admin(off, method, path):
    response = off.request(method, path, json={"tool": "validate_input", "arguments": {}})
    assert response.status_code == 503
    assert "switched off" in response.json()["detail"]


def test_no_new_keys_but_old_ones_can_still_be_listed_and_revoked(off):
    record, _ = api_keys.create(OWNER, "made earlier")
    assert off.post("/api-keys", json={"name": "new"}).status_code == 503
    assert [k["id"] for k in off.get("/api-keys").json()] == [record.id]
    assert off.delete(f"/api-keys/{record.id}").status_code == 204
    assert off.get("/api-keys").json() == []


def test_the_app_is_told_so_it_can_hide_the_pages(off, monkeypatch):
    assert off.get("/me").json()["mcp"] is False
    monkeypatch.setattr(config, "MCP_SERVERS", True)
    assert off.get("/me").json()["mcp"] is True


def test_the_rest_of_the_app_works(off):
    assert off.get("/health").status_code == 200
    assert off.get("/projects").status_code == 200


def test_the_running_app_follows_the_setting():
    """server.app was built on import from this machine's environment (conftest only sets the flag for the tests)."""
    mounted = {r.path for r in server.app.routes if isinstance(r, Mount)}
    assert mounted == ({"/guardrails", ""} if config.mcp_servers() else set())
