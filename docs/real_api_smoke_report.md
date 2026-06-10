# Real API Smoke Report

- Generated at: `2026-06-02T00:24:43`
- Test nmIDs: `197330807, 37320545, 37342770, 36387055, 577510563`
- Test window: `2026-05-31` .. `2026-06-01`
- Google Sheets were read only. No rows were written.
- WB / MPStat responses were summarized only. Raw private payloads were not saved.
- Mock/fake rows were not created.

## Google Sheets tabs

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
- ИТОГО_FULL
- ИТОГО
- ВБро
- Точка вх
- Локализация
- Сравнение карточек

## Results

### Google Sheets

- Endpoint: `spreadsheet metadata`
- Method: `GET`
- Status: `OK`
- HTTP status: `200`
- Objects count: `20`
- Fields found: `spreadsheet_id, tabs`
- Fields missing: `-`
- MVP usable: `YES`
- Error: `-`
- Notes: `read-only check`

### WB Content API

- Endpoint: `/content/v2/get/cards/list`
- Method: `POST`
- Status: `PARTIAL`
- HTTP status: `200`
- Objects count: `0`
- Fields found: `-`
- Fields missing: `nm_id, vendorCode, title, subject, brand`
- MVP usable: `PARTIAL`
- Error: `-`
- Notes: `200 with empty cards list for the current token/account`

### WB Sales Funnel

- Endpoint: `/api/analytics/v3/sales-funnel/products/history`
- Method: `POST`
- Status: `OK`
- HTTP status: `200`
- Objects count: `5`
- Fields found: `date, nm_id, impressions, card_clicks, cartCount, orderCount, orderSum, buyoutSum`
- Fields missing: `-`
- MVP usable: `YES`
- Error: `-`
- Notes: `window 2026-05-31..2026-06-01`

### WB Stocks products

- Endpoint: `/api/v2/stocks-report/products/products`
- Method: `POST`
- Status: `PARTIAL`
- HTTP status: `200`
- Objects count: `5`
- Fields found: `wb_stock_qty, stock_total_sum`
- Fields missing: `mp_stock_qty`
- MVP usable: `PARTIAL`
- Error: `-`
- Notes: `-`

### WB Stocks offices

- Endpoint: `/api/v2/stocks-report/offices`
- Method: `POST`
- Status: `PARTIAL`
- HTTP status: `200`
- Objects count: `0`
- Fields found: `region, warehouse, quantity`
- Fields missing: `-`
- MVP usable: `PARTIAL`
- Error: `-`
- Notes: `useful for regional/detail view, not enough alone for full stock snapshot`

### WB Promotion costs

- Endpoint: `/adv/v1/upd`
- Method: `GET`
- Status: `OK`
- HTTP status: `200`
- Objects count: `96`
- Fields found: `advertId, campaign_name, writeoff_date, sum, document_number`
- Fields missing: `-`
- MVP usable: `YES`
- Error: `-`
- Notes: `-`

### WB Promotion fullstats

- Endpoint: `/adv/v3/fullstats`
- Method: `GET`
- Status: `PARTIAL`
- HTTP status: `200`
- Objects count: `0`
- Fields found: `-`
- Fields missing: `date, advertId, campaign_name, row_type, conversion_type, nm_id, ad_spend, ad_revenue, views, clicks, atbs, orders, ctr, cpc, cpm, cr, roi`
- MVP usable: `PARTIAL`
- Error: `-`
- Notes: `200 with null body for selected campaign ids/date window`

### WB Search texts

- Endpoint: `/api/v2/search-report/product/search-texts`
- Method: `POST`
- Status: `OK`
- HTTP status: `200`
- Objects count: `50`
- Fields found: `search_query, query_count, visibility, avg_position, median_position, clicks, carts, orders`
- Fields missing: `-`
- MVP usable: `YES`
- Error: `-`
- Notes: `Jam endpoint`

### WB Search orders

- Endpoint: `/api/v2/search-report/product/orders`
- Method: `POST`
- Status: `OK`
- HTTP status: `200`
- Objects count: `3`
- Fields found: `search_query, avg_position, orders, date`
- Fields missing: `-`
- MVP usable: `PARTIAL`
- Error: `-`
- Notes: `gives daily orders and positions, not full visibility/click metrics`

### MPStat

- Endpoint: `/item/{nm_id}`
- Method: `GET`
- Status: `FAIL`
- HTTP status: `401`
- Objects count: `0`
- Fields found: `-`
- Fields missing: `nm_id, title, brand`
- MVP usable: `NO`
- Error: `{"code":401,"message":"Authorization Required"}`
- Notes: `connectivity/auth check only`

## Backlog updates

- `WB Content API` | `PARTIAL` | nm_id, vendorCode, title, subject, brand | next: confirm API contract and mapping
- `WB Stocks products` | `PARTIAL` | mp_stock_qty | next: use current stocks API for snapshot and CSV for history
- `WB Stocks offices` | `PARTIAL` | useful for regional/detail view, not enough alone for full stock snapshot | next: use current stocks API for snapshot and CSV for history
- `WB Promotion fullstats` | `PARTIAL` | date, advertId, campaign_name, row_type, conversion_type, nm_id, ad_spend, ad_revenue, views, clicks, atbs, orders, ctr, cpc, cpm, cr, roi | next: derive row_type/conversion_type mapping from nested fullstats structure
- `MPStat` | `FAIL` | {"code":401,"message":"Authorization Required"} | next: verify token category / access rights / subscription

## Safety confirmation

- Google Sheets were not populated.
- Existing Google Sheets data was not cleared.
- WB / MPStat write actions were not executed.
- Full pipeline was not started.
