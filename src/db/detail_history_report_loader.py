from __future__ import annotations

import csv
import io
import json
import time
import uuid
import zipfile
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

import pandas as pd
import requests
from sqlalchemy import select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.db.funnel_loader import build_fact_funnel_day_db_row
from src.db.models import FactFunnelDay
from src.db.session import session_scope, upsert_rows


WB_ANALYTICS_BASE = "https://seller-analytics-api.wildberries.ru"
DETAIL_HISTORY_SOURCE_STATUS = "DETAIL_HISTORY_REPORT"
DETAIL_HISTORY_DATA_STATUS = "REAL_API"
DETAIL_HISTORY_CONFLICT_COLUMNS = ("date", "nm_id")
DETAIL_HISTORY_TARGET_FIELDS = (
    "card_clicks",
    "cart_count",
    "order_count",
    "order_sum",
    "buyout_count",
    "buyout_sum",
    "add_to_cart_conversion",
    "cart_to_order_conversion",
)
DETAIL_HISTORY_ALL_MODEL_COLUMNS = tuple(column.name for column in FactFunnelDay.__table__.columns if not column.primary_key)

FUNNEL_FIELD_ALIASES = {
    "card_clicks": ("card_clicks", "opencount", "open_count", "opencard", "opencardcount", "cardclicks"),
    "cart_count": ("cart_count", "cartcount", "addtocartcount", "addtocart"),
    "order_count": ("order_count", "ordercount", "orderscount"),
    "order_sum": ("order_sum", "ordersum", "orderssumrub", "revenue", "salesum"),
    "buyout_count": ("buyout_count", "buyoutcount", "buyoutscount"),
    "buyout_sum": ("buyout_sum", "buyoutsum", "buyoutssumrub"),
    "add_to_cart_conversion": ("addtocartconversion", "cartconversion"),
    "cart_to_order_conversion": ("carttoorderconversion", "orderconversion"),
}
IDENTITY_ALIASES = {
    "date": ("date", "day", "dt"),
    "nm_id": ("nmid", "nm_id", "nmidwb"),
    "supplier_article": ("supplierarticle", "vendorcode"),
    "title": ("title", "name"),
}


def _truncate_error(value: Any, limit: int = 240) -> str:
    if not value:
        return ""
    return " ".join(str(value).split())[:limit]


def _payload_summary(payload: Any) -> str:
    if payload is None:
        return "empty"
    if isinstance(payload, dict):
        return f"dict:{','.join(list(payload)[:8])}"
    if isinstance(payload, list):
        return f"list:{len(payload)}"
    return type(payload).__name__


def _normalize_header(value: Any) -> str:
    text = str(value or "").strip().lower()
    return "".join(ch for ch in text if ch.isalnum())


def _coerce_date(value: Any) -> date | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    text = str(value).strip()
    if not text:
        return None
    for candidate in (text, text.split("T", 1)[0], text.split(" ", 1)[0]):
        try:
            return date.fromisoformat(candidate)
        except ValueError:
            continue
    parsed = pd.to_datetime(text, errors="coerce", dayfirst=True)
    if pd.isna(parsed):
        return None
    return parsed.date()


def _coerce_int(value: Any) -> int | None:
    if value in (None, "", [], {}):
        return None
    try:
        return int(float(str(value).replace(" ", "").replace(",", ".")))
    except Exception:
        return None


def _coerce_number(value: Any) -> float | int | None:
    if value in (None, "", [], {}):
        return None
    text = str(value).strip().replace(" ", "").replace("\xa0", "").replace(",", ".")
    if not text:
        return None
    try:
        number = float(text)
    except ValueError:
        return None
    if number.is_integer():
        return int(number)
    return number


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item") and callable(getattr(value, "item")):
        try:
            return value.item()
        except Exception:
            pass
    return value


def parse_nm_ids_from_file(path: Path) -> list[int]:
    frame = pd.read_csv(path)
    nm_ids: set[int] = set()
    for record in frame.to_dict(orient="records"):
        nm_id = _coerce_int(record.get("Артикул WB"))
        if nm_id is not None:
            nm_ids.add(nm_id)
    return sorted(nm_ids)


def load_gap_rows(path: Path) -> pd.DataFrame:
    frame = pd.read_csv(path)
    frame["report_date"] = frame["Дата"].map(_coerce_date)
    frame["nm_id"] = frame["Артикул WB"].map(_coerce_int)
    return frame.dropna(subset=["report_date", "nm_id"]).copy()


