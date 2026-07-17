from __future__ import annotations

from datetime import date, datetime, timedelta
from decimal import Decimal
from time import perf_counter
from typing import Any, Iterable
from zoneinfo import ZoneInfo

from sqlalchemy.orm import Session

from src.mcp_server.schemas import (
    WbDailyOperationalDiagnosticsResponse,
    WbDailyOperationalExcludedSectionResponse,
    WbDailyOperationalHighlightsResponse,
    WbDailyOperationalMetricRowResponse,
    WbDailyOperationalReportWindowResponse,
    WbDailyOperationalSectionResponse,
    WbDailyOperationalSignalResponse,
    WbDailyOperationalSourceFreshnessResponse,
    WbDailyOperationalSummaryRequest,
    WbDailyOperationalSummaryResponse,
    WbDailyOperationalTableResponse,
)
from src.mcp_server.wb_daily_operational_summary_analysis import build_highlights_from_analysis, build_internal_analysis
from src.mcp_server.wb_daily_operational_summary_context_sql import build_extended_context
from src.mcp_server.wb_daily_operational_summary_additional import (
    build_additional_data_candidates,
    fetch_competitor_block,
    fetch_database_audit_block,
    fetch_logistics_summary_block,
    fetch_operating_profit_block,
    fetch_pricing_spp_block,
)
from src.mcp_server.wb_daily_operational_summary_format import render_wb_daily_operational_summary_markdown
from src.mcp_server.wb_daily_operational_summary_rules import WbDailyOperationalSummaryRules, get_default_rules
from src.mcp_server.wb_daily_operational_summary_sql import (
    fetch_assortment_changes,
    fetch_core_source_freshness,
    fetch_mart_daily_overview,
    fetch_mart_window_overview,
    fetch_problem_campaigns,
    fetch_profit_overview,
    fetch_search_movers,
    fetch_stock_risks,
)


FORMULA_VERSION = "v1"
MOSCOW_TZ = ZoneInfo("Europe/Moscow")
SECTION_TITLES = {
    "overview": "Краткий итог дня",
    "traffic": "Трафик и видимость",
    "funnel": "Воронка и конверсия",
    "ads": "Рекламная эффективность",
    "sales": "Продажи и оборот",
    "stock": "Остатки и складские риски",
    "assortment": "Ассортимент: ТОП роста и падения",
    "search": "Поиск",
    "priority": "Приоритетные проверки",
    "scenario": "Сценарный итог",
    "profit": "Прибыль",
}


def _to_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _format_decimal(value: Any, decimals: int = 0) -> str:
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return "н/д"
    quant = Decimal("1") if decimals == 0 else Decimal("1." + ("0" * decimals))
    return f"{decimal_value.quantize(quant):,.{decimals}f}".replace(",", " ")


def _format_currency(value: Any) -> str:
    return f"{_format_decimal(value, 0)} ₽"


def _format_percent(value: Any, decimals: int = 1) -> str:
    return f"{_format_decimal(value, decimals)}%"


def _format_pp(value: Any, decimals: int = 1) -> str:
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return "н/д"
    prefix = "+" if decimal_value > 0 else ""
    return f"{prefix}{_format_decimal(decimal_value, decimals)} п.п."


def _safe_diff(current: Any, previous: Any) -> Decimal | None:
    current_decimal = _to_decimal(current)
    previous_decimal = _to_decimal(previous)
    if current_decimal is None or previous_decimal is None:
        return None
    return current_decimal - previous_decimal


def _safe_pct_delta(current: Any, previous: Any) -> Decimal | None:
    current_decimal = _to_decimal(current)
    previous_decimal = _to_decimal(previous)
    if current_decimal is None or previous_decimal in (None, Decimal("0")):
        return None
    return (current_decimal - previous_decimal) / previous_decimal * Decimal("100")


def _safe_pp_delta(current: Any, previous: Any) -> Decimal | None:
    current_decimal = _to_decimal(current)
    previous_decimal = _to_decimal(previous)
    if current_decimal is None or previous_decimal is None:
        return None
    return current_decimal - previous_decimal


def _is_positive(value: Decimal | None) -> bool:
    return value is not None and value > 0


def _is_negative(value: Decimal | None) -> bool:
    return value is not None and value < 0


def _row_by_key(rows: Iterable[dict[str, Any]], key: str) -> dict[Any, dict[str, Any]]:
    result: dict[Any, dict[str, Any]] = {}
    for row in rows:
        result[row.get(key)] = row
    return result


def _stage_elapsed_ms(started_at: float) -> int:
    return int((perf_counter() - started_at) * 1000)


def _query_ms(query_counter: dict[str, Any], *query_names: str) -> int:
    names = set(query_names)
    return sum(int(item.get("ms") or 0) for item in query_counter.get("timings", []) if item.get("query") in names)


def _limited_distinct_ints(values: Iterable[Any], limit: int) -> list[int]:
    result: list[int] = []
    seen: set[int] = set()
    for value in values:
        try:
            parsed = int(value)
        except (TypeError, ValueError):
            continue
        if parsed in seen:
            continue
        seen.add(parsed)
        result.append(parsed)
        if len(result) >= limit:
            break
    return result


def collect_context_candidate_nm_ids(
    assortment_rows: list[dict[str, Any]],
    stock_rows: list[dict[str, Any]],
    search_rows: list[dict[str, Any]],
    *,
    top_n: int,
) -> list[int]:
    ranked_assortment = sorted(assortment_rows, key=lambda row: _to_decimal(row.get("order_sum_delta")) or Decimal("0"), reverse=True)
    weakest_assortment = sorted(assortment_rows, key=lambda row: _to_decimal(row.get("order_sum_delta")) or Decimal("0"))
    values: list[Any] = []
    values.extend(row.get("nm_id") for row in ranked_assortment[:top_n])
    values.extend(row.get("nm_id") for row in weakest_assortment[:top_n])
    values.extend(row.get("nm_id") for row in stock_rows[:top_n])
    values.extend(row.get("nm_id") for row in search_rows[:top_n])
    return _limited_distinct_ints(values, top_n * 4)


