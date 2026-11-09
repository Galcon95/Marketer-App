"""The tone of a discussion analysis's reply.

public.discussion_analyses.tone  neutral, inspiring, friendly, professional, punchy or literary (core/style.TONES).
                                 Analyses made before it was a setting were neutral, so existing rows get "neutral".

Revision ID: 0010
Revises: 0009
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0010"
down_revision: str | None = "0009"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("discussion_analyses",
                  sa.Column("tone", sa.Text(), server_default="neutral", nullable=False))


def downgrade() -> None:
    op.drop_column("discussion_analyses", "tone")
