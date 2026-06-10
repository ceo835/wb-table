# DATABASE_SCHEMA_SPEC

Проектная спецификация PostgreSQL-схемы для `WB_table-main`.

Документ основан на:
- [TOTAL_REPORT_SPEC.md](C:/Users/User/Desktop/WB_table/WB_table-main/docs/TOTAL_REPORT_SPEC.md)
- [TOTAL_REPORT_FORMULA_MAP.md](C:/Users/User/Desktop/WB_table/WB_table-main/docs/TOTAL_REPORT_FORMULA_MAP.md)
- [GOOGLE_SHEETS_FIELD_MAP.md](C:/Users/User/Desktop/WB_table/WB_table-main/docs/GOOGLE_SHEETS_FIELD_MAP.md)
- [total_report_column_map.csv](C:/Users/User/Desktop/WB_table/WB_table-main/data/processed/total_report_column_map.csv)

Важно:
- это только проектирование;
- база, схемы, миграции и materialized views здесь не создаются;
- pipeline и Google Sheets не меняются;
- все wide-отчеты считаются export/view-слоем, а не первичным storage.

## 1. Принципы схемы

1. Храним данные в long/fact формате.
2. Широкие блоки бывшего `Итого` строятся pivot-ом только на этапе экспорта.
3. Пустое значение не заменяется на `0`, если источник не подтвердил число.
4. Snapshot-остатки не выдаются за историю.
5. Mock/fake/test значения запрещены.
6. Для рекламы production-окно по статистике начинается минимум с `D-2`.
7. Manual/external источники хранятся отдельно от API-фактов.
8. `mart_total_report` собирается только поверх validated raw/fact/dim tables.

## 2. Слои и количество таблиц

Предлагается `19` таблиц:

- `raw`: `3`
- `dimensions/settings`: `4`
- `facts`: `11`
- `mart`: `1`

## 3. Таблицы raw layer

### 3.1 `raw_api_response`

- Назначение: аудит и трассировка read-only загрузок API без привязки к Google Sheets.
- Grain: одна запись = один HTTP response / одна logical page / один export file.
- Primary key: `raw_response_id`.
- Unique key: `source_system + endpoint_name + request_hash + response_received_at`.
- Source class: `API`, `CSV_EXPORT`, `MANUAL_UPLOAD`, `PRIVATE_ENDPOINT`.
- Nullable: `response_body_json`, `response_body_path`, `http_status`, `error_message`.
- Индексы:
  - `idx_raw_api_response_source_time (source_system, endpoint_name, response_received_at desc)`
  - `idx_raw_api_response_request_hash (request_hash)`
  - `idx_raw_api_response_batch_id (load_batch_id)`
- Колонки:

| Поле | Тип | Роль | Nullable | Источник |
| --- | --- | --- | --- | --- |
| `raw_response_id` | `bigserial` | PK | no | system |
| `load_batch_id` | `uuid` | batch linkage | no | pipeline |
| `source_system` | `text` | wb/mpstat/manual | no | pipeline |
| `endpoint_name` | `text` | logical endpoint key | no | pipeline |
| `http_method` | `text` | GET/POST/etc | yes | pipeline |
| `request_url` | `text` | sanitized URL | yes | pipeline |
| `request_hash` | `text` | dedup key | no | pipeline |
| `request_params_json` | `jsonb` | sanitized params | yes | pipeline |
| `response_received_at` | `timestamptz` | response ts | no | pipeline |
| `http_status` | `integer` | HTTP code | yes | pipeline |
| `response_body_json` | `jsonb` | optional sanitized body | yes | pipeline |
| `response_body_path` | `text` | external raw storage path | yes | pipeline |
| `rows_detected` | `integer` | parsed row count | yes | parser |
| `parse_status` | `text` | parsed/failed/partial | no | parser |
| `error_code` | `text` | service error | yes | pipeline |
| `error_message` | `text` | short error | yes | pipeline |
| `loaded_at` | `timestamptz` | technical | no | pipeline |

- Покрытие `Итого`: напрямую не экспортируется; служит audit-layer для всех блоков.

### 3.2 `api_load_log`

