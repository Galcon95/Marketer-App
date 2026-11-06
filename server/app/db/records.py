"""Reading and writing the app's records in the database: Pydantic models (schemas.py) in, Pydantic models out, so
the rest of the app does not see SQLAlchemy.

Every function raises database.DatabaseError if the database cannot be reached or a statement fails.
"""

from datetime import datetime

from sqlalchemy import delete, select, update

from app.core.schemas import ApiKey, Project
from app.db.database import session
from app.db.tables import ApiKeyRow, ProjectRow

_PROJECT_COUNTS = {"source_count", "chunk_count", "asset_count", "token_count"}  # computed on read, not stored


# ---------- Projects ----------
def _project(row: ProjectRow) -> Project:
    return Project(id=row.id, name=row.name, description=row.description, created_at=row.created_at,
                   owner_id=row.owner_id or "")


def load_projects() -> dict[str, Project]:
    """All projects by id (called once on server startup); empty if none were saved yet."""
    with session() as s:
        return {row.id: _project(row) for row in s.scalars(select(ProjectRow))}


def save_project(project: Project) -> None:
    """Insert the project, or update it if one with its id exists (e.g. the default project when it is claimed)."""
    data = project.model_dump(exclude=_PROJECT_COUNTS)
    data["owner_id"] = data["owner_id"] or None
    with session() as s:
        s.merge(ProjectRow(**data))


# ---------- API keys ----------
def _api_key(row: ApiKeyRow) -> ApiKey:
    return ApiKey(id=row.id, user_id=row.user_id, email=row.email, name=row.name, shown=row.shown,
                  key_hash=row.key_hash, created_at=row.created_at, last_used_at=row.last_used_at)


def load_api_keys() -> list[ApiKey]:
    """All saved API keys (hashes only), oldest first."""
    with session() as s:
        return [_api_key(row) for row in s.scalars(select(ApiKeyRow).order_by(ApiKeyRow.created_at))]


def add_api_key(key: ApiKey) -> None:
    """Save a new key record (its hash, never the key)."""
    with session() as s:
        s.add(ApiKeyRow(**key.model_dump()))


def delete_api_key(key_id: str) -> None:
    """Delete a key record; nothing happens if there is none with this id."""
    with session() as s:
        s.execute(delete(ApiKeyRow).where(ApiKeyRow.id == key_id))


def set_api_key_last_used(key_id: str, when: datetime) -> None:
    """Note when a key was last used."""
    with session() as s:
        s.execute(update(ApiKeyRow).where(ApiKeyRow.id == key_id).values(last_used_at=when))
