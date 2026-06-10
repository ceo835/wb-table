from src.clients.wb_content_client import WBContentClient


def test_build_cards_list_payload_uses_sort_filter_and_limit():
    payload = WBContentClient.build_cards_list_payload(limit=150)

    assert payload == {
        "settings": {
            "sort": {"ascending": True},
            "cursor": {"limit": 100},
            "filter": {"withPhoto": -1},
        }
    }


def test_build_cards_list_payload_includes_cursor_and_text_search():
    payload = WBContentClient.build_cards_list_payload(
        limit=50,
        cursor={"updatedAt": "2026-05-15T10:04:07.659477Z", "nmID": 238541316},
        text_search="BlackWOM5",
    )

    assert payload["settings"]["cursor"] == {
        "limit": 50,
        "updatedAt": "2026-05-15T10:04:07.659477Z",
        "nmID": 238541316,
    }
    assert payload["settings"]["filter"] == {"withPhoto": -1, "textSearch": "BlackWOM5"}


def test_extract_cards_supports_top_level_and_nested_cards():
    top_level = {"cards": [{"nmID": 1}, {"nmID": 2}]}
    nested = {"data": {"cards": [{"nmID": 3}]}}

    assert WBContentClient.extract_cards(top_level) == [{"nmID": 1}, {"nmID": 2}]
    assert WBContentClient.extract_cards(nested) == [{"nmID": 3}]


def test_extract_cursor_supports_top_level_and_nested_cursor():
    top_level = {"cursor": {"updatedAt": "2026-01-01T00:00:00Z", "nmID": 123, "total": 100}}
    nested = {"data": {"cursor": {"updatedAt": "2026-01-02T00:00:00Z", "nmID": 456}}}

    assert WBContentClient.extract_cursor(top_level, limit=100) == {
        "updatedAt": "2026-01-01T00:00:00Z",
        "nmID": 123,
        "limit": 100,
        "total": 100,
    }
    assert WBContentClient.extract_cursor(nested, limit=50) == {
        "updatedAt": "2026-01-02T00:00:00Z",
        "nmID": 456,
        "limit": 50,
        "total": None,
    }


def test_normalize_card_maps_expected_fields():
    normalized = WBContentClient.normalize_card(
        {
            "nmID": 197330807,
            "vendorCode": "BlackWOM5",
            "title": "Трусы комплект",
            "brand": "PALEY",
            "subjectName": "Трусы",
            "sizes": [{"techSize": "42-44"}],
            "skus": ["sku-1"],
        }
    )

    assert normalized == {
        "nm_id": 197330807,
        "supplier_article": "BlackWOM5",
        "title": "Трусы комплект",
        "brand": "PALEY",
        "subject": "Трусы",
        "sizes": [{"techSize": "42-44"}],
        "skus": ["sku-1"],
    }
