"""Usage and cost logger for every model call: tokens in/out and costs in USD, with running totals.

Chat calls are captured by a LangChain callback handler (UsageCallbackHandler) attached to the chat
model, so every LLM call is logged automatically: asset generation, answers, book summaries. Their
costs are the exact amounts OpenRouter reports for the call (split into input and output); without
them (e.g. OpenAI directly) costs are estimated from PRICES. Embedding calls are logged by
vectorstore.py: LangChain does not pass their usage on, so their tokens are counted with tiktoken
(the embedding models' own tokenizer) and priced from PRICES.

Each call is
  - saved in the database (table usage_log, app/db/records.py) with the id of the HTTP request that caused it
    (logs.py) and the signed-in user, and
  - logged to the server console with the totals so far (input cost, output cost, all costs).
Reports and budgets are sums the database computes (records.usage_totals, records.spending); only the app-wide
totals for the console line are kept in memory.
The operation name comes from the run's metadata: "operation" set by the graph invocation plus the
LangGraph node, e.g. "summarize_book/summarize_chapter".
"""

import logging
import threading
from collections.abc import Iterable
from datetime import datetime, timezone
from functools import cache
from typing import Any
from uuid import UUID

import tiktoken
from langchain_core.callbacks import BaseCallbackHandler
from langchain_core.outputs import LLMResult
from app.core.logs import current_request_id, current_user_id
from app.core.schemas import UsageRecord, UsageReport, UsageTotals
from app.db import records

# USD per 1 million tokens (input, output), by model name without provider prefix. Used for
# embeddings and when the provider reports no cost. Source: OpenAI price list (= OpenRouter prices).
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "text-embedding-3-large": (0.13, 0.0),
    "text-embedding-3-small": (0.02, 0.0),
}

logger = logging.getLogger("usage")  # goes to the console handler set up in logs.py

_lock = threading.Lock()
_totals = UsageTotals()  # all calls so far, for the console line (loaded from the database on startup)


# ---------- Recording ----------
def record(rec: UsageRecord) -> None:
    """Log one model call: save it in the database, update the totals and print a console line.

    Logging must never break the actual request, so database errors are only reported (the call is then missing
    from the reports and budgets).

    Args:
        rec: The call to log; its request_id and user_id are filled in from the current HTTP request if not set.
    """
    if rec.request_id is None:
        rec.request_id = current_request_id()
    if rec.user_id is None:
        rec.user_id = current_user_id()
    try:
        records.add_usage(rec)
    except OSError as e:  # DatabaseError
        logger.warning("Could not save the usage of %s: %s", rec.operation, e)
    with _lock:
        _add(_totals, rec)
        totals = _totals.model_copy()
    logger.info(
        "%-38s %-28s in %7s tok %s | out %6s tok %s | call %s || total so far: in %s, out %s, all %s (%d calls)",
        rec.operation, rec.model, f"{rec.input_tokens:,}", _usd(rec.input_cost), f"{rec.output_tokens:,}",
        _usd(rec.output_cost), _usd(rec.cost), _usd(totals.input_cost), _usd(totals.output_cost),
        _usd(totals.cost), totals.calls,
    )


def record_embedding(operation: str, model: str, texts: Iterable[str] | None = None, tokens: int | None = None,
                     project_id: str | None = None, source_id: str | None = None) -> None:
    """Log an embedding call; its cost is estimated from PRICES (embeddings only have input tokens).

    Args:
        operation: What it was for, e.g. "embed_chunks" or "ask/embed_query".
        model: Embedding model name (with or without provider prefix).
        texts: The embedded texts; their tokens are counted if `tokens` is not given.
        tokens: Token count, if already known (e.g. the chunks' token_count).
        project_id: Optional project the call belongs to.
        source_id: Optional source the call belongs to.
    """
    if tokens is None:
        tokens = sum(count_tokens(t) for t in texts or [])
    input_price, _ = _price(model)
    cost = tokens * input_price / 1_000_000
    record(UsageRecord(
        timestamp=datetime.now(timezone.utc), operation=operation, kind="embedding", model=model,
        input_tokens=tokens, output_tokens=0, input_cost=cost, output_cost=0.0, cost=cost,
        cost_source="estimate", project_id=project_id, source_id=source_id,
    ))


