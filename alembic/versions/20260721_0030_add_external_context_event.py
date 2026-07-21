"""add external calendar context events

Revision ID: 20260721_0030
Revises: 20260716_0029
Create Date: 2026-07-21 00:00:00.000000
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

revision = "20260721_0030"
down_revision = "20260716_0029"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "external_context_event",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("source", sa.String(length=64), nullable=False),
        sa.Column("event_type", sa.String(length=64), nullable=False),
        sa.Column("event_code", sa.String(length=128), nullable=False),
        sa.Column("title", sa.String(length=255), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("date_start", sa.Date(), nullable=False),
        sa.Column("date_end", sa.Date(), nullable=False),
        sa.Column("region", sa.String(length=128), nullable=True),
        sa.Column("category", sa.String(length=255), nullable=True),
        sa.Column("impact_direction", sa.String(length=16), nullable=False, server_default="neutral"),
        sa.Column("impact_strength", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("confidence", sa.String(length=16), nullable=False, server_default="medium"),
        sa.Column("is_active", sa.Boolean(), nullable=False, server_default=sa.text("true")),
        sa.Column("source_reference", sa.Text(), nullable=True),
        sa.Column("metadata_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.text("now()")),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_external_context_event")),
        sa.UniqueConstraint(
            "source", "event_code", "date_start", "date_end", "region", "category",
            name="uq_external_context_event_identity",
        ),
        sa.CheckConstraint("date_end >= date_start", name="ck_external_context_event_date_order"),
        sa.CheckConstraint("impact_direction in ('positive', 'negative', 'mixed', 'neutral')", name="ck_external_context_event_impact_direction"),
        sa.CheckConstraint("impact_strength in ('low', 'medium', 'high')", name="ck_external_context_event_impact_strength"),
        sa.CheckConstraint("confidence in ('low', 'medium', 'high')", name="ck_external_context_event_confidence"),
    )
    op.create_index("idx_external_context_event_dates", "external_context_event", ["date_start", "date_end"])
    op.create_index("idx_external_context_event_type", "external_context_event", ["event_type"])
    op.create_index("idx_external_context_event_category", "external_context_event", ["category"])
    op.create_index("idx_external_context_event_active", "external_context_event", ["is_active"])


def downgrade() -> None:
    op.drop_index("idx_external_context_event_active", table_name="external_context_event")
    op.drop_index("idx_external_context_event_category", table_name="external_context_event")
    op.drop_index("idx_external_context_event_type", table_name="external_context_event")
    op.drop_index("idx_external_context_event_dates", table_name="external_context_event")
    op.drop_table("external_context_event")
