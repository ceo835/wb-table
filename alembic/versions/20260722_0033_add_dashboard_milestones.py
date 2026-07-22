"""add dashboard_milestones table

Revision ID: 20260722_0033
Revises: 20260722_0032
Create Date: 2026-07-22 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260722_0033"
down_revision = "20260722_0032"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "dashboard_milestones",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("milestone_date", sa.Date(), nullable=False),
        sa.Column("milestone_type", sa.String(length=64), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dashboard_milestones")),
    )
    op.create_index("idx_dashboard_milestones_date", "dashboard_milestones", ["milestone_date"])
    op.create_index("idx_dashboard_milestones_active_date", "dashboard_milestones", ["is_active", "milestone_date"])


def downgrade() -> None:
    op.drop_index("idx_dashboard_milestones_active_date", table_name="dashboard_milestones")
    op.drop_index("idx_dashboard_milestones_date", table_name="dashboard_milestones")
    op.drop_table("dashboard_milestones")
