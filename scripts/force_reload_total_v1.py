import os
import sys
import pandas as pd
from googleapiclient.discovery import build
from google.oauth2 import service_account
from dotenv import load_dotenv

# Загрузка переменных окружения
load_dotenv()

# Поддержка разных имен переменных
GOOGLE_SHEET_ID = os.getenv("GOOGLE_SHEET_ID") or os.getenv("GOOGLE_SPREADSHEET_ID")
CREDENTIALS_FILE = os.getenv("GOOGLE_APPLICATION_CREDENTIALS") or os.getenv("GOOGLE_CREDENTIALS_FILE", "credentials.json")

if not GOOGLE_SHEET_ID:
    print("❌ Ошибка: Не найдена переменная GOOGLE_SHEET_ID или GOOGLE_SPREADSHEET_ID в .env")
    sys.exit(1)
if not os.path.exists(CREDENTIALS_FILE):
    print(f"❌ Ошибка: Файл кредов {CREDENTIALS_FILE} не найден")
    sys.exit(1)

def get_sheets_service():
    creds = service_account.Credentials.from_service_account_file(
        CREDENTIALS_FILE, scopes=["https://www.googleapis.com/auth/spreadsheets"]
    )
    return build("sheets", "v4", credentials=creds)

def load_and_fix_data():
    print("🔄 Загрузка и исправление данных...")
    
    # 1. Загружаем базу - Воронка
    funnel_path = "data/processed/fact_funnel_day.csv"
    if not os.path.exists(funnel_path):
        raise FileNotFoundError(f"❌ Критическая ошибка: {funnel_path} не найден! Невозможно построить ИТОГО_v1.")
    
    df = pd.read_csv(funnel_path)
    print(f"✅ Загружено строк в воронке: {len(df)}")
    
    if len(df) == 0:
        raise ValueError("❌ fact_funnel_day пуст. Остановка.")

    # Нормализация ключей
    if 'nmID' in df.columns: df['nm_id'] = df['nmID'].astype(str).str.strip()
    elif 'nm_id' in df.columns: df['nm_id'] = df['nm_id'].astype(str).str.strip()
    
    if 'date' in df.columns:
        df['date'] = pd.to_datetime(df['date']).dt.strftime('%Y-%m-%d')

    # 2. Подтягиваем справочник
    dim_path = "data/processed/dim_product.csv"
    if os.path.exists(dim_path):
        dim_df = pd.read_csv(dim_path)
        # Нормализация имен в справочнике
        if 'nmID' in dim_df.columns: 
            dim_df['nm_id'] = dim_df['nmID'].astype(str).str.strip()
        elif 'nm_id' in dim_df.columns:
            dim_df['nm_id'] = dim_df['nm_id'].astype(str).str.strip()
            
        if 'vendorCode' in dim_df.columns: dim_df['supplier_article'] = dim_df['vendorCode'].astype(str)
        if 'subjectName' in dim_df.columns: dim_df['subject'] = dim_df['subjectName'].astype(str)
        if 'brand' in dim_df.columns: dim_df['brand'] = dim_df['brand'].astype(str)
        if 'title' in dim_df.columns: dim_df['title'] = dim_df['title'].astype(str)

        cols_to_merge = ['nm_id', 'supplier_article', 'title', 'subject', 'brand']
        available_cols = [c for c in cols_to_merge if c in dim_df.columns]
        df = df.merge(dim_df[available_cols].drop_duplicates(subset=['nm_id']), on='nm_id', how='left')
        print(f"✅ Справочник подтянут. Строк: {len(dim_df)}")
    else:
        print("⚠️ dim_product.csv не найден, справочник не подтянется.")

    # 3. Подтягиваем рекламу (с исправлением единиц измерения!)
    ads_path = "data/processed/fact_ad_campaign_nm_day.csv"
    if os.path.exists(ads_path):
        ads_df = pd.read_csv(ads_path)
        if 'nmID' in ads_df.columns: 
            ads_df['nm_id'] = ads_df['nmID'].astype(str).str.strip()
        elif 'nm_id' in ads_df.columns:
            ads_df['nm_id'] = ads_df['nm_id'].astype(str).str.strip()
            
        if 'date' in ads_df.columns: 
            ads_df['date'] = pd.to_datetime(ads_df['date']).dt.strftime('%Y-%m-%d')

        # Исправление: делим деньги на 100, если они огромные
        money_cols = ['ad_spend', 'ad_revenue']
        for col in money_cols:
            if col in ads_df.columns:
                # Эвристика: если среднее значение > 10000, скорее всего это копейки/микро-единицы
                if ads_df[col].mean() > 10000:
                    ads_df[col] = ads_df[col] / 100.0
                    print(f"💰 {col} разделен на 100 (были копейки/условные единицы).")

        ads_cols = ['date', 'nm_id', 'ad_views', 'ad_clicks', 'ad_ctr', 'ad_cpc', 'ad_orders', 'ad_atbs', 'ad_spend', 'ad_revenue']
        available_ads_cols = [c for c in ads_cols if c in ads_df.columns]
        df = df.merge(ads_df[available_ads_cols], on=['date', 'nm_id'], how='left')
        print(f"✅ Реклама подтянута. Строк: {len(ads_df)}")
    
    # 4. Подтягиваем поиск
    search_path = "data/processed/fact_search_query_metric.csv"
    if os.path.exists(search_path):
        search_df = pd.read_csv(search_path)
        if 'nmID' in search_df.columns: 
            search_df['nm_id'] = search_df['nmID'].astype(str).str.strip()
        elif 'nm_id' in search_df.columns:
            search_df['nm_id'] = search_df['nm_id'].astype(str).str.strip()
            
        if 'date' in search_df.columns: 
            search_df['date'] = pd.to_datetime(search_df['date']).dt.strftime('%Y-%m-%d')

        search_cols = ['date', 'nm_id', 'search_queries_count', 'avg_position', 'visibility', 'search_clicks', 'search_cart', 'search_orders']
        available_search_cols = [c for c in search_cols if c in search_df.columns]
        df = df.merge(search_df[available_search_cols], on=['date', 'nm_id'], how='left')
        print(f"✅ Поиск подтянут. Строк: {len(search_df)}")

    # 5. Подтягиваем остатки
    stock_path = "data/processed/fact_stock_snapshot.csv"
    if os.path.exists(stock_path):
        stock_df = pd.read_csv(stock_path)
        if 'nmID' in stock_df.columns: 
            stock_df['nm_id'] = stock_df['nmID'].astype(str).str.strip()
        elif 'nm_id' in stock_df.columns:
            stock_df['nm_id'] = stock_df['nm_id'].astype(str).str.strip()
            
        # Остатки часто snapshot, берем последние или мерджим по nm_id без даты, если даты нет
        if 'date' in stock_df.columns:
             stock_df['date'] = pd.to_datetime(stock_df['date']).dt.strftime('%Y-%m-%d')
             stock_cols = ['date', 'nm_id', 'stockCount', 'stockSum', 'stock_snapshot_date']
        else:
             stock_cols = ['nm_id', 'stockCount', 'stockSum']
             if 'stock_snapshot_date' in stock_df.columns: stock_cols.append('stock_snapshot_date')
        
        available_stock_cols = [c for c in stock_cols if c in stock_df.columns]
        # Если в остатках есть дата, мерджим по дате+nm, иначе только по nm (остаток текущий на все строки)
        if 'date' in available_stock_cols and 'date' in df.columns:
            df = df.merge(stock_df[available_stock_cols], on=['date', 'nm_id'], how='left')
        else:
            # Мердж только по nm_id для снапшота
            merge_cols = [c for c in available_stock_cols if c != 'date']
            if 'nm_id' in merge_cols:
                df = df.merge(stock_df[merge_cols], on='nm_id', how='left')
        
        print(f"✅ Остатки подтянуты. Строк: {len(stock_df)}")

    # 6. Финальная очистка
    # Убираем полные дубли колонок (если вдруг появились)
    df = df.loc[:, ~df.columns.duplicated()]
    
    # Удаляем строки, где нет НИ ОДНОЙ метрики
    metric_cols = ['openCount', 'cartCount', 'orderCount', 'orderSum', 'ad_views', 'ad_spend', 'search_queries_count', 'stockCount']
    existing_metrics = [c for c in metric_cols if c in df.columns]
    if existing_metrics:
        df = df.dropna(subset=existing_metrics, how='all')
    
    print(f"🎯 Итоговое количество строк: {len(df)}")
    print(f"📋 Колонки ({len(df.columns)}): {list(df.columns)}")
    print("\n👀 Первые 5 строк для проверки:")
    print(df.head())
    
    return df

