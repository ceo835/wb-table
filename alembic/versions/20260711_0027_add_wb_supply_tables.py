"""add_wb_supply_tables

Revision ID: 20260711_0027
Revises: 7c9c393f8861
Create Date: 2026-07-11 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa
from sqlalchemy.dialects import postgresql

# revision identifiers, used by Alembic.
revision: str = "20260711_0027"
down_revision: Union[str, None] = "7c9c393f8861"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "wb_supply_source_files",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("google_file_id", sa.String(length=255), nullable=False),
        sa.Column("google_file_name", sa.Text(), nullable=False),
        sa.Column("google_modified_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("detected_warehouse", sa.String(length=255), nullable=True),
        sa.Column("raw_rows_count", sa.Integer(), nullable=True),
        sa.Column("parsed_rows_count", sa.Integer(), nullable=True),
        sa.Column("last_synced_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("last_status", sa.String(length=64), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wb_supply_source_files")),
        sa.UniqueConstraint("google_file_id", name="uq_wb_supply_source_files_google_file_id"),
    )

    op.create_table(
        "wb_supply_rows",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("google_file_id", sa.String(length=255), nullable=False),
        sa.Column("google_file_name", sa.Text(), nullable=False),
        sa.Column("sheet_name", sa.Text(), nullable=False),
        sa.Column("row_number", sa.Integer(), nullable=False),
        sa.Column("warehouse_name", sa.String(length=255), nullable=True),
        sa.Column("nm_id", sa.BigInteger(), nullable=True),
        sa.Column("barcode", sa.Text(), nullable=True),
        sa.Column("vendor_code", sa.String(length=255), nullable=True),
        sa.Column("product_name", sa.Text(), nullable=True),
        sa.Column("supply_quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("comment", sa.Text(), nullable=True),
        sa.Column("raw_payload", postgresql.JSONB(astext_type=sa.Text()), nullable=True),
        sa.Column("row_hash", sa.String(length=64), nullable=False),
        sa.Column("synced_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_wb_supply_rows")),
        sa.UniqueConstraint("google_file_id", "sheet_name", "row_number", name="uq_wb_supply_rows_file_sheet_row"),
    )
    op.create_index("idx_wb_supply_rows_nm_id", "wb_supply_rows", ["nm_id"], unique=False)
    op.create_index("idx_wb_supply_rows_barcode", "wb_supply_rows", ["barcode"], unique=False)
    op.create_index("idx_wb_supply_rows_vendor_code", "wb_supply_rows", ["vendor_code"], unique=False)
    op.create_index("idx_wb_supply_rows_file", "wb_supply_rows", ["google_file_id"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_wb_supply_rows_file", table_name="wb_supply_rows")
    op.drop_index("idx_wb_supply_rows_vendor_code", table_name="wb_supply_rows")
    op.drop_index("idx_wb_supply_rows_barcode", table_name="wb_supply_rows")
    op.drop_index("idx_wb_supply_rows_nm_id", table_name="wb_supply_rows")
    op.drop_table("wb_supply_rows")
    op.drop_table("wb_supply_source_files")
