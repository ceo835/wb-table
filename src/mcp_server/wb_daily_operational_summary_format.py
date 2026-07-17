from __future__ import annotations

from decimal import Decimal
from typing import Any

from src.mcp_server.schemas import WbDailyOperationalExcludedSectionResponse, WbDailyOperationalSummaryResponse


FINAL_REPORT_COMMENT = "<!-- FINAL_USER_REPORT: Present the complete report below without summarizing, paraphrasing, merging, or omitting sections. -->"
FINAL_REPORT_NOTICE = "Полный отчёт MCP. Все разделы ниже являются частью результата и не должны сокращаться."
SECTION_ALIASES = [
    (("overview",), "Главное за день"),
    (("traffic",), "Трафик и видимость"),
    (("funnel",), "Воронка и конверсия"),
    (("ads",), "Рекламная эффективность"),
    (("sales",), "Продажи и оборот"),
    (("profit",), "Прибыль и расходы"),
    (("stock",), "Остатки и склады"),
    (("assortment",), "Ассортимент"),
    (("search",), "Поиск и видимость"),
    (("priority", "priority_checks"), "Приоритетные проверки"),
    (("scenario",), "Сценарный итог"),
]



def _as_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    if isinstance(value, Decimal):
        return value
    try:
        return Decimal(str(value))
    except Exception:
        return None



def _format_number(value: Any, *, decimals: int = 0) -> str:
    decimal_value = _as_decimal(value)
    if decimal_value is None:
        return "н/д"
    quantized = decimal_value.quantize(Decimal("1")) if decimals == 0 else decimal_value.quantize(Decimal("1." + ("0" * decimals)))
    text = f"{quantized:,.{decimals}f}".replace(",", " ")
    return text



def _format_percent(value: Any, *, decimals: int = 1) -> str:
    decimal_value = _as_decimal(value)
    if decimal_value is None:
        return "н/д"
    return f"{_format_number(decimal_value, decimals=decimals)}%"



def _format_pp(value: Any, *, decimals: int = 1) -> str:
    decimal_value = _as_decimal(value)
    if decimal_value is None:
        return "н/д"
    prefix = "+" if decimal_value > 0 else ""
    return f"{prefix}{_format_number(decimal_value, decimals=decimals)} п.п."



def _format_currency(value: Any) -> str:
    decimal_value = _as_decimal(value)
    if decimal_value is None:
        return "н/д"
    return f"{_format_number(decimal_value, decimals=0)} ₽"



def _format_delta_pct(value: Any) -> str:
    decimal_value = _as_decimal(value)
    if decimal_value is None:
        return "н/д"
    prefix = "+" if decimal_value > 0 else ""
    return f"{prefix}{_format_number(decimal_value, decimals=1)}%"



def _format_metric_row(metric_row) -> list[str]:
    metric = metric_row.metric
    value = metric_row.value
    previous = metric_row.previous_value
    delta_abs = metric_row.delta_abs
    delta_pct = metric_row.delta_pct
    delta_pp = metric_row.delta_pp
    trend_7d_pct = metric_row.trend_7d_pct
    trend_7d_pp = metric_row.trend_7d_pp

    if any(keyword in metric.lower() for keyword in ["ctr", "конверсия", "дrr", "доля", "видимость", "позиция"]):
        value_text = _format_percent(value) if "позиция" not in metric.lower() else _format_number(value, decimals=1)
        previous_text = _format_percent(previous) if "позиция" not in metric.lower() else _format_number(previous, decimals=1)
        delta_text = _format_pp(delta_pp) if delta_pp is not None and "позиция" not in metric.lower() else (_format_number(delta_abs, decimals=1) if "позиция" in metric.lower() else _format_delta_pct(delta_pct))
        trend_text = _format_pp(trend_7d_pp) if trend_7d_pp is not None and "позиция" not in metric.lower() else (_format_number(trend_7d_pp, decimals=1) if trend_7d_pp is not None and "позиция" in metric.lower() else _format_delta_pct(trend_7d_pct))
    elif any(keyword in metric.lower() for keyword in ["cpc", "cpm", "cpo", "чек", "оборот", "расход", "прибыль", "сумма"]):
        value_text = _format_currency(value)
        previous_text = _format_currency(previous)
        delta_text = _format_currency(delta_abs) if delta_abs is not None else _format_delta_pct(delta_pct)
        trend_text = _format_delta_pct(trend_7d_pct)
    else:
        value_text = _format_number(value)
        previous_text = _format_number(previous)
        delta_text = _format_number(delta_abs) if delta_abs is not None else _format_delta_pct(delta_pct)
        trend_text = _format_delta_pct(trend_7d_pct)

    return [metric, value_text, delta_text, trend_text, previous_text]



