# Google Sheets Live Structure Sync Report

- Generated at: `2026-06-01T23:56:00`
- Mode: `live-apply`
- Live Google Sheets structure sync was executed.
- Real API / Google Sheets data loading was not performed.
- WB / MPStat API calls were not performed.
- Existing tab/data rows were not cleared.
- Mock/fake rows were not added.

## Current sheets found in live spreadsheet

- README
- API Smoke Test
- Coverage
- Raw Samples Summary
- dim_product
- Воронка на день
- РасходРК
- РК стата
- Поисковые запросы
- Остатки
- Missing fields
- ИТОГО_v1
- Backlog
- Validation_v1
- ИТОГО
- ИТОГО_FULL
- ВБро
- Точка вх
- Локализация
- Сравнение карточек

## Sheets created during live apply

- none

## Header row updates applied

- none

## Sheets not touched

- README
- API Smoke Test
- Coverage
- Raw Samples Summary
- dim_product
- Воронка на день
- РасходРК
- РК стата
- Поисковые запросы
- Остатки
- Missing fields
- ИТОГО_v1
- Backlog
- Validation_v1
- ИТОГО
- ИТОГО_FULL
- ВБро
- Точка вх
- Локализация
- Сравнение карточек

## Apply result

- Live dry-run against Google Sheets returned zero-diff.
- `python scripts/sync_sheet_structure.py --apply` completed with `Applied actions: 0`.
- Required tabs already existed.
- Canonical header rows already matched the schema definitions.

## Safety confirmation

- Existing data rows were not cleared.
- Worksheet bodies were not overwritten.
- Only header-only sync logic was allowed.
- Mock/fake rows were not added.
- WB / MPStat real-api pipeline was not executed.

## Verification

- `python scripts/check_no_secrets.py`: passed
- `pytest`: passed
- Existing warnings remain in `scripts/audit_smoke_test.py` where pytest functions return dictionaries instead of asserting.
