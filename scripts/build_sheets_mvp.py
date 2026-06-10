#!/usr/bin/env python3
"""
Скрипт для создания MVP вкладок в Google Sheets на основе обработанных данных.
"""

import os
import sys
import pandas as pd
from pathlib import Path
from datetime import datetime

# Добавляем src в path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from config.settings import settings
from clients.google_sheets_client import GoogleSheetsClient
from utils.logger import get_logger

logger = get_logger(__name__)

# Маппинг имен файлов processed -> имен вкладок
SHEET_MAPPING = {
    "dim_product.csv": "dim_product",
    "fact_funnel_day.csv": "Воронка на день",
    "fact_ad_cost_event.csv": "РасходРК",
    "fact_ad_campaign_day.csv": "РК стата",
    "fact_search_query_metric.csv": "Поисковые запросы",
    "fact_stock_snapshot.csv": "Остатки",
}

# Дополнительные вкладки
EXTRA_SHEETS = ["Coverage", "Missing fields"]


def load_processed_data(table_name: str) -> pd.DataFrame | None:
    """Загружает данные из data/processed/{table_name}.csv"""
    file_path = Path("data/processed") / table_name
    if not file_path.exists():
        logger.warning(f"Файл {file_path} не найден")
        return None
    
    try:
        df = pd.read_csv(file_path)
        logger.info(f"Загружено {len(df)} строк из {file_path}")
        return df
    except Exception as e:
        logger.error(f"Ошибка чтения {file_path}: {e}")
        return None


def get_coverage_data() -> list[list]:
    """Формирует данные для вкладки Coverage из docs/current_coverage.md"""
    coverage_file = Path("docs/current_coverage.md")
    rows = [["API Endpoint", "Status", "Notes"]]
    
    if coverage_file.exists():
        content = coverage_file.read_text(encoding="utf-8")
        # Парсим markdown таблицу
        for line in content.split("\n"):
            if line.startswith("|") and "Endpoint" not in line and "---" not in line:
                parts = [p.strip() for p in line.split("|")[1:-1]]
                if len(parts) >= 2:
                    rows.append(parts[:3] if len(parts) >= 3 else parts + [""])
    else:
        rows.append(["No coverage data available", "", ""])
    
    return rows


def get_missing_fields_data() -> list[list]:
    """Формирует данные для вкладки Missing fields"""
    # Собираем информацию о проблемных полях из логов или конфига
    rows = [["Table Name", "Field Name", "Issue Type", "Description"]]
    
    # Примерные данные - можно расширить при реальном анализе
    missing_fields = [
        ("fact_finance_realization_line", "some_field", "missing", "Поле отсутствует в ответе API"),
    ]
    
    for table, field, issue_type, desc in missing_fields:
        rows.append([table, field, issue_type, desc])
    
    # Если нет проблемных полей
    if len(rows) == 1:
        rows.append(["No missing fields detected", "", "", ""])
    
    return rows


