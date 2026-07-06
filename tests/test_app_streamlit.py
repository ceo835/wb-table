from __future__ import annotations

from datetime import datetime, timedelta
from decimal import Decimal
from io import BytesIO

import app_streamlit
import pandas as pd
from pandas.io.formats.style import Styler

from app_streamlit import (
    CHART_THRESHOLD_CART_COST,
    CHART_THRESHOLD_CPO,
    DISPLAY_COLUMNS_BY_DATE,
    DEFAULT_STREAMLIT_DISPLAY_MIN_DATE,
    API_WB_AD_SOURCE_LABEL,
    IVAN_MANUAL_AD_SOURCE_LABEL,
    TECHNICAL_EXTRA_COLUMNS_BY_DATE,
    CHART_LEVEL_ARTICLE,
    CHART_LEVEL_CABINET,
    apply_display_min_date_filter,
    apply_tracked_scope_filters,
    aggregate_ivan_manual_ads_for_charts,
    attach_stock_query_groups,
    build_streamlit_display_min_date_caption,
    build_band_summary_table,
    build_category_summary_table,
    build_chart_series_dataframe,
    build_display_coverage_summary,
    build_debug_snapshot,
    build_debug_trace_frame,
    build_chart_metrics_by_date,
    build_chart_kpi_card_html,
    build_chart_period_summary,
    build_ad_cart_cost_chart_series_map,
    build_ad_carts_chart_series_map,
    apply_product_bands,
    build_chart_product_options,
    build_chart_scope_rows,
    build_threshold_breaches_table,
    build_excel_export_bytes,
    build_export_dataframe,
    build_data_quality_label,
    build_overview_export_tables,
    build_overview_visible_columns,
    build_wb_site_price_monitor_dataframe,
    filter_products_with_period_data,
    filter_overview_empty_rows,
    format_wb_conversion_type_label,
    get_latest_product_context,
    build_grouped_by_date_dataset,
    build_import_format_error,
    build_last_upload_result,
    build_upload_tab_sections,
    build_latest_snapshot_dataset,
    build_pipeline_status_messages,
    build_product_timeline_dataset,
    build_warnings,
    build_wb_site_price_monitor_visibility_summary,
    can_apply_import_summary,
    filter_rows_by_selected_product_label,
    format_delta,
    get_app_password,
    get_latest_product_context,
    get_previous_product_date,
    is_password_protection_enabled,
    inspect_tracked_metadata_state,
    merge_ivan_manual_ads_into_chart_scope,
    prepare_dataframe_for_streamlit_display,
    prepare_stock_warehouse_history_snapshot_dataframe,
    prepare_stock_warehouse_table_for_display,
    resolve_data_source,
    resolve_streamlit_display_min_date,
    prepare_dataframe,
    classify_stock_warehouse_history_anomaly,
    build_stock_warehouse_history_ivan_check_table,
    build_stock_warehouse_history_pivot_table,
    build_stock_warehouse_history_summary_metrics,
    build_stock_warehouse_history_table,
    build_stock_warehouse_product_table,
    build_stock_warehouse_problem_profit_total,
    build_ad_campaign_product_scope_dataframe,
    should_render_stock_warehouse_history_pivot,
    build_stock_all_band_level,
    build_stock_all_display_dataframe,
    build_stock_all_size_display_dataframe,
    build_stock_all_size_level,
    build_stock_warehouse_summary_card_html,
    build_stock_all_product_level,
    build_stock_warehouse_display_dataframe,
    build_stock_warehouse_summary_metrics,
    format_summary_rub,
    resolve_stock_warehouse_default_snapshot_date,
    resolve_effective_import_date,
    resolve_export_range,
    summarize_available_dates,
)


def test_build_stock_warehouse_summary_card_html_uses_compact_sizes() -> None:
    html = build_stock_warehouse_summary_card_html("Дата snapshot", "2026-06-16", compact=True)

    assert "1.35rem" in html
    assert "0.72rem" in html
    assert "min-height:94px" in html
    assert "justify-content:space-between" in html
    assert "2026-06-16" in html


def test_build_chart_kpi_card_html_uses_fixed_height_layout() -> None:
    html = build_chart_kpi_card_html(
        label="CPO РК",
        value_text="156.2 руб.",
        caption_text="Порог превышен: 150 руб.",
        background="#fff1f2",
        border="#ef4444",
        value_color="#0f172a",
        caption_color="#b91c1c",
    )

    assert "height:136px" in html
    assert "justify-content:space-between" in html
    assert "min-height:32px" in html
    assert "min-height:28px" in html


def test_spp_columns_are_exposed_in_main_streamlit_views() -> None:
    assert "wb_seller_price" in DISPLAY_COLUMNS_BY_DATE
    assert "spp_rub" in DISPLAY_COLUMNS_BY_DATE
    assert "spp_pct" in DISPLAY_COLUMNS_BY_DATE
    assert "wb_seller_price" in app_streamlit.DISPLAY_COLUMNS_LATEST
    assert "spp_rub" in app_streamlit.DISPLAY_COLUMNS_LATEST
    assert "spp_pct" in app_streamlit.DISPLAY_COLUMNS_LATEST
    assert "wb_seller_price" in app_streamlit.PRODUCT_TIMELINE_COLUMNS
    assert "spp_rub" in app_streamlit.PRODUCT_TIMELINE_COLUMNS
    assert "spp_pct" in app_streamlit.PRODUCT_TIMELINE_COLUMNS
    assert app_streamlit.EXPORT_COLUMN_LABELS["wb_seller_price"] == "Цена продавца ЛК"
    assert app_streamlit.EXPORT_COLUMN_LABELS["spp_rub"] == "СПП, ₽"
    assert app_streamlit.EXPORT_COLUMN_LABELS["spp_pct"] == "СПП, %"


def test_apply_display_min_date_filter_hides_dates_before_cutoff_and_preserves_attrs(monkeypatch) -> None:
    monkeypatch.setenv("STREAMLIT_DISPLAY_MIN_DATE", "2026-06-07")
    df = pd.DataFrame(
        [
            {"report_date": "2026-06-06", "nm_id": 1},
            {"report_date": "2026-06-07", "nm_id": 1},
            {"report_date": "2026-06-08", "nm_id": 2},
        ]
    )
    df.attrs["display_coverage"] = pd.DataFrame([{"field": "x"}])

    result = apply_display_min_date_filter(df)

    assert result["report_date"].tolist() == ["2026-06-07", "2026-06-08"]
    assert "display_coverage" in result.attrs


def test_resolve_streamlit_display_min_date_uses_env_override(monkeypatch) -> None:
    monkeypatch.setenv("STREAMLIT_DISPLAY_MIN_DATE", "2026-03-12")

    assert resolve_streamlit_display_min_date().isoformat() == "2026-03-12"


def test_resolve_streamlit_display_min_date_falls_back_on_invalid_env(monkeypatch) -> None:
    monkeypatch.setenv("STREAMLIT_DISPLAY_MIN_DATE", "not-a-date")

    assert resolve_streamlit_display_min_date() == DEFAULT_STREAMLIT_DISPLAY_MIN_DATE


def test_build_streamlit_display_min_date_caption_uses_effective_date() -> None:
    assert build_streamlit_display_min_date_caption(datetime(2026, 3, 12).date()) == (
        "Технический минимум отображения: 2026-03-12"
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


def test_prepare_dataframe_converts_decimal_calc_metrics_to_numeric() -> None:
    df = pd.DataFrame(
        [
            {
                "report_date": "2026-06-17",
                "has_funnel": True,
                "has_stock": False,
                "has_ad_cost": True,
                "has_ad_campaign": True,
                "has_search": False,
                "has_localization_partial": False,
                "cart_count": 10,
                "order_sum": 200,
                "ad_campaign_spend_total": 30,
                "ad_views_total": 150,
                "ad_clicks_total": 15,
                "ad_atbs_total": 5,
                "ad_orders_total": 2,
                "associated_ad_atbs": 1,
            }
        ]
    )

    prepared = prepare_dataframe(df)

    assert isinstance(prepared.loc[0, "ad_cpc_calc"], float)
    assert isinstance(prepared.loc[0, "ad_cpm_calc"], float)
    assert isinstance(prepared.loc[0, "ad_cost_per_cart_calc"], float)
    assert isinstance(prepared.loc[0, "ad_cpo_calc"], float)


def test_prepare_dataframe_applies_tracked_metadata(monkeypatch) -> None:
    tracked_df = pd.DataFrame(
        [
            {
                "nm_id": 197330807,
                "item_label": "чёрные 5 шт",
                "is_tracked": True,
                "lifecycle_status": "active",
                "source": "ivan_2026-06-15_v2",
                "tracked_label": "чёрные 5 шт",
            }
        ]
    )
    monkeypatch.setattr(app_streamlit, "shared_apply_tracked_products", lambda df: df.merge(
        tracked_df[["nm_id", "is_tracked", "tracked_label", "lifecycle_status"]],
        on="nm_id",
        how="left",
    ).assign(
        is_tracked=lambda frame: frame["is_tracked"].where(frame["is_tracked"].notna(), False).astype(bool),
        lifecycle_status=lambda frame: frame["lifecycle_status"].fillna("not_tracked"),
    ))

    prepared = prepare_dataframe(
        pd.DataFrame(
            [
                {"report_date": "2026-06-07", "nm_id": 197330807, "has_funnel": True},
                {"report_date": "2026-06-07", "nm_id": 999999999, "has_funnel": False},
            ]
        )
    )

    assert bool(prepared.loc[0, "is_tracked"]) is True
    assert prepared.loc[0, "tracked_label"] == "чёрные 5 шт"
    assert prepared.loc[0, "lifecycle_status"] == "active"
    assert bool(prepared.loc[1, "is_tracked"]) is False
    assert prepared.loc[1, "lifecycle_status"] == "not_tracked"


def test_load_app_dataset_db_uses_cache_buster_for_db_loader(monkeypatch) -> None:
    monkeypatch.setenv("STREAMLIT_DATA_SOURCE", "db")
    monkeypatch.setattr(app_streamlit.settings, "database_url", "postgresql://example")
    monkeypatch.setattr(app_streamlit, "get_db_dataset_cache_buster", lambda: "buster-1")

    calls: list[str | None] = []

    def fake_load_dataset_from_db(cache_buster: str | None = None) -> pd.DataFrame:
        calls.append(cache_buster)
        return pd.DataFrame([{"report_date": "2026-06-18", "nm_id": 1, "has_funnel": True}])

    monkeypatch.setattr(app_streamlit, "load_dataset_from_db", fake_load_dataset_from_db)
    monkeypatch.setattr(app_streamlit, "prepare_dataframe", lambda df: df)

    df, source = app_streamlit.load_app_dataset()

    assert source == "db"
    assert calls == ["buster-1"]
    assert len(df) == 1


def test_resolve_db_dataset_cache_buster_returns_none_on_failure(monkeypatch) -> None:
    logged: list[str] = []

    def raise_error() -> str:
        raise RuntimeError("boom")

    monkeypatch.setattr(app_streamlit, "get_db_dataset_cache_buster", raise_error)
    monkeypatch.setattr(app_streamlit.logger, "exception", lambda message: logged.append(message))

    assert app_streamlit.resolve_db_dataset_cache_buster() is None
    assert logged == ["Failed to build DB dataset cache-buster"]


def test_get_db_dataset_cache_buster_includes_seller_price_state(monkeypatch) -> None:
    class _FakeResult:
        def __init__(self, row: tuple[object, ...]) -> None:
            self._row = row

        def one(self) -> tuple[object, ...]:
            return self._row

    rows = iter(
        [
            ("2026-06-29", "2026-06-29T10:00:00+00:00", 100),
            ("2026-06-29", "2026-06-29T10:05:00+00:00", 59),
            ("2026-06-29", "2026-06-29T10:10:00+00:00", 354),
            ("2026-06-29", "2026-06-29T10:15:00+00:00", 3),
            ("2026-06-29", "2026-06-29T10:20:00+00:00", 12),
            ("2026-06-29", "2026-06-29T10:25:00+00:00", 3106),
            ("2026-06-29", "2026-06-29T10:30:00+00:00", 84),
            ("2026-06-29", "2026-06-29T10:35:00+00:00", 44),
            ("2026-06-29", "2026-06-29T10:40:00+00:00", 755),
        ]
    )

    class _FakeSession:
        def execute(self, _statement):
            return _FakeResult(next(rows))

    class _FakeScope:
        def __enter__(self):
            return _FakeSession()

        def __exit__(self, exc_type, exc, tb):
            return False

    monkeypatch.setattr(app_streamlit, "session_scope", lambda: _FakeScope())

    cache_buster = app_streamlit.get_db_dataset_cache_buster()

    assert "2026-06-29T10:10:00+00:00" in cache_buster
    assert "|354|" in f"|{cache_buster}|"
    assert "2026-06-29T10:25:00+00:00" in cache_buster
    assert "|3106|" in f"|{cache_buster}|"
    assert "2026-06-29T10:30:00+00:00" in cache_buster
    assert "|84|" in f"|{cache_buster}|"


def test_load_app_dataset_db_falls_back_when_cache_buster_raises(monkeypatch) -> None:
    monkeypatch.setenv("STREAMLIT_DATA_SOURCE", "db")
    monkeypatch.setattr(app_streamlit.settings, "database_url", "postgresql://example")
    monkeypatch.setattr(app_streamlit, "resolve_db_dataset_cache_buster", lambda: None)

    calls: list[str | None] = []

    def fake_load_dataset_from_db(cache_buster: str | None = None) -> pd.DataFrame:
        calls.append(cache_buster)
        return pd.DataFrame([{"report_date": "2026-06-18", "nm_id": 1, "has_funnel": True}])

    monkeypatch.setattr(app_streamlit, "load_dataset_from_db", fake_load_dataset_from_db)
    monkeypatch.setattr(app_streamlit, "prepare_dataframe", lambda df: df)

    df, source = app_streamlit.load_app_dataset()

    assert source == "db"
    assert calls == [None]
    assert len(df) == 1


def test_build_stock_warehouse_product_table_aggregates_chrt_rows_and_keeps_missing_tracked_products() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 197330807,
                "chrt_id": 1,
                "warehouse_id": 10,
                "warehouse_name": "Владимир WB",
                "stock_qty": 5,
                "in_way_to_client": 1,
                "in_way_from_client": 0,
            },
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 197330807,
                "chrt_id": 2,
                "warehouse_id": 10,
                "warehouse_name": "Владимир WB",
                "stock_qty": 7,
                "in_way_to_client": 2,
                "in_way_from_client": 1,
            },
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 197330807,
                "chrt_id": 1,
                "warehouse_id": 11,
                "warehouse_name": "Тула",
                "stock_qty": 0,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
            },
        ]
    )
    tracked_df = pd.DataFrame(
        [
            {
                "nm_id": 197330807,
                "tracked_label": "BlackWOM5",
                "is_tracked": True,
                "lifecycle_status": "active",
                "query_group": "women_underwear",
            },
            {
                "nm_id": 320893265,
                "tracked_label": "коты 4 большие",
                "is_tracked": True,
                "lifecycle_status": "active",
                "query_group": pd.NA,
            },
        ]
    )

    result = build_stock_warehouse_product_table(
        snapshot_df,
        tracked_df,
        snapshot_date=pd.Timestamp("2026-06-15").date(),
        selected_warehouses=["Владимир WB", "Тула"],
        show_only_tracked=True,
        show_sellout=True,
    )

    product_row = result.loc[result["nm_id"] == 197330807].iloc[0]
    missing_row = result.loc[result["nm_id"] == 320893265].iloc[0]

    assert product_row["Владимир WB"] == 12
    assert product_row["Тула"] == 0
    assert product_row["query_group"] == "women_underwear"
    assert product_row["zero_warehouses_count"] == 1
    assert product_row["no_data_warehouses_count"] == 0
    assert product_row["stock_status"] == "ZERO_ON_WAREHOUSE"

    assert pd.isna(missing_row["Владимир WB"])
    assert pd.isna(missing_row["Тула"])
    assert pd.isna(missing_row["query_group"])
    assert missing_row["no_data_warehouses_count"] == 2
    assert missing_row["stock_status"] == "NO_STOCK_DATA_FOR_PRODUCT"


def test_build_stock_warehouse_product_table_marks_missing_selected_warehouse_as_no_data() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 91470767,
                "chrt_id": 1,
                "warehouse_id": 10,
                "warehouse_name": "Владимир WB",
                "stock_qty": 3,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
            }
        ]
    )
    tracked_df = pd.DataFrame(
        [
            {
                "nm_id": 91470767,
                "tracked_label": "avokadogirl",
                "is_tracked": True,
                "lifecycle_status": "active",
            }
        ]
    )

    result = build_stock_warehouse_product_table(
        snapshot_df,
        tracked_df,
        snapshot_date=pd.Timestamp("2026-06-15").date(),
        selected_warehouses=["Владимир WB", "Тула"],
        show_only_tracked=True,
        show_sellout=True,
    )

    row = result.iloc[0]

    assert row["Владимир WB"] == 3
    assert pd.isna(row["Тула"])
    assert row["zero_warehouses_count"] == 0
    assert row["no_data_warehouses_count"] == 1
    assert row["stock_status"] == "NO_DATA_ON_WAREHOUSE"


def test_build_stock_warehouse_product_table_adds_main_warehouse_aggregates_problem_status_and_sorting() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 10,
                "chrt_id": 1,
                "warehouse_id": 1,
                "warehouse_name": "Владимир WB",
                "stock_qty": 0,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
            },
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 10,
                "chrt_id": 1,
                "warehouse_id": 2,
                "warehouse_name": "Тула",
                "stock_qty": 5,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
            },
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 20,
                "chrt_id": 1,
                "warehouse_id": 1,
                "warehouse_name": "Владимир WB",
                "stock_qty": 7,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
            },
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 30,
                "chrt_id": 1,
                "warehouse_id": 1,
                "warehouse_name": "Владимир WB",
                "stock_qty": 9,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
            },
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 30,
                "chrt_id": 1,
                "warehouse_id": 2,
                "warehouse_name": "Тула",
                "stock_qty": 4,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
            },
        ]
    )
    tracked_df = pd.DataFrame(
        [
            {"nm_id": 10, "tracked_label": "A zero", "is_tracked": True, "lifecycle_status": "active"},
            {"nm_id": 20, "tracked_label": "B partial", "is_tracked": True, "lifecycle_status": "active"},
            {"nm_id": 30, "tracked_label": "C ok sellout", "is_tracked": True, "lifecycle_status": "sellout"},
        ]
    )

    result = build_stock_warehouse_product_table(
        snapshot_df,
        tracked_df,
        snapshot_date=pd.Timestamp("2026-06-15").date(),
        selected_warehouses=["Владимир WB", "Тула"],
        main_warehouses=["Владимир WB", "Тула"],
        show_only_tracked=True,
        show_sellout=True,
    )

    assert result["nm_id"].tolist() == [10, 20, 30]
    first_row = result.iloc[0]
    second_row = result.iloc[1]
    third_row = result.iloc[2]

    assert first_row["problem_status"] == "ZERO_ON_MAIN_WAREHOUSES"
    assert first_row["total_main_warehouses"] == 5
    assert first_row["warehouses_with_stock"] == 1

    assert second_row["problem_status"] == "PARTIAL_STOCK"
    assert second_row["total_main_warehouses"] == 7
    assert second_row["warehouses_with_stock"] == 1

    assert third_row["problem_status"] == "OK"
    assert third_row["total_main_warehouses"] == 13
    assert third_row["warehouses_with_stock"] == 2


