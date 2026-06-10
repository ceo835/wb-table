"""align fact_localization_region_day for period-level region-sale source

Revision ID: 20260605_0006
Revises: 20260605_0005
Create Date: 2026-06-05 13:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260605_0006"
down_revision = "20260605_0005"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.drop_index("idx_fact_localization_region_day_region_date", table_name="fact_localization_region_day")
    op.drop_index("idx_fact_localization_region_day_date_nm_region", table_name="fact_localization_region_day")
    op.drop_constraint("uq_fact_localization_region_day_natural_key", "fact_localization_region_day", type_="unique")

    op.add_column("fact_localization_region_day", sa.Column("period_start", sa.Date(), nullable=True))
    op.add_column("fact_localization_region_day", sa.Column("period_end", sa.Date(), nullable=True))
    op.add_column("fact_localization_region_day", sa.Column("city", sa.String(length=255), nullable=True))
    op.add_column("fact_localization_region_day", sa.Column("orders_local_qty", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("fact_localization_region_day", sa.Column("orders_nonlocal_qty", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("fact_localization_region_day", sa.Column("orders_nonlocal_percent", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("fact_localization_region_day", sa.Column("wb_stock_orders_local_qty", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("fact_localization_region_day", sa.Column("wb_stock_orders_nonlocal_qty", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("fact_localization_region_day", sa.Column("wb_stock_orders_nonlocal_percent", sa.Numeric(precision=18, scale=6), nullable=True))
    op.add_column("fact_localization_region_day", sa.Column("mp_orders_local_qty", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("fact_localization_region_day", sa.Column("mp_orders_nonlocal_qty", sa.Numeric(precision=18, scale=4), nullable=True))
    op.add_column("fact_localization_region_day", sa.Column("mp_orders_nonlocal_percent", sa.Numeric(precision=18, scale=6), nullable=True))

    op.execute("UPDATE fact_localization_region_day SET period_start = date, period_end = date WHERE period_start IS NULL OR period_end IS NULL")
    op.alter_column("fact_localization_region_day", "period_start", nullable=False)
    op.alter_column("fact_localization_region_day", "period_end", nullable=False)

    op.create_unique_constraint(
        "uq_fact_localization_region_day_natural_key",
        "fact_localization_region_day",
        ["period_start", "period_end", "nm_id", "region"],
    )
    op.create_index(
        "idx_fact_localization_region_day_period_nm_region",
        "fact_localization_region_day",
        ["period_start", "period_end", "nm_id", "region"],
    )
    op.create_index(
        "idx_fact_localization_region_day_region_period",
        "fact_localization_region_day",
        ["region", "period_start", "period_end"],
    )


def downgrade() -> None:
    op.drop_index("idx_fact_localization_region_day_region_period", table_name="fact_localization_region_day")
    op.drop_index("idx_fact_localization_region_day_period_nm_region", table_name="fact_localization_region_day")
    op.drop_constraint("uq_fact_localization_region_day_natural_key", "fact_localization_region_day", type_="unique")

    op.drop_column("fact_localization_region_day", "mp_orders_nonlocal_percent")
    op.drop_column("fact_localization_region_day", "mp_orders_nonlocal_qty")
    op.drop_column("fact_localization_region_day", "mp_orders_local_qty")
    op.drop_column("fact_localization_region_day", "wb_stock_orders_nonlocal_percent")
    op.drop_column("fact_localization_region_day", "wb_stock_orders_nonlocal_qty")
    op.drop_column("fact_localization_region_day", "wb_stock_orders_local_qty")
    op.drop_column("fact_localization_region_day", "orders_nonlocal_percent")
    op.drop_column("fact_localization_region_day", "orders_nonlocal_qty")
    op.drop_column("fact_localization_region_day", "orders_local_qty")
    op.drop_column("fact_localization_region_day", "city")
    op.drop_column("fact_localization_region_day", "period_end")
    op.drop_column("fact_localization_region_day", "period_start")

    op.create_unique_constraint(
        "uq_fact_localization_region_day_natural_key",
        "fact_localization_region_day",
        ["date", "nm_id", "region"],
    )
    op.create_index(
        "idx_fact_localization_region_day_date_nm_region",
        "fact_localization_region_day",
        ["date", "nm_id", "region"],
    )
    op.create_index(
        "idx_fact_localization_region_day_region_date",
        "fact_localization_region_day",
        ["region", "date"],
    )