- Назначение: журнал запусков и статусов загрузки по endpoint-ам и таблицам назначения.
- Grain: одна запись = один table-load attempt.
- Primary key: `api_load_log_id`.
- Unique key: `load_batch_id + target_table + endpoint_name + window_start + window_end`.
- Source class: `API`, `CSV_EXPORT`, `MANUAL_UPLOAD`.
- Nullable: `window_start`, `window_end`, `objects_written`, `warning_count`.
- Индексы:
  - `idx_api_load_log_target_time (target_table, started_at desc)`
  - `idx_api_load_log_batch (load_batch_id)`
  - `idx_api_load_log_status (status)`
- Колонки:

| Поле | Тип | Роль |
| --- | --- | --- |
| `api_load_log_id` | `bigserial` | PK |
| `load_batch_id` | `uuid` | batch id |
| `target_table` | `text` | destination table |
| `endpoint_name` | `text` | logical endpoint |
| `source_system` | `text` | wb/mpstat/manual |
| `window_start` | `date` | data window start |
| `window_end` | `date` | data window end |
| `started_at` | `timestamptz` | start time |
| `finished_at` | `timestamptz` | finish time |
| `status` | `text` | success/partial/fail/skipped |
| `http_status` | `integer` | http code if relevant |
| `objects_read` | `integer` | read count |
| `objects_written` | `integer` | written count |
| `warning_count` | `integer` | warnings |
| `error_short` | `text` | short error |
| `source_status` | `text` | REAL_API / PARTIAL / ACCESS_ERROR etc |
| `loaded_at` | `timestamptz` | technical |

- Покрытие `Итого`: напрямую не экспортируется; используется для observability.

### 3.3 `validation_warning`

- Назначение: долговременное хранение warning-ов качества данных, включая `suspicious_ctr`.
- Grain: одна запись = одно предупреждение по сущности/ключу/правилу.
- Primary key: `validation_warning_id`.
- Unique key: `warning_rule + sheet_name + business_key_hash`.
- Source class: `CALCULATED`.
- Nullable: `date`, `nm_id`, `advert_id`, `region`, `details_json`.
- Индексы:
  - `idx_validation_warning_rule_time (warning_rule, created_at desc)`
  - `idx_validation_warning_sheet_date (sheet_name, date)`
  - `idx_validation_warning_nm_id (nm_id)`
- Колонки:

| Поле | Тип | Роль |
| --- | --- | --- |
| `validation_warning_id` | `bigserial` | PK |
| `warning_rule` | `text` | `suspicious_ctr`, etc |
| `severity` | `text` | info/warn/error |
| `sheet_name` | `text` | logical report sheet |
| `source_table` | `text` | originating fact/mart |
| `date` | `date` | optional |
| `nm_id` | `bigint` | optional |
| `advert_id` | `bigint` | optional |
| `region` | `text` | optional |
| `business_key_hash` | `text` | unique hash |
| `reason` | `text` | human-readable reason |
| `details_json` | `jsonb` | contextual metrics |
| `source_status` | `text` | warning source status |
| `created_at` | `timestamptz` | technical |

- Покрытие `Итого`: не участвует в расчете витрины, но питает `Validation_v1`.

## 4. Таблицы dimensions/settings

### 4.1 `dim_product`

- Назначение: единый справочник карточек/артикулов.
- Grain: одна запись = один `nm_id`.
- Primary key: `nm_id`.
- Unique key: `supplier_article` nullable unique only if source confirms uniqueness.
- Source class: `API`, `PARTIAL`.
- Nullable: `supplier_article`, `title`, `subject`, `category`, `brand`, ratings.
- Индексы:
  - `idx_dim_product_supplier_article`
  - `idx_dim_product_brand_subject`
- Основные поля:
  - `nm_id bigint not null`
  - `supplier_article text`
  - `title text`
  - `subject text`
  - `category text`
  - `brand text`
  - `card_rating numeric(8,4)`
  - `reviews_rating numeric(8,4)`
  - `reviews_count integer`
  - `is_deleted boolean`
  - `data_status text`
  - `source_status text`
  - `loaded_at timestamptz`
- Источник данных: `WB Content API`, fallback enrichment из текущих фактов без fake.
- Покрывает `Итого`: `Артикул продавца`, `Артикул WB`, часть `Название/Предмет/Бренд` и справочные поля в зависимых wide-экспортах.

### 4.2 `dim_campaign`

- Назначение: единый справочник рекламных кампаний.
- Grain: одна запись = один `advert_id`.
- Primary key: `advert_id`.
- Unique key: `advert_id`.
- Source class: `API`, `PARTIAL`.
- Nullable: `campaign_name`, `campaign_type`, `payment_model`, `start_date`, `end_date`, `section_display`.
- Индексы:
  - `idx_dim_campaign_type_status (campaign_type, status)`
  - `idx_dim_campaign_name_trgm` or B-tree on `campaign_name`