def test_build_stock_warehouse_product_table_lost_profit_calculation() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 197330807,
                "chrt_id": 1,
                "warehouse_id": 10,
                "warehouse_name": "Владимир WB",
                "stock_qty": 0,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
            },
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 320893265,
                "chrt_id": 2,
                "warehouse_id": 10,
                "warehouse_name": "Владимир WB",
                "stock_qty": 0,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
            },
        ]
    )
    tracked_df = pd.DataFrame(
        [
            {
                "nm_id": 197330807,
                "tracked_label": "BlackWOM5",
                "is_tracked": True,
                "lifecycle_status": "active",
                "query_group": "women_underwear",
            },
            {
                "nm_id": 320893265,
                "tracked_label": "коты 4 большие",
                "is_tracked": True,
                "lifecycle_status": "active",
                "query_group": "unknown",
            },
        ]
    )

    search_queries_dict = {"women_underwear": 1000}
    coefficients_dict = {"women_underwear": Decimal("0.0025")}
    warehouse_areas_dict = {"Владимир WB": ("CFO", Decimal("5.5"))}
    app_lookup = {
        (datetime(2026, 6, 15).date(), 197330807): (12000.0, 10.0, 1000.0) # order_sum, order_count, price
    }

    result = build_stock_warehouse_product_table(
        snapshot_df,
        tracked_df,
        snapshot_date=datetime(2026, 6, 15).date(),
        selected_warehouses=["Владимир WB"],
        main_warehouses=["Владимир WB"],
        show_only_tracked=True,
        show_sellout=True,
        search_queries_dict=search_queries_dict,
        coefficients_dict=coefficients_dict,
        warehouse_areas_dict=warehouse_areas_dict,
        app_lookup=app_lookup,
    )

    row_197330807 = result.loc[result["nm_id"] == 197330807].iloc[0]
    row_320893265 = result.loc[result["nm_id"] == 320893265].iloc[0]

    # Проверяем поисковые запросы
    assert row_197330807["search_queries"] == 1000
    assert pd.isna(row_320893265["search_queries"])

    # Проверяем расчет упущенной выгоды с фиксированной прибылью 100 руб
    # lost_impressions = 1000 * 5.5 / 100 = 55
    # lost_orders = 55 * 0.0025 = 0.1375
    # profit_per_order = 100
    # lost_profit = 0.1375 * 100.0 = 13.75
    assert abs(row_197330807["lost_profit_rub"] - 13.75) < 1e-5
    assert row_197330807["profit_per_order"] == 100.0
    assert pd.isna(row_320893265["lost_profit_rub"])
    assert row_320893265["profit_per_order"] == 100.0

    app_lookup_fallback = {
        (datetime(2026, 6, 15).date(), 197330807): (0.0, 0.0, 1000.0) # order_sum, order_count=0, price=1000.0
    }
    result_fallback = build_stock_warehouse_product_table(
        snapshot_df,
        tracked_df,
        snapshot_date=datetime(2026, 6, 15).date(),
        selected_warehouses=["Владимир WB"],
        main_warehouses=["Владимир WB"],
        show_only_tracked=True,
        show_sellout=True,
        search_queries_dict=search_queries_dict,
        coefficients_dict=coefficients_dict,
        warehouse_areas_dict=warehouse_areas_dict,
        app_lookup=app_lookup_fallback,
    )
    row_fallback = result_fallback.loc[result_fallback["nm_id"] == 197330807].iloc[0]
    # Упущенная прибыль должна по-прежнему считаться с фиксированной ставкой 100 руб, игнорируя app_lookup_fallback
    assert abs(row_fallback["lost_profit_rub"] - 13.75) < 1e-5
    assert row_fallback["profit_per_order"] == 100.0


def test_build_stock_warehouse_product_table_calculated_conversions_and_display() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 100,
                "chrt_id": 1,
                "warehouse_id": 10,
                "warehouse_name": "Владимир WB",
                "stock_qty": 0,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
            },
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 200,
                "chrt_id": 2,
                "warehouse_id": 10,
                "warehouse_name": "Владимир WB",
                "stock_qty": 0,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
            },
        ]
    )
    tracked_df = pd.DataFrame(
        [
            {"nm_id": 100, "tracked_label": "kids_item", "is_tracked": True, "lifecycle_status": "active", "query_group": "kids_underwear"},
            {"nm_id": 200, "tracked_label": "tshirt_item", "is_tracked": True, "lifecycle_status": "active", "query_group": "women_tshirts"},
        ]
    )

    search_queries_dict = {"kids_underwear": 500, "women_tshirts": 800}
    # Нет ручного коэффициента для kids_underwear, но есть для women_tshirts
    coefficients_dict = {"women_tshirts": Decimal("0.001")}
    # calculated конверсия есть для kids_underwear (например, 0.002), но нет для women_tshirts
    calculated_conversions_dict = {"kids_underwear": 0.002}
    warehouse_areas_dict = {"Владимир WB": ("CFO", Decimal("10.0"))}
    app_lookup = {
        (datetime(2026, 6, 15).date(), 100): (20000.0, 10.0, 2000.0),
        (datetime(2026, 6, 15).date(), 200): (15000.0, 10.0, 1500.0),
    }

    result = build_stock_warehouse_product_table(
        snapshot_df,
        tracked_df,
        snapshot_date=datetime(2026, 6, 15).date(),
        selected_warehouses=["Владимир WB"],
        main_warehouses=["Владимир WB"],
        show_only_tracked=True,
        show_sellout=True,
        search_queries_dict=search_queries_dict,
        coefficients_dict=coefficients_dict,
        warehouse_areas_dict=warehouse_areas_dict,
        app_lookup=app_lookup,
        calculated_conversions_dict=calculated_conversions_dict,
    )

    row_kids = result.loc[result["nm_id"] == 100].iloc[0]
    row_tshirts = result.loc[result["nm_id"] == 200].iloc[0]

    # Поисковые запросы отображаются для обеих групп
    assert row_kids["search_queries"] == 500
    assert row_tshirts["search_queries"] == 800

    # Проверка промежуточных колонок
    assert abs(row_kids["zone_share_pct"] - 10.0) < 1e-5
    assert abs(row_kids["conversion_pct"] - 0.2) < 1e-5
    assert row_kids["profit_per_order"] == 100.0
    assert abs(row_kids["lost_orders"] - 0.1) < 1e-5

    assert abs(row_tshirts["zone_share_pct"] - 10.0) < 1e-5
    assert abs(row_tshirts["conversion_pct"] - 0.1) < 1e-5
    assert row_tshirts["profit_per_order"] == 100.0
    assert abs(row_tshirts["lost_orders"] - 0.08) < 1e-5

    # Упущенная выгода (потенциальная прибыль):
    assert abs(row_kids["lost_profit_rub"] - 10.0) < 1e-5
    # 2. Для women_tshirts (calculated нет, fallback на manual coef 0.001):
    # lost_impressions = 800 * 10 / 100 = 80
    # lost_orders = 80 * 0.001 = 0.08
    # profit_per_order = 100.0
    # lost_profit = 0.08 * 100 = 8.0
    assert abs(row_tshirts["lost_profit_rub"] - 8.0) < 1e-5


def test_build_stock_warehouse_product_table_no_conversion_keeps_queries_but_hides_profit() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-06-15",
                "nm_id": 100,
                "chrt_id": 1,
                "warehouse_id": 10,
                "warehouse_name": "Владимир WB",
                "stock_qty": 0,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
            }
        ]
    )
    tracked_df = pd.DataFrame(
        [
            {"nm_id": 100, "tracked_label": "kids_item", "is_tracked": True, "lifecycle_status": "active", "query_group": "kids_underwear"}
        ]
    )

    search_queries_dict = {"kids_underwear": 500}
    result = build_stock_warehouse_product_table(
        snapshot_df,
        tracked_df,
        snapshot_date=datetime(2026, 6, 15).date(),
        selected_warehouses=["Владимир WB"],
        main_warehouses=["Владимир WB"],
        show_only_tracked=True,
        show_sellout=True,
        search_queries_dict=search_queries_dict,
        coefficients_dict={},
        calculated_conversions_dict={},
    )

    row = result.iloc[0]
    assert row["search_queries"] == 500
    assert pd.isna(row["lost_profit_rub"])


def test_calculate_lost_profit_conversions_from_db(monkeypatch) -> None:
    from app_streamlit import calculate_lost_profit_conversions_from_db
    import app_streamlit
    from contextlib import contextmanager
    from datetime import date

    calculate_lost_profit_conversions_from_db.clear()

    class FakeRow:
        def __init__(self, **kwargs):
            for k, v in kwargs.items():
                setattr(self, k, v)

    class FakeResult:
        def __init__(self, items):
            self.items = items
        def all(self):
            return self.items

    calls_count = 0
    def fake_execute(stmt, *args, **kwargs):
        nonlocal calls_count
        calls_count += 1
        if calls_count == 1:
            return FakeResult([
                FakeRow(query_group="kids_underwear", orders_sum=10),
                FakeRow(query_group="women_tshirts", orders_sum=5),
            ])
        else:
            return FakeResult([
                FakeRow(query_group="kids_underwear", search_queries=5000),
                FakeRow(query_group="women_tshirts", search_queries=2000),
            ])

    class FakeSession:
        def execute(self, stmt, *args, **kwargs):
            return fake_execute(stmt, *args, **kwargs)

    @contextmanager
    def fake_session_scope():
        yield FakeSession()

    monkeypatch.setattr(app_streamlit, "session_scope", fake_session_scope)

    conversions = calculate_lost_profit_conversions_from_db(date(2026, 6, 24))

    assert abs(conversions.get("kids_underwear", 0) - 0.002) < 1e-6
    assert abs(conversions.get("women_tshirts", 0) - 0.0025) < 1e-6


def test_prepare_stock_warehouse_table_for_display_keeps_missing_warehouses_numeric_safe() -> None:
    df = pd.DataFrame(
        [
            {"Артикул WB": 1, "Владимир WB": "NO_DATA", "Тула": 0, "problem_status": "NO_DATA_ON_MAIN_WAREHOUSES"},
        ]
    )

    styled = prepare_stock_warehouse_table_for_display(df, ["Владимир WB", "Тула"])

    assert isinstance(styled, Styler)
    assert pd.isna(styled.data.loc[0, "Владимир WB"])
    assert styled.data.loc[0, "Тула"] == 0

    html = styled.to_html()
    assert ("—" in html) or ("вЂ”" in html)
    assert "#e5e7eb" in html
    assert "#fde2e4" in html


def test_build_stock_warehouse_display_dataframe_maps_human_labels_for_main_and_problem_tables() -> None:
    df = pd.DataFrame(
        [
            {
                "nm_id": 197330807,
                "tracked_label": "BlackWOM5",
                "query_group": pd.NA,
                "lifecycle_status": "active",
                "Владимир WB": "NO_DATA",
                "Тула": 0,
                "zero_warehouses_count": 1,
                "no_data_warehouses_count": 1,
                "problem_status": "ZERO_ON_MAIN_WAREHOUSES",
                "zero_warehouses": "Тула",
                "no_data_warehouses": "Владимир WB",
                "problem_warehouses": "Владимир WB, Тула",
                "total_main_warehouses": 0,
                "warehouses_with_stock": 0,
            }
        ]
    )

    main_display = build_stock_warehouse_display_dataframe(df, problem_table=False)
    problem_display = build_stock_warehouse_display_dataframe(df, problem_table=True)

    assert "problem_status" not in main_display.columns
    assert "Проблема" in main_display.columns
    assert main_display.columns[:4].tolist() == [
        "Артикул WB",
        "Название",
        "Товарная группа",
        "Статус товара",
    ]
    assert main_display.loc[0, "Товарная группа"] == "Не определена"
    assert main_display.loc[0, "Статус товара"] == "Основной"
    assert main_display.loc[0, "Проблема"] == "Есть нулевые остатки"
    assert main_display.loc[0, "Владимир WB"] == "—"
    assert main_display.loc[0, "Тула"] == 0
    assert main_display.loc[0, "Складов с нулём"] == 1
    assert main_display.loc[0, "Складов без данных"] == 1

    assert problem_display.columns.tolist() == [
        "Артикул WB",
        "Название",
        "Товарная группа",
        "Статус товара",
        "Нулевые склады",
        "Склады без данных",
        "Поисковые запросы",
        "Доля зоны, %",
        "Конв. поиск→заказ, %",
        "Прибыль/заказ, ₽",
        "Упущ. заказы",
        "Потенц. прибыль, ₽",
        "Проблема",
    ]
    assert problem_display.loc[0, "Проблема"] == "Есть нулевые остатки"
    assert problem_display.loc[0, "Товарная группа"] == "Не определена"


def test_prepare_stock_warehouse_table_for_display_formats_new_lost_profit_columns() -> None:
    from app_streamlit import prepare_stock_warehouse_table_for_display
    df = pd.DataFrame(
        [
            {
                "Артикул WB": 100,
                "Поисковые запросы": 5000,
                "Доля зоны, %": 10.5,
                "Конв. поиск→заказ, %": 0.2005,
                "Прибыль/заказ, ₽": 100,
                "Упущ. заказы": 10.53,
                "Потенц. прибыль, ₽": 1053,
                "Владимир WB": 0,
            },
            {
                "Артикул WB": 200,
                "Поисковые запросы": pd.NA,
                "Доля зоны, %": pd.NA,
                "Конв. поиск→заказ, %": pd.NA,
                "Прибыль/заказ, ₽": 100,
                "Упущ. заказы": pd.NA,
                "Потенц. прибыль, ₽": pd.NA,
                "Владимир WB": pd.NA,
            }
        ]
    )

    styled = prepare_stock_warehouse_table_for_display(df, ["Владимир WB"])
    html = styled.to_html()

    # Проверяем форматирование для первой строки
    assert "5 000" in html
    assert "10.50%" in html
    assert "0.2005%" in html
    assert "100" in html
    assert "10.53" in html
    assert "1 053" in html

    # Проверяем форматирование для второй строки (фиксированная прибыль 100 руб, отсутствующие значения)
    # Должен быть прочерк на месте отсутствующих значений
    assert (html.count("—") + html.count("вЂ”")) >= 5


def test_attach_stock_query_groups_reads_query_group_from_settings_products() -> None:
    tracked_df = pd.DataFrame(
        [
            {"nm_id": 1, "tracked_label": "A", "is_tracked": True, "lifecycle_status": "active"},
            {"nm_id": 2, "tracked_label": "B", "is_tracked": True, "lifecycle_status": "active"},
        ]
    )
    settings_df = pd.DataFrame(
        [
            {"nm_id": 1, "query_group": "women_underwear"},
            {"nm_id": 2, "query_group": ""},
            {"nm_id": 3, "query_group": "unsupported_group"},
        ]
    )

    result = attach_stock_query_groups(tracked_df, settings_df)

    assert result.loc[result["nm_id"] == 1, "query_group"].iloc[0] == "трусы женские"
    assert pd.isna(result.loc[result["nm_id"] == 2, "query_group"].iloc[0])


def test_build_stock_warehouse_display_dataframe_shows_russian_query_group_labels() -> None:
    df = pd.DataFrame(
        [
            {
                "nm_id": 197330807,
                "tracked_label": "BlackWOM5",
                "query_group": "men_tshirts",
                "lifecycle_status": "active",
                "Владимир WB": 1,
                "Тула": 0,
                "zero_warehouses_count": 1,
                "no_data_warehouses_count": 0,
                "problem_status": "ZERO_ON_MAIN_WAREHOUSES",
                "zero_warehouses": "Тула",
                "no_data_warehouses": "",
                "problem_warehouses": "Тула",
                "total_main_warehouses": 1,
                "warehouses_with_stock": 1,
            }
        ]
    )

    main_display = build_stock_warehouse_display_dataframe(df, problem_table=False)

    assert main_display.loc[0, "Товарная группа"] == "мужская футболка"


def test_build_wb_site_price_monitor_dataframe_uses_russian_problem_labels() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_at": "2026-06-17T08:00:00+00:00",
                "snapshot_date": "2026-06-17",
                "nm_id": 197330807,
                "item_label": "BlackWOM5",
                "lifecycle_status": "active",
                "buyer_visible_price": 1299.0,
                "fetch_status": "success",
            },
            {
                "snapshot_at": "2026-06-17T08:05:00+00:00",
                "snapshot_date": "2026-06-17",
                "nm_id": 37320545,
                "item_label": "ЧББ",
                "lifecycle_status": "sellout",
                "buyer_visible_price": None,
                "fetch_status": "no_price_data",
            },
        ]
    )
    alert_df = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-06-17",
                "nm_id": 197330807,
                "previous_success_price": 1190.0,
                "price_delta": 109.0,
                "alert_status": "PRICE_CHANGED_50",
            },
            {
                "snapshot_date": "2026-06-17",
                "nm_id": 37320545,
                "previous_success_price": None,
                "price_delta": None,
                "alert_status": "NO_PRICE_DATA",
            },
        ]
    )
    tracked_df = pd.DataFrame(
        [
            {"nm_id": 197330807, "tracked_label": "BlackWOM5", "lifecycle_status": "active"},
            {"nm_id": 37320545, "tracked_label": "ЧББ", "lifecycle_status": "sellout"},
        ]
    )

    display_df = build_wb_site_price_monitor_dataframe(
        snapshot_df,
        alert_df,
        tracked_df,
        snapshot_date=pd.Timestamp("2026-06-17").date(),
        show_sellout=True,
        only_problematic=False,
    )

    assert display_df.loc[0, "Проблема"] == "Цена изменилась на 50 ₽ или больше"
    assert display_df.loc[0, "Статус товара"] == "Основной"
    assert display_df.loc[1, "Проблема"] == "Нет данных по цене"
    assert display_df.loc[1, "Статус товара"] == "Распродажа"


