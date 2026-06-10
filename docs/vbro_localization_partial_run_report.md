# VBro and Localization Partial Run Report

- Generated at: `2026-06-02T20:45:35+05:00`
- Window: `2026-05-31` .. `2026-06-01`
- Test nmIDs: `197330807, 37320545, 37342770, 36387055, 577510563`
- WB API calls were read-only. No WB/MPStat writes were executed.
- Raw private responses were not saved by this run.
- Mock/fake rows were not added.

## Results

### fact_profit_day

- Status: `PARTIAL`
- Rows written: `10`
- Fields filled: `date,nm_id,supplier_article,title,subject,brand,net_sales_payout,ad_spend,logistics,storage,penalties,deductions,acceptance`
- Fields empty: `organic_sales_qty,cogs,other_costs,operating_profit,operating_profit_per_unit`
- Details: `reportDetailByPeriod provided the financial base, but profit needs COGS/formula confirmation`

### fact_localization_region_day

- Status: `PARTIAL`
- Rows written: `228`
- Fields filled: `date,nm_id,supplier_article,title,subject,brand,country,region,orders_total_qty,sale_item_qty,sale_amount`
- Fields empty: `delivery_time,local_orders_percent,orders_local_qty,orders_nonlocal_qty,wb_stock_qty,mp_stock_qty`
- Details: `regional orders were built from live WB statistics orders; processed table preserved for user wide view`

### fact_localization_region_summary_day

- Status: `PARTIAL`
- Rows written: `86`
- Fields filled: `date,country,region,sale_item_qty,sale_amount,region_orders_share_percent,wb_all_orders_share_percent`
- Fields empty: `local_orders_percent,nonlocal_orders_percent,delivery_time`
- Details: `summary rows were aggregated from regional order rows and kept as processed data`

### ВБро

- Status: `PARTIAL`
- Rows written: `10`
- Fields filled: `date,nm_id,supplier_article`
- Fields empty: `organic_sales_qty,operating_profit,operating_profit_per_unit`
- Details: `profit rows written, but operating profit remains blank until COGS/formula are confirmed`

### Локализация

- Status: `PARTIAL`
- Rows written: `228`
- Fields filled: `Дата,Артикул WB,Артикул продавца,Название,Предмет,Бренд,Регион,Итого заказов, шт,Продажи, шт,Сумма продаж, ₽,Остатки склад ВБ, шт`
- Fields empty: `Остатки МП, шт,Время доставки,Локальные заказы, %,Не локальные заказы, %`
- Details: `wide human-readable regional rows written from live WB statistics orders`

### Coverage

- Status: `OK`
- Rows written: `11`
- Fields filled: `sheet_name,status,details`
- Fields empty: `-`
- Details: `coverage refreshed with current MVP/partial/LATER statuses`

### Backlog

- Status: `OK`
- Rows written: `9`
- Fields filled: `block,status,reason,next_step,priority`
- Fields empty: `-`
- Details: `backlog refreshed with remaining blockers`

## Safety confirmation

- Existing Google Sheets data was not cleared beyond the target data blocks.
- Mock/fake rows were not created.
- WB/MPStat write actions were not executed.
- Unsupported fields were left blank rather than fabricated.
