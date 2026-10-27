"""Usage and cost logger for every model call: tokens in/out and costs in USD, with running totals.

Chat calls are captured by a LangChain callback handler (UsageCallbackHandler) attached to the chat
model, so every LLM call is logged automatically: asset generation, answers, book summaries. Their
costs are the exact amounts OpenRouter reports for the call (split into input and output); without
them (e.g. OpenAI directly) costs are estimated from PRICES. Embedding calls are logged by
vectorstore.py: LangChain does not pass their usage on, so their tokens are counted with tiktoken
(the embedding models' own tokenizer) and priced from PRICES.

Each call is
  - appended to USAGE_FILE (server/assets/usage/usage.jsonl), one JSON object per line, and
  - printed to the server console with the totals so far (input cost, output cost, all costs).
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
from pydantic import ValidationError

from app.core.config import DATA_DIR
from app.core.schemas import UsageRecord, UsageReport, UsageTotals

USAGE_FILE = DATA_DIR / "usage" / "usage.jsonl"

# USD per 1 million tokens (input, output), by model name without provider prefix. Used for
# embeddings and when the provider reports no cost. Source: OpenAI price list (= OpenRouter prices).
PRICES: dict[str, tuple[float, float]] = {
    "gpt-4o-mini": (0.15, 0.60),
    "gpt-4o": (2.50, 10.00),
    "text-embedding-3-large": (0.13, 0.0),
    "text-embedding-3-small": (0.02, 0.0),
}

# Console output: own handler, because uvicorn does not show INFO logs of application modules.
logger = logging.getLogger("usage")
if not logger.handlers:
    _console = logging.StreamHandler()
    _console.setFormatter(logging.Formatter("USAGE  %(message)s"))
    logger.addHandler(_console)
    logger.setLevel(logging.INFO)
    logger.propagate = False

_lock = threading.Lock()
_records: list[UsageRecord] = []  # all calls so far (loaded from USAGE_FILE on startup)
_totals = UsageTotals()


# ---------- Recording ----------
def record(rec: UsageRecord) -> None:
    """Log one model call: append it to USAGE_FILE, update the totals and print a console line.

    Logging must never break the actual request, so file errors are only reported.

    Args:
        rec: The call to log.
    """
    with _lock:
        _records.append(rec)
        _add(_totals, rec)
        totals = _totals.model_copy()
        try:
            USAGE_FILE.parent.mkdir(parents=True, exist_ok=True)
            with USAGE_FILE.open("a", encoding="utf-8") as f:
                f.write(rec.model_dump_json() + "\n")
        except OSError as e:
            logger.warning("Could not write %s: %s", USAGE_FILE, e)
            
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
    """Read USAGE_FILE into memory and compute the totals (called once on server startup)."""
    with _lock:
        _records.clear()
        global _totals
        _totals = UsageTotals()
        try:
            lines = USAGE_FILE.read_text(encoding="utf-8").splitlines()
        except OSError:
            return
        for line in lines:
            try:
                rec = UsageRecord.model_validate_json(line)
            except ValidationError:
                continue
            _records.append(rec)
            _add(_totals, rec)


def report(limit: int = 50) -> UsageReport:
    """Totals so far, totals per operation (highest cost first) and the latest `limit` calls."""
    with _lock:
        by_operation: dict[str, UsageTotals] = {}
        for rec in _records:
            _add(by_operation.setdefault(rec.operation, UsageTotals()), rec)
        return UsageReport(
            totals=_totals.model_copy(),
            by_operation=dict(sorted(by_operation.items(), key=lambda item: item[1].cost, reverse=True)),
            recent=list(reversed(_records[-limit:])),
        )


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