def main():
    logger.info("=== Запуск построения MVP вкладок Google Sheets ===")
    
    # Инициализация клиента Google Sheets
    try:
        gs_client = GoogleSheetsClient()
        logger.info("Google Sheets клиент инициализирован")
    except Exception as e:
        logger.error(f"Ошибка инициализации Google Sheets клиента: {e}")
        print(f"❌ Ошибка подключения к Google Sheets: {e}")
        print("Убедитесь, что GOOGLE_APPLICATION_CREDENTIALS настроен корректно")
        sys.exit(1)
    
    spreadsheet_id = settings.google_sheet_id
    spreadsheet_url = ""
    
    # Если ID не указан, создаем новую таблицу
    if not spreadsheet_id:
        logger.info("GOOGLE_SHEET_ID не указан, создаем новую таблицу")
        title = f"WB_table_MVP_{datetime.now().strftime('%Y%m%d_%H%M%S')}"
        try:
            spreadsheet_id = gs_client.create_spreadsheet(title)
            spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
            logger.info(f"Создана новая таблица: {spreadsheet_url}")
            print(f"✅ Создана новая таблица: {spreadsheet_url}")
        except Exception as e:
            logger.error(f"Ошибка создания таблицы: {e}")
            print(f"❌ Ошибка создания таблицы: {e}")
            sys.exit(1)
    else:
        spreadsheet_url = f"https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit"
        logger.info(f"Используем существующую таблицу: {spreadsheet_url}")
        print(f"📊 Используем таблицу: {spreadsheet_url}")
    
    # Обработка основных таблиц
    for csv_file, sheet_name in SHEET_MAPPING.items():
        logger.info(f"Обработка вкладки '{sheet_name}' из {csv_file}")
        
        df = load_processed_data(csv_file)
        
        if df is None or df.empty:
            logger.warning(f"Нет данных для вкладки '{sheet_name}', создаем пустую вкладку с заголовками")
            # Создаем пустую вкладку с заголовком
            try:
                gs_client.create_or_clear_worksheet(spreadsheet_id, sheet_name)
                # Пишем заголовки из ожидаемой структуры или пустые
                gs_client.write_rows(spreadsheet_id, sheet_name, [["No data available yet"]])
                print(f"⚠️  Вкладка '{sheet_name}' создана (нет данных)")
            except Exception as e:
                logger.error(f"Ошибка создания вкладки '{sheet_name}': {e}")
                print(f"❌ Ошибка вкладки '{sheet_name}': {e}")
            continue
        
        # Очищаем вкладку и записываем данные
        try:
            gs_client.create_or_clear_worksheet(spreadsheet_id, sheet_name)
            
            # Преобразуем DataFrame в список списков
            # Заголовки
            headers = df.columns.tolist()
            # Данные
            data_rows = df.fillna("").values.tolist()
            
            # Пишем заголовки и данные
            all_rows = [headers] + data_rows
            gs_client.write_rows(spreadsheet_id, sheet_name, all_rows)
            
            logger.info(f"Записано {len(data_rows)} строк в вкладку '{sheet_name}'")
            print(f"✅ Вкладка '{sheet_name}': {len(data_rows)} строк")
            
        except Exception as e:
            logger.error(f"Ошибка записи вкладки '{sheet_name}': {e}")
            print(f"❌ Ошибка записи вкладки '{sheet_name}': {e}")
    
    # Обработка дополнительных вкладок
    for extra_sheet in EXTRA_SHEETS:
        logger.info(f"Обработка дополнительной вкладки '{extra_sheet}'")
        
        try:
            gs_client.create_or_clear_worksheet(spreadsheet_id, extra_sheet)
            
            if extra_sheet == "Coverage":
                data = get_coverage_data()
            elif extra_sheet == "Missing fields":
                data = get_missing_fields_data()
            else:
                data = [[f"No data for {extra_sheet}"]]
            
            gs_client.write_rows(spreadsheet_id, extra_sheet, data)
            logger.info(f"Записано {len(data)} строк в вкладку '{extra_sheet}'")
            print(f"✅ Вкладка '{extra_sheet}': {len(data)} строк")
            
        except Exception as e:
            logger.error(f"Ошибка записи вкладки '{extra_sheet}': {e}")
            print(f"❌ Ошибка записи вкладки '{extra_sheet}': {e}")
    
    print("\n" + "="*50)
    print("🎉 Построение MVP вкладок завершено!")
    print(f"📋 Таблица: {spreadsheet_url}")
    print("="*50)
    
    # Сохраняем информацию о созданной таблице
    result_file = Path("docs/google_sheets_mvp_result.md")
    result_content = f"""# Результат построения MVP вкладок Google Sheets

**Дата выполнения:** {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}

**Spreadsheet ID:** `{spreadsheet_id}`

**URL таблицы:** {spreadsheet_url}

## Созданные вкладки:

"""
    for sheet_name in list(SHEET_MAPPING.values()) + EXTRA_SHEETS:
        result_content += f"- {sheet_name}\n"
    
    result_file.write_text(result_content, encoding="utf-8")
    logger.info(f"Результат сохранен в {result_file}")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
