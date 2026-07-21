from __future__ import annotations

from datetime import date
import re
from decimal import Decimal
from typing import Any

from src.mcp_server.schemas import (
    WbDailyOperationalExcludedSectionResponse,
    WbDailyOperationalMetricRowResponse,
    WbDailyOperationalSectionResponse,
    WbDailyOperationalSummaryResponse,
    WbDailyOperationalTableResponse,
)


FINAL_REPORT_COMMENT = "<!-- FINAL_USER_REPORT: Present the complete report below without summarizing, paraphrasing, merging, or omitting sections. -->"
SUMMARY_TITLE = "# ЕЖЕДНЕВНАЯ ОПЕРАТИВНАЯ СВОДКА WILDBERRIES"
NO_DATA_TEXT = "Данных для раздела недостаточно."
NUMBER_RE = re.compile(r"-?\d+(?:[.,]\d+)?")


def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None


def _quantized_decimal(value: Any, decimals: int = 0) -> Decimal | None:
    decimal_value = _as_decimal(value)
    if decimal_value is None:
        return None
    quant = Decimal("1") if decimals == 0 else Decimal("1." + ("0" * decimals))
    quantized = decimal_value.quantize(quant)
    if quantized == 0:
        quantized = abs(quantized)
    return quantized


def _format_date(value: Any) -> str:
    if value is None:
        return "н/д"
    if isinstance(value, str):
        try:
            value = date.fromisoformat(value[:10])
        except ValueError:
            return value
    return value.strftime("%d.%m.%Y")


def _format_number(value: Any, *, decimals: int = 0) -> str:
    decimal_value = _quantized_decimal(value, decimals)
    if decimal_value is None:
        return "н/д"
    text = f"{decimal_value:,.{decimals}f}"
    return text.replace(",", "_").replace(".", ",").replace("_", " ")


def _format_signed_number(value: Any, *, decimals: int = 1) -> str:
    decimal_value = _quantized_decimal(value, decimals)
    if decimal_value is None:
        return "н/д"
    prefix = "+" if decimal_value > 0 else ""
    return f"{prefix}{_format_number(decimal_value, decimals=decimals)}"


def _format_percent(value: Any, *, decimals: int = 1) -> str:
    decimal_value = _quantized_decimal(value, decimals)
    if decimal_value is None:
        return "н/д"
    return f"{_format_number(decimal_value, decimals=decimals)}%"


def _format_pp(value: Any, *, decimals: int = 1) -> str:
    decimal_value = _quantized_decimal(value, decimals)
    if decimal_value is None:
        return "н/д"
    prefix = "+" if decimal_value > 0 else ""
    return f"{prefix}{_format_number(decimal_value, decimals=decimals)} п.п."


def _format_currency(value: Any) -> str:
    decimal_value = _quantized_decimal(value, 0)
    if decimal_value is None:
        return "н/д"
    return f"{_format_number(decimal_value, decimals=0)} ₽"


def _format_delta_pct(value: Any) -> str:
    decimal_value = _quantized_decimal(value, 1)
    if decimal_value is None:
        return "н/д"
    prefix = "+" if decimal_value > 0 else ""
    return f"{prefix}{_format_number(decimal_value, decimals=1)}%"


def _format_days_supply(value: Any) -> str:
    decimal_value = _quantized_decimal(value, 0)
    if decimal_value is None:
        return "н/д"
    number = int(decimal_value)
    remainder_100 = number % 100
    remainder_10 = number % 10
    if 11 <= remainder_100 <= 14:
        suffix = "дней"
    elif remainder_10 == 1:
        suffix = "день"
    elif 2 <= remainder_10 <= 4:
        suffix = "дня"
    else:
        suffix = "дней"
    return f"{_format_number(decimal_value, decimals=0)} {suffix}"


def _metric_category(metric: str) -> str:
    label = metric.lower()
    if "позиц" in label:
        return "position"
    if any(keyword in label for keyword in ("ctr", "конверсия", "доля", "drr", "дрр", "видимость")):
        return "percent"
    if any(keyword in label for keyword in ("cpc", "cpm", "cpo", "чек", "оборот", "расход", "списан", "прибыль", "сумма", "стоимость")):
        return "currency"
    return "number"


def _format_metric_value(metric: str, value: Any) -> str:
    category = _metric_category(metric)
    if category == "position":
        return _format_number(value, decimals=1)
    if category == "percent":
        return _format_percent(value)
    if category == "currency":
        return _format_currency(value)
    return _format_number(value, decimals=0)


def _format_metric_change(metric_row: WbDailyOperationalMetricRowResponse) -> str:
    metric = metric_row.metric
    category = _metric_category(metric)
    if category == "position":
        raw_value = metric_row.delta_abs if metric_row.delta_abs is not None else metric_row.delta_pp
        return _format_signed_number(raw_value, decimals=1)
    if metric_row.delta_pp is not None:
        return _format_pp(metric_row.delta_pp)
    if category == "currency" and metric_row.delta_abs is not None:
        return _format_currency(metric_row.delta_abs)
    if metric_row.delta_pct is not None:
        return _format_delta_pct(metric_row.delta_pct)
    if metric_row.delta_abs is not None:
        decimal_value = _as_decimal(metric_row.delta_abs)
        decimals = 1 if decimal_value not in (None, Decimal("0")) and decimal_value % 1 != 0 else 0
        return _format_signed_number(metric_row.delta_abs, decimals=decimals)
    return "н/д"


