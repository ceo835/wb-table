from __future__ import annotations

import pandas as pd

from app_streamlit import (
    DISPLAY_COLUMNS_BY_DATE,
    TECHNICAL_EXTRA_COLUMNS_BY_DATE,
    build_export_dataframe,
    build_data_quality_label,
    filter_products_with_period_data,
    build_grouped_by_date_dataset,
    build_import_format_error,
    build_last_upload_result,
    build_latest_snapshot_dataset,
    build_pipeline_status_messages,
    build_product_timeline_dataset,
    build_warnings,
    can_apply_import_summary,
    format_delta,
    get_app_password,
    get_latest_product_context,
    get_previous_product_date,
    is_password_protection_enabled,
    resolve_data_source,
    prepare_dataframe,
    resolve_effective_import_date,
    resolve_export_range,
    summarize_available_dates,
)


def test_prepare_dataframe_builds_data_quality_status_when_missing() -> None:
    df = pd.DataFrame(
        [
            {
                "report_date": "2026-05-31",
                "has_funnel": True,
                "has_stock": False,
                "has_ad_cost": False,
                "has_ad_campaign": False,
                "has_search": False,
                "has_localization_partial": False,
            },
            {
                "report_date": "2026-05-31",
                "has_funnel": False,
                "has_stock": False,
                "has_ad_cost": False,
                "has_ad_campaign": False,
                "has_search": False,
                "has_localization_partial": False,
            },
        ]
    )

    prepared = prepare_dataframe(df)

    assert "data_quality_status" in prepared.columns
    assert prepared.loc[0, "data_quality_status"] == "OK_PARTIAL_SOURCES"
    assert prepared.loc[1, "data_quality_status"] == "NO_DATA"


def test_prepare_dataframe_keeps_existing_data_quality_status() -> None:
    df = pd.DataFrame(
        [
            {
                "report_date": "2026-05-31",
                "has_funnel": True,
                "has_stock": False,
                "has_ad_cost": False,
                "has_ad_campaign": False,
                "has_search": False,
                "has_localization_partial": False,
                "data_quality_status": "CUSTOM_STATUS",
            }
        ]
    )

    prepared = prepare_dataframe(df)

    assert prepared.loc[0, "data_quality_status"] == "CUSTOM_STATUS"


def test_prepare_dataframe_builds_note_columns() -> None:
    df = pd.DataFrame(
        [
            {
                "report_date": "2026-06-07",
                "has_funnel": True,
                "has_stock": False,
                "has_ad_cost": False,
                "has_ad_campaign": False,
                "has_search": False,
                "has_localization_partial": False,
                "orders_geography_status": "FILE_IMPORT_PENDING",
                "entry_point_status": "FILE_IMPORT_PENDING",
                "vbro_status": "MANUAL_PENDING",
                "card_clicks": None,
                "impressions": 10,
                "cart_count": None,
                "order_count": None,
            }
        ]
    )

    prepared = prepare_dataframe(df)

    row = prepared.iloc[0]
    assert row["card_clicks_note"] == "API не передал переходы в карточку"
    assert row["funnel_data_note"] == "Воронка есть, но WB отдал неполные данные"
    assert row["search_data_note"] == "Нет данных поиска за дату или источник не отдал"
    assert row["stock_data_note"] == "Нет snapshot остатков за дату"
    assert row["localization_data_note"] == "Ожидается файл География"
    assert row["entry_point_data_note"] == "Ожидается файл Точка входа"
    assert row["vbro_data_note"] == "Ожидается ручной ввод/файл ВБро"


def test_prepare_dataframe_uses_entry_point_fallback_for_main_impressions_and_ctr() -> None:
    df = pd.DataFrame(
        [
            {
                "report_date": "2026-06-07",
                "has_funnel": True,
                "has_stock": False,
                "has_ad_cost": False,
                "has_ad_campaign": False,
                "has_search": False,
                "has_localization_partial": False,
                "orders_geography_status": "FILE_IMPORT_PENDING",
                "entry_point_status": "CSV_EXPORT",
                "vbro_status": "MANUAL_PENDING",
                "impressions": None,
                "ctr_calc": None,
                "entry_impressions_total": 138486,
                "entry_ctr_calc": 4.417775,
            }
        ]
    )

    prepared = prepare_dataframe(df)
    row = prepared.iloc[0]

    assert float(row["impressions"]) == 138486.0
    assert float(row["ctr_calc"]) == 4.417775
    assert row["impressions_source_note"] == "Показы взяты из файла Точка входа"


