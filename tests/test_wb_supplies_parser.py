from __future__ import annotations

from decimal import Decimal

from src.services.wb_supplies.sync_service import (
    detect_warehouse_name,
    normalize_barcode,
    normalize_nm_id,
    normalize_vendor_code,
    parse_supply_sheet,
)


def test_detect_warehouse_name_uses_file_name() -> None:
    assert detect_warehouse_name("Шушары.xlsx", "Лист1") == "Шушары"


def test_parse_supply_sheet_maps_header_variants_and_normalizes_values() -> None:
    rows = [
        ["какой-то заголовок"],
        ["Артикул ВБ", "ШК", "Vendor code", "Название товара", "Кол-во", "Комментарий"],
        ["123456.0", "2037000012345.0", " art-01 ", "Товар 1", "10", "ok"],
        ["", "2037000012346", "art-02", "Товар 2", "5,5", ""],
    ]

    parsed = parse_supply_sheet(
        google_file_id="file-1",
        google_file_name="Шушары.xlsx",
        sheet_name="Лист1",
        rows=rows,
    )

    assert parsed["detected_warehouse"] == "Шушары"
    assert parsed["warnings"] == []
    assert len(parsed["parsed_rows"]) == 2
    assert parsed["parsed_rows"][0]["nm_id"] == 123456
    assert parsed["parsed_rows"][0]["barcode"] == "2037000012345"
    assert parsed["parsed_rows"][0]["vendor_code"] == "art-01"
    assert parsed["parsed_rows"][0]["supply_quantity"] == Decimal("10")
    assert parsed["parsed_rows"][1]["nm_id"] is None
    assert parsed["parsed_rows"][1]["barcode"] == "2037000012346"
    assert parsed["parsed_rows"][1]["supply_quantity"] == Decimal("5.5")


def test_supply_normalizers_handle_common_formats() -> None:
    assert normalize_nm_id("1469020168.0") == 1469020168
    assert normalize_barcode(" 2037 0000 12345 ") == "2037000012345"
    assert normalize_vendor_code(" art-77 ") == "art-77"
