"""Add confirmed itogo formula fields to mart_total_report.

Revision ID: 20260609_0013
Revises: 20260609_0012
Create Date: 2026-06-09 16:55:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260609_0013"
down_revision = "20260609_0012"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mart_total_report", sa.Column("organic_cart_count", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_cost_per_all_carts_calc", sa.Numeric(precision=18, scale=6), nullable=True))


def downgrade() -> None:
    op.drop_column("mart_total_report", "ad_cost_per_all_carts_calc")
    op.drop_column("mart_total_report", "organic_cart_count")
