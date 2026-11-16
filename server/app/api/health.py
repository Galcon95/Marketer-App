"""Basic endpoints: smoke tests, health of the API and its services (open, no sign-in), LLM usage and costs
(each user their own; the admin also the whole app's) with the user's budget, and as an Excel download."""

from datetime import datetime, timedelta, timezone
from typing import Literal

from fastapi import APIRouter, Depends, HTTPException, Query, Response

from app.api.deps import admin_only
from app.core import accounts, llm, usage, usage_export
from app.core import state as db
from app.core.auth import User, current_user
from app.core.limits import LIMITS
from app.core.schemas import Health, ServiceStatus, UsageBudget, UsageReport
from app.db import records
from app.rag import vectorstore

router = APIRouter()


@router.get("/")
def root():
    """Smoke-test endpoint: returns a fixed greeting to show the server is reachable."""
    return {"message": "Hello, World!"}


@router.get("/test")
def test():
    """Second smoke-test endpoint used by the client to check the connection."""
    return {"message": "Hello, Server World!"}


@router.get("/health", response_model=Health)
def health():
    """Report the status of the API and its dependencies.

    The vector database is reported with its vector count and embedding model, the LLM with its
    model and whether LangSmith tracing is on (both down if no API key is set). Overall `ok`
    reflects only the API itself.
    """
    vector_ok, vector_detail = vectorstore.health()
    llm_ok, llm_detail = llm.health()
    services = [
        ServiceStatus(name="api", ok=True, detail="running"),
        ServiceStatus(name="vector_db", ok=vector_ok, detail=vector_detail),
        ServiceStatus(name="llm", ok=llm_ok, detail=llm_detail),
    ]
    return Health(ok=services[0].ok, services=services)


@router.get("/usage", response_model=UsageReport)
def get_usage(limit: int = Query(50, ge=1, le=1000), scope: Literal["me", "app"] = "me",
              user: User = Depends(current_user)):
    """Tokens and costs of model calls so far (see usage.py), with how much of the user's budget is used.

    Args:
        limit: Number of latest calls to include (query parameter, 1-1000).
        scope: "me" (default): the user's own calls; "app": all calls of all users (the admin only).

    Returns:
        Totals (input/output tokens and costs, all costs), totals per operation, latest calls, the user's budget.

    Raises:
        HTTPException: 403 for scope "app" from anyone but the admin; 503 if the database cannot be read.
    """
    if scope == "app":
        admin_only(user)
    projects = [p.id for p in db.projects.values() if accounts.owns(user, p)]
    try:
        report = usage.report(limit) if scope == "app" else usage.report(limit, user.id, projects)
        spent_today, spent_month, _ = usage.spending(user.id, projects, datetime.now(timezone.utc))
    except OSError as e:  # DatabaseError
        raise HTTPException(503, "The usage cannot be read right now, please try again.") from e
    report.budget = UsageBudget(spent_today=spent_today, limit_today=LIMITS.per_user.cost_per_day_usd,
                                spent_month=spent_month, limit_month=LIMITS.per_user.cost_per_month_usd)
    return report


XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


@router.get("/usage/export", responses={200: {"content": {XLSX: {}}}})
def export_usage(period: Literal["this_month", "last_month", "all"] = "this_month", scope: Literal["me", "app"] = "me",
                 user: User = Depends(current_user)):
    """Download the model calls of one period as an Excel workbook (usage_export.py): sheets Calls, By day and By
    operation, with tokens and costs in USD. Months are UTC calendar months.

    Args:
        period: "this_month" (default), "last_month" or "all".
        scope: "me" (default): the user's own calls; "app": all users' calls (the admin only).

    Raises:
        HTTPException: 403 for scope "app" from anyone but the admin; 503 if the database cannot be read.
    """
    if scope == "app":
        admin_only(user)
    now = datetime.now(timezone.utc)
    this_month = now.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
    last_month = (this_month - timedelta(days=1)).replace(day=1)
    start, end, label, name = {
        "this_month": (this_month, None, this_month.strftime("%B %Y"), this_month.strftime("%Y-%m")),
        "last_month": (last_month, this_month, last_month.strftime("%B %Y"), last_month.strftime("%Y-%m")),
        "all": (None, None, f"All calls up to {now:%Y-%m-%d}", f"all-{now:%Y-%m-%d}"),
    }[period]
    projects = [p.id for p in db.projects.values() if accounts.owns(user, p)]
    try:
        calls = (records.usage_between(start, end) if scope == "app"
                 else records.usage_between(start, end, user.id, projects))
    except OSError as e:  # DatabaseError
        raise HTTPException(503, "The usage cannot be read right now, please try again.") from e
    whose = "all users" if scope == "app" else "your calls"
    body = usage_export.to_xlsx(calls, f"LLM usage and costs: {label}, {whose}")
    filename = f"llm-usage-{'app-' if scope == 'app' else ''}{name}.xlsx"
    return Response(body, media_type=XLSX, headers={"Content-Disposition": f'attachment; filename="{filename}"'})

