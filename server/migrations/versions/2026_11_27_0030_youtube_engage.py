"""What the marketing agent writes under an own YouTube video, set apart from Facebook's question switch.

private.automation_settings   + youtube_engage: "thought" (default: a comment about a topic of the video and the
                              book, no question), "question" or "off"; `engage` is now Facebook's only

Revision ID: 0030
Revises: 0029
Create Date: 2026-11-27
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0030"
down_revision: str | None = "0029"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.add_column("automation_settings", sa.Column("youtube_engage", sa.Text(), server_default=sa.text("'thought'"),
                                                   nullable=False), schema="private")


def downgrade() -> None:
    op.drop_column("automation_settings", "youtube_engage", schema="private")
