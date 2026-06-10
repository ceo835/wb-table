"""align mart_total_report for compact db-based v1

Revision ID: 20260605_0007
Revises: 20260605_0006
Create Date: 2026-06-05 14:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260605_0007"
down_revision = "20260605_0006"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_constraint("uq_mart_total_report_natural_key", "mart_total_report", type_="unique")
    op.create_unique_constraint("uq_mart_total_report_natural_key", "mart_total_report", ["report_date", "nm_id"])

    op.add_column("mart_total_report", sa.Column("cart_count", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("buyout_count", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("buyout_sum", sa.Numeric(precision=18, scale=2), nullable=True))
    op.add_column("mart_total_report", sa.Column("buyout_percent", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("add_to_cart_conversion", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("cart_to_order_conversion", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("add_to_wishlist_count", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("avg_delivery_time", sa.Numeric(precision=18, scale=4), nullable=True))
    op.alter_column("mart_total_report", "current_wb_stock_qty", new_column_name="current_stock_qty")
    op.alter_column("mart_total_report", "current_stock_total_sum", new_column_name="current_stock_sum")
    op.add_column("mart_total_report", sa.Column("stock_snapshot_date", sa.Date(), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_cost_spend", sa.Numeric(precision=18, scale=2), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_views", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_clicks", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_atbs", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_orders", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_revenue", sa.Numeric(precision=18, scale=2), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_avg_position", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("direct_ad_atbs", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("associated_ad_atbs", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("multicard_ad_atbs", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("search_queries_count", sa.Integer(), nullable=True))
    op.add_column("mart_total_report", sa.Column("search_avg_position", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("search_visibility", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("search_clicks", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("search_cart", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("search_orders", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("localization_regions_count", sa.Integer(), nullable=True))
    op.add_column("mart_total_report", sa.Column("localization_orders_total_qty", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("localization_sale_item_qty", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("localization_sale_amount", sa.Numeric(precision=18, scale=2), nullable=True))
    op.add_column("mart_total_report", sa.Column("vbro_organic_sales_qty", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("vbro_operating_profit", sa.Numeric(precision=18, scale=2), nullable=True))
    op.add_column("mart_total_report", sa.Column("has_funnel", sa.Boolean(), nullable=True))
    op.add_column("mart_total_report", sa.Column("has_stock", sa.Boolean(), nullable=True))
    op.add_column("mart_total_report", sa.Column("has_ad_cost", sa.Boolean(), nullable=True))
    op.add_column("mart_total_report", sa.Column("has_ad_campaign", sa.Boolean(), nullable=True))
    op.add_column("mart_total_report", sa.Column("has_search", sa.Boolean(), nullable=True))
    op.add_column("mart_total_report", sa.Column("has_localization", sa.Boolean(), nullable=True))
    op.add_column("mart_total_report", sa.Column("has_vbro", sa.Boolean(), nullable=True))
    op.add_column("mart_total_report", sa.Column("has_entry_points", sa.Boolean(), nullable=True))
    op.add_column("mart_total_report", sa.Column("has_card_comparison", sa.Boolean(), nullable=True))
    op.execute("UPDATE mart_total_report SET ad_cost_spend = ad_spend WHERE ad_cost_spend IS NULL AND ad_spend IS NOT NULL")


def downgrade() -> None:
    op.drop_column("mart_total_report", "has_card_comparison")
    op.drop_column("mart_total_report", "has_entry_points")
    op.drop_column("mart_total_report", "has_vbro")
    op.drop_column("mart_total_report", "has_localization")
    op.drop_column("mart_total_report", "has_search")
    op.drop_column("mart_total_report", "has_ad_campaign")
    op.drop_column("mart_total_report", "has_ad_cost")
    op.drop_column("mart_total_report", "has_stock")
    op.drop_column("mart_total_report", "has_funnel")
    op.drop_column("mart_total_report", "vbro_operating_profit")
    op.drop_column("mart_total_report", "vbro_organic_sales_qty")
    op.drop_column("mart_total_report", "localization_sale_amount")
    op.drop_column("mart_total_report", "localization_sale_item_qty")
    op.drop_column("mart_total_report", "localization_orders_total_qty")
    op.drop_column("mart_total_report", "localization_regions_count")
    op.drop_column("mart_total_report", "search_orders")
    op.drop_column("mart_total_report", "search_cart")
    op.drop_column("mart_total_report", "search_clicks")
    op.drop_column("mart_total_report", "search_visibility")
    op.drop_column("mart_total_report", "search_avg_position")
    op.drop_column("mart_total_report", "search_queries_count")
    op.drop_column("mart_total_report", "multicard_ad_atbs")
    op.drop_column("mart_total_report", "associated_ad_atbs")
    op.drop_column("mart_total_report", "direct_ad_atbs")
    op.drop_column("mart_total_report", "ad_avg_position")
    op.drop_column("mart_total_report", "ad_revenue")
    op.drop_column("mart_total_report", "ad_orders")
    op.drop_column("mart_total_report", "ad_atbs")
    op.drop_column("mart_total_report", "ad_clicks")
    op.drop_column("mart_total_report", "ad_views")
    op.drop_column("mart_total_report", "ad_cost_spend")
    op.drop_column("mart_total_report", "stock_snapshot_date")
    op.alter_column("mart_total_report", "current_stock_sum", new_column_name="current_stock_total_sum")
    op.alter_column("mart_total_report", "current_stock_qty", new_column_name="current_wb_stock_qty")
    op.drop_column("mart_total_report", "avg_delivery_time")
    op.drop_column("mart_total_report", "add_to_wishlist_count")
    op.drop_column("mart_total_report", "cart_to_order_conversion")
    op.drop_column("mart_total_report", "add_to_cart_conversion")
    op.drop_column("mart_total_report", "buyout_percent")
    op.drop_column("mart_total_report", "buyout_sum")
    op.drop_column("mart_total_report", "buyout_count")
    op.drop_column("mart_total_report", "cart_count")
    op.drop_constraint("uq_mart_total_report_natural_key", "mart_total_report", type_="unique")
    op.create_unique_constraint(
        "uq_mart_total_report_natural_key",
        "mart_total_report",
        ["report_date", "nm_id", "supplier_article"],
    )
