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
        max_signals: int = 4,
        category_sales_trends: dict[str, dict[str, Any]] | None = None,
    ) -> ExternalContextResponse:
        max_signals = max(1, min(int(max_signals), 4))
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
        }

        # Candidate signals storage
        candidates_p1 = []  # Search demand
        candidates_p2 = []  # Calendar
        candidates_p3 = []  # Consumer Sentiment
        candidates_p4 = []  # Macro

        # SQL Diagnostics trackers
        diag_counts = {
            "calendar": {"candidates": 0, "selected": 0, "excluded": 0},
            "search_demand": {"candidates": 0, "selected": 0, "excluded": 0},
            "consumer_sentiment": {"candidates": 0, "selected": 0, "excluded": 0},
            "macro": {"candidates": 0, "selected": 0, "excluded": 0},
        }

        # ----------------------------------------------------
        # 1. P1: Search Demand Logic
        # ----------------------------------------------------
        if self.settings.external_search_demand_enabled and sources_status["search_demand"] != "disabled":
            try:
                # Fetch search demand metrics from DB
                db_metrics = self.session.scalars(
                    select(ExternalContextMetric)
                    .where(
                        ExternalContextMetric.source.in_(["yandex_direct", "yandex_cloud_wordstat"]),
                        ExternalContextMetric.period_start <= resolved_period_end,
                        ExternalContextMetric.period_end >= resolved_period_start,
                    )
                ).all()

                diag_counts["search_demand"]["candidates"] = len(db_metrics)

                for metric in db_metrics:
                    cat_code = metric.category
                    if not cat_code:
                        continue
                    
                    # Find category config
                    cat_cfg = next((c for c in CATEGORIES_CONFIG if c["category_code"] == cat_code), None)
                    if not cat_cfg or not cat_cfg["is_active"]:
                        diag_counts["search_demand"]["excluded"] += 1
                        continue

                    # If unavailable in DB, skip for main display but keep in diagnostics
                    if metric.data_status != "ok":
                        diag_counts["search_demand"]["excluded"] += 1
                        continue

                    val = metric.value
                    prev_val = metric.previous_value
                    change_pct = metric.change_pct
                    if val is None or prev_val is None or change_pct is None:
                        # Fallback calculation if missing
                        if prev_val and prev_val > 0:
                            change_pct = ((val - prev_val) / prev_val) * 100
                        else:
                            change_pct = Decimal("0")

                    # Check significance threshold
                    if abs(float(change_pct)) < self.settings.search_demand_min_change_pct:
                        diag_counts["search_demand"]["excluded"] += 1
                        continue

                    # Determine sales trend mapping
                    sales_trend = None
                    if category_sales_trends and cat_code in category_sales_trends:
                        sales_trend = category_sales_trends[cat_code]
                    elif category_sales_trends is not None:
                        # Explicit check: if sales trends dictionary is passed, but category is missing,
                        # it means there is no sales mapping for this category.
                        pass

                    # Category mapping matching rules
                    interpretation = None
                    relevance = "low"
                    
                    if sales_trend:
                        sales_change = Decimal(str(sales_trend.get("change_pct") or "0"))
                        relevance = "high"
                        direction_str = "снизился" if change_pct < 0 else "вырос"
                        
                        if change_pct < 0 and sales_change < 0:
                            interpretation = f"Поисковый спрос на {cat_cfg['category_title'].lower()} снизился на {abs(int(change_pct))}%; продажи категории снизились в том же направлении."
                        elif change_pct > 0 and sales_change < 0:
                            interpretation = f"Поисковый спрос на {cat_cfg['category_title'].lower()} вырос на {abs(int(change_pct))}%, а продажи снизились; вероятнее следует проверить внутренние факторы."
                        elif change_pct < 0 and sales_change > 0:
                            interpretation = f"Продажи категории {cat_cfg['category_title'].lower()} растут вопреки снижению внешнего поискового спроса на {abs(int(change_pct))}%."
                        else:
                            interpretation = f"Поисковый спрос на {cat_cfg['category_title'].lower()} вырос на {abs(int(change_pct))}%; продажи категории изменились в том же направлении."
                    else:
                        # If no sales trend correlation is possible, do not show in main operational summary report,
                        # but keep as candidates for diagnostic Tool.
                        interpretation = f"Поисковый спрос на {cat_cfg['category_title'].lower()} изменился на {change_pct}%."

                    signal = ExternalContextSignalResponse(
                        source="search_demand",
                        signal_type="demand_change",
                        metric_code=metric.metric_code,
                        title=f"Поисковый спрос: {cat_cfg['category_title']}",
                        period_start=metric.period_start,
                        period_end=metric.period_end,
                        value=val,
                        previous_value=prev_val,
                        change_pct=change_pct,
                        category=cat_code,
                        relevance=relevance,
                        confidence_level="context_only",
                        interpretation=interpretation,
                        source_reference=metric.source_reference or "Yandex Wordstat",
                        data_status=metric.data_status,
                    )
                    candidates_p1.append(signal)
                    diag_counts["search_demand"]["selected"] += 1
            except SQLAlchemyError as exc:
                sources_status["search_demand"] = "error"

        # ----------------------------------------------------
        # 2. P2: Calendar Logic
        # ----------------------------------------------------
        if self.settings.external_calendar_enabled and sources_status["calendar"] != "disabled":
            try:
                date_match = or_(
                    and_(ExternalContextEvent.date_start <= report_date, ExternalContextEvent.date_end >= report_date),
                    and_(ExternalContextEvent.date_start <= resolved_period_end, ExternalContextEvent.date_end >= resolved_period_start),
                )
                events = self.session.scalars(
                    select(ExternalContextEvent)
                    .where(ExternalContextEvent.is_active.is_(True), date_match)
                    .order_by(ExternalContextEvent.date_start.desc())
                ).all()

                diag_counts["calendar"]["candidates"] = len(events)

                for event in events:
                    # Filter events by display rules
                    requires_supporting = False
                    
                    # Summers season and long seasonal periods require supporting window or query trends
                    if event.event_type == "seasonal_period" or "season" in event.event_code:
                        requires_supporting = True
                    
                    # Metadata override if present
                    meta = event.metadata_json or {}
                    if "requires_supporting_signal" in meta:
                        requires_supporting = bool(meta["requires_supporting_signal"])

                    is_valid = True
                    
                    if requires_supporting:
                        # Check if within start/end transition window
                        near_start = abs((report_date - event.date_start).days) <= self.settings.calendar_transition_window_days
                        near_end = abs((report_date - event.date_end).days) <= self.settings.calendar_transition_window_days
                        
                        # Check category search demand validation if categories are configured
                        has_matching_demand = False
                        if event.category:
                            matching_p1 = [p for p in candidates_p1 if p.category == event.category and p.data_status == "ok"]
                            if matching_p1:
                                has_matching_demand = True

                        if not (near_start or near_end or has_matching_demand):
                            is_valid = False

                    # Exclude generic disclaimers
                    desc = event.description or ""
                    if not desc or "прямое влияние" in desc or "контекстный фактор" in desc:
                        # Exclude empty or meaningless comments
                        is_valid = False

                    if not is_valid:
                        diag_counts["calendar"]["excluded"] += 1
                        continue

                    signal = ExternalContextSignalResponse(
                        source="internal_calendar",
                        signal_type="calendar_event",
                        event_type=event.event_type,
                        event_code=event.event_code,
                        title=event.title,
                        description=desc,
                        date_start=event.date_start,
                        date_end=event.date_end,
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
                    diag_counts["calendar"]["selected"] += 1
            except SQLAlchemyError as exc:
                sources_status["calendar"] = "error"

        # ----------------------------------------------------
        # 3. P3: Consumer Sentiment Logic
        # ----------------------------------------------------
        if self.settings.external_consumer_sentiment_enabled and sources_status["consumer_sentiment"] != "disabled":
            try:
                db_metrics = self.session.scalars(
                    select(ExternalContextMetric)
                    .where(
                        ExternalContextMetric.source == "cbr",
                        ExternalContextMetric.metric_code.in_([
                            "consumer_sentiment_index", "expectations_index", "current_state_index", "inflation_expectations"
                        ])
                    )
                    .order_by(ExternalContextMetric.period_end.desc())
                ).all()

                diag_counts["consumer_sentiment"]["candidates"] = len(db_metrics)

                # Keep only latest unique codes to avoid duplicates
                seen_codes = set()
                latest_metrics = []
                for m in db_metrics:
                    if m.metric_code not in seen_codes:
                        seen_codes.add(m.metric_code)
                        latest_metrics.append(m)

                for metric in latest_metrics:
                    # Apply consumer signal display days limit
                    days_diff = (report_date - metric.period_end).days
                    if days_diff > self.settings.consumer_signal_display_days:
                        diag_counts["consumer_sentiment"]["excluded"] += 1
                        continue

                    # Filter index value changes
                    change_pct = metric.change_pct or Decimal("0")
                    
                    interpretation = ""
                    val_str = _format_decimal(metric.value, 1)
                    change_str = _format_decimal(change_pct, 1)
                    
                    if metric.metric_code == "consumer_sentiment_index":
                        if change_pct < 0:
                            interpretation = f"Индекс потребительских настроений снизился до {val_str} пунктов, что может ограничивать общий потребительский спрос."
                        else:
                            interpretation = f"Индекс потребительских настроений увеличился до {val_str} пунктов."
                    elif metric.metric_code == "inflation_expectations":
                        interpretation = f"Инфляционные ожидания населения составили {val_str}% (изменение на {change_str} п.п.)."
                    else:
                        interpretation = f"{metric.metric_name} составил {val_str} пунктов."

                    signal = ExternalContextSignalResponse(
                        source="cbr",
                        signal_type="consumer_index",
                        metric_code=metric.metric_code,
                        title=metric.metric_name,
                        period_start=metric.period_start,
                        period_end=metric.period_end,
                        value=metric.value,
                        previous_value=metric.previous_value,
                        change_pct=change_pct,
                        relevance="medium",
                        confidence_level="context_only",
                        interpretation=interpretation,
                        source_reference=metric.source_reference or "CBR",
                        data_status=metric.data_status,
                    )
                    candidates_p3.append(signal)
                    diag_counts["consumer_sentiment"]["selected"] += 1
            except SQLAlchemyError as exc:
                sources_status["consumer_sentiment"] = "error"

        # ----------------------------------------------------
        # 4. P4: Macroeconomic Background Logic
        # ----------------------------------------------------
        if self.settings.external_macro_enabled and sources_status["macro"] != "disabled":
            try:
                db_metrics = self.session.scalars(
                    select(ExternalContextMetric)
                    .where(
                        ExternalContextMetric.source.in_(["rosstat", "cbr"]),
                        ExternalContextMetric.metric_code.in_([
                            "inflation_rate", "clothing_inflation_rate", "real_disposable_income", "retail_trade_turnover", "cbr_key_rate"
                        ])
                    )
                    .order_by(ExternalContextMetric.period_end.desc())
                ).all()

                diag_counts["macro"]["candidates"] = len(db_metrics)

                seen_codes = set()
                latest_metrics = []
                for m in db_metrics:
                    if m.metric_code not in seen_codes:
                        seen_codes.add(m.metric_code)
                        latest_metrics.append(m)

                for metric in latest_metrics:
                    # Apply display limit (except Key Rate which acts as static background)
                    if metric.metric_code != "cbr_key_rate":
                        days_diff = (report_date - metric.period_end).days
                        if days_diff > self.settings.macro_signal_display_days:
                            diag_counts["macro"]["excluded"] += 1
                            continue

                    val_str = _format_decimal(metric.value, 1)
                    interpretation = ""
                    
                    if metric.metric_code == "cbr_key_rate":
                        interpretation = f"Ключевая ставка ЦБ РФ составляет {val_str}%, выступая общим финансовым фоном."
                    elif metric.metric_code == "clothing_inflation_rate":
                        interpretation = f"Инфляция в категории одежды и текстиля зафиксирована на уровне {val_str}%."
                    elif metric.metric_code == "inflation_rate":
                        interpretation = f"Годовая инфляция составила {val_str}%."
                    else:
                        interpretation = f"Показатель {metric.metric_name} составил {val_str}%."

                    signal = ExternalContextSignalResponse(
                        source="macro",
                        signal_type="macro_index",
                        metric_code=metric.metric_code,
                        title=metric.metric_name,
                        period_start=metric.period_start,
                        period_end=metric.period_end,
                        value=metric.value,
                        previous_value=metric.previous_value,
                        change_pct=metric.change_pct,
                        relevance="low",
                        confidence_level="context_only",
                        interpretation=interpretation,
                        source_reference=metric.source_reference or "Rosstat",
                        data_status=metric.data_status,
                    )
                    candidates_p4.append(signal)
                    diag_counts["macro"]["selected"] += 1
            except SQLAlchemyError as exc:
                sources_status["macro"] = "error"

        # ----------------------------------------------------
        # 5. Signal Selection and Priority
        # ----------------------------------------------------
        selected_signals = []

        # We select AT MOST 1 signal from each priority bucket (P1, P2, P3, P4)
        # Filters: in main report, only show signal if relevance is high/medium OR it's CBR Key Rate,
        # and data_status is 'ok'.
        
        # P1 Search Demand
        p1_selected = [s for s in candidates_p1 if s.relevance == "high" and s.data_status == "ok"]
        if p1_selected:
            selected_signals.append(p1_selected[0])

        # P2 Calendar
        p2_selected = [s for s in candidates_p2 if s.data_status == "ok"]
        if p2_selected:
            selected_signals.append(p2_selected[0])

        # P3 Consumer Sentiment
        p3_selected = [s for s in candidates_p3 if s.data_status == "ok"]
        if p3_selected:
            selected_signals.append(p3_selected[0])

        # P4 Macro Background
        p4_selected = [s for s in candidates_p4 if s.data_status == "ok"]
        if p4_selected:
            selected_signals.append(p4_selected[0])

        # Limit to max_signals (4)
        selected_signals = selected_signals[:max_signals]

        # Compute general status
        any_errors = any(v == "error" for v in sources_status.values())
        any_ok = any(v == "ok" for v in sources_status.values())
        status = "PARTIAL" if (any_errors and any_ok) else ("OK" if selected_signals else "EMPTY")
        if all(v == "disabled" for v in sources_status.values()):
            status = "DISABLED"

        # Format diagnostics dict
        diagnostics = {
            "candidate_count": sum(c["candidates"] for c in diag_counts.values()),
            "selected_count": len(selected_signals),
            "sources_diagnostics": diag_counts,
            "applied_thresholds": {
                "search_demand_min_change_pct": self.settings.search_demand_min_change_pct,
                "consumer_sentiment_min_change_pct": self.settings.consumer_sentiment_min_change_pct,
                "macro_min_change_pct": self.settings.macro_min_change_pct,
            }
        }

        return ExternalContextResponse(
            report_date=report_date,
            period_start=resolved_period_start,
            period_end=resolved_period_end,
            status=status,
            signals=selected_signals,
            applied_filters=applied_filters,
            diagnostics=diagnostics,
            sources_status=sources_status,
        )
