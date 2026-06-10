"""Expand mart_total_report for v2 grid and calculated metrics.

Revision ID: 20260607_0009
Revises: 20260606_0008
Create Date: 2026-06-07 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260607_0009"
down_revision = "20260606_0008"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mart_total_report", sa.Column("ctr_calc", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("add_to_cart_conversion_calc", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("cart_to_order_conversion_calc", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_cpc_calc", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_cpm_calc", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_cpo_calc", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_share_of_revenue_calc", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("has_localization_partial", sa.Boolean(), nullable=True))
    op.add_column("mart_total_report", sa.Column("entry_point_status", sa.String(length=64), nullable=True))
    op.add_column("mart_total_report", sa.Column("orders_geography_status", sa.String(length=64), nullable=True))
    op.add_column("mart_total_report", sa.Column("vbro_status", sa.String(length=64), nullable=True))
    op.add_column("mart_total_report", sa.Column("card_comparison_status", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("mart_total_report", "card_comparison_status")
    op.drop_column("mart_total_report", "vbro_status")
    op.drop_column("mart_total_report", "orders_geography_status")
    op.drop_column("mart_total_report", "entry_point_status")
    op.drop_column("mart_total_report", "has_localization_partial")
    op.drop_column("mart_total_report", "ad_share_of_revenue_calc")
    op.drop_column("mart_total_report", "ad_cpo_calc")
    op.drop_column("mart_total_report", "ad_cpm_calc")
    op.drop_column("mart_total_report", "ad_cpc_calc")
    op.drop_column("mart_total_report", "cart_to_order_conversion_calc")
    op.drop_column("mart_total_report", "add_to_cart_conversion_calc")
    op.drop_column("mart_total_report", "ctr_calc")
