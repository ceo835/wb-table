from __future__ import annotations

from datetime import date
from decimal import Decimal

from src.db.search_query_loader import (
    FACT_SEARCH_QUERY_METRIC_CONFLICT_COLUMNS,
    build_fact_search_query_metric_db_row,
    prepare_fact_search_query_metric_upsert_rows,
    upsert_fact_search_query_metric,
)


def test_fact_search_query_metric_conflict_columns_match_natural_key():
    assert FACT_SEARCH_QUERY_METRIC_CONFLICT_COLUMNS == ("period_start", "period_end", "nm_id", "search_query")


def test_build_fact_search_query_metric_db_row_preserves_nulls():
    row = build_fact_search_query_metric_db_row(
        {
            "period_start": "2026-06-01",
            "period_end": "2026-06-01",
            "date": "2026-06-01",
            "nm_id": 197330807,
            "supplier_article": "BlackWOM5",
            "title": "Product",
            "subject": "Трусы",
            "brand": "PALEY",
            "search_query": "трусы женские",
            "query_count": 9,
            "query_count_prev": "",
            "visibility": 11,
            "visibility_prev": "",
            "avg_position": 7,
            "avg_position_prev": "",
            "median_position": 6,
            "median_position_prev": "",
            "search_clicks": "",
            "search_cart": "",
            "cart_conversion": "",
            "search_orders": "",
            "order_conversion": "",
            "min_discount_price": "",
            "max_discount_price": "",
            "loaded_at": "2026-06-05T10:00:00+05:00",
        }
    )
    assert row["period_start"] == date(2026, 6, 1)
    assert row["date"] == date(2026, 6, 1)
    assert row["query_count"] == Decimal("9")
    assert row["query_count_prev"] is None
    assert row["search_clicks"] is None
    assert row["min_discount_price"] is None
    assert row["search_clicks_competitor_percentile"] is None


def test_prepare_fact_search_query_metric_upsert_rows_deduplicates():
    rows = prepare_fact_search_query_metric_upsert_rows(
        [
            {
                "period_start": "2026-06-01",
                "period_end": "2026-06-01",
                "date": "2026-06-01",
                "nm_id": 197330807,
                "search_query": "трусы женские",
                "query_count": 9,
                "loaded_at": "2026-06-05T10:00:00+05:00",
            },
            {
                "period_start": "2026-06-01",
                "period_end": "2026-06-01",
                "date": "2026-06-01",
                "nm_id": 197330807,
                "search_query": "трусы женские",
                "query_count": 11,
                "loaded_at": "2026-06-05T10:00:00+05:00",
            },
        ]
    )
    assert len(rows) == 1
    assert rows[0]["query_count"] == Decimal("11")


def test_prepare_fact_search_query_metric_upsert_rows_keeps_competitor_percentiles_null():
    rows = prepare_fact_search_query_metric_upsert_rows(
        [
            {
                "period_start": "2026-06-01",
                "period_end": "2026-06-01",
                "date": "2026-06-01",
                "nm_id": 197330807,
                "search_query": "трусы женские",
                "search_clicks_competitor_percentile": "",
                "search_cart_competitor_percentile": "",
                "cart_conversion_competitor_percentile": "",
                "search_orders_competitor_percentile": "",
                "order_conversion_competitor_percentile": "",
                "loaded_at": "2026-06-05T10:00:00+05:00",
            }
        ]
    )
    assert len(rows) == 1
    assert rows[0]["search_clicks_competitor_percentile"] is None
    assert rows[0]["search_cart_competitor_percentile"] is None
    assert rows[0]["cart_conversion_competitor_percentile"] is None
    assert rows[0]["search_orders_competitor_percentile"] is None
    assert rows[0]["order_conversion_competitor_percentile"] is None


def test_upsert_fact_search_query_metric_uses_batched_upsert(monkeypatch):
    captured = {}

    def fake_upsert_rows(*, session, model, rows, conflict_columns, batch_size=None, update_columns=None):
        captured["rows"] = rows
        captured["conflict_columns"] = conflict_columns
        captured["batch_size"] = batch_size
        return len(rows)

    monkeypatch.setattr("src.db.search_query_loader.upsert_rows", fake_upsert_rows)

    rows_upserted = upsert_fact_search_query_metric(
        session=object(),
        rows=[
            {
                "period_start": "2026-06-01",
                "period_end": "2026-06-01",
                "date": "2026-06-01",
                "nm_id": 197330807,
                "search_query": "трусы",
                "loaded_at": "2026-06-05T10:00:00+05:00",
            }
        ],
    )

    assert rows_upserted == 1
    assert captured["conflict_columns"] == FACT_SEARCH_QUERY_METRIC_CONFLICT_COLUMNS
    assert captured["batch_size"] == 200
