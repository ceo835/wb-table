from __future__ import annotations

import csv
from collections import Counter
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any, Iterable, Mapping, Sequence

from sqlalchemy import select

from src.db.models import FactAdCampaignNmDay, FactAdCostEvent, MartTotalReport
from src.db.session import session_scope


AD_CAMPAIGN_PRODUCT_COLUMNS = [
    "report_date",
    "supplier_article",
    "nm_id",
    "title",
    "brand",
    "subject",
    "advert_id",
    "campaign_name",
    "campaign_type",
    "conversion_type",
    "campaign_spend",
    "ad_views",
    "ad_clicks",
    "ad_atbs",
    "ad_orders",
    "ad_cpc_calc",
    "ad_cpm_calc",
    "ad_cost_per_cart_calc",
    "ad_cpo_calc",
    "order_sum",
    "ad_share_of_order_sum_calc",
]

ROOT_DIR = Path(__file__).resolve().parent.parent
PROCESSED_DIR = ROOT_DIR / "data" / "processed"
AD_CAMPAIGN_PRODUCT_DATASET_PATH = PROCESSED_DIR / "streamlit_ad_campaign_product_dataset.csv"


def _safe_divide(
    numerator: Decimal | None,
    denominator: Decimal | None,
    multiplier: Decimal | None = None,
) -> Decimal | None:
    if numerator is None or denominator in (None, Decimal("0")):
        return None
    result = numerator / denominator
    if multiplier is not None:
        result *= multiplier
    return result


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _normalize_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def _build_mart_index(mart_rows: Sequence[Mapping[str, Any]]) -> dict[tuple[date, int], dict[str, Any]]:
    index: dict[tuple[date, int], dict[str, Any]] = {}
    for row in mart_rows:
        report_date = row.get("report_date")
        nm_id = row.get("nm_id")
        if report_date is None or nm_id in (None, ""):
            continue
        index[(report_date, int(nm_id))] = dict(row)
    return index


def _resolve_single_value(values: Iterable[str | None]) -> str | None:
    cleaned = [value for value in values if value not in (None, "")]
    if not cleaned:
        return None
    counts = Counter(cleaned)
    return counts.most_common(1)[0][0]


def _build_campaign_type_lookup(ad_cost_event_rows: Sequence[Mapping[str, Any]]) -> tuple[dict[tuple[date, int, int], str], dict[tuple[date, int], str]]:
    by_nm: dict[tuple[date, int, int], list[str | None]] = {}
    by_advert: dict[tuple[date, int], list[str | None]] = {}
    for row in ad_cost_event_rows:
        report_date = row.get("date")
        advert_id = row.get("advert_id")
        nm_id = row.get("nm_id")
        campaign_type = row.get("campaign_type")
        if report_date is None or advert_id in (None, ""):
            continue
        by_advert.setdefault((report_date, int(advert_id)), []).append(campaign_type)
        if nm_id not in (None, ""):
            by_nm.setdefault((report_date, int(advert_id), int(nm_id)), []).append(campaign_type)
    return (
        {key: _resolve_single_value(values) for key, values in by_nm.items()},
        {key: _resolve_single_value(values) for key, values in by_advert.items()},
    )


