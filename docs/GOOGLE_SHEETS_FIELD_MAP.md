# GOOGLE_SHEETS_FIELD_MAP

Единая архитектурная карта Google Sheets проекта `WB_table`.

Файл фиксирует:
- какие вкладки должны быть в Google Sheets;
- какие технические processed-таблицы нужны;
- какие поля тянутся из API;
- какие поля считаются;
- какие поля пока доступны только частично;
- какие широкие отчеты собираются из нормализованных таблиц.

---

# 0. Главные правила проекта

1. Боевые вкладки заполняются только реальными API-данными или расчетами на их основе.
2. Mock/fake данные запрещены:
   - `ART-{nm_id}`
   - `Товар тестовый`
   - `TestBrand`
   - искусственные `openCount`, `cartCount`, `orderCount`
   - искусственные рекламные расходы
   - размножение периодных данных на каждый день
3. Если API не вернул данные, поле остается пустым или получает статус `EMPTY` / `PARTIAL`.
4. Если источник пока не подтвержден, блок уходит в `Backlog`.
5. Текущие остатки нельзя выдавать за исторические остатки.
6. Рекламные расходы нельзя распределять по товарам без подтвержденной связи `advertId -> nm_id -> date`.
7. Широкие пользовательские вкладки строятся из нормализованных processed-таблиц.
8. `ИТОГО_FULL` и оригинальный `ИТОГО` — это широкий отчет, а не нормализованная fact-таблица.
9. Для хранения данных используем long/fact-таблицы. Wide-формат нужен только для пользовательских отчетов.
10. Перед записью в Google Sheets проверять:
    - нет дублей колонок;
    - нет дублей по ключу;
    - нет mock/fake значений;
    - деньги в правильных единицах;
    - дата и статус источника заполнены.

---

# 1. Статусы

| Статус | Значение |
|---|---|
| `REAL_API` | Данные получены из реального API |
| `CSV_EXPORT` | Данные получены из CSV/Excel-экспорта кабинета |
| `MANUAL_UPLOAD` | Данные загружены вручную |
| `PRIVATE_ENDPOINT` | Данные получены из private/UI endpoint |
| `PARTIAL` | Данные доступны частично |
| `EMPTY` | Данных нет |
| `NOT_FOUND` | Публичный API endpoint не подтвержден |
| `CALCULATED` | Поле рассчитывается |
| `NEEDS_FORMULA_CONFIRMATION` | Нужна точная формула |
| `NEEDS_API_CONFIRMATION` | Нужно подтвердить наличие поля в API |
| `CSV_ONLY` | Источник пока только CSV/Excel |
| `LATER` | Реализуется позже |
| `ACCESS_ERROR` | Ошибка доступа 401/403 |
| `RATE_LIMIT` | Ошибка лимита 429 |
| `API_UNAVAILABLE_DNS` | API недоступен из-за DNS/сети |

---

# 2. Основные пользовательские вкладки Google Sheets

| Вкладка | Назначение | Статус |
|---|---|---|
| `ИТОГО` / `ИТОГО_FULL` | Полная широкая сводная витрина как в оригинале | TARGET / FULL |
| `ИТОГО_v1` | MVP-версия итоговой витрины | MVP |
| `Воронка на день` | Воронка WB по товарам за день + предыдущий период + реклама + остатки | MVP/PARTIAL |
| `РасходРК` | Финансовые списания рекламы | MVP |
| `РК стата` | Статистика рекламных кампаний и товаров | MVP/PARTIAL |
| `ВБро` | Органические продажи и операционная прибыль | MANUAL_EXTERNAL_SERVICE / MANUAL_UPLOAD |
| `Точка вх` | Детальный отчет по точкам входа | CSV_ONLY / PRIVATE_ENDPOINT / NEEDS_EXPORT_SAMPLE |
| `Локализация` | Региональная локализация заказов и остатков | PARTIAL |
| `Сравнение карточек` | Wide-матрица сравнения карточек | PARTIAL |
| `Поисковые запросы` | Поисковые запросы, позиции, видимость, конверсии | MVP/PARTIAL |
| `Остатки` | Текущие остатки | MVP |
| `Backlog` | Что недоступно или требует подтверждения | MVP |
| `Validation_v1` | Проверки качества данных | MVP |
| `Coverage` | Покрытие источников и полей | MVP |
| `README` | Описание таблицы | MVP |

---

# 3. Технические processed-таблицы

| Таблица | Назначение |
|---|---|
| `dim_product` | Справочник товаров |
| `fact_funnel_day` | Воронка по дням и товарам |
| `fact_stock_snapshot` | Текущие остатки snapshot |
| `fact_stock_day` | Исторические остатки, если будет CSV/API |
| `fact_ad_cost_event` | События списаний рекламы |
| `fact_ad_cost_day` | Агрегированные расходы рекламы по дню/кампании/nm_id |
| `fact_ad_campaign_day` | Итоги рекламных кампаний по дням |
| `fact_ad_campaign_nm_day` | Статистика рекламы по товарам, типам строк и типам конверсии |
| `fact_search_query_metric` | Метрики поисковых запросов |
| `fact_profit_day` | Расчет прибыли и юнит-экономики |
| `fact_entry_point_day` | Long-таблица точек входа |
| `entry_points_wide` | Wide-pivot точек входа для `ИТОГО_FULL` |
| `fact_localization_region_day` | Локализация по товару и региону |
| `fact_localization_region_summary_day` | Сводка по регионам |
| `fact_card_comparison_metric` | Нормализованное сравнение карточек |
| `fact_mpstat_item_day` | Метрики MPStat по карточке/дню, если доступно |

---

# 4. `dim_product`

## Назначение

Справочник товаров.

## Ключ

`nm_id`

