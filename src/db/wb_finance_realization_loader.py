from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import UTC, date, datetime, timedelta
from decimal import Decimal
from typing import Any, Callable, Mapping, Sequence

import pandas as pd
import requests
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.db.funnel_loader import _to_decimal_or_none
from src.db.models import FactFinanceRealizationLine
from src.db.session import session_scope, upsert_rows


WB_STATISTICS_BASE = "https://statistics-api.wildberries.ru"
WB_REPORT_DETAIL_ENDPOINT = f"{WB_STATISTICS_BASE}/api/v5/supplier/reportDetailByPeriod"
FACT_FINANCE_REALIZATION_LINE_CONFLICT_COLUMNS = ("rrd_id",)
DIRECT_LOGISTICS_FIELDS = ("delivery_rub", "rebill_logistic_cost")
AGGREGATE_COST_FIELDS = (
    "delivery_rub",
    "rebill_logistic_cost",
    "storage_fee",
    "acceptance",
    "deduction",
    "penalty",
    "additional_payment",
)


@dataclass
class FinanceRealizationPageResult:
    http_status: str
    payload: Any
    error: str
    request_params: dict[str, Any]
    limit_used: int | None = None


FinanceRealizationRequester = Callable[[dict[str, Any]], FinanceRealizationPageResult]


def _to_int_or_none(value: Any) -> int | None:
    if value in (None, ""):
        return None
    if isinstance(value, bool):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _to_text_or_none(value: Any) -> str | None:
    if value in (None, ""):
        return None
    text_value = str(value).strip()
    if not text_value:
        return None
    if text_value.lower() in {"nan", "none", "null"}:
        return None
    return text_value


def _to_datetime_or_none(value: Any) -> datetime | None:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value
    if isinstance(value, date):
        return datetime.combine(value, datetime.min.time())
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return None
        normalized = text_value.replace("Z", "+00:00")
        try:
            return datetime.fromisoformat(normalized)
        except ValueError:
            for candidate in (text_value.split("T", 1)[0], text_value.split(" ", 1)[0]):
                try:
                    return datetime.fromisoformat(candidate)
                except ValueError:
                    continue
    return None


def _to_date_or_none(value: Any) -> date | None:
    if value in (None, ""):
        return None
    if isinstance(value, date) and not isinstance(value, datetime):
        return value
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, str):
        text_value = value.strip()
        if not text_value:
            return None
        for candidate in (text_value, text_value.split("T", 1)[0], text_value.split(" ", 1)[0]):
            try:
                return date.fromisoformat(candidate)
            except ValueError:
                continue
    return None


def _safe_float(value: Decimal | None) -> float | None:
    if value is None:
        return None
    return float(value)


