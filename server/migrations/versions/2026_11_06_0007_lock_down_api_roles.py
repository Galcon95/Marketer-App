"""Second layer of protection: Supabase's API roles get no privileges on the app's tables.

Every table already has row-level security without a policy, so Supabase's REST API (roles anon and authenticated,
used with the public key or a user's token) sees no rows. Supabase still grants those roles table privileges by
default; revoking them means that even a policy added by mistake later could not open a table to the browser. The
server connects as the tables' owner (DATABASE_URL) and is not affected.

Also turns on row-level security for private.alembic_version (unreachable through the API anyway), so the rule
"every table has row-level security" holds without exception.

A new table needs the same: ENABLE ROW LEVEL SECURITY and REVOKE ALL ... FROM anon, authenticated in its migration.

Revision ID: 0007
Revises: 0006
Create Date: 2026-11-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0007"
down_revision: str | None = "0006"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLES = ["public.projects", "public.sources", "public.summaries", "public.chunks", "public.assets",
          "public.conversations", "public.usage_log", "private.api_keys", "private.alembic_version"]


def upgrade() -> None:
    op.execute("ALTER TABLE private.alembic_version ENABLE ROW LEVEL SECURITY")
    op.execute(f"""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON {", ".join(TABLES)} FROM anon, authenticated;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.execute("ALTER TABLE private.alembic_version DISABLE ROW LEVEL SECURITY")
    # The privileges are not granted back: the tables are meant to stay closed to the API roles.
