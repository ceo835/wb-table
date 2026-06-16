from src.pipelines.mvp_real_run import (
    MvpRealRun,
    _build_suspicious_ctr_validation_rows,
    _format_fullstats_conversion_type_for_sheet,
    _build_ad_section_display_value,
    _classify_campaign_type,
    _detect_nm_id_parse_status,
    _format_writeoff_datetime_for_sheet,
    _map_fullstats_conversion_type,
    _normalize_number_value,
    _parse_nm_id,
    _ratio,
    _sanitize_funnel_ctr_row,
    _first_number,
)


def test_fetch_funnel_uses_runner_nm_ids(monkeypatch):
    run = MvpRealRun()
    run.nm_ids = [111, 222]
    captured = {}

    def fake_request(method, url, headers, json_body=None, params=None):
        captured["json_body"] = json_body
        return "200", {}, ""

    monkeypatch.setattr(run, "_request", fake_request)

    run._fetch_funnel(run.date_from, run.date_to)

    assert captured["json_body"]["nmIds"] == [111, 222]


def test_fetch_search_texts_uses_runner_nm_ids(monkeypatch):
    run = MvpRealRun()
    run.nm_ids = [333, 444]
    captured = {}

    def fake_request(method, url, headers, json_body=None, params=None):
        captured["json_body"] = json_body
        return "200", {}, ""

    monkeypatch.setattr(run, "_request", fake_request)

    run._fetch_search_texts(run.date_to)

    assert captured["json_body"]["nmIds"] == [333, 444]


def test_fetch_search_texts_paginated_merges_pages_and_advances_offset(monkeypatch):
    run = MvpRealRun()
    run.nm_ids = [333, 444]
    offsets: list[int] = []
    first_page_items = [{"nmId": 333, "text": f"q{index}"} for index in range(100)]
    payloads = {
        0: {"data": {"items": first_page_items}},
        100: {"data": {"items": [{"nmId": 444, "text": "q100"}]}},
    }

    def fake_request(method, url, headers, json_body=None, params=None, timeout=90):
        offset = json_body["offset"]
        offsets.append(offset)
        return "200", payloads[offset], ""

    monkeypatch.setattr(run, "_request", fake_request)

    status, payload, error, metadata = run._fetch_search_texts_paginated(run.date_to)

    assert status == "200"
    assert error == ""
    assert offsets == [0, 100]
    assert len(payload["data"]["items"]) == 101
    assert payload["data"]["items"][-1]["text"] == "q100"
    assert metadata["pages_loaded"] == 2


def test_fetch_stocks_paginated_retries_request_error_and_returns_combined_items(monkeypatch):
    run = MvpRealRun()
    run.nm_ids = [111]
    calls: list[int] = []
    state = {"first_retry": True}

    def fake_request(method, url, headers, json_body=None, params=None, timeout=90):
        offset = json_body["offset"]
        calls.append(offset)
        if offset == 0 and state["first_retry"]:
            state["first_retry"] = False
            return "REQUEST_ERROR", None, "temporary"
        if offset == 0:
            return "200", {"data": {"items": [{"nmID": index, "vendorCode": f"A{index}"} for index in range(100)]}}, ""
        return "200", {"data": {"items": []}}, ""

    monkeypatch.setattr(run, "_request", fake_request)
    monkeypatch.setattr("src.pipelines.mvp_real_run.time.sleep", lambda *_args, **_kwargs: None)

    status, payload, error, metadata = run._fetch_stocks_paginated(run.date_to)

    assert status == "200"
    assert error == ""
    assert calls == [0, 0, 100]
    assert len(payload["data"]["items"]) == 100
    assert metadata["http_error_counts"]["REQUEST_ERROR"] == 1


def test_parse_nm_id_from_text():
    assert _parse_nm_id("Кампания ART 197330807 / 2026") == 197330807
    assert _parse_nm_id("no digits here") is None


def test_ratio_handles_zero_and_rounding():
    assert _ratio(5, 20) == 25.0
    assert _ratio(1, 3) == 33.33
    assert _ratio(5, 0) is None


def test_expand_funnel_payload_flattens_nested_history():
    run = MvpRealRun()
    payload = [
        {
            "product": {"nmId": 197330807},
            "history": [
                {"date": "2026-05-31", "orderSum": 10},
                {"date": "2026-06-01", "orderSum": 20},
            ],
        },
        {
            "product": {"nmId": 37320545},
            "history": [
                {"date": "2026-06-01", "orderSum": 30},
            ],
        },
    ]

    items = run._expand_funnel_payload(payload)

    assert [item["orderSum"] for item in items] == [10, 20, 30]


