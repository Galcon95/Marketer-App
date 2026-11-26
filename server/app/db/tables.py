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
    substack: Mapped[str] = mapped_column(Text, server_default=text("''"), default="")  # own Substack publication


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


class FacebookConnectionRow(Base):
    """A user's own Facebook Page, connected with Facebook Login: its Page token only encrypted (secret_box.py);
    see schemas.FacebookConnection. One Page per user."""

    __tablename__ = "facebook_connections"
    __table_args__ = {"schema": PRIVATE}

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)  # Supabase user id
    page_id: Mapped[str] = mapped_column(Text)
    page_name: Mapped[str] = mapped_column(Text)
    token: Mapped[str] = mapped_column(Text)  # the Page access token, encrypted (Fernet)
    connected_at: Mapped[datetime] = mapped_column(UtcDateTime)


class YouTubeConnectionRow(Base):
    """A user's own YouTube channel, connected with Google sign-in: its refresh token only encrypted (secret_box.py);
    see schemas.YouTubeConnection. One channel per user."""

    __tablename__ = "youtube_connections"
    __table_args__ = {"schema": PRIVATE}

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)  # Supabase user id
    channel_id: Mapped[str] = mapped_column(Text)
    channel_name: Mapped[str] = mapped_column(Text)
    token: Mapped[str] = mapped_column(Text)  # Google's refresh token, encrypted (Fernet)
    connected_at: Mapped[datetime] = mapped_column(UtcDateTime)


class AppSwitchRow(Base):
    """A switch of the whole app that must survive a restart (core/alarm.py): "demo" (the guest demo is on) and
    "freeze" (model calls stopped for everyone but the admin). A missing row is the switch's default."""

    __tablename__ = "app_switches"
    __table_args__ = {"schema": PRIVATE}

    name: Mapped[str] = mapped_column(Text, primary_key=True)
    on: Mapped[bool] = mapped_column(Boolean)
    reason: Mapped[str] = mapped_column(Text, server_default=text("''"))  # why it was last changed
    changed_at: Mapped[datetime] = mapped_column(UtcDateTime)


class AutomationSettingsRow(Base):
    """A user's schedule for the marketing agent; see schemas.AutomationSettings. One row per user."""

    __tablename__ = "automation_settings"
    __table_args__ = {"schema": PRIVATE}

    user_id: Mapped[str] = mapped_column(Text, primary_key=True)  # Supabase user id
    mode: Mapped[str] = mapped_column(Text)
    every_minutes: Mapped[int] = mapped_column(Integer)
    times: Mapped[list] = mapped_column(Json)  # ["09:00", "18:00"]
    days: Mapped[list] = mapped_column(Json)  # [0, ..., 6], 0 = Monday
    timezone: Mapped[str] = mapped_column(Text)
    saved_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    last_run_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    paused: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    resumed_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    quiet_from: Mapped[str] = mapped_column(Text, server_default=text("''"))
    quiet_to: Mapped[str] = mapped_column(Text, server_default=text("''"))
    engage: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    engage_days: Mapped[int] = mapped_column(Integer, server_default=text("14"))
    daily_limit: Mapped[int] = mapped_column(Integer, server_default=text("2"))
    book_post: Mapped[bool] = mapped_column(Boolean, server_default=text("true"))
    book_post_picture: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    books: Mapped[list] = mapped_column(Json, server_default=text("'[]'"))
    book_links: Mapped[dict] = mapped_column(Json, server_default=text("'{}'"))
    test_mode: Mapped[bool] = mapped_column(Boolean, server_default=text("false"))
    humanize: Mapped[int] = mapped_column(Integer, server_default=text("80"))
    youtube_engage_days: Mapped[int] = mapped_column(Integer, server_default=text("90"))
    youtube_daily_limit: Mapped[int] = mapped_column(Integer, server_default=text("2"))


class AutomationCycleRow(Base):
    """One cycle of the marketing agent; see schemas.AutomationCycle."""

    __tablename__ = "automation_cycles"
    __table_args__ = (Index("ix_automation_cycles_user_started", "user_id", "started_at"), {"schema": PRIVATE})

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # "cyc_1a2b3c4d"
    user_id: Mapped[str] = mapped_column(Text)
    trigger: Mapped[str] = mapped_column(Text)
    status: Mapped[str] = mapped_column(Text)
    started_at: Mapped[datetime] = mapped_column(UtcDateTime)
    ended_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)
    entries: Mapped[list] = mapped_column(Json)  # list of schemas.CycleEntry
    note: Mapped[str] = mapped_column(Text)


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
    published_id: Mapped[str] = mapped_column(Text, default="")  # Facebook post id; "" = not published
    published_url: Mapped[str] = mapped_column(Text, default="")
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    cost: Mapped[float | None] = mapped_column(Double)  # USD of the model calls that wrote it; None = not recorded


