"""align ad campaign stats tables with fullstats parser

Revision ID: 20260605_0004
Revises: 20260604_0003
Create Date: 2026-06-05 10:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260605_0004"
down_revision = "20260604_0003"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("fact_ad_campaign_day", "views", new_column_name="ad_views")
    op.alter_column("fact_ad_campaign_day", "clicks", new_column_name="ad_clicks")
    op.alter_column("fact_ad_campaign_day", "atbs", new_column_name="ad_atbs")
    op.alter_column("fact_ad_campaign_day", "orders", new_column_name="ad_orders")
    op.alter_column("fact_ad_campaign_day", "cancel_count", new_column_name="ad_cancels")
    op.alter_column("fact_ad_campaign_day", "ctr", new_column_name="ad_ctr")
    op.alter_column("fact_ad_campaign_day", "cpc", new_column_name="ad_cpc")
    op.alter_column("fact_ad_campaign_day", "cpm", new_column_name="ad_cpm")
    op.alter_column("fact_ad_campaign_day", "cr", new_column_name="ad_cr")
    op.alter_column("fact_ad_campaign_day", "roi", new_column_name="ad_roi")
    op.add_column("fact_ad_campaign_day", sa.Column("currency", sa.String(length=16), nullable=True))

    op.drop_constraint("uq_fact_ad_campaign_nm_day_natural_key", "fact_ad_campaign_nm_day", type_="unique")
    op.create_unique_constraint(
        "uq_fact_ad_campaign_nm_day_natural_key",
        "fact_ad_campaign_nm_day",
        ["date", "advert_id", "row_type", "conversion_type_raw", "nm_id"],
    )
    op.alter_column("fact_ad_campaign_nm_day", "views", new_column_name="ad_views")
    op.alter_column("fact_ad_campaign_nm_day", "clicks", new_column_name="ad_clicks")
    op.alter_column("fact_ad_campaign_nm_day", "atbs", new_column_name="ad_atbs")
    op.alter_column("fact_ad_campaign_nm_day", "orders", new_column_name="ad_orders")
    op.alter_column("fact_ad_campaign_nm_day", "cancel_count", new_column_name="ad_cancels")
    op.alter_column("fact_ad_campaign_nm_day", "ctr", new_column_name="ad_ctr")
    op.alter_column("fact_ad_campaign_nm_day", "cpc", new_column_name="ad_cpc")
    op.alter_column("fact_ad_campaign_nm_day", "cpm", new_column_name="ad_cpm")
    op.alter_column("fact_ad_campaign_nm_day", "cr", new_column_name="ad_cr")
    op.alter_column("fact_ad_campaign_nm_day", "roi", new_column_name="ad_roi")
    op.add_column("fact_ad_campaign_nm_day", sa.Column("conversion_type_display", sa.String(length=128), nullable=True))
    op.add_column("fact_ad_campaign_nm_day", sa.Column("currency", sa.String(length=16), nullable=True))


def downgrade() -> None:
    op.drop_column("fact_ad_campaign_nm_day", "currency")
    op.drop_column("fact_ad_campaign_nm_day", "conversion_type_display")
    op.alter_column("fact_ad_campaign_nm_day", "ad_roi", new_column_name="roi")
    op.alter_column("fact_ad_campaign_nm_day", "ad_cr", new_column_name="cr")
    op.alter_column("fact_ad_campaign_nm_day", "ad_cpm", new_column_name="cpm")
    op.alter_column("fact_ad_campaign_nm_day", "ad_cpc", new_column_name="cpc")
    op.alter_column("fact_ad_campaign_nm_day", "ad_ctr", new_column_name="ctr")
    op.alter_column("fact_ad_campaign_nm_day", "ad_cancels", new_column_name="cancel_count")
    op.alter_column("fact_ad_campaign_nm_day", "ad_orders", new_column_name="orders")
    op.alter_column("fact_ad_campaign_nm_day", "ad_atbs", new_column_name="atbs")
    op.alter_column("fact_ad_campaign_nm_day", "ad_clicks", new_column_name="clicks")
    op.alter_column("fact_ad_campaign_nm_day", "ad_views", new_column_name="views")
    op.drop_constraint("uq_fact_ad_campaign_nm_day_natural_key", "fact_ad_campaign_nm_day", type_="unique")
    op.create_unique_constraint(
        "uq_fact_ad_campaign_nm_day_natural_key",
        "fact_ad_campaign_nm_day",
        ["date", "advert_id", "row_type", "conversion_type", "nm_id"],
    )

    op.drop_column("fact_ad_campaign_day", "currency")
    op.alter_column("fact_ad_campaign_day", "ad_roi", new_column_name="roi")
    op.alter_column("fact_ad_campaign_day", "ad_cr", new_column_name="cr")
    op.alter_column("fact_ad_campaign_day", "ad_cpm", new_column_name="cpm")
    op.alter_column("fact_ad_campaign_day", "ad_cpc", new_column_name="cpc")
    op.alter_column("fact_ad_campaign_day", "ad_ctr", new_column_name="ctr")
    op.alter_column("fact_ad_campaign_day", "ad_cancels", new_column_name="cancel_count")
    op.alter_column("fact_ad_campaign_day", "ad_orders", new_column_name="orders")
    op.alter_column("fact_ad_campaign_day", "ad_atbs", new_column_name="atbs")
    op.alter_column("fact_ad_campaign_day", "ad_clicks", new_column_name="clicks")
    op.alter_column("fact_ad_campaign_day", "ad_views", new_column_name="views")
