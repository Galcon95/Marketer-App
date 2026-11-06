"""Generated assets and "Ask your book" conversations move from JSON files into the database.

public.assets         was server/assets/generated/{project_id}/{asset_id}.json
public.conversations  was server/assets/conversations/{project_id}/{conversation_id}.json

Both belong to a project (deleted with it). Row-level security on, no policy, like the tables of 0001.

Revision ID: 0002
Revises: 0001
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.tables import UtcDateTime

revision: str = "0002"
down_revision: str | None = "0001"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def _project_id() -> sa.Column:
    return sa.Column("project_id", sa.Text(), nullable=False)


def _project_fk(table: str) -> sa.ForeignKeyConstraint:
    return sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name=f"fk_{table}_project_id_projects",
                                   ondelete="CASCADE")


def upgrade() -> None:
    op.create_table(
        "assets",
        sa.Column("id", sa.Text(), nullable=False),
        _project_id(),
        sa.Column("asset_type", sa.Text(), nullable=False),
        sa.Column("grounded", sa.Boolean(), nullable=False),
        sa.Column("brief", sa.Text(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("citations", postgresql.JSONB(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("tokens", sa.Integer(), nullable=False),
        sa.Column("tone", sa.Text(), nullable=False),
        sa.Column("length", sa.Text(), nullable=False),
        sa.Column("audience", sa.Text(), nullable=False),
        sa.Column("platform", sa.Text(), nullable=True),
        sa.Column("reply_to", sa.Text(), nullable=False),
        sa.Column("search_query", sa.Text(), nullable=False),
        sa.Column("humanize", sa.Integer(), nullable=False),
        sa.Column("source_ids", postgresql.JSONB(), nullable=False),
        sa.Column("ai_tells", postgresql.JSONB(), nullable=False),
        sa.Column("edited", sa.Boolean(), nullable=False),
        sa.Column("campaign_id", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=True),
        sa.Column("prompt_version", sa.Text(), nullable=True),
        sa.Column("persona", sa.Text(), nullable=False),
        sa.Column("angle", sa.Text(), nullable=False),
        _project_fk("assets"),
        sa.PrimaryKeyConstraint("id", name="pk_assets"),
    )
    op.create_index("ix_assets_project_id", "assets", ["project_id"])
    op.execute("ALTER TABLE public.assets ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "conversations",
        sa.Column("id", sa.Text(), nullable=False),
        _project_id(),
        sa.Column("title", sa.Text(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("updated_at", UtcDateTime(), nullable=False),
        sa.Column("turns", postgresql.JSONB(), nullable=False),
        _project_fk("conversations"),
        sa.PrimaryKeyConstraint("id", name="pk_conversations"),
    )
    op.create_index("ix_conversations_project_id", "conversations", ["project_id"])
    op.execute("ALTER TABLE public.conversations ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_conversations_project_id", table_name="conversations")
    op.drop_table("conversations")
    op.drop_index("ix_assets_project_id", table_name="assets")
    op.drop_table("assets")