def _format_metric_trend(metric_row: WbDailyOperationalMetricRowResponse) -> str:
    metric = metric_row.metric
    category = _metric_category(metric)
    if category == "position":
        raw_value = metric_row.trend_7d_pp if metric_row.trend_7d_pp is not None else metric_row.trend_7d_pct
        return _format_signed_number(raw_value, decimals=1)
    if metric_row.trend_7d_pp is not None:
        return _format_pp(metric_row.trend_7d_pp)
    if metric_row.trend_7d_pct is not None:
        return _format_delta_pct(metric_row.trend_7d_pct)
    return "н/д"


def _render_markdown_table(columns: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def _render_metric_table(metric_rows: list[WbDailyOperationalMetricRowResponse]) -> str:
    rows = [
        [
            metric.metric,
            _format_metric_value(metric.metric, metric.value),
            _format_metric_change(metric),
            _format_metric_trend(metric),
        ]
        for metric in metric_rows
    ]
    return _render_markdown_table(
        ["Показатель", "Значение", "За сутки", "К предыдущим 7 дням"],
        rows,
    )


def _find_section(response: WbDailyOperationalSummaryResponse, *keys: str) -> WbDailyOperationalSectionResponse | None:
    key_set = set(keys)
    for section in response.sections:
        if section.key in key_set:
            return section
    return None


def _find_excluded(response: WbDailyOperationalSummaryResponse, *keys: str) -> WbDailyOperationalExcludedSectionResponse | None:
    key_set = set(keys)
    for section in response.diagnostics.excluded_sections:
        if section.key in key_set:
            return section
    return None


def _metric_by_name(section: WbDailyOperationalSectionResponse | None, metric_name: str) -> WbDailyOperationalMetricRowResponse | None:
    if section is None:
        return None
    for metric in section.metrics:
        if metric.metric == metric_name:
            return metric
    return None


def _first_metric(response: WbDailyOperationalSummaryResponse, metric_name: str, *section_keys: str) -> WbDailyOperationalMetricRowResponse | None:
    for key in section_keys:
        metric = _metric_by_name(_find_section(response, key), metric_name)
        if metric is not None:
            return metric
    return None


def _table_by_title(section: WbDailyOperationalSectionResponse | None, title: str) -> WbDailyOperationalTableResponse | None:
    if section is None:
        return None
    for table in section.tables:
        if table.title == title:
            return table
    return None


def _parse_number(value: Any) -> Decimal | None:
    decimal_value = _as_decimal(value)
    if decimal_value is not None:
        return decimal_value
    if value is None:
        return None
    text = str(value).replace("−", "-").replace("₽", "").replace("%", "").replace("п.п.", "").replace("дн.", "")
    text = text.replace(" ", "").replace(",", ".")
    match = NUMBER_RE.search(text)
    if not match:
        return None
    try:
        return Decimal(match.group(0))
    except Exception:
        return None


def _project_rows(table: WbDailyOperationalTableResponse | None, columns: list[str], *, limit: int) -> list[list[str]]:
    if table is None or not table.rows:
        return []
    projected: list[list[str]] = []
    for row in table.rows[:limit]:
        rendered_row = [str(row.get(column, "")) for column in columns]
        if any(cell.strip() for cell in rendered_row):
            projected.append(rendered_row)
    return projected


def _short_text(value: Any, *, limit: int = 90) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: limit - 1].rstrip() + "…"


def _signal_anchor(signal: dict[str, Any]) -> str:
    if signal.get("nm_id") is not None:
        return f"артикул {signal.get('nm_id')}"
    if signal.get("advert_id") is not None:
        return f"кампания {signal.get('advert_id')}"
    if signal.get("search_query"):
        return f"запрос «{signal.get('search_query')}»"
    if signal.get("warehouse_name"):
        return f"склад {signal.get('warehouse_name')}"
    return "объект"


def _support_phrase(signal: dict[str, Any]) -> str | None:
    kind = str(signal.get("kind") or "")
    if kind == "traffic":
        return "снижение сопровождается просадкой трафика и кликов"
    if kind == "search":
        query = signal.get("search_query")
        if query:
            return f"снижение подтверждается ухудшением поиска по запросу «{query}»"
        return "снижение подтверждается ухудшением поисковых метрик"
    if kind == "ads":
        advert_id = signal.get("advert_id")
        if advert_id is not None:
            return f"рекламный риск заметен в кампании {advert_id}"
        return "рекламная эффективность ухудшилась"
    if kind == "stock":
        return "есть риск дефицита по остаткам"
    if kind == "price":
        return "изменение цены требует отдельной проверки"
    if kind == "large_turnover_loss":
        return "это один из крупнейших вкладов в общее снижение оборота"
    if kind == "large_turnover_growth":
        return "это один из крупнейших вкладов в общий рост оборота"
    return None


