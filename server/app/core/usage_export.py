"""The LLM usage as an Excel workbook (GET /usage/export): one period's model calls with tokens and costs.

Sheets:
    Calls         every call, oldest first: time (UTC), operation, kind, model, tokens, costs, exact or estimated, book,
                  purpose, campaign
    By day        one row per day: calls, tokens, costs (good for a chart)
    By operation  one row per operation, highest cost first (like "By operation" in the usage panel)
    By book       one row per book (calls tagged with one book, see usage.tagged)
    By purpose    one row per purpose: the asset format (Newsletter, Ad copy, ...), Campaign kit, Book summary, ...
    By campaign   one row per campaign kit, with its book title

Calls from before the tagging, or for no single book or campaign, are grouped as "(not recorded)" / "(none)". The
purpose of older single-asset calls is still known from their operation name ("generate_newsletter/...").

Numbers are stored as numbers (costs as USD with 6 decimals), so Excel with any locale can sum and chart them;
every sheet has a bold, frozen header row, filters and a total row.
"""

import io
import re
from collections import defaultdict
from collections.abc import Callable, Iterable
from datetime import date, datetime

from openpyxl import Workbook
from openpyxl.styles import Font
from openpyxl.utils import get_column_letter
from openpyxl.worksheet.worksheet import Worksheet

from app.core import state as db
from app.core.export import TYPE_LABELS
from app.core.schemas import UsageRecord, UsageTotals
from app.rag.retrieval import source_name

USD = '"$"#,##0.000000'
INT = "#,##0"
SUMMED = ["calls", "input_tokens", "output_tokens", "input_cost", "output_cost", "cost"]
SUM_HEADERS = ["Calls", "Input tokens", "Output tokens", "Input cost (USD)", "Output cost (USD)", "Cost (USD)"]
SUM_FORMATS = [INT, INT, INT, USD, USD, USD]
NOT_RECORDED = "(not recorded)"

# Purposes of calls outside single assets and kits, by the first part of their operation name.
OPERATION_PURPOSES = {
    "summarize_book": "Book summary", "embed_chunks": "Book indexing", "ask": "Ask your book",
    "generate_campaign": "Campaign kit", "discussion": "Discussion agent", "page_inbox": "Page inbox agent",
    "verify": "Fact check", "mcp_ask_book": "MCP: ask a book", "mcp_search_book": "MCP: search a book",
}


def purpose(call: UsageRecord) -> str:
    """What a call was for, e.g. "Newsletter", "Campaign kit", "Book summary"; the operation name if unknown."""
    if call.asset_type:
        return TYPE_LABELS.get(call.asset_type, call.asset_type)
    if call.campaign_id:
        return "Campaign kit"
    head = call.operation.split("/")[0]
    if head.startswith("generate_") and head[len("generate_"):] in TYPE_LABELS:  # older calls of single assets
        return TYPE_LABELS[head[len("generate_"):]]
    return OPERATION_PURPOSES.get(head, head)


def to_xlsx(calls: list[UsageRecord], title: str) -> bytes:
    """The workbook as bytes. `title` names the period and whose calls, e.g. "November 2026, your calls"."""
    book = Workbook()
    sheet = book.active
    sheet.title = "Calls"
    _table(sheet, title,
           ["Time (UTC)", "Operation", "Kind", "Model", "Input tokens", "Output tokens", "Input cost (USD)",
            "Output cost (USD)", "Cost (USD)", "Cost source", "Book", "Purpose", "Campaign"],
           [[c.timestamp.replace(tzinfo=None), c.operation, c.kind, c.model, c.input_tokens, c.output_tokens,
             c.input_cost, c.output_cost, c.cost, "exact" if c.cost_source == "provider" else "estimate",
             (source_name(c.source_id) or c.source_id) if c.source_id else "", purpose(c), c.campaign_id or ""]
            for c in calls],
           ["yyyy-mm-dd hh:mm:ss", None, None, None, INT, INT, USD, USD, USD, None, None, None, None],
           sum_from=4)
    by_day = _group(calls, lambda c: c.timestamp.date())
    _table(book.create_sheet("By day"), title, ["Day", *SUM_HEADERS],
           [[day, *_values(t)] for day, t in sorted(by_day.items())], ["yyyy-mm-dd", *SUM_FORMATS], sum_from=1)
    by_operation = _group(calls, lambda c: c.operation)
    _table(book.create_sheet("By operation"), title, ["Operation", *SUM_HEADERS],
           [[op, *_values(t)] for op, t in sorted(by_operation.items(), key=lambda item: -item[1].cost)],
           [None, *SUM_FORMATS], sum_from=1)
    _summed_sheet(book, "By book", "Book", title, calls,
                  lambda c: (source_name(c.source_id) or c.source_id) if c.source_id else NOT_RECORDED)
    _summed_sheet(book, "By purpose", "Purpose", title, calls, purpose)
    names = _campaign_names()
    _summed_sheet(book, "By campaign", "Campaign", title, [c for c in calls if c.campaign_id],
                  lambda c: f"{names.get(c.campaign_id, 'deleted kit')} ({c.campaign_id})")
    out = io.BytesIO()
    book.save(out)
    return out.getvalue()


