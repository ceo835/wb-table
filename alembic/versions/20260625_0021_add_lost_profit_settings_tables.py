"""Add lost-profit settings tables.

Revision ID: 20260625_0021
Revises: 20260625_0020
Create Date: 2026-06-25 13:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260625_0021"
down_revision = "20260625_0020"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "settings_lost_profit_market_areas",
        sa.Column("market_area_code", sa.Text(), primary_key=True),
        sa.Column("market_area_name", sa.Text(), nullable=False),
        sa.Column("population_people", sa.Integer(), nullable=False),
        sa.Column("population_share_pct", sa.Numeric(10, 3), nullable=False),
        sa.Column("source", sa.Text(), nullable=True),
        sa.Column(
            "approval_status",
            sa.String(length=64),
            nullable=False,
            server_default="pending_ivan_review",
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
    )
    op.create_table(
        "settings_lost_profit_warehouse_areas",
        sa.Column("warehouse_name", sa.Text(), primary_key=True),
        sa.Column("market_area_code", sa.Text(), nullable=False),
        sa.Column(
            "approval_status",
            sa.String(length=64),
            nullable=False,
            server_default="pending_ivan_review",
        ),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(
            ["market_area_code"],
            ["settings_lost_profit_market_areas.market_area_code"],
            name="fk_settings_lost_profit_warehouse_areas_market_area_code",
        ),
    )
    op.create_index(
        "idx_settings_lost_profit_warehouse_areas_market_area_code",
        "settings_lost_profit_warehouse_areas",
        ["market_area_code"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index(
        "idx_settings_lost_profit_warehouse_areas_market_area_code",
        table_name="settings_lost_profit_warehouse_areas",
    )
    op.drop_table("settings_lost_profit_warehouse_areas")
    op.drop_table("settings_lost_profit_market_areas")