def _signal_reason(signal: dict[str, Any]) -> str:
    impact = _as_decimal(signal.get("impact_rub"))
    direction = str(signal.get("direction") or "")
    anchor = _signal_anchor(signal)
    parts: list[str] = []
    if impact is not None and impact != 0 and direction in {"negative", "positive"}:
        effect = "потерю оборота" if direction == "negative" else "прирост оборота"
        parts.append(f"{anchor} дал {effect} {_format_currency(impact)}")
    else:
        summary = str(signal.get("summary") or signal.get("title") or anchor).strip()
        if summary:
            parts.append(summary.rstrip("."))
    phrases: list[str] = []
    phrase = _support_phrase(signal)
    if phrase:
        phrases.append(phrase)
    for item in signal.get("supporting_signals") or []:
        if not isinstance(item, dict):
            continue
        nested = _support_phrase(item)
        if nested and nested not in phrases:
            phrases.append(nested)
    if phrases:
        parts.append(phrases[0])
    elif signal.get("cause_status") != "confirmed":
        parts.append("причина требует проверки")
    return "; ".join(part for part in parts if part)


def _is_user_visible(signal: dict[str, Any]) -> bool:
    return bool(signal.get("user_visible", True))


def _format_action_number(val: Any, decimals: int = 0) -> str:
    if val is None:
        return "н/д"
    try:
        dec = Decimal(str(val))
    except Exception:
        return str(val)
    quant = Decimal("1") if decimals == 0 else Decimal("1." + ("0" * decimals))
    dec = dec.quantize(quant)
    text = f"{dec:,.{decimals}f}"
    return text.replace(",", " ").replace(".", ",").replace("-", "−")


def _format_action_currency(val: Any) -> str:
    if val is None:
        return "н/д"
    return f"{_format_action_number(val, 0)} ₽"


def _format_action_percent(val: Any, decimals: int = 1) -> str:
    if val is None:
        return "н/д"
    try:
        val_str = str(val).replace("%", "").strip()
        dec = Decimal(val_str)
        return f"{_format_action_number(dec, decimals)}%"
    except Exception:
        return f"{_format_action_number(val, decimals)}%"


def _get_days_of_supply_from_stock_table(response: WbDailyOperationalSummaryResponse, nm_id: Any) -> int | None:
    stock_section = _find_section(response, "stock")
    if stock_section is None or not stock_section.tables:
        return None
    for table in stock_section.tables:
        if table.title == "Складские риски":
            for row in table.rows:
                if str(row.get("Артикул")) == str(nm_id):
                    val_str = str(row.get("Оценка запаса") or "")
                    match = re.search(r'\d+', val_str)
                    if match:
                        return int(match.group(0))
    return None


