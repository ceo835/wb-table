from __future__ import annotations

import argparse
import json
import sys
from dataclasses import dataclass
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import pandas as pd
import requests

ROOT_DIR = Path(__file__).resolve().parents[1]
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config.settings import settings
from src.tracked_products import TRACKED_PRODUCTS_PATH, load_tracked_products


WB_ANALYTICS_BASE = "https://seller-analytics-api.wildberries.ru"
DEFAULT_OUTPUT_DIR = ROOT_DIR / "data" / "processed" / "stocks_warehouse_smoke"
DEFAULT_TIMEOUT_SECONDS = 60
DEFAULT_LIMIT = 100
DEFAULT_MAX_PAGES = 5

MAIN_WAREHOUSE_NAMES = [
    "Владимир WB",
    "Тула",
    "Казань",
    "Сарапул WB",
    "Склад СПБ Шушары Московское",
    "Волгоград",
    "Краснодар",
    "Екатеринбург - Перспективная 14",
]

NORMALIZED_COLUMNS = [
    "snapshot_date",
    "nm_id",
    "supplier_article",
    "title",
    "brand",
    "subject",
    "warehouse_id",
    "warehouse_name",
    "office_name",
    "warehouse_type",
    "stock_qty",
]


@dataclass
class RequestAttempt:
    variant: str
    payload: dict[str, Any]
    http_status: str
    response_excerpt: Any

    def to_dict(self) -> dict[str, Any]:
        return {
            "variant": self.variant,
            "payload": self.payload,
            "http_status": self.http_status,
            "response_excerpt": self.response_excerpt,
        }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="Smoke test warehouse-level WB stocks endpoint without touching production pipeline.",
    )
    parser.add_argument(
        "--snapshot-date",
        default=(date.today() - timedelta(days=1)).isoformat(),
        help="Snapshot date in YYYY-MM-DD. Default: yesterday.",
    )
    parser.add_argument(
        "--tracked-products",
        action="store_true",
        help="Use nm_id list from data/config/tracked_products.csv.",
    )
    parser.add_argument(
        "--tracked-products-path",
        default=str(TRACKED_PRODUCTS_PATH),
        help="Path to tracked_products.csv.",
    )
    parser.add_argument(
        "--output-dir",
        default=str(DEFAULT_OUTPUT_DIR),
        help="Directory for raw/normalized/summary artifacts.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=DEFAULT_LIMIT,
        help="Per-page limit for the endpoint.",
    )
    parser.add_argument(
        "--max-pages",
        type=int,
        default=DEFAULT_MAX_PAGES,
        help="Maximum number of pages for the smoke test.",
    )
    parser.add_argument(
        "--timeout-seconds",
        type=int,
        default=DEFAULT_TIMEOUT_SECONDS,
        help="HTTP timeout in seconds.",
    )
    return parser.parse_args()


def load_tracked_targets(path: Path) -> dict[str, Any]:
    tracked_df = load_tracked_products(path)
    tracked_only = tracked_df.loc[tracked_df["is_tracked"]].copy()
    nm_ids = sorted(tracked_only["nm_id"].dropna().astype(int).unique().tolist())
    return {
        "tracked_df": tracked_only,
        "nm_ids": nm_ids,
        "tracked_total": len(nm_ids),
        "tracked_active_count": int((tracked_only["lifecycle_status"] == "active").sum()),
        "tracked_sellout_count": int((tracked_only["lifecycle_status"] == "sellout").sum()),
    }


def build_request_payload(
    snapshot_date: date,
    nm_ids: list[int],
    limit: int,
    offset: int,
    include_nm_ids: bool,
) -> dict[str, Any]:
    payload: dict[str, Any] = {
        "currentPeriod": {
            "start": snapshot_date.isoformat(),
            "end": snapshot_date.isoformat(),
        },
        "stockType": "",
        "skipDeletedNm": False,
        "availabilityFilters": [],
        "orderBy": {"field": "stockCount", "mode": "desc"},
        "limit": limit,
        "offset": offset,
    }
    if include_nm_ids and nm_ids:
        payload["nmIDs"] = nm_ids
    return payload


def _coalesce(mapping: dict[str, Any], *keys: str) -> Any:
    for key in keys:
        if key in mapping and mapping[key] is not None:
            return mapping[key]
    return None


