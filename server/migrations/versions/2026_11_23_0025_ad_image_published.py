"""Ad pictures posted on the author's Facebook Page.

public.ad_images   + published_id, published_url, published_at (all nullable: not posted yet)

Revision ID: 0025
Revises: 0024
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.tables import UtcDateTime

revision: str = "0025"
down_revision: str | None = "0024"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("ad_images", sa.Column("published_id", sa.Text(), nullable=True))
    op.add_column("ad_images", sa.Column("published_url", sa.Text(), nullable=True))
    op.add_column("ad_images", sa.Column("published_at", UtcDateTime(), nullable=True))


def downgrade() -> None:
    for name in ("published_at", "published_url", "published_id"):
        op.drop_column("ad_images", name)
