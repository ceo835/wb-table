from __future__ import annotations

from pathlib import Path

import pytest
from sqlalchemy import UniqueConstraint

from src.db.base import Base
from src.db.connection import (
    ensure_safe_database_environment,
    get_database_url,
    mask_database_url,
    normalize_database_url,
)
from src.db.models import (
    ApiLoadLog,
    DimCampaign,
    DimDate,
    DimProduct,
    FactAdCampaignDay,
    FactAdCampaignNmDay,
    FactAdCostDay,
    FactAdCostEvent,
    FactCardComparisonMetric,
    FactEntryPointDay,
    FactFunnelDay,
    FactIvanAdsWideDay,
    FactLocalizationRegionDay,
    FactSearchQueryMetric,
    FactStockSnapshot,
    FactWbSearchQueryTextDay,
    FactVbroManual,
    MartTotalReport,
    RawApiResponse,
    SettingsLostProfitMarketArea,
    SettingsLostProfitWarehouseArea,
    SettingsProducts,
    SettingsReportColumns,
    ValidationWarning,
)


PROJECT_ROOT = Path(__file__).resolve().parent.parent


def test_db_models_import():
    assert RawApiResponse.__tablename__ == "raw_api_response"
    assert MartTotalReport.__tablename__ == "mart_total_report"
    assert SettingsLostProfitMarketArea.__tablename__ == "settings_lost_profit_market_areas"
    assert SettingsLostProfitWarehouseArea.__tablename__ == "settings_lost_profit_warehouse_areas"


def test_db_metadata_contains_expected_tables():
    expected_tables = {
        "raw_api_response",
        "api_load_log",
        "validation_warning",
        "dim_product",
        "dim_campaign",
        "dim_date",
        "settings_products",
        "settings_report_columns",
        "settings_lost_profit_market_areas",
        "settings_lost_profit_warehouse_areas",
        "fact_funnel_day",
        "fact_ad_cost_event",
        "fact_ad_cost_day",
        "fact_ad_campaign_day",
        "fact_ad_campaign_nm_day",
        "fact_search_query_metric",
        "fact_wb_search_query_text_day",
        "fact_stock_snapshot",
        "fact_localization_region_day",
        "fact_entry_point_day",
        "fact_vbro_manual",
        "fact_ivan_ads_wide_day",
        "fact_card_comparison_metric",
        "mart_total_report",
    }
    assert expected_tables.issubset(set(Base.metadata.tables))


def _unique_constraint_columns(model) -> set[tuple[str, ...]]:
    return {
        tuple(constraint.columns.keys())
        for constraint in model.__table__.constraints
        if isinstance(constraint, UniqueConstraint)
    }


def test_natural_unique_constraints_exist():
    assert ("date", "nm_id") in _unique_constraint_columns(FactFunnelDay)
    assert ("date", "advert_id", "document_number", "writeoff_datetime", "spend") in _unique_constraint_columns(FactAdCostEvent)
    assert ("period_start", "period_end", "nm_id", "search_query") in _unique_constraint_columns(FactSearchQueryMetric)
    assert ("day", "nm_id", "query_text") in _unique_constraint_columns(FactWbSearchQueryTextDay)
    assert ("snapshot_date", "nm_id") in _unique_constraint_columns(FactStockSnapshot)
    assert ("period_start", "period_end", "nm_id", "region") in _unique_constraint_columns(FactLocalizationRegionDay)
    assert ("date", "nm_id", "campaign_ref") in _unique_constraint_columns(FactIvanAdsWideDay)
    assert ("report_date", "nm_id") in _unique_constraint_columns(MartTotalReport)


def test_metadata_includes_requested_dimension_and_fact_models():
    models = {
        DimProduct,
        DimCampaign,
        DimDate,
        SettingsProducts,
        SettingsReportColumns,
        SettingsLostProfitMarketArea,
        SettingsLostProfitWarehouseArea,
        FactAdCostDay,
        FactAdCampaignDay,
        FactAdCampaignNmDay,
        FactEntryPointDay,
        FactCardComparisonMetric,
        FactIvanAdsWideDay,
        FactWbSearchQueryTextDay,
        FactVbroManual,
        ValidationWarning,
        ApiLoadLog,
    }
    assert all(model.__table__.name in Base.metadata.tables for model in models)


def test_file_import_models_contain_expected_columns():
    localization_columns = set(FactLocalizationRegionDay.__table__.columns.keys())
    assert "delivery_time_text" in localization_columns

    entry_point_columns = set(FactEntryPointDay.__table__.columns.keys())
    assert {
        "supplier_article",
        "title",
        "subject",
        "brand",
        "impressions",
        "card_clicks",
        "ctr",
        "cart_count",
        "add_to_cart_conversion",
        "order_count",
        "order_conversion",
        "source_file_name",
    }.issubset(entry_point_columns)

    mart_columns = set(MartTotalReport.__table__.columns.keys())
    assert {
        "entry_impressions_total",
        "entry_card_clicks_total",
        "entry_cart_total",
        "entry_orders_total",
        "entry_ctr_calc",
        "entry_cart_conversion_calc",
        "entry_order_conversion_calc",
    }.issubset(mart_columns)


def test_settings_products_contains_discovery_fields():
    column_names = set(SettingsProducts.__table__.columns.keys())
    assert {
        "nm_id",
        "supplier_article",
        "title",
        "subject",
        "brand",
        "active",
        "is_new",
        "report_mode",
        "group_name",
        "query_group",
        "item_type",
        "source_list",
        "first_seen_at",
        "last_seen_at",
        "comment",
        "loaded_at",
    }.issubset(column_names)


def test_database_url_not_required_for_regular_imports():
    assert get_database_url(required=False) in {None, "", get_database_url(required=False)}


def test_prod_database_guard_blocks_by_default():
    with pytest.raises(RuntimeError):
        ensure_safe_database_environment(explicit_env="prod", allow_prod_db=False)


def test_prod_database_guard_can_be_explicitly_overridden():
    ensure_safe_database_environment(explicit_env="prod", allow_prod_db=True)


def test_mask_database_url_hides_password():
    masked = mask_database_url("postgresql://user:supersecret@localhost:5432/wb_table")
    assert masked == "postgresql://user:***@localhost:5432/wb_table"


def test_normalize_database_url_uses_psycopg_driver_for_plain_postgresql_urls():
    normalized = normalize_database_url("postgresql://user:secret@localhost:5432/wb_table")
    assert normalized == "postgresql+psycopg://user:secret@localhost:5432/wb_table"


def test_normalize_database_url_keeps_explicit_driver():
    normalized = normalize_database_url("postgresql+psycopg://user:secret@localhost:5432/wb_table")
    assert normalized == "postgresql+psycopg://user:secret@localhost:5432/wb_table"


def test_db_support_files_exist():
    expected_files = [
        PROJECT_ROOT / "alembic.ini",
        PROJECT_ROOT / "alembic" / "env.py",
        PROJECT_ROOT / "docs" / "DB_SETUP.md",
        PROJECT_ROOT / "scripts" / "db_healthcheck.py",
        PROJECT_ROOT / "scripts" / "db_test_connection.py",
        PROJECT_ROOT / "scripts" / "db_upgrade.py",
    ]
    for file_path in expected_files:
        assert file_path.exists(), f"Missing expected DB support file: {file_path}"


def test_initial_alembic_migration_exists():
    versions_dir = PROJECT_ROOT / "alembic" / "versions"
    migration_files = list(versions_dir.glob("*.py"))
    assert migration_files, "Expected at least one Alembic migration file"
