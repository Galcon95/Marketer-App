"""Shared test setup: a signed-in test user who owns the default project, without Supabase.

Every test gets an empty in-memory SQLite database instead of the real one (DATABASE_URL is never used), a fresh
project list (the default project, owned by OWNER, also saved in that database) and no API keys. Tests that build an app with API routers call sign_in(app) to be OWNER (or another user).
"""

import pytest
from fastapi import FastAPI
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool

from app.campaign import kit
from app.core import api_keys, auth, config, files, llm, storage, usage
from app.core import state as db
from app.core.auth import User
from app.core.schemas import Project, UsageTotals
from app.db import database, records
from app.db.tables import PRIVATE, Base
from app.rag import vectorstore

OWNER = User(id="user-owner", email="owner@example.com")  # owns the default project
STRANGER = User(id="user-stranger", email="stranger@example.com")  # another signed-in user


def sign_in(app: FastAPI, user: User = OWNER) -> None:
    """Make every request to this app come from `user` (instead of checking a Supabase access token)."""
    app.dependency_overrides[auth.current_user] = lambda: user


@pytest.fixture(autouse=True)
def test_database(monkeypatch):
    """An empty in-memory SQLite database with all tables, used instead of DATABASE_URL. SQLite has no "private"
    schema: its tables go to SQLite's only one. StaticPool: one connection, so every session sees the same data
    (and the foreign key setting)."""
    engine = create_engine("sqlite://", poolclass=StaticPool, connect_args={"check_same_thread": False})
    engine = engine.execution_options(schema_translate_map={PRIVATE: None})
    with engine.connect() as connection:  # SQLite checks foreign keys (e.g. an asset's project) only when asked
        connection.exec_driver_sql("PRAGMA foreign_keys = ON")
    Base.metadata.create_all(engine)
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "_sessions", None)
    database.use_engine(engine)
    yield engine
    engine.dispose()


class MemoryFiles:
    """An in-memory stand-in for Supabase Storage (files.Backend): {object name: bytes}."""

    def __init__(self):
        self.objects: dict[str, bytes] = {}

    def put(self, path, data, content_type):
        self.objects[path] = data.read_bytes() if hasattr(data, "read_bytes") else bytes(data)

    def get(self, path):
        return self.objects.get(path)

    def stream(self, path):
        return None if path not in self.objects else iter([self.objects[path]])

    def names(self, folder):
        prefix = folder.rstrip("/") + "/"
        return [p[len(prefix):] for p in self.objects if p.startswith(prefix) and "/" not in p[len(prefix):]]

    def delete(self, paths):
        for p in paths:
            self.objects.pop(p, None)


@pytest.fixture(autouse=True)
def stored_files(monkeypatch) -> MemoryFiles:
    """An empty in-memory file store instead of Supabase Storage, so no test ever reads or writes real files."""
    memory = MemoryFiles()
    monkeypatch.setattr(files, "_backend", memory)
    return memory


@pytest.fixture(autouse=True)
def projects(test_database, monkeypatch):
    """The default project, owned by OWNER, in memory and in the test database."""
    default = Project(id=db.DEFAULT_PROJECT_ID, name="My library", description="", created_at=db.now(),
                      owner_id=OWNER.id)
    records.save_project(default)
    monkeypatch.setattr(db, "projects", {default.id: default})
    return db.projects


@pytest.fixture(autouse=True)
def keys(test_database, monkeypatch):
    """No API keys (in memory; the test database starts empty)."""
    monkeypatch.setattr(api_keys, "_keys", {})
    return api_keys._keys


@pytest.fixture
def offline(tmp_path, monkeypatch):
    """For tests that send requests to API routes: files and vectors in tmp_path (the usage log is in the empty test
    database), and no model
    can be called (no API key: model routes answer 503; a chat model call fails the test). So a request that gets
    past a check it should not pass can neither touch the real library nor cost money."""
    monkeypatch.setattr(storage, "UPLOAD_DIR", tmp_path / "upload_dir")
    monkeypatch.setattr(usage, "_totals", UsageTotals())
    monkeypatch.setattr(config, "API_KEY", None)  # chat model: llm.is_configured() is False → 503
    monkeypatch.setattr(vectorstore, "API_KEY", None)  # embeddings: vectorstore.is_configured() is False → 503

    def no_model(*args, **kwargs):
        raise AssertionError("a test request reached the language model")
    monkeypatch.setattr(llm, "chat_model", no_model)
    monkeypatch.setattr(kit, "chat_model", no_model)
