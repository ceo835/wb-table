"""Add advert metadata and fullstats retry queue tables.

Revision ID: 20260617_0018
Revises: 20260617_0017
Create Date: 2026-06-17 20:10:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql


revision = "20260617_0018"
down_revision = "20260617_0017"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "fact_advert_metadata",
        sa.Column("fact_advert_metadata_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("advert_id", sa.BigInteger(), nullable=False),
        sa.Column("campaign_name", sa.Text(), nullable=True),
        sa.Column("status", sa.String(length=64), nullable=True),
        sa.Column("payment_type", sa.String(length=64), nullable=True),
        sa.Column("primary_nm_id", sa.BigInteger(), nullable=True),
        sa.Column("linked_nm_ids_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("placements_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("raw_payload_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("source_status", sa.String(length=128), nullable=True),
        sa.Column("loaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("fact_advert_metadata_id"),
        sa.UniqueConstraint("advert_id", name="uq_fact_advert_metadata_advert_id"),
    )
    op.create_index(
        "idx_fact_advert_metadata_advert_id",
        "fact_advert_metadata",
        ["advert_id"],
        unique=False,
    )
    op.create_index(
        "idx_fact_advert_metadata_status",
        "fact_advert_metadata",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_fact_advert_metadata_primary_nm_id",
        "fact_advert_metadata",
        ["primary_nm_id"],
        unique=False,
    )

    op.create_table(
        "ad_fullstats_failed_group",
        sa.Column("ad_fullstats_failed_group_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("date_from", sa.Date(), nullable=False),
        sa.Column("date_to", sa.Date(), nullable=False),
        sa.Column("advert_id", sa.BigInteger(), nullable=False),
        sa.Column("group_key", sa.String(length=255), nullable=False),
        sa.Column("campaign_name", sa.Text(), nullable=True),
        sa.Column("nm_ids_json", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("error_type", sa.String(length=64), nullable=True),
        sa.Column("attempts_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_attempt_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("next_retry_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), server_default="pending", nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("ad_fullstats_failed_group_id"),
        sa.UniqueConstraint(
            "date_from",
            "date_to",
            "advert_id",
            "group_key",
            name="uq_ad_fullstats_failed_group_scope",
        ),
    )
    op.create_index(
        "idx_ad_fullstats_failed_group_advert_id",
        "ad_fullstats_failed_group",
        ["advert_id"],
        unique=False,
    )
    op.create_index(
        "idx_ad_fullstats_failed_group_date_range",
        "ad_fullstats_failed_group",
        ["date_from", "date_to"],
        unique=False,
    )
    op.create_index(
        "idx_ad_fullstats_failed_group_status",
        "ad_fullstats_failed_group",
        ["status"],
        unique=False,
    )
    op.create_index(
        "idx_ad_fullstats_failed_group_next_retry_at",
        "ad_fullstats_failed_group",
        ["next_retry_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_ad_fullstats_failed_group_next_retry_at", table_name="ad_fullstats_failed_group")
    op.drop_index("idx_ad_fullstats_failed_group_status", table_name="ad_fullstats_failed_group")
    op.drop_index("idx_ad_fullstats_failed_group_date_range", table_name="ad_fullstats_failed_group")
    op.drop_index("idx_ad_fullstats_failed_group_advert_id", table_name="ad_fullstats_failed_group")
    op.drop_table("ad_fullstats_failed_group")

    op.drop_index("idx_fact_advert_metadata_primary_nm_id", table_name="fact_advert_metadata")
    op.drop_index("idx_fact_advert_metadata_status", table_name="fact_advert_metadata")
    op.drop_index("idx_fact_advert_metadata_advert_id", table_name="fact_advert_metadata")
    op.drop_table("fact_advert_metadata")
