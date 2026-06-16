# Railway Daily Dashboard Refresh

Этот job обновляет warehouse snapshot и dashboard dataset без fake backfill по складам.

## Что запускается

```bash
python scripts/run_daily_dashboard_refresh.py
```

По умолчанию runner:

- снимает warehouse snapshot за текущую дату запуска;
- пересобирает `mart_total_report` за период `2026-06-07 .. today`;
- переэкспортирует `data/processed/streamlit_v1_dataset.csv`;
- сохраняет summary в:
  - `data/processed/daily_runs/dashboard_refresh_YYYY_MM_DD.json`
  - `data/processed/daily_runs/dashboard_refresh_YYYY_MM_DD.md`

Warehouse history назад не догружается. История по складам начинается только с честного snapshot дня.

## Рекомендуемый cron

Railway Scheduled Job:

```cron
0 8 * * *
```

Это соответствует:

- `11:00` МСК
- `13:00` Алматы

## Railway UI

Если scheduler нельзя завести из CLI, настройте job вручную в Railway UI:

1. Откройте проект Railway.
2. Создайте `Scheduled Job` / `Cron`.
3. Укажите cron expression: `0 8 * * *`.
4. Укажите command:

```bash
python scripts/run_daily_dashboard_refresh.py
```

## Переменные окружения

Для job должны быть доступны те же env, что и основному приложению:

- `DATABASE_URL`
- read-only WB token / env, который уже используется текущими loader-скриптами

Job не должен выполнять WB `PUT` / `DELETE`.

## Heavy режим

Если позже понадобится ежедневная догрузка core facts по tracked products, runner уже поддерживает:

```bash
python scripts/run_daily_dashboard_refresh.py --include-core-refresh
```

Этот режим тяжелее и его лучше включать только после отдельного согласования.
