from src.pipelines.vbro_localization_partial_run import VbroLocalizationPartialRun
from src.sheets.backlog_builder import build_backlog_rows


def test_profit_rows_leave_profit_blank_and_copy_identity_fields():
    run = VbroLocalizationPartialRun()
    run.loaded_at = "2026-06-02T16:30:00+05:00"

    funnel_index = {
        ("2026-05-31", "197330807"): {
            "supplier_article": "BlackWOM5",
            "title": "Title A",
            "subject": "Трусы",
            "brand": "PALEY",
        }
    }
    ad_cost_totals = {("2026-05-31", "197330807"): 123.45}
    report_rows = [
        {
            "nm_id": 197330807,
            "rr_dt": "2026-05-31",
            "ppvz_for_pay": 1000,
            "delivery_rub": 10,
            "storage_fee": 5,
            "penalty": 2,
            "deduction": 3,
            "acceptance": 4,
            "sa_name": "BlackWOM5",
            "subject_name": "Трусы",
            "brand_name": "PALEY",
        }
    ]

    rows = run._build_profit_rows(report_rows, funnel_index, ad_cost_totals)

    assert len(rows) == 10
    first = rows[0]
    assert first["date"] == "2026-05-31"
    assert first["nm_id"] == 197330807
    assert first["supplier_article"] == "BlackWOM5"
    assert first["title"] == "Title A"
    assert first["subject"] == "Трусы"
    assert first["brand"] == "PALEY"
    assert first["net_sales_payout"] == 1000.0
    assert first["ad_spend"] == 123.45
    assert first["operating_profit"] == ""
    assert first["operating_profit_per_unit"] == ""
    assert first["source_status"] == "MANUAL_UPLOAD"


def test_localization_rows_group_orders_by_region_and_project_wide_rows():
    run = VbroLocalizationPartialRun()
    run.loaded_at = "2026-06-02T16:30:00+05:00"
    run.nm_ids = [197330807]

    funnel_index = {
        ("2026-05-31", "197330807"): {
            "supplier_article": "BlackWOM5",
            "title": "Title A",
            "subject": "Трусы",
            "brand": "PALEY",
        }
    }
    region_rows = [
        {
            "nmID": 197330807,
            "sa": "BlackWOM5",
            "countryName": "Россия",
            "regionName": "Москва",
            "cityName": "Москва",
            "saleItemInvoiceQty": 1,
            "saleInvoiceCostPrice": 100,
        },
        {
            "nmID": 197330807,
            "sa": "BlackWOM5",
            "countryName": "Россия",
            "regionName": "Москва",
            "cityName": "Москва",
            "saleItemInvoiceQty": 1,
            "saleInvoiceCostPrice": 150,
        },
    ]

    fact_rows, summary_rows = run._build_localization_rows(region_rows, funnel_index)
    projected = run._project_localization_rows(fact_rows, summary_rows)

    assert len(fact_rows) == 1
    assert fact_rows[0]["orders_total_qty"] == 2
    assert fact_rows[0]["sale_amount"] == 250.0
    assert len(summary_rows) == 1
    assert summary_rows[0]["region_orders_share_percent"] == 100.0
    assert len(projected) == 1
    first = projected[0]
    assert first["Дата"] == "2026-06-01"
    assert first["Артикул WB"] == 197330807
    assert first["Артикул продавца"] == "BlackWOM5"
    assert first["Название"] == "Title A"
    assert first["Регион"] == "Москва"
    assert first["Итого заказов, шт"] == 2
    assert first["Продажи, шт"] == 2
    assert first["Сумма продаж, ₽"] == 250.0
    assert first["Остатки склад ВБ, шт"] == ""
    assert first["Остатки МП, шт"] == ""
    assert first["Время доставки"] == ""
    assert first["Локальные заказы, %"] == ""
    assert first["Не локальные заказы, %"] == ""
    assert first["data_status"] == "PARTIAL"
    assert first["source_status"] == "PARTIAL"
    assert all("ART-" not in str(cell) for row in projected for cell in row.values())


