from __future__ import annotations

from collections import Counter
from datetime import date
from decimal import Decimal, InvalidOperation
import json
import logging
import secrets
from typing import Annotated

from fastapi import Depends, FastAPI, HTTPException, Request, Response, status
from fastapi.responses import JSONResponse
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

from src.mcp_server.schemas import (
    ActiveProductsRequest,
    ActiveProductsResponse,
    DashboardSummaryRequest,
    DashboardSummaryResponse,
    DbHealthResponse,
    ErrorResponse,
    HealthResponse,
    MartSchemaResponse,
    PriceMonitorRequest,
    PriceMonitorResponse,
    ProductMetricsRequest,
    ProductMetricsResponse,
    WbDailyOperationalSummaryRequest,
    WbDailyOperationalSummaryResponse,
)
from src.mcp_server.service import McpRepository, PostgresMcpRepository
from src.mcp_server.wb_daily_operational_summary_format import render_wb_daily_operational_summary_markdown
from src.mcp_server.settings import McpServiceSettings, load_mcp_service_settings


logger = logging.getLogger(__name__)
security = HTTPBearer(auto_error=False)
MCP_PROTOCOL_VERSION = "2025-06-18"
MCP_SERVER_NAME = "wb-dashboard-mcp"
MCP_SERVER_VERSION = "0.1.0"
MAX_PRODUCT_DAILY_LINES = 15
MAX_PRICE_MONITOR_LINES = 10
WB_DAILY_OPERATIONAL_SUMMARY_CONTENT_HINT = (
    "Сформируй краткую ежедневную операционную сводку Wildberries по структурированным данным в structuredContent на русском языке.\n"
    "Не придумывай показатели и не используй fake/mock данные. Используй только предоставленные факты. КАТЕГОРИЧЕСКИ ЗАПРЕЩЕНО использовать причинно-следственные формулировки вроде 'из-за', 'за счет', 'вызвано', 'вследствие', если в данных нет явных декомпозиционных расчетов. Заменяй их описанием одновременных изменений (например, пиши: 'снижение операционной прибыли совпало с...', 'спад оборота сопровождался...'). Не называй операционную прибыль (operating_profit) в рублях 'маржой' или 'процентом маржинальности'. Отрицательную операционную прибыль называй 'убытком'.\n"
    "Общий объем отчета должен укладываться примерно в 1-2 страницы (ориентировочно 400-600 слов, сокращение в 3-4 раза относительно стандартного детального отчета).\n\n"
    "ПРАВИЛА ИСКЛЮЧЕНИЯ ПОВТОРОВ:\n"
    "1. Каждый показатель, метрика или числовой факт приводится в отчете ровно один раз.\n"
    "2. Один и тот же артикул (nm_id) не должен подробно анализироваться или расписываться в нескольких аналитических разделах.\n"
    "3. Не пересказывай в тексте значения из таблиц. Под таблицами пиши только выводы по структуре и трендам.\n"
    "4. Не объясняй общеизвестный смысл показателей (например, не пиши, что такое CTR, CPO или ДРР).\n"
    "5. Недоступные показатели (если они отсутствуют в данных) не выводи отдельными строками с 'н/д', если их отсутствие не критично для трактовки отчета.\n\n"
    "ОТЧЕТ ДОЛЖЕН СОСТОЯТЬ РОВНО ИЗ 5 СОДЕРЖАТЕЛЬНЫХ РАЗДЕЛОВ И ФИНАЛЬНОЙ СТРОКИ:\n\n"
    "1. Итоги дня и недели\n"
    "Сформируй одну компактную таблицу со столбцами:\n"
    "Показатель | За день | Изменение ко вчера | Изменение за неделю\n"
    "При наличии weekly_analysis бери показатели изменения за неделю (оборот, заказы, рекламный расход, операционную прибыль) и классификацию тренда непосредственно из него. Изменение ДРР ко вчера (суточное) и за неделю (недельное) выводи КАТЕГОРИЧЕСКИ только в процентных пунктах (п.п.), а не в процентах (%). Дневное изменение ДРР бери из delta_pp суточной строки ДРР в structuredContent, а недельное — из weekly_analysis.aggregate_metrics.delta.drr_abs. Не подменяй изменение ДРР его текущим значением.\n"
    "Включай строки (только если показатели доступны):\n"
    "- Оборот (используй 'Оборот заказов' или 'Сумма заказов')\n"
    "- Заказы\n"
    "- Средний чек\n"
    "- Операционная прибыль (из operating_profit_context.overall.operating_profit)\n"
    "- Прибыль на единицу (из operating_profit_context.overall.operating_profit_per_unit)\n"
    "- Рекламный расход\n"
    "- ДРР или CPO\n"
    "Под таблицей дай ровно 1-2 предложения:\n"
    "- Главное изменение дня.\n"
    "- Главное изменение недельного тренда (укажи форму тренда из weekly_analysis.trend_quality.order_sum.shape или аналогичную).\n"
    "Не повторяй значения из таблицы в тексте!\n\n"
    "2. Трафик и реклама\n"
    "Сформируй одну таблицу со столбцами:\n"
    "Метрика | Значение | Изменение\n"
    "Строки (если доступны):\n"
    "- Клики\n"
    "- Корзины\n"
    "- Заказы\n"
    "- Клик → корзина\n"
    "- Корзина → заказ\n"
    "- Рекламный расход\n"
    "- ДРР\n"
    "- CPO\n"
    "Под таблицей дай ровно один краткий вывод (например, сравнение темпов роста трафика и заказов).\n"
    "Не расписывай отдельные источники трафика или кампании, если по ним нет критических отклонений.\n\n"
    "3. Главные товарные отклонения\n"
    "Сформируй одну таблицу максимум на 6-8 наиболее значимых по влиянию артикулов.\n"
    "Столбцы:\n"
    "Артикул | Изменение оборота | Операционная прибыль | Рекламный расход или ДРР | Главный сигнал\n"
    "Правила для таблицы:\n"
    "- Один артикул должен занимать ровно одну строку. Если по нему несколько сигналов, объедини их в одной ячейке 'Главный сигнал'.\n"
    "- Включай товары с наибольшим влиянием: крупнейший вклад в прибыль/убыток, рост оборота при убытке, падение оборота при хорошей прибыли, критический ДРР, риск дефицита остатка.\n"
    "Под таблицей дай максимум 3 коротких вывода в виде списка. Не создавай отдельные подробные описания по каждому артикулу.\n\n"
    "4. Цены, СПП и остатки\n"
    "Выводи этот раздел только при наличии значимых сигналов (аномалии цен, отрицательный СПП, критический дефицит остатков). Максимум 3-4 строки текста (списка).\n"
    "Не выводи полные таблицы по всем товарам.\n"
    "Обязательно добавь сноску в конце раздела:\n"
    "* СПП рассчитан только для товаров с единой ценой продавца по всем размерам.\n"
    "Не пиши технические детали про chrt_id.\n\n"
    "5. Что требует внимания\n"
    "Сформируй список из максимум 3 приоритетных и конкретных действий (например, проверить экономику конкретных артикулов, остановить неэффективную кампанию).\n"
    "Действия должны быть измеримыми и вытекать из данных выше. Разрешено кратко сослаться на уже показанные артикулы, но без повторения цифр и выводов.\n"
    "Не пиши общие рекомендации вроде 'улучшить карточку' или 'повысить эффективность'.\n\n"
    "Фокус дня\n"
    "В самом конце отчета выведи одну строку:\n"
    "\"Фокус дня: [одно конкретное стратегическое действие на сегодня на основе данных]\""
)
WB_DAILY_OPERATIONAL_SUMMARY_NORMAL_EXCLUDED_KEYS = frozenset({
    "analysis_summary",
    "check",
    "highlights",
    "legacy_markdown",
    "note",
    "notes",
    "recommended_check",
    "recommended_checks",
    "signals",
    "summary",
})


