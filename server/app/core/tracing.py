"""LangSmith tracing, for developers only: on in debug mode (DEBUG_MODE=true in server/.env, plus LANGSMITH_API_KEY),
otherwise off. Read once at startup; change it in server/.env and restart the server. Customers never see it.

Every graph run (Q&A, asset generation, book summary, campaign kit) is wrapped in scope(), which sets LangSmith's
tracing context explicitly. That context overrides the LANGSMITH_TRACING environment variable, so DEBUG_MODE alone
decides for every model call (all model calls of the app happen inside these graphs): with debug mode off, no
prompt, book text, question or generated text leaves for LangSmith.
"""

import logging
from collections.abc import Iterator
from contextlib import contextmanager

import langsmith

from app.core import config

logger = logging.getLogger(__name__)

_enabled = config.tracing_enabled()

if config.DEBUG_MODE and not _enabled:
    logger.warning("DEBUG_MODE is on, but LangSmith tracing is off: no LANGSMITH_API_KEY set.")


def enabled() -> bool:
    """True if graph runs are traced in LangSmith."""
    return _enabled


@contextmanager
def scope() -> Iterator[None]:
    """Run the code inside (one graph run) with tracing on or off as configured, into config.LANGSMITH_PROJECT."""
    with langsmith.tracing_context(enabled=_enabled, project_name=config.LANGSMITH_PROJECT):
        yield