- Основные поля:
  - `advert_id bigint not null`
  - `campaign_name text`
  - `campaign_type text`
  - `payment_model text`
  - `status text`
  - `section_raw text`
  - `section_display text`
  - `nm_id bigint`
  - `nm_id_parse_status text`
  - `start_date date`
  - `end_date date`
  - `source_status text`
  - `loaded_at timestamptz`
- Источник данных: `РасходРК`, `РК стата`, рекламные metadata endpoints, manual parse rules.
- Покрывает `Итого`: campaign matrix headers, `Раздел`, `campaign_type`, joins для ad facts.

### 4.3 `settings_products`

- Назначение: управляемый список артикулов для runs и группировок.
- Grain: одна запись = один `nm_id` в настройках.
- Primary key: `nm_id`.
- Unique key: `nm_id`.
- Source class: `MANUAL_UPLOAD`.
- Nullable: `supplier_article`, `group_name`, `comment`.
- Индексы:
  - `idx_settings_products_active (active)`
  - `idx_settings_products_group_name (group_name)`
- Основные поля:
  - `nm_id bigint not null`
  - `supplier_article text`
  - `group_name text`
  - `item_type text` with allowed values `normal`, `bundle`, `glue`, `multicard`
  - `active boolean not null`
  - `comment text`
  - `loaded_at timestamptz`
- Источник данных: будущая вкладка/таблица `Настройки_артикулы`.
- Покрывает `Итого`: не напрямую, но управляет выборкой для экспорта/построения wide-отчета.

### 4.4 `settings_report_columns`

- Назначение: конфигурация экспортных колонок и wide-pivot секций для `Итого`.
- Grain: одна запись = одна колонка или logical export metric.
- Primary key: `report_column_id`.
- Unique key: `report_name + export_column_key`.
- Source class: `MANUAL_UPLOAD`.
- Nullable: `pivot_dimension`, `formula_note`, `source_table`.
- Индексы:
  - `idx_settings_report_columns_report_order (report_name, display_order)`
  - `idx_settings_report_columns_active (is_active)`
- Основные поля:
  - `report_column_id bigserial`
  - `report_name text`
  - `export_column_key text`
  - `export_column_name text`
  - `source_table text`
  - `source_field text`
  - `pivot_dimension text`
  - `calculation_rule text`
  - `display_order integer`
  - `is_active boolean`
  - `notes text`
  - `loaded_at timestamptz`
- Источник данных: manual configuration from `TOTAL_REPORT_SPEC`.
- Покрывает `Итого`: весь export-order и pivot layout.

## 5. Таблицы fact layer

### 5.1 `fact_funnel_day`

- Назначение: дневная нормализованная воронка WB по товару.
- Grain: `date + nm_id`.
- Primary key: synthetic `fact_funnel_day_id` optional; business unique key `date + nm_id`.
- Unique key: `(date, nm_id)`.
- Source class: `API`, `CALCULATED`, `PARTIAL`.
- Nullable: все previous-period поля, `cancel*`, `avg_delivery_time`, WB Club/B2B fields, local share fields.
- Индексы:
  - `idx_fact_funnel_day_date_nm (date, nm_id)`
  - `idx_fact_funnel_day_nm_date (nm_id, date desc)`
  - `idx_fact_funnel_day_status (source_status)`
- Ключевые поля:
  - `date`
  - `nm_id`
  - `impressions`
  - `impressions_prev`
  - `card_clicks`
  - `card_clicks_prev`
  - `ctr`
  - `ctr_prev`
  - `cart_count`
  - `cart_count_prev`
  - `wishlist_count`
  - `order_count`
  - `order_count_prev`
  - `buyout_count`
  - `buyout_count_prev`
  - `cancel_count`
  - `cancel_count_prev`
  - `order_sum`
  - `order_sum_prev`
  - `buyout_sum`
  - `cancel_sum`
  - `avg_price`
  - `avg_delivery_time`
  - `local_orders_percent`
  - `wbclub_*` optional
  - `b2b_*` optional
  - `data_status`
  - `source_status`
  - `loaded_at`
- Источник данных: `WB Analytics sales funnel`.
- Покрывает `Итого`: базовый блок `Базовая воронка и KPI`, часть локальных KPI, previous period comparisons.