def test_build_export_dataframe_does_not_create_duplicate_pokazy_columns() -> None:
    table_df = pd.DataFrame(
        [
            {
                "report_date": "2026-06-07",
                "supplier_article": "BlackWOM5",
                "nm_id": 197330807,
                "title": "Товар",
                "impressions": 138486,
                "impressions_source_note": "Показы взяты из файла Точка входа",
                "entry_impressions_total": 138486,
                "entry_card_clicks_total": 6118,
                "entry_ctr_calc": 4.417775,
                "card_clicks": 6125,
                "ctr_calc": 4.417775,
                "entry_point_status": "CSV_EXPORT",
            }
        ]
    )

    export_df = build_export_dataframe(
        table_df,
        [
            "report_date",
            "supplier_article",
            "nm_id",
            "title",
            "impressions",
            "impressions_source_note",
            "entry_impressions_total",
            "entry_card_clicks_total",
            "entry_ctr_calc",
            "card_clicks",
            "ctr_calc",
            "entry_point_status",
        ],
    )

    assert "Показы.1" not in export_df.columns
    assert list(export_df.columns).count("Показы") == 1
    assert export_df.columns.is_unique


def test_prepare_dataframe_builds_human_readable_source_labels() -> None:
    df = pd.DataFrame(
        [
            {
                "report_date": "2026-06-07",
                "has_funnel": True,
                "has_stock": False,
                "has_ad_cost": False,
                "has_ad_campaign": False,
                "has_search": False,
                "has_localization_partial": True,
                "entry_point_status": "CSV_EXPORT",
                "orders_geography_status": "CSV_EXPORT",
                "vbro_status": "MANUAL_PENDING",
                "organic_cart_share_status": "MISSING_SOURCE",
            },
            {
                "report_date": "2026-06-07",
                "has_funnel": False,
                "has_stock": False,
                "has_ad_cost": False,
                "has_ad_campaign": False,
                "has_search": False,
                "has_localization_partial": False,
                "entry_point_status": "FILE_IMPORT_PENDING",
                "orders_geography_status": "FILE_IMPORT_PENDING",
                "vbro_status": None,
                "organic_cart_share_status": None,
                "entry_impressions_total": None,
                "entry_card_clicks_total": None,
                "has_entry_points": False,
            },
            {
                "report_date": "2026-06-06",
                "has_funnel": False,
                "has_stock": False,
                "has_ad_cost": False,
                "has_ad_campaign": False,
                "has_search": False,
                "has_localization_partial": True,
                "entry_point_status": "FILE_IMPORT_PENDING",
                "orders_geography_status": "FILE_IMPORT_PENDING",
                "vbro_status": None,
                "organic_cart_share_status": "OK",
            },
        ]
    )

    prepared = prepare_dataframe(df)

    first = prepared.iloc[0]
    second = prepared.iloc[1]
    third = prepared.iloc[2]
    assert first["entry_point_source_label"] == "Файл загружен"
    assert first["orders_geography_source_label"] == "Файл загружен"
    assert first["vbro_status_label"] == "Не внесено"
    assert first["organic_formula_status_label"] == "Недостаточно данных"
    assert second["entry_point_source_label"] == "Нет строки в файле"
    assert second["orders_geography_source_label"] == "Файл не загружен за дату"
    assert second["organic_formula_status_label"] == "—"
    assert third["entry_point_source_label"] == "Файл не загружен за дату"
    assert third["orders_geography_source_label"] == "Есть частичные API-данные"
    assert third["organic_formula_status_label"] == "Рассчитано"


def test_build_export_dataframe_fills_group_label_for_every_row() -> None:
    table_df = pd.DataFrame(
        [
            {"product_group_label": "▼ BlackWOM5 | 197330807", "supplier_article": "BlackWOM5", "nm_id": 197330807},
            {"product_group_label": "", "supplier_article": "BlackWOM5", "nm_id": 197330807},
        ]
    )

    export_df = build_export_dataframe(table_df, ["product_group_label", "supplier_article", "nm_id"])

    assert export_df.iloc[0, 0] == "BlackWOM5 | 197330807"
    assert export_df.iloc[1, 0] == "BlackWOM5 | 197330807"


