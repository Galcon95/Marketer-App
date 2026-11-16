"""The LLM usage as an Excel download (GET /usage/export, core/usage_export.py): one period, the user's own calls
(or all users' for the admin), sheets Calls / By day / By operation with numbers stored as numbers."""

import io
from datetime import datetime, timedelta, timezone

import pytest
from openpyxl import load_workbook

from app.core import state as db
from app.core.schemas import UsageRecord
from app.db import records
from tests.test_ownership import OWNER, STRANGER, app, client_for  # noqa: F401  (app is a fixture)

NOW = datetime.now(timezone.utc)
THIS_MONTH = NOW.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
LAST_MONTH = (THIS_MONTH - timedelta(days=1)).replace(day=1)


def _call(cost: float, when: datetime, operation: str = "ask/answer", user_id: str = OWNER.id,
          source_id: str | None = None) -> UsageRecord:
    return UsageRecord(timestamp=when, operation=operation, kind="chat", model="openai/gpt-4o-mini", input_tokens=1000,
                       output_tokens=100, input_cost=cost * 0.75, output_cost=cost * 0.25, cost=cost,
                       cost_source="provider", project_id=db.DEFAULT_PROJECT_ID, user_id=user_id, source_id=source_id)


@pytest.fixture
def owner(app):  # noqa: F811
    """Two calls of OWNER this month (one for src_a), one last month, one two months ago; one of STRANGER now."""
    for rec in [_call(0.002, THIS_MONTH + timedelta(hours=1), "generate_blurb/generate", source_id="src_a"),
                _call(0.001, THIS_MONTH + timedelta(hours=2)),
                _call(0.004, LAST_MONTH + timedelta(hours=1)),
                _call(0.008, LAST_MONTH - timedelta(days=20)),
                _call(0.5, THIS_MONTH + timedelta(hours=1), user_id=STRANGER.id)]:
        records.add_usage(rec)
    return client_for(app, OWNER)


def _book(response):
    assert response.status_code == 200
    assert response.headers["content-type"].startswith("application/vnd.openxmlformats")
    return load_workbook(io.BytesIO(response.content))


def _data(sheet) -> list[tuple]:
    """The data rows (between the header row and the total row)."""
    return [row for row in sheet.iter_rows(min_row=3, max_row=sheet.max_row - 1, values_only=True)]


def test_this_month_has_the_users_calls_in_every_sheet(owner):
    response = owner.get("/usage/export")
    assert f'filename="llm-usage-{THIS_MONTH:%Y-%m}.xlsx"' in response.headers["content-disposition"]
    book = _book(response)
    assert book.sheetnames == ["Calls", "By day", "By operation", "By book", "By purpose", "By campaign"]
    calls = book["Calls"]
    assert calls["A1"].value == f"LLM usage and costs: {THIS_MONTH:%B %Y}, your calls"
    assert calls["A2"].value == "Time (UTC)" and calls.freeze_panes == "A3"
    rows = _data(calls)
    assert [(r[1], r[8]) for r in rows] == [("generate_blurb/generate", 0.002), ("ask/answer", 0.001)]  # oldest first
    assert isinstance(rows[0][0], datetime) and rows[0][4] == 1000  # a date and a number, not text
    assert rows[0][9] == "exact" and rows[0][10] == "a" and rows[1][10] in ("", None)
    assert rows[0][11] == "Blurb" and rows[1][11] == "Ask your book"  # purpose, also of untagged older calls
    total = calls[calls.max_row]
    assert total[0].value == "Total" and total[8].value == f"=SUM(I3:I{calls.max_row - 1})"
    by_operation = _data(book["By operation"])
    assert [r[0] for r in by_operation] == ["generate_blurb/generate", "ask/answer"]  # highest cost first
    assert _data(book["By day"])[0][1] == 2  # both calls on the first day of the month


def test_last_month_and_all(owner):
    last = _book(owner.get("/usage/export", params={"period": "last_month"}))
    assert [r[8] for r in _data(last["Calls"])] == [0.004]
    everything = _book(owner.get("/usage/export", params={"period": "all"}))
    assert sorted(r[8] for r in _data(everything["Calls"])) == [0.001, 0.002, 0.004, 0.008]  # never STRANGER's


def test_a_month_without_calls_is_an_empty_table(app):  # noqa: F811
    book = _book(client_for(app, STRANGER).get("/usage/export", params={"period": "last_month"}))
    assert _data(book["Calls"]) == [] and book["Calls"]["A3"].value == "Total"


def test_costs_per_book_purpose_and_campaign(app):  # noqa: F811
    db.assets["ast_k"] = db.assets["ast_a"].model_copy(update={"id": "ast_k", "campaign_id": "cmp_k",
                                                               "brief": 'Book: "Garden Cities" by Howard'})
    for rec in [_call(0.003, THIS_MONTH + timedelta(hours=1), "generate_newsletter/generate", source_id="src_a"),
                _call(0.001, THIS_MONTH + timedelta(hours=2), "generate_campaign/personas", source_id="src_a"),
                _call(0.002, THIS_MONTH + timedelta(hours=3), "summarize_book/summarize_chapter")]:
        records.add_usage(rec)
    records.add_usage(_call(0.004, THIS_MONTH + timedelta(hours=4), "generate_campaign/polish").model_copy(
        update={"campaign_id": "cmp_k", "source_id": "src_a"}))
    book = _book(client_for(app, OWNER).get("/usage/export"))
    by_book = {r[0]: r[6] for r in _data(book["By book"])}
    assert by_book == {"a": pytest.approx(0.008), "(not recorded)": 0.002}
    by_purpose = {r[0]: r[6] for r in _data(book["By purpose"])}
    assert by_purpose == {"Campaign kit": pytest.approx(0.005), "Newsletter": 0.003, "Book summary": 0.002}
    assert [r[0] for r in _data(book["By purpose"])][0] == "Campaign kit"  # highest cost first
    assert [(r[0], r[6]) for r in _data(book["By campaign"])] == [("Garden Cities (cmp_k)", 0.004)]
