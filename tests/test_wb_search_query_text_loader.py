from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal

from src.db.wb_search_query_text_loader import (
    FACT_WB_SEARCH_QUERY_TEXT_DAY_CONFLICT_COLUMNS,
    aggregate_search_text_rows_by_query_group,
    build_search_texts_payload,
    filter_products_with_known_query_group,
    load_search_text_rows,
    normalize_search_text_day_rows,
    prepare_fact_wb_search_query_text_day_upsert_rows,
    upsert_fact_wb_search_query_text_day,
)


def test_fact_wb_search_query_text_day_conflict_columns_match_natural_key() -> None:
    assert FACT_WB_SEARCH_QUERY_TEXT_DAY_CONFLICT_COLUMNS == ("day", "nm_id", "query_text")


def test_build_search_texts_payload_uses_previous_day_for_past_period() -> None:
    payload = build_search_texts_payload(
        target_day=date(2026, 6, 24),
        nm_ids=[197330807],
        limit=100,
    )

    assert payload["currentPeriod"] == {"start": "2026-06-24", "end": "2026-06-24"}
    assert payload["pastPeriod"] == {"start": "2026-06-23", "end": "2026-06-23"}
    assert payload["currentPeriod"] != payload["pastPeriod"]
    assert payload["includeSubstitutedSKUs"] is True
    assert payload["includeSearchTexts"] is True
    assert payload["limit"] == 100


def test_filter_products_with_known_query_group_excludes_unknown_and_empty() -> None:
    rows = filter_products_with_known_query_group(
        [
            {"nm_id": 1, "query_group": "women_underwear"},
            {"nm_id": 2, "query_group": "unknown"},
            {"nm_id": 3, "query_group": ""},
            {"nm_id": 4, "query_group": None},
            {"nm_id": 5, "query_group": "gift_sets"},
        ]
    )

    assert [row["nm_id"] for row in rows] == [1, 5]


def test_normalize_search_text_day_rows_maps_metrics_and_query_group() -> None:
    payload = {
        "data": {
            "items": [
                {
                    "nmId": 197330807,
                    "text": "трусы женские",
                    "frequency": {"current": 120},
                    "weekFrequency": 840,
                    "orders": {"current": 14},
                    "visibility": {"current": "27.5"},
                    "avgPosition": {"current": "11.2"},
                    "openCard": {"current": 44},
                    "addToCart": {"current": 9},
                }
            ]
        }
    }

    rows = normalize_search_text_day_rows(
        payload=payload,
        target_day=date(2026, 6, 24),
        query_group_by_nm={197330807: "women_underwear"},
        loaded_at=datetime(2026, 6, 25, 10, 0, tzinfo=timezone.utc),
    )

    assert len(rows) == 1
    assert rows[0]["day"] == date(2026, 6, 24)
    assert rows[0]["nm_id"] == 197330807
    assert rows[0]["query_text"] == "трусы женские"
    assert rows[0]["query_group"] == "women_underwear"
    assert rows[0]["frequency_current"] == 120
    assert rows[0]["week_frequency"] == 840
    assert rows[0]["orders_current"] == 14
    assert rows[0]["visibility_current"] == Decimal("27.5")
    assert rows[0]["avg_position_current"] == Decimal("11.2")
    assert rows[0]["open_card_current"] == 44
    assert rows[0]["add_to_cart_current"] == 9


def test_prepare_fact_wb_search_query_text_day_upsert_rows_deduplicates() -> None:
    rows = prepare_fact_wb_search_query_text_day_upsert_rows(
        [
            {
                "day": "2026-06-24",
                "nm_id": 197330807,
                "query_text": "трусы женские",
                "frequency_current": 100,
            },
            {
                "day": "2026-06-24",
                "nm_id": 197330807,
                "query_text": "трусы женские",
                "frequency_current": 130,
            },
        ]
    )

    assert len(rows) == 1
    assert rows[0]["frequency_current"] == 130