### 5.2 `fact_ad_cost_event`

- Назначение: granular write-off events по рекламе.
- Grain: `date + advert_id + writeoff_datetime + document_number`.
- Primary key: composite unique or synthetic PK with unique business key.
- Unique key: `(date, advert_id, writeoff_datetime, document_number)`.
- Source class: `API`.
- Nullable: `nm_id`, `campaign_name`, `source_name`, `document_number`, `section_display`.
- Индексы:
  - `idx_fact_ad_cost_event_date_advert (date, advert_id)`
  - `idx_fact_ad_cost_event_nm_date (nm_id, date)`
  - `idx_fact_ad_cost_event_document (document_number)`
- Поля:
  - `date`
  - `writeoff_datetime timestamptz`
  - `advert_id bigint`
  - `campaign_name text`
  - `source_name text`
  - `amount numeric(18,2)`
  - `document_number text`
  - `section_raw text`
  - `section_display text`
  - `nm_id bigint`
  - `nm_id_parse_status text`
  - `campaign_type text`
  - `data_status text`
  - `source_status text`
  - `loaded_at timestamptz`
- Источник данных: `WB Promotion write-offs`.
- Покрывает `Итого`: `Сумма кампания`, ad-cost blocks, ad campaign matrix inputs, `РасходРК`.

### 5.3 `fact_ad_cost_day`

- Назначение: дневная агрегация расходов по кампании и товару для аналитики.
- Grain: `date + advert_id + nm_id`.
- Unique key: `(date, advert_id, nm_id)`.
- Source class: `CALCULATED` over `fact_ad_cost_event`.
- Nullable: `nm_id` nullable only if parsed link absent.
- Индексы:
  - `idx_fact_ad_cost_day_date_nm (date, nm_id)`
  - `idx_fact_ad_cost_day_advert_date (advert_id, date)`
- Поля:
  - `date`
  - `advert_id`
  - `nm_id`
  - `campaign_name`
  - `campaign_type`
  - `payment_model`
  - `ad_spend numeric(18,2)`
  - `writeoff_count integer`
  - `data_status`
  - `source_status`
  - `loaded_at`
- Источник данных: rollup from `fact_ad_cost_event` plus `dim_campaign`.
- Покрывает `Итого`: daily ad spend metrics, joins to funnel and mart.

### 5.4 `fact_ad_campaign_day`

- Назначение: дневные итоги по рекламной кампании и типу строки без разреза по nm_id.
- Grain: `date + advert_id + row_type`.
- Unique key: `(date, advert_id, row_type)`.
- Source class: `API`, `PARTIAL`.
- Nullable: `campaign_name`, `row_type`, `views`, `clicks`, `orders`, `ctr`, `cpc`, `cpm`, `roi`.
- Индексы:
  - `idx_fact_ad_campaign_day_date_advert`
  - `idx_fact_ad_campaign_day_row_type`
- Поля:
  - `date`
  - `advert_id`
  - `campaign_name`
  - `row_type` like `CAMPAIGN_TOTAL`
  - `views`
  - `clicks`
  - `atbs`
  - `orders`
  - `ordered_items_qty`
  - `cancel_count`
  - `ad_spend`
  - `ad_revenue`
  - `avg_position`
  - `ctr`
  - `cpc`
  - `cpm`
  - `cr`
  - `roi`
  - `data_status`
  - `source_status`
  - `loaded_at`
- Источник данных: `fullstats` / campaign totals, but only from `D-2` and older.
- Покрывает `Итого`: total rows for campaign summaries, QA against `РК стата`.

### 5.5 `fact_ad_campaign_nm_day`

- Назначение: нормализованная рекламная статистика по дню, кампании, типу строки, типу конверсии и товару.
- Grain: `date + advert_id + row_type + conversion_type + nm_id`.
- Unique key: `(date, advert_id, row_type, conversion_type, nm_id)`.
- Source class: `API`, `PARTIAL`.
- Nullable: `conversion_type`, `nm_id`, `product_name`, `avg_position`, `cpm`, `roi`.
- Индексы:
  - `idx_fact_ad_campaign_nm_day_date_nm (date, nm_id)`
  - `idx_fact_ad_campaign_nm_day_advert (advert_id, date)`
  - `idx_fact_ad_campaign_nm_day_conversion (conversion_type, row_type)`
