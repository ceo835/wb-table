"""add_fact_finance_realization_line

Revision ID: 20260716_0029
Revises: 20260715_0028
Create Date: 2026-07-16 00:00:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260716_0029"
down_revision: Union[str, None] = "20260715_0028"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.create_table(
        "fact_finance_realization_line",
        sa.Column("fact_finance_realization_line_id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("rrd_id", sa.BigInteger(), nullable=False),
        sa.Column("realizationreport_id", sa.BigInteger(), nullable=True),
        sa.Column("operation_date", sa.Date(), nullable=False),
        sa.Column("operation_date_source", sa.String(length=64), nullable=False),
        sa.Column("report_period_from", sa.Date(), nullable=True),
        sa.Column("report_period_to", sa.Date(), nullable=True),
        sa.Column("create_dt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("order_dt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("sale_dt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("rr_dt", sa.DateTime(timezone=True), nullable=True),
        sa.Column("nm_id", sa.BigInteger(), nullable=True),
        sa.Column("sa_name", sa.String(length=255), nullable=True),
        sa.Column("barcode", sa.Text(), nullable=True),
        sa.Column("srid", sa.String(length=255), nullable=True),
        sa.Column("doc_type_name", sa.String(length=255), nullable=True),
        sa.Column("supplier_oper_name", sa.String(length=255), nullable=True),
        sa.Column("quantity", sa.Numeric(18, 4), nullable=True),
        sa.Column("delivery_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("return_amount", sa.Numeric(18, 4), nullable=True),
        sa.Column("delivery_rub", sa.Numeric(18, 2), nullable=True),
        sa.Column("storage_fee", sa.Numeric(18, 2), nullable=True),
        sa.Column("acceptance", sa.Numeric(18, 2), nullable=True),
        sa.Column("rebill_logistic_cost", sa.Numeric(18, 2), nullable=True),
        sa.Column("deduction", sa.Numeric(18, 2), nullable=True),
        sa.Column("penalty", sa.Numeric(18, 2), nullable=True),
        sa.Column("additional_payment", sa.Numeric(18, 2), nullable=True),
        sa.Column("ppvz_for_pay", sa.Numeric(18, 2), nullable=True),
        sa.Column("office_name", sa.String(length=255), nullable=True),
        sa.Column("ppvz_office_name", sa.Text(), nullable=True),
        sa.Column("ppvz_office_id", sa.BigInteger(), nullable=True),
        sa.Column("fix_tariff_date_from", sa.DateTime(timezone=True), nullable=True),
        sa.Column("fix_tariff_date_to", sa.DateTime(timezone=True), nullable=True),
        sa.Column("delivery_method", sa.String(length=255), nullable=True),
        sa.Column("source_endpoint", sa.String(length=255), nullable=False),
        sa.Column("source_row_hash", sa.String(length=64), nullable=False),
        sa.Column("data_status", sa.String(length=64), nullable=True),
        sa.Column("source_status", sa.String(length=128), nullable=True),
        sa.Column("loaded_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("fact_finance_realization_line_id", name=op.f("pk_fact_finance_realization_line")),
        sa.UniqueConstraint("rrd_id", name="uq_fact_finance_realization_line_rrd_id"),
    )
    op.create_index(
        "idx_fact_finance_realization_line_date_nm",
        "fact_finance_realization_line",
        ["operation_date", "nm_id"],
        unique=False,
    )
    op.create_index(
        "idx_fact_finance_realization_line_nm_date",
        "fact_finance_realization_line",
        ["nm_id", "operation_date"],
        unique=False,
    )
    op.create_index(
        "idx_fact_finance_realization_line_office_date",
        "fact_finance_realization_line",
        ["office_name", "operation_date"],
        unique=False,
    )
    op.create_index(
        "idx_fact_finance_realization_line_srid",
        "fact_finance_realization_line",
        ["srid"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("idx_fact_finance_realization_line_srid", table_name="fact_finance_realization_line")
    op.drop_index("idx_fact_finance_realization_line_office_date", table_name="fact_finance_realization_line")
    op.drop_index("idx_fact_finance_realization_line_nm_date", table_name="fact_finance_realization_line")
    op.drop_index("idx_fact_finance_realization_line_date_nm", table_name="fact_finance_realization_line")
    op.drop_table("fact_finance_realization_line")
