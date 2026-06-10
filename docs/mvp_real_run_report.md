# MVP Real Run Report

- Generated at: `2026-06-02T21:41:39+05:00`
- Date window written: `2026-05-31` .. `2026-06-01`
- Test nmIDs: `197330807, 37320545, 37342770, 36387055, 577510563`
- WB/MPStat responses were consumed read-only; raw private payloads were not saved.
- Existing sheet rows were not cleared.
- Mock/fake rows were not created by this run.

## Filled tabs

- `Воронка на день`: 10 rows, `PARTIAL`
- `Остатки`: 5 rows, `PARTIAL`
- `РасходРК`: 155 rows, `PARTIAL`
- `РК стата`: 155 rows, `PARTIAL`
- `Поисковые запросы`: 1000 rows, `PARTIAL`
- `ИТОГО_v1`: 10 rows, `PARTIAL`
- `Backlog`: 9 rows, `OK`

## Source results

### Google Sheets

- Endpoint: `spreadsheet metadata`
- Method: `GET`
- Status: `OK`
- HTTP status: `200`
- Objects count: `20`
- Fields found: `spreadsheet_id, tabs`
- Fields missing: `-`
- Rows written: `0`
- Notes: `read-only check`
- Error: `-`

### WB Content API

- Endpoint: `/content/v2/get/cards/list`
- Method: `POST`
- Status: `PARTIAL`
- HTTP status: `200`
- Objects count: `0`
- Fields found: `-`
- Fields missing: `nm_id, vendorCode, title, subject, brand`
- Rows written: `0`
- Notes: `empty cards list is treated as PARTIAL for this account`
- Error: `-`

### WB Sales Funnel

- Endpoint: `/api/analytics/v3/sales-funnel/products/history`
- Method: `POST`
- Status: `PARTIAL`
- HTTP status: `200`
- Objects count: `10`
- Fields found: `date, nm_id, impressions, card_clicks, cartCount, orderCount, orderSum, buyoutSum`
- Fields missing: `-`
- Rows written: `10`
- Notes: `window written by day with previous-day comparison where available`
- Error: `-`

### WB Stocks products

- Endpoint: `/api/v2/stocks-report/products/products`
- Method: `POST`
- Status: `PARTIAL`
- HTTP status: `200`
- Objects count: `5`
- Fields found: `snapshot_date, nm_id, wb_stock_qty, stock_total_sum`
- Fields missing: `mp_stock_qty`
- Rows written: `5`
- Notes: `current snapshot only; mp_stock_qty remains partial`
- Error: `-`

### WB Promotion costs

- Endpoint: `/adv/v1/upd`
- Method: `GET`
- Status: `PARTIAL`
- HTTP status: `200`
- Objects count: `155`
- Fields found: `advertId, campName, updTime, updSum, updNum`
- Fields missing: `nm_id`
- Rows written: `155`
- Notes: `event-level spend rows written without clearing the sheet`
- Error: `-`

### WB Promotion fullstats

- Endpoint: `/adv/v3/fullstats`
- Method: `GET`
- Status: `PARTIAL`
- HTTP status: `200`
- Objects count: `155`
- Fields found: `date, advertId, campaign_name, row_type, conversion_type, nm_id, ad_spend, ad_revenue, ad_views, ad_clicks, ad_atbs, ad_orders, ad_cancels, avg_position, ad_ctr, ad_cpc, ad_cr`
- Fields missing: `ad_cpm, ad_roi`
- Rows written: `155`
- Notes: `live fullstats rows written; CPM and ROI remain blank until a formula is confirmed`
- Error: `-`

### WB Search texts

- Endpoint: `/api/v2/search-report/product/search-texts`
- Method: `POST`
- Status: `PARTIAL`
- HTTP status: `200`
- Objects count: `1000`
- Fields found: `search_query, query_count, visibility, avg_position, median_position, search_clicks, search_cart, search_orders`
- Fields missing: `competitor_percentiles, min_discount_price, max_discount_price`
- Rows written: `1000`
- Notes: `current day written with previous-period comparison`
- Error: `-`

### WB Analytics + WB Promotion + WB Stocks + WB Search

- Endpoint: `mixed`
- Method: `MIXED`
- Status: `PARTIAL`
- HTTP status: `200`
- Objects count: `10`
- Fields found: `date, nm_id, impressions, card_clicks, orderCount, current_stockCount, search_queries_count`
- Fields missing: `title, subject, brand, ad_views, ad_clicks, ad_orders, ad_atbs`
- Rows written: `10`
- Notes: `wide MVP sheet built from confirmed live sources only`
- Error: `-`

### Backlog

- Endpoint: `sheet append`
- Method: `WRITE`
- Status: `OK`
- HTTP status: `200`
- Objects count: `9`
- Fields found: `-`
- Fields missing: `-`
- Rows written: `9`
- Notes: `appended live-run blockers and later items`
- Error: `-`

### MPStat

- Endpoint: `/item/{nm_id}`
- Method: `GET`
- Status: `FAIL`
- HTTP status: `401`
- Objects count: `0`
- Fields found: `-`
- Fields missing: `nm_id, title, brand`
- Rows written: `0`
- Notes: `connectivity/auth check only`
- Error: `{"code":401,"message":"Authorization Required"}`

## Backlog

- `WB Content API / dim_product` | `PARTIAL` | live content cards response is empty for the current token/account; real rows were not invented | next: recheck catalog access or keep dim_product on confirmed content data only
- `ВБро` | `NEEDS_FORMULA_CONFIRMATION` | operating profit still needs external COGS and a confirmed formula | next: confirm cost-of-goods source and unit-economics formula before filling profit cells
- `Локализация` | `PARTIAL` | regional stock is left blank unless confirmed; local/nonlocal KPI and delivery time remain unconfirmed | next: confirm the exact WB localization KPI or approved CSV export
- `РК стата` | `PARTIAL` | fullstats now returns live rows, but CPM and ROI remain unconfirmed | next: keep the live fullstats rows and leave CPM/ROI blank until an explicit formula is approved
- `MPStat / Сравнение карточек` | `MPSTAT_401` | authentication still returns 401 on the smoke check | next: verify MPStat token, plan, and endpoint contract
- `Точка вх` | `CSV_ONLY / PRIVATE_ENDPOINT` | no public endpoint was confirmed in the current audit run | next: confirm CSV/export/private endpoint before attempting fill
- `Поисковые запросы` | `PARTIAL` | reference fields are enriched, but competitor percentiles and exact search-position sources remain unconfirmed | next: confirm the search percentile source before filling the remaining comparison fields
- `Остатки` | `TECHNICAL / PARTIAL` | the sheet is a helper input, not an original standalone tab | next: keep it as a technical source for other MVP tabs
- `ИТОГО_FULL` | `LATER` | wide pivot still depends on unconfirmed and partial upstream blocks | next: keep the wide pivot deferred until the upstream blocks are complete

## Safety confirmation

- Existing Google Sheets data was not cleared.
- Mock/fake rows were not added by this run.
- WB/MPStat write actions were not executed.
- Unsupported blocks were not force-filled.