def build_ad_campaign_product_rows(
    *,
    campaign_rows: Sequence[Mapping[str, Any]],
    mart_rows: Sequence[Mapping[str, Any]],
    ad_cost_event_rows: Sequence[Mapping[str, Any]],
) -> list[dict[str, Any]]:
    mart_index = _build_mart_index(mart_rows)
    campaign_type_by_nm, campaign_type_by_advert = _build_campaign_type_lookup(ad_cost_event_rows)
    result: list[dict[str, Any]] = []

    valid_row_types = {"PRODUCT", "Товар"}
    for row in campaign_rows:
        if row.get("row_type") not in valid_row_types:
            continue
        report_date = row.get("date")
        nm_id = row.get("nm_id")
        advert_id = row.get("advert_id")
        if report_date is None or nm_id in (None, "") or advert_id in (None, ""):
            continue

        mart_row = mart_index.get((report_date, int(nm_id)), {})
        campaign_spend = _normalize_decimal(row.get("ad_spend"))
        ad_views = _normalize_decimal(row.get("ad_views"))
        ad_clicks = _normalize_decimal(row.get("ad_clicks"))
        ad_atbs = _normalize_decimal(row.get("ad_atbs"))
        ad_orders = _normalize_decimal(row.get("ad_orders"))
        order_sum = _normalize_decimal(mart_row.get("order_sum"))

        conversion_type = (
            row.get("conversion_type_display")
            or row.get("conversion_type")
            or (f"RAW_{row.get('conversion_type_raw')}" if row.get("conversion_type_raw") is not None else None)
        )
        campaign_type = campaign_type_by_nm.get((report_date, int(advert_id), int(nm_id)))
        if campaign_type is None:
            campaign_type = campaign_type_by_advert.get((report_date, int(advert_id)))

        result.append(
            {
                "report_date": report_date,
                "supplier_article": mart_row.get("supplier_article"),
                "nm_id": int(nm_id),
                "title": mart_row.get("title") or row.get("product_name"),
                "brand": mart_row.get("brand"),
                "subject": mart_row.get("subject"),
                "advert_id": int(advert_id),
                "campaign_name": row.get("campaign_name"),
                "campaign_type": campaign_type,
                "conversion_type": conversion_type,
                "campaign_spend": campaign_spend,
                "ad_views": ad_views,
                "ad_clicks": ad_clicks,
                "ad_atbs": ad_atbs,
                "ad_orders": ad_orders,
                "ad_cpc_calc": _safe_divide(campaign_spend, ad_clicks),
                "ad_cpm_calc": _safe_divide(campaign_spend, ad_views, Decimal("1000")),
                "ad_cost_per_cart_calc": _safe_divide(campaign_spend, ad_atbs),
                "ad_cpo_calc": _safe_divide(campaign_spend, ad_orders),
                "order_sum": order_sum,
                "ad_share_of_order_sum_calc": _safe_divide(campaign_spend, order_sum, Decimal("100")),
            }
        )

    result.sort(
        key=lambda item: (
            str(item.get("supplier_article") or ""),
            int(item.get("nm_id") or 0),
            item.get("report_date") or date.min,
            int(item.get("advert_id") or 0),
            str(item.get("conversion_type") or ""),
        )
    )
    return result


def fetch_ad_campaign_product_rows(date_from: date, date_to: date) -> list[dict[str, Any]]:
    with session_scope() as session:
        campaign_rows = [
            _row_to_dict(row)
            for row in session.execute(
                select(FactAdCampaignNmDay).where(
                    FactAdCampaignNmDay.date >= date_from,
                    FactAdCampaignNmDay.date <= date_to,
                )
            ).scalars().all()
        ]
        mart_rows = [
            _row_to_dict(row)
            for row in session.execute(
                select(MartTotalReport).where(
                    MartTotalReport.report_date >= date_from,
                    MartTotalReport.report_date <= date_to,
                )
            ).scalars().all()
        ]
        ad_cost_event_rows = [
            _row_to_dict(row)
            for row in session.execute(
                select(FactAdCostEvent).where(
                    FactAdCostEvent.date >= date_from,
                    FactAdCostEvent.date <= date_to,
                )
            ).scalars().all()
        ]
    return build_ad_campaign_product_rows(
        campaign_rows=campaign_rows,
        mart_rows=mart_rows,
        ad_cost_event_rows=ad_cost_event_rows,
    )


def write_ad_campaign_product_csv(path: Path, rows: Sequence[Mapping[str, Any]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=AD_CAMPAIGN_PRODUCT_COLUMNS, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(rows)