def _json_safe(value: Any) -> Any:
    if isinstance(value, dict):
        return {str(key): _json_safe(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_json_safe(item) for item in value]
    if isinstance(value, Decimal):
        return str(value)
    if isinstance(value, (date, datetime)):
        return value.isoformat()
    return value


def _build_source_row_hash(row: Mapping[str, Any]) -> str:
    payload = json.dumps(_json_safe(dict(row)), ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _derive_operation_date(row: Mapping[str, Any]) -> tuple[date | None, str]:
    for field_name in ("rr_dt", "sale_dt", "order_dt", "create_dt"):
        datetime_value = _to_datetime_or_none(row.get(field_name))
        if datetime_value is not None:
            return datetime_value.date(), field_name
    for field_name in ("date_from", "date_to"):
        date_value = _to_date_or_none(row.get(field_name))
        if date_value is not None:
            return date_value, field_name
    return None, "missing"


def _headers() -> dict[str, str]:
    if not settings.wb_token:
        raise RuntimeError("WB_TOKEN is missing")
    return {
        "Authorization": settings.wb_token,
        "Accept": "application/json",
        "Content-Type": "application/json",
    }


def _split_date_windows(start: date, end: date, window_days: int = 7) -> list[tuple[date, date]]:
    windows: list[tuple[date, date]] = []
    current = start
    while current <= end:
        window_end = min(current + timedelta(days=window_days - 1), end)
        windows.append((current, window_end))
        current = window_end + timedelta(days=1)
    return windows


def build_report_detail_params(
    *,
    date_from: date,
    date_to: date,
    limit: int,
    rrdid: int,
    period: str = "daily",
) -> dict[str, Any]:
    return {
        "dateFrom": date_from.isoformat(),
        "dateTo": date_to.isoformat(),
        "limit": int(limit),
        "rrdid": int(rrdid),
        "period": period,
    }


def _default_requester(timeout_seconds: int = 60) -> FinanceRealizationRequester:
    session = requests.Session()

    def _request(request_params: dict[str, Any]) -> FinanceRealizationPageResult:
        response = session.get(
            WB_REPORT_DETAIL_ENDPOINT,
            headers=_headers(),
            params=request_params,
            timeout=timeout_seconds,
        )
        try:
            payload = response.json()
            error = ""
        except ValueError:
            payload = {"raw_text": response.text[:2000]}
            error = response.text[:500]
        if response.status_code != 200 and not error:
            error = response.text[:500]
        return FinanceRealizationPageResult(
            http_status=str(response.status_code),
            payload=payload,
            error=error,
            request_params=request_params,
        )

    return _request


def fetch_report_detail_by_period_pages(
    *,
    start: date,
    end: date,
    requester: FinanceRealizationRequester | None = None,
    page_limit_options: Sequence[int] = (100000, 1000, 200),
    window_days: int = 7,
    max_pages_per_window: int = 500,
) -> tuple[list[dict[str, Any]], dict[str, Any]]:
    request_page = requester or _default_requester()
    all_rows: list[dict[str, Any]] = []
    page_logs: list[dict[str, Any]] = []
    request_attempts: list[dict[str, Any]] = []
    stop_reason = "completed"
    status = "200"
    error = ""

    for window_start, window_end in _split_date_windows(start, end, window_days=window_days):
        rrdid = 0
        seen_rrdid: set[int] = set()
        page_number = 0

        while True:
            page_number += 1
            limit_used: int | None = None
            result: FinanceRealizationPageResult | None = None

            for limit_value in page_limit_options:
                request_params = build_report_detail_params(
                    date_from=window_start,
                    date_to=window_end,
                    limit=limit_value,
                    rrdid=rrdid,
                )
                page_result = request_page(request_params)
                request_attempts.append(
                    {
                        "window_start": window_start.isoformat(),
                        "window_end": window_end.isoformat(),
                        "page_number": page_number,
                        "rrdid": rrdid,
                        "http_status": page_result.http_status,
                        "limit": limit_value,
                        "error": page_result.error,
                    }
                )
                result = page_result
                if page_result.http_status == "200":
                    limit_used = limit_value
                    break
                if page_result.http_status == "400":
                    continue
                break

            if result is None:
                stop_reason = "requester_returned_none"
                status = "REQUEST_ERROR"
                error = "requester returned no result"
                break

            rows = result.payload if isinstance(result.payload, list) else []
            page_logs.append(
                {
                    "window_start": window_start.isoformat(),
                    "window_end": window_end.isoformat(),
                    "page_number": page_number,
                    "rrdid": rrdid,
                    "limit_used": limit_used,
                    "http_status": result.http_status,
                    "rows_returned": len(rows),
                    "error": result.error,
                }
            )
            if result.http_status != "200":
                stop_reason = f"http_{result.http_status}"
                status = result.http_status
                error = result.error
                break
            if not rows:
                break

            all_rows.extend(dict(row) for row in rows if isinstance(row, dict))
            last_rrd_id = _to_int_or_none(rows[-1].get("rrd_id")) if rows else None
            if last_rrd_id is None:
                stop_reason = "last_rrd_id_missing"
                break
            if last_rrd_id in seen_rrdid:
                stop_reason = "repeated_rrd_id"
                break
            seen_rrdid.add(last_rrd_id)
            if len(rows) < int(limit_used or len(rows)):
                break
            if page_number >= max_pages_per_window:
                stop_reason = "max_pages_per_window_reached"
                break
            rrdid = last_rrd_id

        if status != "200":
            break
        if stop_reason not in {"completed", "repeated_rrd_id", "last_rrd_id_missing", "max_pages_per_window_reached"}:
            continue
        if stop_reason in {"repeated_rrd_id", "last_rrd_id_missing", "max_pages_per_window_reached"}:
            break

    duplicate_rrd_ids = len(all_rows) - len(
        {
            _to_int_or_none(row.get("rrd_id"))
            for row in all_rows
            if _to_int_or_none(row.get("rrd_id")) is not None
        }
    )
    return all_rows, {
        "status": status,
        "error": error,
        "stop_reason": stop_reason,
        "page_logs": page_logs,
        "request_attempts": request_attempts,
        "rows_raw": len(all_rows),
        "duplicate_rrd_ids": duplicate_rrd_ids,
        "windows_count": len(_split_date_windows(start, end, window_days=window_days)),
    }


def build_fact_finance_realization_line_db_row(
    row: Mapping[str, Any],
    *,
    loaded_at: datetime | None = None,
    source_status: str = "API_200",
    source_endpoint: str = "/api/v5/supplier/reportDetailByPeriod",
) -> dict[str, Any]:
    operation_date, operation_date_source = _derive_operation_date(row)
    quantity = _to_decimal_or_none(row.get("quantity"))
    delivery_rub = _to_decimal_or_none(row.get("delivery_rub"))
    rebill_logistic_cost = _to_decimal_or_none(row.get("rebill_logistic_cost"))
    storage_fee = _to_decimal_or_none(row.get("storage_fee"))
    acceptance = _to_decimal_or_none(row.get("acceptance"))
    source_row_hash = _build_source_row_hash(row)
    has_finance_components = any(
        value not in (None, Decimal("0"))
        for value in (delivery_rub, rebill_logistic_cost, storage_fee, acceptance)
    )
    data_status = "OK" if row.get("nm_id") not in (None, "") and has_finance_components else "PARTIAL"
    return {
        "rrd_id": _to_int_or_none(row.get("rrd_id")),
        "realizationreport_id": _to_int_or_none(row.get("realizationreport_id")),
        "operation_date": operation_date,
        "operation_date_source": operation_date_source,
        "report_period_from": _to_date_or_none(row.get("date_from")),
        "report_period_to": _to_date_or_none(row.get("date_to")),
        "create_dt": _to_datetime_or_none(row.get("create_dt")),
        "order_dt": _to_datetime_or_none(row.get("order_dt")),
        "sale_dt": _to_datetime_or_none(row.get("sale_dt")),
        "rr_dt": _to_datetime_or_none(row.get("rr_dt")),
        "nm_id": _to_int_or_none(row.get("nm_id")),
        "sa_name": _to_text_or_none(row.get("sa_name")),
        "barcode": _to_text_or_none(row.get("barcode")),
        "srid": _to_text_or_none(row.get("srid")),
        "doc_type_name": _to_text_or_none(row.get("doc_type_name")),
        "supplier_oper_name": _to_text_or_none(row.get("supplier_oper_name")),
        "quantity": quantity,
        "delivery_amount": _to_decimal_or_none(row.get("delivery_amount")),
        "return_amount": _to_decimal_or_none(row.get("return_amount")),
        "delivery_rub": delivery_rub,
        "storage_fee": storage_fee,
        "acceptance": acceptance,
        "rebill_logistic_cost": rebill_logistic_cost,
        "deduction": _to_decimal_or_none(row.get("deduction")),
        "penalty": _to_decimal_or_none(row.get("penalty")),
        "additional_payment": _to_decimal_or_none(row.get("additional_payment")),
        "ppvz_for_pay": _to_decimal_or_none(row.get("ppvz_for_pay")),
        "office_name": _to_text_or_none(row.get("office_name")),
        "ppvz_office_name": _to_text_or_none(row.get("ppvz_office_name")),
        "ppvz_office_id": _to_int_or_none(row.get("ppvz_office_id")),
        "fix_tariff_date_from": _to_datetime_or_none(row.get("fix_tariff_date_from")),
        "fix_tariff_date_to": _to_datetime_or_none(row.get("fix_tariff_date_to")),
        "delivery_method": _to_text_or_none(row.get("delivery_method")),
        "source_endpoint": source_endpoint,
        "source_row_hash": source_row_hash,
        "data_status": data_status,
        "source_status": source_status,
        "loaded_at": loaded_at or datetime.now(UTC),
    }


def prepare_fact_finance_realization_line_upsert_rows(
    rows: Sequence[Mapping[str, Any]],
    *,
    loaded_at: datetime | None = None,
    source_status: str = "API_200",
) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    prepared: dict[int, dict[str, Any]] = {}
    row_errors: list[dict[str, Any]] = []
    for index, row in enumerate(rows):
        mapped = build_fact_finance_realization_line_db_row(
            row,
            loaded_at=loaded_at,
            source_status=source_status,
        )
        if mapped["rrd_id"] is None:
            row_errors.append({"row_index": index, "reason": "missing_rrd_id"})
            continue
        if mapped["operation_date"] is None:
            row_errors.append({"row_index": index, "rrd_id": mapped["rrd_id"], "reason": "missing_operation_date"})
            continue
        prepared[int(mapped["rrd_id"])] = mapped
    return list(prepared.values()), row_errors


def _fetch_existing_hashes(session: Session, rrd_ids: Sequence[int], batch_size: int = 5000) -> dict[int, str]:
    existing: dict[int, str] = {}
    resolved_rrd_ids = [int(rrd_id) for rrd_id in rrd_ids]
    for index in range(0, len(resolved_rrd_ids), batch_size):
        batch = resolved_rrd_ids[index:index + batch_size]
        rows = session.execute(
            select(FactFinanceRealizationLine.rrd_id, FactFinanceRealizationLine.source_row_hash).where(
                FactFinanceRealizationLine.rrd_id.in_(batch)
            )
        ).all()
        for rrd_id, row_hash in rows:
            if rrd_id is not None and row_hash:
                existing[int(rrd_id)] = str(row_hash)
    return existing


def upsert_fact_finance_realization_lines(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    if not rows:
        return 0
    upsert_rows(
        session=session,
        model=FactFinanceRealizationLine,
        rows=list(rows),
        conflict_columns=FACT_FINANCE_REALIZATION_LINE_CONFLICT_COLUMNS,
        batch_size=500,
    )
    return len(rows)


def count_fact_finance_realization_lines(
    session: Session,
    start: date,
    end: date,
    nm_ids: Sequence[int] | None = None,
) -> int:
    stmt = (
        select(func.count())
        .select_from(FactFinanceRealizationLine)
        .where(
            FactFinanceRealizationLine.operation_date >= start,
            FactFinanceRealizationLine.operation_date <= end,
        )
    )
    if nm_ids:
        stmt = stmt.where(FactFinanceRealizationLine.nm_id.in_([int(nm_id) for nm_id in nm_ids]))
    return int(session.execute(stmt).scalar_one())


def sum_fact_finance_logistics(
    session: Session,
    start: date,
    end: date,
    nm_ids: Sequence[int] | None = None,
) -> Decimal | None:
    stmt = select(
        func.sum(
            func.coalesce(FactFinanceRealizationLine.delivery_rub, 0)
            + func.coalesce(FactFinanceRealizationLine.rebill_logistic_cost, 0)
        )
    ).where(
        FactFinanceRealizationLine.operation_date >= start,
        FactFinanceRealizationLine.operation_date <= end,
    )
    if nm_ids:
        stmt = stmt.where(FactFinanceRealizationLine.nm_id.in_([int(nm_id) for nm_id in nm_ids]))
    return session.execute(stmt).scalar_one()


def load_wb_finance_realization_to_db(
    start: date,
    end: date,
    *,
    write_db: bool = True,
    requester: FinanceRealizationRequester | None = None,
    page_limit_options: Sequence[int] = (100000, 1000, 200),
    window_days: int = 7,
) -> dict[str, Any]:
    loaded_at = datetime.now(UTC)
    raw_rows, fetch_meta = fetch_report_detail_by_period_pages(
        start=start,
        end=end,
        requester=requester,
        page_limit_options=page_limit_options,
        window_days=window_days,
    )
    prepared_rows, row_errors = prepare_fact_finance_realization_line_upsert_rows(
        raw_rows,
        loaded_at=loaded_at,
        source_status=f"API_{fetch_meta.get('status', '') or 'UNKNOWN'}",
    )

    inserted_rows = 0
    updated_rows = 0
    unchanged_rows = 0
    rows_in_db = 0
    total_logistics = None

    if write_db:
        with session_scope() as session:
            existing_hashes = _fetch_existing_hashes(session, [int(row["rrd_id"]) for row in prepared_rows])
            for row in prepared_rows:
                rrd_id = int(row["rrd_id"])
                existing_hash = existing_hashes.get(rrd_id)
                if existing_hash is None:
                    inserted_rows += 1
                elif existing_hash != row["source_row_hash"]:
                    updated_rows += 1
                else:
                    unchanged_rows += 1
            upsert_fact_finance_realization_lines(session, prepared_rows)
            rows_in_db = count_fact_finance_realization_lines(session, start, end)
            total_logistics = sum_fact_finance_logistics(session, start, end)

    duplicate_rrd_ids = len(prepared_rows) - len({int(row["rrd_id"]) for row in prepared_rows})
    return {
        "date_from": start.isoformat(),
        "date_to": end.isoformat(),
        "status": fetch_meta.get("status"),
        "error": fetch_meta.get("error", ""),
        "stop_reason": fetch_meta.get("stop_reason", ""),
        "rows_raw": len(raw_rows),
        "rows_prepared": len(prepared_rows),
        "rows_inserted": inserted_rows,
        "rows_updated": updated_rows,
        "rows_unchanged": unchanged_rows,
        "rows_in_db_for_period": rows_in_db,
        "row_errors_count": len(row_errors),
        "row_errors_sample": row_errors[:20],
        "duplicate_rrd_ids_in_payload": fetch_meta.get("duplicate_rrd_ids", 0),
        "duplicate_rrd_ids_after_prepare": duplicate_rrd_ids,
        "windows_count": fetch_meta.get("windows_count", 0),
        "pages_loaded": len(fetch_meta.get("page_logs", [])),
        "page_logs": fetch_meta.get("page_logs", []),
        "request_attempts": fetch_meta.get("request_attempts", []),
        "total_logistics_sum": _safe_float(total_logistics),
        "source_endpoint": "/api/v5/supplier/reportDetailByPeriod",
    }


def load_fact_finance_realization_frame(
    session: Session,
    start: date,
    end: date,
    *,
    nm_ids: Sequence[int] | None = None,
) -> pd.DataFrame:
    stmt = select(FactFinanceRealizationLine).where(
        FactFinanceRealizationLine.operation_date >= start,
        FactFinanceRealizationLine.operation_date <= end,
    )
    if nm_ids:
        stmt = stmt.where(FactFinanceRealizationLine.nm_id.in_([int(nm_id) for nm_id in nm_ids]))
    rows = session.execute(stmt).scalars().all()
    records = [
        {
            "operation_date": row.operation_date,
            "nm_id": row.nm_id,
            "sa_name": row.sa_name,
            "office_name": row.office_name,
            "quantity": row.quantity,
            "delivery_rub": row.delivery_rub,
            "rebill_logistic_cost": row.rebill_logistic_cost,
            "storage_fee": row.storage_fee,
            "acceptance": row.acceptance,
            "deduction": row.deduction,
            "penalty": row.penalty,
            "additional_payment": row.additional_payment,
        }
        for row in rows
    ]
    return pd.DataFrame.from_records(records)


def aggregate_finance_realization_frame(
    frame: pd.DataFrame,
    *,
    group_keys: Sequence[str],
    office_name_unconfirmed: bool = False,
) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(
            columns=[
                *group_keys,
                "quantity_total",
                "delivery_rub_total",
                "rebill_logistic_cost_total",
                "logistics_total",
                "storage_fee_total",
                "acceptance_total",
                "deduction_total",
                "penalty_total",
                "additional_payment_total",
                "logistics_per_unit",
                "previous_day_logistics_total",
                "day_over_day_logistics_delta",
                "office_name_unconfirmed",
            ]
        )

    working = frame.copy()
    for column in ("quantity", *AGGREGATE_COST_FIELDS):
        working[column] = pd.to_numeric(working.get(column), errors="coerce")
    grouped = (
        working.groupby(list(group_keys), dropna=False, as_index=False)
        .agg(
            quantity_total=("quantity", "sum"),
            delivery_rub_total=("delivery_rub", "sum"),
            rebill_logistic_cost_total=("rebill_logistic_cost", "sum"),
            storage_fee_total=("storage_fee", "sum"),
            acceptance_total=("acceptance", "sum"),
            deduction_total=("deduction", "sum"),
            penalty_total=("penalty", "sum"),
            additional_payment_total=("additional_payment", "sum"),
        )
    )
    grouped["logistics_total"] = grouped["delivery_rub_total"].fillna(0) + grouped["rebill_logistic_cost_total"].fillna(0)
    grouped["logistics_per_unit"] = grouped["logistics_total"] / grouped["quantity_total"].where(grouped["quantity_total"].ne(0))
    grouped["office_name_unconfirmed"] = bool(office_name_unconfirmed)

    partition_keys = [key for key in group_keys if key != "operation_date"]
    if "operation_date" in group_keys:
        grouped = grouped.sort_values([*partition_keys, "operation_date"]).reset_index(drop=True)
        if partition_keys:
            grouped["previous_day_logistics_total"] = grouped.groupby(partition_keys, dropna=False)["logistics_total"].shift(1)
        else:
            grouped["previous_day_logistics_total"] = grouped["logistics_total"].shift(1)
        grouped["day_over_day_logistics_delta"] = grouped["logistics_total"] - grouped["previous_day_logistics_total"]
    else:
        grouped["previous_day_logistics_total"] = pd.NA
        grouped["day_over_day_logistics_delta"] = pd.NA
    return grouped


def build_finance_realization_article_daily_aggregate(frame: pd.DataFrame) -> pd.DataFrame:
    return aggregate_finance_realization_frame(frame, group_keys=("operation_date", "nm_id", "sa_name"))


def build_finance_realization_office_daily_aggregate(frame: pd.DataFrame) -> pd.DataFrame:
    aggregated = aggregate_finance_realization_frame(
        frame,
        group_keys=("operation_date", "office_name"),
        office_name_unconfirmed=True,
    )
    aggregated["attribute_note"] = "office_name is an unconfirmed financial report attribute, not a confirmed WB warehouse"
    return aggregated


def build_last_7_vs_previous_7(frame: pd.DataFrame, *, group_keys: Sequence[str], end_date: date | None = None) -> pd.DataFrame:
    if frame.empty:
        return pd.DataFrame(columns=[*group_keys, "last_7_logistics_total", "prev_7_logistics_total", "delta"])
    working = frame.copy()
    working["operation_date"] = pd.to_datetime(working["operation_date"], errors="coerce").dt.date
    resolved_end_date = end_date or max(item for item in working["operation_date"].dropna().tolist())
    last_7_start = resolved_end_date - timedelta(days=6)
    prev_7_end = last_7_start - timedelta(days=1)
    prev_7_start = prev_7_end - timedelta(days=6)

    aggregated = aggregate_finance_realization_frame(working, group_keys=("operation_date", *group_keys))
    last_7 = aggregated.loc[
        aggregated["operation_date"].between(last_7_start, resolved_end_date),
        [*group_keys, "logistics_total"],
    ]
    prev_7 = aggregated.loc[
        aggregated["operation_date"].between(prev_7_start, prev_7_end),
        [*group_keys, "logistics_total"],
    ]
    last_7_grouped = last_7.groupby(list(group_keys), dropna=False, as_index=False)["logistics_total"].sum()
    prev_7_grouped = prev_7.groupby(list(group_keys), dropna=False, as_index=False)["logistics_total"].sum()
    merged = last_7_grouped.merge(
        prev_7_grouped,
        on=list(group_keys),
        how="outer",
        suffixes=("_last_7", "_prev_7"),
    ).fillna(0)
    merged["delta"] = merged["logistics_total_last_7"] - merged["logistics_total_prev_7"]
    return merged.rename(
        columns={
            "logistics_total_last_7": "last_7_logistics_total",
            "logistics_total_prev_7": "prev_7_logistics_total",
        }
    )