## Источник

WB Content API:

`POST https://content-api.wildberries.ru/content/v2/get/cards/list`

## Поля

| Поле | Оригинальное название | Тип | Источник |
|---|---|---|---|
| `nm_id` | Артикул WB | API | WB Content |
| `supplier_article` | Артикул продавца | API | `vendorCode` |
| `title` | Название | API | WB Content |
| `subject` | Предмет | API | WB Content |
| `category` | Категория | API/PARTIAL | WB/MPStat |
| `brand` | Бренд | API | WB Content |
| `is_deleted` | Удаленный товар | API/PARTIAL | WB Analytics/Content |
| `card_rating` | Рейтинг карточки | API/PARTIAL | WB Analytics/MPStat |
| `reviews_rating` | Рейтинг по отзывам | API/PARTIAL | WB Analytics/MPStat |
| `reviews_count` | Количество отзывов | API/PARTIAL | WB/MPStat |
| `data_status` |  | SYSTEM | pipeline |
| `source_status` |  | SYSTEM | pipeline |
| `loaded_at` |  | SYSTEM | pipeline |

---

# 5. `fact_funnel_day`

## Назначение

Нормализованная дневная воронка WB по товару.

## Ключ

`date + nm_id`

## Источник

WB Analytics sales funnel:

`POST https://seller-analytics-api.wildberries.ru/api/analytics/v3/sales-funnel/products/history`

## Поля

| Поле | Оригинальное название | Тип | Источник / расчет |
|---|---|---|---|
| `date` | Дата | API | history date |
| `nm_id` | Артикул WB | API | WB Analytics |
| `impressions` | Показы | API | WB Analytics |
| `impressions_prev` | Показы (предыдущий период) | CALCULATED | из `fact_funnel_day` за предыдущий период |
| `card_clicks` | Переходы в карточку | API | WB Analytics |
| `card_clicks_prev` | Переходы в карточку (предыдущий период) | CALCULATED | previous period |
| `ctr` | CTR / СиТиАр | API/CALCULATED | `card_clicks / impressions * 100` |
| `ctr_prev` | CTR (предыдущий период) | CALCULATED | previous period |
| `revenue_share_percent` | Доля карточки в выручке | API/PARTIAL | WB Analytics |
| `revenue_share_percent_prev` | Доля карточки в выручке (предыдущий период) | CALCULATED | previous period |
| `cartCount` | Положили в корзину | API | WB Analytics |
| `cartCount_prev` | Положили в корзину (предыдущий период) | CALCULATED | previous period |
| `addToWishlistCount` | Добавили в отложенные | API/PARTIAL | WB Analytics |
| `addToWishlistCount_prev` | Добавили в отложенные (предыдущий период) | CALCULATED | previous period |
| `orderCount` | Заказали товаров, шт | API | WB Analytics |
| `orderCount_prev` | Заказали товаров, шт (предыдущий период) | CALCULATED | previous period |
| `buyoutCount` | Выкупили, шт | API | WB Analytics |
| `buyoutCount_prev` | Выкупы, шт (предыдущий период) | CALCULATED | previous period |
| `cancelCount` | Отменили, шт | API/PARTIAL | WB Analytics |
| `cancelCount_prev` | Отменили, шт (предыдущий период) | CALCULATED | previous period |
| `addToCartConversion` | Конверсия в корзину, % | API/CALCULATED | `cartCount / card_clicks * 100` |
| `addToCartConversion_prev` | Конверсия в корзину, % (предыдущий период) | CALCULATED | previous period |
| `cartToOrderConversion` | Конверсия в заказ, % | API/CALCULATED | `orderCount / cartCount * 100` |
| `cartToOrderConversion_prev` | Конверсия в заказ, % (предыдущий период) | CALCULATED | previous period |
| `buyoutPercent` | Процент выкупа | API/CALCULATED | `buyoutCount / orderCount * 100` |
| `buyoutPercent_prev` | Процент выкупа (предыдущий период) | CALCULATED | previous period |
| `orderSum` | Заказали на сумму, ₽ | API | WB Analytics |
| `orderSum_prev` | Заказали на сумму, ₽ (предыдущий период) | CALCULATED | previous period |
| `orderSumDynamics` | Динамика суммы заказов, ₽ | CALCULATED | `orderSum - orderSum_prev` |
| `buyoutSum` | Выкупили на сумму, ₽ | API | WB Analytics |
| `buyoutSum_prev` | Выкупили на сумму, ₽ (предыдущий период) | CALCULATED | previous period |
| `cancelSum` | Отменили на сумму, ₽ | API/PARTIAL | WB Analytics |
| `cancelSum_prev` | Отменили на сумму, ₽ (предыдущий период) | CALCULATED | previous period |
| `avg_price` | Средняя цена, ₽ | API/CALCULATED | `orderSum / orderCount` |
| `avg_price_prev` | Средняя цена, ₽ (предыдущий период) | CALCULATED | previous period |
| `avg_orders_per_day` | Среднее количество заказов в день, шт | CALCULATED | `orderCount / days_count` |
| `avg_orders_per_day_prev` | Среднее количество заказов в день, шт (предыдущий период) | CALCULATED | previous period |
| `avg_delivery_time` | Среднее время доставки | API/PARTIAL | WB Analytics |
| `avg_delivery_time_prev` | Среднее время доставки (предыдущий период) | CALCULATED | previous period |
| `local_orders_percent` | Локальные заказы, % | API/PARTIAL | WB Analytics / localization |
| `local_orders_percent_prev` | Локальные заказы, % (предыдущий период) | CALCULATED | previous period |
| `data_status` |  | SYSTEM | pipeline |
| `source_status` |  | SYSTEM | pipeline |
| `loaded_at` |  | SYSTEM | pipeline |

