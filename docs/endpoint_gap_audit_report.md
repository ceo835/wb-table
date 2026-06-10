# Endpoint Gap Audit Report

- Generated at: `2026-06-02T19:33:44`
- Test window: `2026-05-31` .. `2026-06-01`
- Test nmIDs: `197330807, 37320545, 37342770, 36387055, 577510563`
- Google Sheets were read only. No rows were written.
- WB / MPStat responses were summarized only. Raw private payloads were not saved.
- Mock/fake rows were not created.

## Block summary

| Block | Endpoint tested | Method | Status | HTTP | Fields found | Fields not found | Next step | Employee question |
|---|---|---|---|---|---|---|---|---|
| WB Content API / dim_product | /content/v2/get/cards/list | POST | PARTIAL | 200 | - | nm_id, vendorCode, title, subjectName, brand, photos, sizes | If cards/list remains empty, keep dim_product as a fallback from funnel/stocks and do not invent catalog data. | Is the current WB token supposed to have content access, or should catalog data stay on the fallback path? |
| Воронка на день | /api/analytics/v3/sales-funnel/products; /api/analytics/v3/sales-funnel/products/history | POST | PARTIAL | 200 | date, nm_id, impressions, cartCount, orderCount, orderSum, buyoutSum, cancelCount, cancelSum, avgPrice, avgOrdersCountPerDay, shareOrderPercent, addToWishlist, timeToReady, localizationPercent, wbClub, productRating, feedbackRating, stock_total_sum, past_period | card_clicks, wb_stock_qty, mp_stock_qty | Keep history for day-level rows and use products endpoint for the comparison block and extra funnel fields. | Need confirmation only if the products endpoint still omits past-period or localization fields. |
| Остатки | /api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups | POST/GET | PARTIAL | 200;200;405;400;200 | wb_stock_qty, stock_total_sum, saleRate, toClientCount, fromClientCount, availability, regionName, officeName, quantity, warehouse_id | mp_stock_qty, size, group | Keep the current stock snapshot for live tabs and use CSV history for historical stock rows. | Can the WB side confirm a public endpoint for MP stock qty or a regional/warehouse stock feed? |
| РК стата | /adv/v1/promotion/count; /adv/v1/upd; /adv/v3/fullstats | GET | PARTIAL | 200;200;200 | advertId, campaign_name, writeoff_datetime, document_number, spend, paymentType, advertType, advertStatus, date, row_type, conversion_type, nm_id, ad_spend, ad_revenue, views, clicks, atbs, orders, ctr, cpc, cr | cpm, roi | If fullstats stays null for the chosen windows, retry with another confirmed campaign set or confirm the exact campaign statuses that expose data. | Can you confirm a campaign set and window where fullstats is guaranteed to return rows? |
| Поисковые запросы | /api/v2/search-report/product/search-texts, /api/v2/search-report/product/orders, /api/v2/search-report/report, /api/v2/search-report/table/groups, /api/v2/search-report/table/details | POST | PARTIAL | 200;400;400;400;400 | search_query, query_count, visibility, visibility_prev, avg_position, avg_position_prev, median_position, median_position_prev, search_clicks, search_clicks_prev, search_clicks_competitor_percentile, search_cart, search_cart_prev, search_cart_competitor_percentile, cart_conversion, cart_conversion_prev, cart_conversion_competitor_percentile, search_orders, search_orders_prev, search_orders_competitor_percentile, order_conversion_prev | order_conversion, order_conversion_competitor_percentile, min_discount_price, max_discount_price | Keep search-texts and search-orders; competitor percentile columns likely need Jam/export or a private search report. | Do we have a supported export/private report for competitor percentiles and min/max discount price? |
| ВБро | /api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales | GET | NEEDS_FORMULA | 200;200;200 | date, nm_id, supplier_article, net_sales_payout, logistics, storage, penalties, deductions, acceptance | organic_sales_qty, ad_spend, cogs, other_costs, operating_profit, operating_profit_per_unit | Use reportDetailByPeriod as the finance base, but keep operating profit blank until COGS and the business formula are confirmed. | What is the approved COGS source and operating-profit formula? |
| Локализация | /api/v1/analytics/region-sale | GET | PARTIAL | 200 | countryName, foName, regionName, cityName, nmID, saleItemInvoiceQty, saleInvoiceCostPrice, saleInvoiceCostPricePerc | delivery_time, local_orders_percent, nonlocal_orders_percent, wb_stock_qty | Keep regional sales, but do not reuse total stock as regional stock until a proper feed is confirmed. | Is there a confirmed regional stock or delivery-time source, or should those columns stay blank? |
| Точка вх | /api/v2/nm-report/downloads; /api/v2/nm-report/downloads/file/{downloadId} | GET/POST | NOT_FOUND | 200;400;SKIPPED | - | download_list, stock_history_csv, entry_point_report_type | If no dedicated entry-point report is listed, keep this block as CSV_ONLY / private endpoint required. | Is there a confirmed CSV/export/private endpoint for the entry-point report type? |
| MPStat / Сравнение карточек | /item/197330807; /item/197330807/sales | GET | NOT_FOUND | REQUEST_ERROR;REQUEST_ERROR | - | nm_id, title, brand, sales, balance, search_position_avg, search_visibility, direct_competitor_feed | Verify the MPStat token, subscription, and endpoint contract before trying competitor comparison again. | Can you confirm the correct MPStat token/base URL and whether this plan includes item endpoints? |

