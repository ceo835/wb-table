from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, date, datetime
from hashlib import sha256
from typing import Any, Callable

from scripts.parse_vvbromo_sheet import parse_vvbromo_values
from src.clients.google_drive_client import GOOGLE_FOLDER_MIME_TYPE, GoogleDriveClient, is_supported_supply_file
from src.clients.google_sheets_client import GoogleSheetsClient
from src.config.settings import settings
from src.db.google_drive_source_loader import load_google_drive_source_file_index, upsert_google_drive_source_file
from src.db.ivan_stock_sheet_loader import STOCK_SHEET_NAME, parse_ivan_stock_values, save_ivan_stock_rows
from src.db.models import FactVvbromoProductDay
from src.db.session import session_scope, upsert_rows
from src.services.wb_supplies.file_reader import ParsedWorkbook, ParsedWorksheet, read_supply_file
from src.utils.logger import get_logger

logger = get_logger("google_drive_daily_sync")

SOURCE_VVBROMO = "WBRO"
SOURCE_IVAN_STOCK = "IVAN_STOCK"

STATUS_DISCOVERED = "DISCOVERED"
STATUS_DOWNLOADED = "DOWNLOADED"
STATUS_VALIDATED = "VALIDATED"
STATUS_PROCESSED = "PROCESSED"
STATUS_SKIPPED_ALREADY_PROCESSED = "SKIPPED_ALREADY_PROCESSED"
STATUS_FAILED_DOWNLOAD = "FAILED_DOWNLOAD"
STATUS_FAILED_VALIDATION = "FAILED_VALIDATION"
STATUS_FAILED_PROCESSING = "FAILED_PROCESSING"

_SKIP_FINAL_STATUSES = {
    STATUS_PROCESSED,
    STATUS_SKIPPED_ALREADY_PROCESSED,
    STATUS_FAILED_VALIDATION,
}


@dataclass(frozen=True)
class DriveSourceConfig:
    source_type: str
    folder_id: str
    display_name: str
    parser: Callable[[ParsedWorkbook, date], dict[str, Any]]
    writer: Callable[[dict[str, Any], bool], int]
    destination_table: str
    loader_entrypoint: str


def _mask_folder_id(folder_id: str | None) -> str | None:
    if not folder_id:
        return None
    text = str(folder_id).strip()
    if len(text) <= 8:
        return text
    return f"{text[:4]}...{text[-4:]}"


def _default_sheets_client() -> GoogleSheetsClient:
    return GoogleSheetsClient(
        credentials_path=settings.google_application_credentials or "credentials.json",
        spreadsheet_id=settings.google_sheet_id,
    )


def _parse_google_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def _parse_file_size(value: Any) -> int | None:
    if value in (None, ""):
        return None
    try:
        return int(value)
    except (TypeError, ValueError):
        return None


def _serialize_for_hash(value: Any) -> Any:
    if isinstance(value, datetime):
        return value.isoformat()
    if isinstance(value, date):
        return value.isoformat()
    if isinstance(value, (str, int, float, bool)) or value is None:
        return value
    if isinstance(value, dict):
        return {str(key): _serialize_for_hash(val) for key, val in value.items()}
    if isinstance(value, (list, tuple, set)):
        return [_serialize_for_hash(item) for item in value]
    return str(value)


def _content_hash(workbook: ParsedWorkbook) -> str:
    payload = {
        "source_file_id": workbook.source_file_id,
        "source_file_name": workbook.source_file_name,
        "effective_file_id": workbook.effective_file_id,
        "effective_file_name": workbook.effective_file_name,
        "worksheets": [
            {
                "sheet_name": worksheet.sheet_name,
                "rows": _serialize_for_hash(worksheet.rows),
            }
            for worksheet in workbook.worksheets
        ],
    }
    raw = json.dumps(payload, ensure_ascii=False, sort_keys=True).encode("utf-8")
    return sha256(raw).hexdigest()


