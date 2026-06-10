#!/usr/bin/env python3
"""
Скрипт для создания вкладки ИТОГО v1 в Google Sheets.
Объединяет данные из dim_product, fact_funnel_day, fact_ad_campaign_nm_day,
fact_search_query_metric и stocks по ключу: date + nm_id + supplier_article.
"""

import os
import sys
import pandas as pd
from pathlib import Path
from dotenv import load_dotenv

# Добавляем src в path
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from clients.google_sheets_client import GoogleSheetsClient
from config.settings import settings

load_dotenv()

PROCESSED_DIR = Path("data/processed")
SHEET_NAME = "ИТОГО_v1"
BACKLOG_SHEET_NAME = "Backlog"


def load_csv_safe(path: Path) -> pd.DataFrame | None:
    """Загружает CSV, если файл существует, иначе возвращает None."""
    if not path.exists():
        return None
    try:
        return pd.read_csv(path)
    except Exception as e:
        print(f"Warning: Could not load {path}: {e}")
        return None


def normalize_date(df: pd.DataFrame, col: str = "date") -> pd.DataFrame:
    """Приводит колонку даты к строковому формату YYYY-MM-DD."""
    if df is None or col not in df.columns:
        return df
    df[col] = pd.to_datetime(df[col], errors="coerce").dt.strftime("%Y-%m-%d")
    return df