def _is_wb_daily_operational_summary_diagnostic(tool_result: WbDailyOperationalSummaryResponse) -> bool:
    return bool((tool_result.requested_options or {}).get("diagnostic"))


def _prune_wb_daily_operational_signal_payload(payload: Any) -> Any:
    if isinstance(payload, list):
        return [_prune_wb_daily_operational_signal_payload(item) for item in payload]
    if isinstance(payload, dict):
        result: dict[str, Any] = {}
        for key, value in payload.items():
            if key in WB_DAILY_OPERATIONAL_SUMMARY_NORMAL_EXCLUDED_KEYS:
                continue
            result[key] = _prune_wb_daily_operational_signal_payload(value)
        return result
    return payload


def _build_wb_daily_operational_summary_structured_content(
    tool_result: WbDailyOperationalSummaryResponse,
) -> dict[str, Any]:
    structured = tool_result.model_dump(mode="json")
    if _is_wb_daily_operational_summary_diagnostic(tool_result):
        structured["legacy_markdown"] = render_wb_daily_operational_summary_markdown(tool_result)
        return structured

    structured.pop("analysis_summary", None)
    structured.pop("highlights", None)
    for section in structured.get("sections") or []:
        if not isinstance(section, dict):
            continue
        section.pop("summary", None)
        section.pop("notes", None)
        section.pop("signals", None)
        for metric in section.get("metrics") or []:
            if isinstance(metric, dict):
                metric.pop("note", None)
        for table in section.get("tables") or []:
            if isinstance(table, dict):
                table.pop("note", None)

    for key in ("business_priorities", "ranked_signals", "data_anomalies"):
        if key in structured:
            structured[key] = _prune_wb_daily_operational_signal_payload(structured.get(key) or [])
    return structured