## Field gaps

### WB Content API / dim_product :: nm_id

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/content/v2/get/cards/list`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: cards/list should expose nmId if the token/account has access
- Employee question: Need a confirmed content access scope or a different token category

### WB Content API / dim_product :: vendorCode

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/content/v2/get/cards/list`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: cards/list should expose vendorCode if the token/account has access
- Employee question: Need a confirmed content access scope or a different token category

### WB Content API / dim_product :: title

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/content/v2/get/cards/list`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: cards/list should expose title if the token/account has access
- Employee question: Need a confirmed content access scope or a different token category

### WB Content API / dim_product :: subjectName

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/content/v2/get/cards/list`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: cards/list should expose subjectName if the token/account has access
- Employee question: Need a confirmed content access scope or a different token category

### WB Content API / dim_product :: brand

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/content/v2/get/cards/list`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: cards/list should expose brand if the token/account has access
- Employee question: Need a confirmed content access scope or a different token category

### WB Content API / dim_product :: photos

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/content/v2/get/cards/list`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: cards/list should expose photos if the token/account has access
- Employee question: Need a confirmed content access scope or a different token category

### WB Content API / dim_product :: sizes

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/content/v2/get/cards/list`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: cards/list should expose sizes if the token/account has access
- Employee question: Need a confirmed content access scope or a different token category

### Воронка на день :: date

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path date`
- Next step: history date
- Employee question: Need to keep history output for daily granularity

### Воронка на день :: nm_id

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path nmId`
- Next step: WB nmId
- Employee question: Need to keep history output for daily granularity

### Воронка на день :: impressions

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path openCount`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: card_clicks

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: cartCount

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path cartCount`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: orderCount

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path orderCount`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: orderSum

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path orderSum`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: buyoutSum

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path buyoutSum`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: cancelCount

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path cancelCount`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: cancelSum

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path cancelSum`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: avgPrice

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path avgPrice`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: avgOrdersCountPerDay

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path avgOrdersCountPerDay`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: shareOrderPercent

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path shareOrderPercent`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: addToWishlist

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path addToWishlistCount`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: timeToReady

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path timeToReady`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: localizationPercent

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path localizationPercent`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: wbClub

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path wbClub`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: productRating

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path productRating`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: feedbackRating

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path feedbackRating`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: wb_stock_qty

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: mp_stock_qty

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: stock_total_sum

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path balanceSum`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Воронка на день :: past_period

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/analytics/v3/sales-funnel/products + /api/analytics/v3/sales-funnel/products/history`
- HTTP status: `200`
- Evidence: `found path past`
- Next step: Need to keep history output for daily granularity
- Employee question: confirm source if missing in history

### Остатки :: wb_stock_qty

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups`
- HTTP status: `200`
- Evidence: `found path stockCount`
- Next step: current snapshot from stock products
- Employee question: Need confirmation only if a regional breakdown is required

### Остатки :: mp_stock_qty

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: not confirmed in the live stock snapshot
- Employee question: Need a confirmed MP-stock or own-stock field from WB

### Остатки :: stock_total_sum

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups`
- HTTP status: `200`
- Evidence: `found path stockSum`
- Next step: current snapshot from stock products
- Employee question: Need confirmation only if a regional breakdown is required

### Остатки :: saleRate

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups`
- HTTP status: `200`
- Evidence: `found path saleRate`
- Next step: current snapshot from stock products
- Employee question: Need confirmation only if a regional breakdown is required

