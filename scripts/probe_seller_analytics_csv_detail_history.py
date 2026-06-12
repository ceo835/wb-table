#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import io
import json
import sys
import time
import uuid
import zipfile
from dataclasses import asdict, dataclass
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable

import pandas as pd
import requests


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.config.settings import settings


WB_ANALYTICS_BASE = "https://seller-analytics-api.wildberries.ru"
DEFAULT_GAP_FILE = ROOT_DIR / "data" / "manual_gap_reports" / "api_gap_funnel_recent_2026-06-05_2026-06-07.csv"
RAW_OUTPUT_PATH = ROOT_DIR / "data" / "processed" / "detail_history_probe_raw.csv"
MATCHED_OUTPUT_PATH = ROOT_DIR / "data" / "processed" / "detail_history_probe_matched_gaps.csv"
SUMMARY_OUTPUT_PATH = ROOT_DIR / "data" / "processed" / "detail_history_probe_summary.json"

FUNNEL_FIELD_ALIASES = {
    "card_clicks": (
        "card_clicks",
        "opencount",
        "open_count",
        "opencard",
        "opencardcount",
        "cardclicks",
        "переходывкарточку",
        "переходывкарточкутовара",
        "открытиякарточки",
    ),
    "cart_count": (
        "cart_count",
        "cartcount",
        "addtocartcount",
        "addtocart",
        "корзины",
        "положиливкорзину",
        "добавлениявкорзину",
    ),
    "order_count": (
        "order_count",
        "ordercount",
        "orderscount",
        "заказы",
        "заказышт",
    ),
    "order_sum": (
        "order_sum",
        "ordersum",
        "orderssumrub",
        "revenue",
        "salesum",
        "заказалинасумму",
        "суммазаказов",
    ),
    "buyout_count": (
        "buyout_count",
        "buyoutcount",
        "buyoutscount",
        "выкупы",
        "выкупышт",
    ),
    "buyout_sum": (
        "buyout_sum",
        "buyoutsum",
        "buyoutssumrub",
        "суммавыкупа",
    ),
    "add_to_cart_conversion": (
        "addtocartconversion",
        "cartconversion",
        "конверсиявкорзину",
    ),
    "cart_to_order_conversion": (
        "carttoorderconversion",
        "orderconversion",
        "конверсиявзаказ",
        "конверсиякорзинывзаказ",
    ),
}

IDENTITY_ALIASES = {
    "date": ("date", "day", "дата"),
    "nm_id": ("nmid", "nm_id", "nmidwb", "артикулwb", "артикулвб"),
    "supplier_article": ("supplierarticle", "vendorcode", "артикулпродавца"),
    "title": ("title", "name", "название"),
}


@dataclass(slots=True)
class ProbeTargetRow:
    report_date: date
    supplier_article: str
    nm_id: int
    missing_labels: list[str]
    recommendation: str


@dataclass(slots=True)
class ProbeTargets:
    rows: list[ProbeTargetRow]
    nm_ids: list[int]


@dataclass(slots=True)
class CreateAttempt:
    label: str
    http_status: str
    response_type: str
    error: str
    request_body: dict[str, Any]
    response_body: Any
    download_id: str


@dataclass(slots=True)
class PollAttempt:
    poll_number: int
    http_status: str
    matched_report_status: str
    download_id: str
    reports_seen: int
    error: str


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Probe WB Seller Analytics CSV DETAIL_HISTORY_REPORT.")
    parser.add_argument("--gap-file", type=Path, default=DEFAULT_GAP_FILE)
    parser.add_argument("--date-from", type=date.fromisoformat, default=date(2026, 6, 4))
    parser.add_argument("--date-to", type=date.fromisoformat, default=date(2026, 6, 7))
    parser.add_argument("--poll-interval-seconds", type=int, default=10)
    parser.add_argument("--max-polls", type=int, default=18)
    parser.add_argument("--timeout-seconds", type=int, default=60)
    parser.add_argument("--report-type", default="DETAIL_HISTORY_REPORT")
    return parser.parse_args()


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


