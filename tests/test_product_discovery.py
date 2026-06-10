from __future__ import annotations

from datetime import datetime, timezone

from src.db.models import SettingsProducts
from src.db.product_discovery import (
    _catalog_to_rows,
    _compute_quality_status,
    _header_matches,
    _merge_observations,
    _sanitize_observation,
    build_settings_products_upsert_rows,
)


def test_header_matches_normalizes_underscore_and_case():
    assert _header_matches("Артикул WB", ("артикулwb",))
    assert _header_matches("Артикул ВБ", ("артикулвб",))
    assert _header_matches("nm_id", ("nmid",))


def test_sanitize_observation_filters_fake_markers():
    fake = _sanitize_observation(
        {
            "nm_id": 123456789,
            "supplier_article": "ART-123456789",
            "title": "Товар тестовый",
            "brand": "TestBrand",
            "source_name": "wb_content_api",
            "seen_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
        }
    )
    assert fake is None


def test_merge_observations_preserves_unique_nm_id_and_sources():
    catalog: dict[int, dict] = {}
    _merge_observations(
        catalog,
        [
            {
                "nm_id": 111,
                "supplier_article": "SUP-111",
                "title": "",
                "subject": "",
                "brand": "",
                "source_name": "stocks_api",
                "seen_at": datetime(2026, 5, 31, tzinfo=timezone.utc),
            },
            {
                "nm_id": 111,
                "supplier_article": "",
                "title": "Product 111",
                "subject": "Subject 111",
                "brand": "Brand 111",
                "source_name": "search_queries_api",
                "seen_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
            },
        ],
    )

    assert list(catalog) == [111]
    assert catalog[111]["supplier_article"] == "SUP-111"
    assert catalog[111]["title"] == "Product 111"
    assert catalog[111]["source_set"] == {"stocks_api", "search_queries_api"}
    assert catalog[111]["first_seen_at"] == datetime(2026, 5, 31, tzinfo=timezone.utc)
    assert catalog[111]["last_seen_at"] == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_compute_quality_status():
    assert _compute_quality_status({"supplier_article": "A", "title": "B", "subject": "C", "brand": "D"}) == "COMPLETE"
    assert _compute_quality_status({"supplier_article": "A", "title": "", "subject": "", "brand": ""}) == "PARTIAL"
    assert _compute_quality_status({"supplier_article": "", "title": "", "subject": "", "brand": ""}) == "NM_ID_ONLY"


def test_build_settings_products_upsert_rows_preserves_existing_manual_values():
    existing = SettingsProducts(
        nm_id=111,
        supplier_article="MANUAL-SKU",
        title="Manual title",
        subject=None,
        brand=None,
        group_name="group-1",
        item_type="bundle",
        active=False,
        is_new=True,
        report_mode="secondary",
        source_list="excel_xlsm",
        comment="manual note",
        first_seen_at=datetime(2026, 5, 20, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 5, 25, tzinfo=timezone.utc),
    )
    catalog = {
        111: {
            "nm_id": 111,
            "supplier_article": "DISCOVERY-SKU",
            "title": "Discovery title",
            "subject": "Discovery subject",
            "brand": "Discovery brand",
            "source_set": {"search_queries_api", "db_fact_stock_snapshot"},
            "first_seen_at": datetime(2026, 5, 31, tzinfo=timezone.utc),
            "last_seen_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
        }
    }

    rows = build_settings_products_upsert_rows(catalog, {111: existing})

    assert len(rows) == 1
    row = rows[0]
    assert row["nm_id"] == 111
    assert row["supplier_article"] == "MANUAL-SKU"
    assert row["title"] == "Manual title"
    assert row["subject"] == "Discovery subject"
    assert row["brand"] == "Discovery brand"
    assert row["active"] is False
    assert row["is_new"] is True
    assert row["report_mode"] == "secondary"
    assert row["group_name"] == "group-1"
    assert row["item_type"] == "bundle"
    assert row["comment"] == "manual note"
    assert set(row["source_list"].split(", ")) == {"excel_xlsm", "search_queries_api", "db_fact_stock_snapshot"}
    assert row["first_seen_at"] == datetime(2026, 5, 20, tzinfo=timezone.utc)
    assert row["last_seen_at"] == datetime(2026, 6, 1, tzinfo=timezone.utc)


def test_build_settings_products_upsert_rows_enriches_empty_reference_fields():
    existing = SettingsProducts(
        nm_id=222,
        supplier_article=None,
        title=None,
        subject=None,
        brand=None,
        group_name="group-2",
        item_type="normal",
        active=True,
        is_new=False,
        report_mode="main",
        source_list="db_fact_ad_cost_event",
        comment="keep me",
        first_seen_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
        last_seen_at=datetime(2026, 5, 30, tzinfo=timezone.utc),
    )
    catalog = {
        222: {
            "nm_id": 222,
            "supplier_article": "BLACKWOM5",
            "title": "Трусы комплект",
            "subject": "Трусы",
            "brand": "PALEY",
            "source_set": {"wb_content_api"},
            "first_seen_at": datetime(2026, 5, 31, tzinfo=timezone.utc),
            "last_seen_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
        }
    }

    rows = build_settings_products_upsert_rows(catalog, {222: existing})

    assert len(rows) == 1
    row = rows[0]
    assert row["supplier_article"] == "BLACKWOM5"
    assert row["title"] == "Трусы комплект"
    assert row["subject"] == "Трусы"
    assert row["brand"] == "PALEY"
    assert row["group_name"] == "group-2"
    assert row["item_type"] == "normal"
    assert row["comment"] == "keep me"
    assert set(row["source_list"].split(", ")) == {"db_fact_ad_cost_event", "wb_content_api"}


def test_catalog_to_rows_marks_fact_table_coverage():
    rows = _catalog_to_rows(
        {
            111: {
                "nm_id": 111,
                "supplier_article": "SUP-111",
                "title": "Product 111",
                "subject": "",
                "brand": "",
                "source_set": {"db_fact_stock_snapshot", "excel_xlsm"},
                "first_seen_at": datetime(2026, 5, 31, tzinfo=timezone.utc),
                "last_seen_at": datetime(2026, 6, 1, tzinfo=timezone.utc),
            }
        },
        fact_table_nm_ids={111},
    )

    assert rows == [
        {
            "nm_id": 111,
            "supplier_article": "SUP-111",
            "title": "Product 111",
            "subject": "",
            "brand": "",
            "source_list": "db_fact_stock_snapshot, excel_xlsm",
            "first_seen_at": "2026-05-31T00:00:00+00:00",
            "last_seen_at": "2026-06-01T00:00:00+00:00",
            "data_quality_status": "PARTIAL",
            "already_in_fact_tables": "true",
        }
    ]