def test_prepare_dataframe_keeps_new_itogo_formula_fields() -> None:
    df = pd.DataFrame(
        [
            {
                "report_date": "2026-06-07",
                "has_funnel": True,
                "has_stock": False,
                "has_ad_cost": True,
                "has_ad_campaign": True,
                "has_search": False,
                "has_localization_partial": False,
                "organic_cart_count": "12",
                "organic_cart_share_calc": "40.5",
                "ad_cost_per_all_carts_calc": "8.25",
            }
        ]
    )

    prepared = prepare_dataframe(df)
    row = prepared.iloc[0]

    assert float(row["organic_cart_count"]) == 12.0
    assert float(row["organic_cart_share_calc"]) == 40.5
    assert float(row["ad_cost_per_all_carts_calc"]) == 8.25


def test_get_previous_product_date_returns_previous_available_date() -> None:
    product_rows = pd.DataFrame(
        [
            {"report_date": pd.to_datetime("2026-05-31").date()},
            {"report_date": pd.to_datetime("2026-06-01").date()},
        ]
    )

    previous = get_previous_product_date(product_rows, pd.to_datetime("2026-06-01").date())

    assert previous == pd.to_datetime("2026-05-31").date()


def test_get_latest_product_context_returns_latest_and_previous_rows() -> None:
    product_rows = prepare_dataframe(
        pd.DataFrame(
            [
                {"report_date": "2026-05-31", "nm_id": 1, "order_count": 1},
                {"report_date": "2026-06-01", "nm_id": 1, "order_count": 2},
            ]
        )
    )

    context = get_latest_product_context(product_rows)

    assert context["latest_date"] == pd.to_datetime("2026-06-01").date()
    assert context["previous_date"] == pd.to_datetime("2026-05-31").date()
    assert context["latest_row"]["order_count"] == 2
    assert context["previous_row"]["order_count"] == 1


def test_format_delta_handles_previous_and_percent() -> None:
    delta_text = format_delta(12, 10)

    assert delta_text == "+2.00 / +20.0%"


def test_format_delta_handles_missing_previous() -> None:
    assert format_delta(12, None) == "нет даты для сравнения"


def test_build_warnings_includes_dynamic_warnings() -> None:
    row = pd.Series(
        {
            "data_quality_status": "OK_PARTIAL_SOURCES",
            "has_ad_campaign": True,
            "order_count": 10,
            "current_stock_qty": 10,
            "entry_point_status": "FILE_IMPORT_PENDING",
            "orders_geography_status": "FILE_IMPORT_PENDING",
            "vbro_status": "MANUAL_PENDING",
            "ad_cpo_calc": 150,
            "ad_campaign_spend_total": 130,
        }
    )
    previous_row = pd.Series(
        {
            "order_count": 20,
            "ad_campaign_spend_total": 100,
            "ad_cpo_calc": 100,
            "current_stock_qty": 20,
        }
    )

    warnings = build_warnings(row, previous_row)

    assert "Заказы упали" in warnings
    assert "Расход рекламы вырос" in warnings
    assert "CPO вырос" in warnings
    assert "Остаток снизился" in warnings


def test_build_data_quality_label_maps_user_friendly_labels() -> None:
    assert build_data_quality_label("OK_PARTIAL_SOURCES") == "Данные есть, внешние источники ожидаются"
    assert build_data_quality_label("NO_DATA") == "Нет данных"
    assert build_data_quality_label("PARTIAL") == "Частично"


