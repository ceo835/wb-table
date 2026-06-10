# Current API Coverage

## Wildberries APIs

### Content API
| Endpoint | Status | Notes |
|----------|--------|-------|
| `/content/v2/get-catalog` | ✅ Audited | Получение структуры каталога |
| `/content/v2/object/list` | ✅ Audited | Список товаров |
| `/content/v2/object/update-by-id` | ⏳ Pending | Обновление товаров |

### Analytics API
| Endpoint | Status | Notes |
|----------|--------|-------|
| `/analytics/api/v2/suppliers/report` | ✅ Audited | Отчет поставщика |
| `/analytics/api/v2/orders` | ✅ Audited | Заказы |
| `/analytics/api/v2/stocks` | ✅ Audited | Остатки |

### Statistics API
| Endpoint | Status | Notes |
|----------|--------|-------|
| `/statistics/api/v2/sales` | ✅ Audited | Продажи |
| `/statistics/api/v2/detailperiod` | ✅ Audited | Детализация по периодам |

### Promotion API
| Endpoint | Status | Notes |
|----------|--------|-------|
| `/promotion/api/v1/campaigns` | ✅ Audited | Список кампаний |
| `/promotion/api/v1/stats` | ✅ Audited | Статистика кампаний |

## MPStats API

| Endpoint | Status | Notes |
|----------|--------|-------|
| `/api/marketplace/analitics/realization` | ✅ Audited | Реализации |
| `/api/marketplace/analitics/storage` | ✅ Audited | Склад |
| `/api/marketplace/nomenclature/list` | ✅ Audited | Номенклатура |

## Google Sheets Integration

| Feature | Status | Notes |
|---------|--------|-------|
| Authentication | ⏳ Pending | Service Account |
| Read Data | ⏳ Pending | - |
| Write Data | ⏳ Pending | - |
| Create Sheet | ⏳ Pending | - |

## Legend
- ✅ Audited - API endpoint изучен, есть результаты аудита
- 🔄 In Progress - В разработке
- ⏳ Pending - Запланировано
- ❌ Not Planned - Не планируется

## Raw Audit Files
Результаты аудита API находятся в директории `docs/api_audit/`.

**Важно:** Raw-ответы API не сохраняются в репозитории.
