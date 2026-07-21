"""add persistent Wordstat display state

Revision ID: 20260722_0032
Revises: 20260721_0031
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260722_0032"
down_revision = "20260721_0031"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_context_wordstat_display",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("wordstat_release_key", sa.String(length=128), nullable=False),
        sa.Column("metric_code", sa.String(length=128), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("first_shown_report_date", sa.Date(), nullable=False),
        sa.Column("last_shown_report_date", sa.Date(), nullable=False),
        sa.Column("last_wb_change_pct", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("last_wb_direction", sa.String(length=16), nullable=True),
        sa.Column("last_comparison_direction", sa.String(length=64), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_context_wordstat_display")),
        sa.UniqueConstraint("wordstat_release_key", name="uq_external_context_wordstat_display_release"),
    )
    op.create_index(
        "idx_external_context_wordstat_display_last_shown",
        "external_context_wordstat_display",
        ["last_shown_report_date"],
    )


def downgrade() -> None:
    op.drop_index("idx_external_context_wordstat_display_last_shown", table_name="external_context_wordstat_display")
    op.drop_table("external_context_wordstat_display")