from __future__ import annotations

from datetime import date
from pathlib import Path

import pandas as pd

from scripts.targeted_funnel_gap_fill import (
    FunnelGapRow,
    classify_row_result,
    load_gap_rows,
)


def test_load_gap_rows_parses_unique_nm_id_date_pairs(tmp_path: Path) -> None:
    path = tmp_path / "gap.csv"
    pd.DataFrame(
        [
            {
                "Дата": "2026-06-05",
                "Артикул продавца": "BlackWOM5",
                "Артикул WB": 197330807,
                "Что отсутствует": "Переходы в карточку,Положили в корзину,Заказы,Заказали на сумму",
                "Рекомендация": "точечно прогнать funnel API",
            },
            {
                "Дата": "2026-06-05",
                "Артикул продавца": "BlackWOM5",
                "Артикул WB": 197330807,
                "Что отсутствует": "Заказы",
                "Рекомендация": "duplicate row",
            },
        ]
    ).to_csv(path, index=False)

    rows = load_gap_rows(path)

    assert len(rows) == 1
    assert rows[0].report_date == date(2026, 6, 5)
    assert rows[0].nm_id == 197330807
    assert rows[0].missing_fields == ["card_clicks", "cart_count", "order_count", "order_sum"]


def test_classify_row_result_marks_filled_when_all_requested_fields_appear() -> None:
    gap_row = FunnelGapRow(
        report_date=date(2026, 6, 5),
        supplier_article="BlackWOM5",
        nm_id=197330807,
        missing_labels=["Переходы в карточку", "Заказы"],
        missing_fields=["card_clicks", "order_count"],
        recommendation="run api",
    )

    result = classify_row_result(
        gap_row=gap_row,
        before_state={"card_clicks": None, "order_count": None},
        after_state={"card_clicks": 100, "order_count": 5},
        status="OK",
        reason="",
        retries_used=0,
    )

    assert result.status == "FILLED"
    assert result.reason == "FILLED"
    assert result.newly_filled_fields == "card_clicks,order_count"
    assert result.remaining_missing_fields == ""


def test_classify_row_result_marks_partial_when_only_some_fields_appear() -> None:
    gap_row = FunnelGapRow(
        report_date=date(2026, 6, 5),
        supplier_article="BlackWOM5",
        nm_id=197330807,
        missing_labels=["Переходы в карточку", "Заказы"],
        missing_fields=["card_clicks", "order_count"],
        recommendation="run api",
    )

    result = classify_row_result(
        gap_row=gap_row,
        before_state={"card_clicks": None, "order_count": None},
        after_state={"card_clicks": 100, "order_count": None},
        status="OK",
        reason="",
        retries_used=0,
    )

    assert result.status == "PARTIAL"
    assert result.reason == "PARTIAL"
    assert result.newly_filled_fields == "card_clicks"
    assert result.remaining_missing_fields == "order_count"


def test_classify_row_result_keeps_no_data_when_nothing_changed() -> None:
    gap_row = FunnelGapRow(
        report_date=date(2026, 6, 5),
        supplier_article="BlackWOM5",
        nm_id=197330807,
        missing_labels=["Переходы в карточку"],
        missing_fields=["card_clicks"],
        recommendation="run api",
    )

    result = classify_row_result(
        gap_row=gap_row,
        before_state={"card_clicks": None},
        after_state={"card_clicks": None},
        status="OK",
        reason="",
        retries_used=0,
    )

    assert result.status == "NO_DATA"
    assert result.reason == "NO_DATA"
