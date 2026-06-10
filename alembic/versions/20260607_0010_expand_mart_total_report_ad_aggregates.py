"""Expand mart_total_report with ad aggregate totals and derived KPIs.

Revision ID: 20260607_0010
Revises: 20260607_0009
Create Date: 2026-06-07 14:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260607_0010"
down_revision = "20260607_0009"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mart_total_report", sa.Column("ad_spend_total", sa.Numeric(precision=18, scale=2), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_views_total", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_clicks_total", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_atbs_total", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_orders_total", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("unknown_ad_atbs", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_cost_per_cart_calc", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("associated_atbs_percent_calc", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("organic_cart_share_calc", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("organic_cart_share_status", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("mart_total_report", "organic_cart_share_status")
    op.drop_column("mart_total_report", "organic_cart_share_calc")
    op.drop_column("mart_total_report", "associated_atbs_percent_calc")
    op.drop_column("mart_total_report", "ad_cost_per_cart_calc")
    op.drop_column("mart_total_report", "unknown_ad_atbs")
    op.drop_column("mart_total_report", "ad_orders_total")
    op.drop_column("mart_total_report", "ad_atbs_total")
    op.drop_column("mart_total_report", "ad_clicks_total")
    op.drop_column("mart_total_report", "ad_views_total")
    op.drop_column("mart_total_report", "ad_spend_total")
