from __future__ import annotations

import json
from datetime import UTC, date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Mapping, Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.db.models import FactWbSitePriceAlert, FactWbSitePriceSnapshot
from src.db.session import session_scope, upsert_rows
from src.tracked_products import TRACKED_PRODUCTS_PATH
from src.wb_site_price_monitor import (
    DEFAULT_TIMEOUT_MS,
    fetch_wb_site_price_snapshots_with_playwright,
    load_price_monitor_targets,
    resolve_proxy_url,
)


WB_SITE_PRICE_SNAPSHOT_SOURCE = "WB_SITE_PUBLIC_CARD"
WB_SITE_PRICE_ALERT_THRESHOLD = Decimal("50.00")
FETCH_STATUS_SUCCESS = "success"
FETCH_STATUS_NO_PRICE_DATA = "no_price_data"
FETCH_STATUS_BLOCKED = "blocked"
FETCH_STATUS_TIMEOUT = "timeout"
FETCH_STATUS_FAILED = "failed"

ALERT_STATUS_OK = "OK"
ALERT_STATUS_PRICE_CHANGED_50 = "PRICE_CHANGED_50"
ALERT_STATUS_NO_PRICE_DATA = "NO_PRICE_DATA"
ALERT_STATUS_FETCH_FAILED = "FETCH_FAILED"

DEFAULT_OUTPUT_DIR = Path(__file__).resolve().parents[2] / "data" / "processed" / "wb_site_price_snapshots"
SNAPSHOT_CONFLICT_COLUMNS = ("snapshot_date", "nm_id")
ALERT_CONFLICT_COLUMNS = ("snapshot_date", "nm_id")


def utc_now() -> datetime:
    return datetime.now(UTC)


def _to_decimal_or_none(value: Any) -> Decimal | None:
    if value in (None, ""):
        return None
    try:
        return Decimal(str(value))
    except (InvalidOperation, TypeError, ValueError):
        return None


def _to_bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() in {"1", "true", "yes", "on"}


def prepare_fact_wb_site_price_snapshot_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    seen: dict[tuple[date, int], int] = {}
    for row in rows:
        snapshot_date = date.fromisoformat(str(row["snapshot_date"]))
        nm_id = int(row["nm_id"])
        prepared_row = {
            "snapshot_at": datetime.fromisoformat(str(row["snapshot_at"])),
            "snapshot_date": snapshot_date,
            "nm_id": nm_id,
            "item_label": row.get("item_label"),
            "lifecycle_status": row.get("lifecycle_status"),
            "product_url": row.get("product_url"),
            "buyer_visible_price": _to_decimal_or_none(row.get("buyer_visible_price")),
            "currency": row.get("currency"),
            "price_text_raw": row.get("price_text_raw"),
            "availability_status": row.get("availability_status"),
            "fetch_status": str(row.get("fetch_status") or FETCH_STATUS_FAILED),
            "error": row.get("error"),
            "proxy_used": _to_bool(row.get("proxy_used")),
            "raw_payload": row.get("raw_payload"),
        }
        dedupe_key = (snapshot_date, nm_id)
        if dedupe_key in seen:
            prepared[seen[dedupe_key]] = prepared_row
        else:
            seen[dedupe_key] = len(prepared)
            prepared.append(prepared_row)
    return prepared


