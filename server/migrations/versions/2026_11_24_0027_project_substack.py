"""The author's own Substack publication, saved with the project (Community: My Substack, own posts left out of scans).

public.projects   + substack (default '': none)

Revision ID: 0027
Revises: 0026
Create Date: 2026-11-24
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0027"
down_revision: str | None = "0026"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("projects", sa.Column("substack", sa.Text(), server_default=sa.text("''"), nullable=False))


def downgrade() -> None:
    op.drop_column("projects", "substack")
