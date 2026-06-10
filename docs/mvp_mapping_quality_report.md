# MVP Mapping Quality Report

- Generated at: `2026-06-02T16:12:51+05:00`
- Scope: clean-write mapping quality after MVP rerun on `2026-05-31 .. 2026-06-01`.
- Goal: keep write paths clean, enrich `ИТОГО_v1`, and prevent malformed ad spend parsing.

## Written Tabs

- `Воронка на день`: 10 rows
- `Остатки`: 5 rows
- `РасходРК`: 155 rows
- `Поисковые запросы`: 1000 rows
- `ИТОГО_v1`: 10 rows
- `Backlog`: 5 rows

## Quality Checks

- `Воронка на день` / `header_match`: `PASS` (0 issues)
- `Воронка на день` / `rows_written`: `PASS` (0 issues)
- `Воронка на день` / `no_mock_fake`: `PASS` (0 issues)
- `Остатки` / `header_match`: `PASS` (0 issues)
- `Остатки` / `rows_written`: `PASS` (0 issues)
- `Остатки` / `no_mock_fake`: `PASS` (0 issues)
- `РасходРК` / `header_match`: `PASS` (0 issues)
- `РасходРК` / `rows_written`: `PASS` (0 issues)
- `РасходРК` / `no_mock_fake`: `PASS` (0 issues)
- `Поисковые запросы` / `header_match`: `PASS` (0 issues)
- `Поисковые запросы` / `rows_written`: `PASS` (0 issues)
- `Поисковые запросы` / `no_mock_fake`: `PASS` (0 issues)
- `ИТОГО_v1` / `header_match`: `PASS` (0 issues)
- `ИТОГО_v1` / `rows_written`: `PASS` (0 issues)
- `ИТОГО_v1` / `no_mock_fake`: `PASS` (0 issues)
- `Backlog` / `header_match`: `PASS` (0 issues)
- `Backlog` / `rows_written`: `PASS` (0 issues)
- `Backlog` / `no_mock_fake`: `PASS` (0 issues)
- `Validation_v1` / `not_touched`: `SKIPPED` (0 issues)
- `Воронка на день` / `required_keys`: `PASS` (0 issues)
- `Воронка на день` / `unique_Дата_Артикул WB`: `PASS` (0 issues)
- `Воронка на день` / `no_leading_zero_decimals`: `PASS` (0 issues)
- `ИТОГО_v1` / `required_keys`: `PASS` (0 issues)
- `ИТОГО_v1` / `unique_date_nm_id`: `PASS` (0 issues)
- `ИТОГО_v1` / `fact_funnel_relation`: `PASS` (0 issues)
- `ИТОГО_v1` / `no_leading_zero_decimals`: `PASS` (0 issues)
- `ИТОГО_v1` / `reference_fields_match`: `PASS` (0 issues)
- `РасходРК` / `nm_id_parse_status_rules`: `PASS` (0 issues)
- `РасходРК` / `campaign_type_rules`: `PASS` (0 issues)

## Notes

- `ИТОГО_v1` now copies `supplier_article`, `title`, `subject`, and `brand` from funnel/product or stock references when available.
- Percent-like values are normalized before write, so the sheet should not show leading-zero decimals such as `09.04`.
- `РасходРК` uses `FROM_CAMPAIGN_NAME`, `FROM_SECTION`, or `NOT_FOUND` for `nm_id_parse_status`.
- `campaign_type` is derived from campaign name and should not contain raw section values.
