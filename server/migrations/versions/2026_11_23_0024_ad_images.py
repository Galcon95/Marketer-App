"""Generated ad pictures of the assets (Content Studio, "Create image").

public.ad_images  one picture of an asset: format, headline, scene, model, prompt version, cost; the picture itself
                  is a PNG in the Storage bucket "books" at {project_id}/ads/{id}.png (core/ad_images.py)

Deleted with its asset or project (foreign keys); when its book is deleted, source_id becomes NULL. Row-level security
on, no policy, and no privileges for Supabase's API roles, like every table (0007).

Revision ID: 0024
Revises: 0023
Create Date: 2026-11-23
"""

from collections.abc import Sequence

import sqlalchemy as sa
from alembic import op

from app.db.tables import UtcDateTime

revision: str = "0024"
down_revision: str | None = "0023"
branch_labels: str | Sequence[str] | None = None
depends_on: str | Sequence[str] | None = None


def upgrade() -> None:
    op.create_table(
        "ad_images",
        sa.Column("id", sa.Text(), nullable=False),
        sa.Column("project_id", sa.Text(), nullable=False),
        sa.Column("asset_id", sa.Text(), nullable=False),
        sa.Column("source_id", sa.Text(), nullable=True),
        sa.Column("format", sa.Text(), nullable=False),
        sa.Column("headline", sa.Text(), nullable=False),
        sa.Column("scene", sa.Text(), nullable=False),
        sa.Column("model", sa.Text(), nullable=False),
        sa.Column("prompt_version", sa.Text(), nullable=False),
        sa.Column("cost", sa.Double(), nullable=True),
        sa.Column("created_at", UtcDateTime(), nullable=False),
        sa.ForeignKeyConstraint(["project_id"], ["projects.id"], name="fk_ad_images_project_id_projects",
                                ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["asset_id"], ["assets.id"], name="fk_ad_images_asset_id_assets", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_id"], ["sources.id"], name="fk_ad_images_source_id_sources",
                                ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_ad_images"),
    )
    op.create_index("ix_ad_images_project_id", "ad_images", ["project_id"])
    op.create_index("ix_ad_images_asset_id", "ad_images", ["asset_id"])
    op.execute("ALTER TABLE public.ad_images ENABLE ROW LEVEL SECURITY")
    op.execute("""
        DO $$ BEGIN
            IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'anon') THEN
                REVOKE ALL ON public.ad_images FROM anon, authenticated;
            END IF;
        END $$
    """)


def downgrade() -> None:
    op.drop_index("ix_ad_images_asset_id", table_name="ad_images")
    op.drop_index("ix_ad_images_project_id", table_name="ad_images")
    op.drop_table("ad_images")
