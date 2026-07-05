from __future__ import annotations

from datetime import UTC, datetime
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.clients.wb_content_client import WBContentClient
from src.db.models import DimProductSize
from src.db.session import session_scope, upsert_rows
from src.tracked_products import get_tracked_nm_ids
from src.utils.logger import get_logger


logger = get_logger("product_size_loader")

DIM_PRODUCT_SIZE_CONFLICT_COLUMNS = ("nm_id", "chrt_id", "barcode")
DIM_PRODUCT_SIZE_SOURCE_STATUS = "WB_CONTENT_API"


def _clean_text(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


def _clean_barcode(value: Any) -> str | None:
    cleaned = _clean_text(value)
    if cleaned is None:
        return None
    return cleaned.replace(" ", "")


def _to_int(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def normalize_wb_content_size_rows(
    cards: Sequence[Mapping[str, Any]],
    *,
    nm_ids: Iterable[int] | None = None,
    source_status: str = DIM_PRODUCT_SIZE_SOURCE_STATUS,
) -> list[dict[str, Any]]:
    target_nm_ids = {int(nm_id) for nm_id in nm_ids} if nm_ids else None
    normalized_rows: dict[tuple[int, int, str | None], dict[str, Any]] = {}

    for card in cards:
        normalized_card = WBContentClient.normalize_card(dict(card))
        if not normalized_card:
            continue

        nm_id = int(normalized_card["nm_id"])
        if target_nm_ids is not None and nm_id not in target_nm_ids:
            continue

        sizes = normalized_card.get("sizes") or []
        if not isinstance(sizes, list):
            continue

        for size in sizes:
            if not isinstance(size, Mapping):
                continue
            chrt_id = _to_int(size.get("chrtID") or size.get("chrtId") or size.get("sizeID"))
            if chrt_id is None:
                continue

            size_name = _clean_text(size.get("wbSize") or size.get("sizeName") or size.get("size"))
            tech_size = _clean_text(size.get("techSize") or size.get("techSizeName"))
            skus = size.get("skus")
            if not isinstance(skus, list):
                skus = []
            barcodes = [_clean_barcode(item) for item in skus if _clean_barcode(item) is not None]
            if not barcodes:
                barcodes = [None]

            for barcode in barcodes:
                dedupe_key = (nm_id, chrt_id, barcode)
                normalized_rows[dedupe_key] = {
                    "nm_id": nm_id,
                    "chrt_id": chrt_id,
                    "barcode": barcode,
                    "size_name": size_name,
                    "tech_size": tech_size,
                    "source_status": source_status,
                }

    return list(normalized_rows.values())


def load_dim_product_size_rows(nm_ids: Sequence[int] | None = None) -> list[dict[str, Any]]:
    with session_scope() as session:
        stmt = select(
            DimProductSize.nm_id,
            DimProductSize.chrt_id,
            DimProductSize.barcode,
            DimProductSize.size_name,
            DimProductSize.tech_size,
            DimProductSize.source_status,
            DimProductSize.updated_at,
        )
        if nm_ids:
            stmt = stmt.where(DimProductSize.nm_id.in_([int(nm_id) for nm_id in nm_ids]))
        stmt = stmt.order_by(DimProductSize.nm_id, DimProductSize.chrt_id, DimProductSize.barcode)
        rows = session.execute(stmt).all()
        return [
            {
                "nm_id": int(row.nm_id),
                "chrt_id": int(row.chrt_id),
                "barcode": row.barcode,
                "size_name": row.size_name,
                "tech_size": row.tech_size,
                "source_status": row.source_status,
                "updated_at": row.updated_at,
            }
            for row in rows
        ]


def upsert_dim_product_size_rows(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows: list[dict[str, Any]] = []
    updated_at = datetime.now(UTC)
    for row in rows:
        nm_id = _to_int(row.get("nm_id"))
        chrt_id = _to_int(row.get("chrt_id"))
        if nm_id is None or chrt_id is None:
            continue
        prepared_rows.append(
            {
                "nm_id": nm_id,
                "chrt_id": chrt_id,
                "barcode": _clean_barcode(row.get("barcode")),
                "size_name": _clean_text(row.get("size_name")),
                "tech_size": _clean_text(row.get("tech_size")),
                "source_status": _clean_text(row.get("source_status")) or DIM_PRODUCT_SIZE_SOURCE_STATUS,
                "updated_at": updated_at,
            }
        )
    if not prepared_rows:
        return 0
    upsert_rows(
        session=session,
        model=DimProductSize,
        rows=prepared_rows,
        conflict_columns=DIM_PRODUCT_SIZE_CONFLICT_COLUMNS,
    )
    return len(prepared_rows)


def refresh_dim_product_size(
    *,
    nm_ids: Sequence[int] | None = None,
    write_db: bool = False,
    client: WBContentClient | None = None,
) -> dict[str, Any]:
    target_nm_ids = [int(nm_id) for nm_id in (nm_ids or get_tracked_nm_ids())]
    wb_client = client or WBContentClient()
    cards = wb_client.fetch_cards_catalog(limit=100, max_pages=100)
    rows = normalize_wb_content_size_rows(cards, nm_ids=target_nm_ids)

    rows_written = 0
    if write_db and rows:
        with session_scope() as session:
            rows_written = upsert_dim_product_size_rows(session, rows)

    distinct_nm_ids = sorted({int(row["nm_id"]) for row in rows})
    distinct_chrt_ids = sorted({int(row["chrt_id"]) for row in rows})

    logger.info(
        "Prepared dim_product_size rows: %s rows for %s products",
        len(rows),
        len(distinct_nm_ids),
    )

    return {
        "success": True,
        "requested_nm_ids_count": len(target_nm_ids),
        "cards_fetched": len(cards),
        "rows_prepared": len(rows),
        "rows_written": rows_written,
        "distinct_nm_ids": len(distinct_nm_ids),
        "distinct_chrt_ids": len(distinct_chrt_ids),
    }
