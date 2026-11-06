"""The database tables as SQLAlchemy models. A change here needs a new Alembic migration (server/migrations/):

    uv run alembic revision --autogenerate -m "what changed"   then check the generated file
    uv run alembic upgrade head

Schemas: "public" for the app's records; "private" for secrets-like data (API key hashes). Supabase's REST API
(PostgREST) serves only "public", so "private" cannot be read through it at all. Every table also has row-level
security turned on without any policy (in the migration), so Supabase's REST API returns no rows of it either: only
the server, which connects as the database owner (DATABASE_URL), reads and writes them.
"""

from datetime import datetime, timezone

from typing import Any

from sqlalchemy import (JSON, BigInteger, Boolean, DateTime, Double, ForeignKey, Identity, Index, Integer,
                        MetaData, Text, text)
from pgvector.sqlalchemy import VECTOR
from sqlalchemy.dialects.postgresql import JSONB
from sqlalchemy.orm import DeclarativeBase, Mapped, mapped_column
from sqlalchemy.types import TypeDecorator

PRIVATE = "private"  # schema of private.api_keys; tests map it to SQLite's only schema


class Base(DeclarativeBase):
    # Fixed constraint names, so migrations can name (and later drop) them the same way on every database.
    metadata = MetaData(naming_convention={
        "ix": "ix_%(table_name)s_%(column_0_name)s",
        "uq": "uq_%(table_name)s_%(column_0_name)s",
        "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s",
        "pk": "pk_%(table_name)s",
    })


# Nested data (citations, chat turns, lists of ids) as JSON: JSONB in PostgreSQL, plain JSON in SQLite (tests).
Json = JSON().with_variant(JSONB(), "postgresql")


# An embedding: pgvector's vector type in PostgreSQL (without a fixed length, so another embedding model needs no
# migration; the price is no approximate index, which this size does not need), a JSON list in SQLite (tests).
Vector = VECTOR().with_variant(JSON(), "sqlite")


def project_fk() -> Any:
    """The project a record belongs to; deleting the project deletes its records too."""
    return mapped_column(Text, ForeignKey("projects.id", ondelete="CASCADE"), index=True)


class UtcDateTime(TypeDecorator):
    """A timestamp with time zone, always returned as an aware UTC datetime (also from SQLite in tests, which
    drops the time zone), so it compares with db.now()."""

    impl = DateTime(timezone=True)
    cache_ok = True

    def process_bind_param(self, value: datetime | None, dialect) -> datetime | None:
        # Always stored in UTC: SQLite keeps no time zone, so its times only compare correctly if they are all UTC.
        if value is not None and value.tzinfo is not None:
            value = value.astimezone(timezone.utc)
        return value

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


class AssetRow(Base):
    """A generated marketing asset; one column per field of schemas.Asset (a test checks they match)."""

    __tablename__ = "assets"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # "ast_1a2b3c4d"
    project_id: Mapped[str] = project_fk()
    asset_type: Mapped[str] = mapped_column(Text)
    grounded: Mapped[bool] = mapped_column(Boolean)
    brief: Mapped[str] = mapped_column(Text)
    text: Mapped[str] = mapped_column(Text)
    citations: Mapped[list] = mapped_column(Json)  # list of schemas.Citation
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    tokens: Mapped[int] = mapped_column(Integer)
    tone: Mapped[str] = mapped_column(Text)
    length: Mapped[str] = mapped_column(Text)
    audience: Mapped[str] = mapped_column(Text)
    platform: Mapped[str | None] = mapped_column(Text)
    reply_to: Mapped[str] = mapped_column(Text)
    search_query: Mapped[str] = mapped_column(Text)
    humanize: Mapped[int] = mapped_column(Integer)
    source_ids: Mapped[list] = mapped_column(Json)  # list of source ids; empty = all books
    ai_tells: Mapped[list] = mapped_column(Json)  # list of phrases
    edited: Mapped[bool] = mapped_column(Boolean)
    campaign_id: Mapped[str] = mapped_column(Text)  # "" = not part of a campaign kit
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    persona: Mapped[str] = mapped_column(Text)
    angle: Mapped[str] = mapped_column(Text)


class ConversationRow(Base):
    """An "Ask your book" chat; see schemas.Conversation. The turns (question, answer, citations, passages) are one
    JSON list: they are always read and written together with their chat."""

    __tablename__ = "conversations"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # "cnv_1a2b3c4d"
    project_id: Mapped[str] = project_fk()
    title: Mapped[str] = mapped_column(Text)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)
    turns: Mapped[list] = mapped_column(Json)  # list of schemas.ChatTurn, oldest first


