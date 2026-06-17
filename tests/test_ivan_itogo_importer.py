from __future__ import annotations

from decimal import Decimal
from pathlib import Path
from contextlib import contextmanager

from src.importers.ivan_itogo_importer import (
    apply_ivan_itogo_insert_missing,
    build_ivan_itogo_audit_summary,
    build_ivan_itogo_import_dry_run_summary,
    build_ivan_itogo_insert_missing_summary,
    parse_ivan_itogo_csv,
)


def _write_csv(tmp_path: Path, content: str) -> Path:
    file_path = tmp_path / "ivan_itogo_sample.csv"
    file_path.write_text(content, encoding="utf-8-sig")
    return file_path


def test_parse_ivan_itogo_csv_uses_first_safe_duplicate_headers(tmp_path: Path) -> None:
    file_path = _write_csv(
        tmp_path,
        "\n".join(
            [
                " Артикул продавца,Артикул WB, Дата, Показы, Переходы в карточку, Положили в корзину,\" Заказали, шт\",СиТиАр, CTR,\" Конверсия в корзину, %\",\"Конверсия в заказ, %\",\" Заказали на сумму, ₽\", Локальные заказы, %, Показы, Дата",
                "art-1,1001, 2026-05-23,1 022,100,20,5,,9.78,20,25,12345,72,9999, 2026-01-01",
            ]
        ),
    )

    parsed = parse_ivan_itogo_csv(file_path)

    assert parsed.rows_read == 1
    row = parsed.rows_normalized[0]
    assert row["supplier_article"] == "art-1"
    assert row["nm_id"] == 1001
    assert row["date"].isoformat() == "2026-05-23"
    assert row["impressions"] == Decimal("1022")
    assert row["ctr"] == Decimal("9.78")
    assert parsed.mapped_columns["impressions"]["indexes"][0] == 4
    assert parsed.mapped_columns["date"]["indexes"][0] == 3


def test_audit_summary_reports_duplicate_date_nm_id_keys(tmp_path: Path) -> None:
    file_path = _write_csv(
        tmp_path,
        "\n".join(
            [
                " Артикул продавца,Артикул WB, Дата, Показы, Переходы в карточку, Положили в корзину,\" Заказали, шт\", CTR",
                "art-1,1001,2026-05-23,100,10,2,1,10",
                "art-1,1001,2026-05-23,100,10,2,1,10",
            ]
        ),
    )

    parsed = parse_ivan_itogo_csv(file_path)
    summary = build_ivan_itogo_audit_summary(parsed)

    assert summary["duplicate_date_nm_id_keys"] == 1
    assert summary["valid_date_nm_id_rows"] == 1
    assert summary["rows_with_impressions"] == 2


def test_import_dry_run_handles_missing_db_without_writes(tmp_path: Path, monkeypatch) -> None:
    file_path = _write_csv(
        tmp_path,
        "\n".join(
            [
                " Артикул продавца,Артикул WB, Дата, Показы, CTR,\" Заказали, шт\"",
                "art-1,1001,2026-05-23,100,10,1",
            ]
        ),
    )

    parsed = parse_ivan_itogo_csv(file_path)

    def _failing_session_scope():
        raise RuntimeError("db unavailable")
        yield

    monkeypatch.setattr("src.importers.ivan_itogo_importer.session_scope", _failing_session_scope)

    summary = build_ivan_itogo_import_dry_run_summary(parsed)

    assert summary["mode"] == "dry-run"
    assert summary["write_executed"] is False
    assert summary["db_check_status"] == "db_unavailable"
    assert summary["potential_fill_impressions"] == 0
    assert summary["potential_fill_ctr"] == 0


def test_insert_missing_summary_skips_existing_keys_and_reports_missing_dim_products(tmp_path: Path, monkeypatch) -> None:
    file_path = _write_csv(
        tmp_path,
        "\n".join(
            [
                " Артикул продавца,Артикул WB, Дата, Показы, CTR,\" Заказали, шт\"",
                "art-1,1001,2026-05-23,100,10,1",
                "art-2,1002,2026-05-24,200,12,2",
            ]
        ),
    )
    parsed = parse_ivan_itogo_csv(file_path)

    @contextmanager
    def _dummy_session_scope():
        yield object()

    monkeypatch.setattr("src.importers.ivan_itogo_importer.session_scope", _dummy_session_scope)
    monkeypatch.setattr(
        "src.importers.ivan_itogo_importer._build_db_fill_coverage",
        lambda parsed, scope_rows=None: {"db_check_status": "ok", "potential_fill_impressions": 0, "potential_fill_ctr": 0},
    )
    monkeypatch.setattr("src.importers.ivan_itogo_importer.get_tracked_nm_ids", lambda: [1001, 1002])
    monkeypatch.setattr(
        "src.importers.ivan_itogo_importer._load_existing_funnel_keys",
        lambda session, rows: {(parsed.rows_normalized[0]["date"], parsed.rows_normalized[0]["nm_id"])},
    )
    monkeypatch.setattr(
        "src.importers.ivan_itogo_importer._load_known_dim_product_nm_ids",
        lambda session, nm_ids: {1001},
    )

    summary = build_ivan_itogo_insert_missing_summary(parsed, scope="all")

    assert summary["db_check_status"] == "ok"
    assert summary["rows_planned_for_insert"] == 1
    assert summary["rows_skipped_existing_keys"] == 1
    assert summary["rows_with_impressions_planned"] == 1
    assert summary["nm_id_not_found_in_dim_product_count"] == 1
    assert summary["nm_id_not_found_in_dim_product"] == [1002]
    assert summary["insert_dates"] == ["2026-05-24"]