## Важно

- Не строить от искусственной сетки `date × nm_id`.
- Не копировать один день на все даты.
- Предыдущий период считать из истории, а не хранить как независимый API-источник.

---

# 6. WB Club и юрлица в воронке

## Статус

`PARTIAL / NEEDS_API_CONFIRMATION`

## Поля WB Club

| Поле | Оригинальное название |
|---|---|
| `wbclub_orderCount` | Заказали ВБ клуб, шт |
| `wbclub_orderCount_prev` | Заказали ВБ клуб, шт (предыдущий период) |
| `wbclub_buyoutCount` | Выкупили ВБ клуб, шт |
| `wbclub_buyoutCount_prev` | Выкупы ВБ клуб, шт (предыдущий период) |
| `wbclub_cancelCount` | Отменили ВБ клуб, шт |
| `wbclub_cancelCount_prev` | Отменили ВБ клуб, шт (предыдущий период) |
| `wbclub_buyoutPercent` | Процент выкупа ВБ клуб |
| `wbclub_buyoutPercent_prev` | Процент выкупа ВБ клуб (предыдущий период) |
| `wbclub_orderSum` | Заказали на сумму ВБ клуб, ₽ |
| `wbclub_orderSum_prev` | Заказали на сумму ВБ клуб, ₽ (предыдущий период) |
| `wbclub_orderSumDynamics` | Динамика суммы заказов ВБ клуб, ₽ |
| `wbclub_buyoutSum` | Выкупили на сумму ВБ клуб, ₽ |
| `wbclub_buyoutSum_prev` | Выкупили на сумму ВБ клуб, ₽ (предыдущий период) |
| `wbclub_cancelSum` | Отменили на сумму ВБ клуб, ₽ |
| `wbclub_cancelSum_prev` | Отменили на сумму ВБ клуб, ₽ (предыдущий период) |
| `wbclub_avg_orders_per_day` | Среднее количество заказов в день ВБ клуб, шт |
| `wbclub_avg_orders_per_day_prev` | Среднее количество заказов в день ВБ клуб, шт (предыдущий период) |

## Поля юрлиц

| Поле | Оригинальное название |
|---|---|
| `b2b_orderCount` | Заказали юрлица, шт |
| `b2b_orderCount_prev` | Заказали юрлица, шт (предыдущий период) |
| `b2b_buyoutCount` | Выкупили юрлица, шт |
| `b2b_buyoutCount_prev` | Выкупили юрлица, шт (предыдущий период) |
| `b2b_cancelCount` | Отменили юрлица, шт |
| `b2b_cancelCount_prev` | Отменили юрлица, шт (предыдущий период) |
| `b2b_orderSum` | Заказали юрлица на сумму, ₽ |
| `b2b_orderSum_prev` | Заказали юрлица на сумму (предыдущий период), ₽ |
| `b2b_buyoutSum` | Выкупили юрлица на сумму, ₽ |
| `b2b_buyoutSum_prev` | Выкупили юрлица на сумму (предыдущий период), ₽ |
| `b2b_cancelSum` | Отменили юрлица на сумму, ₽ |
| `b2b_cancelSum_prev` | Отменили юрлица на сумму (предыдущий период), ₽ |

---

# 7. Пользовательская вкладка `Воронка на день`

## Назначение

Широкая пользовательская вкладка по дневной воронке.

## Ключ

`date + nm_id`

## Состоит из блоков

1. Product identity.
2. Текущий период.
3. Предыдущий период.
4. WB Club.
5. Юрлица.
6. Остатки.
7. Рекламные кабинетные метрики.
8. Служебные статусы.

## Основные поля

| Оригинальная колонка | Техническое поле | Источник |
|---|---|---|
| Артикул продавца | `supplier_article` | dim_product |
| Артикул WB | `nm_id` | dim_product / fact_funnel_day |
| Название | `title` | dim_product |
| Предмет | `subject` | dim_product |
| Бренд | `brand` | dim_product |
| Удаленный товар | `is_deleted` | dim_product / analytics |
| Рейтинг карточки | `card_rating` | dim_product / MPStat |
| Рейтинг по отзывам | `reviews_rating` | dim_product / MPStat |
| Показы | `impressions` | fact_funnel_day |
| CTR | `ctr` | fact_funnel_day |
| Доля карточки в выручке | `revenue_share_percent` | fact_funnel_day / calculated |
| Переходы в карточку | `card_clicks` | fact_funnel_day |
| Положили в корзину | `cartCount` | fact_funnel_day |
| Добавили в отложенные | `addToWishlistCount` | fact_funnel_day |
| Заказали товаров, шт | `orderCount` | fact_funnel_day |
| Выкупили, шт | `buyoutCount` | fact_funnel_day |
| Отменили, шт | `cancelCount` | fact_funnel_day |
| Конверсия в корзину, % | `addToCartConversion` | fact_funnel_day |
| Конверсия в заказ, % | `cartToOrderConversion` | fact_funnel_day |
| Процент выкупа | `buyoutPercent` | fact_funnel_day |
| Заказали на сумму, ₽ | `orderSum` | fact_funnel_day |
| Динамика суммы заказов, ₽ | `orderSumDynamics` | calculated |
| Выкупили на сумму, ₽ | `buyoutSum` | fact_funnel_day |
| Отменили на сумму, ₽ | `cancelSum` | fact_funnel_day |
| Средняя цена, ₽ | `avg_price` | fact_funnel_day |
| Среднее количество заказов в день, шт | `avg_orders_per_day` | calculated |
| Остатки склад ВБ, шт | `wb_stock_qty` | fact_stock_snapshot |
| Остатки МП, шт | `mp_stock_qty` | fact_stock_snapshot |
| Сумма остатков на складах, ₽ | `stock_total_sum` | fact_stock_snapshot |
| Среднее время доставки | `avg_delivery_time` | fact_funnel_day/localization |
| Локальные заказы, % | `local_orders_percent` | fact_funnel_day/localization |

