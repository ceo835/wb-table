"""Add google_drive_source_files table.

Revision ID: 20260715_0028
Revises: 20260711_0027
Create Date: 2026-07-15 15:10:00
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260715_0028"
down_revision = "20260711_0027"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "google_drive_source_files",
        sa.Column("id", sa.BigInteger(), nullable=False),
        sa.Column("source_type", sa.String(length=64), nullable=False),
        sa.Column("google_file_id", sa.String(length=255), nullable=False),
        sa.Column("google_file_name", sa.Text(), nullable=False),
        sa.Column("google_modified_time", sa.DateTime(timezone=True), nullable=True),
        sa.Column("file_size", sa.BigInteger(), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("processing_status", sa.String(length=64), nullable=True),
        sa.Column("processed_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rows_loaded", sa.Integer(), nullable=True),
        sa.Column("error_text", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False, server_default=sa.func.now()),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_google_drive_source_files")),
        sa.UniqueConstraint("source_type", "google_file_id", name="uq_google_drive_source_files_source_file"),
    )
    op.create_index(
        "idx_google_drive_source_files_source_status",
        "google_drive_source_files",
        ["source_type", "processing_status"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_google_drive_source_files_source_status", table_name="google_drive_source_files")
    op.drop_table("google_drive_source_files")
