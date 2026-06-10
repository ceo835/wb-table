# VBro and Localization Partial Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Add a read-only partial run that fills `ВБро`, `Локализация`, `Coverage`, and `Backlog` for the same `2026-05-31 .. 2026-06-01` window and the same 5 `nmID`s, without inventing unsupported profit formulas or fake data.

**Architecture:** Keep the existing MVP pipeline intact and add a narrowly scoped partial-run script that reuses the current Google Sheets client, schema definitions, and existing processed facts. Build `fact_profit_day.csv` and the localization facts from confirmed sources only, then project those rows into the user sheets with explicit `data_status` and `source_status` values.

**Tech Stack:** Python 3.12, pytest, Google Sheets API client, CSV/JSON file processing.

---

### Task 1: Expand schemas for partial-run outputs

**Files:**
- Modify: `src/sheets/schema_definitions.py`
- Modify: `tests/test_sheet_schemas.py`
- Test: `tests/test_sheet_schemas.py`

- [ ] **Step 1: Add the missing fact columns**

```python
PROCESSED_TABLE_SCHEMAS["fact_profit_day"] = SheetSchema(
    name="fact_profit_day",
    object_type="processed_table",
    primary_key=("date", "nm_id"),
    source_fields=("supplier_article", "title", "subject", "brand"),
    columns=(
        "date",
        "nm_id",
        "supplier_article",
        "title",
        "subject",
        "brand",
        "organic_sales_qty",
        "net_sales_payout",
        "ad_spend",
        "logistics",
        "storage",
        "penalties",
        "deductions",
        "acceptance",
        "cogs",
        "other_costs",
        "operating_profit",
        "operating_profit_per_unit",
        "data_status",
        "source_status",
        "loaded_at",
    ),
)
```

- [ ] **Step 2: Add the localization fact columns**

```python
PROCESSED_TABLE_SCHEMAS["fact_localization_region_day"] = SheetSchema(
    name="fact_localization_region_day",
    object_type="processed_table",
    primary_key=("date", "nm_id", "region"),
    source_fields=("supplier_article", "title", "country", "region", "city"),
    columns=(
        "date",
        "nm_id",
        "supplier_article",
        "title",
        "subject",
        "brand",
        "country",
        "region",
        "city",
        "delivery_time",
        "orders_total_qty",
        "orders_local_qty",
        "orders_nonlocal_qty",
        "orders_nonlocal_percent",
        "wb_stock_orders_local_qty",
        "wb_stock_orders_nonlocal_qty",
        "wb_stock_orders_nonlocal_percent",
        "mp_orders_local_qty",
        "mp_orders_nonlocal_qty",
        "mp_orders_nonlocal_percent",
        "wb_stock_qty",
        "mp_stock_qty",
        "sale_item_qty",
        "sale_amount",
        "local_orders_percent",
        "data_status",
        "source_status",
        "loaded_at",
    ),
)
```

- [ ] **Step 3: Add the localization summary columns**

```python
PROCESSED_TABLE_SCHEMAS["fact_localization_region_summary_day"] = SheetSchema(
    name="fact_localization_region_summary_day",
    object_type="processed_table",
    primary_key=("date", "region"),
    source_fields=("country", "region"),
    columns=(
        "date",
        "country",
        "region",
        "sale_item_qty",
        "sale_amount",
        "local_orders_percent",
        "nonlocal_orders_percent",
        "delivery_time",
        "region_orders_share_percent",
        "wb_all_orders_share_percent",
        "data_status",
        "source_status",
        "loaded_at",
    ),
)
```

- [ ] **Step 4: Update the schema tests to match the new column lists**

```python
assert PROCESSED_TABLE_SCHEMAS["fact_profit_day"].columns == (
    "date",
    "nm_id",
    "supplier_article",
    "title",
    "subject",
    "brand",
    "organic_sales_qty",
    "net_sales_payout",
    "ad_spend",
    "logistics",
    "storage",
    "penalties",
    "deductions",
    "acceptance",
    "cogs",
    "other_costs",
    "operating_profit",
    "operating_profit_per_unit",
    "data_status",
    "source_status",
    "loaded_at",
)
```

