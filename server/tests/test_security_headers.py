"""Security headers (core/security_headers.py): every response carries them, an endpoint's own header is kept, and
the real app has the middleware. Also the API description (config.api_docs): only a local server shows it. No model
calls."""

import pytest
from fastapi import FastAPI, Response
from fastapi.testclient import TestClient

import server
from app.core import config
from app.core.security_headers import SecurityHeadersMiddleware


@pytest.fixture
def client():
    app = FastAPI()

    @app.get("/data")
    def data():
        return {"ok": True}

    @app.get("/picture")
    def picture():
        return Response(b"png", media_type="image/png", headers={"Cache-Control": "private, max-age=86400"})

    app.add_middleware(SecurityHeadersMiddleware)
    with TestClient(app) as test_client:
        yield test_client


def test_every_response_carries_the_headers(client):
    headers = client.get("/data").headers
    assert headers["x-content-type-options"] == "nosniff"
    assert headers["x-frame-options"] == "DENY"
    assert headers["referrer-policy"] == "no-referrer"
    assert headers["strict-transport-security"].startswith("max-age=")
    assert headers["content-security-policy"] == "default-src 'none'; frame-ancestors 'none'"
    assert headers["cache-control"] == "no-store"


def test_errors_carry_them_too(client):
    response = client.get("/missing")
    assert response.status_code == 404
    assert response.headers["x-content-type-options"] == "nosniff"


def test_an_endpoints_own_header_is_kept(client):
    headers = client.get("/picture").headers
    assert headers.get_list("cache-control") == ["private, max-age=86400"]
    assert headers["x-content-type-options"] == "nosniff"


def test_the_docs_page_keeps_its_scripts(client):
    response = client.get("/docs")
    assert response.status_code == 200
    assert "content-security-policy" not in response.headers
    assert response.headers["x-content-type-options"] == "nosniff"


def test_the_app_has_the_middleware():
    assert any(m.cls is SecurityHeadersMiddleware for m in server.app.user_middleware)


@pytest.mark.parametrize("environ, shown", [
    ({}, True),  # a local server: the default address, not on Render
    ({"PUBLIC_API_URL": "http://127.0.0.1:8000"}, True),
    ({"PUBLIC_API_URL": "https://marketer-app.onrender.com"}, False),
    ({"PUBLIC_API_URL": "http://localhost.example.com"}, False),
    ({"RENDER": "true"}, False),
    ({"RENDER": "true", "API_DOCS": "true"}, True),  # asked for explicitly
    ({"API_DOCS": "false"}, False),
    ({"API_DOCS": "maybe"}, False),  # unclear means no
])
def test_only_a_local_server_shows_the_api_description(environ, shown):
    assert config.api_docs(environ) is shown


def test_the_app_follows_the_setting():
    paths = {getattr(route, "path", None) for route in server.app.routes}  # an included router has no path
    assert ({"/docs", "/redoc", "/openapi.json"} <= paths) is config.API_DOCS
    if not config.API_DOCS:
        assert not {"/docs", "/redoc", "/openapi.json"} & paths