def _tool_schema(model) -> dict:
    schema = model.model_json_schema()
    schema.pop("$defs", None)
    return schema


def build_mcp_tools_catalog() -> list[dict]:
    return [
        {
            "name": "db_health",
            "description": (
                "Проверяет подключение MCP-сервера к PostgreSQL и возвращает количество строк, "
                "минимальную дату и максимальную дату в mart_total_report. Использовать первым "
                "для диагностики подключения. Ответ показывать пользователю короткой таблицей: "
                "rows, min_date, max_date."
            ),
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "get_mart_schema",
            "description": (
                "Возвращает реальную схему таблицы mart_total_report: список колонок и их типы. "
                "Использовать для диагностики, если аналитические MCP tools падают из-за несовпадения "
                "ожидаемых и фактических колонок в production."
            ),
            "inputSchema": {"type": "object", "properties": {}, "additionalProperties": False},
        },
        {
            "name": "get_dashboard_summary",
            "description": (
                "Возвращает агрегированную сводку по витрине mart_total_report за период. "
                "Использовать для вопросов по общей динамике за даты: строки, товары, переходы, "
                "корзины, заказы, сумма заказов, рекламные расходы, стоимость корзины, CPO. "
                "Не использовать для детального вывода по одному товару — для этого есть get_product_metrics."
            ),
            "inputSchema": _tool_schema(DashboardSummaryRequest),
        },
        {
            "name": "get_product_metrics",
            "description": (
                "Возвращает дневные метрики одного товара nm_id за период. Использовать для анализа "
                "конкретного товара по дням: переходы, корзины, заказы, сумма заказов, CTR, "
                "конверсия в корзину, конверсия в заказ, реклама и цены, если доступны. "
                "Ответ пользователю показывать таблицей по дням и кратким выводом."
            ),
            "inputSchema": _tool_schema(ProductMetricsRequest),
        },
        {
            "name": "get_price_monitor",
            "description": (
                "Возвращает результаты мониторинга цен WB по snapshot_date. Использовать для "
                "проверки цен и алертов: сколько товаров проверено, какие товары имеют предупреждения, "
                "какая buyer-visible price и какой статус проверки. При alerts_only=true показывать "
                "только проблемные строки."
            ),
            "inputSchema": _tool_schema(PriceMonitorRequest),
        },
        {
            "name": "get_active_products",
            "description": (
                "Возвращает список активных товаров по scope core, all_tracked или price_monitor. "
                "Использовать для проверки, какой список товаров применяется в аналитике по умолчанию."
            ),
            "inputSchema": _tool_schema(ActiveProductsRequest),
        },
        {
            "name": "get_wb_daily_operational_summary",
            "description": (
                "Use structuredContent as the primary source for the user-facing analysis. "
                "Generate a coherent operational summary in Russian using only facts available in structuredContent. "
                "Do not mechanically copy content[0].text when structuredContent is available. "
                "Use content[0].text only as a fallback when structuredContent is unavailable. "
                "Do not claim causality unless it is confirmed by the provided evidence. "
                "You may describe simultaneous changes and possible factors, clearly marking them as observations or hypotheses."
            ),
            "inputSchema": _tool_schema(WbDailyOperationalSummaryRequest),
        },
    ]