class AdImageRow(Base):
    """A generated ad picture of an asset; one column per field of schemas.AdImage (a test checks they match). The
    picture is in Storage (core/ad_images.py). Deleted with its asset or project; keeps no book after the book's
    deletion."""

    __tablename__ = "ad_images"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # "img_1a2b3c4d"
    project_id: Mapped[str] = project_fk()
    asset_id: Mapped[str] = mapped_column(Text, ForeignKey("assets.id", ondelete="CASCADE"), index=True)
    source_id: Mapped[str | None] = mapped_column(Text, ForeignKey("sources.id", ondelete="SET NULL"))
    format: Mapped[str] = mapped_column(Text)
    headline: Mapped[str] = mapped_column(Text)
    scene: Mapped[str] = mapped_column(Text)
    model: Mapped[str] = mapped_column(Text)
    prompt_version: Mapped[str] = mapped_column(Text)
    cost: Mapped[float | None] = mapped_column(Double)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    published_id: Mapped[str | None] = mapped_column(Text)
    published_url: Mapped[str | None] = mapped_column(Text)
    published_at: Mapped[datetime | None] = mapped_column(UtcDateTime, nullable=True)


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


class DiscussionRow(Base):
    """A Discussion Relevance Agent result: one discussion analysed for one book; one column per field of
    schemas.DiscussionAnalysis (a test checks they match). Deleted with its project or its book (its citations point
    into the book)."""

    __tablename__ = "discussion_analyses"

    id: Mapped[str] = mapped_column(Text, primary_key=True)  # "dsc_1a2b3c4d"
    project_id: Mapped[str] = project_fk()
    source_id: Mapped[str] = mapped_column(Text, ForeignKey("sources.id", ondelete="CASCADE"), index=True)
    discussion: Mapped[str] = mapped_column(Text)
    url: Mapped[str] = mapped_column(Text)
    platform: Mapped[str] = mapped_column(Text)
    angle: Mapped[str] = mapped_column(Text)
    recommendation: Mapped[str] = mapped_column(Text)  # "contribute", "more_context" or "skip"
    reason: Mapped[str] = mapped_column(Text)
    missing_context: Mapped[str] = mapped_column(Text)
    suggested_reply: Mapped[str] = mapped_column(Text)
    reply: Mapped[str] = mapped_column(Text)
    edited: Mapped[bool] = mapped_column(Boolean)
    book_mention: Mapped[dict | None] = mapped_column(Json)  # schemas.BookMention; NULL when no reply was drafted
    citations: Mapped[list] = mapped_column(Json)  # list of schemas.Citation
    search_queries: Mapped[list] = mapped_column(Json)  # list of strings
    tool_calls: Mapped[list] = mapped_column(Json)  # list of schemas.ToolCallRecord
    platform_issues: Mapped[list] = mapped_column(Json)  # list of strings
    injection_risk: Mapped[str] = mapped_column(Text, server_default="none")  # since migration 0013
    injection_findings: Mapped[list] = mapped_column(Json, server_default="[]")  # list of strings
    output_issues: Mapped[list] = mapped_column(Json, server_default="[]")  # list of strings
    humanize: Mapped[int] = mapped_column(Integer, server_default="70")  # 0-100 (since migration 0009)
    tone: Mapped[str] = mapped_column(Text, server_default="neutral")  # schemas.Tone (since migration 0010)
    facebook_comment_id: Mapped[str] = mapped_column(Text, server_default="")  # since migration 0012
    youtube_comment_id: Mapped[str] = mapped_column(Text, server_default="")  # since migration 0017
    replied_id: Mapped[str] = mapped_column(Text, server_default="")
    replied_url: Mapped[str] = mapped_column(Text, server_default="")
    replied_at: Mapped[datetime | None] = mapped_column(UtcDateTime)
    model: Mapped[str | None] = mapped_column(Text)
    prompt_version: Mapped[str | None] = mapped_column(Text)
    tokens: Mapped[int] = mapped_column(Integer)
    created_at: Mapped[datetime] = mapped_column(UtcDateTime)
    updated_at: Mapped[datetime] = mapped_column(UtcDateTime)


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
    asset_id: Mapped[str | None] = mapped_column(Text, index=True)  # the single asset it generated
    asset_type: Mapped[str | None] = mapped_column(Text)  # that asset's type
    campaign_id: Mapped[str | None] = mapped_column(Text, index=True)  # the campaign kit it was part of


class SourceRow(Base):
    """An uploaded book (or other file) and its processing state; see schemas.Source. Its chunks are in the table
    chunks; the file itself and its cover are in Supabase Storage (bucket "books", core/files.py)."""

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
