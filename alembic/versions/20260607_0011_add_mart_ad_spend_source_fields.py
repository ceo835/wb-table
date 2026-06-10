"""Add separate mart ad spend source fields.

Revision ID: 20260607_0011
Revises: 20260607_0010
Create Date: 2026-06-07 15:15:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260607_0011"
down_revision = "20260607_0010"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("mart_total_report", sa.Column("ad_cost_writeoff_total", sa.Numeric(precision=18, scale=2), nullable=True))
    op.add_column("mart_total_report", sa.Column("ad_campaign_spend_total", sa.Numeric(precision=18, scale=2), nullable=True))


def downgrade() -> None:
    op.drop_column("mart_total_report", "ad_campaign_spend_total")
    op.drop_column("mart_total_report", "ad_cost_writeoff_total")
