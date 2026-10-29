"""The chat model shared by all LangGraph graphs (generation, Q&A, summaries, campaign kit).

ChatOpenAI talks to OpenRouter or OpenAI (see config.py); usage.handler logs every call with its
tokens and costs. GenerationError is the common error of all model-backed features, carrying the
HTTP status the API should return; model_failure turns any exception of a model call into one (504 for
timeouts, 502 otherwise). structured() is the one way the app asks for structured output: the reply is
validated against a Pydantic schema and asked for once more if it does not fit.
"""

import logging
from functools import cache
from typing import Any, TypeVar

import httpx
import openai
from langchain_core.messages import AIMessage
from langchain_core.prompts import ChatPromptTemplate
from langchain_openai import ChatOpenAI
from pydantic import BaseModel

from app.core import config, usage
from app.core import tracing as tracing_switch

logger = logging.getLogger(__name__)

LLM_TEMPERATURE = 0.7  # some creativity for marketing copy; facts are constrained by the prompts
STRUCTURED_ATTEMPTS = 2  # a structured reply that does not fit its schema is asked for once more

Schema = TypeVar("Schema", bound=BaseModel)


class GenerationError(Exception):
    """A model-backed feature failed; status_code is the HTTP status the API should return (409, 502, 503 or 504)."""

    def __init__(self, status_code: int, detail: str):
        super().__init__(detail)
        self.status_code = status_code


def is_configured() -> bool:
    """True if an API key for the models is set (the same key serves chat and embeddings)."""
    return bool(config.API_KEY)


@cache
def chat_model(temperature: float = LLM_TEMPERATURE) -> ChatOpenAI:
    """The chat model, via OpenRouter or OpenAI (same key and endpoint as the embeddings).

    One cached instance per temperature. usage.handler logs every call with its tokens and costs (usage.py).
    Each request times out after LLM_TIMEOUT_SECONDS and is retried up to LLM_MAX_RETRIES times (config.py),
    so every graph inherits the same limits.

    Args:
        temperature: Sampling temperature; higher = more varied wording.
    """
    return ChatOpenAI(model=config.LLM_MODEL, api_key=config.API_KEY, base_url=config.BASE_URL,
                      temperature=temperature, timeout=config.LLM_TIMEOUT_SECONDS,
                      max_retries=config.LLM_MAX_RETRIES, callbacks=[usage.handler])


def is_timeout(error: BaseException) -> bool:
    """True if the error, or an error it was raised from, is a timeout of a model or embedding request."""
    seen = set()
    while error is not None and id(error) not in seen:
        if isinstance(error, (openai.APITimeoutError, httpx.TimeoutException, TimeoutError)):
            return True
        seen.add(id(error))
        error = error.__cause__ or error.__context__
    return False


def model_failure(error: Exception, what: str | None = "The language model call failed") -> GenerationError:
    """The GenerationError for a failed model call: 504 if the provider timed out (after all retries), so the UI can
    offer to try again, else 502 with `what` and the error (the error alone if `what` is None).

    Args:
        error: The exception the model call or retrieval raised.
        what: Start of the 502 message; None for errors whose message already says what failed.
    """
    if is_timeout(error):
        return GenerationError(504, "The language model did not answer in time, even after retrying. Please try again.")
    return GenerationError(502, f"{what}: {error}" if what else str(error))


def structured(prompt: ChatPromptTemplate, values: dict[str, Any], schema: type[Schema], what: str,
               temperature: float = LLM_TEMPERATURE) -> tuple[Schema, int]:
    """Call the chat model for structured output and validate the reply against `schema`.

    The schema is the contract: types, list lengths, number ranges and validators (e.g. "exactly five posts, one per
    angle") are checked by Pydantic, not only asked for in the prompt. A reply that does not fit (or a refusal) is
    logged and requested once more; there is no fallback to the raw text, which would be JSON or a refusal.

    Args:
        prompt: The prompt template.
        values: Its variables.
        schema: The Pydantic model the reply must fit.
        what: What is asked for, for the error message, e.g. "reader personas".
        temperature: Sampling temperature.

    Returns:
        The validated reply and the tokens of all attempts.

    Raises:
        GenerationError: 502 if no attempt fits the schema.
    """
    model = chat_model(temperature).with_structured_output(schema, include_raw=True)
    tokens, error = 0, None
    for attempt in range(1, STRUCTURED_ATTEMPTS + 1):
        result = (prompt | model).invoke(values)
        tokens += tokens_used(result["raw"])
        if (parsed := result.get("parsed")) is not None:
            return parsed, tokens
        error = result.get("parsing_error") or getattr(result["raw"], "additional_kwargs", {}).get("refusal")
        logger.warning("%s: reply %d/%d does not fit %s: %s", what, attempt, STRUCTURED_ATTEMPTS, schema.__name__, error)
    raise GenerationError(502, f"The model returned no usable {what}. Please try again.")


def tokens_used(reply: AIMessage) -> int:
    """Total tokens (prompt + completion) of a model reply, 0 if the provider reported no usage."""
    return (reply.usage_metadata or {}).get("total_tokens", 0)


def health() -> tuple[bool, str]:
    """Status of the language model for GET /health: (ok, detail with model and provider). In debug mode the detail
    also says that LangSmith tracing is on; otherwise tracing is not mentioned, so customers see nothing of it."""
    debug = ["debug mode · LangSmith tracing on"] if tracing_switch.enabled() else []
    if not is_configured():
        return False, " · ".join([config.LLM_MODEL, "no API key", *debug])
    return True, " · ".join([f"{config.LLM_MODEL} via {config.PROVIDER}", *debug])
