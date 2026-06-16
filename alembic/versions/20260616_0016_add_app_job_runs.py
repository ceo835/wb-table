"""Add app_job_runs table.

Revision ID: 20260616_0016
Revises: 20260616_0015
Create Date: 2026-06-16 22:20:00
"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260616_0016"
down_revision = "20260616_0015"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "app_job_runs",
        sa.Column("id", sa.BigInteger(), autoincrement=True, nullable=False),
        sa.Column("job_name", sa.String(length=128), nullable=False),
        sa.Column("run_date", sa.Date(), nullable=False),
        sa.Column("started_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("finished_at", sa.DateTime(timezone=True), nullable=True),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column("summary_path", sa.Text(), nullable=True),
        sa.Column("error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), server_default=sa.text("now()"), nullable=False),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("job_name", "run_date", name="uq_app_job_runs_job_name_run_date"),
    )
    op.create_index("idx_app_job_runs_job_date", "app_job_runs", ["job_name", "run_date"], unique=False)
    op.create_index("idx_app_job_runs_status", "app_job_runs", ["status"], unique=False)


def downgrade() -> None:
    op.drop_index("idx_app_job_runs_status", table_name="app_job_runs")
    op.drop_index("idx_app_job_runs_job_date", table_name="app_job_runs")
    op.drop_table("app_job_runs")
