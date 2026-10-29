"""Request ids and log format (logs.py): every request gets an id that reaches the code handling it, its log
lines and its usage records, and is returned in the X-Request-ID header. No model calls."""

import json
import logging
from datetime import datetime, timezone

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from app.core import logs, usage
from app.core.schemas import UsageRecord


@pytest.fixture
def client():
    """A small app behind the middleware whose endpoint returns the request id it sees."""
    app = FastAPI()

    @app.get("/whoami")
    def whoami():
        return {"request_id": logs.current_request_id()}

    app.add_middleware(logs.RequestIdMiddleware)
    with TestClient(app) as test_client:
        yield test_client


def test_each_request_gets_a_new_id_in_context_and_header(client):
    first, second = client.get("/whoami"), client.get("/whoami")
    assert first.json()["request_id"] == first.headers[logs.HEADER]
    assert first.headers[logs.HEADER] != second.headers[logs.HEADER]
    assert logs.current_request_id() is None  # reset after the request


def test_a_sane_incoming_id_is_kept(client):
    response = client.get("/whoami", headers={logs.HEADER: "client-42.retry_1"})
    assert response.json()["request_id"] == "client-42.retry_1"
    assert response.headers[logs.HEADER] == "client-42.retry_1"


@pytest.mark.parametrize("bad", ["has space", "x" * 65, "line\tbreak", "<script>"])
def test_an_unsafe_incoming_id_is_replaced(client, bad):
    response = client.get("/whoami", headers={logs.HEADER: bad})
    assert response.headers[logs.HEADER] != bad
    assert response.json()["request_id"] == response.headers[logs.HEADER]


def test_json_formatter_writes_one_line_with_the_request_id():
    record = logging.LogRecord("app.api.deps", logging.WARNING, __file__, 1, "Blocked %s", ("question",), None)
    token = logs.request_id.set("abc123")
    try:
        logs.RequestIdFilter().filter(record)
    finally:
        logs.request_id.reset(token)
    line = logs.JsonFormatter().format(record)
    assert "\n" not in line
    entry = json.loads(line)
    assert entry["request_id"] == "abc123"
    assert entry["level"] == "WARNING"
    assert entry["logger"] == "app.api.deps"
    assert entry["message"] == "Blocked question"


def test_records_outside_a_request_get_a_dash():
    record = logging.LogRecord("startup", logging.INFO, __file__, 1, "ready", (), None)
    logs.RequestIdFilter().filter(record)
    assert record.request_id == "-"


def test_usage_records_get_the_current_request_id(monkeypatch, tmp_path):
    monkeypatch.setattr(usage, "USAGE_FILE", tmp_path / "usage.jsonl")
    monkeypatch.setattr(usage, "_records", [])
    monkeypatch.setattr(usage, "_totals", usage.UsageTotals())
    rec = UsageRecord(timestamp=datetime.now(timezone.utc), operation="ask/answer", kind="chat", model="m",
                      input_tokens=1, output_tokens=1, input_cost=0.0, output_cost=0.0, cost=0.0,
                      cost_source="estimate")
    token = logs.request_id.set("req-7")
    try:
        usage.record(rec)
    finally:
        logs.request_id.reset(token)
    saved = json.loads((tmp_path / "usage.jsonl").read_text(encoding="utf-8"))
    assert saved["request_id"] == "req-7"
