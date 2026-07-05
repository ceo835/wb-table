"""add_dim_product_size

Revision ID: 20260705_0025
Revises: 48e2045abf80
Create Date: 2026-07-05 22:15:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260705_0025"
down_revision: Union[str, None] = "48e2045abf80"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "dim_product_size",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("nm_id", sa.BigInteger(), nullable=False),
        sa.Column("chrt_id", sa.BigInteger(), nullable=False),
        sa.Column("barcode", sa.Text(), nullable=True),
        sa.Column("size_name", sa.String(length=128), nullable=True),
        sa.Column("tech_size", sa.String(length=128), nullable=True),
        sa.Column("source_status", sa.String(length=128), nullable=True),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id", name=op.f("pk_dim_product_size")),
        sa.UniqueConstraint("nm_id", "chrt_id", "barcode", name="uq_dim_product_size_nm_chrt_barcode"),
    )
    op.create_index("idx_dim_product_size_nm_chrt", "dim_product_size", ["nm_id", "chrt_id"], unique=False)
    op.create_index("idx_dim_product_size_nm_barcode", "dim_product_size", ["nm_id", "barcode"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_dim_product_size_nm_barcode", table_name="dim_product_size")
    op.drop_index("idx_dim_product_size_nm_chrt", table_name="dim_product_size")
    op.drop_table("dim_product_size")
