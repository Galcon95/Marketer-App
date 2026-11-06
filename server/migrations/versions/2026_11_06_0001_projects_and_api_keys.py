"""Projects and API keys: the first records that move from JSON files into the database.

public.projects     the clients and their owners (was server/assets/projects.json)
private.api_keys    hashes of the personal MCP API keys (was server/assets/api_keys.json)

Row-level security is on for both, with no policy: Supabase's REST API (anon and authenticated roles) sees no rows.
The server connects as the database owner, which RLS does not restrict. The private schema is also closed to those
roles, so its tables are not even visible to them.

Revision ID: 0001
Revises:
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.tables import UtcDateTime

revision: str = "0001"
down_revision: str | None = None
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.execute("CREATE SCHEMA IF NOT EXISTS private")
    op.execute("REVOKE ALL ON SCHEMA private FROM PUBLIC")
    # Supabase's API roles; on a plain PostgreSQL (no such roles) there is nothing to revoke.
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON SCHEMA private FROM anon, authenticated;
            END IF;
        END $$
    """)

    op.create_table(
        "projects",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("description", sa.Text(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("owner_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_projects"),
        sa.UniqueConstraint("owner_id", name="uq_projects_owner_id"),
    )
    op.execute("ALTER TABLE public.projects ENABLE ROW LEVEL SECURITY")

    op.create_table(
        "api_keys",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("email", sa.Text(), nullable=False),
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("shown", sa.Text(), nullable=False),
        sa.Column("key_hash", sa.Text(), nullable=False),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.Column("last_used_at", UtcDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_api_keys"),
        sa.UniqueConstraint("key_hash", name="uq_api_keys_key_hash"),
        schema="private",
    )
    op.create_index("ix_api_keys_user_id", "api_keys", ["user_id"], schema="private")
    op.execute("ALTER TABLE private.api_keys ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_api_keys_user_id", table_name="api_keys", schema="private")
    op.drop_table("api_keys", schema="private")
    op.drop_table("projects")
