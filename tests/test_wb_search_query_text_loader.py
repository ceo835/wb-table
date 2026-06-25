from __future__ import annotations

from contextlib import contextmanager
from datetime import date, datetime, timezone
from decimal import Decimal
import pytest

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
    assert rows[0]["query_group"] == "трусы женские"
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


def test_fetch_search_texts_payload_raises_on_too_many_nm_ids() -> None:
    from src.db.wb_search_query_text_loader import fetch_search_texts_payload
    with pytest.raises(ValueError, match="nm_ids size cannot exceed 50"):
        fetch_search_texts_payload(
            target_day=date(2026, 6, 24),
            nm_ids=list(range(51)),
        )


def test_fetch_search_texts_payload_no_fallback_on_nm_ids_error(monkeypatch) -> None:
    from src.db.wb_search_query_text_loader import fetch_search_texts_payload
    import requests

    class FakeResponse:
        status_code = 400
        text = "nmIds (array: len 58 greater than maximum 50)"
        def json(self):
            return {"detail": self.text}

    def fake_post(*args, **kwargs):
        return FakeResponse()

    monkeypatch.setattr(requests.Session, "post", fake_post)
    monkeypatch.setattr("src.db.wb_search_query_text_loader._headers", lambda: {})

    res = fetch_search_texts_payload(
        target_day=date(2026, 6, 24),
        nm_ids=[1, 2],
    )

    assert res["status"] == "400"
    assert len(res["request_attempts"]) == 1 # No fallback limit attempts!


def test_load_search_text_rows_batches_correctly(monkeypatch) -> None:
    batch_calls = []

    def fake_fetch(*, target_day, nm_ids, limit):
        batch_calls.append(list(nm_ids))
        return {
            "status": "200",
            "limit_used": limit,
            "items": [{"nmId": nm, "text": "test_query"} for nm in nm_ids],
            "fallback_used": False,
        }

    monkeypatch.setattr("src.db.wb_search_query_text_loader.fetch_search_texts_payload", fake_fetch)

    # 58 products
    products = [{"nm_id": i, "query_group": "women_underwear"} for i in range(1, 59)]
    summary = load_search_text_rows(
        target_day=date(2026, 6, 24),
        products=products,
        apply=False,
        nm_batch_size=50,
        request_sleep_seconds=0.0,
    )

    assert len(batch_calls) == 2
    assert len(batch_calls[0]) == 50
    assert len(batch_calls[1]) == 8
    assert summary["batches_total"] == 2
    assert summary["batches_succeeded"] == 2
    assert summary["batches_failed"] == 0
    assert summary["api_status_by_batch"] == ["200", "200"]
    assert summary["rows_prepared"] == 58


def test_load_search_text_rows_validates_batch_size() -> None:
    with pytest.raises(ValueError, match="nm_batch_size cannot exceed 50"):
        load_search_text_rows(
            target_day=date(2026, 6, 24),
            products=[],
            nm_batch_size=51,
        )


def test_load_search_text_rows_aborts_on_429_and_prevents_write(monkeypatch) -> None:
    batch_calls = []

    def fake_fetch(*, target_day, nm_ids, limit):
        batch_calls.append(list(nm_ids))
        return {
            "status": "429",
            "limit_used": limit,
            "items": [],
            "fallback_used": False,
            "error": "Too Many Requests",
            "request_attempts": [{"status": "429", "limit": limit, "error": "Too Many Requests"}]
        }

    calls = {"upserted": 0}
    def fake_upsert(session, rows):
        calls["upserted"] += len(rows)
        return len(rows)

    @contextmanager
    def _dummy_session_scope():
        yield object()

    monkeypatch.setattr("src.db.wb_search_query_text_loader.fetch_search_texts_payload", fake_fetch)
    monkeypatch.setattr("src.db.wb_search_query_text_loader.upsert_fact_wb_search_query_text_day", fake_upsert)
    monkeypatch.setattr("src.db.wb_search_query_text_loader.session_scope", _dummy_session_scope)

    # 58 products -> batching should make 2 batches: 50 and 8
    products = [{"nm_id": i, "query_group": "women_underwear"} for i in range(1, 59)]
    summary = load_search_text_rows(
        target_day=date(2026, 6, 24),
        products=products,
        apply=True,
        nm_batch_size=50,
        request_sleep_seconds=0.0,
        max_retries=1, # 1 retry -> total 2 calls per batch
    )

    # Should fail on first batch and abort. First batch: 1 main call + 1 retry = 2 calls
    assert len(batch_calls) == 2 # 2 calls for the first batch, none for the second
    assert summary["batches_total"] == 2
    assert summary["batches_succeeded"] == 0
    assert summary["batches_failed"] == 1
    assert summary["api_status_by_batch"] == ["429"]
    assert summary["partial_write_prevented"] is True
    assert summary["write_executed"] is False
    assert summary["rows_loaded"] == 0
    assert calls["upserted"] == 0


def test_load_search_text_rows_all_or_nothing_apply(monkeypatch) -> None:
    batch_idx = 0
    def fake_fetch(*, target_day, nm_ids, limit):
        nonlocal batch_idx
        status = "200" if batch_idx == 0 else "500"
        batch_idx += 1
        return {
            "status": status,
            "limit_used": limit,
            "items": [{"nmId": nm, "text": "query"} for nm in nm_ids] if status == "200" else [],
            "fallback_used": False,
            "error": "" if status == "200" else "Internal Error",
            "request_attempts": [{"status": status, "limit": limit, "error": "" if status == "200" else "Internal Error"}]
        }

    calls = {"upserted": 0}
    def fake_upsert(session, rows):
        calls["upserted"] += len(rows)
        return len(rows)

    @contextmanager
    def _dummy_session_scope():
        yield object()

    monkeypatch.setattr("src.db.wb_search_query_text_loader.fetch_search_texts_payload", fake_fetch)
    monkeypatch.setattr("src.db.wb_search_query_text_loader.upsert_fact_wb_search_query_text_day", fake_upsert)
    monkeypatch.setattr("src.db.wb_search_query_text_loader.session_scope", _dummy_session_scope)

    products = [{"nm_id": i, "query_group": "women_underwear"} for i in range(1, 59)]
    summary = load_search_text_rows(
        target_day=date(2026, 6, 24),
        products=products,
        apply=True,
        nm_batch_size=50,
        request_sleep_seconds=0.0,
    )

    # First batch succeeded, second failed -> nothing written
    assert summary["batches_total"] == 2
    assert summary["batches_succeeded"] == 1
    assert summary["batches_failed"] == 1
    assert summary["api_status_by_batch"] == ["200", "500"]
    assert summary["partial_write_prevented"] is True
    assert summary["write_executed"] is False
    assert summary["rows_loaded"] == 0
    assert calls["upserted"] == 0
