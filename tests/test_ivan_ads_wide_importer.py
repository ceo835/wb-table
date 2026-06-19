from __future__ import annotations

from contextlib import contextmanager
from pathlib import Path
from decimal import Decimal

import pytest

from src.importers.ivan_ads_wide_importer import (
    IVAN_ADS_WIDE_DATA_STATUS,
    IVAN_ADS_WIDE_IMPORT_SOURCE,
    build_ivan_ads_wide_audit_summary,
    build_ivan_ads_wide_import_dry_run_summary,
    build_ivan_ads_wide_duplicate_report,
    parse_ivan_ads_wide_csv,
)


HEADER = ",".join(
    [
        "Дата",
        "Артикул",
        "Затраты РК/Раньше было (Реальная корзина)",
        "корзин от этой РК (эффективность РК)",
        "CTR корзины",
        "цена корзин от этой РК (эффективность РК)",
        "Показы РК этого артикула",
        "CPM",
        "Артикул",
        "Затраты РК/Раньше было (Реальная корзина)",
        "корзин от этой РК (эффективность РК)",
        "CTR корзины",
        "цена корзин от этой РК (эффективность РК)",
        "Показы РК этого артикула",
        "CPM",
        "Операционная прибыль",
    ]
)


def _write_cp1251_csv(path: Path, lines: list[str]) -> Path:
    path.write_text("\n".join(lines) + "\n", encoding="cp1251")
    return path


def test_parse_ivan_ads_wide_csv_detects_groups_and_cp1251(tmp_path: Path) -> None:
    file_path = _write_cp1251_csv(
        tmp_path / "ivan_ads_wide.csv",
        [
            HEADER,
            '2026-06-18,111111,16 942,25,"5,31%","16,34",3 229,100,222222,0,0,"0,00%","0,00",0,0,',
            HEADER,
            '2026-06-19,333333,1 250,12,"4,50%","18,50",1 999,98,,,,,,,,',
        ],
    )

    parsed = parse_ivan_ads_wide_csv(file_path)

    assert parsed.encoding == "cp1251"
    assert parsed.group_count == 2
    assert parsed.rows_read == 2
    assert len(parsed.rows_long) == 3
    assert parsed.rows_long[0]["campaign_ref"] == "section_1_group_1"
    assert parsed.rows_long[1]["campaign_ref"] == "section_1_group_2"
    assert parsed.rows_long[2]["campaign_ref"] == "section_2_group_1"
    assert parsed.rows_long[0]["nm_id"] == 111111
    assert parsed.rows_long[1]["nm_id"] == 222222
    assert parsed.rows_long[2]["nm_id"] == 333333


def test_parse_ivan_ads_wide_csv_parses_percent_and_spaced_numbers(tmp_path: Path) -> None:
    file_path = _write_cp1251_csv(
        tmp_path / "ivan_ads_wide_numbers.csv",
        [
            HEADER,
            '2026-06-18,111111,16 942,25,"5,31%","16,34",3 229,100,,,,,,,,',
        ],
    )

    parsed = parse_ivan_ads_wide_csv(file_path)
    row = parsed.rows_long[0]

    assert row["ad_spend"] == Decimal("16942")
    assert row["ad_atbs"] == Decimal("25")
    assert row["ad_cart_ctr"] == Decimal("5.31")
    assert row["ad_cost_per_cart"] == Decimal("16.34")
    assert row["ad_views"] == Decimal("3229")
    assert row["ad_cpm"] == Decimal("100")


def test_parse_ivan_ads_wide_csv_keeps_zero_and_uses_null_for_empty(tmp_path: Path) -> None:
    file_path = _write_cp1251_csv(
        tmp_path / "ivan_ads_wide_zero.csv",
        [
            HEADER,
            '2026-06-18,222222,0,0,"0,00%","0,00",0,0,333333,,,,,,,',
        ],
    )

    parsed = parse_ivan_ads_wide_csv(file_path)

    assert len(parsed.rows_long) == 1
    row = parsed.rows_long[0]
    assert row["nm_id"] == 222222
    assert row["ad_spend"] == Decimal("0")
    assert row["ad_atbs"] == Decimal("0")
    assert row["ad_cart_ctr"] == Decimal("0.00")
    assert row["ad_cost_per_cart"] == Decimal("0.00")
    assert row["ad_views"] == Decimal("0")
    assert row["ad_cpm"] == Decimal("0")


def test_parse_ivan_ads_wide_csv_raises_without_date_header(tmp_path: Path) -> None:
    file_path = _write_cp1251_csv(
        tmp_path / "ivan_ads_wide_no_date.csv",
        [
            HEADER.replace("Дата", "День"),
            '2026-06-18,111111,100,5,"5,00%","20,00",1000,100,,,,,,,,',
        ],
    )

    with pytest.raises(ValueError, match="Дата"):
        parse_ivan_ads_wide_csv(file_path)


def test_parse_ivan_ads_wide_csv_raises_without_group_article_column(tmp_path: Path) -> None:
    file_path = _write_cp1251_csv(
        tmp_path / "ivan_ads_wide_no_article.csv",
        [
            HEADER.replace("Артикул", "Товар", 1).replace("Артикул", "Товар", 1),
            '2026-06-18,111111,100,5,"5,00%","20,00",1000,100,222222,200,6,"6,00%","30,00",2000,120,',
        ],
    )

    with pytest.raises(ValueError, match="Артикул"):
        parse_ivan_ads_wide_csv(file_path)


