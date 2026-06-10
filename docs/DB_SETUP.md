# DB_SETUP

Инструкция по подготовке dev-базы PostgreSQL для `WB_table-main`.

Важно:
- это только DB layer для будущего database-first этапа;
- текущий Google Sheets flow и текущие MVP scripts продолжают работать отдельно;
- боевые WB/MPStat данные этим документом не загружаются.

## 1. Переменные `.env`

Нужны переменные:

```env
ENV=dev
DATABASE_URL=postgresql+psycopg://postgres:postgres@localhost:5432/wb_table_dev
ALLOW_PROD_DB=false
```

Правила:
- `ENV=dev` для локальной базы;
- `ALLOW_PROD_DB=false` оставлять по умолчанию;
- `ENV=prod` без `ALLOW_PROD_DB=true` блокируется защитой в `src/db/connection.py`.

## 2. Как создать dev-базу

Пример для локального PostgreSQL:

```sql
CREATE DATABASE wb_table_dev;
```

Если используется Docker, создайте обычный PostgreSQL container и затем укажите его URL в `.env`.

## 3. Как проверить конфиг без подключения

```bash
python scripts/db_healthcheck.py
```

Скрипт проверяет:
- что SQLAlchemy metadata собирается;
- что prod-guard не срабатывает для `dev`;
- что DB layer подключён к конфигу;
- что `DATABASE_URL` замаскирован в выводе.

## 4. Как проверить подключение к БД

```bash
python scripts/db_test_connection.py
```

Скрипт:
- не пишет данные;
- делает только `SELECT 1`;
- показывает masked DB URL.

## 5. Как применить миграции

```bash
python scripts/db_upgrade.py
```

Опции:

```bash
python scripts/db_upgrade.py --revision head
python scripts/db_upgrade.py --sql
```

Что делает:
- загружает `DATABASE_URL` из `.env`;
- применяет Alembic migration из `alembic/versions/`;
- не трогает Google Sheets flow.

## 6. Как работает Alembic

Основные файлы:
- `alembic.ini`
- `alembic/env.py`
- `alembic/versions/20260604_0001_create_db_layer.py`

Initial migration создаёт таблицы:
- raw: `raw_api_response`, `api_load_log`, `validation_warning`
- dimensions/settings: `dim_product`, `dim_campaign`, `dim_date`, `settings_products`, `settings_report_columns`
- facts: `fact_funnel_day`, `fact_ad_cost_event`, `fact_ad_cost_day`, `fact_ad_campaign_day`, `fact_ad_campaign_nm_day`, `fact_search_query_metric`, `fact_stock_snapshot`, `fact_localization_region_day`, `fact_entry_point_day`, `fact_vbro_manual`, `fact_card_comparison_metric`
- mart: `mart_total_report`

## 7. Ограничения и safety

- Без явной команды не загружать боевые данные в БД.
- Не использовать `ENV=prod` для локальных проверок.
- Не коммитить `.env`, секреты и реальные DB credentials.
- Не считать, что наличие БД заменяет текущий Sheets pipeline: это только технический слой.
