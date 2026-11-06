"""Tests of the database layer (app/db) on the in-memory test database of conftest.py: projects saved and loaded,
one project per owner, the one-time import of the old JSON files, and the connection settings."""

import json

import pytest

from app.core import config
from app.core import state as db
from app.core.schemas import Project
from app.db import database, import_files, records
from app.db.database import DatabaseError
from tests.conftest import OWNER, STRANGER


def _project(id: str, owner_id: str = "") -> Project:
    return Project(id=id, name=id, description="", created_at=db.now(), owner_id=owner_id)


def test_a_project_is_saved_and_loaded_with_its_owner():
    records.save_project(_project("prj_1", STRANGER.id))
    loaded = records.load_projects()["prj_1"]
    assert (loaded.owner_id, loaded.created_at.tzinfo is not None) == (STRANGER.id, True)


def test_a_project_without_owner_stays_without_owner_and_can_be_claimed():
    records.save_project(_project("prj_1"))
    assert records.load_projects()["prj_1"].owner_id == ""
    records.save_project(_project("prj_1", STRANGER.id))  # the same id: updated, not added
    assert records.load_projects()["prj_1"].owner_id == STRANGER.id


def test_counts_are_not_stored():
    records.save_project(_project("prj_1").model_copy(update={"source_count": 7}))
    assert records.load_projects()["prj_1"].source_count == 0


def test_nobody_owns_two_projects():
    """The unique owner_id: also two requests at once cannot give a user a second project."""
    with pytest.raises(DatabaseError):
        records.save_project(_project("prj_second", OWNER.id))  # OWNER already owns the default project (conftest)


def test_projects_without_owner_can_be_many():
    records.save_project(_project("prj_1"))
    records.save_project(_project("prj_2"))
    assert {"prj_1", "prj_2"} <= set(records.load_projects())


# ---------- One-time import of the JSON files ----------

def test_the_import_adds_new_records_once_and_keeps_existing_ones(tmp_path):
    projects_file, keys_file = tmp_path / "projects.json", tmp_path / "api_keys.json"
    projects_file.write_text(json.dumps([
        {"id": db.DEFAULT_PROJECT_ID, "name": "From the file", "description": "", "created_at": "2026-11-05T08:35:01Z",
         "owner_id": "someone-else"},  # already in the database: not overwritten
        {"id": "prj_4b1c3ebd", "name": "a@example.com", "description": "", "created_at": "2026-11-05T09:39:52Z",
         "owner_id": STRANGER.id},
    ]), encoding="utf-8")
    keys_file.write_text(json.dumps([
        {"id": "key_1", "user_id": OWNER.id, "email": OWNER.email, "name": "Claude Desktop", "shown": "mk_abcdefgh",
         "key_hash": "0" * 64, "created_at": "2026-11-05T12:36:13Z", "last_used_at": None},
    ]), encoding="utf-8")

    assert (import_files.import_projects(projects_file), import_files.import_api_keys(keys_file)) == (1, 1)
    assert (import_files.import_projects(projects_file), import_files.import_api_keys(keys_file)) == (0, 0)
    loaded = records.load_projects()
    assert loaded[db.DEFAULT_PROJECT_ID].owner_id == OWNER.id
    assert loaded["prj_4b1c3ebd"].owner_id == STRANGER.id
    assert [k.id for k in records.load_api_keys()] == ["key_1"]


def test_the_import_without_files_imports_nothing(tmp_path):
    assert import_files.import_projects(tmp_path / "missing.json") == 0
    assert import_files.import_api_keys(tmp_path / "missing.json") == 0


# ---------- Connection settings ----------

@pytest.mark.parametrize("url, expected", [
    ("postgresql://u:p@host:5432/postgres", "postgresql+psycopg://u:p@host:5432/postgres"),
    ("postgres://u:p@host:5432/postgres", "postgresql+psycopg://u:p@host:5432/postgres"),
    ("postgresql+psycopg://u:p@host/db", "postgresql+psycopg://u:p@host/db"),
    ("sqlite://", "sqlite://"),
])
def test_the_supabase_connection_string_gets_the_psycopg_driver(url, expected):
    assert config._sqlalchemy_url(url) == expected


def test_without_database_url_nothing_can_be_read(monkeypatch):
    monkeypatch.setattr(database, "_engine", None)
    monkeypatch.setattr(database, "DATABASE_URL", "")
    with pytest.raises(DatabaseError, match="DATABASE_URL"):
        records.load_projects()
