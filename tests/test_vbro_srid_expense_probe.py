from __future__ import annotations

import json
from pathlib import Path

import pandas as pd

from src.reports.vbro_srid_expense_probe import (
    EXPENSE_FIELDS,
    TARGET_NM_IDS,
    aggregate_adv_fullstats_by_nm,
    aggregate_report_detail_by_rr_dt,
    aggregate_report_detail_matched_by_nm,
    aggregate_report_detail_matched_by_operation,
    aggregate_sales_by_nm,
    build_sales_srid_index,
    build_aggregate_summary,
    build_summary,
    prepare_sales_base,
    split_report_detail_rows,
)


def test_prepare_sales_base_keeps_only_target_nm_and_saleid_starting_with_s(tmp_path: Path) -> None:
    sales_path = tmp_path / "sales_raw.csv"
    pd.DataFrame(
        [
            {"nmId": 197330807, "supplierArticle": "BlackWOM5", "saleID": "S123", "srid": "srid-1"},
            {"nmId": 197330807, "supplierArticle": "BlackWOM5", "saleID": "R123", "srid": "srid-x"},
            {"nmId": 37320545, "supplierArticle": "Brand_Wom7Сlassic7", "saleID": "S456", "srid": "srid-2"},
            {"nmId": 999, "supplierArticle": "Other", "saleID": "S789", "srid": "srid-3"},
        ]
    ).to_csv(sales_path, index=False, encoding="utf-8-sig")

    result = prepare_sales_base(sales_path, TARGET_NM_IDS)

    assert len(result) == 2
    assert set(result["nmId"].tolist()) == {197330807, 37320545}
    assert set(result["saleID"].tolist()) == {"S123", "S456"}


def test_build_sales_srid_index_groups_srid_by_nm() -> None:
    sales_base = pd.DataFrame(
        [
            {"nmId": 197330807, "supplierArticle": "BlackWOM5", "srid": "srid-1"},
            {"nmId": 197330807, "supplierArticle": "BlackWOM5", "srid": "srid-2"},
            {"nmId": 37320545, "supplierArticle": "Brand_Wom7Сlassic7", "srid": "srid-3"},
        ]
    )

    result = build_sales_srid_index(sales_base)

    assert result["197330807"]["sales_rows_count"] == 2
    assert result["197330807"]["unique_srid_count"] == 2
    assert result["197330807"]["srids"] == ["srid-1", "srid-2"]
    assert result["37320545"]["srids"] == ["srid-3"]


def test_split_report_detail_rows_matches_by_srid_and_collects_unmatched_by_nm() -> None:
    sales_base = pd.DataFrame(
        [
            {"nmId": 197330807, "supplierArticle": "BlackWOM5", "srid": "srid-1"},
            {"nmId": 37320545, "supplierArticle": "Brand_Wom7Сlassic7", "srid": "srid-2"},
        ]
    )
    report_detail = pd.DataFrame(
        [
            {"nm_id": 197330807, "sa_name": "BlackWOM5", "srid": "srid-1", "supplier_oper_name": "Продажа"},
            {"nm_id": 37320545, "sa_name": "Brand_Wom7Сlassic7", "srid": "srid-x", "supplier_oper_name": "Логистика"},
            {"nm_id": 37320545, "sa_name": "Brand_Wom7Сlassic7", "srid": None, "supplier_oper_name": "Хранение"},
            {"nm_id": 999, "sa_name": "Other", "srid": "srid-z", "supplier_oper_name": "Продажа"},
        ]
    )

    matched, unmatched = split_report_detail_rows(report_detail, sales_base, TARGET_NM_IDS)

    assert len(matched) == 1
    assert matched.iloc[0]["srid"] == "srid-1"
    assert len(unmatched) == 2
    assert set(unmatched["supplier_oper_name"].tolist()) == {"Логистика", "Хранение"}