def _build_actions(response: WbDailyOperationalSummaryResponse, *, limit: int) -> list[str]:
    # P1 Profit candidate
    profit = _first_metric(response, "Операционная прибыль", "profit")
    profit_cand = None
    if profit is not None:
        profit_val = _as_decimal(profit.value)
        profit_delta = _as_decimal(profit.delta_abs)
        profit_trend = _as_decimal(profit.trend_7d_pct if profit.trend_7d_pct is not None else profit.trend_7d_pp)
        
        is_p1_active = False
        text = ""
        if profit_val is not None and profit_val < 0:
            is_p1_active = True
            text = f"Проверить причины отрицательной прибыли по VVBromo: {_format_action_currency(profit_val)}."
        elif profit_delta is not None and profit_delta < -1000:
            is_p1_active = True
            text = f"Проверить причины снижения прибыли по VVBromo: на {_format_action_currency(profit_delta)}."
        elif profit_trend is not None and profit_trend < -10:
            is_p1_active = True
            text = "Проверить причины падения прибыли по VVBromo к предыдущей неделе."
            
        if is_p1_active and text:
            profit_cand = {
                "category": "P1",
                "score": Decimal("1000"),
                "text": text
            }

    # P2 Ads candidate
    drr_metric = _first_metric(response, "ДРР (по кампаниям)", "ads")
    if drr_metric is None:
        drr_metric = _first_metric(response, "Доля расходов по кампаниям от оборота", "ads")
    cpo_metric = _first_metric(response, "CPO", "ads")
    ad_orders_metric = _first_metric(response, "Рекламные заказы", "ads")
    ad_spend_metric = _first_metric(response, "Расход по статистике кампаний", "ads")
    
    drr_val = _as_decimal(drr_metric.value) if drr_metric is not None else None
    drr_delta_pp = _as_decimal(drr_metric.delta_pp) if drr_metric is not None else None
    cpo_val = _as_decimal(cpo_metric.value) if cpo_metric is not None else None
    cpo_delta_pct = _as_decimal(cpo_metric.delta_pct) if cpo_metric is not None else None
    cpo_delta_abs = _as_decimal(cpo_metric.delta_abs) if cpo_metric is not None else None
    ad_orders_delta_pct = _as_decimal(ad_orders_metric.delta_pct) if ad_orders_metric is not None else None
    ad_spend_delta_pct = _as_decimal(ad_spend_metric.delta_pct) if ad_spend_metric is not None else None
    
    drr_worse = drr_delta_pp is not None and drr_delta_pp > 0
    cpo_worse = (cpo_delta_pct is not None and cpo_delta_pct > 0) or (cpo_delta_abs is not None and cpo_delta_abs > 0)
    ad_orders_worse = ad_orders_delta_pct is not None and ad_orders_delta_pct < 0
    
    spend_preservation_worse = False
    if ad_spend_delta_pct is not None and ad_spend_delta_pct >= -10:
        if ad_orders_delta_pct is None or ad_orders_delta_pct <= ad_spend_delta_pct - 5:
            spend_preservation_worse = True
            
    worsening_count = sum([drr_worse, cpo_worse, ad_orders_worse, spend_preservation_worse])
    
    ads_cand = None
    if worsening_count >= 2:
        parts = []
        if drr_val is not None:
            parts.append(f"ДРР {_format_action_percent(drr_val)}")
        if cpo_val is not None:
            parts.append(f"CPO {_format_action_currency(cpo_val)}")
        if ad_orders_delta_pct is not None:
            parts.append(f"рекламные заказы {_format_action_percent(ad_orders_delta_pct)} за сутки")
            
        if parts:
            text = f"Пересмотреть рекламу: {', '.join(parts)}."
            ads_cand = {
                "category": "P2",
                "score": Decimal("900"),
                "text": text
            }

    # P3, P4, P5 candidates from response.business_priorities
    p3_cand = None
    p4_cand = None
    p5_cand = None
    
    for signal in response.business_priorities:
        if not isinstance(signal, dict) or not _is_user_visible(signal):
            continue
        kind = signal.get("kind")
        direction = signal.get("direction")
        nm_id = signal.get("nm_id")
        if nm_id is None:
            continue
            
        score = Decimal(str(signal.get("score") or "0"))
        
        if kind == "stock":
            days = _get_days_of_supply_from_stock_table(response, nm_id)
            adj_score = score + (Decimal("100") if (days is not None and days <= 3) else Decimal("0"))
            if p3_cand is None or adj_score > p3_cand["score"]:
                days_str = _format_days_supply(days) if days is not None else None
                text = f"Проверить остатки {nm_id}: запас {days_str}." if days_str else f"Проверить дефицит и остатки по артикулу {nm_id}."
                p3_cand = {"category": "P3", "score": adj_score, "text": text, "nm_id": nm_id}
                
        elif direction == "negative" and kind in {"large_turnover_loss", "traffic", "search", "price"}:
            if p4_cand is None or score > p4_cand["score"]:
                query = signal.get("search_query")
                if kind == "search" and query:
                    text = f"Проверить видимость в поиске артикула {nm_id} по запросу «{query}»."
                else:
                    text = f"Выявить причины снижения продаж по артикулу {nm_id}."
                p4_cand = {"category": "P4", "score": score, "text": text, "nm_id": nm_id}
                
        elif direction == "positive" and kind in {"article_growth", "large_turnover_growth"}:
            if p5_cand is None or score > p5_cand["score"]:
                text = f"Проверить устойчивость роста по артикулу {nm_id}."
                p5_cand = {"category": "P5", "score": score, "text": text, "nm_id": nm_id}

    # Select actions
    selected_actions = []
    
    # P1 and P2 are higher priority and selected first
    if profit_cand is not None:
        selected_actions.append(profit_cand)
    if ads_cand is not None:
        selected_actions.append(ads_cand)
        
    # Remaining slots filled by competing P3, P4, P5 by score
    competing_candidates = []
    if p3_cand is not None:
        competing_candidates.append(p3_cand)
    if p4_cand is not None:
        competing_candidates.append(p4_cand)
    if p5_cand is not None:
        competing_candidates.append(p5_cand)
        
    competing_candidates.sort(key=lambda x: x["score"], reverse=True)
    
    for cand in competing_candidates:
        if len(selected_actions) >= limit:
            break
        selected_actions.append(cand)
        
    return [act["text"] for act in selected_actions]


