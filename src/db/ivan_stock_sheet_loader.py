from __future__ import annotations

import re
from datetime import date, datetime
from decimal import Decimal
from typing import Any, Mapping, Sequence, Optional
from sqlalchemy import select, func
from sqlalchemy.orm import Session
from src.config.settings import settings
from src.clients.google_sheets_client import GoogleSheetsClient
from src.db.models import FactIvanStockSheetDay
from src.db.session import session_scope, upsert_rows
from src.utils.logger import get_logger

logger = get_logger("ivan_stock_sheet_loader")


def parse_row_nomenclature(text: str) -> tuple[str, Optional[str], str]:
    if not text:
        return "", None, ""
    
    text_str = str(text).strip()
    
    barcode = ""
    barcode_match = re.search(r',\s*(\d+)\s*$', text_str)
    if barcode_match:
        barcode = barcode_match.group(1)
        main_part = text_str[:barcode_match.start()].strip()
    else:
        main_part = text_str.rstrip(',').strip()
        
    size_name = ""
    size_match = re.search(r'Размер:\s*(.*?)(?=\s*Цвет:|,\s*$|$)', main_part)
    if size_match:
        size_name = size_match.group(1).strip()
        
    color_name = None
    color_match = re.search(r'Цвет:\s*(.*?)(?=\s*Размер:|,\s*$|$)', main_part)
    if color_match:
        color_name = color_match.group(1).strip()
        
    return size_name, color_name, barcode


def parse_quantity(val: Any) -> Optional[Decimal]:
    if val is None:
        return None
    val_str = str(val).strip()
    if not val_str:
        return None
    val_str = val_str.replace(" ", "").replace("\xa0", "")
    val_str = val_str.replace(",", ".")
    try:
        return Decimal(val_str)
    except Exception:
        return None


def load_ivan_stock_sheet(
    *,
    sheet_id: Optional[str] = None,
    write_db: bool = False,
) -> dict[str, Any]:
    resolved_sheet_id = sheet_id or settings.vvbromo_google_sheet_id or "1MxVBCfKX6WSqU5_q-r9h_bFhQ61h3VxmgLNyYY9RcEs"
    creds_path = settings.google_application_credentials or "credentials.json"
    
    logger.info(f"Connecting to Google Sheets for stock load: {resolved_sheet_id}")
    gs_client = GoogleSheetsClient(credentials_path=creds_path, spreadsheet_id=resolved_sheet_id)
    
    titles = gs_client.get_worksheet_titles(resolved_sheet_id)
    if not titles:
        raise RuntimeError("Failed to fetch worksheets titles.")
        
    target_sheet = None
    for t in titles:
        if t.strip().lower() == "остатки":
            target_sheet = t
            break
            
    if not target_sheet:
        raise RuntimeError("Worksheet 'Остатки' not found.")
        
    all_values = gs_client.read_range(resolved_sheet_id, f"{target_sheet}!A1:Z")
    if not all_values:
        raise RuntimeError("No data retrieved from sheet 'Остатки'.")
        
    total_rows = len(all_values)
    
    # 1. Date extraction
    stock_date = None
    date_regex = r'\b\d{2}\.\d{2}\.\d{4}\b'
    for r in all_values[:5]:
        for cell in r:
            if cell:
                cell_str = str(cell).strip()
                date_match = re.search(date_regex, cell_str)
                if date_match:
                    d_str = date_match.group(0)
                    day, month, year = map(int, d_str.split('.'))
                    stock_date = date(year, month, day)
                    break
        if stock_date:
            break
            
    if not stock_date:
        raise RuntimeError("Stock date not found in the sheet header.")
        
    # Find headers row
    header_idx = -1
    for idx, r in enumerate(all_values[:10]):
        r_lower = [str(cell).strip().lower() for cell in r if cell]
        if any("номенклатура" in cell or "количество" in cell for cell in r_lower):
            header_idx = idx
            break
            
    if header_idx == -1:
        header_idx = 0
        
    rows_to_save = []
    skipped_no_nm_id = 0
    data_rows = 0
    quantity_sum_total = Decimal("0")
    
    for idx in range(header_idx + 1, len(all_values)):
        row = all_values[idx]
        if not row:
            continue
            
        col1 = str(row[0]).strip() if len(row) > 0 else ""
        col2 = str(row[1]).strip() if len(row) > 1 else ""
        col3 = str(row[2]).strip() if len(row) > 2 else ""
        
        # Skip completely empty rows
        if not col1 and not col2 and not col3:
            continue
            
        data_rows += 1
        
        nm_id_raw = col2.replace(" ", "").replace("\xa0", "").strip()
        if not nm_id_raw:
            skipped_no_nm_id += 1
            continue
            
        try:
            nm_id = int(nm_id_raw)
        except ValueError:
            skipped_no_nm_id += 1
            continue
            
        qty = parse_quantity(col3)
        if qty is None:
            qty = Decimal("0")
            
        quantity_sum_total += qty
        
        size_name, color_name, barcode = parse_row_nomenclature(col1)
        
        rows_to_save.append({
            "stock_date": stock_date,
            "nm_id": nm_id,
            "size_name": size_name,  # normalized to '' in function if None
            "barcode": barcode,      # normalized to '' in function if None
            "color_name": color_name,
            "quantity": qty,
            "nomenclature_raw": col1,
            "source_sheet": "Остатки",
            "raw_row": row
        })
        
    rows_inserted = 0
    if write_db and rows_to_save:
        with session_scope() as session:
            rows_inserted = upsert_rows(
                session=session,
                model=FactIvanStockSheetDay,
                rows=rows_to_save,
                conflict_columns=("stock_date", "nm_id", "size_name", "barcode"),
            )
            
    distinct_nm_ids = {r["nm_id"] for r in rows_to_save}
    distinct_nm_id_sizes = {(r["nm_id"], r["size_name"]) for r in rows_to_save}
    
    rows_with_barcode = sum(1 for r in rows_to_save if r["barcode"])
    return {
        "success": True,
        "stock_date": stock_date,
        "total_rows": total_rows,
        "data_rows": data_rows,
        "rows_with_nm_id": len(rows_to_save),
        "skipped_no_nm_id": skipped_no_nm_id,
        "rows_with_barcode": rows_with_barcode,
        "distinct_nm_id": len(distinct_nm_ids),
        "distinct_nm_id_size": len(distinct_nm_id_sizes),
        "size_level_rows": len(rows_to_save),
        "product_level_rows": len(distinct_nm_ids),
        "quantity_sum_total": int(quantity_sum_total) if quantity_sum_total % 1 == 0 else float(quantity_sum_total),
        "rows_inserted": rows_inserted,
    }


