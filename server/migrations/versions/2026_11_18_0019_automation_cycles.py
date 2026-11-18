"""The marketing agent's cycles, and pausing its schedule.

private.automation_cycles      one row per cycle: when, what started it, its proposals (JSON) and what the author
                               decided; status running / done / error / interrupted
private.automation_settings    + paused (the schedule is off for now), resumed_at (the next run counts from here)

Private schema and row-level security without a policy, like private.automation_settings.

Revision ID: 0019
Revises: 0018
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

from app.db.tables import UtcDateTime

revision: str = "0019"
down_revision: str | None = "0018"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("automation_settings", sa.Column("paused", sa.Boolean(), server_default=sa.text("false"),
                                                   nullable=False), schema="private")
    op.add_column("automation_settings", sa.Column("resumed_at", UtcDateTime(), nullable=True), schema="private")
    op.create_table(
        "automation_cycles",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("trigger", sa.Text(), nullable=False),
        sa.Column("status", sa.Text(), nullable=False),
        sa.Column("started_at", UtcDateTime(), nullable=False),
        sa.Column("ended_at", UtcDateTime(), nullable=True),
        sa.Column("entries", postgresql.JSONB(), nullable=False),
        sa.Column("note", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_automation_cycles"),
        schema="private",
    )
    op.create_index("ix_automation_cycles_user_started", "automation_cycles", ["user_id", "started_at"],
                    schema="private")
    op.execute("ALTER TABLE private.automation_cycles ENABLE ROW LEVEL SECURITY")
    # Supabase's API roles (absent on a plain PostgreSQL): no privileges, as for the other tables (migration 0007).
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON private.automation_cycles FROM anon, authenticated;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_index("ix_automation_cycles_user_started", table_name="automation_cycles", schema="private")
    op.drop_table("automation_cycles", schema="private")
    op.drop_column("automation_settings", "resumed_at", schema="private")
    op.drop_column("automation_settings", "paused", schema="private")