def _build_day_summary(response: WbDailyOperationalSummaryResponse) -> list[str]:
    lines: list[str] = []
    turnover = _first_metric(response, "Оборот заказов", "sales", "overview")
    orders = _first_metric(response, "Заказы", "sales", "funnel", "overview")
    profit = _first_metric(response, "Операционная прибыль", "profit")
    assortment = _find_section(response, "assortment")
    growth_table = _table_by_title(assortment, "ТОП роста")
    decline_table = _table_by_title(assortment, "ТОП падения")

    if turnover is not None:
        lines.append(
            f"Оборот заказов {_format_metric_value(turnover.metric, turnover.value)}, за сутки {_format_metric_change(turnover)}, к предыдущим 7 дням {_format_metric_trend(turnover)}."
        )
    if orders is not None:
        lines.append(
            f"Заказы {_format_metric_value(orders.metric, orders.value)}, за сутки {_format_metric_change(orders)}, к предыдущим 7 дням {_format_metric_trend(orders)}."
        )
    if profit is not None:
        lines.append(
            f"Операционная прибыль по VVBromo {_format_metric_value(profit.metric, profit.value)}, за сутки {_format_metric_change(profit)}, к предыдущим 7 дням {_format_metric_trend(profit)}."
        )
    if decline_table is not None and decline_table.rows and (decline_table.rows[0].get("???????") or decline_table.rows[0].get("???. ???????")):
        row = decline_table.rows[0]
        lines.append(
            f"Основной отрицательный вклад по товарам: артикул {row.get('Артикул')}, {_short_text(row.get('Товар'), limit=48)} — {row.get('Изм. оборота')}."
        )
    if growth_table is not None and growth_table.rows and (growth_table.rows[0].get("???????") or growth_table.rows[0].get("???. ???????")):
        row = growth_table.rows[0]
        lines.append(
            f"Основной положительный вклад по товарам: артикул {row.get('Артикул')}, {_short_text(row.get('Товар'), limit=48)} — {row.get('Изм. оборота')}."
        )

    # Standard lines limit
    result = lines[:5] if len(lines) > 5 else lines

    # Condition-based analytical line
    ad_spend = _first_metric(response, "Фактические рекламные списания", "overview")
    if ad_spend is None:
        ad_spend = _first_metric(response, "Расход по статистике кампаний", "ads")
    ad_orders = _first_metric(response, "Рекламные заказы", "ads")

    turnover_grew = turnover is not None and (
        (turnover.delta_pct is not None and turnover.delta_pct > 0) or
        (turnover.delta_abs is not None and turnover.delta_abs > 0)
    )
    orders_grew = orders is not None and (
        (orders.delta_pct is not None and orders.delta_pct > 0) or
        (orders.delta_abs is not None and orders.delta_abs > 0)
    )
    cond_1 = turnover_grew or orders_grew

    turnover_trend_neg = turnover is not None and (
        (turnover.trend_7d_pct is not None and turnover.trend_7d_pct < 0) or
        (turnover.trend_7d_pp is not None and turnover.trend_7d_pp < 0)
    )
    orders_trend_neg = orders is not None and (
        (orders.trend_7d_pct is not None and orders.trend_7d_pct < 0) or
        (orders.trend_7d_pp is not None and orders.trend_7d_pp < 0)
    )
    cond_2 = turnover_trend_neg or orders_trend_neg

    ad_spend_change_pct = None
    if ad_spend is not None:
        if ad_spend.delta_pct is not None:
            ad_spend_change_pct = ad_spend.delta_pct
        elif ad_spend.delta_abs is not None and ad_spend.previous_value not in (None, 0, Decimal("0")):
            ad_spend_change_pct = (Decimal(str(ad_spend.delta_abs)) / Decimal(str(ad_spend.previous_value))) * 100
    
    cond_3 = ad_spend is not None and (ad_spend_change_pct is None or ad_spend_change_pct >= -10)

    ad_orders_change_pct = None
    if ad_orders is not None:
        if ad_orders.delta_pct is not None:
            ad_orders_change_pct = ad_orders.delta_pct
        elif ad_orders.delta_abs is not None and ad_orders.previous_value not in (None, 0, Decimal("0")):
            ad_orders_change_pct = (Decimal(str(ad_orders.delta_abs)) / Decimal(str(ad_orders.previous_value))) * 100

    cond_4 = ad_orders is not None and ad_orders_change_pct is not None and ad_orders_change_pct < 0

    profit_val = _as_decimal(profit.value) if profit is not None else None
    profit_delta = _as_decimal(profit.delta_abs) if profit is not None else None
    cond_5 = profit is not None and (
        (profit_val is not None and profit_val < 0) or
        (profit_delta is not None and profit_delta < 0)
    )

    if cond_1 and cond_2 and cond_3 and cond_4 and cond_5:
        result.append(
            "Продажи восстановились относительно предыдущего дня, но недельная динамика остаётся отрицательной; "
            "рост рекламных расходов не дал сопоставимого роста рекламных заказов, поэтому прибыль по VVBromo "
            "осталась отрицательной."
        )

    return result or ["Выраженных отклонений по ключевым метрикам не обнаружено."]


def _build_key_metrics(response: WbDailyOperationalSummaryResponse) -> list[WbDailyOperationalMetricRowResponse]:
    order = [
        ("Оборот заказов", ("sales", "overview")),
        ("Заказы", ("sales", "funnel", "overview")),
        ("Общие показы", ("traffic",)),
        ("Общие клики", ("traffic",)),
        ("CTR общий", ("traffic",)),
        ("Корзины", ("funnel",)),
        ("Конверсия в корзину", ("funnel",)),
        ("Конверсия в заказ", ("funnel",)),
        ("Средний чек", ("sales", "funnel")),
        ("Фактические рекламные списания", ("overview",)),
    ]
    rows: list[WbDailyOperationalMetricRowResponse] = []
    for metric_name, section_keys in order:
        metric = _first_metric(response, metric_name, *section_keys)
        if metric is not None:
            rows.append(metric)
    return rows