def fetch_previous_success_price_lookup(
    session: Session,
    *,
    snapshot_date: date,
    nm_ids: Sequence[int],
) -> dict[int, Decimal]:
    if not nm_ids:
        return {}

    rows = session.execute(
        select(
            FactWbSitePriceSnapshot.nm_id,
            FactWbSitePriceSnapshot.snapshot_date,
            FactWbSitePriceSnapshot.buyer_visible_price,
        )
        .where(
            FactWbSitePriceSnapshot.nm_id.in_([int(nm_id) for nm_id in nm_ids]),
            FactWbSitePriceSnapshot.snapshot_date < snapshot_date,
            FactWbSitePriceSnapshot.fetch_status == FETCH_STATUS_SUCCESS,
            FactWbSitePriceSnapshot.buyer_visible_price.is_not(None),
        )
        .order_by(
            FactWbSitePriceSnapshot.nm_id.asc(),
            FactWbSitePriceSnapshot.snapshot_date.desc(),
        )
    ).all()

    lookup: dict[int, Decimal] = {}
    for nm_id, _row_date, buyer_visible_price in rows:
        normalized_nm_id = int(nm_id)
        if normalized_nm_id in lookup or buyer_visible_price is None:
            continue
        lookup[normalized_nm_id] = Decimal(str(buyer_visible_price))
    return lookup


def build_wb_site_price_alert_rows(
    snapshot_rows: Sequence[Mapping[str, Any]],
    previous_success_price_lookup: Mapping[int, Decimal],
    *,
    threshold: Decimal = WB_SITE_PRICE_ALERT_THRESHOLD,
) -> list[dict[str, Any]]:
    alert_rows: list[dict[str, Any]] = []
    for row in snapshot_rows:
        snapshot_date = row["snapshot_date"]
        nm_id = int(row["nm_id"])
        current_price = _to_decimal_or_none(row.get("buyer_visible_price"))
        previous_price = previous_success_price_lookup.get(nm_id)
        fetch_status = str(row.get("fetch_status") or FETCH_STATUS_FAILED)
        price_delta = None

        if fetch_status == FETCH_STATUS_SUCCESS and current_price is not None:
            if previous_price is not None:
                price_delta = current_price - previous_price
            if previous_price is not None and abs(price_delta) >= threshold:
                alert_status = ALERT_STATUS_PRICE_CHANGED_50
            else:
                alert_status = ALERT_STATUS_OK
        elif fetch_status == FETCH_STATUS_NO_PRICE_DATA:
            alert_status = ALERT_STATUS_NO_PRICE_DATA
        else:
            alert_status = ALERT_STATUS_FETCH_FAILED

        alert_rows.append(
            {
                "snapshot_date": snapshot_date,
                "nm_id": nm_id,
                "current_price": current_price,
                "previous_success_price": previous_price,
                "price_delta": price_delta,
                "alert_status": alert_status,
            }
        )
    return alert_rows


def prepare_fact_wb_site_price_alert_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    prepared: list[dict[str, Any]] = []
    seen: dict[tuple[date, int], int] = {}
    for row in rows:
        snapshot_date = row["snapshot_date"]
        if isinstance(snapshot_date, str):
            snapshot_date = date.fromisoformat(snapshot_date)
        nm_id = int(row["nm_id"])
        prepared_row = {
            "snapshot_date": snapshot_date,
            "nm_id": nm_id,
            "current_price": _to_decimal_or_none(row.get("current_price")),
            "previous_success_price": _to_decimal_or_none(row.get("previous_success_price")),
            "price_delta": _to_decimal_or_none(row.get("price_delta")),
            "alert_status": str(row.get("alert_status") or ALERT_STATUS_FETCH_FAILED),
        }
        dedupe_key = (snapshot_date, nm_id)
        if dedupe_key in seen:
            prepared[seen[dedupe_key]] = prepared_row
        else:
            seen[dedupe_key] = len(prepared)
            prepared.append(prepared_row)
    return prepared


