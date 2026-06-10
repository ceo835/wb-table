from __future__ import annotations


def build_coverage_rows() -> list[dict[str, str]]:
    return [
        {"sheet_name": "Воронка на день", "status": "OK", "details": "10 rows written from live API; suspicious CTR values are tracked in Validation_v1"},
        {"sheet_name": "ИТОГО_v1", "status": "OK", "details": "10 rows written and percent formats normalized"},
        {"sheet_name": "Остатки", "status": "TECHNICAL / PARTIAL", "details": "technical helper sheet; no original standalone tab exists"},
        {"sheet_name": "РасходРК", "status": "PARTIAL/OK", "details": "campaign_type includes click campaigns and nm_id parsing is confirmed"},
        {"sheet_name": "Поисковые запросы", "status": "PARTIAL", "details": "reference fields are enriched from funnel/stock rows; competitor percentile fields remain unconfirmed"},
        {"sheet_name": "ВБро", "status": "MANUAL_EXTERNAL_SERVICE / MANUAL_UPLOAD", "details": "profit rows stay blank because operational profit comes from an external manual service"},
        {"sheet_name": "Локализация", "status": "PARTIAL", "details": "region-sale is still partial; orders-geography needs a CSV/Excel sample or cabinet access"},
        {"sheet_name": "РК стата", "status": "PARTIAL", "details": "fullstats returns live rows, but production runs should use D-2 or earlier; CPM and ROI stay blank"},
        {"sheet_name": "Сравнение карточек", "status": "MPSTAT_401", "details": "MPStat auth still returns 401"},
        {"sheet_name": "Точка вх", "status": "CSV_ONLY / PRIVATE_ENDPOINT / NEEDS_EXPORT_SAMPLE", "details": "customer-profile export sample or cabinet access is still required"},
        {"sheet_name": "ИТОГО_FULL", "status": "LATER", "details": "wide pivot remains deferred"},
    ]