def _render_markdown_table(columns: list[str], rows: list[list[str]]) -> str:
    if not rows:
        return ""
    header = "| " + " | ".join(columns) + " |"
    divider = "| " + " | ".join(["---"] * len(columns)) + " |"
    body = ["| " + " | ".join(row) + " |" for row in rows]
    return "\n".join([header, divider, *body])


def _format_data_completeness(response: WbDailyOperationalSummaryResponse) -> str:
    stale_or_missing = [item.source for item in response.source_freshness if item.status != "OK"]
    if not stale_or_missing:
        return "core-источники актуальны на отчётную дату"
    return "требует внимания: " + ", ".join(stale_or_missing)


def _find_section(response: WbDailyOperationalSummaryResponse, keys: tuple[str, ...]):
    for section in response.sections:
        if section.key in keys:
            return section
    return None


def _find_excluded(
    response: WbDailyOperationalSummaryResponse,
    keys: tuple[str, ...],
) -> WbDailyOperationalExcludedSectionResponse | None:
    for item in response.diagnostics.excluded_sections:
        if item.key in keys:
            return item
    return None



def render_wb_daily_operational_summary_markdown(response: WbDailyOperationalSummaryResponse) -> str:
    window = response.report_window
    mode = response.requested_options.get("mode") or "full"
    lines: list[str] = [
        FINAL_REPORT_COMMENT,
        FINAL_REPORT_NOTICE,
        "# ЕЖЕДНЕВНАЯ ОПЕРАТИВНАЯ СВОДКА WILDBERRIES",
        "",
        f"Дата отчёта: {window.report_date.isoformat()}",
        f"Сравнение: {window.report_date.isoformat()} против {window.compare_date.isoformat()}",
        f"Период недельного тренда: {window.trend_current_from.isoformat()} - {window.trend_current_to.isoformat()} против {window.trend_previous_from.isoformat()} - {window.trend_previous_to.isoformat()}",
        f"Полнота данных: {_format_data_completeness(response)}",
        "",
    ]

    if response.highlights.worse:
        lines.append("## Что ухудшилось")
        for item in response.highlights.worse:
            lines.append(f"- {item}")
        lines.append("")

    if response.highlights.better:
        lines.append("## Что выросло")
        for item in response.highlights.better:
            lines.append(f"- {item}")
        lines.append("")

    for keys, heading in SECTION_ALIASES:
        section = _find_section(response, keys)
        excluded = _find_excluded(response, keys)
        lines.append(f"## {heading}")

        if section is not None:
            if section.metrics and mode == "full":
                metric_rows = [_format_metric_row(item) for item in section.metrics]
                lines.append(_render_markdown_table(
                    ["Показатель", "Значение", "Изм. за сутки", "Тренд 7 дней", "Пред. день"],
                    metric_rows,
                ))
                lines.append("")
            if section.tables and mode == "full":
                for table in section.tables:
                    lines.append(f"**{table.title}**")
                    table_rows = [[str(row.get(column, "")) for column in table.columns] for row in table.rows]
                    rendered = _render_markdown_table(table.columns, table_rows)
                    lines.append(rendered or "Данных для раздела недостаточно.")
                    lines.append("")
            if section.summary:
                for summary_line in section.summary[:3]:
                    lines.append(f"- {summary_line}")
            else:
                lines.append("Данных для раздела недостаточно.")
            if section.notes and mode == "full":
                for note in section.notes[:2]:
                    lines.append(f"- {note}")
        elif excluded is not None:
            lines.append(f"- {excluded.reason}")
        elif keys == ("priority", "priority_checks") and response.highlights.priority_checks:
            for item in response.highlights.priority_checks:
                lines.append(f"- {item}")
        else:
            lines.append("Данных для раздела недостаточно.")
        lines.append("")

    if response.requested_options.get("diagnostic"):
        lines.append("## Техническая информация и свежесть источников")
        freshness_rows = [
            [item.source, item.max_date.isoformat() if item.max_date else "н/д", item.status]
            for item in response.source_freshness
        ]
        rendered = _render_markdown_table(["Источник", "Макс. дата", "Статус"], freshness_rows)
        if rendered:
            lines.append(rendered)
            lines.append("")
        for item in response.diagnostics.excluded_sections:
            lines.append(f"- Исключен раздел {item.title}: {item.reason}")
        lines.append("")

    return "\n".join(line for line in lines if line is not None).strip() + "\n"