def build_detail_history_request_payload(
    *,
    report_type: str,
    report_name: str,
    date_from: date,
    date_to: date,
    nm_ids: Sequence[int],
    skip_deleted_nm: bool = False,
    timezone_name: str = "Europe/Moscow",
    aggregation_level: str = "day",
    lowercase_nmids: bool = False,
) -> dict[str, Any]:
    nm_key = "nmIds" if lowercase_nmids else "nmIDs"
    return {
        "id": str(uuid.uuid4()),
        "reportType": report_type,
        "userReportName": report_name,
        "params": {
            nm_key: list(nm_ids),
            "subjectIds": [],
            "brandNames": [],
            "tagIds": [],
            "startDate": date_from.isoformat(),
            "endDate": date_to.isoformat(),
            "timezone": timezone_name,
            "aggregationLevel": aggregation_level,
            "skipDeletedNm": skip_deleted_nm,
        },
    }


def analytics_headers() -> dict[str, str]:
    return {
        "Authorization": settings.wb_analytics_token or "",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    json_body: dict[str, Any] | None = None,
    timeout_seconds: int = 60,
) -> tuple[str, Any, str]:
    try:
        response = session.request(
            method=method,
            url=url,
            headers=analytics_headers(),
            json=json_body,
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        return "REQUEST_ERROR", None, _truncate_error(exc)
    try:
        payload = response.json()
    except ValueError:
        payload = response.text
    if response.status_code >= 400:
        return str(response.status_code), payload, _truncate_error(response.text or response.reason)
    return str(response.status_code), payload, ""


def create_detail_history_download_task(
    session: requests.Session,
    *,
    date_from: date,
    date_to: date,
    nm_ids: Sequence[int],
    report_type: str = "DETAIL_HISTORY_REPORT",
    timeout_seconds: int = 60,
) -> tuple[str, list[dict[str, Any]], str]:
    attempts: list[dict[str, Any]] = []
    payload_variants = [
        ("official_schema", build_detail_history_request_payload(report_type=report_type, report_name=f"detail-history-{datetime.now().strftime('%Y%m%d-%H%M%S')}", date_from=date_from, date_to=date_to, nm_ids=nm_ids)),
        ("official_schema_skip_deleted_true", build_detail_history_request_payload(report_type=report_type, report_name=f"detail-history-{datetime.now().strftime('%Y%m%d-%H%M%S')}-skip", date_from=date_from, date_to=date_to, nm_ids=nm_ids, skip_deleted_nm=True)),
        ("official_schema_lowercase_nmids", build_detail_history_request_payload(report_type=report_type, report_name=f"detail-history-{datetime.now().strftime('%Y%m%d-%H%M%S')}-lower", date_from=date_from, date_to=date_to, nm_ids=nm_ids, lowercase_nmids=True)),
    ]
    report_name_prefix = ""
    for label, payload in payload_variants:
        report_name_prefix = str(payload["userReportName"]).split(" official")[0].split("-skip")[0].split("-lower")[0]
        status, response_payload, error = _request_json(
            session,
            "POST",
            f"{WB_ANALYTICS_BASE}/api/v2/nm-report/downloads",
            json_body=payload,
            timeout_seconds=timeout_seconds,
        )
        attempts.append(
            {
                "label": label,
                "http_status": status,
                "response_type": _payload_summary(response_payload),
                "error": error,
                "request_body": payload,
                "response_body": response_payload,
                "download_id": "",
            }
        )
        if status == "200":
            return report_name_prefix, attempts, ""
        if status == "429":
            return report_name_prefix, attempts, "429"
    return report_name_prefix, attempts, attempts[-1]["error"] if attempts else "create_failed"


def _extract_reports(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, dict):
        for key in ("data", "items", "downloads", "result"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
        return [payload]
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    return []


def _match_report_by_prefix(reports: list[dict[str, Any]], report_name_prefix: str) -> dict[str, Any] | None:
    return next((item for item in reports if str(item.get("name") or "").startswith(report_name_prefix)), None)


def poll_detail_history_download(
    session: requests.Session,
    *,
    report_name_prefix: str,
    poll_interval_seconds: int = 15,
    max_polls: int = 8,
    timeout_seconds: int = 60,
) -> tuple[str, list[dict[str, Any]], Any]:
    attempts: list[dict[str, Any]] = []
    last_payload: Any = None
    for poll_number in range(1, max_polls + 1):
        status, payload, error = _request_json(
            session,
            "GET",
            f"{WB_ANALYTICS_BASE}/api/v2/nm-report/downloads",
            timeout_seconds=timeout_seconds,
        )
        last_payload = payload
        reports = _extract_reports(payload)
        matched = _match_report_by_prefix(reports, report_name_prefix)
        matched_status = str(matched.get("status") or "") if matched else ""
        matched_id = str(matched.get("id") or matched.get("downloadId") or "") if matched else ""
        attempts.append(
            {
                "poll_number": poll_number,
                "http_status": status,
                "matched_report_status": matched_status,
                "download_id": matched_id,
                "reports_seen": len(reports),
                "error": error,
            }
        )
        if matched_status.upper() == "SUCCESS" and matched_id:
            return matched_id, attempts, payload
        if matched_status.upper() in {"FAILED", "ERROR"}:
            return matched_id, attempts, payload
        if poll_number < max_polls:
            time.sleep(poll_interval_seconds)
    return "", attempts, last_payload


def download_detail_history_file(
    session: requests.Session,
    download_id: str,
    *,
    timeout_seconds: int = 60,
) -> tuple[str, bytes, str, str]:
    try:
        response = session.get(
            f"{WB_ANALYTICS_BASE}/api/v2/nm-report/downloads/file/{download_id}",
            headers={"Authorization": settings.wb_analytics_token or "", "Accept": "*/*"},
            timeout=timeout_seconds,
        )
    except requests.RequestException as exc:
        return "REQUEST_ERROR", b"", "", _truncate_error(exc)
    if response.status_code >= 400:
        return str(response.status_code), b"", response.headers.get("Content-Type", ""), _truncate_error(response.text or response.reason)
    return str(response.status_code), response.content, response.headers.get("Content-Type", ""), ""


def _decode_bytes(content: bytes) -> str:
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "windows-1251", "latin-1"):
        try:
            return content.decode(encoding)
        except UnicodeDecodeError:
            continue
    return content.decode("utf-8", errors="replace")


def _read_csv_text(text: str) -> pd.DataFrame:
    sample = text[:4096]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        if ";" in sample and sample.count(";") > sample.count(","):
            delimiter = ";"
    return pd.read_csv(io.StringIO(text), sep=delimiter)


def extract_detail_history_frame(content: bytes, content_type: str) -> tuple[pd.DataFrame, dict[str, Any]]:
    meta: dict[str, Any] = {"content_type": content_type, "archive_member": "", "content_size_bytes": len(content)}
    if content.startswith(b"PK") or "zip" in content_type.lower():
        with zipfile.ZipFile(io.BytesIO(content)) as archive:
            csv_members = [name for name in archive.namelist() if name.lower().endswith(".csv")]
            if not csv_members:
                raise ValueError("ZIP downloaded, but CSV member was not found")
            member_name = csv_members[0]
            meta["archive_member"] = member_name
            text = _decode_bytes(archive.read(member_name))
            return _read_csv_text(text), meta
    text = _decode_bytes(content)
    return _read_csv_text(text), meta


def _alias_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for target, aliases in {**IDENTITY_ALIASES, **FUNNEL_FIELD_ALIASES}.items():
        for alias in aliases:
            mapping[alias] = target
    return mapping


def normalize_detail_history_frame(frame: pd.DataFrame) -> pd.DataFrame:
    alias_map = _alias_map()
    rename_map: dict[str, str] = {}
    for column in frame.columns:
        normalized = _normalize_header(column)
        target = alias_map.get(normalized)
        if target and target not in rename_map.values():
            rename_map[column] = target
    normalized = frame.rename(columns=rename_map).copy()
    for required in ("date", "nm_id", "supplier_article", "title"):
        if required not in normalized.columns:
            normalized[required] = None
    normalized["date"] = normalized["date"].map(_coerce_date)
    normalized["nm_id"] = normalized["nm_id"].map(_coerce_int)
    for numeric_column in DETAIL_HISTORY_TARGET_FIELDS:
        if numeric_column not in normalized.columns:
            normalized[numeric_column] = None
        normalized[numeric_column] = normalized[numeric_column].map(_coerce_number)
    normalized["supplier_article"] = normalized["supplier_article"].map(lambda value: str(value).strip() if value not in (None, "") else "")
    normalized["title"] = normalized["title"].map(lambda value: str(value).strip() if value not in (None, "") else "")
    keep_columns = ["date", "nm_id", "supplier_article", "title", *DETAIL_HISTORY_TARGET_FIELDS]
    for column in keep_columns:
        if column not in normalized.columns:
            normalized[column] = None
    return normalized[keep_columns]


def fetch_existing_funnel_rows(session: Session, *, date_from: date, date_to: date, nm_ids: Sequence[int]) -> dict[tuple[date, int], dict[str, Any]]:
    rows = session.execute(
        select(FactFunnelDay).where(
            FactFunnelDay.date >= date_from,
            FactFunnelDay.date <= date_to,
            FactFunnelDay.nm_id.in_(list(nm_ids)),
        )
    ).scalars().all()
    result: dict[tuple[date, int], dict[str, Any]] = {}
    for row in rows:
        payload = {column: getattr(row, column) for column in DETAIL_HISTORY_ALL_MODEL_COLUMNS}
        payload["date"] = row.date
        payload["nm_id"] = row.nm_id
        result[(row.date, int(row.nm_id))] = payload
    return result


def build_detail_history_fact_rows(
    normalized_frame: pd.DataFrame,
    *,
    loaded_at: datetime,
    existing_rows_by_key: dict[tuple[date, int], dict[str, Any]],
) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for record in normalized_frame.to_dict(orient="records"):
        report_date = record.get("date")
        nm_id = record.get("nm_id")
        if report_date is None or nm_id is None:
            continue
        source_row = {
            "date": report_date,
            "nm_id": nm_id,
            "card_clicks": record.get("card_clicks"),
            "cartCount": record.get("cart_count"),
            "orderCount": record.get("order_count"),
            "orderSum": record.get("order_sum"),
            "buyoutCount": record.get("buyout_count"),
            "buyoutSum": record.get("buyout_sum"),
            "addToCartConversion": record.get("add_to_cart_conversion"),
            "cartToOrderConversion": record.get("cart_to_order_conversion"),
            "data_status": DETAIL_HISTORY_DATA_STATUS,
            "source_status": DETAIL_HISTORY_SOURCE_STATUS,
            "loaded_at": loaded_at,
        }
        incoming = build_fact_funnel_day_db_row(source_row)
        existing = existing_rows_by_key.get((report_date, int(nm_id)), {})
        merged = dict(existing) if existing else {column: None for column in DETAIL_HISTORY_ALL_MODEL_COLUMNS}
        merged["date"] = report_date
        merged["nm_id"] = int(nm_id)
        for key, value in incoming.items():
            if key in {"date", "nm_id"}:
                continue
            if value is not None:
                merged[key] = value
        merged["data_status"] = DETAIL_HISTORY_DATA_STATUS
        merged["source_status"] = DETAIL_HISTORY_SOURCE_STATUS
        merged["loaded_at"] = loaded_at
        rows.append(merged)
    return rows


def apply_detail_history_rows(session: Session, rows: list[dict[str, Any]]) -> int:
    if not rows:
        return 0
    upsert_rows(
        session=session,
        model=FactFunnelDay,
        rows=rows,
        conflict_columns=DETAIL_HISTORY_CONFLICT_COLUMNS,
    )
    return len(rows)


def build_gap_match_frame(gap_rows: pd.DataFrame, normalized_frame: pd.DataFrame) -> pd.DataFrame:
    indexed: dict[tuple[date, int], dict[str, Any]] = {}
    for record in normalized_frame.to_dict(orient="records"):
        report_date = record.get("date")
        nm_id = record.get("nm_id")
        if report_date is None or nm_id is None:
            continue
        indexed[(report_date, int(nm_id))] = record
    rows: list[dict[str, Any]] = []
    for record in gap_rows.to_dict(orient="records"):
        key = (record["report_date"], int(record["nm_id"]))
        matched = indexed.get(key, {})
        rows.append(
            {
                "report_date": record["report_date"].isoformat(),
                "supplier_article": record.get("Артикул продавца") or "",
                "nm_id": int(record["nm_id"]),
                "missing_labels": record.get("Что отсутствует") or "",
                "recommendation": record.get("Рекомендация") or "",
                "match_status": "FOUND" if matched else "NOT_FOUND",
                "matched_supplier_article": matched.get("supplier_article") or "",
                "matched_title": matched.get("title") or "",
                "card_clicks": matched.get("card_clicks"),
                "cart_count": matched.get("cart_count"),
                "order_count": matched.get("order_count"),
                "order_sum": matched.get("order_sum"),
                "buyout_count": matched.get("buyout_count"),
                "buyout_sum": matched.get("buyout_sum"),
                "add_to_cart_conversion": matched.get("add_to_cart_conversion"),
                "cart_to_order_conversion": matched.get("cart_to_order_conversion"),
                "has_card_clicks": bool(matched and matched.get("card_clicks") is not None),
                "has_cart_count": bool(matched and matched.get("cart_count") is not None),
                "has_order_count": bool(matched and matched.get("order_count") is not None),
                "has_order_sum": bool(matched and matched.get("order_sum") is not None),
            }
        )
    return pd.DataFrame(rows)


def save_artifacts(
    *,
    save_raw_dir: Path,
    download_id: str,
    zip_bytes: bytes,
    raw_frame: pd.DataFrame,
    normalized_frame: pd.DataFrame,
    matched_frame: pd.DataFrame,
    summary: dict[str, Any],
) -> dict[str, str]:
    save_raw_dir.mkdir(parents=True, exist_ok=True)
    zip_path = save_raw_dir / f"{download_id}.zip"
    csv_path = save_raw_dir / f"{download_id}.csv"
    normalized_path = save_raw_dir / f"{download_id}_normalized.csv"
    matched_path = save_raw_dir / f"{download_id}_matched_gaps.csv"
    summary_path = save_raw_dir / f"{download_id}_summary.json"
    if zip_bytes:
        zip_path.write_bytes(zip_bytes)
    raw_frame.to_csv(csv_path, index=False, encoding="utf-8-sig")
    normalized_frame.to_csv(normalized_path, index=False, encoding="utf-8-sig")
    matched_frame.to_csv(matched_path, index=False, encoding="utf-8-sig")
    summary_path.write_text(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2), encoding="utf-8")
    return {
        "zip_path": str(zip_path),
        "raw_csv_path": str(csv_path),
        "normalized_csv_path": str(normalized_path),
        "matched_gaps_path": str(matched_path),
        "summary_path": str(summary_path),
    }