def test_build_funnel_row_uses_open_count_as_card_clicks_without_restoring_fake_impressions():
    run = MvpRealRun()
    row = run._build_funnel_row(
        {
            "date": "2026-06-01",
            "nmId": 197330807,
            "openCount": 100,
            "cartCount": 10,
            "orderCount": 5,
            "orderSum": 500,
            "addToCartConversion": 10,
            "cartToOrderConversion": 50,
        },
        None,
        500,
        None,
        {"nmId": 197330807},
        {
            "product": {"stocks": {}},
            "statistic": {
                "selected": {"wbClub": {}, "stocks": {}},
                "past": {"wbClub": {}, "stocks": {}},
            },
        },
    )

    assert row["impressions"] == ""
    assert row["card_clicks"] == 100
    assert row["ctr"] == ""
    assert row["addToCartConversion"] == 10
    assert row["cartToOrderConversion"] == 50


def test_build_funnel_row_preserves_zero_metrics_in_legacy_mapper():
    run = MvpRealRun()
    row = run._build_funnel_row(
        {
            "date": "2026-06-01",
            "nmId": 197330807,
            "openCount": 0,
            "cartCount": 0,
            "orderCount": 0,
            "orderSum": 0,
            "buyoutCount": 0,
            "buyoutSum": 0,
            "cancelCount": 0,
            "cancelSum": 0,
            "addToCartConversion": 0,
            "cartToOrderConversion": 0,
            "buyoutPercent": 0,
        },
        {
            "date": "2026-05-31",
            "nmId": 197330807,
            "openCount": 0,
            "cartCount": 0,
            "orderCount": 0,
            "orderSum": 0,
            "buyoutCount": 0,
            "buyoutSum": 0,
            "cancelCount": 0,
            "cancelSum": 0,
            "addToCartConversion": 0,
            "cartToOrderConversion": 0,
            "buyoutPercent": 0,
        },
        100,
        100,
        {"nmId": 197330807},
        {
            "product": {"stocks": {"wb": 0, "mp": 0, "balanceSum": 0}},
            "statistic": {
                "selected": {"wbClub": {"orderCount": 0, "buyoutCount": 0, "cancelCount": 0}, "stocks": {}, "localizationPercent": 0},
                "past": {"wbClub": {"orderCount": 0, "buyoutCount": 0, "cancelCount": 0}, "stocks": {}, "localizationPercent": 0},
            },
        },
    )

    assert row["card_clicks"] == 0
    assert row["card_clicks_prev"] == 0
    assert row["cartCount"] == 0
    assert row["cartCount_prev"] == 0
    assert row["orderCount"] == 0
    assert row["orderCount_prev"] == 0
    assert row["orderSum"] == 0
    assert row["orderSum_prev"] == 0
    assert row["buyoutCount"] == 0
    assert row["buyoutSum"] == 0
    assert row["cancelCount"] == 0
    assert row["cancelSum"] == 0
    assert row["addToCartConversion"] == 0
    assert row["cartToOrderConversion"] == 0
    assert row["buyoutPercent"] == 0
    assert row["revenue_share_percent"] == 0
    assert row["wb_stock_qty"] == 0
    assert row["mp_stock_qty"] == 0
    assert row["stock_total_sum"] == 0


def test_first_number_returns_none_for_non_mapping_payload():
    assert _first_number(None, "wb") is None
    assert _first_number([], "wb") is None


def test_sanitize_funnel_ctr_row_blanks_artificial_ctr_and_previous_period():
    row = _sanitize_funnel_ctr_row(
        {
            "date": "2026-06-01",
            "nm_id": 197330807,
            "impressions": "5420.0",
            "card_clicks": "5420.0",
            "ctr": "100.0",
            "impressions_prev": "6194.0",
            "card_clicks_prev": "6194.0",
            "ctr_prev": "100.0",
        }
    )

    assert row["card_clicks"] == ""
    assert row["ctr"] == ""
    assert row["card_clicks_prev"] == ""
    assert row["ctr_prev"] == ""


def test_campaign_type_classification_rules():
    assert _classify_campaign_type("Поиск - бренд") == "Поиск"
    assert _classify_campaign_type("Буст весна") == "Буст"
    assert _classify_campaign_type("Единая ставка") == "Единая ставка"
    assert _classify_campaign_type("Ручная ставка акция") == "Ручная ставка"
    assert _classify_campaign_type("ПОЛКИ акция") == "Полки"
    assert _classify_campaign_type("АРК тест") == "АРК"
    assert _classify_campaign_type("За клик акция") == "За клик"
    assert _classify_campaign_type("За  клик акция") == "За клик"
    assert _classify_campaign_type("Оплата за клик Арт. 123") == "За клик"
    assert _classify_campaign_type("Клик Арт. 123") == "За клик"
    assert _classify_campaign_type("Что-то иное") == "UNKNOWN"


