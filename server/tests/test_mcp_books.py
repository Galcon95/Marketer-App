"""Tests of the book MCP server per user (book_server.py behind mcp_auth.py), over real HTTP and MCP: a personal key
reaches only its owner's library, the model tools have the app's limits, and their costs are logged for the key's
owner."""

from contextlib import asynccontextmanager
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.api import deps
from app.core import api_keys, logs, usage
from app.core import state as db
from app.core.mcp_auth import RequireMcpAuth
from app.core.schemas import Source, UsageRecord
from app.db import records
from app.market import book_server as books
from tests.conftest import OWNER, STRANGER

pytestmark = pytest.mark.usefixtures("offline")

PROJECT = db.DEFAULT_PROJECT_ID
NOW = datetime.now(timezone.utc)


@pytest.fixture(scope="module")
def server():
    """The real book server mounted behind RequireMcpAuth like in server.py. Its session manager can run only once
    per process, so one app serves the whole module; the data each test sees comes from its own fixtures."""
    @asynccontextmanager
    async def lifespan(_):
        async with books.book_server.session_manager.run():
            yield

    app = FastAPI(lifespan=lifespan)
    app.mount("/", RequireMcpAuth(books.book_server.streamable_http_app(
        streamable_http_path="/mcp", stateless_http=True, json_response=True)))
    app.add_middleware(logs.RequestIdMiddleware)  # like server.py: the request context for the usage log
    with TestClient(app, base_url="http://127.0.0.1:8000") as client:  # the SDK accepts only localhost hosts
        yield client


@pytest.fixture(autouse=True)
def library(monkeypatch):
    """One ready book (src_a) in OWNER's default project; fresh rate limit counters."""
    deps._llm_calls.clear()
    monkeypatch.setattr(db, "sources", {"src_a": Source(
        id="src_a", project_id=PROJECT, filename="Garden-Cities_Ebenezer-Howard.pdf", kind="document",
        size_bytes=1, status="ready", progress=100, chunk_count=3, created_at=NOW)})
    monkeypatch.setattr(db, "summaries", {})
    yield
    deps._llm_calls.clear()


def call_tool(client: TestClient, user, tool: str, arguments: dict) -> dict:
    """Call a tool with a new personal key of `user`; returns the JSON-RPC result."""
    _, key = api_keys.create(user, "test")
    response = client.post("/mcp", headers={"Authorization": f"Bearer {key}",
                                            "Accept": "application/json, text/event-stream"},
                           json={"jsonrpc": "2.0", "id": 1, "method": "tools/call",
                                 "params": {"name": tool, "arguments": arguments}})
    assert response.status_code == 200
    return response.json()["result"]


def text_of(result: dict) -> str:
    return " ".join(c.get("text", "") for c in result["content"])


def test_the_owner_sees_their_books(server):
    result = call_tool(server, OWNER, "list_books", {})
    assert [b["book_id"] for b in result["structuredContent"]["result"]] == ["src_a"]


def test_another_user_sees_only_their_own_empty_library(server):
    result = call_tool(server, STRANGER, "list_books", {})
    assert result["structuredContent"]["result"] == []


@pytest.mark.parametrize(("tool", "arguments"), [
    ("get_book_summary", {"book_id": "src_a"}),
    ("get_book_summary", {"book_id": "Garden"}),  # by title
    ("search_book", {"query": "garden cities", "book_id": "src_a"}),
    ("ask_book", {"question": "What is a garden city?", "book_id": "src_a"}),
])
def test_another_users_book_cannot_be_reached(server, tool, arguments):
    result = call_tool(server, STRANGER, tool, arguments)
    assert result["isError"] is True
    assert "No single book matches" in text_of(result)


def test_model_tools_have_the_apps_budget(server):
    records.add_usage(UsageRecord(
        timestamp=NOW, operation="ask/answer", kind="chat", model="m", input_tokens=1, output_tokens=1,
        input_cost=5.0, output_cost=0.0, cost=5.0, cost_source="estimate", project_id=PROJECT, user_id=OWNER.id))
    for tool, arguments in [("search_book", {"query": "garden cities"}), ("ask_book", {"question": "Why?"})]:
        result = call_tool(server, OWNER, tool, arguments)
        assert result["isError"] is True
        assert "daily budget of $1.00 is used up" in text_of(result)


def test_model_costs_are_logged_for_the_keys_owner(server, monkeypatch):
    def fake_retrieve(project_id, query, k, source_ids, operation):
        usage.record_embedding(operation, "text-embedding-3-small", tokens=10)
        return []
    monkeypatch.setattr(books, "retrieve_chunks", fake_retrieve)
    result = call_tool(server, STRANGER, "search_book", {"query": "garden cities"})
    assert result.get("isError") is not True
    assert [(r.operation, r.user_id) for r in records.recent_usage(10)] == [("mcp_search_book", STRANGER.id)]
