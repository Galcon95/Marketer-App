"""The audit log (core/audit.py): security-relevant events, only added and read.

private.audit_events   one row per event: id, at, action, user_id, target, detail, request_id

Private schema and row-level security without a policy, like private.app_switches: only the server reads and writes
it.

Revision ID: 0029
Revises: 0028
Create Date: 2026-11-26
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.tables import UtcDateTime

revision: str = "0029"
down_revision: str | None = "0028"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "audit_events",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("at", UtcDateTime(), nullable=False),
        sa.Column("action", sa.Text(), nullable=False),
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("target", sa.Text(), nullable=False),
        sa.Column("detail", sa.Text(), nullable=False),
        sa.Column("request_id", sa.Text(), nullable=False),
        sa.PrimaryKeyConstraint("id", name="pk_audit_events"),
        schema="private",
    )
    op.create_index("ix_audit_events_at", "audit_events", ["at"], schema="private")
    op.create_index("ix_audit_events_user_id", "audit_events", ["user_id"], schema="private")
    op.execute("ALTER TABLE private.audit_events ENABLE ROW LEVEL SECURITY")
    # Supabase's API roles (absent on a plain PostgreSQL): no privileges, as for the other tables (migration 0007).
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON private.audit_events FROM anon, authenticated;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_index("ix_audit_events_user_id", table_name="audit_events", schema="private")
    op.drop_index("ix_audit_events_at", table_name="audit_events", schema="private")
    op.drop_table("audit_events", schema="private")