def test_build_latest_snapshot_dataset_keeps_one_row_per_product_with_deltas() -> None:
    df = pd.DataFrame(
        [
            {
                "report_date": "2026-05-31",
                "supplier_article": "ART-1",
                "nm_id": 1,
                "title": "Товар 1",
                "brand": "Brand",
                "subject": "Subject",
                "impressions": 10,
                "cart_count": 2,
                "order_count": 1,
                "order_sum": 100,
                "ad_campaign_spend_total": 50,
                "ad_atbs_total": 5,
                "ad_orders_total": 1,
                "ad_cpo_calc": 50,
                "search_queries_count": 3,
                "current_stock_qty": 20,
                "data_quality_status": "OK_PARTIAL_SOURCES",
            },
            {
                "report_date": "2026-06-01",
                "supplier_article": "ART-1",
                "nm_id": 1,
                "title": "Товар 1",
                "brand": "Brand",
                "subject": "Subject",
                "impressions": 12,
                "cart_count": 3,
                "order_count": 2,
                "order_sum": 120,
                "ad_campaign_spend_total": 70,
                "ad_atbs_total": 7,
                "ad_orders_total": 2,
                "ad_cpo_calc": 35,
                "search_queries_count": 4,
                "current_stock_qty": 15,
                "data_quality_status": "OK_PARTIAL_SOURCES",
            },
            {
                "report_date": "2026-06-01",
                "supplier_article": "ART-2",
                "nm_id": 2,
                "title": "Товар 2",
                "brand": "Brand",
                "subject": "Subject",
                "impressions": 5,
                "cart_count": 1,
                "order_count": 1,
                "order_sum": 80,
                "ad_campaign_spend_total": None,
                "ad_atbs_total": None,
                "ad_orders_total": None,
                "ad_cpo_calc": None,
                "search_queries_count": None,
                "current_stock_qty": None,
                "data_quality_status": "NO_DATA",
            },
        ]
    )

    prepared = prepare_dataframe(df)
    latest = build_latest_snapshot_dataset(prepared)

    assert len(latest) == 2

    first_row = latest[latest["nm_id"] == 1].iloc[0]
    assert first_row["report_date"] == pd.to_datetime("2026-06-01").date()
    assert first_row["comparison_date"] == pd.to_datetime("2026-05-31").date()
    assert first_row["impressions_delta"] == 2
    assert first_row["cart_count_delta"] == 1
    assert first_row["order_count_delta"] == 1
    assert first_row["order_sum_delta"] == 20
    assert first_row["ad_campaign_spend_delta"] == 20
    assert first_row["ad_atbs_delta"] == 2
    assert first_row["ad_orders_delta"] == 1
    assert first_row["ad_cpo_delta"] == -15
    assert first_row["search_queries_delta"] == 1
    assert first_row["stock_delta"] == -5
    assert first_row["data_quality_label"] == "Данные есть, внешние источники ожидаются"

    second_row = latest[latest["nm_id"] == 2].iloc[0]
    assert pd.isna(second_row["comparison_date"])
    assert pd.isna(second_row["impressions_delta"])
    assert second_row["data_quality_label"] == "Нет данных"


def test_build_grouped_by_date_dataset_groups_rows_by_product_and_sorts_dates() -> None:
    prepared = prepare_dataframe(
        pd.DataFrame(
            [
                {
                    "report_date": "2026-06-07",
                    "supplier_article": "BlackWOM5",
                    "nm_id": 197330807,
                    "title": "Товар 1",
                    "brand": "Brand",
                    "subject": "Subject",
                    "impressions": 10,
                    "cart_count": 2,
                    "order_count": 1,
                    "order_sum": 100,
                    "ad_campaign_spend_total": 50,
                    "ad_atbs_total": 5,
                    "ad_orders_total": 1,
                    "ad_cpo_calc": 50,
                    "search_queries_count": 3,
                    "current_stock_qty": 20,
                    "data_quality_status": "OK_PARTIAL_SOURCES",
                },
                {
                    "report_date": "2026-05-31",
                    "supplier_article": "BlackWOM5",
                    "nm_id": 197330807,
                    "title": "Товар 1",
                    "brand": "Brand",
                    "subject": "Subject",
                    "impressions": 8,
                    "cart_count": 1,
                    "order_count": 1,
                    "order_sum": 80,
                    "ad_campaign_spend_total": 40,
                    "ad_atbs_total": 4,
                    "ad_orders_total": 1,
                    "ad_cpo_calc": 40,
                    "search_queries_count": 2,
                    "current_stock_qty": 25,
                    "data_quality_status": "OK_PARTIAL_SOURCES",
                },
                {
                    "report_date": "2026-06-01",
                    "supplier_article": "BlackWOM5",
                    "nm_id": 197330807,
                    "title": "Товар 1",
                    "brand": "Brand",
                    "subject": "Subject",
                    "impressions": 9,
                    "cart_count": 2,
                    "order_count": 1,
                    "order_sum": 90,
                    "ad_campaign_spend_total": 45,
                    "ad_atbs_total": 4,
                    "ad_orders_total": 1,
                    "ad_cpo_calc": 45,
                    "search_queries_count": 2,
                    "current_stock_qty": 23,
                    "data_quality_status": "OK_PARTIAL_SOURCES",
                },
                {
                    "report_date": "2026-06-01",
                    "supplier_article": "futmix3haki",
                    "nm_id": 2,
                    "title": "Товар 2",
                    "brand": "Brand",
                    "subject": "Subject",
                    "impressions": 5,
                    "cart_count": 1,
                    "order_count": 0,
                    "order_sum": 0,
                    "ad_campaign_spend_total": None,
                    "ad_atbs_total": None,
                    "ad_orders_total": None,
                    "ad_cpo_calc": None,
                    "search_queries_count": None,
                    "current_stock_qty": None,
                    "data_quality_status": "NO_DATA",
                },
            ]
        )
    )

    grouped = build_grouped_by_date_dataset(prepared)

    assert grouped["supplier_article"].tolist() == [
        "BlackWOM5",
        "BlackWOM5",
        "BlackWOM5",
        "futmix3haki",
    ]
    assert grouped["report_date"].tolist() == [
        pd.to_datetime("2026-05-31").date(),
        pd.to_datetime("2026-06-01").date(),
        pd.to_datetime("2026-06-07").date(),
        pd.to_datetime("2026-06-01").date(),
    ]
    assert grouped.iloc[0]["product_group_label"] == "▼ BlackWOM5 | 197330807"
    assert grouped.iloc[1]["product_group_label"] == ""
    assert grouped.iloc[2]["product_group_label"] == ""
    assert grouped.iloc[3]["product_group_label"] == "▼ futmix3haki | 2"
    assert "brand" in grouped.columns
    assert "subject" in grouped.columns


