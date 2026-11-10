"""Where an asset was published: the post on the author's Facebook Page.

public.assets.published_id   id of the Facebook post ("<page id>_<post id>"); "" = not published (all existing rows)
public.assets.published_url  link to that post; ""
public.assets.published_at   when it was published (UTC); NULL = not published

Revision ID: 0011
Revises: 0010
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.tables import UtcDateTime

revision: str = "0011"
down_revision: str | None = "0010"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("assets", sa.Column("published_id", sa.Text(), server_default="", nullable=False))
    op.add_column("assets", sa.Column("published_url", sa.Text(), server_default="", nullable=False))
    op.add_column("assets", sa.Column("published_at", UtcDateTime(), nullable=True))


def downgrade() -> None:
    op.drop_column("assets", "published_at")
    op.drop_column("assets", "published_url")
    op.drop_column("assets", "published_id")