def _campaign_priority(row: dict[str, Any]) -> tuple[int, Decimal, str]:
    issue = str(row.get("Проблема") or "")
    if "заказов нет" in issue.lower():
        severity = 3
    elif "drr" in issue.lower() or "дрр" in issue.lower():
        severity = 2
    elif "растет быстрее" in issue.lower() or "растёт быстрее" in issue.lower():
        severity = 1
    else:
        severity = 0
    spend = _parse_number(row.get("Расход")) or Decimal("0")
    return (-severity, -spend, str(row.get("Кампания") or ""))


def _build_problem_campaign_rows(section: WbDailyOperationalSectionResponse | None, *, limit: int) -> list[list[str]]:
    table = _table_by_title(section, "?????????? ????????")
    if table is None or not table.rows:
        return []
    rows = sorted(table.rows, key=_campaign_priority)[:limit]
    projected: list[list[str]] = []
    for row in rows:
        rendered_row = [
            str(row.get("????????", "")),
            str(row.get("Advert ID", "")),
            str(row.get("??????", "")),
            str(row.get("???", "")),
            str(row.get("??????", "")),
            str(row.get("????????", "")),
        ]
        if any(cell.strip() for cell in rendered_row):
            projected.append(rendered_row)
    return projected


def _build_stock_rows(response: WbDailyOperationalSummaryResponse, *, limit: int) -> list[list[str]]:
    priority_nm_ids: set[int] = set()
    for signal in response.business_priorities:
        if not isinstance(signal, dict):
            continue
        kind = str(signal.get("kind") or "")
        if kind == "stock" or "stock" in [str(item) for item in (signal.get("supported_factors") or [])]:
            try:
                priority_nm_ids.add(int(signal.get("nm_id")))
            except (TypeError, ValueError):
                continue

    ranked: list[tuple[tuple[int, Decimal, int], list[str]]] = []
    for article in response.article_analysis:
        if not isinstance(article, dict):
            continue
        nm_id = article.get("nm_id")
        stock = article.get("stock") or {}
        warehouse_rows = stock.get("warehouse_rows") or []
        total_stock = _as_decimal(stock.get("stock_qty_same_day"))
        avg_orders = _as_decimal(((article.get("funnel") or {}).get("order_count_baseline") or {}).get("avg_prev_7"))
        for row in warehouse_rows:
            candidate_total = _as_decimal(row.get("total_stock_qty"))
            if candidate_total is not None:
                total_stock = candidate_total
                break
        for row in warehouse_rows:
            candidate_avg = _as_decimal(row.get("avg_orders_7d_article"))
            if candidate_avg is not None:
                avg_orders = candidate_avg
                break
        if total_stock is None and avg_orders is None:
            continue
        days_of_supply = None if avg_orders in (None, Decimal("0")) or total_stock is None else total_stock / avg_orders
        with_stock = int(stock.get("warehouses_with_stock") or 0)
        zero_stock = int(stock.get("warehouses_zero_stock") or 0)
        is_relevant = (
            (nm_id is not None and int(nm_id) in priority_nm_ids)
            or (total_stock is not None and total_stock <= 0)
            or (days_of_supply is not None and days_of_supply <= Decimal("7"))
            or zero_stock > 0
        )
        if not is_relevant:
            continue
        if total_stock is not None and total_stock <= 0:
            severity = 0
        elif days_of_supply is not None and days_of_supply <= Decimal("3"):
            severity = 1
        elif days_of_supply is not None and days_of_supply <= Decimal("7"):
            severity = 2
        else:
            severity = 3
        ranked.append(
            (
                (severity, days_of_supply if days_of_supply is not None else Decimal("999999"), -zero_stock),
                [
                    str(nm_id or ""),
                    _short_text(article.get("title"), limit=48),
                    _format_number(total_stock, decimals=0),
                    _format_number(avg_orders, decimals=1),
                    _format_days_supply(days_of_supply),
                    _format_number(with_stock, decimals=0),
                    _format_number(zero_stock, decimals=0),
                ],
            )
        )
    ranked.sort(key=lambda item: item[0])
    return [row for _, row in ranked[:limit]]


def _format_search_delta(value: Any) -> str:
    decimal_value = _as_decimal(value)
    if decimal_value is None:
        return "н/д"
    label = "улучшение" if decimal_value < 0 else "ухудшение"
    return f"{_format_signed_number(decimal_value, decimals=1)} позиции — {label}"


