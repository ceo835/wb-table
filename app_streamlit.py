from __future__ import annotations

import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from typing import Any

import altair as alt
import pandas as pd
import streamlit as st
from sqlalchemy import select

from src.ad_campaign_product_dataset import (
    AD_CAMPAIGN_PRODUCT_COLUMNS,
    AD_CAMPAIGN_PRODUCT_DATASET_PATH,
    fetch_ad_campaign_product_rows,
)
from scripts.export_streamlit_v1_dataset import (
    export_streamlit_v1_dataset,
    get_mart_total_report_date_bounds,
)
from src.config.settings import settings
from src.db.mart_total_report_builder import build_mart_total_report
from src.db.models import FactStockWarehouseSnapshot, MartTotalReport
from src.db.session import session_scope
from src.importers.entry_points_importer import import_entry_points_xlsx
from src.importers.orders_geography_importer import import_orders_geography_xlsx
from src.streamlit_dataset import (
    AD_ZERO_FILL_FIELDS,
    FUNNEL_ZERO_FILL_FIELDS,
    NOTE_COLUMNS,
    build_data_quality_label as shared_build_data_quality_label,
    enrich_streamlit_row as shared_enrich_streamlit_row,
)
from src.tracked_products import (
    apply_tracked_products as shared_apply_tracked_products,
    load_tracked_products,
)


ROOT_DIR = Path(__file__).resolve().parent
DATASET_PATH = ROOT_DIR / "data" / "processed" / "streamlit_v1_dataset.csv"
PRODUCT_BANDS_PATH = ROOT_DIR / "data" / "config" / "product_bands.csv"
MAIN_WB_WAREHOUSES_PATH = ROOT_DIR / "data" / "config" / "main_wb_warehouses.csv"
DEFAULT_DATA_SOURCE = "csv"
STOCK_WAREHOUSE_TAB_LABEL = "Остатки по складам"
WAREHOUSE_SCOPE_MAIN = "Основные склады"
WAREHOUSE_SCOPE_ALL = "Все склады"
STOCK_STATUS_OK = "OK"
STOCK_STATUS_ZERO = "ZERO_ON_WAREHOUSE"
STOCK_STATUS_NO_DATA = "NO_DATA_ON_WAREHOUSE"
STOCK_STATUS_NO_PRODUCT_DATA = "NO_STOCK_DATA_FOR_PRODUCT"
AD_CAMPAIGN_PRODUCT_LABEL = "РК по товару"

LATEST_MODE_LABEL = "Последняя дата + динамика"
BY_DATE_MODE_LABEL = "По датам"
CHART_THRESHOLD_CART_COST = 35.0
CHART_THRESHOLD_CPO = 150.0
STYLER_MAX_CELLS = 250_000
CHART_LEVEL_CABINET = "Кабинет"
CHART_LEVEL_CATEGORY = "Категория"
CHART_LEVEL_BAND = "Банда"
CHART_LEVEL_ARTICLE = "Артикул"
CHART_LEVEL_CONVERSION = "Тип WB / конверсии"
CHART_AGGREGATION_LEVELS = [
    CHART_LEVEL_CABINET,
    CHART_LEVEL_CATEGORY,
    CHART_LEVEL_BAND,
    CHART_LEVEL_ARTICLE,
    CHART_LEVEL_CONVERSION,
]
CHART_ALL_CATEGORIES_LABEL = "Все категории"
CHART_ALL_BANDS_LABEL = "Все банды"
CHART_ALL_CONVERSION_TYPES_LABEL = "Все типы WB"
UNKNOWN_WB_TYPE_LABEL = "Неизвестный тип WB 64"
UNKNOWN_WB_TYPE_HELP_TEXT = (
    "Тип WB 64 пришёл из рекламного API WB, но в публичной документации код не расшифрован. "
    "Поэтому он не переименован в «склейку» или «мультикарту»."
)

DISPLAY_COLUMNS_BY_DATE = [
    "product_group_label",
    "supplier_article",
    "nm_id",
    "report_date",
    "title",
    "brand",
    "subject",
    "impressions",
    "card_clicks",
    "cart_count",
    "order_count",
    "ctr_calc",
    "add_to_cart_conversion_calc",
    "cart_to_order_conversion_calc",
    "order_sum",
    "ad_campaign_spend_total",
    "ad_views_total",
    "ad_clicks_total",
    "ad_atbs_total",
    "ad_orders_total",
    "ad_cpc_calc",
    "ad_cpm_calc",
    "ad_cost_per_cart_calc",
    "ad_cpo_calc",
    "ad_share_of_revenue_calc",
    "ad_cost_per_all_carts_calc",
    "organic_cart_count",
    "organic_cart_share_calc",
    "current_stock_qty",
    "current_mp_stock_qty",
    "search_queries_count",
    "local_orders_percent",
    "entry_point_source_label",
    "orders_geography_source_label",
    "vbro_status_label",
    "organic_formula_status_label",
]

TECHNICAL_NOTE_COLUMNS = [
    "impressions_source_note",
    "funnel_data_note",
    "ad_data_note",
    "card_clicks_note",
    "search_data_note",
    "stock_data_note",
    "localization_data_note",
    "entry_point_data_note",
    "vbro_data_note",
]

TECHNICAL_STATUS_COLUMNS = [
    "organic_cart_share_status",
    "entry_point_status",
    "orders_geography_status",
    "vbro_status",
    "card_comparison_status",
    "data_quality_status",
    "has_funnel",
    "has_stock",
    "has_ad_cost",
    "has_ad_campaign",
    "has_search",
    "has_localization_partial",
]

TECHNICAL_EXTRA_COLUMNS_BY_DATE = [
    "entry_impressions_total",
    "entry_card_clicks_total",
    "entry_ctr_calc",
    "entry_cart_total",
    "entry_orders_total",
    "ad_cost_writeoff_total",
    "technical_ad_campaign_spend_total",
] + TECHNICAL_NOTE_COLUMNS + TECHNICAL_STATUS_COLUMNS

DISPLAY_COLUMNS_LATEST = [
    "supplier_article",
    "nm_id",
    "title",
    "brand",
    "subject",
    "report_date",
    "comparison_date",
    "impressions",
    "impressions_delta",
    "cart_count",
    "cart_count_delta",
    "order_count",
    "order_count_delta",
    "order_sum",
    "order_sum_delta",
    "ad_campaign_spend_total",
    "ad_campaign_spend_delta",
    "ad_atbs_total",
    "ad_atbs_delta",
    "ad_orders_total",
    "ad_orders_delta",
    "ad_cpo_calc",
    "ad_cpo_delta",
    "search_queries_count",
    "search_queries_delta",
    "current_stock_qty",
    "stock_delta",
    "data_quality_label",
]

PRODUCT_TIMELINE_COLUMNS = [
    "report_date",
    "impressions",
    "cart_count",
    "order_count",
    "order_sum",
    "ad_campaign_spend_total",
    "ad_atbs_total",
    "ad_orders_total",
    "ad_cpo_calc",
    "search_queries_count",
    "current_stock_qty",
    "data_quality_status",
]