def build_mcp_success_response(request_id, result: dict) -> JSONResponse:
    return JSONResponse({"jsonrpc": "2.0", "id": request_id, "result": result})


def build_mcp_error_response(request_id, code: int, message: str) -> JSONResponse:
    return JSONResponse(
        {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}},
        status_code=200,
    )


def _to_decimal(value) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except (InvalidOperation, ValueError, TypeError):
        return None


def _format_number(value) -> str:
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return "null"
    if decimal_value == decimal_value.to_integral_value():
        return str(int(decimal_value))
    return format(decimal_value.normalize(), "f")


def _format_currency(value) -> str:
    decimal_value = _to_decimal(value)
    if decimal_value is None:
        return "null"
    return format(decimal_value.normalize(), "f")


def _format_date(value: date | str | None) -> str:
    if value is None:
        return "null"
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _format_bool(value: bool | None) -> str:
    if value is None:
        return "null"
    return "true" if value else "false"


def _format_db_health_content(tool_result: DbHealthResponse) -> str:
    return "\n".join(
        [
            "db_health:",
            f"ok: {_format_bool(tool_result.ok)}",
            f"rows: {tool_result.rows}",
            f"min_date: {_format_date(tool_result.min_date)}",
            f"max_date: {_format_date(tool_result.max_date)}",
        ]
    )


def _format_dashboard_summary_content(tool_result: DashboardSummaryResponse) -> str:
    notes_value = "; ".join(tool_result.data_quality.notes) if tool_result.data_quality.notes else "null"
    return "\n".join(
        [
            "dashboard_summary:",
            f"date_from: {_format_date(tool_result.date_from)}",
            f"date_to: {_format_date(tool_result.date_to)}",
            f"rows: {tool_result.rows}",
            f"nm_count: {tool_result.nm_count}",
            f"card_clicks_total: {_format_number(tool_result.card_clicks)}",
            f"cart_count_total: {_format_number(tool_result.cart_count)}",
            f"order_count_total: {_format_number(tool_result.order_count)}",
            f"order_sum_total: {_format_currency(tool_result.order_sum)}",
            f"ad_spend_total: {_format_currency(tool_result.ad_spend)}",
            f"ad_atbs_total: {_format_number(tool_result.ad_atbs)}",
            f"ad_orders_total: {_format_number(tool_result.ad_orders)}",
            f"cost_per_cart_total: {_format_currency(tool_result.cost_per_cart_total)}",
            f"cpo_total: {_format_currency(tool_result.cpo_total)}",
            f"drr: {_format_number(tool_result.drr)}",
            f"partial_rows: {tool_result.data_quality.partial_rows}",
            f"empty_rows: {tool_result.data_quality.empty_rows}",
            f"notes: {notes_value}",
        ]
    )


def _format_mart_schema_content(tool_result: MartSchemaResponse) -> str:
    lines = [
        "mart_schema:",
        f"table_name: {tool_result.table_name}",
        f"columns_count: {len(tool_result.columns)}",
        "columns_tsv:",
        "column_name\tdata_type",
    ]
    for column in tool_result.columns[:20]:
        lines.append(f"{column.column_name}\t{column.data_type}")
    if len(tool_result.columns) > 20:
        lines.append(f"truncated_columns: {len(tool_result.columns) - 20}")
    return "\n".join(lines)


