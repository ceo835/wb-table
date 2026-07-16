from __future__ import annotations

from datetime import date, timedelta
from typing import Any, Mapping, Sequence

import pandas as pd
from sqlalchemy import select

from src.db.models import DimCampaign, DimProduct, FactAdCampaignDay, FactAdCampaignNmDay, FactAdvertMetadata
from src.db.session import session_scope

AD_CAMPAIGN_SECTION_LABEL = "РК"
AD_CAMPAIGN_PRODUCT_LABEL = "РК по товару"
AD_CAMPAIGN_EFFICIENCY_LABEL = "Эффективность рекламных кампаний"
AD_CAMPAIGN_EFFICIENCY_THRESHOLD_PCT = 15.0
AD_CAMPAIGN_PERIOD_DAILY = "Ежедневно"
AD_CAMPAIGN_PERIOD_WEEKLY = "Еженедельно"
AD_CAMPAIGN_LEVEL_ALL = "Все"
AD_CAMPAIGN_LEVEL_CAMPAIGNS = "Рекламные кампании"
AD_CAMPAIGN_LEVEL_ARTICLES = "Артикулы"
AD_CAMPAIGN_METRIC_ALL = "Все"
AD_CAMPAIGN_METRIC_IMPRESSIONS = "Показы"
AD_CAMPAIGN_METRIC_CARTS = "Корзины"
AD_CAMPAIGN_DIRECTION_ALL = "Все"
AD_CAMPAIGN_DIRECTION_GROWTH = "Рост"
AD_CAMPAIGN_DIRECTION_DECLINE = "Снижение"
AD_CAMPAIGN_SIGNAL_NO_CHANGE = "NO_CHANGE"
AD_CAMPAIGN_SIGNAL_GROWTH = "GROWTH"
AD_CAMPAIGN_SIGNAL_DECLINE = "DECLINE"
AD_CAMPAIGN_SIGNAL_DROP_TO_ZERO = "DROP_TO_ZERO"
AD_CAMPAIGN_SIGNAL_NEW_ACTIVITY = "NEW_ACTIVITY"
AD_CAMPAIGN_SIGNAL_INSUFFICIENT = "INSUFFICIENT_DATA"
AD_CAMPAIGN_SIGNAL_STOPPED_NEUTRAL = "STOPPED_NEUTRAL"
AD_CAMPAIGN_NOTABLE_SIGNALS = {
    AD_CAMPAIGN_SIGNAL_GROWTH,
    AD_CAMPAIGN_SIGNAL_DECLINE,
    AD_CAMPAIGN_SIGNAL_DROP_TO_ZERO,
    AD_CAMPAIGN_SIGNAL_NEW_ACTIVITY,
}
AD_CAMPAIGN_CAMPAIGN_ROW_TYPES = {"Итог кампании", "CAMPAIGN_TOTAL", "TOTAL", "TOTAL_CAMPAIGN"}
AD_CAMPAIGN_PRODUCT_ROW_TYPES = {"PRODUCT", "Товар"}
AD_CAMPAIGN_EFFICIENCY_CAMPAIGN_DISPLAY_COLUMNS = [
    ("advert_id", "ID рекламной кампании"),
    ("campaign_name", "Название рекламной кампании"),
    ("campaign_status", "Статус РК"),
    ("campaign_type", "Тип рекламной кампании"),
    ("metric_name", "Показатель"),
    ("current_value", "Текущее значение"),
    ("previous_value", "Предыдущее значение"),
    ("change_absolute", "Изменение"),
    ("change_percent", "Изменение, %"),
]
AD_CAMPAIGN_EFFICIENCY_ARTICLE_DISPLAY_COLUMNS = [
    ("nm_id", "Артикул WB"),
    ("supplier_article", "Артикул продавца"),
    ("title", "Название товара"),
    ("campaign_ids", "ID рекламных кампаний"),
    ("campaign_names", "Рекламные кампании"),
    ("metric_name", "Показатель"),
    ("current_value", "Текущее значение"),
    ("previous_value", "Предыдущее значение"),
    ("change_absolute", "Изменение"),
    ("change_percent", "Изменение, %"),
]
AD_CAMPAIGN_EFFICIENCY_DISPLAY_EMPTY_VALUE = "—"
AD_CAMPAIGN_EFFICIENCY_TECHNICAL_COLUMNS = {
    "signal_label",
    "signal_code",
    "direction_code",
    "is_notable",
    "is_stopped",
    "comparison_period",
    "search_blob",
    "sort_priority",
    "sort_secondary",
}


def _row_to_dict(row: Any) -> dict[str, Any]:
    return {column.name: getattr(row, column.name) for column in row.__table__.columns}


def _normalize_text_value(value: object) -> str | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    normalized = str(value).strip()
    return normalized or None


def _first_non_empty(values: Sequence[object]) -> str | None:
    for value in values:
        normalized = _normalize_text_value(value)
        if normalized is not None:
            return normalized
    return None


def _coalesce_text(*values: object) -> str | None:
    return _first_non_empty(values)


def _collect_unique_texts(values: Sequence[object]) -> str | None:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        normalized = _normalize_text_value(value)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ", ".join(ordered) if ordered else None


