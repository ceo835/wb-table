from __future__ import annotations

from datetime import date

import pytest

from scripts.export_streamlit_v1_dataset import resolve_export_dates


def test_resolve_export_dates_uses_full_mart_range_by_default(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.export_streamlit_v1_dataset.get_mart_total_report_date_bounds",
        lambda: (date(2026, 5, 31), date(2026, 6, 7)),
    )

    date_from, date_to = resolve_export_dates(None, None)

    assert date_from == date(2026, 5, 31)
    assert date_to == date(2026, 6, 7)


def test_resolve_export_dates_fills_missing_boundary_from_mart(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr(
        "scripts.export_streamlit_v1_dataset.get_mart_total_report_date_bounds",
        lambda: (date(2026, 5, 31), date(2026, 6, 7)),
    )

    date_from, date_to = resolve_export_dates("2026-06-01", None)

    assert date_from == date(2026, 6, 1)
    assert date_to == date(2026, 6, 7)
