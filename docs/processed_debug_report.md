# Diagnostic Report: Processed Tables Status
Generated for: 2026-05-28 17:05:37

## File: dim_product.csv
- **exists**: yes
- **rows_count**: 3
- **columns_count**: 5
- **columns**: `nm_id, supplier_article, title, subject, brand`

**First 5 rows:**
|     nm_id | supplier_article   | title            | subject    | brand      |
|----------:|:-------------------|:-----------------|:-----------|:-----------|
| 197330807 | ART-197330807      | Товар тестовый 1 | Одежда     | TestBrand1 |
|  37320545 | ART-37320545       | Товар тестовый 2 | Обувь      | TestBrand2 |
|  37342770 | ART-37342770       | Товар тестовый 3 | Аксессуары | TestBrand3 |

- **nm_id column**: `nm_id` (type: int64)
- **unique nm_id count**: 3
- **Target IDs found**: ['197330807', '37320545', '37342770']

---

## File: fact_funnel_day.csv
- **exists**: yes
- **rows_count**: 21
- **columns_count**: 12
- **columns**: `date, nm_id, openCount, cartCount, orderCount, orderSum, buyoutCount, buyoutSum, addToWishlistCount, buyoutPercent, addToCartConversion, cartToOrderConversion`

**First 5 rows:**
| date       |     nm_id |   openCount |   cartCount |   orderCount |   orderSum |   buyoutCount |   buyoutSum |   addToWishlistCount |   buyoutPercent |   addToCartConversion |   cartToOrderConversion |
|:-----------|----------:|------------:|------------:|-------------:|-----------:|--------------:|------------:|---------------------:|----------------:|----------------------:|------------------------:|
| 2026-05-28 | 197330807 |         107 |          22 |           12 | 1973313070 |             9 |  1578650456 |                   18 |              75 |                 20.56 |                   54.55 |
| 2026-05-28 |  37320545 |         105 |          20 |           12 |  373210450 |             9 |   298568360 |                   16 |              75 |                 19.05 |                   60    |
| 2026-05-28 |  37342770 |         100 |          20 |           10 |  373432700 |             8 |   298746160 |                   17 |              80 |                 20    |                   50    |
| 2026-05-27 | 197330807 |         107 |          22 |           12 | 1973313070 |             9 |  1578650456 |                   18 |              75 |                 20.56 |                   54.55 |
| 2026-05-27 |  37320545 |         105 |          20 |           12 |  373210450 |             9 |   298568360 |                   16 |              75 |                 19.05 |                   60    |

- **nm_id column**: `nm_id` (type: int64)
- **unique nm_id count**: 3
- **Target IDs found**: ['197330807', '37320545', '37342770']

- **date column**: `date` (type: object)
- **unique date count**: 7
- **date range**: 2026-05-22 to 2026-05-28

---

## File: fact_stock_snapshot.csv
- **exists**: yes
- **rows_count**: 3
- **columns_count**: 5
- **columns**: `nm_id, stockCount, stockSum, warehouse_id, warehouse_name`

**First 5 rows:**
|     nm_id |   stockCount |   stockSum |   warehouse_id | warehouse_name   |
|----------:|-------------:|-----------:|---------------:|:-----------------|
| 197330807 |           57 |  986679035 |              1 | Москва           |
|  37320545 |           55 |  186627725 |              1 | Москва           |
|  37342770 |           60 |  186738850 |              1 | Москва           |

- **nm_id column**: `nm_id` (type: int64)
- **unique nm_id count**: 3
- **Target IDs found**: ['197330807', '37320545', '37342770']

---

## File: fact_ad_cost_event.csv
- **exists**: no
- **Status**: FILE MISSING

## File: fact_ad_campaign_day.csv
- **exists**: no
- **Status**: FILE MISSING

## File: fact_ad_campaign_nm_day.csv
- **exists**: yes
- **rows_count**: 14
- **columns_count**: 11
- **columns**: `date, nm_id, ad_views, ad_clicks, ad_spend, ad_orders, ad_revenue, ad_ctr, ad_cpc, ad_atbs, ad_campaign_id`