def test_build_product_timeline_dataset_returns_all_dates_sorted_desc() -> None:
    prepared = prepare_dataframe(
        pd.DataFrame(
            [
                {
                    "report_date": "2026-05-31",
                    "nm_id": 1,
                    "impressions": 10,
                    "cart_count": 2,
                    "order_count": 1,
                    "order_sum": 100,
                    "ad_campaign_spend_total": 50,
                    "ad_atbs_total": 5,
                    "ad_orders_total": 1,
                    "ad_cpo_calc": 50,
                    "search_queries_count": 3,
                    "current_stock_qty": 20,
                    "data_quality_status": "OK_PARTIAL_SOURCES",
                },
                {
                    "report_date": "2026-06-01",
                    "nm_id": 1,
                    "impressions": 12,
                    "cart_count": 3,
                    "order_count": 2,
                    "order_sum": 120,
                    "ad_campaign_spend_total": 70,
                    "ad_atbs_total": 7,
                    "ad_orders_total": 2,
                    "ad_cpo_calc": 35,
                    "search_queries_count": 4,
                    "current_stock_qty": 15,
                    "data_quality_status": "OK_PARTIAL_SOURCES",
                },
            ]
        )
    )

    timeline = build_product_timeline_dataset(prepared)

    assert timeline["report_date"].tolist() == [
        pd.to_datetime("2026-06-01").date(),
        pd.to_datetime("2026-05-31").date(),
    ]
    assert "data_quality_status" in timeline.columns


def test_resolve_effective_import_date_prefers_detected_date_when_enabled() -> None:
    resolved = resolve_effective_import_date(
        use_file_date=True,
        detected_date="2026-06-07",
        manual_date_text="2026-06-05",
    )

    assert str(resolved) == "2026-06-07"


def test_resolve_effective_import_date_falls_back_to_manual_date() -> None:
    resolved = resolve_effective_import_date(
        use_file_date=False,
        detected_date="2026-06-07",
        manual_date_text="2026-06-05",
    )

    assert str(resolved) == "2026-06-05"


