#!/usr/bin/env python3
from __future__ import annotations

import argparse
import csv
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Iterable


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from sqlalchemy import func, select

from src.db.models import FactAdCampaignNmDay, MartTotalReport
from src.db.session import session_scope


PROCESSED_DIR = ROOT_DIR / "data" / "processed"
PREVIEW_COLUMNS = [
    "report_date",
    "nm_id",
    "supplier_article",
    "title",
    "brand",
    "subject",
    "impressions",
    "card_clicks",
    "ctr_calc",
    "cart_count",
    "add_to_cart_conversion_calc",
    "order_count",
    "cart_to_order_conversion_calc",
    "order_sum",
    "ad_cost_writeoff_total",
    "ad_campaign_spend_total",
    "ad_spend_total",
    "ad_views_total",
    "ad_clicks_total",
    "ad_atbs_total",
    "ad_orders_total",
    "direct_ad_atbs",
    "associated_ad_atbs",
    "multicard_ad_atbs",
    "unknown_ad_atbs",
    "ad_cpc_calc",
    "ad_cpm_calc",
    "ad_cost_per_cart_calc",
    "ad_cpo_calc",
    "ad_share_of_revenue_calc",
    "associated_atbs_percent_calc",
    "organic_cart_share_calc",
    "organic_cart_share_status",
    "search_queries_count",
    "current_stock_qty",
    "has_funnel",
    "has_stock",
    "has_ad_cost",
    "has_ad_campaign",
    "has_search",
    "has_localization_partial",
    "entry_point_status",
    "orders_geography_status",
    "vbro_status",
    "card_comparison_status",
]
FORMULA_SAMPLE_COLUMNS = [
    "report_date",
    "nm_id",
    "supplier_article",
    "title",
    "impressions",
    "card_clicks",
    "ctr_calc",
    "cart_count",
    "add_to_cart_conversion_calc",
    "order_count",
    "cart_to_order_conversion_calc",
    "order_sum",
    "ad_cost_writeoff_total",
    "ad_campaign_spend_total",
    "ad_spend_total",
    "ad_views_total",
    "ad_clicks_total",
    "ad_atbs_total",
    "ad_orders_total",
    "ad_cpc_calc",
    "ad_cpm_calc",
    "ad_cost_per_cart_calc",
    "ad_cpo_calc",
    "ad_share_of_revenue_calc",
    "direct_ad_atbs",
    "associated_ad_atbs",
    "multicard_ad_atbs",
    "unknown_ad_atbs",
    "associated_atbs_percent_calc",
]
AD_AGGREGATES_CHECK_COLUMNS = [
    "report_date",
    "nm_id",
    "supplier_article",
    "title",
    "order_count",
    "order_sum",
    "ad_cost_writeoff_total",
    "ad_campaign_spend_total",
    "ad_spend_total",
    "ad_views_total",
    "ad_clicks_total",
    "ad_atbs_total",
    "ad_orders_total",
    "ad_cost_per_cart_calc",
    "ad_cpo_calc",
    "ad_share_of_revenue_calc",
    "direct_ad_atbs",
    "associated_ad_atbs",
    "multicard_ad_atbs",
    "unknown_ad_atbs",
    "organic_cart_share_status",
]
WITHOUT_DATA_COLUMNS = [
    "report_date",
    "nm_id",
    "supplier_article",
    "title",
    "brand",
    "subject",
    "has_funnel",
    "has_stock",
    "has_ad_cost",
    "has_ad_campaign",
    "has_search",
    "has_localization_partial",
    "entry_point_status",
    "orders_geography_status",
    "vbro_status",
    "card_comparison_status",
]


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Export mart_total_report v2 preview CSVs.")
    parser.add_argument("--date-from", required=True)
    parser.add_argument("--date-to", required=True)
    parser.add_argument("--formula-limit", type=int, default=20)
    return parser.parse_args()


def row_to_dict(row: MartTotalReport) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in MartTotalReport.__table__.columns}


def project_rows(rows: Iterable[dict[str, Any]], columns: list[str]) -> list[dict[str, Any]]:
    return [{column: row.get(column) for column in columns} for row in rows]


def is_formula_sample_row(row: dict[str, Any]) -> bool:
    return any(
        row.get(field) is not None
        for field in (
            "ctr_calc",
            "add_to_cart_conversion_calc",
            "cart_to_order_conversion_calc",
            "ad_cpc_calc",
            "ad_cpm_calc",
            "ad_cpo_calc",
            "ad_share_of_revenue_calc",
            "ad_cost_per_cart_calc",
            "associated_atbs_percent_calc",
        )
    )


