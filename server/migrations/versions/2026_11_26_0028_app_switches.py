"""The app's switches that must survive a restart (core/alarm.py): the guest demo on or off, and the freeze of all
model calls except the admin's.

private.app_switches   one row per switch that was ever changed: name, on, reason, changed_at

Private schema and row-level security without a policy, like private.automation_settings.

Revision ID: 0028
Revises: 0027
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.tables import UtcDateTime

revision: str = "0028"
down_revision: str | None = "0027"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "app_switches",
        sa.Column("name", sa.Text(), nullable=False),
        sa.Column("on", sa.Boolean(), nullable=False),
        sa.Column("reason", sa.Text(), server_default=sa.text("''"), nullable=False),
        sa.Column("changed_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("name", name="pk_app_switches"),
        schema="private",
    )
    op.execute("ALTER TABLE private.app_switches ENABLE ROW LEVEL SECURITY")
    # Supabase's API roles (absent on a plain PostgreSQL): no privileges, as for the other tables (migration 0007).
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON private.app_switches FROM anon, authenticated;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_table("app_switches", schema="private")