def _format_product_metrics_content(tool_result: ProductMetricsResponse) -> str:
    header = [
        "product:",
        f"nm_id: {tool_result.nm_id}",
        f"supplier_article: {tool_result.supplier_article or 'null'}",
        f"title: {tool_result.product_name or 'null'}",
        f"date_from: {_format_date(tool_result.date_from)}",
        f"date_to: {_format_date(tool_result.date_to)}",
    ]
    order_sum_missing_dates = (
        ",".join(_format_date(item) for item in tool_result.data_quality.order_sum_missing_for_dates)
        if tool_result.data_quality.order_sum_missing_for_dates
        else "null"
    )
    if not tool_result.found:
        return "\n".join(
            header
            + [
                "found: false",
                "",
                "period_meta:",
                f"rows_count: {tool_result.period_meta.rows_count}",
                f"days_requested: {tool_result.period_meta.days_requested}",
                f"days_returned: {tool_result.period_meta.days_returned}",
                "",
                "DATA_QUALITY:",
                f"order_sum_available_dates_count: {tool_result.data_quality.order_sum_available_dates_count}",
                f"order_sum_missing_dates_count: {tool_result.data_quality.order_sum_missing_dates_count}",
                f"order_sum_missing_for_dates: {order_sum_missing_dates}",
                f"order_sum_null_meaning: {tool_result.field_definitions.get('order_sum_null', 'missing_data_not_zero')}",
                f"wb_buyer_price_missing: {_format_bool(tool_result.data_quality.wb_buyer_price_missing)}",
                f"ad_metrics_missing: {_format_bool(tool_result.data_quality.ad_metrics_missing)}",
                f"stock_by_size_missing: {_format_bool(tool_result.data_quality.stock_by_size_missing)}",
                f"delivery_time_missing: {_format_bool(tool_result.data_quality.delivery_time_missing)}",
                (
                    "cannot_calculate_period_ctr_without_impressions: "
                    f"{_format_bool(tool_result.data_quality.cannot_calculate_period_ctr_without_impressions)}"
                ),
                "",
                "SOURCE_COVERAGE:",
                *[f"{key}: {value}" for key, value in tool_result.source_coverage.items()],
                "",
                "ANALYSIS_STATUS:",
                tool_result.analysis_status,
                "",
                "ANALYSIS_LIMITS:",
                *[f"- {item}" for item in tool_result.analysis_limits],
                "",
                "rows_tsv:",
                "date\tcard_clicks\tctr\tcart_count\tadd_to_cart_conversion\torder_count\tcart_to_order_conversion\torder_sum",
            ]
        )

    lines = header + [
        "found: true",
        "",
        "period_meta:",
        f"rows_count: {tool_result.period_meta.rows_count}",
        f"days_requested: {tool_result.period_meta.days_requested}",
        f"days_returned: {tool_result.period_meta.days_returned}",
        "",
        "field_legend:",
        "card_clicks = переходы в карточку",
        "cart_count = корзины",
        "order_count = заказы",
        "order_sum = сумма заказов",
        "ctr = CTR",
        "add_to_cart_conversion = конверсия в корзину",
        "cart_to_order_conversion = конверсия корзина -> заказ",
        "",
        "summary:",
        f"card_clicks_total: {_format_number(tool_result.summary.card_clicks_total)}",
        f"cart_count_total: {_format_number(tool_result.summary.cart_count)}",
        f"order_count_total: {_format_number(tool_result.summary.order_count)}",
        f"order_sum_total: {_format_currency(tool_result.summary.order_sum)}",
        f"ad_spend_total: {_format_currency(tool_result.summary.ad_spend)}",
        f"avg_ctr: {_format_number(tool_result.summary.avg_ctr)}",
        f"avg_add_to_cart_conversion: {_format_number(tool_result.summary.avg_add_to_cart_conversion)}",
        f"avg_cart_to_order_conversion: {_format_number(tool_result.summary.avg_cart_to_order_conversion)}",
        "",
        "DATA_QUALITY:",
        f"order_sum_available_dates_count: {tool_result.data_quality.order_sum_available_dates_count}",
        f"order_sum_missing_dates_count: {tool_result.data_quality.order_sum_missing_dates_count}",
        f"order_sum_missing_for_dates: {order_sum_missing_dates}",
        f"order_sum_null_meaning: {tool_result.field_definitions.get('order_sum_null', 'missing_data_not_zero')}",
        f"wb_buyer_price_missing: {_format_bool(tool_result.data_quality.wb_buyer_price_missing)}",
        f"ad_metrics_missing: {_format_bool(tool_result.data_quality.ad_metrics_missing)}",
        f"stock_by_size_missing: {_format_bool(tool_result.data_quality.stock_by_size_missing)}",
        f"delivery_time_missing: {_format_bool(tool_result.data_quality.delivery_time_missing)}",
        (
            "cannot_calculate_period_ctr_without_impressions: "
            f"{_format_bool(tool_result.data_quality.cannot_calculate_period_ctr_without_impressions)}"
        ),
        "",
        "SOURCE_COVERAGE:",
        *[f"{key}: {value}" for key, value in tool_result.source_coverage.items()],
        "",
        "ANALYSIS_STATUS:",
        tool_result.analysis_status,
        "",
        "ALLOWED_INFERENCES:",
        *[f"- {item}" for item in tool_result.allowed_inferences],
        "",
        "FORBIDDEN_INFERENCES:",
        *[f"- {item}" for item in tool_result.forbidden_inferences],
        "",
        "ANALYSIS_LIMITS:",
        *[f"- {item}" for item in tool_result.analysis_limits],
        "",
        "rows_tsv:",
        "date\tcard_clicks\tctr\tcart_count\tadd_to_cart_conversion\torder_count\tcart_to_order_conversion\torder_sum",
    ]
    daily_rows = tool_result.daily[:MAX_PRODUCT_DAILY_LINES]
    for item in daily_rows:
        lines.append(
            "\t".join(
                [
                    _format_date(item.date),
                    _format_number(item.card_clicks),
                    _format_number(item.ctr),
                    _format_number(item.cart_count),
                    _format_number(item.add_to_cart_conversion),
                    _format_number(item.order_count),
                    _format_number(item.cart_to_order_conversion),
                    _format_currency(item.order_sum),
                ]
            )
        )
    if len(tool_result.daily) > MAX_PRODUCT_DAILY_LINES:
        lines.append(f"truncated_rows: {len(tool_result.daily) - MAX_PRODUCT_DAILY_LINES}")
    return "\n".join(lines)