### Остатки :: toClientCount

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups`
- HTTP status: `200`
- Evidence: `found path toClientCount`
- Next step: current snapshot from stock products
- Employee question: Need confirmation only if a regional breakdown is required

### Остатки :: fromClientCount

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups`
- HTTP status: `200`
- Evidence: `found path fromClientCount`
- Next step: current snapshot from stock products
- Employee question: Need confirmation only if a regional breakdown is required

### Остатки :: availability

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups`
- HTTP status: `200`
- Evidence: `found path availability`
- Next step: current snapshot from stock products
- Employee question: Need confirmation only if a regional breakdown is required

### Остатки :: regionName

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups`
- HTTP status: `200`
- Evidence: `found path regionName`
- Next step: regional breakdown if offices/region endpoints return rows
- Employee question: Need confirmation only if regional stock is expected here

### Остатки :: officeName

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups`
- HTTP status: `200`
- Evidence: `found path officeName`
- Next step: regional breakdown if offices/region endpoints return rows
- Employee question: Need confirmation only if regional stock is expected here

### Остатки :: quantity

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups`
- HTTP status: `200`
- Evidence: `found path stockCount`
- Next step: regional breakdown if offices/region endpoints return rows
- Employee question: Need confirmation only if regional stock is expected here

### Остатки :: warehouse_id

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups`
- HTTP status: `200`
- Evidence: `found path officeID`
- Next step: warehouse ID may only be exposed in a report/export
- Employee question: Need a confirmed warehouse-level report if this is required

### Остатки :: size

- Status: `CSV_ONLY`
- Source type: `WB`
- Endpoint: `/api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: size-level stock breakdown may need a dedicated report/export
- Employee question: Need a confirmed size-level report if this is required

### Остатки :: group

- Status: `CSV_ONLY`
- Source type: `WB`
- Endpoint: `/api/v2/stocks-report/products/products; /api/v2/stocks-report/offices; /api/analytics/v1/stocks-report/wb-warehouses; /api/v2/stocks-report/products/sizes; /api/v2/stocks-report/products/groups`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: group-level stock breakdown may need a dedicated report/export
- Employee question: Need a confirmed group-level report if this is required

### РК стата :: advertId

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path advertId`
- Next step: use /adv/v1/promotion/count and /adv/v1/upd
- Employee question: Need a stable campaign-to-product mapping for nm_id

### РК стата :: campaign_name

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path campName`
- Next step: use /adv/v1/upd and/or count metadata
- Employee question: Need a confirmed campaign name source for the sheet

### РК стата :: writeoff_datetime

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path updTime`
- Next step: use /adv/v1/upd
- Employee question: Need to keep the time component instead of truncating to date

### РК стата :: document_number

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path updNum`
- Next step: use /adv/v1/upd
- Employee question: Need the document number to keep event-level uniqueness

### РК стата :: spend

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path updSum`
- Next step: use /adv/v1/upd
- Employee question: Need the spend amount as written-off sum

### РК стата :: paymentType

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path paymentType`
- Next step: use /adv/v1/upd
- Employee question: Need to confirm whether payment type can replace name parsing

### РК стата :: advertType

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path advertType`
- Next step: use /adv/v1/upd
- Employee question: Need to confirm whether campaign type can be mapped from advertType

### РК стата :: advertStatus

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path advertStatus`
- Next step: use /adv/v1/upd
- Employee question: Need to keep the campaign status for filters and backlog

### РК стата :: date

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path days/date`
- Next step: use /adv/v3/fullstats
- Employee question: Need the date grain from fullstats

### РК стата :: row_type

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path days/apps/appType`
- Next step: use /adv/v3/fullstats
- Employee question: Need to map the row type from nested fullstats structure

### РК стата :: conversion_type

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path days/apps/nms/name`
- Next step: use /adv/v3/fullstats
- Employee question: Need to clarify how the conversion type should be derived

### РК стата :: nm_id

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path days/apps/nms/nmId`
- Next step: use /adv/v3/fullstats
- Employee question: Need the campaign-product join to keep nm_id

### РК стата :: ad_spend

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path sum`
- Next step: use /adv/v3/fullstats
- Employee question: Need the spend metric from fullstats

### РК стата :: ad_revenue

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path sum_price`
- Next step: use /adv/v3/fullstats
- Employee question: Need the revenue metric from fullstats

