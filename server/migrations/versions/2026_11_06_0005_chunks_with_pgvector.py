"""Chunks and their vectors move from .chunks.jsonl files and Chroma into the database (pgvector).

public.chunks    one row per chunk: text, location, the embedded text, the vector and its embedding key; deleted
                 with its book. Searched by LangChain's PGVectorStore (rag/vectorstore.py).

The pgvector extension goes into Supabase's "extensions" schema (on the search path), as Supabase recommends. The
vector column has no fixed length, so another embedding model needs no migration; there is no vector index (exact
search; pgvector's indexes take at most 2,000 dimensions, text-embedding-3-large has 3,072).

Row-level security on, no policy, like the other tables.

Revision ID: 0005
Revises: 0004
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from pgvector.sqlalchemy import VECTOR

revision: str = "0005"
down_revision: str | None = "0004"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS extensions")
    op.execute("CREATE EXTENSION IF NOT EXISTS vector WITH SCHEMA extensions")
    op.create_table(
        "chunks",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("position", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("chapter", sa.Text(), nullable=True),
        sa.Column("page", sa.Integer(), nullable=True),
        sa.Column("start_time", sa.Text(), nullable=True),
        sa.Column("end_time", sa.Text(), nullable=True),
        sa.Column("token_count", sa.Integer(), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("embedding", VECTOR(), nullable=False),
        sa.Column("embedding_key", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name="fk_chunks_source_id_sources", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_chunks"),
    )
    op.create_index("ix_chunks_source_id", "chunks", ["source_id"])
    op.create_index("ix_chunks_project_id", "chunks", ["project_id"])
    op.execute("ALTER TABLE public.chunks ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_chunks_project_id", table_name="chunks")
    op.drop_index("ix_chunks_source_id", table_name="chunks")
    op.drop_table("chunks")
    # The extension stays: other things in the database may use it.
