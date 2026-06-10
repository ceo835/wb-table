# Project Plan: WB_table

## Overview
Проект для автоматической сборки большой таблицы аналитики Wildberries с интеграцией данных из различных источников.

## Architecture
Проект следует архитектуре ETL (Extract, Transform, Load):

```
src/
├── config/          # Конфигурация и настройки
├── clients/         # API клиенты (WB, MPStats, Google)
├── extractors/      # Извлечение данных из источников
├── transformers/    # Преобразование и очистка данных
├── loaders/         # Загрузка данных в целевые системы
├── reports/         # Генерация отчетов
├── sheets/          # Работа с Google Sheets
└── utils/           # Утилиты и вспомогательные функции
```

## Data Sources

### Wildberries APIs (Read-Only)
1. **Content API** - информация о товарах
2. **Analytics API** - аналитика продаж
3. **Statistics API** - статистика по товарам
4. **Promotion API** - данные о рекламных кампаниях

### External Services
1. **MPStats API** - дополнительная аналитика
2. **Google Sheets** - хранение и визуализация результатов

## Development Phases

### Phase 1: Foundation (Current)
- [x] Базовая структура проекта
- [x] Настройка конфигурации
- [x] Логгирование
- [ ] Smoke-тесты
- [ ] CI/CD настройка

### Phase 2: Core Implementation
- [ ] WB API клиенты
- [ ] MPStats API клиент
- [ ] Google Sheets интеграция
- [ ] Базовые экстракторы

### Phase 3: Data Pipeline
- [ ] Трансформеры данных
- [ ] Валидация данных
- [ ] Обработка ошибок
- [ ] Кэширование

### Phase 4: Reports & Automation
- [ ] Генерация отчетов
- [ ] Планировщик задач
- [ ] Мониторинг и алерты

## Key Deliverables

### MVP v1
- Справочник товаров
- Воронка продаж на день
- Остатки товаров
- Расход рекламных кампаний
- Статистика РК
- Поисковые запросы

## Security Considerations
- Токены хранятся только в `.env` файле
- Credentials файлы не коммитятся в репозиторий
- Все API запросы read-only
- Raw ответы API не сохраняются в репозитории

## Testing Strategy
- Unit тесты для каждого модуля
- Integration тесты для API клиентов
- Smoke тесты для проверки окружения
- End-to-end тесты для полного пайплайна
