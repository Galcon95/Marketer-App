"""The shared checkpointer's helpers (agents/checkpoints.py); the restore of each agent is tested with the agent."""

from datetime import UTC, datetime, timedelta

from langgraph.checkpoint.memory import MemorySaver

from app.agents import checkpoints


def test_runs_older_than_keep_days_are_old():
    now = datetime.now(UTC)
    assert checkpoints.is_old((now - timedelta(days=checkpoints.KEEP_DAYS + 1)).isoformat())
    assert not checkpoints.is_old((now - timedelta(days=1)).isoformat())
    assert not checkpoints.is_old(None)


def test_tests_use_memory_not_the_database():
    assert isinstance(checkpoints.checkpointer(), MemorySaver)  # conftest's agent_checkpoints


def test_the_sqlalchemy_url_is_turned_back_into_a_psycopg_one(monkeypatch):
    monkeypatch.setattr(checkpoints.config, "DATABASE_URL", "postgresql+psycopg://u:p%40ss@host:5432/postgres")
    assert checkpoints._postgres_url() == "postgresql://u:p%40ss@host:5432/postgres"
    monkeypatch.setattr(checkpoints.config, "DATABASE_URL", "sqlite://")
    assert checkpoints._postgres_url() == ""