def upsert_wb_site_price_snapshot(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_fact_wb_site_price_snapshot_upsert_rows(rows)
    if not prepared_rows:
        return 0
    return upsert_rows(
        session,
        FactWbSitePriceSnapshot,
        prepared_rows,
        conflict_columns=SNAPSHOT_CONFLICT_COLUMNS,
    )


def upsert_wb_site_price_alert(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_fact_wb_site_price_alert_upsert_rows(rows)
    if not prepared_rows:
        return 0
    return upsert_rows(
        session,
        FactWbSitePriceAlert,
        prepared_rows,
        conflict_columns=ALERT_CONFLICT_COLUMNS,
    )


def persist_run_summary(output_dir: Path, snapshot_date: date, summary: dict[str, Any]) -> str:
    output_dir.mkdir(parents=True, exist_ok=True)
    path = output_dir / f"wb_site_price_snapshot_{snapshot_date.isoformat()}.json"
    path.write_text(json.dumps(summary, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
    return str(path)


def load_wb_site_price_snapshot(
    *,
    tracked_products: bool = False,
    nm_ids: Sequence[int] | None = None,
    limit: int | None = None,
    headless: bool = True,
    timeout_ms: int = DEFAULT_TIMEOUT_MS,
    snapshot_date: date | None = None,
    write_db: bool = True,
    proxy_url: str | None = None,
    output_dir: Path = DEFAULT_OUTPUT_DIR,
    fetcher=None,
) -> dict[str, Any]:
    resolved_snapshot_date = snapshot_date or date.today()
    started_at = utc_now()
    resolved_proxy_url = resolve_proxy_url(proxy_url)
    targets = load_price_monitor_targets(
        tracked_path=TRACKED_PRODUCTS_PATH,
        nm_ids=nm_ids,
        limit=limit,
    )

    summary: dict[str, Any] = {
        "success": True,
        "snapshot_date": resolved_snapshot_date.isoformat(),
        "requested_nm_ids": [int(target["nm_id"]) for target in targets],
        "requested_nm_ids_count": len(targets),
        "success_count": 0,
        "failed_count": 0,
        "alerts_count": 0,
        "proxy_enabled": bool(resolved_proxy_url),
        "duration_seconds": 0.0,
        "fetch_status_counts": {},
        "rows_upserted": 0,
        "alerts_upserted": 0,
        "error": "",
        "summary_path": "",
        "region_detected": None,
    }

    if not targets:
        summary["summary_path"] = persist_run_summary(output_dir, resolved_snapshot_date, summary)
        return summary

    fetch_many = fetcher or fetch_wb_site_price_snapshots_with_playwright
    try:
        raw_rows, fetch_meta = fetch_many(
            targets,
            headless=headless,
            timeout_ms=timeout_ms,
            proxy_url=resolved_proxy_url,
        )
        summary["fetch_status_counts"] = dict(fetch_meta.get("fetch_status_counts") or {})
        summary["region_detected"] = fetch_meta.get("region_detected")
        summary["success_count"] = int(summary["fetch_status_counts"].get(FETCH_STATUS_SUCCESS, 0))
        summary["failed_count"] = len(raw_rows) - summary["success_count"]

        if write_db:
            with session_scope() as session:
                previous_lookup = fetch_previous_success_price_lookup(
                    session,
                    snapshot_date=resolved_snapshot_date,
                    nm_ids=[int(row["nm_id"]) for row in raw_rows],
                )
                summary["rows_upserted"] = upsert_wb_site_price_snapshot(session, raw_rows)
                alert_rows = build_wb_site_price_alert_rows(raw_rows, previous_lookup)
                summary["alerts_count"] = sum(1 for row in alert_rows if row["alert_status"] == ALERT_STATUS_PRICE_CHANGED_50)
                summary["alerts_upserted"] = upsert_wb_site_price_alert(session, alert_rows)
        else:
            alert_rows = build_wb_site_price_alert_rows(raw_rows, {})
            summary["alerts_count"] = sum(1 for row in alert_rows if row["alert_status"] == ALERT_STATUS_PRICE_CHANGED_50)
    except Exception as exc:
        summary["success"] = False
        summary["error"] = str(exc)

    finished_at = utc_now()
    summary["run_started_at"] = started_at.isoformat()
    summary["run_finished_at"] = finished_at.isoformat()
    summary["duration_seconds"] = round((finished_at - started_at).total_seconds(), 3)
    summary["summary_path"] = persist_run_summary(output_dir, resolved_snapshot_date, summary)
    return summary