def _collect_unique_int_labels(values: Sequence[object]) -> str | None:
    ordered: list[str] = []
    seen: set[str] = set()
    for value in values:
        try:
            if pd.isna(value):
                continue
        except Exception:
            pass
        try:
            normalized = str(int(value))
        except Exception:
            normalized = _normalize_text_value(value)
        if normalized is None or normalized in seen:
            continue
        seen.add(normalized)
        ordered.append(normalized)
    return ", ".join(ordered) if ordered else None


def _series_first_non_empty(series: pd.Series) -> str | None:
    return _first_non_empty(series.tolist())


def _series_unique_texts(series: pd.Series) -> str | None:
    return _collect_unique_texts(series.tolist())


def _series_unique_int_labels(series: pd.Series) -> str | None:
    return _collect_unique_int_labels(series.tolist())


def _as_float_or_none(value: object) -> float | None:
    if value is None:
        return None
    try:
        if pd.isna(value):
            return None
    except Exception:
        pass
    return float(value)


def _is_stopped_campaign_status(status_value: object) -> bool:
    normalized = (_normalize_text_value(status_value) or "").casefold()
    if not normalized:
        return False
    stop_tokens = (
        "stop",
        "pause",
        "inactive",
        "complete",
        "completed",
        "archive",
        "done",
        "останов",
        "приостанов",
        "заверш",
        "архив",
        "неактив",
    )
    return any(token in normalized for token in stop_tokens)


def load_ad_campaign_efficiency_available_dates() -> list[date]:
    with session_scope() as session:
        campaign_dates = {
            value
            for value in session.execute(select(FactAdCampaignDay.date).distinct()).scalars().all()
            if isinstance(value, date)
        }
        article_dates = {
            value
            for value in session.execute(select(FactAdCampaignNmDay.date).distinct()).scalars().all()
            if isinstance(value, date)
        }
    if campaign_dates and article_dates:
        shared_dates = campaign_dates & article_dates
        if shared_dates:
            return sorted(shared_dates)
    return sorted(campaign_dates | article_dates)


def load_ad_campaign_efficiency_scope_from_db(
    date_from: date,
    date_to: date,
) -> tuple[pd.DataFrame, pd.DataFrame, pd.DataFrame, pd.DataFrame]:
    campaign_columns = ["date", "advert_id", "campaign_name", "row_type", "ad_views", "ad_atbs"]
    article_columns = ["date", "advert_id", "campaign_name", "row_type", "nm_id", "product_name", "ad_views", "ad_atbs"]
    campaign_meta_columns = ["advert_id", "campaign_name", "campaign_type", "campaign_status"]
    product_columns = ["nm_id", "supplier_article", "title"]

    with session_scope() as session:
        campaign_rows = [
            _row_to_dict(row)
            for row in session.execute(
                select(FactAdCampaignDay).where(
                    FactAdCampaignDay.date >= date_from,
                    FactAdCampaignDay.date <= date_to,
                )
            ).scalars().all()
        ]
        article_rows = [
            _row_to_dict(row)
            for row in session.execute(
                select(FactAdCampaignNmDay).where(
                    FactAdCampaignNmDay.date >= date_from,
                    FactAdCampaignNmDay.date <= date_to,
                )
            ).scalars().all()
        ]

        advert_ids = sorted(
            {
                int(value)
                for value in [
                    *(row.get("advert_id") for row in campaign_rows),
                    *(row.get("advert_id") for row in article_rows),
                ]
                if value not in (None, "")
            }
        )
        nm_ids = sorted(
            {
                int(value)
                for value in (row.get("nm_id") for row in article_rows)
                if value not in (None, "")
            }
        )

        dim_campaign_rows = (
            [
                dict(row)
                for row in session.execute(
                    select(
                        DimCampaign.advert_id,
                        DimCampaign.campaign_name,
                        DimCampaign.campaign_type,
                        DimCampaign.status,
                    ).where(DimCampaign.advert_id.in_(advert_ids))
                )
                .mappings()
                .all()
            ]
            if advert_ids
            else []
        )
        advert_metadata_rows = (
            [
                dict(row)
                for row in session.execute(
                    select(
                        FactAdvertMetadata.advert_id,
                        FactAdvertMetadata.campaign_name,
                        FactAdvertMetadata.status,
                    ).where(FactAdvertMetadata.advert_id.in_(advert_ids))
                )
                .mappings()
                .all()
            ]
            if advert_ids
            else []
        )
        product_rows = (
            [
                dict(row)
                for row in session.execute(
                    select(
                        DimProduct.nm_id,
                        DimProduct.supplier_article,
                        DimProduct.title,
                    ).where(DimProduct.nm_id.in_(nm_ids))
                )
                .mappings()
                .all()
            ]
            if nm_ids
            else []
        )

    meta_by_advert: dict[int, dict[str, object]] = {}
    for row in dim_campaign_rows:
        advert_id = int(row["advert_id"])
        meta_by_advert[advert_id] = {
            "advert_id": advert_id,
            "campaign_name": row.get("campaign_name"),
            "campaign_type": row.get("campaign_type"),
            "campaign_status": row.get("status"),
        }
    for row in advert_metadata_rows:
        advert_id = int(row["advert_id"])
        current = meta_by_advert.setdefault(
            advert_id,
            {
                "advert_id": advert_id,
                "campaign_name": None,
                "campaign_type": None,
                "campaign_status": None,
            },
        )
        current["campaign_name"] = _coalesce_text(current.get("campaign_name"), row.get("campaign_name"))
        current["campaign_status"] = _coalesce_text(current.get("campaign_status"), row.get("status"))

    product_lookup_rows = [
        {
            "nm_id": int(row["nm_id"]),
            "supplier_article": row.get("supplier_article"),
            "title": row.get("title"),
        }
        for row in product_rows
        if row.get("nm_id") not in (None, "")
    ]

    campaign_df = pd.DataFrame.from_records(campaign_rows, columns=campaign_columns)
    article_df = pd.DataFrame.from_records(article_rows, columns=article_columns)
    campaign_meta_df = pd.DataFrame.from_records(list(meta_by_advert.values()), columns=campaign_meta_columns)
    product_df = pd.DataFrame.from_records(product_lookup_rows, columns=product_columns)
    return campaign_df, article_df, campaign_meta_df, product_df


