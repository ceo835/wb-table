# Sheet Structure Sync Report

- Generated at: `2026-06-02T00:01:35`
- Mode: `apply`
- Real API / Google Sheets calls for data loading were not performed.
- Existing tab/data rows were not cleared.
- Mock/fake rows were not added.

## Existing tabs in project definitions

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

## Tabs added to canonical structure

- Validation_v1
- ИТОГО
- ИТОГО_FULL
- ВБро
- Точка вх
- Локализация
- Сравнение карточек

## Headers updated in canonical structure

- README
- Coverage
- Backlog
- Validation_v1
- ИТОГО
- ИТОГО_FULL
- ИТОГО_v1
- Воронка на день
- РасходРК
- РК стата
- ВБро
- Точка вх
- Локализация
- Сравнение карточек
- Поисковые запросы
- Остатки

## Processed schemas added or normalized

- dim_product
- fact_funnel_day
- fact_stock_snapshot
- fact_stock_day
- fact_ad_cost_event
- fact_ad_cost_day
- fact_ad_campaign_day
- fact_ad_campaign_nm_day
- fact_search_query_metric
- fact_profit_day
- fact_entry_point_day
- entry_points_wide
- fact_localization_region_day
- fact_localization_region_summary_day
- fact_card_comparison_metric
- fact_mpstat_item_day

## PARTIAL / LATER blocks

- ВБро
- Точка вх
- Локализация
- Сравнение карточек
- Поисковые запросы competitor percentiles
- ИТОГО / ИТОГО_FULL dynamic wide blocks

## Verification

- - Verification notes were not provided.

## Notes

- The report reflects project structure sync and planned Google Sheets header sync.
- Live spreadsheet presence/checks are only available when running this script with `--apply` and a configured spreadsheet ID.
- Data was not populated.
