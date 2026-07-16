# WB Table Streamlit Dashboard

Streamlit-витрина для отчёта WB Table на базе `mart_total_report` в PostgreSQL.

Приложение показывает:
- основной ИТОГО по товарам
- карточку товара с динамикой
- РК по товару
- технический import-раздел для файлов `Точка входа` и `География заказов`

По умолчанию для публикации приложение должно работать от PostgreSQL через `DATABASE_URL`. CSV fallback оставлен только для локальной разработки.

## Структура проекта

- `app_streamlit.py` — основное Streamlit-приложение
- `src/` — бизнес-логика, DB-слой, importers, dataset helpers
- `scripts/` — CLI-скрипты для сборки mart, export и обслуживания
- `alembic/` и `alembic.ini` — миграции PostgreSQL
- `tests/` — точечные тесты Streamlit/dataset-слоя

## Быстрый старт локально

### 1. Установить зависимости

```bash
pip install -r requirements.txt
```

### 2. Создать `.env`

Скопируйте `.env.example` в `.env` и заполните только нужные переменные.

Минимальный набор для Streamlit от БД:

```env
DATABASE_URL=postgresql://...
STREAMLIT_DATA_SOURCE=db
APP_PASSWORD=...
```

Для локального CSV fallback:

```env
STREAMLIT_DATA_SOURCE=csv
APP_PASSWORD=...
```

Для WB site price monitor:

```env
WB_SITE_PRICE_MONITOR_ENABLED=false
WB_SITE_PRICE_PROXY_URL=http://user:pass@host:port
```

### 3. Прогнать проверки

```bash
python -m py_compile app_streamlit.py src/streamlit_dataset.py
python scripts/check_no_secrets.py
pytest tests/test_app_streamlit.py tests/test_streamlit_dataset.py -q --basetemp .pytest_tmp
```

### 4. Запустить Streamlit

```bash
streamlit run app_streamlit.py
```

## Переменные окружения

### Обязательные для деплоя

- `DATABASE_URL` — строка подключения к PostgreSQL
- `STREAMLIT_DATA_SOURCE=db`
- `APP_PASSWORD` — пароль на вход в dashboard

### Опциональные для локальной разработки

- `ENV=dev`
- `ALLOW_PROD_DB=false`
- `WB_SITE_PRICE_MONITOR_ENABLED=false`
- `WB_SITE_PRICE_PROXY_URL=...` только для site monitor, без глобальных `HTTP_PROXY` / `HTTPS_PROXY`

### Не нужны для просмотра dashboard

Токены WB/MPStat не требуются, если приложение только читает готовую БД.

## Защита доступа

Если задан `APP_PASSWORD`, приложение сначала показывает форму входа. Пока пароль не введён, таблицы и данные не отображаются.

## Деплой в Streamlit Community Cloud

1. Создать GitHub-репозиторий и запушить проект.
2. В Streamlit Community Cloud выбрать:
   - repo: `ceo835/wb-table`
   - branch: `main`
   - main file: `app_streamlit.py`
3. Добавить secrets:

```toml
DATABASE_URL = "postgresql://..."
STREAMLIT_DATA_SOURCE = "db"
APP_PASSWORD = "..."
```

4. Нажать `Deploy`.

## Деплой в Railway

Подключить GitHub-репозиторий и задать start command:

```bash
streamlit run app_streamlit.py --server.port $PORT --server.address 0.0.0.0
```

Переменные окружения:

```env
DATABASE_URL=postgresql://...
STREAMLIT_DATA_SOURCE=db
APP_PASSWORD=...
WB_SITE_PRICE_MONITOR_ENABLED=false
WB_SITE_PRICE_PROXY_URL=http://user:pass@host:port
```

## Безопасность публикации

В репозиторий нельзя добавлять:

- `.env`
- `credentials.json`
- `secrets.toml`
- `DATABASE_URL`
- WB/MPStat tokens
- реальные CSV/XLSX/XLSM выгрузки
- дампы БД и логи

Перед `git add .` обязательно проверьте `git status`.

## MVP MCP / HTTP read-only service

В проект добавлен отдельный read-only HTTP service для внешнего assistant/tool доступа к PostgreSQL без CSV и без write-операций.

### Выбранный transport

На первом этапе используется HTTP JSON API на FastAPI с отдельными tool endpoints:

- `GET /health`
- `POST /tools/get_dashboard_summary`
- `POST /tools/get_product_metrics`
- `POST /tools/get_price_monitor`
- `POST /tools/get_wb_daily_operational_summary`

Это не полноценный MCP transport, а совместимый промежуточный HTTP слой для Railway URL-подключения.

### Переменные окружения

Нужны отдельные env:

```env
DATABASE_URL=postgresql://...
MCP_AUTH_TOKEN=...
MCP_MAX_ROWS=500
MCP_QUERY_TIMEOUT_SECONDS=20
```

### Локальный запуск

```bash
pip install -r requirements.txt
uvicorn mcp_server:app --host 127.0.0.1 --port 8001
```

### Railway запуск

Для отдельного web-service:

```bash
uvicorn mcp_server:app --host 0.0.0.0 --port $PORT
```

### Авторизация

Все tool endpoints, кроме `/health`, защищены Bearer token:

```http
Authorization: Bearer <MCP_AUTH_TOKEN>
```

### Примеры запросов

#### Health

```bash
curl http://localhost:8001/health
```

#### Dashboard summary

```bash
curl -X POST http://localhost:8001/tools/get_dashboard_summary \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"date_from\":\"2026-06-07\",\"date_to\":\"2026-06-18\",\"only_tracked\":true}"
```

#### Product metrics

```bash
curl -X POST http://localhost:8001/tools/get_product_metrics \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"nm_id\":91470767,\"date_from\":\"2026-06-07\",\"date_to\":\"2026-06-18\"}"
```

#### Price monitor

```bash
curl -X POST http://localhost:8001/tools/get_price_monitor \
  -H "Authorization: Bearer $MCP_AUTH_TOKEN" \
  -H "Content-Type: application/json" \
  -d "{\"snapshot_date\":\"2026-06-18\",\"alerts_only\":false}"
```

### Ограничения первого этапа

- только PostgreSQL;
- только заранее описанные read-only tools;
- без произвольного SQL от пользователя;
- диапазон дат ограничен 60 днями;
- количество строк ограничено `MCP_MAX_ROWS`;
- suppressed price alerts не считаются активными;
- traceback пишется в server logs, но secrets не логируются.