def write_to_sheets(df, sheet_id, range_name="ИТОГО_v1"):
    print(f"\n📝 Запись в Google Sheets (ID: {sheet_id})...")
    service = get_sheets_service()
    
    # 1. Очищаем вкладку
    try:
        # Получаем ID вкладки
        spreadsheet = service.spreadsheets().get(spreadsheetId=sheet_id).execute()
        sheet_names = [s['properties']['title'] for s in spreadsheet['sheets']]
        
        if range_name not in sheet_names:
            # Создаем вкладку
            body = {"requests": [{"addSheet": {"properties": {"title": range_name}}}]}
            service.spreadsheets().batchUpdate(spreadsheetId=sheet_id, body=body).execute()
            print(f"➕ Вкладка '{range_name}' создана.")
        else:
            # Очищаем существующую - правильный способ через batchUpdate с clearBasicFilter или просто перезапись
            # Сначала получаем диапазон данных для очистки
            clear_range = f"{range_name}!A1:Z1000"
            clear_body = {"values": [[]] * 1000}  # Пустые строки
            # Простой способ: просто пишем новые данные поверх старых, они затрутся
            print(f"🧹 Вкладка '{range_name}' будет перезаписана новыми данными.")
            
    except Exception as e:
        print(f"❌ Ошибка при подготовке вкладки: {e}")
        # Продолжаем запись, не прерываем

    # 2. Форматируем данные для API
    values = [df.columns.tolist()] + df.fillna('').values.tolist()
    body = {"values": values}
    
    try:
        result = service.spreadsheets().values().update(
            spreadsheetId=sheet_id,
            range=f"{range_name}!A1",
            valueInputOption="RAW",
            body=body
        ).execute()
        print(f"✅ Успешно записано {result.get('updatedRows')} строк и {result.get('updatedColumns')} колонок.")
        print(f"🔗 Ссылка: https://docs.google.com/spreadsheets/d/{sheet_id}/edit#gid=0")
    except Exception as e:
        print(f"❌ Ошибка записи: {e}")

if __name__ == "__main__":
    if not GOOGLE_SHEET_ID:
        print("❌ Ошибка: Не указан GOOGLE_SHEET_ID в .env")
        sys.exit(1)
    
    try:
        final_df = load_and_fix_data()
        write_to_sheets(final_df, GOOGLE_SHEET_ID)
    except Exception as e:
        print(f"❌ Критическая ошибка выполнения: {e}")
        import traceback
        traceback.print_exc()