def test_build_wb_site_price_monitor_dataframe_keeps_current_price_empty_for_interstitial() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_at": "2026-06-16T08:00:00+00:00",
                "snapshot_date": "2026-06-16",
                "nm_id": 91470767,
                "item_label": "avokadogirl",
                "lifecycle_status": "active",
                "buyer_visible_price": 799.0,
                "fetch_status": "success",
            },
            {
                "snapshot_at": "2026-06-17T08:00:00+00:00",
                "snapshot_date": "2026-06-17",
                "nm_id": 91470767,
                "item_label": "avokadogirl",
                "lifecycle_status": "active",
                "buyer_visible_price": None,
                "fetch_status": "wb_interstitial",
            },
        ]
    )
    alert_df = pd.DataFrame(columns=["snapshot_date", "nm_id", "previous_success_price", "price_delta", "alert_status"])
    tracked_df = pd.DataFrame(
        [
            {"nm_id": 91470767, "tracked_label": "avokadogirl", "lifecycle_status": "active"},
        ]
    )

    display_df = build_wb_site_price_monitor_dataframe(
        snapshot_df,
        alert_df,
        tracked_df,
        snapshot_date=pd.Timestamp("2026-06-17").date(),
        show_sellout=True,
        only_problematic=False,
    )

    assert pd.isna(display_df.loc[0, "Цена покупателя"])
    assert float(display_df.loc[0, "Предыдущая цена"]) == 799.0
    assert display_df.loc[0, "Проблема"] == "WB временно не отдал карточку"


def test_build_wb_site_price_monitor_dataframe_keeps_full_snapshot_and_marks_alert_subset() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_at": "2026-06-18T08:00:00+00:00",
                "snapshot_date": "2026-06-18",
                "nm_id": 91470767,
                "item_label": "avokadogirl",
                "lifecycle_status": "active",
                "buyer_visible_price": 1022.0,
                "price_text_raw": "1 022 ₽",
                "fetch_status": "success",
                "product_url": "https://www.wildberries.ru/catalog/91470767/detail.aspx",
            },
            {
                "snapshot_at": "2026-06-18T08:01:00+00:00",
                "snapshot_date": "2026-06-18",
                "nm_id": 91744473,
                "item_label": "Мишки дети",
                "lifecycle_status": "active",
                "buyer_visible_price": 880.0,
                "price_text_raw": "880 ₽",
                "fetch_status": "success",
                "product_url": "https://www.wildberries.ru/catalog/91744473/detail.aspx",
            },
            {
                "snapshot_at": "2026-06-17T08:00:00+00:00",
                "snapshot_date": "2026-06-17",
                "nm_id": 91470767,
                "item_label": "avokadogirl",
                "lifecycle_status": "active",
                "buyer_visible_price": 799.0,
                "price_text_raw": "799 ₽",
                "fetch_status": "success",
                "product_url": "https://www.wildberries.ru/catalog/91470767/detail.aspx",
            },
            {
                "snapshot_at": "2026-06-17T08:01:00+00:00",
                "snapshot_date": "2026-06-17",
                "nm_id": 91744473,
                "item_label": "Мишки дети",
                "lifecycle_status": "active",
                "buyer_visible_price": 880.0,
                "price_text_raw": "880 ₽",
                "fetch_status": "success",
                "product_url": "https://www.wildberries.ru/catalog/91744473/detail.aspx",
            },
        ]
    )
    alert_df = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-06-18",
                "nm_id": 91470767,
                "previous_success_price": 799.0,
                "price_delta": 223.0,
                "alert_status": "PRICE_CHANGED_50",
            }
        ]
    )
    tracked_df = pd.DataFrame(
        [
            {"nm_id": 91470767, "tracked_label": "avokadogirl", "lifecycle_status": "active"},
            {"nm_id": 91744473, "tracked_label": "Мишки дети", "lifecycle_status": "active"},
        ]
    )

    display_df = build_wb_site_price_monitor_dataframe(
        snapshot_df,
        alert_df,
        tracked_df,
        snapshot_date=pd.Timestamp("2026-06-18").date(),
        show_sellout=True,
        only_problematic=False,
    )

    assert len(display_df) == 2
    assert set(display_df["Артикул WB"]) == {91470767, 91744473}
    assert int(display_df["Alert"].sum()) == 1
    alert_rows = display_df[display_df["Alert"]]
    assert len(alert_rows) == 1
    assert int(alert_rows.iloc[0]["Артикул WB"]) == 91470767
    assert float(alert_rows.iloc[0]["Цена покупателя"]) == 1022.0
    assert float(alert_rows.iloc[0]["Предыдущая цена"]) == 799.0
    assert float(alert_rows.iloc[0]["Абс. изменение, ₽"]) == 223.0


def test_build_wb_site_price_monitor_dataframe_does_not_recreate_alert_without_alert_row() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_at": "2026-06-17T08:00:00+00:00",
                "snapshot_date": "2026-06-17",
                "nm_id": 26033523,
                "item_label": "sample",
                "lifecycle_status": "active",
                "buyer_visible_price": 630.0,
                "price_text_raw": "630 ₽",
                "fetch_status": "success",
                "product_url": "https://www.wildberries.ru/catalog/26033523/detail.aspx",
            },
            {
                "snapshot_at": "2026-06-18T08:00:00+00:00",
                "snapshot_date": "2026-06-18",
                "nm_id": 26033523,
                "item_label": "sample",
                "lifecycle_status": "active",
                "buyer_visible_price": 1180.0,
                "price_text_raw": "1 180 ₽",
                "fetch_status": "success",
                "product_url": "https://www.wildberries.ru/catalog/26033523/detail.aspx",
            },
        ]
    )
    alert_df = pd.DataFrame(columns=["snapshot_date", "nm_id", "previous_success_price", "price_delta", "alert_status"])
    tracked_df = pd.DataFrame([{"nm_id": 26033523, "tracked_label": "sample", "lifecycle_status": "active"}])

    display_df = build_wb_site_price_monitor_dataframe(
        snapshot_df,
        alert_df,
        tracked_df,
        snapshot_date=pd.Timestamp("2026-06-18").date(),
        show_sellout=True,
        only_problematic=False,
    )

    assert len(display_df) == 1
    assert bool(display_df.loc[0, "Alert"]) is False
    assert float(display_df.loc[0, "Изменение, ₽"]) == 550.0


def test_build_wb_site_price_monitor_visibility_summary_reports_sellout_hidden_rows() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-06-21",
                "nm_id": 91470767,
                "lifecycle_status": "active",
                "buyer_visible_price": 799.0,
                "fetch_status": "success",
            },
            {
                "snapshot_date": "2026-06-21",
                "nm_id": 311071100,
                "lifecycle_status": "sellout",
                "buyer_visible_price": 821.0,
                "fetch_status": "success",
            },
            {
                "snapshot_date": "2026-06-21",
                "nm_id": 91744473,
                "lifecycle_status": "active",
                "buyer_visible_price": 1022.0,
                "fetch_status": "success",
            },
        ]
    )
    tracked_df = pd.DataFrame(
        [
            {"nm_id": 91470767, "tracked_label": "avokado", "lifecycle_status": "active"},
            {"nm_id": 311071100, "tracked_label": "avokado duble", "lifecycle_status": "sellout"},
            {"nm_id": 91744473, "tracked_label": "bear", "lifecycle_status": "active"},
        ]
    )

    result = build_wb_site_price_monitor_visibility_summary(
        snapshot_df,
        tracked_df,
        snapshot_date=pd.Timestamp("2026-06-21").date(),
        show_sellout=False,
        visible_rows=2,
    )

    assert result == {
        "checked_products": 3,
        "prices_received": 3,
        "rows_written_to_db": 3,
        "rows_visible_in_streamlit": 2,
        "hidden_rows_count": 1,
        "hidden_rows_reason": "filtered_by_sellout",
        "hidden_nm_ids": [311071100],
    }


def test_build_stock_warehouse_summary_metrics_counts_ok_zero_and_no_data_rows() -> None:
    product_table = pd.DataFrame(
        [
            {"nm_id": 1, "stock_status": "OK", "zero_warehouses_count": 0, "no_data_warehouses_count": 0},
            {"nm_id": 2, "stock_status": "ZERO_ON_WAREHOUSE", "zero_warehouses_count": 2, "no_data_warehouses_count": 0},
            {"nm_id": 3, "stock_status": "NO_DATA_ON_WAREHOUSE", "zero_warehouses_count": 0, "no_data_warehouses_count": 1},
            {"nm_id": 4, "stock_status": "NO_STOCK_DATA_FOR_PRODUCT", "zero_warehouses_count": 0, "no_data_warehouses_count": 3},
        ]
    )

    metrics = build_stock_warehouse_summary_metrics(product_table)

    assert metrics == {
        "total_products": 4,
        "ok_products": 1,
        "zero_products": 1,
        "no_data_products": 2,
        "total_zero_warehouses": 2,
    }


def test_build_stock_warehouse_problem_profit_total_sums_problem_table_profit() -> None:
    problem_table = pd.DataFrame(
        [
            {"nm_id": 1, "lost_profit_rub": 100.4},
            {"nm_id": 2, "lost_profit_rub": 200},
            {"nm_id": 3, "lost_profit_rub": pd.NA},
        ]
    )

    total = build_stock_warehouse_problem_profit_total(problem_table)

    assert abs(total - 300.4) < 1e-9
    assert format_summary_rub(total) == "300 ₽"


def test_resolve_stock_warehouse_default_snapshot_date_prefers_report_day_and_falls_back_to_latest() -> None:
    available_dates = [
        datetime(2026, 6, 27).date(),
        datetime(2026, 6, 28).date(),
        datetime(2026, 6, 29).date(),
    ]

    assert resolve_stock_warehouse_default_snapshot_date(available_dates, datetime(2026, 6, 28).date()) == datetime(2026, 6, 28).date()
    assert resolve_stock_warehouse_default_snapshot_date(available_dates, datetime(2026, 6, 30).date()) == datetime(2026, 6, 29).date()


def test_load_stock_warehouse_snapshot_from_db_materializes_rows_before_session_close(monkeypatch) -> None:
    state = {"attached": True}

    class FakeRow:
        def __getattribute__(self, name: str):
            if name.startswith("_"):
                return object.__getattribute__(self, name)
            if not state["attached"]:
                raise RuntimeError("detached")
            values = {
                "snapshot_date": pd.Timestamp("2026-06-15").date(),
                "nm_id": 197330807,
                "chrt_id": 1,
                "warehouse_id": 10,
                "warehouse_name": "Владимир WB",
                "region_name": "ЦФО",
                "stock_qty": 5,
                "in_way_to_client": 1,
                "in_way_from_client": 0,
                "source": "WB_API",
                "loaded_at": pd.Timestamp("2026-06-16 10:00:00"),
            }
            return values[name]

    class FakeResult:
        def scalars(self):
            return self

        def all(self):
            return [FakeRow()]

    class FakeSession:
        def execute(self, _stmt):
            return FakeResult()

    class FakeSessionScope:
        def __enter__(self):
            state["attached"] = True
            return FakeSession()

        def __exit__(self, exc_type, exc, tb):
            state["attached"] = False
            return False

    monkeypatch.setattr(app_streamlit, "session_scope", lambda: FakeSessionScope())
    app_streamlit.load_stock_warehouse_snapshot_from_db.clear()

    result = app_streamlit.load_stock_warehouse_snapshot_from_db()

    assert result.to_dict(orient="records") == [
        {
            "snapshot_date": pd.Timestamp("2026-06-15").date(),
            "nm_id": 197330807,
            "chrt_id": 1,
            "warehouse_id": 10,
            "warehouse_name": "Владимир WB",
            "region_name": "ЦФО",
            "stock_qty": 5,
            "in_way_to_client": 1,
            "in_way_from_client": 0,
            "source": "WB_API",
            "loaded_at": pd.Timestamp("2026-06-16 10:00:00"),
        }
    ]


def test_build_debug_snapshot_and_trace_frame_report_rows_and_unique_nm() -> None:
    df = pd.DataFrame(
        [
            {"nm_id": 1, "report_date": "2026-06-04"},
            {"nm_id": 1, "report_date": "2026-06-05"},
            {"nm_id": 2, "report_date": "2026-06-04"},
        ]
    )

    snapshot = build_debug_snapshot("rows_after_load_dataset_from_db", df)
    trace_df = build_debug_trace_frame([snapshot])

    assert snapshot == {
        "stage": "rows_after_load_dataset_from_db",
        "rows": 3,
        "unique_nm": 2,
    }
    assert trace_df.to_dict(orient="records") == [snapshot]


def test_apply_tracked_scope_filters_keeps_only_tracked_and_can_hide_sellout() -> None:
    df = pd.DataFrame(
        [
            {"nm_id": 1, "is_tracked": True, "lifecycle_status": "active"},
            {"nm_id": 2, "is_tracked": True, "lifecycle_status": "sellout"},
            {"nm_id": 3, "is_tracked": False, "lifecycle_status": "not_tracked"},
        ]
    )

    tracked_only = apply_tracked_scope_filters(
        df,
        show_only_tracked=True,
        show_sellout=True,
    )
    active_only = apply_tracked_scope_filters(
        df,
        show_only_tracked=True,
        show_sellout=False,
    )
    all_without_sellout = apply_tracked_scope_filters(
        df,
        show_only_tracked=False,
        show_sellout=False,
    )

    assert tracked_only["nm_id"].tolist() == [1, 2]
    assert active_only["nm_id"].tolist() == [1]
    assert all_without_sellout["nm_id"].tolist() == [1, 3]


def test_apply_tracked_scope_filters_skips_tracked_filter_when_metadata_unavailable() -> None:
    df = pd.DataFrame(
        [
            {"nm_id": 1, "is_tracked": False, "lifecycle_status": "not_tracked"},
            {"nm_id": 2, "is_tracked": False, "lifecycle_status": "not_tracked"},
        ]
    )

    result = apply_tracked_scope_filters(
        df,
        show_only_tracked=True,
        show_sellout=True,
        tracked_metadata_available=False,
    )

    assert result["nm_id"].tolist() == [1, 2]


def test_inspect_tracked_metadata_state_reports_missing_tracked_products(monkeypatch) -> None:
    monkeypatch.setattr(
        app_streamlit,
        "load_tracked_products",
        lambda: pd.DataFrame(columns=["nm_id", "item_label", "is_tracked", "lifecycle_status", "source", "tracked_label"]),
    )
    df = pd.DataFrame(
        [
            {"nm_id": 197330807, "is_tracked": False},
            {"nm_id": 37320545, "is_tracked": False},
        ]
    )

    result = inspect_tracked_metadata_state(df)

    assert result["metadata_available"] is False
    assert result["reason"] == "tracked_products_missing"
    assert result["dataset_unique_nm"] == 2
    assert result["tracked_matches_in_dataset"] == 0
    assert result["is_tracked_counts"] == {"False": 2}


def test_build_display_coverage_summary_counts_null_to_zero_and_positive() -> None:
    original = pd.DataFrame(
        [
            {
                "has_funnel": True,
                "has_ad_cost": False,
                "has_ad_campaign": False,
                "card_clicks": None,
                "order_count": 5,
                "ad_views_total": None,
                "ad_orders_total": None,
            },
            {
                "has_funnel": True,
                "has_ad_cost": True,
                "has_ad_campaign": False,
                "card_clicks": 7,
                "order_count": None,
                "ad_views_total": 10,
                "ad_orders_total": None,
            },
        ]
    )
    enriched = pd.DataFrame(
        [
            {
                "has_funnel": True,
                "has_ad_cost": False,
                "has_ad_campaign": False,
                "card_clicks": 0,
                "order_count": 5,
                "ad_views_total": 0,
                "ad_orders_total": 0,
            },
            {
                "has_funnel": True,
                "has_ad_cost": True,
                "has_ad_campaign": False,
                "card_clicks": 7,
                "order_count": 0,
                "ad_views_total": 10,
                "ad_orders_total": 0,
            },
        ]
    )

    coverage = build_display_coverage_summary(original, enriched)
    coverage_by_field = {row["field"]: row for row in coverage.to_dict(orient="records")}

    assert coverage_by_field["card_clicks"]["null_before"] == 1
    assert coverage_by_field["card_clicks"]["became_zero"] == 1
    assert coverage_by_field["card_clicks"]["positive_after"] == 1
    assert coverage_by_field["ad_views_total"]["null_before"] == 1
    assert coverage_by_field["ad_views_total"]["became_zero"] == 1
    assert coverage_by_field["ad_views_total"]["positive_after"] == 0


def test_prepare_dataframe_for_streamlit_display_uses_styler_for_small_tables(monkeypatch) -> None:
    captions: list[str] = []
    monkeypatch.setattr(app_streamlit.st, "caption", captions.append)
    df = pd.DataFrame([{"data_quality_label": "Частично", "ad_cpo_calc": 50}])

    result = prepare_dataframe_for_streamlit_display(df, status_column="data_quality_label")

    assert isinstance(result, Styler)
    assert captions == []


def test_prepare_dataframe_for_streamlit_display_clears_problematic_dataframe_attrs(monkeypatch) -> None:
    captions: list[str] = []
    monkeypatch.setattr(app_streamlit.st, "caption", captions.append)
    df = pd.DataFrame([{"data_quality_label": "Частично", "ad_cpo_calc": 50}])
    df.attrs["display_coverage"] = pd.DataFrame([{"field": "x", "null_before": 0}])

    result = prepare_dataframe_for_streamlit_display(df, status_column="data_quality_label")

    assert isinstance(result, Styler)
    assert result.data.attrs == {}
    result.data.astype(str)
    assert captions == []


def test_prepare_dataframe_for_streamlit_display_highlights_wb_price_alert(monkeypatch) -> None:
    captions: list[str] = []
    monkeypatch.setattr(app_streamlit.st, "caption", captions.append)
    df = pd.DataFrame(
        [
            {
                "data_quality_label": "Р§Р°СЃС‚РёС‡РЅРѕ",
                "wb_buyer_price": 1022.0,
                "wb_price_alert": True,
            }
        ]
    )

    result = prepare_dataframe_for_streamlit_display(df, status_column="data_quality_label")

    assert isinstance(result, Styler)
    html = result.to_html()
    assert "1022.00" in html
    assert "background-color: #fde2e4;" in html
    assert "color: #7f1d1d;" in html
    assert captions == []


def test_prepare_dataframe_for_streamlit_display_limits_highlights_to_recent_30_days(monkeypatch) -> None:
    captions: list[str] = []
    monkeypatch.setattr(app_streamlit.st, "caption", captions.append)
    df = pd.DataFrame(
        [
            {
                "report_date": "2026-05-01",
                "data_quality_label": "Частично",
                "product_group_label": "old row",
                "wb_buyer_price": 900.0,
                "wb_price_alert": True,
                "ad_cpo_calc": 200.0,
                "ad_cost_per_cart_calc": 40.0,
            },
            {
                "report_date": "2026-06-19",
                "data_quality_label": "Частично",
                "product_group_label": "recent row",
                "wb_buyer_price": 950.0,
                "wb_price_alert": True,
                "ad_cpo_calc": 200.0,
                "ad_cost_per_cart_calc": 40.0,
            },
        ]
    )

    result = prepare_dataframe_for_streamlit_display(df, status_column="data_quality_label")

    assert isinstance(result, Styler)
    ctx = result._compute().ctx
    assert (0, 2) not in ctx
    assert (0, 3) not in ctx
    assert (0, 5) not in ctx
    assert (0, 6) not in ctx
    assert (1, 2) in ctx
    assert (1, 3) in ctx
    assert (1, 5) in ctx
    assert (1, 6) in ctx
    assert captions == []


