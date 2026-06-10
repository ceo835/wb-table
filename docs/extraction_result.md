# Extraction Results Report

## Execution Summary

**Дата запуска:** 2025-05-28  
**Диапазон дат:** последние 2 дня  
**Тестовые nmIDs:** 12345678, 87654321, 11223344, 55667788, 99887766  
**Выходная директория:** `data/raw/`

---

## Реализованные экстракторы

### 1. Products (`src/extractors/products.py`)
- **Источник:** `wb_content_cards_list`
- **Описание:** Загрузка карточек товаров из WB Content API
- **Параметры:** `nm_ids`, `date_from`, `date_to`
- **Формат вывода:** JSON

### 2. Funnel (`src/extractors/funnel.py`)
- **Источник:** `wb_sales_funnel_history`
- **Описание:** История воронки продаж
- **Параметры:** `date_from`, `date_to`, `nm_ids`
- **Формат вывода:** JSON

### 3. Stocks (`src/extractors/stocks.py`)
- **Источники:**
  - `wb_stocks_products` — остатки по товарам
  - `wb_stocks_offices` — остатки по складам
  - `wb_stock_history_daily_csv` — история остатков (CSV, если доступно)
- **Параметры:** `date_from`, `date_to`, `nm_ids`
- **Формат вывода:** JSON / CSV

### 4. Ads (`src/extractors/ads.py`)
- **Источники:**
  - `wb_adv_costs` — расходы на рекламу
  - `wb_adv_fullstats` — полная статистика рекламы
- **Параметры:** `date_from`, `date_to`, `nm_ids`
- **Формат вывода:** JSON

### 5. Search Queries (`src/extractors/search_queries.py`)
- **Источники:**
  - `wb_search_texts` — поисковые запросы
  - `wb_search_orders` — заказы из поиска
- **Параметры:** `date_from`, `date_to`, `nm_ids`
- **Формат вывода:** JSON

### 6. Finance (`src/extractors/finance.py`)
- **Источники:**
  - `wb_statistics_orders` — заказы из статистики
  - `wb_report_detail_by_period` — детальный отчёт за период
- **Параметры:** `date_from`, `date_to`, `nm_ids`
- **Формат вывода:** JSON

### 7. MPStat (`src/extractors/mpstat.py`)
- **Источники:**
  - `mpstats_item_full` — полные данные о товаре
  - `mpstats_item_sales` — продажи товара
  - `mpstats_item_by_category` — товары по категории
- **Параметры:** `nm_ids`, `date_from`, `date_to`, `category_id`
- **Формат вывода:** JSON

---

## Как запустить

### Базовый запуск (последние 2 дня, тестовые nmIDs):
```bash
python scripts/run_extraction.py
```

### С указанием параметров:
```bash
python scripts/run_extraction.py \
    --date-from 2025-05-26 \
    --date-to 2025-05-28 \
    --nm-ids 12345678,87654321,11223344 \
    --output-dir data/raw
```

---

## Структура выходных файлов

Все raw-данные сохраняются в `data/raw/` с именами вида:
- `wb_content_cards_list_YYYYMMDD_HHMMSS.json`
- `wb_sales_funnel_history_YYYY-MM-DD_YYYY-MM-DD_YYYYMMDD_HHMMSS.json`
- `wb_stocks_products_YYYY-MM-DD_YYYY-MM-DD_YYYYMMDD_HHMMSS.json`
- `wb_adv_costs_YYYY-MM-DD_YYYY-MM-DD_YYYYMMDD_HHMMSS.json`
- `mpstats_item_full_YYYYMMDD_HHMMSS.json`
- и т.д.

Также создаётся файл summary:
- `extraction_summary_YYYYMMDD_HHMMSS.json`

---

## Примечания

- ⚠️ **Важно:** Файлы из `data/raw/` не должны коммититься в Git (добавлены в `.gitignore`)
- 🔐 Токены загружаются только из переменных окружения (`.env`)
- 📊 Все запросы read-only
- 🔄 При ошибке 429 (rate limit) автоматически выполняется retry с паузой

---

## Статус выполнения

| Экстрактор | Источники | Статус |
|------------|-----------|--------|
| Products | wb_content_cards_list | ✅ Реализован |
| Funnel | wb_sales_funnel_history | ✅ Реализован |
| Stocks | wb_stocks_products, wb_stocks_offices, wb_stock_history_daily_csv | ✅ Реализован |
| Ads | wb_adv_costs, wb_adv_fullstats | ✅ Реализован |
| Search Queries | wb_search_texts, wb_search_orders | ✅ Реализован |
| Finance | wb_statistics_orders, wb_report_detail_by_period | ✅ Реализован |
| MPStat | mpstats_item_full, mpstats_item_sales, mpstats_item_by_category | ✅ Реализован |

**Всего источников:** 13  
**Реализовано:** 13
