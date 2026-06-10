from src.sheets.coverage_builder import build_coverage_rows


def test_coverage_builder_matches_expected_statuses():
    rows = build_coverage_rows()
    coverage = {row["sheet_name"]: row["status"] for row in rows}

    assert len(rows) == 11
    assert coverage["Воронка на день"] == "OK"
    assert coverage["Остатки"] == "TECHNICAL / PARTIAL"
    assert coverage["ВБро"] == "MANUAL_EXTERNAL_SERVICE / MANUAL_UPLOAD"
    assert coverage["Локализация"] == "PARTIAL"
    assert coverage["РК стата"] == "PARTIAL"
    assert coverage["Точка вх"] == "CSV_ONLY / PRIVATE_ENDPOINT / NEEDS_EXPORT_SAMPLE"
