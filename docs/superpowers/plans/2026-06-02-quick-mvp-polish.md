# Quick MVP Polish Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Apply small safe MVP polish fixes for `Поисковые запросы`, `РасходРК`, `Локализация`, `Coverage`, and `Backlog` without expanding scope.

**Architecture:** Keep the existing live-run pipelines intact and make targeted changes in the current MVP writers. Use confirmed funnel/stock references to enrich search rows, adjust campaign type parsing, stop leaking total stock into regional localization rows, and refresh coverage/backlog status text. Generate a separate quick polish report by reading the already-written Google Sheets data and comparing it to processed CSVs.

**Tech Stack:** Python, Google Sheets API client, CSV report generation, pytest.

---

### Task 1: Enrich Search and Campaign Classification

**Files:**
- Modify: `src/pipelines/mvp_real_run.py`
- Test: `tests/test_mvp_real_run_helpers.py`

- [ ] **Step 1: Write the failing test**

```python
def test_campaign_type_classification_rules():
    assert _classify_campaign_type("За клик Авокадо") == "За клик"
    assert _classify_campaign_type("Оплата за клик Арт. 123") == "За клик"
    assert _classify_campaign_type("Клик Арт. 123") == "За клик"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_mvp_real_run_helpers.py::test_campaign_type_classification_rules -v`
Expected: FAIL before the classifier rule is extended.

- [ ] **Step 3: Write minimal implementation**

```python
if "ЗА КЛИК" in upper or "ОПЛАТА ЗА КЛИК" in upper or upper.startswith("КЛИК"):
    return "За клик"
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_mvp_real_run_helpers.py::test_campaign_type_classification_rules -v`
Expected: PASS.

### Task 2: Keep Localization Regional Stock Blank

**Files:**
- Modify: `src/pipelines/vbro_localization_partial_run.py`
- Test: `tests/test_vbro_localization_partial_run.py`

- [ ] **Step 1: Write the failing test**

```python
assert first["Остатки склад ВБ, шт"] == ""
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vbro_localization_partial_run.py::test_localization_rows_group_orders_by_region_and_project_wide_rows -v`
Expected: FAIL before the regional stock fallback is removed.

- [ ] **Step 3: Write minimal implementation**

```python
"Остатки склад ВБ, шт": "",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vbro_localization_partial_run.py::test_localization_rows_group_orders_by_region_and_project_wide_rows -v`
Expected: PASS.

### Task 3: Refresh Coverage and Backlog Text

**Files:**
- Modify: `src/pipelines/vbro_localization_partial_run.py`
- Test: `tests/test_vbro_localization_partial_run.py`

- [ ] **Step 1: Update the status expectations**

```python
assert coverage["Остатки"] == "TECHNICAL / PARTIAL"
assert coverage["Поисковые запросы"] == "PARTIAL"
assert coverage["РасходРК"] == "PARTIAL/OK"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/test_vbro_localization_partial_run.py::test_coverage_rows_include_requested_statuses -v`
Expected: FAIL before the status strings are updated.

- [ ] **Step 3: Write minimal implementation**

```python
{"sheet_name": "Остатки", "status": "TECHNICAL / PARTIAL", "details": "technical helper sheet; no original standalone tab exists"},
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/test_vbro_localization_partial_run.py::test_coverage_rows_include_requested_statuses -v`
Expected: PASS.

### Task 4: Generate Quick Polish Report

**Files:**
- Modify: `scripts/validate_mvp_rerun_clean_write.py`
- Create: `docs/quick_mvp_polish_report.md`
- Create: `data/processed/quick_mvp_polish_report.csv`

- [ ] **Step 1: Add report rows for search, ad cost, localization, coverage, backlog, and stock sheet checks**

```python
CheckRow(
    object_name="Поисковые запросы",
    check_name="reference_enrichment",
    status="PASS",
    rows_checked=len(search_rows),
    issues_count=0,
    details="supplier_article/title/subject/brand are copied from existing reference tables when available",
)
```

- [ ] **Step 2: Run the validator script**

Run: `python scripts/validate_mvp_rerun_clean_write.py`
Expected: new quick polish report files are written alongside the existing clean-write report.

- [ ] **Step 3: Verify output files exist**

Run: `Get-ChildItem docs/quick_mvp_polish_report.md, data/processed/quick_mvp_polish_report.csv`
Expected: both files present.

### Task 5: Run Checks

**Files:**
- No code changes

- [ ] **Step 1: Run secret scan**

Run: `python scripts/check_no_secrets.py`
Expected: PASS.

- [ ] **Step 2: Run tests**

Run: `pytest`
Expected: PASS.

