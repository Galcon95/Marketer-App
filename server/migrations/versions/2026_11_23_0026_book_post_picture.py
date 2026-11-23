"""The marketing agent's book post can come with an ad picture.

private.automation_settings   + book_post_picture (default false)

Revision ID: 0026
Revises: 0025
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0026"
down_revision: str | None = "0025"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("automation_settings", sa.Column("book_post_picture", sa.Boolean(), server_default=sa.text("false"),
                                                   nullable=False), schema="private")


def downgrade() -> None:
    op.drop_column("automation_settings", "book_post_picture", schema="private")