def test_build_summary_reports_only_technical_counts() -> None:
    sales_base = pd.DataFrame(
        [
            {"nmId": 197330807, "supplierArticle": "BlackWOM5", "srid": "srid-1"},
            {"nmId": 37320545, "supplierArticle": "Brand_Wom7Сlassic7", "srid": "srid-2"},
        ]
    )
    matched = pd.DataFrame(
        [
            {
                "nm_id": 197330807,
                "srid": "srid-1",
                "supplier_oper_name": "Продажа",
                "doc_type_name": "Продажа",
                "delivery_rub": 12.5,
                "storage_fee": 0,
                "deduction": None,
                "acceptance": 0,
                "penalty": 0,
                "additional_payment": 0,
                "rebill_logistic_cost": 0,
            }
        ]
    )
    unmatched = pd.DataFrame(
        [
            {
                "nm_id": 37320545,
                "srid": "",
                "supplier_oper_name": "Логистика",
                "doc_type_name": "",
                "delivery_rub": 0,
                "storage_fee": 4,
                "deduction": 0,
                "acceptance": 0,
                "penalty": 0,
                "additional_payment": 0,
                "rebill_logistic_cost": 7,
            }
        ]
    )
    all_rows = pd.concat([matched, unmatched], ignore_index=True)

    summary = build_summary(
        sales_base=sales_base,
        report_detail_extended=all_rows,
        matched_by_srid=matched,
        unmatched_by_nm=unmatched,
        sales_srid_index=build_sales_srid_index(sales_base),
        adv_fullstats_path=Path("adv_fullstats_raw.json"),
    )

    assert summary["sales_base_rows_count"] == 2
    assert summary["unique_srid_count"] == 2
    assert summary["matched_sales_srid_count"] == 1
    assert summary["missing_sales_srid_count"] == 1
    assert summary["supplier_oper_name_values"] == ["Логистика", "Продажа"]
    assert summary["doc_type_name_values"] == ["Продажа"]
    assert set(summary["nonzero_expense_fields"]) == {"delivery_rub", "storage_fee", "rebill_logistic_cost"}
    dumped = json.dumps(summary, ensure_ascii=False)
    for forbidden in ("profit", "margin", "organic", "formula"):
        assert forbidden not in dumped.lower()
    assert set(summary["expense_fields_checked"]) == set(EXPENSE_FIELDS)


def test_aggregate_sales_by_nm_builds_expected_totals() -> None:
    sales_base = pd.DataFrame(
        [
            {
                "nmId": 197330807,
                "supplierArticle": "BlackWOM5",
                "saleID": "S1",
                "srid": "srid-1",
                "forPay": 100,
                "finishedPrice": 150,
                "priceWithDisc": 140,
                "totalPrice": 200,
            },
            {
                "nmId": 197330807,
                "supplierArticle": "BlackWOM5",
                "saleID": "S2",
                "srid": "srid-2",
                "forPay": 120,
                "finishedPrice": 170,
                "priceWithDisc": 160,
                "totalPrice": 220,
            },
        ]
    )

    result = aggregate_sales_by_nm(sales_base)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["sales_rows_count"] == 2
    assert row["unique_srid_count"] == 2
    assert row["sum_forPay"] == 220
    assert row["avg_finishedPrice"] == 160
    assert row["min_forPay"] == 100
    assert row["max_finishedPrice"] == 170


