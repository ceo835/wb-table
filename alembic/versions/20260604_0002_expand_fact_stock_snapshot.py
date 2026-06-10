"""expand fact_stock_snapshot columns

Revision ID: 20260604_0002
Revises: 20260604_0001
Create Date: 2026-06-04 12:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260604_0002"
down_revision = "20260604_0001"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("fact_stock_snapshot", sa.Column("supplier_article", sa.String(length=255), nullable=True))
    op.add_column("fact_stock_snapshot", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("fact_stock_snapshot", sa.Column("subject", sa.String(length=255), nullable=True))
    op.add_column("fact_stock_snapshot", sa.Column("brand", sa.String(length=255), nullable=True))
    op.add_column("fact_stock_snapshot", sa.Column("stock_total_qty", sa.Numeric(18, 4), nullable=True))
    op.add_column("fact_stock_snapshot", sa.Column("sale_rate", sa.Numeric(18, 6), nullable=True))
    op.add_column("fact_stock_snapshot", sa.Column("to_client_count", sa.Numeric(18, 4), nullable=True))
    op.add_column("fact_stock_snapshot", sa.Column("from_client_count", sa.Numeric(18, 4), nullable=True))
    op.add_column("fact_stock_snapshot", sa.Column("availability", sa.Numeric(18, 6), nullable=True))


def downgrade() -> None:
    op.drop_column("fact_stock_snapshot", "availability")
    op.drop_column("fact_stock_snapshot", "from_client_count")
    op.drop_column("fact_stock_snapshot", "to_client_count")
    op.drop_column("fact_stock_snapshot", "sale_rate")
    op.drop_column("fact_stock_snapshot", "stock_total_qty")
    op.drop_column("fact_stock_snapshot", "brand")
    op.drop_column("fact_stock_snapshot", "subject")
    op.drop_column("fact_stock_snapshot", "title")
    op.drop_column("fact_stock_snapshot", "supplier_article")
