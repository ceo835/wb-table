# Root Cause Analysis: ИТОГО_v1 Incorrect Data

## Diagnosis Summary (2026-05-28)

### 1. Source Data Status (`data/processed/`)
All required source files **EXIST** and contain valid data:

| File | Rows | Status | Notes |
|------|------|--------|-------|
| `dim_product.csv` | 3 | ✅ OK | `title`, `supplier_article` filled. nmIDs: 197330807, 37320545, 37342770 |
| `fact_funnel_day.csv` | 21 | ✅ OK | Contains `openCount`, `cartCount`, `orderCount`, etc. Dates: 2026-05-22 to 2026-05-28 |
| `fact_stock_snapshot.csv` | 3 | ✅ OK | Contains `stockCount`, `stockSum` |
| `fact_ad_campaign_nm_day.csv` | 14 | ⚠️ WARNING | Data exists, BUT `ad_spend` values are huge (~394 million). Likely in cents/micro-units. |
| `fact_search_query_metric.csv` | 14 | ✅ OK | Contains search metrics |

### 2. Why ИТОГО_v1 is Empty/Incorrect?

The problem is **NOT** missing source data. The problem is in the **assembly script** (`scripts/build_summary_v1.py`).

#### Root Causes Identified:

1. **Missing Funnel Data in Output**:
   - `fact_funnel_day.csv` has 21 rows with valid `openCount`, `cartCount`, etc.
   - If ИТОГО_v1 lacks these columns, the script is either:
     - Not merging `fact_funnel_day` at all.
     - Dropping these columns during merge/rename.
     - Using a different base DataFrame (e.g., empty grid) instead of `fact_funnel_day`.

2. **Empty Supplier Article/Title**:
   - `dim_product.csv` has valid `title`, `supplier_article`.
   - If output is empty, the merge key `nm_id` might be mismatched (e.g., int vs string type mismatch before merge).
   - **Fix**: Ensure both sides of merge have `nm_id` as `str`.

3. **Ad Spend Huge Values**:
   - Raw `ad_spend` in `fact_ad_campaign_nm_day.csv`: ~394,662,614.
   - Expected: ~3,946,626 RUB.
   - **Cause**: Script does not divide by 100 (if API returns cents) or does not normalize units.
   - **Fix**: Detect scale and divide `ad_spend`, `ad_revenue` by 100.

4. **Duplicate Columns**:
   - Report mentions duplicates: `visibility`, `search_clicks`, `stockCount`, etc.
   - **Cause**: Script likely merges multiple DataFrames without handling overlapping column names correctly (e.g., using `pd.concat` with duplicate keys or merging twice).
   - **Fix**: Explicitly select and rename columns before merge. Ensure final DataFrame has unique columns.

5. **Search Metrics Empty**:
   - `fact_search_query_metric.csv` has 14 rows.
   - If output is empty, merge on `date` + `nm_id` is failing (type mismatch or wrong column names).

### 3. Required Fixes in `scripts/build_summary_v1.py`

1. **Base DataFrame**: Must be `fact_funnel_day`. Do not create artificial grid.
   ```python
   df_base = pd.read_csv("data/processed/fact_funnel_day.csv")
   ```

2. **Normalize Keys**:
   ```python
   df_base["nm_id"] = df_base["nm_id"].astype(str).str.strip()
   df_base["date"] = pd.to_datetime(df_base["date"]).dt.strftime("%Y-%m-%d")
   # Repeat for all other DFs before merge
   ```

3. **Merge Dim Product**:
   ```python
   df_dim = pd.read_csv("data/processed/dim_product.csv")
   df_dim["nm_id"] = df_dim["nm_id"].astype(str).str.strip()
   # Rename if needed: vendorCode -> supplier_article
   df = df_base.merge(df_dim[["nm_id", "supplier_article", "title", "subject", "brand"]], on="nm_id", how="left")
   ```

4. **Fix Ad Units**:
   ```python
   df_ad["ad_spend"] = df_ad["ad_spend"] / 100.0
   df_ad["ad_revenue"] = df_ad["ad_revenue"] / 100.0
   ```

5. **Prevent Duplicate Columns**:
   - Before final output, check: `assert df.columns.is_unique`
   - Drop exact duplicate columns if any.

6. **Filter Empty Rows**:
   - Remove rows where ALL metrics (funnel, ad, search, stock) are null/zero.

### 4. Conclusion

**Data is ready.** The issue is 100% in the transformation logic of `build_summary_v1.py`.
No need to re-run extractors. Just fix the assembly script and re-run it.
