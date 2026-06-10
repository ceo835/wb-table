# Результаты Smoke Test реальных API

Дата теста: 2026-05-29 16:54:50

## WBContentClient - wb_content_cards_list

- Статус: passed

- Кол-во записей: 0

- Путь к raw файлу: C:\Users\User\Desktop\WB_table-main\WB_table-main\data\raw\WBContentClient__wb_content_cards_list__20260529_165444.json

## WBContentClient - wb_content_get_characteristics

- Статус: failed

- Кол-во записей: 0

- Кол-во nmIDs: 2

- Путь к raw файлу: C:\Users\User\Desktop\WB_table-main\WB_table-main\data\raw\WBContentClient__wb_content_get_characteristics__20260529_165445.json

## WBAnalyticsClient - wb_sales_funnel_history

- Статус: error

- Ошибка: HTTPSConnectionPool(host='analytics-api.wildberries.ru', port=443): Max retries exceeded with url: /ru/v1/sales/funnel/history?dateFrom=2026-05-27&dateTo=2026-05-29 (Caused by NameResolutionError("HTTPSConnection(host='analytics-api.wildberries.ru', port=443): Failed to resolve 'analytics-api.wildberries.ru' ([Errno 11001] getaddrinfo failed)"))

- Кол-во записей: 0

- Период: 2026-05-27 - 2026-05-29

- Путь к raw файлу: None

## WBStatisticsClient - wb_statistics_orders

- Статус: failed

- Кол-во записей: 0

- Период: 2026-05-27 - 2026-05-29

- Путь к raw файлу: C:\Users\User\Desktop\WB_table-main\WB_table-main\data\raw\WBStatisticsClient__wb_statistics_orders__20260529_165446.json

## WBPromotionClient - wb_adv_fullstats

- Статус: failed

- Кол-во записей: 0

- Период: 2026-05-27 - 2026-05-29

- Путь к raw файлу: C:\Users\User\Desktop\WB_table-main\WB_table-main\data\raw\WBPromotionClient__wb_adv_fullstats__20260529_165447.json

## MPStatsClient - mpstats_item_full

- Статус: error

- Ошибка: HTTPSConnectionPool(host='api.mpstats.io', port=443): Max retries exceeded with url: /item/1 (Caused by NameResolutionError("HTTPSConnection(host='api.mpstats.io', port=443): Failed to resolve 'api.mpstats.io' ([Errno 11001] getaddrinfo failed)"))

- Кол-во записей: 0

- Кол-во nmIDs: 1

- Путь к raw файлу: None

## GoogleSheets - health_check

- Статус: passed

- Кол-во записей: 13

- Путь к raw файлу: None
