from __future__ import annotations

from datetime import date, datetime
from unittest.mock import MagicMock, patch

import pandas as pd
import pytest
from sqlalchemy import select

from src.db.models import FactWbStatisticsOrderSizeDay, DimProductSize
from src.db.session import session_scope
from src.db.wb_statistics_order_size_loader import load_wb_statistics_order_size
from app_streamlit import (
    load_size_sales_speed_data_from_db,
    get_size_sales_speed_yesterday2,
    get_size_sales_speed_week,
)


@pytest.fixture
def clean_db():
    with session_scope() as session:
        session.query(FactWbStatisticsOrderSizeDay).delete()
        session.query(DimProductSize).delete()
        session.commit()
    yield
    with session_scope() as session:
        session.query(FactWbStatisticsOrderSizeDay).delete()
        session.query(DimProductSize).delete()
        session.commit()


def test_wb_statistics_order_size_loader_saves_to_db(clean_db):
    # 1. Заполняем справочник размеров в БД
    with session_scope() as session:
        dim_item = DimProductSize(
            nm_id=99999,
            chrt_id=1234567,
            barcode="BC999",
            size_name="M",
            tech_size="M",
            source_status="TEST"
        )
        session.add(dim_item)
        session.commit()

    # 2. Мокаем ответ от Statistics API
    mock_response = [
        {
            "date": "2026-07-04T12:00:00",
            "nmId": 99999,
            "barcode": "BC999",
            "techSize": "M",
            "quantity": 1,
            "isCancel": False,
        },
        {
            "date": "2026-07-04T14:30:00",
            "nmId": 99999,
            "barcode": "BC999",
            "techSize": "M",
            "quantity": 1,
            "isCancel": True,
        },
        {
            "date": "2026-07-03T10:00:00",
            "nmId": 99999,
            "barcode": "BC999",
            "techSize": "M",
            "quantity": 2,
            "isCancel": False,
        },
        # Заказ без chrt_id (barcode не совпадает с димом)
        {
            "date": "2026-07-04T15:00:00",
            "nmId": 99999,
            "barcode": "MISSING_BC",
            "techSize": "S",
            "quantity": 1,
            "isCancel": False,
        }
    ]

    with patch("src.db.wb_statistics_order_size_loader.WBStatisticsClient") as MockClient:
        mock_client_instance = MagicMock()
        mock_client_instance.wb_statistics_orders.return_value = mock_response
        MockClient.return_value = mock_client_instance

        # Запуск лоадера
        res = load_wb_statistics_order_size(
            date_from=date(2026, 7, 3),
            date_to=date(2026, 7, 4),
            dry_run=False,
        )

        assert res["status"] == "success"
        assert res["records_count"] == 4
        assert res["saved_count"] in (3, -1)  # rowcount can be -1 in some PG configurations for upsert
        
        # Проверяем качество сопоставления
        assert res["match_stats"]["unique_nm_ids"] == 1
        assert res["match_stats"]["unique_barcodes"] == 2
        assert res["match_stats"]["matched_count"] == 2  # BC999 в обе даты сматчился
        assert res["match_stats"]["match_percent"] == 66.67  # 2 из 3 строк агрегированных сматчились

    # 3. Проверяем содержимое таблицы в БД
    with session_scope() as session:
        stmt = select(FactWbStatisticsOrderSizeDay).order_by(
            FactWbStatisticsOrderSizeDay.date,
            FactWbStatisticsOrderSizeDay.barcode
        )
        rows = session.execute(stmt).scalars().all()
        
        assert len(rows) == 3
        
        # 2026-07-03, BC999
        row0 = rows[0]
        assert row0.date == date(2026, 7, 3)
        assert row0.nm_id == 99999
        assert row0.barcode == "BC999"
        assert row0.chrt_id == 1234567
        assert row0.tech_size == "M"
        assert row0.order_count == 2
        assert row0.cancel_count == 0

        # 2026-07-04, BC999
        row1 = rows[1]
        assert row1.date == date(2026, 7, 4)
        assert row1.nm_id == 99999
        assert row1.barcode == "BC999"
        assert row1.chrt_id == 1234567
        assert row1.tech_size == "M"
        assert row1.order_count == 2  # 1+1
        assert row1.cancel_count == 1  # 1 отмененный

        # 2026-07-04, MISSING_BC (без chrt_id)
        row2 = rows[2]
        assert row2.date == date(2026, 7, 4)
        assert row2.nm_id == 99999
        assert row2.barcode == "MISSING_BC"
        assert row2.chrt_id is None
        assert row2.tech_size == "S"
        assert row2.order_count == 1
        assert row2.cancel_count == 0


def test_streamlit_size_sales_speed_calculations(clean_db):
    # Записываем тестовые продажи в БД
    with session_scope() as session:
        sales = [
            # Вчера (для snapshot_date=2026-07-05) - это D - 1 (2026-07-04)
            FactWbStatisticsOrderSizeDay(
                date=date(2026, 7, 4),
                nm_id=999,
                barcode="BC-M",
                chrt_id=111,
                tech_size="M",
                order_count=3,
                cancel_count=0
            ),
            # Позавчера - D - 2 (2026-07-03)
            FactWbStatisticsOrderSizeDay(
                date=date(2026, 7, 3),
                nm_id=999,
                barcode="BC-M",
                chrt_id=111,
                tech_size="M",
                order_count=2,
                cancel_count=0
            ),
            # Еще продажи за 2026-07-01
            FactWbStatisticsOrderSizeDay(
                date=date(2026, 7, 1),
                nm_id=999,
                barcode="BC-M",
                chrt_id=111,
                tech_size="M",
                order_count=9,
                cancel_count=0
            ),
        ]
        session.add_all(sales)
        session.commit()

    # Загружаем датафрейм продаж
    snapshot_date = date(2026, 7, 5)
    df = load_size_sales_speed_data_from_db(snapshot_date)
    
    assert not df.empty
    assert len(df) == 3

    # Проверяем расчет скорости за позавчера
    speed_y2 = get_size_sales_speed_yesterday2(df, snapshot_date, 999, "BC-M")
    assert speed_y2 == 2.0

    # Проверяем расчет средней скорости за неделю (7 завершенных дней)
    # Суммарные продажи: 3 (07-04) + 2 (07-03) + 9 (07-01) = 14.
    # Скорость = 14 / 7 = 2.0
    speed_week = get_size_sales_speed_week(df, snapshot_date, 999, "BC-M")
    assert speed_week == 2.0

    # Проверка на отсутствующий размер/баркод
    speed_y2_none = get_size_sales_speed_yesterday2(df, snapshot_date, 999, "NON-EXISTENT")
    assert speed_y2_none == 0.0
    
    speed_week_none = get_size_sales_speed_week(df, snapshot_date, 999, "NON-EXISTENT")
    assert speed_week_none == 0.0