def test_nm_id_parse_status_rules():
    assert _detect_nm_id_parse_status("Арт. 123456", "", 123456, None) == "FROM_CAMPAIGN_NAME"
    assert _detect_nm_id_parse_status("", "section 654321", None, 654321) == "FROM_SECTION"
    assert _detect_nm_id_parse_status("no nm", "none", None, None) == "NOT_FOUND"


def test_ad_section_display_value_rules():
    assert _build_ad_section_display_value("Поиск Арт. 335760311", "9", 335760311, "Поиск") == "335760311"
    assert _build_ad_section_display_value("Буст Арт. 91744473", "9", 91744473, "Буст") == "91744473"
    assert _build_ad_section_display_value("Оплата за клик Арт. 368225219", "9", 368225219, "За клик") == "368225219"
    assert _build_ad_section_display_value("Единая став Арт. 279109013", "9", 279109013, "Единая ставка") == "279109013"
    assert _build_ad_section_display_value("Единая ставка", "9", None, "Единая ставка") == "Единая Ставка"
    assert _build_ad_section_display_value("полки акция", "9", None, "Полки") == "Ручная Ставка"


def test_writeoff_datetime_preserves_time_for_sheet():
    assert _format_writeoff_datetime_for_sheet("2026-05-22T23:59:00") == "2026-05-22 23:59"
    assert _format_writeoff_datetime_for_sheet("2026-05-22 23:59:45") == "2026-05-22 23:59"
    assert _format_writeoff_datetime_for_sheet("2026-05-22") == "2026-05-22"


def test_fullstats_conversion_type_mapping_rules():
    assert _map_fullstats_conversion_type(0) == "ASSOCIATED"
    assert _map_fullstats_conversion_type(1) == "DIRECT"
    assert _map_fullstats_conversion_type(32) == "MULTICARD"
    assert _map_fullstats_conversion_type(64) == "UNKNOWN"


def test_fullstats_conversion_type_display_rules():
    assert _format_fullstats_conversion_type_for_sheet(0, "ASSOCIATED") == "Ассоциированная"
    assert _format_fullstats_conversion_type_for_sheet(1, "DIRECT") == "Прямая"
    assert _format_fullstats_conversion_type_for_sheet(32, "MULTICARD") == "Мультикарточка"
    assert _format_fullstats_conversion_type_for_sheet(64, "UNKNOWN") == "UNKNOWN_CODE_64"
    assert _format_fullstats_conversion_type_for_sheet("", "") == ""


def test_ad_event_row_builds_user_section_separately_from_raw_section():
    run = MvpRealRun()
    row = run._build_ad_event_row(
        {
            "advertId": 1,
            "campName": "Поиск Арт. 335760311",
            "advertType": "9",
            "updTime": "2026-05-22T23:59:00",
            "paymentType": "writeoff",
            "updSum": 123.45,
            "updNum": "DOC-1",
        }
    )

    assert row["section_raw"] == "9"
    assert row["section_display"] == "335760311"
    assert row["writeoff_datetime"] == "2026-05-22T23:59:00"