def test_build_ivan_ads_wide_import_dry_run_summary_does_not_write(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    file_path = _write_cp1251_csv(
        tmp_path / "ivan_ads_wide_dry_run.csv",
        [
            HEADER,
            '2026-06-18,111111,100,5,"5,00%","20,00",1000,100,,,,,,,,',
        ],
    )
    parsed = parse_ivan_ads_wide_csv(file_path)

    @contextmanager
    def _dummy_session_scope():
        class _DummySession:
            pass

        yield _DummySession()

    def _fail_on_write(*_args, **_kwargs):
        raise AssertionError("dry-run must not write to DB")

    monkeypatch.setattr("src.importers.ivan_ads_wide_importer.session_scope", _dummy_session_scope)
    monkeypatch.setattr("src.importers.ivan_ads_wide_importer._upsert_fact_ivan_ads_wide_rows", _fail_on_write)
    monkeypatch.setattr("src.importers.ivan_ads_wide_importer._load_existing_ads_wide_keys", lambda session, rows: set())

    summary = build_ivan_ads_wide_import_dry_run_summary(parsed)

    assert summary["write_executed"] is False
    assert summary["rows_planned_for_import"] == 1
    assert summary["target_table"] == "fact_ivan_ads_wide_day"
    assert summary["import_source"] == IVAN_ADS_WIDE_IMPORT_SOURCE
    assert summary["data_status"] == IVAN_ADS_WIDE_DATA_STATUS


def test_build_ivan_ads_wide_audit_summary_reports_detected_alias_key(tmp_path: Path) -> None:
    file_path = _write_cp1251_csv(
        tmp_path / "ivan_ads_wide_audit.csv",
        [
            HEADER,
            '2026-06-18,111111,100,5,"5,00%","20,00",1000,100,,,,,,,,',
        ],
    )

    parsed = parse_ivan_ads_wide_csv(file_path)
    summary = build_ivan_ads_wide_audit_summary(parsed)

    assert summary["found_date_column"] is True
    assert summary["found_nm_id_column"] is False
    assert summary["found_group_article_alias"] is True
    assert summary["wide_groups_found"] == 2
    assert summary["rows_with_useful_ad_metrics"] == 1


def test_build_ivan_ads_wide_duplicate_report_separates_exact_and_conflicting_groups(tmp_path: Path) -> None:
    file_path = _write_cp1251_csv(
        tmp_path / "ivan_ads_wide_duplicates.csv",
        [
            HEADER,
            '2026-06-18,111111,100,5,"5,00%","20,00",1000,100,,,,,,,,',
            '2026-06-18,111111,100,5,"5,00%","20,00",1000,100,,,,,,,,',
            '2026-06-18,222222,200,6,"6,00%","30,00",2000,120,,,,,,,,',
            '2026-06-18,222222,250,6,"6,00%","30,00",2000,120,,,,,,,,',
        ],
    )

    parsed = parse_ivan_ads_wide_csv(file_path)
    report = build_ivan_ads_wide_duplicate_report(parsed)

    assert report["duplicate_key_count"] == 2
    assert report["duplicate_exact_key_count"] == 1
    assert report["duplicate_conflicting_key_count"] == 1
    assert len(report["duplicate_examples"]) == 2
    assert report["top_dates_with_duplicates"][0]["date"] == "2026-06-18"
    assert report["top_nm_ids_with_duplicates"][0]["nm_id"] == 111111
    assert report["top_campaign_refs_with_duplicates"][0]["campaign_ref"] == "section_1_group_1"

    exact_row = next(row for row in report["duplicate_rows"] if row["nm_id"] == 111111)
    conflicting_row = next(row for row in report["duplicate_rows"] if row["nm_id"] == 222222)
    assert exact_row["rows_identical"] is True
    assert conflicting_row["rows_identical"] is False


def test_build_ivan_ads_wide_import_dry_run_summary_dedupe_exact_drops_only_exact_duplicates(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    file_path = _write_cp1251_csv(
        tmp_path / "ivan_ads_wide_dedupe_exact.csv",
        [
            HEADER,
            '2026-06-18,111111,100,5,"5,00%","20,00",1000,100,,,,,,,,',
            '2026-06-18,111111,100,5,"5,00%","20,00",1000,100,,,,,,,,',
            '2026-06-18,222222,200,6,"6,00%","30,00",2000,120,,,,,,,,',
            '2026-06-18,222222,250,6,"6,00%","30,00",2000,120,,,,,,,,',
        ],
    )
    parsed = parse_ivan_ads_wide_csv(file_path)

    @contextmanager
    def _dummy_session_scope():
        class _DummySession:
            pass

        yield _DummySession()

    monkeypatch.setattr("src.importers.ivan_ads_wide_importer.session_scope", _dummy_session_scope)
    monkeypatch.setattr("src.importers.ivan_ads_wide_importer._load_existing_ads_wide_keys", lambda session, rows: set())

    summary = build_ivan_ads_wide_import_dry_run_summary(parsed, dedupe_mode="exact")

    assert summary["rows_found_total"] == 4
    assert summary["rows_dropped_by_exact_dedupe"] == 1
    assert summary["rows_planned_for_import"] == 3
    assert summary["duplicate_exact_key_count"] == 1
    assert summary["duplicate_conflicting_key_count"] == 1
    assert summary["can_apply"] is False