def _build_search_rows(table: WbDailyOperationalTableResponse | None, *, limit: int) -> list[list[str]]:
    if table is None or not table.rows:
        return []
    rows: list[tuple[Decimal, list[str]]] = []
    for row in table.rows:
        current_position = _parse_number(row.get("Позиция"))
        previous_position = _parse_number(row.get("Пред. позиция"))
        visibility = _parse_number(row.get("Видимость")) or Decimal("0")
        clicks = _parse_number(row.get("Поисковые клики")) or Decimal("0")
        orders = _parse_number(row.get("Поисковые заказы")) or Decimal("0")
        delta = _parse_number(row.get("Изм. позиции"))
        if current_position in (None, Decimal("0")):
            continue
        if previous_position in (None, Decimal("0")):
            continue
        if visibility == 0 and clicks == 0 and orders == 0:
            continue
        if delta is None:
            continue
        rows.append(
            (
                abs(delta),
                [
                    str(row.get("Артикул", "")),
                    _short_text(row.get("Товар"), limit=48),
                    _format_search_delta(delta),
                    str(row.get("Видимость", "")),
                    str(row.get("Поисковые клики", "")),
                    str(row.get("Поисковые заказы", "")),
                ],
            )
        )
    rows.sort(key=lambda item: item[0], reverse=True)
    return [row for _, row in rows[:limit]]


def _collect_quality_warnings(response: WbDailyOperationalSummaryResponse, *, limit: int) -> list[str]:
    warnings: list[str] = []
    seen: set[str] = set()
    for item in response.analysis_summary.get("top_anomalies") or response.data_anomalies:
        if not isinstance(item, dict):
            continue
        summary = " ".join(str(item.get("summary") or "").split()).strip()
        if not summary:
            continue
        normalized = summary.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        warnings.append(summary)
        if len(warnings) >= limit:
            return warnings
    for freshness in response.source_freshness:
        if freshness.status == "OK":
            continue
        text = f"Источник {freshness.source}: статус {freshness.status.lower()}, последняя дата {_format_date(freshness.max_date)}."
        normalized = text.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        warnings.append(text)
        if len(warnings) >= limit:
            break
    return warnings


def _build_external_context_lines(response: WbDailyOperationalSummaryResponse, *, limit: int = 2) -> list[str]:
    context = response.external_context or {}
    ext_status = context.get("external_context_status")
    main_status = context.get("status")

    if ext_status == "sources_unavailable" or main_status in {"UNAVAILABLE", "DISABLED"}:
        return ["— Внешние данные временно недоступны."]

    signals = context.get("signals") or []
    if ext_status == "signals_available" or (main_status == "OK" and signals):
        lines: list[str] = []
        for signal in signals[:limit]:
            if not isinstance(signal, dict):
                continue
            text = signal.get("interpretation") or signal.get("description")
            if not text:
                title = str(signal.get("title") or "").strip()
                if not title:
                    continue
                text = f"{title} — контекстный фактор."
            lines.append(f"— {text}")
        if lines:
            return lines[:limit]

    return ["— Значимых новых внешних сигналов на дату отчёта нет."]


