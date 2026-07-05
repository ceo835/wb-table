from __future__ import annotations

from datetime import date
from typing import Sequence

from sqlalchemy import select
from sqlalchemy.orm import Session

from src.clients.wb_statistics_client import WBStatisticsClient
from src.config.settings import settings
from src.db.models import FactWbStatisticsOrderSizeDay, DimProductSize
from src.db.session import session_scope, upsert_rows
from src.utils.logger import get_logger

logger = get_logger("wb_statistics_order_size_loader")

FACT_WB_STATS_ORDER_SIZE_CONFLICT_COLUMNS = ("date", "nm_id", "barcode")


def load_wb_statistics_order_size(
    date_from: date,
    date_to: date | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Загружает заказы по размерам из Statistics API WB,
    агрегирует по дням/номенклатурам/размерам/баркодам,
    сопоставляет chrt_id и сохраняет в Postgres.
    """
    logger.info(f"Запуск загрузки заказов по размерам с {date_from} по {date_to or 'сейчас'}")
    
    # 1. Получаем данные из API
    client = WBStatisticsClient(token=settings.wb_token)
    response = client.wb_statistics_orders(date_from=date_from, date_to=date_to)
    
    if response is None:
        logger.error("Не удалось получить данные от WB Statistics API.")
        return {"status": "failed", "error": "API returned None"}
        
    records = []
    if isinstance(response, dict):
        records = response.get("data") or response.get("orders") or []
        if not isinstance(records, list):
            # В некоторых ответах это может быть список непосредственно, проверим
            records = []
    elif isinstance(response, list):
        records = response
        
    logger.info(f"Получено {len(records)} сырых записей заказов от API")
    if not records:
        return {
            "status": "success",
            "records_count": 0,
            "saved_count": 0,
            "match_stats": {
                "unique_nm_ids": 0,
                "unique_barcodes": 0,
                "unique_tech_sizes": 0,
                "matched_count": 0,
                "match_percent": 0.0
            }
        }

    # 2. Получаем справочник размеров для сопоставления chrt_id
    dim_lookup = {}
    with session_scope() as session:
        stmt = select(DimProductSize.nm_id, DimProductSize.chrt_id, DimProductSize.barcode)
        dim_rows = session.execute(stmt).all()
        for nm_id, chrt_id, barcode in dim_rows:
            if barcode:
                clean_bc = str(barcode).strip().replace(" ", "")
                dim_lookup[(int(nm_id), clean_bc)] = int(chrt_id)
                
    logger.info(f"Загружено {len(dim_lookup)} связок из справочника dim_product_size")

    # 3. Агрегируем данные
    aggregated_data = {}
    for r in records:
        raw_date = r.get("date")
        if not raw_date:
            continue
        dt_str = raw_date.split("T")[0]
        try:
            dt = date.fromisoformat(dt_str)
        except ValueError:
            continue
            
        nm_id = r.get("nmId")
        if nm_id is None:
            continue
        nm_id = int(nm_id)
        
        raw_bc = r.get("barcode")
        if not raw_bc:
            continue
        barcode = str(raw_bc).strip().replace(" ", "")
        
        tech_size = r.get("techSize")
        if tech_size:
            tech_size = str(tech_size).strip()
        else:
            tech_size = None
            
        is_cancel = bool(r.get("isCancel"))
        
        key = (dt, nm_id, barcode, tech_size)
        if key not in aggregated_data:
            aggregated_data[key] = {
                "order_count": 0,
                "cancel_count": 0
            }
        # Увеличиваем счетчик заказов на значение quantity (обычно 1)
        qty = r.get("quantity") or 1
        aggregated_data[key]["order_count"] += qty
        if is_cancel:
            aggregated_data[key]["cancel_count"] += qty

    # 4. Формируем строки для сохранения и считаем качество сопоставления
    db_rows = []
    matched_count = 0
    unique_nm_ids = set()
    unique_barcodes = set()
    unique_tech_sizes = set()
    
    for (dt, nm_id, barcode, tech_size), metrics in aggregated_data.items():
        chrt_id = dim_lookup.get((nm_id, barcode))
        if chrt_id is not None:
            matched_count += 1
            
        unique_nm_ids.add(nm_id)
        unique_barcodes.add(barcode)
        if tech_size:
            unique_tech_sizes.add(tech_size)
            
        db_rows.append({
            "date": dt,
            "nm_id": nm_id,
            "barcode": barcode,
            "chrt_id": chrt_id,
            "tech_size": tech_size,
            "order_count": metrics["order_count"],
            "cancel_count": metrics["cancel_count"],
        })

    total_aggregated = len(db_rows)
    match_percent = (matched_count / total_aggregated * 100.0) if total_aggregated > 0 else 0.0
    
    match_stats = {
        "unique_nm_ids": len(unique_nm_ids),
        "unique_barcodes": len(unique_barcodes),
        "unique_tech_sizes": len(unique_tech_sizes),
        "matched_count": matched_count,
        "match_percent": round(match_percent, 2)
    }
    
    logger.info(
        f"Качество сопоставления: сматчено {matched_count} из {total_aggregated} строк "
        f"({match_stats['match_percent']}%). Уникальных товаров: {match_stats['unique_nm_ids']}"
    )

    # 5. Сохраняем в базу данных
    saved_count = 0
    if not dry_run and db_rows:
        with session_scope() as session:
            saved_count = upsert_rows(
                session=session,
                model=FactWbStatisticsOrderSizeDay,
                rows=db_rows,
                conflict_columns=list(FACT_WB_STATS_ORDER_SIZE_CONFLICT_COLUMNS),
            )
        logger.info(f"Успешно сохранено {saved_count} строк в БД.")

    return {
        "status": "success",
        "records_count": len(records),
        "saved_count": saved_count,
        "match_stats": match_stats,
        "dry_run": dry_run
    }
