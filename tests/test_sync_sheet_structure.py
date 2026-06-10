from src.sheets.sync_structure import build_sync_plan


def test_sync_plan_creates_missing_sheets_and_updates_only_headers():
    existing = {
        "README": ["old_header"],
        "Coverage": ["block", "status", "details"],
        "РасходРК": ["ID кампании", "Кампания"],
    }

    plan = build_sync_plan(existing_sheet_headers=existing)

    actions = {(action.sheet_name, action.action): action for action in plan.actions}

    assert ("README", "update_headers") in actions
    assert ("Coverage", "create_sheet") not in actions
    assert ("Coverage", "update_headers") in actions
    assert ("РасходРК", "update_headers") in actions
    assert ("РК стата", "create_sheet") in actions
    assert ("РК стата", "update_headers") in actions
    assert not any(action.action == "clear_sheet" for action in plan.actions)
    assert not any(action.action == "write_mock_rows" for action in plan.actions)


def test_sync_plan_is_noop_when_headers_match():
    existing = {
        "README": ["section", "value", "notes"],
        "Coverage": ["sheet_name", "status", "details"],
        "Backlog": ["block", "status", "reason", "next_step", "priority"],
        "Validation_v1": ["sheet_name", "date", "nm_id", "impressions", "card_clicks", "ctr", "reason"],
        "ИТОГО": ["date", "nm_id", "supplier_article"],
        "ИТОГО_FULL": ["date", "nm_id", "supplier_article"],
        "ИТОГО_v1": [
            "date",
            "nm_id",
            "supplier_article",
            "title",
            "subject",
            "brand",
            "impressions",
            "card_clicks",
            "ctr",
            "cartCount",
            "orderCount",
            "orderSum",
            "buyoutCount",
            "buyoutSum",
            "buyoutPercent",
            "addToCartConversion",
            "cartToOrderConversion",
            "addToWishlistCount",
            "ad_views",
            "ad_clicks",
            "ad_ctr",
            "ad_cpc",
            "ad_orders",
            "ad_atbs",
            "ad_spend",
            "ad_revenue",
            "cost_per_cart",
            "cpm",
            "cpo",
            "search_queries_count",
            "avg_position",
            "visibility",
            "search_clicks",
            "search_cart",
            "search_orders",
            "current_stockCount",
            "current_stockSum",
            "stock_snapshot_date",
            "data_status",
            "source_status",
            "loaded_at",
        ],
        "Воронка на день": ["Артикул продавца", "Артикул WB", "Название"],
        "РасходРК": [
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
        ],
        "РК стата": [
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
        ],
        "ВБро": [
            "Дата",
            "Артикул ВБ",
            "Артикул продавца",
            "Продажи (органические)",
            "Операционная прибыль",
            "Операционная прибыль на единицу",
            "data_status",
            "source_status",
            "loaded_at",
        ],
        "Точка вх": ["date", "nm_id", "section", "entry_point", "metric_name", "metric_value", "data_status", "source_status", "loaded_at"],
        "Локализация": ["date", "nm_id", "region", "metric_name", "metric_value", "data_status", "source_status", "loaded_at"],
        "Сравнение карточек": ["period_start", "period_end", "base_nm_id", "compared_nm_id", "metric_group", "metric_name", "metric_value", "data_status", "source_status", "loaded_at"],
        "Поисковые запросы": ["Артикул продавца", "Артикул WB", "Название"],
        "Остатки": ["snapshot_date", "nm_id", "supplier_article"],
    }

    plan = build_sync_plan(existing_sheet_headers=existing)

    coverage_actions = [action for action in plan.actions if action.sheet_name == "Coverage"]
    assert coverage_actions == []
