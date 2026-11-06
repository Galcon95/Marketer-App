"""The book records and their summaries move from .source.json and .summary.json files into the database.

public.sources     was server/assets/uploads/{project_id}/{source_id}/.source.json (the PDF, chunks and cover stay
                   in that folder for now); the same file only once per project (partial unique index on sha256)
public.summaries   was .summary.json next to the book; deleted with its book

Row-level security on, no policy, like the other tables.

Revision ID: 0004
Revises: 0003
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.tables import UtcDateTime

revision: str = "0004"
down_revision: str | None = "0003"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "sources",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("filename", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("size_bytes", sa.BigInteger(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("progress", sa.Integer(), nullable=False),
        sa.Column("chunk_count", sa.Integer(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("author", sa.Text(), nullable=False),
        sa.Column("sha256", sa.Text(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_sources_project_id_projects",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_sources"),
    )
    op.create_index("ix_sources_project_id", "sources", ["project_id"])
    op.create_index("uq_sources_project_id_sha256", "sources", ["project_id", "sha256"], unique=True,
                    postgresql_where=sa.text("sha256 <> ''"))
    op.execute("ALTER TABLE public.sources ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "summaries",
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("summary", sa.Text(), nullable=False),
        sa.Column("themes", postgresql.JSONB(), nullable=False),
        sa.Column("chapters", postgresql.JSONB(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name="fk_summaries_source_id_sources",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("source_id", name="pk_summaries"),
    )
    op.execute("ALTER TABLE public.summaries ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_table("summaries")
    op.drop_index("uq_sources_project_id_sha256", table_name="sources")
    op.drop_index("ix_sources_project_id", table_name="sources")
    op.drop_table("sources")