def append_context_summaries(
    sections: list[WbDailyOperationalSectionResponse],
    *,
    price_context: list[dict[str, Any]],
    logistics_context: list[dict[str, Any]],
) -> None:
    overview = next((section for section in sections if section.key == "overview"), None)
    sales = next((section for section in sections if section.key == "sales"), None)
    if overview is not None:
        biggest_price = max(price_context, key=lambda row: abs(_to_decimal(row.get("price_delta_day")) or Decimal("0")), default=None)
        if biggest_price and _to_decimal(biggest_price.get("price_delta_day")) not in (None, Decimal("0")):
            overview.summary.append(
                f"Есть подтвержденное изменение клиентской цены по артикулу {biggest_price.get('nm_id')}: {_format_currency(biggest_price.get('price_delta_day'))} к предыдущему дню."
            )
    if sales is not None:
        biggest_logistics = max(logistics_context, key=lambda row: abs(_to_decimal(row.get("total_logistics_delta_day")) or Decimal("0")), default=None)
        if biggest_logistics and _to_decimal(biggest_logistics.get("total_logistics_delta_day")) not in (None, Decimal("0")):
            sales.summary.append(
                f"Логистические расходы по finance-слою изменились по артикулу {biggest_logistics.get('nm_id')} на {_format_currency(biggest_logistics.get('total_logistics_delta_day'))}; блок остается PARTIAL по дате rr_dt."
            )


def append_analysis_narratives(
    sections: list[WbDailyOperationalSectionResponse],
    *,
    analysis_summary: dict[str, Any],
) -> None:
    section_narratives = analysis_summary.get("section_narratives") or {}
    for section in sections:
        payload = section_narratives.get(section.key)
        if not isinstance(payload, dict):
            continue
        comment = str(payload.get("comment") or "").strip()
        action = str(payload.get("action") or "").strip()
        if comment:
            line = f"\u041c\u043d\u0435\u043d\u0438\u0435 \u0418\u0418: {comment}"
            if line not in section.summary:
                section.summary.append(line)
        if action:
            line = f"\u0414\u0435\u0439\u0441\u0442\u0432\u0438\u0435: {action}"
            if line not in section.summary:
                section.summary.append(line)


def get_current_moscow_date() -> date:
    return datetime.now(MOSCOW_TZ).date()


def build_report_window(report_date: date, report_date_source: str) -> WbDailyOperationalReportWindowResponse:
    return WbDailyOperationalReportWindowResponse(
        report_date=report_date,
        compare_date=report_date - timedelta(days=1),
        trend_current_from=report_date - timedelta(days=6),
        trend_current_to=report_date,
        trend_previous_from=report_date - timedelta(days=13),
        trend_previous_to=report_date - timedelta(days=7),
        report_date_source=report_date_source,
    )


def resolve_report_date(requested_date: date | None, freshness_rows: list[dict[str, Any]], *, now_date: date | None = None) -> tuple[date, str]:
    current_date = now_date or get_current_moscow_date()
    yesterday = current_date - timedelta(days=1)
    core_dates = [row.get("max_date") for row in freshness_rows if row.get("max_date") is not None]
    if not core_dates:
        raise ValueError("Core sources do not have any dates for report generation.")
    core_limit = min(core_dates)
    last_full_day = min(yesterday, core_limit)
    if requested_date is None:
        return last_full_day, "auto_core_min"
    if requested_date >= current_date:
        raise ValueError("report_date must be earlier than current Moscow date.")
    if requested_date > core_limit:
        raise ValueError("report_date is newer than available core-source data.")
    return requested_date, "requested"


def build_source_freshness(freshness_rows: list[dict[str, Any]], report_date: date) -> list[WbDailyOperationalSourceFreshnessResponse]:
    result: list[WbDailyOperationalSourceFreshnessResponse] = []
    for row in freshness_rows:
        max_date = row.get("max_date")
        if max_date is None:
            status = "MISSING"
            lag_days = None
        else:
            lag_days = max((report_date - max_date).days, 0)
            status = "OK" if max_date >= report_date else "STALE"
        result.append(
            WbDailyOperationalSourceFreshnessResponse(
                source=str(row.get("source_name")),
                max_date=max_date,
                status=status,
                lag_days=lag_days,
            )
        )
    return result


def _metric_row(
    label: str,
    current_value: Any,
    previous_value: Any,
    trend_current_value: Any,
    trend_previous_value: Any,
    *,
    use_percentage_points: bool = False,
    note: str | None = None,
) -> WbDailyOperationalMetricRowResponse:
    return WbDailyOperationalMetricRowResponse(
        metric=label,
        value=current_value,
        previous_value=previous_value,
        delta_abs=_safe_diff(current_value, previous_value),
        delta_pct=None if use_percentage_points else _safe_pct_delta(current_value, previous_value),
        delta_pp=_safe_pp_delta(current_value, previous_value) if use_percentage_points else None,
        trend_7d_pct=None if use_percentage_points else _safe_pct_delta(trend_current_value, trend_previous_value),
        trend_7d_pp=_safe_pp_delta(trend_current_value, trend_previous_value) if use_percentage_points else None,
        note=note,
    )


def _empty_section(key: str, reason: str) -> WbDailyOperationalExcludedSectionResponse:
    return WbDailyOperationalExcludedSectionResponse(key=key, title=SECTION_TITLES[key], reason=reason)


def build_overview_section(current: dict[str, Any], previous: dict[str, Any], current_7d: dict[str, Any], previous_7d: dict[str, Any]) -> WbDailyOperationalSectionResponse:
    order_sum_delta = _safe_pct_delta(current.get("order_sum"), previous.get("order_sum"))
    ad_spend_delta = _safe_pct_delta(current.get("ad_spend"), previous.get("ad_spend"))
    summary: list[str] = []
    if _is_positive(order_sum_delta):
        summary.append(f"Оборот заказов вырос до {_format_currency(current.get('order_sum'))} ({_format_percent(order_sum_delta)} к предыдущему дню).")
    elif _is_negative(order_sum_delta):
        summary.append(f"Оборот заказов снизился до {_format_currency(current.get('order_sum'))} ({_format_percent(order_sum_delta)} к предыдущему дню).")
    if _is_positive(ad_spend_delta):
        summary.append(f"Рекламный расход вырос до {_format_currency(current.get('ad_spend'))}.")
    elif _is_negative(ad_spend_delta):
        summary.append(f"Рекламный расход снизился до {_format_currency(current.get('ad_spend'))}.")
    if not summary:
        summary.append("Суточные изменения по ключевым метрикам не вышли за заметный диапазон.")
    return WbDailyOperationalSectionResponse(
        key="overview",
        title=SECTION_TITLES["overview"],
        status="OK",
        summary=summary,
        metrics=[
            _metric_row("Оборот заказов", current.get("order_sum"), previous.get("order_sum"), current_7d.get("order_sum"), previous_7d.get("order_sum")),
            _metric_row("Заказы", current.get("order_count"), previous.get("order_count"), current_7d.get("order_count"), previous_7d.get("order_count")),
            _metric_row("Рекламный расход", current.get("ad_spend"), previous.get("ad_spend"), current_7d.get("ad_spend"), previous_7d.get("ad_spend")),
        ],
    )


