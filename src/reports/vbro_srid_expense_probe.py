from __future__ import annotations

import json
import shutil
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

import pandas as pd
import requests

from src.config.settings import settings


ROOT_DIR = Path(__file__).resolve().parents[2]
RAW_PROBE_DIR = ROOT_DIR / "data" / "processed" / "vbro_raw_probe_2026-05-23"
OUTPUT_DIR = ROOT_DIR / "data" / "processed" / "vbro_srid_expense_probe_2026-05-23"
SUMMARY_PATH = OUTPUT_DIR / "summary.json"
PROBE_DATE = date(2026, 5, 23)
REPORT_END_DATE = date(2026, 6, 10)
WB_STATISTICS_BASE = "https://statistics-api.wildberries.ru"
TARGET_PRODUCTS: tuple[dict[str, Any], ...] = (
    {"nm_id": 197330807, "supplier_article": "BlackWOM5"},
    {"nm_id": 37320545, "supplier_article": "Brand_Wom7Сlassic7"},
)
TARGET_NM_IDS = tuple(sorted(int(item["nm_id"]) for item in TARGET_PRODUCTS))
EXPENSE_FIELDS = (
    "delivery_rub",
    "storage_fee",
    "deduction",
    "acceptance",
    "penalty",
    "additional_payment",
    "rebill_logistic_cost",
)
REPORT_DETAIL_OPERATION_SUM_FIELDS = (
    "quantity",
    "retail_amount",
    "retail_price_withdisc_rub",
    "ppvz_for_pay",
    "ppvz_reward",
    "ppvz_sales_commission",
    "acquiring_fee",
    "ppvz_vw",
    "ppvz_vw_nds",
    "delivery_amount",
    "return_amount",
    "delivery_rub",
    "storage_fee",
    "deduction",
    "acceptance",
    "penalty",
    "additional_payment",
    "rebill_logistic_cost",
)
REPORT_DETAIL_NM_SUM_FIELDS = (
    "retail_amount",
    "retail_price_withdisc_rub",
    "ppvz_for_pay",
    "delivery_rub",
    "storage_fee",
    "deduction",
    "acceptance",
    "penalty",
    "additional_payment",
    "rebill_logistic_cost",
)
AGGREGATE_FILE_NAMES = {
    "agg_sales_by_nm": "agg_sales_by_nm.csv",
    "agg_report_detail_matched_by_operation": "agg_report_detail_matched_by_operation.csv",
    "agg_report_detail_matched_by_nm": "agg_report_detail_matched_by_nm.csv",
    "agg_adv_fullstats_by_nm": "agg_adv_fullstats_by_nm.csv",
    "agg_report_detail_by_rr_dt": "agg_report_detail_by_rr_dt.csv",
    "agg_summary": "agg_summary.json",
}


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


def _normalize_srid(value: Any) -> str:
    if value in (None, "", [], {}):
        return ""
    text = str(value).strip()
    if text.lower() in {"nan", "none", "null"}:
        return ""
    return text


def _truncate_error(value: Any, limit: int = 240) -> str:
    if not value:
        return ""
    return " ".join(str(value).split())[:limit]


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


