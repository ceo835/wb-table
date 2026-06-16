from __future__ import annotations

import csv
import io
import json
from datetime import date, datetime
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import requests

from src.clients.wb_statistics_client import WBStatisticsClient
from src.config.settings import settings
from src.db.ad_cost_loader import collect_ad_cost_rows
from src.db.detail_history_report_loader import (
    create_detail_history_download_task,
    download_detail_history_file,
    extract_detail_history_frame,
    normalize_detail_history_frame,
    poll_detail_history_download,
)
from src.pipelines.mvp_real_run import MvpRealRun


ROOT_DIR = Path(__file__).resolve().parents[2]
OUTPUT_DIR = ROOT_DIR / "data" / "processed" / "vbro_raw_probe_2026-05-23"
SUMMARY_PATH = OUTPUT_DIR / "summary.json"
PROBE_DATE = date(2026, 5, 23)
WB_STATISTICS_BASE = "https://statistics-api.wildberries.ru"
WB_ANALYTICS_BASE = "https://seller-analytics-api.wildberries.ru"

TARGET_PRODUCTS: tuple[dict[str, Any], ...] = (
    {
        "nm_id": 197330807,
        "supplier_article": "BlackWOM5",
    },
    {
        "nm_id": 37320545,
        "supplier_article": "Brand_Wom7Сlassic7",
    },
)
TARGETS_BY_NM_ID = {int(item["nm_id"]): dict(item) for item in TARGET_PRODUCTS}
TARGET_NM_IDS = tuple(sorted(TARGETS_BY_NM_ID))

FORBIDDEN_SUMMARY_KEYS = {
    "organic_orders_by_orders",
    "organic_buyouts_by_buyouts",
    "profit_before_cogs",
    "profit_before_cogs_per_unit",
    "calculated_operating_profit",
    "margin",
    "profit",
}
LOOKUP_SCHEMA_PATHS = (
    ROOT_DIR / "src" / "db" / "models.py",
    ROOT_DIR / "data" / "processed" / "database_table_field_map.csv",
)


def _truncate_error(value: Any, limit: int = 240) -> str:
    if not value:
        return ""
    return " ".join(str(value).split())[:limit]


def _to_int(value: Any) -> int | None:
    if value in (None, "", [], {}):
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(float(str(value).replace(" ", "").replace(",", ".")))
    except Exception:
        return None


def _to_date(value: Any) -> date | None:
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


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Path):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    if isinstance(value, pd.Timestamp):
        return value.isoformat()
    if hasattr(value, "item") and callable(getattr(value, "item")):
        try:
            return value.item()
        except Exception:
            return value
    return value


def _write_json(path: Path, payload: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(_json_safe(payload), ensure_ascii=False, indent=2), encoding="utf-8")


def _write_dataframe(path: Path, frame: pd.DataFrame) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    frame.to_csv(path, index=False, encoding="utf-8-sig")


