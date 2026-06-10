"""align fact_search_query_metric with current search parser

Revision ID: 20260605_0005
Revises: 20260605_0004
Create Date: 2026-06-05 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260605_0005"
down_revision = "20260605_0004"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fact_search_query_metric", sa.Column("date", sa.Date(), nullable=True))
    op.add_column("fact_search_query_metric", sa.Column("supplier_article", sa.String(length=255), nullable=True))
    op.add_column("fact_search_query_metric", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("fact_search_query_metric", sa.Column("subject", sa.String(length=255), nullable=True))
    op.add_column("fact_search_query_metric", sa.Column("brand", sa.String(length=255), nullable=True))
    op.add_column("fact_search_query_metric", sa.Column("card_rating", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("fact_search_query_metric", sa.Column("reviews_rating", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("fact_search_query_metric", sa.Column("query_count_prev", sa.Numeric(precision=18, scale=4), nullable=True))
    op.alter_column("fact_search_query_metric", "card_clicks", new_column_name="search_clicks")
    op.alter_column("fact_search_query_metric", "card_clicks_prev", new_column_name="search_clicks_prev")
    op.alter_column("fact_search_query_metric", "cart_count", new_column_name="search_cart")
    op.alter_column("fact_search_query_metric", "cart_count_prev", new_column_name="search_cart_prev")
    op.alter_column("fact_search_query_metric", "order_count", new_column_name="search_orders")
    op.alter_column("fact_search_query_metric", "order_count_prev", new_column_name="search_orders_prev")
    op.alter_column("fact_search_query_metric", "add_to_cart_conversion", new_column_name="cart_conversion")
    op.alter_column("fact_search_query_metric", "cart_to_order_conversion", new_column_name="order_conversion")
    op.add_column(
        "fact_search_query_metric",
        sa.Column("search_clicks_competitor_percentile", sa.Numeric(precision=18, scale=6), nullable=True),
    )
    op.add_column(
        "fact_search_query_metric",
        sa.Column("search_cart_competitor_percentile", sa.Numeric(precision=18, scale=6), nullable=True),
    )
    op.add_column(
        "fact_search_query_metric",
        sa.Column("cart_conversion_prev", sa.Numeric(precision=18, scale=6), nullable=True),
    )
    op.add_column(
        "fact_search_query_metric",
        sa.Column("cart_conversion_competitor_percentile", sa.Numeric(precision=18, scale=6), nullable=True),
    )
    op.add_column(
        "fact_search_query_metric",
        sa.Column("search_orders_competitor_percentile", sa.Numeric(precision=18, scale=6), nullable=True),
    )
    op.add_column(
        "fact_search_query_metric",
        sa.Column("order_conversion_prev", sa.Numeric(precision=18, scale=6), nullable=True),
    )
    op.add_column(
        "fact_search_query_metric",
        sa.Column("order_conversion_competitor_percentile", sa.Numeric(precision=18, scale=6), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("fact_search_query_metric", "order_conversion_competitor_percentile")
    op.drop_column("fact_search_query_metric", "order_conversion_prev")
    op.drop_column("fact_search_query_metric", "search_orders_competitor_percentile")
    op.drop_column("fact_search_query_metric", "cart_conversion_competitor_percentile")
    op.drop_column("fact_search_query_metric", "cart_conversion_prev")
    op.drop_column("fact_search_query_metric", "search_cart_competitor_percentile")
    op.drop_column("fact_search_query_metric", "search_clicks_competitor_percentile")
    op.alter_column("fact_search_query_metric", "order_conversion", new_column_name="cart_to_order_conversion")
    op.alter_column("fact_search_query_metric", "cart_conversion", new_column_name="add_to_cart_conversion")
    op.alter_column("fact_search_query_metric", "search_orders_prev", new_column_name="order_count_prev")
    op.alter_column("fact_search_query_metric", "search_orders", new_column_name="order_count")
    op.alter_column("fact_search_query_metric", "search_cart_prev", new_column_name="cart_count_prev")
    op.alter_column("fact_search_query_metric", "search_cart", new_column_name="cart_count")
    op.alter_column("fact_search_query_metric", "search_clicks_prev", new_column_name="card_clicks_prev")
    op.alter_column("fact_search_query_metric", "search_clicks", new_column_name="card_clicks")
    op.drop_column("fact_search_query_metric", "query_count_prev")
    op.drop_column("fact_search_query_metric", "reviews_rating")
    op.drop_column("fact_search_query_metric", "card_rating")
    op.drop_column("fact_search_query_metric", "brand")
    op.drop_column("fact_search_query_metric", "subject")
    op.drop_column("fact_search_query_metric", "title")
    op.drop_column("fact_search_query_metric", "supplier_article")
    op.drop_column("fact_search_query_metric", "date")