- [ ] **Step 5: Run the schema tests**

Run: `pytest tests/test_sheet_schemas.py -q`
Expected: PASS.

### Task 2: Build partial profit and localization facts

**Files:**
- Create: `scripts/vbro_localization_partial_run.py`
- Modify: `src/clients/google_sheets_client.py`
- Test: `tests/test_vbro_localization_partial_run.py`

- [ ] **Step 1: Create a pure parser for the audited WB orders export**

```python
def build_localization_facts(orders_rows, funnel_by_key, stock_by_nm_id, loaded_at):
    ...
```

- [ ] **Step 2: Build `fact_profit_day` without inventing a profit formula**

```python
row = {
    "date": day,
    "nm_id": nm_id,
    "supplier_article": supplier_article,
    "title": title,
    "subject": subject,
    "brand": brand,
    "organic_sales_qty": "",
    "net_sales_payout": "",
    "ad_spend": ad_spend or "",
    "logistics": "",
    "storage": "",
    "penalties": "",
    "deductions": "",
    "acceptance": "",
    "cogs": "",
    "other_costs": "",
    "operating_profit": "",
    "operating_profit_per_unit": "",
    "data_status": "PARTIAL",
    "source_status": "NEEDS_FORMULA_CONFIRMATION",
    "loaded_at": loaded_at,
}
```

- [ ] **Step 3: Build the regional localization facts from order rows**

```python
row = {
    "date": day,
    "nm_id": nm_id,
    "supplier_article": supplier_article,
    "title": title,
    "subject": subject,
    "brand": brand,
    "country": country,
    "region": region,
    "city": "",
    "delivery_time": "",
    "orders_total_qty": total_qty,
    "orders_local_qty": "",
    "orders_nonlocal_qty": "",
    "orders_nonlocal_percent": "",
    "wb_stock_orders_local_qty": "",
    "wb_stock_orders_nonlocal_qty": "",
    "wb_stock_orders_nonlocal_percent": "",
    "mp_orders_local_qty": "",
    "mp_orders_nonlocal_qty": "",
    "mp_orders_nonlocal_percent": "",
    "wb_stock_qty": stock_qty or "",
    "mp_stock_qty": "",
    "sale_item_qty": total_qty,
    "sale_amount": sale_amount,
    "local_orders_percent": "",
    "data_status": "PARTIAL",
    "source_status": "REAL_API",
    "loaded_at": loaded_at,
}
```

- [ ] **Step 4: Build the summary rows by region**

```python
summary_row = {
    "date": day,
    "country": country,
    "region": region,
    "sale_item_qty": total_qty,
    "sale_amount": sale_amount,
    "local_orders_percent": "",
    "nonlocal_orders_percent": "",
    "delivery_time": "",
    "region_orders_share_percent": share_percent,
    "wb_all_orders_share_percent": share_percent,
    "data_status": "PARTIAL",
    "source_status": "REAL_API",
    "loaded_at": loaded_at,
}
```

- [ ] **Step 5: Write focused tests for the builders**

```python
def test_localization_builder_groups_orders_by_nm_id_and_region():
    ...

def test_profit_builder_leaves_formula_fields_empty_when_unconfirmed():
    ...
```

- [ ] **Step 6: Run the partial-run unit tests**

Run: `pytest tests/test_vbro_localization_partial_run.py -q`
Expected: PASS.

### Task 3: Write the partial sheets and reports

**Files:**
- Modify: `scripts/vbro_localization_partial_run.py`
- Modify: `src/pipelines/mvp_real_run.py` only if reusable helpers must be extracted
- Create: `docs/vbro_localization_partial_run_report.md`
- Create: `data/processed/vbro_localization_partial_run_report.csv`

- [ ] **Step 1: Project `fact_profit_day` into the `ВБро` sheet**

```python
vbro_rows = [
    {
        "Дата": row["date"],
        "Артикул ВБ": row["nm_id"],
        "Артикул продавца": row["supplier_article"],
        "Продажи (органические)": row["organic_sales_qty"],
        "Операционная прибыль": row["operating_profit"],
        "Операционная прибыль на единицу": row["operating_profit_per_unit"],
        "data_status": row["data_status"],
        "source_status": row["source_status"],
        "loaded_at": row["loaded_at"],
    }
    for row in fact_profit_rows
]
```