### РК стата :: views

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path views`
- Next step: use /adv/v3/fullstats
- Employee question: Need the views metric from fullstats

### РК стата :: clicks

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path clicks`
- Next step: use /adv/v3/fullstats
- Employee question: Need the clicks metric from fullstats

### РК стата :: atbs

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path atbs`
- Next step: use /adv/v3/fullstats
- Employee question: Need the atbs metric from fullstats

### РК стата :: orders

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path orders`
- Next step: use /adv/v3/fullstats
- Employee question: Need the orders metric from fullstats

### РК стата :: ctr

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path ctr`
- Next step: use /adv/v3/fullstats
- Employee question: Need the CTR metric from fullstats

### РК стата :: cpc

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path cpc`
- Next step: use /adv/v3/fullstats
- Employee question: Need the CPC metric from fullstats

### РК стата :: cpm

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: use /adv/v3/fullstats
- Employee question: Need the CPM metric from fullstats

### РК стата :: cr

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `found path cr`
- Next step: use /adv/v3/fullstats
- Employee question: Need the CR metric from fullstats

### РК стата :: roi

- Status: `NEEDS_FORMULA`
- Source type: `WB`
- Endpoint: `/adv/v1/upd; /adv/v3/fullstats`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: ROI may need a business formula if the endpoint does not expose it directly
- Employee question: Need confirmation of the business ROI formula if not returned directly

### Поисковые запросы :: search_query

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path text`
- Next step: use search-texts/search-orders plus maybe CSV export
- Employee question: Need to confirm the source of any missing competitor-derived query values

### Поисковые запросы :: query_count

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path frequency`
- Next step: use search-texts/search-orders plus maybe CSV export
- Employee question: Need to confirm whether frequency should come from current or weekly period

### Поисковые запросы :: visibility

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path visibility`
- Next step: use search-texts/search-orders plus maybe CSV export
- Employee question: Need to confirm whether visibility is available directly or only via Jam/export

### Поисковые запросы :: visibility_prev

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path visibility/dynamics`
- Next step: previous period can be reconstructed from current and dynamics
- Employee question: Need confirmation only if a direct previous-period field is required

### Поисковые запросы :: avg_position

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path avgPosition`
- Next step: use search-texts/search-orders plus maybe CSV export
- Employee question: Need to confirm if search-report/table/* returns a better position source

### Поисковые запросы :: avg_position_prev

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path avgPosition/dynamics`
- Next step: previous period can be reconstructed from current and dynamics
- Employee question: Need confirmation only if a direct previous-period field is required

### Поисковые запросы :: median_position

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path medianPosition`
- Next step: use search-texts/search-orders plus maybe CSV export
- Employee question: Need to confirm if search-report/table/* returns a better position source

### Поисковые запросы :: median_position_prev

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path medianPosition/dynamics`
- Next step: previous period can be reconstructed from current and dynamics
- Employee question: Need confirmation only if a direct previous-period field is required

### Поисковые запросы :: search_clicks

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path openCard`
- Next step: use search-texts/search-orders plus maybe CSV export
- Employee question: Need confirmation only if a direct search-report endpoint is expected

### Поисковые запросы :: search_clicks_prev

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path openCard/dynamics`
- Next step: previous period can be reconstructed from current and dynamics
- Employee question: Need confirmation only if a direct previous-period field is required

### Поисковые запросы :: search_clicks_competitor_percentile

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path openCard/percentile`
- Next step: competitor percentile likely comes from Jam/export or a private report
- Employee question: Is there a CSV/UI export for competitor percentiles?

### Поисковые запросы :: search_cart

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path addToCart`
- Next step: use search-texts/search-orders plus maybe CSV export
- Employee question: Need confirmation only if a direct search-report endpoint is expected

### Поисковые запросы :: search_cart_prev

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path addToCart/dynamics`
- Next step: previous period can be reconstructed from current and dynamics
- Employee question: Need confirmation only if a direct previous-period field is required

### Поисковые запросы :: search_cart_competitor_percentile

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path addToCart/percentile`
- Next step: competitor percentile likely comes from Jam/export or a private report
- Employee question: Is there a CSV/UI export for competitor percentiles?

