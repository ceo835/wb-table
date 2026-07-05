from __future__ import annotations

import pytest
from datetime import date
from decimal import Decimal
from unittest.mock import MagicMock, patch

from src.db.ivan_stock_sheet_loader import (
    parse_row_nomenclature,
    parse_quantity,
    load_ivan_stock_sheet,
    load_ivan_stock_size_level,
    load_ivan_stock_product_level,
)
from src.db.models import FactIvanStockSheetDay


def test_parse_quantity() -> None:
    assert parse_quantity("1 169,000") == Decimal("1169")
    assert parse_quantity("-20") == Decimal("-20")
    assert parse_quantity("  2 191,000  ") == Decimal("2191")
    assert parse_quantity("0") == Decimal("0")
    assert parse_quantity(None) is None
    assert parse_quantity("") is None


def test_parse_row_nomenclature() -> None:
    # Size, Color, Barcode all present
    size, color, barcode = parse_row_nomenclature(
        "Трусы детские Размер: 10/11 Цвет: Mix животные, 2037074255720"
    )
    assert size == "10/11"
    assert color == "Mix животные"
    assert barcode == "2037074255720"

    # No color
    size, color, barcode = parse_row_nomenclature(
        "Трусы женские Размер: 54-56 Корона Сам, 123124"
    )
    assert size == "54-56 Корона Сам"
    assert color is None
    assert barcode == "123124"

    # No barcode (digits after comma missing)
    size, color, barcode = parse_row_nomenclature(
        "Футболка детская Размер: 10 лет 140-146 Цвет: розовый,"
    )
    assert size == "10 лет 140-146"
    assert color == "розовый"
    assert barcode == ""

    # No size, no color, just barcode at the end
    size, color, barcode = parse_row_nomenclature(
        "Подарочный набор мужской 58-60 , 2042976833877"
    )
    assert size == ""
    assert color is None
    assert barcode == "2042976833877"


@patch("src.db.ivan_stock_sheet_loader.GoogleSheetsClient")
def test_load_ivan_stock_sheet_filters_and_parses(mock_sheets_client_cls) -> None:
    mock_client = MagicMock()
    mock_sheets_client_cls.return_value = mock_client
    
    mock_client.get_worksheet_titles.return_value = ["Остатки"]
    # Mock row data:
    # Row 0: Date
    # Row 1: Header
    # Row 2: Valid row
    # Row 3: Skip row (no nm_id)
    # Row 4: Valid row (negative qty)
    mock_client.read_range.return_value = [
        ["04.07.2026"],
        ["Номенклатура, Штрихкод", "Номенклатура.Артикул", "Количество"],
        ["Трусы детские Размер: 10/11 Цвет: Mix животные, 2037074255720", "134111623", "775"],
        ["Подарочный набор мужской 58-60 , 2042976833877", "", "49"],
        ["Трусы детские Размер: 00 Цвет: черные детские СОБАКИ, 2050852961309", "134111625", "-20"],
    ]

    # Run with write_db=False (dry-run)
    result = load_ivan_stock_sheet(write_db=False)
    
    assert result["success"] is True
    assert result["stock_date"] == date(2026, 7, 4)
    assert result["total_rows"] == 5
    assert result["data_rows"] == 3  # rows after header
    assert result["rows_with_nm_id"] == 2
    assert result["skipped_no_nm_id"] == 1
    assert result["distinct_nm_id"] == 2
    assert result["quantity_sum_total"] == 755  # 775 - 20 = 755
    assert result["rows_inserted"] == 0


@patch("src.db.ivan_stock_sheet_loader.session_scope")
def test_load_ivan_stock_size_level_queries(mock_session_scope) -> None:
    mock_session = MagicMock()
    mock_session_scope.return_value.__enter__.return_value = mock_session
    
    # Mock query result
    mock_row = MagicMock()
    mock_row.stock_date = date(2026, 7, 4)
    mock_row.nm_id = 134111623
    mock_row.size_name = "10/11"
    mock_row.barcode = "2037074255720"
    mock_row.color_name = "Mix животные"
    mock_row.quantity = Decimal("775.000")
    mock_row.nomenclature_raw = "Nomenclature"
    
    mock_session.execute.return_value.all.return_value = [mock_row]
    
    res = load_ivan_stock_size_level(date(2026, 7, 4))
    
    assert len(res) == 1
    assert res[0]["nm_id"] == 134111623
    assert res[0]["quantity"] == 775


@patch("src.db.ivan_stock_sheet_loader.session_scope")
def test_load_ivan_stock_product_level_aggregates(mock_session_scope) -> None:
    mock_session = MagicMock()
    mock_session_scope.return_value.__enter__.return_value = mock_session
    
    mock_row = MagicMock()
    mock_row.stock_date = date(2026, 7, 4)
    mock_row.nm_id = 134111623
    mock_row.ivan_stock_qty = Decimal("1000")
    mock_row.sizes_count = 2
    mock_row.barcodes_count = 2
    
    mock_session.execute.return_value.all.return_value = [mock_row]
    
    res = load_ivan_stock_product_level(date(2026, 7, 4))
    
    assert len(res) == 1
    assert res[0]["nm_id"] == 134111623
    assert res[0]["ivan_stock_qty"] == 1000
    assert res[0]["sizes_count"] == 2
