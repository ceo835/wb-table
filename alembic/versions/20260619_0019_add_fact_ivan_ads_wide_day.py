"""Add fact_ivan_ads_wide_day for manual Ivan ads wide imports.

Revision ID: 20260619_0019
Revises: 20260617_0018
Create Date: 2026-06-19 18:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260619_0019"
down_revision = "20260617_0018"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fact_ivan_ads_wide_day",
        sa.Column("fact_ivan_ads_wide_day_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("date", sa.Date(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("supplier_article", sa.String(length=255), nullable=True),
        sa.Column("title", sa.Text(), nullable=True),
        sa.Column("campaign_ref", sa.String(length=255), nullable=False),
        sa.Column("campaign_name", sa.Text(), nullable=True),
        sa.Column("ad_spend", sa.Numeric(18, 2), nullable=True),
        sa.Column("ad_atbs", sa.Numeric(18, 4), nullable=True),
        sa.Column("ad_cart_ctr", sa.Numeric(18, 6), nullable=True),
        sa.Column("ad_cost_per_cart", sa.Numeric(18, 6), nullable=True),
        sa.Column("ad_views", sa.Numeric(18, 4), nullable=True),
        sa.Column("ad_cpm", sa.Numeric(18, 6), nullable=True),
        sa.Column("source_file_name", sa.Text(), nullable=True),
        sa.Column("data_status", sa.String(length=64), nullable=True),
        sa.Column("source_status", sa.String(length=128), nullable=True),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.UniqueConstraint("date", "nm_id", "campaign_ref", name="uq_fact_ivan_ads_wide_day_date_nm_campaign"),
    )
    op.create_index(
        "idx_fact_ivan_ads_wide_day_date_nm",
        "fact_ivan_ads_wide_day",
        ["date", "nm_id"],
        unique=False,
    )
    op.create_index(
        "idx_fact_ivan_ads_wide_day_campaign",
        "fact_ivan_ads_wide_day",
        ["campaign_ref", "date"],
        unique=False,
    )
    op.create_index(
        "idx_fact_ivan_ads_wide_day_status",
        "fact_ivan_ads_wide_day",
        ["source_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_fact_ivan_ads_wide_day_status", table_name="fact_ivan_ads_wide_day")
    op.drop_index("idx_fact_ivan_ads_wide_day_campaign", table_name="fact_ivan_ads_wide_day")
    op.drop_index("idx_fact_ivan_ads_wide_day_date_nm", table_name="fact_ivan_ads_wide_day")
    op.drop_table("fact_ivan_ads_wide_day")