- Поля:
  - `date`
  - `advert_id`
  - `campaign_name`
  - `row_type`
  - `conversion_type_raw integer`
  - `conversion_type text`
  - `nm_id`
  - `product_name`
  - `views`
  - `clicks`
  - `atbs`
  - `orders`
  - `ordered_items_qty`
  - `cancel_count`
  - `ad_spend`
  - `ad_revenue`
  - `avg_position`
  - `ctr`
  - `cpc`
  - `cpm`
  - `cr`
  - `roi`
  - `data_status`
  - `source_status`
  - `loaded_at`
- Источник данных: `fullstats`, only from `D-2` and older.
- Покрывает `Итого`: `РК стата` block, campaign matrix pivots, ad KPI by item.

### 5.6 `fact_search_query_metric`

- Назначение: нормализованные метрики поисковых запросов.
- Grain: `period_start + period_end + nm_id + search_query`.
- Unique key: `(period_start, period_end, nm_id, search_query)`.
- Source class: `API`, `PARTIAL`.
- Nullable: `visibility`, `avg_position`, `median_position`, `card_clicks`, `cart_count`, `order_count`, competitor percentile fields, min/max price fields.
- Индексы:
  - `idx_fact_search_query_metric_period_nm`
  - `idx_fact_search_query_metric_query`
  - `idx_fact_search_query_metric_nm_query`
- Поля:
  - `period_start`
  - `period_end`
  - `nm_id`
  - `search_query`
  - `query_count`
  - `visibility`
  - `avg_position`
  - `median_position`
  - `card_clicks`
  - `cart_count`
  - `order_count`
  - `add_to_cart_conversion`
  - `cart_to_order_conversion`
  - `visibility_prev`
  - `avg_position_prev`
  - `median_position_prev`
  - `card_clicks_prev`
  - `cart_count_prev`
  - `order_count_prev`
  - `competitor_percentile_*` nullable family
  - `min_discount_price`
  - `max_discount_price`
  - `data_status`
  - `source_status`
  - `loaded_at`
- Источник данных: `search-texts`, `orders`, optional Jam enrichments.
- Покрывает `Итого`: huge `Поисковые запросы` wide-block, query pivots, positional metrics.

### 5.7 `fact_stock_snapshot`

- Назначение: текущий snapshot остатков и их стоимости.
- Grain: `snapshot_at + nm_id` or `snapshot_date + nm_id` depending policy.
- Unique key: `(snapshot_at, nm_id)`.
- Source class: `API`, `PARTIAL`.
- Nullable: `wb_stock_qty`, `mp_stock_qty`, `stock_total_sum`, warehouse details.
- Индексы:
  - `idx_fact_stock_snapshot_snapshot_nm`
  - `idx_fact_stock_snapshot_nm_snapshot`
- Поля:
  - `snapshot_at timestamptz`
  - `snapshot_date date`
  - `nm_id`
  - `wb_stock_qty`
  - `mp_stock_qty`
  - `stock_total_sum`
  - `warehouse_name`
  - `warehouse_type`
  - `data_status`
  - `source_status`
  - `loaded_at`
- Источник данных: stocks snapshot endpoints.
- Покрывает `Итого`: current stock fields only for same-date export context.
- Специальное правило: нельзя использовать snapshot как исторический stock backfill.

### 5.8 `fact_localization_region_day`

- Назначение: региональные продажи/заказы/остатки по товару.
- Grain: `date + nm_id + region`.
- Unique key: `(date, nm_id, region)`.
- Source class: `API`, `CSV_EXPORT`, `PARTIAL`.
- Nullable: `supplier_article`, `title`, `subject`, `brand`, `wb_stock_qty`, `mp_stock_qty`, `delivery_time`, `local_orders_percent`, `nonlocal_orders_percent`.
- Индексы:
  - `idx_fact_localization_region_day_date_nm_region`
  - `idx_fact_localization_region_day_region_date`
- Поля:
  - `date`
  - `nm_id`
  - `supplier_article`
  - `title`
  - `subject`
  - `brand`
  - `country`
  - `region`
  - `orders_total_qty`
  - `sale_item_qty`
  - `sale_amount`
  - `wb_stock_qty`
  - `mp_stock_qty`
  - `delivery_time`
  - `local_orders_percent`
  - `nonlocal_orders_percent`
  - `data_status`
  - `source_status`
  - `loaded_at`
