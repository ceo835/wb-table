from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import gspread
from google.oauth2 import service_account
from src.config.settings import settings


def parse_numeric(val: str, field_name: str, row_num: int, nm_id: int, errors: list[str]) -> int | float | None:
    if not val:
        return None
    # Clean spacing, non-breaking spaces, unicode hyphens and OEM artifacts
    cleaned = (
        val.replace(" ", "")
        .replace("\xa0", "")
        .replace("\u2011", "-")
        .replace("—", "-")
        .replace("–", "-")
        .strip()
    )
    # Treat common empty representations as null
    if cleaned in ("", "-", "—", "–", "null", "None"):
        return None
    
    # Remove hidden character placeholders (like standard question mark or raw CP866 replacements)
    cleaned = cleaned.replace("", "")
    if not cleaned or cleaned == "-":
        return None
        
    try:
        if "." in cleaned or "," in cleaned:
            cleaned = cleaned.replace(",", ".")
            return float(cleaned)
        return int(cleaned)
    except ValueError:
        errors.append(
            f"Row {row_num} (nm_id: {nm_id}): Could not parse numeric value '{val}' for field '{field_name}'"
        )
        return None


def parse_section_date(row: list[str], target_year: int) -> date | None:
    if not row or not row[0]:
        return None
    val = row[0].strip().replace(" ", "")
    # Check that other cells in this row are empty (meaning it's a section header)
    for item in row[1:]:
        if item.strip():
            return None
            
    parts = val.split(".")
    if len(parts) == 2:
        try:
            day = int(parts[0])
            month = int(parts[1])
            return date(target_year, month, day)
        except ValueError:
            return None
    return None


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse horizontal or vertical date blocks in VVBromo Google Sheet.")
    parser.add_argument("--year", type=int, required=True, help="Year to associate with sheet dates.")
    parser.add_argument("--dry-run", action="store_true", help="Run without writing to database.")
    args = parser.parse_args()

    spreadsheet_id = settings.vvbromo_google_sheet_id
    if not spreadsheet_id:
        print("Error: VVBROMO_GOOGLE_SHEET_ID is not configured in settings/environment.")
        return 1

    # 1. Resolve Credentials
    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly"
    ]
    try:
        if settings.google_service_account_json:
            info = json.loads(settings.google_service_account_json)
            creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
        elif settings.google_application_credentials:
            creds = service_account.Credentials.from_service_account_file(
                settings.google_application_credentials,
                scopes=scopes
            )
        else:
            print("Error: No Google Service Account credentials configured.")
            return 1
    except Exception as e:
        print(f"Error parsing credentials: {e}")
        return 1

    # 2. Connect to Sheets API
    try:
        client = gspread.authorize(creds)
        sh = client.open_by_key(spreadsheet_id)
    except gspread.exceptions.APIError:
        print("\nGoogle Sheets access denied.")
        print("Check that the service account email has Viewer access to the spreadsheet.")
        return 1
    except Exception as e:
        print(f"Failed to open spreadsheet: {e}")
        return 1

    # 3. Resolve target worksheet
    target_sheet_name = settings.vvbromo_google_sheet_name
    target_sheet_gid = settings.vvbromo_google_sheet_gid
    ws = None
    try:
        worksheets = sh.worksheets()
        if target_sheet_name:
            ws = sh.worksheet(target_sheet_name)
        else:
            gid_val = 0
            if target_sheet_gid is not None:
                try:
                    gid_val = int(target_sheet_gid)
                except ValueError:
                    pass
            for w in worksheets:
                if w.id == gid_val:
                    ws = w
                    break
            if ws is None:
                ws = worksheets[0]
    except Exception as e:
        print(f"Failed to resolve worksheet: {e}")
        return 1

    # 4. Fetch values
    try:
        all_values = ws.get_all_values()
    except Exception as e:
        print(f"Error fetching worksheet data: {e}")
        return 1

    if not all_values:
        print("Selected sheet is empty.")
        return 0

    # 5. Determine sheet layout structure (Horizontal vs Vertical blocks)
    is_vertical_layout = parse_section_date(all_values[0], args.year) is not None

    parsed_records: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    unique_nm_ids: set[int] = set()
    dates_found: list[date] = []

    if is_vertical_layout:
        print("Detected Vertical Layout (date section blocks stacked vertically)")
        current_date = None
        for idx, row in enumerate(all_values, 1):
            if not row or not row[0]:
                continue
            
            # Check if this row is a new date section header
            sect_date = parse_section_date(row, args.year)
            if sect_date is not None:
                current_date = sect_date
                dates_found.append(current_date)
                continue
                
            first_val = row[0].strip().replace(" ", "")
            if not first_val:
                continue
                
            # Skip sub-headers or helper rows
            if "артикул" in first_val.lower() or not first_val.isdigit():
                # Avoid logging simple string labels or dates that failed clean validation
                if not first_val.replace(".", "").isdigit():
                    parse_errors.append(f"Row {idx}: Invalid non-integer nm_id '{row[0]}'")
                continue
                
            nm_id = int(first_val)
            unique_nm_ids.add(nm_id)
            vendor_code = row[1].strip() if len(row) > 1 else ""
            
            # Parse sales and profit metrics
            organic_sales_raw = row[2].strip() if len(row) > 2 else ""
            operating_profit_raw = row[3].strip() if len(row) > 3 else ""
            operating_profit_per_unit_raw = row[4].strip() if len(row) > 4 else ""
            
            # If everything is empty for this product on this day, skip
            if not organic_sales_raw and not operating_profit_raw and not operating_profit_per_unit_raw:
                continue
                
            organic_sales = parse_numeric(organic_sales_raw, "organic_sales", idx, nm_id, parse_errors)
            operating_profit = parse_numeric(operating_profit_raw, "operating_profit", idx, nm_id, parse_errors)
            operating_profit_per_unit = parse_numeric(operating_profit_per_unit_raw, "operating_profit_per_unit", idx, nm_id, parse_errors)
            
            if current_date is not None:
                parsed_records.append({
                    "day": current_date.isoformat(),
                    "nm_id": nm_id,
                    "vendor_code": vendor_code,
                    "organic_sales": organic_sales,
                    "operating_profit": operating_profit,
                    "operating_profit_per_unit": operating_profit_per_unit
                })
    else:
        print("Detected Horizontal Layout (date blocks placed horizontally in columns)")
        headers = all_values[0]
        data_rows = all_values[2:]
        
        # Parse horizontal headers
        date_blocks: list[tuple[int, date]] = []
        for col_idx in range(2, len(headers), 4):
            date_str = headers[col_idx].strip()
            if not date_str or "." not in date_str:
                continue
            try:
                parts = date_str.split(".")
                day = int(parts[0])
                month = int(parts[1])
                block_date = date(args.year, month, day)
                date_blocks.append((col_idx, block_date))
                dates_found.append(block_date)
            except Exception:
                continue
                
        # Parse horizontal records
        for idx, row in enumerate(data_rows, 3):
            if not row:
                continue
            nm_id_raw = row[0].strip().replace(" ", "")
            if not nm_id_raw:
                continue
                
            try:
                nm_id = int(nm_id_raw)
            except ValueError:
                parse_errors.append(f"Row {idx}: Invalid non-integer nm_id '{row[0]}'")
                continue
                
            unique_nm_ids.add(nm_id)
            vendor_code = row[1].strip() if len(row) > 1 else ""
            
            for col_idx, block_date in date_blocks:
                organic_sales_raw = row[col_idx].strip() if col_idx < len(row) else ""
                operating_profit_raw = row[col_idx + 1].strip() if col_idx + 1 < len(row) else ""
                operating_profit_per_unit_raw = row[col_idx + 2].strip() if col_idx + 2 < len(row) else ""
                
                if not organic_sales_raw and not operating_profit_raw and not operating_profit_per_unit_raw:
                    continue
                    
                organic_sales = parse_numeric(organic_sales_raw, "organic_sales", idx, nm_id, parse_errors)
                operating_profit = parse_numeric(operating_profit_raw, "operating_profit", idx, nm_id, parse_errors)
                operating_profit_per_unit = parse_numeric(operating_profit_per_unit_raw, "operating_profit_per_unit", idx, nm_id, parse_errors)
                
                parsed_records.append({
                    "day": block_date.isoformat(),
                    "nm_id": nm_id,
                    "vendor_code": vendor_code,
                    "organic_sales": organic_sales,
                    "operating_profit": operating_profit,
                    "operating_profit_per_unit": operating_profit_per_unit
                })

    # 7. Output Dry-Run Metrics
    if args.dry_run:
        print("\n--- Dry-Run Metrics ---")
        print(f"dates_found: {[d.isoformat() for d in dates_found]}")
        print(f"blocks_found: {len(dates_found)}")
        print(f"rows_parsed: {len(parsed_records)}")
        print(f"nm_id_count: {len(unique_nm_ids)}")
        print("\nsample_rows (first 10):")
        for i, record in enumerate(parsed_records[:10], 1):
            print(f"  {i}: {record}")
            
        print(f"\nparse_errors (count: {len(parse_errors)}):")
        # Filter helper/header errors that are expected
        filtered_errors = [e for e in parse_errors if "Invalid non-integer nm_id" not in e or not any(x in e for x in ["Артикул", "", " ", "22.06", "19.06", "20.06", "21.06"])]
        print(f"Total raw errors: {len(parse_errors)}")
        print(f"Filtered unexpected errors (count: {len(filtered_errors)}):")
        for err in filtered_errors[:10]:
            print(f"  - {err}")
        if len(filtered_errors) > 10:
            print(f"  ... and {len(filtered_errors) - 10} more unexpected errors.")
            
    return 0


if __name__ == "__main__":
    sys.exit(main())