def _format_price_monitor_content(tool_result: PriceMonitorResponse) -> str:
    title = "price_monitor_alerts_only:" if tool_result.items and all(item.is_alert for item in tool_result.items) else "price_monitor:"
    lines = [title, f"snapshot_date: {_format_date(tool_result.snapshot_date)}"]
    if tool_result.rows == 0:
        lines.extend(
            [
                "rows: 0",
                "alerts: 0",
                "rows_tsv:",
                "nm_id\tsupplier_article\tbuyer_visible_price\tprevious_price\tprice_delta\tfetch_status\tis_alert\tproduct_url",
            ]
        )
        return "\n".join(lines)

    status_counts = Counter(item.fetch_status or "unknown" for item in tool_result.items)
    lines.extend([f"rows: {tool_result.rows}", f"alerts: {tool_result.alerts}"])
    for status_name, count in sorted(status_counts.items()):
        lines.append(f"status_{status_name}: {count}")
    lines.extend(
        [
            "rows_tsv:",
            "nm_id\tsupplier_article\tbuyer_visible_price\tprevious_price\tprice_delta\tfetch_status\tis_alert\tproduct_url",
        ]
    )
    for item in tool_result.items[:MAX_PRICE_MONITOR_LINES]:
        lines.append(
            "\t".join(
                [
                    str(item.nm_id),
                    item.supplier_article or "null",
                    _format_currency(item.buyer_visible_price),
                    _format_currency(item.previous_price),
                    _format_currency(item.price_delta),
                    item.fetch_status or "null",
                    _format_bool(item.is_alert),
                    item.product_url or "null",
                ]
            )
        )
    if len(tool_result.items) > MAX_PRICE_MONITOR_LINES:
        lines.append(f"truncated_rows: {len(tool_result.items) - MAX_PRICE_MONITOR_LINES}")
    return "\n".join(lines)


def _format_active_products_content(tool_result: ActiveProductsResponse) -> str:
    lines = [
        "active_products:",
        f"scope: {tool_result.scope}",
        f"rows: {tool_result.rows}",
        "rows_tsv:",
        "nm_id\tsupplier_article\ttitle\tbrand\tsubject\tanalytics_active\tprice_monitor_enabled\tlifecycle_status\treason",
    ]
    for item in tool_result.items:
        lines.append(
            "\t".join(
                [
                    str(item.nm_id),
                    item.supplier_article or "null",
                    item.title or "null",
                    item.brand or "null",
                    item.subject or item.category or "null",
                    _format_bool(item.analytics_active),
                    _format_bool(item.price_monitor_enabled),
                    item.lifecycle_status or "null",
                    item.reason or "null",
                ]
            )
        )
    return "\n".join(lines)