class UsageRow(Base):
    """One model call (chat or embedding) with its tokens and costs in USD; see schemas.UsageRecord and usage.py.
    The budgets (limits.toml) are sums over these rows. No foreign keys: the costs stay when a project is deleted."""

    __tablename__ = "usage_log"

    # A running number (records have no id of their own): BIGINT GENERATED BY DEFAULT AS IDENTITY in PostgreSQL,
    # INTEGER PRIMARY KEY (autoincrement) in SQLite.
    id: Mapped[int] = mapped_column(BigInteger().with_variant(Integer, "sqlite"), Identity(), primary_key=True)
    timestamp: Mapped[datetime] = mapped_column(UtcDateTime, index=True)  # when the call finished
    operation: Mapped[str] = mapped_column(Text)  # e.g. "generate_blurb/generate", "ask/embed_query"
    kind: Mapped[str] = mapped_column(Text)  # "chat" or "embedding"
    model: Mapped[str] = mapped_column(Text)
    input_tokens: Mapped[int] = mapped_column(Integer)
    output_tokens: Mapped[int] = mapped_column(Integer)
    input_cost: Mapped[float] = mapped_column(Double)  # USD
    output_cost: Mapped[float] = mapped_column(Double)  # USD
    cost: Mapped[float] = mapped_column(Double)  # USD, the whole call
    cost_source: Mapped[str] = mapped_column(Text)  # "provider" (exact, OpenRouter) or "estimate" (price list)
    project_id: Mapped[str | None] = mapped_column(Text)
    source_id: Mapped[str | None] = mapped_column(Text)
    request_id: Mapped[str | None] = mapped_column(Text)  # the HTTP request that caused it
    user_id: Mapped[str | None] = mapped_column(Text, index=True)  # who caused it; None for calls before sign-in


class SourceRow(Base):
    """An uploaded book (or other file) and its processing state; see schemas.Source. The file itself, its chunks and
    its cover are still on disk (server/assets/uploads/{project_id}/{id}/)."""

    __tablename__ = "sources"
    __table_args__ = (
        # The same file only once per project (the upload checks it first; this also holds for two uploads at once).
        # Books uploaded before checksums were recorded have sha256 "" and are not compared.
        Index("uq_sources_project_id_sha256", "project_id", "sha256", unique=True,
              postgresql_where=text("sha256 <> ''"), sqlite_where=text("sha256 <> ''")),
    )

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # "src_1a2b3c4d"
    project_id: Mapped[str] = project_fk()
    filename: Mapped[str] = mapped_column(Text)
    kind: Mapped[str] = mapped_column(Text)  # "document", "video", "audio", "text"
    size_bytes: Mapped[int] = mapped_column(BigInteger)
    # "uploaded", "queued", ..., "ready", "failed". Saved on every change of status; the progress percentage only
    # with it (during processing it lives in memory: polled by the GUI, lost on a restart anyway).
    status: Mapped[str] = mapped_column(Text)
    progress: Mapped[int] = mapped_column(Integer)
    chunk_count: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    error: Mapped[str | None] = mapped_column(Text)
    author: Mapped[str] = mapped_column(Text)
    sha256: Mapped[str] = mapped_column(Text)  # checksum of the file; "" = not recorded (older uploads)


class SummaryRow(Base):
    """The summary of one book (map-reduce over its chapters); see schemas.BookSummary. Deleted with its book."""

    __tablename__ = "summaries"

    source_id: Mapped[str] = mapped_column(Text, ForeignKey("sources.id", ondelete="CASCADE"), primary_key=True)
    summary: Mapped[str] = mapped_column(Text)
    themes: Mapped[list] = mapped_column(Json)  # list of short phrases
    chapters: Mapped[list] = mapped_column(Json)  # list of schemas.ChapterSummary, in reading order
    model: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)


class ChunkRow(Base):
    """A chunk of a book with its embedding; see schemas.Chunk and rag/vectorstore.py. Searched by LangChain's
    PGVectorStore (content, embedding, metadata columns source_id, project_id, chapter, page, embedding_key).
    Deleted with its book."""

    __tablename__ = "chunks"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # "chk_<source>_<n>"
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    project_id: Mapped[str] = mapped_column(Text, index=True)  # the book's project, for the search filter
    position: Mapped[int] = mapped_column(Integer)  # order within the book (1, 2, ...)
    text: Mapped[str] = mapped_column(Text)  # the chunk as the prompt shows it
    chapter: Mapped[str | None] = mapped_column(Text)
    page: Mapped[int | None] = mapped_column(Integer)
    start_time: Mapped[str | None] = mapped_column(Text)  # media only
    end_time: Mapped[str | None] = mapped_column(Text)
    token_count: Mapped[int] = mapped_column(Integer)
    content: Mapped[str] = mapped_column(Text)  # what was embedded: "book · chapter" header + text
    embedding: Mapped[list] = mapped_column(Vector)
    # Embedding model and INDEX_FORMAT ("text-embedding-3-large--v2"): only vectors with the current key are searched,
    # because vectors of different models or differently built texts cannot be compared.
    embedding_key: Mapped[str] = mapped_column(Text)
