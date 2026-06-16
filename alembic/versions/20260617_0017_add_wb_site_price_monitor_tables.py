"""Add WB site price monitor tables.

Revision ID: 20260617_0017
Revises: 20260616_0016
Create Date: 2026-06-17 13:30:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260617_0017"
down_revision = "20260616_0016"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fact_wb_site_price_snapshot",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("item_label", sa.String(length=255), nullable=True),
        sa.Column("lifecycle_status", sa.String(length=64), nullable=True),
        sa.Column("product_url", sa.Text(), nullable=True),
        sa.Column("buyer_visible_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("currency", sa.String(length=16), nullable=True),
        sa.Column("price_text_raw", sa.Text(), nullable=True),
        sa.Column("availability_status", sa.String(length=64), nullable=True),
        sa.Column("fetch_status", sa.String(length=64), nullable=False),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("proxy_used", sa.Boolean(), nullable=False, server_default=sa.text("false")),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_date", "nm_id", name="uq_fact_wb_site_price_snapshot_date_nm_id"),
    )
    op.create_index(
        "idx_fact_wb_site_price_snapshot_date_nm",
        "fact_wb_site_price_snapshot",
        ["snapshot_date", "nm_id"],
        unique=False,
    )
    op.create_index(
        "idx_fact_wb_site_price_snapshot_fetch_status",
        "fact_wb_site_price_snapshot",
        ["fetch_status", "snapshot_date"],
        unique=False,
    )

    op.create_table(
        "fact_wb_site_price_alert",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("snapshot_date", sa.Date(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("current_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("previous_success_price", sa.Numeric(18, 2), nullable=True),
        sa.Column("price_delta", sa.Numeric(18, 2), nullable=True),
        sa.Column("alert_status", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("snapshot_date", "nm_id", name="uq_fact_wb_site_price_alert_date_nm_id"),
    )
    op.create_index(
        "idx_fact_wb_site_price_alert_date_nm",
        "fact_wb_site_price_alert",
        ["snapshot_date", "nm_id"],
        unique=False,
    )
    op.create_index(
        "idx_fact_wb_site_price_alert_status",
        "fact_wb_site_price_alert",
        ["alert_status", "snapshot_date"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_fact_wb_site_price_alert_status", table_name="fact_wb_site_price_alert")
    op.drop_index("idx_fact_wb_site_price_alert_date_nm", table_name="fact_wb_site_price_alert")
    op.drop_table("fact_wb_site_price_alert")

    op.drop_index("idx_fact_wb_site_price_snapshot_fetch_status", table_name="fact_wb_site_price_snapshot")
    op.drop_index("idx_fact_wb_site_price_snapshot_date_nm", table_name="fact_wb_site_price_snapshot")
    op.drop_table("fact_wb_site_price_snapshot")