def test_prepare_dataframe_for_streamlit_display_skips_styler_for_large_tables(monkeypatch) -> None:
    captions: list[str] = []
    monkeypatch.setattr(app_streamlit.st, "caption", captions.append)
    monkeypatch.setattr(app_streamlit, "STYLER_MAX_CELLS", 3)
    df = pd.DataFrame([{"a": 1, "b": 2}, {"a": 3, "b": 4}])

    result = prepare_dataframe_for_streamlit_display(df, status_column=None)

    assert isinstance(result, pd.DataFrame)
    assert captions == []


def test_prepare_dataframe_for_streamlit_display_keeps_styler_for_large_tables(monkeypatch) -> None:
    captions: list[str] = []
    monkeypatch.setattr(app_streamlit.st, "caption", captions.append)
    monkeypatch.setattr(app_streamlit, "STYLER_MAX_CELLS", 4)
    df = pd.DataFrame([{"a": 1, "b": 2}, {"a": 3, "b": 4}])

    result = prepare_dataframe_for_streamlit_display(df, status_column=None)

    assert isinstance(result, Styler)
    assert captions == []


def test_prepare_dataframe_for_streamlit_display_sanitizes_decimal_and_placeholder_types(monkeypatch) -> None:
    captions: list[str] = []
    monkeypatch.setattr(app_streamlit.st, "caption", captions.append)
    df = pd.DataFrame(
        [
            {
                "data_quality_label": "Р§Р°СЃС‚РёС‡РЅРѕ",
                "ad_cpc_calc": Decimal("2.50"),
                "current_stock_qty": "—",
                "wb_buyer_price": Decimal("799.00"),
                "wb_price_alert": True,
            }
        ]
    )

    result = prepare_dataframe_for_streamlit_display(df, status_column="data_quality_label")

    assert isinstance(result, Styler)
    assert result.data.loc[0, "ad_cpc_calc"] == 2.5
    assert result.data.loc[0, "wb_buyer_price"] == 799.0
    assert pd.isna(result.data.loc[0, "current_stock_qty"])
    html = result.to_html()
    assert "799.00" in html
    assert ("—" in html) or ("вЂ”" in html)
    assert captions == []


def test_build_chart_series_dataframe_ignores_problematic_dataframe_attrs() -> None:
    chart_df = pd.DataFrame(
        [
            {"report_date": "2026-06-06", "order_count": 10, "order_sum": 1000},
            {"report_date": "2026-06-07", "order_count": 12, "order_sum": 1200},
        ]
    )
    chart_df.attrs["display_coverage"] = pd.DataFrame([{"field": "order_count", "null_before": 0}])

    result = build_chart_series_dataframe(
        chart_df,
        {"order_count": "Заказы", "order_sum": "Сумма заказов"},
    )

    assert len(result) == 4
    assert set(result["series"]) == {"Заказы", "Сумма заказов"}
    assert result["is_alert"].eq(False).all()


def test_aggregate_ivan_manual_ads_for_charts_sums_metrics_and_preserves_source() -> None:
    raw_df = pd.DataFrame(
        [
            {
                "date": "2026-03-20",
                "nm_id": 111,
                "supplier_article": "a-1",
                "title": "Товар A",
                "ad_spend": 100.0,
                "ad_atbs": 10.0,
                "ad_views": 1000.0,
                "source_status": "IVAN_ADS_WIDE_IMPORT",
                "data_status": "MANUAL_UPLOAD",
                "import_quality": "PARTIAL_CONFLICTS_SKIPPED",
            },
            {
                "date": "2026-03-20",
                "nm_id": 111,
                "supplier_article": "a-1",
                "title": "Товар A",
                "ad_spend": 50.0,
                "ad_atbs": 5.0,
                "ad_views": 500.0,
                "source_status": "IVAN_ADS_WIDE_IMPORT",
                "data_status": "MANUAL_UPLOAD",
                "import_quality": "PARTIAL_CONFLICTS_SKIPPED",
            },
        ]
    )

    result = aggregate_ivan_manual_ads_for_charts(raw_df)

    assert result.to_dict(orient="records") == [
        {
            "report_date": pd.Timestamp("2026-03-20").date(),
            "nm_id": 111,
            "supplier_article": "a-1",
            "title": "Товар A",
            "ad_campaign_spend_total_manual": 150.0,
            "ad_atbs_total_manual": 15.0,
            "ad_views_total_manual": 1500.0,
            "ad_cost_per_cart_manual": 10.0,
            "ad_cpm_manual": 100.0,
            "source_status": "IVAN_ADS_WIDE_IMPORT",
            "data_status": "MANUAL_UPLOAD",
            "import_quality": "PARTIAL_CONFLICTS_SKIPPED",
            "ad_data_source": "IVAN_ADS_WIDE_IMPORT",
        }
    ]


def test_merge_ivan_manual_ads_into_chart_scope_uses_manual_when_api_missing() -> None:
    scope_rows = pd.DataFrame(
        [
            {
                "report_date": "2026-03-20",
                "nm_id": 111,
                "cart_count": 40.0,
                "order_count": 8.0,
                "ad_campaign_spend_total": None,
                "ad_atbs_total": None,
                "ad_views_total": None,
                "has_ad_cost": False,
                "has_ad_campaign": False,
            }
        ]
    )
    manual_chart_df = pd.DataFrame(
        [
            {
                "report_date": pd.Timestamp("2026-03-20").date(),
                "nm_id": 111,
                "supplier_article": "a-1",
                "title": "Товар A",
                "ad_campaign_spend_total_manual": 150.0,
                "ad_atbs_total_manual": 15.0,
                "ad_views_total_manual": 1500.0,
                "ad_cost_per_cart_manual": 10.0,
                "ad_cpm_manual": 100.0,
                "source_status": "IVAN_ADS_WIDE_IMPORT",
                "data_status": "MANUAL_UPLOAD",
                "import_quality": "PARTIAL_CONFLICTS_SKIPPED",
                "ad_data_source": "IVAN_ADS_WIDE_IMPORT",
            }
        ]
    )

    merged, summary = merge_ivan_manual_ads_into_chart_scope(
        scope_rows,
        manual_chart_df,
        aggregation_level=CHART_LEVEL_CABINET,
        period_start=pd.Timestamp("2026-03-20").date(),
        period_end=pd.Timestamp("2026-03-20").date(),
        total_manual_rows=1,
        total_manual_products=1,
        total_manual_spend=150.0,
        manual_period_start=pd.Timestamp("2026-03-20").date(),
        manual_period_end=pd.Timestamp("2026-03-20").date(),
        matched_dim_product_rows=0,
        matched_active_product_rows=0,
    )

    assert float(merged.loc[0, "ad_campaign_spend_total"]) == 150.0
    assert float(merged.loc[0, "ad_atbs_total"]) == 15.0
    assert float(merged.loc[0, "ad_views_total"]) == 1500.0
    assert float(merged.loc[0, "ad_cost_per_cart_calc"]) == 10.0
    assert float(merged.loc[0, "ad_cpm_calc"]) == 100.0
    assert merged.loc[0, "ad_data_source"] == "IVAN_ADS_WIDE_IMPORT"
    assert summary["ivan_manual_rows_used_in_charts"] == 1
    assert summary["ivan_manual_rows_skipped_because_api_exists"] == 0
    assert summary["ivan_manual_rows_hidden_by_current_filters"] == 0


def test_merge_ivan_manual_ads_into_chart_scope_does_not_sum_over_api() -> None:
    scope_rows = pd.DataFrame(
        [
            {
                "report_date": "2026-05-10",
                "nm_id": 111,
                "cart_count": 50.0,
                "order_count": 10.0,
                "ad_campaign_spend_total": 90.0,
                "ad_atbs_total": 9.0,
                "ad_views_total": 900.0,
                "has_ad_cost": True,
                "has_ad_campaign": True,
            }
        ]
    )
    manual_chart_df = pd.DataFrame(
        [
            {
                "report_date": pd.Timestamp("2026-05-10").date(),
                "nm_id": 111,
                "supplier_article": "a-1",
                "title": "Товар A",
                "ad_campaign_spend_total_manual": 150.0,
                "ad_atbs_total_manual": 15.0,
                "ad_views_total_manual": 1500.0,
                "ad_cost_per_cart_manual": 10.0,
                "ad_cpm_manual": 100.0,
                "source_status": "IVAN_ADS_WIDE_IMPORT",
                "data_status": "MANUAL_UPLOAD",
                "import_quality": "PARTIAL_CONFLICTS_SKIPPED",
                "ad_data_source": "IVAN_ADS_WIDE_IMPORT",
            }
        ]
    )

    merged, summary = merge_ivan_manual_ads_into_chart_scope(
        scope_rows,
        manual_chart_df,
        aggregation_level=CHART_LEVEL_CABINET,
        period_start=pd.Timestamp("2026-05-10").date(),
        period_end=pd.Timestamp("2026-05-10").date(),
        total_manual_rows=1,
        total_manual_products=1,
        total_manual_spend=150.0,
        manual_period_start=pd.Timestamp("2026-05-10").date(),
        manual_period_end=pd.Timestamp("2026-05-10").date(),
        matched_dim_product_rows=0,
        matched_active_product_rows=0,
    )

    assert float(merged.loc[0, "ad_campaign_spend_total"]) == 90.0
    assert float(merged.loc[0, "ad_atbs_total"]) == 9.0
    assert summary["ivan_manual_rows_used_in_charts"] == 0
    assert summary["ivan_manual_rows_skipped_because_api_exists"] == 1


def test_merge_ivan_manual_ads_into_chart_scope_hides_manual_without_scope_match_in_cabinet() -> None:
    scope_rows = pd.DataFrame(
        [
            {
                "report_date": "2026-03-20",
                "nm_id": 111,
                "cart_count": 40.0,
                "order_count": 8.0,
                "ad_campaign_spend_total": None,
                "ad_atbs_total": None,
                "ad_views_total": None,
                "has_ad_cost": False,
                "has_ad_campaign": False,
            }
        ]
    )
    manual_chart_df = pd.DataFrame(
        [
            {
                "report_date": pd.Timestamp("2026-03-20").date(),
                "nm_id": 222,
                "supplier_article": "b-2",
                "title": "Товар B",
                "ad_campaign_spend_total_manual": 200.0,
                "ad_atbs_total_manual": 20.0,
                "ad_views_total_manual": 2000.0,
                "ad_cost_per_cart_manual": 10.0,
                "ad_cpm_manual": 100.0,
                "source_status": "IVAN_ADS_WIDE_IMPORT",
                "data_status": "MANUAL_UPLOAD",
                "import_quality": "PARTIAL_CONFLICTS_SKIPPED",
                "ad_data_source": "IVAN_ADS_WIDE_IMPORT",
            }
        ]
    )

    merged, summary = merge_ivan_manual_ads_into_chart_scope(
        scope_rows,
        manual_chart_df,
        aggregation_level=CHART_LEVEL_CABINET,
        period_start=pd.Timestamp("2026-03-20").date(),
        period_end=pd.Timestamp("2026-03-20").date(),
        total_manual_rows=1,
        total_manual_products=1,
        total_manual_spend=200.0,
        manual_period_start=pd.Timestamp("2026-03-20").date(),
        manual_period_end=pd.Timestamp("2026-03-20").date(),
        matched_dim_product_rows=0,
        matched_active_product_rows=0,
    )

    assert merged["nm_id"].tolist() == [111]
    assert summary["ivan_manual_rows_used_in_charts"] == 0
    assert summary["ivan_manual_rows_hidden_by_current_filters"] == 1


def test_merge_ivan_manual_ads_into_chart_scope_reports_hidden_rows_for_article_filter() -> None:
    scope_rows = pd.DataFrame(
        [
            {
                "report_date": "2026-03-20",
                "nm_id": 111,
                "supplier_article": "a-1",
                "title": "Товар A",
                "ad_campaign_spend_total": None,
                "ad_atbs_total": None,
                "ad_views_total": None,
                "has_ad_cost": False,
                "has_ad_campaign": False,
            }
        ]
    )
    manual_chart_df = pd.DataFrame(
        [
            {
                "report_date": pd.Timestamp("2026-03-20").date(),
                "nm_id": 222,
                "supplier_article": "b-2",
                "title": "Товар B",
                "ad_campaign_spend_total_manual": 200.0,
                "ad_atbs_total_manual": 20.0,
                "ad_views_total_manual": 2000.0,
                "ad_cost_per_cart_manual": 10.0,
                "ad_cpm_manual": 100.0,
                "source_status": "IVAN_ADS_WIDE_IMPORT",
                "data_status": "MANUAL_UPLOAD",
                "import_quality": "PARTIAL_CONFLICTS_SKIPPED",
                "ad_data_source": "IVAN_ADS_WIDE_IMPORT",
            }
        ]
    )

    merged, summary = merge_ivan_manual_ads_into_chart_scope(
        scope_rows,
        manual_chart_df,
        aggregation_level=CHART_LEVEL_ARTICLE,
        period_start=pd.Timestamp("2026-03-20").date(),
        period_end=pd.Timestamp("2026-03-20").date(),
        total_manual_rows=1,
        total_manual_products=1,
        total_manual_spend=200.0,
        manual_period_start=pd.Timestamp("2026-03-20").date(),
        manual_period_end=pd.Timestamp("2026-03-20").date(),
        matched_dim_product_rows=0,
        matched_active_product_rows=0,
    )

    assert merged["nm_id"].tolist() == [111]
    assert summary["ivan_manual_rows_used_in_charts"] == 0
    assert summary["ivan_manual_rows_hidden_by_current_filters"] == 1


def test_build_chart_metrics_by_date_keeps_unified_business_metrics_with_source_diagnostics() -> None:
    scope_rows = pd.DataFrame(
        [
            {
                "report_date": "2026-03-20",
                "cart_count": 40.0,
                "order_count": 8.0,
                "ad_campaign_spend_total": 150.0,
                "ad_atbs_total": 15.0,
                "ad_cost_writeoff_total": None,
                "ad_campaign_spend_total_api": None,
                "ad_campaign_spend_total_manual": 150.0,
                "ad_atbs_total_api": None,
                "ad_atbs_total_manual": 15.0,
            },
            {
                "report_date": "2026-05-10",
                "cart_count": 50.0,
                "order_count": 10.0,
                "ad_campaign_spend_total": 90.0,
                "ad_atbs_total": 9.0,
                "ad_cost_writeoff_total": 90.0,
                "ad_campaign_spend_total_api": 90.0,
                "ad_campaign_spend_total_manual": None,
                "ad_atbs_total_api": 9.0,
                "ad_atbs_total_manual": None,
            },
        ]
    )

    chart_df = build_chart_metrics_by_date(scope_rows, reference_date=pd.Timestamp("2026-05-20").date())

    assert "ad_campaign_spend_total_api" in chart_df.columns
    assert "ad_campaign_spend_total_manual" in chart_df.columns
    assert "ad_atbs_total_api_confirmed" in chart_df.columns
    assert "ad_atbs_total_manual_confirmed" in chart_df.columns
    assert "ad_atbs_total_api" in chart_df.columns
    assert "ad_atbs_total_manual" in chart_df.columns
    assert float(chart_df.loc[chart_df["report_date"] == pd.Timestamp("2026-03-20").date(), "ad_atbs_total_confirmed"].iloc[0]) == 15.0
    assert float(chart_df.loc[chart_df["report_date"] == pd.Timestamp("2026-05-10").date(), "ad_atbs_total_confirmed"].iloc[0]) == 9.0
    assert float(chart_df.loc[chart_df["report_date"] == pd.Timestamp("2026-03-20").date(), "ad_cart_cost"].iloc[0]) == 10.0
    assert float(chart_df.loc[chart_df["report_date"] == pd.Timestamp("2026-05-10").date(), "ad_cart_cost"].iloc[0]) == 10.0
    first_row = chart_df.iloc[0]
    second_row = chart_df.iloc[1]
    assert float(first_row["ad_campaign_spend_total_manual"]) == 150.0
    assert pd.isna(first_row["ad_campaign_spend_total_api"])
    assert float(second_row["ad_campaign_spend_total_api"]) == 90.0
    assert pd.isna(second_row["ad_campaign_spend_total_manual"])


def test_build_ad_carts_chart_series_map_uses_only_business_legend_labels() -> None:
    series_map = build_ad_carts_chart_series_map(is_conversion_level=False)

    assert series_map == {
        "cart_count": "Итоговые корзины",
        "ad_atbs_total_confirmed": "Корзины РК",
    }
    assert API_WB_AD_SOURCE_LABEL not in series_map.values()
    assert IVAN_MANUAL_AD_SOURCE_LABEL not in series_map.values()


def test_build_ad_cart_cost_chart_series_map_uses_only_business_legend_labels() -> None:
    series_map = build_ad_cart_cost_chart_series_map(is_conversion_level=False)

    assert series_map == {
        "total_cart_cost": "Стоимость корзины ИТОГО",
        "ad_cart_cost": "Стоимость корзины РК",
    }
    assert API_WB_AD_SOURCE_LABEL not in series_map.values()
    assert IVAN_MANUAL_AD_SOURCE_LABEL not in series_map.values()


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

    assert "Показы общие.1" not in export_df.columns
    assert list(export_df.columns).count("Показы общие") == 1
    assert export_df.columns.is_unique


def test_build_export_dataframe_includes_wb_price_without_helper_fields() -> None:
    table_df = pd.DataFrame(
        [
            {
                "supplier_article": "BlackWOM5",
                "nm_id": 197330807,
                "wb_buyer_price": 799.0,
                "previous_wb_buyer_price": 730.0,
                "wb_price_delta": 69.0,
                "wb_price_alert": True,
            }
        ]
    )

    export_df = build_export_dataframe(table_df, ["supplier_article", "nm_id", "wb_buyer_price"])

    assert list(export_df.columns) == [
        app_streamlit.EXPORT_COLUMN_LABELS["supplier_article"],
        app_streamlit.EXPORT_COLUMN_LABELS["nm_id"],
        app_streamlit.EXPORT_COLUMN_LABELS["wb_buyer_price"],
    ]
    assert float(export_df.loc[0, app_streamlit.EXPORT_COLUMN_LABELS["wb_buyer_price"]]) == 799.0