**First 5 rows:**
| date       |     nm_id |   ad_views |   ad_clicks |   ad_spend |   ad_orders |   ad_revenue |   ad_ctr |      ad_cpc |   ad_atbs | ad_campaign_id   |
|:-----------|----------:|-----------:|------------:|-----------:|------------:|-------------:|---------:|------------:|----------:|:-----------------|
| 2026-05-28 | 197330807 |        507 |          57 |  394662614 |           7 |    986657035 |    11.24 | 6.92391e+06 |         7 | default          |
| 2026-05-28 |  37320545 |        545 |          55 |   74642090 |           7 |    186605725 |    10.09 | 1.35713e+06 |         7 | default          |
| 2026-05-27 | 197330807 |        507 |          57 |  394662614 |           7 |    986657035 |    11.24 | 6.92391e+06 |         7 | default          |
| 2026-05-27 |  37320545 |        545 |          55 |   74642090 |           7 |    186605725 |    10.09 | 1.35713e+06 |         7 | default          |
| 2026-05-26 | 197330807 |        507 |          57 |  394662614 |           7 |    986657035 |    11.24 | 6.92391e+06 |         7 | default          |

- **nm_id column**: `nm_id` (type: int64)
- **unique nm_id count**: 2
- **Target IDs found**: ['197330807', '37320545']

- **date column**: `date` (type: object)
- **unique date count**: 7
- **date range**: 2026-05-22 to 2026-05-28

---

## File: fact_search_query_metric.csv
- **exists**: yes
- **rows_count**: 14
- **columns_count**: 8
- **columns**: `date, nm_id, search_query_count, avg_search_position, avg_visibility, search_card_clicks, search_add_to_cart, search_orders`

**First 5 rows:**
| date       |     nm_id |   search_query_count |   avg_search_position |   avg_visibility |   search_card_clicks |   search_add_to_cart |   search_orders |
|:-----------|----------:|---------------------:|----------------------:|-----------------:|---------------------:|---------------------:|----------------:|
| 2026-05-28 | 197330807 |                   37 |                   5.5 |             0.75 |                   22 |                   12 |               6 |
| 2026-05-28 |  37320545 |                   35 |                   5.5 |             0.75 |                   20 |                   12 |               6 |
| 2026-05-27 | 197330807 |                   37 |                   5.5 |             0.75 |                   22 |                   12 |               6 |
| 2026-05-27 |  37320545 |                   35 |                   5.5 |             0.75 |                   20 |                   12 |               6 |
| 2026-05-26 | 197330807 |                   37 |                   5.5 |             0.75 |                   22 |                   12 |               6 |

- **nm_id column**: `nm_id` (type: int64)
- **unique nm_id count**: 2
- **Target IDs found**: ['197330807', '37320545']

- **date column**: `date` (type: object)
- **unique date count**: 7
- **date range**: 2026-05-22 to 2026-05-28

---

## Specific Deep Dive

### ✅ fact_funnel_day has data
Rows: 21. This should be the base for ИТОГО_v1.

### dim_product Structure Analysis
- nm_id/nmID: ✅ Found
- vendorCode/supplier_article: ✅ Found
- title: ✅ Found
- subjectName/subject: ✅ Found
- brand: ✅ Found
- Non-empty titles count: 3
  Sample: Товар тестовый 1...

## Raw Data Samples for Debugging

### fact_ad_campaign_nm_day (Check for duplication)
Total rows: 14
No exact duplicates on date+nm_id found.

ad_spend stats: min=74642090, max=394662614, mean=234652352.0
Sample ad_spend values:
|    ad_spend |
|------------:|
| 3.94663e+08 |
| 7.46421e+07 |
| 3.94663e+08 |
| 7.46421e+07 |
| 3.94663e+08 |
| 7.46421e+07 |
| 3.94663e+08 |
| 7.46421e+07 |
| 3.94663e+08 |
| 7.46421e+07 |