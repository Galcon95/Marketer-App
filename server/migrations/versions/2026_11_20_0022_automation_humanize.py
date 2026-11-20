"""How human the marketing agent's texts sound.

private.automation_settings   + humanize (0-100, default 80: the value the agents used before it was a setting)

Revision ID: 0022
Revises: 0021
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0022"
down_revision: str | None = "0021"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("automation_settings", sa.Column("humanize", sa.Integer(), server_default=sa.text("80"),
                                                   nullable=False), schema="private")


def downgrade() -> None:
    op.drop_column("automation_settings", "humanize", schema="private")
