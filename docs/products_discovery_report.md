# Products Discovery Report

- Режим: `apply`
- Период live-источников: `2026-05-31 .. 2026-06-01`
- Всего уникальных nm_id: **248**
- Товаров без supplier_article: **0**
- Товаров без title: **2**
- Товаров, уже встречающихся в fact-таблицах: **49**
- Записано/обновлено в settings_products: **248**
- Всего строк в settings_products после запуска: **248**

## Источники

| Источник | Статус | Rows observed | Unique nm_id | Ошибка |
|---|---:|---:|---:|---|
| WB Content API | OK | 248 | 248 |  |
| WB Sales Funnel | OK | 10 | 5 |  |
| WB Stocks | OK | 5 | 5 |  |
| WB Promotion costs | OK | 155 | 49 |  |
| WB Promotion fullstats | OK | 141 | 5 |  |
| WB Search queries | OK | 1000 | 5 | 200 |
| Excel/xlsm | EMPTY | 0 | 0 |  |
| DB fact_funnel_day | OK | 10 | 5 |  |
| DB fact_stock_snapshot | OK | 5 | 5 |  |
| DB fact_ad_cost_event | OK | 155 | 49 |  |
| DB fact_ad_cost_day | OK | 116 | 49 |  |
| DB fact_ad_campaign_nm_day | OK | 141 | 5 |  |
| DB fact_search_query_metric | OK | 1000 | 5 |  |
| DB fact_localization_region_day | OK | 228 | 5 |  |

## Источники, которые не сработали

- Нет
