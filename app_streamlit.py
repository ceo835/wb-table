from __future__ import annotations

import json
from decimal import Decimal
from html import escape
from io import BytesIO
import logging
import os
import tempfile
from datetime import date, datetime, timedelta
from pathlib import Path
from time import perf_counter
from typing import Any, Mapping
from urllib.parse import urlsplit

import altair as alt
import pandas as pd
import streamlit as st
import src.ad_campaign_efficiency as ad_campaign_efficiency
from pandas.io.formats.style import Styler
from sqlalchemy import func, select, text

try:
    pd.options.mode.string_storage = "python"
except Exception:
    pass

try:
    pd.options.future.infer_string = False
except Exception:
    pass

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
from src.db.models import (
    DimProduct,
    DimProductSize,
    FactEntryPointDay,
    FactStockWarehouseSnapshot,
    FactIvanAdsWideDay,
    FactWbSitePriceAlert,
    FactWbSitePriceSnapshot,
    FactWbSellerPriceSnapshot,
    MartTotalReport,
    SettingsProducts,
    FactWbSearchQueryTextDay,
    SettingsLostProfitQueryGroupCoefficient,
    SettingsLostProfitWarehouseArea,
    SettingsLostProfitMarketArea,
    FactFunnelDay,
    FactIvanStockSheetDay,
    FactWbStatisticsOrderSizeDay,
    FactOzonPriceSnapshot,
)
from src.services.dashboard_milestones import (
    DEFAULT_MILESTONE_TYPE,
    MILESTONE_TYPES,
    create_milestone,
    deactivate_milestone,
    list_milestones,
    update_milestone,
)
from src.db.product_query_group_backfill import (
    QUERY_GROUP_UNKNOWN,
    QUERY_GROUP_VALUES as PRODUCT_QUERY_GROUP_VALUES,
    format_query_group_label,
    normalize_query_group_value,
)
from src.db.ivan_stock_sheet_loader import load_ivan_stock_product_level, load_ivan_stock_size_level
from src.db.wb_supply_loader import load_wb_supply_product_level
from src.db.product_size_loader import load_dim_product_size_rows
from src.db.session import session_scope
from src.config.settings import settings
from src.importers.entry_points_importer import import_entry_points_xlsx
from src.importers.orders_geography_importer import import_orders_geography_xlsx
from src.scheduler.daily_refresh_scheduler import start_daily_refresh_scheduler_once
from src.streamlit_dataset import (
    AD_ZERO_FILL_FIELDS,
    FUNNEL_ZERO_FILL_FIELDS,
    NOTE_COLUMNS,
    attach_wb_price_snapshot_fields,
    attach_wb_seller_price_fields,
    build_data_quality_label as shared_build_data_quality_label,
    enrich_streamlit_row as shared_enrich_streamlit_row,
)
from src.tracked_products import (
    apply_tracked_products as shared_apply_tracked_products,
    load_tracked_products,
)
from src.services.communications.ui import render_communications_tab

logger = logging.getLogger(__name__)


def _log_timing(event_name: str, started_at: float, **details: Any) -> None:
    elapsed = perf_counter() - started_at
    detail_suffix = ""
    if details:
        rendered_details = ", ".join(
            f"{key}={value}"
            for key, value in details.items()
            if value is not None
        )
        if rendered_details:
            detail_suffix = f" [{rendered_details}]"
    logger.info("%s finished in %.3fs%s", event_name, elapsed, detail_suffix)


ROOT_DIR = Path(__file__).resolve().parent
DATASET_PATH = ROOT_DIR / "data" / "processed" / "streamlit_v1_dataset.csv"
PRODUCT_BANDS_PATH = ROOT_DIR / "data" / "config" / "product_bands.csv"
MAIN_WB_WAREHOUSES_PATH = ROOT_DIR / "data" / "config" / "main_wb_warehouses.csv"
WB_SITE_PRICE_TAB_LABEL = "Мониторинг цен"
DEFAULT_DATA_SOURCE = "csv"
STOCK_WAREHOUSE_TAB_LABEL = "Остатки по складам"
STOCK_ZERO_POSITIONS_TAB_LABEL = "Контроль нулевых позиций"
STOCK_ALL_POSITIONS_TAB_LABEL = "Контроль всех остатков"
ENTRY_POINT_ANALYTICS_TAB_LABEL = "Аналитика точки входа"
WAREHOUSE_SCOPE_MAIN = "Основные склады"
WAREHOUSE_SCOPE_ALL = "Все склады"
STOCK_STATUS_OK = "OK"
STOCK_STATUS_ZERO = "ZERO_ON_WAREHOUSE"
STOCK_STATUS_NO_DATA = "NO_DATA_ON_WAREHOUSE"
STOCK_STATUS_NO_PRODUCT_DATA = "NO_STOCK_DATA_FOR_PRODUCT"
PROBLEM_STATUS_ZERO_MAIN = "ZERO_ON_MAIN_WAREHOUSES"
PROBLEM_STATUS_PARTIAL_STOCK = "PARTIAL_STOCK"
PROBLEM_STATUS_NO_DATA_MAIN = "NO_DATA_ON_MAIN_WAREHOUSES"
STOCK_WAREHOUSE_NO_DATA_DISPLAY = "—"
STOCK_HISTORY_STATUS_IN_STOCK = "IN_STOCK"
STOCK_HISTORY_STATUS_ZERO = "ZERO_STOCK"
STOCK_HISTORY_STATUS_NO_DATA = "NO_DATA"
STOCK_HISTORY_ANOMALY_ALWAYS_NO_DATA = "ALWAYS_NO_DATA"
STOCK_HISTORY_ANOMALY_ALWAYS_ZERO = "ALWAYS_ZERO"
STOCK_HISTORY_ANOMALY_ALWAYS_IN_STOCK = "ALWAYS_IN_STOCK"
STOCK_HISTORY_ANOMALY_MIXED_ZERO_AND_STOCK = "MIXED_ZERO_AND_STOCK"
STOCK_HISTORY_ANOMALY_MIXED_NO_DATA_AND_STOCK = "MIXED_NO_DATA_AND_STOCK"
STOCK_HISTORY_ANOMALY_UNSTABLE = "UNSTABLE"
QUERY_GROUP_UNDEFINED_LABEL = "Не определена"
QUERY_GROUP_ALLOWED_VALUES = PRODUCT_QUERY_GROUP_VALUES
WB_SITE_PRICE_ALERT_OK = "OK"
WB_SITE_PRICE_ALERT_CHANGED = "PRICE_CHANGED_50"
WB_SITE_PRICE_ALERT_NO_DATA = "NO_PRICE_DATA"
WB_SITE_PRICE_ALERT_FAILED = "FETCH_FAILED"
AD_CAMPAIGN_PRODUCT_LABEL = "РК по товару"
IVAN_MANUAL_AD_SOURCE_LABEL = "Иван / ручная реклама"
API_WB_AD_SOURCE_LABEL = "API WB"
DEFAULT_STREAMLIT_DISPLAY_MIN_DATE = date(2026, 6, 7)
STREAMLIT_DISPLAY_MIN_DATE_ENV_VAR = "STREAMLIT_DISPLAY_MIN_DATE"
TABLE_STYLE_LOOKBACK_DAYS = 30
OVERVIEW_HIDDEN_COLUMNS = {"current_stock_qty", "current_stock_sum"}
OVERVIEW_EMPTY_ROW_METRIC_COLUMNS = ("card_clicks", "cart_count", "order_count", "order_sum")

LATEST_MODE_LABEL = "Последняя дата + динамика"
BY_DATE_MODE_LABEL = "По датам"
CHART_THRESHOLD_CART_COST = 35.0
CHART_THRESHOLD_CPO = 150.0
CHART_AD_PARTIAL_SPEND_COVERAGE_THRESHOLD = 0.9
STYLER_MAX_CELLS = 250_000
STOCK_WAREHOUSE_HISTORY_PIVOT_MAX_CELLS = 120_000
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


def _clip_non_negative_numeric_series(series: "pd.Series") -> "pd.Series":
    numeric = pd.to_numeric(series, errors="coerce")
    return numeric.clip(lower=0)


def _normalize_nullable_int_display_series(series: "pd.Series") -> "pd.Series":
    return pd.to_numeric(series, errors="coerce").fillna(0).astype("Int64")

DISPLAY_DELTA_COLUMNS_HIGHER_IS_BETTER = {
    "impressions_delta",
    "cart_count_delta",
    "order_count_delta",
    "order_sum_delta",
    "ad_atbs_delta",
    "ad_orders_delta",
    "search_queries_delta",
    "stock_delta",
}
DISPLAY_DELTA_COLUMNS_LOWER_IS_BETTER = {
    "ad_cpo_delta",
}
DISPLAY_NUMERIC_PLACEHOLDERS = {
    "",
    "—",
    "NO_DATA",
    STOCK_WAREHOUSE_NO_DATA_DISPLAY,
}
CHART_ALL_CATEGORIES_LABEL = "Все категории"
CHART_ALL_BANDS_LABEL = "Все банды"
CHART_ALL_CONVERSION_TYPES_LABEL = "Все типы WB"
ENTRY_POINT_LEVEL_CABINET = "Кабинет"
ENTRY_POINT_LEVEL_BAND = "Банды"
ENTRY_POINT_LEVEL_ARTICLE = "Артикулы"
ENTRY_POINT_DETAIL_COARSE = "Укрупнённо"
ENTRY_POINT_DETAIL_DETAILED = "Детально"
ENTRY_POINT_GROUP_SEARCH = "Поиск"
ENTRY_POINT_GROUP_CATALOG = "Каталог"
ENTRY_POINT_GROUP_RECOMMENDATION = "Рекомендательные полки"
ENTRY_POINT_GROUP_OTHER = "Остальное"
ENTRY_POINT_GROUP_TOTAL = "Итого"
ENTRY_POINT_GROUP_ORDER = [
    ENTRY_POINT_GROUP_SEARCH,
    ENTRY_POINT_GROUP_CATALOG,
    ENTRY_POINT_GROUP_RECOMMENDATION,
    ENTRY_POINT_GROUP_OTHER,
    ENTRY_POINT_GROUP_TOTAL,
]
ENTRY_POINT_LABEL_DATE = "Дата"
ENTRY_POINT_LABEL_SECTION = "Раздел"
ENTRY_POINT_LABEL_POINT = "Точка входа"
ENTRY_POINT_LABEL_BAND = "Банда"
ENTRY_POINT_LABEL_SUPPLIER_ARTICLE = "Артикул продавца"
ENTRY_POINT_LABEL_WB_ARTICLE = "Артикул WB"
ENTRY_POINT_LABEL_TITLE = "Название"
ENTRY_POINT_LABEL_IMPRESSIONS = "Показы"
ENTRY_POINT_LABEL_CARD_CLICKS = "Переходы в карточку"
ENTRY_POINT_LABEL_CART_COUNT = "Добавления в корзину"
ENTRY_POINT_LABEL_CART_CONVERSION = "Конверсия в корзину"
ENTRY_POINT_LABEL_ORDERS = "Заказы"
ENTRY_POINT_LABEL_ORDER_CONVERSION = "Конверсия в заказ"
ENTRY_POINT_LABEL_NO_BAND = "Без банды"
ENTRY_POINT_LABEL_NO_SECTION = "Без раздела"
ENTRY_POINT_LABEL_NO_POINT = "Без точки входа"
ENTRY_POINT_LABEL_TRAFFIC_TAB = "Трафик"
ENTRY_POINT_ECONOMICS_TAB_LABEL = "Стоимость и CPO"
ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN = "Распределённый расход РК"
ENTRY_POINT_ECONOMICS_CART_COST_COLUMN = "Стоимость корзины РК"
ENTRY_POINT_ECONOMICS_CPO_COLUMN = "CPO РК"
ENTRY_POINT_CONVERSION_HIGHLIGHT = "#fef3c7"
ENTRY_POINT_CART_SPIKE_HIGHLIGHT = "#fee2e2"
ENTRY_POINT_DEFAULT_TOP_N_ARTICLES = 20
ENTRY_POINT_DEFAULT_TOP_N_DETAILED_ARTICLES = 10
ENTRY_POINT_DEFAULT_TOP_N_DETAILED_BANDS = 10
ENTRY_POINT_MAX_DETAILED_ROWS = 500
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
    "wb_buyer_price",
    "wb_seller_price",
    "spp_rub",
    "spp_pct",
    "impressions",
    "card_clicks",
    "cart_count",
    "order_count",
    "ctr_calc",
    "add_to_cart_conversion_calc",
    "cart_to_order_conversion_calc",
    "order_sum",
    "ad_campaign_spend_total",
    "legacy_cost_per_card_click_calc",
    "legacy_cost_per_all_carts_calc",
    "legacy_cost_per_order_calc",
    "legacy_ad_share_of_order_sum_pct",
    "ad_views_total",
    "ad_clicks_total",
    "ad_atbs_total",
    "ad_orders_total",
    "ad_cpc_calc",
    "ad_cpm_calc",
    "ad_cost_per_cart_calc",
    "ad_cpo_calc",
    "organic_cart_count",
    "organic_cart_share_calc",
    "vvbromo_operating_profit",
    "crm_common_calc",
    "current_stock_qty",
    "current_stock_sum",
    "search_queries_count",
    "local_orders_percent",
    "avg_delivery_time",
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
    "wb_buyer_price",
    "wb_seller_price",
    "spp_rub",
    "spp_pct",
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
    "wb_buyer_price",
    "wb_seller_price",
    "spp_rub",
    "spp_pct",
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
    "vvbromo_organic_sales",
    "vvbromo_operating_profit",
    "vvbromo_operating_profit_per_unit",
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
    "wb_buyer_price": "Цена WB",
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
    "wb_buyer_price",
    "previous_wb_buyer_price",
    "wb_price_delta",
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
    "legacy_cost_per_card_click_calc",
    "legacy_cost_per_all_carts_calc",
    "legacy_cost_per_order_calc",
    "legacy_ad_share_of_order_sum_pct",
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
    "current_stock_sum",
    "buyout_count",
    "buyout_sum",
    "buyout_percent",
    "avg_delivery_time",
    "local_orders_percent",
    "localization_orders_total_qty",
    "localization_regions_count",
    "organic_cart_count",
    "organic_cart_share_calc",
    "ad_cost_per_all_carts_calc",
    "vvbromo_organic_sales",
    "vvbromo_operating_profit",
    "vvbromo_operating_profit_per_unit",
    "crm_common_calc",
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
    "current_stock_sum",
    "search_queries_count",
    "local_orders_percent",
    "vvbromo_organic_sales",
    "vvbromo_operating_profit",
    "vvbromo_operating_profit_per_unit",
    "crm_common_calc",
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
VBRO_UPLOAD_KEY = "vbro_import"

EXPORT_COLUMN_LABELS = {
    "product_group_label": "Товар",
    "report_date": "Дата",
    "comparison_date": "Сравнение с датой",
    "supplier_article": "Артикул продавца",
    "nm_id": "Артикул WB",
    "title": "Название",
    "brand": "Бренд",
    "subject": "Предмет",
    "wb_buyer_price": "Цена WB",
    "wb_seller_price": "Цена продавца ЛК",
    "spp_rub": "СПП, ₽",
    "spp_pct": "СПП, %",
    "impressions": "Показы общие",
    "card_clicks": "Переходы в карточку",
    "ctr_calc": "CTR общий",
    "cart_count": "Положили в корзину",
    "add_to_cart_conversion_calc": "Конверсия в корзину, %",
    "order_count": "Заказы",
    "cart_to_order_conversion_calc": "Конверсия корзина → заказ, %",
    "order_sum": "Заказали на сумму",
    "buyout_count": "Выкупы, шт",
    "buyout_sum": "Выкупы, сумма",
    "buyout_percent": "Процент выкупа, %",
    "current_stock_qty": "Остаток WB",
    "current_stock_sum": "Сумма остатков",
    "avg_delivery_time": "Среднее время доставки",
    "local_orders_percent": "Локальные заказы, %",
    "ad_cost_writeoff_total": "Списания рекламы",
    "ad_campaign_spend_total": "Сумма кампании",
    "legacy_cost_per_card_click_calc": "Цена перехода по общим переходам",
    "legacy_cost_per_all_carts_calc": "Расход на все корзины",
    "legacy_cost_per_order_calc": "Расход на все заказы",
    "legacy_ad_share_of_order_sum_pct": "Доля рекламы от суммы заказов, %",
    "ad_views_total": "Показы РК",
    "ad_clicks_total": "Клики РК",
    "ad_atbs_total": "Корзины РК",
    "ad_orders_total": "Заказы РК",
    "ad_cpc_calc": "CPC РК",
    "ad_cpm_calc": "CPM РК",
    "ad_cost_per_cart_calc": "Цена корзины РК",
    "ad_cpo_calc": "CPO РК",
    "ad_share_of_revenue_calc": "Доля рекламы, %",
    "direct_ad_atbs": "Прямые корзины РК",
    "associated_ad_atbs": "Ассоциированные корзины РК",
    "multicard_ad_atbs": "Мультикарточка корзины РК",
    "unknown_ad_atbs": "Unknown корзины РК",
    "associated_atbs_percent_calc": "Ассоциированные корзины, %",
    "organic_cart_count": "Органические корзины",
    "organic_cart_share_calc": "Доля органических корзин, %",
    "ad_cost_per_all_carts_calc": "Тех: расход на все корзины (с assoc.)",
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
        "display_impressions": "Показы общие",
        "display_ctr_calc": "CTR общий",
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
        "vvbromo_organic_sales": "Продажи органические VVBromo",
        "vvbromo_operating_profit": "Операционная прибыль VVBromo",
        "vvbromo_operating_profit_per_unit": "Опер. прибыль/ед. VVBromo",
        "crm_common_calc": "CRM по общим заказам",
    }
)

EXPORT_COLUMN_LABELS.update(
    {
        "add_to_cart_conversion_calc": "Конверсия в корзину",
        "cart_to_order_conversion_calc": "Конверсия в заказ",
        "ad_campaign_spend_total": "Сумма кампании",
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
    display_row = latest_row
    display_date = latest_date
    display_previous_row = previous_row
    display_previous_date = previous_date

    if not has_core_coverage(latest_row):
        candidate_rows = sorted_rows.iloc[:-1]
        for index in range(len(candidate_rows) - 1, -1, -1):
            candidate_row = candidate_rows.iloc[index]
            if not has_core_coverage(candidate_row):
                continue
            display_row = candidate_row
            display_date = candidate_row["report_date"]
            display_previous_row = candidate_rows.iloc[index - 1] if index > 0 else None
            display_previous_date = (
                display_previous_row["report_date"] if display_previous_row is not None else None
            )
            break

    return {
        "latest_row": latest_row,
        "latest_date": latest_date,
        "previous_row": previous_row,
        "previous_date": previous_date,
        "display_row": display_row,
        "display_date": display_date,
        "display_previous_row": display_previous_row,
        "display_previous_date": display_previous_date,
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
def load_dataset_from_db(cache_buster: str | None = None) -> pd.DataFrame:
    with session_scope() as session:
        mart_rows = session.execute(
            select(MartTotalReport).order_by(MartTotalReport.report_date.asc(), MartTotalReport.nm_id.asc())
        ).scalars().all()
        rows = [row_to_dict(row) for row in mart_rows]
    wb_price_snapshot_df = load_wb_site_price_snapshot_from_db(cache_buster)
    if not wb_price_snapshot_df.empty:
        rows = attach_wb_price_snapshot_fields(rows, wb_price_snapshot_df.to_dict(orient="records"))
    wb_seller_price_df = load_wb_seller_price_snapshot_from_db(cache_buster)
    if not wb_seller_price_df.empty:
        rows = attach_wb_seller_price_fields(rows, wb_seller_price_df.to_dict(orient="records"))
    return pd.DataFrame(rows)


@st.cache_data(show_spinner=False)
def load_prepared_dataset_from_db(cache_buster: str | None = None) -> pd.DataFrame:
    return prepare_dataframe(load_dataset_from_db(cache_buster))


def get_db_dataset_cache_buster() -> str:
    with session_scope() as session:
        mart_state = session.execute(
            select(
                func.max(MartTotalReport.report_date),
                func.max(MartTotalReport.loaded_at),
                func.count(),
            )
        ).one()
        price_state = session.execute(
            select(
                func.max(FactWbSitePriceSnapshot.snapshot_date),
                func.max(FactWbSitePriceSnapshot.created_at),
                func.count(),
            )
        ).one()
        seller_price_state = session.execute(
            select(
                func.max(FactWbSellerPriceSnapshot.snapshot_date),
                func.max(FactWbSellerPriceSnapshot.created_at),
                func.count(),
            )
        ).one()
        alert_state = session.execute(
            select(
                func.max(FactWbSitePriceAlert.snapshot_date),
                func.max(FactWbSitePriceAlert.created_at),
                func.count(),
            )
        ).one()
        entry_point_state = session.execute(
            select(
                func.max(FactEntryPointDay.date),
                func.max(FactEntryPointDay.loaded_at),
                func.count(),
            )
        ).one()
        try:
            from src.db.models import FactVvbromoProductDay
            vvbromo_state = session.execute(
                select(
                    func.max(FactVvbromoProductDay.day),
                    func.max(FactVvbromoProductDay.loaded_at),
                    func.count(),
                )
            ).one()
        except Exception:
            vvbromo_state = (None, None, 0)
        stock_warehouse_state = session.execute(
            select(
                func.max(FactStockWarehouseSnapshot.snapshot_date),
                func.max(FactStockWarehouseSnapshot.loaded_at),
                func.count(),
            )
        ).one()
        dim_product_size_state = session.execute(
            select(
                func.max(DimProductSize.updated_at),
                func.count(func.distinct(DimProductSize.nm_id)),
                func.count(),
            )
        ).one()
        size_sales_state = session.execute(
            select(
                func.max(FactWbStatisticsOrderSizeDay.date),
                func.max(FactWbStatisticsOrderSizeDay.loaded_at),
                func.count(),
            )
        ).one()
        ivan_stock_state = session.execute(
            select(
                func.max(FactIvanStockSheetDay.stock_date),
                func.max(FactIvanStockSheetDay.loaded_at),
                func.count(),
            )
        ).one()
        funnel_state = session.execute(
            select(
                func.max(FactFunnelDay.date),
                func.max(FactFunnelDay.loaded_at),
                func.count(),
            )
        ).one()
        settings_products_state = session.execute(
            select(
                func.max(SettingsProducts.loaded_at),
                func.count(func.distinct(SettingsProducts.nm_id)),
                func.count(),
            )
        ).one()
        try:
            ozon_state = session.execute(
                select(
                    func.max(FactOzonPriceSnapshot.snapshot_date),
                    func.max(FactOzonPriceSnapshot.loaded_at),
                    func.count(),
                )
            ).one()
        except Exception:
            ozon_state = (None, None, 0)
    return "|".join(
        "" if value is None else str(value) 
        for value in (
            *mart_state,
            *price_state,
            *seller_price_state,
            *alert_state,
            *entry_point_state,
            *vvbromo_state,
            *stock_warehouse_state,
            *dim_product_size_state,
            *size_sales_state,
            *ivan_stock_state,
            *funnel_state,
            *settings_products_state,
            *ozon_state,
        )
    )


def resolve_db_dataset_cache_buster() -> str | None:
    try:
        return get_db_dataset_cache_buster()
    except Exception:
        logger.exception("Failed to build DB dataset cache-buster")
        return None


def resolve_data_source() -> str:
    explicit_source = os.getenv("STREAMLIT_DATA_SOURCE")
    if explicit_source:
        return explicit_source.strip().lower()
    if os.getenv("DATABASE_URL") or settings.database_url:
        return "db"
    return DEFAULT_DATA_SOURCE


def build_main_tab_labels() -> list[str]:
    return [
        "ИТОГО",
        ENTRY_POINT_ANALYTICS_TAB_LABEL,
        ad_campaign_efficiency.AD_CAMPAIGN_SECTION_LABEL,
        "Карточка товара",
        "Графики",
        WB_SITE_PRICE_TAB_LABEL,
        STOCK_WAREHOUSE_TAB_LABEL,
        UPLOAD_TAB_TITLE,
    ]


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


def attach_vvbromo_to_df(df: pd.DataFrame) -> pd.DataFrame:
    if df.empty:
        return df.copy()

    if "nm_id" not in df.columns or "report_date" not in df.columns:
        # Убедимся, что колонки есть
        for col in ("vvbromo_organic_sales", "vvbromo_operating_profit", "vvbromo_operating_profit_per_unit"):
            if col not in df.columns:
                df[col] = pd.NA
        return df

    # Извлечем уникальные nm_id и даты из DataFrame для оптимизации запроса к БД
    nm_ids = [int(x) for x in df["nm_id"].dropna().unique().tolist()]
    # Приведем report_date к датам на случай, если они еще строки/Timestamp
    dates = pd.to_datetime(df["report_date"], errors="coerce").dt.date.dropna().unique().tolist()

    if not nm_ids or not dates:
        # Убедимся, что колонки есть
        for col in ("vvbromo_organic_sales", "vvbromo_operating_profit", "vvbromo_operating_profit_per_unit"):
            if col not in df.columns:
                df[col] = pd.NA
        return df

    vv_columns = pd.Index(
        ["vv_report_date", "vv_nm_id", "vv_sales", "vv_profit", "vv_profit_per_unit"],
        dtype=object,
    )
    vv_df = pd.DataFrame(columns=vv_columns, dtype=object)
    try:
        from src.db.session import session_scope
        from src.db.models import FactVvbromoProductDay
        from sqlalchemy import select
        with session_scope() as session:
            db_rows = session.execute(
                select(FactVvbromoProductDay).where(
                    FactVvbromoProductDay.nm_id.in_(nm_ids),
                    FactVvbromoProductDay.day.in_(dates)
                )
            ).scalars().all()
            if db_rows:
                vv_records = [
                    {
                        "vv_report_date": r.day,
                        "vv_nm_id": int(r.nm_id),
                        "vv_sales": r.organic_sales,
                        "vv_profit": float(r.operating_profit) if r.operating_profit is not None else None,
                        "vv_profit_per_unit": float(r.operating_profit_per_unit) if r.operating_profit_per_unit is not None else None,
                    }
                    for r in db_rows
                ]
                vv_df = pd.DataFrame.from_records(vv_records, columns=vv_columns)
                vv_df = vv_df.astype(object)
    except Exception as e:
        logger.warning(f"Database connection failed while loading VVBromo: {e}. Falling back to CSV data or NULL.")
        # Если БД недоступна, просто возвращаем df (если колонок нет, добавим пустые)
        for col in ("vvbromo_organic_sales", "vvbromo_operating_profit", "vvbromo_operating_profit_per_unit"):
            if col not in df.columns:
                df[col] = pd.NA
        return df

    if vv_df.empty:
        # В БД нет данных по этим товарам/датам. Убедимся, что колонки есть, и вернем df
        for col in ("vvbromo_organic_sales", "vvbromo_operating_profit", "vvbromo_operating_profit_per_unit"):
            if col not in df.columns:
                df[col] = pd.NA
        return df

    # Преобразуем типы в vv_df для точного merge
    vv_df["vv_report_date"] = pd.to_datetime(vv_df["vv_report_date"]).dt.date
    vv_df["vv_nm_id"] = pd.to_numeric(vv_df["vv_nm_id"], errors="coerce")
    vv_df = vv_df.astype(object)

    # Сделаем merge
    # Чтобы не дублировать колонки, удалим их из df перед merge
    df_clean = df.copy()
    for col in ("vvbromo_organic_sales", "vvbromo_operating_profit", "vvbromo_operating_profit_per_unit"):
        if col in df_clean.columns:
            df_clean = df_clean.drop(columns=[col])

    df_clean["report_date_temp"] = pd.to_datetime(df_clean["report_date"], errors="coerce").dt.date
    df_clean["nm_id_temp"] = pd.to_numeric(df_clean["nm_id"], errors="coerce")

    merged = df_clean.merge(
        vv_df,
        left_on=["report_date_temp", "nm_id_temp"],
        right_on=["vv_report_date", "vv_nm_id"],
        how="left"
    )

    merged["vvbromo_organic_sales"] = merged["vv_sales"]
    merged["vvbromo_operating_profit"] = merged["vv_profit"]
    merged["vvbromo_operating_profit_per_unit"] = merged["vv_profit_per_unit"]

    # Удалим временные колонки
    merged = merged.drop(
        columns=[
            "report_date_temp",
            "nm_id_temp",
            "vv_report_date",
            "vv_nm_id",
            "vv_sales",
            "vv_profit",
            "vv_profit_per_unit"
        ],
        errors="ignore"
    )

    return merged


def prepare_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    started_at = perf_counter()
    prepared = df.copy()
    if "report_date" in prepared.columns:
        prepared["report_date"] = pd.to_datetime(prepared["report_date"], errors="coerce").dt.date
    prepared = attach_vvbromo_to_df(prepared)
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
    def get_vbro_label(row):
        profit = row.get("vvbromo_operating_profit")
        if pd.notna(profit) and profit is not None:
            return "Файл загружен"
        return build_vbro_status_label(row.get("vbro_status"))

    enriched["vbro_status_label"] = enriched.apply(get_vbro_label, axis=1)
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
    for column in NUMERIC_COLUMNS:
        if column in enriched.columns:
            enriched[column] = pd.to_numeric(enriched[column], errors="coerce")
    enriched.attrs["display_coverage"] = build_display_coverage_summary(prepared, enriched).to_dict(orient="records")
    _log_timing("prepare_dataframe", started_at, rows_in=len(df), rows_out=len(enriched))
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
    tracked_metadata_available: bool = True,
) -> pd.DataFrame:
    filtered = df.copy()
    if "is_tracked" not in filtered.columns or "lifecycle_status" not in filtered.columns:
        filtered = shared_apply_tracked_products(filtered)

    if show_only_tracked and tracked_metadata_available and "is_tracked" in filtered.columns:
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


def _serialize_debug_date(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    if isinstance(value, pd.Timestamp):
        return value.date().isoformat()
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def inspect_tracked_metadata_state(df: pd.DataFrame) -> dict[str, object]:
    dataset_nm_ids = pd.Series(dtype="int64")
    if "nm_id" in df.columns:
        dataset_nm_ids = pd.to_numeric(df["nm_id"], errors="coerce").dropna().astype(int)

    tracked_df = load_tracked_products()
    tracked_total = int(len(tracked_df))
    tracked_active_df = (
        tracked_df[tracked_df["is_tracked"].fillna(False)]
        if "is_tracked" in tracked_df.columns
        else tracked_df.iloc[0:0]
    )
    tracked_active_total = int(len(tracked_active_df))
    tracked_matches_in_dataset = 0
    if not tracked_active_df.empty and not dataset_nm_ids.empty:
        tracked_matches_in_dataset = int(tracked_active_df["nm_id"].isin(dataset_nm_ids.unique()).sum())

    if tracked_df.empty:
        reason = "tracked_products_missing"
    elif tracked_active_df.empty:
        reason = "tracked_products_without_active_rows"
    elif tracked_matches_in_dataset == 0:
        reason = "no_matching_tracked_nm_ids"
    else:
        reason = "ok"

    is_tracked_counts: dict[str, int] = {}
    if "is_tracked" in df.columns:
        counts = df["is_tracked"].fillna(False).astype(bool).value_counts(dropna=False)
        is_tracked_counts = {str(key): int(value) for key, value in counts.items()}

    return {
        "metadata_available": tracked_matches_in_dataset > 0,
        "reason": reason,
        "tracked_total": tracked_total,
        "tracked_active_total": tracked_active_total,
        "tracked_matches_in_dataset": tracked_matches_in_dataset,
        "dataset_unique_nm": int(dataset_nm_ids.nunique()),
        "is_tracked_counts": is_tracked_counts,
    }


def build_data_debug_payload(
    df: pd.DataFrame,
    *,
    data_source: str,
    selected_dates: list[date],
    debug_trace: list[dict[str, object]],
    tracked_metadata_state: dict[str, object],
) -> dict[str, object]:
    stage_rows = {str(entry["stage"]): int(entry["rows"]) for entry in debug_trace}
    database_url = os.getenv("DATABASE_URL") or settings.database_url or ""
    db_host = "—"
    if data_source == "db" and database_url:
        try:
            parsed = urlsplit(database_url)
            db_host = parsed.hostname or parsed.netloc or "—"
        except Exception:
            db_host = "invalid"

    return {
        "source": data_source.upper(),
        "db_host": db_host,
        "raw_rows": int(len(df)),
        "date_min": _serialize_debug_date(df["report_date"].min()) if "report_date" in df.columns and not df.empty else None,
        "date_max": _serialize_debug_date(df["report_date"].max()) if "report_date" in df.columns and not df.empty else None,
        "selected_date_min": _serialize_debug_date(min(selected_dates)) if selected_dates else None,
        "selected_date_max": _serialize_debug_date(max(selected_dates)) if selected_dates else None,
        "selected_date_count": int(len(selected_dates)),
        "rows_after_date_filter": stage_rows.get("rows_after_date_filter", 0),
        "rows_after_tracked_filter": stage_rows.get("rows_after_tracked_filter", 0),
        "rows_after_sellout_filter": stage_rows.get("rows_after_sellout_filter", 0),
        "rows_before_export": stage_rows.get("rows_after_all_filters", 0),
        "unique_nm_id": int(df["nm_id"].nunique()) if "nm_id" in df.columns else 0,
        "is_tracked_counts": tracked_metadata_state.get("is_tracked_counts", {}),
        "tracked_metadata_available": bool(tracked_metadata_state.get("metadata_available", False)),
        "tracked_metadata_reason": tracked_metadata_state.get("reason"),
        "tracked_matches_in_dataset": int(tracked_metadata_state.get("tracked_matches_in_dataset", 0)),
    }


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
    started_at = perf_counter()
    data_source = resolve_data_source()
    if data_source == "db":
        if not settings.database_url:
            st.error("DB mode включён, но DATABASE_URL не задан. Переключите STREAMLIT_DATA_SOURCE=csv.")
            st.stop()
        try:
            cache_buster = resolve_db_dataset_cache_buster()
            df = load_prepared_dataset_from_db(cache_buster)
        except Exception as exc:
            logger.exception("Failed to load Streamlit dataset from PostgreSQL")
            st.error(
                "Не удалось загрузить данные из PostgreSQL. "
                "Подробный traceback записан в server logs."
            )
            st.caption(f"DB error: {exc.__class__.__name__}")
            st.stop()
        if df.empty:
            st.warning("В mart_total_report нет строк. Переключите STREAMLIT_DATA_SOURCE=csv или наполните mart.")
            st.stop()
        _log_timing("load_app_dataset", started_at, source="db", rows=len(df))
        return df, "db"

    if not DATASET_PATH.exists():
        st.error("Сначала соберите dataset командой scripts/export_streamlit_v1_dataset.py")
        st.stop()
    df = load_dataset(str(DATASET_PATH), DATASET_PATH.stat().st_mtime)
    _log_timing("load_app_dataset", started_at, source="csv", rows=len(df))
    return df, "csv"


def resolve_streamlit_display_min_date() -> date | None:
    raw_value = (os.getenv(STREAMLIT_DISPLAY_MIN_DATE_ENV_VAR) or "").strip()
    if not raw_value:
        return DEFAULT_STREAMLIT_DISPLAY_MIN_DATE
    try:
        return date.fromisoformat(raw_value)
    except ValueError:
        logger.warning(
            "Invalid %s value %r, falling back to default %s",
            STREAMLIT_DISPLAY_MIN_DATE_ENV_VAR,
            raw_value,
            DEFAULT_STREAMLIT_DISPLAY_MIN_DATE.isoformat(),
        )
        return DEFAULT_STREAMLIT_DISPLAY_MIN_DATE


def build_streamlit_display_min_date_caption(display_min_date: date | None) -> str:
    if display_min_date is None:
        return "Технический минимум отображения: не ограничен"
    return f"Технический минимум отображения: {display_min_date.isoformat()}"


def apply_display_min_date_filter(
    df: pd.DataFrame,
    *,
    date_column: str = "report_date",
    display_min_date: date | None = None,
) -> pd.DataFrame:
    if display_min_date is None:
        display_min_date = resolve_streamlit_display_min_date()
    if display_min_date is None or df.empty or date_column not in df.columns:
        return df

    report_dates = pd.to_datetime(df[date_column], errors="coerce").dt.date
    filtered = df.loc[report_dates.notna() & report_dates.ge(display_min_date)].copy()
    filtered.attrs = getattr(df, "attrs", {}).copy()
    return filtered


def normalize_display_coverage_payload(payload: Any) -> pd.DataFrame | None:
    if payload is None:
        return None
    if isinstance(payload, pd.DataFrame):
        normalized = payload.copy()
    elif isinstance(payload, list):
        normalized = pd.DataFrame(payload)
    elif isinstance(payload, Mapping):
        normalized = pd.DataFrame([payload])
    else:
        return None
    normalized.attrs.clear()
    return normalized


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
def load_wb_site_price_snapshot_from_db(cache_buster: str | None = None) -> pd.DataFrame:
    with session_scope() as session:
        rows = session.execute(
            select(FactWbSitePriceSnapshot).order_by(
                FactWbSitePriceSnapshot.snapshot_date.asc(),
                FactWbSitePriceSnapshot.nm_id.asc(),
            )
        ).scalars().all()
        materialized_rows = [
            {
                "snapshot_at": row.snapshot_at,
                "snapshot_date": row.snapshot_date,
                "nm_id": row.nm_id,
                "item_label": row.item_label,
                "lifecycle_status": row.lifecycle_status,
                "product_url": row.product_url,
                "buyer_visible_price": row.buyer_visible_price,
                "currency": row.currency,
                "price_text_raw": row.price_text_raw,
                "price_extract_source": row.raw_payload.get("price_extract_source") if isinstance(row.raw_payload, dict) else None,
                "availability_status": row.availability_status,
                "fetch_status": row.fetch_status,
                "error": row.error,
                "proxy_used": row.proxy_used,
                "raw_payload": row.raw_payload,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    return pd.DataFrame(materialized_rows)


@st.cache_data(show_spinner=False)
def load_ozon_price_snapshot_from_db(cache_buster: str | None = None) -> pd.DataFrame:
    with session_scope() as session:
        rows = session.execute(
            select(FactOzonPriceSnapshot).order_by(
                FactOzonPriceSnapshot.snapshot_date.asc(),
                FactOzonPriceSnapshot.offer_id.asc(),
            )
        ).scalars().all()
        materialized_rows = [
            {
                "snapshot_at": row.snapshot_at,
                "snapshot_date": row.snapshot_date,
                "offer_id": row.offer_id,
                "product_id": row.product_id,
                "sku": row.sku,
                "name": row.name,
                "seller_status": row.seller_status,
                "stock_total": row.stock_total,
                "seller_price_api": row.seller_price_api,
                "buyer_visible_price_web": row.buyer_visible_price_web,
                "other_bank_price_web": row.other_bank_price_web,
                "old_price_web": row.old_price_web,
                "buyer_regular_price_web": row.buyer_regular_price_web,
                "spp_rub": row.spp_rub,
                "spp_percent": row.spp_percent,
                "final_url": row.final_url,
                "status_api": row.status_api,
                "status_web": row.status_web,
                "error": row.error,
                "loaded_at": row.loaded_at,
            }
            for row in rows
        ]
    return pd.DataFrame(materialized_rows)


@st.cache_data(show_spinner=False)
def load_wb_seller_price_snapshot_from_db(cache_buster: str | None = None) -> pd.DataFrame:
    with session_scope() as session:
        rows = session.execute(
            select(
                FactWbSellerPriceSnapshot.snapshot_date,
                FactWbSellerPriceSnapshot.nm_id,
                func.min(FactWbSellerPriceSnapshot.seller_price).label("wb_seller_price")
            )
            .where(FactWbSellerPriceSnapshot.seller_price > 0)
            .group_by(FactWbSellerPriceSnapshot.snapshot_date, FactWbSellerPriceSnapshot.nm_id)
            .order_by(FactWbSellerPriceSnapshot.snapshot_date.asc(), FactWbSellerPriceSnapshot.nm_id.asc())
        ).all()
        materialized_rows = [
            {
                "snapshot_date": row.snapshot_date,
                "nm_id": row.nm_id,
                "wb_seller_price": row.wb_seller_price,
            }
            for row in rows
        ]
    return pd.DataFrame(materialized_rows)



@st.cache_data(show_spinner=False)
def load_wb_site_price_alert_from_db(cache_buster: str | None = None) -> pd.DataFrame:
    with session_scope() as session:
        rows = session.execute(
            select(FactWbSitePriceAlert).order_by(
                FactWbSitePriceAlert.snapshot_date.asc(),
                FactWbSitePriceAlert.nm_id.asc(),
            )
        ).scalars().all()
        materialized_rows = [
            {
                "snapshot_date": row.snapshot_date,
                "nm_id": row.nm_id,
                "current_price": row.current_price,
                "previous_success_price": row.previous_success_price,
                "price_delta": row.price_delta,
                "alert_status": row.alert_status,
                "created_at": row.created_at,
            }
            for row in rows
        ]
    return pd.DataFrame(materialized_rows)


@st.cache_data(show_spinner=False)
def load_ivan_ads_wide_day_from_db(cache_buster: str | None = None) -> pd.DataFrame:
    with session_scope() as session:
        rows = session.execute(
            select(FactIvanAdsWideDay).order_by(
                FactIvanAdsWideDay.date.asc(),
                FactIvanAdsWideDay.nm_id.asc(),
                FactIvanAdsWideDay.campaign_ref.asc(),
            )
        ).scalars().all()
        materialized_rows = [
            {
                "date": row.date,
                "nm_id": row.nm_id,
                "supplier_article": row.supplier_article,
                "title": row.title,
                "campaign_ref": row.campaign_ref,
                "campaign_name": row.campaign_name,
                "ad_spend": row.ad_spend,
                "ad_atbs": row.ad_atbs,
                "ad_cart_ctr": row.ad_cart_ctr,
                "ad_cost_per_cart": row.ad_cost_per_cart,
                "ad_views": row.ad_views,
                "ad_cpm": row.ad_cpm,
                "data_status": row.data_status,
                "source_status": row.source_status,
                "source_file_name": row.source_file_name,
                "loaded_at": row.loaded_at,
            }
            for row in rows
        ]
    return pd.DataFrame(materialized_rows)


@st.cache_data(show_spinner=False)
def load_ivan_ads_wide_reference_counts_from_db(cache_buster: str | None = None) -> dict[str, int]:
    with session_scope() as session:
        matched_dim_rows = session.execute(
            select(func.count())
            .select_from(FactIvanAdsWideDay)
            .join(DimProduct, DimProduct.nm_id == FactIvanAdsWideDay.nm_id)
        ).scalar_one()
        matched_active_rows = session.execute(
            select(func.count())
            .select_from(FactIvanAdsWideDay)
            .join(
                SettingsProducts,
                (SettingsProducts.nm_id == FactIvanAdsWideDay.nm_id) & (SettingsProducts.active.is_(True)),
            )
        ).scalar_one()
    return {
        "matched_dim_product_rows": int(matched_dim_rows or 0),
        "matched_active_product_rows": int(matched_active_rows or 0),
    }


def build_wb_site_price_monitor_dataframe(
    snapshot_df: pd.DataFrame,
    alert_df: pd.DataFrame,
    tracked_df: pd.DataFrame,
    *,
    snapshot_date: date,
    show_sellout: bool,
    only_problematic: bool,
) -> pd.DataFrame:
    lifecycle_label_map = {
        "active": "Основной",
        "sellout": "Распродажа",
    }
    problem_label_map = {
        WB_SITE_PRICE_ALERT_OK: "Цена без резких изменений",
        WB_SITE_PRICE_ALERT_CHANGED: "Цена изменилась на 50 ₽ или больше",
        WB_SITE_PRICE_ALERT_NO_DATA: "Нет данных по цене",
        WB_SITE_PRICE_ALERT_FAILED: "Ошибка проверки",
    }
    problem_priority = {
        "Цена изменилась на 50 ₽ или больше": 0,
        "Ошибка проверки": 1,
        "WB временно не отдал карточку": 1,
        "Нет данных по цене": 2,
        "Цена без резких изменений": 3,
    }
    lifecycle_priority = {
        "Основной": 0,
        "Распродажа": 1,
    }

    if snapshot_df.empty:
        return pd.DataFrame(
            columns=[
                "Артикул WB",
                "Название",
                "Статус товара",
                "Дата snapshot",
                "Цена покупателя",
                "Текст цены",
                "Источник цены",
                "Статус загрузки",
                "Предыдущая цена",
                "Изменение, ₽",
                "Абс. изменение, ₽",
                "Alert",
                "Причина alert",
                "Ссылка WB",
                "Проблема",
                "Дата/время проверки",
            ]
        )

    snapshots = snapshot_df.copy()
    snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"], errors="coerce").dt.date
    for optional_column in ("price_text_raw", "price_extract_source", "product_url"):
        if optional_column not in snapshots.columns:
            snapshots[optional_column] = pd.NA
    previous_success_history = snapshots[
        snapshots["fetch_status"].astype(str).eq("success")
        & snapshots["buyer_visible_price"].notna()
        & snapshots["snapshot_date"].lt(snapshot_date)
    ].copy()
    if not previous_success_history.empty:
        previous_success_history["snapshot_at"] = pd.to_datetime(previous_success_history["snapshot_at"], errors="coerce")
        latest_success_by_nm = (
            previous_success_history.sort_values(
                by=["nm_id", "snapshot_date", "snapshot_at"],
                ascending=[True, False, False],
                na_position="last",
            )
            .drop_duplicates(subset=["nm_id"], keep="first")[["nm_id", "buyer_visible_price"]]
            .rename(columns={"buyer_visible_price": "_previous_success_price"})
        )
    else:
        latest_success_by_nm = pd.DataFrame(columns=["nm_id", "_previous_success_price"])

    snapshots = snapshots[snapshots["snapshot_date"] == snapshot_date].copy()
    if snapshots.empty:
        return pd.DataFrame(
            columns=[
                "Артикул WB",
                "Название",
                "Статус товара",
                "Дата snapshot",
                "Цена покупателя",
                "Текст цены",
                "Источник цены",
                "Статус загрузки",
                "Предыдущая цена",
                "Изменение, ₽",
                "Абс. изменение, ₽",
                "Alert",
                "Причина alert",
                "Ссылка WB",
                "Проблема",
                "Дата/время проверки",
            ]
        )

    alerts = alert_df.copy()
    if not alerts.empty:
        alerts["snapshot_date"] = pd.to_datetime(alerts["snapshot_date"], errors="coerce").dt.date
        alerts = alerts[alerts["snapshot_date"] == snapshot_date].copy()
        snapshots = snapshots.merge(
            alerts[["snapshot_date", "nm_id", "previous_success_price", "price_delta", "alert_status"]],
            on=["snapshot_date", "nm_id"],
            how="left",
        )
    else:
        snapshots["previous_success_price"] = pd.NA
        snapshots["price_delta"] = pd.NA
        snapshots["alert_status"] = pd.NA

    snapshots = snapshots.merge(latest_success_by_nm, on="nm_id", how="left")

    if not tracked_df.empty:
        tracked_meta = tracked_df[["nm_id", "tracked_label", "lifecycle_status"]].copy()
        snapshots = snapshots.merge(tracked_meta, on="nm_id", how="left", suffixes=("", "_tracked"))
    else:
        snapshots["tracked_label"] = pd.NA
        snapshots["lifecycle_status_tracked"] = pd.NA

    snapshots["Название"] = (
        snapshots["item_label"]
        .where(snapshots["item_label"].notna(), snapshots["tracked_label"])
        .fillna("")
        .astype(str)
        .replace("", pd.NA)
    )
    lifecycle_raw = (
        snapshots["lifecycle_status"]
        .where(snapshots["lifecycle_status"].notna(), snapshots["lifecycle_status_tracked"])
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )
    snapshots["Статус товара"] = lifecycle_raw.map(lambda value: lifecycle_label_map.get(value, "Основной"))

    snapshots["previous_success_price"] = snapshots["previous_success_price"].where(
        snapshots["previous_success_price"].notna(),
        snapshots["_previous_success_price"],
    )
    calculated_delta = snapshots["buyer_visible_price"] - snapshots["previous_success_price"]
    snapshots["price_delta"] = snapshots["price_delta"].where(
        snapshots["price_delta"].notna(),
        calculated_delta,
    )
    snapshots["price_delta_abs"] = snapshots["price_delta"].abs()
    snapshots["is_alert"] = snapshots["alert_status"].astype(str).eq(WB_SITE_PRICE_ALERT_CHANGED)
    snapshots["alert_reason"] = snapshots["alert_status"].where(snapshots["is_alert"], pd.NA)

    def _resolve_problem_label(row: pd.Series) -> str:
        alert_status = row.get("alert_status")
        fetch_status = str(row.get("fetch_status") or "")
        if pd.notna(alert_status) and str(alert_status) == WB_SITE_PRICE_ALERT_CHANGED:
            return problem_label_map.get(str(alert_status), "Ошибка проверки")
        if bool(row.get("is_alert")):
            return problem_label_map[WB_SITE_PRICE_ALERT_CHANGED]
        if fetch_status == "success":
            return problem_label_map[WB_SITE_PRICE_ALERT_OK]
        if fetch_status == "wb_interstitial":
            return "WB временно не отдал карточку"
        if fetch_status == "no_price_data":
            return problem_label_map[WB_SITE_PRICE_ALERT_NO_DATA]
        return problem_label_map[WB_SITE_PRICE_ALERT_FAILED]

    snapshots["Проблема"] = snapshots.apply(_resolve_problem_label, axis=1)
    snapshots["Дата/время проверки"] = pd.to_datetime(snapshots["snapshot_at"], errors="coerce")
    snapshots["_problem_priority"] = snapshots["Проблема"].map(lambda value: problem_priority.get(str(value), 99))
    snapshots["_lifecycle_priority"] = snapshots["Статус товара"].map(lambda value: lifecycle_priority.get(str(value), 99))

    if not show_sellout:
        snapshots = snapshots[snapshots["Статус товара"].ne("Распродажа")].copy()
    if only_problematic:
        snapshots = snapshots[snapshots["is_alert"] | snapshots["Проблема"].ne(problem_label_map[WB_SITE_PRICE_ALERT_OK])].copy()

    snapshots = snapshots.sort_values(
        by=["_lifecycle_priority", "_problem_priority", "Название", "nm_id"],
        ascending=[True, True, True, True],
        na_position="last",
    )

    display_df = snapshots.rename(
        columns={
            "nm_id": "Артикул WB",
            "snapshot_date": "Дата snapshot",
            "buyer_visible_price": "Цена покупателя",
            "price_text_raw": "Текст цены",
            "price_extract_source": "Источник цены",
            "fetch_status": "Статус загрузки",
            "previous_success_price": "Предыдущая цена",
            "price_delta": "Изменение, ₽",
            "price_delta_abs": "Абс. изменение, ₽",
            "is_alert": "Alert",
            "alert_reason": "Причина alert",
            "product_url": "Ссылка WB",
        }
    )[
        [
            "Артикул WB",
            "Название",
            "Статус товара",
            "Дата snapshot",
            "Цена покупателя",
            "Текст цены",
            "Источник цены",
            "Статус загрузки",
            "Предыдущая цена",
            "Изменение, ₽",
            "Абс. изменение, ₽",
            "Alert",
            "Причина alert",
            "Ссылка WB",
            "Проблема",
            "Дата/время проверки",
        ]
    ].reset_index(drop=True)
    display_df.attrs = {}
    return display_df


def process_ozon_snapshot_with_categories(snapshot_df: pd.DataFrame) -> pd.DataFrame:
    from src.ozon.config import load_tracked_articles_with_categories

    if snapshot_df.empty:
        return pd.DataFrame()

    snapshots = snapshot_df.copy()
    snapshots["snapshot_date"] = pd.to_datetime(snapshots["snapshot_date"], errors="coerce").dt.date
    snapshots["snapshot_at"] = pd.to_datetime(snapshots["snapshot_at"], errors="coerce")

    OZON_SKU_MAPPING = {
        # cats7P (Иван)
        "1468642455": "cats7P42-44",
        "1469001166": "cats7P44",
        "1469004334": "cats7P46-48",
        "1469006871": "cats7P48-50",
        "1469009787": "cats7P50",
        "1469020168": "cats7P52-54",
        "1469025956": "cats7P54",
        "2208496198": "cats7P44-46",
        "2208523857": "cats7P50-52",
        "2208566539": "cats7P54-56",
        "3386460980": "cats7P40-42",
        "3386471142": "cats7P38-40",
        "3386477170": "cats7P36-38",
        "3507835267": "cats7P62-64",
        "3507844991": "cats7P64-66",
        "3507852171": "cats7P66-68",

        # competitor or other mapped to cats7P (as per user requests)
        "1825602366": "cats7P42-44",
        "1825602368": "cats7P44",
        "1825602370": "cats7P46-48",
        "1825602376": "cats7P48-50",
        "1825602395": "cats7P50",
        "1825608810": "cats7P52-54",
        "1825602363": "cats7P54",
        "1825602409": "cats7P54-56",

        # AvokaDo (Иван)
        "1456260576": "AvokaDo742-44",
        "1456494260": "AvokaDo744-46",
        "1466830128": "AvokaDo746-48",
        "1466832358": "AvokaDo748-50",
        "1466843663": "AvokaDo750-52",
        "1466862853": "AvokaDo752-54",
        "1467513368": "AvokaDo754-56",
        "1529357364": "AvokaDo740",
        "1538380246": "AvokaDo756-58",
        "2169403112": "AvokaDo740-42",

        # beige (Иван)
        "1477909965": "beige7P42-44",
        "1483240426": "beige7P44-46",
        "1483240398": "beige7P46-48",
        "1483407246": "beige7P48-50",
        "1483407260": "beige7P50-52",
        "1483407243": "beige7P52-54",
        "1483407261": "beige7P54-56",
        "1528888044": "beige7P40-42",

        # white (Иван)
        "1526476714": "white36-38",
        "1526993660": "white38-40",
        "1527043070": "white40-42",
        "1526481636": "white42-44",
        "1527032120": "white44-46",
        "1526963865": "white46-48",
        "1526961386": "white48-50",
        "1526605447": "white50-52",
        "1526612132": "white52-54",
        "1526593951": "white54-56",
        "1526534526": "white56-58",
        "1526534427": "white58-60",

        # Black (Иван)
        "1447571639": "Black5P42-44",
        "1483317248": "Black5P44-46",
        "1483267854": "Black5P46-48",
        "1483267822": "Black5P48-50",
        "1483267793": "Black5P50-52",
        "1483267815": "Black5P52-54",
        "1483293010": "Black5P54-56",
    }

    # Normalize offer_id to string and map using mapping
    snapshots["offer_id_str"] = snapshots["offer_id"].astype(str).str.strip()
    mapped_offer_ids = snapshots["offer_id_str"].map(OZON_SKU_MAPPING)
    snapshots["offer_id"] = mapped_offer_ids.fillna(snapshots["offer_id_str"])

    # Sort so that latest runs come first (descending on snapshot_at)
    snapshots = snapshots.sort_values(
        by=["snapshot_date", "offer_id", "snapshot_at"],
        ascending=[True, True, False]
    )

    # Group by snapshot_date and offer_id, and take the first non-null value for each column
    latest_snapshots = snapshots.groupby(["snapshot_date", "offer_id"], as_index=False).first()

    # Map seller_price_api for cats7P from donor articles (like AvokaDo)
    CATS_DONOR_MAPPING = {
        "cats7P42-44": "AvokaDo742-44",
        "cats7P44": "AvokaDo744-46",
        "cats7P46-48": "AvokaDo746-48",
        "cats7P48-50": "AvokaDo748-50",
        "cats7P50": "AvokaDo750-52",
        "cats7P52-54": "AvokaDo752-54",
        "cats7P54": "AvokaDo754-56",
        "cats7P54-56": "AvokaDo754-56",
    }

    if not latest_snapshots.empty:
        donor_prices = latest_snapshots[
            latest_snapshots["seller_price_api"].notna()
        ].set_index(["snapshot_date", "offer_id"])["seller_price_api"].to_dict()

        def fill_cats_price(row):
            oid = row["offer_id"]
            price = row["seller_price_api"]
            if pd.isna(price) or price is None:
                donor_oid = CATS_DONOR_MAPPING.get(oid)
                if donor_oid:
                    key = (row["snapshot_date"], donor_oid)
                    return donor_prices.get(key, price)
            return price

        latest_snapshots["seller_price_api"] = latest_snapshots.apply(fill_cats_price, axis=1)

        # Recalculate SPP since we now have seller_price_api for cats
        sel_price = pd.to_numeric(latest_snapshots["seller_price_api"], errors="coerce")
        buy_price = pd.to_numeric(latest_snapshots["buyer_regular_price_web"], errors="coerce")

        spp_rub_calc = sel_price - buy_price
        spp_pct_calc = (spp_rub_calc / sel_price) * 100

        if "spp_rub" in latest_snapshots.columns:
            latest_snapshots["spp_rub"] = latest_snapshots["spp_rub"].fillna(spp_rub_calc)
        else:
            latest_snapshots["spp_rub"] = spp_rub_calc

        if "spp_percent" in latest_snapshots.columns:
            latest_snapshots["spp_percent"] = latest_snapshots["spp_percent"].fillna(spp_pct_calc)
        else:
            latest_snapshots["spp_percent"] = spp_pct_calc

    # Drop helper column
    if "offer_id_str" in latest_snapshots.columns:
        latest_snapshots = latest_snapshots.drop(columns=["offer_id_str"])

    # Exclude rows where offer_id is still numeric (purely digits)
    is_numeric = latest_snapshots["offer_id"].astype(str).str.strip().str.isdigit()
    latest_snapshots = latest_snapshots[~is_numeric].copy()

    # Load categories from config
    tracked_list = load_tracked_articles_with_categories()
    if tracked_list:
        tracked_df = pd.DataFrame(tracked_list)
        tracked_df = tracked_df.drop_duplicates(subset=["offer_id"])

        # 1. Try to join by offer_id directly (handling both original textual and mapped textual IDs)
        tracked_df["offer_id_str"] = tracked_df["offer_id"].astype(str).str.strip()
        tracked_df["offer_id_mapped"] = tracked_df["offer_id_str"].map(OZON_SKU_MAPPING).fillna(tracked_df["offer_id_str"])

        cat_df_by_oid = tracked_df[["offer_id_mapped", "category"]].rename(columns={"offer_id_mapped": "offer_id"})
        latest_snapshots = latest_snapshots.merge(cat_df_by_oid, on="offer_id", how="left")

        # 2. As a fallback (especially for test environments), join by snapshot's sku and tracked_df's original offer_id
        if "category" in latest_snapshots.columns:
            latest_snapshots["category_temp"] = latest_snapshots["category"]
            latest_snapshots = latest_snapshots.drop(columns=["category"])
        else:
            latest_snapshots["category_temp"] = np.nan if "np" in globals() else pd.NA

        latest_snapshots["sku_str"] = latest_snapshots["sku"].dropna().astype(str).str.strip()
        cat_df_by_sku = tracked_df[["offer_id_str", "category"]].rename(columns={"offer_id_str": "sku_str", "category": "category_by_sku"})
        latest_snapshots = latest_snapshots.merge(cat_df_by_sku, on="sku_str", how="left")

        if "category_by_sku" in latest_snapshots.columns:
            latest_snapshots["category"] = latest_snapshots["category_temp"].fillna(latest_snapshots["category_by_sku"])
            latest_snapshots = latest_snapshots.drop(columns=["category_by_sku"])
        else:
            latest_snapshots["category"] = latest_snapshots["category_temp"]

        if "category_temp" in latest_snapshots.columns:
            latest_snapshots = latest_snapshots.drop(columns=["category_temp"])
        if "sku_str" in latest_snapshots.columns:
            latest_snapshots = latest_snapshots.drop(columns=["sku_str"])

        if "category" in latest_snapshots.columns:
            latest_snapshots["category"] = latest_snapshots["category"].fillna("без категории")
        else:
            latest_snapshots["category"] = "без категории"
    else:
        latest_snapshots["category"] = "без категории"

    # Category heuristic fallback to avoid "без категории" for known seller articles
    def resolve_category(row):
        cat = str(row.get("category", "")).strip()
        if cat and cat != "без категории":
            return cat
        name = str(row.get("name", "")).lower()
        oid = str(row.get("offer_id", "")).lower()
        if "детск" in name or "kids" in name or "детск" in oid or "kids" in oid:
            return "детские трусы"
        elif "футболк" in name or "tshirt" in name or "t-shirt" in name or "tshirt" in oid or "shirt" in oid:
            return "футболки"
        elif "трусы" in name or "слип" in name or "trus" in oid or "slip" in oid or any(brand in oid for brand in ["avokado", "beige", "white", "cats", "black", "grey", "peach", "pink", "mint"]):
            return "женские трусы"
        return "без категории"

    if not latest_snapshots.empty:
        latest_snapshots["category"] = latest_snapshots.apply(resolve_category, axis=1)

    return latest_snapshots


def build_ozon_price_monitor_dataframe(
    snapshot_df: pd.DataFrame,
    *,
    snapshot_date: date,
) -> pd.DataFrame:
    from src.ozon.config import load_tracked_articles_with_categories
    tracked_list = load_tracked_articles_with_categories()
    
    cols = [
        "Артикул Ozon",
        "Категория",
        "Цена Ozon",
        "Предыдущая цена",
        "Изменение, ₽",
        "Alert",
        "Ссылка на карточку",
    ]

    if snapshot_df.empty:
        if tracked_list:
            display_df = pd.DataFrame(tracked_list)
            display_df = display_df.rename(columns={"offer_id": "Артикул Ozon", "category": "Категория"})
            display_df["Цена Ozon"] = None
            display_df["Предыдущая цена"] = None
            display_df["Изменение, ₽"] = None
            display_df["Alert"] = False
            display_df["Ссылка на карточку"] = ""
            return display_df[cols]
        return pd.DataFrame(columns=cols)

    expanded_all = process_ozon_snapshot_with_categories(snapshot_df)
    if expanded_all.empty:
        return pd.DataFrame(columns=cols)

    # Filter to selected date
    expanded = expanded_all[expanded_all["snapshot_date"] == snapshot_date].copy()

    # Find the latest successful price check before the selected snapshot date
    previous_success_history = expanded_all[
        expanded_all["status_web"].astype(str).eq("ok")
        & expanded_all["buyer_regular_price_web"].notna()
        & expanded_all["snapshot_date"].lt(snapshot_date)
    ].copy()

    if not previous_success_history.empty:
        previous_success_history["snapshot_at"] = pd.to_datetime(previous_success_history["snapshot_at"], errors="coerce")
        latest_success_by_offer = (
            previous_success_history.sort_values(
                by=["offer_id", "snapshot_date", "snapshot_at"],
                ascending=[True, False, False],
                na_position="last",
            )
            .drop_duplicates(subset=["offer_id"], keep="first")[["offer_id", "buyer_regular_price_web"]]
            .rename(columns={"buyer_regular_price_web": "_previous_success_price"})
        )
    else:
        latest_success_by_offer = pd.DataFrame(columns=["offer_id", "_previous_success_price"])

    expanded = expanded.merge(latest_success_by_offer, on="offer_id", how="left")

    curr_price = pd.to_numeric(expanded["buyer_regular_price_web"], errors="coerce")
    prev_price = pd.to_numeric(expanded["_previous_success_price"], errors="coerce")
    
    price_delta = curr_price - prev_price
    expanded["price_delta"] = price_delta
    expanded["price_delta_abs"] = price_delta.abs()
    expanded["Alert"] = expanded["price_delta_abs"] >= 50

    display_df = expanded.rename(
        columns={
            "offer_id": "Артикул Ozon",
            "category": "Категория",
            "buyer_regular_price_web": "Цена Ozon",
            "_previous_success_price": "Предыдущая цена",
            "price_delta": "Изменение, ₽",
            "final_url": "Ссылка на карточку",
        }
    )

    display_df = display_df[[c for c in cols if c in display_df.columns]].copy()
    return display_df.reset_index(drop=True)


def style_ozon_site_price_monitor_table(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    safe_df = sanitize_dataframe_for_streamlit_display(
        df,
        numeric_columns={"Цена Ozon", "Предыдущая цена", "Изменение, ₽"},
    )

    def row_style(row: pd.Series) -> list[str]:
        if bool(row.get("Alert")):
            return ["background-color: #fff7ed;" for _ in row.index]
        return ["" for _ in row.index]

    def delta_style(value: object) -> str:
        if pd.isna(value):
            return ""
        numeric_value = float(value)
        if numeric_value > 0:
            return "color: #b91c1c; font-weight: 600;"
        if numeric_value < 0:
            return "color: #166534; font-weight: 600;"
        return ""

    styler = safe_df.style.apply(row_style, axis=1)
    if "Изменение, ₽" in safe_df.columns:
        styler = styler.map(delta_style, subset=["Изменение, ₽"])
    return styler




def build_wb_site_price_monitor_visibility_summary(
    snapshot_df: pd.DataFrame,
    tracked_df: pd.DataFrame,
    *,
    snapshot_date: date,
    show_sellout: bool,
    visible_rows: int,
) -> dict[str, Any]:
    if snapshot_df.empty:
        return {
            "checked_products": 0,
            "prices_received": 0,
            "rows_written_to_db": 0,
            "rows_visible_in_streamlit": 0,
            "hidden_rows_count": 0,
            "hidden_rows_reason": None,
            "hidden_nm_ids": [],
        }

    current_snapshot = snapshot_df.copy()
    current_snapshot["snapshot_date"] = pd.to_datetime(current_snapshot["snapshot_date"], errors="coerce").dt.date
    current_snapshot = current_snapshot[current_snapshot["snapshot_date"] == snapshot_date].copy()

    if current_snapshot.empty:
        return {
            "checked_products": 0,
            "prices_received": 0,
            "rows_written_to_db": 0,
            "rows_visible_in_streamlit": visible_rows,
            "hidden_rows_count": 0,
            "hidden_rows_reason": None,
            "hidden_nm_ids": [],
        }

    if not tracked_df.empty:
        tracked_meta = tracked_df[["nm_id", "lifecycle_status"]].copy()
        current_snapshot = current_snapshot.merge(
            tracked_meta.rename(columns={"lifecycle_status": "_tracked_lifecycle_status"}),
            on="nm_id",
            how="left",
        )
    else:
        current_snapshot["_tracked_lifecycle_status"] = pd.NA

    lifecycle_raw = (
        current_snapshot["lifecycle_status"]
        .where(current_snapshot["lifecycle_status"].notna(), current_snapshot["_tracked_lifecycle_status"])
        .fillna("")
        .astype(str)
        .str.strip()
        .str.lower()
    )
    sellout_mask = lifecycle_raw.eq("sellout")
    hidden_nm_ids = sorted(current_snapshot.loc[sellout_mask, "nm_id"].dropna().astype(int).unique().tolist())
    hidden_rows_count = int(sellout_mask.sum()) if not show_sellout else 0

    return {
        "checked_products": int(len(current_snapshot)),
        "prices_received": int(current_snapshot["fetch_status"].astype(str).eq("success").sum()),
        "rows_written_to_db": int(len(current_snapshot)),
        "rows_visible_in_streamlit": int(visible_rows),
        "hidden_rows_count": hidden_rows_count,
        "hidden_rows_reason": "filtered_by_sellout" if hidden_rows_count else None,
        "hidden_nm_ids": hidden_nm_ids if hidden_rows_count else [],
    }


def style_wb_site_price_monitor_table(df: pd.DataFrame) -> pd.io.formats.style.Styler:
    safe_df = sanitize_dataframe_for_streamlit_display(
        df,
        numeric_columns={"Текущая цена", "Предыдущая цена", "Изменение, ₽"},
    )

    def row_style(row: pd.Series) -> list[str]:
        if bool(row.get("Alert")):
            return ["background-color: #fff7ed;" for _ in row.index]
        return ["" for _ in row.index]

    def delta_style(value: object) -> str:
        if pd.isna(value):
            return ""
        numeric_value = float(value)
        if numeric_value > 0:
            return "color: #b91c1c; font-weight: 600;"
        if numeric_value < 0:
            return "color: #166534; font-weight: 600;"
        return ""

    styler = safe_df.style.apply(row_style, axis=1)
    if "Изменение, ₽" in safe_df.columns:
        styler = styler.map(delta_style, subset=["Изменение, ₽"])
    return styler


def render_wb_price_monitor_content(cache_buster: str | None) -> None:
    snapshot_df = load_wb_site_price_snapshot_from_db(cache_buster)
    alert_df = load_wb_site_price_alert_from_db(cache_buster)
    if snapshot_df.empty:
        st.warning("В `fact_wb_site_price_snapshot` пока нет строк.")
        return

    snapshot_dates = sorted(pd.to_datetime(snapshot_df["snapshot_date"], errors="coerce").dropna().dt.date.unique().tolist())
    if not snapshot_dates:
        st.warning("В `fact_wb_site_price_snapshot` нет валидных дат snapshot.")
        return

    tracked_df = load_tracked_products()
    selected_snapshot_date = st.selectbox("Дата проверки цен", options=snapshot_dates, index=len(snapshot_dates) - 1)
    filter_cols = st.columns(1)
    show_sellout = filter_cols[0].checkbox("Показывать распродажные товары", value=True, key="wb_site_price_show_sellout")

    current_snapshot = snapshot_df.copy()
    current_snapshot["snapshot_date"] = pd.to_datetime(current_snapshot["snapshot_date"], errors="coerce").dt.date
    current_snapshot = current_snapshot[current_snapshot["snapshot_date"] == selected_snapshot_date].copy()
    current_alerts = alert_df.copy()
    if not current_alerts.empty:
        current_alerts["snapshot_date"] = pd.to_datetime(current_alerts["snapshot_date"], errors="coerce").dt.date
        current_alerts = current_alerts[current_alerts["snapshot_date"] == selected_snapshot_date].copy()

    summary_cols = st.columns(4)
    success_count = int(current_snapshot["fetch_status"].astype(str).eq("success").sum())
    no_price_count = int(current_snapshot["fetch_status"].astype(str).eq("no_price_data").sum())
    error_count = int(current_snapshot["fetch_status"].astype(str).isin(["wb_interstitial", "blocked", "timeout", "failed"]).sum())
    alerts_count = int(current_alerts["alert_status"].astype(str).eq(WB_SITE_PRICE_ALERT_CHANGED).sum()) if not current_alerts.empty else 0
    summary_cols[0].metric("Товаров проверено", f"{len(current_snapshot):,}".replace(",", " "))
    summary_cols[1].metric("Цен получено", f"{success_count:,}".replace(",", " "))
    summary_cols[2].metric("Ошибок проверки", f"{error_count + no_price_count:,}".replace(",", " "))
    summary_cols[3].metric("Изменений от 50 ₽", f"{alerts_count:,}".replace(",", " "))

    display_df = build_wb_site_price_monitor_dataframe(
        snapshot_df,
        alert_df,
        tracked_df,
        snapshot_date=selected_snapshot_date,
        show_sellout=show_sellout,
        only_problematic=False,
    )
    visibility_summary = build_wb_site_price_monitor_visibility_summary(
        snapshot_df,
        tracked_df,
        snapshot_date=selected_snapshot_date,
        show_sellout=show_sellout,
        visible_rows=len(display_df),
    )
    compact_columns = [
        "Артикул WB",
        "Название",
        "Статус товара",
        "Цена покупателя",
        "Предыдущая цена",
        "Изменение, ₽",
        "Alert",
        "Ссылка WB",
    ]
    alert_columns = [
        "Артикул WB",
        "Название",
        "Цена покупателя",
        "Предыдущая цена",
        "Изменение, ₽",
        "Проблема",
        "Ссылка WB",
    ]
    technical_columns = [
        "Артикул WB",
        "Название",
        "Статус товара",
        "Дата snapshot",
        "Цена покупателя",
        "Текст цены",
        "Источник цены",
        "Статус загрузки",
        "Предыдущая цена",
        "Изменение, ₽",
        "Абс. изменение, ₽",
        "Alert",
        "Причина alert",
        "Проблема",
        "Дата/время проверки",
        "Ссылка WB",
    ]

    compact_df = display_df[[column for column in compact_columns if column in display_df.columns]].copy()
    compact_df = compact_df.rename(columns={"Цена покупателя": "Текущая цена"})
    alert_display_df = display_df[display_df["Alert"]].copy()
    alert_display_df = alert_display_df[[column for column in alert_columns if column in alert_display_df.columns]].copy()
    alert_display_df = alert_display_df.rename(columns={"Цена покупателя": "Текущая цена"})
    technical_df = display_df[[column for column in technical_columns if column in display_df.columns]].copy()
    technical_df = technical_df.rename(columns={"Цена покупателя": "Текущая цена"})

    with st.expander("Диагностика видимости", expanded=visibility_summary["hidden_rows_count"] > 0):
        diagnostic_cols = st.columns(5)
        diagnostic_cols[0].metric("Проверено ботом", f"{visibility_summary['checked_products']:,}".replace(",", " "))
        diagnostic_cols[1].metric("Цен получено", f"{visibility_summary['prices_received']:,}".replace(",", " "))
        diagnostic_cols[2].metric("Строк в БД", f"{visibility_summary['rows_written_to_db']:,}".replace(",", " "))
        diagnostic_cols[3].metric(
            "Видно в Streamlit",
            f"{visibility_summary['rows_visible_in_streamlit']:,}".replace(",", " "),
        )
        diagnostic_cols[4].metric("Скрыто строк", f"{visibility_summary['hidden_rows_count']:,}".replace(",", " "))
        if visibility_summary["hidden_rows_reason"] == "filtered_by_sellout":
            hidden_nm_ids = ", ".join(str(value) for value in visibility_summary["hidden_nm_ids"])
            st.info(
                "Часть строк скрыта фильтром «Показывать распродажные товары». "
                f"Скрытые nm_id: {hidden_nm_ids}"
            )

    st.markdown("**Все проверенные цены за дату**")
    safe_st_dataframe(
        style_wb_site_price_monitor_table(compact_df),
        width="stretch",
        hide_index=True,
        column_config={
            "Текущая цена": st.column_config.NumberColumn("Текущая цена", format="%.2f"),
            "Предыдущая цена": st.column_config.NumberColumn("Предыдущая цена", format="%.2f"),
            "Изменение, ₽": st.column_config.NumberColumn("Изменение, ₽", format="%.2f"),
            "Alert": st.column_config.CheckboxColumn("Alert"),
            "Ссылка WB": st.column_config.LinkColumn("Ссылка WB", display_text="Карточка WB"),
        },
    )
    st.markdown("**Только скачки цены / alerts**")
    if alert_display_df.empty:
        st.info("За выбранную дату скачков цены от 50 ₽ не найдено.")
    else:
        safe_st_dataframe(
            style_wb_site_price_monitor_table(alert_display_df),
            width="stretch",
            hide_index=True,
            column_config={
                "Текущая цена": st.column_config.NumberColumn("Текущая цена", format="%.2f"),
                "Предыдущая цена": st.column_config.NumberColumn("Предыдущая цена", format="%.2f"),
                "Изменение, ₽": st.column_config.NumberColumn("Изменение, ₽", format="%.2f"),
                "Ссылка WB": st.column_config.LinkColumn("Ссылка WB", display_text="Карточка WB"),
            },
        )
    with st.expander("Показать технические детали"):
        safe_st_dataframe(
            technical_df,
            width="stretch",
            hide_index=True,
            column_config={
                "Дата snapshot": st.column_config.DateColumn("Дата snapshot", format="DD.MM.YYYY"),
                "Текущая цена": st.column_config.NumberColumn("Текущая цена", format="%.2f"),
                "Предыдущая цена": st.column_config.NumberColumn("Предыдущая цена", format="%.2f"),
                "Изменение, ₽": st.column_config.NumberColumn("Изменение, ₽", format="%.2f"),
                "Абс. изменение, ₽": st.column_config.NumberColumn("Абс. изменение, ₽", format="%.2f"),
                "Alert": st.column_config.CheckboxColumn("Alert"),
                "Ссылка WB": st.column_config.LinkColumn("Ссылка WB", display_text="Карточка WB"),
                "Дата/время проверки": st.column_config.DatetimeColumn("Дата/время проверки", format="DD.MM.YYYY HH:mm"),
            },
        )


def render_ozon_price_monitor_content(cache_buster: str | None) -> None:
    snapshot_df = load_ozon_price_snapshot_from_db(cache_buster)
    if snapshot_df.empty:
        st.warning("В `fact_ozon_price_snapshot` пока нет строк.")
        return

    snapshot_dates = sorted(pd.to_datetime(snapshot_df["snapshot_date"], errors="coerce").dropna().dt.date.unique().tolist())
    if not snapshot_dates:
        st.warning("В `fact_ozon_price_snapshot` нет валидных дат snapshot.")
        return

    selected_snapshot_date = st.selectbox("Дата проверки цен Ozon", options=snapshot_dates, index=len(snapshot_dates) - 1, key="ozon_site_price_date_select")

    current_snapshot = snapshot_df.copy()
    current_snapshot["snapshot_date"] = pd.to_datetime(current_snapshot["snapshot_date"], errors="coerce").dt.date
    current_snapshot = current_snapshot[current_snapshot["snapshot_date"] == selected_snapshot_date].copy()

    # Prepare Ozon monitor dataframe
    display_df = build_ozon_price_monitor_dataframe(
        snapshot_df,
        snapshot_date=selected_snapshot_date,
    )

    # Render summary metrics
    summary_cols = st.columns(4)
    success_count = int(current_snapshot["status_web"].astype(str).eq("ok").sum())
    error_count = int(current_snapshot["status_web"].astype(str).ne("ok").sum())
    alerts_count = int(display_df["Alert"].sum()) if not display_df.empty else 0
    
    summary_cols[0].metric("Товаров проверено", f"{len(current_snapshot):,}".replace(",", " "))
    summary_cols[1].metric("Цен получено", f"{success_count:,}".replace(",", " "))
    summary_cols[2].metric("Ошибок проверки", f"{error_count:,}".replace(",", " "))
    summary_cols[3].metric("Изменений от 50 ₽", f"{alerts_count:,}".replace(",", " "))

    st.markdown("**Все проверенные цены за дату**")
    
    compact_columns = [
        "Артикул Ozon",
        "Категория",
        "Цена Ozon",
        "Предыдущая цена",
        "Изменение, ₽",
        "Alert",
        "Ссылка на карточку",
    ]
    
    compact_df = display_df[[column for column in compact_columns if column in display_df.columns]].copy()
    
    safe_st_dataframe(
        style_ozon_site_price_monitor_table(compact_df),
        width="stretch",
        hide_index=True,
        column_config={
            "Цена Ozon": st.column_config.NumberColumn("Цена Ozon", format="%.2f"),
            "Предыдущая цена": st.column_config.NumberColumn("Предыдущая цена", format="%.2f"),
            "Изменение, ₽": st.column_config.NumberColumn("Изменение, ₽", format="%.2f"),
            "Alert": st.column_config.CheckboxColumn("Alert"),
            "Ссылка на карточку": st.column_config.LinkColumn("Ссылка на карточку", display_text="Карточка Ozon"),
        },
    )

    st.markdown("**Только скачки цены / alerts**")
    alert_display_df = display_df[display_df["Alert"]].copy()
    if alert_display_df.empty:
        st.info("За выбранную дату скачков цены от 50 ₽ не найдено.")
    else:
        alert_columns = [
            "Артикул Ozon",
            "Категория",
            "Цена Ozon",
            "Предыдущая цена",
            "Изменение, ₽",
            "Ссылка на карточку",
        ]
        alert_compact_df = alert_display_df[[column for column in alert_columns if column in alert_display_df.columns]].copy()
        safe_st_dataframe(
            style_ozon_site_price_monitor_table(alert_compact_df),
            width="stretch",
            hide_index=True,
            column_config={
                "Цена Ozon": st.column_config.NumberColumn("Цена Ozon", format="%.2f"),
                "Предыдущая цена": st.column_config.NumberColumn("Предыдущая цена", format="%.2f"),
                "Изменение, ₽": st.column_config.NumberColumn("Изменение, ₽", format="%.2f"),
                "Ссылка на карточку": st.column_config.LinkColumn("Ссылка на карточку", display_text="Карточка Ozon"),
            },
        )


def render_ozon_spp_content(cache_buster: str | None) -> None:
    snapshot_df = load_ozon_price_snapshot_from_db(cache_buster)
    if snapshot_df.empty:
        st.warning("В `fact_ozon_price_snapshot` пока нет строк.")
        return

    processed_df = process_ozon_snapshot_with_categories(snapshot_df)
    if processed_df.empty:
        st.warning("В `fact_ozon_price_snapshot` нет данных.")
        return

    all_dates = sorted(processed_df["snapshot_date"].dropna().unique().tolist())
    if not all_dates:
        st.warning("В `fact_ozon_price_snapshot` нет дат snapshot.")
        return

    min_date = all_dates[0]
    max_date = all_dates[-1]

    # Date range selector
    date_range = st.date_input(
        "Период дат",
        value=[min_date, max_date],
        min_value=min_date,
        max_value=max_date,
        key="ozon_spp_date_range",
    )

    filtered_df = processed_df.copy()

    if isinstance(date_range, (list, tuple)) and len(date_range) == 2:
        start_dt, end_dt = date_range
        filtered_df = filtered_df[(filtered_df["snapshot_date"] >= start_dt) & (filtered_df["snapshot_date"] <= end_dt)]
    elif isinstance(date_range, date):
        filtered_df = filtered_df[filtered_df["snapshot_date"] == date_range]

    if filtered_df.empty:
        st.info("Нет данных за выбранный период.")
        return

    filtered_df = filtered_df.sort_values(by=["snapshot_date", "category", "offer_id"], ascending=[False, True, True])

    spp_df = filtered_df[[
        "snapshot_date",
        "offer_id",
        "category",
        "seller_price_api",
        "buyer_regular_price_web",
        "spp_rub",
        "spp_percent",
        "final_url",
    ]].copy()

    spp_df = spp_df.rename(
        columns={
            "snapshot_date": "Дата",
            "offer_id": "Артикул Ozon",
            "category": "Категория",
            "seller_price_api": "Цена продавца",
            "buyer_regular_price_web": "Видимая цена Ozon",
            "spp_rub": "СПП, ₽",
            "spp_percent": "СПП, %",
            "final_url": "Ссылка",
        }
    )

    def style_spp_table(df: pd.DataFrame) -> pd.io.formats.style.Styler:
        safe_df = sanitize_dataframe_for_streamlit_display(
            df,
            numeric_columns={"Цена продавца", "Видимая цена Ozon", "СПП, ₽", "СПП, %"},
        )
        
        def spp_row_style(row: pd.Series) -> list[str]:
            val = row.get("СПП, %")
            if pd.notna(val) and float(val) > 20.0:
                return ["background-color: #f0fdf4;" for _ in row.index]
            return ["" for _ in row.index]

        return safe_df.style.apply(spp_row_style, axis=1)

    safe_st_dataframe(
        style_spp_table(spp_df),
        width="stretch",
        hide_index=True,
        column_config={
            "Дата": st.column_config.DateColumn("Дата", format="DD.MM.YYYY"),
            "Цена продавца": st.column_config.NumberColumn("Цена продавца", format="%.2f"),
            "Видимая цена Ozon": st.column_config.NumberColumn("Видимая цена Ozon", format="%.2f"),
            "СПП, ₽": st.column_config.NumberColumn("СПП, ₽", format="%.2f"),
            "СПП, %": st.column_config.NumberColumn("СПП, %", format="%.2f"),
            "Ссылка": st.column_config.LinkColumn("Ссылка", display_text="Карточка Ozon"),
        },
    )


def render_wb_site_price_tab(data_source: str) -> None:
    if data_source != "db":
        st.info("Мониторинг цен доступен только в режиме PostgreSQL.")
        return

    cache_buster = resolve_db_dataset_cache_buster()

    marketplace_tabs = st.tabs(["Wildberries", "Ozon"])

    with marketplace_tabs[0]:
        render_wb_price_monitor_content(cache_buster)

    with marketplace_tabs[1]:
        ozon_sub_tabs = st.tabs(["Мониторинг цен Ozon", "СПП Ozon"])
        with ozon_sub_tabs[0]:
            render_ozon_price_monitor_content(cache_buster)
        with ozon_sub_tabs[1]:
            render_ozon_spp_content(cache_buster)


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
def load_stock_warehouse_snapshot_from_db(cache_buster: str | None = None) -> pd.DataFrame:
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


@st.cache_data(show_spinner=False)
def load_settings_product_query_groups_from_db(cache_buster: str | None = None) -> pd.DataFrame:
    try:
        with session_scope() as session:
            rows = session.execute(
                select(
                    SettingsProducts.nm_id,
                    SettingsProducts.query_group,
                    SettingsProducts.supplier_article,
                    SettingsProducts.title,
                ).order_by(SettingsProducts.nm_id.asc())
            ).all()
    except Exception:
        logger.exception("Failed to load query_group from settings_products for stock warehouse tab")
        return pd.DataFrame(columns=["nm_id", "query_group", "supplier_article", "title"])
    return pd.DataFrame(
        [
            {
                "nm_id": row.nm_id,
                "query_group": row.query_group,
                "supplier_article": row.supplier_article,
                "title": row.title,
            }
            for row in rows
        ]
    )


@st.cache_data(show_spinner=False)
def load_entry_point_day_range_from_db(
    report_dates: tuple[date, ...],
    nm_ids: tuple[int, ...],
    cache_buster: str | None = None,
) -> pd.DataFrame:
    columns = [
        "date",
        "nm_id",
        "section",
        "entry_point",
        "supplier_article",
        "title",
        "subject",
        "brand",
        "impressions",
        "card_clicks",
        "cart_count",
        "order_count",
    ]
    if not report_dates or not nm_ids:
        return pd.DataFrame(columns=columns)
    try:
        with session_scope() as session:
            rows = session.execute(
                select(
                    FactEntryPointDay.date,
                    FactEntryPointDay.nm_id,
                    FactEntryPointDay.section,
                    FactEntryPointDay.entry_point,
                    FactEntryPointDay.supplier_article,
                    FactEntryPointDay.title,
                    FactEntryPointDay.subject,
                    FactEntryPointDay.brand,
                    FactEntryPointDay.impressions,
                    FactEntryPointDay.card_clicks,
                    FactEntryPointDay.cart_count,
                    FactEntryPointDay.order_count,
                )
                .where(
                    FactEntryPointDay.date.in_(report_dates),
                    FactEntryPointDay.nm_id.in_(nm_ids),
                )
                .order_by(
                    FactEntryPointDay.date.asc(),
                    FactEntryPointDay.nm_id.asc(),
                    FactEntryPointDay.section.asc(),
                    FactEntryPointDay.entry_point.asc(),
                )
            ).all()
    except Exception:
        logger.exception("Failed to load fact_entry_point_day for entry point analytics tab")
        return pd.DataFrame(columns=columns)

    return pd.DataFrame(
        [
            {
                "date": row.date,
                "nm_id": row.nm_id,
                "section": row.section,
                "entry_point": row.entry_point,
                "supplier_article": row.supplier_article,
                "title": row.title,
                "subject": row.subject,
                "brand": row.brand,
                "impressions": row.impressions,
                "card_clicks": row.card_clicks,
                "cart_count": row.cart_count,
                "order_count": row.order_count,
            }
            for row in rows
        ],
        columns=columns,
    )


@st.cache_data(show_spinner=False)
def load_entry_point_spend_range_from_db(
    report_dates: tuple[date, ...],
    nm_ids: tuple[int, ...],
    cache_buster: str | None = None,
) -> pd.DataFrame:
    columns = ["date", "nm_id", "ad_campaign_spend_total"]
    if not report_dates or not nm_ids:
        return pd.DataFrame(columns=columns)
    try:
        with session_scope() as session:
            rows = session.execute(
                select(
                    MartTotalReport.report_date,
                    MartTotalReport.nm_id,
                    MartTotalReport.ad_campaign_spend_total,
                )
                .where(
                    MartTotalReport.report_date.in_(report_dates),
                    MartTotalReport.nm_id.in_(nm_ids),
                )
                .order_by(
                    MartTotalReport.report_date.asc(),
                    MartTotalReport.nm_id.asc(),
                )
            ).all()
    except Exception:
        logger.exception("Failed to load mart_total_report spend for entry point economics")
        return pd.DataFrame(columns=columns)

    return pd.DataFrame(
        [
            {
                "date": row.report_date,
                "nm_id": row.nm_id,
                "ad_campaign_spend_total": row.ad_campaign_spend_total,
            }
            for row in rows
        ],
        columns=columns,
    )


def build_entry_point_metadata(filtered: pd.DataFrame) -> pd.DataFrame:
    columns = ["nm_id", "supplier_article", "title", "brand", "subject", "band_name"]
    if filtered.empty or "nm_id" not in filtered.columns:
        return pd.DataFrame(columns=columns)

    metadata = filtered.copy()
    if "band_name" not in metadata.columns:
        metadata = apply_product_bands(metadata)

    for column in columns:
        if column not in metadata.columns:
            metadata[column] = pd.NA
    if "report_date" in metadata.columns:
        metadata["report_date"] = pd.to_datetime(metadata["report_date"], errors="coerce").dt.date
        metadata = metadata.sort_values(["report_date", "nm_id"], ascending=[False, True], na_position="last")

    metadata["nm_id"] = pd.to_numeric(metadata["nm_id"], errors="coerce")
    metadata = metadata.dropna(subset=["nm_id"]).copy()
    metadata["nm_id"] = metadata["nm_id"].astype(int)
    return metadata[columns].drop_duplicates(subset=["nm_id"], keep="first").reset_index(drop=True)


def classify_entry_point_bucket(section: object, entry_point: object) -> str:
    combined = " ".join(
        part.strip().lower()
        for part in (str(section or ""), str(entry_point or ""))
        if str(part or "").strip()
    )
    if any(keyword in combined for keyword in ("поиск", "search", "выдача")):
        return ENTRY_POINT_GROUP_SEARCH
    if any(keyword in combined for keyword in ("каталог", "catalog", "катег", "category")):
        return ENTRY_POINT_GROUP_CATALOG
    if any(
        keyword in combined
        for keyword in (
            "рекомен",
            "полк",
            "похож",
            "similar",
            "recommend",
            "related",
            "с этим товаром",
            "смотрите также",
            "подборк",
        )
    ):
        return ENTRY_POINT_GROUP_RECOMMENDATION
    return ENTRY_POINT_GROUP_OTHER


def _compute_entry_point_conversion(numerator: pd.Series, denominator: pd.Series) -> pd.Series:
    numerator_numeric = pd.to_numeric(numerator, errors="coerce")
    denominator_numeric = pd.to_numeric(denominator, errors="coerce")
    result = (numerator_numeric / denominator_numeric) * 100.0
    return result.where(denominator_numeric.gt(0))


def _apply_entry_point_cart_conversion_fallback(
    grouped: pd.DataFrame,
    *,
    group_columns: list[str],
) -> pd.DataFrame:
    if grouped.empty:
        grouped[ENTRY_POINT_LABEL_CART_CONVERSION] = pd.Series(dtype="float64")
        return grouped

    result = grouped.copy()
    result[ENTRY_POINT_LABEL_CART_CONVERSION] = _compute_entry_point_conversion(
        result[ENTRY_POINT_LABEL_CART_COUNT],
        result[ENTRY_POINT_LABEL_CARD_CLICKS],
    )
    result["__entry_point_conversion_fallback_7d"] = False
    base_group_columns = [column for column in group_columns if column != ENTRY_POINT_LABEL_DATE]

    def _apply_group_fallback(group_df: pd.DataFrame) -> pd.DataFrame:
        local = group_df.sort_values(ENTRY_POINT_LABEL_DATE, kind="stable").copy()
        local[ENTRY_POINT_LABEL_DATE] = pd.to_datetime(local[ENTRY_POINT_LABEL_DATE], errors="coerce")
        local["__cart_numeric"] = pd.to_numeric(local[ENTRY_POINT_LABEL_CART_COUNT], errors="coerce")
        local["__clicks_numeric"] = pd.to_numeric(local[ENTRY_POINT_LABEL_CARD_CLICKS], errors="coerce")

        rolling_indexed = local.set_index(ENTRY_POINT_LABEL_DATE)
        rolling_cart = rolling_indexed["__cart_numeric"].rolling("7D", min_periods=1).sum()
        rolling_clicks = rolling_indexed["__clicks_numeric"].rolling("7D", min_periods=1).sum()
        rolling_conversion = (rolling_cart / rolling_clicks) * 100.0
        rolling_conversion = rolling_conversion.where(rolling_clicks.gt(0))

        fallback_mask = local["__cart_numeric"].lt(50).fillna(False)
        local[ENTRY_POINT_LABEL_CART_CONVERSION] = local[ENTRY_POINT_LABEL_CART_CONVERSION].where(
            ~fallback_mask,
            rolling_conversion.to_numpy(),
        )
        local["__entry_point_conversion_fallback_7d"] = fallback_mask
        local[ENTRY_POINT_LABEL_DATE] = local[ENTRY_POINT_LABEL_DATE].dt.date
        return local.drop(columns=["__cart_numeric", "__clicks_numeric"])

    if base_group_columns:
        grouped_frames = [
            _apply_group_fallback(group_df)
            for _group_key, group_df in result.groupby(base_group_columns, dropna=False, sort=False)
        ]
        return pd.concat(grouped_frames, ignore_index=True) if grouped_frames else result
    return _apply_group_fallback(result).reset_index(drop=True)


def _prepare_entry_point_economics_source(
    entry_df: pd.DataFrame,
    spend_df: pd.DataFrame | None,
) -> pd.DataFrame:
    if entry_df.empty:
        result = entry_df.copy()
        result["allocated_point_spend"] = pd.Series(dtype="float64")
        return result

    result = entry_df.copy()
    if "date" not in result.columns:
        result["date"] = pd.NaT
    if "nm_id" not in result.columns:
        result["nm_id"] = pd.NA
    if "cart_count" not in result.columns:
        result["cart_count"] = pd.NA
    if "order_count" not in result.columns:
        result["order_count"] = pd.NA

    result["date"] = pd.to_datetime(result["date"], errors="coerce").dt.date
    result["nm_id"] = pd.to_numeric(result["nm_id"], errors="coerce")
    result["cart_count"] = pd.to_numeric(result["cart_count"], errors="coerce")
    result["order_count"] = pd.to_numeric(result["order_count"], errors="coerce")
    result = result.dropna(subset=["date", "nm_id"]).copy()
    if result.empty:
        result["allocated_point_spend"] = pd.Series(dtype="float64")
        return result

    result["nm_id"] = result["nm_id"].astype(int)
    result["allocated_point_spend"] = pd.Series([float("nan")] * len(result), index=result.index, dtype="float64")
    if spend_df is None or spend_df.empty:
        return result

    spend = spend_df.copy()
    if "date" not in spend.columns:
        if "report_date" in spend.columns:
            spend["date"] = spend["report_date"]
        else:
            return result
    if "nm_id" not in spend.columns or "ad_campaign_spend_total" not in spend.columns:
        return result

    spend["date"] = pd.to_datetime(spend["date"], errors="coerce").dt.date
    spend["nm_id"] = pd.to_numeric(spend["nm_id"], errors="coerce")
    spend["ad_campaign_spend_total"] = pd.to_numeric(spend["ad_campaign_spend_total"], errors="coerce")
    spend = spend.dropna(subset=["date", "nm_id"]).copy()
    if spend.empty:
        return result

    spend["nm_id"] = spend["nm_id"].astype(int)
    spend = spend.drop_duplicates(subset=["date", "nm_id"], keep="first")
    result = result.merge(spend[["date", "nm_id", "ad_campaign_spend_total"]], on=["date", "nm_id"], how="left")
    result["article_cart_total"] = result.groupby(["date", "nm_id"], dropna=False)["cart_count"].transform(
        lambda series: series.sum(min_count=1)
    )
    point_cart_share = [safe_chart_divide(cart_value, total_value) for cart_value, total_value in zip(result["cart_count"], result["article_cart_total"])]
    result["allocated_point_spend"] = result["ad_campaign_spend_total"] * pd.Series(
        point_cart_share,
        index=result.index,
        dtype="float64",
    )
    return result.drop(columns=["article_cart_total", "ad_campaign_spend_total"], errors="ignore")


def _extract_nm_id_from_entry_point_article_label(label: str | None) -> int | None:
    if not label:
        return None
    parts = [part.strip() for part in str(label).split("|")]
    candidates = parts[1:2] if len(parts) >= 2 else parts
    for candidate in candidates:
        parsed = pd.to_numeric(pd.Series([candidate]), errors="coerce").iloc[0]
        if pd.notna(parsed):
            return int(parsed)
    return None


def limit_entry_point_analytics_table(
    display_df: pd.DataFrame,
    *,
    analysis_level: str,
    detail_level: str,
    selected_article_label: str | None = None,
    selected_band: str | None = None,
    top_n_articles: int = ENTRY_POINT_DEFAULT_TOP_N_ARTICLES,
    top_n_detailed_articles: int = ENTRY_POINT_DEFAULT_TOP_N_DETAILED_ARTICLES,
    top_n_detailed_bands: int = ENTRY_POINT_DEFAULT_TOP_N_DETAILED_BANDS,
    max_detailed_rows: int = ENTRY_POINT_MAX_DETAILED_ROWS,
) -> tuple[pd.DataFrame, dict[str, object]]:
    context: dict[str, object] = {
        "mode": "all",
        "message": None,
        "selected_article": selected_article_label,
        "selected_band": selected_band,
    }
    if display_df.empty:
        return display_df, context

    result = display_df.copy()
    cart_column = "Добавления в корзину"

    def _select_top_by_group(df: pd.DataFrame, group_columns: list[str], limit: int) -> pd.DataFrame:
        if not group_columns or any(column not in df.columns for column in group_columns):
            return df
        totals = (
            df.assign(__cart_numeric=pd.to_numeric(df[cart_column], errors="coerce").fillna(0.0))
            .groupby(group_columns, dropna=False)["__cart_numeric"]
            .sum()
            .sort_values(ascending=False, kind="stable")
        )
        top_keys = totals.head(limit).index.tolist()
        if len(group_columns) == 1:
            return df[df[group_columns[0]].isin(top_keys)].copy()
        top_key_frame = pd.DataFrame(top_keys, columns=group_columns)
        return df.merge(top_key_frame, on=group_columns, how="inner")

    if analysis_level == ENTRY_POINT_LEVEL_ARTICLE:
        selected_nm_id = _extract_nm_id_from_entry_point_article_label(selected_article_label)
        if selected_nm_id is not None and "Артикул WB" in result.columns:
            result = result[result["Артикул WB"] == selected_nm_id].copy()
            context["mode"] = "selected_article"
        else:
            limit = top_n_articles if detail_level == ENTRY_POINT_DETAIL_COARSE else top_n_detailed_articles
            result = _select_top_by_group(result, ["Артикул WB"], limit)
            context["mode"] = "top_n_articles"
            context["message"] = (
                f"Показаны топ-{limit} артикулов по добавлениям в корзину за выбранный период. "
                "Для полной детализации выберите конкретный артикул."
            )

    if analysis_level == ENTRY_POINT_LEVEL_BAND and detail_level == ENTRY_POINT_DETAIL_DETAILED:
        if selected_band and selected_band != "Все банды" and "Банда" in result.columns:
            result = result[result["Банда"] == selected_band].copy()
            context["mode"] = "selected_band"
        elif "Банда" in result.columns and result["Банда"].nunique(dropna=True) > top_n_detailed_bands:
            result = _select_top_by_group(result, ["Банда"], top_n_detailed_bands)
            context["mode"] = "top_n_bands"
            context["message"] = (
                f"Показаны топ-{top_n_detailed_bands} банд по добавлениям в корзину за выбранный период. "
                "Для полной детализации выберите конкретную банду."
            )

    if detail_level == ENTRY_POINT_DETAIL_DETAILED:
        sort_columns = [column for column in ("Дата", cart_column) if column in result.columns]
        ascending = [False, False][: len(sort_columns)]
        if sort_columns:
            result = result.sort_values(sort_columns, ascending=ascending, na_position="last", kind="stable")
        if len(result) > max_detailed_rows:
            result = result.head(max_detailed_rows).copy()
            if not context.get("message"):
                context["message"] = (
                    f"Показаны первые {max_detailed_rows} строк после сортировки по дате и добавлениям в корзину."
                )
            context["mode"] = "row_limit"

    return result.reset_index(drop=True), context


def build_entry_point_analytics_table(
    entry_df: pd.DataFrame,
    metadata_df: pd.DataFrame,
    *,
    analysis_level: str,
    detail_level: str,
    spend_df: pd.DataFrame | None = None,
) -> pd.DataFrame:
    economics_enabled = detail_level == ENTRY_POINT_DETAIL_COARSE
    metric_columns = ["impressions", "card_clicks", "cart_count", "order_count"]
    if economics_enabled:
        metric_columns.append("allocated_point_spend")

    if entry_df.empty:
        if analysis_level == ENTRY_POINT_LEVEL_CABINET:
            base_columns = [ENTRY_POINT_LABEL_DATE, ENTRY_POINT_LABEL_SECTION, ENTRY_POINT_LABEL_POINT] if detail_level == ENTRY_POINT_DETAIL_DETAILED else [ENTRY_POINT_LABEL_DATE, ENTRY_POINT_LABEL_POINT]
        elif analysis_level == ENTRY_POINT_LEVEL_BAND:
            base_columns = [ENTRY_POINT_LABEL_DATE, ENTRY_POINT_LABEL_BAND, ENTRY_POINT_LABEL_SECTION, ENTRY_POINT_LABEL_POINT] if detail_level == ENTRY_POINT_DETAIL_DETAILED else [ENTRY_POINT_LABEL_DATE, ENTRY_POINT_LABEL_BAND, ENTRY_POINT_LABEL_POINT]
        else:
            base_columns = (
                [ENTRY_POINT_LABEL_DATE, ENTRY_POINT_LABEL_SUPPLIER_ARTICLE, ENTRY_POINT_LABEL_WB_ARTICLE, ENTRY_POINT_LABEL_TITLE, ENTRY_POINT_LABEL_SECTION, ENTRY_POINT_LABEL_POINT]
                if detail_level == ENTRY_POINT_DETAIL_DETAILED
                else [ENTRY_POINT_LABEL_DATE, ENTRY_POINT_LABEL_SUPPLIER_ARTICLE, ENTRY_POINT_LABEL_WB_ARTICLE, ENTRY_POINT_LABEL_TITLE, ENTRY_POINT_LABEL_POINT]
            )
        return pd.DataFrame(
            columns=base_columns
            + [
                ENTRY_POINT_LABEL_IMPRESSIONS,
                ENTRY_POINT_LABEL_CARD_CLICKS,
                ENTRY_POINT_LABEL_CART_COUNT,
                ENTRY_POINT_LABEL_CART_CONVERSION,
                ENTRY_POINT_LABEL_ORDERS,
                ENTRY_POINT_LABEL_ORDER_CONVERSION,
            ]
            + (
                [
                    ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN,
                    ENTRY_POINT_ECONOMICS_CART_COST_COLUMN,
                    ENTRY_POINT_ECONOMICS_CPO_COLUMN,
                ]
                if economics_enabled
                else []
            )
        )

    df = entry_df.copy()
    if economics_enabled:
        df = _prepare_entry_point_economics_source(df, spend_df)
    else:
        df = df.drop(columns=["allocated_point_spend"], errors="ignore")
    for column in ("nm_id", *metric_columns):
        if column not in df.columns:
            df[column] = pd.NA
    if "date" not in df.columns:
        df["date"] = pd.NaT
    df["nm_id"] = pd.to_numeric(df["nm_id"], errors="coerce")
    df = df.dropna(subset=["nm_id"]).copy()
    df["nm_id"] = df["nm_id"].astype(int)
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    df = df.dropna(subset=["date"]).copy()
    df[ENTRY_POINT_LABEL_DATE] = df["date"]
    for column in metric_columns:
        df[column] = pd.to_numeric(df[column], errors="coerce")

    if not metadata_df.empty:
        meta = metadata_df.copy()
        if "nm_id" not in meta.columns:
            meta["nm_id"] = pd.NA
        meta["nm_id"] = pd.to_numeric(meta["nm_id"], errors="coerce")
        meta = meta.dropna(subset=["nm_id"]).copy()
        meta["nm_id"] = meta["nm_id"].astype(int)
        keep_columns = [column for column in ("nm_id", "supplier_article", "title", "brand", "subject", "band_name") if column in meta.columns]
        meta = meta[keep_columns].drop_duplicates(subset=["nm_id"], keep="first")
        df = df.merge(meta, on="nm_id", how="left", suffixes=("", "_meta"))
        for column in ("supplier_article", "title", "brand", "subject", "band_name"):
            meta_column = f"{column}_meta"
            if meta_column not in df.columns:
                continue
            if column in df.columns:
                df[column] = df[column].where(df[column].notna() & df[column].astype(str).ne(""), df[meta_column])
            else:
                df[column] = df[meta_column]
            df = df.drop(columns=[meta_column])

    for column in ("supplier_article", "title", "section", "entry_point"):
        if column not in df.columns:
            df[column] = pd.NA
    if "band_name" not in df.columns:
        df["band_name"] = pd.NA

    df["supplier_article"] = df["supplier_article"].fillna("").astype(str)
    df["title"] = df["title"].fillna("").astype(str)
    df["section"] = df["section"].fillna("").astype(str)
    df["entry_point"] = df["entry_point"].fillna("").astype(str)
    df["band_name"] = df["band_name"].fillna(ENTRY_POINT_LABEL_NO_BAND).astype(str)

    if detail_level == ENTRY_POINT_DETAIL_COARSE:
        df[ENTRY_POINT_LABEL_POINT] = df.apply(
            lambda row: classify_entry_point_bucket(row.get("section"), row.get("entry_point")),
            axis=1,
        )
    else:
        df[ENTRY_POINT_LABEL_SECTION] = df["section"].replace("", ENTRY_POINT_LABEL_NO_SECTION)
        df[ENTRY_POINT_LABEL_POINT] = df["entry_point"].replace("", ENTRY_POINT_LABEL_NO_POINT)

    if analysis_level == ENTRY_POINT_LEVEL_CABINET:
        group_columns = [ENTRY_POINT_LABEL_DATE, ENTRY_POINT_LABEL_SECTION, ENTRY_POINT_LABEL_POINT] if detail_level == ENTRY_POINT_DETAIL_DETAILED else [ENTRY_POINT_LABEL_DATE, ENTRY_POINT_LABEL_POINT]
    elif analysis_level == ENTRY_POINT_LEVEL_BAND:
        group_columns = [ENTRY_POINT_LABEL_DATE, ENTRY_POINT_LABEL_BAND, ENTRY_POINT_LABEL_SECTION, ENTRY_POINT_LABEL_POINT] if detail_level == ENTRY_POINT_DETAIL_DETAILED else [ENTRY_POINT_LABEL_DATE, ENTRY_POINT_LABEL_BAND, ENTRY_POINT_LABEL_POINT]
        df[ENTRY_POINT_LABEL_BAND] = df["band_name"].replace("", ENTRY_POINT_LABEL_NO_BAND)
    else:
        group_columns = (
            [ENTRY_POINT_LABEL_DATE, ENTRY_POINT_LABEL_SUPPLIER_ARTICLE, ENTRY_POINT_LABEL_WB_ARTICLE, ENTRY_POINT_LABEL_TITLE, ENTRY_POINT_LABEL_SECTION, ENTRY_POINT_LABEL_POINT]
            if detail_level == ENTRY_POINT_DETAIL_DETAILED
            else [ENTRY_POINT_LABEL_DATE, ENTRY_POINT_LABEL_SUPPLIER_ARTICLE, ENTRY_POINT_LABEL_WB_ARTICLE, ENTRY_POINT_LABEL_TITLE, ENTRY_POINT_LABEL_POINT]
        )
        df[ENTRY_POINT_LABEL_WB_ARTICLE] = df["nm_id"]
        df[ENTRY_POINT_LABEL_SUPPLIER_ARTICLE] = df["supplier_article"].replace("", "?")
        df[ENTRY_POINT_LABEL_TITLE] = df["title"].replace("", "?")

    aggregations = {column: (lambda series: series.sum(min_count=1)) for column in metric_columns}
    grouped = (
        df.groupby(group_columns, as_index=False, dropna=False)[metric_columns]
        .agg(aggregations)
        .rename(
            columns={
                "impressions": ENTRY_POINT_LABEL_IMPRESSIONS,
                "card_clicks": ENTRY_POINT_LABEL_CARD_CLICKS,
                "cart_count": ENTRY_POINT_LABEL_CART_COUNT,
                "order_count": ENTRY_POINT_LABEL_ORDERS,
                "allocated_point_spend": ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN,
            }
        )
    )
    if analysis_level == ENTRY_POINT_LEVEL_CABINET and detail_level == ENTRY_POINT_DETAIL_COARSE:
        total_rows: list[dict[str, object]] = []
        for report_date, date_rows in grouped.groupby(ENTRY_POINT_LABEL_DATE, dropna=False, sort=True):
            total_row = {
                ENTRY_POINT_LABEL_DATE: report_date,
                ENTRY_POINT_LABEL_POINT: ENTRY_POINT_GROUP_TOTAL,
                ENTRY_POINT_LABEL_IMPRESSIONS: date_rows[ENTRY_POINT_LABEL_IMPRESSIONS].sum(min_count=1),
                ENTRY_POINT_LABEL_CARD_CLICKS: date_rows[ENTRY_POINT_LABEL_CARD_CLICKS].sum(min_count=1),
                ENTRY_POINT_LABEL_CART_COUNT: date_rows[ENTRY_POINT_LABEL_CART_COUNT].sum(min_count=1),
                ENTRY_POINT_LABEL_ORDERS: date_rows[ENTRY_POINT_LABEL_ORDERS].sum(min_count=1),
            }
            if economics_enabled and ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN in date_rows.columns:
                total_row[ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN] = date_rows[ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN].sum(min_count=1)
            total_rows.append(total_row)
        grouped = pd.concat([grouped, pd.DataFrame(total_rows)], ignore_index=True)

    grouped[ENTRY_POINT_LABEL_ORDER_CONVERSION] = _compute_entry_point_conversion(
        grouped[ENTRY_POINT_LABEL_ORDERS],
        grouped[ENTRY_POINT_LABEL_CART_COUNT],
    )
    grouped = _apply_entry_point_cart_conversion_fallback(grouped, group_columns=group_columns)

    if economics_enabled:
        grouped[ENTRY_POINT_ECONOMICS_CART_COST_COLUMN] = grouped.apply(
            lambda row: safe_chart_divide(row.get(ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN), row.get(ENTRY_POINT_LABEL_CART_COUNT)),
            axis=1,
        )
        grouped[ENTRY_POINT_ECONOMICS_CPO_COLUMN] = grouped.apply(
            lambda row: safe_chart_divide(row.get(ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN), row.get(ENTRY_POINT_LABEL_ORDERS)),
            axis=1,
        )

    if analysis_level == ENTRY_POINT_LEVEL_CABINET and detail_level == ENTRY_POINT_DETAIL_COARSE:
        grouped["__entry_sort"] = grouped[ENTRY_POINT_LABEL_POINT].map(
            {label: index for index, label in enumerate(ENTRY_POINT_GROUP_ORDER)}
        ).fillna(len(ENTRY_POINT_GROUP_ORDER))
        grouped = grouped.sort_values([ENTRY_POINT_LABEL_DATE, "__entry_sort", ENTRY_POINT_LABEL_POINT], kind="stable").drop(columns=["__entry_sort"])
    elif detail_level == ENTRY_POINT_DETAIL_COARSE:
        sort_columns = [ENTRY_POINT_LABEL_DATE, ENTRY_POINT_LABEL_POINT]
        if analysis_level == ENTRY_POINT_LEVEL_BAND:
            sort_columns = [ENTRY_POINT_LABEL_DATE, ENTRY_POINT_LABEL_BAND, ENTRY_POINT_LABEL_POINT]
        elif analysis_level == ENTRY_POINT_LEVEL_ARTICLE:
            sort_columns = [ENTRY_POINT_LABEL_DATE, ENTRY_POINT_LABEL_SUPPLIER_ARTICLE, ENTRY_POINT_LABEL_WB_ARTICLE, ENTRY_POINT_LABEL_POINT]
        grouped["__entry_sort"] = grouped[ENTRY_POINT_LABEL_POINT].map(
            {label: index for index, label in enumerate(ENTRY_POINT_GROUP_ORDER)}
        ).fillna(len(ENTRY_POINT_GROUP_ORDER))
        grouped = grouped.sort_values(
            [column for column in sort_columns if column != ENTRY_POINT_LABEL_POINT] + ["__entry_sort", ENTRY_POINT_LABEL_POINT],
            kind="stable",
        ).drop(columns=["__entry_sort"])
    else:
        grouped = grouped.sort_values(group_columns, kind="stable")

    ordered_columns = list(group_columns) + [
        ENTRY_POINT_LABEL_IMPRESSIONS,
        ENTRY_POINT_LABEL_CARD_CLICKS,
        ENTRY_POINT_LABEL_CART_COUNT,
        ENTRY_POINT_LABEL_CART_CONVERSION,
        ENTRY_POINT_LABEL_ORDERS,
        ENTRY_POINT_LABEL_ORDER_CONVERSION,
    ]
    if economics_enabled:
        ordered_columns += [
            ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN,
            ENTRY_POINT_ECONOMICS_CART_COST_COLUMN,
            ENTRY_POINT_ECONOMICS_CPO_COLUMN,
        ]
    if "__entry_point_conversion_fallback_7d" in grouped.columns:
        ordered_columns.append("__entry_point_conversion_fallback_7d")
    existing_order = [column for column in ordered_columns if column in grouped.columns]
    return grouped[existing_order].reset_index(drop=True)


def style_entry_point_analytics_table(display_df: pd.DataFrame):
    required_columns = {"Добавления в корзину", "Конверсия в корзину"}
    if display_df.empty or not required_columns.issubset(display_df.columns):
        return display_df

    fallback_column = "__entry_point_conversion_fallback_7d"
    style_source = display_df.copy()
    visible_df = style_source.drop(columns=[fallback_column], errors="ignore")
    if len(visible_df.index) * len(visible_df.columns) > STYLER_MAX_CELLS:
        return visible_df

    cart_column_index = visible_df.columns.get_loc("Добавления в корзину")
    conversion_column_index = visible_df.columns.get_loc("Конверсия в корзину")
    metric_columns = {"Показы", "Переходы в карточку", "Добавления в корзину", "Конверсия в корзину", "Заказы", "Конверсия в заказ"}
    comparison_columns = [column for column in visible_df.columns if column not in metric_columns and column != "Дата"]
    cart_numeric = pd.to_numeric(visible_df["Добавления в корзину"], errors="coerce")
    if comparison_columns:
        avg_cart = (
            visible_df.assign(__cart_numeric=cart_numeric)
            .groupby(comparison_columns, dropna=False)["__cart_numeric"]
            .transform("mean")
        )
    else:
        avg_cart = pd.Series(cart_numeric.mean(), index=visible_df.index)
    fallback_mask_series = (
        style_source[fallback_column].astype(bool)
        if fallback_column in style_source.columns
        else cart_numeric.lt(50).fillna(False)
    )

    def _highlight_low_cart_conversion(row: pd.Series) -> list[str]:
        styles = [""] * len(visible_df.columns)
        cart_value = pd.to_numeric(pd.Series([row.get("Добавления в корзину")]), errors="coerce").iloc[0]
        average_cart_value = avg_cart.loc[row.name] if row.name in avg_cart.index else pd.NA
        if (
            pd.notna(cart_value)
            and pd.notna(average_cart_value)
            and float(cart_value) >= 50
            and float(cart_value) >= float(average_cart_value) * 1.5
        ):
            styles[cart_column_index] = f"background-color: {ENTRY_POINT_CART_SPIKE_HIGHLIGHT}"
        if bool(fallback_mask_series.loc[row.name]) if row.name in fallback_mask_series.index else False:
            styles[conversion_column_index] = f"background-color: {ENTRY_POINT_CONVERSION_HIGHLIGHT}"
        return styles

    return visible_df.style.apply(_highlight_low_cart_conversion, axis=1)


def _prepare_entry_point_chart_base_dataframe(
    display_df: pd.DataFrame,
    *,
    analysis_level: str,
    detail_level: str,
) -> pd.DataFrame:
    if display_df.empty:
        return pd.DataFrame(columns=["report_date", "series_name"])

    chart_df = display_df.drop(columns=["__entry_point_conversion_fallback_7d"], errors="ignore").copy()
    if ENTRY_POINT_LABEL_DATE not in chart_df.columns:
        return pd.DataFrame(columns=["report_date", "series_name"])

    chart_df["report_date"] = pd.to_datetime(chart_df[ENTRY_POINT_LABEL_DATE], errors="coerce")
    chart_df = chart_df.dropna(subset=["report_date"]).copy()
    if chart_df.empty:
        return pd.DataFrame(columns=["report_date", "series_name"])

    if analysis_level == ENTRY_POINT_LEVEL_CABINET and ENTRY_POINT_LABEL_POINT in chart_df.columns:
        chart_df = chart_df[chart_df[ENTRY_POINT_LABEL_POINT] != ENTRY_POINT_GROUP_TOTAL].copy()
    if chart_df.empty:
        return pd.DataFrame(columns=["report_date", "series_name"])

    separator = " · "
    if analysis_level == ENTRY_POINT_LEVEL_CABINET:
        if detail_level == ENTRY_POINT_DETAIL_DETAILED and {ENTRY_POINT_LABEL_SECTION, ENTRY_POINT_LABEL_POINT}.issubset(chart_df.columns):
            chart_df["series_name"] = chart_df[ENTRY_POINT_LABEL_SECTION].astype(str) + separator + chart_df[ENTRY_POINT_LABEL_POINT].astype(str)
        else:
            chart_df["series_name"] = chart_df.get(ENTRY_POINT_LABEL_POINT, pd.Series(index=chart_df.index, dtype=object)).astype(str)
    elif analysis_level == ENTRY_POINT_LEVEL_BAND:
        band_series = chart_df.get(ENTRY_POINT_LABEL_BAND, pd.Series(ENTRY_POINT_LABEL_NO_BAND, index=chart_df.index)).fillna(ENTRY_POINT_LABEL_NO_BAND).astype(str)
        if detail_level == ENTRY_POINT_DETAIL_DETAILED and {ENTRY_POINT_LABEL_SECTION, ENTRY_POINT_LABEL_POINT}.issubset(chart_df.columns):
            chart_df["series_name"] = (
                band_series
                + separator
                + chart_df[ENTRY_POINT_LABEL_SECTION].astype(str)
                + separator
                + chart_df[ENTRY_POINT_LABEL_POINT].astype(str)
            )
        else:
            chart_df["series_name"] = band_series + separator + chart_df.get(
                ENTRY_POINT_LABEL_POINT, pd.Series(index=chart_df.index, dtype=object)
            ).astype(str)
    else:
        article_series = (
            chart_df.get(ENTRY_POINT_LABEL_SUPPLIER_ARTICLE, pd.Series("?", index=chart_df.index))
            .fillna("?")
            .astype(str)
            + " | "
            + chart_df.get(ENTRY_POINT_LABEL_WB_ARTICLE, pd.Series("?", index=chart_df.index)).fillna("?").astype(str)
        )
        if detail_level == ENTRY_POINT_DETAIL_DETAILED and {ENTRY_POINT_LABEL_SECTION, ENTRY_POINT_LABEL_POINT}.issubset(chart_df.columns):
            chart_df["series_name"] = (
                article_series
                + separator
                + chart_df[ENTRY_POINT_LABEL_SECTION].astype(str)
                + separator
                + chart_df[ENTRY_POINT_LABEL_POINT].astype(str)
            )
        else:
            chart_df["series_name"] = article_series + separator + chart_df.get(
                ENTRY_POINT_LABEL_POINT, pd.Series(index=chart_df.index, dtype=object)
            ).astype(str)

    return chart_df


def build_entry_point_chart_dataframe(
    display_df: pd.DataFrame,
    *,
    analysis_level: str,
    detail_level: str,
) -> pd.DataFrame:
    expected_columns = [
        "report_date",
        "series_name",
        "cart_count",
        "cart_conversion",
        "order_conversion",
    ]
    chart_df = _prepare_entry_point_chart_base_dataframe(
        display_df,
        analysis_level=analysis_level,
        detail_level=detail_level,
    )
    if chart_df.empty:
        return pd.DataFrame(columns=expected_columns)

    chart_df["cart_count"] = pd.to_numeric(chart_df.get(ENTRY_POINT_LABEL_CART_COUNT), errors="coerce")
    chart_df["cart_conversion"] = pd.to_numeric(chart_df.get(ENTRY_POINT_LABEL_CART_CONVERSION), errors="coerce")
    chart_df["order_conversion"] = pd.to_numeric(chart_df.get(ENTRY_POINT_LABEL_ORDER_CONVERSION), errors="coerce")

    result = chart_df[expected_columns].copy()
    return result.sort_values(["report_date", "series_name"], kind="stable").reset_index(drop=True)


def build_entry_point_economics_chart_dataframe(
    display_df: pd.DataFrame,
    *,
    analysis_level: str,
    detail_level: str,
) -> pd.DataFrame:
    expected_columns = [
        "report_date",
        "series_name",
        "estimated_cost_per_cart",
        "estimated_cpo",
    ]
    if detail_level != ENTRY_POINT_DETAIL_COARSE:
        return pd.DataFrame(columns=expected_columns)

    chart_df = _prepare_entry_point_chart_base_dataframe(
        display_df,
        analysis_level=analysis_level,
        detail_level=detail_level,
    )
    if chart_df.empty:
        return pd.DataFrame(columns=expected_columns)
    if ENTRY_POINT_ECONOMICS_CART_COST_COLUMN not in chart_df.columns or ENTRY_POINT_ECONOMICS_CPO_COLUMN not in chart_df.columns:
        return pd.DataFrame(columns=expected_columns)

    chart_df["estimated_cost_per_cart"] = pd.to_numeric(chart_df.get(ENTRY_POINT_ECONOMICS_CART_COST_COLUMN), errors="coerce")
    chart_df["estimated_cpo"] = pd.to_numeric(chart_df.get(ENTRY_POINT_ECONOMICS_CPO_COLUMN), errors="coerce")

    result = chart_df[expected_columns].copy()
    return result.sort_values(["report_date", "series_name"], kind="stable").reset_index(drop=True)



def build_entry_point_period_cpo_series_labels(
    display_df: pd.DataFrame,
    *,
    analysis_level: str,
    detail_level: str,
) -> dict[str, str]:
    chart_df = _prepare_entry_point_chart_base_dataframe(
        display_df,
        analysis_level=analysis_level,
        detail_level=detail_level,
    )
    if chart_df.empty or "series_name" not in chart_df.columns:
        return {}

    series_names = chart_df["series_name"].dropna().astype(str).drop_duplicates().tolist()
    if not series_names:
        return {}

    if (
        ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN not in chart_df.columns
        or ENTRY_POINT_LABEL_ORDERS not in chart_df.columns
    ):
        return {series_name: f"{series_name} — CPO н/д" for series_name in series_names}

    cpo_source = chart_df[["series_name", ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN, ENTRY_POINT_LABEL_ORDERS]].copy()
    cpo_source[ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN] = pd.to_numeric(
        cpo_source[ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN],
        errors="coerce",
    )
    cpo_source[ENTRY_POINT_LABEL_ORDERS] = pd.to_numeric(cpo_source[ENTRY_POINT_LABEL_ORDERS], errors="coerce")
    grouped = cpo_source.groupby("series_name", dropna=False, sort=False).sum(min_count=1)

    labels: dict[str, str] = {}
    for series_name in series_names:
        spend_value = grouped.at[series_name, ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN] if series_name in grouped.index else pd.NA
        orders_value = grouped.at[series_name, ENTRY_POINT_LABEL_ORDERS] if series_name in grouped.index else pd.NA
        period_cpo = safe_chart_divide(spend_value, orders_value)
        if period_cpo is None:
            labels[series_name] = f"{series_name} — CPO н/д"
        else:
            labels[series_name] = f"{series_name} — CPO {format_summary_rub(period_cpo)}"
    return labels


def build_entry_point_line_chart(
    *,
    chart_df: pd.DataFrame,
    value_column: str,
    y_title: str,
    tooltip_value_title: str,
    value_format: str,
    threshold: float | None = None,
    threshold_label: str | None = None,
) -> alt.Chart | None:
    if chart_df.empty or value_column not in chart_df.columns:
        return None

    prepared = chart_df.dropna(subset=["report_date", "series_name", value_column]).copy()
    if prepared.empty:
        return None

    unique_dates_count = len(prepared["report_date"].unique())
    base = alt.Chart(prepared).encode(
        x=alt.X(
            "report_date:T",
            title="Дата",
            axis=alt.Axis(format="%d.%m", labelAngle=0, tickCount=min(max(unique_dates_count, 2), 10)),
        ),
        y=alt.Y(
            f"{value_column}:Q",
            title=y_title,
            axis=alt.Axis(format=value_format),
            scale=alt.Scale(zero=True, nice=True),
        ),
        color=alt.Color("series_name:N", title="Серия"),
        tooltip=[
            alt.Tooltip("report_date:T", title="Дата", format="%d.%m.%Y"),
            alt.Tooltip("series_name:N", title="Серия"),
            alt.Tooltip(f"{value_column}:Q", title=tooltip_value_title, format=value_format),
        ],
    )

    layers: list[alt.Chart] = [
        base.mark_line(strokeWidth=3),
        base.mark_circle(size=45),
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

    return alt.layer(*layers).resolve_scale(color="shared").properties(height=320)


@st.cache_data(show_spinner=False)
def load_search_queries_by_date_from_db(snapshot_date: date, cache_buster: str | None = None) -> dict[str, int]:
    try:
        with session_scope() as session:
            subq = (
                select(
                    FactWbSearchQueryTextDay.day.label("day"),
                    FactWbSearchQueryTextDay.query_group.label("query_group"),
                    FactWbSearchQueryTextDay.query_text.label("query_text"),
                    func.max(FactWbSearchQueryTextDay.frequency_current).label("max_freq")
                )
                .where(
                    FactWbSearchQueryTextDay.day == snapshot_date,
                    FactWbSearchQueryTextDay.query_group.isnot(None),
                    FactWbSearchQueryTextDay.query_group != "unknown",
                    FactWbSearchQueryTextDay.query_group != "Не определена",
                    FactWbSearchQueryTextDay.query_group != ""
                )
                .group_by(
                    FactWbSearchQueryTextDay.day,
                    FactWbSearchQueryTextDay.query_group,
                    FactWbSearchQueryTextDay.query_text
                )
                .subquery()
            )
            
            stmt = (
                select(
                    subq.c.query_group,
                    func.sum(subq.c.max_freq).label("search_queries")
                )
                .group_by(subq.c.query_group)
            )
            
            rows = session.execute(stmt).all()
            return {row.query_group: int(row.search_queries) for row in rows if row.search_queries is not None}
    except Exception:
        logger.exception("Failed to load search queries aggregates from db for stock warehouse tab")
        return {}


@st.cache_data(show_spinner=False)
def calculate_lost_profit_conversions_from_db(snapshot_date: date, cache_buster: str | None = None) -> dict[str, float]:
    try:
        with session_scope() as session:
            orders_stmt = (
                select(
                    FactWbSearchQueryTextDay.query_group,
                    func.sum(FactWbSearchQueryTextDay.orders_current).label("orders_sum")
                )
                .where(
                    FactWbSearchQueryTextDay.day == snapshot_date,
                    FactWbSearchQueryTextDay.query_group.isnot(None),
                    FactWbSearchQueryTextDay.query_group != "unknown",
                    FactWbSearchQueryTextDay.query_group != "Не определена",
                    FactWbSearchQueryTextDay.query_group != ""
                )
                .group_by(FactWbSearchQueryTextDay.query_group)
            )
            orders_rows = session.execute(orders_stmt).all()
            orders_map = {row.query_group: int(row.orders_sum or 0) for row in orders_rows}

            subq = (
                select(
                    FactWbSearchQueryTextDay.query_group.label("query_group"),
                    FactWbSearchQueryTextDay.query_text.label("query_text"),
                    func.max(FactWbSearchQueryTextDay.frequency_current).label("max_freq")
                )
                .where(
                    FactWbSearchQueryTextDay.day == snapshot_date,
                    FactWbSearchQueryTextDay.query_group.isnot(None),
                    FactWbSearchQueryTextDay.query_group != "unknown",
                    FactWbSearchQueryTextDay.query_group != "Не определена",
                    FactWbSearchQueryTextDay.query_group != ""
                )
                .group_by(
                    FactWbSearchQueryTextDay.query_group,
                    FactWbSearchQueryTextDay.query_text
                )
                .subquery()
            )
            
            freq_stmt = (
                select(
                    subq.c.query_group,
                    func.sum(subq.c.max_freq).label("search_queries")
                )
                .group_by(subq.c.query_group)
            )
            freq_rows = session.execute(freq_stmt).all()
            freq_map = {row.query_group: int(row.search_queries or 0) for row in freq_rows}

            conversions = {}
            for group, orders_sum in orders_map.items():
                freq = freq_map.get(group, 0)
                if freq > 0:
                    conversions[group] = float(orders_sum) / float(freq)
            return conversions
    except Exception:
        logger.exception("Failed to calculate search to order conversions from DB for stock warehouse tab")
        return {}


@st.cache_data(show_spinner=False)
def load_lost_profit_coefficients_from_db(cache_buster: str | None = None) -> dict[str, Decimal]:
    try:
        with session_scope() as session:
            rows = session.execute(
                select(
                    SettingsLostProfitQueryGroupCoefficient.query_group,
                    SettingsLostProfitQueryGroupCoefficient.search_to_order_conversion,
                )
            ).all()
            return {
                row.query_group: row.search_to_order_conversion
                for row in rows
                if row.search_to_order_conversion is not None
            }
    except Exception:
        logger.exception("Failed to load lost profit coefficients from db for stock warehouse tab")
        return {}


@st.cache_data(show_spinner=False)
def load_warehouse_market_areas_from_db(cache_buster: str | None = None) -> dict[str, tuple[str, Decimal]]:
    try:
        with session_scope() as session:
            rows = session.execute(
                select(
                    SettingsLostProfitWarehouseArea.warehouse_name,
                    SettingsLostProfitWarehouseArea.market_area_code,
                    SettingsLostProfitMarketArea.population_share_pct,
                ).join(
                    SettingsLostProfitMarketArea,
                    SettingsLostProfitWarehouseArea.market_area_code == SettingsLostProfitMarketArea.market_area_code,
                )
            ).all()
            return {
                row.warehouse_name: (row.market_area_code, row.population_share_pct)
                for row in rows
            }
    except Exception:
        logger.exception("Failed to load warehouse market areas from db for stock warehouse tab")
        return {}


def attach_stock_query_groups(
    tracked_df: pd.DataFrame,
    query_group_df: pd.DataFrame,
) -> pd.DataFrame:
    tracked_prepared = tracked_df.copy()
    if "query_group" in tracked_prepared.columns:
        tracked_prepared = tracked_prepared.drop(columns=["query_group"])
    if "nm_id" not in tracked_prepared.columns:
        tracked_prepared["query_group"] = pd.NA
        return tracked_prepared

    tracked_prepared["nm_id"] = pd.to_numeric(tracked_prepared["nm_id"], errors="coerce")
    query_group_prepared = query_group_df.copy()
    if query_group_prepared.empty:
        tracked_prepared["query_group"] = pd.NA
        return tracked_prepared

    for column in ("nm_id", "query_group"):
        if column not in query_group_prepared.columns:
            query_group_prepared[column] = pd.NA
    query_group_prepared["nm_id"] = pd.to_numeric(query_group_prepared["nm_id"], errors="coerce")
    query_group_prepared = query_group_prepared.dropna(subset=["nm_id"]).copy()
    if query_group_prepared.empty:
        tracked_prepared["query_group"] = pd.NA
        return tracked_prepared

    query_group_prepared["nm_id"] = query_group_prepared["nm_id"].astype(int)
    query_group_prepared["query_group"] = query_group_prepared["query_group"].map(normalize_query_group_value)
    query_group_prepared["query_group"] = query_group_prepared["query_group"].where(
        query_group_prepared["query_group"].notna(),
        pd.NA,
    )
    query_group_prepared = query_group_prepared.drop_duplicates(subset=["nm_id"], keep="first")

    return tracked_prepared.merge(
        query_group_prepared[["nm_id", "query_group"]],
        on="nm_id",
        how="left",
    )


def prepare_stock_warehouse_snapshot_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    expected_columns = [
        "snapshot_date",
        "nm_id",
        "chrt_id",
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
    prepared["chrt_id"] = pd.to_numeric(prepared["chrt_id"], errors="coerce")
    prepared["warehouse_id"] = pd.to_numeric(prepared["warehouse_id"], errors="coerce")
    for column in ("stock_qty", "in_way_to_client", "in_way_from_client"):
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    prepared["warehouse_name"] = prepared["warehouse_name"].fillna("").astype(str).str.strip()
    prepared = prepared.dropna(subset=["snapshot_date", "nm_id"]).copy()
    prepared["nm_id"] = prepared["nm_id"].astype(int)
    if prepared["chrt_id"].notna().any():
        prepared.loc[prepared["chrt_id"].notna(), "chrt_id"] = prepared.loc[
            prepared["chrt_id"].notna(), "chrt_id"
        ].astype(int)

    aggregated = (
        prepared.groupby(
            ["snapshot_date", "nm_id", "chrt_id", "warehouse_id", "warehouse_name", "region_name"],
            dropna=False,
            as_index=False,
        )[["stock_qty", "in_way_to_client", "in_way_from_client"]]
        .sum(min_count=1)
    )
    return aggregated


def _first_non_empty_value(series: pd.Series) -> object:
    for value in series:
        if pd.notna(value) and str(value).strip() != "":
            return value
    return pd.NA


def prepare_stock_warehouse_history_snapshot_dataframe(df: pd.DataFrame) -> pd.DataFrame:
    expected_columns = [
        "snapshot_date",
        "nm_id",
        "warehouse_id",
        "warehouse_name",
        "region_name",
        "stock_qty",
        "in_way_to_client",
        "in_way_from_client",
        "source",
        "loaded_at",
    ]
    prepared = df.copy()
    for column in expected_columns:
        if column not in prepared.columns:
            prepared[column] = pd.NA

    if prepared.empty:
        return prepared[expected_columns].copy()

    prepared["snapshot_date"] = pd.to_datetime(prepared["snapshot_date"], errors="coerce").dt.date
    prepared["loaded_at"] = pd.to_datetime(prepared["loaded_at"], errors="coerce")
    prepared["nm_id"] = pd.to_numeric(prepared["nm_id"], errors="coerce")
    prepared["warehouse_id"] = pd.to_numeric(prepared["warehouse_id"], errors="coerce")
    for column in ("stock_qty", "in_way_to_client", "in_way_from_client"):
        prepared[column] = pd.to_numeric(prepared[column], errors="coerce")
    prepared["warehouse_name"] = prepared["warehouse_name"].fillna("").astype(str).str.strip()
    prepared = prepared.dropna(subset=["snapshot_date", "nm_id", "warehouse_id"]).copy()
    if prepared.empty:
        return pd.DataFrame(columns=expected_columns)

    prepared["nm_id"] = prepared["nm_id"].astype(int)
    prepared["warehouse_id"] = prepared["warehouse_id"].astype(int)

    aggregated = (
        prepared.groupby(
            ["snapshot_date", "nm_id", "warehouse_id", "loaded_at"],
            dropna=False,
            as_index=False,
        )
        .agg(
            warehouse_name=("warehouse_name", _first_non_empty_value),
            region_name=("region_name", _first_non_empty_value),
            source=("source", _first_non_empty_value),
            stock_qty=("stock_qty", lambda values: values.sum(min_count=1)),
            in_way_to_client=("in_way_to_client", lambda values: values.sum(min_count=1)),
            in_way_from_client=("in_way_from_client", lambda values: values.sum(min_count=1)),
        )
        .sort_values(
            by=["snapshot_date", "nm_id", "warehouse_id", "loaded_at"],
            ascending=[True, True, True, True],
            na_position="first",
        )
        .drop_duplicates(subset=["snapshot_date", "nm_id", "warehouse_id"], keep="last")
        .reset_index(drop=True)
    )

    return aggregated.reindex(columns=expected_columns)


def _prepare_stock_warehouse_history_product_scope(tracked_df: pd.DataFrame) -> pd.DataFrame:
    prepared = tracked_df.copy()
    for column in ("nm_id", "supplier_article", "title", "item_label", "tracked_label", "is_tracked", "lifecycle_status"):
        if column not in prepared.columns:
            prepared[column] = pd.NA

    if prepared.empty:
        return pd.DataFrame(columns=["nm_id", "supplier_article", "product_name", "lifecycle_status"])

    prepared["nm_id"] = pd.to_numeric(prepared["nm_id"], errors="coerce")
    prepared = prepared.dropna(subset=["nm_id"]).copy()
    if prepared.empty:
        return pd.DataFrame(columns=["nm_id", "supplier_article", "product_name", "lifecycle_status"])

    prepared["nm_id"] = prepared["nm_id"].astype(int)
    prepared["is_tracked"] = prepared["is_tracked"].fillna(False).astype(bool)
    prepared["lifecycle_status"] = prepared["lifecycle_status"].fillna("not_tracked").astype(str).str.strip().str.lower()
    prepared = prepared[prepared["is_tracked"]].copy()
    if prepared.empty:
        return pd.DataFrame(columns=["nm_id", "supplier_article", "product_name", "lifecycle_status"])

    prepared["supplier_article"] = (
        prepared["supplier_article"]
        .where(prepared["supplier_article"].notna(), prepared["tracked_label"])
        .where(lambda series: series.notna(), prepared["item_label"])
    )
    prepared["product_name"] = (
        prepared["title"]
        .where(prepared["title"].notna(), prepared["item_label"])
        .where(lambda series: series.notna(), prepared["tracked_label"])
        .where(lambda series: series.notna(), prepared["supplier_article"])
    )

    return (
        prepared[["nm_id", "supplier_article", "product_name", "lifecycle_status"]]
        .drop_duplicates(subset=["nm_id"], keep="first")
        .sort_values(["supplier_article", "nm_id"], na_position="last")
        .reset_index(drop=True)
    )


def _classify_stock_warehouse_history_status(quantity: object) -> str:
    if pd.isna(quantity):
        return STOCK_HISTORY_STATUS_NO_DATA
    try:
        return STOCK_HISTORY_STATUS_ZERO if float(quantity) == 0 else STOCK_HISTORY_STATUS_IN_STOCK
    except (TypeError, ValueError):
        return STOCK_HISTORY_STATUS_NO_DATA


def classify_stock_warehouse_history_anomaly(statuses: list[str] | tuple[str, ...] | pd.Series) -> str:
    normalized = {str(value) for value in statuses if pd.notna(value)}
    if not normalized or normalized == {STOCK_HISTORY_STATUS_NO_DATA}:
        return STOCK_HISTORY_ANOMALY_ALWAYS_NO_DATA
    if normalized == {STOCK_HISTORY_STATUS_ZERO}:
        return STOCK_HISTORY_ANOMALY_ALWAYS_ZERO
    if normalized == {STOCK_HISTORY_STATUS_IN_STOCK}:
        return STOCK_HISTORY_ANOMALY_ALWAYS_IN_STOCK
    if normalized == {STOCK_HISTORY_STATUS_ZERO, STOCK_HISTORY_STATUS_IN_STOCK}:
        return STOCK_HISTORY_ANOMALY_MIXED_ZERO_AND_STOCK
    if normalized == {STOCK_HISTORY_STATUS_NO_DATA, STOCK_HISTORY_STATUS_IN_STOCK}:
        return STOCK_HISTORY_ANOMALY_MIXED_NO_DATA_AND_STOCK
    return STOCK_HISTORY_ANOMALY_UNSTABLE


def build_stock_warehouse_history_table(
    snapshot_df: pd.DataFrame,
    tracked_df: pd.DataFrame,
    *,
    selected_dates: list[date],
    monitored_warehouses: list[str],
) -> pd.DataFrame:
    history_columns = [
        "snapshot_date",
        "nm_id",
        "supplier_article",
        "product_name",
        "lifecycle_status",
        "warehouse_id",
        "warehouse_name",
        "stock_qty",
        "stock_status",
        "loaded_at",
        "anomaly_type",
    ]
    if not selected_dates or not monitored_warehouses:
        return pd.DataFrame(columns=history_columns)

    products = _prepare_stock_warehouse_history_product_scope(tracked_df)
    if products.empty:
        return pd.DataFrame(columns=history_columns)

    snapshot_prepared = prepare_stock_warehouse_history_snapshot_dataframe(snapshot_df)
    snapshot_prepared = snapshot_prepared[
        snapshot_prepared["snapshot_date"].isin(selected_dates)
        & snapshot_prepared["warehouse_name"].isin(monitored_warehouses)
    ].copy()

    lookup = {
        (row["snapshot_date"], int(row["nm_id"]), str(row["warehouse_name"])): row
        for _, row in snapshot_prepared.iterrows()
    }

    rows: list[dict[str, object]] = []
    for _, product in products.iterrows():
        nm_id = int(product["nm_id"])
        for warehouse_name in monitored_warehouses:
            for snapshot_day in selected_dates:
                source_row = lookup.get((snapshot_day, nm_id, str(warehouse_name)))
                stock_qty = source_row["stock_qty"] if source_row is not None else pd.NA
                rows.append(
                    {
                        "snapshot_date": snapshot_day,
                        "nm_id": nm_id,
                        "supplier_article": product.get("supplier_article"),
                        "product_name": product.get("product_name"),
                        "lifecycle_status": product.get("lifecycle_status") or "not_tracked",
                        "warehouse_id": source_row["warehouse_id"] if source_row is not None else pd.NA,
                        "warehouse_name": warehouse_name,
                        "stock_qty": _normalize_stock_display_value(stock_qty),
                        "stock_status": _classify_stock_warehouse_history_status(stock_qty),
                        "loaded_at": source_row["loaded_at"] if source_row is not None else pd.NaT,
                    }
                )

    history_df = pd.DataFrame(rows)
    if history_df.empty:
        return pd.DataFrame(columns=history_columns)

    anomaly_df = (
        history_df.groupby(["nm_id", "warehouse_name"], as_index=False)
        .agg(anomaly_type=("stock_status", lambda values: classify_stock_warehouse_history_anomaly(values.tolist())))
    )
    history_df = history_df.merge(anomaly_df, on=["nm_id", "warehouse_name"], how="left")
    history_df = history_df.sort_values(
        by=["supplier_article", "nm_id", "warehouse_name", "snapshot_date"],
        ascending=[True, True, True, True],
        na_position="last",
    ).reset_index(drop=True)
    return history_df.reindex(columns=history_columns)


def build_stock_warehouse_history_summary_metrics(history_df: pd.DataFrame) -> dict[str, int]:
    if history_df.empty:
        return {
            "dates_count": 0,
            "products_count": 0,
            "warehouses_count": 0,
            "in_stock_rows": 0,
            "zero_rows": 0,
            "no_data_rows": 0,
            "anomalies_count": 0,
        }

    anomaly_pairs = history_df.loc[
        history_df["anomaly_type"].ne(STOCK_HISTORY_ANOMALY_ALWAYS_IN_STOCK),
        ["nm_id", "warehouse_name"],
    ].drop_duplicates()
    return {
        "dates_count": int(history_df["snapshot_date"].nunique()),
        "products_count": int(history_df["nm_id"].nunique()),
        "warehouses_count": int(history_df["warehouse_name"].nunique()),
        "in_stock_rows": int(history_df["stock_status"].eq(STOCK_HISTORY_STATUS_IN_STOCK).sum()),
        "zero_rows": int(history_df["stock_status"].eq(STOCK_HISTORY_STATUS_ZERO).sum()),
        "no_data_rows": int(history_df["stock_status"].eq(STOCK_HISTORY_STATUS_NO_DATA).sum()),
        "anomalies_count": int(len(anomaly_pairs)),
    }


def build_stock_warehouse_history_pivot_table(history_df: pd.DataFrame) -> pd.DataFrame:
    if history_df.empty:
        return pd.DataFrame(columns=["nm_id", "supplier_article", "product_name", "warehouse_name"])

    pivot_df = history_df.copy()
    pivot_df["snapshot_date_label"] = pivot_df["snapshot_date"].map(lambda value: value.isoformat() if pd.notna(value) else "")
    result = (
        pivot_df.pivot_table(
            index=["nm_id", "supplier_article", "product_name", "warehouse_name"],
            columns="snapshot_date_label",
            values="stock_qty",
            aggfunc="first",
            dropna=False,
        )
        .reset_index()
        .sort_values(["supplier_article", "nm_id", "warehouse_name"], na_position="last")
        .reset_index(drop=True)
    )
    result.columns.name = None
    return result


def should_render_stock_warehouse_history_pivot(
    pivot_df: pd.DataFrame,
    *,
    max_cells: int = STOCK_WAREHOUSE_HISTORY_PIVOT_MAX_CELLS,
) -> bool:
    if pivot_df.empty:
        return True
    return int(pivot_df.shape[0] * pivot_df.shape[1]) <= max_cells


def build_stock_warehouse_history_ivan_check_table(history_df: pd.DataFrame) -> pd.DataFrame:
    columns = [
        "nm_id",
        "supplier_article",
        "product_name",
        "warehouse_name",
        "days_with_stock",
        "days_zero",
        "days_no_data",
        "anomaly_type",
        "comment_for_ivan",
    ]
    if history_df.empty:
        return pd.DataFrame(columns=columns)

    summary = (
        history_df.groupby(
            ["nm_id", "supplier_article", "product_name", "warehouse_name", "anomaly_type"],
            dropna=False,
            as_index=False,
        )
        .agg(
            days_with_stock=("stock_status", lambda values: int((pd.Series(values) == STOCK_HISTORY_STATUS_IN_STOCK).sum())),
            days_zero=("stock_status", lambda values: int((pd.Series(values) == STOCK_HISTORY_STATUS_ZERO).sum())),
            days_no_data=("stock_status", lambda values: int((pd.Series(values) == STOCK_HISTORY_STATUS_NO_DATA).sum())),
        )
    )
    summary = summary[summary["anomaly_type"].ne(STOCK_HISTORY_ANOMALY_ALWAYS_IN_STOCK)].copy()
    comment_map = {
        STOCK_HISTORY_ANOMALY_ALWAYS_NO_DATA: "Нет строк по складу во всём выбранном периоде.",
        STOCK_HISTORY_ANOMALY_ALWAYS_ZERO: "Остаток всё время нулевой.",
        STOCK_HISTORY_ANOMALY_MIXED_ZERO_AND_STOCK: "Остаток переключается между нулём и наличием.",
        STOCK_HISTORY_ANOMALY_MIXED_NO_DATA_AND_STOCK: "Есть дни без данных и дни с остатком.",
        STOCK_HISTORY_ANOMALY_UNSTABLE: "Смешаны ноль, наличие и/или отсутствие данных.",
    }
    summary["comment_for_ivan"] = summary["anomaly_type"].map(lambda value: comment_map.get(str(value), "Проверьте историю склада."))
    return summary.reindex(columns=columns).sort_values(
        ["anomaly_type", "supplier_article", "nm_id", "warehouse_name"],
        na_position="last",
    ).reset_index(drop=True)


def _normalize_stock_display_value(value: object) -> int | float | object:
    if pd.isna(value):
        return pd.NA
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


def _build_problem_status(*, warehouse_count: int, zero_count: int, no_data_count: int) -> str:
    if warehouse_count <= 0 or no_data_count >= warehouse_count:
        return PROBLEM_STATUS_NO_DATA_MAIN
    if zero_count > 0:
        return PROBLEM_STATUS_ZERO_MAIN
    if no_data_count > 0:
        return PROBLEM_STATUS_PARTIAL_STOCK
    return STOCK_STATUS_OK


def _lifecycle_sort_priority(value: object) -> int:
    normalized = str(value or "").strip().lower()
    if normalized == "active":
        return 0
    if normalized == "sellout":
        return 2
    return 1


def _problem_sort_priority(value: object) -> int:
    priorities = {
        PROBLEM_STATUS_ZERO_MAIN: 0,
        PROBLEM_STATUS_PARTIAL_STOCK: 1,
        PROBLEM_STATUS_NO_DATA_MAIN: 2,
        STOCK_STATUS_OK: 3,
    }
    return priorities.get(str(value or ""), 99)


def build_stock_warehouse_product_table(
    snapshot_df: pd.DataFrame,
    tracked_df: pd.DataFrame,
    *,
    snapshot_date: date,
    selected_warehouses: list[str],
    main_warehouses: list[str] | None = None,
    show_only_tracked: bool,
    show_sellout: bool,
    search_queries_dict: dict[str, int] | None = None,
    coefficients_dict: dict[str, Decimal] | None = None,
    warehouse_areas_dict: dict[str, tuple[str, Decimal]] | None = None,
    app_lookup: dict[tuple[date, int], tuple[float, float, float]] | None = None,
    calculated_conversions_dict: dict[str, float] | None = None,
) -> pd.DataFrame:
    warehouse_names = list(dict.fromkeys(selected_warehouses))
    main_warehouse_names = [warehouse for warehouse in dict.fromkeys(main_warehouses or warehouse_names) if warehouse]
    if not main_warehouse_names:
        main_warehouse_names = warehouse_names.copy()
    snapshot_prepared = prepare_stock_warehouse_snapshot_dataframe(snapshot_df)
    tracked_prepared = tracked_df.copy()
    for column in ("nm_id", "tracked_label", "is_tracked", "lifecycle_status", "query_group"):
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

    tracked_columns = ["nm_id", "tracked_label", "is_tracked", "lifecycle_status", "query_group"]
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
                "query_group",
                "lifecycle_status",
                *warehouse_names,
                "total_main_warehouses",
                "warehouses_with_stock",
                "zero_warehouses_count",
                "no_data_warehouses_count",
                "search_queries",
                "zone_share_pct",
                "conversion_pct",
                "profit_per_order",
                "lost_orders",
                "lost_profit_rub",
                "zero_warehouses",
                "no_data_warehouses",
                "problem_warehouses",
                "stock_status",
                "problem_status",
            ]
        )

    if not show_sellout:
        base_products = base_products[base_products["lifecycle_status"].fillna("not_tracked").ne("sellout")].copy()

    current_snapshot_unfiltered = snapshot_prepared[snapshot_prepared["snapshot_date"] == snapshot_date].copy()
    current_snapshot_unfiltered = current_snapshot_unfiltered.groupby(["nm_id", "warehouse_name"], as_index=False)[
        ["stock_qty", "in_way_to_client", "in_way_from_client"]
    ].sum(min_count=1)

    unfiltered_stock_lookup = {
        (int(row["nm_id"]), str(row["warehouse_name"])): row["stock_qty"]
        for _, row in current_snapshot_unfiltered.iterrows()
    }

    # Заранее соберем нулевые склады для каждого nm_id по всем складам из snapshot
    zero_warehouses_by_nm: dict[int, list[str]] = {}
    for (nm_id_key, wh_name), qty in unfiltered_stock_lookup.items():
        display_val = _normalize_stock_display_value(qty)
        if not pd.isna(display_val) and float(display_val) == 0:
            zero_warehouses_by_nm.setdefault(nm_id_key, []).append(wh_name)

    if search_queries_dict is None:
        search_queries_dict = load_search_queries_by_date_from_db(snapshot_date)
    if calculated_conversions_dict is None:
        calculated_conversions_dict = calculate_lost_profit_conversions_from_db(snapshot_date)
    if coefficients_dict is None:
        coefficients_dict = load_lost_profit_coefficients_from_db()
    if warehouse_areas_dict is None:
        warehouse_areas_dict = load_warehouse_market_areas_from_db()
    if app_lookup is None:
        app_lookup = {}
        try:
            app_df, _ = load_app_dataset()
            if not app_df.empty:
                app_df_copy = app_df.copy()
                app_df_copy["report_date"] = pd.to_datetime(app_df_copy["report_date"], errors="coerce").dt.date
                for _, row in app_df_copy.iterrows():
                    rep_date = row["report_date"]
                    nm = int(row["nm_id"]) if not pd.isna(row["nm_id"]) else None
                    if rep_date and nm:
                        app_lookup[(rep_date, nm)] = (
                            row.get("order_sum"),
                            row.get("order_count"),
                            row.get("wb_buyer_price")
                        )
        except Exception:
            logger.warning("Could not load app dataset for lost profit calculations, using empty lookup.")

    rows: list[dict[str, object]] = []
    for _, product_row in base_products.sort_values(["tracked_label", "nm_id"], na_position="last").iterrows():
        nm_id = int(product_row["nm_id"])
        has_any_snapshot = nm_id in any_snapshot_nm_ids_for_date
        query_group = product_row.get("query_group")
        row: dict[str, object] = {
            "nm_id": nm_id,
            "tracked_label": product_row.get("tracked_label"),
            "query_group": query_group,
            "lifecycle_status": product_row.get("lifecycle_status") or "not_tracked",
        }
        zero_warehouses = sorted(zero_warehouses_by_nm.get(nm_id, []))
        no_data_warehouses: list[str] = []
        total_main_warehouses = 0.0
        warehouses_with_stock = 0

        for warehouse_name in warehouse_names:
            quantity = unfiltered_stock_lookup.get((nm_id, warehouse_name), pd.NA)
            display_value = _normalize_stock_display_value(quantity)
            row[warehouse_name] = display_value
            if warehouse_name not in main_warehouse_names:
                continue
            if pd.isna(display_value):
                no_data_warehouses.append(warehouse_name)
                continue
            numeric_value = float(display_value)
            total_main_warehouses += numeric_value
            if numeric_value > 0:
                warehouses_with_stock += 1

        row["total_main_warehouses"] = int(total_main_warehouses) if total_main_warehouses.is_integer() else round(total_main_warehouses, 2)
        row["warehouses_with_stock"] = warehouses_with_stock
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
        row["problem_status"] = _build_problem_status(
            warehouse_count=len(main_warehouse_names),
            zero_count=len(zero_warehouses),
            no_data_count=len(no_data_warehouses),
        )

        search_val = pd.NA
        if pd.notna(query_group) and query_group and query_group not in ("unknown", "Не определена"):
            if query_group in search_queries_dict:
                search_val = search_queries_dict[query_group]
        row["search_queries"] = search_val

        zone_share_pct = pd.NA
        conversion_pct = pd.NA
        lost_orders_val = pd.NA
        lost_profit_val = pd.NA

        # Fixed profit per order setting for all rows
        profit_per_order_val = settings.profit_per_order_rub

        if pd.notna(query_group) and query_group and query_group not in ("unknown", "Не определена") and not pd.isna(search_val):
            coef = None
            if calculated_conversions_dict is not None:
                coef = calculated_conversions_dict.get(query_group)
            if coef is None and coefficients_dict is not None:
                coef = coefficients_dict.get(query_group)
            if coef is not None:
                conversion_pct = float(coef) * 100.0

            if zero_warehouses:
                sum_share = 0.0
                missing_component = False
                for wh in zero_warehouses:
                    wh_info = warehouse_areas_dict.get(wh)
                    if wh_info is None:
                        missing_component = True
                        break
                    market_area_code, pop_share = wh_info
                    if pop_share is None or pd.isna(pop_share):
                        missing_component = True
                        break
                    sum_share += float(pop_share)
                
                if not missing_component:
                    zone_share_pct = sum_share

            if pd.notna(zone_share_pct) and pd.notna(conversion_pct):
                lost_impressions = float(search_val) * float(zone_share_pct) / 100.0
                lost_orders_val = lost_impressions * float(coef)
                lost_profit_val = lost_orders_val * float(profit_per_order_val)

        row["zone_share_pct"] = zone_share_pct
        row["conversion_pct"] = conversion_pct
        row["profit_per_order"] = profit_per_order_val
        row["lost_orders"] = lost_orders_val
        row["lost_profit_rub"] = lost_profit_val

        rows.append(row)

    result = pd.DataFrame(rows)
    result["_lifecycle_priority"] = result["lifecycle_status"].map(_lifecycle_sort_priority)
    result["_problem_priority"] = result["problem_status"].map(_problem_sort_priority)
    result = result.sort_values(
        by=[
            "_lifecycle_priority",
            "_problem_priority",
            "zero_warehouses_count",
            "no_data_warehouses_count",
            "tracked_label",
            "nm_id",
        ],
        ascending=[True, True, False, False, True, True],
        na_position="last",
    )
    return result.drop(columns=["_lifecycle_priority", "_problem_priority"]).reset_index(drop=True)


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
        "ok_products": int(product_table["problem_status"].eq(STOCK_STATUS_OK).sum()) if "problem_status" in product_table.columns else int(product_table["stock_status"].eq(STOCK_STATUS_OK).sum()),
        "zero_products": int(product_table["problem_status"].eq(PROBLEM_STATUS_ZERO_MAIN).sum()) if "problem_status" in product_table.columns else int(product_table["stock_status"].eq(STOCK_STATUS_ZERO).sum()),
        "no_data_products": int(product_table["problem_status"].isin([PROBLEM_STATUS_PARTIAL_STOCK, PROBLEM_STATUS_NO_DATA_MAIN]).sum()) if "problem_status" in product_table.columns else int(product_table["stock_status"].isin([STOCK_STATUS_NO_DATA, STOCK_STATUS_NO_PRODUCT_DATA]).sum()),
        "total_zero_warehouses": int(pd.to_numeric(product_table["zero_warehouses_count"], errors="coerce").fillna(0).sum()),
    }


def build_stock_warehouse_problem_profit_total(problem_table: pd.DataFrame) -> float:
    if problem_table.empty or "lost_profit_rub" not in problem_table.columns:
        return 0.0
    return float(pd.to_numeric(problem_table["lost_profit_rub"], errors="coerce").fillna(0).sum())


def build_stock_warehouse_summary_card_html(label: str, value: object, *, compact: bool = True) -> str:
    value_font_size = "1.35rem" if compact else "1.8rem"
    label_font_size = "0.72rem" if compact else "0.82rem"
    padding = "0.55rem 0.7rem" if compact else "0.8rem 0.9rem"
    min_height = "94px" if compact else "112px"
    return (
        f'<div style="border:1px solid #e5e7eb;border-radius:12px;background:#ffffff;'
        f'padding:{padding};min-height:{min_height};display:flex;flex-direction:column;justify-content:space-between;box-sizing:border-box;">'
        f'<div style="font-size:{label_font_size};line-height:1.2;color:#6b7280;min-height:2.1rem;">{escape(str(label))}</div>'
        f'<div style="font-size:{value_font_size};line-height:1.1;font-weight:700;color:#111827;min-height:1.7rem;display:flex;align-items:flex-end;">{escape(str(value))}</div>'
        f"</div>"
    )


def format_summary_rub(value: float) -> str:
    return f"{value:,.0f} ₽".replace(",", " ")


def resolve_stock_warehouse_default_snapshot_date(
    available_dates: list[date],
    report_day: date,
) -> date:
    if not available_dates:
        return report_day
    if report_day in available_dates:
        return report_day
    return available_dates[-1]


def build_dashboard_summary_card_html(label: str, value: object) -> str:
    return (
        '<div style="border:1px solid #e5e7eb;border-radius:12px;background:#ffffff;'
        'padding:0.62rem 0.8rem;min-height:86px;display:flex;flex-direction:column;justify-content:space-between;">'
        f'<div style="font-size:0.9rem;line-height:1.15;color:#6b7280;min-height:2.1rem;">{escape(str(label))}</div>'
        f'<div style="font-size:1.52rem;line-height:1;font-weight:700;color:#111827;margin-top:0.16rem;">{escape(str(value))}</div>'
        "</div>"
    )


def render_compact_metric_css() -> None:
    st.markdown(
        """
        <style>
        div[data-testid="stMetric"] label[data-testid="stMetricLabel"] p {
            font-size: 0.6rem;
        }
        div[data-testid="stMetric"] div[data-testid="stMetricValue"] {
            font-size: 1rem;
        }
        </style>
        """,
        unsafe_allow_html=True,
    )


def build_stock_warehouse_problem_table(product_table: pd.DataFrame) -> pd.DataFrame:
    if product_table.empty:
        return pd.DataFrame(
            columns=[
                "nm_id", "tracked_label", "query_group", "lifecycle_status",
                "total_main_warehouses", "warehouses_with_stock",
                "zero_warehouses_count", "no_data_warehouses_count",
                "zero_warehouses", "no_data_warehouses",
                "search_queries", "zone_share_pct", "conversion_pct",
                "profit_per_order", "lost_orders", "lost_profit_rub",
                "problem_status"
            ]
        )
    status_column = "problem_status" if "problem_status" in product_table.columns else "stock_status"
    return product_table.loc[
        product_table[status_column].ne(STOCK_STATUS_OK),
        [
            "nm_id", "tracked_label", "query_group", "lifecycle_status",
            "total_main_warehouses", "warehouses_with_stock",
            "zero_warehouses_count", "no_data_warehouses_count",
            "zero_warehouses", "no_data_warehouses",
            "search_queries", "zone_share_pct", "conversion_pct",
            "profit_per_order", "lost_orders", "lost_profit_rub",
            status_column
        ],
    ].copy()


def build_stock_warehouse_display_dataframe(
    df: pd.DataFrame,
    *,
    problem_table: bool,
) -> pd.DataFrame:
    safe_df = df.copy()
    safe_df.attrs = {}
    safe_df = safe_df.replace("NO_DATA", STOCK_WAREHOUSE_NO_DATA_DISPLAY)

    lifecycle_label_map = {
        "active": "Основной",
        "sellout": "Распродажа",
    }
    problem_label_map = {
        STOCK_STATUS_OK: "В наличии на складах",
        STOCK_STATUS_ZERO: "Есть нулевые остатки",
        STOCK_STATUS_NO_DATA: "Нет данных по части складов",
        STOCK_STATUS_NO_PRODUCT_DATA: "Нет данных по товару",
        PROBLEM_STATUS_ZERO_MAIN: "Есть нулевые остатки",
        PROBLEM_STATUS_PARTIAL_STOCK: "Нет данных по части складов",
        PROBLEM_STATUS_NO_DATA_MAIN: "Нет данных по товару",
    }

    if "lifecycle_status" in safe_df.columns:
        safe_df["lifecycle_status"] = safe_df["lifecycle_status"].map(
            lambda value: lifecycle_label_map.get(str(value), value)
        )
    if "query_group" in safe_df.columns:
        safe_df["query_group"] = safe_df["query_group"].map(
            lambda value: format_query_group_label(value, undefined_label=QUERY_GROUP_UNDEFINED_LABEL)
        )

    status_column = "problem_status" if "problem_status" in safe_df.columns else "stock_status"
    if status_column in safe_df.columns:
        safe_df["Проблема"] = safe_df[status_column].map(
            lambda value: problem_label_map.get(str(value), value)
        )

    if problem_table:
        display_df = safe_df.rename(
            columns={
                "nm_id": "Артикул WB",
                "tracked_label": "Название",
                "query_group": "Товарная группа",
                "lifecycle_status": "Статус товара",
                "total_main_warehouses": "Итого по осн. складам",
                "warehouses_with_stock": "Складов в наличии",
                "zero_warehouses_count": "Складов с нулём",
                "no_data_warehouses_count": "Складов без данных",
                "zero_warehouses": "Нулевые склады",
                "no_data_warehouses": "Склады без данных",
                "search_queries": "Поисковые запросы",
                "zone_share_pct": "Доля зоны, %",
                "conversion_pct": "Конв. поиск→заказ, %",
                "profit_per_order": "Прибыль/заказ, ₽",
                "lost_orders": "Упущ. заказы",
                "lost_profit_rub": "Потенц. прибыль, ₽",
            }
        )
        return display_df.reindex(
            columns=[
                "Артикул WB",
                "Название",
                "Товарная группа",
                "Статус товара",
                "Итого по осн. складам",
                "Складов в наличии",
                "Складов с нулём",
                "Складов без данных",
                "Нулевые склады",
                "Склады без данных",
                "Поисковые запросы",
                "Доля зоны, %",
                "Конв. поиск→заказ, %",
                "Прибыль/заказ, ₽",
                "Упущ. заказы",
                "Потенц. прибыль, ₽",
                "Проблема",
            ]
        )

    display_df = safe_df.rename(
        columns={
            "nm_id": "Артикул WB",
            "tracked_label": "Название",
            "query_group": "Товарная группа",
            "lifecycle_status": "Статус товара",
            "total_main_warehouses": "Итого по осн. складам",
            "warehouses_with_stock": "Складов в наличии",
            "zero_warehouses_count": "Складов с нулём",
            "no_data_warehouses_count": "Складов без данных",
            "search_queries": "Поисковые запросы",
            "lost_profit_rub": "Потенц. прибыль, ₽",
        }
    )
    return display_df.drop(
        columns=[column for column in ("problem_status", "stock_status") if column in display_df.columns]
    )


def style_stock_warehouse_table(
    df: pd.DataFrame,
    warehouse_columns: list[str],
) -> pd.io.formats.style.Styler:
    def warehouse_value_color(value: object) -> str:
        if pd.isna(value):
            return "background-color: #e5e7eb; color: #4b5563;"
        try:
            if float(value) == 0:
                return "background-color: #fde2e4; color: #7f1d1d;"
        except (TypeError, ValueError):
            return ""
        return ""

    def stock_status_color(value: object) -> str:
        if value in (STOCK_STATUS_OK, "В наличии на складах"):
            return "background-color: #e8f5e9; color: #1b5e20;"
        if value in (STOCK_STATUS_ZERO, PROBLEM_STATUS_ZERO_MAIN, "Есть нулевые остатки"):
            return "background-color: #fff3cd; color: #7a4b00;"
        if value in (
            STOCK_STATUS_NO_DATA,
            STOCK_STATUS_NO_PRODUCT_DATA,
            PROBLEM_STATUS_PARTIAL_STOCK,
            PROBLEM_STATUS_NO_DATA_MAIN,
            "Нет данных по части складов",
            "Нет данных по товару",
        ):
            return "background-color: #e5e7eb; color: #374151;"
        return ""

    def format_search_queries(x):
        if pd.isna(x) or x in ("—", "NO_DATA", ""):
            return "—"
        try:
            return f"{float(x):,.0f}".replace(",", " ")
        except (ValueError, TypeError):
            return str(x)

    def format_zone_share(x):
        if pd.isna(x) or x in ("—", "NO_DATA", ""):
            return "—"
        try:
            return f"{float(x):.2f}%"
        except (ValueError, TypeError):
            return str(x)

    def format_pct_3_4(x):
        if pd.isna(x) or x in ("—", "NO_DATA", ""):
            return "—"
        try:
            val = float(x)
            if abs(val * 1000 - round(val * 1000)) > 1e-6:
                return f"{val:.4f}%"
            return f"{val:.3f}%"
        except (ValueError, TypeError):
            return str(x)

    def format_profit_per_order(x):
        if pd.isna(x) or x in ("—", "NO_DATA", ""):
            return "—"
        try:
            val = float(x)
            if val.is_integer():
                return f"{val:,.0f}".replace(",", " ")
            return f"{val:,.2f}".replace(",", " ")
        except (ValueError, TypeError):
            return str(x)

    def format_lost_orders(x):
        if pd.isna(x) or x in ("—", "NO_DATA", ""):
            return "—"
        try:
            return f"{float(x):.2f}"
        except (ValueError, TypeError):
            return str(x)

    def format_potential_profit(x):
        if pd.isna(x) or x in ("—", "NO_DATA", ""):
            return "—"
        try:
            return f"{float(x):,.0f}".replace(",", " ")
        except (ValueError, TypeError):
            return str(x)

    format_dict = {}
    if "Поисковые запросы" in df.columns:
        format_dict["Поисковые запросы"] = format_search_queries
    if "Доля зоны, %" in df.columns:
        format_dict["Доля зоны, %"] = format_zone_share
    if "Конв. поиск→заказ, %" in df.columns:
        format_dict["Конв. поиск→заказ, %"] = format_pct_3_4
    if "Прибыль/заказ, ₽" in df.columns:
        format_dict["Прибыль/заказ, ₽"] = format_profit_per_order
    if "Упущ. заказы" in df.columns:
        format_dict["Упущ. заказы"] = format_lost_orders
    if "Потенц. прибыль, ₽" in df.columns:
        format_dict["Потенц. прибыль, ₽"] = format_potential_profit

    styler = df.style
    if warehouse_columns:
        styler = styler.map(warehouse_value_color, subset=warehouse_columns)
    if "Проблема" in df.columns:
        styler = styler.map(stock_status_color, subset=["Проблема"])
    elif "problem_status" in df.columns:
        styler = styler.map(stock_status_color, subset=["problem_status"])
    elif "stock_status" in df.columns:
        styler = styler.map(stock_status_color, subset=["stock_status"])
    return styler.format(format_dict, precision=0, na_rep="—")


def prepare_stock_warehouse_table_for_display(
    df: pd.DataFrame,
    warehouse_columns: list[str],
) -> pd.DataFrame | pd.io.formats.style.Styler:
    numeric_columns = set(warehouse_columns) | {
        "Артикул WB",
        "Итого по осн. складам",
        "Складов в наличии",
        "Складов с нулём",
        "Складов без данных",
        "Поисковые запросы",
        "Доля зоны, %",
        "Конв. поиск→заказ, %",
        "Прибыль/заказ, ₽",
        "Упущ. заказы",
        "Потенц. прибыль, ₽",
    }
    safe_df = sanitize_dataframe_for_streamlit_display(df, numeric_columns=numeric_columns)
    return style_stock_warehouse_table(safe_df, warehouse_columns)



# ---------------------------------------------------------------------------
# Контроль всех остатков — вспомогательные функции
# ---------------------------------------------------------------------------

def build_stock_all_product_level(
    snapshot_df: "pd.DataFrame",
    settings_df: "pd.DataFrame",
    snapshot_date: "date",
    one_c_stock_df: "pd.DataFrame | None" = None,
    tracked_df: "pd.DataFrame | None" = None,
    wb_supply_df: "pd.DataFrame | None" = None,
    product_size_df: "pd.DataFrame | None" = None,
) -> "pd.DataFrame":
    """
    Агрегирует fact_stock_warehouse_snapshot до уровня nm_id за выбранную дату.

    Возвращает product-level DataFrame:
    - band (= query_group из settings_products)
    - nm_id, vendor_code (supplier_article)
    - wb_stock_qty          = SUM(stock_qty)
    - wb_in_way_to_client   = SUM(in_way_to_client)  [уже ушли покупателям]
    - wb_in_way_from_client = SUM(in_way_from_client) [возвраты в пути]
    - wb_total_in_contour   = сумма трёх компонентов
    - one_c_stock_qty       = None  (источник не подключён)
    - wb_supply_qty         = None  (поставки на склад WB — отдельный источник)
    """
    empty_cols = [
        "query_group", "band", "band_name", "nm_id", "vendor_code", "title",
        "wb_stock_qty", "wb_in_way_to_client", "wb_in_way_from_client",
        "wb_total_in_contour", "one_c_stock_qty", "wb_supply_qty", "wb_vs_one_c_diff",
    ]
    if settings_df.empty and snapshot_df.empty:
        return pd.DataFrame(columns=empty_cols)

    # 1. Сбор базового allowlist только из tracked_products, settings_df — лишь справочник метаданных
    metadata_df = pd.DataFrame(columns=["nm_id", "query_group", "supplier_article", "title"])
    if not settings_df.empty:
        s = settings_df.copy()
        s["nm_id"] = pd.to_numeric(s["nm_id"], errors="coerce")
        s = s.dropna(subset=["nm_id"])
        s["nm_id"] = s["nm_id"].astype(int)
        keep = ["nm_id"]
        for col in ("query_group", "supplier_article", "title"):
            if col in s.columns:
                keep.append(col)
        metadata_df = s[keep].drop_duplicates(subset=["nm_id"]).copy()

    base_df = pd.DataFrame(columns=["nm_id", "query_group", "supplier_article", "title", "tracked_label"])
    if tracked_df is not None and not tracked_df.empty:
        tracked_base = tracked_df.copy()
        tracked_base["nm_id"] = pd.to_numeric(tracked_base.get("nm_id"), errors="coerce")
        tracked_base = tracked_base.dropna(subset=["nm_id"]).copy()
        tracked_base["nm_id"] = tracked_base["nm_id"].astype(int)
        if "is_tracked" in tracked_base.columns:
            tracked_base["is_tracked"] = tracked_base["is_tracked"].fillna(False).astype(bool)
            tracked_base = tracked_base[tracked_base["is_tracked"]].copy()
        if "tracked_label" not in tracked_base.columns:
            tracked_base["tracked_label"] = pd.NA
        tracked_base = tracked_base[["nm_id", "tracked_label"]].drop_duplicates(subset=["nm_id"]).copy()
        if not tracked_base.empty:
            if not metadata_df.empty:
                base_df = tracked_base.merge(metadata_df, on="nm_id", how="left")
            else:
                base_df = tracked_base.copy()
                base_df["query_group"] = pd.NA
                base_df["supplier_article"] = pd.NA
                base_df["title"] = pd.NA
    elif not metadata_df.empty:
        base_df = metadata_df.copy()
        base_df["tracked_label"] = pd.NA

    # 2. Агрегация остатков WB
    if not snapshot_df.empty:
        prepared_snapshot_df = snapshot_df.copy()
        prepared_snapshot_df["snapshot_date"] = pd.to_datetime(
            prepared_snapshot_df["snapshot_date"],
            errors="coerce",
        ).dt.date
        day_df = prepared_snapshot_df[prepared_snapshot_df["snapshot_date"] == snapshot_date].copy()
    else:
        day_df = pd.DataFrame()
    if not day_df.empty:
        for col in ("stock_qty", "in_way_to_client", "in_way_from_client"):
            if col not in day_df.columns:
                day_df[col] = pd.NA
            day_df[col] = pd.to_numeric(day_df[col], errors="coerce")

        agg = (
            day_df.groupby("nm_id", as_index=False)[
                ["stock_qty", "in_way_to_client", "in_way_from_client"]
            ]
            .sum(min_count=1)
            .rename(columns={
                "stock_qty": "wb_stock_qty",
                "in_way_to_client": "wb_in_way_to_client",
                "in_way_from_client": "wb_in_way_from_client",
            })
        )
        tmp = agg[["wb_stock_qty", "wb_in_way_to_client", "wb_in_way_from_client"]]
        has_any = tmp.notna().any(axis=1)
        agg["wb_total_in_contour"] = tmp.sum(axis=1, min_count=1).where(has_any, other=pd.NA)
    else:
        agg = pd.DataFrame(columns=["nm_id", "wb_stock_qty", "wb_in_way_to_client", "wb_in_way_from_client", "wb_total_in_contour"])

    agg["nm_id"] = pd.to_numeric(agg["nm_id"], errors="coerce")
    agg = agg.dropna(subset=["nm_id"])
    agg["nm_id"] = agg["nm_id"].astype(int)

    # 3. Соединение базового фрейма и остатков WB
    if not base_df.empty:
        agg = base_df.merge(agg, on="nm_id", how="left")
    else:
        if day_df.empty:
            return pd.DataFrame(columns=empty_cols)
        agg["query_group"] = pd.NA
        agg["supplier_article"] = pd.NA
        agg["title"] = pd.NA
        agg["tracked_label"] = pd.NA

    # 4. Прикрепление остатков 1С
    agg["one_c_stock_qty"] = pd.NA
    agg["wb_supply_qty"] = pd.NA

    if one_c_stock_df is not None and not one_c_stock_df.empty:
        one_c_df = one_c_stock_df.copy()
        one_c_df["nm_id"] = pd.to_numeric(one_c_df.get("nm_id"), errors="coerce")
        one_c_df["ivan_stock_qty"] = _clip_non_negative_numeric_series(one_c_df.get("ivan_stock_qty"))
        one_c_df = one_c_df.dropna(subset=["nm_id"]).copy()
        if not one_c_df.empty:
            one_c_df["nm_id"] = one_c_df["nm_id"].astype(int)
            one_c_df = (
                one_c_df.groupby("nm_id", as_index=False)["ivan_stock_qty"]
                .sum(min_count=1)
                .rename(columns={"ivan_stock_qty": "one_c_stock_qty"})
            )
            agg = agg.drop(columns=["one_c_stock_qty"], errors="ignore").merge(one_c_df, on="nm_id", how="left")

    if wb_supply_df is not None and not wb_supply_df.empty:
        supply_df = wb_supply_df.copy()
        supply_df["nm_id"] = pd.to_numeric(supply_df.get("nm_id"), errors="coerce")
        supply_df["wb_supply_qty"] = pd.to_numeric(supply_df.get("wb_supply_qty"), errors="coerce")
        if "vendor_code" not in supply_df.columns:
            supply_df["vendor_code"] = pd.NA
        if "barcode" not in supply_df.columns:
            supply_df["barcode"] = pd.NA

        supply_df["vendor_code"] = supply_df["vendor_code"].fillna("").astype(str).str.strip()
        supply_df["barcode_normalized"] = supply_df["barcode"].map(_normalize_stock_size_barcode)
        supply_df["resolved_nm_id"] = pd.NA

        main_barcode_column = next((column for column in ("barcode", "barcode_clean", "Баркод") if column in agg.columns), None)
        main_df_has_barcode = main_barcode_column is not None
        matched_by_barcode = 0
        matched_by_nm_id = 0
        matched_by_vendor_code = 0

        if main_barcode_column is not None:
            agg["__main_barcode"] = agg[main_barcode_column].map(_normalize_stock_size_barcode)
            direct_barcode_lookup = (
                supply_df.dropna(subset=["barcode_normalized", "wb_supply_qty"])
                .groupby("barcode_normalized")["wb_supply_qty"]
                .sum(min_count=1)
            )
            direct_barcode_series = agg["__main_barcode"].map(direct_barcode_lookup)
            agg["wb_supply_qty"] = agg["wb_supply_qty"].where(agg["wb_supply_qty"].notna(), direct_barcode_series)
            matched_by_barcode = int(agg["wb_supply_qty"].notna().sum())

        if product_size_df is not None and not product_size_df.empty:
            prepared_product_size = product_size_df.copy()
            prepared_product_size["nm_id"] = pd.to_numeric(prepared_product_size.get("nm_id"), errors="coerce")
            prepared_product_size["barcode_normalized"] = prepared_product_size.get("barcode").map(_normalize_stock_size_barcode)
            prepared_product_size = prepared_product_size.dropna(subset=["nm_id", "barcode_normalized"]).copy()
            if not prepared_product_size.empty:
                prepared_product_size["nm_id"] = prepared_product_size["nm_id"].astype(int)
                barcode_mapping_df = (
                    prepared_product_size.groupby("barcode_normalized", as_index=False)
                    .agg(nm_id=("nm_id", "first"), nm_id_count=("nm_id", pd.Series.nunique))
                )
                barcode_mapping_df = barcode_mapping_df[barcode_mapping_df["nm_id_count"] == 1].copy()
                if not barcode_mapping_df.empty:
                    barcode_nm_lookup = barcode_mapping_df.set_index("barcode_normalized")["nm_id"]
                    supply_df["resolved_nm_id"] = supply_df["barcode_normalized"].map(barcode_nm_lookup)

        barcode_mapped_supply_df = supply_df.dropna(subset=["resolved_nm_id", "wb_supply_qty"]).copy()
        if not barcode_mapped_supply_df.empty:
            barcode_mapped_supply_df["resolved_nm_id"] = barcode_mapped_supply_df["resolved_nm_id"].astype(int)
            barcode_supply_lookup = (
                barcode_mapped_supply_df.groupby("resolved_nm_id")["wb_supply_qty"]
                .sum(min_count=1)
            )
            before_fill = int(agg["wb_supply_qty"].notna().sum())
            barcode_series = agg["nm_id"].map(barcode_supply_lookup)
            agg["wb_supply_qty"] = agg["wb_supply_qty"].where(agg["wb_supply_qty"].notna(), barcode_series)
            matched_by_barcode += int(agg["wb_supply_qty"].notna().sum()) - before_fill

        nm_supply_df = supply_df[supply_df["resolved_nm_id"].isna()].dropna(subset=["nm_id", "wb_supply_qty"]).copy()
        if not nm_supply_df.empty:
            nm_supply_df["nm_id"] = nm_supply_df["nm_id"].astype(int)
            nm_supply_lookup = nm_supply_df.groupby("nm_id")["wb_supply_qty"].sum(min_count=1)
            before_fill = int(agg["wb_supply_qty"].notna().sum())
            nm_series = agg["nm_id"].map(nm_supply_lookup)
            agg["wb_supply_qty"] = agg["wb_supply_qty"].where(agg["wb_supply_qty"].notna(), nm_series)
            matched_by_nm_id = int(agg["wb_supply_qty"].notna().sum()) - before_fill

        vendor_supply_df = supply_df[supply_df["resolved_nm_id"].isna() & supply_df["nm_id"].isna()].copy()
        vendor_supply_df = vendor_supply_df[(vendor_supply_df["vendor_code"] != "") & vendor_supply_df["wb_supply_qty"].notna()]
        vendor_key_column = "vendor_code" if "vendor_code" in agg.columns else "supplier_article"
        if not vendor_supply_df.empty and vendor_key_column in agg.columns:
            vendor_lookup = vendor_supply_df.groupby("vendor_code")["wb_supply_qty"].sum(min_count=1)
            before_fill = int(agg["wb_supply_qty"].notna().sum())
            vendor_series = agg[vendor_key_column].fillna("").astype(str).str.strip().map(vendor_lookup)
            agg["wb_supply_qty"] = agg["wb_supply_qty"].where(agg["wb_supply_qty"].notna(), vendor_series)
            matched_by_vendor_code = int(agg["wb_supply_qty"].notna().sum()) - before_fill

        final_non_empty_supplies = int(agg["wb_supply_qty"].notna().sum())
        logger.info(
            "WB supply product-level diagnostics: supply_rows_count=%s, supply_rows_with_barcode=%s, main_df_rows=%s, main_df_has_barcode=%s, matched_by_barcode=%s, matched_by_nm_id=%s, matched_by_vendor_code=%s, final_non_empty_supplies=%s",
            len(supply_df),
            int(supply_df["barcode_normalized"].notna().sum()),
            len(agg),
            main_df_has_barcode,
            matched_by_barcode,
            matched_by_nm_id,
            matched_by_vendor_code,
            final_non_empty_supplies,
        )
        if final_non_empty_supplies == 0:
            sample_main_df = pd.DataFrame({
                "nm_id": agg.get("nm_id"),
                "vendor_code": agg.get(vendor_key_column) if vendor_key_column in agg.columns else pd.Series(dtype="object"),
            })
            if main_barcode_column is not None:
                sample_main_df["barcode"] = agg["__main_barcode"]
            logger.info(
                "WB supply product-level samples: supply_barcodes=%s, main_keys=%s",
                supply_df["barcode_normalized"].dropna().astype(str).head(10).tolist(),
                sample_main_df.head(10).to_dict(orient="records"),
            )
        agg = agg.drop(columns=["__main_barcode"], errors="ignore")

    agg["query_group"] = agg["query_group"].map(normalize_query_group_value)
    agg = agg.rename(columns={"supplier_article": "vendor_code"})
    agg["band"] = agg["query_group"]
    agg["band_name"] = agg["query_group"].map(build_stock_all_band_name)
    agg["title"] = agg["title"].where(agg["title"].notna(), agg.get("tracked_label"))
    agg["title"] = agg["title"].where(agg["title"].notna(), agg["vendor_code"])
    agg["title"] = agg["title"].where(agg["title"].notna(), agg["nm_id"].astype(str))
    wb_stock_series = pd.to_numeric(agg["wb_stock_qty"], errors="coerce")
    one_c_stock_series = pd.to_numeric(agg["one_c_stock_qty"], errors="coerce")
    agg["wb_vs_one_c_diff"] = (wb_stock_series - one_c_stock_series).where(
        wb_stock_series.notna() & one_c_stock_series.notna(),
        other=pd.NA,
    )

    for col in empty_cols:
        if col not in agg.columns:
            agg[col] = pd.NA

    return (
        agg[empty_cols]
        .sort_values(["title", "nm_id"], na_position="last")
        .reset_index(drop=True)
    )


def build_stock_all_band_level(product_df: "pd.DataFrame") -> "pd.DataFrame":
    """
    Агрегирует product-level до band-level.
    Null-значения (1С, поставки WB) сохраняются как null, не заменяются на 0.
    """
    empty_cols = [
        "band", "band_name", "products_count",
        "wb_stock_qty", "wb_in_way_to_client", "wb_in_way_from_client",
        "wb_total_in_contour", "one_c_stock_qty", "wb_supply_qty", "wb_vs_one_c_diff",
    ]
    if product_df.empty:
        return pd.DataFrame(columns=empty_cols)

    product_df = product_df.copy()
    if "one_c_stock_qty" in product_df.columns:
        product_df["one_c_stock_qty"] = _clip_non_negative_numeric_series(product_df["one_c_stock_qty"])
    if "band" not in product_df.columns:
        product_df["band"] = pd.NA

    if "query_group" not in product_df.columns:
        product_df["query_group"] = product_df["band"]

    for col in [
        "wb_stock_qty",
        "wb_in_way_to_client",
        "wb_in_way_from_client",
        "wb_total_in_contour",
        "one_c_stock_qty",
        "wb_supply_qty",
    ]:
        if col not in product_df.columns:
            product_df[col] = pd.NA
    product_df["query_group"] = product_df["query_group"].map(normalize_query_group_value)
    product_df["band"] = product_df["query_group"]
    if "band_name" not in product_df.columns:
        product_df["band_name"] = product_df["query_group"].map(build_stock_all_band_name)
    else:
        product_df["band_name"] = product_df["query_group"].map(build_stock_all_band_name)
    if product_df.empty:
        return pd.DataFrame(columns=empty_cols)

    agg = (
        product_df.groupby("band_name", as_index=False, dropna=False)
        .agg(
            products_count=("nm_id", "nunique"),
            band=("query_group", "first"),
            wb_stock_qty=("wb_stock_qty", lambda s: s.sum(min_count=1)),
            wb_in_way_to_client=("wb_in_way_to_client", lambda s: s.sum(min_count=1)),
            wb_in_way_from_client=("wb_in_way_from_client", lambda s: s.sum(min_count=1)),
            wb_total_in_contour=("wb_total_in_contour", lambda s: s.sum(min_count=1)),
            one_c_stock_qty=("one_c_stock_qty", lambda s: s.sum(min_count=1)),
            wb_supply_qty=("wb_supply_qty", lambda s: s.sum(min_count=1)),
        )
    )
    wb_stock_series = pd.to_numeric(agg["wb_stock_qty"], errors="coerce")
    one_c_stock_series = pd.to_numeric(agg["one_c_stock_qty"], errors="coerce")
    agg["wb_vs_one_c_diff"] = (wb_stock_series - one_c_stock_series).where(
        wb_stock_series.notna() & one_c_stock_series.notna(),
        other=pd.NA,
    )

    return agg[empty_cols].sort_values("band_name", na_position="last").reset_index(drop=True)


def _collect_stock_all_product_level_nm_ids(*frames: "pd.DataFrame | None") -> tuple[int, ...]:
    nm_ids: set[int] = set()
    for frame in frames:
        if frame is None or frame.empty or "nm_id" not in frame.columns:
            continue
        series = pd.to_numeric(frame["nm_id"], errors="coerce").dropna()
        if series.empty:
            continue
        nm_ids.update(series.astype(int).tolist())
    return tuple(sorted(nm_ids))


def _normalize_stock_size_barcode(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().replace(" ", "").replace("\xa0", "")
    if "." in text:
        integer_part, dot, fractional_part = text.partition(".")
        if dot and integer_part.isdigit() and fractional_part and set(fractional_part) == {"0"}:
            text = integer_part
    return text or None


def _normalize_stock_size_name(value: object) -> str | None:
    if value is None or pd.isna(value):
        return None
    text = str(value).strip().lower()
    text = " ".join(text.split())
    text = text.replace(" / ", "/").replace("/ ", "/").replace(" /", "/")
    if text == "sm":
        text = "s/m"
    return text or None


def build_stock_all_size_level(
    snapshot_df: "pd.DataFrame",
    settings_df: "pd.DataFrame",
    snapshot_date: "date",
    one_c_size_df: "pd.DataFrame | None" = None,
    product_size_df: "pd.DataFrame | None" = None,
) -> "pd.DataFrame":
    empty_cols = [
        "query_group",
        "band",
        "band_name",
        "nm_id",
        "vendor_code",
        "title",
        "chrt_id",
        "size_name",
        "barcode",
        "tech_size",
        "wb_size_stock_qty",
        "one_c_size_stock_qty",
        "wb_vs_one_c_size_diff",
        "match_source",
    ]

    prepared_snapshot_df = snapshot_df.copy()
    if "snapshot_date" in prepared_snapshot_df.columns:
        prepared_snapshot_df["snapshot_date"] = pd.to_datetime(
            prepared_snapshot_df["snapshot_date"],
            errors="coerce",
        ).dt.date
    wb_day_df = prepared_snapshot_df[prepared_snapshot_df["snapshot_date"] == snapshot_date].copy()
    one_c_day_df = (one_c_size_df.copy() if one_c_size_df is not None else pd.DataFrame())

    if wb_day_df.empty and one_c_day_df.empty:
        return pd.DataFrame(columns=empty_cols)

    wb_day_df["nm_id"] = pd.to_numeric(wb_day_df.get("nm_id"), errors="coerce")
    wb_day_df["chrt_id"] = pd.to_numeric(wb_day_df.get("chrt_id"), errors="coerce")
    wb_day_df["stock_qty"] = pd.to_numeric(wb_day_df.get("stock_qty"), errors="coerce")
    wb_day_df = wb_day_df.dropna(subset=["nm_id", "chrt_id"])
    if not wb_day_df.empty:
        wb_day_df["nm_id"] = wb_day_df["nm_id"].astype(int)
        wb_day_df["chrt_id"] = wb_day_df["chrt_id"].astype(int)
    wb_grouped = (
        wb_day_df.groupby(["nm_id", "chrt_id"], as_index=False)["stock_qty"]
        .sum(min_count=1)
        .rename(columns={"stock_qty": "wb_size_stock_qty"})
    )
    wb_lookup = {
        (int(row["nm_id"]), int(row["chrt_id"])): row["wb_size_stock_qty"]
        for row in wb_grouped.to_dict(orient="records")
    }

    one_c_day_df["nm_id"] = pd.to_numeric(one_c_day_df.get("nm_id"), errors="coerce")
    one_c_day_df["quantity"] = _clip_non_negative_numeric_series(one_c_day_df.get("quantity"))
    one_c_day_df = one_c_day_df.dropna(subset=["nm_id"]).copy()
    if not one_c_day_df.empty:
        one_c_day_df["nm_id"] = one_c_day_df["nm_id"].astype(int)
        one_c_day_df["barcode"] = one_c_day_df.get("barcode").map(_normalize_stock_size_barcode)
        one_c_grouped = (
            one_c_day_df.groupby(["nm_id", "size_name", "barcode"], dropna=False, as_index=False)["quantity"]
            .sum(min_count=1)
            .rename(columns={"quantity": "one_c_size_stock_qty"})
        )
    else:
        one_c_grouped = pd.DataFrame(columns=["nm_id", "size_name", "barcode", "one_c_size_stock_qty"])

    prepared_product_size = product_size_df.copy() if product_size_df is not None else pd.DataFrame()
    if not prepared_product_size.empty:
        prepared_product_size["nm_id"] = pd.to_numeric(prepared_product_size.get("nm_id"), errors="coerce")
        prepared_product_size["chrt_id"] = pd.to_numeric(prepared_product_size.get("chrt_id"), errors="coerce")
        prepared_product_size = prepared_product_size.dropna(subset=["nm_id", "chrt_id"]).copy()
        prepared_product_size["nm_id"] = prepared_product_size["nm_id"].astype(int)
        prepared_product_size["chrt_id"] = prepared_product_size["chrt_id"].astype(int)
        prepared_product_size["barcode"] = prepared_product_size.get("barcode").map(_normalize_stock_size_barcode)
        prepared_product_size["size_name"] = prepared_product_size.get("size_name").where(
            prepared_product_size.get("size_name").notna(),
            prepared_product_size.get("tech_size"),
        )
        prepared_product_size = prepared_product_size.drop_duplicates(
            subset=["nm_id", "chrt_id", "barcode", "size_name", "tech_size"],
            keep="first",
        )

    settings_meta: dict[int, dict[str, object]] = {}
    if not settings_df.empty:
        prepared_settings = settings_df.copy()
        prepared_settings["nm_id"] = pd.to_numeric(prepared_settings.get("nm_id"), errors="coerce")
        prepared_settings = prepared_settings.dropna(subset=["nm_id"]).copy()
        prepared_settings["nm_id"] = prepared_settings["nm_id"].astype(int)
        for row in prepared_settings.to_dict(orient="records"):
            nm_id = int(row["nm_id"])
            normalized_query_group = normalize_query_group_value(row.get("query_group"))
            settings_meta[nm_id] = {
                "query_group": normalized_query_group,
                "band": normalized_query_group,
                "band_name": build_stock_all_band_name(normalized_query_group),
                "vendor_code": row.get("supplier_article"),
                "title": row.get("title"),
            }

    def _with_product_meta(nm_id: int, payload: dict[str, object]) -> dict[str, object]:
        meta = settings_meta.get(nm_id, {})
        payload["query_group"] = meta.get("query_group")
        payload["band"] = meta.get("band")
        payload["band_name"] = meta.get("band_name", "Прочее")
        payload["vendor_code"] = meta.get("vendor_code")
        payload["title"] = meta.get("title") or meta.get("vendor_code") or str(nm_id)
        return payload

    barcode_matches: dict[tuple[int, str], dict[str, object] | None] = {}
    size_name_matches: dict[tuple[int, str], dict[str, object] | None] = {}
    chrt_meta: dict[tuple[int, int], list[dict[str, object]]] = {}
    for row in prepared_product_size.to_dict(orient="records") if not prepared_product_size.empty else []:
        nm_id = int(row["nm_id"])
        chrt_id = int(row["chrt_id"])
        clean_row = {
            "nm_id": nm_id,
            "chrt_id": chrt_id,
            "barcode": row.get("barcode"),
            "size_name": row.get("size_name"),
            "tech_size": row.get("tech_size"),
        }
        chrt_meta.setdefault((nm_id, chrt_id), []).append(clean_row)
        barcode_key = clean_row.get("barcode")
        if barcode_key:
            match_key = (nm_id, barcode_key)
            if match_key not in barcode_matches:
                barcode_matches[match_key] = clean_row
            elif barcode_matches[match_key] != clean_row:
                barcode_matches[match_key] = None
        size_key = _normalize_stock_size_name(clean_row.get("size_name") or clean_row.get("tech_size"))
        if size_key:
            match_key = (nm_id, size_key)
            if match_key not in size_name_matches:
                size_name_matches[match_key] = clean_row
            elif size_name_matches[match_key] != clean_row:
                size_name_matches[match_key] = None

    used_wb_keys: set[tuple[int, int]] = set()
    rows: list[dict[str, object]] = []

    for row in one_c_grouped.to_dict(orient="records"):
        nm_id = int(row["nm_id"])
        barcode = _normalize_stock_size_barcode(row.get("barcode"))
        size_name = row.get("size_name")
        size_key = _normalize_stock_size_name(size_name)
        matched_row: dict[str, object] | None = None
        match_source = "one_c_only"
        if barcode:
            matched_row = barcode_matches.get((nm_id, barcode))
            if matched_row is not None:
                match_source = "barcode"
        if matched_row is None and size_key:
            size_match = size_name_matches.get((nm_id, size_key))
            if size_match is not None:
                matched_row = size_match
                match_source = "size_name"

        chrt_id = int(matched_row["chrt_id"]) if matched_row else pd.NA
        wb_qty = pd.NA
        if matched_row:
            wb_key = (nm_id, int(matched_row["chrt_id"]))
            if wb_key in wb_lookup and wb_key not in used_wb_keys:
                wb_qty = wb_lookup[wb_key]
                used_wb_keys.add(wb_key)

        result_row = _with_product_meta(
            nm_id,
            {
                "nm_id": nm_id,
                "chrt_id": chrt_id,
                "size_name": size_name or (matched_row.get("size_name") if matched_row else None) or (matched_row.get("tech_size") if matched_row else None),
                "barcode": barcode or (matched_row.get("barcode") if matched_row else None),
                "tech_size": matched_row.get("tech_size") if matched_row else None,
                "wb_size_stock_qty": wb_qty,
                "one_c_size_stock_qty": row.get("one_c_size_stock_qty"),
                "match_source": match_source,
            },
        )
        wb_series = pd.to_numeric(pd.Series([result_row["wb_size_stock_qty"]]), errors="coerce")
        one_c_series = pd.to_numeric(pd.Series([result_row["one_c_size_stock_qty"]]), errors="coerce")
        result_row["wb_vs_one_c_size_diff"] = (
            wb_series - one_c_series
        ).where(wb_series.notna() & one_c_series.notna(), other=pd.NA).iloc[0]
        rows.append(result_row)

    for (nm_id, chrt_id), wb_qty in wb_lookup.items():
        if (nm_id, chrt_id) in used_wb_keys:
            continue
        representative = (chrt_meta.get((nm_id, chrt_id)) or [{}])[0]
        size_name = representative.get("size_name") or representative.get("tech_size") or f"chrt_id {chrt_id}"
        rows.append(
            _with_product_meta(
                nm_id,
                {
                    "nm_id": nm_id,
                    "chrt_id": chrt_id,
                    "size_name": size_name,
                    "barcode": representative.get("barcode"),
                    "tech_size": representative.get("tech_size"),
                    "wb_size_stock_qty": wb_qty,
                    "one_c_size_stock_qty": pd.NA,
                    "wb_vs_one_c_size_diff": pd.NA,
                    "match_source": "wb_only",
                },
            )
        )

    result = pd.DataFrame(rows)
    if result.empty:
        return pd.DataFrame(columns=empty_cols)
    for column in empty_cols:
        if column not in result.columns:
            result[column] = pd.NA
    return (
        result[empty_cols]
        .sort_values(["title", "nm_id", "size_name", "barcode"], na_position="last")
        .reset_index(drop=True)
    )


def build_stock_all_display_dataframe(
    product_df: "pd.DataFrame",
    *,
    level: str,
    snapshot_date: "date | None" = None,
    sales_df: "pd.DataFrame | None" = None,
) -> tuple["pd.DataFrame", set[str]]:
    if level == "По бандам":
        source_df = build_stock_all_band_level(product_df)
        source_columns = [
            "band_name",
            "products_count",
            "wb_stock_qty",
            "wb_in_way_to_client",
            "wb_in_way_from_client",
            "wb_total_in_contour",
            "one_c_stock_qty",
            "wb_supply_qty",
            "wb_vs_one_c_diff",
        ]
        rename_map = {
            "band_name": "Банда",
            "products_count": "Товаров",
            "wb_stock_qty": "Остаток WB на складах",
            "wb_in_way_to_client": "В пути к клиенту",
            "wb_in_way_from_client": "Возвраты в пути",
            "wb_total_in_contour": "Итого в контуре WB",
            "one_c_stock_qty": "Остаток 1С",
            "wb_supply_qty": "Поставки на WB",
        }
        ordered_columns = [
            "Банда",
            "Товаров",
            "Остаток WB на складах",
            "В пути к клиенту",
            "Возвраты в пути",
            "Итого в контуре WB",
            "Остаток 1С",
            "Поставки на WB",
        ]
        numeric_cols = {
            "Товаров",
            "Остаток WB на складах",
            "В пути к клиенту",
            "Возвраты в пути",
            "Итого в контуре WB",
        }
    else:
        source_df = product_df.copy()
        source_columns = [
            "band_name",
            "nm_id",
            "vendor_code",
            "title",
            "wb_stock_qty",
            "wb_in_way_to_client",
            "wb_in_way_from_client",
            "wb_total_in_contour",
            "one_c_stock_qty",
            "wb_supply_qty",
        ]
        rename_map = {
            "band_name": "Банда",
            "nm_id": "Артикул WB",
            "vendor_code": "Артикул продавца",
            "title": "Название",
            "wb_stock_qty": "Остаток WB на складах",
            "wb_in_way_to_client": "В пути к клиенту",
            "wb_in_way_from_client": "Возвраты в пути",
            "wb_total_in_contour": "Итого в контуре WB",
            "one_c_stock_qty": "Остаток 1С",
            "wb_supply_qty": "Поставки на WB",
        }
        ordered_columns = [
            "Банда",
            "Артикул WB",
            "Артикул продавца",
            "Название",
            "Остаток WB на складах",
            "В пути к клиенту",
            "Возвраты в пути",
            "Итого в контуре WB",
            "Остаток 1С",
            "Поставки на WB",
            "Скорость продаж за позавчера",
            "Скорость продаж за прошедшую неделю",
            "Прогноз остатков по скорости позавчера",
            "Прогноз остатков по скорости недели",
        ]
        numeric_cols = {
            "Артикул WB",
            "Остаток WB на складах",
            "В пути к клиенту",
            "Возвраты в пути",
            "Итого в контуре WB",
            "Скорость продаж за позавчера",
            "Скорость продаж за прошедшую неделю",
            "Прогноз остатков по скорости позавчера",
            "Прогноз остатков по скорости недели",
        }

    display_df = source_df.reindex(columns=source_columns).rename(columns=rename_map)
    difference_label = "Разница WB - 1С"
    supply_label = "Поставки на WB"
    one_c_label = "Остаток 1С"

    numeric_cols = set(numeric_cols)
    numeric_cols.add(one_c_label)
    numeric_cols.add(supply_label)

    # Разницу не выводим в UI ни на уровне товаров, ни на уровне банд

    # Расчет скоростей продаж и прогнозов остатков
    if level == "По товарам":
        display_df["Скорость продаж за позавчера"] = pd.NA
        display_df["Скорость продаж за прошедшую неделю"] = pd.NA
        display_df["Прогноз остатков по скорости позавчера"] = pd.NA
        display_df["Прогноз остатков по скорости недели"] = pd.NA

        if snapshot_date is not None and sales_df is not None and not sales_df.empty:
            p_yesterday2 = snapshot_date - timedelta(days=2)
            p_week_start = snapshot_date - timedelta(days=7)
            p_week_end = snapshot_date - timedelta(days=1)

            # Скорость за позавчера
            df_yesterday2 = sales_df[sales_df["date"] == p_yesterday2]
            if not df_yesterday2.empty:
                y2_series = df_yesterday2.groupby("nm_id")["order_count"].sum(min_count=1)
                nm_ids = pd.to_numeric(display_df["Артикул WB"], errors="coerce")
                display_df["Скорость продаж за позавчера"] = nm_ids.map(y2_series)

            # Средняя скорость за 7 дней
            df_week = sales_df[(sales_df["date"] >= p_week_start) & (sales_df["date"] <= p_week_end)]
            if not df_week.empty:
                week_sum = df_week.groupby("nm_id")["order_count"].sum(min_count=1)
                week_speed = week_sum / 7.0
                nm_ids = pd.to_numeric(display_df["Артикул WB"], errors="coerce")
                display_df["Скорость продаж за прошедшую неделю"] = nm_ids.map(week_speed)

            # Прогноз остатков (Суммарный остаток = Остаток WB + Остаток 1С)
            wb_stock = pd.to_numeric(display_df["Остаток WB на складах"], errors="coerce")
            one_c_stock = _clip_non_negative_numeric_series(display_df["Остаток 1С"])
            
            total_stock = wb_stock.fillna(0) + one_c_stock.fillna(0)
            total_stock = total_stock.where(wb_stock.notna() | one_c_stock.notna(), pd.NA)

            # Прогноз по позавчера
            speed_y2 = pd.to_numeric(display_df["Скорость продаж за позавчера"], errors="coerce")
            forecast_y2 = total_stock / speed_y2
            display_df["Прогноз остатков по скорости позавчера"] = forecast_y2.where(
                (speed_y2 > 0) & speed_y2.notna() & total_stock.notna(), pd.NA
            )

            # Прогноз по неделе
            speed_w = pd.to_numeric(display_df["Скорость продаж за прошедшую неделю"], errors="coerce")
            forecast_w = total_stock / speed_w
            display_df["Прогноз остатков по скорости недели"] = forecast_w.where(
                (speed_w > 0) & speed_w.notna() & total_stock.notna(), pd.NA
            )

    for column_name in ordered_columns:
        if column_name not in display_df.columns:
            display_df[column_name] = pd.NA
    if supply_label in display_df.columns:
        display_df[supply_label] = _normalize_nullable_int_display_series(display_df[supply_label])
    display_df = display_df[ordered_columns].copy()
    display_df.attrs.clear()
    return display_df, numeric_cols


def _resolve_size_sales_metrics_by_row(
    size_sales_df: pd.DataFrame,
    snapshot_date: date,
    nm_id: object,
    barcode: object,
    tech_size: object,
    size_name: object,
) -> tuple[float | None, float | None]:
    if size_sales_df.empty:
        return (None, None)

    resolved_nm_id = pd.to_numeric(pd.Series([nm_id]), errors="coerce").iloc[0]
    if pd.isna(resolved_nm_id):
        return (None, None)
    resolved_nm_id = int(resolved_nm_id)
    resolved_barcode = _normalize_stock_size_barcode(barcode)
    resolved_size_key = _normalize_stock_size_name(tech_size) or _normalize_stock_size_name(size_name)

    sales_df = size_sales_df.copy()
    sales_df["date"] = pd.to_datetime(sales_df.get("date"), errors="coerce").dt.date
    sales_df["nm_id"] = pd.to_numeric(sales_df.get("nm_id"), errors="coerce")
    sales_df["barcode"] = sales_df.get("barcode").map(_normalize_stock_size_barcode)
    sales_df["tech_size_key"] = sales_df.get("tech_size").map(_normalize_stock_size_name)
    sales_df["order_count"] = pd.to_numeric(sales_df.get("order_count"), errors="coerce")
    sales_df = sales_df.dropna(subset=["date", "nm_id"]).copy()
    if sales_df.empty:
        return (None, None)
    sales_df["nm_id"] = sales_df["nm_id"].astype(int)
    sales_df = sales_df[sales_df["nm_id"] == resolved_nm_id].copy()
    if sales_df.empty:
        return (None, None)

    date_y2 = snapshot_date - timedelta(days=2)
    date_from = snapshot_date - timedelta(days=7)
    date_to = snapshot_date - timedelta(days=1)
    y2_df = sales_df[sales_df["date"] == date_y2].copy()
    week_df = sales_df[(sales_df["date"] >= date_from) & (sales_df["date"] <= date_to)].copy()

    def _aggregate_by_barcode(df: pd.DataFrame) -> dict[tuple[int, str], float]:
        if df.empty:
            return {}
        prepared = df.dropna(subset=["barcode"]).copy()
        if prepared.empty:
            return {}
        grouped = prepared.groupby(["nm_id", "barcode"], dropna=False)["order_count"].sum(min_count=1)
        return {
            (int(group_nm_id), str(group_barcode)): float(value)
            for (group_nm_id, group_barcode), value in grouped.items()
            if group_barcode
        }

    def _aggregate_by_unique_tech_size(df: pd.DataFrame) -> dict[tuple[int, str], float]:
        if df.empty:
            return {}
        prepared = df.dropna(subset=["tech_size_key"]).copy()
        if prepared.empty:
            return {}
        result: dict[tuple[int, str], float] = {}
        for (group_nm_id, group_tech_size), part in prepared.groupby(["nm_id", "tech_size_key"], dropna=False):
            distinct_barcodes = {
                _normalize_stock_size_barcode(value)
                for value in part["barcode"].dropna().tolist()
            }
            distinct_barcodes.discard(None)
            if len(distinct_barcodes) > 1:
                continue
            total_orders = pd.to_numeric(part["order_count"], errors="coerce").sum(min_count=1)
            if pd.notna(total_orders):
                result[(int(group_nm_id), str(group_tech_size))] = float(total_orders)
        return result

    barcode_y2 = _aggregate_by_barcode(y2_df)
    barcode_week_sum = _aggregate_by_barcode(week_df)
    tech_y2 = _aggregate_by_unique_tech_size(y2_df)
    tech_week_sum = _aggregate_by_unique_tech_size(week_df)

    if resolved_barcode:
        return (
            barcode_y2.get((resolved_nm_id, resolved_barcode), 0.0),
            barcode_week_sum.get((resolved_nm_id, resolved_barcode), 0.0) / 7.0,
        )

    if resolved_size_key:
        tech_key = (resolved_nm_id, resolved_size_key)
        if tech_key in tech_y2 or tech_key in tech_week_sum:
            return (
                tech_y2.get(tech_key, 0.0),
                tech_week_sum.get(tech_key, 0.0) / 7.0,
            )

    return (None, None)


def build_stock_all_size_display_dataframe(
    size_df: "pd.DataFrame",
    *,
    snapshot_date: "date | None" = None,
    size_sales_df: "pd.DataFrame | None" = None,
) -> tuple["pd.DataFrame", set[str]]:
    source_columns = [
        "band_name",
        "nm_id",
        "vendor_code",
        "title",
        "size_name",
        "barcode",
        "tech_size",
        "wb_size_stock_qty",
        "one_c_size_stock_qty",
        "wb_vs_one_c_size_diff",
    ]
    rename_map = {
        "band_name": "Банда",
        "nm_id": "Артикул WB",
        "vendor_code": "Артикул продавца",
        "title": "Название",
        "size_name": "Размер",
        "barcode": "Баркод",
        "tech_size": "_tech_size",
        "wb_size_stock_qty": "Остаток WB по размеру",
        "one_c_size_stock_qty": "Остаток 1С по размеру",
        "wb_vs_one_c_size_diff": "Разница WB - 1С по размеру",
    }
    ordered_columns = [
        "Банда",
        "Артикул WB",
        "Артикул продавца",
        "Название",
        "Размер",
        "Баркод",
        "Остаток WB по размеру",
        "Остаток 1С по размеру",
        "Скорость продаж за позавчера",
        "Скорость продаж за прошедшую неделю",
        "Прогноз остатков по скорости позавчера",
        "Прогноз остатков по скорости недели",
    ]
    numeric_cols = {
        "Артикул WB",
        "Остаток WB по размеру",
        "Остаток 1С по размеру",
        "Скорость продаж за позавчера",
        "Скорость продаж за прошедшую неделю",
        "Прогноз остатков по скорости позавчера",
        "Прогноз остатков по скорости недели",
    }
    display_df = size_df.reindex(columns=source_columns).rename(columns=rename_map)
    display_df["Скорость продаж за позавчера"] = pd.NA
    display_df["Скорость продаж за прошедшую неделю"] = pd.NA
    display_df["Прогноз остатков по скорости позавчера"] = pd.NA
    display_df["Прогноз остатков по скорости недели"] = pd.NA

    if snapshot_date is not None and size_sales_df is not None and not display_df.empty:
        for row_idx, row in display_df.iterrows():
            speed_y2, speed_week = _resolve_size_sales_metrics_by_row(
                size_sales_df=size_sales_df,
                snapshot_date=snapshot_date,
                nm_id=row.get("Артикул WB"),
                barcode=row.get("Баркод"),
                tech_size=row.get("_tech_size"),
                size_name=row.get("Размер"),
            )
            display_df.at[row_idx, "Скорость продаж за позавчера"] = speed_y2
            display_df.at[row_idx, "Скорость продаж за прошедшую неделю"] = speed_week

        wb_stock = pd.to_numeric(display_df["Остаток WB по размеру"], errors="coerce")
        one_c_stock = _clip_non_negative_numeric_series(display_df["Остаток 1С по размеру"])
        total_stock = wb_stock.fillna(0) + one_c_stock.fillna(0)
        total_stock = total_stock.where(wb_stock.notna() | one_c_stock.notna(), pd.NA)

        speed_y2_series = pd.to_numeric(display_df["Скорость продаж за позавчера"], errors="coerce")
        speed_week_series = pd.to_numeric(display_df["Скорость продаж за прошедшую неделю"], errors="coerce")
        display_df["Прогноз остатков по скорости позавчера"] = (total_stock / speed_y2_series).where(
            (speed_y2_series > 0) & speed_y2_series.notna() & total_stock.notna(),
            pd.NA,
        )
        display_df["Прогноз остатков по скорости недели"] = (total_stock / speed_week_series).where(
            (speed_week_series > 0) & speed_week_series.notna() & total_stock.notna(),
            pd.NA,
        )

    for column_name in ordered_columns:
        if column_name not in display_df.columns:
            display_df[column_name] = pd.NA
    return display_df[ordered_columns].copy(), numeric_cols


def _fmt_stock_int(value: object) -> str:
    """Форматирует целое число с пробелами как разделителями тысяч или '—' если null."""
    if value is None or (isinstance(value, float) and pd.isna(value)):
        return "—"
    try:
        return f"{int(value):,}".replace(",", "\u202f")
    except (TypeError, ValueError):
        return str(value)


def build_stock_all_band_name(query_group: object) -> str:
    normalized = normalize_query_group_value(query_group)
    if normalized == "трусы женские":
        return "Трусы женские"
    if normalized == "трусы детские":
        return "Трусы детские"
    if normalized in {"женская футболка", "мужская футболка"}:
        return "Футболки"
    return "Прочее"


def render_stock_all_tab(
    snapshot_df: "pd.DataFrame",
    settings_df: "pd.DataFrame",
    available_dates: "list[date]",
    cache_buster: str | None = None,
) -> None:
    """Рендерит вкладку 'Контроль всех остатков'."""
    if False:
        st.info(
        "**В пути к клиенту** — товары, которые уже ушли покупателям "
        "(WB передал их службе доставки). Это **не** поставки на склад WB. "
        "Поставки на склад WB (`Поставки на WB`) будут добавлены отдельно "
        "после подключения соответствующего источника.",
        icon="ℹ️",
    )

    latest_date = available_dates[-1] if available_dates else None
    if latest_date is None:
        st.warning("В `fact_stock_warehouse_snapshot` нет данных.")
        return

    st.markdown(f"**Дата актуальности WB-остатков:** `{latest_date.isoformat()}`")

    import zoneinfo
    moscow_tz = zoneinfo.ZoneInfo("Europe/Moscow")
    report_day = (datetime.now(moscow_tz) - timedelta(days=1)).date()
    default_snapshot_date = resolve_stock_warehouse_default_snapshot_date(available_dates, report_day)
    selected_snapshot_date = st.date_input(
        "Дата среза остатков",
        value=default_snapshot_date,
        min_value=available_dates[0],
        max_value=available_dates[-1],
        key="stock_all_snapshot_date",
    )

    one_c_product_df = load_ivan_stock_product_level_from_db(selected_snapshot_date, cache_buster=cache_buster)
    wb_supply_product_df = load_wb_supply_product_level_from_db(cache_buster=cache_buster)
    tracked_product_df = load_tracked_products()
    snapshot_day_df = snapshot_df.loc[snapshot_df["snapshot_date"] == selected_snapshot_date, ["nm_id"]].copy()
    product_level_nm_ids = _collect_stock_all_product_level_nm_ids(
        snapshot_day_df,
        settings_df,
        one_c_product_df,
        tracked_product_df,
    )
    if product_level_nm_ids:
        product_size_df = load_dim_product_size_from_db(product_level_nm_ids, cache_buster=cache_buster)
    else:
        product_size_df = pd.DataFrame(columns=["nm_id", "chrt_id", "barcode", "size_name", "tech_size", "source_status", "updated_at"])
    product_df = build_stock_all_product_level(
        snapshot_df,
        settings_df,
        selected_snapshot_date,
        one_c_stock_df=one_c_product_df,
        tracked_df=tracked_product_df,
        wb_supply_df=wb_supply_product_df,
        product_size_df=product_size_df,
    )

    if product_df.empty:
        st.warning(f"Нет строк за {latest_date.isoformat()} в `fact_stock_warehouse_snapshot`.")
        return

    wb_stock_total = product_df["wb_stock_qty"].sum(min_count=1)
    wb_in_way = product_df["wb_in_way_to_client"].sum(min_count=1)
    wb_from_client = product_df["wb_in_way_from_client"].sum(min_count=1)
    wb_contour = product_df["wb_total_in_contour"].sum(min_count=1)
    one_c_stock_total = pd.to_numeric(product_df["one_c_stock_qty"], errors="coerce").sum(min_count=1)
    wb_supply_series = pd.to_numeric(product_df["wb_supply_qty"], errors="coerce") if "wb_supply_qty" in product_df.columns else pd.Series(dtype="float64")
    wb_supply_total = wb_supply_series.sum(min_count=1)
    wb_vs_one_c_diff_total = pd.to_numeric(product_df["wb_vs_one_c_diff"], errors="coerce").sum(min_count=1)
    products_count = product_df["nm_id"].nunique()
    band_count = int(product_df["band_name"].nunique())

    metric_items = [
        ("Остаток WB на складах", _fmt_stock_int(wb_stock_total)),
        ("В пути к клиенту", _fmt_stock_int(wb_in_way)),
        ("Возвраты в пути", _fmt_stock_int(wb_from_client)),
        ("Итого в контуре WB", _fmt_stock_int(wb_contour)),
        ("Остаток 1С", "нет данных"),
        ("Поставки на WB", "нет данных"),
        ("Товаров / Банд", f"{products_count}\u202f/\u202f{band_count}"),
    ]
    if len(metric_items) >= 5:
        metric_items[4] = ("Остаток 1С", _fmt_stock_int(one_c_stock_total))
        if pd.notna(wb_supply_total):
            metric_items[5] = ("Поставки на WB", _fmt_stock_int(wb_supply_total))

    cols = st.columns(len(metric_items))
    for col, (label, value) in zip(cols, metric_items):
        col.markdown(
            build_stock_warehouse_summary_card_html(label, value, compact=True),
            unsafe_allow_html=True,
        )
    st.divider()

    level = st.radio(
        "Уровень агрегации",
        options=["По товарам", "По бандам", "По размерам"],
        horizontal=True,
        key="stock_all_level_radio",
    )
    if level == "По размерам":
        one_c_size_df = load_ivan_stock_size_level_from_db(selected_snapshot_date, cache_buster=cache_buster)
        wb_nm_ids = set(
            pd.to_numeric(
                snapshot_df.loc[snapshot_df["snapshot_date"] == selected_snapshot_date, "nm_id"],
                errors="coerce",
            ).dropna().astype(int).tolist()
        )
        if one_c_size_df.empty:
            one_c_nm_ids: set[int] = set()
        else:
            one_c_nm_ids = set(
                pd.to_numeric(one_c_size_df.get("nm_id"), errors="coerce").dropna().astype(int).tolist()
            )
        product_size_df = load_dim_product_size_from_db(
            tuple(sorted(wb_nm_ids | one_c_nm_ids)),
            cache_buster=cache_buster,
        )
        size_sales_df = load_size_sales_speed_data_from_db(selected_snapshot_date, cache_buster=cache_buster)
        size_df = build_stock_all_size_level(
            snapshot_df,
            settings_df,
            selected_snapshot_date,
            one_c_size_df=one_c_size_df,
            product_size_df=product_size_df,
        )
        display_df, numeric_cols = build_stock_all_size_display_dataframe(
            size_df,
            snapshot_date=selected_snapshot_date,
            size_sales_df=size_sales_df,
        )
    else:
        sales_df = load_sales_speed_data_from_db(selected_snapshot_date, cache_buster=cache_buster)
        display_df, numeric_cols = build_stock_all_display_dataframe(
            product_df,
            level=level,
            snapshot_date=selected_snapshot_date,
            sales_df=sales_df,
        )
    display_df_raw = display_df.copy()

    # null-колонки — явно "нет данных", не 0
    null_columns = ("Остаток 1С",)
    if level == "По размерам":
        null_columns = ("Остаток 1С по размеру",)
    for null_col in null_columns:
        if null_col in display_df.columns:
            display_df[null_col] = "нет данных"

    for null_col in null_columns:
        if null_col in display_df.columns and null_col in display_df_raw.columns:
            display_df[null_col] = display_df_raw[null_col].where(display_df_raw[null_col].notna(), "нет данных")

    st.download_button(
        "Скачать XLSX",
        data=build_excel_export_bytes(display_df.copy()),
        file_name=build_stock_all_export_filename(selected_snapshot_date, level),
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key=f"stock_all_xlsx_download_{level}",
    )

    display_df.attrs = {}
    safe_st_dataframe(
        sanitize_dataframe_for_streamlit_display(display_df, numeric_columns=numeric_cols),
        width="stretch",
        hide_index=True,
    )
    st.markdown("* Прогноз остатков рассчитывается как суммарный остаток WB + 1С, делённый на скорость продаж. Значение указано в днях.")

    # Итоговые карточки
    return
    wb_stock_total = product_df["wb_stock_qty"].sum(min_count=1)
    wb_in_way = product_df["wb_in_way_to_client"].sum(min_count=1)
    wb_from_client = product_df["wb_in_way_from_client"].sum(min_count=1)
    wb_contour = product_df["wb_total_in_contour"].sum(min_count=1)
    products_count = product_df["nm_id"].nunique()
    band_count = int(product_df["band"].nunique())

    metric_items = [
        ("Остаток WB на складах", _fmt_stock_int(wb_stock_total)),
        ("В пути к клиенту", _fmt_stock_int(wb_in_way)),
        ("Возвраты в пути", _fmt_stock_int(wb_from_client)),
        ("Итого в контуре WB", _fmt_stock_int(wb_contour)),
        ("Остаток 1С", "нет данных"),
        ("Поставки на WB", "нет данных"),
        ("Товаров / Банд", f"{products_count}\u202f/\u202f{band_count}"),
    ]
    cols = st.columns(len(metric_items))
    for col, (label, value) in zip(cols, metric_items):
        col.markdown(
            build_stock_warehouse_summary_card_html(label, value, compact=True),
            unsafe_allow_html=True,
        )


def render_stock_warehouse_tab(data_source: str) -> None:
    """
    Вкладка \u2018Остатки по складам\u2019 с двумя внутренними вкладками:
    1. Контроль нулевых позиций (существующая логика без изменений)
    2. Контроль всех остатков (новая)
    """
    if data_source != "db":
        st.info("Вкладка складских остатков доступна в режиме PostgreSQL.")
        return

    cache_buster = resolve_db_dataset_cache_buster()
    snapshot_df = load_stock_warehouse_snapshot_from_db(cache_buster)
    prepared_snapshot = prepare_stock_warehouse_snapshot_dataframe(snapshot_df)
    available_dates = sorted(d for d in prepared_snapshot["snapshot_date"].dropna().unique().tolist())
    latest_date = available_dates[-1] if available_dates else None

    # Загружаем settings_products один раз для обеих вкладок
    settings_qg_df = load_settings_product_query_groups_from_db(cache_buster)

    tab_zero, tab_all = st.tabs([
        STOCK_ZERO_POSITIONS_TAB_LABEL,
        STOCK_ALL_POSITIONS_TAB_LABEL,
    ])

    with tab_all:
        render_stock_all_tab(prepared_snapshot, settings_qg_df, available_dates, cache_buster=cache_buster)

    with tab_zero:
        if snapshot_df.empty:
            st.warning("В `fact_stock_warehouse_snapshot` пока нет строк.")
            return

        if not available_dates:
            st.warning("В `fact_stock_warehouse_snapshot` нет валидных дат snapshot.")
            return

        tracked_df = load_tracked_products()
        tracked_df = attach_stock_query_groups(tracked_df, settings_qg_df)
        main_warehouses = load_main_wb_warehouses(
            str(MAIN_WB_WAREHOUSES_PATH),
            MAIN_WB_WAREHOUSES_PATH.stat().st_mtime if MAIN_WB_WAREHOUSES_PATH.exists() else None,
        )
        import zoneinfo
        moscow_tz = zoneinfo.ZoneInfo("Europe/Moscow")
        report_day = (datetime.now(moscow_tz) - timedelta(days=1)).date()
        default_snapshot_date = resolve_stock_warehouse_default_snapshot_date(available_dates, report_day)
        selected_snapshot_date = st.date_input(
            "Дата отчёта",
            value=default_snapshot_date,
            min_value=available_dates[0],
            max_value=available_dates[-1],
            key="stock_warehouse_snapshot_date",
        )

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
            main_warehouses=main_warehouses,
            show_only_tracked=show_only_tracked,
            show_sellout=show_sellout,
        )
        summary_metrics = build_stock_warehouse_summary_metrics(product_table)
        problem_table = build_stock_warehouse_problem_table(product_table)
        problem_profit_total = build_stock_warehouse_problem_profit_total(problem_table)

        summary_items = [
            ("Дата snapshot", selected_snapshot_date.isoformat()),
            ("Всего tracked товаров", f"{summary_metrics['total_products']:,}".replace(",", " ")),
            ("Потенц. прибыль", format_summary_rub(problem_profit_total)),
            ("Товаров с нулём на складах", f"{summary_metrics['zero_products']:,}".replace(",", " ")),
            ("Товаров без данных", f"{summary_metrics['no_data_products']:,}".replace(",", " ")),
            ("Всего нулевых складов", f"{summary_metrics['total_zero_warehouses']:,}".replace(",", " ")),
        ]
        summary_cols = st.columns(6)
        for column, (label, value) in zip(summary_cols, summary_items):
            column.markdown(
                build_stock_warehouse_summary_card_html(label, value, compact=True),
                unsafe_allow_html=True,
            )

        st.write("**Проблемные товары**")
        problem_display = build_stock_warehouse_display_dataframe(problem_table, problem_table=True)
        problem_excel_bytes = build_excel_export_bytes(problem_display)
        st.download_button(
            "Скачать XLSX",
            data=problem_excel_bytes,
            file_name=f"stock_problem_products_{selected_snapshot_date.isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="stock_problem_products_xlsx_download",
        )
        safe_st_dataframe(
            prepare_stock_warehouse_table_for_display(problem_display, []),
            width="stretch",
            hide_index=True,
        )

        if only_problematic:
            product_table = product_table[product_table["problem_status"].ne(STOCK_STATUS_OK)].copy()

        display_columns = [
            "nm_id",
            "tracked_label",
            "query_group",
            "lifecycle_status",
            *selected_warehouses,
            "total_main_warehouses",
            "warehouses_with_stock",
            "zero_warehouses_count",
            "no_data_warehouses_count",
            "problem_status",
        ]
        table_display = build_stock_warehouse_display_dataframe(
            product_table.reindex(columns=display_columns),
            problem_table=False,
        )
        warehouse_display_columns = [warehouse_name for warehouse_name in selected_warehouses if warehouse_name in table_display.columns]

        st.write("**Остатки по складам**")
        warehouse_excel_bytes = build_excel_export_bytes(table_display)
        st.download_button(
            "Скачать XLSX",
            data=warehouse_excel_bytes,
            file_name=f"stock_warehouses_{selected_snapshot_date.isoformat()}.xlsx",
            mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            key="stock_warehouses_xlsx_download",
        )
        safe_st_dataframe(
            prepare_stock_warehouse_table_for_display(table_display, warehouse_display_columns),
            width="stretch",
            hide_index=True,
        )

        st.divider()
        st.write("**История остатков по складам**")
        history_default_start = available_dates[max(0, len(available_dates) - 7)]
        history_period = st.date_input(
            "Период истории складов",
            value=(history_default_start, available_dates[-1]),
            min_value=available_dates[0],
            max_value=available_dates[-1],
        )
        if isinstance(history_period, tuple) and len(history_period) == 2:
            raw_history_start, raw_history_end = history_period
        else:
            raw_history_start = raw_history_end = selected_snapshot_date
        history_start = min(raw_history_start, raw_history_end)
        history_end = max(raw_history_start, raw_history_end)
        selected_history_dates = [value for value in available_dates if history_start <= value <= history_end]

        if not selected_history_dates:
            st.info("В выбранном периоде нет доступных дат snapshot.")
            return

        history_table = build_stock_warehouse_history_table(
            snapshot_df,
            tracked_df,
            selected_dates=selected_history_dates,
            monitored_warehouses=selected_warehouses,
        )
        history_summary = build_stock_warehouse_history_summary_metrics(history_table)
        history_pivot = build_stock_warehouse_history_pivot_table(history_table)
        history_ivan_check = build_stock_warehouse_history_ivan_check_table(history_table)

        history_summary_items = [
            ("Дат в периоде", f"{history_summary['dates_count']:,}".replace(",", " ")),
            ("Товаров", f"{history_summary['products_count']:,}".replace(",", " ")),
            ("Складов", f"{history_summary['warehouses_count']:,}".replace(",", " ")),
            ("Строк с остатком", f"{history_summary['in_stock_rows']:,}".replace(",", " ")),
            ("Нулевых строк", f"{history_summary['zero_rows']:,}".replace(",", " ")),
            ("Строк без данных", f"{history_summary['no_data_rows']:,}".replace(",", " ")),
            ("Аномалий", f"{history_summary['anomalies_count']:,}".replace(",", " ")),
        ]
        history_summary_cols = st.columns(len(history_summary_items))
        for column, (label, value) in zip(history_summary_cols, history_summary_items):
            column.markdown(build_stock_warehouse_summary_card_html(label, value, compact=True), unsafe_allow_html=True)

        stock_status_labels = {
            STOCK_HISTORY_STATUS_IN_STOCK: "Есть остаток",
            STOCK_HISTORY_STATUS_ZERO: "0",
            STOCK_HISTORY_STATUS_NO_DATA: "Нет данных",
        }
        history_display = history_table.copy()
        history_display["loaded_at"] = pd.to_datetime(history_display["loaded_at"], errors="coerce").dt.strftime("%Y-%m-%d %H:%M:%S")
        history_display["loaded_at"] = history_display["loaded_at"].fillna(STOCK_WAREHOUSE_NO_DATA_DISPLAY)
        history_display["stock_status"] = history_display["stock_status"].map(
            lambda value: stock_status_labels.get(str(value), value)
        )
        history_display = history_display.rename(
            columns={
                "snapshot_date": "Дата",
                "nm_id": "Артикул WB",
                "supplier_article": "Артикул",
                "product_name": "Товар",
                "lifecycle_status": "Статус товара",
                "warehouse_name": "Склад",
                "stock_qty": "Остаток",
                "stock_status": "Статус остатка",
                "loaded_at": "Загружено в БД",
            }
        )
        history_display["Статус товара"] = history_display["Статус товара"].map(
            lambda value: {"active": "Основной", "sellout": "Распродажа"}.get(str(value), value)
        )
        st.caption("`NO_DATA` показывается отдельно и не считается нулевым остатком.")
        safe_st_dataframe(
            sanitize_dataframe_for_streamlit_display(
                history_display[
                    ["Дата", "Артикул WB", "Артикул", "Товар", "Статус товара", "Склад", "Остаток", "Статус остатка", "Загружено в БД"]
                ],
                numeric_columns={"Артикул WB", "Остаток"},
            ),
            width="stretch",
            hide_index=True,
        )
        with st.expander("Диагностика поисковых запросов (Debug Check)"):
            try:
                with session_scope() as session:
                    diag_stmt1 = """
                        select
                          day,
                          query_group,
                          count(*) as rows_count,
                          count(distinct nm_id) as nm_count,
                          count(distinct query_text) as query_text_count,
                          sum(coalesce(orders_current, 0)) as orders_sum,
                          sum(coalesce(frequency_current, 0)) as raw_frequency_sum
                        from fact_wb_search_query_text_day
                        where day = :report_day
                        group by day, query_group
                        order by query_group;
                    """
                    res1 = session.execute(
                        text(diag_stmt1),
                        {"report_day": selected_snapshot_date}
                    ).all()
                    df1 = pd.DataFrame([dict(row._mapping) for row in res1])
                    st.markdown("**Общая статистика по группам:**")
                    if not df1.empty:
                        safe_st_dataframe(df1)
                    else:
                        st.write("Нет данных.")

                    diag_stmt2 = """
                        with dedup as (
                          select
                            day,
                            query_group,
                            query_text,
                            max(frequency_current) as frequency
                          from fact_wb_search_query_text_day
                          where day = :report_day
                          group by day, query_group, query_text
                        )
                        select
                          day,
                          query_group,
                          sum(frequency) as search_queries
                        from dedup
                        group by day, query_group
                        order by query_group;
                    """
                    res2 = session.execute(
                        text(diag_stmt2),
                        {"report_day": selected_snapshot_date}
                    ).all()
                    df2 = pd.DataFrame([dict(row._mapping) for row in res2])
                    st.markdown("**Dedupe-агрегат поисковых запросов:**")
                    if not df2.empty:
                        safe_st_dataframe(df2)
                    else:
                        st.write("Нет данных.")
            except Exception as e:
                st.error(f"Ошибка при загрузке диагностики: {e}")


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
        safe_st_dataframe(pd.DataFrame(preview_rows[:10]), width="stretch", hide_index=True)

    skipped_rows_preview = summary.get("skipped_rows_preview") or []
    if skipped_rows_preview:
        st.write("**Пропущенные строки**")
        safe_st_dataframe(pd.DataFrame(skipped_rows_preview[:10]), width="stretch", hide_index=True)

    source_status_counts = summary.get("source_status_counts")
    if source_status_counts:
        st.write("**source_status counts**")
        st.json(source_status_counts)


def render_last_upload_result(last_result: dict[str, object] | None) -> None:
    if not last_result:
        return
    st.write("**Последние результаты загрузки**")
    safe_st_dataframe(pd.DataFrame([last_result]), width="stretch", hide_index=True)


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


def build_filtered_dataset(df: pd.DataFrame, data_source: str) -> tuple[pd.DataFrame, list[dict[str, object]]]:
    filtered = df.copy()
    tracked_metadata_state = inspect_tracked_metadata_state(df)
    debug_trace = [build_debug_snapshot("rows_after_load_dataset_from_db", filtered)]

    with st.sidebar:
        st.header("Фильтры")

        available_dates = sorted(d for d in filtered["report_date"].dropna().unique().tolist())
        selected_dates = st.multiselect("Дата", options=available_dates, default=available_dates)
        if selected_dates:
            filtered = filtered[filtered["report_date"].isin(selected_dates)]
        debug_trace.append(build_debug_snapshot("rows_after_date_filter", filtered))

        show_only_tracked = st.checkbox("Показывать только отслеживаемые товары", value=True)
        if show_only_tracked and not tracked_metadata_state["metadata_available"]:
            st.warning(
                "Tracked metadata недоступна или не подмешалась в dataset. "
                "Фильтр по отслеживаемым товарам временно не применяется, чтобы не обнулить таблицу."
            )
        filtered = apply_tracked_scope_filters(
            filtered,
            show_only_tracked=show_only_tracked,
            show_sellout=True,
            tracked_metadata_available=bool(tracked_metadata_state["metadata_available"]),
        )
        debug_trace.append(build_debug_snapshot("rows_after_tracked_filter", filtered))

        show_sellout = st.checkbox("Показывать распродажные товары", value=True)
        filtered = apply_tracked_scope_filters(
            filtered,
            show_only_tracked=False,
            show_sellout=show_sellout,
            tracked_metadata_available=bool(tracked_metadata_state["metadata_available"]),
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

        show_products_without_data = st.checkbox("Показывать строки без данных", value=False)
        debug_trace.append(build_debug_snapshot("rows_after_products_without_data_toggle", filtered))

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
    data_debug = build_data_debug_payload(
        df,
        data_source=data_source,
        selected_dates=selected_dates,
        debug_trace=debug_trace,
        tracked_metadata_state=tracked_metadata_state,
    )
    filtered.attrs["show_rows_without_data"] = bool(show_products_without_data)
    with st.sidebar.expander("DATA DEBUG"):
        st.json(data_debug)
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


def _convert_decimal_cell(value: object) -> object:
    if isinstance(value, Decimal):
        return float(value)
    return value


def _sanitize_numeric_series(series: pd.Series) -> pd.Series:
    replaced = series.replace(list(DISPLAY_NUMERIC_PLACEHOLDERS), pd.NA)
    return pd.to_numeric(replaced, errors="coerce")


def _sanitize_streamlit_object_cell(
    value: object,
    *,
    force_object_strings: bool = False,
) -> object:
    if isinstance(value, Decimal):
        value = float(value)

    if isinstance(value, (bytes, bytearray)):
        try:
            return bytes(value).decode("utf-8")
        except UnicodeDecodeError:
            return bytes(value).decode("utf-8", errors="replace")

    if isinstance(value, (dict, list, tuple, set)):
        return json.dumps(value, ensure_ascii=False, default=str)

    if isinstance(value, (pd.DataFrame, pd.Series)) or isinstance(value, complex):
        return str(value)

    if value is None:
        return ""

    try:
        if pd.isna(value):
            return ""
    except TypeError:
        pass

    if force_object_strings:
        return str(value)

    return value



def _sanitize_object_series_for_streamlit_display(
    series: pd.Series,
    *,
    force_object_strings: bool = False,
) -> pd.Series:
    sanitized_values = [
        _sanitize_streamlit_object_cell(value, force_object_strings=force_object_strings)
        for value in series.tolist()
    ]
    return pd.Series(sanitized_values, index=series.index, dtype=object)



def sanitize_dataframe_for_streamlit_display(
    df: pd.DataFrame,
    *,
    numeric_columns: set[str] | None = None,
    force_object_strings: bool = False,
) -> pd.DataFrame:
    safe_df = df.copy(deep=True)
    safe_df.attrs.clear()
    safe_df.columns = pd.Index([str(column_name) for column_name in safe_df.columns], dtype=object)
    safe_df.index = pd.RangeIndex(len(safe_df))
    numeric_columns = numeric_columns or set()

    for column_name in safe_df.columns:
        series = safe_df[column_name]
        if series.dtype == object and series.map(lambda value: isinstance(value, Decimal)).any():
            safe_df[column_name] = series.map(_convert_decimal_cell)

    for column_name in numeric_columns:
        if column_name in safe_df.columns:
            safe_df[column_name] = _sanitize_numeric_series(safe_df[column_name])

    if "Поставки на WB" in safe_df.columns:
        safe_df["Поставки на WB"] = _normalize_nullable_int_display_series(safe_df["Поставки на WB"])

    for column_name in safe_df.columns:
        if column_name in numeric_columns:
            continue
        series = safe_df[column_name]
        if (
            series.dtype == object
            or pd.api.types.is_string_dtype(series.dtype)
            or str(series.dtype).startswith("string[")
        ):
            safe_df[column_name] = _sanitize_object_series_for_streamlit_display(
                series,
                force_object_strings=force_object_strings,
            )

    return safe_df



def _get_streamlit_display_numeric_columns() -> set[str]:
    return set(NUMERIC_COLUMNS) | DISPLAY_DELTA_COLUMNS_HIGHER_IS_BETTER | DISPLAY_DELTA_COLUMNS_LOWER_IS_BETTER | {
        "technical_ad_campaign_spend_total",
    }



def safe_st_dataframe(
    df: pd.DataFrame | Styler,
    *,
    numeric_columns: set[str] | None = None,
    force_object_strings: bool = False,
    **kwargs: Any,
):
    if isinstance(df, Styler):
        df.data = sanitize_dataframe_for_streamlit_display(
            df.data,
            numeric_columns=numeric_columns,
            force_object_strings=force_object_strings,
        )
        return st.dataframe(df, **kwargs)

    safe_df = sanitize_dataframe_for_streamlit_display(
        df,
        numeric_columns=numeric_columns,
        force_object_strings=force_object_strings,
    )
    return st.dataframe(safe_df, **kwargs)


def build_product_timeline_dataset(product_rows: pd.DataFrame) -> pd.DataFrame:
    timeline = product_rows.reindex(columns=PRODUCT_TIMELINE_COLUMNS).copy()
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

    def threshold_warning_color(value: object, threshold: float) -> str:
        if pd.isna(value):
            return ""
        if float(value) > threshold:
            return "background-color: #ffe5d0; color: #9a3412;"
        return ""

    def delta_color(value: object, *, lower_is_better: bool = False) -> str:
        if pd.isna(value):
            return ""
        numeric_value = float(value)
        if numeric_value == 0:
            return ""
        is_positive_outcome = numeric_value < 0 if lower_is_better else numeric_value > 0
        if is_positive_outcome:
            return "color: #166534; font-weight: 600;"
        return "color: #b91c1c; font-weight: 600;"

    def product_group_color(value: object) -> str:
        if str(value or "").strip():
            return "background-color: #f8fafc; border-top: 2px solid #d1d5db; font-weight: 600;"
        return ""

    def wb_price_alert_color(column: pd.Series) -> list[str]:
        alerts = (
            df.loc[column.index, "wb_price_alert"]
            .fillna(False)
            .astype(bool)
            .tolist()
        )
        return [
            "background-color: #fde2e4; color: #7f1d1d;" if is_alert else ""
            for is_alert in alerts
        ]

    styler = df.style
    if status_column in df.columns:
        styler = styler.map(status_color, subset=[status_column])
    if "ad_cpo_calc" in df.columns:
        styler = styler.map(lambda value: threshold_warning_color(value, CHART_THRESHOLD_CPO), subset=["ad_cpo_calc"])
    if "ad_cost_per_cart_calc" in df.columns:
        styler = styler.map(
            lambda value: threshold_warning_color(value, CHART_THRESHOLD_CART_COST),
            subset=["ad_cost_per_cart_calc"],
        )
    if "wb_buyer_price" in df.columns and "wb_price_alert" in df.columns:
        styler = styler.apply(wb_price_alert_color, subset=["wb_buyer_price"])
    if "product_group_label" in df.columns:
        styler = styler.map(product_group_color, subset=["product_group_label"])
    higher_is_better_columns = [column for column in DISPLAY_DELTA_COLUMNS_HIGHER_IS_BETTER if column in df.columns]
    if higher_is_better_columns:
        styler = styler.map(lambda value: delta_color(value, lower_is_better=False), subset=higher_is_better_columns)
    lower_is_better_columns = [column for column in DISPLAY_DELTA_COLUMNS_LOWER_IS_BETTER if column in df.columns]
    if lower_is_better_columns:
        styler = styler.map(lambda value: delta_color(value, lower_is_better=True), subset=lower_is_better_columns)
    return styler.format(precision=2, na_rep="—")


def style_table_recent_window(df: pd.DataFrame, status_column: str | None = None) -> pd.io.formats.style.Styler:
    recent_row_mask = pd.Series(True, index=df.index, dtype=bool)
    if "report_date" in df.columns:
        report_dates = pd.to_datetime(df["report_date"], errors="coerce").dt.date
        non_null_dates = report_dates.dropna()
        if not non_null_dates.empty:
            style_cutoff_date = non_null_dates.max() - timedelta(days=TABLE_STYLE_LOOKBACK_DAYS)
            recent_row_mask = report_dates.ge(style_cutoff_date).fillna(False)

    def status_color(value: object) -> str:
        if value in ("РќРµС‚ РґР°РЅРЅС‹С…", "NO_DATA"):
            return "background-color: #fde2e4; color: #7f1d1d;"
        if value in ("Р”Р°РЅРЅС‹Рµ РµСЃС‚СЊ, РІРЅРµС€РЅРёРµ РёСЃС‚РѕС‡РЅРёРєРё РѕР¶РёРґР°СЋС‚СЃСЏ", "OK_PARTIAL_SOURCES"):
            return "background-color: #e8f5e9; color: #1b5e20;"
        if value in ("Р§Р°СЃС‚РёС‡РЅРѕ", "PARTIAL"):
            return "background-color: #fff3cd; color: #7a4b00;"
        return ""

    def threshold_warning_color(value: object, threshold: float) -> str:
        if pd.isna(value):
            return ""
        if float(value) > threshold:
            return "background-color: #ffe5d0; color: #9a3412;"
        return ""

    def product_group_color(value: object) -> str:
        if str(value or "").strip():
            return "background-color: #f8fafc; border-top: 2px solid #d1d5db; font-weight: 600;"
        return ""

    def recent_only_map(column: pd.Series, formatter) -> list[str]:
        return [
            formatter(value) if bool(recent_row_mask.loc[index]) else ""
            for index, value in column.items()
        ]

    def wb_price_alert_color(column: pd.Series) -> list[str]:
        alerts = df.loc[column.index, "wb_price_alert"].fillna(False).astype(bool).tolist()
        return [
            "background-color: #fde2e4; color: #7f1d1d;"
            if is_alert and bool(recent_row_mask.loc[index])
            else ""
            for index, is_alert in zip(column.index, alerts)
        ]

    styler = df.style
    if status_column in df.columns:
        styler = styler.apply(lambda column: recent_only_map(column, status_color), subset=[status_column])
    if "ad_cpo_calc" in df.columns:
        styler = styler.apply(
            lambda column: recent_only_map(column, lambda value: threshold_warning_color(value, CHART_THRESHOLD_CPO)),
            subset=["ad_cpo_calc"],
        )
    if "ad_cost_per_cart_calc" in df.columns:
        styler = styler.apply(
            lambda column: recent_only_map(column, lambda value: threshold_warning_color(value, CHART_THRESHOLD_CART_COST)),
            subset=["ad_cost_per_cart_calc"],
        )
    if "wb_buyer_price" in df.columns and "wb_price_alert" in df.columns:
        styler = styler.apply(wb_price_alert_color, subset=["wb_buyer_price"])
    if "product_group_label" in df.columns:
        styler = styler.apply(lambda column: recent_only_map(column, product_group_color), subset=["product_group_label"])
    return styler.format(precision=2, na_rep="вЂ”")


def prepare_dataframe_for_streamlit_display(
    df: pd.DataFrame,
    status_column: str | None = None,
) -> pd.DataFrame | pd.io.formats.style.Styler:
    numeric_columns = _get_streamlit_display_numeric_columns()
    safe_df = sanitize_dataframe_for_streamlit_display(df, numeric_columns=numeric_columns)
    if safe_df.shape[0] * max(safe_df.shape[1], 1) > STYLER_MAX_CELLS:
        return safe_df
    return style_table_recent_window(safe_df, status_column=status_column)



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
    export_df = export_df.rename(columns=renamed_columns)
    return export_df.where(pd.notna(export_df), "—")


def _is_overview_empty_metric_value(value: object) -> bool:
    if pd.isna(value):
        return True
    if isinstance(value, str):
        return value.strip() in DISPLAY_NUMERIC_PLACEHOLDERS
    return False


def filter_overview_empty_rows(table_df: pd.DataFrame) -> pd.DataFrame:
    if table_df.empty:
        return table_df.copy()

    metric_presence_flags = pd.DataFrame(index=table_df.index)
    for column_name in OVERVIEW_EMPTY_ROW_METRIC_COLUMNS:
        if column_name in table_df.columns:
            metric_presence_flags[column_name] = ~table_df[column_name].map(_is_overview_empty_metric_value)
        else:
            metric_presence_flags[column_name] = False

    has_any_metric = metric_presence_flags.any(axis=1)
    return table_df.loc[has_any_metric].copy()


def build_overview_visible_columns() -> list[str]:
    return [column_name for column_name in DISPLAY_COLUMNS_BY_DATE if column_name not in OVERVIEW_HIDDEN_COLUMNS]


def build_overview_export_tables(
    table_df: pd.DataFrame,
    *,
    show_empty_rows: bool,
) -> tuple[pd.DataFrame, pd.DataFrame]:
    overview_rows = table_df.copy() if show_empty_rows else filter_overview_empty_rows(table_df)
    visible_columns = build_overview_visible_columns()
    display_df = overview_rows.reindex(columns=visible_columns).copy()
    export_df = build_export_dataframe(overview_rows, visible_columns)
    return display_df, export_df


def build_excel_export_bytes(export_df: pd.DataFrame) -> bytes:
    buffer = BytesIO()
    with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
        export_df.to_excel(writer, index=False, sheet_name="Итого")
    buffer.seek(0)
    return buffer.getvalue()


def build_filtered_table_export_filename(table_df: pd.DataFrame, extension: str) -> str:
    if "report_date" not in table_df.columns:
        return f"wb_table_filtered.{extension}"

    report_dates = pd.to_datetime(table_df["report_date"], errors="coerce").dt.date.dropna()
    if report_dates.empty:
        return f"wb_table_filtered.{extension}"

    min_date = report_dates.min().isoformat()
    max_date = report_dates.max().isoformat()
    return f"wb_table_filtered_{min_date}_{max_date}.{extension}"


def build_stock_all_export_filename(snapshot_date: date, level: str) -> str:
    level_slug_map = {
        "По товарам": "products",
        "По бандам": "bands",
        "По размерам": "sizes",
    }
    level_slug = level_slug_map.get(level, "table")
    return f"stock_all_{level_slug}_{snapshot_date.isoformat()}.xlsx"


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


OVERVIEW_ALL_PRODUCTS_LABEL = "Все товары"


def filter_rows_by_selected_product_label(
    rows: pd.DataFrame,
    selected_label: str | None,
    option_map: dict[str, dict[str, object]],
) -> pd.DataFrame:
    if rows.empty or not selected_label or selected_label == OVERVIEW_ALL_PRODUCTS_LABEL:
        return rows.copy()
    if "nm_id" not in rows.columns:
        return rows.copy()

    selected_nm_id = option_map.get(selected_label, {}).get("nm_id")
    if selected_nm_id is None:
        return rows.copy()

    nm_id_series = pd.to_numeric(rows["nm_id"], errors="coerce")
    return rows.loc[nm_id_series == int(selected_nm_id)].copy()


def build_ad_campaign_product_scope_dataframe(
    rows: pd.DataFrame,
    *,
    selected_product_label: str | None,
    option_map: dict[str, dict[str, object]],
    allowed_report_dates: list[date] | None = None,
) -> pd.DataFrame:
    scoped = filter_rows_by_selected_product_label(rows, selected_product_label, option_map)
    if scoped.empty or not allowed_report_dates or "report_date" not in scoped.columns:
        return scoped
    scoped = scoped.copy()
    scoped["report_date"] = pd.to_datetime(scoped["report_date"], errors="coerce").dt.date
    return scoped[scoped["report_date"].isin(allowed_report_dates)].copy()


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


def render_entry_point_analytics_tab(filtered: pd.DataFrame) -> None:
    st.subheader(ENTRY_POINT_ANALYTICS_TAB_LABEL)

    selected_dates = sorted(d for d in filtered.get("report_date", pd.Series(dtype=object)).dropna().unique().tolist())
    selected_nm_ids = sorted(
        pd.to_numeric(filtered.get("nm_id", pd.Series(dtype=object)), errors="coerce")
        .dropna()
        .astype(int)
        .unique()
        .tolist()
    )
    if not selected_dates or not selected_nm_ids:
        st.info("Нет выбранных дат или товаров для аналитики точки входа.")
        return

    selector_columns = st.columns(2)
    analysis_level = selector_columns[0].radio(
        "Уровень анализа",
        options=[ENTRY_POINT_LEVEL_CABINET, ENTRY_POINT_LEVEL_BAND, ENTRY_POINT_LEVEL_ARTICLE],
        horizontal=True,
        key="entry_point_analysis_level",
    )
    detail_level = selector_columns[1].radio(
        "Детализация",
        options=[ENTRY_POINT_DETAIL_COARSE, ENTRY_POINT_DETAIL_DETAILED],
        horizontal=True,
        key="entry_point_detail_level",
    )

    cache_buster = resolve_db_dataset_cache_buster()
    entry_df = load_entry_point_day_range_from_db(tuple(selected_dates), tuple(selected_nm_ids), cache_buster=cache_buster)
    if entry_df.empty:
        st.info("В выбранном периоде нет данных из fact_entry_point_day.")
        return

    metadata_df = build_entry_point_metadata(filtered)
    spend_df = None
    if detail_level == ENTRY_POINT_DETAIL_COARSE:
        spend_df = load_entry_point_spend_range_from_db(tuple(selected_dates), tuple(selected_nm_ids), cache_buster=cache_buster)
    display_df = build_entry_point_analytics_table(
        entry_df,
        metadata_df,
        analysis_level=analysis_level,
        detail_level=detail_level,
        spend_df=spend_df,
    )
    if display_df.empty:
        st.info("После агрегации данных для выбранного режима не осталось строк.")
        return

    selected_article_label: str | None = None
    selected_band: str | None = None

    if analysis_level == ENTRY_POINT_LEVEL_ARTICLE:
        article_filtered = filtered.copy()
        if "nm_id" in article_filtered.columns:
            article_filtered["nm_id"] = pd.to_numeric(article_filtered["nm_id"], errors="coerce")
            article_filtered = article_filtered[article_filtered["nm_id"].isin(selected_nm_ids)].copy()
        article_options, _ = get_product_options(article_filtered)
        article_options = ["Топ артикулов по корзинам"] + article_options
        selected_article_label = st.selectbox(
            "Артикул для детализации",
            options=article_options,
            key="entry_point_article_filter",
        )
        if selected_article_label == "Топ артикулов по корзинам":
            selected_article_label = None

    if analysis_level == ENTRY_POINT_LEVEL_BAND and detail_level == ENTRY_POINT_DETAIL_DETAILED:
        band_options = ["Все банды"]
        if "band_name" in metadata_df.columns:
            band_values = sorted(
                value
                for value in metadata_df["band_name"].dropna().astype(str).unique().tolist()
                if value.strip()
            )
            band_options.extend(band_values)
        selected_band = st.selectbox(
            "Банда для детализации",
            options=band_options,
            key="entry_point_band_filter",
        )

    display_df, limit_context = limit_entry_point_analytics_table(
        display_df,
        analysis_level=analysis_level,
        detail_level=detail_level,
        selected_article_label=selected_article_label,
        selected_band=selected_band,
    )
    if display_df.empty:
        st.info("После применения ограничений для выбранного режима не осталось строк.")
        return
    if limit_context.get("message"):
        st.caption(str(limit_context["message"]))

    export_display_df = display_df.drop(columns=["__entry_point_conversion_fallback_7d"], errors="ignore")
    export_file_name = (
        f"entry_point_analytics_{selected_dates[0].isoformat()}_{selected_dates[-1].isoformat()}.xlsx"
        if selected_dates
        else "entry_point_analytics.xlsx"
    )
    export_bytes = build_excel_export_bytes(export_display_df)
    st.download_button(
        "Скачать XLSX",
        data=export_bytes,
        file_name=export_file_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="entry_point_analytics_xlsx_download",
    )

    column_config = {
        ENTRY_POINT_LABEL_DATE: st.column_config.DateColumn(ENTRY_POINT_LABEL_DATE),
        ENTRY_POINT_LABEL_WB_ARTICLE: st.column_config.NumberColumn(ENTRY_POINT_LABEL_WB_ARTICLE, format="%d"),
        ENTRY_POINT_LABEL_IMPRESSIONS: st.column_config.NumberColumn(ENTRY_POINT_LABEL_IMPRESSIONS, format="%.0f"),
        ENTRY_POINT_LABEL_CARD_CLICKS: st.column_config.NumberColumn(ENTRY_POINT_LABEL_CARD_CLICKS, format="%.0f"),
        ENTRY_POINT_LABEL_CART_COUNT: st.column_config.NumberColumn(ENTRY_POINT_LABEL_CART_COUNT, format="%.0f"),
        ENTRY_POINT_LABEL_CART_CONVERSION: st.column_config.NumberColumn(ENTRY_POINT_LABEL_CART_CONVERSION, format="%.2f"),
        ENTRY_POINT_LABEL_ORDERS: st.column_config.NumberColumn(ENTRY_POINT_LABEL_ORDERS, format="%.0f"),
        ENTRY_POINT_LABEL_ORDER_CONVERSION: st.column_config.NumberColumn(ENTRY_POINT_LABEL_ORDER_CONVERSION, format="%.2f"),
    }
    if ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN in display_df.columns:
        column_config[ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN] = st.column_config.NumberColumn(
            ENTRY_POINT_ECONOMICS_ALLOCATED_SPEND_COLUMN,
            format="%.2f",
        )
        column_config[ENTRY_POINT_ECONOMICS_CART_COST_COLUMN] = st.column_config.NumberColumn(
            ENTRY_POINT_ECONOMICS_CART_COST_COLUMN,
            format="%.2f",
        )
        column_config[ENTRY_POINT_ECONOMICS_CPO_COLUMN] = st.column_config.NumberColumn(
            ENTRY_POINT_ECONOMICS_CPO_COLUMN,
            format="%.2f",
        )

    safe_st_dataframe(
        style_entry_point_analytics_table(display_df),
        width="stretch",
        hide_index=True,
        height=720,
        column_config=column_config,
    )
    st.caption(
        "* Если за день менее 50 корзин, конверсия в корзину считается за последние 7 дней и подсвечивается жёлтым цветом. "
        "Всплески добавлений в корзину относительно среднего по этой группе подсвечиваются красным."
    )


def render_overview_tab(
    filtered: pd.DataFrame,
    filter_debug_trace: list[dict[str, object]],
    display_coverage: pd.DataFrame | None = None,
) -> tuple[int, int]:
    started_at = perf_counter()
    view_mode = BY_DATE_MODE_LABEL
    show_empty_rows = bool(filtered.attrs.get("show_rows_without_data", False))

    if view_mode == LATEST_MODE_LABEL:
        st.info("Одна строка = один товар. Показана последняя доступная дата и изменение к предыдущей доступной дате по этому товару.")
        table_df = build_latest_snapshot_dataset(filtered)
        display_columns = DISPLAY_COLUMNS_LATEST
        export_columns = DISPLAY_COLUMNS_LATEST
        status_column = "data_quality_label"
        download_label = "Скачать CSV"
    else:
        table_df = build_grouped_by_date_dataset(filtered).copy()
        table_df["technical_ad_campaign_spend_total"] = table_df.get("ad_campaign_spend_total")
        display_columns = DISPLAY_COLUMNS_BY_DATE
        export_columns = DISPLAY_COLUMNS_BY_DATE
        status_column = "data_quality_label"
        download_label = "Скачать расширенный ИТОГО CSV"

    overview_product_options, overview_product_option_map = get_product_options(filtered)
    overview_product_filter_options = [OVERVIEW_ALL_PRODUCTS_LABEL, *overview_product_options]
    selected_overview_product_label = st.selectbox(
        "Выбрать товар",
        options=overview_product_filter_options,
        index=0,
        key="overview_selected_product_label",
    )
    table_df = filter_rows_by_selected_product_label(
        table_df,
        selected_overview_product_label,
        overview_product_option_map,
    )

    if view_mode == LATEST_MODE_LABEL:
        table_display_df = table_df.reindex(columns=display_columns).copy()
        export_df = build_export_dataframe(table_df, export_columns)
    else:
        table_display_df, export_df = build_overview_export_tables(table_df, show_empty_rows=show_empty_rows)
    export_debug_trace = [
        build_debug_snapshot("rows_before_export_table_df", table_df),
        build_debug_snapshot("rows_before_export_export_df", export_df),
    ]
    csv_file_name = build_filtered_table_export_filename(table_display_df, "csv")
    excel_file_name = build_filtered_table_export_filename(table_display_df, "xlsx")
    csv_bytes = export_df.to_csv(index=False).encode("utf-8-sig")
    excel_bytes = build_excel_export_bytes(export_df)
    download_cols = st.columns(2)
    download_cols[0].download_button(download_label, data=csv_bytes, file_name=csv_file_name, mime="text/csv")
    download_cols[1].download_button(
        "Скачать текущую таблицу в Excel",
        data=excel_bytes,
        file_name=excel_file_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    )
    with st.expander("Debug фильтрации и экспорта"):
        st.caption("Экспорт CSV строится не из полного load_dataset_from_db(), а из текущего table_df после всех применённых фильтров.")
        safe_st_dataframe(build_debug_trace_frame(filter_debug_trace), width="stretch", hide_index=True, force_object_strings=True)
        safe_st_dataframe(build_debug_trace_frame(export_debug_trace), width="stretch", hide_index=True, force_object_strings=True)
        if display_coverage is not None and not display_coverage.empty:
            st.caption("Coverage по display-заменам: сколько значений были NULL, сколько стали 0 по правилам display-слоя, сколько осталось реально > 0.")
            safe_st_dataframe(display_coverage, width="stretch", hide_index=True, force_object_strings=True)
    safe_st_dataframe(
        table_display_df,
        numeric_columns=_get_streamlit_display_numeric_columns(),
        force_object_strings=True,
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
            "wb_buyer_price": st.column_config.NumberColumn("Цена WB", format="%.2f"),
            "wb_seller_price": st.column_config.NumberColumn("Цена продавца ЛК", format="%.2f"),
            "spp_rub": st.column_config.NumberColumn("СПП, ₽", format="%.2f"),
            "spp_pct": st.column_config.NumberColumn("СПП, %", format="%.2f"),
            "impressions": st.column_config.NumberColumn("Показы общие", format="%.0f"),
            "card_clicks": st.column_config.NumberColumn("Переходы в карточку", format="%.0f"),
            "ctr_calc": st.column_config.NumberColumn("CTR общий", format="%.2f"),
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
            "ad_campaign_spend_total": st.column_config.NumberColumn("Сумма кампании", format="%.2f"),
            "legacy_cost_per_card_click_calc": st.column_config.NumberColumn("Цена перехода по общим переходам", format="%.2f"),
            "legacy_cost_per_all_carts_calc": st.column_config.NumberColumn("Расход на все корзины", format="%.2f"),
            "legacy_cost_per_order_calc": st.column_config.NumberColumn("Расход на все заказы", format="%.2f"),
            "legacy_ad_share_of_order_sum_pct": st.column_config.NumberColumn("Доля рекламы от суммы заказов, %", format="%.2f"),
            "technical_ad_campaign_spend_total": st.column_config.NumberColumn("Расход РК по статистике", format="%.2f"),
            "ad_campaign_spend_delta": st.column_config.NumberColumn("Δ Расход РК", format="%.2f"),
            "ad_views_total": st.column_config.NumberColumn("Показы РК", format="%.0f"),
            "ad_clicks_total": st.column_config.NumberColumn("Клики РК", format="%.0f"),
            "ad_atbs_total": st.column_config.NumberColumn("Корзины РК", format="%.0f"),
            "ad_atbs_delta": st.column_config.NumberColumn("Δ Корзины РК", format="%.0f"),
            "ad_orders_total": st.column_config.NumberColumn("Заказы РК", format="%.0f"),
            "ad_orders_delta": st.column_config.NumberColumn("Δ Заказы РК", format="%.0f"),
            "ad_cpc_calc": st.column_config.NumberColumn("CPC РК", format="%.2f"),
            "ad_cpm_calc": st.column_config.NumberColumn("CPM РК", format="%.2f"),
            "ad_cost_per_cart_calc": st.column_config.NumberColumn("Цена корзины РК", format="%.2f"),
            "ad_cpo_calc": st.column_config.NumberColumn("CPO РК", format="%.2f"),
            "ad_cpo_delta": st.column_config.NumberColumn("Δ CPO", format="%.2f"),
            "ad_share_of_revenue_calc": st.column_config.NumberColumn("Доля рекламы от суммы заказов, %", format="%.2f"),
            "direct_ad_atbs": st.column_config.NumberColumn("Прямые корзины РК", format="%.0f"),
            "associated_ad_atbs": st.column_config.NumberColumn("Ассоциированные корзины РК", format="%.0f"),
            "multicard_ad_atbs": st.column_config.NumberColumn("Мультикарточка корзины РК", format="%.0f"),
            "unknown_ad_atbs": st.column_config.NumberColumn("Unknown корзины РК", format="%.0f"),
            "associated_atbs_percent_calc": st.column_config.NumberColumn("Ассоциированные корзины, %", format="%.2f"),
            "organic_cart_count": st.column_config.NumberColumn("Органические корзины", format="%.0f"),
            "organic_cart_share_calc": st.column_config.NumberColumn("Процент органики от рекламных корзин", format="%.2f"),
            "vvbromo_organic_sales": st.column_config.NumberColumn("Продажи органические VVBromo", format="%.0f"),
            "vvbromo_operating_profit": st.column_config.NumberColumn("Операционная прибыль VVBromo", format="%.2f"),
            "vvbromo_operating_profit_per_unit": st.column_config.NumberColumn("Опер. прибыль/ед. VVBromo", format="%.2f"),
            "crm_common_calc": st.column_config.NumberColumn("CRM по общим заказам", format="%.2f"),
            "ad_cost_per_all_carts_calc": st.column_config.NumberColumn("Тех: расход на все корзины (с assoc.)", format="%.2f"),
            "avg_delivery_time": st.column_config.NumberColumn("Среднее время доставки", format="%.2f"),
            "organic_cart_share_status": st.column_config.TextColumn("Статус формулы органики", width="medium"),
            "search_queries_count": st.column_config.NumberColumn("Поисковые запросы", format="%.0f"),
            "search_avg_position": st.column_config.NumberColumn("Средняя позиция поиска", format="%.2f"),
            "search_visibility": st.column_config.NumberColumn("Видимость поиска", format="%.2f"),
            "search_clicks": st.column_config.NumberColumn("Клики из поиска", format="%.0f"),
            "search_cart": st.column_config.NumberColumn("Корзины из поиска", format="%.0f"),
            "search_orders": st.column_config.NumberColumn("Заказы из поиска", format="%.0f"),
            "search_queries_delta": st.column_config.NumberColumn("Δ Поиск", format="%.0f"),
            "current_stock_qty": st.column_config.NumberColumn("Остаток WB", format="%.0f"),
            "current_stock_sum": st.column_config.NumberColumn("Сумма остатков", format="%.2f"),
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
    _log_timing("render_overview_tab", started_at, filtered_rows=len(filtered), displayed_rows=len(table_display_df))
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
    safe_st_dataframe(
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


def render_simple_kpi_row(
    latest_row: pd.Series,
    configs: list[tuple[str, str, int, float | None, str | None]],
) -> None:
    cols = st.columns(len(configs))
    for column, config in zip(cols, configs):
        field_name, label, digits, threshold, threshold_label = config
        with column:
            st.metric(label, fmt_num(latest_row.get(field_name), digits))
            value = latest_row.get(field_name)
            if threshold is not None and not pd.isna(value) and float(value) > threshold and threshold_label:
                st.caption(f"Превышение: {threshold_label}")


def render_summary_kpis(latest_row: pd.Series) -> None:
    st.subheader("Основные KPI по последней дате")
    render_simple_kpi_row(
        latest_row,
        [
            ("cart_count", "Корзины", 0, None, None),
            ("order_count", "Заказы", 0, None, None),
            ("order_sum", "Сумма заказов", 2, None, None),
            ("ad_cpo_calc", "CPO", 2, CHART_THRESHOLD_CPO, "CPO выше 150 руб."),
        ],
    )
    render_simple_kpi_row(
        latest_row,
        [
            ("ad_campaign_spend_total", "Расход РК", 2, None, None),
            ("ad_atbs_total", "Корзины РК", 0, None, None),
            ("ad_orders_total", "Заказы РК", 0, None, None),
            ("ad_cost_per_cart_calc", "Цена рекламной корзины", 2, CHART_THRESHOLD_CART_COST, "Цена корзины выше 35 руб."),
        ],
    )
    render_simple_kpi_row(
        latest_row,
        [
            ("impressions", "Показы", 0, None, None),
            ("search_queries_count", "Поисковые запросы", 0, None, None),
            ("current_stock_qty", "Текущий остаток", 0, None, None),
            ("ad_share_of_revenue_calc", "ДРР", 2, None, None),
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
        safe_st_dataframe(
            timeline,
            width="stretch",
            hide_index=True,
            column_config={
            "report_date": st.column_config.DateColumn("Дата"),
            "wb_buyer_price": st.column_config.NumberColumn("Цена WB", format="%.2f"),
            "wb_seller_price": st.column_config.NumberColumn("Цена продавца ЛК", format="%.2f"),
            "spp_rub": st.column_config.NumberColumn("СПП, ₽", format="%.2f"),
            "spp_pct": st.column_config.NumberColumn("СПП, %", format="%.2f"),
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
    latest_row: pd.Series = context["display_row"]
    latest_date = context["display_date"]
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
    render_info_field(passport_cols_mid[2], "Дата данных карточки", latest_date)

    render_info_field(st, "Статус данных", latest_row.get("data_quality_label"))

    render_summary_kpis(latest_row)

    detail_dates = sorted(product_rows["report_date"].dropna().unique().tolist(), reverse=True)
    default_detail_index = detail_dates.index(latest_date) if latest_date in detail_dates else 0
    detail_date = st.selectbox(
        "Дата для детализации формул",
        options=detail_dates,
        index=default_detail_index,
        format_func=lambda d: str(d),
    )
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
            ("Цена WB", detail_row.get("wb_buyer_price"), 2),
            ("Цена продавца ЛК", detail_row.get("wb_seller_price"), 2),
            ("СПП, ₽", detail_row.get("spp_rub"), 2),
            ("СПП, %", detail_row.get("spp_pct"), 2),
            ("Количество поисковых запросов", detail_row.get("search_queries_count"), 0),
            ("Текущий остаток", detail_row.get("current_stock_qty"), 0),
        ],
    )

    with st.expander("Проверка формул", expanded=False):
        render_formula_details(detail_row, detail_date)

    render_product_charts_section(product_rows)
    render_product_timeline_table(product_rows)

    st.subheader("Внимание")
    warnings = build_warnings(latest_row, context["display_previous_row"])
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


def _row_has_api_ad_metrics(row: Mapping[str, Any]) -> bool:
    if bool(row.get("has_ad_cost")) or bool(row.get("has_ad_campaign")):
        return True
    for field_name in (
        "ad_campaign_spend_total",
        "ad_atbs_total",
        "ad_views_total",
        "ad_orders_total",
        "ad_cost_writeoff_total",
    ):
        if not pd.isna(row.get(field_name)):
            return True
    return False


def aggregate_ivan_manual_ads_for_charts(
    manual_ads_df: pd.DataFrame,
    *,
    date_from: date | None = None,
    date_to: date | None = None,
) -> pd.DataFrame:
    columns = [
        "report_date",
        "nm_id",
        "supplier_article",
        "title",
        "ad_campaign_spend_total_manual",
        "ad_atbs_total_manual",
        "ad_views_total_manual",
        "ad_cost_per_cart_manual",
        "ad_cpm_manual",
        "source_status",
        "data_status",
        "import_quality",
        "ad_data_source",
    ]
    if manual_ads_df.empty:
        return pd.DataFrame(columns=columns)

    df = manual_ads_df.copy()
    df["date"] = pd.to_datetime(df["date"], errors="coerce").dt.date
    if date_from is not None:
        df = df[df["date"] >= date_from].copy()
    if date_to is not None:
        df = df[df["date"] <= date_to].copy()
    if df.empty:
        return pd.DataFrame(columns=columns)

    for optional_column in ("supplier_article", "title", "source_status", "data_status", "import_quality"):
        if optional_column not in df.columns:
            df[optional_column] = pd.NA

    grouped = (
        df.groupby(["date", "nm_id"], as_index=False)
        .agg(
            supplier_article=("supplier_article", "first"),
            title=("title", "first"),
            ad_spend=("ad_spend", lambda values: pd.to_numeric(pd.Series(values), errors="coerce").sum(min_count=1)),
            ad_atbs=("ad_atbs", lambda values: pd.to_numeric(pd.Series(values), errors="coerce").sum(min_count=1)),
            ad_views=("ad_views", lambda values: pd.to_numeric(pd.Series(values), errors="coerce").sum(min_count=1)),
            source_status=("source_status", "first"),
            data_status=("data_status", "first"),
            import_quality=("import_quality", "first"),
        )
        .sort_values(["date", "nm_id"], kind="stable")
        .reset_index(drop=True)
    )
    grouped["ad_cost_per_cart_manual"] = grouped.apply(
        lambda row: safe_chart_divide(row.get("ad_spend"), row.get("ad_atbs")),
        axis=1,
    )
    grouped["ad_cpm_manual"] = grouped.apply(
        lambda row: (
            None
            if safe_chart_divide(row.get("ad_spend"), row.get("ad_views")) is None
            else safe_chart_divide(row.get("ad_spend"), row.get("ad_views")) * 1000
        ),
        axis=1,
    )
    grouped["ad_data_source"] = grouped["source_status"].fillna(IVAN_MANUAL_AD_SOURCE_LABEL)
    grouped = grouped.rename(
        columns={
            "date": "report_date",
            "ad_spend": "ad_campaign_spend_total_manual",
            "ad_atbs": "ad_atbs_total_manual",
            "ad_views": "ad_views_total_manual",
        }
    )
    return grouped[columns]


def merge_ivan_manual_ads_into_chart_scope(
    scope_rows: pd.DataFrame,
    manual_chart_df: pd.DataFrame,
    *,
    aggregation_level: str,
    period_start: date | None,
    period_end: date | None,
    total_manual_rows: int,
    total_manual_products: int,
    total_manual_spend: float | None,
    manual_period_start: date | None,
    manual_period_end: date | None,
    matched_dim_product_rows: int,
    matched_active_product_rows: int,
) -> tuple[pd.DataFrame, dict[str, object]]:
    summary: dict[str, object] = {
        "api_ad_rows_in_selected_period": 0,
        "ivan_manual_ad_rows_total": int(total_manual_rows),
        "ivan_manual_ad_rows_in_selected_period": 0,
        "ivan_manual_products": int(total_manual_products),
        "ivan_manual_period": (
            f"{manual_period_start.isoformat()} .. {manual_period_end.isoformat()}"
            if manual_period_start and manual_period_end
            else None
        ),
        "ivan_manual_spend_total": total_manual_spend,
        "ivan_manual_rows_matched_to_dim_product": int(matched_dim_product_rows),
        "ivan_manual_rows_matched_to_active_products": int(matched_active_product_rows),
        "ivan_manual_rows_used_in_charts": 0,
        "ivan_manual_rows_skipped_because_api_exists": 0,
        "ivan_manual_rows_hidden_by_current_filters": 0,
    }

    result = scope_rows.copy()
    if "report_date" in result.columns:
        result["report_date"] = pd.to_datetime(result["report_date"], errors="coerce").dt.date
    else:
        result["report_date"] = pd.NaT
    manual_period_df = manual_chart_df.copy()
    if not manual_period_df.empty:
        manual_period_df["report_date"] = pd.to_datetime(manual_period_df["report_date"], errors="coerce").dt.date
        if period_start is not None:
            manual_period_df = manual_period_df[manual_period_df["report_date"] >= period_start].copy()
        if period_end is not None:
            manual_period_df = manual_period_df[manual_period_df["report_date"] <= period_end].copy()
    summary["ivan_manual_ad_rows_in_selected_period"] = int(len(manual_period_df))

    if manual_period_df.empty:
        return result, summary

    api_mask = result.apply(_row_has_api_ad_metrics, axis=1) if not result.empty else pd.Series(dtype=bool)
    summary["api_ad_rows_in_selected_period"] = int(api_mask.sum()) if not api_mask.empty else 0

    scope_keys = {
        (row.report_date, int(row.nm_id))
        for row in result[["report_date", "nm_id"]].dropna().itertuples(index=False)
    }
    api_keys = {
        (result.iloc[index]["report_date"], int(result.iloc[index]["nm_id"]))
        for index, is_api in enumerate(api_mask.tolist())
        if is_api
    }
    manual_period_df["_merge_key"] = list(
        zip(
            manual_period_df["report_date"],
            manual_period_df["nm_id"].astype(int),
        )
    )
    manual_keys = set(manual_period_df["_merge_key"].tolist())
    skipped_api_keys = manual_keys & api_keys
    appendable_keys = set()
    used_existing_keys = {key for key in manual_keys if key in scope_keys and key not in api_keys}
    hidden_keys = manual_keys - skipped_api_keys - appendable_keys - used_existing_keys

    summary["ivan_manual_rows_used_in_charts"] = int(len(used_existing_keys) + len(appendable_keys))
    summary["ivan_manual_rows_skipped_because_api_exists"] = int(len(skipped_api_keys))
    summary["ivan_manual_rows_hidden_by_current_filters"] = int(len(hidden_keys))

    for api_column, base_column in (
        ("ad_campaign_spend_total_api", "ad_campaign_spend_total"),
        ("ad_atbs_total_api", "ad_atbs_total"),
        ("ad_views_total_api", "ad_views_total"),
    ):
        if api_column not in result.columns:
            result[api_column] = result.get(base_column)

    merge_columns = [
        "report_date",
        "nm_id",
        "supplier_article",
        "title",
        "ad_campaign_spend_total_manual",
        "ad_atbs_total_manual",
        "ad_views_total_manual",
        "ad_cost_per_cart_manual",
        "ad_cpm_manual",
        "source_status",
        "data_status",
        "import_quality",
        "ad_data_source",
    ]
    result = result.merge(
        manual_period_df[merge_columns],
        on=["report_date", "nm_id"],
        how="left",
        suffixes=("", "_ivan"),
    )

    api_mask = result.apply(_row_has_api_ad_metrics, axis=1) if not result.empty else pd.Series(dtype=bool)
    manual_available_mask = (
        result.get("ad_campaign_spend_total_manual").notna()
        | result.get("ad_atbs_total_manual").notna()
        | result.get("ad_views_total_manual").notna()
    )
    manual_used_mask = manual_available_mask & ~api_mask

    for base_column, manual_column in (
        ("ad_campaign_spend_total", "ad_campaign_spend_total_manual"),
        ("ad_atbs_total", "ad_atbs_total_manual"),
        ("ad_views_total", "ad_views_total_manual"),
    ):
        if base_column not in result.columns:
            result[base_column] = pd.NA
        result[base_column] = result[base_column].where(~manual_used_mask, result[manual_column])

    if "ad_cost_per_cart_calc" not in result.columns:
        result["ad_cost_per_cart_calc"] = pd.NA
    if "ad_cpm_calc" not in result.columns:
        result["ad_cpm_calc"] = pd.NA
    if "ad_data_source" not in result.columns:
        result["ad_data_source"] = pd.NA
    if "has_ad_campaign" not in result.columns:
        result["has_ad_campaign"] = False
    if "has_ad_cost" not in result.columns:
        result["has_ad_cost"] = False

    result["ad_cost_per_cart_calc"] = result["ad_cost_per_cart_calc"].where(~manual_used_mask, result["ad_cost_per_cart_manual"])
    result["ad_cpm_calc"] = result["ad_cpm_calc"].where(~manual_used_mask, result["ad_cpm_manual"])
    result["ad_data_source"] = result["ad_data_source"].where(~manual_used_mask, result["ad_data_source_ivan"] if "ad_data_source_ivan" in result.columns else result["ad_data_source"])
    result.loc[api_mask & result["ad_data_source"].isna(), "ad_data_source"] = API_WB_AD_SOURCE_LABEL
    result["has_ad_campaign"] = result["has_ad_campaign"].where(~manual_used_mask, True)

    if "source_status_ivan" in result.columns:
        result["manual_source_status"] = result["source_status_ivan"]
    if "data_status_ivan" in result.columns:
        result["manual_data_status"] = result["data_status_ivan"]
    if "import_quality_ivan" in result.columns:
        result["manual_import_quality"] = result["import_quality_ivan"]

    result.attrs = {}
    return result, summary


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
        confirmed_df = source_df[build_user_facing_ad_kpi_mask(source_df, reference_date=reference_date)].copy()

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


def build_user_facing_ad_kpi_mask(
    chart_df: pd.DataFrame,
    *,
    reference_date: date | None = None,
) -> pd.Series:
    if chart_df.empty or "report_date" not in chart_df.columns:
        return pd.Series(False, index=chart_df.index, dtype="bool")

    report_dates = pd.to_datetime(chart_df["report_date"], errors="coerce").dt.date
    cutoffs = get_chart_metric_cutoffs(reference_date)
    mask = report_dates.notna() & report_dates.le(cutoffs["ad_attribution_cutoff"])
    if "ad_attribution_status" in chart_df.columns:
        mask &= chart_df["ad_attribution_status"].fillna("OK").astype(str).ne("AD_ATTRIBUTION_LAGGED")
    return mask


def format_ad_kpi_period_caption(period_start: date | None, period_end: date | None) -> str:
    if period_start is None or period_end is None:
        return "Период расчёта рекламных KPI: нет доступных данных"
    return (
        "Период расчёта рекламных KPI: "
        f"{period_start.strftime('%d.%m.%Y')}–{period_end.strftime('%d.%m.%Y')}"
    )


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
            "ad_kpi_period_start": None,
            "ad_kpi_period_end": None,
            "has_lagged_ad_attribution": False,
            "has_partial_ad_attribution": False,
        }

    report_dates = pd.to_datetime(chart_df["report_date"], errors="coerce").dt.date
    cutoffs = get_chart_metric_cutoffs(reference_date)
    total_mask = report_dates.notna() & report_dates.le(cutoffs["total_metrics_cutoff"])
    ad_attribution_mask = build_user_facing_ad_kpi_mask(chart_df, reference_date=reference_date)
    ad_period_dates = report_dates[ad_attribution_mask]
    ad_kpi_period_start = ad_period_dates.min() if not ad_period_dates.empty else None
    ad_kpi_period_end = ad_period_dates.max() if not ad_period_dates.empty else None

    total_carts = sum_chart_metric(chart_df, "cart_count", total_mask)
    total_orders = sum_chart_metric(chart_df, "order_count", total_mask)
    ad_spend_total = sum_chart_metric(chart_df, "ad_campaign_spend_total", ad_attribution_mask)
    ad_carts = sum_chart_metric(
        chart_df,
        "ad_atbs_total_confirmed" if "ad_atbs_total_confirmed" in chart_df.columns else "ad_atbs_total",
        ad_attribution_mask,
    )
    ad_orders = sum_chart_metric(
        chart_df,
        "ad_orders_total_confirmed" if "ad_orders_total_confirmed" in chart_df.columns else "ad_orders_total",
        ad_attribution_mask,
    )
    ad_spend_confirmed = sum_chart_metric(
        chart_df,
        "ad_spend_confirmed" if "ad_spend_confirmed" in chart_df.columns else "ad_campaign_spend_total",
        ad_attribution_mask,
    )

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
        "ad_kpi_period_start": ad_kpi_period_start,
        "ad_kpi_period_end": ad_kpi_period_end,
        "has_lagged_ad_attribution": bool((report_dates > cutoffs["ad_attribution_cutoff"]).any()),
        "has_partial_ad_attribution": bool(
            "ad_attribution_status" in chart_df.columns
            and chart_df["ad_attribution_status"].eq("AD_DATA_PARTIAL").any()
        ),
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
        "ad_atbs_total_api",
        "ad_atbs_total_manual",
        "order_count",
        "ad_orders_total",
        "ad_campaign_spend_total",
        "ad_campaign_spend_total_api",
        "ad_campaign_spend_total_manual",
        "ad_cost_writeoff_total",
        "ad_views_total",
        "ad_views_total_api",
        "ad_views_total_manual",
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
    partial_mask = pd.Series(False, index=grouped.index)
    if "ad_campaign_spend_total" in grouped.columns and "ad_cost_writeoff_total" in grouped.columns:
        ad_campaign_spend_series = pd.to_numeric(grouped["ad_campaign_spend_total"], errors="coerce")
        ad_cost_writeoff_series = pd.to_numeric(grouped["ad_cost_writeoff_total"], errors="coerce")
        # AD_DATA_PARTIAL compares campaign-statistics spend with writeoff spend.
        # These sources use different date semantics.
        # The flag is diagnostic only and must not exclude rows from user-facing
        # fullstats advertising KPIs.
        partial_mask = (
            ~lagged_mask
            & ad_cost_writeoff_series.notna()
            & ad_cost_writeoff_series.gt(0)
            & ad_campaign_spend_series.notna()
            & ad_campaign_spend_series.lt(ad_cost_writeoff_series * CHART_AD_PARTIAL_SPEND_COVERAGE_THRESHOLD)
        )

    grouped["ad_attribution_status"] = "OK"
    grouped.loc[lagged_mask, "ad_attribution_status"] = "AD_ATTRIBUTION_LAGGED"
    grouped.loc[partial_mask, "ad_attribution_status"] = "AD_DATA_PARTIAL"
    confirmed_mask = ~lagged_mask
    if "ad_atbs_total" in grouped.columns:
        grouped["ad_atbs_total_confirmed"] = grouped["ad_atbs_total"].where(confirmed_mask)
    if "ad_atbs_total_api" in grouped.columns:
        grouped["ad_atbs_total_api_confirmed"] = grouped["ad_atbs_total_api"].where(confirmed_mask)
    if "ad_atbs_total_manual" in grouped.columns:
        grouped["ad_atbs_total_manual_confirmed"] = grouped["ad_atbs_total_manual"]
    if "ad_orders_total" in grouped.columns:
        grouped["ad_orders_total_confirmed"] = grouped["ad_orders_total"].where(confirmed_mask)
    if "ad_campaign_spend_total" in grouped.columns:
        grouped["ad_spend_confirmed"] = grouped["ad_campaign_spend_total"].where(confirmed_mask)
    if "ad_campaign_spend_total_api" in grouped.columns:
        grouped["ad_spend_api_confirmed"] = grouped["ad_campaign_spend_total_api"].where(confirmed_mask)
    if "ad_campaign_spend_total_manual" in grouped.columns:
        grouped["ad_spend_manual_confirmed"] = grouped["ad_campaign_spend_total_manual"]
    grouped["total_cart_cost"] = grouped.apply(
        lambda row: safe_chart_divide(row.get("ad_campaign_spend_total"), row.get("cart_count")),
        axis=1,
    )
    grouped["ad_cart_cost"] = grouped.apply(
        lambda row: safe_chart_divide(row.get("ad_spend_confirmed"), row.get("ad_atbs_total_confirmed")),
        axis=1,
    )
    grouped["ad_cart_cost_api"] = grouped.apply(
        lambda row: safe_chart_divide(row.get("ad_spend_api_confirmed"), row.get("ad_atbs_total_api_confirmed")),
        axis=1,
    )
    grouped["ad_cart_cost_manual"] = grouped.apply(
        lambda row: safe_chart_divide(row.get("ad_spend_manual_confirmed"), row.get("ad_atbs_total_manual_confirmed")),
        axis=1,
    )
    grouped["ad_cpm_api"] = grouped.apply(
        lambda row: (
            None
            if safe_chart_divide(row.get("ad_campaign_spend_total_api"), row.get("ad_views_total_api")) is None
            else safe_chart_divide(row.get("ad_campaign_spend_total_api"), row.get("ad_views_total_api")) * 1000
        ),
        axis=1,
    )
    grouped["ad_cpm_manual"] = grouped.apply(
        lambda row: (
            None
            if safe_chart_divide(row.get("ad_campaign_spend_total_manual"), row.get("ad_views_total_manual")) is None
            else safe_chart_divide(row.get("ad_campaign_spend_total_manual"), row.get("ad_views_total_manual")) * 1000
        ),
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


def build_milestones_altair_layer(milestones: list[dict[str, Any]]) -> alt.Chart | None:
    if not milestones:
        return None
    rows = []
    for m in milestones:
        rows.append({
            "milestone_date": pd.to_datetime(m["milestone_date"]),
            "milestone_type_label": m.get("milestone_type_label") or m.get("milestone_type", ""),
            "title": m.get("title", ""),
            "comment": m.get("comment") or "—",
            "milestone_type": m.get("milestone_type", ""),
        })
    df_m = pd.DataFrame(rows)
    if df_m.empty:
        return None

    color_scale = alt.Scale(
        domain=["price_discount", "advertising", "stock_supply", "content", "technical", "other"],
        range=["#d97706", "#ec4899", "#10b981", "#8b5cf6", "#ef4444", "#6b7280"],
    )

    milestone_rules = alt.Chart(df_m).mark_rule(
        strokeDash=[4, 4],
        strokeWidth=2,
    ).encode(
        x=alt.X("milestone_date:T"),
        color=alt.Color("milestone_type:N", scale=color_scale, legend=alt.Legend(title="Тип вехи")),
        tooltip=[
            alt.Tooltip("milestone_date:T", title="Дата вехи", format="%d.%m.%Y"),
            alt.Tooltip("milestone_type_label:N", title="Тип вехи"),
            alt.Tooltip("title:N", title="Название"),
            alt.Tooltip("comment:N", title="Комментарий"),
        ],
    )
    return milestone_rules


def render_milestones_management_block(chart_df: pd.DataFrame) -> None:
    st.markdown("#### Управление вехами")
    min_date = (
        chart_df["report_date"].dropna().min()
        if "report_date" in chart_df.columns and not chart_df["report_date"].dropna().empty
        else datetime.now().date()
    )
    max_date = (
        chart_df["report_date"].dropna().max()
        if "report_date" in chart_df.columns and not chart_df["report_date"].dropna().empty
        else datetime.now().date()
    )

    with st.expander("➕ Добавить веху", expanded=False):
        with st.form(key="add_milestone_form"):
            c1, c2 = st.columns(2)
            with c1:
                new_date = st.date_input("Дата вехи", value=max_date)
                new_type = st.selectbox(
                    "Тип вехи",
                    options=list(MILESTONE_TYPES.keys()),
                    format_func=lambda x: MILESTONE_TYPES[x],
                    index=0,
                )
            with c2:
                new_title = st.text_input("Название вехи", placeholder="Например, Снижение цены на 10%")
                new_comment = st.text_input("Комментарий (необязательно)", placeholder="Детали изменения...")
            submitted = st.form_submit_button("Сохранить веху")
            if submitted:
                if not new_title.strip():
                    st.error("Укажите название вехи!")
                else:
                    try:
                        create_milestone(
                            milestone_date=new_date,
                            milestone_type=new_type,
                            title=new_title,
                            comment=new_comment,
                        )
                        st.success("Веха сохранена!")
                        st.rerun()
                    except Exception as e:
                        st.error(f"Ошибка при сохранении: {e}")

    try:
        period_milestones = list_milestones(date_from=min_date, date_to=max_date, include_inactive=False)
    except Exception:
        logger.exception("Не удалось загрузить вехи кабинета для блока управления")
        period_milestones = []

    if not period_milestones:
        st.caption("За выбранный период вех нет.")
    else:
        for m in period_milestones:
            m_id = m["id"]
            m_date_str = m["milestone_date"].strftime("%d.%m.%Y")
            m_type_label = m["milestone_type_label"]
            m_title = m["title"]
            m_comment = f" ({m['comment']})" if m.get("comment") else ""

            col_info, col_edit, col_hide = st.columns([6, 1, 1])
            with col_info:
                st.markdown(f"**{m_date_str}** — **[{m_type_label}]** {m_title}{m_comment}")
            with col_edit:
                if st.button("Изменить", key=f"edit_btn_m_{m_id}"):
                    st.session_state[f"editing_m_{m_id}"] = not st.session_state.get(f"editing_m_{m_id}", False)
            with col_hide:
                if st.button("Скрыть", key=f"hide_btn_m_{m_id}"):
                    deactivate_milestone(m_id)
                    st.rerun()

            if st.session_state.get(f"editing_m_{m_id}", False):
                with st.form(key=f"edit_m_form_{m_id}"):
                    ec1, ec2 = st.columns(2)
                    with ec1:
                        edit_date = st.date_input("Дата вехи", value=m["milestone_date"], key=f"edit_date_{m_id}")
                        type_keys = list(MILESTONE_TYPES.keys())
                        type_idx = type_keys.index(m["milestone_type"]) if m["milestone_type"] in type_keys else 0
                        edit_type = st.selectbox(
                            "Тип вехи",
                            options=type_keys,
                            format_func=lambda x: MILESTONE_TYPES[x],
                            index=type_idx,
                            key=f"edit_type_{m_id}",
                        )
                    with ec2:
                        edit_title = st.text_input("Название", value=m["title"], key=f"edit_title_{m_id}")
                        edit_comment = st.text_input("Комментарий", value=m.get("comment") or "", key=f"edit_comment_{m_id}")

                    save_edit = st.form_submit_button("Сохранить изменения")
                    if save_edit:
                        if not edit_title.strip():
                            st.error("Название не может быть пустым!")
                        else:
                            try:
                                update_milestone(
                                    milestone_id=m_id,
                                    milestone_date=edit_date,
                                    milestone_type=edit_type,
                                    title=edit_title,
                                    comment=edit_comment,
                                )
                                st.session_state[f"editing_m_{m_id}"] = False
                                st.success("Изменения сохранены!")
                                st.rerun()
                            except Exception as e:
                                st.error(f"Ошибка при обновлении: {e}")


def format_chart_kpi_value(value: float | None, digits: int = 1, suffix: str = "") -> str:
    if value is None or pd.isna(value):
        return "—"
    if digits == 0:
        return f"{int(round(float(value))):,}".replace(",", " ") + suffix
    return f"{float(value):,.{digits}f}".replace(",", " ") + suffix


def build_chart_kpi_card_html(
    *,
    label: str,
    value_text: str,
    caption_text: str,
    background: str,
    border: str,
    value_color: str,
    caption_color: str,
) -> str:
    return f"""
        <div style="
            border:1px solid {border};
            background:{background};
            border-radius:12px;
            padding:14px;
            height:136px;
            box-sizing:border-box;
            display:flex;
            flex-direction:column;
            justify-content:space-between;
        ">
            <div style="font-size:13px; line-height:1.2; color:#475569; min-height:32px;">{label}</div>
            <div style="font-size:28px; line-height:1; font-weight:700; color:{value_color}; min-height:32px; display:flex; align-items:center;">{value_text}</div>
            <div style="font-size:12px; line-height:1.2; color:{caption_color}; min-height:28px; display:flex; align-items:flex-end;">{caption_text}</div>
        </div>
    """


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
        build_chart_kpi_card_html(
            label=label,
            value_text=format_chart_kpi_value(value, digits, suffix),
            caption_text=caption,
            background=background,
            border=border,
            value_color="#0f172a",
            caption_color="#b91c1c",
        ),
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


@st.cache_data(show_spinner=False)
def load_sales_speed_data_from_db(snapshot_date: date, cache_buster: str | None = None) -> pd.DataFrame:
    """
    Загружает nm_id, date и order_count из fact_funnel_day за 7 завершенных дней
    до snapshot_date (т.е. [snapshot_date - 7 days, snapshot_date - 1 day]).
    """
    date_from = snapshot_date - timedelta(days=7)
    date_to = snapshot_date - timedelta(days=1)
    with session_scope() as session:
        stmt = select(
            FactFunnelDay.nm_id,
            FactFunnelDay.date,
            FactFunnelDay.order_count
        ).where(
            FactFunnelDay.date >= date_from,
            FactFunnelDay.date <= date_to
        )
        results = session.execute(stmt).all()
        if not results:
            return pd.DataFrame(columns=["nm_id", "date", "order_count"])
        df = pd.DataFrame([
            {
                "nm_id": r.nm_id,
                "date": r.date,
                "order_count": r.order_count
            }
            for r in results
        ])
        df["nm_id"] = pd.to_numeric(df["nm_id"], errors="coerce")
        df["order_count"] = pd.to_numeric(df["order_count"], errors="coerce")
        return df


@st.cache_data(show_spinner=False)
def load_size_sales_speed_data_from_db(snapshot_date: date, cache_buster: str | None = None) -> pd.DataFrame:
    """
    Загружает продажи по размерам из fact_wb_statistics_order_size_day за 7 завершенных дней
    до snapshot_date (т.е. [snapshot_date - 7 days, snapshot_date - 1 day]).
    """
    date_from = snapshot_date - timedelta(days=7)
    date_to = snapshot_date - timedelta(days=1)
    with session_scope() as session:
        stmt = select(
            FactWbStatisticsOrderSizeDay.date,
            FactWbStatisticsOrderSizeDay.nm_id,
            FactWbStatisticsOrderSizeDay.barcode,
            FactWbStatisticsOrderSizeDay.chrt_id,
            FactWbStatisticsOrderSizeDay.tech_size,
            FactWbStatisticsOrderSizeDay.order_count,
            FactWbStatisticsOrderSizeDay.cancel_count
        ).where(
            FactWbStatisticsOrderSizeDay.date >= date_from,
            FactWbStatisticsOrderSizeDay.date <= date_to
        )
        results = session.execute(stmt).all()
        if not results:
            return pd.DataFrame(columns=["date", "nm_id", "barcode", "chrt_id", "tech_size", "order_count", "cancel_count"])
        df = pd.DataFrame([
            {
                "date": r.date,
                "nm_id": r.nm_id,
                "barcode": r.barcode,
                "chrt_id": r.chrt_id,
                "tech_size": r.tech_size,
                "order_count": r.order_count,
                "cancel_count": r.cancel_count,
            }
            for r in results
        ])
        df["nm_id"] = pd.to_numeric(df["nm_id"], errors="coerce")
        df["chrt_id"] = pd.to_numeric(df["chrt_id"], errors="coerce")
        df["order_count"] = pd.to_numeric(df["order_count"], errors="coerce")
        df["cancel_count"] = pd.to_numeric(df["cancel_count"], errors="coerce")
        return df


def get_size_sales_speed_yesterday2(
    size_sales_df: pd.DataFrame,
    snapshot_date: date,
    nm_id: int,
    barcode: str,
) -> float | None:
    """
    Возвращает скорость продаж размера за позавчера (snapshot_date - 2 days).
    """
    if size_sales_df.empty:
        return None
    target_date = snapshot_date - timedelta(days=2)
    clean_bc = str(barcode).strip().replace(" ", "")
    mask = (
        (size_sales_df["date"] == target_date) & 
        (size_sales_df["nm_id"] == nm_id) & 
        (size_sales_df["barcode"].str.strip().str.replace(" ", "") == clean_bc)
    )
    filtered = size_sales_df[mask]
    if filtered.empty:
        return 0.0
    return float(filtered["order_count"].sum())


def get_size_sales_speed_week(
    size_sales_df: pd.DataFrame,
    snapshot_date: date,
    nm_id: int,
    barcode: str,
) -> float | None:
    """
    Возвращает среднюю скорость продаж размера за последние 7 завершенных дней.
    """
    if size_sales_df.empty:
        return None
    date_from = snapshot_date - timedelta(days=7)
    date_to = snapshot_date - timedelta(days=1)
    clean_bc = str(barcode).strip().replace(" ", "")
    mask = (
        (size_sales_df["date"] >= date_from) & 
        (size_sales_df["date"] <= date_to) & 
        (size_sales_df["nm_id"] == nm_id) & 
        (size_sales_df["barcode"].str.strip().str.replace(" ", "") == clean_bc)
    )
    filtered = size_sales_df[mask]
    if filtered.empty:
        return 0.0
    total_orders = float(filtered["order_count"].sum())
    return total_orders / 7.0


@st.cache_data(show_spinner=False)
def load_ivan_stock_product_level_from_db(stock_date: date, cache_buster: str | None = None) -> pd.DataFrame:
    rows = load_ivan_stock_product_level(stock_date)
    if not rows:
        return pd.DataFrame(columns=["stock_date", "nm_id", "ivan_stock_qty", "sizes_count", "barcodes_count"])
    df = pd.DataFrame(rows)
    if "nm_id" in df.columns:
        df["nm_id"] = pd.to_numeric(df["nm_id"], errors="coerce")
    if "ivan_stock_qty" in df.columns:
        df["ivan_stock_qty"] = _clip_non_negative_numeric_series(df["ivan_stock_qty"])
    return df


@st.cache_data(show_spinner=False)
def load_wb_supply_product_level_from_db(cache_buster: str | None = None) -> pd.DataFrame:
    rows = load_wb_supply_product_level()
    if not rows:
        return pd.DataFrame(columns=["nm_id", "vendor_code", "barcode", "wb_supply_qty"])
    df = pd.DataFrame(rows)
    if "nm_id" in df.columns:
        df["nm_id"] = pd.to_numeric(df["nm_id"], errors="coerce")
    if "vendor_code" in df.columns:
        df["vendor_code"] = df["vendor_code"].fillna("").astype(str).str.strip()
    else:
        df["vendor_code"] = ""
    if "barcode" in df.columns:
        df["barcode"] = df["barcode"].fillna("").astype(str).str.strip()
    else:
        df["barcode"] = ""
    if "wb_supply_qty" in df.columns:
        df["wb_supply_qty"] = pd.to_numeric(df["wb_supply_qty"], errors="coerce")
    return df


@st.cache_data(show_spinner=False)
def load_ivan_stock_size_level_from_db(stock_date: date, cache_buster: str | None = None) -> pd.DataFrame:
    rows = load_ivan_stock_size_level(stock_date)
    if not rows:
        return pd.DataFrame(columns=["stock_date", "nm_id", "size_name", "barcode", "quantity", "color_name", "nomenclature_raw"])
    df = pd.DataFrame(rows)
    if "nm_id" in df.columns:
        df["nm_id"] = pd.to_numeric(df["nm_id"], errors="coerce")
    if "quantity" in df.columns:
        df["quantity"] = _clip_non_negative_numeric_series(df["quantity"])
    return df


@st.cache_data(show_spinner=False)
def load_dim_product_size_from_db(nm_ids: tuple[int, ...], cache_buster: str | None = None) -> pd.DataFrame:
    rows = load_dim_product_size_rows(nm_ids=list(nm_ids))
    if not rows:
        return pd.DataFrame(columns=["nm_id", "chrt_id", "barcode", "size_name", "tech_size", "source_status", "updated_at"])
    df = pd.DataFrame(rows)
    for column in ("nm_id", "chrt_id"):
        if column in df.columns:
            df[column] = pd.to_numeric(df[column], errors="coerce")
    return df


def render_not_applicable_kpi_card(*, label: str, reason: str = "Не применяется") -> None:
    st.markdown(
        build_chart_kpi_card_html(
            label=label,
            value_text="—",
            caption_text=reason,
            background="#f8fafc",
            border="#dbe4ee",
            value_color="#94a3b8",
            caption_color="#64748b",
        ),
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


def build_ad_carts_chart_series_map(*, is_conversion_level: bool) -> dict[str, str]:
    if is_conversion_level:
        return {"ad_atbs_total_confirmed": "Корзины РК"}
    return {
        "cart_count": "Итоговые корзины",
        "ad_atbs_total_confirmed": "Корзины РК",
    }


def build_ad_cart_cost_chart_series_map(*, is_conversion_level: bool) -> dict[str, str]:
    if is_conversion_level:
        return {"ad_cart_cost": "Стоимость корзины РК"}
    return {
        "total_cart_cost": "Стоимость корзины ИТОГО",
        "ad_cart_cost": "Стоимость корзины РК",
    }


def render_efficiency_charts(
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
            safe_st_dataframe(
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
            safe_st_dataframe(
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
    cache_buster = resolve_db_dataset_cache_buster()
    try:
        raw_manual_ads_df = load_ivan_ads_wide_day_from_db(cache_buster)
        manual_reference_counts = load_ivan_ads_wide_reference_counts_from_db(cache_buster)
    except Exception:
        logger.exception("Не удалось загрузить ручную рекламу Ивана для графиков")
        raw_manual_ads_df = pd.DataFrame()
        manual_reference_counts = {
            "matched_dim_product_rows": 0,
            "matched_active_product_rows": 0,
        }

    selected_period_dates = pd.to_datetime(filtered.get("report_date", pd.Series(dtype=object)), errors="coerce").dropna().dt.date
    selected_period_start = selected_period_dates.min() if not selected_period_dates.empty else None
    selected_period_end = selected_period_dates.max() if not selected_period_dates.empty else None
    manual_period_dates = (
        pd.to_datetime(raw_manual_ads_df.get("date", pd.Series(dtype=object)), errors="coerce").dropna().dt.date
        if not raw_manual_ads_df.empty
        else pd.Series(dtype=object)
    )
    manual_period_start = manual_period_dates.min() if not manual_period_dates.empty else None
    manual_period_end = manual_period_dates.max() if not manual_period_dates.empty else None
    manual_ads_chart_df = aggregate_ivan_manual_ads_for_charts(
        raw_manual_ads_df,
        date_from=selected_period_start,
        date_to=selected_period_end,
    )
    total_manual_spend = None
    if not raw_manual_ads_df.empty and "ad_spend" in raw_manual_ads_df.columns:
        total_manual_spend = pd.to_numeric(raw_manual_ads_df["ad_spend"], errors="coerce").sum(min_count=1)
        if not pd.isna(total_manual_spend):
            total_manual_spend = float(total_manual_spend)
        else:
            total_manual_spend = None
    scope_rows, manual_ads_summary = merge_ivan_manual_ads_into_chart_scope(
        scope_rows,
        manual_ads_chart_df,
        aggregation_level=aggregation_level,
        period_start=selected_period_start,
        period_end=selected_period_end,
        total_manual_rows=len(raw_manual_ads_df),
        total_manual_products=int(raw_manual_ads_df["nm_id"].nunique()) if not raw_manual_ads_df.empty and "nm_id" in raw_manual_ads_df.columns else 0,
        total_manual_spend=total_manual_spend,
        manual_period_start=manual_period_start,
        manual_period_end=manual_period_end,
        matched_dim_product_rows=int(manual_reference_counts.get("matched_dim_product_rows", 0)),
        matched_active_product_rows=int(manual_reference_counts.get("matched_active_product_rows", 0)),
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
    st.caption(
        format_ad_kpi_period_caption(
            period_summary.get("ad_kpi_period_start"),
            period_summary.get("ad_kpi_period_end"),
        )
    )

    if period_summary["has_lagged_ad_attribution"]:
        st.caption("Статус рекламной атрибуции: AD_ATTRIBUTION_LAGGED")
    elif period_summary["has_partial_ad_attribution"]:
        st.caption("Статус рекламной атрибуции: AD_DATA_PARTIAL")

    show_milestones = True
    milestones_list = []
    if aggregation_level == CHART_LEVEL_CABINET:
        show_milestones = st.toggle("Показывать вехи", value=True, key="toggle_show_milestones")
        if show_milestones and "report_date" in chart_df.columns and not chart_df["report_date"].dropna().empty:
            min_date = chart_df["report_date"].dropna().min()
            max_date = chart_df["report_date"].dropna().max()
            try:
                milestones_list = list_milestones(date_from=min_date, date_to=max_date, include_inactive=False)
            except Exception:
                logger.exception("Не удалось загрузить вехи кабинета для графика")
                milestones_list = []

    st.markdown("### Динамика корзин")
    st.caption(
        "Итоговые корзины и корзины из рекламы по дням."
        if not is_conversion_level
        else "Корзины РК по выбранному типу WB / конверсии."
    )
    carts_chart = build_user_friendly_chart(
        chart_df=chart_df,
        series_map=build_ad_carts_chart_series_map(is_conversion_level=is_conversion_level),
        y_title="Корзины, шт.",
        tooltip_value_title="Значение, шт.",
        value_format=".0f",
        line_colors=["#2563eb", "#f97316"],
    )
    if carts_chart is None:
        st.info("Нет данных за выбранный период.")
    else:
        if aggregation_level == CHART_LEVEL_CABINET and show_milestones and milestones_list:
            m_layer = build_milestones_altair_layer(milestones_list)
            if m_layer is not None:
                carts_chart = alt.layer(carts_chart, m_layer).resolve_scale(color="independent")
        st.altair_chart(carts_chart, width="stretch")

    if aggregation_level == CHART_LEVEL_CABINET:
        render_milestones_management_block(chart_df)

    st.markdown("### Стоимость корзины")
    st.caption(
        "Сколько рублей рекламного расхода приходится на одну корзину."
        if not is_conversion_level
        else "Сколько рублей рекламного расхода приходится на одну рекламную корзину."
    )
    cart_cost_chart = build_user_friendly_chart(
        chart_df=chart_df,
        series_map=build_ad_cart_cost_chart_series_map(is_conversion_level=is_conversion_level),
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
        safe_st_dataframe(
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


@st.cache_data(show_spinner=False)
def load_stock_warehouse_snapshot_range_from_db(
    date_from: date,
    date_to: date,
    cache_buster: str | None = None,
) -> pd.DataFrame:
    with session_scope() as session:
        rows = session.execute(
            select(FactStockWarehouseSnapshot)
            .where(
                FactStockWarehouseSnapshot.snapshot_date >= date_from,
                FactStockWarehouseSnapshot.snapshot_date <= date_to
            )
        ).scalars().all()
        if not rows:
            return pd.DataFrame(columns=["snapshot_date", "nm_id", "stock_qty"])
        materialized_rows = [
            {
                "snapshot_date": row.snapshot_date,
                "nm_id": row.nm_id,
                "stock_qty": row.stock_qty,
            }
            for row in rows
        ]
        df = pd.DataFrame(materialized_rows)
        df["nm_id"] = pd.to_numeric(df["nm_id"], errors="coerce")
        df["stock_qty"] = pd.to_numeric(df["stock_qty"], errors="coerce")
        return df


@st.cache_data(show_spinner=False)
def load_ivan_stock_range_from_db(
    date_from: date,
    date_to: date,
    cache_buster: str | None = None,
) -> pd.DataFrame:
    with session_scope() as session:
        stmt = select(
            FactIvanStockSheetDay.stock_date,
            FactIvanStockSheetDay.nm_id,
            FactIvanStockSheetDay.quantity
        ).where(
            FactIvanStockSheetDay.stock_date <= date_to
        )
        results = session.execute(stmt).all()
        if not results:
            return pd.DataFrame(columns=["snapshot_date", "nm_id", "one_c_stock_qty"])
        df = pd.DataFrame([
            {
                "snapshot_date": r.stock_date,
                "nm_id": r.nm_id,
                "one_c_stock_qty": r.quantity
            }
            for r in results
        ])
        df["nm_id"] = pd.to_numeric(df["nm_id"], errors="coerce")
        df["one_c_stock_qty"] = _clip_non_negative_numeric_series(df["one_c_stock_qty"])
        df["snapshot_date"] = pd.to_datetime(df["snapshot_date"], errors="coerce").dt.date
        df = (
            df.dropna(subset=["snapshot_date", "nm_id"])
            .groupby(["snapshot_date", "nm_id"], as_index=False)["one_c_stock_qty"]
            .sum(min_count=1)
        )
        df["nm_id"] = pd.to_numeric(df["nm_id"], errors="coerce")
        df = df.dropna(subset=["nm_id"]).copy()
        if df.empty:
            return pd.DataFrame(columns=["snapshot_date", "nm_id", "one_c_stock_qty"])
        df["nm_id"] = df["nm_id"].astype("int64")
        df = (
            df.sort_values(["nm_id", "snapshot_date"])
            .drop_duplicates(subset=["nm_id", "snapshot_date"], keep="last")
            .reset_index(drop=True)
        )
        target_nm_ids = sorted(df["nm_id"].dropna().astype(int).unique().tolist())
        if not target_nm_ids:
            return pd.DataFrame(columns=["snapshot_date", "nm_id", "one_c_stock_qty"])
        date_grid = pd.MultiIndex.from_product(
            [target_nm_ids, pd.date_range(start=date_from, end=date_to).date],
            names=["nm_id", "snapshot_date"],
        ).to_frame(index=False)
        date_grid["nm_id"] = pd.to_numeric(date_grid["nm_id"], errors="coerce").astype("int64")
        date_grid["snapshot_date"] = pd.to_datetime(date_grid["snapshot_date"])
        df["snapshot_date"] = pd.to_datetime(df["snapshot_date"])
        materialized = pd.merge_asof(
            date_grid.sort_values(["snapshot_date", "nm_id"]),
            df.sort_values(["snapshot_date", "nm_id"]),
            on="snapshot_date",
            by="nm_id",
            direction="backward",
        )
        materialized["snapshot_date"] = pd.to_datetime(materialized["snapshot_date"], errors="coerce").dt.date
        materialized["one_c_stock_qty"] = _clip_non_negative_numeric_series(materialized["one_c_stock_qty"])
        materialized = materialized.dropna(subset=["snapshot_date", "nm_id", "one_c_stock_qty"]).copy()
        materialized["nm_id"] = materialized["nm_id"].astype("int64")
        return materialized.reset_index(drop=True)


@st.cache_data(show_spinner=False)
def load_funnel_sales_range_from_db(
    date_from: date,
    date_to: date,
    cache_buster: str | None = None,
) -> pd.DataFrame:
    with session_scope() as session:
        stmt = select(
            FactFunnelDay.nm_id,
            FactFunnelDay.date,
            FactFunnelDay.order_count
        ).where(
            FactFunnelDay.date >= date_from,
            FactFunnelDay.date <= date_to
        )
        results = session.execute(stmt).all()
        if not results:
            return pd.DataFrame(columns=["nm_id", "date", "order_count"])
        df = pd.DataFrame([
            {
                "nm_id": r.nm_id,
                "date": r.date,
                "order_count": r.order_count
            }
            for r in results
        ])
        df["nm_id"] = pd.to_numeric(df["nm_id"], errors="coerce")
        df["order_count"] = pd.to_numeric(df["order_count"], errors="coerce")
        return df


def prepare_stock_speed_charts_dataframe(
    snapshot_df: pd.DataFrame,
    one_c_df: pd.DataFrame,
    sales_df: pd.DataFrame,
    settings_qg_df: pd.DataFrame,
    min_date: date,
    max_date: date,
) -> pd.DataFrame:
    if snapshot_df.empty:
        wb_daily = pd.DataFrame(columns=["date", "nm_id", "wb_stock_qty"])
    else:
        wb_daily = snapshot_df.groupby(["snapshot_date", "nm_id"], as_index=False)["stock_qty"].sum(min_count=1)
        wb_daily = wb_daily.rename(columns={"snapshot_date": "date", "stock_qty": "wb_stock_qty"})

    if one_c_df.empty:
        one_c_daily = pd.DataFrame(columns=["date", "nm_id", "one_c_stock_qty"])
    else:
        one_c_daily = one_c_df.rename(columns={"snapshot_date": "date"}).copy()

    # Приводим к типу date
    if not wb_daily.empty:
        wb_daily["date"] = pd.to_datetime(wb_daily["date"]).dt.date
        wb_daily["nm_id"] = pd.to_numeric(wb_daily["nm_id"], errors="coerce")
        wb_daily = wb_daily.dropna(subset=["nm_id"]).copy()
        wb_daily["nm_id"] = wb_daily["nm_id"].astype("int64")
    if not one_c_daily.empty:
        one_c_daily["date"] = pd.to_datetime(one_c_daily["date"]).dt.date
        one_c_daily["nm_id"] = pd.to_numeric(one_c_daily["nm_id"], errors="coerce")
        one_c_daily = one_c_daily.dropna(subset=["nm_id"]).copy()
        one_c_daily["nm_id"] = one_c_daily["nm_id"].astype("int64")
        one_c_daily["one_c_stock_qty"] = _clip_non_negative_numeric_series(one_c_daily["one_c_stock_qty"])
        one_c_daily = one_c_daily.dropna(subset=["one_c_stock_qty"]).copy()
        one_c_daily = (
            one_c_daily.sort_values(["nm_id", "date"])
            .drop_duplicates(subset=["nm_id", "date"], keep="last")
            .reset_index(drop=True)
        )
        target_nm_ids = sorted(
            {
                *pd.to_numeric(wb_daily.get("nm_id"), errors="coerce").dropna().astype(int).tolist(),
                *pd.to_numeric(one_c_daily.get("nm_id"), errors="coerce").dropna().astype(int).tolist(),
            }
        )
        if target_nm_ids:
            one_c_grid = pd.MultiIndex.from_product(
                [target_nm_ids, pd.date_range(start=min_date, end=max_date).date],
                names=["nm_id", "date"],
            ).to_frame(index=False)
            one_c_grid["nm_id"] = pd.to_numeric(one_c_grid["nm_id"], errors="coerce").astype("int64")
            one_c_grid["date"] = pd.to_datetime(one_c_grid["date"])
            one_c_daily["date"] = pd.to_datetime(one_c_daily["date"])
            one_c_daily = pd.merge_asof(
                one_c_grid.sort_values(["date", "nm_id"]),
                one_c_daily.sort_values(["date", "nm_id"]),
                on="date",
                by="nm_id",
                direction="backward",
            )
            one_c_daily["date"] = pd.to_datetime(one_c_daily["date"]).dt.date

    stocks_daily = pd.merge(wb_daily, one_c_daily, on=["date", "nm_id"], how="outer")
    wb_qty = pd.to_numeric(stocks_daily["wb_stock_qty"], errors="coerce")
    one_c_qty = _clip_non_negative_numeric_series(stocks_daily["one_c_stock_qty"])
    stocks_daily["one_c_stock_qty"] = one_c_qty
    stocks_daily["total_stock"] = wb_qty.fillna(0) + one_c_qty.fillna(0)
    stocks_daily["total_stock"] = stocks_daily["total_stock"].where(wb_qty.notna() | one_c_qty.notna(), pd.NA)

    if sales_df.empty:
        merged = stocks_daily.copy()
        merged["sales_speed_y2"] = pd.NA
        merged["sales_speed_7d"] = pd.NA
    else:
        all_nm_ids = sales_df["nm_id"].unique()
        date_range_idx = pd.date_range(start=min_date - timedelta(days=7), end=max_date)
        grid = pd.MultiIndex.from_product([all_nm_ids, date_range_idx.date], names=["nm_id", "date"]).to_frame().reset_index(drop=True)

        sales_df_clean = sales_df.copy()
        sales_df_clean["nm_id"] = pd.to_numeric(sales_df_clean["nm_id"], errors="coerce")
        sales_df_clean = sales_df_clean.dropna(subset=["nm_id"])
        sales_df_clean["nm_id"] = sales_df_clean["nm_id"].astype(int)

        grid = grid.merge(sales_df_clean, on=["nm_id", "date"], how="left")
        grid = grid.sort_values(["nm_id", "date"]).reset_index(drop=True)

        grid["order_count_filled"] = pd.to_numeric(grid["order_count"], errors="coerce").fillna(0)
        grid["has_data"] = grid["order_count"].notna().astype(int)

        groupby_obj = grid.groupby("nm_id")
        grid["sales_speed_y2"] = groupby_obj["order_count"].shift(2)

        grid["sum_7d"] = groupby_obj["order_count_filled"].shift(1).groupby(grid["nm_id"]).rolling(7, min_periods=1).sum().reset_index(level=0, drop=True)
        grid["count_7d"] = groupby_obj["has_data"].shift(1).groupby(grid["nm_id"]).rolling(7, min_periods=1).sum().reset_index(level=0, drop=True)

        grid["sales_speed_7d"] = grid["sum_7d"] / 7.0
        grid["sales_speed_7d"] = grid["sales_speed_7d"].where(grid["count_7d"] > 0, pd.NA)

        # Мержим остатки с сеткой скоростей
        stocks_daily["date"] = pd.to_datetime(stocks_daily["date"]).dt.date
        grid["date"] = pd.to_datetime(grid["date"]).dt.date
        merged = pd.merge(stocks_daily, grid[["nm_id", "date", "sales_speed_y2", "sales_speed_7d"]], on=["nm_id", "date"], how="left")

    merged = merged[(merged["date"] >= min_date) & (merged["date"] <= max_date)]

    # Привязываем query_group / band
    if not settings_qg_df.empty:
        s = settings_qg_df.copy()
        s["nm_id"] = pd.to_numeric(s["nm_id"], errors="coerce")
        s = s.dropna(subset=["nm_id"])
        s["nm_id"] = s["nm_id"].astype(int)
        keep = ["nm_id"]
        if "query_group" in s.columns:
            keep.append("query_group")
        if "supplier_article" in s.columns:
            keep.append("supplier_article")
        if "title" in s.columns:
            keep.append("title")
        s = s[keep].drop_duplicates(subset=["nm_id"])
        merged = merged.merge(s, on="nm_id", how="left")
    else:
        merged["query_group"] = pd.NA
        merged["supplier_article"] = pd.NA
        merged["title"] = pd.NA

    merged["query_group"] = merged["query_group"].map(normalize_query_group_value)
    merged["band_name"] = merged["query_group"].map(build_stock_all_band_name)
    return merged


def aggregate_stock_charts_by_article(df_all: pd.DataFrame, speed_col: str, selected_label: str) -> pd.DataFrame:
    df = df_all.copy()
    df["display_label"] = (
        df["supplier_article"].fillna("").astype(str) + " | " + 
        df["nm_id"].astype(str) + " | " + 
        df["title"].fillna("").astype(str)
    )
    df_chart = df[df["display_label"] == selected_label].copy()
    if df_chart.empty:
        return pd.DataFrame(columns=["date", "sales_speed", "forecast_months", "band_name"])

    stock = pd.to_numeric(df_chart["total_stock"], errors="coerce")
    speed = pd.to_numeric(df_chart[speed_col], errors="coerce")

    forecast_days = stock / speed
    df_chart["forecast_months"] = forecast_days / 30.0
    df_chart["forecast_months"] = df_chart["forecast_months"].where(
        (speed > 0) & speed.notna() & stock.notna(), pd.NA
    )
    df_chart["sales_speed"] = speed
    df_chart["band_name"] = "Товар"
    return df_chart


def aggregate_stock_charts_by_band(df_all: pd.DataFrame, speed_col: str) -> pd.DataFrame:
    df = df_all.copy()
    df["sales_speed_item"] = pd.to_numeric(df[speed_col], errors="coerce")
    df["total_stock_item"] = pd.to_numeric(df["total_stock"], errors="coerce")

    agg_df = df.groupby(["date", "band_name"], as_index=False).agg({
        "sales_speed_item": lambda s: s.sum(min_count=1),
        "total_stock_item": lambda s: s.sum(min_count=1),
    })

    speed = agg_df["sales_speed_item"]
    stock = agg_df["total_stock_item"]

    forecast_days = stock / speed
    agg_df["forecast_months"] = forecast_days / 30.0
    agg_df["forecast_months"] = agg_df["forecast_months"].where(
        (speed > 0) & speed.notna() & stock.notna(), pd.NA
    )
    agg_df["sales_speed"] = speed
    return agg_df


def aggregate_stock_charts_by_cabinet(df_all: pd.DataFrame, speed_col: str) -> pd.DataFrame:
    df = df_all.copy()
    df["sales_speed_item"] = pd.to_numeric(df[speed_col], errors="coerce")
    df["total_stock_item"] = pd.to_numeric(df["total_stock"], errors="coerce")

    agg_df = df.groupby(["date"], as_index=False).agg({
        "sales_speed_item": lambda s: s.sum(min_count=1),
        "total_stock_item": lambda s: s.sum(min_count=1),
    })

    speed = agg_df["sales_speed_item"]
    stock = agg_df["total_stock_item"]

    forecast_days = stock / speed
    agg_df["forecast_months"] = forecast_days / 30.0
    agg_df["forecast_months"] = agg_df["forecast_months"].where(
        (speed > 0) & speed.notna() & stock.notna(), pd.NA
    )
    agg_df["sales_speed"] = speed
    agg_df["band_name"] = "Кабинет"
    return agg_df


def build_stock_speed_chart_altair(
    *,
    chart_df: pd.DataFrame,
    value_column: str,
    y_title: str,
    tooltip_value_title: str,
    value_format: str,
    color_column: str | None = None,
    thresholds: list[float] | None = None,
) -> alt.Chart | None:
    if chart_df.empty:
        return None

    df_plot = chart_df.copy()
    df_plot["report_date"] = pd.to_datetime(df_plot["date"])
    df_plot = df_plot.dropna(subset=[value_column])
    if df_plot.empty:
        return None

    unique_dates_count = len(df_plot["report_date"].unique())

    x_encode = alt.X(
        "report_date:T",
        title="Дата",
        axis=alt.Axis(format="%d.%m", labelAngle=0, tickCount=min(max(unique_dates_count, 2), 10)),
    )
    y_encode = alt.Y(
        f"{value_column}:Q",
        title=y_title,
        axis=alt.Axis(format=value_format),
        scale=alt.Scale(zero=True, nice=True),
    )

    tooltip_list = [
        alt.Tooltip("report_date:T", title="Дата", format="%d.%m.%Y"),
        alt.Tooltip(f"{value_column}:Q", title=tooltip_value_title, format=value_format),
    ]

    if color_column:
        color_encode = alt.Color(f"{color_column}:N", title="Банда")
        tooltip_list.insert(1, alt.Tooltip(f"{color_column}:N", title="Банда"))
        base = alt.Chart(df_plot).encode(x=x_encode, y=y_encode, color=color_encode, tooltip=tooltip_list)
    else:
        base = alt.Chart(df_plot).encode(x=x_encode, y=y_encode, tooltip=tooltip_list)

    layers: list[alt.Chart] = [
        base.mark_line(strokeWidth=3),
        base.mark_circle(size=55),
    ]

    if thresholds:
        for val in thresholds:
            rule_df = pd.DataFrame({"threshold": [val], "label": [f"{val} мес."]})
            layers.append(
                alt.Chart(rule_df).mark_rule(color="#10b981", strokeDash=[6, 4], strokeWidth=1.5).encode(y="threshold:Q")
            )
            layers.append(
                alt.Chart(rule_df)
                .mark_text(color="#10b981", align="left", dx=8, dy=-6, fontSize=11)
                .encode(x=alt.value(8), y="threshold:Q", text="label:N")
            )

    return alt.layer(*layers).resolve_scale(color="shared").properties(height=320)


def render_stock_speed_charts(filtered: pd.DataFrame, preselected_product_label: str | None) -> None:
    st.subheader("Остатки и скорость заказов")

    unique_dates = sorted(d for d in filtered["report_date"].dropna().unique().tolist())
    if not unique_dates:
        st.warning("В выбранном периоде нет данных.")
        return

    min_date = unique_dates[0]
    max_date = unique_dates[-1]

    # Селекторы
    grouping = st.radio("Группировка", options=["По артикулам", "По бандам", "За кабинет"], horizontal=True, key="stock_charts_grouping")
    speed_method = st.radio("Метод скорости", options=["Позавчера", "Прошедшая неделя"], horizontal=True, key="stock_charts_speed_method")

    # Загрузка
    snapshot_df = load_stock_warehouse_snapshot_range_from_db(
        min_date,
        max_date,
        cache_buster=resolve_db_dataset_cache_buster(),
    )
    one_c_df = load_ivan_stock_range_from_db(
        min_date,
        max_date,
        cache_buster=resolve_db_dataset_cache_buster(),
    )
    sales_df = load_funnel_sales_range_from_db(
        min_date - timedelta(days=7),
        max_date - timedelta(days=1),
        cache_buster=resolve_db_dataset_cache_buster(),
    )
    settings_qg_df = load_settings_product_query_groups_from_db(resolve_db_dataset_cache_buster())

    if snapshot_df.empty and one_c_df.empty:
        st.info("Нет данных об остатках за выбранный период.")
        return

    df_all = prepare_stock_speed_charts_dataframe(
        snapshot_df=snapshot_df,
        one_c_df=one_c_df,
        sales_df=sales_df,
        settings_qg_df=settings_qg_df,
        min_date=min_date,
        max_date=max_date
    )

    if df_all.empty:
        st.info("Нет данных для построения графиков.")
        return

    speed_col = "sales_speed_y2" if speed_method == "Позавчера" else "sales_speed_7d"

    if grouping == "По артикулам":
        df_all["display_label"] = (
            df_all["supplier_article"].fillna("").astype(str) + " | " + 
            df_all["nm_id"].astype(str) + " | " + 
            df_all["title"].fillna("").astype(str)
        )
        options = sorted(df_all["display_label"].dropna().unique().tolist())
        if not options:
            st.info("Нет доступных артикулов.")
            return

        default_idx = 0
        if preselected_product_label:
            for idx, opt in enumerate(options):
                if preselected_product_label in opt:
                    default_idx = idx
                    break

        selected_label = st.selectbox("Артикул", options=options, index=default_idx, key="stock_charts_article_select")
        df_chart = aggregate_stock_charts_by_article(df_all, speed_col, selected_label)
        color_col = None
    elif grouping == "По бандам":
        df_chart = aggregate_stock_charts_by_band(df_all, speed_col)
        color_col = "band_name"
    else:
        df_chart = aggregate_stock_charts_by_cabinet(df_all, speed_col)
        color_col = None

    # Графики
    st.markdown("### Скорость заказов")
    speed_chart = build_stock_speed_chart_altair(
        chart_df=df_chart,
        value_column="sales_speed",
        y_title="Скорость заказов, шт/день",
        tooltip_value_title="Скорость заказов",
        value_format=".1f",
        color_column=color_col,
    )
    if speed_chart:
        st.altair_chart(speed_chart, width="stretch")
    else:
        st.info("Нет данных для построения графика скорости продаж.")

    st.markdown("### Прогноз остатков")
    forecast_chart = build_stock_speed_chart_altair(
        chart_df=df_chart,
        value_column="forecast_months",
        y_title="Прогноз остатков, мес.",
        tooltip_value_title="Прогноз",
        value_format=".1f",
        color_column=color_col,
        thresholds=[3.5, 4.5]
    )
    if forecast_chart:
        st.altair_chart(forecast_chart, width="stretch")
    else:
        st.info("Нет данных для построения графика прогноза остатков.")


def render_charts_tab(
    filtered: pd.DataFrame,
    preselected_product_label: str | None,
    option_map: dict[str, dict[str, object]],
    ad_campaign_product_df: pd.DataFrame | None = None,
) -> None:
    tab_eff, tab_vbro, tab_stock, tab_entry = st.tabs(
        ["Эффективность рекламы", "VVBromo", "Остатки и скорость продаж", "Точки входа"]
    )
    with tab_eff:
        render_efficiency_charts(
            filtered=filtered,
            preselected_product_label=preselected_product_label,
            option_map=option_map,
            ad_campaign_product_df=ad_campaign_product_df,
        )
    with tab_vbro:
        render_vvbromo_charts(filtered)
    with tab_stock:
        render_stock_speed_charts(filtered, preselected_product_label)
    with tab_entry:
        render_entry_point_charts(filtered, preselected_product_label)


def render_entry_point_charts(
    filtered: pd.DataFrame,
    preselected_product_label: str | None,
) -> None:
    st.subheader("Точки входа")

    selected_dates = sorted(d for d in filtered.get("report_date", pd.Series(dtype=object)).dropna().unique().tolist())
    selected_nm_ids = sorted(
        pd.to_numeric(filtered.get("nm_id", pd.Series(dtype=object)), errors="coerce")
        .dropna()
        .astype(int)
        .unique()
        .tolist()
    )
    if not selected_dates or not selected_nm_ids:
        st.info("Нет выбранных дат или товаров для графиков точки входа.")
        return

    selector_columns = st.columns(2)
    analysis_level = selector_columns[0].radio(
        "Уровень анализа",
        options=[ENTRY_POINT_LEVEL_CABINET, ENTRY_POINT_LEVEL_BAND, ENTRY_POINT_LEVEL_ARTICLE],
        horizontal=True,
        key="entry_point_chart_analysis_level",
    )
    detail_level = selector_columns[1].radio(
        "Детализация",
        options=[ENTRY_POINT_DETAIL_COARSE, ENTRY_POINT_DETAIL_DETAILED],
        horizontal=True,
        key="entry_point_chart_detail_level",
    )

    cache_buster = resolve_db_dataset_cache_buster()
    entry_df = load_entry_point_day_range_from_db(tuple(selected_dates), tuple(selected_nm_ids), cache_buster=cache_buster)
    if entry_df.empty:
        st.info("В выбранном периоде нет данных из fact_entry_point_day для графиков.")
        return

    metadata_df = build_entry_point_metadata(filtered)
    spend_df = None
    if detail_level == ENTRY_POINT_DETAIL_COARSE:
        spend_df = load_entry_point_spend_range_from_db(tuple(selected_dates), tuple(selected_nm_ids), cache_buster=cache_buster)
    display_df = build_entry_point_analytics_table(
        entry_df,
        metadata_df,
        analysis_level=analysis_level,
        detail_level=detail_level,
        spend_df=spend_df,
    )
    if display_df.empty:
        st.info("После агрегации данных для графиков точки входа не осталось строк.")
        return

    selected_article_label: str | None = preselected_product_label
    selected_band: str | None = None

    if analysis_level == ENTRY_POINT_LEVEL_ARTICLE:
        article_filtered = filtered.copy()
        if "nm_id" in article_filtered.columns:
            article_filtered["nm_id"] = pd.to_numeric(article_filtered["nm_id"], errors="coerce")
            article_filtered = article_filtered[article_filtered["nm_id"].isin(selected_nm_ids)].copy()
        article_options, _ = get_product_options(article_filtered)
        if preselected_product_label not in article_options:
            selected_article_label = None

    if analysis_level == ENTRY_POINT_LEVEL_BAND and detail_level == ENTRY_POINT_DETAIL_DETAILED:
        band_options = ["Все банды"]
        if "band_name" in metadata_df.columns:
            band_values = sorted(
                value
                for value in metadata_df["band_name"].dropna().astype(str).unique().tolist()
                if value.strip()
            )
            band_options.extend(band_values)
        selected_band = st.selectbox(
            "Банда для графиков",
            options=band_options,
            key="entry_point_chart_band_filter",
        )

    display_df, limit_context = limit_entry_point_analytics_table(
        display_df,
        analysis_level=analysis_level,
        detail_level=detail_level,
        selected_article_label=selected_article_label,
        selected_band=selected_band,
    )
    if display_df.empty:
        st.info("После применения ограничений для выбранного режима не осталось строк для графиков.")
        return
    if limit_context.get("message"):
        st.caption(str(limit_context["message"]))

    traffic_chart_df = build_entry_point_chart_dataframe(
        display_df,
        analysis_level=analysis_level,
        detail_level=detail_level,
    )
    economics_chart_df = build_entry_point_economics_chart_dataframe(
        display_df,
        analysis_level=analysis_level,
        detail_level=detail_level,
    )
    if traffic_chart_df.empty and economics_chart_df.empty:
        st.info("После подготовки данных графики точки входа не построены: нет отображаемых рядов.")
        return

    traffic_tab, economics_tab = st.tabs([ENTRY_POINT_LABEL_TRAFFIC_TAB, ENTRY_POINT_ECONOMICS_TAB_LABEL])
    with traffic_tab:
        st.markdown("### Добавления в корзину по дням")
        cart_series_name_labels = build_entry_point_period_cpo_series_labels(
            display_df,
            analysis_level=analysis_level,
            detail_level=detail_level,
        )
        cart_chart_df = traffic_chart_df.copy()
        if cart_series_name_labels:
            cart_chart_df["series_name"] = cart_chart_df["series_name"].map(cart_series_name_labels).fillna(cart_chart_df["series_name"])
        cart_chart = build_entry_point_line_chart(
            chart_df=cart_chart_df,
            value_column="cart_count",
            y_title="Добавления в корзину",
            tooltip_value_title="Добавления в корзину",
            value_format=".0f",
        )
        if cart_chart is None:
            st.info("Нет данных для графика добавлений в корзину.")
        else:
            st.altair_chart(cart_chart, width="stretch")

        st.markdown("### Конверсия в корзину по дням")
        cart_conversion_chart = build_entry_point_line_chart(
            chart_df=traffic_chart_df,
            value_column="cart_conversion",
            y_title="Конверсия в корзину, %",
            tooltip_value_title="Конверсия в корзину",
            value_format=".2f",
        )
        if cart_conversion_chart is None:
            st.info("Нет данных для графика конверсии в корзину.")
        else:
            st.altair_chart(cart_conversion_chart, width="stretch")

        st.markdown("### Конверсия в заказ по дням")
        order_conversion_chart = build_entry_point_line_chart(
            chart_df=traffic_chart_df,
            value_column="order_conversion",
            y_title="Конверсия в заказ, %",
            tooltip_value_title="Конверсия в заказ",
            value_format=".2f",
            threshold=35.0,
            threshold_label="Порог 35%",
        )
        if order_conversion_chart is None:
            st.info("Нет данных для графика конверсии в заказ.")
        else:
            st.altair_chart(order_conversion_chart, width="stretch")

    with economics_tab:
        if detail_level != ENTRY_POINT_DETAIL_COARSE:
            st.info("Экономические графики доступны только в режиме Укрупнённо.")
            return
        if economics_chart_df.empty:
            st.info("После подготовки данных графики стоимости корзины и CPO не построены: нет отображаемых рядов.")
            return

        st.markdown("### Стоимость корзины РК по дням")
        cart_cost_chart = build_entry_point_line_chart(
            chart_df=economics_chart_df,
            value_column="estimated_cost_per_cart",
            y_title="Стоимость корзины РК, руб.",
            tooltip_value_title="Стоимость корзины РК, руб.",
            value_format=".2f",
            threshold=CHART_THRESHOLD_CART_COST,
            threshold_label="Порог 35 руб.",
        )
        if cart_cost_chart is None:
            st.info("Нет данных для графика стоимости корзины РК.")
        else:
            st.altair_chart(cart_cost_chart, width="stretch")

        st.markdown("### CPO РК по дням")
        cpo_chart = build_entry_point_line_chart(
            chart_df=economics_chart_df,
            value_column="estimated_cpo",
            y_title="CPO РК, руб.",
            tooltip_value_title="CPO РК, руб.",
            value_format=".2f",
            threshold=CHART_THRESHOLD_CPO,
            threshold_label="Порог 150 руб.",
        )
        if cpo_chart is None:
            st.info("Нет данных для графика CPO РК.")
        else:
            st.altair_chart(cpo_chart, width="stretch")


def build_vvbromo_chart(
    *,
    chart_df: pd.DataFrame,
    value_column: str,
    y_title: str,
    tooltip_value_title: str,
    value_format: str,
    threshold: float | None = None,
    threshold_label: str | None = None,
) -> alt.Chart | None:
    if chart_df.empty:
        return None

    unique_dates_count = len(chart_df["report_date"].unique())
    base = alt.Chart(chart_df).encode(
        x=alt.X(
            "report_date:T",
            title="Дата",
            axis=alt.Axis(format="%d.%m", labelAngle=0, tickCount=min(max(unique_dates_count, 2), 10)),
        ),
        y=alt.Y(
            f"{value_column}:Q",
            title=y_title,
            axis=alt.Axis(format=value_format),
            scale=alt.Scale(zero=True, nice=True),
        ),
        color=alt.Color(
            "band_name:N",
            title="Банда",
        ),
        tooltip=[
            alt.Tooltip("report_date:T", title="Дата", format="%d.%m.%Y"),
            alt.Tooltip("band_name:N", title="Банда"),
            alt.Tooltip(f"{value_column}:Q", title=tooltip_value_title, format=value_format),
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

    return alt.layer(*layers).resolve_scale(color="shared").properties(height=320)


def render_vvbromo_charts(filtered: pd.DataFrame) -> None:
    st.markdown("### VVBromo: опер. прибыль/ед., ₽")
    st.caption("Отношение операционной прибыли VVBromo к органическим продажам VVBromo по бандам.")

    df_bands = apply_product_bands(filtered)
    if "band_name" not in df_bands.columns or df_bands.dropna(subset=["band_name"]).empty:
        st.info("Нет товаров с привязкой к бандам за выбранный период.")
        return

    df_bands = df_bands.dropna(subset=["band_name"])

    # Агрегируем по датам и бандам
    agg_df = df_bands.groupby(["report_date", "band_name"], as_index=False).agg({
        "vvbromo_operating_profit": lambda x: x.sum(min_count=1),
        "vvbromo_organic_sales": lambda x: x.sum(min_count=1),
    })

    # Расчет операционной прибыли на единицу
    def calc_profit_per_unit(row):
        profit = row.get("vvbromo_operating_profit")
        sales = row.get("vvbromo_organic_sales")
        if pd.isna(sales) or sales == 0:
            return None
        if pd.isna(profit):
            return None
        return float(profit) / float(sales)

    agg_df["profit_per_unit"] = agg_df.apply(calc_profit_per_unit, axis=1)

    # Первый график
    g1_data = agg_df.dropna(subset=["profit_per_unit"]).copy()
    g1_data["report_date"] = pd.to_datetime(g1_data["report_date"])
    g1_chart = build_vvbromo_chart(
        chart_df=g1_data,
        value_column="profit_per_unit",
        y_title="Опер. прибыль/ед., руб.",
        tooltip_value_title="Опер. прибыль/ед.",
        value_format=".2f",
        threshold=150.0,
        threshold_label="План 150 руб.",
    )
    if g1_chart is None:
        st.info("Нет данных для графика опер. прибыли/ед.")
    else:
        st.altair_chart(g1_chart, width="stretch")

    # Второй график
    st.markdown("### VVBromo: операционная прибыль, ₽")
    st.caption("Суммарная операционная прибыль VVBromo по бандам.")

    g2_data = agg_df.dropna(subset=["vvbromo_operating_profit"]).copy()
    g2_data["report_date"] = pd.to_datetime(g2_data["report_date"])
    g2_chart = build_vvbromo_chart(
        chart_df=g2_data,
        value_column="vvbromo_operating_profit",
        y_title="Операционная прибыль, руб.",
        tooltip_value_title="Операционная прибыль",
        value_format=".2f",
    )
    if g2_chart is None:
        st.info("Нет данных для графика операционной прибыли.")
    else:
        st.altair_chart(g2_chart, width="stretch")


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
    safe_st_dataframe(source_df, width="stretch", hide_index=True)


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


def build_upload_tab_sections() -> list[dict[str, object]]:
    return [
        {
            "title": "Загрузить Точка входа",
            "report_name": "Точка входа",
            "state_key": ENTRY_POINT_UPLOAD_KEY,
            "implemented": True,
            "importer_func": import_entry_points_xlsx,
        },
        {
            "title": "Загрузить География заказов",
            "report_name": "География заказов",
            "state_key": ORDERS_GEOGRAPHY_UPLOAD_KEY,
            "implemented": True,
            "importer_func": import_orders_geography_xlsx,
        },
        {
            "title": "Загрузить ВБро",
            "report_name": "ВБро",
            "state_key": VBRO_UPLOAD_KEY,
            "implemented": False,
            "accepted_extensions": ["xlsx", "xls", "csv"],
        },
    ]


def render_pending_import_block(
    *,
    title: str,
    report_name: str,
    state_key: str,
    accepted_extensions: list[str] | None = None,
) -> None:
    st.markdown(f"### {title}")
    suffixes = accepted_extensions or ["xlsx"]
    uploaded_file = st.file_uploader(
        f"{report_name}: {', '.join(ext.upper() for ext in suffixes)}",
        type=suffixes,
        key=f"{state_key}_file",
    )
    if uploaded_file is None:
        st.info("Формат файла ВБро пока не подключён. Можно выбрать файл позже, когда будет утверждена схема импорта.")
        return

    st.success(f"Файл выбран: {getattr(uploaded_file, 'name', 'upload')}")
    st.warning("Импорт ВБро пока не реализован: файл не записывается в БД и не участвует в пересборке витрин.")


def render_upload_tab() -> None:
    st.subheader(UPLOAD_TAB_TITLE)
    sections = build_upload_tab_sections()
    for index, section in enumerate(sections):
        if index > 0:
            st.divider()
        if bool(section.get("implemented")):
            render_import_block(
                title=str(section["title"]),
                report_name=str(section["report_name"]),
                importer_func=section["importer_func"],
                state_key=str(section["state_key"]),
            )
        else:
            render_pending_import_block(
                title=str(section["title"]),
                report_name=str(section["report_name"]),
                state_key=str(section["state_key"]),
                accepted_extensions=[str(ext) for ext in section.get("accepted_extensions", ["xlsx"])],
            )




def render_ad_campaign_product_tab(
    df: pd.DataFrame,
    data_source: str,
    error_text: str | None = None,
    *,
    selected_product_label: str | None = None,
    option_map: dict[str, dict[str, object]] | None = None,
    allowed_report_dates: list[date] | None = None,
) -> None:
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

    filtered = build_ad_campaign_product_scope_dataframe(
        df,
        selected_product_label=selected_product_label,
        option_map=option_map or {},
        allowed_report_dates=allowed_report_dates,
    )
    if filtered.empty:
        st.info("По выбранному товару и периоду строки РК не найдены.")
        return

    filter_cols_2 = st.columns(4)
    conversion_options = sorted(
        value for value in filtered["conversion_type"].dropna().astype(str).unique().tolist()
    )
    selected_conversions = filter_cols_2[0].multiselect("Тип конверсии", options=conversion_options)
    spend_only = filter_cols_2[1].checkbox("Только строки с расходом")
    atbs_only = filter_cols_2[2].checkbox("Только строки с корзинами")
    orders_only = filter_cols_2[3].checkbox("Только строки с заказами")

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

    report_dates = pd.to_datetime(filtered["report_date"], errors="coerce").dt.date.dropna()
    if report_dates.empty:
        xlsx_file_name = "ad_campaign_product_filtered.xlsx"
    else:
        xlsx_file_name = (
            f"ad_campaign_product_{report_dates.min().isoformat()}_{report_dates.max().isoformat()}.xlsx"
        )
    st.download_button(
        "Скачать XLSX",
        data=build_excel_export_bytes(download_df),
        file_name=xlsx_file_name,
        mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
        key="ad_campaign_product_xlsx_download",
    )

    safe_st_dataframe(
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


def render_ad_campaign_efficiency_tab() -> None:
    st.subheader(ad_campaign_efficiency.AD_CAMPAIGN_EFFICIENCY_LABEL)

    if not (os.getenv("DATABASE_URL") or settings.database_url):
        st.info("Экран эффективности рекламных кампаний доступен только при работе с БД.")
        return

    available_dates = ad_campaign_efficiency.load_ad_campaign_efficiency_available_dates()
    if not available_dates:
        st.info("Для экрана эффективности рекламных кампаний пока нет данных.")
        return

    latest_report_date = max(available_dates)
    filter_cols = st.columns(6)
    report_date_value = filter_cols[0].selectbox(
        "Дата среза",
        options=available_dates,
        index=available_dates.index(latest_report_date),
        format_func=lambda value: value.strftime("%d.%m.%Y"),
        key="ad_campaign_efficiency_report_date",
    )
    period_mode = filter_cols[1].selectbox(
        "Период сравнения",
        options=[
            ad_campaign_efficiency.AD_CAMPAIGN_PERIOD_DAILY,
            ad_campaign_efficiency.AD_CAMPAIGN_PERIOD_WEEKLY,
        ],
        key="ad_campaign_efficiency_period_mode",
    )
    level_filter = filter_cols[2].selectbox(
        "Уровень",
        options=[
            ad_campaign_efficiency.AD_CAMPAIGN_LEVEL_ALL,
            ad_campaign_efficiency.AD_CAMPAIGN_LEVEL_CAMPAIGNS,
            ad_campaign_efficiency.AD_CAMPAIGN_LEVEL_ARTICLES,
        ],
        key="ad_campaign_efficiency_level_filter",
    )
    metric_filter = filter_cols[3].selectbox(
        "Метрика",
        options=[
            ad_campaign_efficiency.AD_CAMPAIGN_METRIC_ALL,
            ad_campaign_efficiency.AD_CAMPAIGN_METRIC_IMPRESSIONS,
            ad_campaign_efficiency.AD_CAMPAIGN_METRIC_CARTS,
        ],
        key="ad_campaign_efficiency_metric_filter",
    )
    direction_filter = filter_cols[4].selectbox(
        "Направление",
        options=[
            ad_campaign_efficiency.AD_CAMPAIGN_DIRECTION_ALL,
            ad_campaign_efficiency.AD_CAMPAIGN_DIRECTION_GROWTH,
            ad_campaign_efficiency.AD_CAMPAIGN_DIRECTION_DECLINE,
        ],
        key="ad_campaign_efficiency_direction_filter",
    )
    threshold_pct = float(
        filter_cols[5].number_input(
            "Порог, %",
            min_value=0.0,
            value=float(ad_campaign_efficiency.AD_CAMPAIGN_EFFICIENCY_THRESHOLD_PCT),
            step=1.0,
            key="ad_campaign_efficiency_threshold_pct",
        )
    )
    only_notable = st.checkbox(
        "Только заметные отклонения",
        value=False,
        key="ad_campaign_efficiency_only_notable",
    )
    search_text = st.text_input("Поиск", key="ad_campaign_efficiency_search_text")

    window = ad_campaign_efficiency.resolve_ad_campaign_efficiency_window(report_date_value, period_mode)
    campaign_stats_df, article_stats_df, campaign_meta_df, product_df = ad_campaign_efficiency.load_ad_campaign_efficiency_scope_from_db(
        window["previous_start"],
        window["current_end"],
    )
    campaign_rows, article_rows, resolved_window = ad_campaign_efficiency.build_ad_campaign_efficiency_tables(
        campaign_stats_df,
        article_stats_df,
        campaign_meta_df,
        product_df,
        report_date_value=report_date_value,
        period_mode=period_mode,
        threshold_pct=threshold_pct,
    )
    summary = ad_campaign_efficiency.build_ad_campaign_efficiency_summary(campaign_rows, article_rows)

    metric_cols = st.columns(5)
    metric_cols[0].metric("Активных кампаний", f"{summary['active_campaigns']:,}".replace(",", " "))
    metric_cols[1].metric("Алерты по показам", f"{summary['campaign_impression_alerts']:,}".replace(",", " "))
    metric_cols[2].metric("Алерты по корзинам", f"{summary['campaign_cart_alerts']:,}".replace(",", " "))
    metric_cols[3].metric("Алерты по артикулам", f"{summary['article_alerts']:,}".replace(",", " "))
    metric_cols[4].metric("Падение в ноль / новая активность", f"{summary['drop_to_zero'] + summary['new_activity']:,}".replace(",", " "))
    st.caption(ad_campaign_efficiency.build_ad_campaign_efficiency_comparison_caption(report_date_value, period_mode))

    show_campaigns = level_filter in {
        ad_campaign_efficiency.AD_CAMPAIGN_LEVEL_ALL,
        ad_campaign_efficiency.AD_CAMPAIGN_LEVEL_CAMPAIGNS,
    }
    show_articles = level_filter in {
        ad_campaign_efficiency.AD_CAMPAIGN_LEVEL_ALL,
        ad_campaign_efficiency.AD_CAMPAIGN_LEVEL_ARTICLES,
    }

    if show_campaigns:
        st.markdown("#### Кампании")
        filtered_campaign_rows = ad_campaign_efficiency.filter_ad_campaign_efficiency_rows(
            campaign_rows,
            metric_filter=metric_filter,
            direction_filter=direction_filter,
            only_notable=only_notable,
            search_text=search_text,
        )
        if filtered_campaign_rows.empty:
            st.info("По текущим фильтрам кампании не найдены.")
        else:
            campaign_display_df = ad_campaign_efficiency.build_ad_campaign_efficiency_display_dataframe(
                filtered_campaign_rows,
                level=ad_campaign_efficiency.AD_CAMPAIGN_LEVEL_CAMPAIGNS,
            )
            campaign_download_cols = st.columns(2)
            campaign_download_cols[0].download_button(
                "Скачать CSV",
                data=campaign_display_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=ad_campaign_efficiency.build_ad_campaign_efficiency_export_filename(
                    "campaigns",
                    report_date_value,
                    period_mode,
                    "csv",
                ),
                mime="text/csv",
                key="ad_campaign_efficiency_campaigns_csv_download",
            )
            campaign_download_cols[1].download_button(
                "Скачать XLSX",
                data=build_excel_export_bytes(campaign_display_df),
                file_name=ad_campaign_efficiency.build_ad_campaign_efficiency_export_filename(
                    "campaigns",
                    report_date_value,
                    period_mode,
                    "xlsx",
                ),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="ad_campaign_efficiency_campaigns_xlsx_download",
            )
            safe_st_dataframe(
                ad_campaign_efficiency.style_ad_campaign_efficiency_display_table(
                    campaign_display_df,
                    filtered_campaign_rows,
                ),
                width="stretch",
                hide_index=True,
                force_object_strings=True,
            )

    if show_articles:
        st.markdown("#### Артикулы")
        filtered_article_rows = ad_campaign_efficiency.filter_ad_campaign_efficiency_rows(
            article_rows,
            metric_filter=metric_filter,
            direction_filter=direction_filter,
            only_notable=only_notable,
            search_text=search_text,
        )
        if filtered_article_rows.empty:
            st.info("По текущим фильтрам артикулами отклонения не найдены.")
        else:
            article_display_df = ad_campaign_efficiency.build_ad_campaign_efficiency_display_dataframe(
                filtered_article_rows,
                level=ad_campaign_efficiency.AD_CAMPAIGN_LEVEL_ARTICLES,
            )
            article_download_cols = st.columns(2)
            article_download_cols[0].download_button(
                "Скачать CSV",
                data=article_display_df.to_csv(index=False).encode("utf-8-sig"),
                file_name=ad_campaign_efficiency.build_ad_campaign_efficiency_export_filename(
                    "articles",
                    report_date_value,
                    period_mode,
                    "csv",
                ),
                mime="text/csv",
                key="ad_campaign_efficiency_articles_csv_download",
            )
            article_download_cols[1].download_button(
                "Скачать XLSX",
                data=build_excel_export_bytes(article_display_df),
                file_name=ad_campaign_efficiency.build_ad_campaign_efficiency_export_filename(
                    "articles",
                    report_date_value,
                    period_mode,
                    "xlsx",
                ),
                mime="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
                key="ad_campaign_efficiency_articles_xlsx_download",
            )
            safe_st_dataframe(
                ad_campaign_efficiency.style_ad_campaign_efficiency_display_table(
                    article_display_df,
                    filtered_article_rows,
                ),
                width="stretch",
                hide_index=True,
                force_object_strings=True,
            )


def main() -> None:
    st.set_page_config(page_title="MP Control Center", layout="wide")
    st.title("MP Control Center")
    st.caption("Остатки, реклама, цены, поставки и коммуникации")
    initialize_background_services()
    render_password_gate()
    if st.button("Обновить данные из источника", width="content"):
        clear_streamlit_data_caches()
        st.rerun()

    df, data_source = load_app_dataset()
    display_coverage = normalize_display_coverage_payload(df.attrs.get("display_coverage"))
    render_compact_metric_css()
    render_available_dates_summary(df)
    filtered, filter_debug_trace = build_filtered_dataset(df, data_source)

    metric_cols = st.columns(7)
    summary_cards = [
        ("Всего строк", f"{len(filtered):,}".replace(",", " ")),
        ("Товаров", f"{filtered['nm_id'].nunique():,}".replace(",", " ")),
        ("Дат", f"{filtered['report_date'].nunique():,}".replace(",", " ")),
        ("Строк без данных", f"{(filtered['data_quality_status'] == 'NO_DATA').sum():,}".replace(",", " ")),
        ("Строк с рекламой", f"{filtered['has_ad_campaign'].sum():,}".replace(",", " ")),
        ("Строк с поиском", f"{filtered['has_search'].sum():,}".replace(",", " ")),
        ("Строк с остатками", f"{filtered['has_stock'].sum():,}".replace(",", " ")),
    ]
    for column, (label, value) in zip(metric_cols, summary_cards):
        column.markdown(build_dashboard_summary_card_html(label, value), unsafe_allow_html=True)

    if filtered.empty:
        st.warning("После фильтров данных не осталось.")
        st.stop()

    main_labels = build_main_tab_labels()
    tab_labels = main_labels[:-1] + ["Коммуникации", main_labels[-1]]
    selected_main_section = st.radio(
        "Раздел",
        options=tab_labels,
        horizontal=True,
        key="main_section",
        label_visibility="collapsed",
    )

    selected_product_label: str | None = None
    option_map: dict[str, dict[str, object]] = {}
    product_rows = pd.DataFrame()
    default_detail_date: object = None
    ad_campaign_product_df = pd.DataFrame()
    ad_campaign_product_error: str | None = None

    needs_product_context = selected_main_section in {tab_labels[2], tab_labels[3], tab_labels[4]}
    needs_ad_campaign_dataset = selected_main_section in {tab_labels[2], tab_labels[4]}

    if needs_product_context:
        product_options, option_map = get_product_options(filtered)
        selected_product_label = st.selectbox("Выбрать товар", options=product_options)
        product_rows = get_selected_product_rows(filtered, selected_product_label, option_map)
        detail_dates = sorted(product_rows["report_date"].dropna().unique().tolist(), reverse=True)
        default_detail_date = detail_dates[0] if detail_dates else None

    if needs_ad_campaign_dataset:
        ad_campaign_product_df, ad_campaign_product_error = load_ad_campaign_product_app_dataset(data_source)

    if selected_main_section == tab_labels[0]:
        render_overview_tab(filtered, filter_debug_trace, display_coverage)
    elif selected_main_section == tab_labels[1]:
        render_entry_point_analytics_tab(filtered)
    elif selected_main_section == tab_labels[2]:
        ad_tab_product, ad_tab_efficiency = st.tabs(
            [
                AD_CAMPAIGN_PRODUCT_LABEL,
                ad_campaign_efficiency.AD_CAMPAIGN_EFFICIENCY_LABEL,
            ]
        )
        with ad_tab_product:
            render_ad_campaign_product_tab(
                ad_campaign_product_df,
                data_source,
                ad_campaign_product_error,
                selected_product_label=selected_product_label,
                option_map=option_map,
                allowed_report_dates=sorted(d for d in filtered["report_date"].dropna().unique().tolist()),
            )
        with ad_tab_efficiency:
            render_ad_campaign_efficiency_tab()
    elif selected_main_section == tab_labels[3]:
        render_product_tab(product_rows, default_detail_date)
    elif selected_main_section == tab_labels[4]:
        render_charts_tab(filtered, selected_product_label, option_map, ad_campaign_product_df)
    elif selected_main_section == tab_labels[5]:
        render_wb_site_price_tab(data_source)
    elif selected_main_section == tab_labels[6]:
        render_stock_warehouse_tab(data_source)
    elif selected_main_section == tab_labels[7]:
        render_communications_tab()
    else:
        render_upload_tab()


@st.cache_resource(show_spinner=False)
def initialize_background_services() -> bool:
    return start_daily_refresh_scheduler_once()


if __name__ == "__main__":
    main()