def is_ad_aggregates_check_row(row: dict[str, Any]) -> bool:
    return bool(row.get("has_ad_campaign")) or any(
        row.get(field) is not None
        for field in ("ad_spend_total", "ad_cost_writeoff_total", "ad_campaign_spend_total")
    )


def is_without_any_data_row(row: dict[str, Any]) -> bool:
    return not any(
        row.get(field)
        for field in (
            "has_funnel",
            "has_stock",
            "has_ad_cost",
            "has_ad_campaign",
            "has_search",
            "has_localization_partial",
        )
    )


def write_csv(path: Path, rows: list[dict[str, Any]], columns: list[str]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        writer.writerows(project_rows(rows, columns))


def build_conversion_type_summary_rows(date_from: date, date_to: date) -> list[dict[str, Any]]:
    with session_scope() as session:
        rows = session.execute(
            select(
                FactAdCampaignNmDay.conversion_type_display,
                func.count().label("row_count"),
                func.count(FactAdCampaignNmDay.ad_atbs).label("rows_with_atbs"),
                func.sum(FactAdCampaignNmDay.ad_spend).label("sum_ad_spend"),
                func.sum(FactAdCampaignNmDay.ad_views).label("sum_ad_views"),
                func.sum(FactAdCampaignNmDay.ad_clicks).label("sum_ad_clicks"),
                func.sum(FactAdCampaignNmDay.ad_atbs).label("sum_ad_atbs"),
                func.sum(FactAdCampaignNmDay.ad_orders).label("sum_ad_orders"),
            )
            .where(FactAdCampaignNmDay.date >= date_from, FactAdCampaignNmDay.date <= date_to)
            .group_by(FactAdCampaignNmDay.conversion_type_display)
            .order_by(FactAdCampaignNmDay.conversion_type_display.asc())
        ).all()
    return [
        {
            "conversion_type": conversion_type,
            "row_count": row_count,
            "rows_with_atbs": rows_with_atbs,
            "sum_ad_spend": sum_ad_spend,
            "sum_ad_views": sum_ad_views,
            "sum_ad_clicks": sum_ad_clicks,
            "sum_ad_atbs": sum_ad_atbs,
            "sum_ad_orders": sum_ad_orders,
        }
        for conversion_type, row_count, rows_with_atbs, sum_ad_spend, sum_ad_views, sum_ad_clicks, sum_ad_atbs, sum_ad_orders in rows
    ]


def main() -> int:
    args = parse_args()
    date_from = date.fromisoformat(args.date_from)
    date_to = date.fromisoformat(args.date_to)

    with session_scope() as session:
        mart_rows = session.execute(
            select(MartTotalReport)
            .where(MartTotalReport.report_date >= date_from, MartTotalReport.report_date <= date_to)
            .order_by(MartTotalReport.report_date.asc(), MartTotalReport.nm_id.asc())
        ).scalars().all()
        rows = [row_to_dict(row) for row in mart_rows]
    formula_rows = [row for row in rows if is_formula_sample_row(row)][: args.formula_limit]
    without_data_rows = [row for row in rows if is_without_any_data_row(row)]
    ad_aggregates_rows = [row for row in rows if is_ad_aggregates_check_row(row)]

    preview_path = PROCESSED_DIR / "mart_total_report_preview.csv"
    formula_path = PROCESSED_DIR / "mart_formula_check_sample.csv"
    without_data_path = PROCESSED_DIR / "mart_rows_without_any_data.csv"
    ad_aggregates_path = PROCESSED_DIR / "mart_ad_aggregates_check.csv"
    conversion_summary_path = PROCESSED_DIR / "mart_ad_conversion_type_summary.csv"
    conversion_summary_rows = build_conversion_type_summary_rows(date_from, date_to)

    write_csv(preview_path, rows, PREVIEW_COLUMNS)
    write_csv(formula_path, formula_rows, FORMULA_SAMPLE_COLUMNS)
    write_csv(without_data_path, without_data_rows, WITHOUT_DATA_COLUMNS)
    write_csv(ad_aggregates_path, ad_aggregates_rows, AD_AGGREGATES_CHECK_COLUMNS)
    write_csv(
        conversion_summary_path,
        conversion_summary_rows,
        [
            "conversion_type",
            "row_count",
            "rows_with_atbs",
            "sum_ad_spend",
            "sum_ad_views",
            "sum_ad_clicks",
            "sum_ad_atbs",
            "sum_ad_orders",
        ],
    )

    rows_with_ad_spend_total = sum(1 for row in rows if row.get("ad_spend_total") is not None)
    rows_with_ad_cost_writeoff_total = sum(1 for row in rows if row.get("ad_cost_writeoff_total") is not None)
    rows_with_ad_campaign_spend_total = sum(1 for row in rows if row.get("ad_campaign_spend_total") is not None)
    rows_with_ad_atbs_total = sum(1 for row in rows if row.get("ad_atbs_total") is not None)
    rows_with_unknown_ad_atbs = sum(1 for row in rows if row.get("unknown_ad_atbs") is not None)
    rows_with_multicard_ad_atbs = sum(1 for row in rows if row.get("multicard_ad_atbs") is not None)
    rows_with_associated_ad_atbs = sum(1 for row in rows if row.get("associated_ad_atbs") is not None)
    associated_rows = [item for item in conversion_summary_rows if item["conversion_type"] == "Ассоциированная"]
    associated_row_count = associated_rows[0]["row_count"] if associated_rows else 0
    associated_rows_with_atbs = associated_rows[0]["rows_with_atbs"] if associated_rows else 0
    associated_sum_ad_atbs = associated_rows[0]["sum_ad_atbs"] if associated_rows else None
    sum_ad_spend_total = sum((row.get("ad_spend_total") for row in rows if row.get("ad_spend_total") is not None), start=0)
    sum_ad_cost_writeoff_total = sum((row.get("ad_cost_writeoff_total") for row in rows if row.get("ad_cost_writeoff_total") is not None), start=0)
    sum_ad_campaign_spend_total = sum((row.get("ad_campaign_spend_total") for row in rows if row.get("ad_campaign_spend_total") is not None), start=0)
    sum_ad_atbs_total = sum((row.get("ad_atbs_total") for row in rows if row.get("ad_atbs_total") is not None), start=0)
    sum_unknown_ad_atbs = sum((row.get("unknown_ad_atbs") for row in rows if row.get("unknown_ad_atbs") is not None), start=0)
    sum_multicard_ad_atbs = sum((row.get("multicard_ad_atbs") for row in rows if row.get("multicard_ad_atbs") is not None), start=0)
    sum_associated_ad_atbs = sum((row.get("associated_ad_atbs") for row in rows if row.get("associated_ad_atbs") is not None), start=0)

    print(
        json.dumps(
            {
                "date_from": date_from.isoformat(),
                "date_to": date_to.isoformat(),
                "preview_rows": len(rows),
                "formula_sample_rows": len(formula_rows),
                "ad_aggregates_check_rows": len(ad_aggregates_rows),
                "rows_without_any_data": len(without_data_rows),
                "rows_with_ad_spend_total": rows_with_ad_spend_total,
                "rows_with_ad_cost_writeoff_total": rows_with_ad_cost_writeoff_total,
                "rows_with_ad_campaign_spend_total": rows_with_ad_campaign_spend_total,
                "rows_with_ad_atbs_total": rows_with_ad_atbs_total,
                "rows_with_unknown_ad_atbs": rows_with_unknown_ad_atbs,
                "rows_with_multicard_ad_atbs": rows_with_multicard_ad_atbs,
                "rows_with_associated_ad_atbs": rows_with_associated_ad_atbs,
                "sum_ad_spend_total": str(sum_ad_spend_total),
                "sum_ad_cost_writeoff_total": str(sum_ad_cost_writeoff_total),
                "sum_ad_campaign_spend_total": str(sum_ad_campaign_spend_total),
                "sum_ad_atbs_total": str(sum_ad_atbs_total),
                "sum_unknown_ad_atbs": str(sum_unknown_ad_atbs),
                "sum_multicard_ad_atbs": str(sum_multicard_ad_atbs),
                "sum_associated_ad_atbs": str(sum_associated_ad_atbs),
                "associated_row_count": associated_row_count,
                "associated_rows_with_atbs": associated_rows_with_atbs,
                "associated_sum_ad_atbs": str(associated_sum_ad_atbs) if associated_sum_ad_atbs is not None else None,
                "preview_path": str(preview_path),
                "formula_path": str(formula_path),
                "without_data_path": str(without_data_path),
                "ad_aggregates_path": str(ad_aggregates_path),
                "conversion_summary_path": str(conversion_summary_path),
            },
            ensure_ascii=False,
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
