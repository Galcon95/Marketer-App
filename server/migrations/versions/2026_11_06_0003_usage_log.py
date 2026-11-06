"""The usage log (every model call with its tokens and costs) moves from usage.jsonl into the database.

public.usage_log    was server/assets/usage/usage.jsonl; the budgets of limits.toml are sums over it

No foreign keys (the costs stay when a project is deleted). Indexed by time (budgets: today, this month) and user.
Row-level security on, no policy, like the other tables.

Revision ID: 0003
Revises: 0002
Create Date: 2026-11-06
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.tables import UtcDateTime

revision: str = "0003"
down_revision: str | None = "0002"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "usage_log",
        sa.Column("id", sa.BigInteger(), sa.Identity(), nullable=False),
        sa.Column("timestamp", UtcDateTime(), nullable=False),
        sa.Column("operation", sa.Text(), nullable=False),
        sa.Column("kind", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("input_tokens", sa.Integer(), nullable=False),
        sa.Column("output_tokens", sa.Integer(), nullable=False),
        sa.Column("input_cost", sa.Double(), nullable=False),
        sa.Column("output_cost", sa.Double(), nullable=False),
        sa.Column("cost", sa.Double(), nullable=False),
        sa.Column("cost_source", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=True),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("request_id", sa.Text(), nullable=True),
        sa.Column("user_id", sa.Text(), nullable=True),
        sa.PrimaryKeyConstraint("id", name="pk_usage_log"),
    )
    op.create_index("ix_usage_log_timestamp", "usage_log", ["timestamp"])
    op.create_index("ix_usage_log_user_id", "usage_log", ["user_id"])
    op.execute("ALTER TABLE public.usage_log ENABLE ROW LEVEL SECURITY")


def downgrade() -> None:
    op.drop_index("ix_usage_log_user_id", table_name="usage_log")
    op.drop_index("ix_usage_log_timestamp", table_name="usage_log")
    op.drop_table("usage_log")