def test_fullstats_rows_map_conversion_type_to_technical_and_display():
    run = MvpRealRun()
    payload = {
        "data": [
            {
                "advertId": 123,
                "campName": "Campaign",
                "days": [
                    {
                        "date": "2026-06-01",
                        "sum": 10,
                        "sum_price": 20,
                        "views": 30,
                        "clicks": 4,
                        "atbs": 1,
                        "orders": 1,
                        "shks": 1,
                        "canceled": 0,
                        "ctr": 13.33,
                        "cpc": 2.5,
                        "cr": 25,
                        "apps": [
                            {
                                "appType": 0,
                                "nms": [
                                    {
                                        "nmId": 197330807,
                                        "name": "Товар",
                                        "sum": 10,
                                        "sum_price": 20,
                                        "views": 30,
                                        "clicks": 4,
                                        "atbs": 1,
                                        "orders": 1,
                                        "shks": 1,
                                        "canceled": 0,
                                        "ctr": 13.33,
                                        "cpc": 2.5,
                                        "cr": 25,
                                    }
                                ],
                            },
                            {
                                "appType": 64,
                                "nms": [
                                    {
                                        "nmId": 37320545,
                                        "name": "Товар 2",
                                        "sum": 5,
                                        "sum_price": 8,
                                        "views": 9,
                                        "clicks": 1,
                                        "atbs": 0,
                                        "orders": 0,
                                        "shks": 0,
                                        "canceled": 0,
                                        "ctr": 11.11,
                                        "cpc": 5,
                                        "cr": 0,
                                    }
                                ],
                            },
                        ],
                    }
                ],
                "boosterStats": [],
            }
        ]
    }

    campaign_rows, nm_rows = run._build_fullstats_rows(payload, {123: "Campaign"})

    assert campaign_rows[0]["row_type"] == "Итог кампании"
    assert "conversion_type" not in campaign_rows[0]
    assert nm_rows[0]["conversion_type_raw"] == 0
    assert nm_rows[0]["conversion_type"] == "ASSOCIATED"
    assert nm_rows[0]["nm_id"] == 197330807
    assert nm_rows[1]["conversion_type_raw"] == 64
    assert nm_rows[1]["conversion_type"] == "UNKNOWN"


def test_suspicious_ctr_validation_rows_include_high_ctr_only():
    rows = _build_suspicious_ctr_validation_rows(
        [
            {"date": "2026-06-01", "nm_id": 197330807, "impressions": 10, "card_clicks": 8, "ctr": 80},
            {"date": "2026-06-01", "nm_id": 37320545, "impressions": 10, "card_clicks": 10, "ctr": 100},
            {"date": "2026-06-01", "nm_id": 37342770, "impressions": 10, "card_clicks": 3, "ctr": 30},
        ]
    )

    assert len(rows) == 2
    assert rows[0]["sheet_name"] == "Воронка на день"
    assert rows[0]["nm_id"] == "197330807"
    assert rows[0]["reason"] == "suspicious_ctr: CTR >= 80, verify WB source manually"
    assert rows[1]["ctr"] == 100


def test_normalize_number_value_strips_leading_zero():
    assert _normalize_number_value("09.04") == 9.04
    assert _normalize_number_value("9") == 9
    assert _normalize_number_value("abc") == "abc"


def test_itogo_uses_reference_fields_from_funnel_and_stock():
    run = MvpRealRun()
    run.date_from = run.date_to
    funnel_rows = [
        {
            "date": run.date_to.isoformat(),
            "nm_id": 197330807,
            "supplier_article": "BlackWOM5",
            "title": "Трусы комплект",
            "subject": "Трусы",
            "brand": "PALEY",
            "impressions": 100,
            "card_clicks": 50,
            "ctr": 50.0,
            "cartCount": 20,
            "orderCount": 10,
            "orderSum": 1234,
            "buyoutCount": 8,
            "buyoutSum": 1111,
            "buyoutPercent": 80.0,
            "addToCartConversion": 40.0,
            "cartToOrderConversion": 50.0,
            "addToWishlistCount": 2,
        }
    ]
    stock_rows = [
        {
            "nm_id": 197330807,
            "supplier_article": "BlackWOM5",
            "title": "Трусы комплект",
            "subject": "Трусы",
            "brand": "PALEY",
            "stock_total_qty": 7,
            "stock_total_sum": 999,
            "snapshot_date": run.date_to.isoformat(),
        }
    ]
    search_rows = []
    ad_day_rows = [
        {
            "date": run.date_to.isoformat(),
            "nm_id": 197330807,
            "total_spend": 100,
        }
    ]

    rows = run._build_itogo_rows(funnel_rows, stock_rows, search_rows, ad_day_rows)

    assert rows[0]["supplier_article"] == "BlackWOM5"
    assert rows[0]["title"] == "Трусы комплект"
    assert rows[0]["subject"] == "Трусы"
    assert rows[0]["brand"] == "PALEY"
    assert rows[0]["ctr"] == 50
    assert rows[0]["buyoutPercent"] == 80


def test_search_rows_use_reference_fields_from_funnel_and_stock():
    run = MvpRealRun()
    row = run._build_search_item(
        {
            "nmId": 197330807,
            "text": "трусы женские",
            "openCard": 12,
            "addToCart": 4,
            "orders": 2,
            "frequency": 9,
            "visibility": 11,
            "avgPosition": 7,
            "medianPosition": 6,
            "minDiscountPrice": 99,
            "maxDiscountPrice": 199,
        },
        None,
        run.date_to,
        {
            "supplier_article": "BlackWOM5",
            "title": "Трусы комплект",
            "subject": "Трусы",
            "brand": "PALEY",
        },
    )

    assert row["supplier_article"] == "BlackWOM5"
    assert row["title"] == "Трусы комплект"
    assert row["subject"] == "Трусы"
    assert row["brand"] == "PALEY"
    assert row["search_query"] == "трусы женские"


