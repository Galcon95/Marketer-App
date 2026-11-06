"""The database tables as SQLAlchemy models. A change here needs a new Alembic migration (server/migrations/):

    uv run alembic revision --autogenerate -m "what changed"   then check the generated file
    uv run alembic upgrade head

Schemas: "public" for the app's records; "private" for secrets-like data (API key hashes). Supabase's REST API
(PostgREST) serves only "public", so "private" cannot be read through it at all. Every table also has row-level
security turned on without any policy (in the migration), so Supabase's REST API returns no rows of it either: only
the server, which connects as the database owner (DATABASE_URL), reads and writes them.
"""

from datetime import datetime, timezone

from sqlalchemy import DateTime, MetaData, Text
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

PRIVATE = "private"  # schema of private.api_keys; tests map it to SQLite's only schema


class Base(DeclarativeBase):
    # Fixed constraint names, so migrations can name (and later drop) them the same way on every database.
    metadata = MetaData(naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "pk": "pk_%(table_name)s",
    })


class UtcDateTime(TypeDecorator):
    """A timestamp with time zone, always returned as an aware UTC datetime (also from SQLite in tests, which
    drops the time zone), so it compares with db.now()."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_result_value(self, value: datetime | None, dialect) -> datetime | None:
        if value is not None and value.tzinfo is None:
            value = value.replace(tzinfo=timezone.utc)
        return value


class ProjectRow(Base):
    """A project (client) and its owner; see schemas.Project. Its counts are computed, not stored."""

    __tablename__ = "projects"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # "prj_1a2b3c4d" or "demo-campaign"
    name: Mapped[str] = mapped_column(Text)
    description: Mapped[str] = mapped_column(Text, default="")
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    # Supabase user id of the owner; NULL = nobody yet (the default project before it is claimed). Unique: each
    # user owns one project, also if two first requests arrive at once.
    owner_id: Mapped[str | None] = mapped_column(Text, unique=True)


class ApiKeyRow(Base):
    """A personal API key for the MCP servers, as saved: only its hash, never the key; see schemas.ApiKey."""

    __tablename__ = "api_keys"
    __table_args__ = {"schema": PRIVATE}

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # "key_1a2b3c4d"
    user_id: Mapped[str] = mapped_column(Text, index=True)  # Supabase user id of the owner
    email: Mapped[str] = mapped_column(Text)
    name: Mapped[str] = mapped_column(Text)  # what it is for, e.g. "Claude Desktop"
    shown: Mapped[str] = mapped_column(Text)  # the key's first characters, e.g. "mk_AbC123x7"
    key_hash: Mapped[str] = mapped_column(Text, unique=True)  # SHA-256 of the key (hex)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    last_used_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