## Рекламные кабинетные метрики в `Воронка на день`

| Оригинальная колонка | Техническое поле | Источник |
|---|---|---|
| процент показов рекламных | `ad_impressions_percent` | calculated |
| показы РК | `ad_views` | fact_ad_campaign_nm_day |
| переплат за корзину в сравнении со вчера | `cart_overpay_vs_yesterday` | calculated |
| конверсия из показа в корзину | `ad_view_to_cart_conversion` | calculated |
| стоимость клика за кабинет | `cabinet_cpc` | fact_ad_campaign_nm_day |
| стоимость корзины за кабинет | `cabinet_cost_per_cart` | calculated |
| стоимость заказа за кабинет (CPO) | `cabinet_cpo` | calculated |
| стоимость 1000 показов за кабинет | `cabinet_cpm` | fact_ad_campaign_nm_day |
| рк | `campaign_name_or_id` | fact_ad_campaign_nm_day |

---

# 8. `fact_stock_snapshot`

## Назначение

Текущие остатки snapshot.

## Ключ

`snapshot_date + nm_id`

## Источник

WB stocks products/offices.

## Поля

| Поле | Оригинальное название | Тип |
|---|---|---|
| `snapshot_date` | Дата снимка | SYSTEM/API |
| `nm_id` | Артикул WB | API |
| `supplier_article` | Артикул продавца | dim_product |
| `title` | Название | dim_product |
| `subject` | Предмет | dim_product |
| `brand` | Бренд | dim_product |
| `wb_stock_qty` | Остатки склад ВБ, шт | API/PARTIAL |
| `mp_stock_qty` | Остатки МП, шт / Свой склад | API/PARTIAL |
| `stock_total_qty` | Общий остаток, шт | CALCULATED |
| `stock_total_sum` | Сумма остатков на складах, ₽ | API/CALCULATED |
| `saleRate` | Скорость продаж | API/PARTIAL |
| `toClientCount` | В пути к клиенту | API/PARTIAL |
| `fromClientCount` | Возвраты | API/PARTIAL |
| `availability` | Наличие | CALCULATED |
| `data_status` |  | SYSTEM |
| `source_status` |  | SYSTEM |
| `loaded_at` |  | SYSTEM |

---

# 9. `РасходРК`

## Назначение

Пользовательская вкладка финансовых списаний рекламы.

## Оригинальные колонки

| Оригинальная колонка | Техническое поле |
|---|---|
| ID кампании | `advertId` |
| Кампания | `campaign_name` |
| Раздел | `section_raw` |
| Дата списания | `writeoff_datetime` |
| Источник списания | `writeoff_source` |
| Сумма | `spend` |
| Номер документа | `document_number` |

## Техническая таблица `fact_ad_cost_event`

### Ключ

`date + advertId + writeoff_datetime + document_number`

### Поля

| Поле | Тип | Правило |
|---|---|---|
| `date` | CALCULATED | дата из `writeoff_datetime` |
| `advertId` | API | ID кампании |
| `campaign_name` | API | название кампании |
| `section_raw` | API/CSV | оригинальное значение колонки `Раздел` |
| `writeoff_datetime` | API | дата и время списания |
| `writeoff_source` | API | источник списания |
| `spend` | API | сумма |
| `document_number` | API | номер документа |
| `nm_id_from_section` | CALCULATED | если `section_raw` число |
| `nm_id_from_campaign_name` | CALCULATED | regex `Арт.\s*(\d+)` |
| `nm_id` | CALCULATED/PARTIAL | итоговый nm_id |
| `nm_id_parse_status` | SYSTEM | `FROM_SECTION` / `FROM_CAMPAIGN_NAME` / `NOT_FOUND` |
| `campaign_type` | CALCULATED/PARTIAL | Буст / Поиск / Единая ставка / Ручная ставка / Клик |
| `currency` | SYSTEM | RUB |
| `data_status` | SYSTEM | status |
| `source_status` | SYSTEM | source |
| `loaded_at` | SYSTEM | loaded_at |

## Агрегат `fact_ad_cost_day`

| Поле | Назначение |
|---|---|
| `date` | дата |
| `advertId` | ID кампании |
| `campaign_name` | кампания |
| `nm_id` | товар, если удалось определить |
| `total_spend` | сумма расходов за день |
| `events_count` | количество событий |
| `allocation_status` | `ALLOCATED` / `UNALLOCATED` / `PARTIAL` |
| `data_status` | статус |
| `source_status` | источник |
| `loaded_at` | дата загрузки |

---

# 10. `РК стата`

## Назначение

Новая пользовательская вкладка статистики рекламных кампаний и товаров.

## Правило боевого режима

Для production-run статистику рекламных кампаний брать минимум за `D-2`, а не за вчера, потому что WB может не успеть обработать данные за вчера.

## Ключи

Для строки `Итог кампании`:

`date + advertId + row_type`

Для строки `Товар`:

`date + advertId + row_type + conversion_type + nm_id`

## Оригинальные колонки и mapping

| Оригинальная колонка | Техническое поле |
|---|---|
| Дата | `date` |
| ID кампании | `advertId` |
| Название кампании | `campaign_name` |
| Тип строки | `row_type` |
| Тип конверсии | `conversion_type_raw` |
| Номенклатура | `nm_id` |
| Название товара | `product_name` |
| Затраты, ₽ | `ad_spend` |
| Выручка, ₽ | `ad_revenue` |
| Показы | `ad_views` |
| Клики | `ad_clicks` |
| Добавления в корзину | `ad_atbs` |
| Заказы | `ad_orders` |
| Заказанные товары, шт. | `ordered_items_qty` |
| Отмены | `ad_cancels` |
| Средняя позиция | `avg_position` |
| CTR, % | `ad_ctr` |
| CPC, ₽ | `ad_cpc` |
| CPM, ₽ | `ad_cpm` |
| CR, % | `ad_cr` |
| ROI, % | `ad_roi` |