def test_apply_insert_missing_executes_insert_and_rebuild_hooks(tmp_path: Path, monkeypatch) -> None:
    file_path = _write_csv(
        tmp_path,
        "\n".join(
            [
                " Артикул продавца,Артикул WB, Дата, Показы, CTR,\" Заказали, шт\"",
                "art-1,1001,2026-05-23,100,10,1",
            ]
        ),
    )
    parsed = parse_ivan_itogo_csv(file_path)

    @contextmanager
    def _dummy_session_scope():
        yield object()

    monkeypatch.setattr("src.importers.ivan_itogo_importer.session_scope", _dummy_session_scope)
    monkeypatch.setattr(
        "src.importers.ivan_itogo_importer._build_db_fill_coverage",
        lambda parsed, scope_rows=None: {"db_check_status": "ok", "potential_fill_impressions": 0, "potential_fill_ctr": 0},
    )
    monkeypatch.setattr("src.importers.ivan_itogo_importer.get_tracked_nm_ids", lambda: [1001])
    monkeypatch.setattr("src.importers.ivan_itogo_importer._load_existing_funnel_keys", lambda session, rows: set())
    monkeypatch.setattr("src.importers.ivan_itogo_importer._load_known_dim_product_nm_ids", lambda session, nm_ids: {1001})
    monkeypatch.setattr("src.importers.ivan_itogo_importer._insert_fact_funnel_day_rows", lambda session, rows: len(rows))
    monkeypatch.setattr(
        "src.importers.ivan_itogo_importer.build_mart_total_report",
        lambda date_from, date_to, version="v2": {"rows_in_db": 1, "date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
    )
    monkeypatch.setattr(
        "src.importers.ivan_itogo_importer.export_streamlit_v1_dataset",
        lambda date_from, date_to: {"total_rows": 1, "date_from": date_from.isoformat(), "date_to": date_to.isoformat()},
    )

    summary = apply_ivan_itogo_insert_missing(parsed, scope="all")

    assert summary["write_executed"] is True
    assert summary["rows_inserted"] == 1
    assert summary["rows_planned_for_insert"] == 1
    assert summary["mart_rebuild_summary"]["rows_in_db"] == 1
    assert summary["streamlit_export_summary"]["total_rows"] == 1


def test_insert_missing_summary_tracked_scope_skips_nm_ids_outside_tracked(tmp_path: Path, monkeypatch) -> None:
    file_path = _write_csv(
        tmp_path,
        "\n".join(
            [
                " Артикул продавца,Артикул WB, Дата, Показы, CTR,\" Заказали, шт\"",
                "art-1,1001,2026-05-23,100,10,1",
                "art-2,1002,2026-05-24,200,12,2",
            ]
        ),
    )
    parsed = parse_ivan_itogo_csv(file_path)

    @contextmanager
    def _dummy_session_scope():
        yield object()

    monkeypatch.setattr("src.importers.ivan_itogo_importer.session_scope", _dummy_session_scope)
    monkeypatch.setattr(
        "src.importers.ivan_itogo_importer._build_db_fill_coverage",
        lambda parsed, scope_rows=None: {"db_check_status": "ok", "potential_fill_impressions": 0, "potential_fill_ctr": 0},
    )
    monkeypatch.setattr("src.importers.ivan_itogo_importer.get_tracked_nm_ids", lambda: [1001])
    monkeypatch.setattr("src.importers.ivan_itogo_importer._load_existing_funnel_keys", lambda session, rows: set())
    monkeypatch.setattr("src.importers.ivan_itogo_importer._load_known_dim_product_nm_ids", lambda session, nm_ids: {1001})

    summary = build_ivan_itogo_insert_missing_summary(parsed, scope="tracked")

    assert summary["scope"] == "tracked"
    assert summary["scope_valid_date_nm_id_rows"] == 1
    assert summary["rows_skipped_out_of_scope"] == 1
    assert summary["skipped_scope_nm_ids"] == [1002]
    assert summary["rows_planned_for_insert"] == 1