### Поисковые запросы :: cart_conversion

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path cartToOrder`
- Next step: use search-texts/search-orders plus maybe CSV export
- Employee question: Need confirmation only if a direct search-report endpoint is expected

### Поисковые запросы :: cart_conversion_prev

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path cartToOrder/dynamics`
- Next step: previous period can be reconstructed from current and dynamics
- Employee question: Need confirmation only if a direct previous-period field is required

### Поисковые запросы :: cart_conversion_competitor_percentile

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path cartToOrder/percentile`
- Next step: competitor percentile likely comes from Jam/export or a private report
- Employee question: Is there a CSV/UI export for competitor percentiles?

### Поисковые запросы :: search_orders

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path orders`
- Next step: use search-texts/search-orders plus maybe CSV export
- Employee question: Need confirmation only if a direct search-report endpoint is expected

### Поисковые запросы :: search_orders_prev

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path orders/dynamics`
- Next step: previous period can be reconstructed from current and dynamics
- Employee question: Need confirmation only if a direct previous-period field is required

### Поисковые запросы :: search_orders_competitor_percentile

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `found path orders/percentile`
- Next step: competitor percentile likely comes from Jam/export or a private report
- Employee question: Is there a CSV/UI export for competitor percentiles?

### Поисковые запросы :: order_conversion

- Status: `CSV_ONLY`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `not found in tested response`
- Next step: requires a dedicated report/table endpoint if it is not returned by search-texts
- Employee question: Does a search report endpoint expose order conversion directly?

### Поисковые запросы :: order_conversion_prev

- Status: `NEEDS_FORMULA`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `not found in tested response`
- Next step: previous period can be reconstructed from current and dynamics
- Employee question: Need confirmation only if a direct previous-period field is required

### Поисковые запросы :: order_conversion_competitor_percentile

- Status: `CSV_ONLY`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `not found in tested response`
- Next step: competitor percentile likely comes from Jam/export or a private report
- Employee question: Is there a CSV/UI export for competitor percentiles?

### Поисковые запросы :: min_discount_price

- Status: `CSV_ONLY`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `not found in tested response`
- Next step: likely available only through a table/export report
- Employee question: Does search-report/table/details expose min/max discount price?

### Поисковые запросы :: max_discount_price

- Status: `CSV_ONLY`
- Source type: `WB`
- Endpoint: `/api/v2/search-report/product/search-texts; /api/v2/search-report/product/orders; /api/v2/search-report/report; /api/v2/search-report/table/groups; /api/v2/search-report/table/details`
- HTTP status: `200;400;400;400;400`
- Evidence: `not found in tested response`
- Next step: likely available only through a table/export report
- Employee question: Does search-report/table/details expose min/max discount price?

### ВБро :: date

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales`
- HTTP status: `200`
- Evidence: `found path sale_dt`
- Next step: finance base from reportDetailByPeriod and orders/sales
- Employee question: Need a stable line date for aggregation

### ВБро :: nm_id

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales`
- HTTP status: `200`
- Evidence: `found path nm_id`
- Next step: finance base from reportDetailByPeriod and orders/sales
- Employee question: Need a stable nm_id for aggregation

### ВБро :: supplier_article

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales`
- HTTP status: `200`
- Evidence: `found path sa_name`
- Next step: finance base from reportDetailByPeriod and orders/sales
- Employee question: Need supplier article for VBro and matching with funnel/stock reference

### ВБро :: organic_sales_qty

- Status: `NEEDS_FORMULA`
- Source type: `FORMULA`
- Endpoint: `/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: could be derived only with a confirmed formula
- Employee question: What is the agreed formula for organic sales quantity?

### ВБро :: net_sales_payout

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales`
- HTTP status: `200`
- Evidence: `found path ppvz_for_pay`
- Next step: reportDetailByPeriod and sales/orders give the finance base
- Employee question: Need the agreed base payout metric for VBro

### ВБро :: ad_spend

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: use promotion costs / writeoff feed
- Employee question: Need to confirm whether ad spend should be linked by advertId or allocated to nm_id

### ВБро :: logistics

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales`
- HTTP status: `200`
- Evidence: `found path delivery_rub`
- Next step: reportDetailByPeriod gives the logistics base
- Employee question: Need to confirm whether logistics should use delivery_rub only or a broader formula

### ВБро :: storage

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales`
- HTTP status: `200`
- Evidence: `found path storage_fee`
- Next step: reportDetailByPeriod gives the storage base
- Employee question: Need to confirm whether storage should include all holding fees