def test_display_columns_by_date_include_wb_price() -> None:
    assert "wb_buyer_price" in DISPLAY_COLUMNS_BY_DATE


def test_build_product_timeline_dataset_keeps_wb_price() -> None:
    product_rows = pd.DataFrame(
        [
            {
                "report_date": "2026-06-17",
                "wb_buyer_price": 799.0,
                "impressions": 10,
                "cart_count": 2,
                "order_count": 1,
                "order_sum": 1000.0,
                "ad_campaign_spend_total": 50.0,
                "ad_atbs_total": 1,
                "ad_orders_total": 1,
                "ad_cpo_calc": 50.0,
                "search_queries_count": 3,
                "current_stock_qty": 10,
                "data_quality_status": "OK_PARTIAL_SOURCES",
            }
        ]
    )

    timeline = build_product_timeline_dataset(product_rows)

    assert "wb_buyer_price" in timeline.columns
    assert float(timeline.loc[0, "wb_buyer_price"]) == 799.0


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


def test_build_chart_metrics_by_date_calculates_user_friendly_metrics() -> None:
    source_df = pd.DataFrame(
        [
            {
                "report_date": "2026-06-05",
                "cart_count": 10,
                "ad_atbs_total": 5,
                "order_count": 4,
                "ad_orders_total": 2,
                "ad_campaign_spend_total": 200,
            },
            {
                "report_date": "2026-06-05",
                "cart_count": 5,
                "ad_atbs_total": 5,
                "order_count": 1,
                "ad_orders_total": 1,
                "ad_campaign_spend_total": 100,
            },
            {
                "report_date": "2026-06-06",
                "cart_count": None,
                "ad_atbs_total": 0,
                "order_count": 0,
                "ad_orders_total": None,
                "ad_campaign_spend_total": 50,
            },
        ]
    )

    result = build_chart_metrics_by_date(source_df)

    first = result.iloc[0]
    second = result.iloc[1]
    assert float(first["cart_count"]) == 15.0
    assert float(first["ad_atbs_total"]) == 10.0
    assert float(first["total_cart_cost"]) == 20.0
    assert float(first["ad_cart_cost"]) == 30.0
    assert float(first["total_cpo"]) == 60.0
    assert float(first["ad_cpo"]) == 100.0
    assert pd.isna(second["total_cart_cost"])
    assert pd.isna(second["ad_cart_cost"])
    assert pd.isna(second["total_cpo"])
    assert pd.isna(second["ad_cpo"])


def test_build_chart_metrics_by_date_marks_yesterday_ad_attribution_as_lagged() -> None:
    source_df = pd.DataFrame(
        [
            {
                "report_date": "2026-06-06",
                "cart_count": 10,
                "ad_atbs_total": 5,
                "order_count": 4,
                "ad_orders_total": 2,
                "ad_campaign_spend_total": 100,
            },
            {
                "report_date": "2026-06-07",
                "cart_count": 8,
                "ad_atbs_total": 3,
                "order_count": 3,
                "ad_orders_total": 1,
                "ad_campaign_spend_total": 50,
            },
        ]
    )

    result = build_chart_metrics_by_date(source_df, reference_date=datetime(2026, 6, 8).date())

    mature_row = result.loc[result["report_date"] == pd.to_datetime("2026-06-06").date()].iloc[0]
    lagged_row = result.loc[result["report_date"] == pd.to_datetime("2026-06-07").date()].iloc[0]

    assert mature_row["ad_attribution_status"] == "OK"
    assert float(mature_row["ad_atbs_total_confirmed"]) == 5.0
    assert float(mature_row["ad_orders_total_confirmed"]) == 2.0
    assert float(mature_row["ad_spend_confirmed"]) == 100.0
    assert float(mature_row["ad_cart_cost"]) == 20.0
    assert float(mature_row["ad_cpo"]) == 50.0

    assert lagged_row["ad_attribution_status"] == "AD_ATTRIBUTION_LAGGED"
    assert pd.isna(lagged_row["ad_atbs_total_confirmed"])
    assert pd.isna(lagged_row["ad_orders_total_confirmed"])
    assert pd.isna(lagged_row["ad_spend_confirmed"])
    assert pd.isna(lagged_row["ad_cart_cost"])
    assert pd.isna(lagged_row["ad_cpo"])
    assert float(lagged_row["total_cart_cost"]) == 6.25


def test_build_chart_metrics_by_date_marks_partial_ad_attribution_when_spend_coverage_is_low() -> None:
    source_df = pd.DataFrame(
        [
            {
                "report_date": "2026-06-08",
                "cart_count": 100,
                "ad_atbs_total": 20,
                "order_count": 40,
                "ad_orders_total": 10,
                "ad_campaign_spend_total": 1000,
                "ad_cost_writeoff_total": 10000,
            }
        ]
    )

    result = build_chart_metrics_by_date(source_df, reference_date=datetime(2026, 6, 17).date())

    row = result.iloc[0]

    assert row["ad_attribution_status"] == "AD_DATA_PARTIAL"
    assert pd.isna(row["ad_atbs_total_confirmed"])
    assert pd.isna(row["ad_orders_total_confirmed"])
    assert pd.isna(row["ad_spend_confirmed"])
    assert pd.isna(row["ad_cart_cost"])
    assert pd.isna(row["ad_cpo"])
    assert float(row["total_cart_cost"]) == 10.0


def test_build_chart_period_summary_uses_separate_cutoffs_for_total_and_ad_metrics() -> None:
    chart_df = pd.DataFrame(
        [
            {
                "report_date": pd.to_datetime("2026-06-06").date(),
                "cart_count": 10,
                "ad_atbs_total": 5,
                "ad_atbs_total_confirmed": 5,
                "order_count": 4,
                "ad_orders_total": 2,
                "ad_orders_total_confirmed": 2,
                "ad_campaign_spend_total": 100,
                "ad_spend_confirmed": 100,
                "ad_attribution_status": "OK",
            },
            {
                "report_date": pd.to_datetime("2026-06-07").date(),
                "cart_count": 8,
                "ad_atbs_total": 3,
                "ad_atbs_total_confirmed": None,
                "order_count": 3,
                "ad_orders_total": 1,
                "ad_orders_total_confirmed": None,
                "ad_campaign_spend_total": 50,
                "ad_spend_confirmed": None,
                "ad_attribution_status": "AD_ATTRIBUTION_LAGGED",
            },
        ]
    )

    summary = build_chart_period_summary(chart_df, reference_date=datetime(2026, 6, 8).date())

    assert float(summary["total_carts"]) == 18.0
    assert float(summary["total_orders"]) == 7.0
    assert float(summary["ad_spend_total"]) == 150.0
    assert float(summary["ad_carts"]) == 5.0
    assert float(summary["ad_orders"]) == 2.0
    assert float(summary["ad_spend_confirmed"]) == 100.0
    assert round(float(summary["total_cart_cost"]), 4) == round(150.0 / 18.0, 4)
    assert round(float(summary["total_cpo"]), 4) == round(150.0 / 7.0, 4)
    assert float(summary["ad_cart_cost"]) == 20.0
    assert float(summary["ad_cpo"]) == 50.0
    assert summary["has_lagged_ad_attribution"] is True
    assert summary["has_partial_ad_attribution"] is False


def test_build_chart_product_options_filters_to_ad_active_products_by_default() -> None:
    filtered = pd.DataFrame(
        [
            {
                "supplier_article": "BlackWOM5",
                "nm_id": 197330807,
                "subject": "Трусы",
                "ad_campaign_spend_total": 100,
                "ad_atbs_total": 5,
                "ad_orders_total": 1,
                "ad_views_total": 10,
                "ad_clicks_total": 2,
            },
            {
                "supplier_article": "NoAds",
                "nm_id": 2,
                "subject": "Топы",
                "ad_campaign_spend_total": None,
                "ad_atbs_total": None,
                "ad_orders_total": None,
                "ad_views_total": None,
                "ad_clicks_total": None,
            },
        ]
    )

    active_options, active_map = build_chart_product_options(filtered, ads_only=True)
    all_options, all_map = build_chart_product_options(filtered, ads_only=False)

    assert active_options == ["BlackWOM5 | 197330807 | Трусы"]
    assert active_map["BlackWOM5 | 197330807 | Трусы"]["nm_id"] == 197330807
    assert all_options == [
        "BlackWOM5 | 197330807 | Трусы",
        "NoAds | 2 | Топы",
    ]
    assert all_map["NoAds | 2 | Топы"]["nm_id"] == 2


def test_build_chart_scope_rows_returns_category_slice_and_context() -> None:
    filtered = pd.DataFrame(
        [
            {"report_date": "2026-06-06", "nm_id": 1, "subject": "Трусы", "cart_count": 5},
            {"report_date": "2026-06-06", "nm_id": 2, "subject": "Топы", "cart_count": 3},
        ]
    )

    scope_rows, context = build_chart_scope_rows(
        filtered=filtered,
        aggregation_level="Категория",
        selected_product_label=None,
        option_map={},
        selected_subject="Трусы",
        ad_campaign_product_df=pd.DataFrame(),
        selected_conversion_type=None,
    )

    assert scope_rows["subject"].tolist() == ["Трусы"]
    assert context["scope"] == "Категория"
    assert context["level_value"] == "Трусы"


def test_build_chart_scope_rows_returns_band_slice_and_context() -> None:
    filtered = pd.DataFrame(
        [
            {"report_date": "2026-06-06", "nm_id": 1, "band_name": "Банда Футболки", "cart_count": 5},
            {"report_date": "2026-06-06", "nm_id": 2, "band_name": "Банда ТРУСЫ Женские", "cart_count": 3},
        ]
    )

    scope_rows, context = build_chart_scope_rows(
        filtered=filtered,
        aggregation_level="Банда",
        selected_product_label=None,
        option_map={},
        selected_subject=None,
        selected_band="Банда Футболки",
        ad_campaign_product_df=pd.DataFrame(),
        selected_conversion_type=None,
    )

    assert scope_rows["band_name"].tolist() == ["Банда Футболки"]
    assert context["scope"] == "Банда"
    assert context["level_value"] == "Банда Футболки"


def test_build_chart_scope_rows_returns_conversion_scope_from_ad_dataset() -> None:
    filtered = pd.DataFrame(
        [
            {"report_date": pd.to_datetime("2026-06-07").date(), "nm_id": 197330807},
            {"report_date": pd.to_datetime("2026-06-07").date(), "nm_id": 37320545},
        ]
    )
    ad_campaign_product_df = pd.DataFrame(
        [
            {
                "report_date": pd.to_datetime("2026-06-07").date(),
                "nm_id": 197330807,
                "conversion_type": "UNKNOWN_CODE_64",
                "campaign_spend": 150,
                "ad_atbs": 5,
                "ad_orders": 2,
            },
            {
                "report_date": pd.to_datetime("2026-06-07").date(),
                "nm_id": 999,
                "conversion_type": "UNKNOWN_CODE_64",
                "campaign_spend": 999,
                "ad_atbs": 99,
                "ad_orders": 9,
            },
            {
                "report_date": pd.to_datetime("2026-06-07").date(),
                "nm_id": 197330807,
                "conversion_type": "Прямая",
                "campaign_spend": 120,
                "ad_atbs": 4,
                "ad_orders": 1,
            },
        ]
    )

    scope_rows, context = build_chart_scope_rows(
        filtered=filtered,
        aggregation_level="Тип WB / конверсии",
        selected_product_label=None,
        option_map={},
        selected_subject=None,
        ad_campaign_product_df=ad_campaign_product_df,
        selected_conversion_type="UNKNOWN_CODE_64",
    )

    assert len(scope_rows) == 1
    assert float(scope_rows.iloc[0]["ad_campaign_spend_total"]) == 150.0
    assert float(scope_rows.iloc[0]["ad_atbs_total"]) == 5.0
    assert float(scope_rows.iloc[0]["ad_orders_total"]) == 2.0
    assert context["scope"] == "Тип WB / конверсии"
    assert context["level_value"] == "Неизвестный тип WB 64"
    assert context["technical_level_value"] == "UNKNOWN_CODE_64"


def test_build_category_summary_table_aggregates_categories_and_flags_thresholds() -> None:
    filtered = pd.DataFrame(
        [
            {
                "subject": "Трусы",
                "cart_count": 10,
                "ad_atbs_total": 2,
                "ad_campaign_spend_total": 100,
                "ad_orders_total": 1,
            },
                {
                    "subject": "Трусы",
                    "cart_count": 5,
                    "ad_atbs_total": 3,
                    "ad_campaign_spend_total": 100,
                    "ad_orders_total": 1,
                },
            {
                "subject": "Топы",
                "cart_count": 8,
                "ad_atbs_total": 4,
                "ad_campaign_spend_total": 80,
                "ad_orders_total": 2,
            },
        ]
    )

    summary_df = build_category_summary_table(filtered)

    assert summary_df["Категория"].tolist() == ["Трусы", "Топы"]
    assert float(summary_df.iloc[0]["Корзины РК"]) == 5.0
    assert float(summary_df.iloc[0]["CPO РК"]) == 100.0
    assert summary_df.iloc[0]["Флаг превышения"] == "Да"
    assert summary_df.iloc[1]["Флаг превышения"] == "—"


def test_build_band_summary_table_aggregates_bands_and_flags_thresholds() -> None:
    filtered = pd.DataFrame(
        [
            {
                "band_name": "Банда Футболки",
                "nm_id": 1,
                "cart_count": 10,
                "ad_atbs_total": 2,
                "ad_campaign_spend_total": 100,
                "ad_orders_total": 1,
            },
            {
                "band_name": "Банда Футболки",
                "nm_id": 2,
                "cart_count": 5,
                "ad_atbs_total": 3,
                "ad_campaign_spend_total": 100,
                "ad_orders_total": 1,
            },
            {
                "band_name": "Банда ТРУСЫ Женские",
                "nm_id": 3,
                "cart_count": 8,
                "ad_atbs_total": 4,
                "ad_campaign_spend_total": 80,
                "ad_orders_total": 2,
            },
        ]
    )

    summary_df = build_band_summary_table(filtered)

    assert summary_df["Банда"].tolist() == ["Банда Футболки", "Банда ТРУСЫ Женские"]
    assert float(summary_df.iloc[0]["Товаров"]) == 2.0
    assert float(summary_df.iloc[0]["Корзины РК"]) == 5.0
    assert float(summary_df.iloc[0]["CPO РК"]) == 100.0
    assert summary_df.iloc[0]["Превышения"] == "Да"
    assert summary_df.iloc[1]["Превышения"] == "—"


def test_apply_product_bands_adds_band_name_and_excludes_unmapped_as_null() -> None:
    filtered = pd.DataFrame(
        [
            {"nm_id": 577510563, "supplier_article": "futmix3haki"},
            {"nm_id": 999999999, "supplier_article": "unknown"},
        ]
    )

    band_df = apply_product_bands(filtered)

    assert band_df.loc[0, "band_name"] == "Банда Футболки"
    assert pd.isna(band_df.loc[1, "band_name"])


def test_format_wb_conversion_type_label_maps_unknown_code_for_ui() -> None:
    assert format_wb_conversion_type_label("Прямая") == "Прямая"
    assert format_wb_conversion_type_label("UNKNOWN_CODE_64") == "Неизвестный тип WB 64"
    assert format_wb_conversion_type_label(None) == "—"


def test_build_threshold_breaches_table_returns_only_rows_above_thresholds() -> None:
    chart_df = pd.DataFrame(
        [
            {
                "report_date": "2026-06-05",
                "total_cart_cost": CHART_THRESHOLD_CART_COST + 1,
                "ad_cart_cost": CHART_THRESHOLD_CART_COST - 1,
                "total_cpo": CHART_THRESHOLD_CPO + 5,
                "ad_cpo": CHART_THRESHOLD_CPO + 10,
            },
            {
                "report_date": "2026-06-06",
                "total_cart_cost": CHART_THRESHOLD_CART_COST - 1,
                "ad_cart_cost": CHART_THRESHOLD_CART_COST - 1,
                "total_cpo": CHART_THRESHOLD_CPO - 1,
                "ad_cpo": CHART_THRESHOLD_CPO - 1,
            },
        ]
    )

    context = {
        "supplier_article": "BlackWOM5",
        "nm_id": 197330807,
        "title": "Трусы",
    }
    result = build_threshold_breaches_table(chart_df, context)

    assert len(result) == 3
    assert set(result["Показатель"].tolist()) == {
        "Стоимость корзины ИТОГО",
        "CPO ИТОГО",
        "CPO РК",
    }
    assert set(result["Артикул продавца"].tolist()) == {"BlackWOM5"}


def test_build_threshold_breaches_table_includes_level_context_columns() -> None:
    chart_df = pd.DataFrame(
        [
            {
                "report_date": "2026-06-07",
                "ad_cart_cost": CHART_THRESHOLD_CART_COST + 3,
            }
        ]
    )

    context = {
        "scope": "Категория",
        "level_value": "Трусы",
        "supplier_article": "Все товары",
        "nm_id": None,
        "title": "Сумма по выбранным товарам",
    }

    result = build_threshold_breaches_table(
        chart_df,
        context,
        metrics=[("ad_cart_cost", "Стоимость корзины РК", CHART_THRESHOLD_CART_COST)],
    )

    assert result.iloc[0]["Уровень"] == "Категория"
    assert result.iloc[0]["Значение уровня"] == "Трусы"
    assert result.iloc[0]["Превышение"] == "Да"


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


def test_get_latest_product_context_uses_previous_core_coverage_row_for_card_display() -> None:
    product_rows = prepare_dataframe(
        pd.DataFrame(
            [
                {
                    "report_date": "2026-06-15",
                    "nm_id": 1,
                    "has_funnel": True,
                    "cart_count": 10,
                    "order_count": 4,
                },
                {
                    "report_date": "2026-06-16",
                    "nm_id": 1,
                    "has_stock": True,
                    "current_stock_qty": 100,
                },
                {
                    "report_date": "2026-06-17",
                    "nm_id": 1,
                    "has_stock": True,
                    "current_stock_qty": 90,
                },
            ]
        )
    )

    context = get_latest_product_context(product_rows)

    assert context["latest_date"] == pd.to_datetime("2026-06-17").date()
    assert context["display_date"] == pd.to_datetime("2026-06-15").date()
    assert context["display_row"]["cart_count"] == 10
    assert context["display_previous_row"] is None


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


def test_build_warnings_includes_threshold_and_recent_ad_warnings() -> None:
    row = pd.Series(
        {
            "data_quality_status": "OK_PARTIAL_SOURCES",
            "has_ad_campaign": False,
            "order_count": 1,
            "current_stock_qty": 10,
            "entry_point_status": None,
            "orders_geography_status": None,
            "vbro_status": None,
            "ad_cpo_calc": 151,
            "ad_cost_per_cart_calc": 36,
            "report_date": (datetime.now().date() - timedelta(days=1)).isoformat(),
        }
    )

    warnings = build_warnings(row, None)

    assert "Высокий CPO" in warnings
    assert "Высокая стоимость корзины" in warnings
    assert "РК-данные за последние 1–2 дня могут быть неполными" in warnings


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