def test_build_last_upload_result_formats_compact_summary() -> None:
    summary = {
        "effective_date": "2026-06-07",
        "rows_upserted": 15,
        "rows_in_db_for_date": 15,
        "duplicate_keys": 0,
        "target_table": "fact_entry_point_day",
        "source_status": "CSV_EXPORT",
        "applied_at": "2026-06-09 10:15:00",
    }

    result = build_last_upload_result("Точка входа", summary)

    assert result["Тип файла"] == "Точка входа"
    assert result["Дата"] == "2026-06-07"
    assert result["Записано строк"] == 15
    assert result["Строк в БД после записи"] == 15
    assert result["Дубликаты"] == 0
    assert result["Таблица"] == "fact_entry_point_day"
    assert result["source_status"] == "CSV_EXPORT"
    assert result["Время загрузки"] == "2026-06-09 10:15:00"


def test_build_pipeline_status_messages_reports_apply_mart_and_dataset_steps() -> None:
    messages = build_pipeline_status_messages(
        apply_summary={"rows_upserted": 15},
        mart_summary={"rows_upserted": 248},
        dataset_summary={"total_rows": 744},
    )

    assert messages == [
        "Файл записан в БД: 15 строк",
        "Mart пересобран: 248 строк",
        "Dataset обновлён: 744 строк",
        "Если данные не видны, обновите страницу",
    ]


def test_can_apply_import_summary_requires_successful_dry_run() -> None:
    assert can_apply_import_summary(
        {
            "missing_required_columns": [],
            "rows_read": 10,
            "detected_date": "2026-06-07",
        }
    )
    assert not can_apply_import_summary(
        {
            "missing_required_columns": ["Артикул WB"],
            "rows_read": 10,
            "detected_date": "2026-06-07",
        }
    )
    assert not can_apply_import_summary(
        {
            "missing_required_columns": [],
            "rows_read": 0,
            "detected_date": "2026-06-07",
        }
    )


def test_build_import_format_error_mentions_report_name_and_missing_columns() -> None:
    message = build_import_format_error("Точка входа", ["Артикул WB", "Показы"])

    assert "Точка входа" in message
    assert "Артикул WB" in message
    assert "Показы" in message


def test_resolve_export_range_uses_available_bounds() -> None:
    date_from, date_to = resolve_export_range("2026-05-31", "2026-06-07")

    assert str(date_from) == "2026-05-31"
    assert str(date_to) == "2026-06-07"


def test_summarize_available_dates_returns_full_sorted_list() -> None:
    prepared = prepare_dataframe(
        pd.DataFrame(
            [
                {"report_date": "2026-06-07"},
                {"report_date": "2026-05-31"},
                {"report_date": "2026-06-01"},
                {"report_date": "2026-06-07"},
            ]
        )
    )

    summary = summarize_available_dates(prepared)

    assert str(summary["min_date"]) == "2026-05-31"
    assert str(summary["max_date"]) == "2026-06-07"
    assert summary["date_count"] == 3
    assert [str(value) for value in summary["dates"]] == [
        "2026-05-31",
        "2026-06-01",
        "2026-06-07",
    ]


def test_display_columns_by_date_keep_only_business_columns() -> None:
    expected_columns = {
        "product_group_label",
        "supplier_article",
        "nm_id",
        "report_date",
        "title",
        "brand",
        "subject",
        "impressions",
        "card_clicks",
        "cart_count",
        "order_count",
        "ctr_calc",
        "add_to_cart_conversion_calc",
        "cart_to_order_conversion_calc",
        "order_sum",
        "ad_campaign_spend_total",
        "ad_views_total",
        "ad_clicks_total",
        "ad_atbs_total",
        "ad_orders_total",
        "ad_cpc_calc",
        "ad_cpm_calc",
        "ad_cost_per_cart_calc",
        "ad_cpo_calc",
        "ad_share_of_revenue_calc",
        "ad_cost_per_all_carts_calc",
        "organic_cart_count",
        "organic_cart_share_calc",
        "current_stock_qty",
        "current_mp_stock_qty",
        "search_queries_count",
        "local_orders_percent",
        "entry_point_source_label",
        "orders_geography_source_label",
        "vbro_status_label",
        "organic_formula_status_label",
    }
    excluded_columns = {
        "entry_impressions_total",
        "entry_card_clicks_total",
        "entry_ctr_calc",
        "entry_cart_total",
        "entry_orders_total",
        "ad_cost_writeoff_total",
        "buyout_count",
        "buyout_sum",
        "buyout_percent",
        "direct_ad_atbs",
        "associated_ad_atbs",
        "multicard_ad_atbs",
        "unknown_ad_atbs",
        "search_avg_position",
        "search_visibility",
        "search_clicks",
        "search_cart",
        "search_orders",
        "localization_orders_total_qty",
        "localization_regions_count",
        "data_quality_label",
    }

    assert expected_columns.issubset(set(DISPLAY_COLUMNS_BY_DATE))
    assert excluded_columns.isdisjoint(set(DISPLAY_COLUMNS_BY_DATE))


