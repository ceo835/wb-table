# Localization User View Report

- Generated at: `2026-06-02T20:45:35+05:00`
- Window: `2026-05-31` .. `2026-06-01`
- Test nmIDs: `197330807, 37320545, 37342770, 36387055, 577510563`
- User sheet format: wide one-row-per-date-nm_id-region
- Processed tables were preserved unchanged.

## Results

### fact_localization_region_day

- Status: `PARTIAL`
- Rows written / checked: `228`
- Fields filled: `date,nm_id,supplier_article,title,subject,brand,country,region,orders_total_qty,sale_item_qty,sale_amount,wb_stock_qty`
- Fields empty: `delivery_time,local_orders_percent,orders_local_qty,orders_nonlocal_qty,mp_stock_qty`
- Details: `processed table preserved; wide user view is projected from this source`

### fact_localization_region_summary_day

- Status: `PARTIAL`
- Rows written / checked: `86`
- Fields filled: `date,country,region,sale_item_qty,sale_amount,region_orders_share_percent,wb_all_orders_share_percent`
- Fields empty: `local_orders_percent,nonlocal_orders_percent,delivery_time`
- Details: `processed summary table preserved; not written to the user sheet`

### Локализация

- Status: `PARTIAL`
- Rows written / checked: `228`
- Fields filled: `Дата,Артикул WB,Артикул продавца,Название,Предмет,Бренд,Регион,Итого заказов, шт,Продажи, шт,Сумма продаж, ₽,Остатки склад ВБ, шт`
- Fields empty: `Остатки МП, шт,Время доставки,Локальные заказы, %,Не локальные заказы, %`
- Details: `wide one-row-per-region user view written without metric_name/metric_value projection`

### check::no_mock_fake

- Status: `PASS`
- Rows written / checked: `228`
- Fields filled: `-`
- Fields empty: `-`
- Details: `no ART-, TestBrand, DRY_RUN, mock, or fake markers were found`

### check::no_duplicates

- Status: `PASS`
- Rows written / checked: `228`
- Fields filled: `-`
- Fields empty: `-`
- Details: `rows are unique by date + nm_id + region`

### check::no_metric_columns

- Status: `PASS`
- Rows written / checked: `1`
- Fields filled: `-`
- Fields empty: `-`
- Details: `metric_name and metric_value are not present in the user sheet headers`

### check::real_regions

- Status: `PASS`
- Rows written / checked: `228`
- Fields filled: `-`
- Fields empty: `-`
- Details: `real region values are present in the user sheet`

### check::real_metrics

- Status: `PASS`
- Rows written / checked: `228`
- Fields filled: `-`
- Fields empty: `-`
- Details: `orders_total_qty, sale_item_qty, or sale_amount contain real values`

### check::processed_tables_preserved

- Status: `PASS`
- Rows written / checked: `314`
- Fields filled: `-`
- Fields empty: `-`
- Details: `fact_localization_region_day and fact_localization_region_summary_day were not lost`

## Safety confirmation

- Mock/fake rows were not added.
- Unsupported fields remained blank rather than fabricated.
- Processed localization tables remained available on disk.