def build_traffic_section(current: dict[str, Any], previous: dict[str, Any], current_7d: dict[str, Any], previous_7d: dict[str, Any]) -> WbDailyOperationalSectionResponse | None:
    if current.get("impressions") is None and current.get("card_clicks") is None:
        return None
    ctr_delta_pp = _safe_pp_delta(current.get("ctr"), previous.get("ctr"))
    summary: list[str] = []
    if _is_negative(ctr_delta_pp):
        summary.append("Показы изменились быстрее кликов, поэтому CTR снизился.")
    elif _is_positive(ctr_delta_pp):
        summary.append("CTR улучшился: клики росли не медленнее показов.")
    return WbDailyOperationalSectionResponse(
        key="traffic",
        title=SECTION_TITLES["traffic"],
        status="OK",
        summary=summary or ["Трафиковые метрики доступны по последнему полному дню и 7-дневному окну."],
        metrics=[
            _metric_row("Общие показы", current.get("impressions"), previous.get("impressions"), current_7d.get("impressions"), previous_7d.get("impressions")),
            _metric_row("Общие клики", current.get("card_clicks"), previous.get("card_clicks"), current_7d.get("card_clicks"), previous_7d.get("card_clicks")),
            _metric_row("CTR общий", current.get("ctr"), previous.get("ctr"), current_7d.get("ctr"), previous_7d.get("ctr"), use_percentage_points=True),
            _metric_row("Рекламные показы", current.get("ad_views"), previous.get("ad_views"), current_7d.get("ad_views"), previous_7d.get("ad_views")),
            _metric_row("Рекламные клики", current.get("ad_clicks"), previous.get("ad_clicks"), current_7d.get("ad_clicks"), previous_7d.get("ad_clicks")),
        ],
    )


def build_funnel_section(current: dict[str, Any], previous: dict[str, Any], current_7d: dict[str, Any], previous_7d: dict[str, Any]) -> WbDailyOperationalSectionResponse | None:
    if current.get("cart_count") is None and current.get("order_count") is None:
        return None
    summary: list[str] = []
    cart_conv_delta = _safe_pp_delta(current.get("add_to_cart_conversion"), previous.get("add_to_cart_conversion"))
    order_conv_delta = _safe_pp_delta(current.get("cart_to_order_conversion"), previous.get("cart_to_order_conversion"))
    if _is_negative(cart_conv_delta):
        summary.append("Конверсия в корзину снизилась относительно предыдущего дня.")
    if _is_negative(order_conv_delta):
        summary.append("Конверсия из корзины в заказ снизилась относительно предыдущего дня.")
    if not summary:
        summary.append("Воронка без резких отклонений по ключевым конверсиям.")
    return WbDailyOperationalSectionResponse(
        key="funnel",
        title=SECTION_TITLES["funnel"],
        status="OK",
        summary=summary,
        metrics=[
            _metric_row("Корзины", current.get("cart_count"), previous.get("cart_count"), current_7d.get("cart_count"), previous_7d.get("cart_count")),
            _metric_row("Конверсия в корзину", current.get("add_to_cart_conversion"), previous.get("add_to_cart_conversion"), current_7d.get("add_to_cart_conversion"), previous_7d.get("add_to_cart_conversion"), use_percentage_points=True),
            _metric_row("Заказы", current.get("order_count"), previous.get("order_count"), current_7d.get("order_count"), previous_7d.get("order_count")),
            _metric_row("Конверсия в заказ", current.get("cart_to_order_conversion"), previous.get("cart_to_order_conversion"), current_7d.get("cart_to_order_conversion"), previous_7d.get("cart_to_order_conversion"), use_percentage_points=True),
            _metric_row("Средний чек", current.get("avg_check"), previous.get("avg_check"), current_7d.get("avg_check"), previous_7d.get("avg_check")),
            _metric_row("Сумма заказов", current.get("order_sum"), previous.get("order_sum"), current_7d.get("order_sum"), previous_7d.get("order_sum")),

        ],

    )