- [ ] **Step 2: Project localization rows into the `Локализация` sheet**

```python
localization_sheet_rows = [
    {
        "date": row["date"],
        "nm_id": row["nm_id"],
        "region": row["region"],
        "metric_name": "sale_item_qty",
        "metric_value": row["sale_item_qty"],
        "data_status": row["data_status"],
        "source_status": row["source_status"],
        "loaded_at": row["loaded_at"],
    },
    ...
]
```

- [ ] **Step 3: Refresh `Coverage` and `Backlog` with the required statuses**

```python
coverage_rows = [
    {"sheet_name": "Воронка на день", "status": "OK", "details": "10 rows written"},
    {"sheet_name": "ИТОГО_v1", "status": "OK", "details": "10 rows written"},
    {"sheet_name": "Остатки", "status": "PARTIAL", "details": "stock snapshot only; mp_stock_qty still partial"},
    {"sheet_name": "РасходРК", "status": "PARTIAL/OK", "details": "campaign spend and nm_id parsing confirmed"},
    {"sheet_name": "Поисковые запросы", "status": "PARTIAL", "details": "competitor percentile fields still partial"},
    {"sheet_name": "ВБро", "status": "PARTIAL / NEEDS_FORMULA_CONFIRMATION", "details": "profit formulas and COGS remain unconfirmed"},
    {"sheet_name": "Локализация", "status": "PARTIAL", "details": "regional sales rows only; local/nonlocal KPI still partial"},
    {"sheet_name": "РК стата", "status": "PARTIAL / WAIT_FULLSTATS", "details": "fullstats still null for the current window"},
    {"sheet_name": "Сравнение карточек", "status": "FAIL / MPSTAT_401", "details": "MPStat auth still rejected"},
    {"sheet_name": "Точка вх", "status": "CSV_ONLY / PRIVATE_ENDPOINT", "details": "no public endpoint confirmed"},
    {"sheet_name": "ИТОГО_FULL", "status": "LATER", "details": "wide pivot still deferred"},
]
```

- [ ] **Step 4: Generate the report files**

```python
report_csv_rows = [
    {"object_name": "ВБро", "status": "PARTIAL", "rows_written": "10", "fields_filled": "date,nm_id,supplier_article,ad_spend", "fields_empty": "organic_sales_qty,operating_profit,operating_profit_per_unit", "details": "profit formula not confirmed"},
    {"object_name": "Локализация", "status": "PARTIAL", "rows_written": "N", "fields_filled": "date,nm_id,region,sale_item_qty,sale_amount", "fields_empty": "delivery_time,local_orders_percent,nonlocal_*", "details": "regional orders derived from WB statistics orders"},
]
```

- [ ] **Step 5: Run the live read-only write and validation**

Run:
`python scripts/vbro_localization_partial_run.py`
`python scripts/check_no_secrets.py`
`pytest`

Expected:
`ВБро`, `Локализация`, `Coverage`, and `Backlog` are refreshed without fake rows or formula invention.

### Task 4: Verify the live sheet state

**Files:**
- Modify: `tests/test_vbro_localization_partial_run.py`
- Modify: `docs/vbro_localization_partial_run_report.md` if validation uncovers gaps

- [ ] **Step 1: Assert the sheet counts and empty-field behavior**

```python
assert len(vbro_rows) == 10
assert len(localization_rows) > 0
assert all(row["Операционная прибыль"] == "" for row in vbro_rows)
assert all("ART-" not in cell for row in vbro_rows for cell in row.values())
```

- [ ] **Step 2: Assert no mock/fake markers are present**

```python
assert not any(marker in cell for row in localization_rows for cell in row.values() for marker in ["ART-", "TestBrand", "DRY_RUN", "mock", "fake"])
```

- [ ] **Step 3: Run the full validation suite**

Run: `pytest`
Expected: PASS with the existing `audit_smoke_test.py` warnings only.

