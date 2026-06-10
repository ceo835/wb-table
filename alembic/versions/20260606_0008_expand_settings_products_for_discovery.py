"""expand settings_products for product discovery

Revision ID: 20260606_0008
Revises: 20260605_0007
Create Date: 2026-06-06 10:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260606_0008"
down_revision = "20260605_0007"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("settings_products", sa.Column("title", sa.Text(), nullable=True))
    op.add_column("settings_products", sa.Column("subject", sa.String(length=255), nullable=True))
    op.add_column("settings_products", sa.Column("brand", sa.String(length=255), nullable=True))
    op.add_column("settings_products", sa.Column("is_new", sa.Boolean(), nullable=False, server_default=sa.text("false")))
    op.add_column("settings_products", sa.Column("report_mode", sa.String(length=32), nullable=False, server_default=sa.text("'main'")))
    op.add_column("settings_products", sa.Column("source_list", sa.Text(), nullable=True))
    op.add_column("settings_products", sa.Column("first_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.add_column("settings_products", sa.Column("last_seen_at", sa.DateTime(timezone=True), nullable=True))
    op.create_index("idx_settings_products_report_mode", "settings_products", ["report_mode"])
    op.alter_column("settings_products", "is_new", server_default=None)
    op.alter_column("settings_products", "report_mode", server_default=None)


def downgrade() -> None:
    op.drop_index("idx_settings_products_report_mode", table_name="settings_products")
    op.drop_column("settings_products", "last_seen_at")
    op.drop_column("settings_products", "first_seen_at")
    op.drop_column("settings_products", "source_list")
    op.drop_column("settings_products", "report_mode")
    op.drop_column("settings_products", "is_new")
    op.drop_column("settings_products", "brand")
    op.drop_column("settings_products", "subject")
    op.drop_column("settings_products", "title")