def test_build_upload_tab_sections_includes_vbro_placeholder() -> None:
    sections = build_upload_tab_sections()

    assert [section["report_name"] for section in sections] == [
        "Точка входа",
        "География заказов",
        "ВБро",
    ]
    assert sections[2]["implemented"] is False
    assert sections[2]["state_key"] == "vbro_import"


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
        "legacy_cost_per_card_click_calc",
        "legacy_cost_per_all_carts_calc",
        "legacy_cost_per_order_calc",
        "legacy_ad_share_of_order_sum_pct",
        "avg_delivery_time",
        "ad_campaign_spend_total",
        "ad_views_total",
        "ad_clicks_total",
        "ad_atbs_total",
        "ad_orders_total",
        "ad_cpc_calc",
        "ad_cpm_calc",
        "ad_cost_per_cart_calc",
        "ad_cpo_calc",
        "organic_cart_count",
        "organic_cart_share_calc",
        "current_stock_qty",
        "current_stock_sum",
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
        "current_mp_stock_qty",
        "direct_ad_atbs",
        "associated_ad_atbs",
        "multicard_ad_atbs",
        "unknown_ad_atbs",
        "ad_share_of_revenue_calc",
        "ad_cost_per_all_carts_calc",
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


def test_display_columns_by_date_places_legacy_block_before_api_ad_block() -> None:
    legacy_start = DISPLAY_COLUMNS_BY_DATE.index("ad_campaign_spend_total")
    api_start = DISPLAY_COLUMNS_BY_DATE.index("ad_views_total")

    expected_legacy_block = [
        "ad_campaign_spend_total",
        "legacy_cost_per_card_click_calc",
        "legacy_cost_per_all_carts_calc",
        "legacy_cost_per_order_calc",
        "legacy_ad_share_of_order_sum_pct",
    ]

    assert DISPLAY_COLUMNS_BY_DATE[legacy_start:api_start] == expected_legacy_block
    assert api_start > legacy_start


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
                "legacy_cpm_common_calc": 6.51,
                "legacy_cost_per_card_click_calc": 1.25,
                "legacy_cost_per_all_carts_calc": 7.51,
                "legacy_cost_per_order_calc": 47.47,
                "legacy_ad_share_of_order_sum_pct": 90.2,
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
                "current_stock_sum": 3500.5,
                "avg_delivery_time": 42.75,
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

    assert "Показы общие" in export_df.columns
    assert "CTR общий" in export_df.columns
    assert "Среднее время доставки" in export_df.columns
    assert "Сумма остатков" in export_df.columns
    assert "Сумма кампании" in export_df.columns
    assert "CPM по общим показам" not in export_df.columns
    assert "Цена перехода по общим переходам" in export_df.columns
    assert "Расход на все корзины" in export_df.columns
    assert "Расход на все заказы" in export_df.columns
    assert "Доля рекламы от суммы заказов, %" in export_df.columns
    assert "CPC РК" in export_df.columns
    assert "CPM РК" in export_df.columns
    assert "Цена корзины РК" in export_df.columns
    assert "CPO РК" in export_df.columns
    assert "Источник точки входа" in export_df.columns
    assert "Источник географии" in export_df.columns
    assert "CPM" not in export_df.columns
    assert "CPC" not in export_df.columns
    assert "CPO" not in export_df.columns
    assert "Показы из Точки входа" not in export_df.columns
    assert "Переходы из Точки входа" not in export_df.columns
    assert "CTR из Точки входа" not in export_df.columns
    assert not any(str(column).startswith("Note:") for column in export_df.columns)
    assert "Остаток МП" not in export_df.columns
    assert "Статус точки входа" not in export_df.columns
    assert "Статус географии" not in export_df.columns
    assert "Технический статус данных" not in export_df.columns


def test_build_export_dataframe_replaces_missing_values_with_dash() -> None:
    table_df = pd.DataFrame(
        [
            {
                "supplier_article": "BlackWOM5",
                "nm_id": 197330807,
                "report_date": "2026-06-07",
                "ad_cpo_calc": None,
                "avg_delivery_time": None,
                "current_stock_sum": None,
            }
        ]
    )

    export_df = build_export_dataframe(
        table_df,
        ["supplier_article", "nm_id", "report_date", "ad_cpo_calc", "avg_delivery_time", "current_stock_sum"],
    )

    assert export_df.loc[0, "CPO РК"] == "—"
    assert export_df.loc[0, "Среднее время доставки"] == "—"
    assert export_df.loc[0, "Сумма остатков"] == "—"


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


def test_filter_overview_empty_rows_removes_only_fully_empty_rows() -> None:
    table_df = pd.DataFrame(
        [
            {
                "nm_id": 1,
                "supplier_article": "empty-all-none",
                "card_clicks": None,
                "cart_count": None,
                "order_count": None,
                "order_sum": None,
            },
            {
                "nm_id": 2,
                "supplier_article": "has-clicks-zero-rest",
                "card_clicks": 5,
                "cart_count": 0,
                "order_count": 0,
                "order_sum": 0,
            },
            {
                "nm_id": 3,
                "supplier_article": "all-zero-is-real-data",
                "card_clicks": 0,
                "cart_count": 0,
                "order_count": 0,
                "order_sum": 0,
            },
            {
                "nm_id": 4,
                "supplier_article": "dash-is-empty-but-order-sum-filled",
                "card_clicks": "—",
                "cart_count": "—",
                "order_count": "—",
                "order_sum": 1250,
            },
        ]
    )

    result = filter_overview_empty_rows(table_df)

    assert result["nm_id"].tolist() == [2, 3, 4]


def test_build_overview_visible_columns_hide_stock_columns() -> None:
    columns = build_overview_visible_columns()

    assert "current_stock_qty" not in columns
    assert "current_stock_sum" not in columns
    assert "wb_buyer_price" in columns
    assert "card_clicks" in columns


def test_build_overview_export_tables_hide_stock_columns_and_empty_rows() -> None:
    table_df = pd.DataFrame(
        [
            {
                "report_date": "2026-06-18",
                "supplier_article": "hidden-empty",
                "nm_id": 101,
                "card_clicks": None,
                "cart_count": None,
                "order_count": None,
                "order_sum": None,
                "current_stock_qty": 10,
                "current_stock_sum": 1000,
                "wb_buyer_price": 799,
            },
            {
                "report_date": "2026-06-18",
                "supplier_article": "kept-row",
                "nm_id": 202,
                "card_clicks": 7,
                "cart_count": 0,
                "order_count": 0,
                "order_sum": 0,
                "current_stock_qty": 20,
                "current_stock_sum": 2000,
                "wb_buyer_price": 899,
            },
        ]
    )

    display_df, export_df = build_overview_export_tables(table_df, show_empty_rows=False)

    assert display_df["nm_id"].tolist() == [202]
    assert "current_stock_qty" not in display_df.columns
    assert "current_stock_sum" not in display_df.columns
    assert "Остаток WB" not in export_df.columns
    assert "Сумма остатков" not in export_df.columns
    assert export_df["Артикул WB"].tolist() == [202]


def test_filter_rows_by_selected_product_label_returns_all_rows_for_all_products() -> None:
    rows = pd.DataFrame(
        [
            {"report_date": "2026-06-18", "nm_id": 101, "supplier_article": "alpha"},
            {"report_date": "2026-06-19", "nm_id": 202, "supplier_article": "beta"},
        ]
    )

    result = filter_rows_by_selected_product_label(
        rows,
        app_streamlit.OVERVIEW_ALL_PRODUCTS_LABEL,
        {"alpha | 101 | Product A": {"nm_id": 101}},
    )

    assert result.to_dict(orient="records") == rows.to_dict(orient="records")


def test_filter_rows_by_selected_product_label_filters_overview_by_nm_id() -> None:
    rows = pd.DataFrame(
        [
            {"report_date": "2026-06-18", "nm_id": 101, "supplier_article": "alpha"},
            {"report_date": "2026-06-19", "nm_id": 101, "supplier_article": "alpha"},
            {"report_date": "2026-06-18", "nm_id": 202, "supplier_article": "beta"},
        ]
    )
    option_map = {
        "alpha | 101 | Product A": {"nm_id": 101},
        "beta | 202 | Product B": {"nm_id": 202},
    }

    result = filter_rows_by_selected_product_label(rows, "beta | 202 | Product B", option_map)

    assert result["nm_id"].tolist() == [202]
    assert result["supplier_article"].tolist() == ["beta"]


def test_build_ad_campaign_product_scope_dataframe_uses_selected_product_and_sidebar_dates() -> None:
    df = pd.DataFrame(
        [
            {"report_date": "2026-06-18", "nm_id": 101, "supplier_article": "alpha", "advert_id": 1},
            {"report_date": "2026-06-19", "nm_id": 101, "supplier_article": "alpha", "advert_id": 2},
            {"report_date": "2026-06-18", "nm_id": 202, "supplier_article": "beta", "advert_id": 3},
            {"report_date": "2026-06-20", "nm_id": 101, "supplier_article": "alpha", "advert_id": 4},
        ]
    )
    option_map = {
        "alpha | 101 | Product A": {"nm_id": 101},
        "beta | 202 | Product B": {"nm_id": 202},
    }

    result = build_ad_campaign_product_scope_dataframe(
        df,
        selected_product_label="alpha | 101 | Product A",
        option_map=option_map,
        allowed_report_dates=[
            pd.to_datetime("2026-06-18").date(),
            pd.to_datetime("2026-06-19").date(),
        ],
    )

    assert result["nm_id"].tolist() == [101, 101]
    assert result["report_date"].tolist() == [
        pd.to_datetime("2026-06-18").date(),
        pd.to_datetime("2026-06-19").date(),
    ]


def test_build_excel_export_bytes_creates_xlsx_from_current_table() -> None:
    export_df = pd.DataFrame(
        [
            {
                "Дата": "2026-06-18",
                "Артикул WB": 202,
                "Артикул продавца": "kept-row",
                "Цена WB": 899.0,
            }
        ]
    )

    payload = build_excel_export_bytes(export_df)
    restored = pd.read_excel(BytesIO(payload))

    assert payload[:2] == b"PK"
    assert restored.to_dict(orient="records") == export_df.to_dict(orient="records")


def test_prepare_stock_warehouse_history_snapshot_dataframe_keeps_latest_loaded_at_per_day_nm_warehouse() -> None:
    raw = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-06-18",
                "nm_id": 101,
                "chrt_id": 1,
                "warehouse_id": 10,
                "warehouse_name": "Коледино",
                "stock_qty": 5,
                "loaded_at": "2026-06-18T09:00:00",
            },
            {
                "snapshot_date": "2026-06-18",
                "nm_id": 101,
                "chrt_id": 2,
                "warehouse_id": 10,
                "warehouse_name": "Коледино",
                "stock_qty": 7,
                "loaded_at": "2026-06-18T09:00:00",
            },
            {
                "snapshot_date": "2026-06-18",
                "nm_id": 101,
                "chrt_id": 1,
                "warehouse_id": 10,
                "warehouse_name": "Коледино",
                "stock_qty": 3,
                "loaded_at": "2026-06-18T11:00:00",
            },
            {
                "snapshot_date": "2026-06-18",
                "nm_id": 101,
                "chrt_id": 2,
                "warehouse_id": 10,
                "warehouse_name": "Коледино",
                "stock_qty": 2,
                "loaded_at": "2026-06-18T11:00:00",
            },
        ]
    )

    prepared = prepare_stock_warehouse_history_snapshot_dataframe(raw)

    assert len(prepared) == 1
    assert prepared.loc[0, "stock_qty"] == 5
    assert prepared.loc[0, "loaded_at"] == pd.Timestamp("2026-06-18T11:00:00")


def test_classify_stock_warehouse_history_anomaly_supports_expected_status_sets() -> None:
    assert classify_stock_warehouse_history_anomaly(["NO_DATA", "NO_DATA"]) == "ALWAYS_NO_DATA"
    assert classify_stock_warehouse_history_anomaly(["ZERO_STOCK", "ZERO_STOCK"]) == "ALWAYS_ZERO"
    assert classify_stock_warehouse_history_anomaly(["IN_STOCK", "IN_STOCK"]) == "ALWAYS_IN_STOCK"
    assert classify_stock_warehouse_history_anomaly(["ZERO_STOCK", "IN_STOCK"]) == "MIXED_ZERO_AND_STOCK"
    assert classify_stock_warehouse_history_anomaly(["NO_DATA", "IN_STOCK"]) == "MIXED_NO_DATA_AND_STOCK"
    assert classify_stock_warehouse_history_anomaly(["NO_DATA", "ZERO_STOCK", "IN_STOCK"]) == "UNSTABLE"


def test_build_stock_warehouse_history_table_builds_virtual_grid_and_stock_statuses_in_memory() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-06-18",
                "nm_id": 101,
                "warehouse_id": 10,
                "warehouse_name": "Коледино",
                "stock_qty": 4,
                "loaded_at": "2026-06-18T09:00:00",
            },
            {
                "snapshot_date": "2026-06-19",
                "nm_id": 101,
                "warehouse_id": 10,
                "warehouse_name": "Коледино",
                "stock_qty": 0,
                "loaded_at": "2026-06-19T09:00:00",
            },
        ]
    )
    tracked_df = pd.DataFrame(
        [
            {
                "nm_id": 101,
                "supplier_article": "sku-101",
                "item_label": "Товар 101",
                "tracked_label": "Товар 101",
                "is_tracked": True,
                "lifecycle_status": "active",
            },
            {
                "nm_id": 202,
                "supplier_article": "sku-202",
                "item_label": "Товар 202",
                "tracked_label": "Товар 202",
                "is_tracked": True,
                "lifecycle_status": "active",
            },
        ]
    )

    history = build_stock_warehouse_history_table(
        snapshot_df,
        tracked_df,
        selected_dates=[pd.Timestamp("2026-06-18").date(), pd.Timestamp("2026-06-19").date()],
        monitored_warehouses=["Коледино"],
    )

    assert len(history) == 4
    assert history[["nm_id", "snapshot_date"]].to_dict(orient="records") == [
        {"nm_id": 101, "snapshot_date": pd.Timestamp("2026-06-18").date()},
        {"nm_id": 101, "snapshot_date": pd.Timestamp("2026-06-19").date()},
        {"nm_id": 202, "snapshot_date": pd.Timestamp("2026-06-18").date()},
        {"nm_id": 202, "snapshot_date": pd.Timestamp("2026-06-19").date()},
    ]
    row_in_stock = history[
        (history["snapshot_date"] == pd.Timestamp("2026-06-18").date()) & (history["nm_id"] == 101)
    ].iloc[0]
    row_zero = history[
        (history["snapshot_date"] == pd.Timestamp("2026-06-19").date()) & (history["nm_id"] == 101)
    ].iloc[0]
    row_no_data = history[
        (history["snapshot_date"] == pd.Timestamp("2026-06-18").date()) & (history["nm_id"] == 202)
    ].iloc[0]

    assert row_in_stock["stock_status"] == "IN_STOCK"
    assert row_in_stock["stock_qty"] == 4
    assert row_zero["stock_status"] == "ZERO_STOCK"
    assert row_zero["stock_qty"] == 0
    assert row_no_data["stock_status"] == "NO_DATA"
    assert pd.isna(row_no_data["stock_qty"])


def test_build_stock_all_product_level_keeps_product_title_for_display() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_date": pd.Timestamp("2026-06-30").date(),
                "nm_id": 101,
                "warehouse_id": 10,
                "warehouse_name": "Коледино",
                "stock_qty": 5,
                "in_way_to_client": 1,
                "in_way_from_client": 0,
            },
            {
                "snapshot_date": pd.Timestamp("2026-06-30").date(),
                "nm_id": 202,
                "warehouse_id": 20,
                "warehouse_name": "Казань",
                "stock_qty": 3,
                "in_way_to_client": 0,
                "in_way_from_client": 2,
            },
        ]
    )
    settings_df = pd.DataFrame(
        [
            {
                "nm_id": 101,
                "query_group": "kids_underwear",
                "supplier_article": "art-101",
                "title": "Товар 101",
            },
            {
                "nm_id": 202,
                "query_group": "women_underwear",
                "supplier_article": "art-202",
                "title": "Товар 202",
            },
        ]
    )

    result = build_stock_all_product_level(snapshot_df, settings_df, pd.Timestamp("2026-06-30").date())

    assert "title" in result.columns
    assert "query_group" in result.columns
    assert "band_name" in result.columns
    assert result[["nm_id", "title"]].to_dict(orient="records") == [
        {"nm_id": 101, "title": "Товар 101"},
        {"nm_id": 202, "title": "Товар 202"},
    ]
    assert result[["nm_id", "query_group", "band_name"]].to_dict(orient="records") == [
        {"nm_id": 101, "query_group": "трусы детские", "band_name": "Трусы детские"},
        {"nm_id": 202, "query_group": "трусы женские", "band_name": "Трусы женские"},
    ]


def test_build_stock_all_product_level_merges_ivan_stock_and_calculates_diff() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_date": pd.Timestamp("2026-06-30").date(),
                "nm_id": 101,
                "warehouse_id": 10,
                "warehouse_name": "Коледино",
                "stock_qty": 8,
                "in_way_to_client": 1,
                "in_way_from_client": 0,
            },
            {
                "snapshot_date": pd.Timestamp("2026-06-30").date(),
                "nm_id": 202,
                "warehouse_id": 20,
                "warehouse_name": "Казань",
                "stock_qty": 3,
                "in_way_to_client": 0,
                "in_way_from_client": 0,
            },
        ]
    )
    settings_df = pd.DataFrame(
        [
            {"nm_id": 101, "query_group": "kids_underwear", "supplier_article": "art-101", "title": "Товар 101"},
            {"nm_id": 202, "query_group": "women_underwear", "supplier_article": "art-202", "title": "Товар 202"},
        ]
    )
    one_c_stock_df = pd.DataFrame(
        [
            {"stock_date": pd.Timestamp("2026-06-30").date(), "nm_id": 101, "ivan_stock_qty": 5},
            {"stock_date": pd.Timestamp("2026-06-30").date(), "nm_id": 202, "ivan_stock_qty": 7},
        ]
    )

    result = build_stock_all_product_level(
        snapshot_df,
        settings_df,
        pd.Timestamp("2026-06-30").date(),
        one_c_stock_df=one_c_stock_df,
    )

    assert result[["nm_id", "one_c_stock_qty", "wb_vs_one_c_diff"]].to_dict(orient="records") == [
        {"nm_id": 101, "one_c_stock_qty": 5, "wb_vs_one_c_diff": 3},
        {"nm_id": 202, "one_c_stock_qty": 7, "wb_vs_one_c_diff": -4},
    ]


