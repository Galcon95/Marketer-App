"""Safety net for the whole app (server.py): every endpoint and every MCP server needs a sign-in, except the open
ones listed in OPEN. It goes through all routes of the real app, so a new router or endpoint that forgets the
sign-in check fails here, without anyone having to remember to write a test for it.

The app is used without starting it (no lifespan), so no saved data is loaded and no MCP session runs: every
request must be refused by the sign-in check before anything else happens.
"""

import re

import pytest
from fastapi.routing import APIRoute
from fastapi.testclient import TestClient
from starlette.routing import Mount, Route

import server
from app.core import api_keys, auth
from app.core.mcp_auth import RequireMcpAuth
from tests.conftest import OWNER

# Open on purpose: the health check (the login page shows whether the API is up), two fixed greetings to see that
# the server runs (health.py: "/" and "/test"), and FastAPI's own API docs. None of them shows or changes any data.
OPEN = {("GET", "/health"), ("GET", "/"), ("GET", "/test"), ("GET", "/openapi.json"), ("GET", "/docs"),
        ("GET", "/docs/oauth2-redirect"), ("GET", "/redoc")}

def endpoints(routes, prefix: str = ""):
    """(method, path) of every endpoint, also inside included routers. FastAPI 0.143+ keeps an included router as
    one _IncludedRouter entry (with its prefix) instead of copying its routes into the app's list."""
    for route in routes:
        if isinstance(route, (APIRoute, Route)):
            yield from ((method, prefix + route.path) for method in route.methods)
        elif hasattr(route, "original_router"):  # _IncludedRouter
            yield from endpoints(route.original_router.routes, prefix + route.include_context.prefix)


API_ROUTES = sorted({(m, p) for m, p in endpoints(server.app.routes) if m != "HEAD"})  # HEAD mirrors GET
MCP_PATHS = ["/mcp", "/guardrails/mcp", "/anything-else"]  # "/" is mounted too: every unknown path goes to an MCP app


def concrete(path: str) -> str:
    """The path with every {parameter} filled in, e.g. /sources/{source_id} → /sources/x."""
    return re.sub(r"\{[^}]+\}", "x", path)


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setattr(auth, "SUPABASE_URL", "https://example.supabase.co")  # configured, but no network is needed
    return TestClient(server.app)


def test_the_list_of_routes_is_complete():
    """The sweep below really sees the app's routes (if this fails, the route discovery is broken)."""
    paths = {path for _, path in API_ROUTES}
    assert {"/me", "/projects/{project_id}/ask", "/sources/{source_id}", "/api-keys", "/usage"} <= paths
    assert len(API_ROUTES) > 30


@pytest.mark.parametrize(("method", "path"), [r for r in API_ROUTES if r not in OPEN], ids=lambda v: v)
def test_every_endpoint_needs_a_sign_in(client, method, path):
    response = client.request(method, concrete(path))
    assert response.status_code == 401, f"{method} {path} answers {response.status_code} without a sign-in"


@pytest.mark.parametrize(("method", "path"), [r for r in API_ROUTES if r not in OPEN], ids=lambda v: v)
def test_a_personal_api_key_is_no_sign_in_for_the_app(client, method, path):
    """Keys are for the MCP servers only: a leaked key cannot read books, spend money or manage keys in the app."""
    _, key = api_keys.create(OWNER, "k")
    response = client.request(method, concrete(path), headers={"Authorization": f"Bearer {key}"})
    assert response.status_code == 401


def test_the_open_endpoints_are_only_the_listed_ones(client):
    assert {r for r in API_ROUTES if r in OPEN} == OPEN
    assert client.get("/health").status_code == 200


def test_every_mounted_app_is_behind_the_mcp_sign_in_check():
    mounts = [route for route in server.app.routes if isinstance(route, Mount)]
    assert {m.path for m in mounts} == {"/guardrails", ""}  # "" is the mount at "/"
    assert all(isinstance(m.app, RequireMcpAuth) for m in mounts)


@pytest.mark.parametrize("path", MCP_PATHS)
def test_the_mcp_servers_need_a_key(client, path):
    response = client.post(path, json={"jsonrpc": "2.0", "id": 1, "method": "tools/list"},
                           headers={"Accept": "application/json, text/event-stream"})
    assert response.status_code == 401