def build_ads_section(current: dict[str, Any], previous: dict[str, Any], current_7d: dict[str, Any], previous_7d: dict[str, Any], campaign_rows: list[dict[str, Any]], top_n: int, rules: WbDailyOperationalSummaryRules) -> WbDailyOperationalSectionResponse | None:
    if current.get("ad_spend") is None:
        return None
    problematic: list[dict[str, Any]] = []
    for row in campaign_rows:
        spend_current = _to_decimal(row.get("spend_current")) or Decimal("0")
        spend_previous = _to_decimal(row.get("spend_previous")) or Decimal("0")
        orders_current = _to_decimal(row.get("orders_current")) or Decimal("0")
        orders_previous = _to_decimal(row.get("orders_previous")) or Decimal("0")
        revenue_current = _to_decimal(row.get("revenue_current")) or Decimal("0")
        drr_current = (spend_current / revenue_current * Decimal("100")) if revenue_current > 0 else None
        spend_delta_pct = _safe_pct_delta(spend_current, spend_previous)
        orders_delta_pct = _safe_pct_delta(orders_current, orders_previous)
        issue: str | None = None
        severity = 0
        if spend_current >= rules.zero_order_spend_threshold and orders_current == 0:
            issue = "Расход есть, заказов нет"
            severity = 3
        elif drr_current is not None and drr_current >= rules.high_drr_threshold:
            issue = "Высокий ДРР"
            severity = 2
        elif _is_positive(spend_delta_pct) and not _is_positive(orders_delta_pct):
            issue = "Расход растет быстрее заказов"
            severity = 1
        if issue:
            problematic.append(
                {
                    "severity": severity,
                    "Кампания": row.get("campaign_name") or f"advert {row.get('advert_id')}",
                    "Advert ID": str(row.get("advert_id")),
                    "Тип": row.get("row_type") or "н/д",
                    "Расход": _format_currency(spend_current),
                    "Изм. расхода": _format_percent(spend_delta_pct) if spend_delta_pct is not None else "н/д",
                    "Заказы": _format_decimal(orders_current),
                    "ДРР": _format_percent(drr_current) if drr_current is not None else "н/д",
                    "Проблема": issue,
                }
            )
    problematic.sort(key=lambda item: (-int(item["severity"]), item["Кампания"]))
    problematic_rows = [{key: value for key, value in item.items() if key != "severity"} for item in problematic[:top_n]]
    summary = ["Рекламный блок собран по дневным данным кампаний и сравнен с предыдущим полным днем."]
    if problematic_rows:
        summary.append("Есть кампании, где расход растет быстрее заказов или расход остается без заказов.")
    return WbDailyOperationalSectionResponse(
        key="ads",
        title=SECTION_TITLES["ads"],
        status="OK",
        summary=summary,
        metrics=[
            _metric_row("Расход", current.get("ad_spend"), previous.get("ad_spend"), current_7d.get("ad_spend"), previous_7d.get("ad_spend")),
            _metric_row("ДРР", current.get("drr"), previous.get("drr"), current_7d.get("drr"), previous_7d.get("drr"), use_percentage_points=True),
            _metric_row("CPC", current.get("cpc"), previous.get("cpc"), current_7d.get("cpc"), previous_7d.get("cpc")),
            _metric_row("CPM", current.get("cpm"), previous.get("cpm"), current_7d.get("cpm"), previous_7d.get("cpm")),
            _metric_row("CPO", current.get("cpo"), previous.get("cpo"), current_7d.get("cpo"), previous_7d.get("cpo")),
            _metric_row("Стоимость корзины", current.get("cost_per_cart"), previous.get("cost_per_cart"), current_7d.get("cost_per_cart"), previous_7d.get("cost_per_cart")),
            _metric_row("Рекламные показы", current.get("ad_views"), previous.get("ad_views"), current_7d.get("ad_views"), previous_7d.get("ad_views")),
            _metric_row("Рекламные клики", current.get("ad_clicks"), previous.get("ad_clicks"), current_7d.get("ad_clicks"), previous_7d.get("ad_clicks")),
            _metric_row("Рекламные корзины", current.get("ad_atbs"), previous.get("ad_atbs"), current_7d.get("ad_atbs"), previous_7d.get("ad_atbs")),
            _metric_row("Рекламные заказы", current.get("ad_orders"), previous.get("ad_orders"), current_7d.get("ad_orders"), previous_7d.get("ad_orders")),
        ],
        tables=[WbDailyOperationalTableResponse(title="Проблемные кампании", columns=["Кампания", "Advert ID", "Тип", "Расход", "Изм. расхода", "Заказы", "ДРР", "Проблема"], rows=problematic_rows)] if problematic_rows else [],
        signals=[WbDailyOperationalSignalResponse(fact=f"Проблемных кампаний: {len(problematic_rows)}", interpretation="Есть кампании с расходом без заказов или ухудшением эффективности." if problematic_rows else "Критичных проблемных кампаний не найдено.", recommended_check="Проверить ставки и распределение бюджета по верхним проблемным кампаниям." if problematic_rows else None, confidence="high")],
    )


def build_sales_section(current: dict[str, Any], previous: dict[str, Any], current_7d: dict[str, Any], previous_7d: dict[str, Any]) -> WbDailyOperationalSectionResponse | None:
    if current.get("order_sum") is None:
        return None
    summary: list[str] = []
    avg_check_delta = _safe_pct_delta(current.get("avg_check"), previous.get("avg_check"))
    orders_delta = _safe_pct_delta(current.get("order_count"), previous.get("order_count"))
    if _is_positive(avg_check_delta) and _is_positive(orders_delta):
        summary.append("Оборот поддержали и средний чек, и количество заказов.")
    elif _is_positive(avg_check_delta):
        summary.append("Изменение оборота поддержал рост среднего чека.")
    elif _is_positive(orders_delta):
        summary.append("Изменение оборота поддержало количество заказов.")
    else:
        summary.append("Продажи изменились без выраженного роста среднего чека и числа заказов одновременно.")
    return WbDailyOperationalSectionResponse(
        key="sales",
        title=SECTION_TITLES["sales"],
        status="OK",
        summary=summary,
        metrics=[
            _metric_row("Оборот заказов", current.get("order_sum"), previous.get("order_sum"), current_7d.get("order_sum"), previous_7d.get("order_sum")),
            _metric_row("Заказы", current.get("order_count"), previous.get("order_count"), current_7d.get("order_count"), previous_7d.get("order_count")),


            _metric_row("Средний чек", current.get("avg_check"), previous.get("avg_check"), current_7d.get("avg_check"), previous_7d.get("avg_check")),
        ],

    )


def build_stock_section(stock_rows: list[dict[str, Any]], top_n: int, rules: WbDailyOperationalSummaryRules) -> WbDailyOperationalSectionResponse | None:
    risk_rows: list[dict[str, Any]] = []
    risk_order = {"Нулевой остаток": 0, "Низкий запас": 1, "Избыточный запас": 2}
    for row in stock_rows:
        stock_qty = _to_decimal(row.get("stock_qty")) or Decimal("0")
        avg_orders = _to_decimal(row.get("avg_orders_7d")) or Decimal("0")
        days_of_supply = _to_decimal(row.get("days_of_supply"))
        if avg_orders < rules.minimum_sales_for_stock_signal:
            continue
        risk_type: str | None = None
        if stock_qty <= 0:
            risk_type = "Нулевой остаток"
        elif days_of_supply is not None and days_of_supply <= rules.low_stock_days:
            risk_type = "Низкий запас"
        elif days_of_supply is not None and days_of_supply >= rules.high_stock_days:
            risk_type = "Избыточный запас"
        if risk_type:
            risk_rows.append({
                "Артикул": str(row.get("nm_id")),
                "Артикул продавца": row.get("supplier_article") or "н/д",
                "Товар": row.get("title") or "н/д",
                "Склад": row.get("warehouse_name") or "н/д",
                "Остаток": _format_decimal(stock_qty),
                "Средние заказы 7д": _format_decimal(avg_orders, 1),
                "Оценка запаса": (_format_decimal(days_of_supply, 0) + " дн.") if days_of_supply is not None else "н/д",
                "Риск": risk_type,
                "risk_order": risk_order.get(risk_type, 99),
                "days_sort": days_of_supply if days_of_supply is not None else Decimal("999999"),
            })
    risk_rows = sorted(risk_rows, key=lambda item: (item["risk_order"], item["days_sort"], item["Артикул"]))[:top_n]
    for item in risk_rows:
        item.pop("risk_order", None)
        item.pop("days_sort", None)
    if not risk_rows:
        return None
    return WbDailyOperationalSectionResponse(
        key="stock",
        title=SECTION_TITLES["stock"],
        status="OK",
        summary=["Показана оценка запаса по общей скорости артикула, а не точный warehouse-level DOS."],
        tables=[WbDailyOperationalTableResponse(title="Складские риски", columns=["Артикул", "Артикул продавца", "Товар", "Склад", "Остаток", "Средние заказы 7д", "Оценка запаса", "Риск"], rows=risk_rows)],
        notes=["Оценка запаса основана на общей скорости заказов артикула, а не на фактических продажах конкретного склада."],
    )