def test_build_stock_row_preserves_zero_stock_values():
    run = MvpRealRun()

    row = run._build_stock_row(
        {
            "nmID": 197330807,
            "vendorCode": "BlackWOM5",
            "name": "Трусы комплект",
            "subjectName": "Трусы",
            "brandName": "PALEY",
            "metrics": {
                "stockCount": 0,
                "stockSum": 0,
                "saleRate": 0,
                "toClientCount": 0,
                "fromClientCount": 0,
                "availability": 0,
            },
        }
    )

    assert row["wb_stock_qty"] == 0
    assert row["stock_total_qty"] == 0
    assert row["stock_total_sum"] == 0
    assert row["saleRate"] == 0
    assert row["toClientCount"] == 0
    assert row["fromClientCount"] == 0
    assert row["availability"] == 0


def test_build_search_item_preserves_zero_metrics():
    run = MvpRealRun()

    row = run._build_search_item(
        {
            "nmId": 197330807,
            "text": "трусы женские",
            "openCard": 0,
            "addToCart": 0,
            "orders": 0,
            "frequency": 0,
            "visibility": 0,
            "avgPosition": 0,
            "medianPosition": 0,
            "rating": 0,
            "feedbackRating": 0,
            "minDiscountPrice": 0,
            "maxDiscountPrice": 0,
        },
        {
            "nmId": 197330807,
            "text": "трусы женские",
            "openCard": 0,
            "addToCart": 0,
            "orders": 0,
            "frequency": 0,
            "visibility": 0,
            "avgPosition": 0,
            "medianPosition": 0,
        },
        run.date_to,
        {},
    )

    assert row["card_rating"] == 0
    assert row["reviews_rating"] == 0
    assert row["query_count"] == 0
    assert row["query_count_prev"] == 0
    assert row["visibility"] == 0
    assert row["visibility_prev"] == 0
    assert row["avg_position"] == 0
    assert row["avg_position_prev"] == 0
    assert row["median_position"] == 0
    assert row["median_position_prev"] == 0
    assert row["search_clicks"] == 0
    assert row["search_clicks_prev"] == 0
    assert row["search_cart"] == 0
    assert row["search_cart_prev"] == 0
    assert row["search_orders"] == 0
    assert row["search_orders_prev"] == 0
    assert row["cart_conversion"] == 0
    assert row["cart_conversion_prev"] == 0
    assert row["order_conversion"] == 0
    assert row["order_conversion_prev"] == 0


def test_fullstats_rows_flatten_campaign_and_nm_metrics():
    run = MvpRealRun()
    payload = {
        "data": [
            {
                "advertId": 123,
                "campName": "Поиск тест",
                "days": [
                    {
                        "date": "2026-06-01",
                        "sum": 100,
                        "sum_price": 200,
                        "views": 300,
                        "clicks": 30,
                        "atbs": 5,
                        "orders": 2,
                        "shks": 2,
                        "canceled": 1,
                        "ctr": 10,
                        "cpc": 3,
                        "cr": 6,
                        "apps": [
                            {
                                "appType": "search",
                                "nms": [
                                    {
                                        "nmId": 197330807,
                                        "name": "Товар",
                                        "sum": 50,
                                        "sum_price": 100,
                                        "views": 150,
                                        "clicks": 15,
                                        "atbs": 3,
                                        "orders": 1,
                                        "shks": 1,
                                        "canceled": 0,
                                        "ctr": 12,
                                        "cpc": 4,
                                        "cr": 7,
                                    }
                                ],
                            }
                        ],
                    }
                ],
                "boosterStats": [
                    {"date": "2026-06-01", "nm": 197330807, "avg_position": 7.5},
                ],
            }
        ]
    }

    campaign_rows, nm_rows = run._build_fullstats_rows(payload, {123: "Поиск тест"})

    assert len(campaign_rows) == 1
    assert len(nm_rows) == 1
    assert campaign_rows[0]["campaign_name"] == "Поиск тест"
    assert campaign_rows[0]["ad_cpm"] == ""
    assert campaign_rows[0]["ad_roi"] == ""
    assert nm_rows[0]["nm_id"] == 197330807
    assert nm_rows[0]["avg_position"] == 7.5
