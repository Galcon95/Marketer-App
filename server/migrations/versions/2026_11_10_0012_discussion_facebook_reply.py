"""Discussion analyses of comments on the author's own Facebook Page, and the reply posted there.

public.discussion_analyses.facebook_comment_id  the comment the analysis answers ("own Page" mode); "" = none
public.discussion_analyses.replied_id           the reply posted as the Page under it; "" = not posted from the app
public.discussion_analyses.replied_url          link to that reply; ""
public.discussion_analyses.replied_at           when it was posted (UTC); NULL = not posted

Existing rows are analyses of discussions elsewhere: all empty.

Revision ID: 0012
Revises: 0011
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.tables import UtcDateTime

revision: str = "0012"
down_revision: str | None = "0011"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "discussion_analyses"


def upgrade() -> None:
    for name in ("facebook_comment_id", "replied_id", "replied_url"):
        op.add_column(TABLE, sa.Column(name, sa.Text(), server_default="", nullable=False))
    op.add_column(TABLE, sa.Column("replied_at", UtcDateTime(), nullable=True))


def downgrade() -> None:
    for name in ("replied_at", "replied_url", "replied_id", "facebook_comment_id"):
        op.drop_column(TABLE, name)