def _numeric_series(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([pd.NA] * len(frame), index=frame.index, dtype="Float64")
    return pd.to_numeric(frame[column], errors="coerce")


def _ensure_date_string(frame: pd.DataFrame, column: str) -> pd.Series:
    if column not in frame.columns:
        return pd.Series([""] * len(frame), index=frame.index, dtype="string")
    values = pd.to_datetime(frame[column], errors="coerce")
    formatted = values.dt.strftime("%Y-%m-%d").astype("string")
    return formatted.fillna("")


def _distinct_text_values(series: pd.Series) -> list[str]:
    values: set[str] = set()
    for value in series.tolist():
        if pd.isna(value):
            continue
        text = str(value).strip()
        if not text or text.lower() in {"nan", "none", "null"}:
            continue
        values.add(text)
    return sorted(values)


def _statistics_headers() -> dict[str, str]:
    return {
        "Authorization": settings.wb_token or "",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _request_json(
    session: requests.Session,
    method: str,
    url: str,
    *,
    headers: Mapping[str, str],
    params: Mapping[str, Any] | None = None,
    timeout_seconds: int = 60,
) -> tuple[str, Any, str]:
    try:
        response = session.request(
            method=method,
            url=url,
            headers=dict(headers),
            params=params,
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


def prepare_sales_base(sales_raw_path: Path, target_nm_ids: Sequence[int]) -> pd.DataFrame:
    frame = pd.read_csv(sales_raw_path)
    frame["nmId"] = frame["nmId"].map(_to_int)
    frame["saleID"] = frame["saleID"].astype(str)
    frame["srid"] = frame["srid"].map(_normalize_srid)
    filtered = frame.loc[
        frame["nmId"].isin([int(item) for item in target_nm_ids]) & frame["saleID"].str.startswith("S", na=False)
    ].copy()
    return filtered.sort_values(["nmId", "saleID", "srid"]).reset_index(drop=True)


def build_sales_srid_index(sales_base: pd.DataFrame) -> dict[str, dict[str, Any]]:
    result: dict[str, dict[str, Any]] = {}
    for nm_id, group in sales_base.groupby("nmId", dropna=False):
        srids = sorted({value for value in group["srid"].tolist() if value})
        supplier_article = next(
            (str(value) for value in group.get("supplierArticle", pd.Series(dtype=str)).tolist() if str(value).strip()),
            "",
        )
        result[str(int(nm_id))] = {
            "nm_id": int(nm_id),
            "supplier_article": supplier_article,
            "sales_rows_count": int(len(group)),
            "unique_srid_count": int(len(srids)),
            "srids": srids,
        }
    return result


def split_report_detail_rows(
    report_detail_extended: pd.DataFrame,
    sales_base: pd.DataFrame,
    target_nm_ids: Sequence[int],
) -> tuple[pd.DataFrame, pd.DataFrame]:
    report = report_detail_extended.copy()
    report["nm_id"] = report["nm_id"].map(_to_int)
    report["srid"] = report["srid"].map(_normalize_srid)
    sales_srids = {value for value in sales_base["srid"].tolist() if value}
    target_set = {int(item) for item in target_nm_ids}
    matched_by_srid = report.loc[report["srid"].isin(sales_srids)].copy()
    unmatched_by_nm = report.loc[
        report["nm_id"].isin(target_set) & ~report["srid"].isin(sales_srids)
    ].copy()
    sort_columns = [column for column in ("nm_id", "srid", "rr_dt") if column in report.columns]
    return (
        matched_by_srid.sort_values(sort_columns, na_position="last").reset_index(drop=True),
        unmatched_by_nm.sort_values(sort_columns, na_position="last").reset_index(drop=True),
    )


def build_summary(
    *,
    sales_base: pd.DataFrame,
    report_detail_extended: pd.DataFrame,
    matched_by_srid: pd.DataFrame,
    unmatched_by_nm: pd.DataFrame,
    sales_srid_index: Mapping[str, Mapping[str, Any]],
    adv_fullstats_path: Path,
) -> dict[str, Any]:
    sales_srids = {value for value in sales_base["srid"].tolist() if value}
    matched_srids = {value for value in matched_by_srid["srid"].tolist() if value}
    missing_srids = sorted(sales_srids - matched_srids)
    combined = pd.concat([matched_by_srid, unmatched_by_nm], ignore_index=True) if not matched_by_srid.empty or not unmatched_by_nm.empty else pd.DataFrame()

    supplier_oper_names = _distinct_text_values(combined.get("supplier_oper_name", pd.Series(dtype=str)))
    doc_type_names = _distinct_text_values(combined.get("doc_type_name", pd.Series(dtype=str)))

    nonzero_expense_fields: list[str] = []
    for field in EXPENSE_FIELDS:
        if field in combined.columns:
            values = pd.to_numeric(combined[field], errors="coerce")
            if values.fillna(0).ne(0).any():
                nonzero_expense_fields.append(field)

    return {
        "probe_date": PROBE_DATE.isoformat(),
        "report_period_start": PROBE_DATE.isoformat(),
        "report_period_end": REPORT_END_DATE.isoformat(),
        "targets": [dict(item) for item in TARGET_PRODUCTS],
        "sales_base_rows_count": int(len(sales_base)),
        "sales_base_counts_by_nm_id": {key: int(value["sales_rows_count"]) for key, value in sales_srid_index.items()},
        "unique_srid_count": int(len(sales_srids)),
        "report_detail_extended_rows_count": int(len(report_detail_extended)),
        "matched_report_detail_rows_count": int(len(matched_by_srid)),
        "unmatched_by_nm_rows_count": int(len(unmatched_by_nm)),
        "matched_sales_srid_count": int(len(matched_srids)),
        "missing_sales_srid_count": int(len(missing_srids)),
        "missing_sales_srids_sample": missing_srids[:20],
        "supplier_oper_name_values": supplier_oper_names,
        "doc_type_name_values": doc_type_names,
        "expense_fields_checked": list(EXPENSE_FIELDS),
        "nonzero_expense_fields": nonzero_expense_fields,
        "adv_fullstats_copied_from": str(adv_fullstats_path),
    }


def aggregate_sales_by_nm(sales_base: pd.DataFrame) -> pd.DataFrame:
    working = sales_base.copy()
    working["srid"] = working.get("srid", pd.Series(dtype=object)).map(_normalize_srid)
    for column in ("forPay", "finishedPrice", "priceWithDisc", "totalPrice"):
        working[column] = _numeric_series(working, column)

    grouped = (
        working.groupby(["nmId", "supplierArticle"], dropna=False)
        .agg(
            sales_rows_count=("saleID", "size"),
            unique_srid_count=("srid", lambda values: len({item for item in values if item})),
            sum_forPay=("forPay", "sum"),
            sum_finishedPrice=("finishedPrice", "sum"),
            sum_priceWithDisc=("priceWithDisc", "sum"),
            sum_totalPrice=("totalPrice", "sum"),
            avg_forPay=("forPay", "mean"),
            avg_finishedPrice=("finishedPrice", "mean"),
            avg_priceWithDisc=("priceWithDisc", "mean"),
            min_forPay=("forPay", "min"),
            max_forPay=("forPay", "max"),
            min_finishedPrice=("finishedPrice", "min"),
            max_finishedPrice=("finishedPrice", "max"),
        )
        .reset_index()
        .sort_values(["nmId", "supplierArticle"], na_position="last")
        .reset_index(drop=True)
    )
    return grouped


def aggregate_report_detail_matched_by_operation(matched_by_srid: pd.DataFrame) -> pd.DataFrame:
    working = matched_by_srid.copy()
    working["srid"] = working.get("srid", pd.Series(dtype=object)).map(_normalize_srid)
    for column in REPORT_DETAIL_OPERATION_SUM_FIELDS:
        working[column] = _numeric_series(working, column)

    aggregations: dict[str, tuple[str, Any]] = {
        "rows_count": ("srid", "size"),
        "unique_srid_count": ("srid", lambda values: len({item for item in values if item})),
    }
    aggregations.update({f"{column}_sum": (column, "sum") for column in REPORT_DETAIL_OPERATION_SUM_FIELDS})

    grouped = (
        working.groupby(["nm_id", "sa_name", "supplier_oper_name", "doc_type_name"], dropna=False)
        .agg(**aggregations)
        .reset_index()
        .sort_values(["nm_id", "sa_name", "supplier_oper_name", "doc_type_name"], na_position="last")
        .reset_index(drop=True)
    )
    return grouped


def aggregate_report_detail_matched_by_nm(matched_by_srid: pd.DataFrame) -> pd.DataFrame:
    working = matched_by_srid.copy()
    working["srid"] = working.get("srid", pd.Series(dtype=object)).map(_normalize_srid)
    quantity = _numeric_series(working, "quantity")
    supplier_oper_name = working.get("supplier_oper_name", pd.Series("", index=working.index)).astype("string")
    doc_type_name = working.get("doc_type_name", pd.Series("", index=working.index)).astype("string")
    sale_mask = supplier_oper_name.eq("Продажа") | doc_type_name.eq("Продажа")
    return_mask = supplier_oper_name.eq("Возврат") | doc_type_name.eq("Возврат")
    working["sale_quantity_component"] = quantity.where(sale_mask)
    working["return_quantity_component"] = quantity.where(return_mask)
    for column in REPORT_DETAIL_NM_SUM_FIELDS:
        working[column] = _numeric_series(working, column)

    aggregations: dict[str, tuple[str, Any]] = {
        "rows_count": ("srid", "size"),
        "unique_srid_count": ("srid", lambda values: len({item for item in values if item})),
        "sale_quantity_sum": ("sale_quantity_component", "sum"),
        "return_quantity_sum": ("return_quantity_component", "sum"),
    }
    aggregations.update({f"{column}_sum": (column, "sum") for column in REPORT_DETAIL_NM_SUM_FIELDS})

    grouped = (
        working.groupby(["nm_id", "sa_name"], dropna=False)
        .agg(**aggregations)
        .reset_index()
        .sort_values(["nm_id", "sa_name"], na_position="last")
        .reset_index(drop=True)
    )
    return grouped


def aggregate_report_detail_by_rr_dt(matched_by_srid: pd.DataFrame) -> pd.DataFrame:
    working = matched_by_srid.copy()
    working["srid"] = working.get("srid", pd.Series(dtype=object)).map(_normalize_srid)
    working["rr_dt"] = _ensure_date_string(working, "rr_dt")
    fields = (
        "quantity",
        "ppvz_for_pay",
        "delivery_rub",
        "penalty",
        "rebill_logistic_cost",
        "storage_fee",
        "deduction",
        "acceptance",
        "additional_payment",
    )
    for column in fields:
        working[column] = _numeric_series(working, column)

    aggregations: dict[str, tuple[str, Any]] = {
        "rows_count": ("srid", "size"),
        "unique_srid_count": ("srid", lambda values: len({item for item in values if item})),
    }
    aggregations.update({f"{column}_sum": (column, "sum") for column in fields})

    grouped = (
        working.groupby(["nm_id", "rr_dt", "supplier_oper_name", "doc_type_name"], dropna=False)
        .agg(**aggregations)
        .reset_index()
        .sort_values(["nm_id", "rr_dt", "supplier_oper_name", "doc_type_name"], na_position="last")
        .reset_index(drop=True)
    )
    return grouped


def _flatten_adv_fullstats_rows(raw_payload: Mapping[str, Any]) -> pd.DataFrame:
    rows: list[dict[str, Any]] = []
    for request in raw_payload.get("requests", []):
        advert_ids = request.get("advert_ids", [])
        payload = request.get("payload", [])
        if not isinstance(payload, list):
            continue
        for campaign in payload:
            if not isinstance(campaign, dict):
                continue
            advert_id = _to_int(campaign.get("advertId"))
            for day in campaign.get("days", []) or []:
                if not isinstance(day, dict):
                    continue
                day_value = _to_date(day.get("date"))
                for app in day.get("apps", []) or []:
                    if not isinstance(app, dict):
                        continue
                    for nm_row in app.get("nms", []) or []:
                        if not isinstance(nm_row, dict):
                            continue
                        row = {
                            "nmId": _to_int(nm_row.get("nmId")),
                            "advertId": advert_id,
                            "date": day_value.isoformat() if day_value else "",
                            "views": nm_row.get("views"),
                            "clicks": nm_row.get("clicks"),
                            "atbs": nm_row.get("atbs"),
                            "orders": nm_row.get("orders"),
                            "shks": nm_row.get("shks"),
                            "sum": nm_row.get("sum"),
                            "sum_price": nm_row.get("sum_price"),
                        }
                        if advert_id is None and isinstance(advert_ids, list) and len(advert_ids) == 1:
                            row["advertId"] = _to_int(advert_ids[0])
                        rows.append(row)
    return pd.DataFrame(rows)


def aggregate_adv_fullstats_by_nm(
    raw_payload: Mapping[str, Any],
    target_nm_ids: Sequence[int] | None = TARGET_NM_IDS,
) -> pd.DataFrame:
    working = _flatten_adv_fullstats_rows(raw_payload)
    if target_nm_ids is not None and not working.empty:
        target_set = {int(item) for item in target_nm_ids}
        working = working.loc[working["nmId"].isin(target_set)].copy()
    if working.empty:
        columns = [
            "nmId",
            "rows_count",
            "sum_views",
            "sum_clicks",
            "sum_atbs",
            "sum_orders",
            "sum_shks",
            "sum_sum",
            "sum_sum_price",
            "unique_campaign_count",
        ]
        return pd.DataFrame(columns=columns)

    working["advertId"] = working.get("advertId", pd.Series(dtype=object)).map(_to_int)
    for column in ("views", "clicks", "atbs", "orders", "shks", "sum", "sum_price"):
        working[column] = _numeric_series(working, column)

    grouped = (
        working.groupby(["nmId"], dropna=False)
        .agg(
            rows_count=("nmId", "size"),
            sum_views=("views", "sum"),
            sum_clicks=("clicks", "sum"),
            sum_atbs=("atbs", "sum"),
            sum_orders=("orders", "sum"),
            sum_shks=("shks", "sum"),
            sum_sum=("sum", "sum"),
            sum_sum_price=("sum_price", "sum"),
            unique_campaign_count=("advertId", lambda values: len({item for item in values if item is not None})),
        )
        .reset_index()
        .sort_values(["nmId"], na_position="last")
        .reset_index(drop=True)
    )
    return grouped


def build_aggregate_summary(
    *,
    source_files: Sequence[str],
    aggregate_frames: Mapping[str, pd.DataFrame],
    matched_by_srid: pd.DataFrame,
) -> dict[str, Any]:
    combined = matched_by_srid.copy()
    supplier_oper_names = _distinct_text_values(combined.get("supplier_oper_name", pd.Series(dtype=str)))
    doc_type_names = _distinct_text_values(combined.get("doc_type_name", pd.Series(dtype=str)))
    nonzero_expense_fields: list[str] = []
    for field in EXPENSE_FIELDS:
        if field in combined.columns:
            values = pd.to_numeric(combined[field], errors="coerce")
            if values.fillna(0).ne(0).any():
                nonzero_expense_fields.append(field)

    return {
        "aggregate_files_created": {
            key: AGGREGATE_FILE_NAMES[key]
            for key in (
                "agg_sales_by_nm",
                "agg_report_detail_matched_by_operation",
                "agg_report_detail_matched_by_nm",
                "agg_adv_fullstats_by_nm",
                "agg_report_detail_by_rr_dt",
                "agg_summary",
            )
        },
        "aggregate_row_counts": {key: int(len(frame)) for key, frame in aggregate_frames.items()},
        "source_files_used": list(source_files),
        "nonzero_financial_fields": nonzero_expense_fields,
        "supplier_oper_name_values": supplier_oper_names,
        "doc_type_name_values": doc_type_names,
    }


def _split_date_windows(start: date, end: date, window_days: int = 7) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    current = start
    while current <= end:
        window_end = min(current + timedelta(days=window_days - 1), end)
        windows.append((current, window_end))
        current = window_end + timedelta(days=1)
    return windows


def _fetch_report_detail_extended(start: date, end: date) -> tuple[pd.DataFrame, dict[str, Any]]:
    session = requests.Session()
    all_rows: list[dict[str, Any]] = []
    window_logs: list[dict[str, Any]] = []
    page_limit_options = (100000, 1000, 200)

    for window_start, window_end in _split_date_windows(start, end, window_days=7):
        rrdid = 0
        seen_rrdid: set[int] = set()
        page_number = 0
        limit_used = None
        while True:
            page_number += 1
            page_payload = None
            page_status = ""
            page_error = ""
            for limit in page_limit_options:
                status, payload, error = _request_json(
                    session,
                    "GET",
                    f"{WB_STATISTICS_BASE}/api/v5/supplier/reportDetailByPeriod",
                    headers=_statistics_headers(),
                    params={
                        "dateFrom": window_start.isoformat(),
                        "dateTo": window_end.isoformat(),
                        "limit": limit,
                        "rrdid": rrdid,
                        "period": "daily",
                    },
                )
                page_status = status
                page_payload = payload
                page_error = error
                if status == "200":
                    limit_used = limit
                    break
                if status == "400":
                    continue
                break

            rows = page_payload if isinstance(page_payload, list) else []
            window_logs.append(
                {
                    "window_start": window_start.isoformat(),
                    "window_end": window_end.isoformat(),
                    "page_number": page_number,
                    "rrdid": rrdid,
                    "limit_used": limit_used,
                    "http_status": page_status,
                    "rows_returned": len(rows),
                    "error": page_error,
                }
            )
            if page_status != "200":
                break
            if not rows:
                break

            all_rows.extend(dict(row) for row in rows if isinstance(row, dict))
            last_rrd_id = _to_int(rows[-1].get("rrd_id")) if rows and isinstance(rows[-1], dict) else None
            if last_rrd_id is None or last_rrd_id in seen_rrdid:
                break
            seen_rrdid.add(last_rrd_id)
            if len(rows) < (limit_used or len(rows)):
                break
            rrdid = last_rrd_id

    frame = pd.DataFrame(all_rows)
    return frame, {"windows": window_logs}


def _copy_adv_fullstats_raw(source_dir: Path, output_dir: Path) -> Path:
    source_path = source_dir / "adv_fullstats_raw.json"
    target_path = output_dir / "adv_fullstats_raw.json"
    if not source_path.exists():
        raise FileNotFoundError(f"Source adv_fullstats_raw.json not found: {source_path}")
    target_path.parent.mkdir(parents=True, exist_ok=True)
    shutil.copyfile(source_path, target_path)
    return target_path


def run_vbro_srid_expense_aggregates(output_dir: Path = OUTPUT_DIR) -> dict[str, Any]:
    sales_base_path = output_dir / "sales_base_2026-05-23.csv"
    matched_path = output_dir / "report_detail_matched_by_srid.csv"
    adv_fullstats_path = output_dir / "adv_fullstats_raw.json"

    if not sales_base_path.exists():
        raise FileNotFoundError(f"sales base file not found: {sales_base_path}")
    if not matched_path.exists():
        raise FileNotFoundError(f"matched report detail file not found: {matched_path}")
    if not adv_fullstats_path.exists():
        raise FileNotFoundError(f"adv fullstats file not found: {adv_fullstats_path}")

    sales_base = pd.read_csv(sales_base_path)
    matched_by_srid = pd.read_csv(matched_path)
    adv_payload = json.loads(adv_fullstats_path.read_text(encoding="utf-8"))

    aggregate_frames = {
        "agg_sales_by_nm": aggregate_sales_by_nm(sales_base),
        "agg_report_detail_matched_by_operation": aggregate_report_detail_matched_by_operation(matched_by_srid),
        "agg_report_detail_matched_by_nm": aggregate_report_detail_matched_by_nm(matched_by_srid),
        "agg_adv_fullstats_by_nm": aggregate_adv_fullstats_by_nm(adv_payload),
        "agg_report_detail_by_rr_dt": aggregate_report_detail_by_rr_dt(matched_by_srid),
    }

    saved_files: dict[str, str] = {}
    for key, frame in aggregate_frames.items():
        file_name = AGGREGATE_FILE_NAMES[key]
        _write_dataframe(output_dir / file_name, frame)
        saved_files[key] = file_name

    summary = build_aggregate_summary(
        source_files=[
            sales_base_path.name,
            matched_path.name,
            "report_detail_unmatched_by_nm.csv",
            adv_fullstats_path.name,
            "summary.json",
        ],
        aggregate_frames=aggregate_frames,
        matched_by_srid=matched_by_srid,
    )
    summary["saved_files"] = [*saved_files.values(), AGGREGATE_FILE_NAMES["agg_summary"]]
    summary_path = output_dir / AGGREGATE_FILE_NAMES["agg_summary"]
    _write_json(summary_path, summary)
    return {
        "output_dir": str(output_dir),
        "summary_path": str(summary_path),
        "summary": summary,
    }


def run_vbro_srid_expense_probe() -> dict[str, Any]:
    if not settings.wb_token:
        raise ValueError("WB_TOKEN is missing")

    sales_raw_path = RAW_PROBE_DIR / "sales_raw.csv"
    if not sales_raw_path.exists():
        raise FileNotFoundError(f"sales_raw.csv not found: {sales_raw_path}")

    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)

    sales_base = prepare_sales_base(sales_raw_path, TARGET_NM_IDS)
    sales_base_path = OUTPUT_DIR / "sales_base_2026-05-23.csv"
    _write_dataframe(sales_base_path, sales_base)

    sales_srid_index = build_sales_srid_index(sales_base)
    sales_srid_path = OUTPUT_DIR / "sales_srid_list.json"
    _write_json(sales_srid_path, sales_srid_index)

    report_detail_extended, fetch_meta = _fetch_report_detail_extended(PROBE_DATE, REPORT_END_DATE)
    report_detail_extended["nm_id"] = report_detail_extended.get("nm_id", pd.Series(dtype=object)).map(_to_int)
    report_detail_extended["srid"] = report_detail_extended.get("srid", pd.Series(dtype=object)).map(_normalize_srid)
    report_detail_path = OUTPUT_DIR / "report_detail_by_period_extended_raw.csv"
    _write_dataframe(report_detail_path, report_detail_extended)

    matched_by_srid, unmatched_by_nm = split_report_detail_rows(report_detail_extended, sales_base, TARGET_NM_IDS)
    matched_path = OUTPUT_DIR / "report_detail_matched_by_srid.csv"
    unmatched_path = OUTPUT_DIR / "report_detail_unmatched_by_nm.csv"
    _write_dataframe(matched_path, matched_by_srid)
    _write_dataframe(unmatched_path, unmatched_by_nm)

    adv_fullstats_path = _copy_adv_fullstats_raw(RAW_PROBE_DIR, OUTPUT_DIR)

    summary = build_summary(
        sales_base=sales_base,
        report_detail_extended=report_detail_extended,
        matched_by_srid=matched_by_srid,
        unmatched_by_nm=unmatched_by_nm,
        sales_srid_index=sales_srid_index,
        adv_fullstats_path=adv_fullstats_path,
    )
    summary["report_detail_fetch_meta"] = fetch_meta
    summary["saved_files"] = [
        sales_base_path.name,
        sales_srid_path.name,
        report_detail_path.name,
        matched_path.name,
        unmatched_path.name,
        adv_fullstats_path.name,
        SUMMARY_PATH.name,
    ]
    _write_json(SUMMARY_PATH, summary)
    return {
        "output_dir": str(OUTPUT_DIR),
        "summary_path": str(SUMMARY_PATH),
        "summary": summary,
    }
