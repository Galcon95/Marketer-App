"""Tests of the debug mode (core/config.py, core/tracing.py): LangSmith tracing only with DEBUG_MODE and an API key,
and DEBUG_MODE decides for LangChain whatever LANGSMITH_TRACING says. No network calls: no run is started."""

from langchain_core.callbacks.manager import CallbackManager
from langchain_core.tracers.langchain import LangChainTracer

from app.core import config, tracing


def tracer_attached() -> bool:
    """True if LangChain would attach its LangSmith tracer to a run started here."""
    return any(isinstance(h, LangChainTracer) for h in CallbackManager.configure().handlers)


def test_tracing_needs_debug_mode_and_a_key(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test")
    monkeypatch.setattr(config, "DEBUG_MODE", True)
    assert config.tracing_enabled()
    monkeypatch.setattr(config, "DEBUG_MODE", False)
    assert not config.tracing_enabled()
    monkeypatch.setattr(config, "DEBUG_MODE", True)
    monkeypatch.delenv("LANGSMITH_API_KEY")
    monkeypatch.delenv("LANGCHAIN_API_KEY", raising=False)
    assert not config.tracing_enabled()


def test_debug_mode_off_wins_over_langsmith_tracing(monkeypatch):
    monkeypatch.setenv("LANGSMITH_TRACING", "true")
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test")
    monkeypatch.setattr(tracing, "_enabled", False)
    with tracing.scope():
        assert not tracer_attached()


def test_debug_mode_on_attaches_the_tracer(monkeypatch):
    monkeypatch.setenv("LANGSMITH_API_KEY", "lsv2_test")
    monkeypatch.setattr(tracing, "_enabled", True)
    with tracing.scope():
        assert tracer_attached()
