"""Prompt-injection scan of the discussion and output guard of the reply, saved with each analysis.

public.discussion_analyses.injection_risk      "none", "low" or "high": the scan of the pasted discussion
public.discussion_analyses.injection_findings  what the scan found, one "rule: excerpt" line each
public.discussion_analyses.output_issues       what the output guard found in the drafted reply

Existing rows were not scanned: "none" and empty lists.

Revision ID: 0013
Revises: 0012
Create Date: 2026-11-10
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision: str = "0013"
down_revision: str | None = "0012"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None

TABLE = "discussion_analyses"


def upgrade() -> None:
    op.add_column(TABLE, sa.Column("injection_risk", sa.Text(), server_default="none", nullable=False))
    for name in ("injection_findings", "output_issues"):
        op.add_column(TABLE, sa.Column(name, postgresql.JSONB(), server_default=sa.text("'[]'::jsonb"),
                                       nullable=False))


def downgrade() -> None:
    for name in ("output_issues", "injection_findings", "injection_risk"):
        op.drop_column(TABLE, name)