def test_build_export_dataframe_for_by_date_view_omits_technical_columns() -> None:
    table_df = pd.DataFrame(
        [
            {
                "product_group_label": "BlackWOM5 | 197330807",
                "supplier_article": "BlackWOM5",
                "nm_id": 197330807,
                "report_date": "2026-06-07",
                "title": "Товар",
                "brand": "PALEY",
                "subject": "Трусы",
                "impressions": 138486,
                "card_clicks": 6125,
                "cart_count": 818,
                "order_count": 218,
                "ctr_calc": 4.417775,
                "add_to_cart_conversion_calc": 13.355102,
                "cart_to_order_conversion_calc": 26.650367,
                "order_sum": 1000,
                "ad_campaign_spend_total": 902,
                "ad_views_total": 9118,
                "ad_clicks_total": 649,
                "ad_atbs_total": 120,
                "ad_orders_total": 19,
                "ad_cpc_calc": 1.38,
                "ad_cpm_calc": 98.92,
                "ad_cost_per_cart_calc": 7.51,
                "ad_cpo_calc": 47.47,
                "ad_share_of_revenue_calc": 3.08,
                "ad_cost_per_all_carts_calc": 5.12,
                "organic_cart_count": 698,
                "organic_cart_share_calc": 581.67,
                "current_stock_qty": 100,
                "current_mp_stock_qty": 20,
                "search_queries_count": 15,
                "local_orders_percent": 55.1,
                "entry_point_source_label": "Файл загружен",
                "orders_geography_source_label": "Файл загружен",
                "vbro_status_label": "Не внесено",
                "organic_formula_status_label": "Рассчитано",
                "entry_impressions_total": 138486,
                "entry_card_clicks_total": 6118,
                "entry_ctr_calc": 4.417775,
                "entry_cart_total": 810,
                "entry_orders_total": 210,
                "impressions_source_note": "Показы взяты из файла",
                "funnel_data_note": "OK",
                "entry_point_status": "CSV_EXPORT",
                "orders_geography_status": "CSV_EXPORT",
                "data_quality_status": "OK_PARTIAL_SOURCES",
                "data_quality_label": "Данные есть",
            }
        ]
    )

    export_df = build_export_dataframe(table_df, DISPLAY_COLUMNS_BY_DATE)

    assert "Показы" in export_df.columns
    assert "CTR" in export_df.columns
    assert "Источник точки входа" in export_df.columns
    assert "Источник географии" in export_df.columns
    assert "Показы из Точки входа" not in export_df.columns
    assert "Переходы из Точки входа" not in export_df.columns
    assert "CTR из Точки входа" not in export_df.columns
    assert not any(str(column).startswith("Note:") for column in export_df.columns)
    assert "Статус точки входа" not in export_df.columns
    assert "Статус географии" not in export_df.columns
    assert "Технический статус данных" not in export_df.columns


def test_technical_extra_columns_by_date_include_source_control_fields() -> None:
    expected = {
        "entry_impressions_total",
        "entry_card_clicks_total",
        "entry_ctr_calc",
        "entry_cart_total",
        "entry_orders_total",
        "impressions_source_note",
        "funnel_data_note",
        "search_data_note",
        "stock_data_note",
        "localization_data_note",
        "entry_point_data_note",
        "vbro_data_note",
        "ad_cost_writeoff_total",
        "technical_ad_campaign_spend_total",
        "organic_cart_share_status",
        "entry_point_status",
        "orders_geography_status",
        "vbro_status",
        "card_comparison_status",
        "data_quality_status",
    }

    assert expected.issubset(set(TECHNICAL_EXTRA_COLUMNS_BY_DATE))


def test_resolve_data_source_prefers_explicit_env(monkeypatch) -> None:
    monkeypatch.setenv("STREAMLIT_DATA_SOURCE", "csv")
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")

    assert resolve_data_source() == "csv"