def resolve_ad_campaign_efficiency_window(report_date_value: date, period_mode: str) -> dict[str, object]:
    if period_mode == AD_CAMPAIGN_PERIOD_WEEKLY:
        current_end = report_date_value
        current_start = current_end - timedelta(days=6)
        previous_end = current_start - timedelta(days=1)
        previous_start = previous_end - timedelta(days=6)
        comparison_label = (
            f"{current_start.strftime('%d.%m.%Y')}–{current_end.strftime('%d.%m.%Y')} "
            f"против {previous_start.strftime('%d.%m.%Y')}–{previous_end.strftime('%d.%m.%Y')}"
        )
    else:
        current_start = report_date_value
        current_end = report_date_value
        previous_start = report_date_value - timedelta(days=1)
        previous_end = previous_start
        comparison_label = f"{current_start.strftime('%d.%m.%Y')} против {previous_start.strftime('%d.%m.%Y')}"

    current_dates = [current_start + timedelta(days=offset) for offset in range((current_end - current_start).days + 1)]
    previous_dates = [previous_start + timedelta(days=offset) for offset in range((previous_end - previous_start).days + 1)]
    return {
        "current_start": current_start,
        "current_end": current_end,
        "previous_start": previous_start,
        "previous_end": previous_end,
        "current_dates": current_dates,
        "previous_dates": previous_dates,
        "required_dates": previous_dates + current_dates,
        "comparison_label": comparison_label,
    }


def calculate_ad_campaign_efficiency_signal(
    current_value: object,
    previous_value: object,
    *,
    threshold_pct: float = AD_CAMPAIGN_EFFICIENCY_THRESHOLD_PCT,
    stopped_campaign: bool = False,
) -> dict[str, object]:
    current_numeric = _as_float_or_none(current_value)
    previous_numeric = _as_float_or_none(previous_value)
    if current_numeric is None or previous_numeric is None:
        return {
            "change_absolute": None,
            "change_percent": None,
            "signal_code": AD_CAMPAIGN_SIGNAL_INSUFFICIENT,
            "signal_label": "Недостаточно данных",
            "direction_code": "neutral",
            "is_notable": False,
        }

    change_absolute = current_numeric - previous_numeric
    change_percent: float | None
    signal_code = AD_CAMPAIGN_SIGNAL_NO_CHANGE
    signal_label = "Без изменений"
    direction_code = "neutral"

    if previous_numeric == 0 and current_numeric == 0:
        change_percent = 0.0
    elif previous_numeric == 0 and current_numeric > 0:
        change_percent = None
        signal_code = AD_CAMPAIGN_SIGNAL_NEW_ACTIVITY
        signal_label = "Новая активность"
        direction_code = "growth"
    else:
        change_percent = (change_absolute / previous_numeric) * 100 if previous_numeric != 0 else None
        if previous_numeric > 0 and current_numeric == 0:
            signal_code = AD_CAMPAIGN_SIGNAL_DROP_TO_ZERO
            signal_label = "Падение до нуля"
            direction_code = "decline"
            change_percent = -100.0
        elif change_percent is not None and abs(change_percent) >= threshold_pct:
            if change_percent > 0:
                signal_code = AD_CAMPAIGN_SIGNAL_GROWTH
                signal_label = "Рост"
                direction_code = "growth"
            elif change_percent < 0:
                signal_code = AD_CAMPAIGN_SIGNAL_DECLINE
                signal_label = "Снижение"
                direction_code = "decline"

    if stopped_campaign and signal_code in {AD_CAMPAIGN_SIGNAL_DECLINE, AD_CAMPAIGN_SIGNAL_DROP_TO_ZERO}:
        signal_code = AD_CAMPAIGN_SIGNAL_STOPPED_NEUTRAL
        signal_label = "Остановлена / завершена"
        direction_code = "neutral"

    return {
        "change_absolute": change_absolute,
        "change_percent": change_percent,
        "signal_code": signal_code,
        "signal_label": signal_label,
        "direction_code": direction_code,
        "is_notable": signal_code in AD_CAMPAIGN_NOTABLE_SIGNALS,
    }