def _iter_items(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if not isinstance(payload, dict):
        return []
    data = payload.get("data")
    if isinstance(data, dict):
        for key in ("items", "rows", "result", "content", "groups"):
            value = data.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
    for key in ("items", "rows", "result", "content", "groups"):
        value = payload.get(key)
        if isinstance(value, list):
            return [item for item in value if isinstance(item, dict)]
    return []


def extract_office_rows(payload: Any, snapshot_date: date) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    seen: set[tuple[Any, ...]] = set()
    if isinstance(payload, dict):
        regions = ((payload.get("data") or {}).get("regions") or []) if isinstance(payload.get("data"), dict) else []
        if isinstance(regions, list):
            for region in regions:
                if not isinstance(region, dict):
                    continue
                region_name = _coalesce(region, "regionName", "name")
                for office in region.get("offices") or []:
                    if not isinstance(office, dict):
                        continue
                    office_metrics = office.get("metrics") or {}
                    row = {
                        "snapshot_date": snapshot_date.isoformat(),
                        "nm_id": None,
                        "supplier_article": None,
                        "title": None,
                        "brand": None,
                        "subject": None,
                        "warehouse_id": _coalesce(office, "warehouseID", "warehouseId", "officeID", "officeId"),
                        "warehouse_name": _coalesce(office, "warehouseName", "officeName", "name"),
                        "office_name": _coalesce(office, "officeName", "warehouseName", "name"),
                        "warehouse_type": region_name,
                        "stock_qty": _coalesce(
                            office,
                            "quantity",
                            "stockQty",
                            "stockCount",
                            "qty",
                        ),
                    }
                    if row["stock_qty"] is None and isinstance(office_metrics, dict):
                        row["stock_qty"] = _coalesce(office_metrics, "quantity", "stockQty", "stockCount", "qty")
                    dedupe_key = (
                        row["snapshot_date"],
                        row["warehouse_id"],
                        row["warehouse_name"],
                        row["office_name"],
                        row["warehouse_type"],
                        row["stock_qty"],
                    )
                    if dedupe_key in seen:
                        continue
                    seen.add(dedupe_key)
                    rows.append(row)
    for item in _iter_items(payload):
        nm_id = _coalesce(item, "nmID", "nmId", "nm_id")
        supplier_article = _coalesce(item, "vendorCode", "supplierArticle", "supplier_article")
        title = _coalesce(item, "name", "title")
        brand = _coalesce(item, "brandName", "brand")
        subject = _coalesce(item, "subjectName", "subject")
        offices = item.get("offices")
        if not isinstance(offices, list):
            offices = [item]
        for office in offices:
            if not isinstance(office, dict):
                continue
            warehouse_name = _coalesce(
                office,
                "warehouseName",
                "officeName",
                "name",
            )
            office_name = _coalesce(office, "officeName", "warehouseName", "name")
            warehouse_id = _coalesce(office, "warehouseID", "warehouseId", "officeID", "officeId")
            warehouse_type = _coalesce(office, "warehouseType", "officeType", "type")
            stock_qty = _coalesce(office, "quantity", "stockQty", "stockCount", "qty")
            row = {
                "snapshot_date": snapshot_date.isoformat(),
                "nm_id": nm_id,
                "supplier_article": supplier_article,
                "title": title,
                "brand": brand,
                "subject": subject,
                "warehouse_id": warehouse_id,
                "warehouse_name": warehouse_name,
                "office_name": office_name,
                "warehouse_type": warehouse_type,
                "stock_qty": stock_qty,
            }
            dedupe_key = (
                row["snapshot_date"],
                row["nm_id"],
                row["warehouse_id"],
                row["warehouse_name"],
                row["office_name"],
                row["stock_qty"],
            )
            if dedupe_key in seen:
                continue
            seen.add(dedupe_key)
            rows.append(row)
    return rows


def _normalize_response_excerpt(payload: Any) -> Any:
    if isinstance(payload, dict):
        if "error" in payload:
            return {"error": payload.get("error")}
        if "message" in payload:
            return {"message": payload.get("message")}
        regions = ((payload.get("data") or {}).get("regions") or []) if isinstance(payload.get("data"), dict) else []
        if isinstance(regions, list) and regions:
            first_region = regions[0] if isinstance(regions[0], dict) else {}
            offices = first_region.get("offices") or [] if isinstance(first_region, dict) else []
            first_office = offices[0] if offices and isinstance(offices[0], dict) else {}
            return {
                "top_level_keys": sorted(payload.keys()),
                "regions_count": len(regions),
                "sample_region_keys": sorted(first_region.keys()) if isinstance(first_region, dict) else [],
                "sample_office_keys": sorted(first_office.keys()) if isinstance(first_office, dict) else [],
            }
        items = _iter_items(payload)
        return {
            "top_level_keys": sorted(payload.keys()),
            "items_count": len(items),
            "sample_item_keys": sorted(items[0].keys()) if items else [],
        }
    return payload


def build_smoke_summary(
    snapshot_date: date,
    tracked_total: int,
    tracked_nm_ids: list[int],
    request_variant: str,
    http_status: str,
    normalized_df: pd.DataFrame,
    request_attempts: list[dict[str, Any]],
    raw_payload: Any,
) -> dict[str, Any]:
    normalized = normalized_df.copy()
    if normalized.empty:
        normalized = pd.DataFrame(columns=NORMALIZED_COLUMNS)
    product_level_rows = normalized.loc[pd.to_numeric(normalized["nm_id"], errors="coerce").notna()].copy()
    aggregate_only_rows = normalized.loc[pd.to_numeric(normalized["nm_id"], errors="coerce").isna()].copy()
    returned_warehouses = sorted(
        normalized["warehouse_name"].dropna().astype(str).str.strip().replace("", pd.NA).dropna().unique().tolist()
    )
    returned_nm_ids = sorted(pd.to_numeric(product_level_rows["nm_id"], errors="coerce").dropna().astype(int).unique().tolist())
    found_main = sorted(set(returned_warehouses) & set(MAIN_WAREHOUSE_NAMES))
    missing_main = sorted(set(MAIN_WAREHOUSE_NAMES) - set(returned_warehouses))
    can_build_table = (
        all(column in normalized.columns for column in ("snapshot_date", "nm_id", "warehouse_name", "stock_qty"))
        and not product_level_rows.empty
    )
    return {
        "snapshot_date": snapshot_date.isoformat(),
        "endpoint": "/api/v2/stocks-report/offices",
        "endpoint_works": http_status == "200",
        "request_variant": request_variant,
        "tracked_total": tracked_total,
        "tracked_nm_ids_sent": len(tracked_nm_ids),
        "tracked_nm_ids_sample": tracked_nm_ids[:10],
        "returned_nm_ids_count": len(returned_nm_ids),
        "returned_nm_ids": returned_nm_ids,
        "returned_warehouses_count": len(returned_warehouses),
        "returned_warehouses": returned_warehouses,
        "product_level_rows_count": int(len(product_level_rows)),
        "aggregate_only_rows_count": int(len(aggregate_only_rows)),
        "fields_present": sorted(
            {
                key
                for row in normalized.to_dict(orient="records")
                for key, value in row.items()
                if value is not None and not (isinstance(value, float) and pd.isna(value))
            }
        ),
        "normalized_columns": normalized.columns.tolist(),
        "found_main_warehouses": found_main,
        "missing_main_warehouses": missing_main,
        "can_build_warehouse_table": can_build_table,
        "normalized_row_count": int(len(normalized)),
        "normalized_sample": normalized.head(5).replace({pd.NA: None}).where(pd.notna(normalized.head(5)), None).to_dict(orient="records"),
        "aggregate_only_sample": aggregate_only_rows.head(5).replace({pd.NA: None}).where(
            pd.notna(aggregate_only_rows.head(5)),
            None,
        ).to_dict(orient="records"),
        "request_attempts": request_attempts,
        "raw_payload_excerpt": _normalize_response_excerpt(raw_payload),
    }


def _headers() -> dict[str, str]:
    if not settings.wb_analytics_token:
        raise RuntimeError("WB_ANALYTICS_TOKEN is missing")
    return {
        "Authorization": settings.wb_analytics_token,
        "Content-Type": "application/json",
        "Accept": "application/json",
    }


def _request_page(
    session: requests.Session,
    snapshot_date: date,
    nm_ids: list[int],
    include_nm_ids: bool,
    limit: int,
    offset: int,
    timeout_seconds: int,
) -> tuple[str, Any, dict[str, Any]]:
    payload = build_request_payload(
        snapshot_date=snapshot_date,
        nm_ids=nm_ids,
        limit=limit,
        offset=offset,
        include_nm_ids=include_nm_ids,
    )
    try:
        response = session.post(
            f"{WB_ANALYTICS_BASE}/api/v2/stocks-report/offices",
            headers=_headers(),
            json=payload,
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        return "REQUEST_ERROR", {"error": str(exc)}, payload
    try:
        parsed = response.json()
    except ValueError:
        parsed = {"raw_text": response.text[:2000]}
    return str(response.status_code), parsed, payload


def _fetch_smoke_payload(
    snapshot_date: date,
    nm_ids: list[int],
    limit: int,
    max_pages: int,
    timeout_seconds: int,
) -> tuple[str, str, Any, list[dict[str, Any]]]:
    session = requests.Session()
    attempts: list[dict[str, Any]] = []
    variants = [("with_nmids", True), ("without_nmids", False)]
    fallback_variant = "no_successful_variant"
    fallback_status = "N/A"
    fallback_payload: Any = {}
    for variant_name, include_nm_ids in variants:
        combined_items: list[dict[str, Any]] = []
        last_payload: Any = {}
        last_status = "N/A"
        for page in range(max_pages):
            offset = page * limit
            status, payload, request_payload = _request_page(
                session=session,
                snapshot_date=snapshot_date,
                nm_ids=nm_ids,
                include_nm_ids=include_nm_ids,
                limit=limit,
                offset=offset,
                timeout_seconds=timeout_seconds,
            )
            attempts.append(
                RequestAttempt(
                    variant=f"{variant_name}:page_{page + 1}",
                    payload=request_payload,
                    http_status=status,
                    response_excerpt=_normalize_response_excerpt(payload),
                ).to_dict()
            )
            last_payload = payload
            last_status = status
            if status != "200":
                break
            page_items = _iter_items(payload)
            if not page_items:
                break
            combined_items.extend(page_items)
            if len(page_items) < limit:
                break
        if combined_items:
            return variant_name, last_status, {"data": {"items": combined_items}}, attempts
        if last_status == "200":
            fallback_variant = variant_name
            fallback_status = last_status
            fallback_payload = last_payload
    if attempts:
        fallback_status = attempts[-1]["http_status"]
    return fallback_variant, fallback_status, fallback_payload, attempts


def _write_artifacts(output_dir: Path, snapshot_date: date, raw_payload: Any, normalized_df: pd.DataFrame, summary: dict[str, Any]) -> dict[str, str]:
    output_dir.mkdir(parents=True, exist_ok=True)
    suffix = snapshot_date.isoformat()
    raw_path = output_dir / f"stocks_offices_raw_{suffix}.json"
    normalized_path = output_dir / f"stocks_offices_normalized_{suffix}.csv"
    summary_path = output_dir / f"stocks_offices_summary_{suffix}.json"
    raw_path.write_text(json.dumps(raw_payload, ensure_ascii=False, indent=2), encoding="utf-8")
    normalized_df.to_csv(normalized_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "raw_path": str(raw_path),
        "normalized_path": str(normalized_path),
        "summary_path": str(summary_path),
    }


def main() -> None:
    args = parse_args()
    snapshot_date = date.fromisoformat(args.snapshot_date)
    tracked_path = Path(args.tracked_products_path)
    targets = load_tracked_targets(tracked_path) if args.tracked_products else {
        "tracked_df": pd.DataFrame(),
        "nm_ids": [],
        "tracked_total": 0,
        "tracked_active_count": 0,
        "tracked_sellout_count": 0,
    }
    variant, http_status, raw_payload, attempts = _fetch_smoke_payload(
        snapshot_date=snapshot_date,
        nm_ids=targets["nm_ids"],
        limit=args.limit,
        max_pages=args.max_pages,
        timeout_seconds=args.timeout_seconds,
    )
    normalized_rows = extract_office_rows(raw_payload, snapshot_date=snapshot_date)
    normalized_df = pd.DataFrame(normalized_rows, columns=NORMALIZED_COLUMNS)
    summary = build_smoke_summary(
        snapshot_date=snapshot_date,
        tracked_total=targets["tracked_total"],
        tracked_nm_ids=targets["nm_ids"],
        request_variant=variant,
        http_status=http_status,
        normalized_df=normalized_df,
        request_attempts=attempts,
        raw_payload=raw_payload,
    )
    summary["tracked_active_count"] = targets["tracked_active_count"]
    summary["tracked_sellout_count"] = targets["tracked_sellout_count"]
    summary["artifact_generated_at"] = datetime.now().isoformat(timespec="seconds")
    summary["artifacts"] = _write_artifacts(
        output_dir=Path(args.output_dir),
        snapshot_date=snapshot_date,
        raw_payload=raw_payload,
        normalized_df=normalized_df,
        summary=summary,
    )
    print(json.dumps(summary, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