## Типы строк

| Русское значение | Техническое значение |
|---|---|
| Итог кампании | `CAMPAIGN_TOTAL` |
| Товар | `PRODUCT` |

## Типы конверсии

| Русское значение | Техническое значение |
|---|---|
| Ассоциированная | `ASSOCIATED` |
| Прямая | `DIRECT` |
| Мультикарточка | `MULTICARD` |

## `fact_ad_campaign_day`

Строки уровня `Итог кампании`.

Поля:

```text
date
advertId
campaign_name
row_type
ad_spend
ad_revenue
ad_views
ad_clicks
ad_atbs
ad_orders
ordered_items_qty
ad_cancels
avg_position
ad_ctr
ad_cpc
ad_cpm
ad_cr
ad_roi
currency
data_status
source_status
loaded_at
```

## `fact_ad_campaign_nm_day`

Строки уровня товара.

Поля:

```text
date
advertId
campaign_name
row_type
conversion_type
conversion_type_raw
nm_id
product_name
ad_spend
ad_revenue
ad_views
ad_clicks
ad_atbs
ad_orders
ordered_items_qty
ad_cancels
avg_position
ad_ctr
ad_cpc
ad_cpm
ad_cr
ad_roi
currency
data_status
source_status
loaded_at
```

## Для `ИТОГО_FULL`

Из `fact_ad_campaign_nm_day` считаются:

```text
direct_ad_atbs
associated_ad_atbs
multicard_ad_atbs
direct_ad_orders
associated_ad_orders
multicard_ad_orders
associated_atbs_percent
```

---

# 11. `ВБро`

## Назначение

Пользовательская вкладка прибыли.

## Оригинальные колонки

| Оригинальная колонка | Техническое поле |
|---|---|
| Дата | `date` |
| Артикул ВБ | `nm_id` |
| Артикул продавца | `supplier_article` |
| Продажи (органические) | `organic_sales_qty` |
| Операционная прибыль | `operating_profit` |
| Операционная прибыль на единицу | `operating_profit_per_unit` |

## Статус

`MANUAL_EXTERNAL_SERVICE / MANUAL_UPLOAD`

Операционная прибыль и ВБро подтверждены сотрудником как ручная выгрузка из внешнего сервиса. В текущем этапе проект не считает прибыль, не требует COGS и не пытается автоматически заполнить эти поля.

## `fact_profit_day`

Расширенная техническая таблица.

| Поле | Назначение |
|---|---|
| `date` | дата |
| `nm_id` | артикул WB |
| `supplier_article` | артикул продавца |
| `organic_sales_qty` | органические продажи |
| `net_sales_payout` | к перечислению |
| `ad_spend` | реклама |
| `logistics` | логистика |
| `storage` | хранение |
| `penalties` | штрафы |
| `deductions` | удержания |
| `acceptance` | приемка |
| `cogs` | себестоимость |
| `other_costs` | прочие расходы |
| `operating_profit` | операционная прибыль |
| `operating_profit_per_unit` | операционная прибыль на единицу |
| `data_status` | статус |
| `source_status` | источник |
| `loaded_at` | дата загрузки |

## Текущий режим

`fact_profit_day` можно использовать только как техническую финансовую базу из WB-источников.

Поля:

- `operating_profit`
- `operating_profit_per_unit`

в пользовательской вкладке остаются пустыми до ручной выгрузки из внешнего сервиса.

---

# 12. `Точка вх`

## Назначение

Детальный отчет по точкам входа.

## Статус

`CSV_ONLY / PRIVATE_ENDPOINT / NEEDS_EXPORT_SAMPLE`

Публичный API пока не подтвержден. Целевой источник:

- Аналитика развития бизнеса / Портрет покупателя
- https://seller.wildberries.ru/platform-analytics/customer-profile

Для продолжения нужен CSV/Excel пример или доступ к кабинету.

## Пользовательская вкладка

Оригинальные колонки:

| Оригинальная колонка | Техническое поле |
|---|---|
| Раздел | `section` |
| Точка входа | `entry_point` |
| Артикул ВБ | `nm_id` |
| Артикул продавца | `supplier_article` |
| Бренд | `brand` |
| Название | `title` |
| Предмет | `subject` |
| Показы | `impressions` |
| Переходы в карточку | `card_clicks` |
| CTR | `ctr` |
| Добавления в корзину | `add_to_cart` |
| Конверсия в корзину | `cart_conversion` |
| Заказы | `orders` |
| Конверсия в заказ | `order_conversion` |

## `fact_entry_point_day`

Ключ:

`date + nm_id + section + entry_point`

Поля:

```text
date
period_start
period_end
section
entry_point
nm_id
supplier_article
brand
title
subject
impressions
card_clicks
ctr
add_to_cart
cart_conversion
orders
order_conversion
data_status
source_status
loaded_at
```

## `entry_points_wide`

Назначение: wide-pivot для `ИТОГО_FULL`.

Ключ:

`date + nm_id`

Колонки точек входа динамические. Сначала используем метрику `impressions`.

Примеры динамических колонок:

```text
Подборки и рекомендации (Карточка)
Кнопка «Похожие»
Рекомендации продавца
Бренд и его категории
Блок «Ещё предложения»
Поисковая выдача
Поиск по тегам
Поиск по категории
Подборки и рекомендации (Главная)
Баннер (Главная)
Покупки
Доставка
Личный кабинет
Экран с QR-кодом
Отзывы и вопросы
Страница «Ничего не нашлось»
Чаты и возвраты
Карусель
На товар
Выдача в категории
Баннер (Каталог)
Блок «Вы недавно смотрели»
Лист ожидания
Блоки «Избранное» и «Отложенное»
Корзина
Каталог товаров в акции
Категории (акции)
Подборки с товарами в акции
```

---

# 13. `Локализация`

## Назначение

Региональная локализация заказов и остатков.

## Статус

`PARTIAL / CSV_EXPORT / NEEDS_API_CONFIRMATION`

Текущий подтвержденный источник:

- `region-sale` как partial API

Целевой источник для недостающих geography-полей:

- Аналитика остатков / География заказов
- https://seller.wildberries.ru/remains-analytics/orders-geography

Для продолжения нужен CSV/Excel пример или доступ к кабинету.

## Пользовательская вкладка состоит из двух зон

1. Детальная таблица по товару и региону.
2. Сводка по регионам за дату.

## `fact_localization_region_day`

Ключ:

`date + nm_id + region`

Поля:

| Поле | Оригинальная колонка |
|---|---|
| `date` | дата отчета |
| `supplier_article` | Артикул продавца |
| `title` | Название |
| `nm_id` | Артикул WB |
| `subject` | Предмет |
| `brand` | Бренд |
| `region` | Регион |
| `delivery_time` | Время доставки |
| `orders_total_qty` | Итого заказов, шт |
| `orders_local_qty` | Итого заказов по товарам локально, шт |
| `orders_nonlocal_qty` | Итого заказов по товарам не локально, шт |
| `orders_nonlocal_percent` | Итого заказы по товарам не локально, % |
| `wb_stock_orders_local_qty` | Заказы со склада ВБ локально, шт |
| `wb_stock_orders_nonlocal_qty` | Заказы со склада ВБ не локально, шт |
| `wb_stock_orders_nonlocal_percent` | Заказы со склада ВБ не локально, % |
| `mp_orders_local_qty` | Заказы Маркетплейс локально, шт |
| `mp_orders_nonlocal_qty` | Заказы Маркетплейс не локально, шт |
| `mp_orders_nonlocal_percent` | Заказы Маркетплейс не локально, % |
| `wb_stock_qty` | Остатки склад ВБ, шт |
| `mp_stock_qty` | Остатки МП, шт |
| `data_status` | статус |
| `source_status` | источник |
| `loaded_at` | дата загрузки |

## `fact_localization_region_summary_day`

Ключ:

`date + region`

Поля:

| Поле | Оригинальная колонка |
|---|---|
| `date` | дата отчета |
| `region` | Регион |
| `local_orders_percent` | Локальные заказы, % |
| `nonlocal_orders_percent` | Не локальные заказы, % |
| `delivery_time` | Время доставки |
| `region_orders_share_percent` | Доля региона в заказах, % |
| `wb_all_orders_share_percent` | Доля всех заказов ВБ, % |
| `data_status` | статус |
| `source_status` | источник |
| `loaded_at` | дата загрузки |

---

# 14. `Сравнение карточек`

## Назначение

Wide-матрица сравнения базового артикула с другими карточками.

## Пользовательская структура

Строки:

`Показатели`

Колонки динамические:

```text
Артикул WB {base_nm_id}
Артикул WB {compared_nm_id}
Разница артикул {compared_nm_id} - артикул {base_nm_id}
Артикул WB {base_nm_id} (предыдущий период)
Артикул WB {compared_nm_id} (предыдущий период)
Разница артикул {compared_nm_id} - артикул {base_nm_id} (предыдущий период)
```

## Группы показателей

| Группа | Метрики |
|---|---|
| `product_identity` | Название, Категория, Предмет, Бренд |
| `reputation` | Рейтинг карточки, Рейтинг по отзывам, Количество отзывов |
| `price` | Минимальная цена со скидкой, Максимальная цена со скидкой, Медианная цена покупателя |
| `logistics` | Среднее время доставки |
| `search_position` | Средняя позиция |
| `funnel` | Показы, Переходы, CTR, Корзины, Заказы, Выкупы, Конверсии |

## `fact_card_comparison_metric`

Ключ:

`period_start + period_end + base_nm_id + compared_nm_id + metric_name`

Поля:

```text
period_start
period_end
base_nm_id
compared_nm_id
metric_name
metric_group
base_value
compared_value
difference
difference_percent
base_value_prev
compared_value_prev
difference_prev
difference_percent_prev
data_status
source_status
loaded_at
```

## Источники

| Тип карточки | Источник |
|---|---|
| Свои товары | WB API + processed facts |
| Чужие карточки | MPStat / внешний сервис |

Статус: `PARTIAL`.

---

# 15. `Поисковые запросы`

## Назначение

Поисковые запросы по товару: частотность, видимость, позиции, переходы, корзины, заказы, конверсии и сравнение с конкурентами.

## Оригинальные колонки

