#!/usr/bin/env python3
"""
Скрипт для интеграции с Google Sheets.

Если GOOGLE_SHEET_ID пустой:
- создаёт новую таблицу WB_table_MVP_test
- выводит spreadsheet_id в консоль
- записывает его в docs/google_sheet_created.md

Если GOOGLE_SHEET_ID указан:
- использует существующую таблицу

Создаёт тестовые вкладки:
- README
- API Smoke Test
- Coverage
- Raw Samples Summary
"""
import sys
from datetime import datetime
from pathlib import Path

# Добавляем src в путь импорта
src_path = Path(__file__).resolve().parent.parent / "src"
sys.path.insert(0, str(src_path))

root_path = Path(__file__).resolve().parent.parent
if str(root_path) not in sys.path:
    sys.path.insert(0, str(root_path))


def create_google_sheets_integration():
    """Основная функция интеграции с Google Sheets."""
    from src.config.settings import GOOGLE_SHEET_ID, GOOGLE_APPLICATION_CREDENTIALS
    from src.clients.google_sheets_client import GoogleSheetsClient
    
    print("=" * 60)
    print("Google Sheets Integration")
    print("=" * 60)
    
    # Инициализируем клиент
    client = GoogleSheetsClient()
    
    # Проверяем credentials
    if not GOOGLE_APPLICATION_CREDENTIALS:
        print("ERROR: GOOGLE_APPLICATION_CREDENTIALS not set")
        return False
    
    creds_path = Path(GOOGLE_APPLICATION_CREDENTIALS)
    if not creds_path.exists():
        print(f"ERROR: Credentials file not found: {creds_path}")
        return False
    
    print(f"Credentials file: {creds_path}")
    print(f"Spreadsheet ID: {GOOGLE_SHEET_ID or '(not set - will create new)'}")
    
    spreadsheet_id = GOOGLE_SHEET_ID
    is_new_spreadsheet = False
    
    # Если GOOGLE_SHEET_ID пустой - создаём новую таблицу
    if not spreadsheet_id:
        print("\nCreating new spreadsheet 'WB_table_MVP_test'...")
        result = client.create_spreadsheet(
            title="WB_table_MVP_test",
            worksheet_titles=["README", "API Smoke Test", "Coverage", "Raw Samples Summary"]
        )
        
        if result is None:
            print("ERROR: Failed to create spreadsheet")
            return False
        
        spreadsheet_id = result.get("spreadsheetId")
        is_new_spreadsheet = True
        
        print(f"✓ Created new spreadsheet with ID: {spreadsheet_id}")
        
        # Записываем ID в docs/google_sheet_created.md
        docs_dir = Path(__file__).resolve().parent.parent / "docs"
        docs_dir.mkdir(parents=True, exist_ok=True)
        
        created_file = docs_dir / "google_sheet_created.md"
        with open(created_file, "w", encoding="utf-8") as f:
            f.write(f"# Google Sheet Created\n\n")
            f.write(f"**Date:** {datetime.now().isoformat()}\n\n")
            f.write(f"**Spreadsheet ID:** `{spreadsheet_id}`\n\n")
            f.write(f"**Title:** WB_table_MVP_test\n\n")
            f.write(f"**URL:** https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit\n\n")
            f.write("---\n")
            f.write(f"Файл создан автоматически скриптом scripts/integrate_google_sheets.py\n")
        
        print(f"✓ Saved spreadsheet ID to docs/google_sheet_created.md")
    else:
        print(f"\nUsing existing spreadsheet: {spreadsheet_id}")
        
        # Проверяем доступ к таблице
        info = client.get_spreadsheet_info()
        if info:
            title = info.get("properties", {}).get("title", "Unknown")
            print(f"✓ Spreadsheet title: {title}")
        else:
            print("WARNING: Could not get spreadsheet info")
    
    # Создаём или очищаем тестовые вкладки
    worksheets = ["README", "API Smoke Test", "Coverage", "Raw Samples Summary"]
    
    print("\nCreating/clearing worksheets...")
    for ws_title in worksheets:
        success = client.create_or_clear_worksheet(spreadsheet_id, ws_title)
        if success:
            print(f"  ✓ {ws_title}")
        else:
            print(f"  ✗ {ws_title} - failed")
    
    # Записываем данные в README вкладку
    print("\nWriting data to README worksheet...")
    readme_data = [
        ["WB_table MVP - Test Spreadsheet"],
        [""],
        [f"Date created: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        [""],
        ["This is a TEST spreadsheet for the WB_table project."],
        [""],
        ["## Data Sources"],
        ["The following sources will be connected:"],
        ["- Wildberries Content API"],
        ["- Wildberries Analytics API"],
        ["- Wildberries Statistics API"],
        ["- Wildberries Promotion API"],
        ["- MPStats API"],
        [""],
        ["## Worksheets"],
        ["- README: This information page"],
        ["- API Smoke Test: Results of API connectivity tests"],
        ["- Coverage: API coverage documentation"],
        ["- Raw Samples Summary: Summary of raw API responses"],
        [""],
        ["---"],
        ["Do NOT store tokens, credentials, raw JSON, or private data in this spreadsheet."]
    ]
    
    success = client.write_rows(
        spreadsheet_id=spreadsheet_id,
        worksheet_title="README",
        rows=readme_data
    )
    
    if success:
        print("  ✓ README worksheet populated")
    else:
        print("  ✗ Failed to write README data")
    
    # Записываем результаты smoke-теста в API Smoke Test вкладку
    print("\nWriting API Smoke Test results...")
    smoke_test_header = [
        ["API Smoke Test Results"],
        [f"Test Date: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        [""],
        ["API", "Endpoint", "Status", "Notes"]
    ]
    
    smoke_test_data = [
        ["WB Content", "cards_list", "Pending", "Run audit_smoke_test.py"],
        ["WB Analytics", "sales_funnel_history", "Pending", "Run audit_smoke_test.py"],
        ["WB Analytics", "stocks_products", "Pending", "Run audit_smoke_test.py"],
        ["WB Analytics", "stocks_offices", "Pending", "Run audit_smoke_test.py"],
        ["WB Analytics", "region_sale", "Pending", "Run audit_smoke_test.py"],
        ["WB Analytics", "search_texts", "Pending", "Run audit_smoke_test.py"],
        ["WB Analytics", "search_orders", "Pending", "Run audit_smoke_test.py"],
        ["WB Statistics", "orders", "Pending", "Run audit_smoke_test.py"],
        ["WB Statistics", "report_detail_by_period", "Pending", "Run audit_smoke_test.py"],
        ["WB Promotion", "count", "Pending", "Run audit_smoke_test.py"],
        ["WB Promotion", "adv_costs", "Pending", "Run audit_smoke_test.py"],
        ["WB Promotion", "adv_fullstats", "Pending", "Run audit_smoke_test.py"],
        ["MPStats", "item_full", "Pending", "Run audit_smoke_test.py"],
        ["MPStats", "item_sales", "Pending", "Run audit_smoke_test.py"],
        ["MPStats", "item_by_category", "Pending", "Run audit_smoke_test.py"],
        ["Google Sheets", "health_check", "OK" if success else "Failed", "Integration script"]
    ]
    
    all_data = smoke_test_header + smoke_test_data
    success = client.write_rows(
        spreadsheet_id=spreadsheet_id,
        worksheet_title="API Smoke Test",
        rows=all_data
    )
    
    if success:
        print("  ✓ API Smoke Test worksheet populated")
    else:
        print("  ✗ Failed to write API Smoke Test data")
    
    # Записываем Coverage данные
    print("\nWriting Coverage data...")
    coverage_header = [
        ["API Coverage"],
        [f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        [""],
        ["API", "Endpoints Implemented", "Status"]
    ]
    
    coverage_data = [
        ["WB Content", "1 (cards_list)", "Implemented"],
        ["WB Analytics", "7 (sales_funnel, stocks, region_sale, search)", "Implemented"],
        ["WB Statistics", "2 (orders, detail report)", "Implemented"],
        ["WB Promotion", "3 (count, costs, fullstats)", "Implemented"],
        ["MPStats", "3 (item_full, item_sales, by_category)", "Implemented"],
        ["Google Sheets", "4 (CRUD operations)", "Implemented"]
    ]
    
    all_coverage = coverage_header + coverage_data
    success = client.write_rows(
        spreadsheet_id=spreadsheet_id,
        worksheet_title="Coverage",
        rows=all_coverage
    )
    
    if success:
        print("  ✓ Coverage worksheet populated")
    else:
        print("  ✗ Failed to write Coverage data")
    
    # Записываем Raw Samples Summary
    print("\nWriting Raw Samples Summary...")
    raw_samples_header = [
        ["Raw Samples Summary"],
        [f"Generated: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}"],
        [""],
        ["Note: Raw JSON responses are stored locally in data/raw/ directory."],
        ["This sheet contains only metadata summaries."],
        [""],
        ["API", "Sample Files Location", "Format"]
    ]
    
    raw_samples_data = [
        ["WB Content", "data/raw/wb_content/", "JSON"],
        ["WB Analytics", "data/raw/wb_analytics/", "JSON"],
        ["WB Statistics", "data/raw/wb_statistics/", "JSON"],
        ["WB Promotion", "data/raw/wb_promotion/", "JSON"],
        ["MPStats", "data/raw/mpstats/", "JSON"],
        ["", "", ""],
        ["IMPORTANT: Raw files are NOT committed to git (.gitignore configured)"]
    ]
    
    all_raw = raw_samples_header + raw_samples_data
    success = client.write_rows(
        spreadsheet_id=spreadsheet_id,
        worksheet_title="Raw Samples Summary",
        rows=all_raw
    )
    
    if success:
        print("  ✓ Raw Samples Summary worksheet populated")
    else:
        print("  ✗ Failed to write Raw Samples Summary data")
    
    print("\n" + "=" * 60)
    print("Integration Complete!")
    print("=" * 60)
    print(f"\nSpreadsheet URL: https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit")
    
    if is_new_spreadsheet:
        print(f"\nNew spreadsheet created: {spreadsheet_id}")
    
    return True


if __name__ == "__main__":
    try:
        success = create_google_sheets_integration()
        sys.exit(0 if success else 1)
    except Exception as e:
        print(f"ERROR: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
