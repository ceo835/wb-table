# DATABASE_BUILD_PLAN

Пошаговый план перехода от Google Sheets-first MVP к database-first архитектуре.

Важно:
- база и миграции на этом этапе не создаются;
- текущий pipeline не переписывается;
- документ фиксирует порядок работ.

## Этап 1. PostgreSQL schema + raw layer

Цель:
- подготовить базовую схему хранения;
- отделить raw/load audit от business facts.

Что входит:
- создать logical schema names: `raw`, `dim`, `fact`, `mart`, `settings`
- ввести таблицы:
  - `raw_api_response`
  - `api_load_log`
  - `validation_warning`
  - `settings_products`
  - `settings_report_columns`
- определить общие technical fields:
  - `data_status`
  - `source_status`
  - `loaded_at`
  - `load_batch_id` где нужен batch tracking

Критерий готовности:
- можно принимать sanitized API/load metadata;
- можно писать warnings качества без Google Sheets.

## Этап 2. Перенос текущих WB API loaders из Google Sheets в DB

Цель:
- изменить целевой storage с `processed csv + Sheets` на `fact/dim tables`.

Что переносим в первую очередь:
- `dim_product`
- `dim_campaign`
- `fact_funnel_day`
- `fact_ad_cost_event`
- `fact_ad_cost_day`
- `fact_ad_campaign_day`
- `fact_ad_campaign_nm_day`
- `fact_search_query_metric`
- `fact_stock_snapshot`
- `fact_localization_region_day`

Правила:
- не строить искусственную сетку `date × nm_id`
- previous-period поля либо хранить в same-row grain, либо считать в mart/view
- для рекламной статистики production window = minimum `D-2`
- `NULL` не заменять на `0`

Критерий готовности:
- текущие API-first блоки `ИТОГО_v1` и `Воронка на день` можно собирать из БД без прямой записи в Sheets.

## Этап 3. Импорт manual/CSV источников

Цель:
- закрыть блоки, которые не подтверждены public API.

Импортируемые источники:
- `fact_vbro_manual`
  - внешний сервис `ВБро`
  - manual upload
- `fact_entry_point_day`
  - `customer-profile`
  - CSV/Excel export или private endpoint
- `fact_localization_region_day`
  - `orders-geography`
  - CSV/Excel export или доступ к кабинету
- `fact_card_comparison_metric`
  - MPStat / external upload

Что нужно от сотрудника:
- export sample для `orders-geography`
- export sample для `customer-profile`
- формат manual выгрузки `ВБро`
- корректный доступ или export format для comparison source

Критерий готовности:
- manual/external зоны больше не живут только в Excel/Sheets, а имеют свой storage layer.

## Этап 4. Сборка `mart_total_report`

Цель:
- собрать единую row-based витрину `date + nm_id`.

Anchor:
- `fact_funnel_day`

Join order:
1. `fact_funnel_day`
2. `dim_product`
3. `fact_ad_cost_day`
4. `fact_stock_snapshot`
5. `fact_vbro_manual`
6. summarized search/localization inputs

Что считаем в mart:
- confirmed KPI поверх API/manual facts
- previous-period comparisons
- cost-per-action metrics

Что не пишем в mart как wide-columns:
- campaign matrices
- search query matrices
- entry-point matrices
- region matrices
- comparison matrices

Критерий готовности:
- все row-grain поля `ИТОГО_v1` и core of `Итого` собираются SQL-слоем.

## Этап 5. Экспорт `Итого` в Google Sheets / dashboard

Цель:
- отделить storage от presentation.

Что происходит:
- `settings_report_columns` задает export order
- wide-блоки строятся pivot-ом из fact tables
- выгрузка идет в:
  - Google Sheets
  - dashboard
  - Excel export

Pivot-only блоки:
- `РК стата`
- `Поисковые запросы`
- `Точка вх`
- `Локализация` regional summary
- `Сравнение карточек`

Критерий готовности:
- `Итого` и `ИТОГО_FULL` перестают зависеть от Excel-формул и строятся из БД.

## Зависимости между этапами

1. Этап 1 обязателен до любого переноса loaders.
2. Этап 2 можно делать по частям, начиная с API-first блоков.
3. Этап 3 зависит от получения manual/export samples.
4. Этап 4 запускается после заполнения minimum required facts.
5. Этап 5 финализирует separation of storage and presentation.

## Риски

- В xlsm есть макросы, часть скрытой подготовки данных может быть неочевидной.
- Wide-матрицы `Итого` нельзя переносить в БД как тысячи физических колонок.
- `ВБро`, `Точка вх`, `orders-geography`, `MPStat` зависят от manual/external access.
- Рекламная статистика за вчера может быть недосчитана, поэтому нужен `D-2`.
- Snapshot-остатки нельзя выдавать за историю.