### ВБро :: penalties

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales`
- HTTP status: `200`
- Evidence: `found path penalty`
- Next step: reportDetailByPeriod gives the penalty base
- Employee question: Need to confirm whether penalties should include deductions/withholds

### ВБро :: deductions

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales`
- HTTP status: `200`
- Evidence: `found path deduction`
- Next step: reportDetailByPeriod gives the deduction base
- Employee question: Need to confirm whether deductions should include all удержания

### ВБро :: acceptance

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales`
- HTTP status: `200`
- Evidence: `found path acceptance`
- Next step: reportDetailByPeriod gives the acceptance base
- Employee question: Need to confirm whether acceptance should be included as a separate cost line

### ВБро :: cogs

- Status: `NEEDS_FORMULA`
- Source type: `EXTERNAL_SOURCE`
- Endpoint: `/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: COGS is not available from WB API
- Employee question: What is the approved COGS source?

### ВБро :: other_costs

- Status: `NEEDS_FORMULA`
- Source type: `FORMULA`
- Endpoint: `/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: other costs are not directly exposed by WB API
- Employee question: What formula should be used for other costs?

### ВБро :: operating_profit

- Status: `NEEDS_FORMULA`
- Source type: `FORMULA`
- Endpoint: `/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: requires COGS and a confirmed business formula
- Employee question: What is the approved operating profit formula?

### ВБро :: operating_profit_per_unit

- Status: `NEEDS_FORMULA`
- Source type: `FORMULA`
- Endpoint: `/api/v5/supplier/reportDetailByPeriod; /api/v1/supplier/orders; /api/v1/supplier/sales`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: requires operating profit and a unit formula
- Employee question: What is the approved unit-profit formula?

### Локализация :: countryName

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v1/analytics/region-sale`
- HTTP status: `200`
- Evidence: `found path countryName`
- Next step: regional sales feed
- Employee question: Need confirmation only if the country dimension is required

### Локализация :: foName

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v1/analytics/region-sale`
- HTTP status: `200`
- Evidence: `found path foName`
- Next step: regional sales feed
- Employee question: Need confirmation only if the federal district dimension is required

### Локализация :: regionName

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v1/analytics/region-sale`
- HTTP status: `200`
- Evidence: `found path regionName`
- Next step: regional sales feed
- Employee question: Need confirmation only if the region dimension is required

### Локализация :: cityName

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v1/analytics/region-sale`
- HTTP status: `200`
- Evidence: `found path cityName`
- Next step: regional sales feed
- Employee question: Need confirmation only if the city dimension is required

### Локализация :: nmID

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v1/analytics/region-sale`
- HTTP status: `200`
- Evidence: `found path nmID`
- Next step: regional sales feed
- Employee question: Need confirmation only if the nmID dimension is required

### Локализация :: saleItemInvoiceQty

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v1/analytics/region-sale`
- HTTP status: `200`
- Evidence: `found path saleItemInvoiceQty`
- Next step: regional sales feed
- Employee question: Need confirmation only if the regional sales metric is required

### Локализация :: saleInvoiceCostPrice

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v1/analytics/region-sale`
- HTTP status: `200`
- Evidence: `found path saleInvoiceCostPrice`
- Next step: regional sales feed
- Employee question: Need confirmation only if the cost metric is required

### Локализация :: saleInvoiceCostPricePerc

- Status: `FOUND`
- Source type: `WB`
- Endpoint: `/api/v1/analytics/region-sale`
- HTTP status: `200`
- Evidence: `found path saleInvoiceCostPricePerc`
- Next step: regional sales feed
- Employee question: Need confirmation only if the percent metric is required

### Локализация :: delivery_time

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/api/v1/analytics/region-sale`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: regional sales feed does not confirm delivery time
- Employee question: Need a confirmed source or accepted business rule for delivery time

### Локализация :: local_orders_percent

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/api/v1/analytics/region-sale`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: regional sales feed does not confirm local/nonlocal KPI
- Employee question: Need a confirmed business formula for local/nonlocal orders

### Локализация :: nonlocal_orders_percent

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/api/v1/analytics/region-sale`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: regional sales feed does not confirm local/nonlocal KPI
- Employee question: Need a confirmed business formula for local/nonlocal orders

