"""create db layer tables

Revision ID: 20260604_0001
Revises:
Create Date: 2026-06-04 10:00:00
"""

from __future__ import annotations

from alembic import op

from src.db.base import Base
from src.db import models as _models  # noqa: F401


revision = "20260604_0001"
down_revision = None
branch_labels = None
depends_on = None


TABLE_NAMES = [
    "raw_api_response",
    "api_load_log",
    "validation_warning",
    "dim_product",
    "dim_campaign",
    "dim_date",
    "settings_products",
    "settings_report_columns",
    "fact_funnel_day",
    "fact_ad_cost_event",
    "fact_ad_cost_day",
    "fact_ad_campaign_day",
    "fact_ad_campaign_nm_day",
    "fact_search_query_metric",
    "fact_stock_snapshot",
    "fact_localization_region_day",
    "fact_entry_point_day",
    "fact_vbro_manual",
    "fact_card_comparison_metric",
    "mart_total_report",
]


def upgrade() -> None:
    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in TABLE_NAMES]
    Base.metadata.create_all(bind=bind, tables=tables, checkfirst=True)


def downgrade() -> None:
    bind = op.get_bind()
    tables = [Base.metadata.tables[name] for name in reversed(TABLE_NAMES)]
    Base.metadata.drop_all(bind=bind, tables=tables, checkfirst=True)