def _summed_sheet(book: Workbook, name: str, label: str, title: str, calls: list[UsageRecord],
                  key: Callable[[UsageRecord], str]) -> None:
    """A sheet with one row of sums per key, highest cost first."""
    groups = _group(calls, key)
    _table(book.create_sheet(name), title, [label, *SUM_HEADERS],
           [[k, *_values(t)] for k, t in sorted(groups.items(), key=lambda item: -item[1].cost)],
           [None, *SUM_FORMATS], sum_from=1)


def _campaign_names() -> dict[str, str]:
    """Campaign id → the book title of its brief (from the kits still in memory)."""
    names: dict[str, str] = {}
    for a in db.assets.values():
        if a.campaign_id and a.campaign_id not in names:
            match = re.match(r'Book: "([^"]+)"', a.brief)
            names[a.campaign_id] = match.group(1) if match else "Campaign"
    return names


def _group(calls: Iterable[UsageRecord], key: Callable[[UsageRecord], date | str]) -> dict:
    """Totals per key (day or operation)."""
    groups: dict = defaultdict(UsageTotals)
    for c in calls:
        t = groups[key(c)]
        t.calls += 1
        t.input_tokens += c.input_tokens
        t.output_tokens += c.output_tokens
        t.input_cost += c.input_cost
        t.output_cost += c.output_cost
        t.cost += c.cost
    return groups


def _values(t: UsageTotals) -> list:
    return [getattr(t, field) for field in SUMMED]


def _table(sheet: Worksheet, title: str, headers: list[str], rows: list[list], formats: list[str | None],
           sum_from: int) -> None:
    """Write a title line, a bold frozen header row with filters, the rows and a bold total row that sums the
    columns from index `sum_from` on (Excel formulas, so they follow edits); set number formats and widths."""
    sheet.append([title])
    sheet["A1"].font = Font(bold=True, size=12)
    sheet.append(headers)
    for cell in sheet[2]:
        cell.font = Font(bold=True)
    for row in rows:
        sheet.append(row)
    first, last = 3, 2 + len(rows)
    total = ["Total", *[None] * (len(headers) - 1)]
    for i in range(sum_from, len(headers)):
        if formats[i] in (INT, USD):
            col = get_column_letter(i + 1)
            total[i] = f"=SUM({col}{first}:{col}{last})" if rows else 0
    sheet.append(total)
    for cell in sheet[sheet.max_row]:
        cell.font = Font(bold=True)
    for i, fmt in enumerate(formats, start=1):
        if fmt:
            for (cell,) in sheet.iter_rows(min_row=first, max_row=sheet.max_row, min_col=i, max_col=i):
                cell.number_format = fmt
    sheet.freeze_panes = "A3"
    sheet.auto_filter.ref = f"A2:{get_column_letter(len(headers))}{max(last, 2)}"
    for i, header in enumerate(headers, start=1):
        values = [header, *(row[i - 1] for row in rows)]
        width = max(len(v.strftime("%Y-%m-%d %H:%M:%S")) if isinstance(v, datetime) else len(str(v)) for v in values)
        sheet.column_dimensions[get_column_letter(i)].width = min(max(width + 2, 10), 50)
