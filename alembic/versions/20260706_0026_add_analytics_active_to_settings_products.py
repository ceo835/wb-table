"""add_analytics_active_to_settings_products

Revision ID: 20260706_0026
Revises: 31b39255d27e
Create Date: 2026-07-06 12:20:00.000000

"""
from __future__ import annotations

from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "20260706_0026"
down_revision: Union[str, None] = "31b39255d27e"
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    op.add_column(
        "settings_products",
        sa.Column(
            "analytics_active",
            sa.Boolean(),
            nullable=False,
            server_default=sa.false(),
        ),
    )
    op.create_index(
        "idx_settings_products_analytics_active",
        "settings_products",
        ["analytics_active"],
        unique=False,
    )
    op.alter_column("settings_products", "analytics_active", server_default=None)


def downgrade() -> None:
    op.drop_index("idx_settings_products_analytics_active", table_name="settings_products")
    op.drop_column("settings_products", "analytics_active")
