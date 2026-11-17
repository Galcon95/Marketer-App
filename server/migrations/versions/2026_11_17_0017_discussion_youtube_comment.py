"""Discussion analyses of comments on the author's own YouTube channel.

public.discussion_analyses.youtube_comment_id  the comment the analysis answers ("own channel" mode); "" = none. The
                                               reply posted under it goes into replied_id/url/at (migration 0012).

Existing rows are analyses of other discussions: all empty.

Revision ID: 0017
Revises: 0016
Create Date: 2026-11-17
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0017"
down_revision: str | None = "0016"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("discussion_analyses", sa.Column("youtube_comment_id", sa.Text(), server_default="", nullable=False))


def downgrade() -> None:
    op.drop_column("discussion_analyses", "youtube_comment_id")
