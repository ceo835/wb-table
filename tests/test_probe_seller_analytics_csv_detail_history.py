from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from scripts.probe_seller_analytics_csv_detail_history import (
    _build_create_payloads,
    _match_download_report,
    build_gap_match_frame,
    build_probe_summary,
    load_probe_targets,
    normalize_detail_history_frame,
)


def test_load_probe_targets_deduplicates_nm_id_date_pairs(tmp_path: Path) -> None:
    path = tmp_path / "gap.csv"
    pd.DataFrame(
        [
            {
                "Дата": "2026-06-05",
                "Артикул продавца": "BlackWOM5",
                "Артикул WB": 197330807,
                "Что отсутствует": "Положили в корзину, Заказы",
                "Рекомендация": "probe csv",
            },
            {
                "Дата": "2026-06-05",
                "Артикул продавца": "BlackWOM5",
                "Артикул WB": 197330807,
                "Что отсутствует": "Заказы",
                "Рекомендация": "duplicate",
            },
        ]
    ).to_csv(path, index=False)

    targets = load_probe_targets(path)

    assert len(targets.rows) == 1
    assert targets.rows[0].report_date == date(2026, 6, 5)
    assert targets.rows[0].nm_id == 197330807
    assert targets.nm_ids == [197330807]


def test_normalize_detail_history_frame_maps_russian_headers() -> None:
    frame = pd.DataFrame(
        [
            {
                "Дата": "2026-06-07",
                "Артикул WB": "197330807",
                "Артикул продавца": "BlackWOM5",
                "Переходы в карточку": "6125",
                "Положили в корзину": "818",
                "Заказы": "218",
                "Заказали на сумму": "288099",
            }
        ]
    )

    normalized = normalize_detail_history_frame(frame)

    assert normalized.loc[0, "date"] == date(2026, 6, 7)
    assert normalized.loc[0, "nm_id"] == 197330807
    assert normalized.loc[0, "supplier_article"] == "BlackWOM5"
    assert normalized.loc[0, "card_clicks"] == 6125
    assert normalized.loc[0, "cart_count"] == 818
    assert normalized.loc[0, "order_count"] == 218
    assert normalized.loc[0, "order_sum"] == 288099


def test_normalize_detail_history_frame_maps_wb_csv_headers() -> None:
    frame = pd.DataFrame(
        [
            {
                "nmID": "197330807",
                "dt": "2026-06-07",
                "openCardCount": "6125",
                "addToCartCount": "818",
                "ordersCount": "218",
                "ordersSumRub": "288099",
                "buyoutsCount": "150",
                "buyoutsSumRub": "200000",
                "addToCartConversion": "13.35",
                "cartToOrderConversion": "26.65",
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


def test_build_gap_match_frame_marks_found_and_missing_rows() -> None:
    targets = load_probe_targets_from_rows(
        [
            {
                "report_date": date(2026, 6, 5),
                "supplier_article": "BlackWOM5",
                "nm_id": 197330807,
                "missing_labels": ["Положили в корзину", "Заказы"],
                "recommendation": "probe csv",
            },
            {
                "report_date": date(2026, 6, 6),
                "supplier_article": "NoData",
                "nm_id": 123,
                "missing_labels": ["Заказы"],
                "recommendation": "probe csv",
            },
        ]
    )
    report_frame = pd.DataFrame(
        [
            {
                "date": date(2026, 6, 5),
                "nm_id": 197330807,
                "supplier_article": "BlackWOM5",
                "card_clicks": 6125,
                "cart_count": 818,
                "order_count": 218,
                "order_sum": 288099,
            }
        ]
    )

    matched = build_gap_match_frame(targets.rows, report_frame)

    assert len(matched) == 2
    found = matched.loc[matched["nm_id"] == 197330807].iloc[0]
    missing = matched.loc[matched["nm_id"] == 123].iloc[0]
    assert found["match_status"] == "FOUND"
    assert bool(found["has_cart_count"]) is True
    assert bool(found["has_order_count"]) is True
    assert missing["match_status"] == "NOT_FOUND"
    assert bool(missing["has_order_count"]) is False


def test_build_probe_summary_counts_gap_coverage() -> None:
    report_frame = pd.DataFrame(
        [
            {
                "date": date(2026, 6, 5),
                "nm_id": 197330807,
                "supplier_article": "BlackWOM5",
                "card_clicks": 6125,
                "cart_count": 818,
                "order_count": 218,
                "order_sum": 288099,
            }
        ]
    )
    matched = pd.DataFrame(
        [
            {
                "report_date": "2026-06-05",
                "nm_id": 197330807,
                "match_status": "FOUND",
                "has_card_clicks": True,
                "has_cart_count": True,
                "has_order_count": True,
                "has_order_sum": True,
            },
            {
                "report_date": "2026-06-06",
                "nm_id": 123,
                "match_status": "NOT_FOUND",
                "has_card_clicks": False,
                "has_cart_count": False,
                "has_order_count": False,
                "has_order_sum": False,
            },
        ]
    )

    summary = build_probe_summary(
        date_from=date(2026, 6, 4),
        date_to=date(2026, 6, 7),
        targets_count=2,
        unique_nm_ids_count=2,
        report_frame=report_frame,
        matched_frame=matched,
        create_attempts=[],
        poll_attempts=[],
        download_meta={"content_type": "text/csv"},
    )

    assert summary["gap_rows_total"] == 2
    assert summary["gap_rows_found_in_report"] == 1
    assert summary["gap_rows_with_cart_count"] == 1
    assert summary["gap_rows_with_order_count"] == 1
    assert summary["gap_rows_with_order_sum"] == 1
    assert summary["report_distinct_dates"] == ["2026-06-05"]


def test_build_create_payloads_returns_limited_variant_set() -> None:
    payloads = _build_create_payloads(
        report_name="probe",
        report_type="DETAIL_HISTORY_REPORT",
        date_from=date(2026, 6, 4),
        date_to=date(2026, 6, 7),
        nm_ids=[1, 2, 3],
    )

    assert len(payloads) == 3
    labels = [label for label, _ in payloads]
    assert labels == [
        "official_schema",
        "official_schema_skip_deleted_true",
        "official_schema_lowercase_nmids",
    ]
    first_payload = payloads[0][1]
    assert first_payload["reportType"] == "DETAIL_HISTORY_REPORT"
    assert first_payload["params"]["nmIDs"] == [1, 2, 3]
    assert first_payload["params"]["aggregationLevel"] == "day"
    assert first_payload["params"]["timezone"] == "Europe/Moscow"


def test_match_download_report_uses_name_prefix_when_download_id_missing() -> None:
    reports = [
        {
            "id": "abc",
            "status": "SUCCESS",
            "name": "detail-history-probe-20260612-142455 official",
        }
    ]

    matched = _match_download_report(
        reports,
        download_id="",
        report_name_prefix="detail-history-probe-20260612-142455",
    )

    assert matched is not None
    assert matched["id"] == "abc"


def load_probe_targets_from_rows(rows: list[dict[str, object]]):
    path = Path(__file__).parent / "_tmp_probe_targets.csv"
    pd.DataFrame(
        [
            {
                "Дата": row["report_date"].isoformat(),
                "Артикул продавца": row["supplier_article"],
                "Артикул WB": row["nm_id"],
                "Что отсутствует": ", ".join(row["missing_labels"]),
                "Рекомендация": row["recommendation"],
            }
            for row in rows
        ]
    ).to_csv(path, index=False)
    try:
        return load_probe_targets(path)
    finally:
        path.unlink(missing_ok=True)