def _prepare_efficiency_source_dataframe(
    df: pd.DataFrame,
    *,
    row_types: set[str],
    required_id_columns: Sequence[str],
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    prepared = df.copy()
    prepared["date"] = pd.to_datetime(prepared.get("date"), errors="coerce").dt.date
    prepared = prepared[prepared["date"].notna()].copy()
    if "row_type" in prepared.columns:
        prepared = prepared[prepared["row_type"].isin(row_types)].copy()
    for column_name in required_id_columns:
        prepared[column_name] = pd.to_numeric(prepared.get(column_name), errors="coerce")
        prepared = prepared[prepared[column_name].notna()].copy()
        prepared[column_name] = prepared[column_name].astype("Int64")
    for metric_column in ("ad_views", "ad_atbs"):
        if metric_column in prepared.columns:
            prepared[metric_column] = pd.to_numeric(prepared[metric_column], errors="coerce")
    return prepared


def _aggregate_period_sums(
    df: pd.DataFrame,
    *,
    key_columns: Sequence[str],
    date_from: date,
    date_to: date,
    prefix: str,
) -> pd.DataFrame:
    metric_columns = ["ad_views", "ad_atbs"]
    if df.empty:
        return pd.DataFrame(columns=[*key_columns, *(f"{prefix}_{column}" for column in metric_columns)])
    mask = df["date"].ge(date_from) & df["date"].le(date_to)
    grouped = df.loc[mask].groupby(list(key_columns), dropna=False)[metric_columns].sum(min_count=1).reset_index()
    return grouped.rename(columns={column: f"{prefix}_{column}" for column in metric_columns})


def _build_sort_fields(signal_code: str, change_percent: float | None) -> tuple[int, float]:
    priority_map = {
        AD_CAMPAIGN_SIGNAL_DROP_TO_ZERO: 0,
        AD_CAMPAIGN_SIGNAL_DECLINE: 1,
        AD_CAMPAIGN_SIGNAL_GROWTH: 2,
        AD_CAMPAIGN_SIGNAL_NEW_ACTIVITY: 3,
        AD_CAMPAIGN_SIGNAL_NO_CHANGE: 4,
        AD_CAMPAIGN_SIGNAL_STOPPED_NEUTRAL: 5,
        AD_CAMPAIGN_SIGNAL_INSUFFICIENT: 6,
    }
    if signal_code == AD_CAMPAIGN_SIGNAL_DECLINE:
        secondary = change_percent if change_percent is not None else 0.0
    elif signal_code == AD_CAMPAIGN_SIGNAL_GROWTH:
        secondary = -(change_percent if change_percent is not None else 0.0)
    elif signal_code == AD_CAMPAIGN_SIGNAL_DROP_TO_ZERO:
        secondary = -1000.0
    else:
        secondary = 0.0
    return priority_map.get(signal_code, 99), secondary


def build_ad_campaign_efficiency_campaign_table(
    campaign_stats_df: pd.DataFrame,
    campaign_meta_df: pd.DataFrame,
    *,
    window: Mapping[str, object],
    threshold_pct: float = AD_CAMPAIGN_EFFICIENCY_THRESHOLD_PCT,
) -> pd.DataFrame:
    source = _prepare_efficiency_source_dataframe(
        campaign_stats_df,
        row_types=AD_CAMPAIGN_CAMPAIGN_ROW_TYPES,
        required_id_columns=["advert_id"],
    )
    columns = [
        "campaign_status",
        "advert_id",
        "campaign_name",
        "campaign_type",
        "metric_name",
        "current_value",
        "previous_value",
        "change_absolute",
        "change_percent",
        "signal_label",
        "signal_code",
        "direction_code",
        "comparison_period",
        "is_notable",
        "is_stopped",
        "search_blob",
        "sort_priority",
        "sort_secondary",
    ]
    if source.empty:
        return pd.DataFrame(columns=columns)

    dims = source.groupby("advert_id", dropna=False).agg(campaign_name=("campaign_name", _series_first_non_empty)).reset_index()
    if campaign_meta_df.empty:
        base = dims.copy()
        base["campaign_type"] = None
        base["campaign_status"] = None
    else:
        meta = campaign_meta_df.copy()
        meta["advert_id"] = pd.to_numeric(meta["advert_id"], errors="coerce").astype("Int64")
        meta = meta.rename(columns={
            "campaign_name": "campaign_name_meta",
            "campaign_type": "campaign_type_meta",
            "campaign_status": "campaign_status_meta",
        })
        base = dims.merge(meta, on="advert_id", how="outer")
        base["campaign_name"] = base.apply(lambda row: _coalesce_text(row.get("campaign_name_meta"), row.get("campaign_name")), axis=1)
        base["campaign_type"] = base["campaign_type_meta"]
        base["campaign_status"] = base["campaign_status_meta"]
        base = base.drop(columns=["campaign_name_meta", "campaign_type_meta", "campaign_status_meta"], errors="ignore")

    base = base.merge(
        _aggregate_period_sums(source, key_columns=["advert_id"], date_from=window["current_start"], date_to=window["current_end"], prefix="current"),
        on="advert_id",
        how="outer",
    )
    base = base.merge(
        _aggregate_period_sums(source, key_columns=["advert_id"], date_from=window["previous_start"], date_to=window["previous_end"], prefix="previous"),
        on="advert_id",
        how="outer",
    )

    rows: list[dict[str, object]] = []
    for record in base.to_dict("records"):
        advert_id_value = record.get("advert_id")
        if advert_id_value is None or pd.isna(advert_id_value):
            continue
        advert_id = int(advert_id_value)
        campaign_status = _normalize_text_value(record.get("campaign_status"))
        campaign_name = _coalesce_text(record.get("campaign_name"), f"РК {advert_id}")
        campaign_type = _normalize_text_value(record.get("campaign_type"))
        is_stopped = _is_stopped_campaign_status(campaign_status)
        for metric_name, metric_column in ((AD_CAMPAIGN_METRIC_IMPRESSIONS, "ad_views"), (AD_CAMPAIGN_METRIC_CARTS, "ad_atbs")):
            signal = calculate_ad_campaign_efficiency_signal(
                record.get(f"current_{metric_column}"),
                record.get(f"previous_{metric_column}"),
                threshold_pct=threshold_pct,
                stopped_campaign=is_stopped,
            )
            sort_priority, sort_secondary = _build_sort_fields(
                str(signal["signal_code"]),
                signal["change_percent"] if isinstance(signal["change_percent"], float) else None,
            )
            rows.append({
                "campaign_status": campaign_status or "—",
                "advert_id": advert_id,
                "campaign_name": campaign_name,
                "campaign_type": campaign_type or "—",
                "metric_name": metric_name,
                "current_value": _as_float_or_none(record.get(f"current_{metric_column}")),
                "previous_value": _as_float_or_none(record.get(f"previous_{metric_column}")),
                "change_absolute": signal["change_absolute"],
                "change_percent": signal["change_percent"],
                "signal_label": signal["signal_label"],
                "signal_code": signal["signal_code"],
                "direction_code": signal["direction_code"],
                "comparison_period": window["comparison_label"],
                "is_notable": bool(signal["is_notable"]),
                "is_stopped": is_stopped,
                "search_blob": " ".join(part for part in (str(advert_id), campaign_name, campaign_type or "", campaign_status or "") if part).casefold(),
                "sort_priority": sort_priority,
                "sort_secondary": sort_secondary,
            })

    result = pd.DataFrame(rows, columns=columns)
    if result.empty:
        return result
    return result.sort_values(by=["sort_priority", "sort_secondary", "advert_id", "metric_name"], ascending=[True, True, True, True], na_position="last").reset_index(drop=True)

def _prepare_efficiency_source_dataframe(
    df: pd.DataFrame,
    *,
    row_types: set[str],
    required_id_columns: Sequence[str],
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    prepared = df.copy()
    prepared["date"] = pd.to_datetime(prepared.get("date"), errors="coerce").dt.date
    prepared = prepared[prepared["date"].notna()].copy()
    if "row_type" in prepared.columns:
        prepared = prepared[prepared["row_type"].isin(row_types)].copy()
    for column_name in required_id_columns:
        prepared[column_name] = pd.to_numeric(prepared.get(column_name), errors="coerce")
        prepared = prepared[prepared[column_name].notna()].copy()
        prepared[column_name] = prepared[column_name].astype("Int64")
    for metric_column in ("ad_views", "ad_atbs"):
        if metric_column in prepared.columns:
            prepared[metric_column] = pd.to_numeric(prepared[metric_column], errors="coerce")
    return prepared


def build_ad_campaign_efficiency_article_table(
    article_stats_df: pd.DataFrame,
    product_df: pd.DataFrame,
    *,
    window: Mapping[str, object],
    threshold_pct: float = AD_CAMPAIGN_EFFICIENCY_THRESHOLD_PCT,
) -> pd.DataFrame:
    columns = [
        "supplier_article",
        "nm_id",
        "title",
        "campaign_ids",
        "campaign_names",
        "metric_name",
        "current_value",
        "previous_value",
        "change_absolute",
        "change_percent",
        "signal_label",
        "signal_code",
        "direction_code",
        "comparison_period",
        "is_notable",
        "search_blob",
        "sort_priority",
        "sort_secondary",
    ]
    source = _prepare_efficiency_source_dataframe(
        article_stats_df,
        row_types=AD_CAMPAIGN_PRODUCT_ROW_TYPES,
        required_id_columns=["advert_id", "nm_id"],
    )
    if source.empty:
        return pd.DataFrame(columns=columns)

    article_dims = source.groupby("nm_id", dropna=False).agg(
        title_source=("product_name", _series_first_non_empty),
        campaign_ids=("advert_id", _series_unique_int_labels),
        campaign_names=("campaign_name", _series_unique_texts),
    ).reset_index()
    if product_df.empty:
        base = article_dims.copy()
        base["supplier_article"] = None
        base["title"] = base["title_source"]
    else:
        product_meta = product_df.copy()
        product_meta["nm_id"] = pd.to_numeric(product_meta["nm_id"], errors="coerce").astype("Int64")
        product_meta = product_meta.rename(columns={"supplier_article": "supplier_article_meta", "title": "title_meta"})
        base = article_dims.merge(product_meta, on="nm_id", how="left")
        base["supplier_article"] = base["supplier_article_meta"]
        base["title"] = base.apply(
            lambda row: _coalesce_text(row.get("title_meta"), row.get("title_source"), f"nm_id {int(row['nm_id'])}"),
            axis=1,
        )
        base = base.drop(columns=["supplier_article_meta", "title_meta"], errors="ignore")

    base = base.merge(
        _aggregate_period_sums(source, key_columns=["nm_id"], date_from=window["current_start"], date_to=window["current_end"], prefix="current"),
        on="nm_id",
        how="outer",
    )
    base = base.merge(
        _aggregate_period_sums(source, key_columns=["nm_id"], date_from=window["previous_start"], date_to=window["previous_end"], prefix="previous"),
        on="nm_id",
        how="outer",
    )

    rows: list[dict[str, object]] = []
    for record in base.to_dict("records"):
        nm_id_value = record.get("nm_id")
        if nm_id_value is None or pd.isna(nm_id_value):
            continue
        nm_id = int(nm_id_value)
        supplier_article = _normalize_text_value(record.get("supplier_article"))
        title = _normalize_text_value(record.get("title")) or f"nm_id {nm_id}"
        campaign_ids = _normalize_text_value(record.get("campaign_ids")) or "—"
        campaign_names = _normalize_text_value(record.get("campaign_names")) or "—"
        for metric_name, metric_column in ((AD_CAMPAIGN_METRIC_IMPRESSIONS, "ad_views"), (AD_CAMPAIGN_METRIC_CARTS, "ad_atbs")):
            signal = calculate_ad_campaign_efficiency_signal(
                record.get(f"current_{metric_column}"),
                record.get(f"previous_{metric_column}"),
                threshold_pct=threshold_pct,
            )
            sort_priority, sort_secondary = _build_sort_fields(
                str(signal["signal_code"]),
                signal["change_percent"] if isinstance(signal["change_percent"], float) else None,
            )
            rows.append({
                "supplier_article": supplier_article or "—",
                "nm_id": nm_id,
                "title": title,
                "campaign_ids": campaign_ids,
                "campaign_names": campaign_names,
                "metric_name": metric_name,
                "current_value": _as_float_or_none(record.get(f"current_{metric_column}")),
                "previous_value": _as_float_or_none(record.get(f"previous_{metric_column}")),
                "change_absolute": signal["change_absolute"],
                "change_percent": signal["change_percent"],
                "signal_label": signal["signal_label"],
                "signal_code": signal["signal_code"],
                "direction_code": signal["direction_code"],
                "comparison_period": window["comparison_label"],
                "is_notable": bool(signal["is_notable"]),
                "search_blob": " ".join(part for part in (str(nm_id), supplier_article or "", title, campaign_ids, campaign_names) if part).casefold(),
                "sort_priority": sort_priority,
                "sort_secondary": sort_secondary,
            })

    result = pd.DataFrame(rows, columns=columns)
    if result.empty:
        return result
    return result.sort_values(by=["sort_priority", "sort_secondary", "nm_id", "metric_name"], ascending=[True, True, True, True], na_position="last").reset_index(drop=True)


def build_ad_campaign_efficiency_tables(
    campaign_stats_df: pd.DataFrame,
    article_stats_df: pd.DataFrame,
    campaign_meta_df: pd.DataFrame,
    product_df: pd.DataFrame,
    *,
    report_date_value: date,
    period_mode: str,
    threshold_pct: float = AD_CAMPAIGN_EFFICIENCY_THRESHOLD_PCT,
) -> tuple[pd.DataFrame, pd.DataFrame, dict[str, object]]:
    window = resolve_ad_campaign_efficiency_window(report_date_value, period_mode)
    campaign_table = build_ad_campaign_efficiency_campaign_table(
        campaign_stats_df,
        campaign_meta_df,
        window=window,
        threshold_pct=threshold_pct,
    )
    article_table = build_ad_campaign_efficiency_article_table(
        article_stats_df,
        product_df,
        window=window,
        threshold_pct=threshold_pct,
    )
    return campaign_table, article_table, window


def filter_ad_campaign_efficiency_rows(
    df: pd.DataFrame,
    *,
    metric_filter: str = AD_CAMPAIGN_METRIC_ALL,
    direction_filter: str = AD_CAMPAIGN_DIRECTION_ALL,
    only_notable: bool = False,
    search_text: str = "",
) -> pd.DataFrame:
    if df.empty:
        return df.copy()
    filtered = df.copy()
    if metric_filter != AD_CAMPAIGN_METRIC_ALL:
        filtered = filtered[filtered["metric_name"] == metric_filter]
    if direction_filter == AD_CAMPAIGN_DIRECTION_GROWTH:
        filtered = filtered[filtered["direction_code"] == "growth"]
    elif direction_filter == AD_CAMPAIGN_DIRECTION_DECLINE:
        filtered = filtered[filtered["direction_code"] == "decline"]
    if only_notable:
        filtered = filtered[filtered["is_notable"].fillna(False).astype(bool)]
    normalized_search = search_text.strip().casefold()
    if normalized_search:
        filtered = filtered[
            filtered["search_blob"].fillna("").astype(str).str.contains(normalized_search, regex=False)
        ]
    return filtered.sort_values(by=["sort_priority", "sort_secondary"], ascending=[True, True], na_position="last").reset_index(drop=True)


def build_ad_campaign_efficiency_summary(campaign_rows: pd.DataFrame, article_rows: pd.DataFrame) -> dict[str, int]:
    if campaign_rows.empty:
        active_campaigns = 0
        campaign_impression_alerts = 0
        campaign_cart_alerts = 0
    else:
        active_campaigns = int(campaign_rows.loc[~campaign_rows["is_stopped"].fillna(False), "advert_id"].nunique())
        campaign_impression_alerts = int(
            campaign_rows[
                (campaign_rows["metric_name"] == AD_CAMPAIGN_METRIC_IMPRESSIONS)
                & campaign_rows["is_notable"].fillna(False)
            ]["advert_id"].nunique()
        )
        campaign_cart_alerts = int(
            campaign_rows[
                (campaign_rows["metric_name"] == AD_CAMPAIGN_METRIC_CARTS)
                & campaign_rows["is_notable"].fillna(False)
            ]["advert_id"].nunique()
        )
    article_alerts = int(article_rows[article_rows["is_notable"].fillna(False)]["nm_id"].nunique()) if not article_rows.empty else 0
    drop_to_zero = int((campaign_rows["signal_code"] == AD_CAMPAIGN_SIGNAL_DROP_TO_ZERO).sum() if not campaign_rows.empty else 0)
    drop_to_zero += int((article_rows["signal_code"] == AD_CAMPAIGN_SIGNAL_DROP_TO_ZERO).sum() if not article_rows.empty else 0)
    new_activity = int((campaign_rows["signal_code"] == AD_CAMPAIGN_SIGNAL_NEW_ACTIVITY).sum() if not campaign_rows.empty else 0)
    new_activity += int((article_rows["signal_code"] == AD_CAMPAIGN_SIGNAL_NEW_ACTIVITY).sum() if not article_rows.empty else 0)
    return {
        "active_campaigns": active_campaigns,
        "campaign_impression_alerts": campaign_impression_alerts,
        "campaign_cart_alerts": campaign_cart_alerts,
        "article_alerts": article_alerts,
        "drop_to_zero": drop_to_zero,
        "new_activity": new_activity,
    }



def _looks_numeric_status_token(value: str) -> bool:
    candidate = value.strip().replace(",", ".")
    if not candidate:
        return False
    if candidate[0] in "+-":
        candidate = candidate[1:]
    if candidate.count(".") > 1:
        return False
    return candidate.replace(".", "", 1).isdigit()



def _normalize_campaign_status_display(value: object) -> str | None:
    normalized = _normalize_text_value(value)
    if normalized is None:
        return None
    lowered = normalized.casefold()
    if any(token in lowered for token in ("active", "актив")):
        return "Активна"
    if any(token in lowered for token in ("pause", "paused", "suspend", "приостанов", "пауза")):
        return "Приостановлена"
    if any(token in lowered for token in ("stop", "stopped", "complete", "completed", "finish", "finished", "archive", "архив", "заверш", "останов")):
        return "Завершена"
    if _looks_numeric_status_token(normalized):
        return None
    return "Неизвестный статус"



def _has_meaningful_display_values(series: pd.Series) -> bool:
    normalized = series.fillna("").astype(str).str.strip()
    return bool((normalized != "").any() and (normalized != AD_CAMPAIGN_EFFICIENCY_DISPLAY_EMPTY_VALUE).any())



def _format_efficiency_integer(value: object) -> str:
    numeric = _as_float_or_none(value)
    if numeric is None:
        return AD_CAMPAIGN_EFFICIENCY_DISPLAY_EMPTY_VALUE
    rounded = int(round(numeric))
    if rounded == 0:
        return "0"
    return f"{rounded:,}".replace(",", " ")



def _format_efficiency_signed_integer(value: object) -> str:
    numeric = _as_float_or_none(value)
    if numeric is None:
        return AD_CAMPAIGN_EFFICIENCY_DISPLAY_EMPTY_VALUE
    rounded = int(round(numeric))
    if rounded == 0:
        return "0"
    sign = "+" if rounded > 0 else "−"
    return f"{sign}{abs(rounded):,}".replace(",", " ")



def _format_efficiency_percent(value: object) -> str:
    numeric = _as_float_or_none(value)
    if numeric is None:
        return AD_CAMPAIGN_EFFICIENCY_DISPLAY_EMPTY_VALUE
    if abs(numeric) < 1e-9:
        return "0,0%"
    sign = "+" if numeric > 0 else "−"
    return f"{sign}{abs(numeric):.1f}%".replace(".", ",")



def build_ad_campaign_efficiency_comparison_caption(report_date_value: date, period_mode: str) -> str:
    if period_mode == AD_CAMPAIGN_PERIOD_WEEKLY:
        return "Сравнение: последние 7 полных дней с предыдущими 7 днями"
    return f"Сравнение: {report_date_value.strftime('%d.%m.%Y')} с предыдущим полным днём"



def build_ad_campaign_efficiency_export_filename(section_slug: str, report_date_value: date, period_mode: str, extension: str) -> str:
    period_slug = "weekly" if period_mode == AD_CAMPAIGN_PERIOD_WEEKLY else "daily"
    return f"ad_campaign_efficiency_{section_slug}_{period_slug}_{report_date_value.isoformat()}.{extension}"



def build_ad_campaign_efficiency_display_dataframe(
    df: pd.DataFrame,
    *,
    level: str,
) -> pd.DataFrame:
    if level == AD_CAMPAIGN_LEVEL_ARTICLES:
        column_pairs = AD_CAMPAIGN_EFFICIENCY_ARTICLE_DISPLAY_COLUMNS
    else:
        column_pairs = AD_CAMPAIGN_EFFICIENCY_CAMPAIGN_DISPLAY_COLUMNS

    if df.empty:
        return pd.DataFrame(columns=[label for _, label in column_pairs])

    working = df.copy()
    display_df = pd.DataFrame(index=working.index)

    if level == AD_CAMPAIGN_LEVEL_ARTICLES:
        supplier_article_series = working.get("supplier_article", pd.Series(index=working.index, dtype=object)).map(_normalize_text_value)
        working["supplier_article"] = supplier_article_series
        hide_supplier_article = not _has_meaningful_display_values(
            supplier_article_series.fillna(AD_CAMPAIGN_EFFICIENCY_DISPLAY_EMPTY_VALUE)
        )
    else:
        campaign_status_series = working.get("campaign_status", pd.Series(index=working.index, dtype=object)).map(
            _normalize_campaign_status_display
        )
        campaign_type_series = working.get("campaign_type", pd.Series(index=working.index, dtype=object)).map(_normalize_text_value)
        working["campaign_status"] = campaign_status_series
        working["campaign_type"] = campaign_type_series
        hide_status = not _has_meaningful_display_values(campaign_status_series.fillna(AD_CAMPAIGN_EFFICIENCY_DISPLAY_EMPTY_VALUE))
        hide_campaign_type = not _has_meaningful_display_values(campaign_type_series.fillna(AD_CAMPAIGN_EFFICIENCY_DISPLAY_EMPTY_VALUE))

    for source_column, display_label in column_pairs:
        if source_column in AD_CAMPAIGN_EFFICIENCY_TECHNICAL_COLUMNS:
            continue
        if level == AD_CAMPAIGN_LEVEL_ARTICLES and source_column == "supplier_article" and hide_supplier_article:
            continue
        if level != AD_CAMPAIGN_LEVEL_ARTICLES and source_column == "campaign_status" and hide_status:
            continue
        if level != AD_CAMPAIGN_LEVEL_ARTICLES and source_column == "campaign_type" and hide_campaign_type:
            continue

        source_series = working.get(source_column, pd.Series(index=working.index, dtype=object))
        if source_column in {"advert_id", "nm_id", "campaign_ids"}:
            display_df[display_label] = source_series.fillna(AD_CAMPAIGN_EFFICIENCY_DISPLAY_EMPTY_VALUE).astype(str)
        elif source_column in {"campaign_name", "campaign_names", "title", "metric_name", "supplier_article", "campaign_status", "campaign_type"}:
            display_df[display_label] = source_series.map(_normalize_text_value).fillna(AD_CAMPAIGN_EFFICIENCY_DISPLAY_EMPTY_VALUE)
        elif source_column in {"current_value", "previous_value"}:
            display_df[display_label] = source_series.map(_format_efficiency_integer)
        elif source_column == "change_absolute":
            display_df[display_label] = source_series.map(_format_efficiency_signed_integer)
        elif source_column == "change_percent":
            display_df[display_label] = source_series.map(_format_efficiency_percent)
        else:
            display_df[display_label] = source_series.fillna(AD_CAMPAIGN_EFFICIENCY_DISPLAY_EMPTY_VALUE).astype(str)

    return display_df.reset_index(drop=True)



def _resolve_efficiency_signal_style(signal_code: object) -> str:
    if signal_code == AD_CAMPAIGN_SIGNAL_GROWTH:
        return "background-color: #dcfce7; color: #166534; font-weight: 600;"
    if signal_code == AD_CAMPAIGN_SIGNAL_DECLINE:
        return "background-color: #fee2e2; color: #b91c1c; font-weight: 600;"
    if signal_code == AD_CAMPAIGN_SIGNAL_DROP_TO_ZERO:
        return "background-color: #dc2626; color: #ffffff; font-weight: 700;"
    if signal_code == AD_CAMPAIGN_SIGNAL_NEW_ACTIVITY:
        return "background-color: #dbeafe; color: #1d4ed8; font-weight: 600;"
    if signal_code == AD_CAMPAIGN_SIGNAL_INSUFFICIENT:
        return "background-color: #e5e7eb; color: #4b5563;"
    return ""



def style_ad_campaign_efficiency_display_table(
    display_df: pd.DataFrame,
    source_df: pd.DataFrame,
) -> pd.io.formats.style.Styler:
    styler = display_df.style
    if display_df.empty:
        return styler

    delta_columns = [column for column in ("Изменение", "Изменение, %") if column in display_df.columns]
    if not delta_columns or "signal_code" not in source_df.columns:
        return styler

    signal_codes = source_df.reset_index(drop=True).get("signal_code", pd.Series(dtype=object))

    def _style_delta_row(row: pd.Series) -> list[str]:
        signal_code = signal_codes.iloc[row.name] if row.name < len(signal_codes) else None
        style = _resolve_efficiency_signal_style(signal_code)
        return [style] * len(row)

    return styler.apply(_style_delta_row, axis=1, subset=delta_columns)


