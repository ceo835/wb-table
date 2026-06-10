from src.sheets.schema_definitions import (
    PROCESSED_TABLE_SCHEMAS,
    REQUIRED_PROCESSED_TABLE_NAMES,
    REQUIRED_USER_SHEET_NAMES,
    USER_SHEET_SCHEMAS,
)


def test_required_user_sheets_present():
    assert REQUIRED_USER_SHEET_NAMES == [
        "README",
        "Coverage",
        "Backlog",
        "Validation_v1",
        "ИТОГО",
        "ИТОГО_FULL",
        "ИТОГО_v1",
        "Воронка на день",
        "РасходРК",
        "РК стата",
        "ВБро",
        "Точка вх",
        "Локализация",
        "Сравнение карточек",
        "Поисковые запросы",
        "Остатки",
    ]
    assert set(USER_SHEET_SCHEMAS) == set(REQUIRED_USER_SHEET_NAMES)


def test_required_processed_tables_present():
    assert REQUIRED_PROCESSED_TABLE_NAMES == [
        "dim_product",
        "fact_funnel_day",
        "fact_stock_snapshot",
        "fact_stock_day",
        "fact_ad_cost_event",
        "fact_ad_cost_day",
        "fact_ad_campaign_day",
        "fact_ad_campaign_nm_day",
        "fact_search_query_metric",
        "fact_profit_day",
        "fact_entry_point_day",
        "entry_points_wide",
        "fact_localization_region_day",
        "fact_localization_region_summary_day",
        "fact_card_comparison_metric",
        "fact_mpstat_item_day",
    ]
    assert set(PROCESSED_TABLE_SCHEMAS) == set(REQUIRED_PROCESSED_TABLE_NAMES)


def test_processed_tables_have_service_fields():
    for schema in PROCESSED_TABLE_SCHEMAS.values():
        assert "data_status" in schema.columns
        assert "source_status" in schema.columns
        assert "loaded_at" in schema.columns


def test_primary_keys_match_spec():
    expected = {
        "dim_product": ("nm_id",),
        "fact_funnel_day": ("date", "nm_id"),
        "fact_stock_snapshot": ("snapshot_date", "nm_id"),
        "fact_ad_cost_event": ("date", "advertId", "writeoff_datetime", "document_number"),
        "fact_ad_cost_day": ("date", "advertId", "nm_id"),
        "fact_ad_campaign_day": ("date", "advertId", "row_type"),
        "fact_ad_campaign_nm_day": ("date", "advertId", "row_type", "conversion_type", "nm_id"),
        "fact_search_query_metric": ("period_start", "period_end", "nm_id", "search_query"),
        "fact_profit_day": ("date", "nm_id"),
        "fact_entry_point_day": ("date", "nm_id", "section", "entry_point"),
        "fact_localization_region_day": ("date", "nm_id", "region"),
        "fact_localization_region_summary_day": ("date", "region"),
        "fact_card_comparison_metric": (
            "period_start",
            "period_end",
            "base_nm_id",
            "compared_nm_id",
            "metric_name",
        ),
    }
    for name, primary_key in expected.items():
        assert PROCESSED_TABLE_SCHEMAS[name].primary_key == primary_key


def test_key_user_sheet_headers_match_spec():
    assert USER_SHEET_SCHEMAS["Validation_v1"].columns == (
        "sheet_name",
        "date",
        "nm_id",
        "impressions",
        "card_clicks",
        "ctr",
        "reason",
    )
    assert USER_SHEET_SCHEMAS["РК стата"].columns == (
        "Дата",
        "ID кампании",
        "Название кампании",
        "Тип строки",
        "Тип конверсии",
        "Номенклатура",
        "Название товара",
        "Затраты, ₽",
        "Выручка, ₽",
        "Показы",
        "Клики",
        "Добавления в корзину",
        "Заказы",
        "Заказанные товары, шт.",
        "Отмены",
        "Средняя позиция",
        "CTR, %",
        "CPC, ₽",
        "CPM, ₽",
        "CR, %",
        "ROI, %",
        "data_status",
        "source_status",
        "loaded_at",
    )
    assert USER_SHEET_SCHEMAS["РасходРК"].columns == (
        "ID кампании",
        "Кампания",
        "Раздел",
        "Дата списания",
        "Источник списания",
        "Сумма",
        "Номер документа",
        "nm_id",
        "nm_id_parse_status",
        "campaign_type",
        "data_status",
        "source_status",
        "loaded_at",
    )
    assert USER_SHEET_SCHEMAS["ВБро"].columns == (
        "Дата",
        "Артикул ВБ",
        "Артикул продавца",
        "Продажи (органические)",
        "Операционная прибыль",
        "Операционная прибыль на единицу",
        "data_status",
        "source_status",
        "loaded_at",
    )


def test_search_sheet_has_required_columns():
    columns = USER_SHEET_SCHEMAS["Поисковые запросы"].columns
    assert "Количество запросов (предыдущий период)" in columns
    assert "Переходы в карточку больше, чем у n% карточек конкурентов, %" in columns
    assert "Положили в корзину больше, чем n% карточек конкурентов, %" in columns
    assert "Заказали больше, чем n% карточек конкурентов, %" in columns
    assert "Минимальная цена со скидкой (по размерам), ₽" in columns
    assert "Максимальная цена со скидкой (по размерам), ₽" in columns
