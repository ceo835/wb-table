"""align ad cost table columns with loaders

Revision ID: 20260604_0003
Revises: 20260604_0002
Create Date: 2026-06-04 13:00:00
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op


revision = "20260604_0003"
down_revision = "20260604_0002"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.alter_column("fact_ad_cost_event", "source_name", new_column_name="writeoff_source")
    op.alter_column("fact_ad_cost_event", "amount", new_column_name="spend")
    op.add_column("fact_ad_cost_event", sa.Column("nm_id_from_section", sa.BigInteger(), nullable=True))
    op.add_column("fact_ad_cost_event", sa.Column("nm_id_from_campaign_name", sa.BigInteger(), nullable=True))
    op.add_column("fact_ad_cost_event", sa.Column("currency", sa.String(length=16), nullable=True))

    op.drop_constraint("uq_fact_ad_cost_event_natural_key", "fact_ad_cost_event", type_="unique")
    op.create_unique_constraint(
        "uq_fact_ad_cost_event_natural_key",
        "fact_ad_cost_event",
        ["date", "advert_id", "document_number", "writeoff_datetime", "spend"],
    )

    op.alter_column("fact_ad_cost_day", "ad_spend", new_column_name="total_spend")
    op.alter_column("fact_ad_cost_day", "writeoff_count", new_column_name="events_count")
    op.add_column("fact_ad_cost_day", sa.Column("allocation_status", sa.String(length=64), nullable=True))


def downgrade() -> None:
    op.drop_column("fact_ad_cost_day", "allocation_status")
    op.alter_column("fact_ad_cost_day", "events_count", new_column_name="writeoff_count")
    op.alter_column("fact_ad_cost_day", "total_spend", new_column_name="ad_spend")

    op.drop_constraint("uq_fact_ad_cost_event_natural_key", "fact_ad_cost_event", type_="unique")
    op.create_unique_constraint(
        "uq_fact_ad_cost_event_natural_key",
        "fact_ad_cost_event",
        ["date", "advert_id", "document_number", "writeoff_datetime"],
    )

    op.drop_column("fact_ad_cost_event", "currency")
    op.drop_column("fact_ad_cost_event", "nm_id_from_campaign_name")
    op.drop_column("fact_ad_cost_event", "nm_id_from_section")
    op.alter_column("fact_ad_cost_event", "spend", new_column_name="amount")
    op.alter_column("fact_ad_cost_event", "writeoff_source", new_column_name="source_name")