def _format_tool_content(tool_result) -> str:
    if isinstance(tool_result, DbHealthResponse):
        return _format_db_health_content(tool_result)
    if isinstance(tool_result, MartSchemaResponse):
        return _format_mart_schema_content(tool_result)
    if isinstance(tool_result, DashboardSummaryResponse):
        return _format_dashboard_summary_content(tool_result)
    if isinstance(tool_result, ProductMetricsResponse):
        return _format_product_metrics_content(tool_result)
    if isinstance(tool_result, PriceMonitorResponse):
        return _format_price_monitor_content(tool_result)
    if isinstance(tool_result, ActiveProductsResponse):
        return _format_active_products_content(tool_result)
    if isinstance(tool_result, WbDailyOperationalSummaryResponse):
        return render_wb_daily_operational_summary_markdown(tool_result)
    return json.dumps(tool_result.model_dump(mode="json"), ensure_ascii=False)


def _build_tool_result_payload(tool_result) -> dict:
    try:
        if isinstance(tool_result, WbDailyOperationalSummaryResponse):
            structured = _build_wb_daily_operational_summary_structured_content(tool_result)
            text_content = WB_DAILY_OPERATIONAL_SUMMARY_CONTENT_HINT
        else:
            structured = tool_result.model_dump(mode="json")
            text_content = _format_tool_content(tool_result)
    except Exception:
        logger.exception("Failed to build human-readable MCP content")
        structured = tool_result.model_dump(mode="json")
        text_content = json.dumps(structured, ensure_ascii=False)
    return {
        "content": [
            {
                "type": "text",
                "text": text_content,
            }
        ],
        "structuredContent": structured,
        "isError": False,
    }


def _execute_mcp_tool(name: str, arguments: dict, repository: McpRepository) -> dict:
    if name == "db_health":
        result = repository.get_db_health()
    elif name == "get_mart_schema":
        result = repository.get_mart_schema()
    elif name == "get_dashboard_summary":
        result = repository.get_dashboard_summary(DashboardSummaryRequest.model_validate(arguments))
    elif name == "get_product_metrics":
        result = repository.get_product_metrics(ProductMetricsRequest.model_validate(arguments))
    elif name == "get_price_monitor":
        result = repository.get_price_monitor(PriceMonitorRequest.model_validate(arguments))
    elif name == "get_active_products":
        result = repository.get_active_products(ActiveProductsRequest.model_validate(arguments))
    elif name == "get_wb_daily_operational_summary":
        result = repository.get_wb_daily_operational_summary(WbDailyOperationalSummaryRequest.model_validate(arguments))
    else:
        raise KeyError(name)
    return _build_tool_result_payload(result)


def create_auth_dependency(settings: McpServiceSettings):
    def verify_token(
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    ) -> None:
        if credentials is None or credentials.scheme.lower() != "bearer":
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Missing bearer token.")
        if not secrets.compare_digest(credentials.credentials, settings.auth_token):
            raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid bearer token.")

    return verify_token


