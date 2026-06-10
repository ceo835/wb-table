from src.pipelines.api_enrichment_run import ApiEnrichmentRun


def test_report_rows_cover_requested_tabs():
    run = ApiEnrichmentRun()
    mvp_summary = {
        "results": [
            {"target": "Воронка на день", "rows_written": 10, "endpoint": "funnel"},
            {"target": "Остатки", "rows_written": 5, "endpoint": "stocks"},
            {"target": "РасходРК", "rows_written": 155, "endpoint": "ads"},
            {"target": "РК стата", "rows_written": 20, "endpoint": "fullstats"},
            {"target": "Поисковые запросы", "rows_written": 1000, "endpoint": "search"},
            {"target": "ИТОГО_v1", "rows_written": 10, "endpoint": "mixed"},
        ]
    }
    vbro_summary = {
        "results": [
            {"target": "ВБро", "rows_written": 10, "endpoint": "profit"},
            {"target": "Локализация", "rows_written": 331, "endpoint": "localization"},
            {"target": "Coverage", "rows_written": 9, "endpoint": "sheet write"},
            {"target": "Backlog", "rows_written": 9, "endpoint": "sheet write"},
        ]
    }

    rows = run._report_rows(mvp_summary, vbro_summary)
    sheet_names = [row.sheet_name for row in rows]

    assert "Воронка на день" in sheet_names
    assert "РК стата" in sheet_names
    assert "Поисковые запросы" in sheet_names
    assert "ВБро" in sheet_names
    assert "Локализация" in sheet_names
    assert "Coverage" in sheet_names
    assert "Backlog" in sheet_names
