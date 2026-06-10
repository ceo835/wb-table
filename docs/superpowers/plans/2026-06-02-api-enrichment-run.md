# API Enrichment Run Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Enrich the existing MVP sheets with additional real fields confirmed by endpoint-gap audit, without adding mock data or expanding scope.

**Architecture:** Reuse the existing MVP live-run pipeline as the write path, extend the funnel mapper to consume nested `sales-funnel/products` comparison fields, add a small `РК стата` builder from `adv/v3/fullstats` plus campaign-name lookup from `adv/v1/upd`, and keep all writes header-safe and non-destructive. Write a separate report artifact for this enrichment pass by reading back the updated sheets after the live run.

**Tech Stack:** Python, `requests`, existing WB client helpers, Google Sheets client, `pytest`.

---

### Task 1: Extend funnel sheet structure and mapper

**Files:**
- Modify: `src/sheets/schema_definitions.py`
- Modify: `src/pipelines/mvp_real_run.py`
- Test: `tests/test_sheet_schemas.py`
- Test: `tests/test_mvp_real_run_helpers.py`

- [ ] **Step 1: Add the missing funnel comparison and WB Club columns to the user sheet schema**

Use the documented field map to add previous-period columns and WB Club fields to `USER_SHEET_SCHEMAS["Воронка на день"]`.

- [ ] **Step 2: Add nested metric helpers and the `sales-funnel/products` fetch**

Add a read-only fetch for `/api/analytics/v3/sales-funnel/products` and a helper that reads `selected`, `past`, and `comparison` blocks safely.

- [ ] **Step 3: Enrich the funnel sheet rows**

Map current and previous period values from `history`, and fill `Рейтинг карточки`, `Рейтинг по отзывам`, `Среднее время доставки`, `Локальные заказы, %`, stock columns, and WB Club fields from `products` when present.

- [ ] **Step 4: Run the focused tests**

Run: `pytest tests/test_sheet_schemas.py tests/test_mvp_real_run_helpers.py -q`

Expected: schema tests and helper tests pass after the header expansion and nested parsing changes.

### Task 2: Add `РК стата` live rows

**Files:**
- Modify: `src/pipelines/mvp_real_run.py`
- Test: `tests/test_mvp_real_run_helpers.py`
- Test: `tests/test_sheet_schemas.py`

- [ ] **Step 1: Fetch promotion ids and fullstats**

Use `/adv/v1/promotion/count` to collect campaign ids, then call `/adv/v3/fullstats` with the confirmed test window.

- [ ] **Step 2: Flatten fullstats into campaign and product rows**

Build `fact_ad_campaign_day` and `fact_ad_campaign_nm_day` rows from the nested `days -> apps -> nms` structure, keeping `CPM` and `ROI` blank if not exposed.

- [ ] **Step 3: Write the `РК стата` user sheet**

Write only the real fields from the same flattened source, using `advertId`, `campaign_name`, `row_type`, `conversion_type`, `nm_id`, and the numeric metrics returned by fullstats.

- [ ] **Step 4: Verify with tests**

Run: `pytest tests/test_mvp_real_run_helpers.py -q`

Expected: helper tests cover the flattening logic and the `РК стата` row shape.

### Task 3: Produce an enrichment report

**Files:**
- Create: `scripts/api_enrichment_run.py`
- Create: `src/pipelines/api_enrichment_run.py`
- Create: `docs/api_enrichment_run_report.md`
- Create: `data/processed/api_enrichment_run_report.csv`

- [ ] **Step 1: Run the live enrichment pass**

Reuse the updated MVP write path to populate the existing sheets and then read back the updated headers and row counts.

- [ ] **Step 2: Summarize the enrichment safely**

Write a block-oriented markdown report and a field-oriented CSV report with only safe summary data.

- [ ] **Step 3: Confirm no raw payloads were saved**

Include a safety section that explicitly states no raw/private payloads were stored.

### Task 4: Verification

**Files:**
- No file changes; run checks only

- [ ] **Step 1: Run secret scan**

Run: `python scripts/check_no_secrets.py`

- [ ] **Step 2: Run the test suite**

Run: `pytest`

- [ ] **Step 3: Review any warnings**

Confirm any remaining warnings are pre-existing and unrelated to the enrichment run.

---

### Self-Review

**Spec coverage**
- Funnel comparison fields and WB Club fields are covered in Task 1.
- `РК стата` rows from fullstats are covered in Task 2.
- Safe reporting is covered in Task 3.
- Secrets/tests are covered in Task 4.

**Placeholder scan**
- No TBD/TODO placeholders left in the plan.

**Type consistency**
- The same sheet names, endpoint names, and field names are used consistently across tasks.
