"""Add fact_stock_warehouse_snapshot table.

Revision ID: 20260616_0015
Revises: 20260609_0014
Create Date: 2026-06-16 17:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260616_0015"
down_revision = "20260609_0014"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fact_stock_warehouse_snapshot",
        sa.Column("fact_stock_warehouse_snapshot_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("chrt_id", sa.BigInteger(), nullable=False),
        sa.Column("warehouse_id", sa.BigInteger(), nullable=False),
        sa.Column("warehouse_name", sa.String(length=255), nullable=True),
        sa.Column("region_name", sa.String(length=255), nullable=True),
        sa.Column("stock_qty", sa.Integer(), nullable=True),
        sa.Column("in_way_to_client", sa.Integer(), nullable=True),
        sa.Column("in_way_from_client", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=128), nullable=False),
        sa.Column("loaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("fact_stock_warehouse_snapshot_id"),
        sa.UniqueConstraint(
            "snapshot_date",
            "nm_id",
            "chrt_id",
            "warehouse_id",
            name="uq_fact_stock_warehouse_snapshot_natural_key",
        ),
    )
    op.create_index(
        "idx_fact_stock_warehouse_snapshot_date_nm",
        "fact_stock_warehouse_snapshot",
        ["snapshot_date", "nm_id"],
        unique=False,
    )
    op.create_index(
        "idx_fact_stock_warehouse_snapshot_nm_warehouse",
        "fact_stock_warehouse_snapshot",
        ["nm_id", "warehouse_id"],
        unique=False,
    )
    op.create_index(
        "idx_fact_stock_warehouse_snapshot_warehouse",
        "fact_stock_warehouse_snapshot",
        ["warehouse_name", "snapshot_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_fact_stock_warehouse_snapshot_warehouse", table_name="fact_stock_warehouse_snapshot")
    op.drop_index("idx_fact_stock_warehouse_snapshot_nm_warehouse", table_name="fact_stock_warehouse_snapshot")
    op.drop_index("idx_fact_stock_warehouse_snapshot_date_nm", table_name="fact_stock_warehouse_snapshot")
    op.drop_table("fact_stock_warehouse_snapshot")