| Оригинальная колонка | Техническое поле |
|---|---|
| Артикул продавца | `supplier_article` |
| Артикул WB | `nm_id` |
| Название | `title` |
| Предмет | `subject` |
| Бренд | `brand` |
| Рейтинг карточки | `card_rating` |
| Рейтинг по отзывам | `reviews_rating` |
| Поисковый запрос | `search_query` |
| Количество запросов | `query_count` |
| Количество запросов (предыдущий период) | `query_count_prev` |
| Видимость, % | `visibility` |
| Видимость, % (предыдущий период) | `visibility_prev` |
| Средняя позиция | `avg_position` |
| Средняя позиция (предыдущий период) | `avg_position_prev` |
| Медианная позиция | `median_position` |
| Медианная позиция (предыдущий период) | `median_position_prev` |
| Переходы в карточку | `search_clicks` |
| Переходы в карточку (предыдущий период) | `search_clicks_prev` |
| Переходы в карточку больше, чем у n% карточек конкурентов, % | `search_clicks_competitor_percentile` |
| Положили в корзину | `search_cart` |
| Положили в корзину (предыдущий период) | `search_cart_prev` |
| Положили в корзину больше, чем n% карточек конкурентов, % | `search_cart_competitor_percentile` |
| Конверсия в корзину, % | `cart_conversion` |
| Конверсия в корзину, % (предыдущий период) | `cart_conversion_prev` |
| Конверсия в корзину больше, чем у n% карточек конкурентов, % | `cart_conversion_competitor_percentile` |
| Заказали, шт | `search_orders` |
| Заказали, шт (предыдущий период) | `search_orders_prev` |
| Заказали больше, чем n% карточек конкурентов, % | `search_orders_competitor_percentile` |
| Конверсия в заказ, % | `order_conversion` |
| Конверсия в заказ, % (предыдущий период) | `order_conversion_prev` |
| Конверсия в заказ больше, чем у n% карточек конкурентов, % | `order_conversion_competitor_percentile` |
| Минимальная цена со скидкой (по размерам), ₽ | `min_discount_price` |
| Максимальная цена со скидкой (по размерам), ₽ | `max_discount_price` |

## `fact_search_query_metric`

Ключ:

`period_start + period_end + nm_id + search_query`

Поля:

```text
period_start
period_end
date
nm_id
supplier_article
title
subject
brand
card_rating
reviews_rating
search_query
query_count
query_count_prev
visibility
visibility_prev
avg_position
avg_position_prev
median_position
median_position_prev
search_clicks
search_clicks_prev
search_clicks_competitor_percentile
search_cart
search_cart_prev
search_cart_competitor_percentile
cart_conversion
cart_conversion_prev
cart_conversion_competitor_percentile
search_orders
search_orders_prev
search_orders_competitor_percentile
order_conversion
order_conversion_prev
order_conversion_competitor_percentile
min_discount_price
max_discount_price
data_status
source_status
loaded_at
```

## Источник

WB Search report / Джем:

- `search-texts`
- `orders`
- возможно CSV/export для competitor percentile

## Важно

1. Если API возвращает периодные данные, не размножать их на каждый день.
2. Previous period считать отдельным запросом/периодом, а не копировать.
3. Метрики “больше, чем у n% конкурентов” могут быть недоступны в публичном API. Тогда статус `PARTIAL`.
4. Для `ИТОГО_FULL` поисковые запросы могут разворачиваться в wide-матрицу, где один запрос = одна колонка.

---

# 16. `ИТОГО_v1`

## Назначение

MVP-итоговая витрина, которую реально собрать первой.

## Ключ

`date + nm_id`

## База

`fact_funnel_day`

## Источники

- `fact_funnel_day`
- `dim_product`
- `fact_stock_snapshot`
- `fact_ad_campaign_nm_day`
- `fact_search_query_metric`
- позже `fact_profit_day`

## Поля MVP

```text
date
nm_id
supplier_article
title
subject
brand
impressions
card_clicks
ctr
cartCount
orderCount
orderSum
buyoutCount
buyoutSum
buyoutPercent
addToCartConversion
cartToOrderConversion
addToWishlistCount
ad_views
ad_clicks
ad_ctr
ad_cpc
ad_orders
ad_atbs
ad_spend
ad_revenue
cost_per_cart
cpm
cpo
search_queries_count
avg_position
visibility
search_clicks
search_cart
search_orders
current_stockCount
current_stockSum
stock_snapshot_date
data_status
source_status
loaded_at
```

## Проверки

```python
assert total_df.columns.is_unique
```

Проверить:

- нет дублей `date + nm_id`;
- нет mock/fake;
- нет дублей колонок;
- реклама не размножена;
- остатки имеют `stock_snapshot_date`.

---

# 17. `ИТОГО_FULL` / оригинальная вкладка `ИТОГО`

## Назначение

Полная широкая витрина как в оригинальной таблице.

## Статус

`TARGET / FULL`

## Ключ

`date + nm_id + supplier_article`

## Блоки

1. `base_funnel_block`
2. `ads_summary_block`
3. `ad_campaign_wide_block`
4. `associated_carts_block`
5. `profit_block`
6. `entry_points_wide_block`
7. `mpstat_block`
8. `localization_wide_block`
9. `search_queries_wide_block`

## Базовый блок

| Оригинальная колонка | Техническое поле |
|---|---|
| Артикул продавца | `supplier_article` |
| Артикул WB | `nm_id` |
| Дата | `date` |
| Показы | `impressions` |
| Переходы в карточку | `card_clicks` |
| Положили в корзину | `cartCount` |
| Заказали, шт | `orderCount` |
| CTR / СиТиАр | `ctr` |
| Конверсия в корзину, % | `addToCartConversion` |
| Конверсия в заказ, % | `cartToOrderConversion` |
| Заказали на сумму, ₽ | `orderSum` |
| Расход на все корзины | `ad_spend / cartCount` или `ad_spend / ad_atbs` — `NEEDS_FORMULA_CONFIRMATION` |
| Локальные заказы, % | `local_orders_percent` |

## Рекламный wide-блок

Динамические колонки по рекламным кампаниям:

```text
Затраты РК/Раньше было (Реальная корзина)
корзин от этой РК (эффективность РК)
CTR корзины
цена корзин от этой РК (эффективность РК)
Показы РК этого артикула
CPM
```

Источник:

`fact_ad_campaign_nm_day` + `fact_ad_cost_day`.

