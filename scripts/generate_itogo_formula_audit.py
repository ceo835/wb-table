#!/usr/bin/env python3
from __future__ import annotations

import csv
import sys
from pathlib import Path


ROOT_DIR = Path(__file__).resolve().parent.parent
SRC_DIR = ROOT_DIR / "src"
if str(SRC_DIR) not in sys.path:
    sys.path.insert(0, str(SRC_DIR))
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

from src.db.models import MartTotalReport


OUTPUT_PATH = ROOT_DIR / "data" / "processed" / "itogo_formula_audit.csv"


AUDIT_ROWS = [
    {
        "formula_name": "Показы",
        "source_excel_formula": "из Воронка на день / API funnel",
        "current_mart_field": "impressions",
        "current_status": "OK",
        "action_needed": "",
        "comment": "поле уже в mart",
    },
    {
        "formula_name": "Переходы в карточку",
        "source_excel_formula": "из Воронка на день / API funnel, если API передаёт",
        "current_mart_field": "card_clicks",
        "current_status": "EXISTS_BUT_NEEDS_CHECK",
        "action_needed": "проверить NULL-handling и card_clicks_note",
        "comment": "API может не передавать переходы",
    },
    {
        "formula_name": "Положили в корзину",
        "source_excel_formula": "cart_count из funnel",
        "current_mart_field": "cart_count",
        "current_status": "OK",
        "action_needed": "",
        "comment": "поле уже в mart",
    },
    {
        "formula_name": "Заказали, шт",
        "source_excel_formula": "order_count из funnel",
        "current_mart_field": "order_count",
        "current_status": "OK",
        "action_needed": "",
        "comment": "поле уже в mart",
    },
    {
        "formula_name": "СиТиАр",
        "source_excel_formula": "card_clicks / impressions",
        "current_mart_field": "ctr_calc",
        "current_status": "EXISTS_BUT_NEEDS_CHECK",
        "action_needed": "проверить формулу и NULL при card_clicks NULL",
        "comment": "используется расчётное поле",
    },
    {
        "formula_name": "CTR",
        "source_excel_formula": "из funnel либо card_clicks / impressions * 100",
        "current_mart_field": "ctr_calc",
        "current_status": "EXISTS_BUT_NEEDS_CHECK",
        "action_needed": "сверить с card_clicks/impressions",
        "comment": "в Streamlit используется ctr_calc",
    },
    {
        "formula_name": "Конверсия в корзину, %",
        "source_excel_formula": "cart_count / card_clicks * 100",
        "current_mart_field": "add_to_cart_conversion_calc",
        "current_status": "EXISTS_BUT_NEEDS_CHECK",
        "action_needed": "проверить NULL при card_clicks NULL",
        "comment": "подтверждённый расчёт",
    },
    {
        "formula_name": "Конверсия в заказ, %",
        "source_excel_formula": "order_count / cart_count * 100",
        "current_mart_field": "cart_to_order_conversion_calc",
        "current_status": "EXISTS_BUT_NEEDS_CHECK",
        "action_needed": "проверить деление на 0",
        "comment": "подтверждённый расчёт",
    },
    {
        "formula_name": "Заказали на сумму, ₽",
        "source_excel_formula": "order_sum из funnel",
        "current_mart_field": "order_sum",
        "current_status": "OK",
        "action_needed": "",
        "comment": "поле уже в mart",
    },
    {
        "formula_name": "Сумма кампания",
        "source_excel_formula": "сумма рекламных расходов по кампаниям артикула",
        "current_mart_field": "ad_campaign_spend_total",
        "current_status": "OK",
        "action_needed": "",
        "comment": "берётся из fullstats aggregate",
    },
    {
        "formula_name": "Ассоциированные корзины",
        "source_excel_formula": "confirmed field BA из старого ИТОГО",
        "current_mart_field": "associated_ad_atbs",
        "current_status": "OK",
        "action_needed": "",
        "comment": "агрегируется по ASSOCIATED conversion",
    },
    {
        "formula_name": "Расход на все корзины",
        "source_excel_formula": "campaign_sum / (cart_count + associated_ad_atbs)",
        "current_mart_field": "ad_cost_per_all_carts_calc",
        "current_status": "MISSING_ADD_FIELD",
        "action_needed": "добавить поле и формулу в mart",
        "comment": "новое подтверждённое поле",
    },
    {
        "formula_name": "Органические корзины",
        "source_excel_formula": "cart_count - ad_atbs_total",
        "current_mart_field": "organic_cart_count",
        "current_status": "MISSING_ADD_FIELD",
        "action_needed": "добавить поле и формулу в mart",
        "comment": "новое подтверждённое поле",
    },
    {
        "formula_name": "Процент органических корзин от рекламных",
        "source_excel_formula": "organic_cart_count / ad_atbs_total * 100",
        "current_mart_field": "organic_cart_share_calc",
        "current_status": "EXISTS_BUT_NEEDS_CHECK",
        "action_needed": "заменить NEEDS_FORMULA_CONFIRMATION на подтверждённую формулу",
        "comment": "поле есть, формула требовала подтверждения",
    },
    {
        "formula_name": "Локальные заказы, %",
        "source_excel_formula": "из Воронка / либо из orders-geography",
        "current_mart_field": "local_orders_percent",
        "current_status": "EXISTS_BUT_NEEDS_CHECK",
        "action_needed": "оставить текущий API/funnel source, не придумывать Excel logic",
        "comment": "источник частичный, поле может быть NULL",
    },
]


def main() -> int:
    mart_columns = {column.name for column in MartTotalReport.__table__.columns}
    rows = []
    for row in AUDIT_ROWS:
        exists_in_mart = row["current_mart_field"] in mart_columns
        adjusted = dict(row)
        adjusted["exists_in_mart"] = "true" if exists_in_mart else "false"
        if not exists_in_mart and row["current_status"] == "OK":
            adjusted["current_status"] = "MISSING_ADD_FIELD"
        rows.append(adjusted)

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    with OUTPUT_PATH.open("w", encoding="utf-8-sig", newline="") as fh:
        writer = csv.DictWriter(
            fh,
            fieldnames=[
                "formula_name",
                "source_excel_formula",
                "current_mart_field",
                "exists_in_mart",
                "current_status",
                "action_needed",
                "comment",
            ],
        )
        writer.writeheader()
        writer.writerows(rows)

    print(OUTPUT_PATH)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