def main():
    # Инициализация клиента Google Sheets
    try:
        gs_client = GoogleSheetsClient()
    except Exception as e:
        print(f"Error initializing Google Sheets client: {e}")
        print("Check GOOGLE_APPLICATION_CREDENTIALS and credentials.json")
        return

    spreadsheet_id = settings.google_sheet_id
    if not spreadsheet_id:
        print("GOOGLE_SHEET_ID not found. Creating new spreadsheet...")
        spreadsheet_id = gs_client.create_spreadsheet("WB_table_MVP_Final")
        print(f"Created new spreadsheet: {spreadsheet_id}")
        # Обновляем .env или просто используем в памяти
    else:
        print(f"Using existing spreadsheet: {spreadsheet_id}")

    # 1. Загрузка данных из processed
    print("Loading data from data/processed/...")

    df_product = load_csv_safe(PROCESSED_DIR / "dim_product.csv")
    df_funnel = load_csv_safe(PROCESSED_DIR / "fact_funnel_day.csv")
    df_ads = load_csv_safe(PROCESSED_DIR / "fact_ad_campaign_nm_day.csv")
    df_search = load_csv_safe(PROCESSED_DIR / "fact_search_query_metric.csv")
    df_stocks = load_csv_safe(PROCESSED_DIR / "fact_stock_day.csv")

    # Нормализация дат и ключей
    for df in [df_product, df_funnel, df_ads, df_search, df_stocks]:
        if df is not None:
            normalize_date(df)
            if "nm_id" in df.columns:
                df["nm_id"] = df["nm_id"].astype(str)
            if "supplier_article" in df.columns:
                df["supplier_article"] = df["supplier_article"].astype(str)

    # 2. Формирование базового набора (на основе продуктов или воронки)
    base_df = None
    if df_funnel is not None:
        base_df = df_funnel.copy()
    elif df_product is not None:
        base_df = df_product[["nm_id", "supplier_article"]].drop_duplicates()
        # Добавляем фиктивную дату, если нет фактов
        if "date" not in base_df.columns:
            base_df["date"] = pd.Timestamp.now().strftime("%Y-%m-%d")
    else:
        # Если совсем нет данных, создаем пустой каркас
        print("No source data found. Creating empty template.")
        base_df = pd.DataFrame(columns=["date", "nm_id", "supplier_article"])

    # Ключ для мержа
    merge_keys = ["date", "nm_id", "supplier_article"]

    # 3. Мерж с dim_product
    if df_product is not None:
        cols_product = ["nm_id", "supplier_article", "title", "subject", "brand"]
        available_cols = [c for c in cols_product if c in df_product.columns]
        
        # Убедимся, что ключевые колонки есть в base_df перед мержем
        for key_col in ["nm_id", "supplier_article"]:
            if key_col not in base_df.columns and key_col in df_product.columns:
                base_df[key_col] = None
        
        # Определяем реальные ключи для мержа (только те, что есть в обоих DF)
        actual_merge_keys = [k for k in ["nm_id", "supplier_article"] if k in base_df.columns and k in df_product.columns]
        
        if actual_merge_keys:
            base_df = base_df.merge(
                df_product[available_cols].drop_duplicates(subset=["nm_id"]),
                on=actual_merge_keys,
                how="left"
            )
            print(f"Merged dim_product: {len(available_cols)} columns, keys={actual_merge_keys}")
        else:
            # Если нет общих ключей, просто копируем данные из product
            for col in available_cols:
                if col not in base_df.columns:
                    base_df[col] = None
            print("No common merge keys with dim_product, adding null columns")
    else:
        for col in ["title", "subject", "brand"]:
            if col not in base_df.columns:
                base_df[col] = None

    # 4. Мерж с fact_funnel_day (уже может быть основой)
    funnel_cols = [
        "openCount", "cartCount", "orderCount", "orderSum",
        "buyoutCount", "buyoutSum", "buyoutPercent",
        "addToCartConversion", "cartToOrderConversion", "addToWishlistCount"
    ]
    if df_funnel is not None and base_df is not df_funnel:
        available_cols = [c for c in funnel_cols if c in df_funnel.columns]
        # Ключи для мержа с funnel - только те, что есть в обоих DF
        funnel_merge_keys = [k for k in ["date", "nm_id"] if k in base_df.columns and k in df_funnel.columns]
        
        if funnel_merge_keys:
            base_df = base_df.merge(
                df_funnel[funnel_merge_keys + available_cols],
                on=funnel_merge_keys,
                how="left"
            )
            print(f"Merged fact_funnel_day: {len(available_cols)} columns, keys={funnel_merge_keys}")
        else:
            for col in available_cols:
                if col not in base_df.columns:
                    base_df[col] = None
            print("No common merge keys with fact_funnel_day")
    elif df_funnel is None:
        for col in funnel_cols:
            if col not in base_df.columns:
                base_df[col] = None

    # 5. Мерж с fact_ad_campaign_nm_day
    ad_cols = [
        "ad_views", "ad_clicks", "ad_ctr", "ad_cpc",
        "ad_orders", "ad_atbs", "ad_spend", "ad_revenue"
    ]
    if df_ads is not None:
        # Агрегируем если есть дубли, берем сумму по числовым полям
        # Для простоты просто мерджим
        available_cols = [c for c in ad_cols if c in df_ads.columns]
        # Ключи для мержа с ads - только те, что есть в обоих DF
        ad_merge_keys = [k for k in ["date", "nm_id"] if k in base_df.columns and k in df_ads.columns]
        
        if ad_merge_keys:
            base_df = base_df.merge(
                df_ads[ad_merge_keys + available_cols],
                on=ad_merge_keys,
                how="left"
            )
            print(f"Merged fact_ad_campaign_nm_day: {len(available_cols)} columns, keys={ad_merge_keys}")
        else:
            for col in available_cols:
                if col not in base_df.columns:
                    base_df[col] = None
            print("No common merge keys with fact_ad_campaign_nm_day")
    else:
        for col in ad_cols:
            if col not in base_df.columns:
                base_df[col] = None

    # 6. Мерж с fact_search_query_metric
    # Тут группировка по nm_id и дате, так как запросов много
    search_cols = [
        "search_queries_count", "avg_position", "visibility",
        "search_clicks", "search_cart", "search_orders"
    ]
    if df_search is not None:
        # Ключи для мержа с search - только те, что есть в обоих DF
        search_merge_keys = [k for k in ["date", "nm_id"] if k in base_df.columns and k in df_search.columns]
        
        # Агрегация: сумма запросов, кликов, корзин, заказов; среднее позиции
        agg_dict = {}
        if "search_queries_count" in df_search.columns: agg_dict["search_queries_count"] = "sum"
        if "position" in df_search.columns: agg_dict["position"] = "mean" # средняя позиция
        if "clicks" in df_search.columns: agg_dict["clicks"] = "sum"
        if "cart" in df_search.columns: agg_dict["cart"] = "sum"
        if "orders" in df_search.columns: agg_dict["orders"] = "sum"
        
        # Переименуем для соответствия ожидаемым полям если нужно
        # В данном случае предполагаем, что в CSV уже нужные имена или мы их мапим
        
        # Для упрощения, если CSV имеет стандартные поля из трансформера:
        # Используем простые названия из списка выше, если они есть в df_search
        # Если в df_search другие имена, нужно мапить. 
        # Предположим, трансформер выдал поля: query_count, avg_pos, visibility, clicks, carts, orders
        
        # Попытка загрузить стандартные поля
        final_search_cols = []
        for col in search_cols:
            if col in df_search.columns:
                final_search_cols.append(col)
        
        if not final_search_cols:
            # Если имена не совпали, пробуем альтернативные (частые случаи)
            alt_map = {
                "search_queries_count": ["count", "queries_count"],
                "avg_position": ["avg_pos", "position_avg"],
                "visibility": ["vis", "visibility_score"],
                "search_clicks": ["clicks"],
                "search_cart": ["carts", "cart_count"],
                "search_orders": ["orders", "order_count"]
            }
            for target, sources in alt_map.items():
                for src in sources:
                    if src in df_search.columns and target not in final_search_cols:
                         # Переименуем временно
                         df_search[target] = df_search[src]
                         final_search_cols.append(target)
                         break

        if final_search_cols and search_merge_keys:
             # Группируем по ключам и агрегируем
             grouped_search = df_search[search_merge_keys + final_search_cols].groupby(search_merge_keys).sum(numeric_only=True).reset_index()
             base_df = base_df.merge(
                grouped_search,
                on=search_merge_keys,
                how="left"
            )
             print(f"Merged fact_search_query_metric: {len(final_search_cols)} columns, keys={search_merge_keys}")
        elif not search_merge_keys:
            for col in final_search_cols:
                if col not in base_df.columns:
                    base_df[col] = None
            print("No common merge keys with fact_search_query_metric")
    
    for col in search_cols:
        if col not in base_df.columns:
            base_df[col] = None

    # 7. Мерж с stocks (fact_stock_day)
    stock_cols = ["stockCount", "stockSum"]
    if df_stocks is not None:
        available_cols = [c for c in stock_cols if c in df_stocks.columns]
        # Ключи для мержа со stocks - только те, что есть в обоих DF
        stock_merge_keys = [k for k in ["date", "nm_id"] if k in base_df.columns and k in df_stocks.columns]
        
        # Берем последний снимок по дате или сумму? Обычно snapshot на конец дня.
        # Мерджим просто
        if stock_merge_keys:
            base_df = base_df.merge(
                df_stocks[stock_merge_keys + available_cols],
                on=stock_merge_keys,
                how="left"
            )
            print(f"Merged fact_stock_day: {len(available_cols)} columns, keys={stock_merge_keys}")
        else:
            for col in available_cols:
                if col not in base_df.columns:
                    base_df[col] = None
            print("No common merge keys with fact_stock_day")
    else:
        for col in stock_cols:
            if col not in base_df.columns:
                base_df[col] = None

    # 8. Подготовка к выгрузке
    # Упорядочиваем колонки
    ordered_cols = [
        "date", "nm_id", "supplier_article",
        "title", "subject", "brand",
        "openCount", "cartCount", "orderCount", "orderSum",
        "buyoutCount", "buyoutSum", "buyoutPercent",
        "addToCartConversion", "cartToOrderConversion", "addToWishlistCount",
        "ad_views", "ad_clicks", "ad_ctr", "ad_cpc",
        "ad_orders", "ad_atbs", "ad_spend", "ad_revenue",
        "search_queries_count", "avg_position", "visibility",
        "search_clicks", "search_cart", "search_orders",
        "stockCount", "stockSum"
    ]
    
    # Оставляем только те, что есть в df
    final_cols = [c for c in ordered_cols if c in base_df.columns]
    final_df = base_df[final_cols]
    
    # Заполняем NaN пустыми строками или 0 для чисел (для красоты в GS)
    # Но лучше оставить None для null
    final_df = final_df.fillna("")

    print(f"Final dataset shape: {final_df.shape}")

    # 9. Запись в Google Sheets
    print(f"Writing to sheet '{SHEET_NAME}'...")
    try:
        gs_client.create_or_clear_worksheet(spreadsheet_id, SHEET_NAME)
        gs_client.write_dataframe(spreadsheet_id, SHEET_NAME, final_df)
        print(f"Successfully wrote {len(final_df)} rows to '{SHEET_NAME}'.")
    except Exception as e:
        print(f"Error writing summary sheet: {e}")

    # 10. Заполнение Backlog
    backlog_data = [
        ["Поле", "Причина отсутствия", "Статус"],
        ["entry_point", "Нет источника атрибуции входа", "Backlog"],
        ["operational_profit", "Нет формулы расчета и данных о себестоимости", "Backlog"],
        ["logistics_cost", "Нет данных о логистике", "Backlog"],
        ["tax_cost", "Нет данных о налогах", "Backlog"]
    ]
    
    print(f"Writing to sheet '{BACKLOG_SHEET_NAME}'...")
    try:
        gs_client.create_or_clear_worksheet(spreadsheet_id, BACKLOG_SHEET_NAME)
        gs_client.write_rows(spreadsheet_id, BACKLOG_SHEET_NAME, backlog_data)
        print(f"Successfully wrote backlog items.")
    except Exception as e:
        print(f"Error writing backlog sheet: {e}")

    print("-" * 30)
    print(f"Spreadsheet URL: https://docs.google.com/spreadsheets/d/{spreadsheet_id}/edit")
    print("Done!")


if __name__ == "__main__":
    main()