AD_CAMPAIGN_PRODUCT_NUMERIC_COLUMNS = [
    "advert_id",
    "nm_id",
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

AD_CAMPAIGN_PRODUCT_EXPORT_LABELS = {
    "report_date": "Дата",
    "supplier_article": "Артикул продавца",
    "nm_id": "Артикул WB",
    "title": "Название",
    "brand": "Бренд",
    "subject": "Предмет",
    "advert_id": "ID РК",
    "campaign_name": "Название РК",
    "campaign_type": "Тип кампании",
    "conversion_type": "Тип конверсии",
    "campaign_spend": "Расход РК по статистике",
    "ad_views": "Показы РК",
    "ad_clicks": "Клики РК",
    "ad_atbs": "Корзины РК",
    "ad_orders": "Заказы РК",
    "ad_cpc_calc": "CPC",
    "ad_cpm_calc": "CPM",
    "ad_cost_per_cart_calc": "Цена корзины",
    "ad_cpo_calc": "CPO",
    "order_sum": "Сумма заказов товара",
    "ad_share_of_order_sum_calc": "Доля расхода РК от суммы заказов товара, %",
}

NUMERIC_COLUMNS = [
    "display_impressions",
    "display_ctr_calc",
    "impressions",
    "card_clicks",
    "ctr_calc",
    "entry_impressions_total",
    "entry_card_clicks_total",
    "entry_ctr_calc",
    "cart_count",
    "add_to_cart_conversion_calc",
    "entry_cart_total",
    "entry_cart_conversion_calc",
    "order_count",
    "cart_to_order_conversion_calc",
    "entry_orders_total",
    "entry_order_conversion_calc",
    "order_sum",
    "ad_cost_writeoff_total",
    "ad_campaign_spend_total",
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
    "search_queries_count",
    "search_avg_position",
    "search_visibility",
    "search_clicks",
    "search_cart",
    "search_orders",
    "current_stock_qty",
    "current_mp_stock_qty",
    "buyout_count",
    "buyout_sum",
    "buyout_percent",
    "local_orders_percent",
    "localization_orders_total_qty",
    "localization_regions_count",
    "organic_cart_count",
    "organic_cart_share_calc",
    "ad_cost_per_all_carts_calc",
]

SOURCE_FLAG_COLUMNS = [
    "has_funnel",
    "has_stock",
    "has_ad_cost",
    "has_ad_campaign",
    "has_search",
    "has_localization_partial",
]

PERIOD_DATA_METRIC_COLUMNS = [
    "impressions",
    "card_clicks",
    "cart_count",
    "order_count",
    "order_sum",
    "ad_campaign_spend_total",
    "ad_views_total",
    "ad_clicks_total",
    "ad_atbs_total",
    "ad_orders_total",
    "current_stock_qty",
    "current_mp_stock_qty",
    "search_queries_count",
    "local_orders_percent",
]

SUMMARY_KPI_CONFIG = [
    ("impressions", "Показы", 0, False),
    ("cart_count", "Корзины", 0, False),
    ("order_count", "Заказы", 0, False),
    ("order_sum", "Сумма заказов", 2, False),
    ("ad_campaign_spend_total", "Расход РК по статистике", 2, False),
    ("ad_atbs_total", "Корзины РК", 0, False),
    ("ad_orders_total", "Заказы РК", 0, False),
    ("ad_cpo_calc", "CPO", 2, True),
    ("search_queries_count", "Поисковых запросов", 0, False),
    ("current_stock_qty", "Текущий остаток", 0, False),
]

UPLOAD_TAB_TITLE = "Загрузка данных"
ENTRY_POINT_UPLOAD_KEY = "entry_point_import"
ORDERS_GEOGRAPHY_UPLOAD_KEY = "orders_geography_import"

EXPORT_COLUMN_LABELS = {
    "product_group_label": "Товар",
    "report_date": "Дата",
    "comparison_date": "Сравнение с датой",
    "supplier_article": "Артикул продавца",
    "nm_id": "Артикул WB",
    "title": "Название",
    "brand": "Бренд",
    "subject": "Предмет",
    "impressions": "Показы",
    "card_clicks": "Переходы в карточку",
    "ctr_calc": "CTR",
    "cart_count": "Положили в корзину",
    "add_to_cart_conversion_calc": "Конверсия в корзину, %",
    "order_count": "Заказы",
    "cart_to_order_conversion_calc": "Конверсия корзина → заказ, %",
    "order_sum": "Заказали на сумму",
    "buyout_count": "Выкупы, шт",
    "buyout_sum": "Выкупы, сумма",
    "buyout_percent": "Процент выкупа, %",
    "current_stock_qty": "Остаток WB",
    "current_mp_stock_qty": "Остаток МП",
    "local_orders_percent": "Локальные заказы, %",
    "ad_cost_writeoff_total": "Списания рекламы",
    "ad_campaign_spend_total": "Расход РК по статистике",
    "ad_views_total": "Показы РК",
    "ad_clicks_total": "Клики РК",
    "ad_atbs_total": "Корзины РК",
    "ad_orders_total": "Заказы РК",
    "ad_cpc_calc": "CPC",
    "ad_cpm_calc": "CPM",
    "ad_cost_per_cart_calc": "Цена рекламной корзины",
    "ad_cpo_calc": "CPO",
    "ad_share_of_revenue_calc": "Доля рекламы, %",
    "direct_ad_atbs": "Прямые корзины РК",
    "associated_ad_atbs": "Ассоциированные корзины РК",
    "multicard_ad_atbs": "Мультикарточка корзины РК",
    "unknown_ad_atbs": "Unknown корзины РК",
    "associated_atbs_percent_calc": "Ассоциированные корзины, %",
    "organic_cart_count": "Органические корзины",
    "organic_cart_share_calc": "Доля органических корзин, %",
    "ad_cost_per_all_carts_calc": "Расход на все корзины",
    "organic_cart_share_status": "Статус формулы органики",
    "search_queries_count": "Поисковых запросов",
    "search_avg_position": "Средняя позиция поиска",
    "search_visibility": "Видимость поиска",
    "search_clicks": "Клики из поиска",
    "search_cart": "Корзины из поиска",
    "search_orders": "Заказы из поиска",
    "localization_orders_total_qty": "Локализация: заказы, шт",
    "localization_regions_count": "Локализация: регионов",
    "has_funnel": "Есть воронка",
    "has_stock": "Есть остатки",
    "has_ad_cost": "Есть списания",
    "has_ad_campaign": "Есть fullstats",
    "has_search": "Есть поиск",
    "has_localization_partial": "Есть partial localization",
    "entry_point_status": "Статус точки входа",
    "orders_geography_status": "Статус географии",
    "vbro_status": "Статус ВБро",
    "card_comparison_status": "Статус сравнения карточек",
    "data_quality_status": "Технический статус данных",
    "data_quality_label": "Статус данных",
    "funnel_data_note": "Note: Воронка",
    "ad_data_note": "Note: Реклама",
    "card_clicks_note": "Note: Переходы в карточку",
    "search_data_note": "Note: Поиск",
    "stock_data_note": "Note: Остатки",
    "localization_data_note": "Note: География",
    "entry_point_data_note": "Note: Точка входа",
    "vbro_data_note": "Note: ВБро",
    "impressions_delta": "Δ Показы",
    "cart_count_delta": "Δ Корзины",
    "order_count_delta": "Δ Заказы",
    "order_sum_delta": "Δ Сумма заказов",
    "ad_campaign_spend_delta": "Δ Расход РК",
    "ad_atbs_delta": "Δ Корзины РК",
    "ad_orders_delta": "Δ Заказы РК",
    "ad_cpo_delta": "Δ CPO",
    "search_queries_delta": "Δ Поиск",
    "stock_delta": "Δ Остаток",
}

EXPORT_COLUMN_LABELS.update(
    {
        "display_impressions": "Показы",
        "display_ctr_calc": "CTR",
        "impressions_source_note": "Note: Источник показов",
        "entry_impressions_total": "Показы из Точки входа",
        "entry_card_clicks_total": "Переходы из Точки входа",
        "entry_ctr_calc": "CTR из Точки входа",
        "entry_cart_total": "Корзины из Точки входа",
        "entry_cart_conversion_calc": "Конверсия в корзину из Точки входа, %",
        "entry_orders_total": "Заказы из Точки входа",
        "entry_order_conversion_calc": "Конверсия в заказ из Точки входа, %",
    }
)

EXPORT_COLUMN_LABELS.update(
    {
        "product_group_label": "Группа товара",
        "entry_point_source_label": "Источник точки входа",
        "orders_geography_source_label": "Источник географии",
        "vbro_status_label": "ВБро",
        "organic_formula_status_label": "Статус формулы органики",
    }
)

EXPORT_COLUMN_LABELS.update(
    {
        "add_to_cart_conversion_calc": "Конверсия в корзину",
        "cart_to_order_conversion_calc": "Конверсия в заказ",
        "ad_campaign_spend_total": "Сумма кампания",
        "technical_ad_campaign_spend_total": "Расход РК по статистике",
        "ad_cost_per_cart_calc": "Цена корзины РК",
        "ad_share_of_revenue_calc": "Доля рекламы от суммы заказов, %",
        "organic_cart_share_calc": "Процент органики от рекламных корзин",
        "search_queries_count": "Поисковые запросы",
    }
)


def normalize_bool(value: object) -> bool:
    if isinstance(value, bool):
        return value
    if pd.isna(value):
        return False
    return str(value).strip().lower() == "true"


def has_any_source(row: pd.Series) -> bool:
    return any(bool(row.get(field)) for field in SOURCE_FLAG_COLUMNS)


def has_core_coverage(row: pd.Series) -> bool:
    return bool(row.get("has_funnel")) or bool(row.get("has_ad_cost")) or bool(row.get("has_ad_campaign"))


def compute_data_quality_status(row: pd.Series) -> str:
    if not has_any_source(row):
        return "NO_DATA"
    if has_core_coverage(row):
        return "OK_PARTIAL_SOURCES"
    return "PARTIAL"


def build_data_quality_label(status: object) -> str:
    return shared_build_data_quality_label(status)


def build_entry_point_source_label(
    *,
    report_date: object,
    status: object,
    has_entry_points: object,
    entry_impressions_total: object,
    entry_card_clicks_total: object,
    loaded_dates: set[date],
) -> str:
    if (
        normalize_bool(has_entry_points)
        or not pd.isna(entry_impressions_total)
        or not pd.isna(entry_card_clicks_total)
        or status == "CSV_EXPORT"
    ):
        return "Файл загружен"
    if report_date in loaded_dates:
        return "Нет строки в файле"
    return "Файл не загружен за дату"


def build_orders_geography_source_label(status: object, has_localization_partial: object) -> str:
    if status == "CSV_EXPORT":
        return "Файл загружен"
    if normalize_bool(has_localization_partial):
        return "Есть частичные API-данные"
    return "Файл не загружен за дату"


def build_vbro_status_label(status: object) -> str:
    if status == "MANUAL_PENDING":
        return "Не внесено"
    return "—"


def build_organic_formula_status_label(status: object) -> str:
    if status == "OK":
        return "Рассчитано"
    if status == "MISSING_SOURCE":
        return "Недостаточно данных"
    return "—"


def parse_optional_iso_date(value: str | None) -> date | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text:
        return None
    try:
        return date.fromisoformat(text)
    except ValueError:
        return None


def resolve_effective_import_date(
    *,
    use_file_date: bool,
    detected_date: object,
    manual_date_text: str | None,
) -> date | None:
    detected = parse_optional_iso_date(None if detected_date is None else str(detected_date))
    manual = parse_optional_iso_date(manual_date_text)
    if use_file_date:
        return detected or manual
    return manual or detected


def can_apply_import_summary(summary: dict[str, Any] | None) -> bool:
    if not summary:
        return False
    if summary.get("missing_required_columns"):
        return False
    if int(summary.get("rows_read") or 0) <= 0:
        return False
    effective_date = summary.get("effective_date") or summary.get("detected_date")
    return effective_date not in (None, "")


def build_pipeline_status_messages(
    *,
    apply_summary: dict[str, Any] | None = None,
    mart_summary: dict[str, Any] | None = None,
    dataset_summary: dict[str, Any] | None = None,
) -> list[str]:
    messages: list[str] = []
    if apply_summary:
        messages.append(f"Файл записан в БД: {int(apply_summary.get('rows_upserted') or 0)} строк")
    if mart_summary:
        messages.append(f"Mart пересобран: {int(mart_summary.get('rows_upserted') or mart_summary.get('rows_in_db') or 0)} строк")
    if dataset_summary:
        messages.append(f"Dataset обновлён: {int(dataset_summary.get('total_rows') or 0)} строк")
    if messages:
        messages.append("Если данные не видны, обновите страницу")
    return messages


def build_last_upload_result(report_name: str, summary: dict[str, Any]) -> dict[str, object]:
    return {
        "Тип файла": report_name,
        "Дата": fmt_text(summary.get("effective_date") or summary.get("detected_date")),
        "Записано строк": int(summary.get("rows_upserted") or 0),
        "Строк в БД после записи": int(summary.get("rows_in_db_for_date") or 0),
        "Дубликаты": int(summary.get("duplicate_keys") or 0),
        "Таблица": fmt_text(summary.get("target_table")),
        "source_status": fmt_text(summary.get("source_status")),
        "Время загрузки": fmt_text(summary.get("applied_at")),
    }


def build_import_format_error(report_name: str, missing_required_columns: list[str] | tuple[str, ...]) -> str:
    missing = ", ".join(str(column) for column in missing_required_columns)
    return f"Файл не похож на отчёт {report_name}: не найдены обязательные колонки: {missing}"


def resolve_export_range(min_date: object, max_date: object) -> tuple[date | None, date | None]:
    resolved_min = parse_optional_iso_date(None if min_date is None else str(min_date))
    resolved_max = parse_optional_iso_date(None if max_date is None else str(max_date))
    return resolved_min, resolved_max


def summarize_available_dates(df: pd.DataFrame) -> dict[str, object]:
    available_dates = sorted(d for d in df["report_date"].dropna().unique().tolist())
    return {
        "min_date": available_dates[0] if available_dates else None,
        "max_date": available_dates[-1] if available_dates else None,
        "date_count": len(available_dates),
        "dates": available_dates,
    }


def fmt_text(value: object) -> str:
    if pd.isna(value) or value is None or value == "":
        return "—"
    return str(value)


def fmt_num(value: object, digits: int = 2) -> str:
    if pd.isna(value) or value is None:
        return "—"
    return f"{float(value):,.{digits}f}".replace(",", " ")


def row_to_dict(row: MartTotalReport) -> dict[str, object]:
    return {column.name: getattr(row, column.name) for column in MartTotalReport.__table__.columns}


def compute_delta(current: object, previous: object) -> float | None:
    if pd.isna(current) or current is None or pd.isna(previous) or previous is None:
        return None
    return float(current) - float(previous)


def get_previous_product_date(product_rows: pd.DataFrame, selected_date: object) -> object:
    available_dates = sorted(d for d in product_rows["report_date"].dropna().unique().tolist())
    previous_dates = [candidate for candidate in available_dates if candidate < selected_date]
    return previous_dates[-1] if previous_dates else None


def get_row_for_date(product_rows: pd.DataFrame, selected_date: object) -> pd.Series | None:
    matched = product_rows[product_rows["report_date"] == selected_date]
    return None if matched.empty else matched.iloc[0]


def get_latest_product_context(product_rows: pd.DataFrame) -> dict[str, object]:
    sorted_rows = product_rows.sort_values("report_date")
    latest_row = sorted_rows.iloc[-1]
    latest_date = latest_row["report_date"]
    previous_row = sorted_rows.iloc[-2] if len(sorted_rows) > 1 else None
    previous_date = previous_row["report_date"] if previous_row is not None else None
    return {
        "latest_row": latest_row,
        "latest_date": latest_date,
        "previous_row": previous_row,
        "previous_date": previous_date,
        "period_start": sorted_rows["report_date"].min(),
        "period_end": sorted_rows["report_date"].max(),
    }


def format_delta(current: object, previous: object, lower_is_better: bool = False) -> str:
    del lower_is_better
    if pd.isna(current) or current is None:
        return "—"
    if pd.isna(previous) or previous is None:
        return "нет даты для сравнения"

    current_value = float(current)
    previous_value = float(previous)
    delta = current_value - previous_value
    sign = "+" if delta > 0 else ""
    if previous_value == 0:
        return f"{sign}{delta:.2f} / нет %"

    percent_delta = (delta / previous_value) * 100
    percent_sign = "+" if percent_delta > 0 else ""
    return f"{sign}{delta:.2f} / {percent_sign}{percent_delta:.1f}%"


def metric_delta_color(lower_is_better: bool = False) -> str:
    return "inverse" if lower_is_better else "normal"


def build_metric_delta_text(
    current: object,
    previous: object,
    comparison_date: object,
    lower_is_better: bool = False,
) -> str | None:
    delta_text = format_delta(current, previous, lower_is_better=lower_is_better)
    if delta_text == "—":
        return None
    if delta_text == "нет даты для сравнения":
        return delta_text
    if comparison_date is None:
        return delta_text
    return f"{delta_text} к {comparison_date}"


def render_delta_metric(
    label: str,
    current: object,
    previous: object,
    comparison_date: object,
    digits: int = 2,
    lower_is_better: bool = False,
) -> None:
    value = fmt_num(current, digits)
    delta_text = build_metric_delta_text(current, previous, comparison_date, lower_is_better=lower_is_better)
    delta_color = metric_delta_color(lower_is_better) if delta_text not in (None, "нет даты для сравнения") else "off"
    st.metric(label, value, delta=delta_text, delta_color=delta_color)


@st.cache_data(show_spinner=False)
def load_dataset(path: str, cache_buster: float | None = None) -> pd.DataFrame:
    return prepare_dataframe(pd.read_csv(path))


@st.cache_data(show_spinner=False)
def load_dataset_from_db() -> pd.DataFrame:
    with session_scope() as session:
        mart_rows = session.execute(
            select(MartTotalReport).order_by(MartTotalReport.report_date.asc(), MartTotalReport.nm_id.asc())
        ).scalars().all()
        rows = [row_to_dict(row) for row in mart_rows]
    return pd.DataFrame(rows)


def resolve_data_source() -> str:
    explicit_source = os.getenv("STREAMLIT_DATA_SOURCE")
    if explicit_source:
        return explicit_source.strip().lower()
    if os.getenv("DATABASE_URL") or settings.database_url:
        return "db"
    return DEFAULT_DATA_SOURCE


def get_app_password() -> str | None:
    env_password = os.getenv("APP_PASSWORD")
    if env_password:
        return env_password
    try:
        secret_password = st.secrets.get("APP_PASSWORD")
    except Exception:
        secret_password = None
    return secret_password or None


def is_password_protection_enabled() -> bool:
    return bool(get_app_password())


def render_password_gate() -> None:
    expected_password = get_app_password()
    if not expected_password:
        return
    if st.session_state.get("app_authenticated") is True:
        return

    st.subheader("Вход")
    with st.form("app_password_form", clear_on_submit=False):
        entered_password = st.text_input("Пароль", type="password")
        submitted = st.form_submit_button("Открыть dashboard", width="content")
    if submitted:
        if entered_password == expected_password:
            st.session_state["app_authenticated"] = True
            st.rerun()
        else:
            st.error("Неверный пароль.")
    else:
        st.info("Введите пароль для доступа к dashboard.")
    st.stop()


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy()
    if "report_date" in prepared.columns:
        prepared["report_date"] = pd.to_datetime(prepared["report_date"], errors="coerce").dt.date
    for column in NUMERIC_COLUMNS:
        if column in prepared.columns:
            prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    for column in SOURCE_FLAG_COLUMNS:
        if column in prepared.columns:
            prepared[column] = prepared[column].map(normalize_bool)
        else:
            prepared[column] = False
    enriched_rows = [shared_enrich_streamlit_row(row) for row in prepared.to_dict(orient="records")]
    enriched = pd.DataFrame(enriched_rows)
    enriched = shared_apply_tracked_products(enriched)
    if "report_date" in enriched.columns:
        enriched["report_date"] = pd.to_datetime(enriched["report_date"], errors="coerce").dt.date
    if "display_impressions" in enriched.columns:
        if "impressions" not in enriched.columns:
            enriched["impressions"] = pd.NA
        enriched["impressions"] = enriched["impressions"].fillna(enriched["display_impressions"])
    if "display_ctr_calc" in enriched.columns:
        if "ctr_calc" not in enriched.columns:
            enriched["ctr_calc"] = pd.NA
        enriched["ctr_calc"] = enriched["ctr_calc"].fillna(enriched["display_ctr_calc"])
    loaded_entry_point_dates = {
        report_date
        for report_date in enriched.loc[enriched.get("entry_point_status").eq("CSV_EXPORT"), "report_date"].dropna().tolist()
    } if "entry_point_status" in enriched.columns and "report_date" in enriched.columns else set()
    enriched["entry_point_source_label"] = enriched.apply(
        lambda row: build_entry_point_source_label(
            report_date=row.get("report_date"),
            status=row.get("entry_point_status"),
            has_entry_points=row.get("has_entry_points"),
            entry_impressions_total=row.get("entry_impressions_total"),
            entry_card_clicks_total=row.get("entry_card_clicks_total"),
            loaded_dates=loaded_entry_point_dates,
        ),
        axis=1,
    )
    enriched["orders_geography_source_label"] = enriched.apply(
        lambda row: build_orders_geography_source_label(
            row.get("orders_geography_status"),
            row.get("has_localization_partial"),
        ),
        axis=1,
    )
    enriched["vbro_status_label"] = enriched.apply(
        lambda row: build_vbro_status_label(row.get("vbro_status")),
        axis=1,
    )
    enriched["organic_formula_status_label"] = enriched.apply(
        lambda row: build_organic_formula_status_label(row.get("organic_cart_share_status")),
        axis=1,
    )
    for column in SOURCE_FLAG_COLUMNS:
        if column in enriched.columns:
            enriched[column] = enriched[column].map(normalize_bool)
    for column in NOTE_COLUMNS:
        if column not in enriched.columns:
            enriched[column] = "—"
    enriched.attrs["display_coverage"] = build_display_coverage_summary(prepared, enriched)
    return enriched


def prepare_ad_campaign_product_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    prepared = df.copy()
    for column_name in AD_CAMPAIGN_PRODUCT_COLUMNS:
        if column_name not in prepared.columns:
            prepared[column_name] = None
    if "report_date" in prepared.columns:
        prepared["report_date"] = pd.to_datetime(prepared["report_date"], errors="coerce").dt.date
    for column in AD_CAMPAIGN_PRODUCT_NUMERIC_COLUMNS:
        if column in prepared.columns:
            prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    return prepared


def filter_products_with_period_data(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty or "nm_id" not in df.columns:
        return df.copy()

    metric_columns = [column for column in PERIOD_DATA_METRIC_COLUMNS if column in df.columns]
    if not metric_columns:
        return df.copy()

    has_period_data = (
        df[metric_columns]
        .notna()
        .any(axis=1)
        .groupby(df["nm_id"])
        .transform("any")
    )
    return df[has_period_data].copy()


def apply_tracked_scope_filters(
    df: pd.DataFrame,
    *,
    show_only_tracked: bool,
    show_sellout: bool,
) -> pd.DataFrame:
    filtered = df.copy()
    if "is_tracked" not in filtered.columns or "lifecycle_status" not in filtered.columns:
        filtered = shared_apply_tracked_products(filtered)

    if show_only_tracked and "is_tracked" in filtered.columns:
        filtered = filtered[filtered["is_tracked"].fillna(False)]

    if not show_sellout and "lifecycle_status" in filtered.columns:
        filtered = filtered[filtered["lifecycle_status"].fillna("not_tracked").ne("sellout")]

    return filtered.copy()


def build_debug_snapshot(stage: str, df: pd.DataFrame) -> dict[str, object]:
    return {
        "stage": stage,
        "rows": int(len(df)),
        "unique_nm": int(df["nm_id"].nunique()) if "nm_id" in df.columns else 0,
    }


def build_debug_trace_frame(trace: list[dict[str, object]]) -> pd.DataFrame:
    return pd.DataFrame(trace, columns=["stage", "rows", "unique_nm"])


def build_display_coverage_summary(original_df: pd.DataFrame, enriched_df: pd.DataFrame) -> pd.DataFrame:
    coverage_rows: list[dict[str, object]] = []
    coverage_fields = list(dict.fromkeys(FUNNEL_ZERO_FILL_FIELDS + AD_ZERO_FILL_FIELDS))
    original = original_df.reset_index(drop=True)
    enriched = enriched_df.reset_index(drop=True)

    for field in coverage_fields:
        if field not in original.columns and field not in enriched.columns:
            continue

        before_source = original[field] if field in original.columns else pd.Series([pd.NA] * len(original), index=original.index)
        after_source = enriched[field] if field in enriched.columns else pd.Series([pd.NA] * len(enriched), index=enriched.index)
        before = pd.to_numeric(before_source, errors="coerce")
        after = pd.to_numeric(after_source, errors="coerce")
        if field in FUNNEL_ZERO_FILL_FIELDS:
            source_mask = original.get("has_funnel", pd.Series(False, index=original.index)).fillna(False).astype(bool)
            source_name = "funnel"
        else:
            has_ad_cost = original.get("has_ad_cost", pd.Series(False, index=original.index)).fillna(False).astype(bool)
            has_ad_campaign = original.get("has_ad_campaign", pd.Series(False, index=original.index)).fillna(False).astype(bool)
            source_mask = ~(has_ad_cost | has_ad_campaign)
            source_name = "ads"

        null_before = before.isna() & source_mask
        became_zero = null_before & after.fillna(pd.NA).eq(0)
        positive_after = after.gt(0) & source_mask
        coverage_rows.append(
            {
                "source": source_name,
                "field": field,
                "null_before": int(null_before.sum()),
                "became_zero": int(became_zero.sum()),
                "positive_after": int(positive_after.sum()),
            }
        )

    return pd.DataFrame(coverage_rows, columns=["source", "field", "null_before", "became_zero", "positive_after"])


def load_app_dataset() -> tuple[pd.DataFrame, str]:
    data_source = resolve_data_source()
    if data_source == "db":
        if not settings.database_url:
            st.error("DB mode включён, но DATABASE_URL не задан. Переключите STREAMLIT_DATA_SOURCE=csv.")
            st.stop()
        try:
            df = prepare_dataframe(load_dataset_from_db())
        except Exception as exc:
            st.error(
                "Не удалось загрузить данные из PostgreSQL. "
                "Проверьте DATABASE_URL или переключите STREAMLIT_DATA_SOURCE=csv."
            )
            st.caption(f"DB error: {exc.__class__.__name__}")
            st.stop()
        if df.empty:
            st.warning("В mart_total_report нет строк. Переключите STREAMLIT_DATA_SOURCE=csv или наполните mart.")
            st.stop()
        return df, "db"

    if not DATASET_PATH.exists():
        st.error("Сначала соберите dataset командой scripts/export_streamlit_v1_dataset.py")
        st.stop()
    return load_dataset(str(DATASET_PATH), DATASET_PATH.stat().st_mtime), "csv"


@st.cache_data(show_spinner=False)
def load_ad_campaign_product_dataset(path: str, cache_buster: float | None = None) -> pd.DataFrame:
    return prepare_ad_campaign_product_dataframe(pd.read_csv(path))


@st.cache_data(show_spinner=False)
def load_ad_campaign_product_dataset_from_db() -> pd.DataFrame:
    min_date, max_date = get_mart_total_report_date_bounds()
    if min_date is None or max_date is None:
        return pd.DataFrame(columns=AD_CAMPAIGN_PRODUCT_COLUMNS)
    rows = fetch_ad_campaign_product_rows(min_date, max_date)
    return prepare_ad_campaign_product_dataframe(pd.DataFrame(rows))


def load_ad_campaign_product_app_dataset(data_source: str) -> tuple[pd.DataFrame, str | None]:
    if data_source == "db":
        try:
            return load_ad_campaign_product_dataset_from_db(), None
        except Exception as exc:
            return pd.DataFrame(columns=AD_CAMPAIGN_PRODUCT_COLUMNS), str(exc)

    if not AD_CAMPAIGN_PRODUCT_DATASET_PATH.exists():
        return pd.DataFrame(columns=AD_CAMPAIGN_PRODUCT_COLUMNS), (
            "Сначала соберите dataset командой scripts/export_ad_campaign_product_dataset.py"
        )
    return load_ad_campaign_product_dataset(
        str(AD_CAMPAIGN_PRODUCT_DATASET_PATH),
        AD_CAMPAIGN_PRODUCT_DATASET_PATH.stat().st_mtime,
    ), None


@st.cache_data(show_spinner=False)
def load_main_wb_warehouses(path: str, cache_buster: float | None = None) -> list[str]:
    csv_path = Path(path)
    if not csv_path.exists():
        return []
    warehouses_df = pd.read_csv(csv_path)
    if "warehouse_name" not in warehouses_df.columns:
        return []
    if "is_main" in warehouses_df.columns:
        is_main = warehouses_df["is_main"].fillna(False).astype(str).str.strip().str.lower().eq("true")
        warehouses_df = warehouses_df[is_main]
    return [
        warehouse_name
        for warehouse_name in warehouses_df["warehouse_name"].fillna("").astype(str).str.strip().tolist()
        if warehouse_name
    ]


@st.cache_data(show_spinner=False)
def load_stock_warehouse_snapshot_from_db() -> pd.DataFrame:
    with session_scope() as session:
        rows = session.execute(
            select(FactStockWarehouseSnapshot).order_by(
                FactStockWarehouseSnapshot.snapshot_date.asc(),
                FactStockWarehouseSnapshot.nm_id.asc(),
                FactStockWarehouseSnapshot.warehouse_name.asc(),
            )
        ).scalars().all()
        materialized_rows = [
            {
                "snapshot_date": row.snapshot_date,
                "nm_id": row.nm_id,
                "chrt_id": row.chrt_id,
                "warehouse_id": row.warehouse_id,
                "warehouse_name": row.warehouse_name,
                "region_name": row.region_name,
                "stock_qty": row.stock_qty,
                "in_way_to_client": row.in_way_to_client,
                "in_way_from_client": row.in_way_from_client,
                "source": row.source,
                "loaded_at": row.loaded_at,
            }
            for row in rows
        ]

    return pd.DataFrame(materialized_rows)


def prepare_stock_warehouse_snapshot_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    expected_columns = [
        "snapshot_date",
        "nm_id",
        "warehouse_id",
        "warehouse_name",
        "region_name",
        "stock_qty",
        "in_way_to_client",
        "in_way_from_client",
    ]
    prepared = df.copy()
    for column in expected_columns:
        if column not in prepared.columns:
            prepared[column] = pd.NA

    if prepared.empty:
        return prepared[expected_columns].copy()

    prepared["snapshot_date"] = pd.to_datetime(prepared["snapshot_date"], errors="coerce").dt.date
    prepared["nm_id"] = pd.to_numeric(prepared["nm_id"], errors="coerce")
    prepared["warehouse_id"] = pd.to_numeric(prepared["warehouse_id"], errors="coerce")
    for column in ("stock_qty", "in_way_to_client", "in_way_from_client"):
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    prepared["warehouse_name"] = prepared["warehouse_name"].fillna("").astype(str).str.strip()
    prepared = prepared.dropna(subset=["snapshot_date", "nm_id"]).copy()
    prepared["nm_id"] = prepared["nm_id"].astype(int)

    aggregated = (
        prepared.groupby(
            ["snapshot_date", "nm_id", "warehouse_id", "warehouse_name", "region_name"],
            dropna=False,
            as_index=False,
        )[["stock_qty", "in_way_to_client", "in_way_from_client"]]
        .sum(min_count=1)
    )
    return aggregated


def _normalize_stock_display_value(value: object) -> int | float | str:
    if pd.isna(value):
        return "NO_DATA"
    numeric_value = float(value)
    if numeric_value.is_integer():
        return int(numeric_value)
    return round(numeric_value, 2)


def _build_stock_status(*, has_any_snapshot: bool, zero_count: int, no_data_count: int) -> str:
    if not has_any_snapshot:
        return STOCK_STATUS_NO_PRODUCT_DATA
    if no_data_count > 0:
        return STOCK_STATUS_NO_DATA
    if zero_count > 0:
        return STOCK_STATUS_ZERO
    return STOCK_STATUS_OK


def build_stock_warehouse_product_table(
    snapshot_df: pd.DataFrame,
    tracked_df: pd.DataFrame,
    *,
    snapshot_date: date,
    selected_warehouses: list[str],
    show_only_tracked: bool,
    show_sellout: bool,
) -> pd.DataFrame:
    warehouse_names = list(dict.fromkeys(selected_warehouses))
    snapshot_prepared = prepare_stock_warehouse_snapshot_dataframe(snapshot_df)
    tracked_prepared = tracked_df.copy()
    for column in ("nm_id", "tracked_label", "is_tracked", "lifecycle_status"):
        if column not in tracked_prepared.columns:
            tracked_prepared[column] = pd.NA
    if not tracked_prepared.empty:
        tracked_prepared["nm_id"] = pd.to_numeric(tracked_prepared["nm_id"], errors="coerce")
        tracked_prepared = tracked_prepared.dropna(subset=["nm_id"]).copy()
        tracked_prepared["nm_id"] = tracked_prepared["nm_id"].astype(int)
        tracked_prepared["is_tracked"] = tracked_prepared["is_tracked"].fillna(False).astype(bool)
        tracked_prepared["lifecycle_status"] = tracked_prepared["lifecycle_status"].fillna("not_tracked")
        tracked_prepared = tracked_prepared.drop_duplicates(subset=["nm_id"], keep="first")

    current_snapshot = snapshot_prepared[snapshot_prepared["snapshot_date"] == snapshot_date].copy()
    current_snapshot = current_snapshot[current_snapshot["warehouse_name"].isin(warehouse_names)].copy()
    snapshot_nm_ids = set(current_snapshot["nm_id"].dropna().astype(int).tolist())
    any_snapshot_nm_ids_for_date = set(
        snapshot_prepared.loc[snapshot_prepared["snapshot_date"] == snapshot_date, "nm_id"].dropna().astype(int).tolist()
    )

    tracked_columns = ["nm_id", "tracked_label", "is_tracked", "lifecycle_status"]
    if show_only_tracked:
        base_products = tracked_prepared.loc[tracked_prepared["is_tracked"], tracked_columns].copy()
    else:
        snapshot_products = pd.DataFrame({"nm_id": sorted(snapshot_nm_ids | any_snapshot_nm_ids_for_date)})
        base_products = snapshot_products.merge(
            tracked_prepared[tracked_columns],
            on="nm_id",
            how="left",
        )
        base_products["is_tracked"] = base_products["is_tracked"].fillna(False).astype(bool)
        base_products["lifecycle_status"] = base_products["lifecycle_status"].fillna("not_tracked")
        missing_tracked = tracked_prepared.loc[~tracked_prepared["nm_id"].isin(base_products["nm_id"]), tracked_columns]
        if not missing_tracked.empty:
            base_products = pd.concat([base_products, missing_tracked], ignore_index=True)

    if base_products.empty:
        return pd.DataFrame(
            columns=[
                "nm_id",
                "tracked_label",
                "lifecycle_status",
                *warehouse_names,
                "zero_warehouses_count",
                "no_data_warehouses_count",
                "zero_warehouses",
                "no_data_warehouses",
                "problem_warehouses",
                "stock_status",
            ]
        )

    if not show_sellout:
        base_products = base_products[base_products["lifecycle_status"].fillna("not_tracked").ne("sellout")].copy()

    current_snapshot = current_snapshot.groupby(["nm_id", "warehouse_name"], as_index=False)[
        ["stock_qty", "in_way_to_client", "in_way_from_client"]
    ].sum(min_count=1)

    stock_lookup = {
        (int(row["nm_id"]), str(row["warehouse_name"])): row["stock_qty"]
        for _, row in current_snapshot.iterrows()
    }

    rows: list[dict[str, object]] = []
    for _, product_row in base_products.sort_values(["tracked_label", "nm_id"], na_position="last").iterrows():
        nm_id = int(product_row["nm_id"])
        has_any_snapshot = nm_id in any_snapshot_nm_ids_for_date
        row: dict[str, object] = {
            "nm_id": nm_id,
            "tracked_label": product_row.get("tracked_label"),
            "lifecycle_status": product_row.get("lifecycle_status") or "not_tracked",
        }
        zero_warehouses: list[str] = []
        no_data_warehouses: list[str] = []

        for warehouse_name in warehouse_names:
            quantity = stock_lookup.get((nm_id, warehouse_name), pd.NA)
            display_value = _normalize_stock_display_value(quantity)
            row[warehouse_name] = display_value
            if display_value == "NO_DATA":
                no_data_warehouses.append(warehouse_name)
            elif float(display_value) == 0:
                zero_warehouses.append(warehouse_name)

        row["zero_warehouses_count"] = len(zero_warehouses)
        row["no_data_warehouses_count"] = len(no_data_warehouses)
        row["zero_warehouses"] = ", ".join(zero_warehouses) if zero_warehouses else "—"
        row["no_data_warehouses"] = ", ".join(no_data_warehouses) if no_data_warehouses else "—"
        problem_warehouses = list(dict.fromkeys(no_data_warehouses + zero_warehouses))
        row["problem_warehouses"] = ", ".join(problem_warehouses) if problem_warehouses else "—"
        row["stock_status"] = _build_stock_status(
            has_any_snapshot=has_any_snapshot,
            zero_count=len(zero_warehouses),
            no_data_count=len(no_data_warehouses),
        )
        rows.append(row)

    return pd.DataFrame(rows)


def build_stock_warehouse_summary_metrics(product_table: pd.DataFrame) -> dict[str, int]:
    if product_table.empty:
        return {
            "total_products": 0,
            "ok_products": 0,
            "zero_products": 0,
            "no_data_products": 0,
            "total_zero_warehouses": 0,
        }

    return {
        "total_products": int(len(product_table)),
        "ok_products": int(product_table["stock_status"].eq(STOCK_STATUS_OK).sum()),
        "zero_products": int(product_table["stock_status"].eq(STOCK_STATUS_ZERO).sum()),
        "no_data_products": int(product_table["stock_status"].isin([STOCK_STATUS_NO_DATA, STOCK_STATUS_NO_PRODUCT_DATA]).sum()),
        "total_zero_warehouses": int(pd.to_numeric(product_table["zero_warehouses_count"], errors="coerce").fillna(0).sum()),
    }


def build_stock_warehouse_problem_table(product_table: pd.DataFrame) -> pd.DataFrame:
    if product_table.empty:
        return pd.DataFrame(
            columns=["nm_id", "tracked_label", "problem_warehouses", "zero_warehouses", "no_data_warehouses", "stock_status"]
        )
    return product_table.loc[
        product_table["stock_status"].ne(STOCK_STATUS_OK),
        ["nm_id", "tracked_label", "problem_warehouses", "zero_warehouses", "no_data_warehouses", "stock_status"],
    ].copy()


def style_stock_warehouse_table(
    df: pd.DataFrame,
    warehouse_columns: list[str],
) -> pd.io.formats.style.Styler:
    def warehouse_value_color(value: object) -> str:
        if value == "NO_DATA":
            return "background-color: #e5e7eb; color: #4b5563;"
        if pd.isna(value):
            return ""
        try:
            if float(value) == 0:
                return "background-color: #fde2e4; color: #7f1d1d;"
        except (TypeError, ValueError):
            return ""
        return ""

    def stock_status_color(value: object) -> str:
        if value == STOCK_STATUS_OK:
            return "background-color: #e8f5e9; color: #1b5e20;"
        if value == STOCK_STATUS_ZERO:
            return "background-color: #fff3cd; color: #7a4b00;"
        if value in (STOCK_STATUS_NO_DATA, STOCK_STATUS_NO_PRODUCT_DATA):
            return "background-color: #e5e7eb; color: #374151;"
        return ""

    styler = df.style
    if warehouse_columns:
        styler = styler.map(warehouse_value_color, subset=warehouse_columns)
    if "stock_status" in df.columns:
        styler = styler.map(stock_status_color, subset=["stock_status"])
    return styler.format(precision=0, na_rep="—")


def prepare_stock_warehouse_table_for_display(
    df: pd.DataFrame,
    warehouse_columns: list[str],
) -> pd.DataFrame | pd.io.formats.style.Styler:
    safe_df = df.copy()
    safe_df.attrs = {}
    cells_count = int(df.shape[0]) * int(df.shape[1])
    if cells_count > STYLER_MAX_CELLS:
        st.caption(
            f"Большая таблица складских остатков: {df.shape[0]} строк × {df.shape[1]} колонок = {cells_count:,} ячеек. "
            "Цветовое оформление отключено для стабильной загрузки."
        )
        return safe_df
    return style_stock_warehouse_table(safe_df, warehouse_columns)


def render_stock_warehouse_tab(data_source: str) -> None:
    st.caption("Источник: `fact_stock_warehouse_snapshot`, агрегация до уровня Артикул WB × склад.")
    if data_source != "db":
        st.info("Вкладка складских остатков доступна в режиме PostgreSQL, потому что читает `fact_stock_warehouse_snapshot` напрямую.")
        return

    snapshot_df = load_stock_warehouse_snapshot_from_db()
    if snapshot_df.empty:
        st.warning("В `fact_stock_warehouse_snapshot` пока нет строк.")
        return

    prepared_snapshot = prepare_stock_warehouse_snapshot_dataframe(snapshot_df)
    available_dates = sorted(d for d in prepared_snapshot["snapshot_date"].dropna().unique().tolist())
    if not available_dates:
        st.warning("В `fact_stock_warehouse_snapshot` нет валидных дат snapshot.")
        return

    tracked_df = load_tracked_products()
    main_warehouses = load_main_wb_warehouses(
        str(MAIN_WB_WAREHOUSES_PATH),
        MAIN_WB_WAREHOUSES_PATH.stat().st_mtime if MAIN_WB_WAREHOUSES_PATH.exists() else None,
    )
    selected_snapshot_date = st.selectbox("Дата snapshot", options=available_dates, index=len(available_dates) - 1)

    filter_cols = st.columns(4)
    show_only_tracked = filter_cols[0].checkbox("Показывать только отслеживаемые товары", value=True)
    show_sellout = filter_cols[1].checkbox("Показывать распродажные товары", value=True)
    only_problematic = filter_cols[2].checkbox("Показывать только проблемные товары", value=False)
    warehouse_scope = filter_cols[3].radio("Склады", options=[WAREHOUSE_SCOPE_MAIN, WAREHOUSE_SCOPE_ALL], horizontal=False)

    current_snapshot = prepared_snapshot[prepared_snapshot["snapshot_date"] == selected_snapshot_date].copy()
    all_warehouses = sorted(current_snapshot["warehouse_name"].dropna().astype(str).unique().tolist())
    selected_warehouses = main_warehouses if warehouse_scope == WAREHOUSE_SCOPE_MAIN else all_warehouses
    if not selected_warehouses:
        st.warning("Для выбранной даты не найден список складов.")
        return

    product_table = build_stock_warehouse_product_table(
        prepared_snapshot,
        tracked_df,
        snapshot_date=selected_snapshot_date,
        selected_warehouses=selected_warehouses,
        show_only_tracked=show_only_tracked,
        show_sellout=show_sellout,
    )
    summary_metrics = build_stock_warehouse_summary_metrics(product_table)
    problem_table = build_stock_warehouse_problem_table(product_table)

    summary_cols = st.columns(6)
    summary_cols[0].metric("Дата snapshot", selected_snapshot_date.isoformat())
    summary_cols[1].metric("Всего tracked товаров", f"{summary_metrics['total_products']:,}".replace(",", " "))
    summary_cols[2].metric("Товаров с OK", f"{summary_metrics['ok_products']:,}".replace(",", " "))
    summary_cols[3].metric("Товаров с нулём на складах", f"{summary_metrics['zero_products']:,}".replace(",", " "))
    summary_cols[4].metric("Товаров с NO_DATA", f"{summary_metrics['no_data_products']:,}".replace(",", " "))
    summary_cols[5].metric("Всего нулевых складов", f"{summary_metrics['total_zero_warehouses']:,}".replace(",", " "))

    st.write("**Проблемные товары**")
    problem_display = problem_table.rename(
        columns={
            "nm_id": "Артикул WB",
            "tracked_label": "Название",
            "problem_warehouses": "Проблемные склады",
            "zero_warehouses": "Нулевые склады",
            "no_data_warehouses": "Склады без данных",
            "stock_status": "stock_status",
        }
    )
    st.dataframe(
        prepare_stock_warehouse_table_for_display(problem_display, []),
        width="stretch",
        hide_index=True,
    )

    if only_problematic:
        product_table = product_table[product_table["stock_status"].ne(STOCK_STATUS_OK)].copy()

    display_columns = ["nm_id", "tracked_label", "lifecycle_status", *selected_warehouses, "zero_warehouses_count", "no_data_warehouses_count", "stock_status"]
    table_display = product_table.reindex(columns=display_columns).rename(
        columns={
            "nm_id": "Артикул WB",
            "tracked_label": "Название / tracked_label",
            "lifecycle_status": "lifecycle_status",
            "zero_warehouses_count": "zero_warehouses_count",
            "no_data_warehouses_count": "no_data_warehouses_count",
            "stock_status": "stock_status",
        }
    )
    warehouse_display_columns = [warehouse_name for warehouse_name in selected_warehouses if warehouse_name in table_display.columns]

    st.write("**Остатки по складам**")
    st.dataframe(
        prepare_stock_warehouse_table_for_display(table_display, warehouse_display_columns),
        width="stretch",
        hide_index=True,
    )


def save_uploaded_file_to_temp(uploaded_file: Any) -> Path:
    suffix = Path(getattr(uploaded_file, "name", "upload.xlsx")).suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suffix) as tmp_file:
        tmp_file.write(uploaded_file.getvalue())
        return Path(tmp_file.name)


def run_import_preview(
    *,
    importer_func,
    uploaded_file: Any,
    use_file_date: bool,
    manual_date_text: str | None,
) -> dict[str, Any]:
    temp_path = save_uploaded_file_to_temp(uploaded_file)
    try:
        summary = importer_func(
            str(temp_path),
            explicit_date=None if use_file_date else parse_optional_iso_date(manual_date_text),
            apply=False,
        )
    finally:
        temp_path.unlink(missing_ok=True)

    effective_date = resolve_effective_import_date(
        use_file_date=use_file_date,
        detected_date=summary.get("detected_date"),
        manual_date_text=manual_date_text,
    )
    summary["effective_date"] = effective_date.isoformat() if effective_date else None
    summary["can_apply"] = can_apply_import_summary(summary)
    return summary


def run_import_apply(
    *,
    importer_func,
    uploaded_file: Any,
    effective_date: date | None,
) -> dict[str, Any]:
    temp_path = save_uploaded_file_to_temp(uploaded_file)
    try:
        summary = importer_func(str(temp_path), explicit_date=effective_date, apply=True)
    finally:
        temp_path.unlink(missing_ok=True)
    summary["effective_date"] = effective_date.isoformat() if effective_date else None
    summary["applied_at"] = datetime.now().strftime("%Y-%m-%d %H:%M:%S")
    return summary


def render_import_result(summary: dict[str, Any], report_name: str) -> None:
    missing_required_columns = summary.get("missing_required_columns") or []
    if missing_required_columns:
        st.error(build_import_format_error(report_name, missing_required_columns))
    elif int(summary.get("rows_read") or 0) <= 0:
        st.warning("Файл прочитан, но строки с данными не найдены.")
    else:
        st.success("Файл успешно проверен.")

    info_cols = st.columns(4)
    info_cols[0].metric("detected_date", fmt_text(summary.get("detected_date")))
    info_cols[1].metric("effective_date", fmt_text(summary.get("effective_date")))
    info_cols[2].metric("rows_read", fmt_text(summary.get("rows_read")))
    info_cols[3].metric("invalid_rows_count", fmt_text(summary.get("skipped_rows_count")))

    if summary.get("rows_upserted") is not None:
        write_cols = st.columns(6)
        write_cols[0].metric("rows_upserted", fmt_text(summary.get("rows_upserted")))
        write_cols[1].metric("rows_in_db_for_date", fmt_text(summary.get("rows_in_db_for_date")))
        write_cols[2].metric("duplicate_keys", fmt_text(summary.get("duplicate_keys")))
        write_cols[3].metric("target_table", fmt_text(summary.get("target_table")))
        write_cols[4].metric("source_status", fmt_text(summary.get("source_status")))
        source_counts = summary.get("source_status_counts") or {}
        write_cols[5].metric("source_status rows", fmt_text(source_counts.get(summary.get("source_status"))))

    preview_rows = summary.get("preview_rows") or []
    if preview_rows:
        st.write("**Первые нормализованные строки**")
        st.dataframe(pd.DataFrame(preview_rows[:10]), width="stretch", hide_index=True)

    skipped_rows_preview = summary.get("skipped_rows_preview") or []
    if skipped_rows_preview:
        st.write("**Пропущенные строки**")
        st.dataframe(pd.DataFrame(skipped_rows_preview[:10]), width="stretch", hide_index=True)

    source_status_counts = summary.get("source_status_counts")
    if source_status_counts:
        st.write("**source_status counts**")
        st.json(source_status_counts)


def render_last_upload_result(last_result: dict[str, object] | None) -> None:
    if not last_result:
        return
    st.write("**Последние результаты загрузки**")
    st.dataframe(pd.DataFrame([last_result]), width="stretch", hide_index=True)


def clear_streamlit_data_caches() -> None:
    for cached_func in (
        load_dataset,
        load_dataset_from_db,
        load_ad_campaign_product_dataset,
        load_ad_campaign_product_dataset_from_db,
        load_main_wb_warehouses,
        load_stock_warehouse_snapshot_from_db,
    ):
        try:
            cached_func.clear()
        except Exception:
            pass


def rebuild_mart_for_date(report_date: date) -> dict[str, Any]:
    result = build_mart_total_report(report_date, report_date, version="v2")
    clear_streamlit_data_caches()
    return result


def refresh_streamlit_dataset() -> dict[str, Any]:
    min_date, max_date = resolve_export_range(*get_mart_total_report_date_bounds())
    if min_date is None or max_date is None:
        raise RuntimeError("В mart_total_report нет дат для экспорта dataset.")
    result = export_streamlit_v1_dataset(min_date, max_date)
    clear_streamlit_data_caches()
    return result


def build_filtered_dataset(df: pd.DataFrame) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    filtered = df.copy()
    debug_trace = [build_debug_snapshot("rows_after_load_dataset_from_db", filtered)]

    with st.sidebar:
        st.header("Фильтры")

        available_dates = sorted(d for d in filtered["report_date"].dropna().unique().tolist())
        selected_dates = st.multiselect("Дата", options=available_dates, default=available_dates)
        if selected_dates:
            filtered = filtered[filtered["report_date"].isin(selected_dates)]
        debug_trace.append(build_debug_snapshot("rows_after_date_filter", filtered))

        show_only_tracked = st.checkbox("Показывать только отслеживаемые товары", value=True)
        filtered = apply_tracked_scope_filters(
            filtered,
            show_only_tracked=show_only_tracked,
            show_sellout=True,
        )
        debug_trace.append(build_debug_snapshot("rows_after_tracked_filter", filtered))

        show_sellout = st.checkbox("Показывать распродажные товары", value=True)
        filtered = apply_tracked_scope_filters(
            filtered,
            show_only_tracked=False,
            show_sellout=show_sellout,
        )
        debug_trace.append(build_debug_snapshot("rows_after_sellout_filter", filtered))

        supplier_search = st.text_input("Поиск по артикулу продавца")
        if supplier_search:
            filtered = filtered[
                filtered["supplier_article"].fillna("").str.contains(supplier_search, case=False, na=False)
            ]
        debug_trace.append(build_debug_snapshot("rows_after_supplier_article_filter", filtered))

        nm_search = st.text_input("Поиск по nm_id")
        if nm_search:
            filtered = filtered[filtered["nm_id"].astype(str).str.contains(nm_search, case=False, na=False)]
        debug_trace.append(build_debug_snapshot("rows_after_nm_id_filter", filtered))

        brand_options = sorted(b for b in filtered["brand"].dropna().astype(str).unique().tolist())
        selected_brands = st.multiselect("Бренд", options=brand_options)
        if selected_brands:
            filtered = filtered[filtered["brand"].isin(selected_brands)]
        debug_trace.append(build_debug_snapshot("rows_after_brand_filter", filtered))

        subject_options = sorted(s for s in filtered["subject"].dropna().astype(str).unique().tolist())
        selected_subjects = st.multiselect("Предмет", options=subject_options)
        if selected_subjects:
            filtered = filtered[filtered["subject"].isin(selected_subjects)]
        debug_trace.append(build_debug_snapshot("rows_after_subject_filter", filtered))

        status_options = sorted(s for s in filtered["data_quality_status"].dropna().astype(str).unique().tolist())
        selected_statuses = st.multiselect("data_quality_status", options=status_options)
        if selected_statuses:
            filtered = filtered[filtered["data_quality_status"].isin(selected_statuses)]
        debug_trace.append(build_debug_snapshot("rows_after_data_quality_status_filter", filtered))

        ads_only = st.checkbox("Показывать только товары с рекламой")
        if ads_only:
            filtered = filtered[filtered["has_ad_campaign"] | filtered["has_ad_cost"]]
        debug_trace.append(build_debug_snapshot("rows_after_ads_only_filter", filtered))

        show_products_without_data = st.checkbox("Показывать товары без данных", value=False)
        if not show_products_without_data:
            filtered = filter_products_with_period_data(filtered)
        debug_trace.append(build_debug_snapshot("rows_after_products_without_data_filter", filtered))

        no_data_only = st.checkbox("Показывать только товары без данных")
        if no_data_only:
            filtered = filtered[filtered["data_quality_status"] == "NO_DATA"]
        debug_trace.append(build_debug_snapshot("rows_after_no_data_only_filter", filtered))

        pending_only = st.checkbox("Показывать только товары с pending-источниками")
        if pending_only:
            pending_mask = (
                filtered["entry_point_status"].eq("FILE_IMPORT_PENDING")
                | filtered["orders_geography_status"].eq("FILE_IMPORT_PENDING")
                | filtered["vbro_status"].eq("MANUAL_PENDING")
            )
            filtered = filtered[pending_mask]
        debug_trace.append(build_debug_snapshot("rows_after_pending_only_filter", filtered))

    filtered = filtered.sort_values(
        by=["report_date", "order_sum", "order_count"],
        ascending=[False, False, False],
        na_position="last",
    )
    debug_trace.append(build_debug_snapshot("rows_after_all_filters", filtered))
    return filtered, debug_trace


def build_latest_snapshot_dataset(filtered: pd.DataFrame) -> pd.DataFrame:
    if filtered.empty:
        return filtered.copy()

    rows: list[dict[str, object]] = []
    grouped = filtered.sort_values(["nm_id", "report_date"]).groupby("nm_id", sort=False)

    for _, product_rows in grouped:
        context = get_latest_product_context(product_rows)
        current_row = context["latest_row"]
        previous_row = context["previous_row"]

        row_data = current_row.to_dict()
        row_data["impressions_delta"] = compute_delta(
            current_row.get("impressions"),
            None if previous_row is None else previous_row.get("impressions"),
        )
        row_data["cart_count_delta"] = compute_delta(
            current_row.get("cart_count"),
            None if previous_row is None else previous_row.get("cart_count"),
        )
        row_data["order_count_delta"] = compute_delta(
            current_row.get("order_count"),
            None if previous_row is None else previous_row.get("order_count"),
        )
        row_data["order_sum_delta"] = compute_delta(
            current_row.get("order_sum"),
            None if previous_row is None else previous_row.get("order_sum"),
        )
        row_data["ad_campaign_spend_delta"] = compute_delta(
            current_row.get("ad_campaign_spend_total"),
            None if previous_row is None else previous_row.get("ad_campaign_spend_total"),
        )
        row_data["ad_atbs_delta"] = compute_delta(
            current_row.get("ad_atbs_total"),
            None if previous_row is None else previous_row.get("ad_atbs_total"),
        )
        row_data["ad_orders_delta"] = compute_delta(
            current_row.get("ad_orders_total"),
            None if previous_row is None else previous_row.get("ad_orders_total"),
        )
        row_data["ad_cpo_delta"] = compute_delta(
            current_row.get("ad_cpo_calc"),
            None if previous_row is None else previous_row.get("ad_cpo_calc"),
        )
        row_data["search_queries_delta"] = compute_delta(
            current_row.get("search_queries_count"),
            None if previous_row is None else previous_row.get("search_queries_count"),
        )
        row_data["stock_delta"] = compute_delta(
            current_row.get("current_stock_qty"),
            None if previous_row is None else previous_row.get("current_stock_qty"),
        )
        row_data["comparison_date"] = None if previous_row is None else previous_row.get("report_date")
        row_data["data_quality_label"] = build_data_quality_label(current_row.get("data_quality_status"))
        rows.append(row_data)

    latest_df = pd.DataFrame(rows)
    return latest_df.sort_values(
        by=["report_date", "order_sum", "order_count"],
        ascending=[False, False, False],
        na_position="last",
    )


def build_grouped_by_date_dataset(filtered: pd.DataFrame) -> pd.DataFrame:
    if filtered.empty:
        return filtered.copy()

    grouped_df = filtered.copy().sort_values(
        by=["supplier_article", "nm_id", "report_date"],
        ascending=[True, True, True],
        na_position="last",
    )
    grouped_df["product_group_label"] = ""

    previous_key: tuple[object, object] | None = None
    for index, row in grouped_df.iterrows():
        current_key = (row.get("supplier_article"), row.get("nm_id"))
        if current_key != previous_key:
            grouped_df.at[index, "product_group_label"] = (
                f"▼ {fmt_text(row.get('supplier_article'))} | {fmt_text(row.get('nm_id'))}"
            )
        previous_key = current_key

    return grouped_df


def build_product_timeline_dataset(product_rows: pd.DataFrame) -> pd.DataFrame:
    timeline = product_rows[PRODUCT_TIMELINE_COLUMNS].copy()
    return timeline.sort_values("report_date", ascending=False, na_position="last")


def style_table(df: pd.DataFrame, status_column: str | None = None) -> pd.io.formats.style.Styler:
    def status_color(value: object) -> str:
        if value in ("Нет данных", "NO_DATA"):
            return "background-color: #fde2e4; color: #7f1d1d;"
        if value in ("Данные есть, внешние источники ожидаются", "OK_PARTIAL_SOURCES"):
            return "background-color: #e8f5e9; color: #1b5e20;"
        if value in ("Частично", "PARTIAL"):
            return "background-color: #fff3cd; color: #7a4b00;"
        return ""

    def ad_cpo_color(value: object) -> str:
        if pd.isna(value):
            return ""
        if float(value) > 100:
            return "background-color: #ffe5d0; color: #9a3412;"
        return ""

    styler = df.style
    if status_column in df.columns:
        styler = styler.map(status_color, subset=[status_column])
    if "ad_cpo_calc" in df.columns:
        styler = styler.map(ad_cpo_color, subset=["ad_cpo_calc"])
    if "product_group_label" in df.columns:
        def highlight_product_group(row: pd.Series) -> list[str]:
            if str(row.get("product_group_label") or "").strip():
                return ["background-color: #f8fafc; border-top: 2px solid #d1d5db;"] * len(row)
            return [""] * len(row)

        styler = styler.apply(highlight_product_group, axis=1)
    return styler.format(precision=2, na_rep="—")


def prepare_dataframe_for_streamlit_display(
    df: pd.DataFrame,
    status_column: str | None = None,
) -> pd.DataFrame | pd.io.formats.style.Styler:
    safe_df = df.copy()
    safe_df.attrs = {}
    cells_count = int(df.shape[0]) * int(df.shape[1])
    if cells_count > STYLER_MAX_CELLS:
        st.caption(
            f"Большая таблица: {df.shape[0]} строк × {df.shape[1]} колонок = {cells_count:,} ячеек. "
            "Цветовое оформление отключено для стабильной загрузки."
        )
        return safe_df
    return style_table(safe_df, status_column=status_column)


def build_export_dataframe(table_df: pd.DataFrame, display_columns: list[str]) -> pd.DataFrame:
    export_df = table_df.reindex(columns=display_columns).copy()
    if "product_group_label" in export_df.columns:
        filled_group_label = (
            export_df["supplier_article"].fillna("").astype(str).str.strip()
            + " | "
            + export_df["nm_id"].fillna("").astype(str).str.strip()
        ).str.strip(" |")
        normalized_existing = (
            export_df["product_group_label"]
            .fillna("")
            .astype(str)
            .str.replace("▼", "", regex=False)
            .str.strip()
        )
        export_df["product_group_label"] = normalized_existing.where(
            normalized_existing.ne(""),
            filled_group_label,
        )
    renamed_columns = {
        column_name: EXPORT_COLUMN_LABELS.get(column_name, column_name)
        for column_name in export_df.columns
    }
    return export_df.rename(columns=renamed_columns)


def get_product_options(filtered: pd.DataFrame) -> tuple[list[str], dict[str, dict[str, object]]]:
    product_rows = (
        filtered.sort_values(["supplier_article", "nm_id", "title"], na_position="last")
        .drop_duplicates(subset=["nm_id"])
        .copy()
    )
    option_map: dict[str, dict[str, object]] = {}
    options: list[str] = []
    for _, row in product_rows.iterrows():
        label = f"{fmt_text(row.get('supplier_article'))} | {int(row['nm_id'])} | {fmt_text(row.get('title'))}"
        option_map[label] = {"nm_id": int(row["nm_id"])}
        options.append(label)
    return options, option_map


def get_selected_product_rows(
    filtered: pd.DataFrame,
    selected_label: str,
    option_map: dict[str, dict[str, object]],
) -> pd.DataFrame:
    selected_nm_id = option_map[selected_label]["nm_id"]
    return filtered[filtered["nm_id"] == selected_nm_id].sort_values("report_date")


def build_warnings(row: pd.Series, previous_row: pd.Series | None = None) -> list[str]:
    warnings: list[str] = []
    if row.get("data_quality_status") == "NO_DATA":
        warnings.append("Нет данных по товару")
    if bool(row.get("has_ad_campaign")) and (pd.isna(row.get("order_count")) or float(row.get("order_count") or 0) <= 0):
        warnings.append("Есть реклама, но нет заказов")
    if not pd.isna(row.get("ad_cpo_calc")) and float(row["ad_cpo_calc"]) > CHART_THRESHOLD_CPO:
        warnings.append("Высокий CPO")
    if not pd.isna(row.get("ad_cost_per_cart_calc")) and float(row["ad_cost_per_cart_calc"]) > CHART_THRESHOLD_CART_COST:
        warnings.append("Высокая стоимость корзины")
    if pd.isna(row.get("current_stock_qty")) or float(row.get("current_stock_qty") or 0) <= 0:
        warnings.append("Нет остатка")
    if row.get("entry_point_status") == "FILE_IMPORT_PENDING":
        warnings.append("Точка входа ожидает файл")
    if row.get("orders_geography_status") == "FILE_IMPORT_PENDING":
        warnings.append("География ожидает файл")
    if row.get("vbro_status") == "MANUAL_PENDING":
        warnings.append("ВБро ожидает ручной ввод")
    report_date = row.get("report_date")
    if not pd.isna(report_date):
        report_date_value = pd.to_datetime(report_date, errors="coerce")
        if not pd.isna(report_date_value) and report_date_value.date() > (datetime.now().date() - timedelta(days=2)):
            warnings.append("РК-данные за последние 1–2 дня могут быть неполными")

    if previous_row is not None:
        if not pd.isna(previous_row.get("order_count")) and float(previous_row.get("order_count") or 0) > 0:
            current = float(row.get("order_count") or 0)
            previous = float(previous_row.get("order_count") or 0)
            if current < previous * 0.8:
                warnings.append("Заказы упали")

        if not pd.isna(previous_row.get("ad_campaign_spend_total")) and float(previous_row.get("ad_campaign_spend_total") or 0) > 0:
            current = float(row.get("ad_campaign_spend_total") or 0)
            previous = float(previous_row.get("ad_campaign_spend_total") or 0)
            if current > previous * 1.2:
                warnings.append("Расход рекламы вырос")

        if not pd.isna(previous_row.get("ad_cpo_calc")) and float(previous_row.get("ad_cpo_calc") or 0) > 0:
            current = float(row.get("ad_cpo_calc") or 0)
            previous = float(previous_row.get("ad_cpo_calc") or 0)
            if current > previous * 1.2:
                warnings.append("CPO вырос")

        if not pd.isna(previous_row.get("current_stock_qty")) and float(previous_row.get("current_stock_qty") or 0) > 0:
            current = float(row.get("current_stock_qty") or 0)
            previous = float(previous_row.get("current_stock_qty") or 0)
            if current < previous * 0.8:
                warnings.append("Остаток снизился")

    return warnings


def render_overview_tab(
    filtered: pd.DataFrame,
    filter_debug_trace: list[dict[str, object]],
    display_coverage: pd.DataFrame | None = None,
) -> tuple[int, int]:
    view_mode = st.radio(
        "Вид таблицы",
        options=[LATEST_MODE_LABEL, BY_DATE_MODE_LABEL],
        horizontal=True,
    )

    if view_mode == LATEST_MODE_LABEL:
        st.info("Одна строка = один товар. Показана последняя доступная дата и изменение к предыдущей доступной дате по этому товару.")
        table_df = build_latest_snapshot_dataset(filtered)
        display_columns = DISPLAY_COLUMNS_LATEST
        export_columns = DISPLAY_COLUMNS_LATEST
        status_column = "data_quality_label"
        download_label = "Скачать CSV"
    else:
        st.info("Одна строка = один товар за одну дату. Таблица сгруппирована по артикулам: сначала все даты одного товара, затем следующий товар. Пустые значения не заменяются нулями. Причины пустых данных указаны в колонках с пометкой note.")
        table_df = build_grouped_by_date_dataset(filtered).copy()
        table_df["technical_ad_campaign_spend_total"] = table_df.get("ad_campaign_spend_total")
        st.caption("В основном виде оставлены только бизнес-колонки. Технические поля скрыты и не попадают в основной CSV, пока чекбокс выключен.")
        show_technical_fields = st.checkbox("Показать технические поля", value=False)
        display_columns = DISPLAY_COLUMNS_BY_DATE + (TECHNICAL_EXTRA_COLUMNS_BY_DATE if show_technical_fields else [])
        export_columns = DISPLAY_COLUMNS_BY_DATE + (TECHNICAL_EXTRA_COLUMNS_BY_DATE if show_technical_fields else [])
        status_column = "data_quality_label"
        download_label = "Скачать расширенный ИТОГО CSV"

    table_display_df = table_df.reindex(columns=display_columns).copy()
    export_df = build_export_dataframe(table_df, export_columns)
    export_debug_trace = [
        build_debug_snapshot("rows_before_export_table_df", table_df),
        build_debug_snapshot("rows_before_export_export_df", export_df),
    ]
    csv_bytes = export_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(download_label, data=csv_bytes, file_name="streamlit_v1_filtered.csv", mime="text/csv")
    with st.expander("Debug фильтрации и экспорта"):
        st.caption("Экспорт CSV строится не из полного load_dataset_from_db(), а из текущего table_df после всех применённых фильтров.")
        st.dataframe(build_debug_trace_frame(filter_debug_trace), width="stretch", hide_index=True)
        st.dataframe(build_debug_trace_frame(export_debug_trace), width="stretch", hide_index=True)
        if display_coverage is not None and not display_coverage.empty:
            st.caption("Coverage по display-заменам: сколько значений были NULL, сколько стали 0 по правилам display-слоя, сколько осталось реально > 0.")
            st.dataframe(display_coverage, width="stretch", hide_index=True)
    st.dataframe(
        prepare_dataframe_for_streamlit_display(
            table_display_df,
            status_column=status_column,
        ),
        width="stretch",
        hide_index=True,
        height=720,
        column_config={
            "entry_impressions_total": st.column_config.NumberColumn("Показы из Точки входа", format="%.0f"),
            "entry_card_clicks_total": st.column_config.NumberColumn("Переходы из Точки входа", format="%.0f"),
            "entry_ctr_calc": st.column_config.NumberColumn("CTR из Точки входа", format="%.6f"),
            "entry_cart_total": st.column_config.NumberColumn("Корзины из Точки входа", format="%.0f"),
            "entry_orders_total": st.column_config.NumberColumn("Заказы из Точки входа", format="%.0f"),
            "entry_point_source_label": st.column_config.TextColumn("Источник точки входа", width="medium"),
            "orders_geography_source_label": st.column_config.TextColumn("Источник географии", width="medium"),
            "vbro_status_label": st.column_config.TextColumn("ВБро", width="medium"),
            "organic_formula_status_label": st.column_config.TextColumn("Статус формулы органики", width="medium"),
            "product_group_label": st.column_config.TextColumn("Группа товара", width="medium"),
            "report_date": st.column_config.DateColumn("Дата"),
            "comparison_date": st.column_config.DateColumn("Сравнение с датой"),
            "supplier_article": st.column_config.TextColumn("Артикул продавца", width="medium"),
            "nm_id": st.column_config.NumberColumn("Артикул WB", format="%d"),
            "title": st.column_config.TextColumn("Название", width="large"),
            "brand": st.column_config.TextColumn("Бренд"),
            "subject": st.column_config.TextColumn("Предмет"),
            "impressions": st.column_config.NumberColumn("Показы", format="%.0f"),
            "card_clicks": st.column_config.NumberColumn("Переходы в карточку", format="%.0f"),
            "ctr_calc": st.column_config.NumberColumn("CTR", format="%.2f"),
            "impressions_delta": st.column_config.NumberColumn("Δ Показы", format="%.0f"),
            "cart_count": st.column_config.NumberColumn("Положили в корзину", format="%.0f"),
            "add_to_cart_conversion_calc": st.column_config.NumberColumn("Конверсия в корзину", format="%.2f"),
            "cart_count_delta": st.column_config.NumberColumn("Δ Корзины", format="%.0f"),
            "order_count": st.column_config.NumberColumn("Заказы", format="%.0f"),
            "order_count_delta": st.column_config.NumberColumn("Δ Заказы", format="%.0f"),
            "order_sum": st.column_config.NumberColumn("Заказали на сумму", format="%.2f"),
            "order_sum_delta": st.column_config.NumberColumn("Δ Сумма заказов", format="%.2f"),
            "buyout_count": st.column_config.NumberColumn("Выкупы, шт", format="%.0f"),
            "buyout_sum": st.column_config.NumberColumn("Выкупы, сумма", format="%.2f"),
            "buyout_percent": st.column_config.NumberColumn("Процент выкупа, %", format="%.2f"),
            "cart_to_order_conversion_calc": st.column_config.NumberColumn("Конверсия в заказ", format="%.2f"),
            "ad_cost_writeoff_total": st.column_config.NumberColumn("Списания рекламы", format="%.2f"),
            "ad_campaign_spend_total": st.column_config.NumberColumn("Сумма кампания", format="%.2f"),
            "technical_ad_campaign_spend_total": st.column_config.NumberColumn("Расход РК по статистике", format="%.2f"),
            "ad_campaign_spend_delta": st.column_config.NumberColumn("Δ Расход РК", format="%.2f"),
            "ad_views_total": st.column_config.NumberColumn("Показы РК", format="%.0f"),
            "ad_clicks_total": st.column_config.NumberColumn("Клики РК", format="%.0f"),
            "ad_atbs_total": st.column_config.NumberColumn("Корзины РК", format="%.0f"),
            "ad_atbs_delta": st.column_config.NumberColumn("Δ Корзины РК", format="%.0f"),
            "ad_orders_total": st.column_config.NumberColumn("Заказы РК", format="%.0f"),
            "ad_orders_delta": st.column_config.NumberColumn("Δ Заказы РК", format="%.0f"),
            "ad_cpc_calc": st.column_config.NumberColumn("CPC", format="%.2f"),
            "ad_cpm_calc": st.column_config.NumberColumn("CPM", format="%.2f"),
            "ad_cost_per_cart_calc": st.column_config.NumberColumn("Цена корзины РК", format="%.2f"),
            "ad_cpo_calc": st.column_config.NumberColumn("CPO", format="%.2f"),
            "ad_cpo_delta": st.column_config.NumberColumn("Δ CPO", format="%.2f"),
            "ad_share_of_revenue_calc": st.column_config.NumberColumn("Доля рекламы от суммы заказов, %", format="%.2f"),
            "direct_ad_atbs": st.column_config.NumberColumn("Прямые корзины РК", format="%.0f"),
            "associated_ad_atbs": st.column_config.NumberColumn("Ассоциированные корзины РК", format="%.0f"),
            "multicard_ad_atbs": st.column_config.NumberColumn("Мультикарточка корзины РК", format="%.0f"),
            "unknown_ad_atbs": st.column_config.NumberColumn("Unknown корзины РК", format="%.0f"),
            "associated_atbs_percent_calc": st.column_config.NumberColumn("Ассоциированные корзины, %", format="%.2f"),
            "organic_cart_count": st.column_config.NumberColumn("Органические корзины", format="%.0f"),
            "organic_cart_share_calc": st.column_config.NumberColumn("Процент органики от рекламных корзин", format="%.2f"),
            "ad_cost_per_all_carts_calc": st.column_config.NumberColumn("Расход на все корзины", format="%.2f"),
            "organic_cart_share_status": st.column_config.TextColumn("Статус формулы органики", width="medium"),
            "search_queries_count": st.column_config.NumberColumn("Поисковые запросы", format="%.0f"),
            "search_avg_position": st.column_config.NumberColumn("Средняя позиция поиска", format="%.2f"),
            "search_visibility": st.column_config.NumberColumn("Видимость поиска", format="%.2f"),
            "search_clicks": st.column_config.NumberColumn("Клики из поиска", format="%.0f"),
            "search_cart": st.column_config.NumberColumn("Корзины из поиска", format="%.0f"),
            "search_orders": st.column_config.NumberColumn("Заказы из поиска", format="%.0f"),
            "search_queries_delta": st.column_config.NumberColumn("Δ Поиск", format="%.0f"),
            "current_stock_qty": st.column_config.NumberColumn("Остаток WB", format="%.0f"),
            "current_mp_stock_qty": st.column_config.NumberColumn("Остаток МП", format="%.0f"),
            "local_orders_percent": st.column_config.NumberColumn("Локальные заказы, %", format="%.2f"),
            "localization_orders_total_qty": st.column_config.NumberColumn("Локализация: заказы, шт", format="%.0f"),
            "localization_regions_count": st.column_config.NumberColumn("Локализация: регионов", format="%.0f"),
            "stock_delta": st.column_config.NumberColumn("Δ Остаток", format="%.0f"),
            "has_funnel": st.column_config.CheckboxColumn("Есть воронка"),
            "has_stock": st.column_config.CheckboxColumn("Есть остатки"),
            "has_ad_cost": st.column_config.CheckboxColumn("Есть списания"),
            "has_ad_campaign": st.column_config.CheckboxColumn("Есть fullstats"),
            "has_search": st.column_config.CheckboxColumn("Есть поиск"),
            "has_localization_partial": st.column_config.CheckboxColumn("Есть partial localization"),
            "entry_point_status": st.column_config.TextColumn("Статус точки входа", width="medium"),
            "orders_geography_status": st.column_config.TextColumn("Статус географии", width="medium"),
            "vbro_status": st.column_config.TextColumn("Статус ВБро", width="medium"),
            "card_comparison_status": st.column_config.TextColumn("Статус сравнения карточек", width="medium"),
            "data_quality_status": st.column_config.TextColumn("Технический статус данных", width="medium"),
            "data_quality_label": st.column_config.TextColumn("Статус данных", width="medium"),
            "funnel_data_note": st.column_config.TextColumn("Note: Воронка", width="large"),
            "ad_data_note": st.column_config.TextColumn("Note: Реклама", width="medium"),
            "card_clicks_note": st.column_config.TextColumn("Note: Переходы в карточку", width="large"),
            "search_data_note": st.column_config.TextColumn("Note: Поиск", width="large"),
            "stock_data_note": st.column_config.TextColumn("Note: Остатки", width="large"),
            "localization_data_note": st.column_config.TextColumn("Note: География", width="large"),
            "entry_point_data_note": st.column_config.TextColumn("Note: Точка входа", width="large"),
            "vbro_data_note": st.column_config.TextColumn("Note: ВБро", width="large"),
        },
    )
    return len(filtered), len(table_df)


def render_available_dates_summary(df: pd.DataFrame) -> None:
    summary = summarize_available_dates(df)
    with st.expander("Доступные даты в данных", expanded=False):
        metric_cols = st.columns(3)
        metric_cols[0].metric("Минимальная дата", fmt_text(summary["min_date"]))
        metric_cols[1].metric("Максимальная дата", fmt_text(summary["max_date"]))
        metric_cols[2].metric("Количество дат", str(summary["date_count"]))
        dates_text = ", ".join(str(value) for value in summary["dates"]) if summary["dates"] else "—"
        st.caption(f"Список дат: {dates_text}")


def build_formula_line(label: str, numerator: object, denominator: object, multiplier: float, result: object) -> str:
    if pd.isna(numerator) or pd.isna(denominator) or denominator in (0, 0.0, None):
        return f"{label}: Недостаточно данных"
    if multiplier == 1000:
        formula = f"{fmt_num(numerator)} / {fmt_num(denominator)} × 1000 = {fmt_num(result)}"
    elif multiplier == 100:
        formula = f"{fmt_num(numerator)} / {fmt_num(denominator)} × 100 = {fmt_num(result)}"
    else:
        formula = f"{fmt_num(numerator)} / {fmt_num(denominator)} = {fmt_num(result)}"
    return f"{label}: {formula}"


def render_info_field(container: Any, label: str, value: object) -> None:
    container.markdown(f"**{label}**")
    container.write(fmt_text(value))


def build_key_value_table(rows: list[tuple[str, object, int | None]]) -> pd.DataFrame:
    formatted_rows: list[dict[str, str]] = []
    for label, value, digits in rows:
        if digits is None:
            formatted_value = fmt_text(value)
        else:
            formatted_value = fmt_num(value, digits)
        formatted_rows.append({"Показатель": label, "Значение": formatted_value})
    return pd.DataFrame(formatted_rows)


def render_compact_metric_table(title: str, rows: list[tuple[str, object, int | None]]) -> None:
    st.subheader(title)
    st.dataframe(
        build_key_value_table(rows),
        width="stretch",
        hide_index=True,
        column_config={
            "Показатель": st.column_config.TextColumn("Показатель", width="medium"),
            "Значение": st.column_config.TextColumn("Значение", width="medium"),
        },
    )


def render_grouped_kpi_row(
    latest_row: pd.Series,
    previous_row: pd.Series | None,
    previous_date: object,
    configs: list[tuple[str, str, int, bool, float | None, str | None]],
) -> None:
    cols = st.columns(len(configs))
    for column, config in zip(cols, configs):
        field_name, label, digits, lower_is_better, threshold, threshold_label = config
        with column:
            render_delta_metric(
                label,
                latest_row.get(field_name),
                None if previous_row is None else previous_row.get(field_name),
                previous_date,
                digits=digits,
                lower_is_better=lower_is_better,
            )
            value = latest_row.get(field_name)
            if threshold is not None and not pd.isna(value) and float(value) > threshold and threshold_label:
                st.caption(f"Превышение: {threshold_label}")


def render_summary_kpis(latest_row: pd.Series, previous_row: pd.Series | None, previous_date: object) -> None:
    st.subheader("Основные KPI по последней дате")
    st.caption("Дельта считается к предыдущей доступной дате по товару.")
    render_grouped_kpi_row(
        latest_row,
        previous_row,
        previous_date,
        [
            ("cart_count", "Корзины", 0, False, None, None),
            ("order_count", "Заказы", 0, False, None, None),
            ("order_sum", "Сумма заказов", 2, False, None, None),
            ("ad_cpo_calc", "CPO", 2, True, CHART_THRESHOLD_CPO, "CPO выше 150 руб."),
        ],
    )
    render_grouped_kpi_row(
        latest_row,
        previous_row,
        previous_date,
        [
            ("ad_campaign_spend_total", "Расход РК", 2, False, None, None),
            ("ad_atbs_total", "Корзины РК", 0, False, None, None),
            ("ad_orders_total", "Заказы РК", 0, False, None, None),
            ("ad_cost_per_cart_calc", "Цена рекламной корзины", 2, True, CHART_THRESHOLD_CART_COST, "Цена корзины выше 35 руб."),
        ],
    )
    render_grouped_kpi_row(
        latest_row,
        previous_row,
        previous_date,
        [
            ("impressions", "Показы", 0, False, None, None),
            ("search_queries_count", "Поисковые запросы", 0, False, None, None),
            ("current_stock_qty", "Текущий остаток", 0, False, None, None),
            ("ad_share_of_revenue_calc", "ДРР", 2, True, None, None),
        ],
    )


def render_formula_details(detail_row: pd.Series, detail_date: object) -> None:
    st.subheader(f"Проверка формул за {detail_date}")
    st.write(
        build_formula_line(
            "Конверсия в заказ",
            detail_row.get("order_count"),
            detail_row.get("cart_count"),
            100,
            detail_row.get("cart_to_order_conversion_calc"),
        )
    )
    st.write(
        build_formula_line(
            "CPC",
            detail_row.get("ad_campaign_spend_total"),
            detail_row.get("ad_clicks_total"),
            1,
            detail_row.get("ad_cpc_calc"),
        )
    )
    st.write(
        build_formula_line(
            "CPM",
            detail_row.get("ad_campaign_spend_total"),
            detail_row.get("ad_views_total"),
            1000,
            detail_row.get("ad_cpm_calc"),
        )
    )
    st.write(
        build_formula_line(
            "Цена рекламной корзины",
            detail_row.get("ad_campaign_spend_total"),
            detail_row.get("ad_atbs_total"),
            1,
            detail_row.get("ad_cost_per_cart_calc"),
        )
    )
    st.write(
        build_formula_line(
            "CPO",
            detail_row.get("ad_campaign_spend_total"),
            detail_row.get("ad_orders_total"),
            1,
            detail_row.get("ad_cpo_calc"),
        )
    )
    st.write(
        build_formula_line(
            "Доля рекламы",
            detail_row.get("ad_campaign_spend_total"),
            detail_row.get("order_sum"),
            100,
            detail_row.get("ad_share_of_revenue_calc"),
        )
    )


def render_product_charts_section(product_rows: pd.DataFrame) -> None:
    st.subheader("Динамика товара")
    chart_df = build_chart_metrics_by_date(product_rows)
    if chart_df.empty:
        st.info("Нет данных за выбранный период.")
        return

    carts_chart = build_user_friendly_chart(
        chart_df=chart_df,
        series_map={"cart_count": "Итоговые корзины", "ad_atbs_total": "Корзины РК"},
        y_title="Корзины, шт.",
        tooltip_value_title="Значение, шт.",
        value_format=".0f",
        line_colors=["#2563eb", "#f97316"],
    )
    st.markdown("#### Корзины товара")
    if carts_chart is None:
        st.info("Нет данных за выбранный период.")
    else:
        st.altair_chart(carts_chart, width="stretch")

    cart_cost_chart = build_user_friendly_chart(
        chart_df=chart_df,
        series_map={"total_cart_cost": "Стоимость корзины ИТОГ", "ad_cart_cost": "Стоимость корзины РК"},
        y_title="Стоимость, руб.",
        tooltip_value_title="Стоимость, руб.",
        value_format=".1f",
        line_colors=["#0f766e", "#f59e0b"],
        threshold=CHART_THRESHOLD_CART_COST,
        threshold_label="Порог 35 руб.",
    )
    st.markdown("#### Стоимость корзины товара")
    if cart_cost_chart is None:
        st.info("Нет данных за выбранный период.")
    else:
        st.altair_chart(cart_cost_chart, width="stretch")

    cpo_chart = build_user_friendly_chart(
        chart_df=chart_df,
        series_map={"total_cpo": "CPO ИТОГ", "ad_cpo": "CPO РК"},
        y_title="CPO, руб.",
        tooltip_value_title="CPO, руб.",
        value_format=".1f",
        line_colors=["#7c3aed", "#ef4444"],
        threshold=CHART_THRESHOLD_CPO,
        threshold_label="Порог 150 руб.",
    )
    st.markdown("#### CPO товара")
    if cpo_chart is None:
        st.info("Нет данных за выбранный период.")
    else:
        st.altair_chart(cpo_chart, width="stretch")


def render_product_timeline_table(product_rows: pd.DataFrame) -> None:
    with st.expander("Таблица динамики по датам", expanded=False):
        timeline = build_product_timeline_dataset(product_rows)
        st.dataframe(
            timeline,
            width="stretch",
            hide_index=True,
            column_config={
                "report_date": st.column_config.DateColumn("Дата"),
                "impressions": st.column_config.NumberColumn("Показы", format="%.0f"),
                "cart_count": st.column_config.NumberColumn("Корзины", format="%.0f"),
                "order_count": st.column_config.NumberColumn("Заказы", format="%.0f"),
                "order_sum": st.column_config.NumberColumn("Сумма заказов", format="%.2f"),
                "ad_campaign_spend_total": st.column_config.NumberColumn("Расход РК по статистике", format="%.2f"),
                "ad_atbs_total": st.column_config.NumberColumn("Корзины РК", format="%.0f"),
                "ad_orders_total": st.column_config.NumberColumn("Заказы РК", format="%.0f"),
                "ad_cpo_calc": st.column_config.NumberColumn("CPO", format="%.2f"),
                "search_queries_count": st.column_config.NumberColumn("Поисковых запросов", format="%.0f"),
                "current_stock_qty": st.column_config.NumberColumn("Текущий остаток", format="%.0f"),
                "data_quality_status": st.column_config.TextColumn("Статус данных"),
            },
        )


def render_product_tab(product_rows: pd.DataFrame, selected_product_date: object) -> None:
    context = get_latest_product_context(product_rows)
    latest_row: pd.Series = context["latest_row"]
    latest_date = context["latest_date"]
    previous_row: pd.Series | None = context["previous_row"]
    previous_date = context["previous_date"]
    period_start = context["period_start"]
    period_end = context["period_end"]

    st.subheader("Карточка товара")
    st.markdown(f"**{fmt_text(latest_row.get('supplier_article'))} | {fmt_text(latest_row.get('nm_id'))}**")
    st.caption(fmt_text(latest_row.get("title")))

    passport_cols_top = st.columns(3)
    render_info_field(passport_cols_top[0], "Артикул продавца", latest_row.get("supplier_article"))
    render_info_field(passport_cols_top[1], "Артикул WB", latest_row.get("nm_id"))
    render_info_field(passport_cols_top[2], "Бренд", latest_row.get("brand"))

    passport_cols_mid = st.columns(3)
    render_info_field(passport_cols_mid[0], "Предмет", latest_row.get("subject"))
    render_info_field(passport_cols_mid[1], "Доступный период", f"{period_start} — {period_end}")
    render_info_field(passport_cols_mid[2], "Последняя дата", latest_date)

    passport_cols_bottom = st.columns(2)
    render_info_field(
        passport_cols_bottom[0],
        "Дата сравнения",
        previous_date if previous_date is not None else "Нет предыдущей даты для сравнения",
    )
    render_info_field(passport_cols_bottom[1], "Статус данных", latest_row.get("data_quality_label"))

    render_summary_kpis(latest_row, previous_row, previous_date)

    detail_dates = sorted(product_rows["report_date"].dropna().unique().tolist(), reverse=True)
    detail_date = st.selectbox("Дата для детализации формул", options=detail_dates, format_func=lambda d: str(d))
    detail_row = get_row_for_date(product_rows, detail_date)
    if detail_row is None:
        st.error("Не удалось найти строку для выбранной даты детализации.")
        return

    render_compact_metric_table(
        "Воронка за дату",
        [
            ("Показы", detail_row.get("impressions"), 0),
            ("Переходы в карточку", detail_row.get("card_clicks"), 0),
            ("CTR", detail_row.get("ctr_calc"), 2),
            ("Корзины", detail_row.get("cart_count"), 0),
            ("Конверсия в корзину", detail_row.get("add_to_cart_conversion_calc"), 2),
            ("Заказы", detail_row.get("order_count"), 0),
            ("Конверсия корзина → заказ", detail_row.get("cart_to_order_conversion_calc"), 2),
            ("Сумма заказов", detail_row.get("order_sum"), 2),
        ],
    )

    render_compact_metric_table(
        "Реклама за дату",
        [
            ("Финансовые списания рекламы", detail_row.get("ad_cost_writeoff_total"), 2),
            ("Расход РК по статистике", detail_row.get("ad_campaign_spend_total"), 2),
            ("Показы РК", detail_row.get("ad_views_total"), 0),
            ("Клики РК", detail_row.get("ad_clicks_total"), 0),
            ("Корзины РК", detail_row.get("ad_atbs_total"), 0),
            ("Заказы РК", detail_row.get("ad_orders_total"), 0),
            ("CPC", detail_row.get("ad_cpc_calc"), 2),
            ("CPM", detail_row.get("ad_cpm_calc"), 2),
            ("Цена рекламной корзины", detail_row.get("ad_cost_per_cart_calc"), 2),
            ("CPO", detail_row.get("ad_cpo_calc"), 2),
            ("ДРР / Доля рекламы от суммы заказов, %", detail_row.get("ad_share_of_revenue_calc"), 2),
        ],
    )
    with st.expander("Техническое пояснение", expanded=False):
        st.markdown(
            """
            - `Финансовые списания рекламы` = данные из `ad_cost_writeoff_total`
            - `Расход РК по статистике` = данные из `ad_campaign_spend_total`
            """
        )

    render_compact_metric_table(
        "Корзины рекламы по типам",
        [
            ("Прямые", detail_row.get("direct_ad_atbs"), 0),
            ("Ассоциированные", detail_row.get("associated_ad_atbs"), 0),
            ("Мультикарточка", detail_row.get("multicard_ad_atbs"), 0),
            ("Unknown", detail_row.get("unknown_ad_atbs"), 0),
        ],
    )

    render_compact_metric_table(
        "Поиск и остатки за дату",
        [
            ("Количество поисковых запросов", detail_row.get("search_queries_count"), 0),
            ("Текущий остаток", detail_row.get("current_stock_qty"), 0),
        ],
    )

    with st.expander("Проверка формул", expanded=False):
        render_formula_details(detail_row, detail_date)

    render_product_charts_section(product_rows)
    render_product_timeline_table(product_rows)

    st.subheader("Внимание")
    warnings = build_warnings(latest_row, previous_row)
    if warnings:
        for warning in warnings:
            st.warning(warning)
    else:
        st.success("Явных предупреждений по товару нет")


def safe_chart_divide(numerator: object, denominator: object) -> float | None:
    if pd.isna(numerator) or pd.isna(denominator):
        return None
    denominator_value = float(denominator)
    if denominator_value == 0:
        return None
    return float(numerator) / denominator_value


def format_wb_conversion_type_label(value: object) -> str:
    if pd.isna(value) or value in (None, ""):
        return "—"
    if str(value) == "UNKNOWN_CODE_64":
        return UNKNOWN_WB_TYPE_LABEL
    return str(value)


def build_chart_product_options(
    filtered: pd.DataFrame,
    *,
    ads_only: bool,
) -> tuple[list[str], dict[str, dict[str, object]]]:
    if filtered.empty:
        return [], {}

    source_df = filtered.copy()
    if ads_only:
        ad_activity_columns = [
            column
            for column in (
                "ad_campaign_spend_total",
                "ad_atbs_total",
                "ad_orders_total",
                "ad_views_total",
                "ad_clicks_total",
            )
            if column in source_df.columns
        ]
        if ad_activity_columns:
            ad_activity_mask = pd.Series(False, index=source_df.index)
            for column in ad_activity_columns:
                ad_activity_mask |= pd.to_numeric(source_df[column], errors="coerce").fillna(0).gt(0)
            active_nm_ids = source_df.loc[ad_activity_mask, "nm_id"].dropna().unique().tolist()
            source_df = source_df[source_df["nm_id"].isin(active_nm_ids)]

    if source_df.empty:
        return [], {}

    sort_columns = [
        column for column in ["supplier_article", "nm_id", "subject", "title"] if column in source_df.columns
    ]
    product_rows = source_df.sort_values(sort_columns, na_position="last").drop_duplicates(subset=["nm_id"]).copy()
    option_map: dict[str, dict[str, object]] = {}
    options: list[str] = []
    for _, row in product_rows.iterrows():
        label = f"{fmt_text(row.get('supplier_article'))} | {fmt_text(row.get('nm_id'))} | {fmt_text(row.get('subject'))}"
        option_map[label] = {"nm_id": int(row["nm_id"])}
        options.append(label)
    return options, option_map


@st.cache_data(show_spinner=False)
def load_product_bands() -> pd.DataFrame:
    columns = ["band_name", "band_type", "item_label", "nm_id"]
    if not PRODUCT_BANDS_PATH.exists():
        return pd.DataFrame(columns=columns)

    band_df = pd.read_csv(PRODUCT_BANDS_PATH)
    for column in columns:
        if column not in band_df.columns:
            band_df[column] = pd.NA
    band_df = band_df[columns].copy()
    band_df["nm_id"] = pd.to_numeric(band_df["nm_id"], errors="coerce")
    band_df = band_df.dropna(subset=["band_name", "nm_id"]).copy()
    band_df["nm_id"] = band_df["nm_id"].astype(int)
    return band_df.drop_duplicates(subset=["nm_id"], keep="first")


def apply_product_bands(filtered: pd.DataFrame) -> pd.DataFrame:
    enriched = filtered.copy()
    if enriched.empty or "nm_id" not in enriched.columns:
        if "band_name" not in enriched.columns:
            enriched["band_name"] = pd.NA
        return enriched

    band_df = load_product_bands()
    if "band_name" in enriched.columns:
        enriched = enriched.drop(columns=["band_name"])
    enriched["nm_id"] = pd.to_numeric(enriched["nm_id"], errors="coerce")
    if band_df.empty:
        enriched["band_name"] = pd.NA
        return enriched
    return enriched.merge(band_df[["nm_id", "band_name"]], on="nm_id", how="left")


def build_group_summary_table(
    filtered: pd.DataFrame,
    *,
    group_column: str,
    group_label: str,
    reference_date: date | None = None,
    include_products: bool = False,
    spend_label: str = "Расход",
    breach_label: str = "Флаг превышения",
) -> pd.DataFrame:
    if filtered.empty or group_column not in filtered.columns:
        return pd.DataFrame()

    source_df = filtered.dropna(subset=[group_column]).copy()
    if source_df.empty:
        return pd.DataFrame()

    product_counts = pd.DataFrame()
    if include_products and "nm_id" in source_df.columns:
        product_counts = (
            source_df.groupby(group_column, as_index=False)["nm_id"]
            .nunique()
            .rename(columns={"nm_id": "Товаров"})
        )

    if "report_date" not in source_df.columns:
        metric_columns = [
            column
            for column in ("cart_count", "ad_atbs_total", "ad_campaign_spend_total", "ad_orders_total")
            if column in source_df.columns
        ]
        if not metric_columns:
            return pd.DataFrame()
        grouped = source_df.groupby(group_column, as_index=False)[metric_columns].sum(min_count=1)
    else:
        cutoffs = get_chart_metric_cutoffs(reference_date)
        source_df["report_date"] = pd.to_datetime(source_df["report_date"], errors="coerce").dt.date
        total_df = source_df[source_df["report_date"].le(cutoffs["total_metrics_cutoff"])].copy()
        confirmed_df = source_df[source_df["report_date"].le(cutoffs["ad_attribution_cutoff"])].copy()

        total_columns = [
            column for column in ("cart_count", "ad_campaign_spend_total") if column in total_df.columns
        ]
        confirmed_columns = [
            column for column in ("ad_atbs_total", "ad_orders_total", "ad_campaign_spend_total") if column in confirmed_df.columns
        ]
        grouped = pd.DataFrame({group_column: sorted(source_df[group_column].dropna().astype(str).unique().tolist())})
        if total_columns:
            total_grouped = total_df.groupby(group_column, as_index=False)[total_columns].sum(min_count=1)
            grouped = grouped.merge(total_grouped, on=group_column, how="left")
        if confirmed_columns:
            confirmed_grouped = confirmed_df.groupby(group_column, as_index=False)[confirmed_columns].sum(min_count=1)
            if "ad_campaign_spend_total" in confirmed_grouped.columns:
                confirmed_grouped = confirmed_grouped.rename(
                    columns={"ad_campaign_spend_total": "ad_campaign_spend_total_confirmed"}
                )
            grouped = grouped.merge(confirmed_grouped, on=group_column, how="left")

    if grouped.empty:
        return pd.DataFrame()

    if not product_counts.empty:
        grouped = grouped.merge(product_counts, on=group_column, how="left")

    spend_for_ad_metrics = (
        "ad_campaign_spend_total_confirmed" if "ad_campaign_spend_total_confirmed" in grouped.columns else "ad_campaign_spend_total"
    )
    grouped["Стоимость корзины РК"] = grouped.apply(
        lambda row: safe_chart_divide(row.get(spend_for_ad_metrics), row.get("ad_atbs_total")),
        axis=1,
    )
    grouped["CPO РК"] = grouped.apply(
        lambda row: safe_chart_divide(row.get(spend_for_ad_metrics), row.get("ad_orders_total")),
        axis=1,
    )
    grouped[breach_label] = grouped.apply(
        lambda row: "Да"
        if (
            (not pd.isna(row.get("Стоимость корзины РК")) and float(row.get("Стоимость корзины РК")) > CHART_THRESHOLD_CART_COST)
            or (not pd.isna(row.get("CPO РК")) and float(row.get("CPO РК")) > CHART_THRESHOLD_CPO)
        )
        else "—",
        axis=1,
    )

    grouped = grouped.rename(
        columns={
            group_column: group_label,
            "cart_count": "Итоговые корзины",
            "ad_atbs_total": "Корзины РК",
            "ad_campaign_spend_total": spend_label,
        }
    )
    result_columns = [group_label]
    if include_products:
        result_columns.append("Товаров")
    result_columns.extend(
        [
            "Итоговые корзины",
            "Корзины РК",
            spend_label,
            "Стоимость корзины РК",
            "CPO РК",
            breach_label,
        ]
    )
    return grouped[result_columns].sort_values(
        ["Корзины РК", "Итоговые корзины"],
        ascending=[False, False],
        na_position="last",
    )


def build_category_summary_table(
    filtered: pd.DataFrame,
    *,
    reference_date: date | None = None,
) -> pd.DataFrame:
    return build_group_summary_table(
        filtered,
        group_column="subject",
        group_label="Категория",
        reference_date=reference_date,
        spend_label="Расход",
        breach_label="Флаг превышения",
    )


def build_band_summary_table(
    filtered: pd.DataFrame,
    *,
    reference_date: date | None = None,
) -> pd.DataFrame:
    return build_group_summary_table(
        filtered,
        group_column="band_name",
        group_label="Банда",
        reference_date=reference_date,
        include_products=True,
        spend_label="Расход РК",
        breach_label="Превышения",
    )


def build_chart_scope_rows(
    filtered: pd.DataFrame,
    aggregation_level: str,
    selected_product_label: str | None,
    option_map: dict[str, dict[str, object]],
) -> tuple[pd.DataFrame, dict[str, object]]:
    if aggregation_level == "Артикул" and selected_product_label:
        product_rows = get_selected_product_rows(filtered, selected_product_label, option_map).copy()
        first_row = product_rows.iloc[0] if not product_rows.empty else pd.Series(dtype=object)
        context = {
            "scope": aggregation_level,
            "supplier_article": first_row.get("supplier_article"),
            "nm_id": first_row.get("nm_id"),
            "title": first_row.get("title"),
        }
        return product_rows, context

    context = {
        "scope": "Кабинет",
        "supplier_article": "Все товары",
        "nm_id": None,
        "title": "Сумма по выбранным товарам",
    }
    return filtered.copy(), context


def get_chart_metric_cutoffs(reference_date: date | None = None) -> dict[str, date]:
    today = reference_date or datetime.now().date()
    return {
        "total_metrics_cutoff": today - timedelta(days=1),
        "ad_spend_cutoff": today - timedelta(days=1),
        "ad_attribution_cutoff": today - timedelta(days=2),
    }


def sum_chart_metric(
    chart_df: pd.DataFrame,
    column: str,
    mask: pd.Series | None = None,
) -> float | None:
    if column not in chart_df.columns:
        return None
    series = pd.to_numeric(chart_df[column], errors="coerce")
    if mask is not None:
        series = series[mask]
    return series.sum(min_count=1)


def build_chart_period_summary(
    chart_df: pd.DataFrame,
    *,
    reference_date: date | None = None,
) -> dict[str, object]:
    if chart_df.empty or "report_date" not in chart_df.columns:
        return {
            "total_carts": None,
            "ad_carts": None,
            "total_orders": None,
            "ad_orders": None,
            "ad_spend_total": None,
            "ad_spend_confirmed": None,
            "total_cart_cost": None,
            "ad_cart_cost": None,
            "total_cpo": None,
            "ad_cpo": None,
            "has_lagged_ad_attribution": False,
        }

    report_dates = pd.to_datetime(chart_df["report_date"], errors="coerce").dt.date
    cutoffs = get_chart_metric_cutoffs(reference_date)
    total_mask = report_dates.notna() & report_dates.le(cutoffs["total_metrics_cutoff"])
    ad_spend_mask = report_dates.notna() & report_dates.le(cutoffs["ad_spend_cutoff"])
    ad_attribution_mask = report_dates.notna() & report_dates.le(cutoffs["ad_attribution_cutoff"])

    total_carts = sum_chart_metric(chart_df, "cart_count", total_mask)
    total_orders = sum_chart_metric(chart_df, "order_count", total_mask)
    ad_spend_total = sum_chart_metric(chart_df, "ad_campaign_spend_total", ad_spend_mask)
    ad_carts = sum_chart_metric(chart_df, "ad_atbs_total_confirmed", ad_attribution_mask)
    ad_orders = sum_chart_metric(chart_df, "ad_orders_total_confirmed", ad_attribution_mask)
    ad_spend_confirmed = sum_chart_metric(chart_df, "ad_spend_confirmed", ad_attribution_mask)

    return {
        "total_carts": total_carts,
        "ad_carts": ad_carts,
        "total_orders": total_orders,
        "ad_orders": ad_orders,
        "ad_spend_total": ad_spend_total,
        "ad_spend_confirmed": ad_spend_confirmed,
        "total_cart_cost": safe_chart_divide(ad_spend_total, total_carts),
        "ad_cart_cost": safe_chart_divide(ad_spend_confirmed, ad_carts),
        "total_cpo": safe_chart_divide(ad_spend_total, total_orders),
        "ad_cpo": safe_chart_divide(ad_spend_confirmed, ad_orders),
        "has_lagged_ad_attribution": bool((report_dates > cutoffs["ad_attribution_cutoff"]).any()),
    }


def build_chart_metrics_by_date(
    scope_rows: pd.DataFrame,
    *,
    reference_date: date | None = None,
) -> pd.DataFrame:
    if scope_rows.empty:
        return pd.DataFrame()

    aggregation_columns = [
        "cart_count",
        "ad_atbs_total",
        "order_count",
        "ad_orders_total",
        "ad_campaign_spend_total",
    ]
    available_columns = [column for column in aggregation_columns if column in scope_rows.columns]
    if not available_columns:
        return pd.DataFrame()

    grouped = (
        scope_rows.dropna(subset=["report_date"])
        .groupby("report_date", as_index=False)[available_columns]
        .sum(min_count=1)
        .sort_values("report_date")
    )
    grouped["report_date"] = pd.to_datetime(grouped["report_date"], errors="coerce").dt.date
    cutoffs = get_chart_metric_cutoffs(reference_date)
    lagged_mask = grouped["report_date"].gt(cutoffs["ad_attribution_cutoff"])
    grouped["ad_attribution_status"] = lagged_mask.map({True: "AD_ATTRIBUTION_LAGGED", False: "OK"})
    if "ad_atbs_total" in grouped.columns:
        grouped["ad_atbs_total_confirmed"] = grouped["ad_atbs_total"].where(~lagged_mask)
    if "ad_orders_total" in grouped.columns:
        grouped["ad_orders_total_confirmed"] = grouped["ad_orders_total"].where(~lagged_mask)
    if "ad_campaign_spend_total" in grouped.columns:
        grouped["ad_spend_confirmed"] = grouped["ad_campaign_spend_total"].where(~lagged_mask)
    grouped["total_cart_cost"] = grouped.apply(
        lambda row: safe_chart_divide(row.get("ad_campaign_spend_total"), row.get("cart_count")),
        axis=1,
    )
    grouped["ad_cart_cost"] = grouped.apply(
        lambda row: safe_chart_divide(row.get("ad_spend_confirmed"), row.get("ad_atbs_total_confirmed")),
        axis=1,
    )
    grouped["total_cpo"] = grouped.apply(
        lambda row: safe_chart_divide(row.get("ad_campaign_spend_total"), row.get("order_count")),
        axis=1,
    )
    grouped["ad_cpo"] = grouped.apply(
        lambda row: safe_chart_divide(row.get("ad_spend_confirmed"), row.get("ad_orders_total_confirmed")),
        axis=1,
    )
    return grouped


def build_chart_series_dataframe(
    chart_df: pd.DataFrame,
    series_map: dict[str, str],
    threshold: float | None = None,
) -> pd.DataFrame:
    safe_frames: list[pd.DataFrame] = []
    for source_column, label in series_map.items():
        if source_column not in chart_df.columns:
            continue
        frame = chart_df[["report_date", source_column]].rename(columns={source_column: "value"}).copy()
        frame["series"] = label
        frame = frame[frame["value"].notna()]
        if frame is None or frame.empty:
            continue
        safe_frame = frame.copy()
        safe_frame.attrs = {}
        safe_frames.append(safe_frame)

    if not safe_frames:
        return pd.DataFrame(columns=["report_date", "value", "series", "is_alert"])

    combined = pd.concat(safe_frames, ignore_index=True)
    combined.attrs = {}
    combined["report_date"] = pd.to_datetime(combined["report_date"], errors="coerce").dt.date
    combined["is_alert"] = False if threshold is None else combined["value"] > threshold
    return combined


def build_user_friendly_chart(
    *,
    chart_df: pd.DataFrame,
    series_map: dict[str, str],
    y_title: str,
    tooltip_value_title: str,
    value_format: str,
    line_colors: list[str],
    threshold: float | None = None,
    threshold_label: str | None = None,
) -> alt.Chart | None:
    series_df = build_chart_series_dataframe(chart_df, series_map, threshold=threshold)
    if series_df.empty:
        return None

    base = alt.Chart(series_df).encode(
        x=alt.X(
            "report_date:T",
            title="Дата",
            axis=alt.Axis(format="%d.%m", labelAngle=0, tickCount=min(max(len(chart_df), 2), 10)),
        ),
        y=alt.Y(
            "value:Q",
            title=y_title,
            axis=alt.Axis(format=value_format),
            scale=alt.Scale(zero=True, nice=True),
        ),
        color=alt.Color(
            "series:N",
            title="Показатель",
            scale=alt.Scale(domain=list(series_map.values()), range=line_colors[: len(series_map)]),
        ),
        tooltip=[
            alt.Tooltip("report_date:T", title="Дата", format="%d.%m.%Y"),
            alt.Tooltip("series:N", title="Показатель"),
            alt.Tooltip("value:Q", title=tooltip_value_title, format=value_format),
        ],
    )

    layers: list[alt.Chart] = [
        base.mark_line(strokeWidth=3),
        base.mark_circle(size=55),
    ]

    if threshold is not None and threshold_label:
        threshold_df = pd.DataFrame({"threshold": [threshold], "label": [threshold_label]})
        layers.append(
            alt.Chart(threshold_df).mark_rule(color="#dc2626", strokeDash=[6, 4]).encode(y="threshold:Q")
        )
        layers.append(
            alt.Chart(threshold_df)
            .mark_text(color="#dc2626", align="left", dx=8, dy=-6, fontSize=12)
            .encode(x=alt.value(8), y="threshold:Q", text="label:N")
        )
        alert_df = series_df[series_df["is_alert"]].copy()
        if not alert_df.empty:
            layers.append(
                alt.Chart(alert_df)
                .mark_circle(size=90, color="#dc2626")
                .encode(
                    x=alt.X("report_date:T", title="Дата", axis=alt.Axis(format="%d.%m", labelAngle=0)),
                    y=alt.Y("value:Q", title=y_title, axis=alt.Axis(format=value_format)),
                    tooltip=[
                        alt.Tooltip("report_date:T", title="Дата", format="%d.%m.%Y"),
                        alt.Tooltip("series:N", title="Показатель"),
                        alt.Tooltip("value:Q", title=tooltip_value_title, format=value_format),
                    ],
                )
            )

    return alt.layer(*layers).resolve_scale(color="shared").properties(height=320)


def format_chart_kpi_value(value: float | None, digits: int = 1, suffix: str = "") -> str:
    if value is None or pd.isna(value):
        return "—"
    if digits == 0:
        return f"{int(round(float(value))):,}".replace(",", " ") + suffix
    return f"{float(value):,.{digits}f}".replace(",", " ") + suffix


def render_chart_kpi_card(
    *,
    label: str,
    value: float | None,
    digits: int,
    suffix: str = "",
    threshold: float | None = None,
) -> None:
    is_alert = threshold is not None and value is not None and not pd.isna(value) and float(value) > threshold
    background = "#fff1f2" if is_alert else "#f8fafc"
    border = "#ef4444" if is_alert else "#dbe4ee"
    caption = f"Порог превышен: {threshold:g}{suffix}" if is_alert and threshold is not None else "&nbsp;"
    st.markdown(
        f"""
        <div style="border:1px solid {border}; background:{background}; border-radius:12px; padding:14px; min-height:120px;">
            <div style="font-size:13px; color:#475569; margin-bottom:8px;">{label}</div>
            <div style="font-size:28px; font-weight:700; color:#0f172a;">{format_chart_kpi_value(value, digits, suffix)}</div>
            <div style="font-size:12px; color:#b91c1c; margin-top:8px;">{caption}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_threshold_breaches_table(chart_df: pd.DataFrame, context: dict[str, object]) -> pd.DataFrame:
    if chart_df.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    metrics = [
        ("total_cart_cost", "Стоимость корзины ИТОГО", CHART_THRESHOLD_CART_COST),
        ("ad_cart_cost", "Стоимость корзины РК", CHART_THRESHOLD_CART_COST),
        ("total_cpo", "CPO ИТОГО", CHART_THRESHOLD_CPO),
        ("ad_cpo", "CPO РК", CHART_THRESHOLD_CPO),
    ]
    for _, row in chart_df.iterrows():
        for field_name, label, threshold in metrics:
            value = row.get(field_name)
            if pd.isna(value) or float(value) <= threshold:
                continue
            rows.append(
                {
                    "Дата": row.get("report_date"),
                    "Артикул продавца": context.get("supplier_article") or "Все товары",
                    "Артикул WB": context.get("nm_id"),
                    "Название товара": context.get("title") or "Сумма по выбранным товарам",
                    "Показатель": label,
                    "Значение": round(float(value), 1),
                    "Порог": threshold,
                }
            )
    return pd.DataFrame(rows)


def render_charts_tab(
    filtered: pd.DataFrame,
    preselected_product_label: str | None,
    option_map: dict[str, dict[str, object]],
) -> None:
    st.subheader("Корзины и эффективность")
    st.caption("Динамика корзин, стоимости корзины и CPO по выбранному периоду.")

    aggregation_level = st.radio("Уровень агрегации", options=["Кабинет", "Артикул"], horizontal=True)
    selected_product_label = preselected_product_label
    if aggregation_level == "Артикул":
        product_options = list(option_map.keys())
        if not product_options:
            st.info("Нет данных за выбранный период.")
            return
        default_index = product_options.index(preselected_product_label) if preselected_product_label in product_options else 0
        selected_product_label = st.selectbox("Артикул", options=product_options, index=default_index)

    scope_rows, context = build_chart_scope_rows(filtered, aggregation_level, selected_product_label, option_map)
    chart_df = build_chart_metrics_by_date(scope_rows)
    if chart_df.empty:
        st.info("Нет данных за выбранный период.")
        return

    st.caption(
        "Важно: рекламные корзины и рекламные заказы могут быть доступны только до позавчера. "
        "Поэтому стоимость корзины РК и CPO РК считаются только по датам с подтверждённой рекламной статистикой. "
        "Итоговые корзины, итоговые заказы и расходы могут отображаться за вчера."
    )

    if aggregation_level == "Кабинет":
        st.info("Графики построены по сумме всех товаров, попавших в текущие фильтры периода.")
    else:
        article_caption = f"{fmt_text(context.get('supplier_article'))} | {fmt_text(context.get('nm_id'))} | {fmt_text(context.get('title'))}"
        st.caption(f"Выбранный товар: {article_caption}")

    period_summary = build_chart_period_summary(chart_df)
    total_carts = period_summary["total_carts"]
    ad_carts = period_summary["ad_carts"]
    total_orders = period_summary["total_orders"]
    ad_orders = period_summary["ad_orders"]
    ad_spend = period_summary["ad_spend_total"]
    total_cart_cost = period_summary["total_cart_cost"]
    ad_cart_cost = period_summary["ad_cart_cost"]
    total_cpo = period_summary["total_cpo"]
    ad_cpo = period_summary["ad_cpo"]

    kpi_cols = st.columns(6)
    with kpi_cols[0]:
        render_chart_kpi_card(label="Итоговые корзины", value=total_carts, digits=0)
    with kpi_cols[1]:
        render_chart_kpi_card(label="Корзины РК", value=ad_carts, digits=0)
    with kpi_cols[2]:
        render_chart_kpi_card(
            label="Стоимость корзины ИТОГО",
            value=total_cart_cost,
            digits=1,
            suffix=" руб.",
            threshold=CHART_THRESHOLD_CART_COST,
        )
    with kpi_cols[3]:
        if period_summary["has_lagged_ad_attribution"] and ad_cart_cost is None:
            render_not_applicable_kpi_card(label="Стоимость корзины РК", reason="Корзины РК ещё не доступны")
        else:
            render_chart_kpi_card(
                label="Стоимость корзины РК",
                value=ad_cart_cost,
                digits=1,
                suffix=" руб.",
                threshold=CHART_THRESHOLD_CART_COST,
            )
    with kpi_cols[4]:
        render_chart_kpi_card(
            label="CPO ИТОГО",
            value=total_cpo,
            digits=1,
            suffix=" руб.",
            threshold=CHART_THRESHOLD_CPO,
        )
    with kpi_cols[5]:
        if period_summary["has_lagged_ad_attribution"] and ad_cpo is None:
            render_not_applicable_kpi_card(label="CPO РК", reason="Заказы РК ещё не доступны")
        else:
            render_chart_kpi_card(
                label="CPO РК",
                value=ad_cpo,
                digits=1,
                suffix=" руб.",
                threshold=CHART_THRESHOLD_CPO,
            )

    latest_report_date = chart_df["report_date"].dropna().max() if "report_date" in chart_df.columns else None
    if latest_report_date and latest_report_date > (datetime.now().date() - timedelta(days=2)):
        st.warning("Корзины РК за последние 1–2 дня могут быть неполными.")

    st.markdown("### Динамика корзин")
    st.caption("Итоговые корзины и корзины из рекламы по дням.")
    carts_chart = build_user_friendly_chart(
        chart_df=chart_df,
        series_map={"cart_count": "Итоговые корзины", "ad_atbs_total": "Корзины РК"},
        y_title="Корзины, шт.",
        tooltip_value_title="Значение, шт.",
        value_format=".0f",
        line_colors=["#2563eb", "#f97316"],
    )
    if carts_chart is None:
        st.info("Нет данных за выбранный период.")
    else:
        st.altair_chart(carts_chart, width="stretch")

    st.markdown("### Стоимость корзины")
    st.caption("Сколько рублей рекламного расхода приходится на одну корзину.")
    cart_cost_chart = build_user_friendly_chart(
        chart_df=chart_df,
        series_map={"total_cart_cost": "Стоимость корзины ИТОГО", "ad_cart_cost": "Стоимость корзины РК"},
        y_title="Стоимость, руб.",
        tooltip_value_title="Стоимость, руб.",
        value_format=".1f",
        line_colors=["#0f766e", "#f59e0b"],
        threshold=CHART_THRESHOLD_CART_COST,
        threshold_label="Порог 35 руб.",
    )
    if cart_cost_chart is None:
        st.info("Нет данных за выбранный период.")
    else:
        st.altair_chart(cart_cost_chart, width="stretch")

    st.markdown("### CPO")
    st.caption("Стоимость одного заказа.")
    cpo_chart = build_user_friendly_chart(
        chart_df=chart_df,
        series_map={"total_cpo": "CPO ИТОГО", "ad_cpo": "CPO РК"},
        y_title="CPO, руб.",
        tooltip_value_title="CPO, руб.",
        value_format=".1f",
        line_colors=["#7c3aed", "#ef4444"],
        threshold=CHART_THRESHOLD_CPO,
        threshold_label="Порог 150 руб.",
    )
    if cpo_chart is None:
        st.info("Нет данных за выбранный период.")
    else:
        st.altair_chart(cpo_chart, width="stretch")

    st.markdown("### Превышения порогов")
    breaches_df = build_threshold_breaches_table(chart_df, context)
    if breaches_df.empty:
        st.success("Превышений по выбранному периоду нет.")
    else:
        st.dataframe(
            breaches_df,
            width="stretch",
            hide_index=True,
            column_config={
                "Дата": st.column_config.DateColumn("Дата"),
                "Артикул WB": st.column_config.NumberColumn("Артикул WB", format="%d"),
                "Значение": st.column_config.NumberColumn("Значение", format="%.1f"),
                "Порог": st.column_config.NumberColumn("Порог", format="%.1f"),
            },
        )


def render_not_applicable_kpi_card(*, label: str, reason: str = "Не применяется") -> None:
    st.markdown(
        f"""
        <div style="border:1px solid #dbe4ee; background:#f8fafc; border-radius:12px; padding:14px; min-height:120px;">
            <div style="font-size:13px; color:#475569; margin-bottom:8px;">{label}</div>
            <div style="font-size:24px; font-weight:700; color:#94a3b8;">—</div>
            <div style="font-size:12px; color:#64748b; margin-top:8px;">{reason}</div>
        </div>
        """,
        unsafe_allow_html=True,
    )


def build_chart_scope_rows(
    filtered: pd.DataFrame,
    aggregation_level: str,
    selected_product_label: str | None,
    option_map: dict[str, dict[str, object]],
    *,
    selected_subject: str | None = None,
    selected_band: str | None = None,
    ad_campaign_product_df: pd.DataFrame | None = None,
    selected_conversion_type: str | None = None,
) -> tuple[pd.DataFrame, dict[str, object]]:
    if aggregation_level == CHART_LEVEL_ARTICLE and selected_product_label:
        product_rows = get_selected_product_rows(filtered, selected_product_label, option_map).copy()
        first_row = product_rows.iloc[0] if not product_rows.empty else pd.Series(dtype=object)
        context = {
            "scope": aggregation_level,
            "supplier_article": first_row.get("supplier_article"),
            "nm_id": first_row.get("nm_id"),
            "title": first_row.get("title"),
            "level_value": (
                f"{fmt_text(first_row.get('supplier_article'))} | {fmt_text(first_row.get('nm_id'))} | {fmt_text(first_row.get('subject'))}"
                if not first_row.empty
                else "—"
            ),
        }
        return product_rows, context

    if aggregation_level == CHART_LEVEL_CATEGORY:
        scope_rows = filtered.copy()
        if selected_subject and selected_subject != CHART_ALL_CATEGORIES_LABEL:
            scope_rows = scope_rows[scope_rows["subject"] == selected_subject].copy()
        context = {
            "scope": aggregation_level,
            "supplier_article": "Все товары",
            "nm_id": None,
            "title": "Сумма по выбранным товарам",
            "level_value": selected_subject or CHART_ALL_CATEGORIES_LABEL,
        }
        return scope_rows, context

    if aggregation_level == CHART_LEVEL_BAND:
        scope_rows = filtered.dropna(subset=["band_name"]).copy() if "band_name" in filtered.columns else pd.DataFrame()
        if selected_band and selected_band != CHART_ALL_BANDS_LABEL:
            scope_rows = scope_rows[scope_rows["band_name"] == selected_band].copy()
        context = {
            "scope": aggregation_level,
            "supplier_article": "Все товары",
            "nm_id": None,
            "title": "Сумма по выбранным товарам",
            "level_value": selected_band or CHART_ALL_BANDS_LABEL,
        }
        return scope_rows, context

    if aggregation_level == CHART_LEVEL_CONVERSION:
        scope_rows = ad_campaign_product_df.copy() if ad_campaign_product_df is not None else pd.DataFrame()
        if scope_rows.empty:
            return scope_rows, {
                "scope": aggregation_level,
                "supplier_article": "Все товары",
                "nm_id": None,
                "title": "Рекламная детализация по типу WB",
                "level_value": (
                    format_wb_conversion_type_label(selected_conversion_type)
                    if selected_conversion_type
                    else CHART_ALL_CONVERSION_TYPES_LABEL
                ),
                "technical_level_value": selected_conversion_type,
            }
        visible_dates = set(filtered["report_date"].dropna().tolist()) if "report_date" in filtered.columns else set()
        visible_nm_ids = set(filtered["nm_id"].dropna().astype(int).tolist()) if "nm_id" in filtered.columns else set()
        if visible_dates:
            scope_rows = scope_rows[scope_rows["report_date"].isin(visible_dates)].copy()
        if visible_nm_ids:
            scope_rows = scope_rows[scope_rows["nm_id"].isin(visible_nm_ids)].copy()
        if selected_conversion_type:
            scope_rows = scope_rows[scope_rows["conversion_type"].astype(str) == str(selected_conversion_type)].copy()
        scope_rows = scope_rows.rename(
            columns={
                "campaign_spend": "ad_campaign_spend_total",
                "ad_atbs": "ad_atbs_total",
                "ad_orders": "ad_orders_total",
            }
        )
        context = {
            "scope": aggregation_level,
            "supplier_article": "Все товары",
            "nm_id": None,
            "title": "Рекламная детализация по типу WB",
            "level_value": (
                format_wb_conversion_type_label(selected_conversion_type)
                if selected_conversion_type
                else CHART_ALL_CONVERSION_TYPES_LABEL
            ),
            "technical_level_value": selected_conversion_type,
        }
        return scope_rows, context

    context = {
        "scope": CHART_LEVEL_CABINET,
        "supplier_article": "Все товары",
        "nm_id": None,
        "title": "Сумма по выбранным товарам",
        "level_value": "Все товары",
    }
    return filtered.copy(), context


def build_threshold_breaches_table(
    chart_df: pd.DataFrame,
    context: dict[str, object],
    metrics: list[tuple[str, str, float]] | None = None,
) -> pd.DataFrame:
    if chart_df.empty:
        return pd.DataFrame()

    rows: list[dict[str, object]] = []
    metrics = metrics or [
        ("total_cart_cost", "Стоимость корзины ИТОГО", CHART_THRESHOLD_CART_COST),
        ("ad_cart_cost", "Стоимость корзины РК", CHART_THRESHOLD_CART_COST),
        ("total_cpo", "CPO ИТОГО", CHART_THRESHOLD_CPO),
        ("ad_cpo", "CPO РК", CHART_THRESHOLD_CPO),
    ]
    for _, row in chart_df.iterrows():
        for field_name, label, threshold in metrics:
            value = row.get(field_name)
            if pd.isna(value) or float(value) <= threshold:
                continue
            rows.append(
                {
                    "Дата": row.get("report_date"),
                    "Уровень": context.get("scope") or CHART_LEVEL_CABINET,
                    "Значение уровня": context.get("level_value") or "Все товары",
                    "Артикул продавца": context.get("supplier_article") or "Все товары",
                    "Артикул WB": context.get("nm_id"),
                    "Название товара": context.get("title") or "Сумма по выбранным товарам",
                    "Показатель": label,
                    "Значение": round(float(value), 1),
                    "Порог": threshold,
                    "Превышение": "Да",
                }
            )
    return pd.DataFrame(rows)


def render_charts_tab(
    filtered: pd.DataFrame,
    preselected_product_label: str | None,
    option_map: dict[str, dict[str, object]],
    ad_campaign_product_df: pd.DataFrame | None = None,
) -> None:
    st.subheader("Корзины и эффективность")
    st.caption("Динамика корзин, стоимости корзины и CPO по выбранному периоду.")
    st.warning(
        "Важно: рекламные корзины и рекламные заказы могут быть доступны только до позавчера. "
        "Поэтому стоимость корзины РК и CPO РК считаются только по датам с подтверждённой рекламной статистикой. "
        "Итоговые корзины, итоговые заказы и расходы могут отображаться за вчера."
    )

    aggregation_level = st.radio("Уровень агрегации", options=CHART_AGGREGATION_LEVELS, horizontal=True)
    selected_product_label = preselected_product_label
    selected_subject: str | None = None
    selected_band: str | None = None
    selected_conversion_type: str | None = None
    chart_source_df = filtered

    if aggregation_level == CHART_LEVEL_CATEGORY:
        category_summary_df = build_category_summary_table(filtered)
        category_options = [CHART_ALL_CATEGORIES_LABEL]
        if not category_summary_df.empty:
            category_options.extend(category_summary_df["Категория"].astype(str).tolist())
        else:
            category_options.extend(sorted(filtered["subject"].dropna().astype(str).unique().tolist()))
        selected_subject = st.selectbox("Категория / предмет", options=category_options, index=0)
        if not category_summary_df.empty:
            st.caption("Сводка по категориям за выбранный период.")
            st.dataframe(
                category_summary_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "Итоговые корзины": st.column_config.NumberColumn("Итоговые корзины", format="%.0f"),
                    "Корзины РК": st.column_config.NumberColumn("Корзины РК", format="%.0f"),
                    "Расход": st.column_config.NumberColumn("Расход", format="%.2f"),
                    "Стоимость корзины РК": st.column_config.NumberColumn("Стоимость корзины РК", format="%.1f"),
                    "CPO РК": st.column_config.NumberColumn("CPO РК", format="%.1f"),
                },
            )
    elif aggregation_level == CHART_LEVEL_BAND:
        chart_source_df = apply_product_bands(filtered)
        band_summary_df = build_band_summary_table(chart_source_df)
        if chart_source_df.get("band_name") is None or chart_source_df["band_name"].dropna().empty:
            st.info("За выбранный период нет товаров из справочника банд.")
            return
        band_options = [CHART_ALL_BANDS_LABEL]
        if not band_summary_df.empty:
            band_options.extend(band_summary_df["Банда"].astype(str).tolist())
        else:
            band_options.extend(sorted(chart_source_df["band_name"].dropna().astype(str).unique().tolist()))
        selected_band = st.selectbox("Банда", options=band_options, index=0)
        if not band_summary_df.empty:
            st.caption("Сводка по бандам за выбранный период.")
            st.dataframe(
                band_summary_df,
                width="stretch",
                hide_index=True,
                column_config={
                    "Товаров": st.column_config.NumberColumn("Товаров", format="%.0f"),
                    "Итоговые корзины": st.column_config.NumberColumn("Итоговые корзины", format="%.0f"),
                    "Корзины РК": st.column_config.NumberColumn("Корзины РК", format="%.0f"),
                    "Расход РК": st.column_config.NumberColumn("Расход РК", format="%.2f"),
                    "Стоимость корзины РК": st.column_config.NumberColumn("Стоимость корзины РК", format="%.1f"),
                    "CPO РК": st.column_config.NumberColumn("CPO РК", format="%.1f"),
                },
            )
    elif aggregation_level == CHART_LEVEL_ARTICLE:
        show_only_ad_active_products = st.checkbox(
            "Показывать только артикулы с рекламной активностью",
            value=True,
        )
        product_options, chart_option_map = build_chart_product_options(filtered, ads_only=show_only_ad_active_products)
        if not product_options:
            if show_only_ad_active_products:
                st.info("За выбранный период нет артикулов с рекламной активностью.")
            else:
                st.info("Нет данных за выбранный период.")
            return
        preselected_nm_id = option_map.get(preselected_product_label or "", {}).get("nm_id")
        default_index = 0
        if preselected_nm_id is not None:
            for index, label in enumerate(product_options):
                if chart_option_map[label]["nm_id"] == preselected_nm_id:
                    default_index = index
                    break
        selected_product_label = st.selectbox("Артикул", options=product_options, index=default_index)
        option_map = chart_option_map
    elif aggregation_level == CHART_LEVEL_CONVERSION:
        visible_dates = set(filtered["report_date"].dropna().tolist()) if "report_date" in filtered.columns else set()
        visible_nm_ids = set(filtered["nm_id"].dropna().astype(int).tolist()) if "nm_id" in filtered.columns else set()
        conversion_scope = ad_campaign_product_df.copy() if ad_campaign_product_df is not None else pd.DataFrame()
        if visible_dates:
            conversion_scope = conversion_scope[conversion_scope["report_date"].isin(visible_dates)]
        if visible_nm_ids:
            conversion_scope = conversion_scope[conversion_scope["nm_id"].isin(visible_nm_ids)]
        conversion_values = sorted(
            value
            for value in conversion_scope.get("conversion_type", pd.Series(dtype=object)).dropna().astype(str).unique().tolist()
        )
        if not conversion_values:
            st.info("За выбранный период нет рекламных данных по типам WB / конверсии.")
            return
        conversion_display_map = {
            format_wb_conversion_type_label(value): value
            for value in conversion_values
        }
        conversion_display_options = [CHART_ALL_CONVERSION_TYPES_LABEL] + list(conversion_display_map.keys())
        selected_conversion_display = st.selectbox(
            "Тип WB / конверсии",
            options=conversion_display_options,
            index=0,
        )
        selected_conversion_type = conversion_display_map.get(selected_conversion_display)
        if selected_conversion_type == "UNKNOWN_CODE_64":
            st.caption(UNKNOWN_WB_TYPE_HELP_TEXT)

    scope_rows, context = build_chart_scope_rows(
        chart_source_df,
        aggregation_level,
        selected_product_label,
        option_map,
        selected_subject=selected_subject,
        selected_band=selected_band,
        ad_campaign_product_df=ad_campaign_product_df,
        selected_conversion_type=selected_conversion_type,
    )
    chart_df = build_chart_metrics_by_date(scope_rows)
    if chart_df.empty:
        st.info("Нет данных за выбранный период.")
        return

    if aggregation_level == CHART_LEVEL_CABINET:
        st.info("Графики построены по сумме всех товаров, попавших в текущие фильтры периода.")
    elif aggregation_level == CHART_LEVEL_CATEGORY:
        st.caption(f"Выбранная категория: {context.get('level_value')}")
    elif aggregation_level == CHART_LEVEL_BAND:
        st.caption(f"Выбранная банда: {context.get('level_value')}")
    elif aggregation_level == CHART_LEVEL_CONVERSION:
        st.caption(f"Выбранный тип WB / конверсии: {context.get('level_value')}")
    else:
        article_caption = f"{fmt_text(context.get('supplier_article'))} | {fmt_text(context.get('nm_id'))} | {fmt_text(context.get('title'))}"
        st.caption(f"Выбранный товар: {article_caption}")

    period_summary = build_chart_period_summary(chart_df)
    total_carts = period_summary["total_carts"]
    ad_carts = period_summary["ad_carts"]
    total_orders = period_summary["total_orders"]
    ad_orders = period_summary["ad_orders"]
    ad_spend = period_summary["ad_spend_total"]
    total_cart_cost = period_summary["total_cart_cost"]
    ad_cart_cost = period_summary["ad_cart_cost"]
    total_cpo = period_summary["total_cpo"]
    ad_cpo = period_summary["ad_cpo"]

    is_conversion_level = aggregation_level == CHART_LEVEL_CONVERSION
    kpi_cols = st.columns(6)
    with kpi_cols[0]:
        if is_conversion_level:
            render_not_applicable_kpi_card(label="Итоговые корзины", reason="Метрика не применяется на уровне типа WB")
        else:
            render_chart_kpi_card(label="Итоговые корзины", value=total_carts, digits=0)
    with kpi_cols[1]:
        render_chart_kpi_card(label="Корзины РК", value=ad_carts, digits=0)
    with kpi_cols[2]:
        if is_conversion_level:
            render_not_applicable_kpi_card(label="Стоимость корзины ИТОГО", reason="Метрика не применяется на уровне типа WB")
        else:
            render_chart_kpi_card(
                label="Стоимость корзины ИТОГО",
                value=total_cart_cost,
                digits=1,
                suffix=" руб.",
                threshold=CHART_THRESHOLD_CART_COST,
            )
    with kpi_cols[3]:
        if period_summary["has_lagged_ad_attribution"] and ad_cart_cost is None:
            render_not_applicable_kpi_card(label="Стоимость корзины РК", reason="Корзины РК ещё не доступны")
        else:
            render_chart_kpi_card(
                label="Стоимость корзины РК",
                value=ad_cart_cost,
                digits=1,
                suffix=" руб.",
                threshold=CHART_THRESHOLD_CART_COST,
            )
    with kpi_cols[4]:
        if is_conversion_level:
            render_not_applicable_kpi_card(label="CPO ИТОГО", reason="Метрика не применяется на уровне типа WB")
        else:
            render_chart_kpi_card(
                label="CPO ИТОГО",
                value=total_cpo,
                digits=1,
                suffix=" руб.",
                threshold=CHART_THRESHOLD_CPO,
            )
    with kpi_cols[5]:
        if period_summary["has_lagged_ad_attribution"] and ad_cpo is None:
            render_not_applicable_kpi_card(label="CPO РК", reason="Заказы РК ещё не доступны")
        else:
            render_chart_kpi_card(
                label="CPO РК",
                value=ad_cpo,
                digits=1,
                suffix=" руб.",
                threshold=CHART_THRESHOLD_CPO,
            )
    st.caption(f"Расход РК за период: {format_chart_kpi_value(ad_spend, digits=2, suffix=' руб.')}")

    if period_summary["has_lagged_ad_attribution"]:
        st.caption("Статус рекламной атрибуции: AD_ATTRIBUTION_LAGGED")

    st.markdown("### Динамика корзин")
    st.caption(
        "Итоговые корзины и корзины из рекламы по дням."
        if not is_conversion_level
        else "Корзины РК по выбранному типу WB / конверсии."
    )
    carts_chart = build_user_friendly_chart(
        chart_df=chart_df,
        series_map=(
            {"cart_count": "Итоговые корзины", "ad_atbs_total_confirmed": "Корзины РК"}
            if not is_conversion_level
            else {"ad_atbs_total_confirmed": "Корзины РК"}
        ),
        y_title="Корзины, шт.",
        tooltip_value_title="Значение, шт.",
        value_format=".0f",
        line_colors=["#2563eb", "#f97316"],
    )
    if carts_chart is None:
        st.info("Нет данных за выбранный период.")
    else:
        st.altair_chart(carts_chart, width="stretch")

    st.markdown("### Стоимость корзины")
    st.caption(
        "Сколько рублей рекламного расхода приходится на одну корзину."
        if not is_conversion_level
        else "Сколько рублей рекламного расхода приходится на одну рекламную корзину."
    )
    cart_cost_chart = build_user_friendly_chart(
        chart_df=chart_df,
        series_map=(
            {"total_cart_cost": "Стоимость корзины ИТОГО", "ad_cart_cost": "Стоимость корзины РК"}
            if not is_conversion_level
            else {"ad_cart_cost": "Стоимость корзины РК"}
        ),
        y_title="Стоимость, руб.",
        tooltip_value_title="Стоимость, руб.",
        value_format=".1f",
        line_colors=["#0f766e", "#f59e0b"],
        threshold=CHART_THRESHOLD_CART_COST,
        threshold_label="Порог 35 руб.",
    )
    if cart_cost_chart is None:
        st.info("Нет данных за выбранный период.")
    else:
        st.altair_chart(cart_cost_chart, width="stretch")

    st.markdown("### CPO")
    st.caption(
        "Стоимость одного заказа."
        if not is_conversion_level
        else "Стоимость одного рекламного заказа."
    )
    cpo_chart = build_user_friendly_chart(
        chart_df=chart_df,
        series_map=(
            {"total_cpo": "CPO ИТОГО", "ad_cpo": "CPO РК"}
            if not is_conversion_level
            else {"ad_cpo": "CPO РК"}
        ),
        y_title="CPO, руб.",
        tooltip_value_title="CPO, руб.",
        value_format=".1f",
        line_colors=["#7c3aed", "#ef4444"],
        threshold=CHART_THRESHOLD_CPO,
        threshold_label="Порог 150 руб.",
    )
    if cpo_chart is None:
        st.info("Нет данных за выбранный период.")
    else:
        st.altair_chart(cpo_chart, width="stretch")

    st.markdown("### Превышения порогов")
    breaches_metrics = (
        [
            ("ad_cart_cost", "Стоимость корзины РК", CHART_THRESHOLD_CART_COST),
            ("ad_cpo", "CPO РК", CHART_THRESHOLD_CPO),
        ]
        if is_conversion_level
        else None
    )
    breaches_df = build_threshold_breaches_table(chart_df, context, metrics=breaches_metrics)
    if breaches_df.empty:
        st.success("Превышений по выбранному периоду нет.")
    else:
        st.dataframe(
            breaches_df,
            width="stretch",
            hide_index=True,
            column_config={
                "Дата": st.column_config.DateColumn("Дата"),
                "Артикул WB": st.column_config.NumberColumn("Артикул WB", format="%d"),
                "Значение": st.column_config.NumberColumn("Значение", format="%.1f"),
                "Порог": st.column_config.NumberColumn("Порог", format="%.1f"),
            },
        )


def render_sources_tab(latest_row: pd.Series) -> None:
    st.subheader("Статусы источников")
    st.markdown(
        """
        - `FILE_IMPORT_PENDING` = ждём файл
        - `MANUAL_PENDING` = ждём ручной ввод
        - `NOT_INCLUDED` = не входит в v1
        - `NO_DATA` = по товару нет данных в текущих источниках
        """
    )
    source_df = pd.DataFrame(
        [
            {"Источник": "Точка входа", "Статус": fmt_text(latest_row.get("entry_point_status"))},
            {"Источник": "География", "Статус": fmt_text(latest_row.get("orders_geography_status"))},
            {"Источник": "ВБро", "Статус": fmt_text(latest_row.get("vbro_status"))},
            {"Источник": "Сравнение карточек", "Статус": fmt_text(latest_row.get("card_comparison_status"))},
            {"Источник": "Organic cart share", "Статус": fmt_text(latest_row.get("organic_cart_share_status"))},
            {"Источник": "Data quality", "Статус": fmt_text(latest_row.get("data_quality_status"))},
        ]
    )
    st.dataframe(source_df, width="stretch", hide_index=True)


def render_import_block(
    *,
    title: str,
    report_name: str,
    importer_func,
    state_key: str,
) -> None:
    st.markdown(f"### {title}")
    uploaded_file = st.file_uploader(
        f"{report_name}: XLSX",
        type=["xlsx"],
        key=f"{state_key}_file",
    )
    manual_date_text = st.text_input(
        "Дата отчёта",
        value="",
        placeholder="YYYY-MM-DD",
        key=f"{state_key}_date",
    )
    use_file_date = st.checkbox(
        "Использовать дату из файла, если найдена",
        value=True,
        key=f"{state_key}_use_file_date",
    )

    button_cols = st.columns(2)
    validate_clicked = button_cols[0].button("Проверить файл", key=f"{state_key}_validate")
    stored_summary = st.session_state.get(f"{state_key}_summary")
    apply_disabled = uploaded_file is None or not can_apply_import_summary(stored_summary)
    apply_clicked = button_cols[1].button(
        "Записать в базу",
        key=f"{state_key}_apply",
        disabled=apply_disabled,
    )

    if validate_clicked:
        if uploaded_file is None:
            st.warning("Сначала выберите XLSX-файл.")
        else:
            stored_summary = run_import_preview(
                importer_func=importer_func,
                uploaded_file=uploaded_file,
                use_file_date=use_file_date,
                manual_date_text=manual_date_text,
            )
            st.session_state[f"{state_key}_summary"] = stored_summary
            st.session_state.pop(f"{state_key}_apply_summary", None)
            st.session_state.pop(f"{state_key}_mart_summary", None)
            st.session_state.pop(f"{state_key}_dataset_summary", None)

    if stored_summary:
        render_import_result(stored_summary, report_name)

    if apply_clicked:
        if uploaded_file is None or not can_apply_import_summary(stored_summary):
            st.error("Сначала выполните успешный dry-run: обязательные колонки, дата и строки данных должны быть найдены.")
        else:
            effective_date = parse_optional_iso_date(stored_summary.get("effective_date"))
            apply_summary = run_import_apply(
                importer_func=importer_func,
                uploaded_file=uploaded_file,
                effective_date=effective_date,
            )
            st.session_state[f"{state_key}_apply_summary"] = apply_summary
            st.session_state[f"{state_key}_last_upload_result"] = build_last_upload_result(report_name, apply_summary)
            st.success(f"Файл записан в БД: {int(apply_summary.get('rows_upserted') or 0)} строк")
            render_import_result(apply_summary, report_name)

    apply_summary = st.session_state.get(f"{state_key}_apply_summary")
    if apply_summary:
        for message in build_pipeline_status_messages(apply_summary=apply_summary):
            st.info(message)
        render_last_upload_result(st.session_state.get(f"{state_key}_last_upload_result"))
        st.markdown("### Следующий шаг")
        st.info("Файл загружен в базу. Чтобы данные появились в ИТОГО, нужно пересобрать mart_total_report и Streamlit dataset.")
        next_step_cols = st.columns(2)
        rebuild_clicked = next_step_cols[0].button("Пересобрать mart за дату", key=f"{state_key}_rebuild_mart")
        refresh_clicked = next_step_cols[1].button("Обновить dataset для Streamlit", key=f"{state_key}_refresh_dataset")

        if rebuild_clicked:
            effective_date = parse_optional_iso_date(apply_summary.get("effective_date"))
            if effective_date is None:
                st.error("Не удалось определить дату для пересборки mart.")
            else:
                try:
                    mart_summary = rebuild_mart_for_date(effective_date)
                    st.session_state[f"{state_key}_mart_summary"] = mart_summary
                    for message in build_pipeline_status_messages(
                        apply_summary=apply_summary,
                        mart_summary=mart_summary,
                    ):
                        st.info(message)
                    if report_name == "Точка входа" and int(apply_summary.get("rows_in_db_for_date") or 0) > 0:
                        st.warning("Импорт Точки входа работает, но mart mapping ещё не реализован")
                    elif report_name == "География заказов":
                        if int(mart_summary.get("rows_with_localization_partial") or 0) > 0:
                            st.success(
                                "География записана в fact_localization_region_day и попадает в mart через общий localization block. "
                                "Отдельный mart-status для orders_geography CSV_EXPORT пока не реализован."
                            )
                        else:
                            st.warning(
                                "География записана в факт-таблицу, но в mart не видна как localization. "
                                "Проверьте date/period_start/period_end, nm_id, source_status и join-логику has_localization_partial."
                            )
                except Exception as exc:
                    st.error(f"Не удалось пересобрать mart: {exc}")

        mart_summary = st.session_state.get(f"{state_key}_mart_summary")
        if mart_summary:
            st.write("**Результат пересборки mart**")
            st.json(mart_summary)

        if refresh_clicked:
            try:
                dataset_summary = refresh_streamlit_dataset()
                st.session_state[f"{state_key}_dataset_summary"] = dataset_summary
                for message in build_pipeline_status_messages(
                    apply_summary=apply_summary,
                    mart_summary=st.session_state.get(f"{state_key}_mart_summary"),
                    dataset_summary=dataset_summary,
                ):
                    st.info(message)
            except Exception as exc:
                st.error(f"Не удалось обновить dataset: {exc}")

        dataset_summary = st.session_state.get(f"{state_key}_dataset_summary")
        if dataset_summary:
            st.success("Dataset обновлён. Если данные не видны, обновите страницу.")
            st.json(dataset_summary)


def render_upload_tab() -> None:
    st.subheader(UPLOAD_TAB_TITLE)
    render_import_block(
        title="Загрузить Точка входа",
        report_name="Точка входа",
        importer_func=import_entry_points_xlsx,
        state_key=ENTRY_POINT_UPLOAD_KEY,
    )
    st.divider()
    render_import_block(
        title="Загрузить География заказов",
        report_name="География заказов",
        importer_func=import_orders_geography_xlsx,
        state_key=ORDERS_GEOGRAPHY_UPLOAD_KEY,
    )


def render_ad_campaign_product_tab(df: pd.DataFrame, data_source: str, error_text: str | None = None) -> None:
    st.subheader(AD_CAMPAIGN_PRODUCT_LABEL)
    st.caption(
        "Отдельная детализация рекламы по grain: дата + товар + advert_id + тип конверсии. "
        "Основной ИТОГО не меняется."
    )
    if error_text:
        st.warning(error_text)
        return
    if df.empty:
        st.info("Для выбранного режима данных строки РК по товару пока отсутствуют.")
        return

    filter_cols = st.columns(4)
    available_dates = sorted(d for d in df["report_date"].dropna().unique().tolist())
    selected_dates = filter_cols[0].multiselect("Дата", options=available_dates, default=available_dates)
    supplier_search = filter_cols[1].text_input("Артикул продавца")
    nm_search = filter_cols[2].text_input("nm_id")
    advert_search = filter_cols[3].text_input("advert_id")

    filter_cols_2 = st.columns(4)
    conversion_options = sorted(
        value for value in df["conversion_type"].dropna().astype(str).unique().tolist()
    )
    selected_conversions = filter_cols_2[0].multiselect("Тип конверсии", options=conversion_options)
    spend_only = filter_cols_2[1].checkbox("Только строки с расходом")
    atbs_only = filter_cols_2[2].checkbox("Только строки с корзинами")
    orders_only = filter_cols_2[3].checkbox("Только строки с заказами")

    filtered = df.copy()
    if selected_dates:
        filtered = filtered[filtered["report_date"].isin(selected_dates)]
    if supplier_search:
        filtered = filtered[
            filtered["supplier_article"].fillna("").str.contains(supplier_search, case=False, na=False)
        ]
    if nm_search:
        filtered = filtered[filtered["nm_id"].astype(str).str.contains(nm_search, case=False, na=False)]
    if advert_search:
        filtered = filtered[filtered["advert_id"].astype(str).str.contains(advert_search, case=False, na=False)]
    if selected_conversions:
        filtered = filtered[filtered["conversion_type"].isin(selected_conversions)]
    if spend_only:
        filtered = filtered[filtered["campaign_spend"].notna()]
    if atbs_only:
        filtered = filtered[filtered["ad_atbs"].notna() & (filtered["ad_atbs"] > 0)]
    if orders_only:
        filtered = filtered[filtered["ad_orders"].notna() & (filtered["ad_orders"] > 0)]

    filtered = filtered.sort_values(
        by=["supplier_article", "nm_id", "report_date", "advert_id", "conversion_type"],
        ascending=[True, True, True, True, True],
        na_position="last",
    )

    metric_cols = st.columns(5)
    metric_cols[0].metric("Строк", f"{len(filtered):,}".replace(",", " "))
    metric_cols[1].metric("Товаров", f"{filtered['nm_id'].nunique():,}".replace(",", " "))
    metric_cols[2].metric("РК", f"{filtered['advert_id'].nunique():,}".replace(",", " "))
    metric_cols[3].metric("Типов конверсии", f"{filtered['conversion_type'].nunique():,}".replace(",", " "))
    metric_cols[4].metric("Режим", "PostgreSQL" if data_source == "db" else "CSV")

    download_df = filtered.reindex(columns=AD_CAMPAIGN_PRODUCT_COLUMNS).rename(columns=AD_CAMPAIGN_PRODUCT_EXPORT_LABELS)
    csv_bytes = download_df.to_csv(index=False).encode("utf-8-sig")
    st.download_button(
        "Скачать РК по товару CSV",
        data=csv_bytes,
        file_name="streamlit_ad_campaign_product_dataset_filtered.csv",
        mime="text/csv",
    )

    st.dataframe(
        filtered.reindex(columns=AD_CAMPAIGN_PRODUCT_COLUMNS),
        width="stretch",
        hide_index=True,
        column_config={
            "report_date": st.column_config.DateColumn("Дата"),
            "supplier_article": st.column_config.TextColumn("Артикул продавца", width="medium"),
            "nm_id": st.column_config.NumberColumn("Артикул WB", format="%d"),
            "title": st.column_config.TextColumn("Название", width="large"),
            "brand": st.column_config.TextColumn("Бренд"),
            "subject": st.column_config.TextColumn("Предмет"),
            "advert_id": st.column_config.NumberColumn("ID РК", format="%d"),
            "campaign_name": st.column_config.TextColumn("Название РК", width="large"),
            "campaign_type": st.column_config.TextColumn("Тип кампании"),
            "conversion_type": st.column_config.TextColumn("Тип конверсии"),
            "campaign_spend": st.column_config.NumberColumn("Расход РК по статистике", format="%.2f"),
            "ad_views": st.column_config.NumberColumn("Показы РК", format="%.0f"),
            "ad_clicks": st.column_config.NumberColumn("Клики РК", format="%.0f"),
            "ad_atbs": st.column_config.NumberColumn("Корзины РК", format="%.0f"),
            "ad_orders": st.column_config.NumberColumn("Заказы РК", format="%.0f"),
            "ad_cpc_calc": st.column_config.NumberColumn("CPC", format="%.2f"),
            "ad_cpm_calc": st.column_config.NumberColumn("CPM", format="%.2f"),
            "ad_cost_per_cart_calc": st.column_config.NumberColumn("Цена корзины", format="%.2f"),
            "ad_cpo_calc": st.column_config.NumberColumn("CPO", format="%.2f"),
            "order_sum": st.column_config.NumberColumn("Сумма заказов товара", format="%.2f"),
            "ad_share_of_order_sum_calc": st.column_config.NumberColumn(
                "Доля расхода РК от суммы заказов товара, %",
                format="%.2f",
            ),
        },
    )


def main() -> None:
    st.set_page_config(page_title="WB ИТОГО", layout="wide")
    st.title("WB ИТОГО")
    st.caption("Витрина по товарам на основе mart_total_report v2")
    render_password_gate()
    if st.button("Обновить данные из источника", width="content"):
        clear_streamlit_data_caches()
        st.rerun()

    df, data_source = load_app_dataset()
    display_coverage = df.attrs.get("display_coverage")
    ad_campaign_product_df, ad_campaign_product_error = load_ad_campaign_product_app_dataset(data_source)
    st.caption(f"Источник данных: {'PostgreSQL' if data_source == 'db' else 'CSV'}")
    render_available_dates_summary(df)
    filtered, filter_debug_trace = build_filtered_dataset(df)

    metric_cols = st.columns(7)
    metric_cols[0].metric("Всего строк", f"{len(filtered):,}".replace(",", " "))
    metric_cols[1].metric("Товаров", f"{filtered['nm_id'].nunique():,}".replace(",", " "))
    metric_cols[2].metric("Дат", f"{filtered['report_date'].nunique():,}".replace(",", " "))
    metric_cols[3].metric("Строк без данных", f"{(filtered['data_quality_status'] == 'NO_DATA').sum():,}".replace(",", " "))
    metric_cols[4].metric("Строк с рекламой", f"{filtered['has_ad_campaign'].sum():,}".replace(",", " "))
    metric_cols[5].metric("Строк с поиском", f"{filtered['has_search'].sum():,}".replace(",", " "))
    metric_cols[6].metric("Строк с остатками", f"{filtered['has_stock'].sum():,}".replace(",", " "))

    if filtered.empty:
        st.warning("После фильтров данных не осталось.")
        st.stop()

    product_options, option_map = get_product_options(filtered)
    selected_product_label = st.selectbox("Выбрать товар", options=product_options)
    product_rows = get_selected_product_rows(filtered, selected_product_label, option_map)
    product_context = get_latest_product_context(product_rows)
    latest_row: pd.Series = product_context["latest_row"]

    detail_dates = sorted(product_rows["report_date"].dropna().unique().tolist(), reverse=True)
    default_detail_date = detail_dates[0]

    tab_overview, tab_ad_campaign, tab_product, tab_charts, tab_sources, tab_stock_warehouse, tab_upload = st.tabs(
        [
            "ИТОГО",
            AD_CAMPAIGN_PRODUCT_LABEL,
            "Карточка товара",
            "Графики",
            "Источники",
            STOCK_WAREHOUSE_TAB_LABEL,
            UPLOAD_TAB_TITLE,
        ]
    )
    with tab_overview:
        render_overview_tab(filtered, filter_debug_trace, display_coverage)
    with tab_ad_campaign:
        render_ad_campaign_product_tab(ad_campaign_product_df, data_source, ad_campaign_product_error)
    with tab_product:
        render_product_tab(product_rows, default_detail_date)
    with tab_charts:
        render_charts_tab(filtered, selected_product_label, option_map, ad_campaign_product_df)
    with tab_sources:
        render_sources_tab(latest_row)
    with tab_stock_warehouse:
        render_stock_warehouse_tab(data_source)
    with tab_upload:
        render_upload_tab()


if __name__ == "__main__":
    main()
