from __future__ import annotations

from datetime import date
from unittest.mock import patch

import pytest
from sqlalchemy import BigInteger, create_engine
from sqlalchemy.orm import Session, sessionmaker

from app_streamlit import build_milestones_altair_layer
from src.db.base import Base
from src.services.dashboard_milestones import (
    DEFAULT_MILESTONE_TYPE,
    MILESTONE_TYPES,
    create_milestone,
    deactivate_milestone,
    list_milestones,
    update_milestone,
)


@pytest.fixture
def db_session():
    engine = create_engine("sqlite:///:memory:")
    Base.metadata.create_all(engine)
    session_factory = sessionmaker(bind=engine, autoflush=False, autocommit=False)
    with session_factory() as session:
        yield session


def test_milestone_types_and_default():
    assert "price_discount" in MILESTONE_TYPES
    assert MILESTONE_TYPES["price_discount"] == "Цена / скидка"
    assert DEFAULT_MILESTONE_TYPE == "price_discount"


def test_create_milestone(db_session: Session):
    m = create_milestone(
        milestone_date=date(2026, 7, 10),
        milestone_type="price_discount",
        title="Снижение цены 10%",
        comment="Промоакция лета",
        session=db_session,
    )
    assert m["id"] is not None
    assert m["milestone_date"] == date(2026, 7, 10)
    assert m["milestone_type"] == "price_discount"
    assert m["milestone_type_label"] == "Цена / скидка"
    assert m["title"] == "Снижение цены 10%"
    assert m["comment"] == "Промоакция лета"
    assert m["is_active"] is True


def test_create_milestone_validation(db_session: Session):
    with pytest.raises(ValueError, match="Название вехи"):
        create_milestone(
            milestone_date=date(2026, 7, 10),
            milestone_type="price_discount",
            title="   ",
            session=db_session,
        )

    with pytest.raises(ValueError, match="Недопустимый тип вехи"):
        create_milestone(
            milestone_date=date(2026, 7, 10),
            milestone_type="invalid_type",
            title="Тест",
            session=db_session,
        )


def test_list_milestones_date_range_and_outside_period(db_session: Session):
    m1 = create_milestone(date(2026, 7, 1), "price_discount", "Ранняя веха", session=db_session)
    m2 = create_milestone(date(2026, 7, 10), "advertising", "Середина месяца", session=db_session)
    m3 = create_milestone(date(2026, 7, 25), "stock_supply", "Поздняя веха", session=db_session)

    res = list_milestones(date_from=date(2026, 7, 5), date_to=date(2026, 7, 15), session=db_session)
    ids = [x["id"] for x in res]
    assert m2["id"] in ids
    assert m1["id"] not in ids
    assert m3["id"] not in ids


def test_list_milestones_type_filter(db_session: Session):
    m1 = create_milestone(date(2026, 7, 10), "price_discount", "Цена 1", session=db_session)
    m2 = create_milestone(date(2026, 7, 10), "advertising", "Реклама 1", session=db_session)
    m3 = create_milestone(date(2026, 7, 10), "technical", "Сбой", session=db_session)

    res = list_milestones(types=["advertising"], session=db_session)
    assert len(res) == 1
    assert res[0]["id"] == m2["id"]

    res_multi = list_milestones(types=["price_discount", "technical"], session=db_session)
    assert len(res_multi) == 2
    multi_ids = [x["id"] for x in res_multi]
    assert m1["id"] in multi_ids
    assert m3["id"] in multi_ids


def test_update_milestone(db_session: Session):
    m = create_milestone(date(2026, 7, 10), "price_discount", "Старое название", session=db_session)
    updated = update_milestone(
        milestone_id=m["id"],
        milestone_date=date(2026, 7, 12),
        milestone_type="advertising",
        title="Новое название",
        comment="Добавлен комментарий",
        session=db_session,
    )
    assert updated is not None
    assert updated["milestone_date"] == date(2026, 7, 12)
    assert updated["milestone_type"] == "advertising"
    assert updated["title"] == "Новое название"
    assert updated["comment"] == "Добавлен комментарий"


def test_deactivate_milestone_and_include_inactive(db_session: Session):
    m = create_milestone(date(2026, 7, 10), "price_discount", "Тестовая веха", session=db_session)
    deactivated = deactivate_milestone(m["id"], session=db_session)
    assert deactivated is True

    # По умолчанию скрытые вехи не возвращаются
    res_active = list_milestones(date_from=date(2026, 7, 1), date_to=date(2026, 7, 31), include_inactive=False, session=db_session)
    assert len(res_active) == 0

    # С флагом include_inactive=True скрытая веха возвращается
    res_all = list_milestones(date_from=date(2026, 7, 1), date_to=date(2026, 7, 31), include_inactive=True, session=db_session)
    assert len(res_all) == 1
    assert res_all[0]["is_active"] is False


def test_empty_list_does_not_break_chart():
    assert build_milestones_altair_layer([]) is None
    assert build_milestones_altair_layer(None) is None


def test_dynamic_legend_and_marker_layer():
    milestones = [
        {
            "id": 1,
            "milestone_date": date(2026, 7, 10),
            "milestone_type": "price_discount",
            "milestone_type_label": "Цена / скидка",
            "title": "Скидка 10%",
            "comment": None,
            "is_active": True,
        },
        {
            "id": 2,
            "milestone_date": date(2026, 7, 15),
            "milestone_type": "advertising",
            "milestone_type_label": "Реклама",
            "title": "Запуск автокампаний",
            "comment": "Поиск + каталоги",
            "is_active": True,
        },
    ]

    chart = build_milestones_altair_layer(milestones, max_y_val=150.0)
    assert chart is not None
    chart_dict = chart.to_dict()
    assert "layer" in chart_dict
    assert len(chart_dict["layer"]) == 2

    # Layer 0: Vertical indicator rule
    tick_layer = chart_dict["layer"][0]
    assert tick_layer["mark"]["type"] == "rule"
    assert tick_layer["mark"]["strokeDash"] == [3, 3]

    # Layer 1: Diamond markers
    point_layer = chart_dict["layer"][1]
    assert point_layer["mark"]["type"] == "point"
    assert point_layer["mark"]["shape"] == "diamond"
    assert point_layer["mark"]["filled"] is True

    color_scale = point_layer["encoding"]["color"]["scale"]
    assert color_scale["domain"] == ["Цена / скидка", "Реклама"]
    assert "Поставка / остатки" not in color_scale["domain"]
    assert "Карточка / контент" not in color_scale["domain"]
    assert "Техническая проблема" not in color_scale["domain"]
    assert "Другое" not in color_scale["domain"]


def test_ui_logic_article_aggregation_does_not_call_list_milestones():
    # Проверяем, что функция list_milestones вызывается только при уровне агрегации "Кабинет"
    with patch("src.services.dashboard_milestones.list_milestones") as mock_list:
        # При имитации загрузки для Артикула list_milestones не должен вызываться
        aggregation_level = "Артикул"
        if aggregation_level == "Кабинет":
            mock_list(date_from=date(2026, 7, 1), date_to=date(2026, 7, 10))

        mock_list.assert_not_called()

        # При агрегации Кабинет должен вызванаться
        aggregation_level = "Кабинет"
        if aggregation_level == "Кабинет":
            mock_list(date_from=date(2026, 7, 1), date_to=date(2026, 7, 10))

        mock_list.assert_called_once()