def load_probe_targets(path: Path) -> ProbeTargets:
    frame = pd.read_csv(path)
    rows: list[ProbeTargetRow] = []
    seen: set[tuple[date, int]] = set()
    nm_ids: set[int] = set()
    for record in frame.to_dict(orient="records"):
        report_date = _coerce_date(record.get("Дата"))
        nm_id = _coerce_int(record.get("Артикул WB"))
        if report_date is None or nm_id is None:
            continue
        key = (report_date, nm_id)
        if key in seen:
            continue
        seen.add(key)
        nm_ids.add(nm_id)
        rows.append(
            ProbeTargetRow(
                report_date=report_date,
                supplier_article=str(record.get("Артикул продавца") or "").strip(),
                nm_id=nm_id,
                missing_labels=[part.strip() for part in str(record.get("Что отсутствует") or "").split(",") if part.strip()],
                recommendation=str(record.get("Рекомендация") or "").strip(),
            )
        )
    rows.sort(key=lambda item: (item.report_date, item.nm_id))
    return ProbeTargets(rows=rows, nm_ids=sorted(nm_ids))


def _alias_map() -> dict[str, str]:
    mapping: dict[str, str] = {}
    for target, aliases in {**IDENTITY_ALIASES, **FUNNEL_FIELD_ALIASES}.items():
        for alias in aliases:
            mapping[alias] = target
    mapping["dt"] = "date"
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
    for numeric_column in (
        "card_clicks",
        "cart_count",
        "order_count",
        "order_sum",
        "buyout_count",
        "buyout_sum",
        "add_to_cart_conversion",
        "cart_to_order_conversion",
    ):
        if numeric_column not in normalized.columns:
            normalized[numeric_column] = None
        normalized[numeric_column] = normalized[numeric_column].map(_coerce_number)
    normalized["supplier_article"] = normalized["supplier_article"].map(lambda value: str(value).strip() if value not in (None, "") else "")
    normalized["title"] = normalized["title"].map(lambda value: str(value).strip() if value not in (None, "") else "")
    keep_columns = [
        "date",
        "nm_id",
        "supplier_article",
        "title",
        "card_clicks",
        "cart_count",
        "order_count",
        "order_sum",
        "buyout_count",
        "buyout_sum",
        "add_to_cart_conversion",
        "cart_to_order_conversion",
    ]
    for column in keep_columns:
        if column not in normalized.columns:
            normalized[column] = None
    return normalized[keep_columns]


