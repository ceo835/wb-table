"""Add entry point metrics to mart_total_report.

Revision ID: 20260609_0014
Revises: 20260609_0013
Create Date: 2026-06-09 22:25:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260609_0014"
down_revision = "20260609_0013"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mart_total_report", sa.Column("entry_impressions_total", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("entry_card_clicks_total", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("entry_cart_total", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("entry_orders_total", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("entry_ctr_calc", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("entry_cart_conversion_calc", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("mart_total_report", sa.Column("entry_order_conversion_calc", sa.Numeric(precision=18, scale=6), nullable=True))


def downgrade() -> None:
    op.drop_column("mart_total_report", "entry_order_conversion_calc")
    op.drop_column("mart_total_report", "entry_cart_conversion_calc")
    op.drop_column("mart_total_report", "entry_ctr_calc")
    op.drop_column("mart_total_report", "entry_orders_total")
    op.drop_column("mart_total_report", "entry_cart_total")
    op.drop_column("mart_total_report", "entry_card_clicks_total")
    op.drop_column("mart_total_report", "entry_impressions_total")