def load_detail_history_report(
    *,
    date_from: date,
    date_to: date,
    nmids_from_file: Path | None = None,
    nm_ids: Sequence[int] | None = None,
    poll_interval_seconds: int = 15,
    max_polls: int = 8,
    dry_run: bool = False,
    save_raw_dir: Path | None = None,
    timeout_seconds: int = 60,
) -> dict[str, Any]:
    resolved_nm_ids = sorted({int(value) for value in (nm_ids or [])})
    gap_rows = pd.DataFrame()
    if nmids_from_file is not None:
        gap_rows = load_gap_rows(nmids_from_file)
        resolved_nm_ids = sorted(set(resolved_nm_ids) | set(int(value) for value in gap_rows["nm_id"].tolist()))
    if not resolved_nm_ids:
        raise ValueError("No nm_ids resolved for DETAIL_HISTORY_REPORT load")

    requests_session = requests.Session()
    report_name_prefix, create_attempts, create_error = create_detail_history_download_task(
        requests_session,
        date_from=date_from,
        date_to=date_to,
        nm_ids=resolved_nm_ids,
        timeout_seconds=timeout_seconds,
    )
    if not any(attempt["http_status"] == "200" for attempt in create_attempts):
        summary = {
            "dry_run": dry_run,
            "requested_nm_ids": len(resolved_nm_ids),
            "report_rows": 0,
            "parsed_rows": 0,
            "upserted_rows": 0,
            "updated_existing_rows": 0,
            "inserted_new_rows": 0,
            "skipped_rows": 0,
            "gaps_found_in_report": 0,
            "remaining_gaps": int(len(gap_rows)) if not gap_rows.empty else 0,
            "errors": [create_error] if create_error else [],
            "create_attempts": create_attempts,
            "poll_attempts": [],
        }
        return summary

    download_id, poll_attempts, list_payload = poll_detail_history_download(
        requests_session,
        report_name_prefix=report_name_prefix,
        poll_interval_seconds=poll_interval_seconds,
        max_polls=max_polls,
        timeout_seconds=timeout_seconds,
    )
    if not download_id:
        summary = {
            "dry_run": dry_run,
            "requested_nm_ids": len(resolved_nm_ids),
            "report_rows": 0,
            "parsed_rows": 0,
            "upserted_rows": 0,
            "updated_existing_rows": 0,
            "inserted_new_rows": 0,
            "skipped_rows": 0,
            "gaps_found_in_report": 0,
            "remaining_gaps": int(len(gap_rows)) if not gap_rows.empty else 0,
            "errors": ["download_id_not_resolved"],
            "create_attempts": create_attempts,
            "poll_attempts": poll_attempts,
            "list_payload_summary": _payload_summary(list_payload),
        }
        return summary

    download_status, zip_bytes, content_type, download_error = download_detail_history_file(
        requests_session,
        download_id,
        timeout_seconds=timeout_seconds,
    )
    if download_status != "200":
        return {
            "dry_run": dry_run,
            "requested_nm_ids": len(resolved_nm_ids),
            "report_rows": 0,
            "parsed_rows": 0,
            "upserted_rows": 0,
            "updated_existing_rows": 0,
            "inserted_new_rows": 0,
            "skipped_rows": 0,
            "gaps_found_in_report": 0,
            "remaining_gaps": int(len(gap_rows)) if not gap_rows.empty else 0,
            "errors": [download_error or download_status],
            "create_attempts": create_attempts,
            "poll_attempts": poll_attempts,
        }

    raw_frame, download_meta = extract_detail_history_frame(zip_bytes, content_type)
    normalized_frame = normalize_detail_history_frame(raw_frame)
    matched_frame = build_gap_match_frame(gap_rows, normalized_frame) if not gap_rows.empty else pd.DataFrame()

    upserted_rows = 0
    inserted_new_rows = 0
    updated_existing_rows = 0
    skipped_rows = 0
    if not dry_run:
        loaded_at = datetime.now(timezone.utc)
        with session_scope() as session:
            existing_rows_by_key = fetch_existing_funnel_rows(
                session,
                date_from=date_from,
                date_to=date_to,
                nm_ids=resolved_nm_ids,
            )
            fact_rows = build_detail_history_fact_rows(
                normalized_frame,
                loaded_at=loaded_at,
                existing_rows_by_key=existing_rows_by_key,
            )
            keys_in_report = {(row["date"], int(row["nm_id"])) for row in fact_rows}
            inserted_new_rows = sum(1 for key in keys_in_report if key not in existing_rows_by_key)
            updated_existing_rows = sum(1 for key in keys_in_report if key in existing_rows_by_key)
            upserted_rows = apply_detail_history_rows(session, fact_rows)
            skipped_rows = max(len(normalized_frame) - len(fact_rows), 0)
    else:
        skipped_rows = int(normalized_frame["date"].isna().sum() + normalized_frame["nm_id"].isna().sum()) if not normalized_frame.empty else 0

    summary = {
        "dry_run": dry_run,
        "requested_nm_ids": len(resolved_nm_ids),
        "report_rows": int(len(raw_frame)),
        "parsed_rows": int(len(normalized_frame.dropna(subset=["date", "nm_id"]))),
        "upserted_rows": upserted_rows,
        "updated_existing_rows": updated_existing_rows,
        "inserted_new_rows": inserted_new_rows,
        "skipped_rows": skipped_rows,
        "gaps_total": int(len(gap_rows)) if not gap_rows.empty else 0,
        "gaps_found_in_report": int((matched_frame["match_status"] == "FOUND").sum()) if not matched_frame.empty else 0,
        "remaining_gaps": int((matched_frame["match_status"] != "FOUND").sum()) if not matched_frame.empty else 0,
        "errors": [],
        "create_attempts": create_attempts,
        "poll_attempts": poll_attempts,
        "download_id": download_id,
        "download_meta": {
            **download_meta,
            "download_status": download_status,
            "download_error": download_error,
            "list_payload_summary": _payload_summary(list_payload),
        },
    }
    if save_raw_dir is not None:
        summary["artifacts"] = save_artifacts(
            save_raw_dir=save_raw_dir,
            download_id=download_id,
            zip_bytes=zip_bytes,
            raw_frame=raw_frame,
            normalized_frame=normalized_frame,
            matched_frame=matched_frame,
            summary=summary,
        )
    return summary
