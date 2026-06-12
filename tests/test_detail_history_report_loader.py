from __future__ import annotations

import io
import zipfile
from datetime import date, datetime, timezone
from decimal import Decimal
from pathlib import Path

import pandas as pd

from src.db.detail_history_report_loader import (
    DETAIL_HISTORY_SOURCE_STATUS,
    build_detail_history_fact_rows,
    extract_detail_history_frame,
    load_detail_history_report,
    normalize_detail_history_frame,
)


def test_normalize_detail_history_frame_maps_downloaded_wb_headers() -> None:
    frame = pd.DataFrame(
        [
            {
                "nmID": 197330807,
                "dt": "2026-06-07",
                "openCardCount": 6125,
                "addToCartCount": 818,
                "ordersCount": 218,
                "ordersSumRub": 288099,
                "buyoutsCount": 150,
                "buyoutsSumRub": 200000,
                "addToCartConversion": 13.35,
                "cartToOrderConversion": 26.65,
            }
        ]
    )

    normalized = normalize_detail_history_frame(frame)

    assert normalized.loc[0, "date"] == date(2026, 6, 7)
    assert normalized.loc[0, "nm_id"] == 197330807
    assert normalized.loc[0, "card_clicks"] == 6125
    assert normalized.loc[0, "cart_count"] == 818
    assert normalized.loc[0, "order_count"] == 218
    assert normalized.loc[0, "order_sum"] == 288099
    assert normalized.loc[0, "buyout_count"] == 150
    assert normalized.loc[0, "buyout_sum"] == 200000


def test_extract_detail_history_frame_reads_zip_bytes_even_for_text_csv_content_type() -> None:
    csv_text = "nmID,dt,openCardCount\n197330807,2026-06-07,6125\n"
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("detail.csv", csv_text.encode("utf-8"))

    frame, meta = extract_detail_history_frame(buffer.getvalue(), "text/csv")

    assert meta["archive_member"] == "detail.csv"
    assert frame.loc[0, "nmID"] == 197330807
    assert frame.loc[0, "openCardCount"] == 6125


def test_build_detail_history_fact_rows_preserves_existing_non_null_values_when_incoming_is_null() -> None:
    normalized = pd.DataFrame(
        [
            {
                "date": date(2026, 6, 7),
                "nm_id": 197330807,
                "card_clicks": 6125,
                "cart_count": None,
                "order_count": None,
                "order_sum": None,
                "buyout_count": None,
                "buyout_sum": None,
                "add_to_cart_conversion": None,
                "cart_to_order_conversion": None,
            }
        ]
    )
    existing = {
        (date(2026, 6, 7), 197330807): {
            "date": date(2026, 6, 7),
            "nm_id": 197330807,
            "card_clicks": Decimal("5000"),
            "cart_count": Decimal("100"),
            "order_count": Decimal("50"),
            "order_sum": Decimal("9999.99"),
            "buyout_count": None,
            "buyout_sum": None,
            "add_to_cart_conversion": Decimal("2.5"),
            "cart_to_order_conversion": Decimal("30.0"),
        }
    }

    rows = build_detail_history_fact_rows(
        normalized,
        loaded_at=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
        existing_rows_by_key=existing,
    )

    assert len(rows) == 1
    row = rows[0]
    assert row["card_clicks"] == Decimal("6125")
    assert row["cart_count"] == Decimal("100")
    assert row["order_count"] == Decimal("50")
    assert row["order_sum"] == Decimal("9999.99")
    assert row["add_to_cart_conversion"] == Decimal("2.5")


def test_build_detail_history_fact_rows_keeps_explicit_zero_values() -> None:
    normalized = pd.DataFrame(
        [
            {
                "date": date(2026, 6, 7),
                "nm_id": 197330807,
                "card_clicks": 10,
                "cart_count": 0,
                "order_count": 0,
                "order_sum": 0,
                "buyout_count": 0,
                "buyout_sum": 0,
                "add_to_cart_conversion": 0,
                "cart_to_order_conversion": 0,
            }
        ]
    )

    rows = build_detail_history_fact_rows(
        normalized,
        loaded_at=datetime(2026, 6, 12, 10, 0, tzinfo=timezone.utc),
        existing_rows_by_key={},
    )

    row = rows[0]
    assert row["cart_count"] == Decimal("0")
    assert row["order_count"] == Decimal("0")
    assert row["order_sum"] == Decimal("0")
    assert row["source_status"] == DETAIL_HISTORY_SOURCE_STATUS


def test_load_detail_history_report_dry_run_does_not_write_db(monkeypatch, tmp_path: Path) -> None:
    csv_text = (
        "nmID,dt,openCardCount,addToCartCount,ordersCount,ordersSumRub,addToCartConversion,cartToOrderConversion\n"
        "197330807,2026-06-07,6125,818,218,288099,13.35,26.65\n"
    )
    buffer = io.BytesIO()
    with zipfile.ZipFile(buffer, "w", zipfile.ZIP_DEFLATED) as archive:
        archive.writestr("detail.csv", csv_text.encode("utf-8"))
    zip_bytes = buffer.getvalue()

    def fake_create(*args, **kwargs):
        return "download-1", [{"label": "official_schema", "http_status": "200", "error": "", "request_body": {}, "response_body": {"data": "ok"}, "download_id": ""}], ""

    def fake_poll(*args, **kwargs):
        return "download-1", [{"poll_number": 1, "http_status": "200", "matched_report_status": "SUCCESS", "download_id": "download-1", "reports_seen": 1, "error": ""}], {"data": []}

    def fake_download(*args, **kwargs):
        return "200", zip_bytes, "application/zip", ""

    def fail_if_db_called(*args, **kwargs):
        raise AssertionError("DB should not be touched during dry-run")

    gap_file = tmp_path / "gaps.csv"
    pd.DataFrame(
        [
            {
                "Дата": "2026-06-07",
                "Артикул продавца": "BlackWOM5",
                "Артикул WB": 197330807,
                "Что отсутствует": "Положили в корзину, Заказы, Заказали на сумму",
                "Рекомендация": "probe csv",
            }
        ]
    ).to_csv(gap_file, index=False)

    monkeypatch.setattr("src.db.detail_history_report_loader.create_detail_history_download_task", fake_create)
    monkeypatch.setattr("src.db.detail_history_report_loader.poll_detail_history_download", fake_poll)
    monkeypatch.setattr("src.db.detail_history_report_loader.download_detail_history_file", fake_download)
    monkeypatch.setattr("src.db.detail_history_report_loader.fetch_existing_funnel_rows", fail_if_db_called)
    monkeypatch.setattr("src.db.detail_history_report_loader.apply_detail_history_rows", fail_if_db_called)

    result = load_detail_history_report(
        date_from=date(2026, 6, 4),
        date_to=date(2026, 6, 7),
        nmids_from_file=gap_file,
        dry_run=True,
        save_raw_dir=tmp_path / "raw",
    )

    assert result["dry_run"] is True
    assert result["report_rows"] == 1
    assert result["parsed_rows"] == 1
    assert result["upserted_rows"] == 0
    assert result["gaps_found_in_report"] == 1
