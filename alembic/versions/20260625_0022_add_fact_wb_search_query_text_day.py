"""Add fact_wb_search_query_text_day.

Revision ID: 20260625_0022
Revises: 20260625_0021
Create Date: 2026-06-25 18:00:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260625_0022"
down_revision = "20260625_0021"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fact_wb_search_query_text_day",
        sa.Column("fact_wb_search_query_text_day_id", sa.BigInteger(), primary_key=True, autoincrement=True),
        sa.Column("day", sa.Date(), nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("query_text", sa.Text(), nullable=False),
        sa.Column("query_group", sa.String(length=64), nullable=True),
        sa.Column("frequency_current", sa.Integer(), nullable=True),
        sa.Column("week_frequency", sa.Integer(), nullable=True),
        sa.Column("orders_current", sa.Integer(), nullable=True),
        sa.Column("visibility_current", sa.Numeric(18, 6), nullable=True),
        sa.Column("avg_position_current", sa.Numeric(18, 6), nullable=True),
        sa.Column("open_card_current", sa.Integer(), nullable=True),
        sa.Column("add_to_cart_current", sa.Integer(), nullable=True),
        sa.Column("source", sa.String(length=64), nullable=False, server_default="wb_search_texts_api"),
        sa.Column("loaded_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.UniqueConstraint("day", "nm_id", "query_text", name="uq_fact_wb_search_query_text_day_day_nm_query_text"),
    )
    op.create_index(
        "idx_fact_wb_search_query_text_day_day_nm",
        "fact_wb_search_query_text_day",
        ["day", "nm_id"],
        unique=False,
    )
    op.create_index(
        "idx_fact_wb_search_query_text_day_query_group",
        "fact_wb_search_query_text_day",
        ["query_group", "day"],
        unique=False,
    )
    op.create_index(
        "idx_fact_wb_search_query_text_day_source",
        "fact_wb_search_query_text_day",
        ["source", "day"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_fact_wb_search_query_text_day_source", table_name="fact_wb_search_query_text_day")
    op.drop_index("idx_fact_wb_search_query_text_day_query_group", table_name="fact_wb_search_query_text_day")
    op.drop_index("idx_fact_wb_search_query_text_day_day_nm", table_name="fact_wb_search_query_text_day")
    op.drop_table("fact_wb_search_query_text_day")
