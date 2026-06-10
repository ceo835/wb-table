# Coverage Map: старый `ИТОГО` vs `mart_total_report v2`

Файлы:

- `data/processed/itogo_mart_coverage_map.csv`
- `data/processed/itogo_formula_map.csv`
- `data/processed/itogo_formula_sources_summary.csv`
- `data/processed/itogo_formula_analysis_first_pass.md`

## Что именно покрыто

Карта сделана по **смысловым колонкам и группам**, а не по всем `2000+` wide-колонкам старого Excel 1:1. Это сознательно: `mart_total_report v2` строится как нормализованная витрина `report_date + nm_id`, а не как копия wide-листа `ИТОГО`.

## Статусы покрытия

- `DONE`: `31`
- `PARTIAL`: `6`
- `FILE_IMPORT_PENDING`: `2`
- `MANUAL_PENDING`: `3`
- `LATER`: `3`
- `NEEDS_FORMULA_CONFIRMATION`: `3`
- `BROKEN_REF`: `3`
- `NOT_NEEDED_IN_STREAMLIT_V1`: `2`

Итого уже покрыто `DONE + PARTIAL = 37` смысловых колонок/групп.

## Что готово для Streamlit v1

- `base_funnel`
  - базовая сетка `date × active products`
  - `impressions`
  - `cart_count`
  - `order_count`
  - `order_sum`
  - `ctr_calc`
  - `add_to_cart_conversion_calc`
  - `cart_to_order_conversion_calc`
- `ad_writeoff`
  - `ad_cost_writeoff_total`
- `ad_campaign_performance`
  - `ad_campaign_spend_total`
  - `ad_views_total`
  - `ad_clicks_total`
  - `ad_atbs_total`
  - `ad_orders_total`
  - `ad_cpc_calc`
  - `ad_cpm_calc`
  - `ad_cost_per_cart_calc`
  - `ad_cpo_calc`
  - `ad_share_of_revenue_calc`
- `ad_conversion_buckets`
  - `direct_ad_atbs`
  - `associated_ad_atbs`
  - `multicard_ad_atbs`
  - `unknown_ad_atbs`
- `search_queries`
  - товарные агрегаты поиска уже есть в `mart_total_report v2`
- `localization`
  - текущий `PARTIAL region-sale` уже можно показывать как ограниченное покрытие

## Что нельзя закрыть без файлов / ручного источника

- `entry_points`
  - статус: `FILE_IMPORT_PENDING`
  - нужен файл/экспорт или подтверждённый private endpoint из `customer-profile`
- `orders-geography`
  - статус: `FILE_IMPORT_PENDING`
  - нужен файл/экспорт из `orders-geography`
- `profit_vbro`
  - статус: `MANUAL_PENDING`
  - операционная прибыль и related поля остаются на ручном внешнем сервисе

## Что отложено

- `card_comparison`
  - статус: `LATER / PARTIAL`
  - старый wide-блок `Сравнение карточек` не перенесён 1:1
- `mpstat`
  - статус: `LATER`
  - для Streamlit v1 не обязателен
- `technical_legacy`
  - wide-колонки отдельных РК и wide-поиск не нужны как физические поля mart v2

## Формулы, которые нельзя переносить вслепую

- `organic_cart_share_calc`
  - статус: `NEEDS_FORMULA_CONFIRMATION`
  - старые формулы `BD/BE` неоднозначны
- `Расход на все корзины`
  - статус: `NEEDS_FORMULA_CONFIRMATION`
  - старая формула смешивает spend и ассоциированные корзины

## `#REF!` в старом `ИТОГО`

- В первичном анализе найдено `12` формул с `#REF!` внутри формулы.
- В coverage-map они сведены в `3` проблемные смысловые зоны:
  - `AY` — корзины от реклам этого артикула
  - `AZ` — `Он своровал`
  - сводный блок `#REF!` / dynamic wide ad formulas

Эти формулы **не переносились как есть**.

## Вывод

`mart_total_report v2` уже покрывает основную витрину для Streamlit v1 по воронке, рекламе, поиску и частичной локализации. Следующие реальные блокеры для приближения к старому `ИТОГО` — это:

1. файл/экспорт `Точка входа`
2. файл/экспорт `География заказов`
3. ручной источник `ВБро`
4. подтверждение спорных формул `organic / associated`
