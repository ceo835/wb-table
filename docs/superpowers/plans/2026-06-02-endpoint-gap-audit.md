# Endpoint Gap Audit Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Produce a read-only endpoint-gap audit for the current WB/MPStat setup and save a safe report set without writing to Google Sheets.

**Architecture:** Add one standalone audit runner under `scripts/` that performs direct read-only requests against the confirmed WB/MPStat endpoints, extracts presence/absence of the required fields, and writes markdown/CSV/JSON reports into `docs/` and `data/processed/`. Keep the runner isolated from the live pipelines and reuse existing auth/config helpers from `src/config/settings.py` plus the shared request patterns already used by `scripts/real_api_smoke_test.py`.

**Tech Stack:** Python, `requests`, existing WB/MPStat clients/helpers, `pytest`.

---

### Task 1: Add a standalone endpoint-gap audit runner

**Files:**
- Create: `scripts/endpoint_gap_audit.py`
- Modify: `src/config/settings.py` only if a missing setting accessor is required

- [ ] **Step 1: Define the audit record model and endpoint checks**

```python
from dataclasses import dataclass

@dataclass
class GapAuditRow:
    block: str
    field: str
    status: str
    source_type: str
    endpoint: str
    http_status: str
    evidence_short: str
    next_step: str
    employee_question: str
```

- [ ] **Step 2: Implement read-only requests for the documented endpoints**

Use the same window and nmID sample already established in the project:
`2026-05-31 .. 2026-06-01`, `197330807, 37320545, 37342770, 36387055, 577510563`.

Cover:
- `sales-funnel/products`
- `sales-funnel/products/history`
- `search-texts`
- `search-orders`
- `search-report/report`
- `search-report/table/groups`
- `search-report/table/details`
- `adv/v1/promotion/count`
- `adv/v3/fullstats`
- `adv/v1/upd`
- `stocks-report/products/products`
- `stocks-report/offices`
- `analytics/v1/stocks-report/wb-warehouses`
- `stocks-report/products/sizes`
- `stocks-report/products/groups`
- `analytics/v1/analytics/region-sale`
- `statistics-api/api/v5/supplier/reportDetailByPeriod`
- `statistics-api/api/v1/supplier/orders`
- `statistics-api/api/v1/supplier/sales`
- `content/v2/get/cards/list`
- `nm-report/downloads`
- `nm-report/downloads/file/{downloadId}`
- `MPStat item full`
- `MPStat item sales`
- `MPStat category/items` if auth succeeds

- [ ] **Step 3: Extract fields and classify gaps**

Use recursive key search and path checks to fill:
- `status`: `FOUND`, `PARTIAL`, `NOT_FOUND`, `NEEDS_FORMULA`, `NEEDS_ACCESS`, `CSV_ONLY`
- `fields_found`
- `fields_not_found`
- `next_step`
- `employee_question`

Keep the output safe: no raw response bodies in the final artifacts.

- [ ] **Step 4: Write reports**

Create:
- `docs/endpoint_gap_audit_report.md`
- `data/processed/endpoint_gap_audit_report.csv`
- `data/processed/endpoint_gap_audit_summary.json`

The markdown report should be block-oriented. The CSV should be field-oriented with one row per field gap/result.

---

### Task 2: Add test coverage for the audit helpers

**Files:**
- Create: `tests/test_endpoint_gap_audit.py`

- [ ] **Step 1: Add tests for recursive field detection and status mapping**

Cover:
- nested key detection for WB/MPStat response shapes
- `FOUND` vs `PARTIAL` vs `NEEDS_ACCESS`
- classification for CSV-only and formula-only gaps

Example cases:
- `search-texts` payload includes `visibility`, `avgPosition`, `medianPosition`, `clicks`, `carts`, `orders`
- `fullstats` payload with `null` body remains `PARTIAL`
- `mpstat` `401` maps to `NEEDS_ACCESS`

- [ ] **Step 2: Verify the test file does not require network**

Run:
`pytest tests/test_endpoint_gap_audit.py -q`

Expected:
all tests pass using synthetic payloads only

---

### Task 3: Execute the audit and verify the safe outputs

**Files:**
- Generated: `docs/endpoint_gap_audit_report.md`
- Generated: `data/processed/endpoint_gap_audit_report.csv`
- Generated: `data/processed/endpoint_gap_audit_summary.json`

- [ ] **Step 1: Run the audit runner**

Run:
`python scripts/endpoint_gap_audit.py`

Expected:
reports are written, no Google Sheets writes occur, no raw payload files are added

- [ ] **Step 2: Run safety and test checks**

Run:
`python scripts/check_no_secrets.py`
`pytest`

Expected:
no secrets detected; test suite passes

- [ ] **Step 3: Review the final report contents**

Confirm the report states:
- which fields can be filled from existing WB/MPStat endpoints
- which fields require CSV/export/private endpoints
- which fields require formulas or employee confirmation
- that Google Sheets were not written

---

### Self-Review

**Spec coverage**
- WB funnel endpoints, search endpoints, ads endpoints, stocks endpoints, localization, finance, content, CSV download flow, and MPStat are all covered by Task 1.
- Safe report generation is covered by Task 1 and Task 3.
- Non-network tests are covered by Task 2.

**Placeholder scan**
- No TBD/TODO placeholders left in the plan.

**Type consistency**
- The same block names and statuses are used consistently across the plan, tests, and report outputs.