def load_ivan_stock_size_level(stock_date: Optional[date] = None) -> list[dict[str, Any]]:
    with session_scope() as session:
        if stock_date is None:
            latest_stmt = select(func.max(FactIvanStockSheetDay.stock_date))
            stock_date = session.execute(latest_stmt).scalar()
            if stock_date is None:
                return []
                
        stmt = select(
            FactIvanStockSheetDay.stock_date,
            FactIvanStockSheetDay.nm_id,
            FactIvanStockSheetDay.size_name,
            FactIvanStockSheetDay.barcode,
            FactIvanStockSheetDay.color_name,
            FactIvanStockSheetDay.quantity,
            FactIvanStockSheetDay.nomenclature_raw,
        ).where(FactIvanStockSheetDay.stock_date == stock_date)
        
        results = session.execute(stmt).all()
        return [
            {
                "stock_date": r.stock_date,
                "nm_id": r.nm_id,
                "size_name": r.size_name,
                "barcode": r.barcode,
                "color_name": r.color_name,
                "quantity": int(r.quantity) if r.quantity % 1 == 0 else float(r.quantity),
                "nomenclature_raw": r.nomenclature_raw,
            }
            for r in results
        ]


def load_ivan_stock_product_level(stock_date: Optional[date] = None) -> list[dict[str, Any]]:
    with session_scope() as session:
        if stock_date is None:
            latest_stmt = select(func.max(FactIvanStockSheetDay.stock_date))
            stock_date = session.execute(latest_stmt).scalar()
            if stock_date is None:
                return []
                
        stmt = select(
            FactIvanStockSheetDay.stock_date,
            FactIvanStockSheetDay.nm_id,
            func.sum(FactIvanStockSheetDay.quantity).label("ivan_stock_qty"),
            func.count(func.distinct(FactIvanStockSheetDay.size_name)).label("sizes_count"),
            func.count(func.distinct(FactIvanStockSheetDay.barcode)).label("barcodes_count"),
        ).where(FactIvanStockSheetDay.stock_date == stock_date).group_by(
            FactIvanStockSheetDay.stock_date,
            FactIvanStockSheetDay.nm_id
        )
        
        results = session.execute(stmt).all()
        return [
            {
                "stock_date": r.stock_date,
                "nm_id": r.nm_id,
                "ivan_stock_qty": int(r.ivan_stock_qty) if r.ivan_stock_qty % 1 == 0 else float(r.ivan_stock_qty),
                "sizes_count": r.sizes_count,
                "barcodes_count": r.barcodes_count,
            }
            for r in results
        ]
