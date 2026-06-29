from __future__ import annotations

import time
from datetime import date, datetime, UTC
from decimal import Decimal
from typing import Any, Mapping, Sequence

import requests
from sqlalchemy.orm import Session

from src.config.settings import settings
from src.db.models import FactWbSellerPriceSnapshot
from src.db.session import session_scope, upsert_rows
from src.tracked_products import get_tracked_nm_ids
from src.utils.logger import get_logger

logger = get_logger("wb_seller_price_loader")

def load_wb_seller_price_snapshot(
    *,
    snapshot_date: date | None = None,
    nm_ids: Sequence[int] | None = None,
    write_db: bool = True,
) -> dict[str, Any]:
    resolved_date = snapshot_date or date.today()
    target_nm_ids = nm_ids or get_tracked_nm_ids()
    
    if not target_nm_ids:
        logger.info("No tracked nm_ids found for loading seller prices.")
        return {
            "success": True,
            "resolved_date": resolved_date,
            "nm_ids_count": 0,
            "rows_inserted": 0,
        }

    token = settings.wb_token
    if not token:
        raise ValueError("WB_TOKEN не найден в настройках / переменных окружения")

    logger.info(f"Loading seller prices for {len(target_nm_ids)} products for date {resolved_date}")
    
    headers = {
        "Authorization": token,
        "Accept": "application/json"
    }
    url = "https://discounts-prices-api.wildberries.ru/api/v2/list/goods/filter"
    
    rows_to_save = []
    success_count = 0
    failed_count = 0
    
    for nm_id in target_nm_ids:
        params = {
            "limit": 10,
            "filterNmID": nm_id
        }
        try:
            res = requests.get(url, headers=headers, params=params, timeout=15)
            # Support Bearer prefix retry if raw token doesn't match directly
            if res.status_code in (401, 403) and not token.startswith("Bearer "):
                headers["Authorization"] = f"Bearer {token}"
                res = requests.get(url, headers=headers, params=params, timeout=15)
                
            if res.status_code != 200:
                logger.error(f"Failed to fetch seller price for nm_id {nm_id}: HTTP {res.status_code}")
                failed_count += 1
                continue
                
            data = res.json()
            list_goods = data.get("data", {}).get("listGoods", [])
            if not list_goods:
                logger.warning(f"No goods data returned for nm_id {nm_id}")
                continue
                
            goods = list_goods[0]
            discount = goods.get("discount", 0)
            sizes = goods.get("sizes", [])
            
            for size in sizes:
                chrt_id = size.get("sizeID")
                tech_size = size.get("techSizeName")
                price = size.get("price")
                seller_price = size.get("discountedPrice")
                
                if chrt_id is None:
                    continue
                    
                rows_to_save.append({
                    "snapshot_date": resolved_date,
                    "nm_id": nm_id,
                    "chrt_id": chrt_id,
                    "tech_size": tech_size,
                    "price": Decimal(str(price)) if price is not None else None,
                    "discount": int(discount) if discount is not None else None,
                    "seller_price": Decimal(str(seller_price)) if seller_price is not None else None,
                })
            success_count += 1
            # Sleep briefly to respect API rate limits
            time.sleep(0.1)
        except Exception as exc:
            logger.error(f"Error fetching seller price for nm_id {nm_id}: {exc}")
            failed_count += 1
            
    rows_inserted = 0
    if write_db and rows_to_save:
        with session_scope() as session:
            upsert_rows(
                session,
                FactWbSellerPriceSnapshot,
                rows_to_save,
                conflict_columns=("snapshot_date", "nm_id", "chrt_id")
            )
            rows_inserted = len(rows_to_save)
        logger.info(f"Successfully upserted {rows_inserted} price records into DB.")
        
    return {
        "success": failed_count == 0,
        "resolved_date": resolved_date,
        "nm_ids_count": len(target_nm_ids),
        "success_count": success_count,
        "failed_count": failed_count,
        "rows_inserted": rows_inserted,
    }
