from datetime import date

import app_streamlit
import pandas as pd

from src.ad_campaign_efficiency import (
    AD_CAMPAIGN_PERIOD_DAILY,
    AD_CAMPAIGN_PERIOD_WEEKLY,
    AD_CAMPAIGN_SIGNAL_GROWTH,
    AD_CAMPAIGN_SIGNAL_INSUFFICIENT,
    AD_CAMPAIGN_SIGNAL_NEW_ACTIVITY,
    AD_CAMPAIGN_SIGNAL_NO_CHANGE,
    AD_CAMPAIGN_SIGNAL_STOPPED_NEUTRAL,
    build_ad_campaign_efficiency_tables,
    calculate_ad_campaign_efficiency_signal,
    filter_ad_campaign_efficiency_rows,
    resolve_ad_campaign_efficiency_window,
)


def test_build_main_tab_labels_uses_rk_section() -> None:
    labels = app_streamlit.build_main_tab_labels()

    assert labels[2] == "РК"


def test_resolve_ad_campaign_efficiency_window_supports_daily_and_weekly() -> None:
    daily = resolve_ad_campaign_efficiency_window(date(2026, 7, 15), AD_CAMPAIGN_PERIOD_DAILY)
    weekly = resolve_ad_campaign_efficiency_window(date(2026, 7, 15), AD_CAMPAIGN_PERIOD_WEEKLY)

    assert daily["current_start"] == date(2026, 7, 15)
    assert daily["previous_start"] == date(2026, 7, 14)
    assert daily["comparison_label"] == "15.07.2026 против 14.07.2026"
    assert weekly["current_start"] == date(2026, 7, 9)
    assert weekly["current_end"] == date(2026, 7, 15)
    assert weekly["previous_start"] == date(2026, 7, 2)
    assert weekly["previous_end"] == date(2026, 7, 8)


def test_calculate_ad_campaign_efficiency_signal_handles_zero_and_missing_values() -> None:
    missing = calculate_ad_campaign_efficiency_signal(None, 10)
    flat = calculate_ad_campaign_efficiency_signal(0, 0)
    new_activity = calculate_ad_campaign_efficiency_signal(12, 0)

    assert missing["signal_code"] == AD_CAMPAIGN_SIGNAL_INSUFFICIENT
    assert flat["signal_code"] == AD_CAMPAIGN_SIGNAL_NO_CHANGE
    assert flat["change_percent"] == 0.0
    assert new_activity["signal_code"] == AD_CAMPAIGN_SIGNAL_NEW_ACTIVITY
    assert new_activity["change_percent"] is None