def test_build_stock_all_band_level_uses_only_real_query_groups_from_db() -> None:
    product_df = pd.DataFrame(
        [
            {
                "band": "трусы женские",
                "nm_id": 101,
                "wb_stock_qty": 5,
                "wb_in_way_to_client": 1,
                "wb_in_way_from_client": 0,
                "wb_total_in_contour": 6,
            },
            {
                "band": "детская футболка",
                "nm_id": 202,
                "wb_stock_qty": 3,
                "wb_in_way_to_client": 0,
                "wb_in_way_from_client": 2,
                "wb_total_in_contour": 5,
            },
            {
                "band": "unknown",
                "nm_id": 303,
                "wb_stock_qty": 9,
                "wb_in_way_to_client": 0,
                "wb_in_way_from_client": 0,
                "wb_total_in_contour": 9,
            },
            {
                "band": pd.NA,
                "nm_id": 404,
                "wb_stock_qty": 7,
                "wb_in_way_to_client": 0,
                "wb_in_way_from_client": 0,
                "wb_total_in_contour": 7,
            },
        ]
    )

    result = build_stock_all_band_level(product_df)
    assert result["band_name"].tolist() == ["Прочее", "Трусы женские"]
    assert result["products_count"].tolist() == [3, 1]
    return

    assert result["band"].tolist() == ["детская футболка", "трусы женские"]
    assert result["products_count"].tolist() == [3, 1]


def test_build_stock_all_product_level_exposes_business_band_name_from_query_group() -> None:
    snapshot_df = pd.DataFrame(
        [
            {"snapshot_date": pd.Timestamp("2026-06-30").date(), "nm_id": 1, "stock_qty": 1, "in_way_to_client": 0, "in_way_from_client": 0},
            {"snapshot_date": pd.Timestamp("2026-06-30").date(), "nm_id": 2, "stock_qty": 1, "in_way_to_client": 0, "in_way_from_client": 0},
            {"snapshot_date": pd.Timestamp("2026-06-30").date(), "nm_id": 3, "stock_qty": 1, "in_way_to_client": 0, "in_way_from_client": 0},
            {"snapshot_date": pd.Timestamp("2026-06-30").date(), "nm_id": 4, "stock_qty": 1, "in_way_to_client": 0, "in_way_from_client": 0},
        ]
    )
    settings_df = pd.DataFrame(
        [
            {"nm_id": 1, "query_group": "women_underwear", "supplier_article": "a1", "title": "A1"},
            {"nm_id": 2, "query_group": "kids_underwear", "supplier_article": "a2", "title": "A2"},
            {"nm_id": 3, "query_group": "men_tshirts", "supplier_article": "a3", "title": "A3"},
            {"nm_id": 4, "query_group": "unknown", "supplier_article": "a4", "title": "A4"},
        ]
    )

    result = build_stock_all_product_level(snapshot_df, settings_df, pd.Timestamp("2026-06-30").date())

    assert "query_group" in result.columns
    assert "band_name" in result.columns
    assert result[["nm_id", "band_name"]].to_dict(orient="records") == [
        {"nm_id": 1, "band_name": "Трусы женские"},
        {"nm_id": 2, "band_name": "Трусы детские"},
        {"nm_id": 3, "band_name": "Футболки"},
        {"nm_id": 4, "band_name": "Прочее"},
    ]


def test_build_stock_all_band_level_groups_by_business_band_name_and_preserves_totals() -> None:
    product_df = pd.DataFrame(
        [
            {"query_group": "women_underwear", "band_name": "Трусы женские", "nm_id": 101, "wb_stock_qty": 5, "wb_in_way_to_client": 1, "wb_in_way_from_client": 0, "wb_total_in_contour": 6},
            {"query_group": "kids_underwear", "band_name": "Трусы детские", "nm_id": 202, "wb_stock_qty": 3, "wb_in_way_to_client": 0, "wb_in_way_from_client": 2, "wb_total_in_contour": 5},
            {"query_group": "women_tshirts", "band_name": "Футболки", "nm_id": 303, "wb_stock_qty": 9, "wb_in_way_to_client": 0, "wb_in_way_from_client": 0, "wb_total_in_contour": 9},
            {"query_group": "men_tshirts", "band_name": "Футболки", "nm_id": 304, "wb_stock_qty": 2, "wb_in_way_to_client": 1, "wb_in_way_from_client": 0, "wb_total_in_contour": 3},
            {"query_group": "gift_sets", "band_name": "Прочее", "nm_id": 404, "wb_stock_qty": 7, "wb_in_way_to_client": 0, "wb_in_way_from_client": 0, "wb_total_in_contour": 7},
        ]
    )

    result = build_stock_all_band_level(product_df)

    assert result["band_name"].tolist() == ["Прочее", "Трусы детские", "Трусы женские", "Футболки"]
    assert result["products_count"].tolist() == [1, 1, 1, 2]
    assert result["wb_total_in_contour"].sum() == product_df["wb_total_in_contour"].sum()


def test_build_stock_all_display_dataframe_product_mode_uses_safe_rename_and_keeps_all_columns() -> None:
    product_df = pd.DataFrame(
        [
            {
                "band_name": "Трусы женские",
                "nm_id": 101,
                "vendor_code": "art-101",
                "title": "Товар 101",
                "wb_stock_qty": 5,
                "wb_in_way_to_client": 1,
                "wb_in_way_from_client": 0,
                "wb_total_in_contour": 6,
                "one_c_stock_qty": 4,
                "wb_vs_one_c_diff": 1,
                "wb_supply_qty": pd.NA,
            }
        ]
    )

    result, numeric_cols = build_stock_all_display_dataframe(product_df, level="По товарам")

    assert result.columns.tolist() == [
        "Банда",
        "Артикул WB",
        "Артикул продавца",
        "Название",
        "Остаток WB на складах",
        "В пути к клиенту",
        "Возвраты в пути",
        "Итого в контуре WB",
        "Остаток 1С",
        "Поставки на WB",
        "Скорость продаж за позавчера",
        "Скорость продаж за прошедшую неделю",
        "Прогноз остатков по скорости позавчера",
        "Прогноз остатков по скорости недели",
    ]
    assert result.iloc[0]["Банда"] == "Трусы женские"
    assert result.iloc[0]["Артикул WB"] == 101
    assert result.iloc[0]["Остаток 1С"] == 4
    assert "Разница WB - 1С" not in result.columns
    assert "Разница WB - 1С" not in numeric_cols
    assert "Артикул WB" in numeric_cols
    assert "Скорость продаж за позавчера" in numeric_cols
    assert "Скорость продаж за прошедшую неделю" in numeric_cols
    assert "Прогноз остатков по скорости позавчера" in numeric_cols
    assert "Прогноз остатков по скорости недели" in numeric_cols


def test_build_stock_all_display_dataframe_with_sales_speed_calculations() -> None:
    from datetime import date
    
    product_df = pd.DataFrame(
        [
            {
                "query_group": "women_underwear",
                "band_name": "Трусы женские",
                "nm_id": 101,
                "wb_stock_qty": 10,
                "wb_in_way_to_client": 0,
                "wb_in_way_from_client": 0,
                "wb_total_in_contour": 10,
                "one_c_stock_qty": 4,  # Суммарный остаток = 10 + 4 = 14
                "wb_vs_one_c_diff": 6,
                "wb_supply_qty": pd.NA,
            },
            {
                "query_group": "women_underwear",
                "band_name": "Трусы женские",
                "nm_id": 102,
                "wb_stock_qty": 5,
                "wb_in_way_to_client": 0,
                "wb_in_way_from_client": 0,
                "wb_total_in_contour": 5,
                "one_c_stock_qty": pd.NA,  # Суммарный остаток = 5
                "wb_vs_one_c_diff": pd.NA,
                "wb_supply_qty": pd.NA,
            },
            {
                "query_group": "women_underwear",
                "band_name": "Трусы женские",
                "nm_id": 103,
                "wb_stock_qty": 0,
                "wb_in_way_to_client": 0,
                "wb_in_way_from_client": 0,
                "wb_total_in_contour": 0,
                "one_c_stock_qty": 0,  # Суммарный остаток = 0
                "wb_vs_one_c_diff": 0,
                "wb_supply_qty": pd.NA,
            }
        ]
    )

    snapshot_date = date(2026, 7, 4)
    # Позавчера = 2026-07-02
    # Неделя = 2026-06-27 - 2026-07-03
    sales_data = [
        # Для 101:
        # позавчера: 2
        {"nm_id": 101, "date": date(2026, 7, 2), "order_count": 2},
        # другие дни за неделю: 1, 0, 3, 1, 0. Всего за неделю: 2 + 1 + 0 + 3 + 1 + 0 = 7. Средняя = 7 / 7 = 1.0
        {"nm_id": 101, "date": date(2026, 7, 3), "order_count": 1},
        {"nm_id": 101, "date": date(2026, 7, 1), "order_count": 0},
        {"nm_id": 101, "date": date(2026, 6, 30), "order_count": 3},
        {"nm_id": 101, "date": date(2026, 6, 29), "order_count": 1},
        {"nm_id": 101, "date": date(2026, 6, 28), "order_count": 0},
        # Для 102:
        # позавчера: данных нет (должно быть pd.NA)
        # неделя: все продажи 0. Сумма = 0. Средняя = 0.0.
        {"nm_id": 102, "date": date(2026, 7, 3), "order_count": 0},
        {"nm_id": 102, "date": date(2026, 7, 1), "order_count": 0},
        # Для 103:
        # позавчера: 1. Прогноз по позавчера: 0 / 1 = 0
        {"nm_id": 103, "date": date(2026, 7, 2), "order_count": 1},
    ]
    sales_df = pd.DataFrame(sales_data)

    result, numeric_cols = build_stock_all_display_dataframe(
        product_df,
        level="По товарам",
        snapshot_date=snapshot_date,
        sales_df=sales_df
    )

    # Товар 101
    row_101 = result[result["Артикул WB"] == 101].iloc[0]
    assert row_101["Скорость продаж за позавчера"] == 2
    assert row_101["Скорость продаж за прошедшую неделю"] == 1.0
    # Прогноз позавчера: 14 / 2 = 7.0
    assert row_101["Прогноз остатков по скорости позавчера"] == 7.0
    # Прогноз неделя: 14 / 1.0 = 14.0
    assert row_101["Прогноз остатков по скорости недели"] == 14.0

    # Товар 102
    row_102 = result[result["Артикул WB"] == 102].iloc[0]
    assert pd.isna(row_102["Скорость продаж за позавчера"])
    assert row_102["Скорость продаж за прошедшую неделю"] == 0.0
    # Прогнозы должны быть null (позавчера - нет скорости, неделя - скорость 0)
    assert pd.isna(row_102["Прогноз остатков по скорости позавчера"])
    assert pd.isna(row_102["Прогноз остатков по скорости недели"])

    # Товар 103
    row_103 = result[result["Артикул WB"] == 103].iloc[0]
    assert row_103["Скорость продаж за позавчера"] == 1
    # Прогноз позавчера: 0 / 1 = 0.0
    assert row_103["Прогноз остатков по скорости позавчера"] == 0.0


def test_build_stock_all_display_dataframe_band_mode_adds_missing_optional_columns_without_crash() -> None:
    product_df = pd.DataFrame(
        [
            {
                "query_group": "women_underwear",
                "band_name": "Трусы женские",
                "nm_id": 101,
                "wb_stock_qty": 5,
                "wb_in_way_to_client": 1,
                "wb_in_way_from_client": 0,
                "wb_total_in_contour": 6,
                "one_c_stock_qty": 4,
                "wb_vs_one_c_diff": 1,
            }
        ]
    )

    result, numeric_cols = build_stock_all_display_dataframe(product_df, level="По бандам")

    assert result.columns.tolist() == [
        "Банда",
        "Товаров",
        "Остаток WB на складах",
        "В пути к клиенту",
        "Возвраты в пути",
        "Итого в контуре WB",
        "Остаток 1С",
        "Поставки на WB",
    ]
    assert result.iloc[0]["Банда"] == "Трусы женские"
    assert result.iloc[0]["Товаров"] == 1
    assert result.iloc[0]["Остаток 1С"] == 4
    assert "Разница WB - 1С" not in result.columns
    assert "Разница WB - 1С" not in numeric_cols
    assert "Товаров" in numeric_cols


def test_build_stock_warehouse_history_summary_metrics_counts_row_statuses() -> None:
    history = pd.DataFrame(
        [
            {
                "snapshot_date": pd.Timestamp("2026-06-18").date(),
                "nm_id": 101,
                "warehouse_name": "Коледино",
                "stock_status": "IN_STOCK",
                "anomaly_type": "MIXED_ZERO_AND_STOCK",
            },
            {
                "snapshot_date": pd.Timestamp("2026-06-19").date(),
                "nm_id": 101,
                "warehouse_name": "Коледино",
                "stock_status": "ZERO_STOCK",
                "anomaly_type": "MIXED_ZERO_AND_STOCK",
            },
            {
                "snapshot_date": pd.Timestamp("2026-06-18").date(),
                "nm_id": 202,
                "warehouse_name": "Коледино",
                "stock_status": "NO_DATA",
                "anomaly_type": "ALWAYS_NO_DATA",
            },
        ]
    )

    metrics = build_stock_warehouse_history_summary_metrics(history)

    assert metrics == {
        "dates_count": 2,
        "products_count": 2,
        "warehouses_count": 1,
        "in_stock_rows": 1,
        "zero_rows": 1,
        "no_data_rows": 1,
        "anomalies_count": 2,
    }


def test_build_stock_warehouse_history_pivot_table_keeps_zero_and_missing_distinct() -> None:
    history = pd.DataFrame(
        [
            {
                "snapshot_date": pd.Timestamp("2026-06-18").date(),
                "nm_id": 101,
                "supplier_article": "sku-101",
                "product_name": "Товар 101",
                "warehouse_name": "Коледино",
                "stock_qty": 4,
                "stock_status": "IN_STOCK",
            },
            {
                "snapshot_date": pd.Timestamp("2026-06-19").date(),
                "nm_id": 101,
                "supplier_article": "sku-101",
                "product_name": "Товар 101",
                "warehouse_name": "Коледино",
                "stock_qty": 0,
                "stock_status": "ZERO_STOCK",
            },
            {
                "snapshot_date": pd.Timestamp("2026-06-18").date(),
                "nm_id": 202,
                "supplier_article": "sku-202",
                "product_name": "Товар 202",
                "warehouse_name": "Коледино",
                "stock_qty": pd.NA,
                "stock_status": "NO_DATA",
            },
        ]
    )

    pivot = build_stock_warehouse_history_pivot_table(history)

    assert pivot.loc[0, "2026-06-18"] == 4
    assert pivot.loc[0, "2026-06-19"] == 0
    assert pd.isna(pivot.loc[1, "2026-06-18"])


def test_should_render_stock_warehouse_history_pivot_blocks_oversized_tables() -> None:
    pivot = pd.DataFrame({"nm_id": range(400), **{f"2026-06-{day:02d}": [1] * 400 for day in range(1, 31)}})

    assert should_render_stock_warehouse_history_pivot(pivot, max_cells=10_000) is False
    assert should_render_stock_warehouse_history_pivot(pivot, max_cells=20_000) is True


def test_build_stock_warehouse_history_ivan_check_table_contains_only_problem_pairs() -> None:
    history = pd.DataFrame(
        [
            {
                "snapshot_date": pd.Timestamp("2026-06-18").date(),
                "nm_id": 101,
                "supplier_article": "sku-101",
                "product_name": "Товар 101",
                "warehouse_name": "Коледино",
                "stock_status": "NO_DATA",
                "anomaly_type": "ALWAYS_NO_DATA",
            },
            {
                "snapshot_date": pd.Timestamp("2026-06-19").date(),
                "nm_id": 101,
                "supplier_article": "sku-101",
                "product_name": "Товар 101",
                "warehouse_name": "Коледино",
                "stock_status": "NO_DATA",
                "anomaly_type": "ALWAYS_NO_DATA",
            },
            {
                "snapshot_date": pd.Timestamp("2026-06-18").date(),
                "nm_id": 202,
                "supplier_article": "sku-202",
                "product_name": "Товар 202",
                "warehouse_name": "Коледино",
                "stock_status": "IN_STOCK",
                "anomaly_type": "ALWAYS_IN_STOCK",
            },
            {
                "snapshot_date": pd.Timestamp("2026-06-19").date(),
                "nm_id": 202,
                "supplier_article": "sku-202",
                "product_name": "Товар 202",
                "warehouse_name": "Коледино",
                "stock_status": "IN_STOCK",
                "anomaly_type": "ALWAYS_IN_STOCK",
            },
        ]
    )

    ivan_check = build_stock_warehouse_history_ivan_check_table(history)

    assert ivan_check["nm_id"].tolist() == [101]
    assert ivan_check.loc[0, "days_with_stock"] == 0
    assert ivan_check.loc[0, "days_zero"] == 0
    assert ivan_check.loc[0, "days_no_data"] == 2
    assert ivan_check.loc[0, "anomaly_type"] == "ALWAYS_NO_DATA"


def test_build_stock_all_size_level_matches_by_barcode_and_calculates_diff() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-07-04",
                "nm_id": 197330807,
                "chrt_id": 101,
                "warehouse_id": 1,
                "warehouse_name": "Р’Р»Р°РґРёРјРёСЂ WB",
                "stock_qty": 4,
            },
            {
                "snapshot_date": "2026-07-04",
                "nm_id": 197330807,
                "chrt_id": 101,
                "warehouse_id": 2,
                "warehouse_name": "РўСѓР»Р°",
                "stock_qty": 3,
            },
            {
                "snapshot_date": "2026-07-04",
                "nm_id": 197330807,
                "chrt_id": 102,
                "warehouse_id": 1,
                "warehouse_name": "Р’Р»Р°РґРёРјРёСЂ WB",
                "stock_qty": 5,
            },
        ]
    )
    settings_df = pd.DataFrame(
        [
            {
                "nm_id": 197330807,
                "supplier_article": "BlackWOM5",
                "title": "РўСЂСѓСЃС‹ РєРѕРјРїР»РµРєС‚",
                "query_group": "women_underwear",
            }
        ]
    )
    one_c_size_df = pd.DataFrame(
        [
            {
                "stock_date": "2026-07-04",
                "nm_id": 197330807,
                "size_name": "M",
                "barcode": "111",
                "quantity": 6,
            },
            {
                "stock_date": "2026-07-04",
                "nm_id": 197330807,
                "size_name": "L",
                "barcode": "222",
                "quantity": 2,
            },
        ]
    )
    product_size_df = pd.DataFrame(
        [
            {"nm_id": 197330807, "chrt_id": 101, "barcode": "111", "size_name": "M", "tech_size": "42-44"},
            {"nm_id": 197330807, "chrt_id": 102, "barcode": "222", "size_name": "L", "tech_size": "46-48"},
        ]
    )

    result = build_stock_all_size_level(
        snapshot_df,
        settings_df,
        pd.Timestamp("2026-07-04").date(),
        one_c_size_df=one_c_size_df,
        product_size_df=product_size_df,
    )

    assert result["barcode"].tolist() == ["222", "111"]
    row_l = result.loc[result["barcode"] == "222"].iloc[0]
    row_m = result.loc[result["barcode"] == "111"].iloc[0]

    assert row_l["wb_size_stock_qty"] == 5
    assert row_l["one_c_size_stock_qty"] == 2
    assert row_l["wb_vs_one_c_size_diff"] == 3
    assert row_l["match_source"] == "barcode"

    assert row_m["wb_size_stock_qty"] == 7
    assert row_m["one_c_size_stock_qty"] == 6
    assert row_m["wb_vs_one_c_size_diff"] == 1
    assert row_m["vendor_code"] == "BlackWOM5"
    assert row_m["band_name"] == "Трусы женские"


