"""Results of the Discussion Relevance Agent (Market Intelligence).

public.discussion_analyses  one discussion analysed for one book: recommendation, reason, reply, citations, trace

Belongs to a project and to a book (deleted with either). Row-level security on, no policy, and no privileges for
Supabase's API roles, like every table (0007).

Revision ID: 0008
Revises: 0007
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.tables import UtcDateTime

revision: str = "0008"
down_revision: str | None = "0007"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "discussion_analyses",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=False),
        sa.Column("discussion", sa.Text(), nullable=False),
        sa.Column("url", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False),
        sa.Column("recommendation", sa.Text(), nullable=False),
        sa.Column("reason", sa.Text(), nullable=False),
        sa.Column("missing_context", sa.Text(), nullable=False),
        sa.Column("suggested_reply", sa.Text(), nullable=False),
        sa.Column("reply", sa.Text(), nullable=False),
        sa.Column("edited", sa.Boolean(), nullable=False),
        sa.Column("book_mention", postgresql.JSONB(), nullable=True),
        sa.Column("citations", postgresql.JSONB(), nullable=False),
        sa.Column("search_queries", postgresql.JSONB(), nullable=False),
        sa.Column("tool_calls", postgresql.JSONB(), nullable=False),
        sa.Column("platform_issues", postgresql.JSONB(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_discussion_analyses_project_id_projects",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name="fk_discussion_analyses_source_id_sources",
                                ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_discussion_analyses"),
    )
    op.create_index("ix_discussion_analyses_project_id", "discussion_analyses", ["project_id"])
    op.create_index("ix_discussion_analyses_source_id", "discussion_analyses", ["source_id"])
    op.execute("ALTER TABLE public.discussion_analyses ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON public.discussion_analyses FROM anon, authenticated;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_index("ix_discussion_analyses_source_id", table_name="discussion_analyses")
    op.drop_index("ix_discussion_analyses_project_id", table_name="discussion_analyses")
    op.drop_table("discussion_analyses")
