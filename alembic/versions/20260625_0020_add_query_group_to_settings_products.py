"""Add query_group to settings_products.

Revision ID: 20260625_0020
Revises: 20260619_0019
Create Date: 2026-06-25 12:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260625_0020"
down_revision = "20260619_0019"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("settings_products", sa.Column("query_group", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("settings_products", "query_group")
