from __future__ import annotations

import csv
from contextlib import contextmanager
from decimal import Decimal
from pathlib import Path

from src.importers.ivan_current_importer import (
    apply_ivan_current_insert_missing,
    build_ivan_current_audit_summary,
    build_ivan_current_import_dry_run_summary,
    normalize_ivan_current_file,
    parse_ivan_current_file,
    persist_ivan_current_import_dry_run_report,
)


def _write_cp1251_csv(tmp_path: Path, content: str) -> Path:
    file_path = tmp_path / "ivan_current_itogo.csv"
    file_path.write_text(content, encoding="cp1251")
    return file_path


def test_parse_ivan_current_file_maps_funnel_and_ad_blocks(tmp_path: Path) -> None:
    header = ' Артикул продавца,Артикул WB, Дата, Показы, Переходы в карточку, Положили в корзину," Заказали, шт",СиТиАр, CTR," Конверсия в корзину, %","Конверсия в заказ, %"," Заказали на сумму, ? ",Расход на все корзины," Локальные заказы, %", Сумма кампания, Показы, Переходы в карточку, Положили в корзину," Заказали, шт"'
    file_path = _write_cp1251_csv(
        tmp_path,
        "\n".join(
            [
                header,
                ' art-1,1001, 2026-06-18,1 022,120,33,10,,11,7,30,456789,582,72,12377,"90,78","13,32","45,50","12,00"',
            ]
        ),
    )

    parsed = parse_ivan_current_file(file_path)

    assert parsed.file_type == "csv"
    assert parsed.encoding == "cp1251"
    assert parsed.rows_read == 1
    assert set(parsed.recognized_blocks) == {"ad_day", "funnel_day"}
    row = parsed.rows_normalized[0]
    assert row["supplier_article"] == "art-1"
    assert row["nm_id"] == 1001
    assert row["date"].isoformat() == "2026-06-18"
    assert row["impressions"] == Decimal("1022")
    assert row["ad_spend"] == Decimal("12377")
    assert row.get("ad_views") is None
    assert row.get("ad_orders") is None


def test_audit_summary_reports_active_scope_overlap(tmp_path: Path, monkeypatch) -> None:
    header = ' Артикул продавца,Артикул WB, Дата, Показы, Переходы в карточку, Положили в корзину," Заказали, шт",СиТиАр, CTR," Конверсия в корзину, %","Конверсия в заказ, %"," Заказали на сумму, ? ",Расход на все корзины," Локальные заказы, %", Сумма кампания, Показы, Переходы в карточку, Положили в корзину," Заказали, шт"'
    file_path = _write_cp1251_csv(
        tmp_path,
        "\n".join(
            [
                header,
                ' art-1,1001, 2026-06-18,100,10,2,1,,10,5,50,1000,11,70,300,"40,00","4,00","1,00","1,00"',
                ' art-2,1002, 2026-06-18,200,20,4,2,,10,5,50,2000,22,71,400,"50,00","5,00","2,00","2,00"',
            ]
        ),
    )
    parsed = parse_ivan_current_file(file_path)
    monkeypatch.setattr(
        "src.importers.ivan_current_importer._load_active_products",
        lambda: {
            1001: {"nm_id": 1001, "supplier_article": "art-1"},
            1003: {"nm_id": 1003, "supplier_article": "art-3"},
        },
    )

    summary = build_ivan_current_audit_summary(parsed, only_active_products=True)

    assert summary["unique_nm_id_count"] == 2
    assert summary["file_nm_ids_in_active_count"] == 1
    assert summary["active_nm_ids_missing_in_file_count"] == 1
    assert summary["file_nm_ids_outside_active_count"] == 1
    assert summary["rows_for_active_products"] == 1


def test_normalize_ivan_current_file_creates_expected_outputs(tmp_path: Path, monkeypatch) -> None:
    header = ' Артикул продавца,Артикул WB, Дата, Показы, Переходы в карточку, Положили в корзину," Заказали, шт",СиТиАр, CTR," Конверсия в корзину, %","Конверсия в заказ, %"," Заказали на сумму, ? ",Расход на все корзины," Локальные заказы, %", Сумма кампания, Показы, Переходы в карточку, Положили в корзину," Заказали, шт"'
    file_path = _write_cp1251_csv(
        tmp_path,
        "\n".join(
            [
                header,
                ' art-1,1001, 2026-06-18,100,10,2,1,,10,5,50,1000,11,70,300,"40,00","4,00","1,00","1,00"',
            ]
        ),
    )
    parsed = parse_ivan_current_file(file_path)
    monkeypatch.setattr(
        "src.importers.ivan_current_importer._load_active_products",
        lambda: {1001: {"nm_id": 1001, "supplier_article": "art-1"}},
    )

    output_dir = tmp_path / "normalized"
    summary = normalize_ivan_current_file(parsed, only_active_products=True, output_dir=output_dir, split_by_nm=True)

    assert summary["funnel_rows"] == 1
    assert summary["ad_rows"] == 1
    assert (output_dir / "funnel_day.csv").exists()
    assert (output_dir / "ad_day.csv").exists()
    assert (output_dir / "unmapped_columns.csv").exists()
    assert (tmp_path / "by_nm_id" / "1001.csv").exists()


