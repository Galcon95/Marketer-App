"""Shared test setup: a signed-in test user who owns the default project, without Supabase.

Every test gets a fresh project list (the default project, owned by OWNER) and a temporary projects.json, so the
real one is never written. Tests that build an app with API routers call sign_in(app) to be OWNER (or another user).
"""

import pytest
from fastapi import FastAPI

from app.core import auth, storage
from app.core import state as db
from app.core.auth import User
from app.core.schemas import Project

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
