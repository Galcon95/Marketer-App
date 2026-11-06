"""The private Supabase Storage bucket "books" for the uploaded files and their covers (core/files.py).

storage.buckets  row "books": private, at most 50 MB per file (limits.toml max_upload_mb, Supabase's free-plan
                 limit), only PDFs and PNG covers

Storage's own row-level security on storage.objects has no policy for this bucket, so only the server (secret key)
reaches its files. On a PostgreSQL without Supabase Storage (no storage schema) nothing happens.

Downgrade leaves the bucket as it is: it holds the users' books.

Revision ID: 0006
Revises: 0005
Create Date: 2026-11-06
"""

from collections.abc import Sequence

from alembic import op

revision: str = "0006"
down_revision: str | None = "0005"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

MAX_FILE_BYTES = 50 * 1024 * 1024


def upgrade() -> None:
    op.execute(f"""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM information_schema.tables
                       WHERE table_schema = 'storage' AND table_name = 'buckets') THEN
                INSERT INTO storage.buckets (id, name, public, file_size_limit, allowed_mime_types)
                VALUES ('books', 'books', false, {MAX_FILE_BYTES}, ARRAY['application/pdf', 'image/png'])
                ON CONFLICT (id) DO UPDATE SET public = false, file_size_limit = EXCLUDED.file_size_limit,
                                               allowed_mime_types = EXCLUDED.allowed_mime_types;
            END IF;
        END $$
    """)


def downgrade() -> None:
    pass  # the bucket and the books in it stay
