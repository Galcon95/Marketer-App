"""The "how human" setting of a discussion analysis.

public.discussion_analyses.humanize  0-100, the setting the reply was written with (core/style.py). Analyses made
                                     before it was a setting were written with 70, so existing rows get 70.

Revision ID: 0009
Revises: 0008
Create Date: 2026-11-09
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0009"
down_revision: str | None = "0008"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("discussion_analyses",
                  sa.Column("humanize", sa.Integer(), server_default="70", nullable=False))


def downgrade() -> None:
    op.drop_column("discussion_analyses", "humanize")