def test_aggregate_report_detail_outputs_expected_groupings() -> None:
    matched = pd.DataFrame(
        [
            {
                "nm_id": 197330807,
                "sa_name": "BlackWOM5",
                "supplier_oper_name": "Продажа",
                "doc_type_name": "Продажа",
                "srid": "srid-1",
                "quantity": 1,
                "retail_amount": 200,
                "retail_price_withdisc_rub": 180,
                "ppvz_for_pay": 100,
                "ppvz_reward": 10,
                "ppvz_sales_commission": 5,
                "acquiring_fee": 2,
                "ppvz_vw": 3,
                "ppvz_vw_nds": 1,
                "delivery_amount": 0,
                "return_amount": 0,
                "delivery_rub": 8,
                "storage_fee": 0,
                "deduction": 0,
                "acceptance": 0,
                "penalty": 0,
                "additional_payment": 0,
                "rebill_logistic_cost": 0,
                "rr_dt": "2026-05-25",
            },
            {
                "nm_id": 197330807,
                "sa_name": "BlackWOM5",
                "supplier_oper_name": "Возврат",
                "doc_type_name": "Возврат",
                "srid": "srid-1",
                "quantity": 1,
                "retail_amount": 200,
                "retail_price_withdisc_rub": 180,
                "ppvz_for_pay": -100,
                "ppvz_reward": -10,
                "ppvz_sales_commission": -5,
                "acquiring_fee": -2,
                "ppvz_vw": -3,
                "ppvz_vw_nds": -1,
                "delivery_amount": 0,
                "return_amount": 1,
                "delivery_rub": 0,
                "storage_fee": 0,
                "deduction": 0,
                "acceptance": 0,
                "penalty": 4,
                "additional_payment": 0,
                "rebill_logistic_cost": 6,
                "rr_dt": "2026-05-26",
            },
        ]
    )

    by_operation = aggregate_report_detail_matched_by_operation(matched)
    by_nm = aggregate_report_detail_matched_by_nm(matched)
    by_rr_dt = aggregate_report_detail_by_rr_dt(matched)

    assert len(by_operation) == 2
    assert set(by_operation["supplier_oper_name"].tolist()) == {"Продажа", "Возврат"}
    nm_row = by_nm.iloc[0]
    assert nm_row["sale_quantity_sum"] == 1
    assert nm_row["return_quantity_sum"] == 1
    assert nm_row["delivery_rub_sum"] == 8
    assert nm_row["penalty_sum"] == 4
    assert len(by_rr_dt) == 2
    assert sorted(by_rr_dt["rr_dt"].tolist()) == ["2026-05-25", "2026-05-26"]


def test_aggregate_adv_fullstats_by_nm_flattens_nested_payload() -> None:
    raw_payload = {
        "requests": [
            {
                "advert_ids": [123],
                "payload": [
                    {
                        "advertId": 123,
                        "days": [
                            {
                                "date": "2026-05-23",
                                "apps": [
                                    {
                                        "nms": [
                                            {
                                                "nmId": 197330807,
                                                "views": 10,
                                                "clicks": 2,
                                                "atbs": 1,
                                                "orders": 1,
                                                "shks": 1,
                                                "sum": 50,
                                                "sum_price": 100,
                                            },
                                            {
                                                "nmId": 197330807,
                                                "views": 20,
                                                "clicks": 3,
                                                "atbs": 2,
                                                "orders": 1,
                                                "shks": 2,
                                                "sum": 70,
                                                "sum_price": 120,
                                            },
                                        ]
                                    }
                                ],
                            }
                        ],
                    }
                ],
            }
        ]
    }

    result = aggregate_adv_fullstats_by_nm(raw_payload)

    assert len(result) == 1
    row = result.iloc[0]
    assert row["nmId"] == 197330807
    assert row["rows_count"] == 2
    assert row["sum_views"] == 30
    assert row["sum_clicks"] == 5
    assert row["sum_sum"] == 120
    assert row["unique_campaign_count"] == 1


def test_build_aggregate_summary_is_technical_only() -> None:
    matched = pd.DataFrame(
        [
            {
                "supplier_oper_name": "Продажа",
                "doc_type_name": "Продажа",
                "delivery_rub": 10,
                "storage_fee": 0,
                "deduction": 0,
                "acceptance": 0,
                "penalty": 2,
                "additional_payment": 0,
                "rebill_logistic_cost": 0,
            }
        ]
    )

    summary = build_aggregate_summary(
        source_files=["a.csv", "b.csv"],
        aggregate_frames={
            "agg_sales_by_nm": pd.DataFrame([{"nmId": 1}]),
            "agg_report_detail_matched_by_operation": pd.DataFrame([{"nm_id": 1}]),
        },
        matched_by_srid=matched,
    )

    assert summary["aggregate_row_counts"]["agg_sales_by_nm"] == 1
    assert summary["nonzero_financial_fields"] == ["delivery_rub", "penalty"]
    dumped = json.dumps(summary, ensure_ascii=False).lower()
    for forbidden in ("profit", "margin", "organic", "formula"):
        assert forbidden not in dumped