def render_wb_daily_operational_summary_markdown(response: WbDailyOperationalSummaryResponse) -> str:
    window = response.report_window
    mode = response.requested_options.get("mode") or "full"
    diagnostic = bool(response.requested_options.get("diagnostic"))

    lines: list[str] = [
        FINAL_REPORT_COMMENT,
        SUMMARY_TITLE,
        "",
        f"Дата отчёта: {_format_date(window.report_date)}",
        f"Сравнение: {_format_date(window.report_date)} к {_format_date(window.compare_date)}",
        f"Период 7 дней: {_format_date(window.trend_current_from)}–{_format_date(window.trend_current_to)} против {_format_date(window.trend_previous_from)}–{_format_date(window.trend_previous_to)}",
        "",
        "## Итог дня",
    ]
    for sentence in _build_day_summary(response):
        lines.append(f"- {sentence}")
    lines.append("")

    key_metrics = _build_key_metrics(response)
    lines.append("## Ключевые показатели")
    if key_metrics:
        lines.append(_render_metric_table(key_metrics))
    else:
        lines.append(NO_DATA_TEXT)
    lines.append("")
    ads_section = _find_section(response, "ads")
    lines.append("## Рекламная эффективность")
    if ads_section is not None and (ads_section.metrics or ads_section.tables):
        if ads_section.metrics:
            lines.append(_render_metric_table(ads_section.metrics))
        campaign_rows = _build_problem_campaign_rows(ads_section, limit=3) if mode == "full" else []
        if campaign_rows:
            if ads_section.metrics:
                lines.append("")
            lines.append("**Проблемные кампании**")
            lines.append(
                _render_markdown_table(
                    ["Кампания", "Advert ID", "Расход", "ДРР", "Заказы", "Проблема"],
                    campaign_rows,
                )
            )
        elif not ads_section.metrics:
            lines.append(NO_DATA_TEXT)
    else:
        lines.append(NO_DATA_TEXT)
    lines.append("")

    profit_section = _find_section(response, "profit")
    profit_excluded = _find_excluded(response, "profit")
    lines.append("## Операционная прибыль по VVBromo")
    if profit_section is not None and profit_section.metrics:
        lines.append(_render_metric_table(profit_section.metrics))
        note = "Partial: только товары VVBromo."
        if profit_section.status == "STALE":
            note = "Источник partial: данные по VVBromo доступны с отставанием и могут быть неполными."
        lines.append("")
        lines.append(f"- {note}")
    elif profit_excluded is not None:
        reason = "Блок отключён параметром include_profit." if profit_excluded.reason == "include_profit=false" else profit_excluded.reason
        lines.append(f"- {reason}")
    else:
        lines.append(NO_DATA_TEXT)
    lines.append("")

    if mode == "full":
        assortment_section = _find_section(response, "assortment")
        lines.append("## Товары")
        if assortment_section is not None and assortment_section.tables:
            growth_rows = _project_rows(
                _table_by_title(assortment_section, "ТОП роста"),
                ["Артикул", "Товар", "Оборот", "Изм. оборота", "Заказы", "Реклама", "Остаток"],
                limit=3,
            )
            decline_rows = _project_rows(
                _table_by_title(assortment_section, "ТОП падения"),
                ["Артикул", "Товар", "Оборот", "Изм. оборота", "Заказы", "Реклама", "Остаток"],
                limit=3,
            )
            if growth_rows:
                lines.append("**ТОП роста**")
                lines.append(
                    _render_markdown_table(
                        ["Артикул", "Товар", "Оборот", "Изм. оборота", "Заказы", "Реклама", "Остаток"],
                        growth_rows,
                    )
                )
                lines.append("")
            if decline_rows:
                lines.append("**ТОП падения**")
                lines.append(
                    _render_markdown_table(
                        ["Артикул", "Товар", "Оборот", "Изм. оборота", "Заказы", "Реклама", "Остаток"],
                        decline_rows,
                    )
                )
            if not growth_rows and not decline_rows:
                lines.append(NO_DATA_TEXT)
        else:
            lines.append(NO_DATA_TEXT)
        lines.append("")

        lines.append("## Остатки")
        stock_rows = _build_stock_rows(response, limit=3)
        if stock_rows:
            lines.append(
                _render_markdown_table(
                    ["Артикул", "Товар", "Общий остаток", "Средние заказы 7д", "Дней запаса", "Складов с остатком", "Складов без остатка"],
                    stock_rows,
                )
            )
            lines.append("")
            lines.append("- Оценка по общей скорости заказов артикула.")
        else:
            lines.append(NO_DATA_TEXT)
        lines.append("")

        search_section = _find_section(response, "search")
        lines.append("## Поиск")
        search_metrics = search_section.metrics if search_section is not None else []
        if search_metrics:
            lines.append(_render_metric_table(search_metrics))
        else:
            lines.append(NO_DATA_TEXT)
        if search_section is not None:
            improved_rows = _build_search_rows(_table_by_title(search_section, "Улучшение позиции в поиске"), limit=3)
            worsened_rows = _build_search_rows(_table_by_title(search_section, "Ухудшение позиции в поиске"), limit=3)
            if improved_rows:
                lines.append("")
                lines.append("**Подтверждённые улучшения**")
                lines.append(
                    _render_markdown_table(
                        ["Артикул", "Товар", "Изм. позиции", "Видимость", "Поисковые клики", "Поисковые заказы"],
                        improved_rows,
                    )
                )
            if worsened_rows:
                lines.append("")
                lines.append("**Подтверждённые ухудшения**")
                lines.append(
                    _render_markdown_table(
                        ["Артикул", "Товар", "Изм. позиции", "Видимость", "Поисковые клики", "Поисковые заказы"],
                        worsened_rows,
                    )
                )
        lines.append("")

    external_lines = _build_external_context_lines(response)
    if external_lines:
        lines.append("## Внешний фон")
        lines.extend(external_lines)
        lines.append("")

    lines.append("## Действия на день")
    actions = _build_actions(response, limit=3)
    if actions:
        for index, action in enumerate(actions[:3], start=1):
            lines.append(f"{index}. {action}")
    else:
        lines.append("1. Проверить ключевые отклонения по товарам и рекламе: подтверждённых приоритетов для отдельного действия недостаточно.")
    lines.append("")

    quality_warnings = _collect_quality_warnings(response, limit=3)
    if quality_warnings:
        lines.append("## Проверки качества данных")
        for item in quality_warnings:
            lines.append(f"- {item}")
        lines.append("")

    if diagnostic:
        lines.append("## Техническая информация и свежесть источников")
        freshness_rows = [
            [item.source, _format_date(item.max_date), item.status]
            for item in response.source_freshness
        ]
        rendered = _render_markdown_table(["Источник", "Макс. дата", "Статус"], freshness_rows)
        if rendered:
            lines.append(rendered)
            lines.append("")
        for item in response.diagnostics.excluded_sections:
            lines.append(f"- Исключён раздел {item.title}: {item.reason}")
        lines.append("")

    return "\n".join(line for line in lines if line is not None).strip() + "\n"
