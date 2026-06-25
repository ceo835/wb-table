from __future__ import annotations

from decimal import Decimal
from typing import Any, Mapping, Sequence

from sqlalchemy.orm import Session

from src.db.models import (
    SettingsLostProfitMarketArea,
    SettingsLostProfitWarehouseArea,
    SettingsLostProfitQueryGroupCoefficient,
)
from src.db.session import session_scope, upsert_rows


MARKET_AREA_CONFLICT_COLUMNS = ("market_area_code",)
WAREHOUSE_AREA_CONFLICT_COLUMNS = ("warehouse_name",)
DEFAULT_APPROVAL_STATUS = "pending_ivan_review"
DEFAULT_MARKET_AREA_SOURCE = "manual_seed_v1"

INITIAL_MARKET_AREAS: list[dict[str, Any]] = [
    {
        "market_area_code": "vladimir_area",
        "market_area_name": "Владимир / городской округ",
        "population_people": 344242,
        "population_share_pct": Decimal("0.236"),
        "source": DEFAULT_MARKET_AREA_SOURCE,
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Пока считаем городской округ Владимир",
    },
    {
        "market_area_code": "tula_novomoskovsk_agglomeration",
        "market_area_name": "Тульско-Новомосковская агломерация",
        "population_people": 1001700,
        "population_share_pct": Decimal("0.686"),
        "source": DEFAULT_MARKET_AREA_SOURCE,
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Расширенная зона вместо города Тула",
    },
    {
        "market_area_code": "kazan",
        "market_area_name": "Казань",
        "population_people": 1330000,
        "population_share_pct": Decimal("0.911"),
        "source": DEFAULT_MARKET_AREA_SOURCE,
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Пока считаем город Казань",
    },
    {
        "market_area_code": "izhevsk_udmurt_area",
        "market_area_name": "Ижевская агломерация / Удмуртская зона",
        "population_people": 1000000,
        "population_share_pct": Decimal("0.685"),
        "source": DEFAULT_MARKET_AREA_SOURCE,
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Расширенная зона покрытия вместо города Сарапул",
    },
    {
        "market_area_code": "spb",
        "market_area_name": "Санкт-Петербург",
        "population_people": 5653000,
        "population_share_pct": Decimal("3.871"),
        "source": DEFAULT_MARKET_AREA_SOURCE,
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Шушары считаем как Санкт-Петербург",
    },
    {
        "market_area_code": "volgograd",
        "market_area_name": "Волгоград",
        "population_people": 1012000,
        "population_share_pct": Decimal("0.693"),
        "source": DEFAULT_MARKET_AREA_SOURCE,
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Пока считаем город Волгоград",
    },
    {
        "market_area_code": "krasnodar",
        "market_area_name": "Краснодар",
        "population_people": 1155000,
        "population_share_pct": Decimal("0.791"),
        "source": DEFAULT_MARKET_AREA_SOURCE,
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Пока считаем город Краснодар",
    },
    {
        "market_area_code": "ekaterinburg",
        "market_area_name": "Екатеринбург",
        "population_people": 1548000,
        "population_share_pct": Decimal("1.060"),
        "source": DEFAULT_MARKET_AREA_SOURCE,
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Пока считаем город Екатеринбург",
    },
]

INITIAL_WAREHOUSE_AREAS: list[dict[str, Any]] = [
    {
        "warehouse_name": "Владимир WB",
        "market_area_code": "vladimir_area",
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Связь склада с зоной покрытия",
    },
    {
        "warehouse_name": "Тула",
        "market_area_code": "tula_novomoskovsk_agglomeration",
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Связь склада с расширенной зоной покрытия",
    },
    {
        "warehouse_name": "Казань",
        "market_area_code": "kazan",
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Связь склада с зоной покрытия",
    },
    {
        "warehouse_name": "Сарапул WB",
        "market_area_code": "izhevsk_udmurt_area",
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Сарапул считаем через Ижевскую/Удмуртскую зону",
    },
    {
        "warehouse_name": "Склад СПБ Шушары Московское",
        "market_area_code": "spb",
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Шушары считаем как Санкт-Петербург",
    },
    {
        "warehouse_name": "Волгоград",
        "market_area_code": "volgograd",
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Связь склада с зоной покрытия",
    },
    {
        "warehouse_name": "Краснодар",
        "market_area_code": "krasnodar",
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Связь склада с зоной покрытия",
    },
    {
        "warehouse_name": "Екатеринбург - Перспективная 14",
        "market_area_code": "ekaterinburg",
        "approval_status": DEFAULT_APPROVAL_STATUS,
        "comment": "Связь склада с зоной покрытия",
    },
]


def _normalize_decimal(value: Any) -> Decimal:
    if isinstance(value, Decimal):
        return value
    return Decimal(str(value))


