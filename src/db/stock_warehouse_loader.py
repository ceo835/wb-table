from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from typing import Any, Callable, Mapping, Sequence

import pandas as pd
import requests
from sqlalchemy import delete, func, select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.db.models import FactStockWarehouseSnapshot
from src.db.session import session_scope, upsert_rows
from src.tracked_products import TRACKED_PRODUCTS_PATH, get_tracked_nm_ids


WB_ANALYTICS_BASE = "https://seller-analytics-api.wildberries.ru"
WB_WAREHOUSE_STOCK_ENDPOINT = f"{WB_ANALYTICS_BASE}/api/analytics/v1/stocks-report/wb-warehouses"
WAREHOUSE_STOCK_SOURCE = "WB_ANALYTICS_WB_WAREHOUSES"
FACT_STOCK_WAREHOUSE_SNAPSHOT_CONFLICT_COLUMNS = ("snapshot_date", "nm_id", "chrt_id", "warehouse_id")
DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "processed" / "stock_warehouse_snapshots"
DEFAULT_PAGE_LIMIT = 5000

NORMALIZED_WAREHOUSE_STOCK_COLUMNS = [
    "snapshot_date",
    "nm_id",
    "chrt_id",
    "warehouse_id",
    "warehouse_name",
    "region_name",
    "stock_qty",
    "in_way_to_client",
    "in_way_from_client",
    "source",
]

AGGREGATED_WAREHOUSE_STOCK_COLUMNS = [
    "snapshot_date",
    "nm_id",
    "warehouse_id",
    "warehouse_name",
    "region_name",
    "stock_qty_total",
]


@dataclass
class WarehouseStockPageResult:
    http_status: str
    payload: Any
    error: str
    request_payload: dict[str, Any]


WarehouseStockRequester = Callable[[dict[str, Any]], WarehouseStockPageResult]


def _to_int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _coalesce(*values: Any) -> Any:
    for value in values:
        if value is not None:
            return value
    return None


