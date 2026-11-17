"""Every user's own YouTube channel, connected with Google sign-in.

private.youtube_connections   one row per user: the channel's id and name, Google's refresh token encrypted (Fernet,
                              key TOKEN_ENCRYPTION_KEY in the server's environment, never in the database)

Private schema and row-level security without a policy, like private.facebook_connections.

Revision ID: 0016
Revises: 0015
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.tables import UtcDateTime

revision: str = "0016"
down_revision: str | None = "0015"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "youtube_connections",
        sa.Column("user_id", sa.Text(), nullable=False),
        sa.Column("channel_id", sa.Text(), nullable=False),
        sa.Column("channel_name", sa.Text(), nullable=False),
        sa.Column("token", sa.Text(), nullable=False),
        sa.Column("connected_at", UtcDateTime(), nullable=False),
        sa.PrimaryKeyConstraint("user_id", name="pk_youtube_connections"),
        schema="private",
    )
    op.execute("ALTER TABLE private.youtube_connections ENABLE ROW LEVEL SECURITY")
    # Supabase's API roles (absent on a plain PostgreSQL): no privileges, as for the other tables (migration 0007).
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON private.youtube_connections FROM anon, authenticated;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_table("youtube_connections", schema="private")
