"""create external_context_metric table

Revision ID: 20260721_0031
Revises: 20260721_0030
Create Date: 2026-07-21 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260721_0031"
down_revision = "20260721_0030"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_context_metric",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("metric_code", sa.String(length=128), nullable=False),
        sa.Column("metric_name", sa.String(length=255), nullable=False),
        sa.Column("period_start", sa.Date(), nullable=False),
        sa.Column("period_end", sa.Date(), nullable=False),
        sa.Column("published_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("retrieved_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("region", sa.String(length=128), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("query_text", sa.String(length=255), nullable=True),
        sa.Column("value", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("previous_value", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("change_value", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("change_pct", sa.Numeric(precision=18, scale=4), nullable=True),
        sa.Column("unit", sa.String(length=32), nullable=True),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("data_status", sa.String(length=32), nullable=False, server_default="ok"),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_context_metric")),
        sa.UniqueConstraint(
            "source", "metric_code", "period_start", "period_end", "region", "category", "query_text",
            name="uq_external_context_metric_identity",
        ),
        sa.CheckConstraint("period_end >= period_start", name="ck_external_context_metric_period_order"),
        sa.CheckConstraint("data_status in ('ok', 'partial', 'stale', 'unavailable', 'error')", name="ck_external_context_metric_data_status"),
    )
    op.create_index("idx_external_context_metric_source", "external_context_metric", ["source"])
    op.create_index("idx_external_context_metric_code", "external_context_metric", ["metric_code"])
    op.create_index("idx_external_context_metric_dates", "external_context_metric", ["period_start", "period_end"])
    op.create_index("idx_external_context_metric_category", "external_context_metric", ["category"])
    op.create_index("idx_external_context_metric_region", "external_context_metric", ["region"])
    op.create_index("idx_external_context_metric_status", "external_context_metric", ["data_status"])


def downgrade() -> None:
    op.drop_index("idx_external_context_metric_status", table_name="external_context_metric")
    op.drop_index("idx_external_context_metric_region", table_name="external_context_metric")
    op.drop_index("idx_external_context_metric_category", table_name="external_context_metric")
    op.drop_index("idx_external_context_metric_dates", table_name="external_context_metric")
    op.drop_index("idx_external_context_metric_code", table_name="external_context_metric")
    op.drop_index("idx_external_context_metric_source", table_name="external_context_metric")
    op.drop_table("external_context_metric")