## Ассоциированные корзины

Поля:

```text
own_ad_carts
associated_carts
associated_carts_percent
all_ad_carts_for_nm
stolen_carts
associated_carts_all
associated_carts_low_spend
direct_ad_atbs
associated_ad_atbs
multicard_ad_atbs
```

Источник:

`fact_ad_campaign_nm_day.conversion_type`.

## Profit block

Источник:

`fact_profit_day`.

Поля:

```text
organic_sales_qty
operating_profit
operating_profit_per_unit
```

## Entry points wide block

Источник:

`entry_points_wide`.

Колонки динамические по точкам входа.

## MPStat block

Источник:

`fact_mpstat_item_day`.

Поля:

```text
mpstat_card_rating
mpstat_reviews_rating
mpstat_avg_delivery_time
mpstat_avg_position
mpstat_impressions
mpstat_card_clicks
mpstat_cart
mpstat_orders
mpstat_buyouts
mpstat_ctr
mpstat_cart_conversion
mpstat_order_conversion
mpstat_buyout_percent
```

Статус:

`PARTIAL / NEEDS_API_CONFIRMATION`.

## Localization wide block

Источник:

`fact_localization_region_day` + `fact_localization_region_summary_day`.

Колонки динамические по регионам.

## Search queries wide block

Источник:

`fact_search_query_metric`.

Колонки динамические, один поисковый запрос = одна колонка. Для хранения используется long-таблица, wide нужен только для отчета.

---

# 18. `Backlog`

## Базовые строки

| block | status | reason | next_step | priority |
|---|---|---|---|---|
| Точка входа | CSV_ONLY / PRIVATE_ENDPOINT / NEEDS_EXPORT_SAMPLE | Нужен seller-cabinet export из customer-profile | получить CSV/Excel пример или доступ к кабинету | high |
| ВБро | MANUAL_EXTERNAL_SERVICE / MANUAL_UPLOAD | Операционная прибыль ведется вручную во внешнем сервисе | получить manual upload/export flow, если понадобится заполнение | high |
| Локализация | PARTIAL | region-sale остается partial; недостающие поля ожидаются из orders-geography | получить CSV/Excel пример или доступ к кабинету | medium |
| Сравнение карточек | PARTIAL | Для чужих карточек нужен MPStat | проверить MPStat | medium |
| Search competitor percentiles | PARTIAL | Метрики “лучше n% конкурентов” могут быть только в кабинете/Джем | проверить API/export | medium |
| MPStat | PARTIAL | Нужно подтвердить endpoints и доступ | исправить base URL и smoke test | medium |
| Исторические остатки | CSV_ONLY | История через CSV/API flow | исследовать | medium |
| Настройки_артикулы | LATER | Нужна отдельная вкладка управления рабочим списком артикулов | создать tab с полями nm_id, supplier_article, group_name, item_type, active, comment | medium |

---

# 19. `Validation_v1`

## Колонки

| Колонка | Смысл |
|---|---|
| `sheet_name` | источник предупреждения |
| `date` | дата строки |
| `nm_id` | артикул WB |
| `impressions` | показы |
| `card_clicks` | переходы в карточку |
| `ctr` | CTR строки |
| `reason` | текст предупреждения |

## Текущее правило

Если в `Воронка на день`:

- `CTR >= 80`

то в `Validation_v1` добавляется warning:

- `reason = suspicious_ctr: CTR >= 80, verify WB source manually`

CTR автоматически не исправляется.

---

# 20. Минимальный план разработки

## Этап 1. Синхронизация структуры

- обновить Google Sheets заголовки;
- добавить новую вкладку `РК стата`;
- добавить/зафиксировать технические processed-таблицы;
- не заполнять mock-данные.

## Этап 2. Real API smoke test

Проверить:

- WB Content;
- WB Analytics sales funnel;
- WB Promotion fullstats;
- WB Promotion costs;
- WB Search/Jam;
- WB Stocks;
- Google Sheets.

## Этап 3. MVP run

Заполнить на 5 nmID × 2 дня:

- `dim_product`;
- `fact_funnel_day`;
- `fact_stock_snapshot`;
- `fact_ad_cost_event`;
- `fact_ad_campaign_day`;
- `fact_ad_campaign_nm_day`;
- `fact_search_query_metric`;
- `Воронка на день`;
- `РасходРК`;
- `РК стата`;
- `Поисковые запросы`;
- `Остатки`;
- `ИТОГО_v1`;
- `Validation_v1`;
- `Backlog`.

## Этап 4. FULL reports

После успешного MVP:

- `ИТОГО_FULL`;
- `Точка вх`;
- `Локализация`;
- `Сравнение карточек`;
- `ВБро`.

## Этап 5. Управляемый список артикулов

Добавить вкладку `Настройки_артикулы` со структурой:

- `nm_id`
- `supplier_article`
- `group_name`
- `item_type`
- `active`
- `comment`

Допустимые `item_type`:

- `normal`
- `bundle`
- `glue`
- `multicard`

---

# 21. Главный принцип архитектуры

Для разработки и API используем нормализованные таблицы:

```text
dim_product
fact_funnel_day
fact_ad_cost_event
fact_ad_cost_day
fact_ad_campaign_day
fact_ad_campaign_nm_day
fact_search_query_metric
fact_stock_snapshot
fact_profit_day
fact_entry_point_day
fact_localization_region_day
fact_card_comparison_metric
```

Для пользователя собираем широкие отчеты:

```text
ИТОГО_FULL
Воронка на день
РасходРК
РК стата
ВБро
Точка вх
Локализация
Сравнение карточек
Поисковые запросы
```

Так мы не теряем структуру, не плодим фейковые значения и можем постепенно подключать реальные источники.