def prepare_market_area_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: dict[str, dict[str, Any]] = {}
    for row in rows:
        code = str(row.get("market_area_code") or "").strip()
        if not code:
            continue
        name = str(row.get("market_area_name") or "").strip()
        if not name:
            continue
        population_people = row.get("population_people")
        share = row.get("population_share_pct")
        if population_people in (None, "") or share in (None, ""):
            continue
        deduplicated[code] = {
            "market_area_code": code,
            "market_area_name": name,
            "population_people": int(population_people),
            "population_share_pct": _normalize_decimal(share),
            "source": row.get("source") or None,
            "approval_status": str(row.get("approval_status") or DEFAULT_APPROVAL_STATUS),
            "comment": row.get("comment") or None,
        }
    return list(deduplicated.values())


def prepare_warehouse_area_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: dict[str, dict[str, Any]] = {}
    for row in rows:
        warehouse_name = str(row.get("warehouse_name") or "").strip()
        market_area_code = str(row.get("market_area_code") or "").strip()
        if not warehouse_name or not market_area_code:
            continue
        deduplicated[warehouse_name] = {
            "warehouse_name": warehouse_name,
            "market_area_code": market_area_code,
            "approval_status": str(row.get("approval_status") or DEFAULT_APPROVAL_STATUS),
            "comment": row.get("comment") or None,
        }
    return list(deduplicated.values())


def upsert_market_area_rows(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_market_area_upsert_rows(rows)
    return upsert_rows(
        session=session,
        model=SettingsLostProfitMarketArea,
        rows=prepared_rows,
        conflict_columns=MARKET_AREA_CONFLICT_COLUMNS,
    )


def upsert_warehouse_area_rows(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_warehouse_area_upsert_rows(rows)
    return upsert_rows(
        session=session,
        model=SettingsLostProfitWarehouseArea,
        rows=prepared_rows,
        conflict_columns=WAREHOUSE_AREA_CONFLICT_COLUMNS,
    )


def seed_lost_profit_settings_to_db(*, apply: bool) -> dict[str, Any]:
    market_rows = prepare_market_area_upsert_rows(INITIAL_MARKET_AREAS)
    warehouse_rows = prepare_warehouse_area_upsert_rows(INITIAL_WAREHOUSE_AREAS)
    summary = {
        "apply": bool(apply),
        "market_areas_count": len(market_rows),
        "warehouse_areas_count": len(warehouse_rows),
        "market_area_codes": [row["market_area_code"] for row in market_rows],
        "warehouse_names": [row["warehouse_name"] for row in warehouse_rows],
        "rows_upserted_market_areas": 0,
        "rows_upserted_warehouse_areas": 0,
    }
    if not apply:
        return summary

    with session_scope() as session:
        summary["rows_upserted_market_areas"] = upsert_market_area_rows(session, market_rows)
        summary["rows_upserted_warehouse_areas"] = upsert_warehouse_area_rows(session, warehouse_rows)
    return summary


def prepare_query_group_coefficient_upsert_rows(rows: Sequence[Mapping[str, Any]]) -> list[dict[str, Any]]:
    deduplicated: dict[str, dict[str, Any]] = {}
    for row in rows:
        query_group = str(row.get("query_group") or "").strip()
        if not query_group:
            continue
        conversion = row.get("search_to_order_conversion")
        deduplicated[query_group] = {
            "query_group": query_group,
            "search_to_order_conversion": _normalize_decimal(conversion) if conversion not in (None, "") else None,
            "approval_status": str(row.get("approval_status") or DEFAULT_APPROVAL_STATUS),
            "comment": row.get("comment") or None,
        }
    return list(deduplicated.values())


def upsert_query_group_coefficient_rows(session: Session, rows: Sequence[Mapping[str, Any]]) -> int:
    prepared_rows = prepare_query_group_coefficient_upsert_rows(rows)
    return upsert_rows(
        session=session,
        model=SettingsLostProfitQueryGroupCoefficient,
        rows=prepared_rows,
        conflict_columns=("query_group",),
    )


def seed_lost_profit_query_group_coefficients_to_db(*, apply: bool) -> dict[str, Any]:
    initial_coefficients = [
        {
            "query_group": "women_underwear",
            "search_to_order_conversion": Decimal("0.0025"),
            "approval_status": "pending_ivan_review",
            "comment": "Коэффициент из ТЗ Ивана",
        }
    ]
    coefficient_rows = prepare_query_group_coefficient_upsert_rows(initial_coefficients)
    summary = {
        "apply": bool(apply),
        "coefficients_count": len(coefficient_rows),
        "query_groups": [row["query_group"] for row in coefficient_rows],
        "rows_upserted_coefficients": 0,
    }
    if not apply:
        return summary

    with session_scope() as session:
        summary["rows_upserted_coefficients"] = upsert_query_group_coefficient_rows(session, coefficient_rows)
    return summary

