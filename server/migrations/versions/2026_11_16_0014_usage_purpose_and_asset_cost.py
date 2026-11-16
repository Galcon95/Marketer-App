"""What each model call was for, and the cost of each generated asset.

public.usage_log.asset_id     the single asset the call generated (POST /generate)
public.usage_log.asset_type   that asset's type, e.g. "newsletter"
public.usage_log.campaign_id  the campaign kit the call was part of (POST /campaigns)
public.assets.cost            USD of the model calls that wrote the asset

Existing rows were not tagged: NULL ("not recorded").

Revision ID: 0014
Revises: 0013
Create Date: 2026-11-16
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

revision: str = "0014"
down_revision: str | None = "0013"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    for name in ("asset_id", "asset_type", "campaign_id"):
        op.add_column("usage_log", sa.Column(name, sa.Text(), nullable=True))
    op.create_index("ix_usage_log_asset_id", "usage_log", ["asset_id"])
    op.create_index("ix_usage_log_campaign_id", "usage_log", ["campaign_id"])
    op.add_column("assets", sa.Column("cost", sa.Double(), nullable=True))


def downgrade() -> None:
    op.drop_column("assets", "cost")
    op.drop_index("ix_usage_log_campaign_id", table_name="usage_log")
    op.drop_index("ix_usage_log_asset_id", table_name="usage_log")
    for name in ("campaign_id", "asset_type", "asset_id"):
        op.drop_column("usage_log", name)