def test_localization_rows_use_stock_snapshot_as_reference_fallback():
    run = VbroLocalizationPartialRun()
    run.loaded_at = "2026-06-02T16:30:00+05:00"
    run.nm_ids = [197330807]

    funnel_index = {}
    stock_index = {
        "197330807": {
            "supplier_article": "BlackWOM5",
            "title": "Тестовая карточка",
            "subject": "Трусы",
            "brand": "PALEY",
            "wb_stock_qty": "12",
        }
    }
    region_rows = [
        {
            "nmID": 197330807,
            "sa": "",
            "countryName": "Россия",
            "regionName": "Москва",
            "cityName": "Москва",
            "saleItemInvoiceQty": 1,
            "saleInvoiceCostPrice": 100,
        }
    ]

    fact_rows, summary_rows = run._build_localization_rows(region_rows, funnel_index, stock_index)

    assert len(fact_rows) == 1
    assert fact_rows[0]["supplier_article"] == "BlackWOM5"
    assert fact_rows[0]["title"] == "Тестовая карточка"
    assert fact_rows[0]["wb_stock_qty"] == ""
    assert fact_rows[0]["source_status"] == "REAL_API"
    assert len(summary_rows) == 1
    assert summary_rows[0]["source_status"] == "CALCULATED"


def test_profit_rows_respect_runner_nm_ids():
    run = VbroLocalizationPartialRun()
    run.nm_ids = [197330807]

    rows = run._build_profit_rows(
        report_rows=[
            {"nm_id": 197330807, "rr_dt": "2026-05-31", "ppvz_for_pay": 10},
            {"nm_id": 37320545, "rr_dt": "2026-05-31", "ppvz_for_pay": 20},
        ],
        funnel_index={},
        ad_cost_totals={},
    )

    assert len(rows) == 2
    assert {row["nm_id"] for row in rows} == {197330807}


def test_coverage_rows_include_requested_statuses():
    run = VbroLocalizationPartialRun()
    coverage = {row["sheet_name"]: row["status"] for row in run._coverage_rows()}

    assert coverage["Воронка на день"] == "OK"
    assert coverage["ИТОГО_v1"] == "OK"
    assert coverage["Остатки"] == "TECHNICAL / PARTIAL"
    assert coverage["РасходРК"] == "PARTIAL/OK"
    assert coverage["Поисковые запросы"] == "PARTIAL"
    assert coverage["ВБро"] == "MANUAL_EXTERNAL_SERVICE / MANUAL_UPLOAD"
    assert coverage["Локализация"] == "PARTIAL"
    assert coverage["РК стата"] == "PARTIAL"
    assert coverage["Сравнение карточек"] == "MPSTAT_401"
    assert coverage["Точка вх"] == "CSV_ONLY / PRIVATE_ENDPOINT / NEEDS_EXPORT_SAMPLE"


def test_backlog_rows_include_requested_statuses():
    run = VbroLocalizationPartialRun()
    backlog = {row["block"]: row["status"] for row in run._backlog_rows()}
    canonical = {row["block"]: row["status"] for row in build_backlog_rows()}

    assert len(backlog) == 10
    assert backlog == canonical
    assert backlog["WB Content API / dim_product"] == "PARTIAL"
    assert backlog["ВБро"] == "MANUAL_EXTERNAL_SERVICE / MANUAL_UPLOAD"
    assert backlog["Локализация"] == "PARTIAL"
    assert backlog["РК стата"] == "PARTIAL"
    assert backlog["MPStat / Сравнение карточек"] == "MPSTAT_401"
    assert backlog["Точка вх"] == "CSV_ONLY / PRIVATE_ENDPOINT / NEEDS_EXPORT_SAMPLE"
    assert backlog["Поисковые запросы"] == "PARTIAL"
    assert backlog["Остатки"] == "TECHNICAL / PARTIAL"
    assert backlog["ИТОГО_FULL"] == "LATER"
    assert backlog["Настройки_артикулы"] == "LATER"