def test_build_ad_campaign_efficiency_tables_aggregates_and_marks_stopped_campaigns_neutral() -> None:
    campaign_stats_df = pd.DataFrame(
        [
            {"date": date(2026, 7, 14), "advert_id": 501, "campaign_name": "Campaign A", "row_type": "Итог кампании", "ad_views": 100, "ad_atbs": 10},
            {"date": date(2026, 7, 15), "advert_id": 501, "campaign_name": "Campaign A", "row_type": "Итог кампании", "ad_views": 130, "ad_atbs": 8},
            {"date": date(2026, 7, 14), "advert_id": 502, "campaign_name": "Campaign B", "row_type": "Итог кампании", "ad_views": 80, "ad_atbs": 4},
            {"date": date(2026, 7, 15), "advert_id": 502, "campaign_name": "Campaign B", "row_type": "Итог кампании", "ad_views": 0, "ad_atbs": 0},
        ]
    )
    article_stats_df = pd.DataFrame(
        [
            {"date": date(2026, 7, 14), "advert_id": 501, "campaign_name": "Campaign A", "row_type": "Товар", "nm_id": 101, "product_name": "Product A", "ad_views": 60, "ad_atbs": 6},
            {"date": date(2026, 7, 15), "advert_id": 501, "campaign_name": "Campaign A", "row_type": "Товар", "nm_id": 101, "product_name": "Product A", "ad_views": 90, "ad_atbs": 7},
            {"date": date(2026, 7, 14), "advert_id": 502, "campaign_name": "Campaign B", "row_type": "Товар", "nm_id": 101, "product_name": "Product A", "ad_views": 20, "ad_atbs": 2},
            {"date": date(2026, 7, 15), "advert_id": 502, "campaign_name": "Campaign B", "row_type": "Товар", "nm_id": 101, "product_name": "Product A", "ad_views": 10, "ad_atbs": 1},
        ]
    )
    campaign_meta_df = pd.DataFrame(
        [
            {"advert_id": 501, "campaign_name": "Campaign A", "campaign_type": "auction", "campaign_status": "active"},
            {"advert_id": 502, "campaign_name": "Campaign B", "campaign_type": "auction", "campaign_status": "завершена"},
        ]
    )
    product_df = pd.DataFrame([{"nm_id": 101, "supplier_article": "art-101", "title": "Product A"}])

    campaign_rows, article_rows, _ = build_ad_campaign_efficiency_tables(
        campaign_stats_df,
        article_stats_df,
        campaign_meta_df,
        product_df,
        report_date_value=date(2026, 7, 15),
        period_mode=AD_CAMPAIGN_PERIOD_DAILY,
    )

    growth_row = campaign_rows[(campaign_rows["advert_id"] == 501) & (campaign_rows["metric_name"] == "Показы")].iloc[0]
    stopped_row = campaign_rows[(campaign_rows["advert_id"] == 502) & (campaign_rows["metric_name"] == "Показы")].iloc[0]
    article_row = article_rows[(article_rows["nm_id"] == 101) & (article_rows["metric_name"] == "Показы")].iloc[0]

    assert growth_row["signal_code"] == AD_CAMPAIGN_SIGNAL_GROWTH
    assert growth_row["change_absolute"] == 30.0
    assert round(float(growth_row["change_percent"]), 2) == 30.0
    assert stopped_row["signal_code"] == AD_CAMPAIGN_SIGNAL_STOPPED_NEUTRAL
    assert article_row["current_value"] == 100.0
    assert article_row["previous_value"] == 80.0
    assert round(float(article_row["change_percent"]), 2) == 25.0
    assert article_row["campaign_ids"] == "501, 502"


def test_filter_ad_campaign_efficiency_rows_keeps_only_notable_matches() -> None:
    campaign_stats_df = pd.DataFrame(
        [
            {"date": date(2026, 7, 14), "advert_id": 501, "campaign_name": "Campaign A", "row_type": "Итог кампании", "ad_views": 100, "ad_atbs": 10},
            {"date": date(2026, 7, 15), "advert_id": 501, "campaign_name": "Campaign A", "row_type": "Итог кампании", "ad_views": 130, "ad_atbs": 10},
            {"date": date(2026, 7, 14), "advert_id": 502, "campaign_name": "Campaign B", "row_type": "Итог кампании", "ad_views": 50, "ad_atbs": 5},
            {"date": date(2026, 7, 15), "advert_id": 502, "campaign_name": "Campaign B", "row_type": "Итог кампании", "ad_views": 50, "ad_atbs": 5},
        ]
    )
    campaign_meta_df = pd.DataFrame(
        [
            {"advert_id": 501, "campaign_name": "Campaign A", "campaign_type": "auction", "campaign_status": "active"},
            {"advert_id": 502, "campaign_name": "Campaign B", "campaign_type": "auction", "campaign_status": "active"},
        ]
    )

    campaign_rows, _, _ = build_ad_campaign_efficiency_tables(
        campaign_stats_df,
        pd.DataFrame(),
        campaign_meta_df,
        pd.DataFrame(),
        report_date_value=date(2026, 7, 15),
        period_mode=AD_CAMPAIGN_PERIOD_DAILY,
    )

    filtered = filter_ad_campaign_efficiency_rows(
        campaign_rows,
        metric_filter="Показы",
        direction_filter="Рост",
        only_notable=True,
        search_text="campaign a",
    )

    assert len(filtered) == 1
    assert filtered.iloc[0]["advert_id"] == 501
