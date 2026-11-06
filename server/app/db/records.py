"""Reading and writing the app's records in the database: Pydantic models (schemas.py) in, Pydantic models out, so
the rest of the app does not see SQLAlchemy.

Every function raises database.DatabaseError if the database cannot be reached or a statement fails.
"""

from collections.abc import Iterable
from datetime import datetime
from typing import TypeVar

from pydantic import BaseModel
from sqlalchemy import and_, case, delete, func, or_, select, update
from sqlalchemy import inspect as sa_inspect

from app.core.schemas import ApiKey, Asset, Conversation, Project, UsageRecord, UsageTotals
from app.db.database import session
from app.db.tables import ApiKeyRow, AssetRow, Base, ConversationRow, ProjectRow, UsageRow

# Fields saved in a JSON column (nested models, lists): written in JSON mode, so datetimes inside become strings.
ASSET_JSON_FIELDS = {"citations", "source_ids", "ai_tells"}
CONVERSATION_JSON_FIELDS = {"turns"}


def to_row(row_class: type[Base], record: BaseModel, json_fields: set[str]) -> Base:
    """The table row of a record: plain fields as they are, json_fields in JSON mode (datetimes become strings)."""
    data = record.model_dump(exclude=json_fields)
    data.update(record.model_dump(mode="json", include=json_fields))
    return row_class(**data)


M = TypeVar("M", bound=BaseModel)


def _record(model: type[M], row: Base) -> M:
    return model.model_validate({c.key: getattr(row, c.key) for c in sa_inspect(row).mapper.column_attrs})

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


# ---------- Generated assets ----------
def load_assets() -> dict[str, Asset]:
    """All generated assets by id, oldest first (called once on server startup)."""
    with session() as s:
        return {row.id: _record(Asset, row) for row in s.scalars(select(AssetRow).order_by(AssetRow.created_at))}


def save_assets(assets: Iterable[Asset]) -> None:
    """Insert or update these assets in one transaction: all are saved, or none (e.g. a whole campaign kit)."""
    with session() as s:
        for asset in assets:
            s.merge(to_row(AssetRow, asset, ASSET_JSON_FIELDS))


def delete_assets(asset_ids: Iterable[str]) -> None:
    """Delete these assets; unknown ids are ignored."""
    ids = list(asset_ids)
    if ids:
        with session() as s:
            s.execute(delete(AssetRow).where(AssetRow.id.in_(ids)))


# ---------- "Ask your book" conversations ----------
def load_conversations() -> dict[str, Conversation]:
    """All conversations by id, oldest first (called once on server startup)."""
    with session() as s:
        rows = s.scalars(select(ConversationRow).order_by(ConversationRow.created_at))
        return {row.id: _record(Conversation, row) for row in rows}


def save_conversation(conversation: Conversation) -> None:
    """Insert the conversation, or replace the saved one (with all its turns)."""
    with session() as s:
        s.merge(to_row(ConversationRow, conversation, CONVERSATION_JSON_FIELDS))


def delete_conversations(conversation_ids: Iterable[str]) -> None:
    """Delete these conversations; unknown ids are ignored."""
    ids = list(conversation_ids)
    if ids:
        with session() as s:
            s.execute(delete(ConversationRow).where(ConversationRow.id.in_(ids)))


# ---------- Usage log (model calls and their costs) ----------
def add_usage(rec: UsageRecord) -> None:
    """Save one model call."""
    with session() as s:
        s.add(UsageRow(**rec.model_dump()))


def _of_user(user_id: str, project_ids: Iterable[str]):
    """The calls a user caused: their user id is on it, or it is from before sign-in existed (no user id) and belongs
    to one of their projects."""
    return or_(UsageRow.user_id == user_id,
               and_(UsageRow.user_id.is_(None), UsageRow.project_id.in_(list(project_ids))))


def _where(user_id: str | None, project_ids: Iterable[str]) -> list:
    return [] if user_id is None else [_of_user(user_id, project_ids)]


_SUMS = (func.count(), func.coalesce(func.sum(UsageRow.input_tokens), 0),
         func.coalesce(func.sum(UsageRow.output_tokens), 0), func.coalesce(func.sum(UsageRow.input_cost), 0.0),
         func.coalesce(func.sum(UsageRow.output_cost), 0.0), func.coalesce(func.sum(UsageRow.cost), 0.0))


def _totals(row) -> UsageTotals:
    calls, input_tokens, output_tokens, input_cost, output_cost, cost = row
    return UsageTotals(calls=calls, input_tokens=input_tokens, output_tokens=output_tokens,
                       input_cost=input_cost, output_cost=output_cost, cost=cost)


def usage_totals(user_id: str | None = None, project_ids: Iterable[str] = ()) -> UsageTotals:
    """Sums over all calls, or with `user_id` over that user's calls."""
    with session() as s:
        return _totals(s.execute(select(*_SUMS).where(*_where(user_id, project_ids))).one())


def usage_by_operation(user_id: str | None = None, project_ids: Iterable[str] = ()) -> dict[str, UsageTotals]:
    """Sums per operation (highest cost first), of all calls or of the user's."""
    query = (select(UsageRow.operation, *_SUMS).where(*_where(user_id, project_ids))
             .group_by(UsageRow.operation).order_by(func.sum(UsageRow.cost).desc()))
    with session() as s:
        return {row[0]: _totals(row[1:]) for row in s.execute(query)}


def recent_usage(limit: int, user_id: str | None = None, project_ids: Iterable[str] = ()) -> list[UsageRecord]:
    """The latest `limit` calls, newest first, of all calls or of the user's."""
    query = (select(UsageRow).where(*_where(user_id, project_ids))
             .order_by(UsageRow.timestamp.desc(), UsageRow.id.desc()).limit(limit))
    with session() as s:
        return [UsageRecord.model_validate({k: getattr(row, k) for k in UsageRecord.model_fields})
                for row in s.scalars(query)]


def spending(user_id: str, project_ids: Iterable[str], today: datetime, month: datetime) -> tuple[float, float, float]:
    """In one query: what the user spent since `today` and since `month`, and what all users spent since `today`
    (USD). The budget check runs before every model request, so this is one round trip, not three."""
    mine, since_today = _of_user(user_id, project_ids), UsageRow.timestamp >= today

    def total(condition) -> object:
        return func.coalesce(func.sum(case((condition, UsageRow.cost), else_=0.0)), 0.0)

    # Only this month's rows are read (the timestamp index); today lies within them.
    query = (select(total(and_(mine, since_today)), total(mine), total(since_today))
             .where(UsageRow.timestamp >= min(month, today)))
    with session() as s:
        user_today, user_month, app_today = s.execute(query).one()
    return float(user_today), float(user_month), float(app_today)