def _walk_supported_files(drive_client: GoogleDriveClient, folder_id: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    queue = [folder_id]
    visited_folders: set[str] = set()
    supported: list[dict[str, Any]] = []
    unsupported: list[dict[str, Any]] = []
    seen_files: set[str] = set()

    while queue:
        current_folder_id = queue.pop(0)
        if current_folder_id in visited_folders:
            continue
        visited_folders.add(current_folder_id)

        for child in drive_client.list_folder_children(current_folder_id):
            child_id = str(child.get("id") or "")
            if child.get("mimeType") == GOOGLE_FOLDER_MIME_TYPE:
                if child_id:
                    queue.append(child_id)
                continue
            if child_id and child_id in seen_files:
                continue
            if child_id:
                seen_files.add(child_id)
            if is_supported_supply_file(child):
                supported.append(dict(child))
            else:
                unsupported.append(dict(child))

    return supported, unsupported


def _parse_vvbromo_workbook(workbook: ParsedWorkbook, run_date: date) -> dict[str, Any]:
    best_result: dict[str, Any] | None = None
    best_worksheet: ParsedWorksheet | None = None
    for worksheet in workbook.worksheets:
        result = parse_vvbromo_values(worksheet.rows, run_date.year)
        if best_result is None or result["rows_parsed"] > best_result["rows_parsed"]:
            best_result = result
            best_worksheet = worksheet
    if best_result is None or best_result["rows_parsed"] <= 0:
        raise ValueError("No VVBROMO rows could be parsed from workbook.")
    return {
        "worksheet_name": best_worksheet.sheet_name if best_worksheet else None,
        "rows_loaded": best_result["rows_parsed"],
        "records": list(best_result["parsed_records"]),
        "summary": {key: value for key, value in best_result.items() if key not in {"parsed_records", "dates_found"}},
    }


def _parse_ivan_stock_workbook(workbook: ParsedWorkbook, _run_date: date) -> dict[str, Any]:
    ordered_worksheets = sorted(
        workbook.worksheets,
        key=lambda worksheet: (0 if worksheet.sheet_name.strip().lower() == STOCK_SHEET_NAME.lower() else 1, worksheet.sheet_name),
    )
    best_result: dict[str, Any] | None = None
    best_worksheet: ParsedWorksheet | None = None
    for worksheet in ordered_worksheets:
        try:
            result = parse_ivan_stock_values(worksheet.rows, source_sheet=worksheet.sheet_name)
        except Exception:
            continue
        if best_result is None or result["rows_with_nm_id"] > best_result["rows_with_nm_id"]:
            best_result = result
            best_worksheet = worksheet
    if best_result is None or best_result["rows_with_nm_id"] <= 0:
        raise ValueError("No IVAN_STOCK rows could be parsed from workbook.")
    return {
        "worksheet_name": best_worksheet.sheet_name if best_worksheet else None,
        "rows_loaded": best_result["rows_with_nm_id"],
        "records": list(best_result["rows_to_save"]),
        "summary": {key: value for key, value in best_result.items() if key != "rows_to_save"},
    }


def _write_vvbromo_rows(parsed_payload: dict[str, Any], write_db: bool) -> int:
    records = list(parsed_payload.get("records") or [])
    if not write_db or not records:
        return 0
    with session_scope() as session:
        rowcount = upsert_rows(
            session=session,
            model=FactVvbromoProductDay,
            rows=records,
            conflict_columns=("day", "nm_id"),
        )
    return rowcount if rowcount >= 0 else len(records)


def _write_ivan_stock_rows(parsed_payload: dict[str, Any], write_db: bool) -> int:
    summary = parsed_payload.get("summary") or {}
    write_result = save_ivan_stock_rows(
        stock_date=summary["stock_date"],
        rows_to_save=parsed_payload.get("records") or [],
        write_db=write_db,
    )
    return int(write_result.get("rows_inserted") or 0)


def _build_source_config(source_type: str) -> DriveSourceConfig:
    if source_type == SOURCE_VVBROMO:
        folder_id = settings.vvbromo_google_drive_folder_id
        if not folder_id:
            raise ValueError("VVBROMO_GOOGLE_DRIVE_FOLDER_ID is not configured.")
        return DriveSourceConfig(
            source_type=SOURCE_VVBROMO,
            folder_id=folder_id,
            display_name="VVBROMO",
            parser=_parse_vvbromo_workbook,
            writer=_write_vvbromo_rows,
            destination_table="fact_vvbromo_product_day",
            loader_entrypoint="scripts.parse_vvbromo_sheet.run_loader",
        )
    if source_type == SOURCE_IVAN_STOCK:
        folder_id = settings.ivan_stock_google_drive_folder_id
        if not folder_id:
            raise ValueError("IVAN_STOCK_GOOGLE_DRIVE_FOLDER_ID is not configured.")
        return DriveSourceConfig(
            source_type=SOURCE_IVAN_STOCK,
            folder_id=folder_id,
            display_name="IVAN_STOCK",
            parser=_parse_ivan_stock_workbook,
            writer=_write_ivan_stock_rows,
            destination_table="fact_ivan_stock_sheet_day",
            loader_entrypoint="src.db.ivan_stock_sheet_loader.load_ivan_stock_sheet",
        )
    raise ValueError(f"Unsupported source_type: {source_type}")


def _load_existing_index(source_type: str) -> dict[str, Any]:
    with session_scope() as session:
        return load_google_drive_source_file_index(session, source_type)


def _save_source_file_state(state: dict[str, Any]) -> None:
    with session_scope() as session:
        upsert_google_drive_source_file(session, state)


def _base_file_state(source_type: str, file_meta: dict[str, Any]) -> dict[str, Any]:
    return {
        "source_type": source_type,
        "google_file_id": str(file_meta.get("id") or ""),
        "google_file_name": str(file_meta.get("name") or ""),
        "google_modified_time": _parse_google_datetime(file_meta.get("modifiedTime")),
        "file_size": _parse_file_size(file_meta.get("size")),
        "content_hash": None,
        "processing_status": STATUS_DISCOVERED,
        "processed_at": datetime.now(UTC),
        "rows_loaded": 0,
        "error_text": None,
    }


def _is_unchanged_processed(existing: Any, file_meta: dict[str, Any]) -> bool:
    if existing is None:
        return False
    if getattr(existing, "processing_status", None) not in _SKIP_FINAL_STATUSES:
        return False
    existing_modified = getattr(existing, "google_modified_time", None)
    new_modified = _parse_google_datetime(file_meta.get("modifiedTime"))
    existing_size = getattr(existing, "file_size", None)
    new_size = _parse_file_size(file_meta.get("size"))
    return existing_modified == new_modified and existing_size == new_size


def _sync_drive_source(
    source_type: str,
    *,
    run_date: date,
    write_db: bool,
    drive_client: GoogleDriveClient | None = None,
    sheets_client: GoogleSheetsClient | None = None,
) -> dict[str, Any]:
    config = _build_source_config(source_type)
    resolved_drive_client = drive_client or GoogleDriveClient()
    resolved_sheets_client = sheets_client or _default_sheets_client()
    existing_index = _load_existing_index(source_type)

    supported_files, unsupported_files = _walk_supported_files(resolved_drive_client, config.folder_id)
    supported_files.sort(key=lambda item: (str(item.get("name") or ""), str(item.get("id") or "")))

    summary: dict[str, Any] = {
        "source": source_type,
        "display_name": config.display_name,
        "destination_table": config.destination_table,
        "loader_entrypoint": config.loader_entrypoint,
        "run_date": run_date.isoformat(),
        "folder_id_masked": _mask_folder_id(config.folder_id),
        "files_found": len(supported_files),
        "new_files": 0,
        "already_processed": 0,
        "processed_files": 0,
        "skipped_files": 0,
        "failed_files": 0,
        "rows_loaded": 0,
        "unsupported_files": [
            {
                "google_file_id": str(item.get("id") or ""),
                "google_file_name": str(item.get("name") or ""),
                "mime_type": item.get("mimeType"),
            }
            for item in unsupported_files
        ],
        "file_results": [],
        "success": True,
        "status": "NO_NEW_FILES",
    }

    for file_meta in supported_files:
        state = _base_file_state(source_type, file_meta)
        existing = existing_index.get(state["google_file_id"])
        file_result = {
            "google_file_id": state["google_file_id"],
            "google_file_name": state["google_file_name"],
            "status": STATUS_DISCOVERED,
            "rows_loaded": 0,
            "worksheet_name": None,
            "error": None,
        }

        if _is_unchanged_processed(existing, file_meta):
            summary["already_processed"] += 1
            summary["skipped_files"] += 1
            file_result["status"] = STATUS_SKIPPED_ALREADY_PROCESSED
            if write_db:
                state["content_hash"] = getattr(existing, "content_hash", None)
                state["processing_status"] = STATUS_SKIPPED_ALREADY_PROCESSED
                state["rows_loaded"] = getattr(existing, "rows_loaded", 0)
                _save_source_file_state(state)
            summary["file_results"].append(file_result)
            continue

        summary["new_files"] += 1
        try:
            workbook = read_supply_file(
                file_meta,
                drive_client=resolved_drive_client,
                sheets_client=resolved_sheets_client,
            )
            state["processing_status"] = STATUS_DOWNLOADED
            workbook_hash = _content_hash(workbook)
            state["content_hash"] = workbook_hash

            if (
                existing is not None
                and getattr(existing, "content_hash", None)
                and getattr(existing, "content_hash", None) == workbook_hash
                and getattr(existing, "processing_status", None) in _SKIP_FINAL_STATUSES
            ):
                summary["already_processed"] += 1
                summary["skipped_files"] += 1
                file_result["status"] = STATUS_SKIPPED_ALREADY_PROCESSED
                if write_db:
                    state["processing_status"] = STATUS_SKIPPED_ALREADY_PROCESSED
                    state["rows_loaded"] = getattr(existing, "rows_loaded", 0)
                continue

            parsed_payload = config.parser(workbook, run_date)
            state["processing_status"] = STATUS_VALIDATED
            file_result["worksheet_name"] = parsed_payload.get("worksheet_name")
            file_result["rows_loaded"] = int(parsed_payload.get("rows_loaded") or 0)
            rows_written = config.writer(parsed_payload, write_db)
            state["processing_status"] = STATUS_PROCESSED
            state["rows_loaded"] = int(parsed_payload.get("rows_loaded") or 0)
            summary["processed_files"] += 1
            summary["rows_loaded"] += state["rows_loaded"]
            file_result["status"] = STATUS_PROCESSED
            file_result["rows_written"] = rows_written
        except ValueError as exc:
            state["processing_status"] = STATUS_FAILED_VALIDATION
            state["error_text"] = str(exc)
            summary["failed_files"] += 1
            summary["success"] = False
            file_result["status"] = STATUS_FAILED_VALIDATION
            file_result["error"] = str(exc)
        except Exception as exc:
            message = str(exc)
            status = STATUS_FAILED_DOWNLOAD if state["processing_status"] == STATUS_DISCOVERED else STATUS_FAILED_PROCESSING
            state["processing_status"] = status
            state["error_text"] = message
            summary["failed_files"] += 1
            summary["success"] = False
            file_result["status"] = status
            file_result["error"] = message
            logger.warning("Drive sync failed for %s/%s: %s", source_type, state["google_file_name"], message)
        finally:
            summary["file_results"].append(file_result)
            if write_db:
                _save_source_file_state(state)

    if summary["processed_files"] > 0 and summary["failed_files"] == 0:
        summary["status"] = "OK"
    elif summary["processed_files"] > 0 and summary["failed_files"] > 0:
        summary["status"] = "PARTIAL"
    elif summary["failed_files"] > 0:
        summary["status"] = "FAILED"
    elif summary["already_processed"] > 0 or summary["files_found"] == 0:
        summary["status"] = "NO_NEW_FILES"

    return summary


def sync_vvbromo_from_google_drive(
    *,
    run_date: date,
    write_db: bool,
    drive_client: GoogleDriveClient | None = None,
    sheets_client: GoogleSheetsClient | None = None,
) -> dict[str, Any]:
    return _sync_drive_source(
        SOURCE_VVBROMO,
        run_date=run_date,
        write_db=write_db,
        drive_client=drive_client,
        sheets_client=sheets_client,
    )


def sync_ivan_stock_from_google_drive(
    *,
    run_date: date,
    write_db: bool,
    drive_client: GoogleDriveClient | None = None,
    sheets_client: GoogleSheetsClient | None = None,
) -> dict[str, Any]:
    return _sync_drive_source(
        SOURCE_IVAN_STOCK,
        run_date=run_date,
        write_db=write_db,
        drive_client=drive_client,
        sheets_client=sheets_client,
    )