def test_aggregate_search_text_rows_by_query_group_dedupes_query_text_across_nm_ids() -> None:
    rows = aggregate_search_text_rows_by_query_group(
        [
            {
                "day": date(2026, 6, 24),
                "nm_id": 1,
                "query_group": "women_underwear",
                "query_text": "трусы женские",
                "frequency_current": 120,
                "week_frequency": 800,
                "orders_current": 14,
                "visibility_current": Decimal("27.5"),
            },
            {
                "day": date(2026, 6, 24),
                "nm_id": 2,
                "query_group": "women_underwear",
                "query_text": "трусы женские",
                "frequency_current": 95,
                "week_frequency": 810,
                "orders_current": 12,
                "visibility_current": Decimal("26.0"),
            },
        ]
    )

    assert len(rows) == 1
    assert rows[0]["day"] == date(2026, 6, 24)
    assert rows[0]["query_group"] == "women_underwear"
    assert rows[0]["query_text"] == "трусы женские"
    assert rows[0]["frequency_current"] == 120
    assert rows[0]["week_frequency"] == 810
    assert rows[0]["orders_current"] == 14
    assert rows[0]["nm_id_count"] == 2


def test_upsert_fact_wb_search_query_text_day_uses_batched_upsert(monkeypatch) -> None:
    captured: dict[str, object] = {}

    def fake_upsert_rows(*, session, model, rows, conflict_columns, batch_size=None, update_columns=None):
        captured["rows"] = rows
        captured["conflict_columns"] = conflict_columns
        captured["batch_size"] = batch_size
        return len(rows)

    monkeypatch.setattr("src.db.wb_search_query_text_loader.upsert_rows", fake_upsert_rows)

    rows_upserted = upsert_fact_wb_search_query_text_day(
        session=object(),
        rows=[
            {
                "day": "2026-06-24",
                "nm_id": 197330807,
                "query_text": "трусы женские",
                "loaded_at": "2026-06-25T10:00:00+00:00",
            }
        ],
    )

    assert rows_upserted == 1
    assert captured["conflict_columns"] == FACT_WB_SEARCH_QUERY_TEXT_DAY_CONFLICT_COLUMNS
    assert captured["batch_size"] == 200


def test_load_search_text_rows_dry_run_does_not_write(monkeypatch) -> None:
    calls = {"upserted": 0}

    def fake_fetch(*, target_day, nm_ids, limit):
        return {
            "status": "200",
            "limit_used": limit,
            "items": [
                {
                    "nmId": 197330807,
                    "text": "трусы женские",
                    "frequency": {"current": 120},
                }
            ],
            "fallback_used": False,
        }

    def fake_upsert(session, rows):
        calls["upserted"] += 1
        return len(rows)

    @contextmanager
    def _dummy_session_scope():
        yield object()

    monkeypatch.setattr("src.db.wb_search_query_text_loader.fetch_search_texts_payload", fake_fetch)
    monkeypatch.setattr("src.db.wb_search_query_text_loader.upsert_fact_wb_search_query_text_day", fake_upsert)
    monkeypatch.setattr("src.db.wb_search_query_text_loader.session_scope", _dummy_session_scope)

    summary = load_search_text_rows(
        target_day=date(2026, 6, 24),
        products=[{"nm_id": 197330807, "query_group": "women_underwear"}],
        apply=False,
    )

    assert summary["write_executed"] is False
    assert summary["rows_loaded"] == 0
    assert summary["rows_prepared"] == 1
    assert calls["upserted"] == 0


def test_load_search_text_rows_apply_writes_rows(monkeypatch) -> None:
    calls = {"upserted": 0}

    def fake_fetch(*, target_day, nm_ids, limit):
        return {
            "status": "200",
            "limit_used": limit,
            "items": [
                {
                    "nmId": 197330807,
                    "text": "трусы женские",
                    "frequency": {"current": 120},
                }
            ],
            "fallback_used": False,
        }

    def fake_upsert(session, rows):
        calls["upserted"] += len(rows)
        return len(rows)

    @contextmanager
    def _dummy_session_scope():
        yield object()

    monkeypatch.setattr("src.db.wb_search_query_text_loader.fetch_search_texts_payload", fake_fetch)
    monkeypatch.setattr("src.db.wb_search_query_text_loader.upsert_fact_wb_search_query_text_day", fake_upsert)
    monkeypatch.setattr("src.db.wb_search_query_text_loader.session_scope", _dummy_session_scope)

    summary = load_search_text_rows(
        target_day=date(2026, 6, 24),
        products=[{"nm_id": 197330807, "query_group": "women_underwear"}],
        apply=True,
    )

    assert summary["write_executed"] is True
    assert summary["rows_loaded"] == 1
    assert calls["upserted"] == 1