def build_assortment_section(assortment_rows: list[dict[str, Any]], top_n: int) -> WbDailyOperationalSectionResponse | None:
    if not assortment_rows:
        return None
    ranked = []
    for row in assortment_rows:
        delta = _to_decimal(row.get("order_sum_delta")) or Decimal("0")
        previous_value = _to_decimal(row.get("order_sum_previous")) or Decimal("0")
        ranked.append({
            "Артикул": str(row.get("nm_id")),
            "Артикул продавца": row.get("supplier_article") or "н/д",
            "Товар": row.get("title") or "н/д",
            "Оборот": _format_currency(row.get("order_sum_current")),
            "Изм. оборота": _format_currency(delta),
            "Изм. оборота %": _format_percent(_safe_pct_delta(row.get("order_sum_current"), previous_value)) if previous_value not in (None, Decimal("0")) else "н/д",
            "Заказы": _format_decimal(row.get("order_count_current")),
            "Реклама": _format_currency(row.get("ad_spend_current")),
            "Остаток": _format_decimal(row.get("current_stock_qty")),
            "delta_raw": delta,
        })
    growth = sorted(ranked, key=lambda item: item["delta_raw"], reverse=True)[:top_n]
    decline = sorted(ranked, key=lambda item: item["delta_raw"])[:top_n]
    for items in (growth, decline):
        for item in items:
            item.pop("delta_raw", None)
    return WbDailyOperationalSectionResponse(
        key="assortment",
        title=SECTION_TITLES["assortment"],
        status="OK",
        summary=["Раздел показывает артикулы, которые дали основной вклад в рост и падение суточного оборота."],
        tables=[
            WbDailyOperationalTableResponse(title="ТОП роста", columns=["Артикул", "Артикул продавца", "Товар", "Оборот", "Изм. оборота", "Изм. оборота %", "Заказы", "Реклама", "Остаток"], rows=growth),
            WbDailyOperationalTableResponse(title="ТОП падения", columns=["Артикул", "Артикул продавца", "Товар", "Оборот", "Изм. оборота", "Изм. оборота %", "Заказы", "Реклама", "Остаток"], rows=decline),
        ],
    )


def build_search_section(current: dict[str, Any], previous: dict[str, Any], current_7d: dict[str, Any], previous_7d: dict[str, Any], search_rows: list[dict[str, Any]], top_n: int, rules: WbDailyOperationalSummaryRules) -> WbDailyOperationalSectionResponse | None:
    has_summary = any(current.get(key) is not None for key in ("search_avg_position", "search_visibility", "search_clicks", "search_orders"))
    if not has_summary and not search_rows:
        return None
    improved: list[dict[str, Any]] = []
    worsened: list[dict[str, Any]] = []
    for row in search_rows:
        current_position = _to_decimal(row.get("avg_position_current"))
        previous_position = _to_decimal(row.get("avg_position_previous"))
        if current_position is None or previous_position is None:
            continue
        delta = current_position - previous_position
        item = {
            "Артикул": str(row.get("nm_id")),
            "Артикул продавца": row.get("supplier_article") or "н/д",
            "Товар": row.get("title") or "н/д",
            "Позиция": _format_decimal(current_position, 1),
            "Пред. позиция": _format_decimal(previous_position, 1),
            "Изм. позиции": _format_decimal(delta, 1),
            "Видимость": _format_percent(row.get("visibility_current")),
            "Поисковые клики": _format_decimal(row.get("search_clicks_current")),
            "Поисковые заказы": _format_decimal(row.get("search_orders_current")),
            "delta_raw": delta,
        }
        if delta <= -rules.search_position_change_threshold:
            improved.append(item)
        elif delta >= rules.search_position_change_threshold:
            worsened.append(item)
    improved = sorted(improved, key=lambda item: item["delta_raw"])[:top_n]
    worsened = sorted(worsened, key=lambda item: item["delta_raw"], reverse=True)[:top_n]
    for items in (improved, worsened):
        for item in items:
            item.pop("delta_raw", None)
    summary = ["Для поиска улучшение позиции означает уменьшение среднего номера позиции."]
    if worsened:
        summary.append("Есть артикулы с заметным ухудшением средней позиции в поиске.")
    return WbDailyOperationalSectionResponse(
        key="search",
        title=SECTION_TITLES["search"],
        status="OK",
        summary=summary,
        metrics=[
            _metric_row("Средняя позиция", current.get("search_avg_position"), previous.get("search_avg_position"), current_7d.get("search_avg_position"), previous_7d.get("search_avg_position"), use_percentage_points=True),
            _metric_row("Видимость", current.get("search_visibility"), previous.get("search_visibility"), current_7d.get("search_visibility"), previous_7d.get("search_visibility"), use_percentage_points=True),
            _metric_row("Поисковые клики", current.get("search_clicks"), previous.get("search_clicks"), current_7d.get("search_clicks"), previous_7d.get("search_clicks")),
            _metric_row("Поисковые корзины", current.get("search_cart"), previous.get("search_cart"), current_7d.get("search_cart"), previous_7d.get("search_cart")),
            _metric_row("Поисковые заказы", current.get("search_orders"), previous.get("search_orders"), current_7d.get("search_orders"), previous_7d.get("search_orders")),
        ],
        tables=[
            WbDailyOperationalTableResponse(title="Улучшение позиции в поиске", columns=["Артикул", "Артикул продавца", "Товар", "Позиция", "Пред. позиция", "Изм. позиции", "Видимость", "Поисковые клики", "Поисковые заказы"], rows=improved),
            WbDailyOperationalTableResponse(title="Ухудшение позиции в поиске", columns=["Артикул", "Артикул продавца", "Товар", "Позиция", "Пред. позиция", "Изм. позиции", "Видимость", "Поисковые клики", "Поисковые заказы"], rows=worsened),
        ],
    )


