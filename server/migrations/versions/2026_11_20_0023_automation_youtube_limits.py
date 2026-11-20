"""YouTube's own age window and daily limit for the marketing agent's questions under videos.

private.automation_settings   + youtube_engage_days (default 90), youtube_daily_limit (default 2); engage_days and
                              daily_limit are now Facebook's only

Revision ID: 0023
Revises: 0022
Create Date: 2026-11-20
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0023"
down_revision: str | None = "0022"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = [("youtube_engage_days", "90"), ("youtube_daily_limit", "2")]


def upgrade() -> None:
    for name, default in COLUMNS:
        op.add_column("automation_settings", sa.Column(name, sa.Integer(), server_default=sa.text(default),
                                                       nullable=False), schema="private")


def downgrade() -> None:
    for name, _ in reversed(COLUMNS):
        op.drop_column("automation_settings", name, schema="private")
