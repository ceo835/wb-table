from __future__ import annotations

from decimal import Decimal

from openpyxl import Workbook

from src.importers.orders_geography_importer import (
    ORDERS_GEOGRAPHY_CONFLICT_COLUMNS,
    build_orders_geography_summary,
    parse_orders_geography_xlsx,
    prepare_orders_geography_upsert_rows,
)


def _build_orders_geography_workbook(path) -> None:
    workbook = Workbook()
    info_sheet = workbook.active
    info_sheet.title = "Общая информация"
    info_sheet["A1"] = "Период"
    info_sheet["B1"] = "07.06.2026"

    data_sheet = workbook.create_sheet("Детальные данные")
    headers = [
        "Артикул продавца",
        "Название",
        "Артикул WB",
        "Предмет",
        "Бренд",
        "Регион",
        "Время доставки",
        "Итого заказов, шт",
        "Итого заказов по товарам локально, шт",
        "Итого заказов по товарам не локально, шт",
        "Итого заказы по товарам не локально, %",
        "Заказы со склада WB локально, шт",
        "Заказы со склада WB не локально, шт",
        "Заказы со склада WB не локально, %",
        "Заказы Маркетплейс локально, шт",
        "Заказы Маркетплейс не локально, шт",
        "Заказы Маркетплейс не локально, %",
        "Остатки склад WB, шт",
        "Остатки МП, шт",
    ]
    data_sheet.append(headers)
    data_sheet.append(
        [
            "BlackWOM5",
            "Трусы",
            197330807,
            "Трусы",
            "PALEY",
            "Москва",
            "-",
            10,
            4,
            6,
            0.96,
            2,
            8,
            0.8,
            1,
            9,
            0.9,
            "",
            17,
        ]
    )
    data_sheet["K2"].number_format = "0.00%"
    data_sheet["N2"].number_format = "0.00%"
    data_sheet["Q2"].number_format = "0.00%"
    workbook.save(path)


def test_parse_orders_geography_xlsx_detects_sheet_date_and_percent_formats(tmp_path):
    file_path = tmp_path / "orders_geography_export.xlsx"
    _build_orders_geography_workbook(file_path)

    parsed = parse_orders_geography_xlsx(str(file_path))

    assert parsed.detected_date.isoformat() == "2026-06-07"
    assert parsed.sheet_name == "Детальные данные"
    assert parsed.rows_read == 1
    assert not parsed.missing_required_columns
    row = parsed.rows_normalized[0]
    assert row["nm_id"] == 197330807
    assert row["region"] == "Москва"
    assert row["orders_nonlocal_percent"] == Decimal("96.00")
    assert row["wb_stock_orders_nonlocal_percent"] == Decimal("80.0")
    assert row["mp_orders_nonlocal_percent"] == Decimal("90.0")
    assert row["delivery_time"] is None
    assert row["delivery_time_text"] == "-"
    assert row["wb_stock_qty"] is None
    assert row["source_status"] == "CSV_EXPORT"
    assert row["data_status"] == "REAL_FILE"


def test_parse_orders_geography_xlsx_releases_file_handle(tmp_path):
    file_path = tmp_path / "orders_geography_export.xlsx"
    _build_orders_geography_workbook(file_path)

    parse_orders_geography_xlsx(str(file_path))
    file_path.unlink()

    assert not file_path.exists()


def test_prepare_orders_geography_upsert_rows_deduplicates_by_period_nm_region():
    rows = prepare_orders_geography_upsert_rows(
        [
            {
                "period_start": "2026-06-07",
                "period_end": "2026-06-07",
                "date": "2026-06-07",
                "nm_id": 197330807,
                "region": "Москва",
                "orders_total_qty": Decimal("1"),
            },
            {
                "period_start": "2026-06-07",
                "period_end": "2026-06-07",
                "date": "2026-06-07",
                "nm_id": 197330807,
                "region": "Москва",
                "orders_total_qty": Decimal("3"),
            },
        ]
    )
    assert ORDERS_GEOGRAPHY_CONFLICT_COLUMNS == ("period_start", "period_end", "nm_id", "region")
    assert len(rows) == 1
    assert rows[0]["orders_total_qty"] == Decimal("3")
    assert rows[0]["loaded_at"] is not None


def test_build_orders_geography_summary_includes_target_table_and_source_status(tmp_path):
    file_path = tmp_path / "orders_geography_export.xlsx"
    _build_orders_geography_workbook(file_path)

    parsed = parse_orders_geography_xlsx(str(file_path))
    summary = build_orders_geography_summary(parsed)

    assert summary["target_table"] == "fact_localization_region_day"
    assert summary["source_status"] == "CSV_EXPORT"
