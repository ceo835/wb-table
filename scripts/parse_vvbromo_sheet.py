from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path
from typing import Any, Sequence

# Add project root to path
ROOT_DIR = Path(__file__).resolve().parent.parent
if str(ROOT_DIR) not in sys.path:
    sys.path.insert(0, str(ROOT_DIR))

import gspread
from google.oauth2 import service_account

from src.config.settings import settings
from src.db.models import FactVvbromoProductDay
from src.db.session import session_scope, upsert_rows


def parse_numeric(val: str, field_name: str, row_num: int, nm_id: int, errors: list[str]) -> int | float | None:
    if not val:
        return None
    cleaned = (
        val.replace(" ", "")
        .replace("\xa0", "")
        .replace("\u2011", "-")
        .replace("\u2014", "-")
        .replace("\u2013", "-")
        .strip()
    )
    if cleaned in ("", "-", "\uFFFD", "null", "None"):
        return None
    if not any(ch.isdigit() for ch in cleaned) and cleaned.strip("?-\uFFFD") == "":
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


def parse_section_date(row: Sequence[Any], target_year: int) -> date | None:
    if not row or not row[0]:
        return None
    val = str(row[0]).strip().replace(" ", "")
    for item in row[1:]:
        if str(item).strip():
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


def parse_vvbromo_values(all_values: Sequence[Sequence[Any]], year: int) -> dict[str, Any]:
    if not all_values:
        return {
            "rows_parsed": 0,
            "date_min": None,
            "date_max": None,
            "distinct_dates": 0,
            "distinct_nm_id": 0,
            "errors": 0,
            "parse_errors_list": [],
            "parsed_records": [],
            "dates_found": [],
        }

    is_vertical_layout = parse_section_date(all_values[0], year) is not None
    parsed_records: list[dict[str, Any]] = []
    parse_errors: list[str] = []
    unique_nm_ids: set[int] = set()
    dates_found: list[date] = []

    if is_vertical_layout:
        current_date: date | None = None
        for idx, row in enumerate(all_values, 1):
            if not row or not str(row[0]).strip():
                continue

            sect_date = parse_section_date(row, year)
            if sect_date is not None:
                current_date = sect_date
                dates_found.append(current_date)
                continue

            first_val = str(row[0]).strip().replace(" ", "")
            if not first_val:
                continue

            if "??????????????" in first_val.lower() or not first_val.isdigit():
                if not first_val.replace(".", "").isdigit():
                    parse_errors.append(f"Row {idx}: Invalid non-integer nm_id '{row[0]}'")
                continue

            nm_id = int(first_val)
            unique_nm_ids.add(nm_id)
            vendor_code = str(row[1]).strip() if len(row) > 1 else ""

            organic_sales_raw = str(row[2]).strip() if len(row) > 2 else ""
            operating_profit_raw = str(row[3]).strip() if len(row) > 3 else ""
            operating_profit_per_unit_raw = str(row[4]).strip() if len(row) > 4 else ""

            if not organic_sales_raw and not operating_profit_raw and not operating_profit_per_unit_raw:
                continue

            organic_sales = parse_numeric(organic_sales_raw, "organic_sales", idx, nm_id, parse_errors)
            operating_profit = parse_numeric(operating_profit_raw, "operating_profit", idx, nm_id, parse_errors)
            operating_profit_per_unit = parse_numeric(
                operating_profit_per_unit_raw,
                "operating_profit_per_unit",
                idx,
                nm_id,
                parse_errors,
            )

            if current_date is None:
                continue

            parsed_records.append(
                {
                    "day": current_date,
                    "nm_id": nm_id,
                    "vendor_code": vendor_code,
                    "organic_sales": organic_sales,
                    "operating_profit": operating_profit,
                    "operating_profit_per_unit": operating_profit_per_unit,
                    "raw_row": {
                        "nm_id": row[0],
                        "vendor_code": row[1] if len(row) > 1 else "",
                        "organic_sales": row[2] if len(row) > 2 else "",
                        "operating_profit": row[3] if len(row) > 3 else "",
                        "operating_profit_per_unit": row[4] if len(row) > 4 else "",
                    },
                }
            )
    else:
        headers = all_values[0]
        data_rows = all_values[2:]
        date_blocks: list[tuple[int, date]] = []
        for col_idx in range(2, len(headers), 4):
            date_str = str(headers[col_idx]).strip()
            if not date_str or "." not in date_str:
                continue
            try:
                day_num, month_num = (int(part) for part in date_str.split(".", 1))
                block_date = date(year, month_num, day_num)
            except Exception:
                continue
            date_blocks.append((col_idx, block_date))
            dates_found.append(block_date)

        for idx, row in enumerate(data_rows, 3):
            if not row:
                continue
            nm_id_raw = str(row[0]).strip().replace(" ", "")
            if not nm_id_raw:
                continue
            try:
                nm_id = int(nm_id_raw)
            except ValueError:
                parse_errors.append(f"Row {idx}: Invalid non-integer nm_id '{row[0]}'")
                continue

            unique_nm_ids.add(nm_id)
            vendor_code = str(row[1]).strip() if len(row) > 1 else ""
            for col_idx, block_date in date_blocks:
                organic_sales_raw = str(row[col_idx]).strip() if col_idx < len(row) else ""
                operating_profit_raw = str(row[col_idx + 1]).strip() if col_idx + 1 < len(row) else ""
                operating_profit_per_unit_raw = str(row[col_idx + 2]).strip() if col_idx + 2 < len(row) else ""
                if not organic_sales_raw and not operating_profit_raw and not operating_profit_per_unit_raw:
                    continue

                organic_sales = parse_numeric(organic_sales_raw, "organic_sales", idx, nm_id, parse_errors)
                operating_profit = parse_numeric(operating_profit_raw, "operating_profit", idx, nm_id, parse_errors)
                operating_profit_per_unit = parse_numeric(
                    operating_profit_per_unit_raw,
                    "operating_profit_per_unit",
                    idx,
                    nm_id,
                    parse_errors,
                )
                parsed_records.append(
                    {
                        "day": block_date,
                        "nm_id": nm_id,
                        "vendor_code": vendor_code,
                        "organic_sales": organic_sales,
                        "operating_profit": operating_profit,
                        "operating_profit_per_unit": operating_profit_per_unit,
                        "raw_row": {
                            "nm_id": row[0],
                            "vendor_code": row[1] if len(row) > 1 else "",
                            "organic_sales": row[col_idx] if col_idx < len(row) else "",
                            "operating_profit": row[col_idx + 1] if col_idx + 1 < len(row) else "",
                            "operating_profit_per_unit": row[col_idx + 2] if col_idx + 2 < len(row) else "",
                        },
                    }
                )

    deduped_records: dict[tuple[date, int], dict[str, Any]] = {}
    for record in parsed_records:
        deduped_records[(record["day"], record["nm_id"])] = record
    parsed_records = list(deduped_records.values())

    return {
        "rows_parsed": len(parsed_records),
        "date_min": min(dates_found).isoformat() if dates_found else None,
        "date_max": max(dates_found).isoformat() if dates_found else None,
        "distinct_dates": len(set(dates_found)),
        "distinct_nm_id": len(unique_nm_ids),
        "errors": len(parse_errors),
        "parse_errors_list": parse_errors,
        "parsed_records": parsed_records,
        "dates_found": dates_found,
    }