class UsageCallbackHandler(BaseCallbackHandler):
    """LangChain callback handler that logs every chat model call with its tokens and costs.

    on_chat_model_start remembers the run's metadata (operation, LangGraph node, project/source id);
    on_llm_end reads the token usage and OpenRouter's cost details from the reply and calls record().
    """

    def __init__(self) -> None:
        self._runs: dict[UUID, dict[str, Any]] = {}  # run id → metadata, until the call ends

    def on_chat_model_start(self, serialized: dict[str, Any], messages: list, *, run_id: UUID,
                            metadata: dict[str, Any] | None = None, **kwargs: Any) -> None:
        """Remember the metadata of a starting chat call."""
        self._runs[run_id] = metadata or {}

    def on_llm_error(self, error: BaseException, *, run_id: UUID, **kwargs: Any) -> None:
        """Forget a failed call (nothing is charged for it)."""
        self._runs.pop(run_id, None)

    def on_llm_end(self, response: LLMResult, *, run_id: UUID, **kwargs: Any) -> None:
        """Log a finished chat call: tokens from usage_metadata, costs from OpenRouter (or PRICES)."""
        meta = self._runs.pop(run_id, {})
        try:
            message = response.generations[0][0].message
        except (IndexError, AttributeError):
            return
        usage = getattr(message, "usage_metadata", None) or {}
        token_usage = message.response_metadata.get("token_usage") or (response.llm_output or {}).get("token_usage") or {}
        model = message.response_metadata.get("model_name") or (response.llm_output or {}).get("model_name") or "unknown"
        input_tokens = usage.get("input_tokens", token_usage.get("prompt_tokens", 0))
        output_tokens = usage.get("output_tokens", token_usage.get("completion_tokens", 0))

        details = token_usage.get("cost_details") or {}
        if token_usage.get("cost") is not None:  # exact cost reported by OpenRouter
            cost = float(token_usage["cost"])
            input_cost = float(details.get("upstream_inference_prompt_cost") or 0.0)
            output_cost = float(details.get("upstream_inference_completions_cost") or 0.0)
            if not details:  # total only: split it by the price list ratio
                input_cost, output_cost = _split(cost, model, input_tokens, output_tokens)
            source = "provider"
        else:
            input_price, output_price = _price(model)
            input_cost = input_tokens * input_price / 1_000_000
            output_cost = output_tokens * output_price / 1_000_000
            cost, source = input_cost + output_cost, "estimate"

        operation = meta.get("operation", "llm")
        if meta.get("langgraph_node"):
            operation += f"/{meta['langgraph_node']}"
        record(UsageRecord(
            timestamp=datetime.now(timezone.utc), operation=operation, kind="chat", model=model,
            input_tokens=input_tokens, output_tokens=output_tokens, input_cost=input_cost,
            output_cost=output_cost, cost=cost, cost_source=source,
            project_id=meta.get("project_id"), source_id=meta.get("source_id"),
        ))


handler = UsageCallbackHandler()  # attached to the chat model in llm.chat_model()


# ---------- Reading ----------
def load() -> None:
    """Compute the app-wide totals for the console line from the database (called once on server startup).

    Raises:
        DatabaseError: If the database cannot be read.
    """
    global _totals
    totals = records.usage_totals()
    with _lock:
        _totals = totals


def report(limit: int = 50, user_id: str | None = None, project_ids: Iterable[str] = ()) -> UsageReport:
    """Totals so far, totals per operation (highest cost first) and the latest `limit` calls: of all calls, or with
    `user_id` only of that user's calls (records._of_user).

    Raises:
        DatabaseError: If the database cannot be read.
    """
    project_ids = list(project_ids)
    return UsageReport(totals=records.usage_totals(user_id, project_ids),
                       by_operation=records.usage_by_operation(user_id, project_ids),
                       recent=records.recent_usage(limit, user_id, project_ids))


def spending(user_id: str, project_ids: Iterable[str], now: datetime) -> tuple[float, float, float]:
    """What the user spent today and this month (UTC) and what all users spent today, in USD.

    Raises:
        DatabaseError: If the database cannot be read.
    """
    today = now.replace(hour=0, minute=0, second=0, microsecond=0)
    user_today, user_month, app_today = records.spending(user_id, project_ids, today, today.replace(day=1))
    return user_today, user_month, app_today


# ---------- Helpers ----------
@cache
def _encoding() -> tiktoken.Encoding:
    """cl100k_base, the tokenizer of the OpenAI text-embedding-3 models."""
    return tiktoken.get_encoding("cl100k_base")


def count_tokens(text: str) -> int:
    """Number of tokens of a text for the embedding models."""
    return len(_encoding().encode(text))


def _price(model: str) -> tuple[float, float]:
    """(input, output) USD per 1M tokens for a model, (0, 0) if unknown. "openai/gpt-4o-mini" → "gpt-4o-mini"."""
    name = model.split("/")[-1]
    for known, price in PRICES.items():  # also matches dated names such as "gpt-4o-mini-2024-07-18"
        if name == known or name.startswith(known + "-"):
            return price
    return 0.0, 0.0


def _split(cost: float, model: str, input_tokens: int, output_tokens: int) -> tuple[float, float]:
    """Split a total cost into input and output parts in the ratio of the price list."""
    input_price, output_price = _price(model)
    weight_in, weight_out = input_tokens * input_price, output_tokens * output_price
    if weight_in + weight_out == 0:
        return cost, 0.0
    return cost * weight_in / (weight_in + weight_out), cost * weight_out / (weight_in + weight_out)


def _add(totals: UsageTotals, rec: UsageRecord) -> None:
    """Add one call to a totals object (in place)."""
    totals.calls += 1
    totals.input_tokens += rec.input_tokens
    totals.output_tokens += rec.output_tokens
    totals.input_cost += rec.input_cost
    totals.output_cost += rec.output_cost
    totals.cost += rec.cost


def _usd(amount: float) -> str:
    """Format a USD amount with enough decimals for fractions of a cent, e.g. "$0.000435"."""
    return f"${amount:.6f}" if amount < 0.01 else f"${amount:.4f}"