def _headers() -> dict[str, str]:
    if not settings.wb_analytics_token:
        raise RuntimeError("WB_ANALYTICS_TOKEN is missing")
    return {
        "Authorization": settings.wb_analytics_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def build_wb_warehouse_stock_payload(
    *,
    snapshot_date: date,
    limit: int,
    offset: int,
    nm_ids: Sequence[int] | None = None,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "currentPeriod": {
            "start": snapshot_date.isoformat(),
            "end": snapshot_date.isoformat(),
        },
        "limit": limit,
        "offset": offset,
    }
    if nm_ids:
        payload["nmIDs"] = [int(nm_id) for nm_id in nm_ids]
    return payload


def _default_requester(timeout_seconds: int = 60) -> WarehouseStockRequester:
    session = requests.Session()

    def _request(request_payload: dict[str, Any]) -> WarehouseStockPageResult:
        response = session.post(
            WB_WAREHOUSE_STOCK_ENDPOINT,
            headers=_headers(),
            json=request_payload,
            timeout=timeout_seconds,
        )
        try:
            payload = response.json()
            error = ""
        except ValueError:
            payload = {"raw_text": response.text[:2000]}
            error = response.text[:500]
        if response.status_code != 200 and not error:
            error = json.dumps(payload, ensure_ascii=False)[:500]
        return WarehouseStockPageResult(
            http_status=str(response.status_code),
            payload=payload,
            error=error,
            request_payload=request_payload,
        )

    return _request


def _list_items(payload: Any) -> list[dict[str, Any]]:
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        items = data.get("items")
        if isinstance(items, list):
            return [item for item in items if isinstance(item, dict)]
    items = payload.get("items")
    if isinstance(items, list):
        return [item for item in items if isinstance(item, dict)]
    return []


def fetch_wb_warehouse_stock_pages(
    *,
    snapshot_date: date,
    nm_ids: Sequence[int] | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
    max_pages: int | None = None,
    requester: WarehouseStockRequester | None = None,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    request_page = requester or _default_requester()
    page_number = 0
    offset = 0
    all_items: list[dict[str, Any]] = []
    page_logs: list[dict[str, Any]] = []
    request_attempts: list[dict[str, Any]] = []
    while True:
        page_number += 1
        request_payload = build_wb_warehouse_stock_payload(
            snapshot_date=snapshot_date,
            limit=limit,
            offset=offset,
            nm_ids=nm_ids,
        )
        result = request_page(request_payload)
        request_attempts.append(
            {
                "page_number": page_number,
                "http_status": result.http_status,
                "request_payload": result.request_payload,
                "error": result.error,
            }
        )
        if result.http_status != "200":
            return all_items, {
                "status": result.http_status,
                "error": result.error,
                "pages_loaded": page_number - 1,
                "rows_raw": len(all_items),
                "page_logs": page_logs,
                "request_attempts": request_attempts,
            }

        page_items = _list_items(result.payload)
        all_items.extend(page_items)
        page_logs.append(
            {
                "page_number": page_number,
                "offset": offset,
                "limit_requested": limit,
                "items_returned": len(page_items),
            }
        )
        if not page_items or len(page_items) < limit:
            return all_items, {
                "status": result.http_status,
                "error": result.error,
                "pages_loaded": page_number,
                "rows_raw": len(all_items),
                "page_logs": page_logs,
                "request_attempts": request_attempts,
            }
        if max_pages is not None and page_number >= max_pages:
            return all_items, {
                "status": result.http_status,
                "error": "MAX_PAGES_REACHED",
                "pages_loaded": page_number,
                "rows_raw": len(all_items),
                "page_logs": page_logs,
                "request_attempts": request_attempts,
            }
        offset += limit


def normalize_wb_warehouse_stock_rows(
    raw_rows: Sequence[Mapping[str, Any]],
    snapshot_date: date,
    *,
    tracked_nm_ids: Sequence[int] | None = None,
    source: str = WAREHOUSE_STOCK_SOURCE,
) -> list[dict[str, Any]]:
    tracked_set = {int(nm_id) for nm_id in tracked_nm_ids} if tracked_nm_ids else None
    normalized_rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    for row in raw_rows:
        nm_id = _to_int_or_none(row.get("nmId") or row.get("nmID") or row.get("nm_id"))
        if nm_id is None:
            continue
        if tracked_set is not None and nm_id not in tracked_set:
            continue
        chrt_id = _to_int_or_none(row.get("chrtId") or row.get("chrtID") or row.get("chrt_id"))
        warehouse_id = _to_int_or_none(row.get("warehouseId") or row.get("warehouseID") or row.get("warehouse_id"))
        if warehouse_id is None:
            continue
        normalized_row = {
            "snapshot_date": snapshot_date.isoformat(),
            "nm_id": nm_id,
            "chrt_id": chrt_id,
            "warehouse_id": warehouse_id,
            "warehouse_name": row.get("warehouseName") or row.get("warehouse_name") or None,
            "region_name": row.get("regionName") or row.get("region_name") or None,
            "stock_qty": _to_int_or_none(_coalesce(row.get("quantity"), row.get("stock_qty"))),
            "in_way_to_client": _to_int_or_none(_coalesce(row.get("inWayToClient"), row.get("in_way_to_client"))),
            "in_way_from_client": _to_int_or_none(_coalesce(row.get("inWayFromClient"), row.get("in_way_from_client"))),
            "source": source,
        }
        dedupe_key = (
            normalized_row["snapshot_date"],
            normalized_row["nm_id"],
            normalized_row["chrt_id"],
            normalized_row["warehouse_id"],
        )
        if dedupe_key in seen:
            continue
        seen.add(dedupe_key)
        normalized_rows.append(normalized_row)
    return normalized_rows


def prepare_fact_stock_warehouse_snapshot_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: dict[tuple[Any, ...], dict[str, Any]] = {}
    for row in rows:
        snapshot_value = row.get("snapshot_date")
        snapshot_date_value = date.fromisoformat(snapshot_value) if isinstance(snapshot_value, str) else snapshot_value
        nm_id = _to_int_or_none(row.get("nm_id"))
        chrt_id = _to_int_or_none(row.get("chrt_id"))
        warehouse_id = _to_int_or_none(row.get("warehouse_id"))
        if snapshot_date_value is None or nm_id is None or warehouse_id is None:
            continue
        if chrt_id is None:
            chrt_id = -1
        prepared[(snapshot_date_value, nm_id, chrt_id, warehouse_id)] = {
            "snapshot_date": snapshot_date_value,
            "nm_id": nm_id,
            "chrt_id": chrt_id,
            "warehouse_id": warehouse_id,
            "warehouse_name": row.get("warehouse_name") or None,
            "region_name": row.get("region_name") or None,
            "stock_qty": _to_int_or_none(row.get("stock_qty")),
            "in_way_to_client": _to_int_or_none(row.get("in_way_to_client")),
            "in_way_from_client": _to_int_or_none(row.get("in_way_from_client")),
            "source": row.get("source") or WAREHOUSE_STOCK_SOURCE,
        }
    return list(prepared.values())


def aggregate_stock_warehouse_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    df = pd.DataFrame(rows)
    if df.empty:
        return pd.DataFrame(columns=AGGREGATED_WAREHOUSE_STOCK_COLUMNS).to_dict(orient="records")
    grouped = (
        df.groupby(["snapshot_date", "nm_id", "warehouse_id", "warehouse_name", "region_name"], dropna=False, as_index=False)["stock_qty"]
        .sum(min_count=1)
        .rename(columns={"stock_qty": "stock_qty_total"})
    )
    return grouped[AGGREGATED_WAREHOUSE_STOCK_COLUMNS].to_dict(orient="records")


def upsert_stock_warehouse_snapshot(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_fact_stock_warehouse_snapshot_upsert_rows(rows)
    if not prepared_rows:
        return 0
    upsert_rows(
        session=session,
        model=FactStockWarehouseSnapshot,
        rows=prepared_rows,
        conflict_columns=FACT_STOCK_WAREHOUSE_SNAPSHOT_CONFLICT_COLUMNS,
    )
    return len(prepared_rows)


def delete_stock_warehouse_snapshot_scope(session: Session, snapshot_date: date, nm_ids: Sequence[int]) -> int:
    requested_nm_ids = sorted({int(nm_id) for nm_id in nm_ids})
    if not requested_nm_ids:
        return 0
    stmt = (
        delete(FactStockWarehouseSnapshot)
        .where(FactStockWarehouseSnapshot.snapshot_date == snapshot_date)
        .where(FactStockWarehouseSnapshot.nm_id.in_(requested_nm_ids))
    )
    result = session.execute(stmt)
    return int(result.rowcount or 0)


def replace_stock_warehouse_snapshot_scope(
    session: Session,
    *,
    snapshot_date: date,
    requested_nm_ids: Sequence[int],
    rows: Sequence[Mapping[str, Any]],
) -> tuple[int, int]:
    deleted_rows = delete_stock_warehouse_snapshot_scope(session, snapshot_date, requested_nm_ids)
    inserted_rows = upsert_stock_warehouse_snapshot(session, rows)
    return deleted_rows, inserted_rows


def count_stock_warehouse_snapshot_rows(session: Session, snapshot_date: date, nm_ids: Sequence[int] | None = None) -> int:
    stmt = select(func.count()).select_from(FactStockWarehouseSnapshot).where(FactStockWarehouseSnapshot.snapshot_date == snapshot_date)
    if nm_ids:
        stmt = stmt.where(FactStockWarehouseSnapshot.nm_id.in_([int(nm_id) for nm_id in nm_ids]))
    return int(session.execute(stmt).scalar_one())


def write_stock_warehouse_artifacts(
    *,
    output_dir: Path,
    snapshot_date: date,
    raw_items: Sequence[Mapping[str, Any]],
    normalized_rows: Sequence[Mapping[str, Any]],
    aggregate_rows: Sequence[Mapping[str, Any]],
    summary: Mapping[str, Any],
) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = snapshot_date.isoformat()
    raw_path = output_dir / f"warehouse_stock_raw_{suffix}.json"
    normalized_path = output_dir / f"warehouse_stock_normalized_{suffix}.csv"
    aggregate_path = output_dir / f"warehouse_stock_aggregate_{suffix}.csv"
    summary_path = output_dir / f"warehouse_stock_summary_{suffix}.json"
    raw_path.write_text(json.dumps({"snapshot_date": suffix, "items": list(raw_items)}, ensure_ascii=False, indent=2), encoding="utf-8")
    pd.DataFrame(normalized_rows, columns=NORMALIZED_WAREHOUSE_STOCK_COLUMNS).to_csv(normalized_path, index=False, encoding="utf-8-sig")
    pd.DataFrame(aggregate_rows, columns=AGGREGATED_WAREHOUSE_STOCK_COLUMNS).to_csv(aggregate_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "raw_path": str(raw_path),
        "normalized_path": str(normalized_path),
        "aggregate_path": str(aggregate_path),
        "summary_path": str(summary_path),
    }


def load_stock_warehouse_snapshot(
    *,
    snapshot_date: date,
    tracked_products: bool = False,
    nm_ids: Sequence[int] | None = None,
    limit: int = DEFAULT_PAGE_LIMIT,
    max_pages: int | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    write_db: bool = True,
    requester: WarehouseStockRequester | None = None,
) -> dict[str, Any]:
    tracked_nm_ids = get_tracked_nm_ids(TRACKED_PRODUCTS_PATH) if tracked_products else None
    requested_nm_ids = list(nm_ids or tracked_nm_ids or [])
    raw_items, fetch_meta = fetch_wb_warehouse_stock_pages(
        snapshot_date=snapshot_date,
        nm_ids=requested_nm_ids if requested_nm_ids else None,
        limit=limit,
        max_pages=max_pages,
        requester=requester,
    )
    normalized_rows = normalize_wb_warehouse_stock_rows(
        raw_items,
        snapshot_date,
        tracked_nm_ids=requested_nm_ids if requested_nm_ids else None,
    )
    aggregate_rows = aggregate_stock_warehouse_rows(normalized_rows)
    unique_nm_ids = sorted({int(row["nm_id"]) for row in normalized_rows if row.get("nm_id") is not None})
    unique_chrt_ids = sorted({int(row["chrt_id"]) for row in normalized_rows if row.get("chrt_id") not in (None, "")})
    unique_warehouses = sorted({str(row["warehouse_name"]) for row in normalized_rows if row.get("warehouse_name")})
    pages_loaded = int(fetch_meta.get("pages_loaded", 0) or 0)
    rows_in_db = 0
    rows_upserted = 0
    rows_deleted_before_replace = 0
    replace_scope_applied = False
    fetch_succeeded = fetch_meta.get("status") == "200" and not fetch_meta.get("error")
    if write_db:
        with session_scope() as session:
            if fetch_succeeded:
                if requested_nm_ids:
                    rows_deleted_before_replace, rows_upserted = replace_stock_warehouse_snapshot_scope(
                        session,
                        snapshot_date=snapshot_date,
                        requested_nm_ids=requested_nm_ids,
                        rows=normalized_rows,
                    )
                    replace_scope_applied = True
                else:
                    rows_upserted = upsert_stock_warehouse_snapshot(session, normalized_rows)
                rows_in_db = count_stock_warehouse_snapshot_rows(session, snapshot_date, requested_nm_ids or unique_nm_ids)
            else:
                rows_in_db = count_stock_warehouse_snapshot_rows(session, snapshot_date, requested_nm_ids or unique_nm_ids)
    main_warehouses = {
        "Владимир WB",
        "Тула",
        "Казань",
        "Сарапул WB",
        "Склад СПБ Шушары Московское",
        "Волгоград",
        "Краснодар",
        "Екатеринбург - Перспективная 14",
    }
    summary: dict[str, Any] = {
        "snapshot_date": snapshot_date.isoformat(),
        "endpoint": WB_WAREHOUSE_STOCK_ENDPOINT,
        "tracked_products": tracked_products,
        "tracked_total": len(tracked_nm_ids or []),
        "requested_nm_ids_count": len(requested_nm_ids),
        "api_status": fetch_meta.get("status"),
        "api_error": fetch_meta.get("error", ""),
        "pages_loaded": pages_loaded,
        "rows_raw": len(raw_items),
        "rows_normalized": len(normalized_rows),
        "rows_upserted": rows_upserted,
        "rows_deleted_before_replace": rows_deleted_before_replace,
        "replace_scope_applied": replace_scope_applied,
        "rows_in_db_for_snapshot": rows_in_db,
        "unique_nm_ids": len(unique_nm_ids),
        "unique_chrt_ids": len(unique_chrt_ids),
        "unique_warehouses": len(unique_warehouses),
        "found_main_warehouses": sorted(main_warehouses & set(unique_warehouses)),
        "missing_main_warehouses": sorted(main_warehouses - set(unique_warehouses)),
        "rows_for_main_warehouses": int(
            sum(1 for row in aggregate_rows if row.get("warehouse_name") in main_warehouses)
        ),
        "can_build_snapshot_nm_warehouse": bool(aggregate_rows),
        "page_logs": fetch_meta.get("page_logs", []),
        "request_attempts": fetch_meta.get("request_attempts", []),
        "normalized_sample": normalized_rows[:5],
        "aggregate_sample": aggregate_rows[:5],
    }
    summary["artifacts"] = write_stock_warehouse_artifacts(
        output_dir=output_dir,
        snapshot_date=snapshot_date,
        raw_items=raw_items,
        normalized_rows=normalized_rows,
        aggregate_rows=aggregate_rows,
        summary=summary,
    )
    return summary