def run_loader(year: int, apply: bool = False, dry_run: bool = True) -> dict[str, Any]:
    effective_dry_run = not (apply and not dry_run)

    spreadsheet_id = settings.vvbromo_google_sheet_id
    if not spreadsheet_id:
        raise ValueError("VVBROMO_GOOGLE_SHEET_ID is not configured in settings/environment.")

    scopes = [
        "https://www.googleapis.com/auth/spreadsheets",
        "https://www.googleapis.com/auth/drive.readonly",
    ]
    if settings.google_service_account_json:
        info = json.loads(settings.google_service_account_json)
        creds = service_account.Credentials.from_service_account_info(info, scopes=scopes)
    elif settings.google_application_credentials:
        creds = service_account.Credentials.from_service_account_file(
            settings.google_application_credentials,
            scopes=scopes,
        )
    else:
        raise ValueError("No Google Service Account credentials configured.")

    try:
        client = gspread.authorize(creds)
        sh = client.open_by_key(spreadsheet_id)
    except gspread.exceptions.APIError as exc:
        raise RuntimeError(f"Google Sheets access denied: {exc}") from exc
    except Exception as exc:
        raise RuntimeError(f"Failed to open spreadsheet: {exc}") from exc

    target_sheet_name = settings.vvbromo_google_sheet_name
    target_sheet_gid = settings.vvbromo_google_sheet_gid
    ws = None
    worksheets = sh.worksheets()
    if target_sheet_name:
        ws = sh.worksheet(target_sheet_name)
    else:
        gid_val = 0
        if target_sheet_gid is not None:
            try:
                gid_val = int(target_sheet_gid)
            except ValueError:
                gid_val = 0
        for worksheet in worksheets:
            if worksheet.id == gid_val:
                ws = worksheet
                break
        if ws is None:
            ws = worksheets[0]

    all_values = ws.get_all_values()
    parse_result = parse_vvbromo_values(all_values, year)
    parsed_records = list(parse_result["parsed_records"])
    parse_errors = list(parse_result["parse_errors_list"])
    dates_found = list(parse_result["dates_found"])

    if effective_dry_run:
        print("\n--- Dry-Run Metrics ---")
        print(f"dates_found: {[d.isoformat() for d in dates_found]}")
        print(f"blocks_found: {len(dates_found)}")
        print(f"rows_parsed: {parse_result['rows_parsed']}")
        print(f"nm_id_count: {parse_result['distinct_nm_id']}")
        print("\nsample_rows (first 10):")
        for idx, record in enumerate(parsed_records[:10], 1):
            readable = dict(record)
            readable["day"] = readable["day"].isoformat()
            print(f"  {idx}: {readable}")

        print(f"\nparse_errors (count: {len(parse_errors)}):")
        filtered_errors = [
            error
            for error in parse_errors
            if "Invalid non-integer nm_id" not in error
            or not any(value in error for value in ["??????????????", "", " ", "22.06", "19.06", "20.06", "21.06"])
        ]
        print(f"Total raw errors: {len(parse_errors)}")
        print(f"Filtered unexpected errors (count: {len(filtered_errors)}):")
        for error in filtered_errors[:10]:
            print(f"  - {error}")
        if len(filtered_errors) > 10:
            print(f"  ... and {len(filtered_errors) - 10} more unexpected errors.")

    rows_upserted = 0
    db_changed = False
    if not effective_dry_run and parsed_records:
        with session_scope() as session:
            rowcount = upsert_rows(
                session=session,
                model=FactVvbromoProductDay,
                rows=parsed_records,
                conflict_columns=["day", "nm_id"],
            )
            rows_upserted = rowcount if rowcount >= 0 else len(parsed_records)
            db_changed = rows_upserted > 0

    return {
        "rows_parsed": parse_result["rows_parsed"],
        "rows_upserted": rows_upserted,
        "date_min": parse_result["date_min"],
        "date_max": parse_result["date_max"],
        "distinct_dates": parse_result["distinct_dates"],
        "distinct_nm_id": parse_result["distinct_nm_id"],
        "errors": parse_result["errors"],
        "db_changed": db_changed,
        "parse_errors_list": parse_errors,
    }


def main() -> int:
    parser = argparse.ArgumentParser(description="Parse horizontal or vertical date blocks in VVBromo Google Sheet.")
    parser.add_argument("--year", type=int, required=True, help="Year to associate with sheet dates.")
    parser.add_argument("--dry-run", action="store_true", help="Run without writing to database (default).")
    parser.add_argument("--apply", action="store_true", help="Write parsed data to database.")
    args = parser.parse_args()

    try:
        summary = run_loader(year=args.year, apply=args.apply, dry_run=args.dry_run)
        print("\n--- Summary ---")
        print(f"rows_parsed: {summary['rows_parsed']}")
        print(f"rows_valid: {summary['rows_parsed']}")
        print(f"rows_upserted: {summary['rows_upserted']}")
        print(f"date_min: {summary['date_min']}")
        print(f"date_max: {summary['date_max']}")
        print(f"distinct_dates: {summary['distinct_dates']}")
        print(f"distinct_nm_id: {summary['distinct_nm_id']}")
        print(f"errors: {summary['errors']}")
        print(f"db_changed: {summary['db_changed']}")
        return 0
    except Exception as exc:
        print(f"Execution failed: {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
