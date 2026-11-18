"""Every user's schedule for the marketing agent (agents/automation.py).

private.automation_settings   one row per user: manual or scheduled, every N minutes or at times of day, days of the
                              week, time zone; when it last ran

Private schema and row-level security without a policy, like private.youtube_connections.

Revision ID: 0018
Revises: 0017
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.tables import UtcDateTime

revision: str = "0018"
down_revision: str | None = "0017"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "automation_settings",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("mode", sa.Text(), nullable=False),
        sa.Column("every_minutes", sa.Integer(), nullable=False),
        sa.Column("times", postgresql.JSONB(), nullable=False),
        sa.Column("days", postgresql.JSONB(), nullable=False),
        sa.Column("timezone", sa.Text(), nullable=False),
        sa.Column("saved_at", UtcDateTime(), nullable=True),
        sa.Column("last_run_at", UtcDateTime(), nullable=True),
        sa.PrimaryKeyConstraint("user_id", name="pk_automation_settings"),
        schema="private",
    )
    op.execute("ALTER TABLE private.automation_settings ENABLE ROW LEVEL SECURITY")
    # Supabase's API roles (absent on a plain PostgreSQL): no privileges, as for the other tables (migration 0007).
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON private.automation_settings FROM anon, authenticated;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_table("automation_settings", schema="private")