def test_resolve_data_source_prefers_db_when_database_url_present(monkeypatch) -> None:
    monkeypatch.delenv("STREAMLIT_DATA_SOURCE", raising=False)
    monkeypatch.setenv("DATABASE_URL", "postgresql://example")

    assert resolve_data_source() == "db"


def test_password_helpers_use_env(monkeypatch) -> None:
    monkeypatch.setenv("APP_PASSWORD", "secret-pass")

    assert get_app_password() == "secret-pass"
    assert is_password_protection_enabled() is True


def test_password_helpers_allow_open_access_when_password_missing(monkeypatch) -> None:
    monkeypatch.delenv("APP_PASSWORD", raising=False)

    assert get_app_password() is None
    assert is_password_protection_enabled() is False


def test_filter_products_with_period_data_hides_products_without_any_business_metrics() -> None:
    filtered = filter_products_with_period_data(
        pd.DataFrame(
            [
                {
                    "nm_id": 1,
                    "supplier_article": "BlackWOM5",
                    "report_date": "2026-06-06",
                    "impressions": None,
                    "card_clicks": None,
                    "cart_count": None,
                    "order_count": None,
                    "order_sum": None,
                    "ad_campaign_spend_total": None,
                    "ad_views_total": None,
                    "ad_clicks_total": None,
                    "ad_atbs_total": None,
                    "ad_orders_total": None,
                    "current_stock_qty": None,
                    "current_mp_stock_qty": None,
                    "search_queries_count": None,
                    "local_orders_percent": None,
                },
                {
                    "nm_id": 1,
                    "supplier_article": "BlackWOM5",
                    "report_date": "2026-06-07",
                    "impressions": 138486,
                    "card_clicks": 6125,
                    "cart_count": 818,
                    "order_count": 218,
                    "order_sum": 308241,
                    "ad_campaign_spend_total": 26391.1,
                    "ad_views_total": 128847,
                    "ad_clicks_total": 3396,
                    "ad_atbs_total": 614,
                    "ad_orders_total": 161,
                    "current_stock_qty": 8285,
                    "current_mp_stock_qty": None,
                    "search_queries_count": 100,
                    "local_orders_percent": 72,
                },
                {
                    "nm_id": 2,
                    "supplier_article": "NoData",
                    "report_date": "2026-06-06",
                    "impressions": None,
                    "card_clicks": None,
                    "cart_count": None,
                    "order_count": None,
                    "order_sum": None,
                    "ad_campaign_spend_total": None,
                    "ad_views_total": None,
                    "ad_clicks_total": None,
                    "ad_atbs_total": None,
                    "ad_orders_total": None,
                    "current_stock_qty": None,
                    "current_mp_stock_qty": None,
                    "search_queries_count": None,
                    "local_orders_percent": None,
                },
                {
                    "nm_id": 2,
                    "supplier_article": "NoData",
                    "report_date": "2026-06-07",
                    "impressions": None,
                    "card_clicks": None,
                    "cart_count": None,
                    "order_count": None,
                    "order_sum": None,
                    "ad_campaign_spend_total": None,
                    "ad_views_total": None,
                    "ad_clicks_total": None,
                    "ad_atbs_total": None,
                    "ad_orders_total": None,
                    "current_stock_qty": None,
                    "current_mp_stock_qty": None,
                    "search_queries_count": None,
                    "local_orders_percent": None,
                },
            ]
        )
    )

    assert filtered["nm_id"].unique().tolist() == [1]


def test_filter_products_with_period_data_keeps_products_with_zero_but_non_null_metrics() -> None:
    filtered = filter_products_with_period_data(
        pd.DataFrame(
            [
                {
                    "nm_id": 10,
                    "supplier_article": "ZeroButReal",
                    "report_date": "2026-06-07",
                    "impressions": 0,
                    "card_clicks": 0,
                    "cart_count": 0,
                    "order_count": 0,
                    "order_sum": 0,
                    "ad_campaign_spend_total": None,
                    "ad_views_total": None,
                    "ad_clicks_total": None,
                    "ad_atbs_total": None,
                    "ad_orders_total": None,
                    "current_stock_qty": 0,
                    "current_mp_stock_qty": None,
                    "search_queries_count": 0,
                    "local_orders_percent": 0,
                }
            ]
        )
    )

    assert filtered["nm_id"].unique().tolist() == [10]
