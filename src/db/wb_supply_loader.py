from __future__ import annotations

from decimal import Decimal
from typing import Any, Sequence

from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.db.models import WbSupplyRow, WbSupplySourceFile
from src.db.session import session_scope, upsert_rows


def _normalize_numeric(value: Decimal | int | float | None) -> int | float | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return int(value) if value % 1 == 0 else float(value)
    return value


def delete_wb_supply_rows_for_file(session: Session, google_file_id: str) -> int:
    result = session.execute(delete(WbSupplyRow).where(WbSupplyRow.google_file_id == google_file_id))
    return max(result.rowcount or 0, 0)


def replace_wb_supply_file_rows(session: Session, google_file_id: str, rows: Sequence[dict[str, Any]]) -> dict[str, int]:
    rows_deleted = delete_wb_supply_rows_for_file(session, google_file_id)
    rows_upserted = upsert_rows(
        session=session,
        model=WbSupplyRow,
        rows=rows,
        conflict_columns=("google_file_id", "sheet_name", "row_number"),
    ) if rows else 0
    return {"rows_deleted": rows_deleted, "rows_upserted": rows_upserted}


def upsert_wb_supply_source_file(session: Session, row: dict[str, Any]) -> int:
    return upsert_rows(
        session=session,
        model=WbSupplySourceFile,
        rows=[row],
        conflict_columns=("google_file_id",),
    )


def load_wb_supply_product_level() -> list[dict[str, Any]]:
    with session_scope() as session:
        stmt = (
            select(
                WbSupplyRow.nm_id,
                WbSupplyRow.vendor_code,
                WbSupplyRow.barcode,
                func.sum(WbSupplyRow.supply_quantity).label("wb_supply_qty"),
            )
            .group_by(WbSupplyRow.nm_id, WbSupplyRow.vendor_code, WbSupplyRow.barcode)
            .order_by(WbSupplyRow.nm_id, WbSupplyRow.vendor_code, WbSupplyRow.barcode)
        )
        rows = session.execute(stmt).all()
        return [
            {
                "nm_id": row.nm_id,
                "vendor_code": row.vendor_code,
                "barcode": row.barcode,
                "wb_supply_qty": _normalize_numeric(row.wb_supply_qty),
            }
            for row in rows
        ]


def count_wb_supply_rows() -> int:
    with session_scope() as session:
        return int(session.execute(select(func.count()).select_from(WbSupplyRow)).scalar() or 0)