def create_app(
    repository: McpRepository | None = None,
    settings: McpServiceSettings | None = None,
) -> FastAPI:
    resolved_settings = settings or load_mcp_service_settings()
    resolved_repository = repository or PostgresMcpRepository(resolved_settings)
    require_auth = create_auth_dependency(resolved_settings)

    app = FastAPI(
        title="WB Dashboard MCP Service",
        version="0.1.0",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
    )

    @app.exception_handler(ValueError)
    async def handle_value_error(_request, exc: ValueError):
        return JSONResponse(
            status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
            content=ErrorResponse(detail=str(exc), code="INVALID_REQUEST").model_dump(mode="json"),
        )

    @app.get("/health", response_model=HealthResponse)
    async def health() -> HealthResponse:
        return HealthResponse(ok=True)

    @app.post("/mcp")
    async def mcp_endpoint(
        request: Request,
        credentials: Annotated[HTTPAuthorizationCredentials | None, Depends(security)],
    ) -> Response:
        if not resolved_settings.mcp_public_mode:
            require_auth(credentials)

        payload = await request.json()
        messages = payload if isinstance(payload, list) else [payload]
        responses: list[dict] = []

        for message in messages:
            request_id = message.get("id")
            method = message.get("method")
            params = message.get("params") or {}

            if method == "notifications/initialized":
                continue

            if method == "initialize":
                responses.append(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {
                            "protocolVersion": MCP_PROTOCOL_VERSION,
                            "capabilities": {
        "tools": {"listChanged": False},
                            },
                            "serverInfo": {
                                "name": MCP_SERVER_NAME,
                                "version": MCP_SERVER_VERSION,
                            },
                        },
                    }
                )
                continue

            if method == "ping":
                responses.append({"jsonrpc": "2.0", "id": request_id, "result": {}})
                continue

            if method == "tools/list":
                responses.append(
                    {
                        "jsonrpc": "2.0",
                        "id": request_id,
                        "result": {"tools": build_mcp_tools_catalog()},
                    }
                )
                continue

            if method == "tools/call":
                tool_name = str(params.get("name") or "")
                arguments = params.get("arguments") or {}
                try:
                    tool_result = _execute_mcp_tool(tool_name, arguments, resolved_repository)
                except KeyError:
                    responses.append(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32601, "message": f"Unknown tool: {tool_name}"},
                        }
                    )
                except ValueError as exc:
                    responses.append(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32602, "message": str(exc)},
                        }
                    )
                except Exception:
                    logger.exception("MCP transport tool call failed: %s", tool_name)
                    responses.append(
                        {
                            "jsonrpc": "2.0",
                            "id": request_id,
                            "error": {"code": -32603, "message": "Internal server error."},
                        }
                    )
                else:
                    responses.append({"jsonrpc": "2.0", "id": request_id, "result": tool_result})
                continue

            responses.append(
                {
                    "jsonrpc": "2.0",
                    "id": request_id,
                    "error": {"code": -32601, "message": f"Method not found: {method}"},
                }
            )

        if not responses:
            return Response(status_code=202)
        if isinstance(payload, list):
            return JSONResponse(responses)
        return JSONResponse(responses[0])

    @app.post(
        "/tools/db_health",
        response_model=DbHealthResponse,
        dependencies=[Depends(require_auth)],
    )
    async def db_health() -> DbHealthResponse:
        try:
            return resolved_repository.get_db_health()
        except Exception:
            logger.exception("MCP tool failed: db_health")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

    @app.post(
        "/tools/get_mart_schema",
        response_model=MartSchemaResponse,
        dependencies=[Depends(require_auth)],
    )
    async def get_mart_schema() -> MartSchemaResponse:
        try:
            return resolved_repository.get_mart_schema()
        except Exception:
            logger.exception("MCP tool failed: get_mart_schema")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

    @app.post(
        "/tools/get_dashboard_summary",
        response_model=DashboardSummaryResponse,
        dependencies=[Depends(require_auth)],
    )
    async def get_dashboard_summary(payload: DashboardSummaryRequest) -> DashboardSummaryResponse:
        try:
            return resolved_repository.get_dashboard_summary(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except Exception:
            logger.exception("MCP tool failed: get_dashboard_summary")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

    @app.post(
        "/tools/get_product_metrics",
        response_model=ProductMetricsResponse,
        dependencies=[Depends(require_auth)],
    )
    async def get_product_metrics(payload: ProductMetricsRequest) -> ProductMetricsResponse:
        try:
            return resolved_repository.get_product_metrics(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except Exception:
            logger.exception("MCP tool failed: get_product_metrics")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

    @app.post(
        "/tools/get_price_monitor",
        response_model=PriceMonitorResponse,
        dependencies=[Depends(require_auth)],
    )
    async def get_price_monitor(payload: PriceMonitorRequest) -> PriceMonitorResponse:
        try:
            return resolved_repository.get_price_monitor(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except Exception:
            logger.exception("MCP tool failed: get_price_monitor")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

    @app.post(
        "/tools/get_active_products",
        response_model=ActiveProductsResponse,
        dependencies=[Depends(require_auth)],
    )
    async def get_active_products(payload: ActiveProductsRequest) -> ActiveProductsResponse:
        try:
            return resolved_repository.get_active_products(payload)
        except ValueError as exc:
            raise HTTPException(status_code=status.HTTP_422_UNPROCESSABLE_ENTITY, detail=str(exc)) from exc
        except Exception:
            logger.exception("MCP tool failed: get_active_products")
            raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Internal server error.")

    return app
