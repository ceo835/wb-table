# API Enrichment Run Report

- Generated at: `2026-06-02T20:44:51+05:00`
- Period unchanged: `2026-05-31` .. `2026-06-01`.
- nmIDs unchanged: `197330807, 37320545, 37342770, 36387055, 577510563`.
- Raw/private payloads were not stored.
- Mock/fake rows were not added.

## Summary

- `Воронка на день` rows: `10`
- `Поисковые запросы` rows: `1000`
- `РК стата` rows: `155`
- `ВБро` rows: `10`
- `Локализация` rows: `228`
- `Coverage` rows: `11`
- `Backlog` rows: `9`
- `mock/fake` markers found: `0`

## Validations

- Воронка на день: 10 rows, duplicate keys=0, forbidden markers=0
- Поисковые запросы: 1000 rows, forbidden markers=0
- РК стата: 155 rows, forbidden markers=0
- Локализация: 228 rows, duplicate keys=0, forbidden markers=0
- ВБро: 10 rows, forbidden markers=0
- Coverage: 11 rows, headers intact=True
- Backlog: 9 rows, headers intact=True

## Field Coverage

| sheet_name | field_name | status | rows_updated | source_endpoint | details |
| --- | --- | --- | ---: | --- | --- |
| Воронка на день | confirmed enrichment | AVAILABLE | 10 | /api/analytics/v3/sales-funnel/products/history | previous-period metrics, WB Club fields, ratings, stocks, delivery time and localization were populated when the endpoint exposed them |
| Воронка на день | ad placeholders | PARTIAL | 10 | /api/analytics/v3/sales-funnel/products/history | ad proxy columns stay blank because they are not confirmed by the sales-funnel endpoint |
| Остатки | helper stock snapshot | PARTIAL | 5 | /api/v2/stocks-report/products/products | wb_stock_qty and stock_total_sum are confirmed; mp_stock_qty remains blank |
| РасходРК | cost allocation | PARTIAL/OK | 155 | /adv/v1/upd | nm_id parsing and click-campaign classification were normalized without changing spend values |
| РК стата | campaign/product metrics | AVAILABLE | 155 | /adv/v3/fullstats | live fullstats rows were written for campaign and product grains |
| РК стата | CPM / ROI | PARTIAL | 155 | /adv/v3/fullstats | CPM and ROI remain blank until the formula is explicitly confirmed |
| Поисковые запросы | core search metrics + reference fields | AVAILABLE | 1000 | /api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders | supplier_article, title, subject, brand, visibility, positions, clicks, carts, orders and conversion rates were populated |
| Поисковые запросы | competitor percentiles / min-max price | PARTIAL | 1000 | /api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders | competitor percentile fields and min/max discount prices stay blank because the source was not confirmed |
| ИТОГО_v1 | derived summary | PARTIAL | 10 | mixed | wide summary was refreshed from confirmed funnel, stock, search and ad sources |
| ВБро | financial base | PARTIAL | 10 | /api/v5/supplier/reportDetailByPeriod | profit base is preserved in processed data, while the operational profit cells stay blank |
| ВБро | operating profit | NEEDS_FORMULA_CONFIRMATION | 10 | /api/v5/supplier/reportDetailByPeriod | COGS and formula confirmation are still required before writing the profit cells |
| Локализация | regional sales rows | AVAILABLE | 228 | /api/v1/analytics/region-sale | regional sales feed is period-level; date is mapped to the window end and reference fields come from the existing funnel snapshot |
| Локализация | regional stock / delivery / local% | PARTIAL | 228 | /api/v1/analytics/region-sale | regional stock, delivery time and local/nonlocal percentages stay blank because the region-sale endpoint does not confirm them |
| Coverage | status refresh | OK | 11 | sheet write | coverage statuses were refreshed for the current enrichment scope |
| Backlog | canonical backlog | OK | 9 | sheet write | backlog is produced by the shared canonical builder and no longer depends on script order |
