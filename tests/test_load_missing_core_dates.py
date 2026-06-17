from __future__ import annotations

from datetime import date

from scripts.load_missing_core_dates import (
    FullstatsAdvertGroup,
    _count_remaining_fullstats_groups,
    _select_failed_fullstats_groups_for_retry,
    _select_fullstats_groups_for_processing,
)


def test_select_fullstats_groups_keeps_partially_processed_advert() -> None:
    groups = [
        FullstatsAdvertGroup(
            advert_id=1001,
            rows=[{"advertId": 1001, "campaign_name": "Campaign", "nm_id": 197330807}],
            dates={date(2026, 6, 7), date(2026, 6, 8)},
        )
    ]

    selected_groups, fully_processed_count = _select_fullstats_groups_for_processing(
        groups,
        processed_pairs={(1001, date(2026, 6, 7))},
        force_refresh=False,
    )

    assert fully_processed_count == 0
    assert [group.advert_id for group in selected_groups] == [1001]


def test_select_fullstats_groups_skips_fully_processed_advert_without_force_refresh() -> None:
    groups = [
        FullstatsAdvertGroup(
            advert_id=1001,
            rows=[{"advertId": 1001, "campaign_name": "Campaign", "nm_id": 197330807}],
            dates={date(2026, 6, 7), date(2026, 6, 8)},
        )
    ]

    selected_groups, fully_processed_count = _select_fullstats_groups_for_processing(
        groups,
        processed_pairs={(1001, date(2026, 6, 7)), (1001, date(2026, 6, 8))},
        force_refresh=False,
    )

    assert fully_processed_count == 1
    assert selected_groups == []


def test_select_fullstats_groups_force_refresh_includes_fully_processed_advert() -> None:
    groups = [
        FullstatsAdvertGroup(
            advert_id=1001,
            rows=[{"advertId": 1001, "campaign_name": "Campaign", "nm_id": 197330807}],
            dates={date(2026, 6, 7), date(2026, 6, 8)},
        )
    ]

    selected_groups, fully_processed_count = _select_fullstats_groups_for_processing(
        groups,
        processed_pairs={(1001, date(2026, 6, 7)), (1001, date(2026, 6, 8))},
        force_refresh=True,
    )

    assert fully_processed_count == 1
    assert [group.advert_id for group in selected_groups] == [1001]


def test_count_remaining_fullstats_groups_uses_advert_date_coverage() -> None:
    groups = [
        FullstatsAdvertGroup(
            advert_id=1001,
            rows=[{"advertId": 1001, "campaign_name": "Campaign A", "nm_id": 197330807}],
            dates={date(2026, 6, 7), date(2026, 6, 8)},
        ),
        FullstatsAdvertGroup(
            advert_id=1002,
            rows=[{"advertId": 1002, "campaign_name": "Campaign B", "nm_id": 37320545}],
            dates={date(2026, 6, 7)},
        ),
    ]

    remaining = _count_remaining_fullstats_groups(
        groups,
        processed_pairs={(1001, date(2026, 6, 7)), (1002, date(2026, 6, 7))},
    )

    assert remaining == 1


def test_select_failed_fullstats_groups_for_retry_uses_only_pending_adverts() -> None:
    groups = [
        FullstatsAdvertGroup(
            advert_id=1001,
            rows=[{"advertId": 1001, "campaign_name": "Campaign A", "nm_id": 197330807}],
            dates={date(2026, 6, 8), date(2026, 6, 9)},
        ),
        FullstatsAdvertGroup(
            advert_id=1002,
            rows=[{"advertId": 1002, "campaign_name": "Campaign B", "nm_id": 37320545}],
            dates={date(2026, 6, 8)},
        ),
    ]

    selected_groups = _select_failed_fullstats_groups_for_retry(
        groups,
        failed_advert_ids={1002},
    )

    assert [group.advert_id for group in selected_groups] == [1002]