def build_gap_match_frame(target_rows: Iterable[ProbeTargetRow], report_frame: pd.DataFrame) -> pd.DataFrame:
    indexed: dict[tuple[date, int], dict[str, Any]] = {}
    for record in report_frame.to_dict(orient="records"):
        report_date = record.get("date")
        nm_id = record.get("nm_id")
        if report_date is None or nm_id is None:
            continue
        indexed[(report_date, nm_id)] = record

    rows: list[dict[str, Any]] = []
    for target in target_rows:
        matched = indexed.get((target.report_date, target.nm_id), {})
        row = {
            "report_date": target.report_date.isoformat(),
            "supplier_article": target.supplier_article,
            "nm_id": target.nm_id,
            "missing_labels": ", ".join(target.missing_labels),
            "recommendation": target.recommendation,
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
        rows.append(row)
    return pd.DataFrame(rows)


def build_probe_summary(
    *,
    date_from: date,
    date_to: date,
    targets_count: int,
    unique_nm_ids_count: int,
    report_frame: pd.DataFrame,
    matched_frame: pd.DataFrame,
    create_attempts: list[dict[str, Any]],
    poll_attempts: list[dict[str, Any]],
    download_meta: dict[str, Any],
) -> dict[str, Any]:
    report_dates = sorted({value.isoformat() for value in report_frame["date"].dropna().tolist()}) if "date" in report_frame else []
    report_columns = report_frame.columns.tolist()
    create_errors = [attempt["error"] for attempt in create_attempts if attempt.get("error")]
    download_status = str(download_meta.get("download_status") or "")
    if report_columns:
        probe_status = "DOWNLOADED"
    elif any("sum type variant" in error.lower() for error in create_errors):
        probe_status = "MISSING_SUM_TYPE_VARIANT"
    elif any(attempt.get("http_status") == "429" for attempt in create_attempts):
        probe_status = "RATE_LIMITED"
    elif create_attempts:
        probe_status = "CREATE_FAILED"
    else:
        probe_status = "NOT_STARTED"
    return {
        "probe_status": probe_status,
        "date_from": date_from.isoformat(),
        "date_to": date_to.isoformat(),
        "gap_rows_total": targets_count,
        "gap_unique_nm_ids_total": unique_nm_ids_count,
        "report_rows_total": int(len(report_frame)),
        "report_distinct_nm_ids": int(report_frame["nm_id"].dropna().nunique()) if "nm_id" in report_frame else 0,
        "report_distinct_dates": report_dates,
        "report_columns": report_columns,
        "gap_rows_found_in_report": int((matched_frame["match_status"] == "FOUND").sum()) if not matched_frame.empty else 0,
        "gap_rows_with_card_clicks": int(matched_frame["has_card_clicks"].sum()) if "has_card_clicks" in matched_frame else 0,
        "gap_rows_with_cart_count": int(matched_frame["has_cart_count"].sum()) if "has_cart_count" in matched_frame else 0,
        "gap_rows_with_order_count": int(matched_frame["has_order_count"].sum()) if "has_order_count" in matched_frame else 0,
        "gap_rows_with_order_sum": int(matched_frame["has_order_sum"].sum()) if "has_order_sum" in matched_frame else 0,
        "create_attempts": create_attempts,
        "poll_attempts": poll_attempts,
        "download_meta": download_meta,
        "can_map_to_funnel": {
            "date": "date" in report_columns,
            "nm_id": "nm_id" in report_columns,
            "supplier_article": "supplier_article" in report_columns,
            "card_clicks": "card_clicks" in report_columns,
            "cart_count": "cart_count" in report_columns,
            "order_count": "order_count" in report_columns,
            "order_sum": "order_sum" in report_columns,
            "buyout_count": "buyout_count" in report_columns and report_frame["buyout_count"].notna().any() if "buyout_count" in report_frame else False,
            "buyout_sum": "buyout_sum" in report_columns and report_frame["buyout_sum"].notna().any() if "buyout_sum" in report_frame else False,
            "add_to_cart_conversion": "add_to_cart_conversion" in report_columns and report_frame["add_to_cart_conversion"].notna().any() if "add_to_cart_conversion" in report_frame else False,
            "cart_to_order_conversion": "cart_to_order_conversion" in report_columns and report_frame["cart_to_order_conversion"].notna().any() if "cart_to_order_conversion" in report_frame else False,
        },
    }


def _analytics_headers() -> dict[str, str]:
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
            headers=_analytics_headers(),
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


def _request_bytes(
    session: requests.Session,
    url: str,
    *,
    timeout_seconds: int = 60,
) -> tuple[str, bytes, str, str]:
    try:
        response = session.get(url, headers={"Authorization": settings.wb_analytics_token or "", "Accept": "*/*"}, timeout=timeout_seconds)
    except requests.RequestException as exc:
        return "REQUEST_ERROR", b"", "", _truncate_error(exc)
    if response.status_code >= 400:
        return str(response.status_code), b"", response.headers.get("Content-Type", ""), _truncate_error(response.text or response.reason)
    return str(response.status_code), response.content, response.headers.get("Content-Type", ""), ""


def _extract_download_id(payload: Any) -> str:
    if isinstance(payload, dict):
        for key in ("id", "downloadId"):
            value = payload.get(key)
            if value:
                return str(value)
        for nested_key in ("data", "result"):
            nested = payload.get(nested_key)
            extracted = _extract_download_id(nested)
            if extracted:
                return extracted
    if isinstance(payload, list):
        for item in payload:
            extracted = _extract_download_id(item)
            if extracted:
                return extracted
    return ""


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


def _match_download_report(reports: list[dict[str, Any]], *, download_id: str, report_name_prefix: str) -> dict[str, Any] | None:
    if download_id:
        matched = next((item for item in reports if str(item.get("id") or item.get("downloadId") or "") == download_id), None)
        if matched is not None:
            return matched
    return next(
        (
            item
            for item in reports
            if str(item.get("name") or "").startswith(report_name_prefix)
        ),
        None,
    )


def _build_create_payloads(
    *,
    report_name: str,
    report_type: str,
    date_from: date,
    date_to: date,
    nm_ids: list[int],
) -> list[tuple[str, dict[str, Any]]]:
    base_id = str(uuid.uuid4())
    return [
        (
            "official_schema",
            {
                "id": base_id,
                "reportType": report_type,
                "userReportName": f"{report_name} official",
                "params": {
                    "startDate": date_from.isoformat(),
                    "endDate": date_to.isoformat(),
                    "nmIDs": nm_ids,
                    "subjectIds": [],
                    "brandNames": [],
                    "tagIds": [],
                    "timezone": "Europe/Moscow",
                    "aggregationLevel": "day",
                    "skipDeletedNm": False,
                },
            },
        ),
        (
            "official_schema_skip_deleted_true",
            {
                "id": str(uuid.uuid4()),
                "reportType": report_type,
                "userReportName": f"{report_name} skip-deleted-true",
                "params": {
                    "startDate": date_from.isoformat(),
                    "endDate": date_to.isoformat(),
                    "nmIDs": nm_ids,
                    "subjectIds": [],
                    "brandNames": [],
                    "tagIds": [],
                    "timezone": "Europe/Moscow",
                    "aggregationLevel": "day",
                    "skipDeletedNm": True,
                },
            },
        ),
        (
            "official_schema_lowercase_nmids",
            {
                "id": str(uuid.uuid4()),
                "reportType": report_type,
                "userReportName": f"{report_name} lowercase-nmids",
                "params": {
                    "startDate": date_from.isoformat(),
                    "endDate": date_to.isoformat(),
                    "nmIds": nm_ids,
                    "subjectIds": [],
                    "brandNames": [],
                    "tagIds": [],
                    "timezone": "Europe/Moscow",
                    "aggregationLevel": "day",
                    "skipDeletedNm": False,
                },
            },
        ),
    ]


def _create_detail_history_report(
    session: requests.Session,
    *,
    report_name: str,
    report_type: str,
    date_from: date,
    date_to: date,
    nm_ids: list[int],
    timeout_seconds: int,
) -> tuple[str, list[dict[str, Any]]]:
    attempts: list[dict[str, Any]] = []
    for label, payload in _build_create_payloads(
        report_name=report_name,
        report_type=report_type,
        date_from=date_from,
        date_to=date_to,
        nm_ids=nm_ids,
    ):
        status, response_payload, error = _request_json(
            session,
            "POST",
            f"{WB_ANALYTICS_BASE}/api/v2/nm-report/downloads",
            json_body=payload,
            timeout_seconds=timeout_seconds,
        )
        download_id = _extract_download_id(response_payload)
        attempts.append(
            asdict(
                CreateAttempt(
                    label=label,
                    http_status=status,
                    response_type=_payload_summary(response_payload),
                    error=error,
                    request_body=payload,
                    response_body=response_payload,
                    download_id=download_id,
                )
            )
        )
        if status in {"200", "201", "202"}:
            return download_id, attempts
        if status == "429":
            return "", attempts
    return "", attempts


def _poll_report_until_ready(
    session: requests.Session,
    *,
    report_name: str,
    download_id: str,
    max_polls: int,
    poll_interval_seconds: int,
    timeout_seconds: int,
) -> tuple[str, list[dict[str, Any]], Any]:
    polls: list[dict[str, Any]] = []
    last_payload: Any = None
    for index in range(1, max_polls + 1):
        status, payload, error = _request_json(
            session,
            "GET",
            f"{WB_ANALYTICS_BASE}/api/v2/nm-report/downloads",
            timeout_seconds=timeout_seconds,
        )
        last_payload = payload
        reports = _extract_reports(payload)
        matched_report = _match_download_report(reports, download_id=download_id, report_name_prefix=report_name)
        matched_status = str(matched_report.get("status") or "") if matched_report else ""
        matched_id = str(matched_report.get("id") or matched_report.get("downloadId") or download_id or "") if matched_report else download_id
        polls.append(
            asdict(
                PollAttempt(
                    poll_number=index,
                    http_status=status,
                    matched_report_status=matched_status,
                    download_id=matched_id,
                    reports_seen=len(reports),
                    error=error,
                )
            )
        )
        if matched_status.upper() == "SUCCESS" and matched_id:
            return matched_id, polls, payload
        if matched_status.upper() in {"FAILED", "ERROR"}:
            return matched_id, polls, payload
        if index < max_polls:
            time.sleep(poll_interval_seconds)
    return download_id, polls, last_payload


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


def _extract_report_frame(content: bytes, content_type: str) -> tuple[pd.DataFrame, dict[str, Any]]:
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


def _save_frame(frame: pd.DataFrame, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


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


def _save_json(payload: dict[str, Any], path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def main() -> None:
    args = parse_args()
    if not settings.wb_analytics_token:
        raise SystemExit("WB_ANALYTICS_TOKEN not configured")

    targets = load_probe_targets(args.gap_file)
    report_name = f"detail-history-probe-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    session = requests.Session()
    download_id, create_attempts = _create_detail_history_report(
        session,
        report_name=report_name,
        report_type=args.report_type,
        date_from=args.date_from,
        date_to=args.date_to,
        nm_ids=targets.nm_ids,
        timeout_seconds=args.timeout_seconds,
    )

    resolved_download_id = download_id
    poll_attempts: list[dict[str, Any]] = []
    list_payload: Any = None
    if any(attempt["http_status"] in {"200", "201", "202"} for attempt in create_attempts):
        resolved_download_id, poll_attempts, list_payload = _poll_report_until_ready(
            session,
            report_name=report_name,
            download_id=download_id,
            max_polls=args.max_polls,
            poll_interval_seconds=args.poll_interval_seconds,
            timeout_seconds=args.timeout_seconds,
        )

    raw_frame = pd.DataFrame()
    matched_frame = pd.DataFrame()
    download_meta: dict[str, Any] = {"content_type": "", "archive_member": "", "content_size_bytes": 0}
    download_status = "SKIPPED"
    download_error = ""
    if resolved_download_id:
        download_status, content, content_type, download_error = _request_bytes(
            session,
            f"{WB_ANALYTICS_BASE}/api/v2/nm-report/downloads/file/{resolved_download_id}",
            timeout_seconds=args.timeout_seconds,
        )
        if download_status == "200":
            raw_frame, download_meta = _extract_report_frame(content, content_type)
            normalized_frame = normalize_detail_history_frame(raw_frame)
            matched_frame = build_gap_match_frame(targets.rows, normalized_frame)
    if matched_frame.empty:
        matched_frame = build_gap_match_frame(targets.rows, pd.DataFrame(columns=["date", "nm_id"]))
    _save_frame(raw_frame, RAW_OUTPUT_PATH)
    _save_frame(matched_frame, MATCHED_OUTPUT_PATH)

    summary = build_probe_summary(
        date_from=args.date_from,
        date_to=args.date_to,
        targets_count=len(targets.rows),
        unique_nm_ids_count=len(targets.nm_ids),
        report_frame=normalize_detail_history_frame(raw_frame) if not raw_frame.empty else pd.DataFrame(),
        matched_frame=matched_frame,
        create_attempts=create_attempts,
        poll_attempts=poll_attempts,
        download_meta={
            **download_meta,
            "download_status": download_status,
            "download_error": download_error,
            "download_id": resolved_download_id,
            "report_name": report_name,
            "list_payload_summary": _payload_summary(list_payload),
        },
    )
    _save_json(summary, SUMMARY_OUTPUT_PATH)

    print(json.dumps(_json_safe(summary), ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