def _write_records_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    _write_dataframe(path, pd.DataFrame(list(rows)))


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    headers: Mapping[str, str],
    *,
    params: Mapping[str, Any] | None = None,
    json_body: Mapping[str, Any] | None = None,
    timeout_seconds: int = 60,
) -> tuple[str, Any, str]:
    try:
        response = session.request(
            method=method,
            url=url,
            headers=dict(headers),
            params=params,
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


def _payload_summary(payload: Any) -> str:
    if payload is None:
        return "empty"
    if isinstance(payload, dict):
        return f"dict:{','.join(list(payload)[:8])}"
    if isinstance(payload, list):
        return f"list:{len(payload)}"
    return type(payload).__name__


def _statistics_headers() -> dict[str, str]:
    return {
        "Authorization": settings.wb_token or "",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _analytics_headers() -> dict[str, str]:
    return {
        "Authorization": settings.wb_analytics_token or "",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _promotion_headers(runner: MvpRealRun) -> dict[str, str]:
    return runner._headers_promotion()


def _extract_records(payload: Any) -> list[dict[str, Any]]:
    if isinstance(payload, list):
        return [item for item in payload if isinstance(item, dict)]
    if isinstance(payload, dict):
        for key in ("data", "items", "rows", "result", "report", "cards", "history"):
            value = payload.get(key)
            if isinstance(value, list):
                return [item for item in value if isinstance(item, dict)]
            if isinstance(value, dict):
                nested = _extract_records(value)
                if nested:
                    return nested
        return [payload]
    return []


def _fields_from_payload(payload: Any) -> list[str]:
    if isinstance(payload, pd.DataFrame):
        return [str(column) for column in payload.columns.tolist()]
    records = _extract_records(payload)
    if records:
        fields: set[str] = set()
        for item in records:
            fields.update(str(key) for key in item.keys())
        return sorted(fields)
    if isinstance(payload, dict):
        return sorted(str(key) for key in payload.keys())
    return []


def _filter_rows_by_nm_and_date(
    rows: Iterable[Mapping[str, Any]],
    *,
    nm_ids: Sequence[int],
    probe_date: date,
    nm_keys: Sequence[str],
    date_keys: Sequence[str],
) -> list[dict[str, Any]]:
    target_set = {int(item) for item in nm_ids}
    result: list[dict[str, Any]] = []
    for row in rows:
        nm_id = next((_to_int(row.get(key)) for key in nm_keys if _to_int(row.get(key)) is not None), None)
        if nm_id not in target_set:
            continue
        if date_keys:
            row_date = next((_to_date(row.get(key)) for key in date_keys if _to_date(row.get(key)) is not None), None)
            if row_date is not None and row_date != probe_date:
                continue
        result.append(dict(row))
    return result


def extract_deductions_rows(
    rows: Iterable[Mapping[str, Any]],
    *,
    nm_ids: Sequence[int],
    probe_date: date,
) -> list[dict[str, Any]]:
    filtered = _filter_rows_by_nm_and_date(
        rows,
        nm_ids=nm_ids,
        probe_date=probe_date,
        nm_keys=("nm_id", "nmId", "nmID", "nmid"),
        date_keys=("sale_dt", "date", "rr_dt", "create_dt"),
    )
    deductions: list[dict[str, Any]] = []
    for row in filtered:
        if any(
            row.get(key) not in (None, "", 0, 0.0, "0", "0.0")
            for key in ("deduction", "penalty", "acceptance", "additional_payment")
        ):
            deductions.append(dict(row))
    return deductions


def build_source_summary(
    *,
    source_name: str,
    endpoint: str,
    saved_files: Sequence[str],
    http_status: str | None,
    rows_count: int,
    fields_available: Sequence[str],
    error: str = "",
    note: str = "",
) -> dict[str, Any]:
    status = "OK"
    if http_status in {"404", "405"}:
        status = "ENDPOINT_NOT_CONFIRMED"
    elif http_status in {"400", "401", "402", "403", "429", "500", "REQUEST_ERROR"}:
        status = "FAILED"
    elif rows_count == 0:
        status = "EMPTY"
    payload = {
        "source_name": source_name,
        "endpoint": endpoint,
        "http_status": http_status or "",
        "status": status,
        "rows_count": rows_count,
        "fields_available": list(fields_available),
        "saved_files": list(saved_files),
        "error": error,
        "note": note,
    }
    for forbidden_key in FORBIDDEN_SUMMARY_KEYS:
        payload.pop(forbidden_key, None)
    return payload


def build_probe_summary(
    *,
    output_dir: Path,
    source_summaries: Mapping[str, Mapping[str, Any]],
) -> dict[str, Any]:
    succeeded: list[str] = []
    failed: list[str] = []
    empty: list[str] = []
    require_other_endpoint: list[str] = []
    saved_files: list[str] = []
    for source_name, meta in source_summaries.items():
        status = str(meta.get("status") or "")
        if status == "OK":
            succeeded.append(source_name)
        elif status == "EMPTY":
            empty.append(source_name)
        elif status == "ENDPOINT_NOT_CONFIRMED":
            require_other_endpoint.append(source_name)
        else:
            failed.append(source_name)
        saved_files.extend(meta.get("saved_files", []))

    summary = {
        "probe_date": PROBE_DATE.isoformat(),
        "targets": [dict(item) for item in TARGET_PRODUCTS],
        "output_dir": str(output_dir),
        "sources_succeeded": sorted(succeeded),
        "sources_failed": sorted(failed),
        "sources_empty": sorted(empty),
        "sources_require_another_endpoint_or_host": sorted(require_other_endpoint),
        "saved_files": sorted(saved_files),
        "sources": {key: dict(value) for key, value in source_summaries.items()},
    }
    summary_text = json.dumps(_json_safe(summary), ensure_ascii=False)
    for forbidden_key in FORBIDDEN_SUMMARY_KEYS:
        if forbidden_key in summary_text:
            raise ValueError(f"Forbidden field leaked into summary: {forbidden_key}")
    return summary


def _decode_csv_bytes(content: bytes) -> pd.DataFrame:
    text = ""
    for encoding in ("utf-8-sig", "utf-8", "cp1251", "windows-1251", "latin-1"):
        try:
            text = content.decode(encoding)
            break
        except UnicodeDecodeError:
            continue
    sample = text[:4096]
    delimiter = ","
    try:
        dialect = csv.Sniffer().sniff(sample, delimiters=",;\t|")
        delimiter = dialect.delimiter
    except csv.Error:
        if ";" in sample and sample.count(";") > sample.count(","):
            delimiter = ";"
    return pd.read_csv(io.StringIO(text), sep=delimiter)


def _fetch_detail_history_report(
    probe_date: date,
    nm_ids: Sequence[int],
) -> tuple[dict[str, Any], pd.DataFrame]:
    session = requests.Session()
    report_name_prefix, create_attempts, create_error = create_detail_history_download_task(
        session,
        date_from=probe_date,
        date_to=probe_date,
        nm_ids=nm_ids,
    )
    create_path = OUTPUT_DIR / "detail_history_report_create_attempts.json"
    _write_json(create_path, {"attempts": create_attempts, "error": create_error, "report_name_prefix": report_name_prefix})

    if not any(attempt.get("http_status") == "200" for attempt in create_attempts):
        return (
            build_source_summary(
                source_name="detail_history_report",
                endpoint="/api/v2/nm-report/downloads",
                saved_files=[create_path.name],
                http_status=create_attempts[-1]["http_status"] if create_attempts else "",
                rows_count=0,
                fields_available=[],
                error=create_error,
            ),
            pd.DataFrame(),
        )

    download_id, poll_attempts, poll_payload = poll_detail_history_download(
        session,
        report_name_prefix=report_name_prefix,
        poll_interval_seconds=15,
        max_polls=8,
    )
    poll_path = OUTPUT_DIR / "detail_history_report_poll_attempts.json"
    _write_json(poll_path, {"attempts": poll_attempts, "poll_payload_summary": _payload_summary(poll_payload), "download_id": download_id})
    if not download_id:
        return (
            build_source_summary(
                source_name="detail_history_report",
                endpoint="/api/v2/nm-report/downloads",
                saved_files=[create_path.name, poll_path.name],
                http_status=poll_attempts[-1]["http_status"] if poll_attempts else "",
                rows_count=0,
                fields_available=[],
                error="download_id_not_resolved",
            ),
            pd.DataFrame(),
        )

    download_status, zip_bytes, content_type, download_error = download_detail_history_file(session, download_id)
    if download_status != "200":
        error_path = OUTPUT_DIR / "detail_history_report_error.json"
        _write_json(
            error_path,
            {
                "download_id": download_id,
                "http_status": download_status,
                "content_type": content_type,
                "error": download_error,
            },
        )
        return (
            build_source_summary(
                source_name="detail_history_report",
                endpoint="/api/v2/nm-report/downloads/file/{downloadId}",
                saved_files=[create_path.name, poll_path.name, error_path.name],
                http_status=download_status,
                rows_count=0,
                fields_available=[],
                error=download_error,
            ),
            pd.DataFrame(),
        )

    raw_frame, _ = extract_detail_history_frame(zip_bytes, content_type)
    normalized = normalize_detail_history_frame(raw_frame)
    raw_path = OUTPUT_DIR / "detail_history_report_raw.csv"
    normalized_path = OUTPUT_DIR / "detail_history_report_normalized.csv"
    zip_path = OUTPUT_DIR / "detail_history_report_raw.zip"
    _write_dataframe(raw_path, raw_frame)
    _write_dataframe(normalized_path, normalized)
    zip_path.write_bytes(zip_bytes)

    return (
        build_source_summary(
            source_name="detail_history_report",
            endpoint="/api/v2/nm-report/downloads",
            saved_files=[create_path.name, poll_path.name, zip_path.name, raw_path.name, normalized_path.name],
            http_status=download_status,
            rows_count=int(len(raw_frame)),
            fields_available=raw_frame.columns.tolist(),
            note=f"download_id={download_id}",
        ),
        normalized,
    )


def _probe_nm_report_endpoint(
    *,
    endpoint: str,
    artifact_name: str,
    probe_date: date,
    nm_ids: Sequence[int],
) -> dict[str, Any]:
    session = requests.Session()
    payload_variants = [
        {
            "nmIDs": list(nm_ids),
            "startDate": probe_date.isoformat(),
            "endDate": probe_date.isoformat(),
            "timezone": "Europe/Moscow",
            "aggregationLevel": "day",
            "skipDeletedNm": False,
        },
        {
            "selectedPeriod": {"start": probe_date.isoformat(), "end": probe_date.isoformat()},
            "nmIDs": list(nm_ids),
            "timezone": "Europe/Moscow",
            "aggregationLevel": "day",
            "skipDeletedNm": False,
        },
    ]
    attempts: list[dict[str, Any]] = []
    success_payload: Any = None
    success_status = ""
    success_error = ""
    for index, payload in enumerate(payload_variants, start=1):
        status, response_payload, error = _request_json(
            session,
            "POST",
            f"{WB_ANALYTICS_BASE}{endpoint}",
            _analytics_headers(),
            json_body=payload,
        )
        attempts.append(
            {
                "attempt": index,
                "http_status": status,
                "error": error,
                "request_body": payload,
                "response_summary": _payload_summary(response_payload),
                "response_body": response_payload,
            }
        )
        if status == "200":
            success_payload = response_payload
            success_status = status
            break
        success_status = status
        success_error = error
    artifact_path = OUTPUT_DIR / artifact_name
    _write_json(artifact_path, {"endpoint": endpoint, "attempts": attempts})
    summary_payload = success_payload if success_payload is not None else {}
    rows = len(_extract_records(summary_payload))
    return build_source_summary(
        source_name=artifact_name.replace("_raw.json", ""),
        endpoint=endpoint,
        saved_files=[artifact_path.name],
        http_status=success_status,
        rows_count=rows,
        fields_available=_fields_from_payload(summary_payload),
        error=success_error,
    )


def _fetch_fullstats_raw(
    probe_date: date,
    nm_ids: Sequence[int],
) -> dict[str, Any]:
    runner = MvpRealRun()
    runner.date_from = probe_date
    runner.date_to = probe_date
    runner.nm_ids = list(nm_ids)
    artifact_path = OUTPUT_DIR / "adv_fullstats_raw.json"
    try:
        ad_event_rows, _, ad_cost_meta = collect_ad_cost_rows(runner, probe_date, probe_date, nm_ids=nm_ids)
        advert_ids = sorted({int(row["advertId"]) for row in ad_event_rows if row.get("advertId") not in (None, "")})
    except Exception as exc:
        _write_json(artifact_path, {"error": str(exc)})
        return build_source_summary(
            source_name="adv_fullstats",
            endpoint="/adv/v3/fullstats",
            saved_files=[artifact_path.name],
            http_status="REQUEST_ERROR",
            rows_count=0,
            fields_available=[],
            error=str(exc),
        )

    requests_payloads: list[dict[str, Any]] = []
    nm_row_count = 0
    nm_fields: set[str] = set()
    for start_index in range(0, len(advert_ids), 20):
        chunk = advert_ids[start_index:start_index + 20]
        status, payload, error = _request_json(
            requests.Session(),
            "GET",
            "https://advert-api.wildberries.ru/adv/v3/fullstats",
            _promotion_headers(runner),
            params={
                "ids": ",".join(str(value) for value in chunk),
                "beginDate": probe_date.isoformat(),
                "endDate": probe_date.isoformat(),
            },
        )
        requests_payloads.append(
            {
                "advert_ids": chunk,
                "http_status": status,
                "error": error,
                "payload": payload,
            }
        )
        for campaign in _extract_records(payload):
            for day in campaign.get("days", []) if isinstance(campaign.get("days"), list) else []:
                day_date = _to_date(day.get("date"))
                if day_date != probe_date:
                    continue
                for app in day.get("apps", []) if isinstance(day.get("apps"), list) else []:
                    for nm_row in app.get("nms", []) if isinstance(app.get("nms"), list) else []:
                        nm_id = _to_int(nm_row.get("nmId"))
                        if nm_id in TARGETS_BY_NM_ID:
                            nm_row_count += 1
                            nm_fields.update(str(key) for key in nm_row.keys())

    _write_json(
        artifact_path,
        {
            "probe_date": probe_date.isoformat(),
            "matched_ad_cost_rows": ad_event_rows,
            "ad_cost_meta": ad_cost_meta,
            "advert_ids": advert_ids,
            "requests": requests_payloads,
        },
    )
    last_status = requests_payloads[-1]["http_status"] if requests_payloads else "SKIPPED"
    last_error = requests_payloads[-1]["error"] if requests_payloads else "no_advert_ids"
    note = "advert ids resolved from ad_cost events" if advert_ids else "no advert ids resolved from ad_cost events"
    return build_source_summary(
        source_name="adv_fullstats",
        endpoint="/adv/v3/fullstats",
        saved_files=[artifact_path.name],
        http_status=last_status,
        rows_count=nm_row_count,
        fields_available=sorted(nm_fields),
        error=last_error if last_status != "200" else "",
        note=note,
    )


def _fetch_statistics_source(
    *,
    source_name: str,
    endpoint: str,
    artifact_name: str,
    probe_date: date,
    nm_keys: Sequence[str],
    date_keys: Sequence[str],
) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    session = requests.Session()
    status, payload, error = _request_json(
        session,
        "GET",
        f"{WB_STATISTICS_BASE}{endpoint}",
        _statistics_headers(),
        params={"dateFrom": probe_date.isoformat(), "dateTo": probe_date.isoformat(), "limit": 1000},
    )
    rows = _extract_records(payload)
    filtered = _filter_rows_by_nm_and_date(
        rows,
        nm_ids=TARGET_NM_IDS,
        probe_date=probe_date,
        nm_keys=nm_keys,
        date_keys=date_keys,
    )
    artifact_path = OUTPUT_DIR / artifact_name
    _write_records_csv(artifact_path, filtered)
    summary = build_source_summary(
        source_name=source_name,
        endpoint=endpoint,
        saved_files=[artifact_path.name],
        http_status=status,
        rows_count=len(filtered),
        fields_available=pd.DataFrame(filtered).columns.tolist() if filtered else _fields_from_payload(payload),
        error=error,
    )
    return summary, filtered


def _fetch_report_detail_by_period(probe_date: date) -> tuple[dict[str, Any], list[dict[str, Any]]]:
    artifact_path = OUTPUT_DIR / "report_detail_by_period_raw.csv"
    try:
        client = WBStatisticsClient()
        payload = client.wb_report_detail_by_period(probe_date, probe_date)
    except Exception as exc:
        _write_records_csv(artifact_path, [])
        summary = build_source_summary(
            source_name="report_detail_by_period",
            endpoint="/api/v5/supplier/reportDetailByPeriod",
            saved_files=[artifact_path.name],
            http_status="REQUEST_ERROR",
            rows_count=0,
            fields_available=[],
            error=str(exc),
        )
        return summary, []
    rows = payload if isinstance(payload, list) else []
    filtered = _filter_rows_by_nm_and_date(
        rows,
        nm_ids=TARGET_NM_IDS,
        probe_date=probe_date,
        nm_keys=("nm_id", "nmId", "nmID", "nmid"),
        date_keys=("sale_dt", "date", "rr_dt", "create_dt"),
    )
    _write_records_csv(artifact_path, filtered)
    summary = build_source_summary(
        source_name="report_detail_by_period",
        endpoint="/api/v5/supplier/reportDetailByPeriod",
        saved_files=[artifact_path.name],
        http_status="200" if isinstance(payload, list) else "FAILED",
        rows_count=len(filtered),
        fields_available=pd.DataFrame(filtered).columns.tolist() if filtered else _fields_from_payload(payload),
        error="" if isinstance(payload, list) else "empty_or_invalid_payload",
    )
    return summary, filtered


def _fetch_optional_statistics_source(
    *,
    source_name: str,
    endpoint: str,
    raw_csv_name: str,
    error_json_name: str,
    probe_date: date,
) -> dict[str, Any]:
    session = requests.Session()
    status, payload, error = _request_json(
        session,
        "GET",
        f"{WB_STATISTICS_BASE}{endpoint}",
        _statistics_headers(),
        params={"dateFrom": probe_date.isoformat(), "dateTo": probe_date.isoformat()},
    )
    if status != "200":
        error_path = OUTPUT_DIR / error_json_name
        _write_json(
            error_path,
            {
                "endpoint": endpoint,
                "http_status": status,
                "error": error,
                "response": payload,
            },
        )
        note = "endpoint_not_confirmed" if status == "404" else ""
        return build_source_summary(
            source_name=source_name,
            endpoint=endpoint,
            saved_files=[error_path.name],
            http_status=status,
            rows_count=0,
            fields_available=_fields_from_payload(payload),
            error=error,
            note=note,
        )
    rows = _extract_records(payload)
    filtered = _filter_rows_by_nm_and_date(
        rows,
        nm_ids=TARGET_NM_IDS,
        probe_date=probe_date,
        nm_keys=("nm_id", "nmId", "nmID", "nmid"),
        date_keys=("date", "lastChangeDate", "create_dt", "shkCreateDate"),
    )
    raw_path = OUTPUT_DIR / raw_csv_name
    _write_records_csv(raw_path, filtered)
    return build_source_summary(
        source_name=source_name,
        endpoint=endpoint,
        saved_files=[raw_path.name],
        http_status=status,
        rows_count=len(filtered),
        fields_available=pd.DataFrame(filtered).columns.tolist() if filtered else _fields_from_payload(payload),
        error="",
    )


def _fetch_stocks_raw(probe_date: date, nm_ids: Sequence[int]) -> dict[str, Any]:
    runner = MvpRealRun()
    runner.date_from = probe_date
    runner.date_to = probe_date
    runner.nm_ids = list(nm_ids)
    session = requests.Session()
    attempts: list[dict[str, Any]] = []

    get_status, get_payload, get_error = _request_json(
        session,
        "GET",
        f"{WB_ANALYTICS_BASE}/api/analytics/v1/stocks-report/wb-warehouses",
        _analytics_headers(),
    )
    attempts.append(
        {
            "endpoint": "/api/analytics/v1/stocks-report/wb-warehouses",
            "method": "GET",
            "http_status": get_status,
            "error": get_error,
            "response": get_payload,
        }
    )

    fallback_status, fallback_payload, fallback_error, fallback_meta = runner._fetch_stocks_paginated(probe_date)
    attempts.append(
        {
            "endpoint": "/api/v2/stocks-report/products/products",
            "method": "POST",
            "http_status": fallback_status,
            "error": fallback_error,
            "pagination_meta": fallback_meta,
            "response": fallback_payload,
        }
    )

    matched_rows: list[dict[str, Any]] = []
    for row in _extract_records(fallback_payload):
        nm_id = _to_int(row.get("nmId") or row.get("nmID") or row.get("nm_id"))
        if nm_id in TARGETS_BY_NM_ID:
            matched_rows.append(dict(row))

    artifact_path = OUTPUT_DIR / "stocks_wb_warehouses_raw.json"
    _write_json(
        artifact_path,
        {
            "probe_date": probe_date.isoformat(),
            "attempts": attempts,
            "matched_product_rows": matched_rows,
        },
    )
    note = "product snapshot fallback included" if fallback_status == "200" else ""
    return build_source_summary(
        source_name="stocks_wb_warehouses",
        endpoint="/api/analytics/v1/stocks-report/wb-warehouses",
        saved_files=[artifact_path.name],
        http_status=fallback_status if fallback_status == "200" else get_status,
        rows_count=len(matched_rows),
        fields_available=pd.DataFrame(matched_rows).columns.tolist() if matched_rows else _fields_from_payload(fallback_payload),
        error=fallback_error if fallback_status != "200" else get_error if get_status != "200" else "",
        note=note,
    )


def _build_lookup_payload(
    *,
    lookup_name: str,
    keywords: Sequence[str],
) -> dict[str, Any]:
    matches: list[dict[str, Any]] = []
    for path in LOOKUP_SCHEMA_PATHS:
        if not path.exists():
            continue
        text = path.read_text(encoding="utf-8", errors="ignore")
        for line_number, line in enumerate(text.splitlines(), start=1):
            lowered = line.lower()
            for keyword in keywords:
                if keyword.lower() in lowered:
                    matches.append(
                        {
                            "file": str(path.relative_to(ROOT_DIR)),
                            "line": line_number,
                            "keyword": keyword,
                            "excerpt": line.strip()[:240],
                        }
                    )
                    break
    return {
        "lookup_name": lookup_name,
        "source_found": bool(matches),
        "lookup_scope": [str(path.relative_to(ROOT_DIR)) for path in LOOKUP_SCHEMA_PATHS if path.exists()],
        "keywords": list(keywords),
        "matches": matches,
    }


def write_probe_outputs(source_summaries: Mapping[str, Mapping[str, Any]]) -> dict[str, Any]:
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    summary = build_probe_summary(output_dir=OUTPUT_DIR, source_summaries=source_summaries)
    _write_json(SUMMARY_PATH, summary)
    return summary


def run_vbro_profit_reconstruction_probe(probe_date: date = PROBE_DATE) -> dict[str, Any]:
    if not settings.wb_token:
        raise ValueError("WB_TOKEN is missing")
    if not settings.wb_analytics_token:
        raise ValueError("WB_ANALYTICS_TOKEN is missing")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    source_summaries: dict[str, dict[str, Any]] = {}

    detail_history_summary, _ = _fetch_detail_history_report(probe_date, TARGET_NM_IDS)
    source_summaries["detail_history_report"] = detail_history_summary

    source_summaries["nm_report_detail"] = _probe_nm_report_endpoint(
        endpoint="/api/v2/nm-report/detail",
        artifact_name="nm_report_detail_raw.json",
        probe_date=probe_date,
        nm_ids=TARGET_NM_IDS,
    )
    source_summaries["nm_report_detail_history"] = _probe_nm_report_endpoint(
        endpoint="/api/v2/nm-report/detail/history",
        artifact_name="nm_report_detail_history_raw.json",
        probe_date=probe_date,
        nm_ids=TARGET_NM_IDS,
    )

    source_summaries["adv_fullstats"] = _fetch_fullstats_raw(probe_date, TARGET_NM_IDS)

    orders_summary, _ = _fetch_statistics_source(
        source_name="orders",
        endpoint="/api/v1/supplier/orders",
        artifact_name="orders_raw.csv",
        probe_date=probe_date,
        nm_keys=("nmId", "nmID", "nm_id", "nmid"),
        date_keys=("date", "lastChangeDate"),
    )
    source_summaries["orders"] = orders_summary

    sales_summary, _ = _fetch_statistics_source(
        source_name="sales",
        endpoint="/api/v1/supplier/sales",
        artifact_name="sales_raw.csv",
        probe_date=probe_date,
        nm_keys=("nmId", "nmID", "nm_id", "nmid"),
        date_keys=("date", "lastChangeDate"),
    )
    source_summaries["sales"] = sales_summary

    report_detail_summary, report_detail_rows = _fetch_report_detail_by_period(probe_date)
    source_summaries["report_detail_by_period"] = report_detail_summary

    source_summaries["paid_storage"] = _fetch_optional_statistics_source(
        source_name="paid_storage",
        endpoint="/api/v1/paid_storage",
        raw_csv_name="paid_storage_raw.csv",
        error_json_name="paid_storage_error.json",
        probe_date=probe_date,
    )
    source_summaries["acceptance"] = _fetch_optional_statistics_source(
        source_name="acceptance",
        endpoint="/api/v1/acceptance_report",
        raw_csv_name="acceptance_raw.csv",
        error_json_name="acceptance_error.json",
        probe_date=probe_date,
    )

    deductions_rows = extract_deductions_rows(report_detail_rows, nm_ids=TARGET_NM_IDS, probe_date=probe_date)
    deductions_path = OUTPUT_DIR / "deductions_raw.csv"
    if deductions_rows:
        _write_records_csv(deductions_path, deductions_rows)
    else:
        _write_dataframe(deductions_path, pd.DataFrame(columns=pd.DataFrame(report_detail_rows).columns.tolist()))
    source_summaries["deductions"] = build_source_summary(
        source_name="deductions",
        endpoint="/api/v5/supplier/reportDetailByPeriod",
        saved_files=[deductions_path.name],
        http_status="200" if report_detail_rows else report_detail_summary.get("http_status", ""),
        rows_count=len(deductions_rows),
        fields_available=pd.DataFrame(deductions_rows).columns.tolist() if deductions_rows else pd.DataFrame(report_detail_rows).columns.tolist(),
        note="extracted from reportDetailByPeriod rows",
    )

    source_summaries["stocks_wb_warehouses"] = _fetch_stocks_raw(probe_date, TARGET_NM_IDS)

    cost_lookup = _build_lookup_payload(
        lookup_name="cost_price",
        keywords=("cost_price", "purchase_price", "avg_purchase_price", "себестоим", "закупоч"),
    )
    cost_lookup_path = OUTPUT_DIR / "cost_price_lookup.json"
    _write_json(cost_lookup_path, cost_lookup)
    source_summaries["cost_price_lookup"] = build_source_summary(
        source_name="cost_price_lookup",
        endpoint="project_lookup",
        saved_files=[cost_lookup_path.name],
        http_status="PROJECT_LOOKUP",
        rows_count=len(cost_lookup.get("matches", [])),
        fields_available=["file", "line", "keyword", "excerpt"] if cost_lookup.get("matches") else [],
        note="project schema lookup only",
    )

    tax_lookup = _build_lookup_payload(
        lookup_name="tax_rate",
        keywords=("tax_rate", "tax", "налог"),
    )
    tax_lookup_path = OUTPUT_DIR / "tax_lookup.json"
    _write_json(tax_lookup_path, tax_lookup)
    source_summaries["tax_lookup"] = build_source_summary(
        source_name="tax_lookup",
        endpoint="project_lookup",
        saved_files=[tax_lookup_path.name],
        http_status="PROJECT_LOOKUP",
        rows_count=len(tax_lookup.get("matches", [])),
        fields_available=["file", "line", "keyword", "excerpt"] if tax_lookup.get("matches") else [],
        note="project schema lookup only",
    )

    summary = write_probe_outputs(source_summaries)
    return {
        "output_dir": str(OUTPUT_DIR),
        "summary_path": str(SUMMARY_PATH),
        "summary": summary,
    }
