from __future__ import annotations

from src.reports.vbro_profit_reconstruction_probe import (
    FORBIDDEN_SUMMARY_KEYS,
    PROBE_DATE,
    TARGET_NM_IDS,
    build_probe_summary,
    build_source_summary,
    extract_deductions_rows,
)


def test_extract_deductions_rows_keeps_only_target_nm_and_cost_lines() -> None:
    rows = [
        {
            "sale_dt": "2026-05-23T10:00:00",
            "nm_id": 197330807,
            "supplier_article": "BlackWOM5",
            "deduction": 15,
            "penalty": 0,
        },
        {
            "sale_dt": "2026-05-23T11:00:00",
            "nm_id": 197330807,
            "supplier_article": "BlackWOM5",
            "deduction": 0,
            "penalty": 0,
            "acceptance": 0,
        },
        {
            "sale_dt": "2026-05-22T10:00:00",
            "nm_id": 197330807,
            "deduction": 99,
        },
        {
            "sale_dt": "2026-05-23T10:00:00",
            "nm_id": 999999,
            "deduction": 30,
        },
    ]

    result = extract_deductions_rows(rows, nm_ids=TARGET_NM_IDS, probe_date=PROBE_DATE)

    assert len(result) == 1
    assert result[0]["nm_id"] == 197330807
    assert result[0]["deduction"] == 15


def test_build_source_summary_marks_endpoint_not_confirmed_for_404() -> None:
    summary = build_source_summary(
        source_name="paid_storage",
        endpoint="/api/v1/paid_storage",
        saved_files=["paid_storage_error.json"],
        http_status="404",
        rows_count=0,
        fields_available=["error"],
        error="Not Found",
        note="endpoint_not_confirmed",
    )

    assert summary["status"] == "ENDPOINT_NOT_CONFIRMED"
    assert summary["saved_files"] == ["paid_storage_error.json"]
    assert summary["rows_count"] == 0


def test_build_probe_summary_stays_raw_only() -> None:
    source_summaries = {
        "detail_history_report": build_source_summary(
            source_name="detail_history_report",
            endpoint="/api/v2/nm-report/downloads",
            saved_files=["detail_history_report_raw.csv"],
            http_status="200",
            rows_count=2,
            fields_available=["dt", "nmID", "ordersCount"],
        ),
        "paid_storage": build_source_summary(
            source_name="paid_storage",
            endpoint="/api/v1/paid_storage",
            saved_files=["paid_storage_error.json"],
            http_status="404",
            rows_count=0,
            fields_available=[],
            error="Not Found",
        ),
    }

    summary = build_probe_summary(output_dir="data/processed/vbro_raw_probe_2026-05-23", source_summaries=source_summaries)

    assert summary["sources_succeeded"] == ["detail_history_report"]
    assert summary["sources_require_another_endpoint_or_host"] == ["paid_storage"]
    assert "detail_history_report_raw.csv" in summary["saved_files"]
    assert "paid_storage_error.json" in summary["saved_files"]
    flattened = str(summary)
    for forbidden_key in FORBIDDEN_SUMMARY_KEYS:
        assert forbidden_key not in flattened
