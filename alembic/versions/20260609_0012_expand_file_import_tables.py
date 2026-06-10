"""Expand file import tables for WB xlsx imports.

Revision ID: 20260609_0012
Revises: 20260607_0011
Create Date: 2026-06-09 14:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260609_0012"
down_revision = "20260607_0011"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fact_localization_region_day", sa.Column("delivery_time_text", sa.String(length=255), nullable=True))

    op.add_column("fact_entry_point_day", sa.Column("supplier_article", sa.String(length=255), nullable=True))
    op.add_column("fact_entry_point_day", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("fact_entry_point_day", sa.Column("subject", sa.String(length=255), nullable=True))
    op.add_column("fact_entry_point_day", sa.Column("brand", sa.String(length=255), nullable=True))
    op.add_column("fact_entry_point_day", sa.Column("impressions", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("fact_entry_point_day", sa.Column("card_clicks", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("fact_entry_point_day", sa.Column("ctr", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("fact_entry_point_day", sa.Column("cart_count", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("fact_entry_point_day", sa.Column("add_to_cart_conversion", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("fact_entry_point_day", sa.Column("order_count", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("fact_entry_point_day", sa.Column("order_conversion", sa.Numeric(precision=18, scale=6), nullable=True))
    op.alter_column("fact_entry_point_day", "date", existing_type=sa.Date(), nullable=False)


def downgrade() -> None:
    op.alter_column("fact_entry_point_day", "date", existing_type=sa.Date(), nullable=True)
    op.drop_column("fact_entry_point_day", "order_conversion")
    op.drop_column("fact_entry_point_day", "order_count")
    op.drop_column("fact_entry_point_day", "add_to_cart_conversion")
    op.drop_column("fact_entry_point_day", "cart_count")
    op.drop_column("fact_entry_point_day", "ctr")
    op.drop_column("fact_entry_point_day", "card_clicks")
    op.drop_column("fact_entry_point_day", "impressions")
    op.drop_column("fact_entry_point_day", "brand")
    op.drop_column("fact_entry_point_day", "subject")
    op.drop_column("fact_entry_point_day", "title")
    op.drop_column("fact_entry_point_day", "supplier_article")
    op.drop_column("fact_localization_region_day", "delivery_time_text")
