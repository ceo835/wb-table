from __future__ import annotations

import re
from datetime import date, timedelta
from typing import Any, Iterable
from decimal import Decimal

from sqlalchemy import and_, or_, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from src.db.models import ExternalContextEvent, ExternalContextMetric
from src.services.external_context.schemas import ExternalContextResponse, ExternalContextSignalResponse
from src.services.external_context.category_config import CATEGORIES_CONFIG, get_active_categories

from typing import TYPE_CHECKING
if TYPE_CHECKING:
    from src.mcp_server.settings import McpServiceSettings


def _format_decimal(val: Any, decimals: int = 1) -> str:
    if val is None:
        return "н/д"
    try:
        dec = Decimal(str(val))
        quant = Decimal("1") if decimals == 0 else Decimal("1." + ("0" * decimals))
        dec = dec.quantize(quant)
        text = f"{dec:,.{decimals}f}"
        return text.replace(",", " ").replace(".", ",").replace("-", "−")
    except Exception:
        return str(val).replace("-", "−")


CAT_DATIVE_LOWER = {
    "womens_underwear": "женским трусам",
    "childrens_underwear": "детским трусам",
    "womens_tshirts": "женским футболкам",
    "childrens_tshirts": "детским футболкам",
}


class ExternalContextService:
    def __init__(self, session: Session, settings: McpServiceSettings | None = None):
        self.session = session
        if settings is None:
            from src.mcp_server.settings import load_mcp_service_settings
            self.settings = load_mcp_service_settings()
        else:
            self.settings = settings

    def get_external_context(
        self,
        report_date: date,
        period_start: date | None = None,
        period_end: date | None = None,
        categories: Iterable[str] | None = None,
        region: str | None = None,
        max_signals: int = 6,
        category_sales_trends: dict[str, dict[str, Any]] | None = None,
        diagnostic: bool = False,
    ) -> ExternalContextResponse:
        max_signals = max(1, min(int(max_signals), 10))
        resolved_period_start = period_start if period_start is not None else report_date
        resolved_period_end = period_end if period_end is not None else report_date
        if resolved_period_start > resolved_period_end:
            resolved_period_start, resolved_period_end = resolved_period_end, resolved_period_start

        # Initialize source statuses
        sources_status = {
            "calendar": "ok" if self.settings.external_calendar_enabled else "disabled",
            "search_demand": "disabled",
            "consumer_sentiment": "disabled",
            "macro": "disabled",
        }

        if self.settings.external_search_demand_enabled:
            has_credentials = bool(self.settings.yandex_search_api_key or self.settings.yandex_direct_token)
            sources_status["search_demand"] = "ok" if has_credentials else "unavailable"
        if self.settings.external_consumer_sentiment_enabled:
            sources_status["consumer_sentiment"] = "ok"
        if self.settings.external_macro_enabled:
            sources_status["macro"] = "ok"

        # Applied filters mapping for response metadata
        applied_filters = {
            "report_date": report_date.isoformat(),
            "period_start": resolved_period_start.isoformat(),
            "period_end": resolved_period_end.isoformat(),
            "region": region,
            "max_signals": max_signals,
            "diagnostic": diagnostic,
        }

        candidates_p1: list[ExternalContextSignalResponse] = []  # Search demand (Wordstat)
        candidates_p2: list[ExternalContextSignalResponse] = []  # Calendar events
        candidates_p3: list[ExternalContextSignalResponse] = []  # Consumer Sentiment Index
        candidates_p4: list[ExternalContextSignalResponse] = []  # Annual Inflation / Macro

        diag_details: list[dict[str, Any]] = []

        # ----------------------------------------------------
        # 1. P1: Wordstat (Search Demand)
        # ----------------------------------------------------
        if self.settings.external_search_demand_enabled and sources_status["search_demand"] != "disabled":
            try:
                db_metrics = self.session.scalars(
                    select(ExternalContextMetric)
                    .where(
                        ExternalContextMetric.source.in_(["yandex_direct", "yandex_cloud_wordstat"]),
                        ExternalContextMetric.period_start <= resolved_period_end,
                        ExternalContextMetric.period_end >= resolved_period_start,
                    )
                ).all()

                for metric in db_metrics:
                    cat_code = metric.category
                    if not cat_code:
                        continue
                    cat_cfg = next((c for c in CATEGORIES_CONFIG if c["category_code"] == cat_code), None)
                    if not cat_cfg or not cat_cfg["is_active"]:
                        diag_details.append({
                            "source": "search_demand",
                            "metric_code": metric.metric_code,
                            "excluded_reason": "category_inactive",
                        })
                        continue

                    # Freshness for Wordstat: period_end must be within 14 days of report_date
                    days_diff = (report_date - metric.period_end).days
                    if days_diff > 14 or days_diff < 0:
                        diag_details.append({
                            "source": "search_demand",
                            "metric_code": metric.metric_code,
                            "excluded_reason": "stale_period",
                            "days_diff": days_diff,
                        })
                        continue

                    if metric.data_status != "ok":
                        diag_details.append({
                            "source": "search_demand",
                            "metric_code": metric.metric_code,
                            "excluded_reason": "data_status_not_ok",
                        })
                        continue

                    val = metric.value
                    prev_val = metric.previous_value
                    change_pct = metric.change_pct
                    if val is None or prev_val is None or change_pct is None:
                        if prev_val and prev_val > 0:
                            change_pct = ((val - prev_val) / prev_val) * Decimal("100")
                        else:
                            change_pct = Decimal("0")

                    if abs(float(change_pct)) < self.settings.search_demand_min_change_pct:
                        diag_details.append({
                            "source": "search_demand",
                            "metric_code": metric.metric_code,
                            "excluded_reason": "change_pct_below_threshold",
                            "change_pct": float(change_pct),
                        })
                        continue

                    cat_title = cat_cfg["category_title"]
                    cat_dative = CAT_DATIVE_LOWER.get(cat_code, cat_title.lower())

                    # Check category sales trend matching ONLY for the SAME category
                    sales_trend = category_sales_trends.get(cat_code) if (category_sales_trends and isinstance(category_sales_trends, dict)) else None
                    wb_change_pct = Decimal(str(sales_trend.get("change_pct"))) if (sales_trend and sales_trend.get("change_pct") is not None) else None
                    comparison_available = wb_change_pct is not None

                    ext_change = float(change_pct)
                    ext_dir_word = "вырос" if ext_change > 0 else "снизился"
                    ext_abs_pct = abs(int(round(ext_change)))

                    comparison_direction = None
                    selection_reason = None
                    is_selectable = False

                    if comparison_available and wb_change_pct is not None:
                        wb_change = float(wb_change_pct)
                        wb_abs_pct = abs(int(round(wb_change)))

                        if -1.0 < wb_change < 1.0:
                            comparison_direction = "stable_vs_growth" if ext_change > 0 else "stable_vs_decline"
                            relevance = "medium"
                            is_selectable = True
                            selection_reason = "category_matched_wb_stable"
                            short_interpretation = f"Внешний поисковый интерес в Яндексе к {cat_dative} {ext_dir_word} на {ext_abs_pct}%, а продажи категории на WB практически не изменились."
                        elif ext_change > 0 and wb_change >= 1.0:
                            comparison_direction = "matching"
                            relevance = "medium"
                            is_selectable = True
                            selection_reason = "category_matched_same_direction"
                            short_interpretation = f"Внешний поисковый интерес в Яндексе к {cat_dative} и продажи категории на WB растут одновременно."
                        elif ext_change < 0 and wb_change <= -1.0:
                            comparison_direction = "matching"
                            relevance = "medium"
                            is_selectable = True
                            selection_reason = "category_matched_same_direction"
                            short_interpretation = f"Внешний поисковый интерес в Яндексе к {cat_dative} и продажи категории на WB снижаются одновременно."
                        elif ext_change > 0 and wb_change <= -1.0:
                            comparison_direction = "divergent"
                            relevance = "high"
                            is_selectable = True
                            selection_reason = "category_matched_divergent_direction"
                            short_interpretation = f"Внешний поисковый интерес в Яндексе к {cat_dative} вырос на {ext_abs_pct}%, при этом поисковые заказы категории на WB снизились на {wb_abs_pct}%."
                        elif ext_change < 0 and wb_change >= 1.0:
                            comparison_direction = "divergent"
                            relevance = "high"
                            is_selectable = True
                            selection_reason = "category_matched_divergent_direction"
                            short_interpretation = f"Продажи категории {cat_title.lower()} на WB выросли на {wb_abs_pct}% вопреки снижению внешнего поискового интереса в Яндексе на {ext_abs_pct}%."
                        else:
                            comparison_direction = "standalone"
                            is_selectable = abs(ext_change) >= 25.0
                            relevance = "medium" if is_selectable else "low"
                            selection_reason = "standalone_strong_change" if is_selectable else "standalone_normal_change_diagnostic_only"
                            short_interpretation = f"Внешний поисковый интерес в Яндексе к {cat_dative} {ext_dir_word} на {ext_abs_pct}%."
                    else:
                        comparison_direction = "standalone"
                        is_selectable = abs(ext_change) >= 25.0
                        relevance = "medium" if is_selectable else "low"
                        selection_reason = "standalone_strong_change" if is_selectable else "standalone_normal_change_diagnostic_only"
                        short_interpretation = f"Внешний поисковый интерес в Яндексе к {cat_dative} {ext_dir_word} на {ext_abs_pct}%."

                    fresh_until = metric.period_end + timedelta(days=7)
                    pub_date = metric.published_at.date() if metric.published_at else metric.period_end

                    diag_details.append({
                        "source": "search_demand",
                        "metric_code": metric.metric_code,
                        "wordstat_category": cat_code,
                        "wb_category": cat_code if comparison_available else None,
                        "external_change_pct": float(change_pct),
                        "wb_change_pct": float(wb_change_pct) if wb_change_pct is not None else None,
                        "comparison_available": comparison_available,
                        "comparison_direction": comparison_direction,
                        "selection_reason": selection_reason,
                        "is_selectable": is_selectable,
                    })

                    if is_selectable:
                        signal = ExternalContextSignalResponse(
                            source="search_demand",
                            signal_type="demand_change",
                            metric_code=metric.metric_code,
                            title=f"Поисковый спрос: {cat_title}",
                            period_start=metric.period_start,
                            period_end=metric.period_end,
                            value=val,
                            current_value=val,
                            previous_value=prev_val,
                            change_value=val - prev_val if (val is not None and prev_val is not None) else None,
                            change_pct=change_pct,
                            published_at=pub_date,
                            fresh_until=fresh_until,
                            neutral_level=None,
                            category=cat_code,
                            relevance=relevance,
                            confidence_level="context_only",
                            interpretation=short_interpretation,
                            source_reference=metric.source_reference or "Yandex Wordstat",
                            data_status=metric.data_status,
                        )
                        candidates_p1.append(signal)

                # Prioritize Wordstat signals:
                # 1. Discrepancy with WB (relevance="high")
                # 2. Strong category-matched change with WB
                # 3. Standalone strong change without WB comparison
                def _wordstat_priority_key(sig: ExternalContextSignalResponse) -> tuple[int, float]:
                    rel_rank = 2
                    if sig.relevance == "high":
                        rel_rank = 0
                    elif "WB" in (sig.interpretation or ""):
                        rel_rank = 1

                    change_mag = float(abs(sig.change_pct)) if sig.change_pct is not None else 0.0
                    return (rel_rank, -change_mag)

                candidates_p1.sort(key=_wordstat_priority_key)
            except SQLAlchemyError:
                sources_status["search_demand"] = "error"

        # ----------------------------------------------------
        # 2. P2: Calendar Events
        # ----------------------------------------------------
        if self.settings.external_calendar_enabled and sources_status["calendar"] != "disabled":
            try:
                events = self.session.scalars(
                    select(ExternalContextEvent)
                    .where(ExternalContextEvent.is_active.is_(True))
                    .order_by(ExternalContextEvent.date_start.desc())
                ).all()

                for event in events:
                    # Calendar freshness: active from date_start - 3 days to date_end + 2 days
                    start_window = event.date_start - timedelta(days=3)
                    end_window = event.date_end + timedelta(days=2)
                    if not (start_window <= report_date <= end_window):
                        diag_details.append({
                            "source": "internal_calendar",
                            "event_code": event.event_code,
                            "excluded_reason": "outside_event_window",
                            "date_start": event.date_start.isoformat(),
                            "date_end": event.date_end.isoformat(),
                        })
                        continue

                    desc = event.description or event.title
                    fresh_until = event.date_end + timedelta(days=2)

                    diag_details.append({
                        "source": "internal_calendar",
                        "event_code": event.event_code,
                        "is_selectable": True,
                        "selection_reason": "active_calendar_event",
                    })

                    signal = ExternalContextSignalResponse(
                        source="internal_calendar",
                        signal_type="calendar_event",
                        event_type=event.event_type,
                        event_code=event.event_code,
                        title=event.title,
                        description=desc,
                        date_start=event.date_start,
                        date_end=event.date_end,
                        period_start=event.date_start,
                        period_end=event.date_end,
                        published_at=event.date_start,
                        fresh_until=fresh_until,
                        region=event.region,
                        category=event.category,
                        impact_direction=event.impact_direction,
                        impact_strength=event.impact_strength,
                        confidence=event.confidence,
                        confidence_level="context_only",
                        interpretation=desc,
                        source_reference=event.source_reference,
                        data_status="ok",
                    )
                    candidates_p2.append(signal)
            except SQLAlchemyError:
                sources_status["calendar"] = "error"

        # ----------------------------------------------------
        # 3. P3: Consumer Sentiment Index (CBR)
        # ----------------------------------------------------
        if self.settings.external_consumer_sentiment_enabled and sources_status["consumer_sentiment"] != "disabled":
            try:
                metrics = self.session.scalars(
                    select(ExternalContextMetric)
                    .where(
                        ExternalContextMetric.source == "cbr",
                        ExternalContextMetric.metric_code == "consumer_sentiment_index",
                    )
                    .order_by(ExternalContextMetric.period_end.desc())
                ).all()

                for metric in metrics[:1]:  # Latest metric only
                    pub_date = metric.published_at.date() if metric.published_at else metric.period_end
                    days_diff = (report_date - pub_date).days
                    fresh_until = pub_date + timedelta(days=7)

                    if pub_date > report_date:
                        diag_details.append({
                            "source": "cbr",
                            "metric_code": metric.metric_code,
                            "excluded_reason": "published_after_report_date",
                            "days_diff": days_diff,
                            "published_at": pub_date.isoformat(),
                            "is_selectable": False,
                        })
                        continue
                    elif days_diff > 7:
                        diag_details.append({
                            "source": "cbr",
                            "metric_code": metric.metric_code,
                            "excluded_reason": "outside_7day_freshness_window",
                            "days_diff": days_diff,
                            "published_at": pub_date.isoformat(),
                            "is_selectable": False,
                        })
                        continue

                    val_str = _format_decimal(metric.value, 1)
                    prev_val = metric.previous_value
                    change_val = metric.change_value if metric.change_value is not None else (
                        metric.value - prev_val if (metric.value is not None and prev_val is not None) else None
                    )

                    if prev_val is not None:
                        if change_val is not None and change_val > 0:
                            short_interpretation = f"Индекс потребительских настроений вырос до {val_str} пункта."
                        elif change_val is not None and change_val < 0:
                            short_interpretation = f"Индекс потребительских настроений снизился до {val_str} пункта."
                        else:
                            short_interpretation = f"Индекс потребительских настроений составил {val_str} пункта."
                    else:
                        short_interpretation = f"Индекс потребительских настроений составил {val_str} пункта."

                    diag_details.append({
                        "source": "cbr",
                        "metric_code": metric.metric_code,
                        "is_selectable": True,
                        "selection_reason": "valid_fresh_sentiment_index",
                    })

                    signal = ExternalContextSignalResponse(
                        source="cbr",
                        signal_type="consumer_index",
                        metric_code=metric.metric_code,
                        title=metric.metric_name,
                        period_start=metric.period_start,
                        period_end=metric.period_end,
                        value=metric.value,
                        current_value=metric.value,
                        previous_value=prev_val,
                        change_value=change_val,
                        change_pct=metric.change_pct,
                        published_at=pub_date,
                        fresh_until=fresh_until,
                        neutral_level=Decimal("100.0"),
                        relevance="medium",
                        confidence_level="context_only",
                        interpretation=short_interpretation,
                        source_reference=metric.source_reference or "CBR",
                        data_status=metric.data_status,
                    )
                    candidates_p3.append(signal)
            except SQLAlchemyError:
                sources_status["consumer_sentiment"] = "error"

        # ----------------------------------------------------
        # 4. P4: Annual Inflation (Rosstat / CBR)
        # ----------------------------------------------------
        if self.settings.external_macro_enabled and sources_status["macro"] != "disabled":
            try:
                metrics = self.session.scalars(
                    select(ExternalContextMetric)
                    .where(
                        ExternalContextMetric.source.in_(["rosstat", "cbr"]),
                        ExternalContextMetric.metric_code == "inflation_rate",
                    )
                    .order_by(ExternalContextMetric.period_end.desc())
                ).all()

                for metric in metrics[:1]:  # Latest metric only
                    pub_date = metric.published_at.date() if metric.published_at else metric.period_end
                    days_diff = (report_date - pub_date).days
                    fresh_until = pub_date + timedelta(days=7)

                    if pub_date > report_date:
                        diag_details.append({
                            "source": metric.source,
                            "metric_code": metric.metric_code,
                            "excluded_reason": "published_after_report_date",
                            "days_diff": days_diff,
                            "published_at": pub_date.isoformat(),
                            "is_selectable": False,
                        })
                        continue
                    elif days_diff > 7:
                        diag_details.append({
                            "source": metric.source,
                            "metric_code": metric.metric_code,
                            "excluded_reason": "outside_7day_freshness_window",
                            "days_diff": days_diff,
                            "published_at": pub_date.isoformat(),
                            "is_selectable": False,
                        })
                        continue

                    val_str = _format_decimal(metric.value, 1)
                    prev_val = metric.previous_value

                    if prev_val is not None:
                        if metric.value is not None and metric.value > prev_val:
                            short_interpretation = f"Годовая инфляция ускорилась до {val_str}%."
                        elif metric.value is not None and metric.value < prev_val:
                            short_interpretation = f"Годовая инфляция замедлилась до {val_str}%."
                        else:
                            short_interpretation = f"Годовая инфляция составила {val_str}%."
                    else:
                        short_interpretation = f"Годовая инфляция составила {val_str}%."

                    diag_details.append({
                        "source": metric.source,
                        "metric_code": metric.metric_code,
                        "is_selectable": True,
                        "selection_reason": "valid_fresh_inflation_rate",
                    })

                    signal = ExternalContextSignalResponse(
                        source=metric.source,
                        signal_type="macro_index",
                        metric_code=metric.metric_code,
                        title=metric.metric_name,
                        period_start=metric.period_start,
                        period_end=metric.period_end,
                        value=metric.value,
                        current_value=metric.value,
                        previous_value=prev_val,
                        change_value=metric.value - prev_val if (metric.value is not None and prev_val is not None) else None,
                        change_pct=metric.change_pct,
                        published_at=pub_date,
                        fresh_until=fresh_until,
                        neutral_level=None,
                        relevance="low",
                        confidence_level="context_only",
                        interpretation=short_interpretation,
                        source_reference=metric.source_reference or "Rosstat",
                        data_status=metric.data_status,
                    )
                    candidates_p4.append(signal)
            except SQLAlchemyError:
                sources_status["macro"] = "error"

        # ----------------------------------------------------
        # 5. Selection & Ranking across all sources (max_signals)
        # Wordstat is capped at maximum 2 signals for main output.
        # ----------------------------------------------------
        selected_wordstat: list[ExternalContextSignalResponse] = candidates_p1[:2]

        all_candidates: list[ExternalContextSignalResponse] = (
            selected_wordstat + candidates_p2 + candidates_p3 + candidates_p4
        )

        def _overall_signal_sort_key(sig: ExternalContextSignalResponse) -> tuple[int, int, float]:
            rel_map = {"high": 0, "medium": 1, "low": 2}
            rel_rank = rel_map.get(sig.relevance or "medium", 1)

            pub_date = sig.published_at or sig.period_end or report_date
            days_ago = max(0, (report_date - pub_date).days)

            mag = float(abs(sig.change_pct)) if sig.change_pct is not None else 0.0

            return (rel_rank, days_ago, -mag)

        all_candidates.sort(key=_overall_signal_sort_key)
        selected_signals: list[ExternalContextSignalResponse] = all_candidates[:max_signals]

        # Compute refined status for search_demand
        if self.settings.external_search_demand_enabled and sources_status["search_demand"] != "disabled":
            if "db_metrics" in locals() and db_metrics:
                has_real = any(m.value and m.value > 0 or (m.change_pct is not None and m.change_pct != Decimal("0")) for m in db_metrics)
                if has_real:
                    sources_status["search_demand"] = "ok"
                else:
                    sources_status["search_demand"] = "placeholder"

        # Compute status and external_context_status
        all_unavailable_or_error = all(v in {"error", "unavailable", "disabled"} for v in sources_status.values()) and any(v in {"error", "unavailable"} for v in sources_status.values())

        if selected_signals:
            external_context_status = "signals_available"
            status = "OK"
        elif all_unavailable_or_error:
            external_context_status = "sources_unavailable"
            status = "UNAVAILABLE"
        else:
            external_context_status = "no_significant_signals"
            status = "EMPTY"

        # Collect last_successful_update for sources
        sources_checked = {}
        for src_key, src_stat in sources_status.items():
            sources_checked[src_key] = {
                "status": src_stat,
                "last_successful_update": report_date.isoformat() if src_stat == "ok" else None,
            }

        # Build selection_details and exclusion_reasons
        selected_metric_codes = {s.metric_code or s.event_code or s.title for s in selected_signals}
        selection_details: list[dict[str, Any]] = []
        exclusion_reasons: list[dict[str, Any]] = []

        for item in diag_details:
            is_sel = item.get("is_selectable", False)
            code = item.get("metric_code") or item.get("event_code") or item.get("source")
            if is_sel and code in selected_metric_codes:
                selection_details.append(item)
            else:
                exclusion_reasons.append(item)

        candidate_count = len(diag_details)
        selected_count = len(selected_signals)
        excluded_count = candidate_count - selected_count

        diagnostics = {
            "sources_checked": sources_checked,
            "candidate_count": candidate_count,
            "selected_count": selected_count,
            "excluded_count": excluded_count,
            "candidate_evaluations": diag_details,
            "selection_details": selection_details,
            "exclusion_reasons": exclusion_reasons,
            "max_signals": max_signals,
            "external_context_status": external_context_status,
            "sentiment_neutral_level": "Индекс находится относительно нейтрального уровня 100, где значение выше 100 указывает на более позитивные потребительские настроения.",
        }

        return ExternalContextResponse(
            report_date=report_date,
            period_start=resolved_period_start,
            period_end=resolved_period_end,
            status=status,
            external_context_status=external_context_status,
            signals=selected_signals,
            applied_filters=applied_filters,
            diagnostics=diagnostics,
            sources_status=sources_status,
        )