- Источник данных: current `region-sale` partial; target source `orders-geography` export/access.
- Покрывает `Итого`: `Локализация` wide-region blocks and regional summary inputs.

### 5.9 `fact_entry_point_day`

- Назначение: long-таблица точек входа / customer profile.
- Grain: `date + nm_id + section + entry_point`.
- Unique key: `(date, nm_id, section, entry_point)`.
- Source class: `CSV_EXPORT`, `PRIVATE_ENDPOINT`, `MANUAL_UPLOAD`.
- Nullable: `date` if export only has period-end, `entry_value`, `orders_qty`, `revenue`.
- Индексы:
  - `idx_fact_entry_point_day_nm_date`
  - `idx_fact_entry_point_day_section_entry`
- Поля:
  - `date`
  - `nm_id`
  - `section`
  - `entry_point`
  - `metric_name`
  - `metric_value`
  - `orders_qty`
  - `revenue`
  - `source_file_name`
  - `data_status`
  - `source_status`
  - `loaded_at`
- Источник данных: `customer-profile` export or private endpoint.
- Покрывает `Итого`: both `Точка входа` blocks and future `entry_points_wide`.

### 5.10 `fact_vbro_manual`

- Назначение: manual import из внешнего сервиса `ВБро`.
- Grain: `date + nm_id`.
- Unique key: `(date, nm_id)`.
- Source class: `MANUAL_UPLOAD`, `EXTERNAL`.
- Nullable: practically all finance fields except keys and statuses.
- Индексы:
  - `idx_fact_vbro_manual_date_nm`
  - `idx_fact_vbro_manual_nm_date`
- Поля:
  - `date`
  - `nm_id`
  - `supplier_article`
  - `organic_sales_qty`
  - `net_sales_payout`
  - `ad_spend`
  - `logistics`
  - `storage`
  - `penalties`
  - `deductions`
  - `acceptance`
  - `operating_profit`
  - `operating_profit_per_unit`
  - `manual_file_name`
  - `data_status`
  - `source_status`
  - `loaded_at`
- Источник данных: manual upload from external service.
- Покрывает `Итого`: `ВБро` block and profit columns in future `mart_total_report`.

### 5.11 `fact_card_comparison_metric`

- Назначение: нормализованное сравнение карточек и competitor metrics.
- Grain: `period_start + period_end + base_nm_id + compared_nm_id + metric_name`.
- Unique key: `(period_start, period_end, base_nm_id, compared_nm_id, metric_name)`.
- Source class: `EXTERNAL`, `MANUAL_UPLOAD`, `PARTIAL`.
- Nullable: `compared_nm_id`, `metric_numeric_value`, `metric_text_value`, `rank_position`.
- Индексы:
  - `idx_fact_card_comparison_metric_base_period`
  - `idx_fact_card_comparison_metric_metric_name`
- Поля:
  - `period_start`
  - `period_end`
  - `base_nm_id`
  - `compared_nm_id`
  - `metric_name`
  - `metric_numeric_value`
  - `metric_text_value`
  - `rank_position`
  - `source_system`
  - `data_status`
  - `source_status`
  - `loaded_at`
- Источник данных: MPStat or external comparison upload.
- Покрывает `Итого`: `Сравнение карточек`, ratings, position and competitor enrichments.

## 6. Таблица mart layer

### 6.1 `mart_total_report`

- Назначение: итоговая витрина, из которой потом строится `ИТОГО_v1`, `ИТОГО`, `ИТОГО_FULL`, dashboard или экспорт в Google Sheets.
- Grain: `date + nm_id`.
- Unique key: `(date, nm_id)`.
- Source class: `CALCULATED` over facts + dims + manual tables.
- Nullable: любые поля, для которых источник partial/manual/external не подтвержден.
- Индексы:
  - `idx_mart_total_report_date_nm`
  - `idx_mart_total_report_nm_date`
  - `idx_mart_total_report_supplier_article`
- Базовые поля mart:
  - key fields: `date`, `nm_id`
  - dimension fields: `supplier_article`, `title`, `subject`, `brand`
  - funnel fields and previous-period fields
  - ad spend and derived ad KPI
  - current stock snapshot fields
  - partial search summary fields if included at row grain
  - partial vbro fields from `fact_vbro_manual`
  - quality/status fields: `data_status`, `source_status`, `loaded_at`