def test_build_stock_all_size_level_falls_back_to_size_name_and_keeps_unmatched_wb_rows() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-07-04",
                "nm_id": 91470767,
                "chrt_id": 501,
                "warehouse_id": 1,
                "warehouse_name": "Р’Р»Р°РґРёРјРёСЂ WB",
                "stock_qty": 8,
            },
            {
                "snapshot_date": "2026-07-04",
                "nm_id": 91470767,
                "chrt_id": 502,
                "warehouse_id": 1,
                "warehouse_name": "Р’Р»Р°РґРёРјРёСЂ WB",
                "stock_qty": 3,
            },
        ]
    )
    settings_df = pd.DataFrame(
        [
            {
                "nm_id": 91470767,
                "supplier_article": "avokadogirl",
                "title": "РўСЂСѓСЃС‹ РґРµС‚СЃРєРёРµ",
                "query_group": "kids_underwear",
            }
        ]
    )
    one_c_size_df = pd.DataFrame(
        [
            {
                "stock_date": "2026-07-04",
                "nm_id": 91470767,
                "size_name": "92",
                "barcode": "",
                "quantity": 5,
            }
        ]
    )
    product_size_df = pd.DataFrame(
        [
            {"nm_id": 91470767, "chrt_id": 501, "barcode": "9001", "size_name": "92", "tech_size": "86-92"},
        ]
    )

    result = build_stock_all_size_level(
        snapshot_df,
        settings_df,
        pd.Timestamp("2026-07-04").date(),
        one_c_size_df=one_c_size_df,
        product_size_df=product_size_df,
    )

    assert len(result) == 2

    matched_row = result.loc[result["chrt_id"] == 501].iloc[0]
    wb_only_row = result.loc[result["chrt_id"] == 502].iloc[0]

    assert matched_row["match_source"] == "size_name"
    assert matched_row["wb_size_stock_qty"] == 8
    assert matched_row["one_c_size_stock_qty"] == 5
    assert matched_row["barcode"] == "9001"

    assert wb_only_row["match_source"] == "wb_only"
    assert wb_only_row["wb_size_stock_qty"] == 3
    assert pd.isna(wb_only_row["one_c_size_stock_qty"])


def test_build_stock_all_size_display_dataframe_adds_sales_speed_and_forecasts() -> None:
    snapshot_date = pd.Timestamp("2026-07-05").date()
    size_df = pd.DataFrame(
        [
            {
                "band_name": "Трусы женские",
                "nm_id": 197330807,
                "vendor_code": "BlackWOM5",
                "title": "Трусы набор",
                "size_name": "M",
                "barcode": "BC-M",
                "tech_size": "M",
                "wb_size_stock_qty": 8,
                "one_c_size_stock_qty": 2,
            },
            {
                "band_name": "Трусы женские",
                "nm_id": 197330807,
                "vendor_code": "BlackWOM5",
                "title": "Трусы набор",
                "size_name": "S",
                "barcode": pd.NA,
                "tech_size": "S",
                "wb_size_stock_qty": 4,
                "one_c_size_stock_qty": 1,
            },
        ]
    )
    size_sales_df = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-07-03").date(),
                "nm_id": 197330807,
                "barcode": "BC-M",
                "chrt_id": 101,
                "tech_size": "M",
                "order_count": 4,
                "cancel_count": 0,
            },
            {
                "date": pd.Timestamp("2026-07-01").date(),
                "nm_id": 197330807,
                "barcode": "BC-M",
                "chrt_id": 101,
                "tech_size": "M",
                "order_count": 10,
                "cancel_count": 0,
            },
            {
                "date": pd.Timestamp("2026-07-03").date(),
                "nm_id": 197330807,
                "barcode": "BC-S-UNIQUE",
                "chrt_id": 102,
                "tech_size": "S",
                "order_count": 3,
                "cancel_count": 0,
            },
            {
                "date": pd.Timestamp("2026-07-02").date(),
                "nm_id": 197330807,
                "barcode": "BC-S-UNIQUE",
                "chrt_id": 102,
                "tech_size": "S",
                "order_count": 4,
                "cancel_count": 0,
            },
        ]
    )

    display_df, numeric_cols = build_stock_all_size_display_dataframe(
        size_df,
        snapshot_date=snapshot_date,
        size_sales_df=size_sales_df,
    )

    assert "Скорость продаж за позавчера" in display_df.columns
    assert "Скорость продаж за прошедшую неделю" in display_df.columns
    assert "Прогноз остатков по скорости позавчера" in display_df.columns
    assert "Прогноз остатков по скорости недели" in display_df.columns
    assert "Остаток WB по размеру" in numeric_cols
    assert "Скорость продаж за позавчера" in numeric_cols

    row_m = display_df.loc[display_df["Размер"] == "M"].iloc[0]
    assert row_m["Скорость продаж за позавчера"] == 4
    assert row_m["Скорость продаж за прошедшую неделю"] == 2
    assert row_m["Прогноз остатков по скорости позавчера"] == 2.5
    assert row_m["Прогноз остатков по скорости недели"] == 5

    row_s = display_df.loc[display_df["Размер"] == "S"].iloc[0]
    assert row_s["Скорость продаж за позавчера"] == 3
    assert row_s["Скорость продаж за прошедшую неделю"] == 1
    assert row_s["Прогноз остатков по скорости позавчера"] == 5 / 3
    assert row_s["Прогноз остатков по скорости недели"] == 5


def test_build_stock_all_size_display_dataframe_does_not_use_ambiguous_tech_size_fallback() -> None:
    snapshot_date = pd.Timestamp("2026-07-05").date()
    size_df = pd.DataFrame(
        [
            {
                "band_name": "Трусы женские",
                "nm_id": 197330807,
                "vendor_code": "BlackWOM5",
                "title": "Трусы набор",
                "size_name": "S",
                "barcode": pd.NA,
                "tech_size": "S",
                "wb_size_stock_qty": 4,
                "one_c_size_stock_qty": 1,
            },
        ]
    )
    size_sales_df = pd.DataFrame(
        [
            {
                "date": pd.Timestamp("2026-07-03").date(),
                "nm_id": 197330807,
                "barcode": "BC-S-1",
                "chrt_id": 102,
                "tech_size": "S",
                "order_count": 3,
                "cancel_count": 0,
            },
            {
                "date": pd.Timestamp("2026-07-03").date(),
                "nm_id": 197330807,
                "barcode": "BC-S-2",
                "chrt_id": 103,
                "tech_size": "S",
                "order_count": 2,
                "cancel_count": 0,
            },
        ]
    )

    display_df, _ = build_stock_all_size_display_dataframe(
        size_df,
        snapshot_date=snapshot_date,
        size_sales_df=size_sales_df,
    )

    row = display_df.iloc[0]
    assert pd.isna(row["Скорость продаж за позавчера"])
    assert pd.isna(row["Скорость продаж за прошедшую неделю"])
    assert pd.isna(row["Прогноз остатков по скорости позавчера"])
    assert pd.isna(row["Прогноз остатков по скорости недели"])


def test_build_stock_all_size_display_dataframe_uses_russian_columns() -> None:
    size_df = pd.DataFrame(
        [
            {
                "band_name": "РўСЂСѓСЃС‹ Р¶РµРЅСЃРєРёРµ",
                "nm_id": 197330807,
                "vendor_code": "BlackWOM5",
                "title": "РўСЂСѓСЃС‹ РєРѕРјРїР»РµРєС‚",
                "size_name": "M",
                "barcode": "111",
                "wb_size_stock_qty": 7,
                "one_c_size_stock_qty": 6,
                "wb_vs_one_c_size_diff": 1,
            }
        ]
    )

    result, numeric_cols = build_stock_all_size_display_dataframe(size_df)

    assert result.columns.tolist() == [
        "Банда",
        "Артикул WB",
        "Артикул продавца",
        "Название",
        "Размер",
        "Баркод",
        "Остаток WB по размеру",
        "Остаток 1С по размеру",
        "Скорость продаж за позавчера",
        "Скорость продаж за прошедшую неделю",
        "Прогноз остатков по скорости позавчера",
        "Прогноз остатков по скорости недели",
    ]
    assert result.iloc[0]["Размер"] == "M"
    assert result.iloc[0]["Баркод"] == "111"
    assert "Остаток WB по размеру" in numeric_cols
    assert "Разница WB - 1С по размеру" not in numeric_cols


def test_stock_speed_charts_calculations_and_aggregations() -> None:
    from datetime import date
    from app_streamlit import (
        prepare_stock_speed_charts_dataframe,
        aggregate_stock_charts_by_article,
        aggregate_stock_charts_by_band,
        aggregate_stock_charts_by_cabinet
    )
    
    # 1. Mock Data
    snapshot_df = pd.DataFrame([
        {"snapshot_date": date(2026, 7, 3), "nm_id": 101, "stock_qty": 10},
        {"snapshot_date": date(2026, 7, 4), "nm_id": 101, "stock_qty": 12},
        {"snapshot_date": date(2026, 7, 4), "nm_id": 102, "stock_qty": 5},
    ])
    
    one_c_df = pd.DataFrame([
        {"snapshot_date": date(2026, 7, 3), "nm_id": 101, "one_c_stock_qty": 4},
        {"snapshot_date": date(2026, 7, 4), "nm_id": 101, "one_c_stock_qty": pd.NA},
    ])
    
    sales_df = pd.DataFrame([
        {"nm_id": 101, "date": date(2026, 7, 2), "order_count": 2},
        {"nm_id": 101, "date": date(2026, 7, 3), "order_count": 1},
        {"nm_id": 102, "date": date(2026, 7, 2), "order_count": 0},
    ])
    
    settings_qg_df = pd.DataFrame([
        {"nm_id": 101, "query_group": "women_underwear", "supplier_article": "art-101", "title": "Товар 101"},
        {"nm_id": 102, "query_group": "women_underwear", "supplier_article": "art-102", "title": "Товар 102"},
    ])
    
    # 2. prepare dataframe
    df_all = prepare_stock_speed_charts_dataframe(
        snapshot_df=snapshot_df,
        one_c_df=one_c_df,
        sales_df=sales_df,
        settings_qg_df=settings_qg_df,
        min_date=date(2026, 7, 3),
        max_date=date(2026, 7, 4)
    )
    
    assert not df_all.empty
    
    # Проверяем total_stock
    row_101_3 = df_all[(df_all["nm_id"] == 101) & (df_all["date"] == date(2026, 7, 3))].iloc[0]
    assert row_101_3["total_stock"] == 14
    
    row_101_4 = df_all[(df_all["nm_id"] == 101) & (df_all["date"] == date(2026, 7, 4))].iloc[0]
    assert row_101_4["total_stock"] == 16
    
    # Проверяем скорость позавчера для 2026-07-04
    assert row_101_4["sales_speed_y2"] == 2
    
    # 3. Test aggregate_stock_charts_by_article
    selected_label = "art-101 | 101 | Товар 101"
    df_art = aggregate_stock_charts_by_article(df_all, "sales_speed_y2", selected_label)
    
    art_row_4 = df_art[df_art["date"] == date(2026, 7, 4)].iloc[0]
    assert art_row_4["sales_speed"] == 2
    assert abs(art_row_4["forecast_months"] - (16.0 / 60.0)) < 1e-5
    
    # 4. Test aggregate_stock_charts_by_band
    df_band = aggregate_stock_charts_by_band(df_all, "sales_speed_y2")
    band_row_4 = df_band[(df_band["date"] == date(2026, 7, 4)) & (df_band["band_name"] == "Трусы женские")].iloc[0]
    assert band_row_4["sales_speed"] == 2
    assert abs(band_row_4["forecast_months"] - (21.0 / 60.0)) < 1e-5
    
    # 5. Test aggregate_stock_charts_by_cabinet
    df_cab = aggregate_stock_charts_by_cabinet(df_all, "sales_speed_y2")
    cab_row_4 = df_cab[df_cab["date"] == date(2026, 7, 4)].iloc[0]
    assert cab_row_4["sales_speed"] == 2
    assert abs(cab_row_4["forecast_months"] - (21.0 / 60.0)) < 1e-5
    
    # 6. Test zero division safety
    df_art_102 = aggregate_stock_charts_by_article(df_all, "sales_speed_y2", "art-102 | 102 | Товар 102")
    art_102_row_4 = df_art_102[df_art_102["date"] == date(2026, 7, 4)].iloc[0]
    assert art_102_row_4["sales_speed"] == 0
    assert pd.isna(art_102_row_4["forecast_months"])


def test_stock_speed_charts_clip_negative_one_c_stock_to_zero() -> None:
    from datetime import date
    from app_streamlit import prepare_stock_speed_charts_dataframe

    snapshot_df = pd.DataFrame([
        {"snapshot_date": date(2026, 7, 4), "nm_id": 101, "stock_qty": 12},
    ])
    one_c_df = pd.DataFrame([
        {"snapshot_date": date(2026, 7, 4), "nm_id": 101, "one_c_stock_qty": -5},
    ])
    sales_df = pd.DataFrame([
        {"nm_id": 101, "date": date(2026, 7, 2), "order_count": 2},
    ])
    settings_qg_df = pd.DataFrame([
        {"nm_id": 101, "query_group": "women_underwear", "supplier_article": "art-101", "title": "Товар 101"},
    ])

    df_all = prepare_stock_speed_charts_dataframe(
        snapshot_df=snapshot_df,
        one_c_df=one_c_df,
        sales_df=sales_df,
        settings_qg_df=settings_qg_df,
        min_date=date(2026, 7, 4),
        max_date=date(2026, 7, 4),
    )

    row = df_all[(df_all["nm_id"] == 101) & (df_all["date"] == date(2026, 7, 4))].iloc[0]
    assert row["total_stock"] == 12


def test_build_stock_all_product_level_clips_negative_one_c_stock_to_zero() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-07-04",
                "nm_id": 101,
                "chrt_id": 1,
                "warehouse_id": 1,
                "warehouse_name": "Владимир WB",
                "stock_qty": 8,
                "in_way_to_client": 1,
                "in_way_from_client": 0,
            }
        ]
    )
    settings_df = pd.DataFrame(
        [{"nm_id": 101, "supplier_article": "art-101", "title": "Товар 101", "query_group": "women_underwear"}]
    )
    one_c_df = pd.DataFrame(
        [{"stock_date": "2026-07-04", "nm_id": 101, "ivan_stock_qty": -3}]
    )

    result = build_stock_all_product_level(
        snapshot_df,
        settings_df,
        pd.Timestamp("2026-07-04").date(),
        one_c_stock_df=one_c_df,
    )

    row = result.iloc[0]
    assert row["one_c_stock_qty"] == 0
    assert row["wb_vs_one_c_diff"] == 8


def test_build_stock_all_band_level_clips_negative_one_c_stock_to_zero() -> None:
    product_df = pd.DataFrame(
        [
            {
                "query_group": "women_underwear",
                "band_name": "Трусы женские",
                "nm_id": 101,
                "wb_stock_qty": 10,
                "wb_in_way_to_client": 0,
                "wb_in_way_from_client": 0,
                "wb_total_in_contour": 10,
                "one_c_stock_qty": -4,
            }
        ]
    )

    result = build_stock_all_band_level(product_df)

    row = result.iloc[0]
    assert row["one_c_stock_qty"] == 0
    assert row["wb_vs_one_c_diff"] == 10


def test_build_stock_all_size_level_clips_negative_one_c_stock_to_zero() -> None:
    snapshot_df = pd.DataFrame(
        [
            {
                "snapshot_date": "2026-07-04",
                "nm_id": 101,
                "chrt_id": 1,
                "warehouse_id": 1,
                "warehouse_name": "Владимир WB",
                "stock_qty": 5,
            }
        ]
    )
    settings_df = pd.DataFrame(
        [{"nm_id": 101, "supplier_article": "art-101", "title": "Товар 101", "query_group": "women_underwear"}]
    )
    one_c_size_df = pd.DataFrame(
        [{"stock_date": "2026-07-04", "nm_id": 101, "size_name": "M", "barcode": "111", "quantity": -2}]
    )
    product_size_df = pd.DataFrame(
        [{"nm_id": 101, "chrt_id": 1, "barcode": "111", "size_name": "M", "tech_size": "42-44"}]
    )

    result = build_stock_all_size_level(
        snapshot_df,
        settings_df,
        pd.Timestamp("2026-07-04").date(),
        one_c_size_df=one_c_size_df,
        product_size_df=product_size_df,
    )

    row = result.iloc[0]
    assert row["one_c_size_stock_qty"] == 0
    assert row["wb_vs_one_c_size_diff"] == 5


def test_render_charts_tab_contains_new_tab() -> None:
    from unittest.mock import patch, MagicMock
    import pandas as pd
    from app_streamlit import render_charts_tab
    
    filtered_mock = pd.DataFrame({"report_date": []})
    
    with patch("streamlit.tabs") as mock_tabs:
        mock_tabs.return_value = (MagicMock(), MagicMock(), MagicMock())
        
        with patch("streamlit.subheader"), \
             patch("streamlit.selectbox"), \
             patch("streamlit.radio"), \
             patch("streamlit.info"), \
             patch("streamlit.warning"), \
             patch("streamlit.markdown"), \
             patch("app_streamlit.render_efficiency_charts"), \
             patch("app_streamlit.render_vvbromo_charts"), \
             patch("app_streamlit.render_stock_speed_charts"):
             
            render_charts_tab(filtered_mock, None, {})
            
            mock_tabs.assert_called_once()
            args, kwargs = mock_tabs.call_args
            assert "Остатки и скорость продаж" in args[0]