def test_import_dry_run_reports_existing_keys_without_writes(tmp_path: Path, monkeypatch) -> None:
    normalized_dir = tmp_path / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    with (normalized_dir / "funnel_day.csv").open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(
            file_handle,
            fieldnames=[
                "date",
                "nm_id",
                "supplier_article",
                "impressions",
                "card_clicks",
                "cart_count",
                "order_count",
                "order_sum",
                "ctr",
                "add_to_cart_conversion",
                "cart_to_order_conversion",
                "local_orders_percent",
                "avg_delivery_time",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "date": "2026-06-18",
                "nm_id": "1001",
                "supplier_article": "art-1",
                "impressions": "100",
                "card_clicks": "10",
                "cart_count": "2",
                "order_count": "1",
                "order_sum": "1000",
                "ctr": "10",
                "add_to_cart_conversion": "5",
                "cart_to_order_conversion": "50",
                "local_orders_percent": "70",
                "avg_delivery_time": "",
            }
        )
    monkeypatch.setattr(
        "src.importers.ivan_current_importer._load_active_products",
        lambda: {1001: {"nm_id": 1001, "supplier_article": "art-1"}},
    )

    @contextmanager
    def _dummy_session_scope():
        yield object()

    monkeypatch.setattr("src.importers.ivan_current_importer.session_scope", _dummy_session_scope)
    monkeypatch.setattr(
        "src.importers.ivan_current_importer._load_existing_funnel_keys",
        lambda session, rows: {(rows[0]["date"], int(rows[0]["nm_id"]))},
    )

    summary = build_ivan_current_import_dry_run_summary(
        source_dir=normalized_dir,
        only_active_products=True,
        mode="insert-missing",
    )

    assert summary["planned_tables"] == ["fact_funnel_day"]
    assert summary["rows_with_valid_date_nm_id"] == 1
    assert summary["rows_already_in_db"] == 1
    assert summary["rows_can_insert"] == 0
    assert summary["write_executed"] is False


def test_import_dry_run_builds_insertable_breakdowns_and_persists_reports(tmp_path: Path, monkeypatch) -> None:
    normalized_dir = tmp_path / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    with (normalized_dir / "funnel_day.csv").open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(
            file_handle,
            fieldnames=[
                "date",
                "nm_id",
                "supplier_article",
                "impressions",
                "card_clicks",
                "cart_count",
                "order_count",
                "order_sum",
                "ctr",
                "add_to_cart_conversion",
                "cart_to_order_conversion",
                "local_orders_percent",
                "avg_delivery_time",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "date": "2026-06-18",
                "nm_id": "1001",
                "supplier_article": "art-1",
                "impressions": "100",
                "card_clicks": "10",
                "cart_count": "2",
                "order_count": "1",
                "order_sum": "1000",
                "ctr": "10",
                "add_to_cart_conversion": "5",
                "cart_to_order_conversion": "50",
                "local_orders_percent": "70",
                "avg_delivery_time": "",
            }
        )
        writer.writerow(
            {
                "date": "2026-06-19",
                "nm_id": "1001",
                "supplier_article": "art-1",
                "impressions": "",
                "card_clicks": "",
                "cart_count": "",
                "order_count": "",
                "order_sum": "",
                "ctr": "",
                "add_to_cart_conversion": "",
                "cart_to_order_conversion": "",
                "local_orders_percent": "",
                "avg_delivery_time": "",
            }
        )
        writer.writerow(
            {
                "date": "2026-06-18",
                "nm_id": "1002",
                "supplier_article": "art-2",
                "impressions": "200",
                "card_clicks": "20",
                "cart_count": "4",
                "order_count": "2",
                "order_sum": "",
                "ctr": "10",
                "add_to_cart_conversion": "6",
                "cart_to_order_conversion": "40",
                "local_orders_percent": "",
                "avg_delivery_time": "",
            }
        )
    monkeypatch.setattr(
        "src.importers.ivan_current_importer._load_active_products",
        lambda: {
            1001: {"nm_id": 1001, "supplier_article": "art-1"},
            1002: {"nm_id": 1002, "supplier_article": "art-2"},
        },
    )

    @contextmanager
    def _dummy_session_scope():
        yield object()

    monkeypatch.setattr("src.importers.ivan_current_importer.session_scope", _dummy_session_scope)
    monkeypatch.setattr(
        "src.importers.ivan_current_importer._load_existing_funnel_keys",
        lambda session, rows: {(rows[0]["date"], int(rows[0]["nm_id"]))},
    )

    summary = build_ivan_current_import_dry_run_summary(
        source_dir=normalized_dir,
        only_active_products=True,
        mode="insert-missing",
    )

    assert summary["insertable_rows_before_empty_guard"] == 2
    assert summary["skipped_empty_rows"] == 1
    assert summary["rows_to_insert"] == 1
    assert summary["rows_can_insert"] == 1
    assert summary["insertable_date_min"] == "2026-06-18"
    assert summary["insertable_date_max"] == "2026-06-18"
    assert summary["insertable_by_date"][0]["date"] == "2026-06-18"
    assert summary["insertable_by_date"][0]["rows_to_insert"] == 1
    assert summary["insertable_by_nm_id"][0]["nm_id"] == 1002
    assert summary["insertable_rows_with_useful_data"] == 1
    assert summary["insertable_rows_almost_empty"] == 1
    assert summary["insertable_field_non_null_counts"]["card_clicks"] == 1
    assert summary["insertable_field_null_counts"]["avg_delivery_time"] == 1

    output_dir = tmp_path / "manual_imports" / "ivan_current"
    persisted = persist_ivan_current_import_dry_run_report(summary, output_dir=output_dir)

    assert Path(persisted["dry_run_report_path"]).exists()
    assert Path(persisted["dry_run_by_date_path"]).exists()
    assert Path(persisted["dry_run_by_nm_id_path"]).exists()


