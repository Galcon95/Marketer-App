"""Shared test setup: a signed-in test user who owns the default project, without Supabase.

Every test gets a fresh project list (the default project, owned by OWNER) and a temporary projects.json, and no
API keys with a temporary api_keys.json, so the real files are never written. Tests that build an app with API routers call sign_in(app) to be OWNER (or another user).
"""

import pytest
from fastapi import FastAPI

from app.campaign import kit
from app.core import api_keys, auth, config, llm, storage, usage
from app.core import state as db
from app.core.auth import User
from app.core.schemas import Project, UsageTotals
from app.rag import vectorstore

OWNER = User(id="user-owner", email="owner@example.com")  # owns the default project
STRANGER = User(id="user-stranger", email="stranger@example.com")  # another signed-in user


def sign_in(app: FastAPI, user: User = OWNER) -> None:
    """Make every request to this app come from `user` (instead of checking a Supabase access token)."""
    app.dependency_overrides[auth.current_user] = lambda: user


@pytest.fixture(autouse=True)
def projects(tmp_path, monkeypatch):
    """The default project, owned by OWNER; projects.json goes to a temporary folder."""
    monkeypatch.setattr(storage, "PROJECTS_FILE", tmp_path / "projects.json")
    default = Project(id=db.DEFAULT_PROJECT_ID, name="My library", description="", created_at=db.now(),
                      owner_id=OWNER.id)
    monkeypatch.setattr(db, "projects", {default.id: default})
    return db.projects


@pytest.fixture(autouse=True)
def keys(tmp_path, monkeypatch):
    """No API keys; api_keys.json goes to a temporary folder, so the real one is never read or written."""
    monkeypatch.setattr(api_keys, "KEYS_FILE", tmp_path / "api_keys.json")
    monkeypatch.setattr(api_keys, "_keys", {})
    return api_keys._keys


@pytest.fixture
def offline(tmp_path, monkeypatch):
    """For tests that send requests to API routes: files, vectors and an empty usage log in tmp_path, and no model
    can be called (no API key: model routes answer 503; a chat model call fails the test). So a request that gets
    past a check it should not pass can neither touch the real library nor cost money."""
    for name in ("UPLOAD_DIR", "GENERATED_DIR", "CONVERSATIONS_DIR"):
        monkeypatch.setattr(storage, name, tmp_path / name.lower())
    monkeypatch.setattr(vectorstore, "CHROMA_DIR", tmp_path / "chroma")
    monkeypatch.setattr(usage, "USAGE_FILE", tmp_path / "usage.jsonl")
    monkeypatch.setattr(usage, "_records", [])
    monkeypatch.setattr(usage, "_totals", UsageTotals())
    monkeypatch.setattr(config, "API_KEY", None)  # chat model: llm.is_configured() is False → 503
    monkeypatch.setattr(vectorstore, "API_KEY", None)  # embeddings: vectorstore.is_configured() is False → 503

    def no_model(*args, **kwargs):
        raise AssertionError("a test request reached the language model")
    monkeypatch.setattr(llm, "chat_model", no_model)
    monkeypatch.setattr(kit, "chat_model", no_model)
