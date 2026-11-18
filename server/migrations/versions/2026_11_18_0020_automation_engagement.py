"""The marketing agent's engagement phase and quiet hours.

private.automation_settings   + quiet_from, quiet_to ("HH:MM", "" = none), engage (propose a question under an own
                              post without comments), engage_days (how recent the post), daily_limit (own comments
                              and posts per day)

Revision ID: 0020
Revises: 0019
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0020"
down_revision: str | None = "0019"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = [
    ("quiet_from", sa.Text(), "''"),
    ("quiet_to", sa.Text(), "''"),
    ("engage", sa.Boolean(), "true"),
    ("engage_days", sa.Integer(), "14"),
    ("daily_limit", sa.Integer(), "2"),
]


def upgrade() -> None:
    for name, type_, default in COLUMNS:
        op.add_column("automation_settings", sa.Column(name, type_, server_default=sa.text(default), nullable=False),
                      schema="private")


def downgrade() -> None:
    for name, _, _ in reversed(COLUMNS):
        op.drop_column("automation_settings", name, schema="private")
