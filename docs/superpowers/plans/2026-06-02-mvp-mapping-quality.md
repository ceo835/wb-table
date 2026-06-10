# MVP Mapping Quality Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Improve MVP real-api mapping quality without changing the project architecture or introducing fake data.

**Architecture:** Keep the current MVP pipeline intact. Patch only the row mappers, numeric normalization, and live validation so Google Sheets writes remain clean, deterministic, and header-safe.

**Tech Stack:** Python, Google Sheets API client, pytest, existing local CSV artifacts.

---

### Task 1: Fix `ИТОГО_v1` enrichment and numeric normalization

**Files:**
- Modify: `src/pipelines/mvp_real_run.py`
- Test: `tests/test_mvp_real_run_helpers.py`

- [ ] **Step 1: Add failing tests**

```python
def test_ad_campaign_type_classification():
    assert _classify_campaign_type("Поиск - бренд") == "Поиск"
    assert _classify_campaign_type("Буст весна") == "Буст"
    assert _classify_campaign_type("Единая ставка") == "Единая ставка"
    assert _classify_campaign_type("ПОЛКИ акция") == "Полки"
    assert _classify_campaign_type("АРК тест") == "АРК"
    assert _classify_campaign_type("Что-то иное") == "UNKNOWN"
```

- [ ] **Step 2: Implement product reference fallback**

```python
def _first_text(*sources, *keys):
    ...
```

- [ ] **Step 3: Normalize selected numeric fields**

```python
def _normalize_number_value(value):
    ...
```

- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_mvp_real_run_helpers.py -q`
Expected: PASS

### Task 2: Fix `РасходРК` parsing rules

**Files:**
- Modify: `src/pipelines/mvp_real_run.py`
- Test: `tests/test_mvp_real_run_helpers.py`

- [ ] **Step 1: Add failing tests for `nm_id_parse_status`**

```python
def test_campaign_parse_status_rules():
    ...
```

- [ ] **Step 2: Implement `FROM_CAMPAIGN_NAME` / `FROM_SECTION` / `NOT_FOUND`**
- [ ] **Step 3: Use campaign-name based `campaign_type` classification**
- [ ] **Step 4: Run focused tests**

Run: `pytest tests/test_mvp_real_run_helpers.py -q`
Expected: PASS

### Task 3: Re-run clean write and validate live sheets

**Files:**
- Modify: `src/pipelines/mvp_real_run.py`
- Modify: `scripts/validate_mvp_rerun_clean_write.py`
- Create: `docs/mvp_mapping_quality_report.md`

- [ ] **Step 1: Re-run `python scripts/mvp_real_run.py`**
- [ ] **Step 2: Re-run validation script**
- [ ] **Step 3: Confirm no duplicates, no mock/fake, and enriched refs**
- [ ] **Step 4: Save the quality report**

Run:
```bash
python scripts/mvp_real_run.py
python scripts/validate_mvp_rerun_clean_write.py
```
Expected: `Воронка на день` = 10 rows, `ИТОГО_v1` = 10 rows, mapping quality checks PASS.

### Task 4: Final verification

**Files:**
- None

- [ ] **Step 1: Run secrets scan**
- [ ] **Step 2: Run full pytest**

Run:
```bash
python scripts/check_no_secrets.py
pytest
```
Expected: both commands pass.

