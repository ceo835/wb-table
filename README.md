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