def test_apply_insert_missing_skips_empty_rows_and_runs_post_apply_hooks(tmp_path: Path, monkeypatch) -> None:
    normalized_dir = tmp_path / "normalized"
    normalized_dir.mkdir(parents=True, exist_ok=True)
    with (normalized_dir / "funnel_day.csv").open("w", encoding="utf-8", newline="") as file_handle:
        writer = csv.DictWriter(
            file_handle,
            fieldnames=[
                "date",
                "nm_id",
                "supplier_article",
                "impressions",
                "card_clicks",
                "cart_count",
                "order_count",
                "order_sum",
                "ctr",
                "add_to_cart_conversion",
                "cart_to_order_conversion",
                "local_orders_percent",
                "avg_delivery_time",
            ],
        )
        writer.writeheader()
        writer.writerow(
            {
                "date": "2026-06-18",
                "nm_id": "1001",
                "supplier_article": "art-1",
                "impressions": "100",
                "card_clicks": "10",
                "cart_count": "2",
                "order_count": "1",
                "order_sum": "",
                "ctr": "10",
                "add_to_cart_conversion": "5",
                "cart_to_order_conversion": "50",
                "local_orders_percent": "",
                "avg_delivery_time": "",
            }
        )
        writer.writerow(
            {
                "date": "2026-06-19",
                "nm_id": "1002",
                "supplier_article": "art-2",
                "impressions": "",
                "card_clicks": "",
                "cart_count": "",
                "order_count": "",
                "order_sum": "",
                "ctr": "",
                "add_to_cart_conversion": "",
                "cart_to_order_conversion": "",
                "local_orders_percent": "",
                "avg_delivery_time": "",
            }
        )

    monkeypatch.setattr(
        "src.importers.ivan_current_importer._load_active_products",
        lambda: {
            1001: {"nm_id": 1001, "supplier_article": "art-1"},
            1002: {"nm_id": 1002, "supplier_article": "art-2"},
        },
    )

    @contextmanager
    def _dummy_session_scope():
        yield object()

    monkeypatch.setattr("src.importers.ivan_current_importer.session_scope", _dummy_session_scope)
    monkeypatch.setattr("src.importers.ivan_current_importer._load_existing_funnel_keys", lambda session, rows: set())
    monkeypatch.setattr("src.importers.ivan_current_importer._insert_fact_funnel_day_rows", lambda session, rows: len(rows))
    monkeypatch.setattr(
        "src.importers.ivan_current_importer.build_mart_total_report",
        lambda date_from, date_to, version="v2": {"rows_in_db": 1, "date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
    )
    monkeypatch.setattr(
        "src.importers.ivan_current_importer.export_streamlit_v1_dataset",
        lambda date_from, date_to: {"total_rows": 1, "date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
    )
    monkeypatch.setattr(
        "src.importers.ivan_current_importer._build_post_apply_readback_summary",
        lambda inserted_rows, rows_inserted: {
            "rows_inserted": rows_inserted,
            "inserted_date_min": "2026-06-18",
            "inserted_date_max": "2026-06-18",
            "inserted_nm_id_count": 1,
            "duplicate_date_nm_id_keys": 0,
            "existing_api_rows_overwritten": 0,
        },
    )

    summary = apply_ivan_current_insert_missing(
        source_dir=normalized_dir,
        only_active_products=True,
        mode="insert-missing",
    )

    assert summary["write_executed"] is True
    assert summary["skipped_empty_rows"] == 1
    assert summary["rows_to_insert"] == 1
    assert summary["rows_inserted"] == 1
    assert summary["mart_rebuild_summary"]["rows_in_db"] == 1
    assert summary["streamlit_export_summary"]["total_rows"] == 1
