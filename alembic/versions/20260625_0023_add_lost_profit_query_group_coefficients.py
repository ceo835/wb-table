"""Add lost profit query group coefficients settings table.

Revision ID: 20260625_0023
Revises: 20260625_0022
Create Date: 2026-06-25 18:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260625_0023"
down_revision = "20260625_0022"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings_lost_profit_query_group_coefficients",
        sa.Column("query_group", sa.Text(), primary_key=True),
        sa.Column("search_to_order_conversion", sa.Numeric(precision=10, scale=6), nullable=True),
        sa.Column("approval_status", sa.String(length=64), nullable=False, server_default="pending_ivan_review"),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )


def downgrade() -> None:
    op.drop_table("settings_lost_profit_query_group_coefficients")