def build_profit_section(profit_payload: dict[str, Any], report_date: date, compare_date: date) -> WbDailyOperationalSectionResponse | None:
    daily_by_date = _row_by_key(profit_payload.get("daily", []), "day")
    trend_by_bucket = _row_by_key(profit_payload.get("trend", []), "bucket")
    current = daily_by_date.get(report_date)
    previous = daily_by_date.get(compare_date)
    if not current:
        return None
    max_day = profit_payload.get("max_day")
    status = "PARTIAL"
    notes = ["Источник прибыли: fact_vvbromo_product_day. Источник внешний и не смешивается с сырыми finance-полями."]
    if max_day and max_day < report_date:
        status = "STALE"
        notes.append(f"Источник отстает: последняя дата {max_day.isoformat()}.")
    else:
        notes.append("Источник частичный: прибыль строится только по VVBromo.")
    return WbDailyOperationalSectionResponse(
        key="profit",
        title=SECTION_TITLES["profit"],
        status=status,
        summary=["Блок прибыли показан только как partial-источник без факторного разложения причин."],
        metrics=[
            _metric_row("Операционная прибыль", current.get("operating_profit"), previous.get("operating_profit") if previous else None, trend_by_bucket.get("current", {}).get("operating_profit"), trend_by_bucket.get("previous", {}).get("operating_profit")),
            _metric_row("Прибыль на единицу", current.get("profit_per_unit"), previous.get("profit_per_unit") if previous else None, trend_by_bucket.get("current", {}).get("profit_per_unit"), trend_by_bucket.get("previous", {}).get("profit_per_unit")),
        ],
        notes=notes,
    )


def collect_highlights(sections: list[WbDailyOperationalSectionResponse], top_n: int) -> WbDailyOperationalHighlightsResponse:
    worse: list[str] = []
    better: list[str] = []
    priority_checks: list[str] = []
    for section in sections:
        if section.key == "traffic":
            for metric in section.metrics:
                if metric.metric == "CTR общий" and _is_negative(metric.delta_pp):
                    worse.append(f"CTR снизился на {_format_pp(metric.delta_pp)}.")
                if metric.metric == "Общие показы" and _is_positive(metric.delta_pct):
                    better.append(f"Показы выросли на {_format_percent(metric.delta_pct)}.")
        elif section.key == "funnel":
            for metric in section.metrics:
                if metric.metric == "Заказы" and _is_positive(metric.delta_pct):
                    better.append(f"Заказы выросли на {_format_percent(metric.delta_pct)}.")
                if metric.metric == "Конверсия в корзину" and _is_negative(metric.delta_pp):
                    worse.append(f"Конверсия в корзину снизилась на {_format_pp(metric.delta_pp)}.")
        elif section.key == "ads" and section.tables and section.tables[0].rows:
            priority_checks.append("Проверить проблемные рекламные кампании из рекламного блока.")
            worse.append(f"Есть {len(section.tables[0].rows)} проблемных рекламных кампаний.")
        elif section.key == "stock" and section.tables and section.tables[0].rows:
            priority_checks.append("Проверить позиции с риском нулевого остатка или низкого запаса.")
            worse.append(f"Найдено {len(section.tables[0].rows)} складских риска в топе отчета.")
        elif section.key == "search":
            for table in section.tables:
                if table.title == "Ухудшение позиции в поиске" and table.rows:
                    priority_checks.append("Проверить артикулы с ухудшением позиции в поиске.")
                    worse.append(f"Есть {len(table.rows)} артикула с заметным ухудшением позиции в поиске.")
                if table.title == "Улучшение позиции в поиске" and table.rows:
                    better.append(f"Есть {len(table.rows)} артикула с улучшением позиции в поиске.")
        elif section.key == "sales":
            for metric in section.metrics:
                if metric.metric == "Оборот заказов" and _is_positive(metric.delta_pct):
                    better.append(f"Оборот заказов вырос на {_format_percent(metric.delta_pct)}.")
                if metric.metric == "Оборот заказов" and _is_negative(metric.delta_pct):
                    worse.append(f"Оборот заказов снизился на {_format_percent(metric.delta_pct)}.")
    return WbDailyOperationalHighlightsResponse(worse=worse[:top_n], better=better[:top_n], priority_checks=priority_checks[:top_n])


def build_priority_section(
    highlights: WbDailyOperationalHighlightsResponse,
    analysis_summary: dict[str, Any] | None = None,
) -> WbDailyOperationalSectionResponse | None:
    priority_narratives = (analysis_summary or {}).get("priority_narratives") or []
    if priority_narratives:
        summary = [str(item.get("text")) for item in priority_narratives if item.get("text")][:5]
        if summary:
            return WbDailyOperationalSectionResponse(
                key="priority",
                title=SECTION_TITLES["priority"],
                status="OK",
                summary=summary,
            )
    if not highlights.priority_checks:
        return None
    return WbDailyOperationalSectionResponse(key="priority", title=SECTION_TITLES["priority"], status="OK", summary=highlights.priority_checks[:3])


def build_scenario_section(
    highlights: WbDailyOperationalHighlightsResponse,
    analysis_summary: dict[str, Any] | None = None,
) -> WbDailyOperationalSectionResponse:
    summary: list[str] = []
    scenario_narrative = str(((analysis_summary or {}).get("scenario_narrative") or "")).strip()
    if scenario_narrative:
        summary.append(scenario_narrative)
    else:
        if highlights.better:
            summary.append(f"\u0413\u043b\u0430\u0432\u043d\u0430\u044f \u0442\u043e\u0447\u043a\u0430 \u0440\u043e\u0441\u0442\u0430 \u0434\u043d\u044f: {highlights.better[0]}")
        if highlights.worse:
            summary.append(f"\u0413\u043b\u0430\u0432\u043d\u044b\u0439 \u0440\u0438\u0441\u043a \u0434\u043d\u044f: {highlights.worse[0]}")
        if highlights.priority_checks:
            summary.append(f"\u0411\u043b\u0438\u0436\u0430\u0439\u0448\u0430\u044f \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0430: {highlights.priority_checks[0]}")
    if not summary:
        summary.append("\u0421\u0446\u0435\u043d\u0430\u0440\u043d\u044b\u0439 \u0438\u0442\u043e\u0433 \u043d\u0435 \u0441\u0444\u043e\u0440\u043c\u0438\u0440\u043e\u0432\u0430\u043d: \u043f\u043e \u0434\u043e\u0441\u0442\u0443\u043f\u043d\u044b\u043c \u0434\u0430\u043d\u043d\u044b\u043c \u043d\u0435\u0442 \u0432\u044b\u0440\u0430\u0436\u0435\u043d\u043d\u044b\u0445 \u0441\u0438\u0433\u043d\u0430\u043b\u043e\u0432 \u0434\u043b\u044f \u043f\u0440\u0438\u043e\u0440\u0438\u0442\u0435\u0442\u043d\u043e\u0439 \u043f\u0440\u043e\u0432\u0435\u0440\u043a\u0438.")
    return WbDailyOperationalSectionResponse(key="scenario", title=SECTION_TITLES["scenario"], status="OK", summary=summary, notes=["\u0420\u0430\u0437\u0434\u0435\u043b \u043d\u0435 \u0441\u043e\u0434\u0435\u0440\u0436\u0438\u0442 \u043f\u0440\u043e\u0433\u043d\u043e\u0437\u0430 \u043e\u0431\u043e\u0440\u043e\u0442\u0430 \u0438\u043b\u0438 \u043f\u0440\u0438\u0431\u044b\u043b\u0438 \u0438 \u043e\u043f\u0438\u0440\u0430\u0435\u0442\u0441\u044f \u0442\u043e\u043b\u044c\u043a\u043e \u043d\u0430 \u043f\u043e\u0434\u0442\u0432\u0435\u0440\u0436\u0434\u0435\u043d\u043d\u044b\u0435 \u0441\u0438\u0433\u043d\u0430\u043b\u044b."])