### Локализация :: wb_stock_qty

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/api/v1/analytics/region-sale`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: regional stock cannot be inferred from total WB stock
- Employee question: Need a confirmed regional stock source

### Точка вх :: download_list

- Status: `PARTIAL`
- Source type: `WB`
- Endpoint: `/api/v2/nm-report/downloads; /api/v2/nm-report/downloads/file/{downloadId}`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: nm-report/downloads list endpoint
- Employee question: Need a confirmed report type if entry points should be automated

### Точка вх :: stock_history_csv

- Status: `CSV_ONLY`
- Source type: `WB`
- Endpoint: `/api/v2/nm-report/downloads; /api/v2/nm-report/downloads/file/{downloadId}`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: stock history is already proven as CSV-only in the project
- Employee question: Need a CSV flow if historical stock rows are required

### Точка вх :: entry_point_report_type

- Status: `NOT_FOUND`
- Source type: `WB`
- Endpoint: `/api/v2/nm-report/downloads; /api/v2/nm-report/downloads/file/{downloadId}`
- HTTP status: `200`
- Evidence: `not found in tested response`
- Next step: entry-point report type was not confirmed in the downloads list
- Employee question: Need a confirmed CSV/export/private endpoint for entry points

### MPStat / Сравнение карточек :: nm_id

- Status: `NEEDS_ACCESS`
- Source type: `MPSTAT`
- Endpoint: `/item/197330807; /item/197330807/sales`
- HTTP status: `REQUEST_ERROR`
- Evidence: `not found in tested response`
- Next step: MPStat is blocked until auth succeeds
- Employee question: Need a valid MPStat token/base-url combination

### MPStat / Сравнение карточек :: title

- Status: `NEEDS_ACCESS`
- Source type: `MPSTAT`
- Endpoint: `/item/197330807; /item/197330807/sales`
- HTTP status: `REQUEST_ERROR`
- Evidence: `not found in tested response`
- Next step: MPStat is blocked until auth succeeds
- Employee question: Need a valid MPStat token/base-url combination

### MPStat / Сравнение карточек :: brand

- Status: `NEEDS_ACCESS`
- Source type: `MPSTAT`
- Endpoint: `/item/197330807; /item/197330807/sales`
- HTTP status: `REQUEST_ERROR`
- Evidence: `not found in tested response`
- Next step: MPStat is blocked until auth succeeds
- Employee question: Need a valid MPStat token/base-url combination

### MPStat / Сравнение карточек :: sales

- Status: `NEEDS_ACCESS`
- Source type: `MPSTAT`
- Endpoint: `/item/197330807; /item/197330807/sales`
- HTTP status: `REQUEST_ERROR`
- Evidence: `not found in tested response`
- Next step: MPStat item sales is blocked until auth succeeds
- Employee question: Need a valid MPStat token/base-url combination

### MPStat / Сравнение карточек :: balance

- Status: `NEEDS_ACCESS`
- Source type: `MPSTAT`
- Endpoint: `/item/197330807; /item/197330807/sales`
- HTTP status: `REQUEST_ERROR`
- Evidence: `not found in tested response`
- Next step: MPStat item sales is blocked until auth succeeds
- Employee question: Need a valid MPStat token/base-url combination

### MPStat / Сравнение карточек :: search_position_avg

- Status: `NEEDS_ACCESS`
- Source type: `MPSTAT`
- Endpoint: `/item/197330807; /item/197330807/sales`
- HTTP status: `REQUEST_ERROR`
- Evidence: `not found in tested response`
- Next step: MPStat item sales is blocked until auth succeeds
- Employee question: Need a valid MPStat token/base-url combination

### MPStat / Сравнение карточек :: search_visibility

- Status: `NEEDS_ACCESS`
- Source type: `MPSTAT`
- Endpoint: `/item/197330807; /item/197330807/sales`
- HTTP status: `REQUEST_ERROR`
- Evidence: `not found in tested response`
- Next step: MPStat item sales is blocked until auth succeeds
- Employee question: Need a valid MPStat token/base-url combination

### MPStat / Сравнение карточек :: direct_competitor_feed

- Status: `NEEDS_ACCESS`
- Source type: `MPSTAT`
- Endpoint: `/item/197330807; /item/197330807/sales`
- HTTP status: `REQUEST_ERROR`
- Evidence: `not found in tested response`
- Next step: competitor feed not assembled from tested endpoints
- Employee question: Need a valid MPStat token/base-url combination

## Safety confirmation

- Google Sheets were not populated.
- Existing Google Sheets data was not cleared.
- WB / MPStat write actions were not executed.
- Full pipeline was not started.
