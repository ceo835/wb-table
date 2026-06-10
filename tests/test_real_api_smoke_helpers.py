from scripts.real_api_smoke_test import SmokeResult, append_backlog_updates, count_matching_dicts, has_key


def test_has_key_finds_nested_fields() -> None:
    payload = {
        "data": {
            "items": [
                {
                    "nmId": 1,
                    "frequency": {"current": 3},
                    "avgPosition": {"current": 5},
                }
            ]
        }
    }

    assert has_key(payload, ["nmId"])
    assert has_key(payload, ["frequency"])
    assert has_key(payload, ["avg_position", "avgPosition"])


def test_count_matching_dicts_counts_nested_rows() -> None:
    payload = {
        "data": {
            "items": [
                {"nmId": 1, "date": "2026-06-01"},
                {"nmId": 2, "date": "2026-06-01"},
            ]
        }
    }

    assert count_matching_dicts(payload, ["nmId", "date"]) == 2


def test_append_backlog_updates_only_returns_non_usable_results() -> None:
    results = [
        SmokeResult(
            source="WB Content API",
            endpoint="/content/v2/get/cards/list",
            method="POST",
            status="OK",
            http_status="200",
            objects_count=5,
            fields_found=["nm_id"],
            fields_missing=[],
            error_short="",
            mvp_usable="YES",
        ),
        SmokeResult(
            source="WB Promotion fullstats",
            endpoint="/adv/v3/fullstats",
            method="GET",
            status="PARTIAL",
            http_status="200",
            objects_count=2,
            fields_found=["advertId"],
            fields_missing=["cpm", "roi"],
            error_short="",
            mvp_usable="PARTIAL",
        ),
    ]

    updates = append_backlog_updates(results)

    assert len(updates) == 1
    assert updates[0]["block"] == "WB Promotion fullstats"