def build_operational_summary(session: Session, payload: WbDailyOperationalSummaryRequest, *, rules: WbDailyOperationalSummaryRules | None = None, now_date: date | None = None) -> WbDailyOperationalSummaryResponse:
    resolved_rules = rules or get_default_rules()
    started_at = perf_counter()
    query_counter = {"count": 0, "timings": []}
    stage_timings: list[dict[str, Any]] = []

    stage_started = perf_counter()
    freshness_rows = fetch_core_source_freshness(session, query_counter)
    stage_timings.append({"stage": "core_source_freshness", "ms": _stage_elapsed_ms(stage_started)})
    report_date, report_date_source = resolve_report_date(payload.report_date, freshness_rows, now_date=now_date)
    window = build_report_window(report_date, report_date_source)

    stage_started = perf_counter()
    daily_rows = fetch_mart_daily_overview(session, window.report_date, window.compare_date, query_counter)
    stage_timings.append({"stage": "mart_daily_overview", "ms": _stage_elapsed_ms(stage_started)})
    stage_started = perf_counter()
    window_rows = fetch_mart_window_overview(session, window.trend_current_from, window.trend_current_to, window.trend_previous_from, window.trend_previous_to, query_counter)
    stage_timings.append({"stage": "mart_window_overview", "ms": _stage_elapsed_ms(stage_started)})
    stage_started = perf_counter()
    assortment_rows = fetch_assortment_changes(session, window.report_date, window.compare_date, query_counter)
    stage_timings.append({"stage": "assortment_changes", "ms": _stage_elapsed_ms(stage_started)})
    stage_started = perf_counter()
    campaign_rows = fetch_problem_campaigns(session, window.report_date, window.compare_date, query_counter)
    stage_timings.append({"stage": "problem_campaigns", "ms": _stage_elapsed_ms(stage_started)})
    stage_started = perf_counter()
    stock_rows = fetch_stock_risks(session, window.report_date, window.trend_current_from, query_counter)
    stage_timings.append({"stage": "stock_risks", "ms": _stage_elapsed_ms(stage_started)})
    stage_started = perf_counter()
    search_rows = fetch_search_movers(session, window.report_date, window.compare_date, query_counter)
    stage_timings.append({"stage": "search_movers", "ms": _stage_elapsed_ms(stage_started)})

    candidate_nm_ids = collect_context_candidate_nm_ids(assortment_rows, stock_rows, search_rows, top_n=payload.top_n)
    extended_context = build_extended_context(
        session,
        report_date=window.report_date,
        compare_date=window.compare_date,
        trend_current_from=window.trend_current_from,
        top_n=payload.top_n,
        nm_ids=candidate_nm_ids,
        query_counter=query_counter,
    )

    stage_started = perf_counter()
    database_audit = fetch_database_audit_block(session, query_counter=query_counter)
    stage_timings.append({"stage": "database_audit", "ms": _stage_elapsed_ms(stage_started)})

    stage_started = perf_counter()
    operating_profit_context = fetch_operating_profit_block(
        session,
        report_date=window.report_date,
        compare_date=window.compare_date,
        trend_current_from=window.trend_current_from,
        trend_current_to=window.trend_current_to,
        trend_previous_from=window.trend_previous_from,
        trend_previous_to=window.trend_previous_to,
        top_n=payload.top_n,
        query_counter=query_counter,
    )
    stage_timings.append({"stage": "operating_profit_context", "ms": _stage_elapsed_ms(stage_started)})

    stage_started = perf_counter()
    logistics_summary = fetch_logistics_summary_block(
        session,
        report_date=window.report_date,
        compare_date=window.compare_date,
        trend_current_from=window.trend_current_from,
        trend_current_to=window.trend_current_to,
        trend_previous_from=window.trend_previous_from,
        trend_previous_to=window.trend_previous_to,
        top_n=payload.top_n,
        query_counter=query_counter,
    )
    stage_timings.append({"stage": "logistics_summary", "ms": _stage_elapsed_ms(stage_started)})

    stage_started = perf_counter()
    pricing_spp_context = fetch_pricing_spp_block(
        session,
        report_date=window.report_date,
        compare_date=window.compare_date,
        trend_current_from=window.trend_current_from,
        top_n=payload.top_n,
        query_counter=query_counter,
    )
    stage_timings.append({"stage": "pricing_spp_context", "ms": _stage_elapsed_ms(stage_started)})

    stage_started = perf_counter()
    competitor_context = fetch_competitor_block(
        session,
        report_date=window.report_date,
        top_n=payload.top_n,
        query_counter=query_counter,
    )
    stage_timings.append({"stage": "competitor_context", "ms": _stage_elapsed_ms(stage_started)})

    additional_data_candidates = build_additional_data_candidates(database_audit_block=database_audit)
    source_freshness = build_source_freshness(freshness_rows + extended_context.get("additional_source_freshness", []), report_date)

    daily_by_date = _row_by_key(daily_rows, "report_date")
    window_by_bucket = _row_by_key(window_rows, "bucket")
    current = daily_by_date.get(window.report_date, {})
    previous = daily_by_date.get(window.compare_date, {})
    current_7d = window_by_bucket.get("current", {})
    previous_7d = window_by_bucket.get("previous", {})

    sections: list[WbDailyOperationalSectionResponse] = [build_overview_section(current, previous, current_7d, previous_7d)]
    excluded_sections: list[WbDailyOperationalExcludedSectionResponse] = []

    for key, section in (
        ("traffic", build_traffic_section(current, previous, current_7d, previous_7d)),
        ("funnel", build_funnel_section(current, previous, current_7d, previous_7d)),
        ("ads", build_ads_section(current, previous, current_7d, previous_7d, campaign_rows, payload.top_n, resolved_rules)),
        ("sales", build_sales_section(current, previous, current_7d, previous_7d)),
        ("stock", build_stock_section(stock_rows, payload.top_n, resolved_rules)),
        ("assortment", build_assortment_section(assortment_rows, payload.top_n)),
        ("search", build_search_section(current, previous, current_7d, previous_7d, search_rows, payload.top_n, resolved_rules)),
    ):
        if section is None:
            excluded_sections.append(_empty_section(key, f"Раздел {SECTION_TITLES[key].lower()} исключен: нет подтвержденных данных."))
        else:
            sections.append(section)

    append_context_summaries(
        sections,
        price_context=extended_context.get("price_context", []),
        logistics_context=extended_context.get("logistics_context", []),
    )

    combined_data_gaps = list(extended_context.get("data_gaps", []))
    stage_started = perf_counter()
    analysis_payload = build_internal_analysis(
        report_date=window.report_date,
        daily_rows=daily_rows,
        article_context=extended_context.get("article_context", []),
        warehouse_context=extended_context.get("warehouse_context", []),
        campaign_context=extended_context.get("campaign_context", []),
        search_query_context=extended_context.get("search_query_context", []),
        entry_point_context=extended_context.get("entry_point_context", []),
        price_context=extended_context.get("price_context", []),
        logistics_context=extended_context.get("logistics_context", []),
        database_audit=database_audit,
        operating_profit_context=operating_profit_context,
        logistics_summary=logistics_summary,
        pricing_spp_context=pricing_spp_context,
        competitor_context=competitor_context,
        additional_data_candidates=additional_data_candidates,
        data_gaps=combined_data_gaps,
        rules=resolved_rules,
        top_n=payload.top_n,
    )
    stage_timings.append({"stage": "analysis_layer", "ms": _stage_elapsed_ms(stage_started)})
    combined_data_gaps.extend(analysis_payload.get("data_gaps", []))
    append_analysis_narratives(sections, analysis_summary=analysis_payload.get("analysis_summary", {}))

    if payload.include_profit and payload.include_partial_sections:
        profit_payload = fetch_profit_overview(session, window.report_date, window.compare_date, window.trend_current_from, window.trend_current_to, window.trend_previous_from, window.trend_previous_to, query_counter)
        profit_section = build_profit_section(profit_payload, window.report_date, window.compare_date)
        if profit_section is None:
            excluded_sections.append(_empty_section("profit", "Источник прибыли не вернул данные на отчетную дату."))
        else:
            sections.append(profit_section)
    else:
        excluded_sections.append(_empty_section("profit", "Блок прибыли выключен по параметрам include_profit/include_partial_sections."))

    analysis_highlights = build_highlights_from_analysis(analysis_payload, top_n=payload.top_n)
    highlights = analysis_highlights if (analysis_highlights.worse or analysis_highlights.better or analysis_highlights.priority_checks) else collect_highlights(sections, payload.top_n)
    priority = build_priority_section(highlights, analysis_payload.get("analysis_summary", {}))
    if priority is None:
        excluded_sections.append(_empty_section("priority", "Нет сигналов для приоритетных проверок."))
    else:
        sections.append(priority)
    sections.append(build_scenario_section(highlights, analysis_payload.get("analysis_summary", {})))

    execution_ms = _stage_elapsed_ms(started_at)
    stage_entries = stage_timings + [
        {"stage": "article_context", "ms": _query_ms(query_counter, "article_context")},
        {"stage": "warehouse_context", "ms": _query_ms(query_counter, "warehouse_context")},
        {"stage": "campaign_context", "ms": _query_ms(query_counter, "campaign_context")},
        {"stage": "search_query_context", "ms": _query_ms(query_counter, "search_query_context")},
        {"stage": "entry_point_context", "ms": _query_ms(query_counter, "entry_point_context", "entry_point_context_freshness")},
        {"stage": "price_context", "ms": _query_ms(query_counter, "price_context_site", "price_context_seller_partial")},
        {"stage": "logistics_context", "ms": _query_ms(query_counter, "logistics_context")},
    ]
    query_timings = sorted(query_counter.get("timings", []), key=lambda item: int(item.get("ms") or 0), reverse=True)[:10]
    diagnostics = WbDailyOperationalDiagnosticsResponse(
        included_sections=[section.key for section in sections],
        partial_sections=[section.key for section in sections if section.status in {"PARTIAL", "STALE"}],
        excluded_sections=excluded_sections,
        query_count=int(query_counter["count"]),
        execution_ms=execution_ms,
        query_timings=query_timings,
        formula_version=FORMULA_VERSION,
    )

    response = WbDailyOperationalSummaryResponse(
        formula_version=FORMULA_VERSION,
        report_window=window,
        requested_options={
            "report_date": payload.report_date.isoformat() if payload.report_date else None,
            "mode": payload.mode,
            "include_profit": payload.include_profit,
            "include_partial_sections": payload.include_partial_sections,
            "top_n": payload.top_n,
            "diagnostic": payload.diagnostic,
        },
        source_freshness=source_freshness,
        sections=sections,
        highlights=highlights,
        diagnostics=diagnostics,
        article_context=extended_context.get("article_context", []),
        warehouse_context=extended_context.get("warehouse_context", []),
        campaign_context=extended_context.get("campaign_context", []),
        search_query_context=extended_context.get("search_query_context", []),
        entry_point_context=extended_context.get("entry_point_context", []),
        price_context=extended_context.get("price_context", []),
        logistics_context=extended_context.get("logistics_context", []),
        data_gaps=combined_data_gaps,
        article_analysis=analysis_payload.get("article_analysis", []),
        business_priorities=analysis_payload.get("business_priorities", analysis_payload.get("ranked_signals", [])),
        ranked_signals=analysis_payload.get("ranked_signals", []),
        data_anomalies=analysis_payload.get("data_anomalies", []),
        analysis_summary=analysis_payload.get("analysis_summary", {}),
    )
    if payload.diagnostic:
        stage_started = perf_counter()
        render_wb_daily_operational_summary_markdown(response)
        markdown_ms = _stage_elapsed_ms(stage_started)
        stage_started = perf_counter()
        response.model_dump(mode="json")
        serialization_ms = _stage_elapsed_ms(stage_started)
        response.diagnostics.execution_ms = _stage_elapsed_ms(started_at)
        response.diagnostics.query_timings = (
            stage_entries
            + [
                {"stage": "markdown_formatting", "ms": markdown_ms},
                {"stage": "serialization", "ms": serialization_ms},
                {"stage": "total", "ms": int(response.diagnostics.execution_ms or 0)},
            ]
            + sorted(query_counter.get("timings", []), key=lambda item: int(item.get("ms") or 0), reverse=True)
        )
    return response