- Источник данных: joins/aggregations over `dim_product`, `fact_funnel_day`, `fact_ad_cost_day`, `fact_stock_snapshot`, `fact_vbro_manual`, optional summarized search/localization inputs.
- Покрывает `Итого`: row-grain core of report. Wide blocks должны строиться поверх mart/facts в export layer, а не храниться как новые тысячи колонок.

## 7. Как собирать `mart_total_report`

### 7.1 Базовый row-grain

Базовый anchor:
- `fact_funnel_day.date`
- `fact_funnel_day.nm_id`

Потому что:
- именно этот grain уже совпадает с основной строкой `Итого`;
- в текущем Excel большинство row-level формул привязано к `Дата + Артикул WB`;
- искусственную сетку `date × nm_id` строить нельзя.

### 7.2 Базовые join-источники

1. `fact_funnel_day`
2. `dim_product` by `nm_id`
3. `fact_ad_cost_day` by `date + nm_id`
4. `fact_stock_snapshot`
5. `fact_vbro_manual` by `date + nm_id` only when manual file exists

### 7.3 Wide-блоки, которые не должны храниться колонками в mart

Pivot only at export:
- `РК стата / матрица кампаний`
- `Поисковые запросы`
- `Точка входа`
- `Локализация` региональные колонки
- `Сравнение карточек` wide competitor matrix

То есть:
- в БД они хранятся в long-fact таблицах;
- в Google Sheets/Excel они разворачиваются через export config из `settings_report_columns`.

### 7.4 Что должно считаться в mart

В mart разумно считать:
- `site_ctr`
- `расход на все корзины`
- рекламные cost-per-action KPI
- процент показов от рекламы
- агрегаты и предыдущий период, если они опираются на подтвержденные факты

Не считать в mart без подтвержденного источника:
- `ВБро` прибыль из COGS
- local/nonlocal derived KPI, если источник incomplete
- неизвестные макросные поля из xlsm

## 8. Порядок зависимостей загрузки

1. `settings_products`
2. `settings_report_columns`
3. `raw_api_response`
4. `api_load_log`
5. `dim_product`
6. `dim_campaign`
7. `fact_funnel_day`
8. `fact_ad_cost_event`
9. `fact_ad_cost_day`
10. `fact_ad_campaign_day`
11. `fact_ad_campaign_nm_day`
12. `fact_search_query_metric`
13. `fact_stock_snapshot`
14. `fact_localization_region_day`
15. `fact_entry_point_day`
16. `fact_vbro_manual`
17. `fact_card_comparison_metric`
18. `validation_warning`
19. `mart_total_report`

## 9. Специальные правила данных

### 9.1 Рекламная статистика `D-2`

- `fact_ad_campaign_day` и `fact_ad_campaign_nm_day` в production не должны загружаться за вчера.
- Минимально безопасное окно: `today - 2 days`.
- Если пользователь просит более свежее окно, данные должны маркироваться как `PARTIAL` и не считаться финальными.

### 9.2 Пусто не равно ноль

- Если API не вернул число, хранить `NULL`.
- `0` допустим только когда источник явно вернул нулевое значение.
- Для mart/export нельзя заменять `NULL` на `0` ради визуальной полноты.

### 9.3 Snapshot не равен история

- `fact_stock_snapshot` можно использовать только как snapshot на момент загрузки.
- Исторический stock-day нужен отдельным источником (`fact_stock_day` later), а не backfill из snapshot.

### 9.4 Mock/fake запрещены

Никогда не хранить:
- `ART-{nm_id}`
- `TestBrand`
- `Товар тестовый`
- `DRY_RUN`
- искусственные `openCount/cartCount/orderCount`
- искусственно размноженные days

### 9.5 Manual и external храним отдельно

- `ВБро` не смешивается с API-расчетом прибыли.
- `Точка вх` и `orders-geography` не маскируются под API.
- `MPStat` / comparison хранятся как external-source слой.

## 10. Какие блоки `Итого` покрываются по классам источников

### API-first

- базовая воронка
- часть рекламных расходов
- часть рекламной статистики
- часть поисковых запросов
- текущие остатки snapshot
- часть локализации

### CSV / manual / private endpoint

- `ВБро`
- `Точка вх`
- целевой `orders-geography`
- возможные export blocks для wide-pivot comparison

### External

- `MPStat / Сравнение карточек`

### Needs confirmation

- `#REF!`-колонки и неизвестные макросные KPI
- некоторые derived KPI, которые в xlsm считаются локально без явной бизнес-спецификации

