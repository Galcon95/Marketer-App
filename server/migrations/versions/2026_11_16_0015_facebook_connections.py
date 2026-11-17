"""Every user's own Facebook Page, connected with Facebook Login.

private.facebook_connections   one row per user: the Page's id and name, its access token encrypted (Fernet, key
                               TOKEN_ENCRYPTION_KEY in the server's environment, never in the database)

Private schema and row-level security without a policy, like private.api_keys: Supabase's REST API sees nothing.

Revision ID: 0015
Revises: 0014
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.tables import UtcDateTime

revision: str = "0015"
down_revision: str | None = "0014"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "facebook_connections",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("page_id", sa.Text(), nullable=False),
        sa.Column("page_name", sa.Text(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("connected_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name="pk_facebook_connections"),
        schema="private",
    )
    op.execute("ALTER TABLE private.facebook_connections ENABLE ROW LEVEL SECURITY")
    # Supabase's API roles (absent on a plain PostgreSQL): no privileges, as for the other tables (migration 0007).
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON private.facebook_connections FROM anon, authenticated;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_table("facebook_connections", schema="private")
