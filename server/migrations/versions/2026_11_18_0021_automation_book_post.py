"""The marketing agent's books, its book post phase and test mode.

private.automation_settings   + books (the book ids the agent uses; [] = FACEBOOK_INBOX_BOOKS), book_links (book id →
                              where to get it, the book post's link), book_post (propose a new post about the next
                              book topic at the end of a cycle), test_mode (propose everything, publish nothing)

Revision ID: 0021
Revises: 0020
Create Date: 2026-11-18
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0021"
down_revision: str | None = "0020"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

COLUMNS = [
    ("books", postgresql.JSONB(), "'[]'::jsonb"),
    ("book_links", postgresql.JSONB(), "'{}'::jsonb"),
    ("book_post", sa.Boolean(), "true"),
    ("test_mode", sa.Boolean(), "false"),
]


def upgrade() -> None:
    for name, type_, default in COLUMNS:
        op.add_column("automation_settings", sa.Column(name, type_, server_default=sa.text(default), nullable=False),
                      schema="private")


def downgrade() -> None:
    for name, _, _ in reversed(COLUMNS):
        op.drop_column("automation_settings", name, schema="private")
