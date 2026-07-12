from __future__ import annotations

import hashlib
import json
import re
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Sequence

from src.clients.google_drive_client import (
    GOOGLE_FOLDER_MIME_TYPE,
    GOOGLE_SHEETS_MIME_TYPE,
    MS_EXCEL_MIME_TYPES,
    GoogleDriveClient,
    READ_ONLY_DRIVE_SCOPES,
    get_unsupported_supply_reason,
    is_supported_supply_file,
)
from src.clients.google_sheets_client import GoogleSheetsClient
from src.config.settings import settings
from src.db.session import session_scope
from src.db.wb_supply_loader import replace_wb_supply_file_rows, upsert_wb_supply_source_file
from src.services.wb_supplies.file_reader import ParsedWorkbook, read_supply_file
from src.utils.logger import get_logger

logger = get_logger("wb_supplies_sync")

HEADER_ALIASES: dict[str, set[str]] = {
    "nm_id": {"nmid", "nm id", "нм", "артикул wb", "артикул вб", "артикул wildberries", "wb article"},
    "barcode": {"barcode", "баркод", "штрихкод", "шк", "sku barcode"},
    "vendor_code": {"vendor code", "артикул продавца", "артикул поставщика", "seller article", "seller sku"},
    "product_name": {"название", "название товара", "наименование", "товар", "номенклатура", "product name"},
    "supply_quantity": {"количество", "кол-во", "поставка", "qty", "quantity", "кол во"},
    "warehouse_name": {"склад", "направление", "warehouse", "destination"},
    "comment": {"комментарий", "коммент", "comment", "примечание"},
}
HEADER_WEIGHTS = {
    "nm_id": 4,
    "barcode": 4,
    "vendor_code": 3,
    "product_name": 2,
    "supply_quantity": 5,
    "warehouse_name": 1,
    "comment": 1,
}
MAX_HEADER_SCAN_ROWS = 80


def normalize_header_name(value: Any) -> str:
    text = str(value or "").strip().lower().replace("\xa0", " ")
    text = text.replace("_", " ").replace("-", " ")
    text = re.sub(r"[^0-9a-zа-яё ]+", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def detect_warehouse_name(file_name: str, sheet_name: str | None = None) -> str | None:
    for raw in (file_name, sheet_name):
        if not raw:
            continue
        candidate = Path(str(raw)).stem.strip()
        candidate = re.sub(r"\s+", " ", candidate)
        candidate = candidate.strip(" -_")
        if candidate and candidate.lower() not in {"лист1", "sheet1", "sheet", "лист"}:
            return candidate
    return None


def _normalize_digits(value: Any) -> str | None:
    if value is None:
        return None
    text = str(value).strip().replace(" ", "").replace("\xa0", "")
    if not text:
        return None
    if "." in text:
        head, _, tail = text.partition(".")
        if head.isdigit() and tail and set(tail) == {"0"}:
            text = head
    return text if text.isdigit() else None


def normalize_nm_id(value: Any) -> int | None:
    digits = _normalize_digits(value)
    return int(digits) if digits else None


def normalize_barcode(value: Any) -> str | None:
    return _normalize_digits(value)


def normalize_vendor_code(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def normalize_text(value: Any) -> str | None:
    text = str(value or "").strip()
    return text or None


def parse_google_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    text = str(value).strip()
    try:
        return datetime.fromisoformat(text.replace("Z", "+00:00"))
    except ValueError:
        return None


def parse_supply_quantity(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip().replace(" ", "").replace("\xa0", "")
    if not text or text in {"-", "—"}:
        return None
    text = text.replace(",", ".")
    try:
        return Decimal(text)
    except (InvalidOperation, ValueError):
        return None


def build_row_hash(*, google_file_id: str, sheet_name: str, row_number: int, raw_row: Sequence[Any]) -> str:
    payload = json.dumps(
        {
            "google_file_id": google_file_id,
            "sheet_name": sheet_name,
            "row_number": row_number,
            "raw_row": list(raw_row),
        },
        ensure_ascii=False,
        sort_keys=True,
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def _header_match_score(row: Sequence[Any]) -> tuple[int, dict[str, int]]:
    mapping: dict[str, int] = {}
    score = 0
    for idx, cell in enumerate(row):
        normalized = normalize_header_name(cell)
        if not normalized:
            continue
        for field, aliases in HEADER_ALIASES.items():
            if field in mapping:
                continue
            if any(normalized == alias or alias in normalized or normalized in alias for alias in aliases):
                mapping[field] = idx
                score += HEADER_WEIGHTS.get(field, 1)
                break
    if "supply_quantity" not in mapping:
        return 0, {}
    if not any(key in mapping for key in ("nm_id", "barcode", "vendor_code", "product_name")):
        return 0, {}
    return score, mapping


def detect_header_row(rows: Sequence[Sequence[Any]]) -> tuple[int | None, dict[str, int]]:
    best_index: int | None = None
    best_mapping: dict[str, int] = {}
    best_score = 0
    for idx, row in enumerate(rows[:MAX_HEADER_SCAN_ROWS]):
        score, mapping = _header_match_score(row)
        if score > best_score:
            best_index = idx
            best_mapping = mapping
            best_score = score
    return best_index, best_mapping


def _cell(row: Sequence[Any], index: int | None) -> Any:
    if index is None or index >= len(row):
        return None
    return row[index]


def parse_supply_sheet(
    *,
    google_file_id: str,
    google_file_name: str,
    sheet_name: str,
    rows: Sequence[Sequence[Any]],
) -> dict[str, Any]:
    header_idx, mapping = detect_header_row(rows)
    detected_warehouse = detect_warehouse_name(google_file_name, sheet_name)
    if header_idx is None:
        return {
            "raw_rows_count": len(rows),
            "parsed_rows": [],
            "warnings": [f"{google_file_name}/{sheet_name}: header row not found"],
            "detected_warehouse": detected_warehouse,
        }

    parsed_rows: list[dict[str, Any]] = []
    warnings: list[str] = []
    header_signature = [normalize_header_name(cell) for cell in rows[header_idx]]

    for row_number, row in enumerate(rows[header_idx + 1 :], start=header_idx + 2):
        if not any(str(cell or "").strip() for cell in row):
            continue

        row_signature = [normalize_header_name(cell) for cell in row[: len(header_signature)]]
        if row_signature == header_signature:
            continue

        nm_id = normalize_nm_id(_cell(row, mapping.get("nm_id")))
        barcode = normalize_barcode(_cell(row, mapping.get("barcode")))
        vendor_code = normalize_vendor_code(_cell(row, mapping.get("vendor_code")))
        product_name = normalize_text(_cell(row, mapping.get("product_name")))
        quantity = parse_supply_quantity(_cell(row, mapping.get("supply_quantity")))
        comment = normalize_text(_cell(row, mapping.get("comment")))
        warehouse_name = normalize_text(_cell(row, mapping.get("warehouse_name"))) or detected_warehouse

        if quantity is None and not any([nm_id, barcode, vendor_code, product_name]):
            continue
        if quantity is None:
            warnings.append(f"{google_file_name}/{sheet_name} row {row_number}: quantity not found")
            continue
        if nm_id is None and not barcode and not vendor_code and not product_name:
            warnings.append(f"{google_file_name}/{sheet_name} row {row_number}: no identifier columns found")
            continue

        parsed_rows.append(
            {
                "google_file_id": google_file_id,
                "google_file_name": google_file_name,
                "sheet_name": sheet_name,
                "row_number": row_number,
                "warehouse_name": warehouse_name,
                "nm_id": nm_id,
                "barcode": barcode,
                "vendor_code": vendor_code,
                "product_name": product_name,
                "supply_quantity": quantity,
                "comment": comment,
                "raw_payload": {"row": list(row), "mapping": mapping},
                "row_hash": build_row_hash(
                    google_file_id=google_file_id,
                    sheet_name=sheet_name,
                    row_number=row_number,
                    raw_row=row,
                ),
                "synced_at": datetime.now(timezone.utc),
            }
        )

    return {
        "raw_rows_count": len(rows),
        "parsed_rows": parsed_rows,
        "warnings": warnings,
        "detected_warehouse": detected_warehouse,
    }


def _annotate_file_item(file_item: dict[str, Any]) -> dict[str, Any]:
    annotated = dict(file_item)
    reason = get_unsupported_supply_reason(file_item)
    annotated["supported"] = reason is None
    annotated["unsupported_reason"] = reason
    return annotated


def _classify_files(file_items: Sequence[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    annotated = [_annotate_file_item(item) for item in file_items]
    supported = [item for item in annotated if item["supported"]]
    unsupported = [item for item in annotated if not item["supported"]]
    return annotated, supported, unsupported


def _build_files_found_zero_reason(diagnostics: dict[str, Any]) -> str:
    if not diagnostics.get("folder_visible"):
        return "service account does not have access to folder metadata via files.get"

    direct_children = diagnostics.get("direct_children") or []
    nested_flat = [child for children in (diagnostics.get("nested_children") or {}).values() for child in children]
    direct_subfolders = [item for item in direct_children if item.get("mimeType") == GOOGLE_FOLDER_MIME_TYPE]

    if diagnostics.get("direct_supported_files_count"):
        return "supported supply files are present in the folder; supported_files_count should not be zero"
    if diagnostics.get("nested_supported_files_count") and direct_subfolders:
        return "nested subfolders contain supported supply files, while current sync scans only direct children of folder_id"
    if direct_subfolders and not nested_flat:
        return "folder contains only subfolders and no direct files"
    if direct_children:
        return "folder contains files, but none are in supported supply formats"
    return "folder is visible, but Drive returned no direct children for this folder_id"


def build_wb_supplies_drive_diagnostics(
    *,
    folder_id: str | None = None,
    drive_client: GoogleDriveClient | None = None,
) -> dict[str, Any]:
    resolved_folder_id = folder_id or settings.wb_supplies_google_drive_folder_id
    if not resolved_folder_id:
        raise ValueError("WB_SUPPLIES_GOOGLE_DRIVE_FOLDER_ID is not configured.")

    drive_client = drive_client or GoogleDriveClient()
    raw = drive_client.audit_folder_access(resolved_folder_id)
    direct_children = raw.get("direct_children") or []
    subfolders = raw.get("subfolders") or []
    nested_children = raw.get("nested_children") or {}
    nested_flat = [child for children in nested_children.values() for child in children]

    direct_annotated, direct_supported, direct_unsupported = _classify_files(direct_children)
    nested_annotated_map: dict[str, list[dict[str, Any]]] = {}
    nested_supported_count = 0
    nested_unsupported_count = 0
    for subfolder_id, children in nested_children.items():
        annotated, supported, unsupported = _classify_files(children)
        nested_annotated_map[subfolder_id] = annotated
        nested_supported_count += len(supported)
        nested_unsupported_count += len(unsupported)

    diagnostics = {
        "folder_id": resolved_folder_id,
        "folder_visible": bool(raw.get("folder_visible")),
        "folder_metadata": raw.get("folder_metadata"),
        "folder_error": raw.get("folder_error"),
        "direct_children_count": len(direct_children),
        "direct_children": direct_annotated,
        "subfolders_count": len(subfolders),
        "subfolders": subfolders,
        "nested_children_count": len(nested_flat),
        "nested_children": nested_annotated_map,
        "direct_google_sheets_count": sum(1 for item in direct_children if item.get("mimeType") == GOOGLE_SHEETS_MIME_TYPE),
        "direct_excel_count": sum(1 for item in direct_children if item.get("mimeType") in MS_EXCEL_MIME_TYPES),
        "direct_supported_files_count": len(direct_supported),
        "direct_unsupported_files_count": len(direct_unsupported),
        "nested_supported_files_count": nested_supported_count,
        "nested_unsupported_files_count": nested_unsupported_count,
        "unsupported_files": [
            {
                "id": item.get("id"),
                "name": item.get("name"),
                "mimeType": item.get("mimeType"),
                "reason": item.get("unsupported_reason"),
                "webViewLink": item.get("webViewLink"),
            }
            for item in direct_unsupported
        ],
    }
    diagnostics["files_found_zero_reason"] = _build_files_found_zero_reason(diagnostics)
    return diagnostics


def _default_sheets_client() -> GoogleSheetsClient:
    return GoogleSheetsClient(
        credentials_path=settings.google_application_credentials,
        scopes=READ_ONLY_DRIVE_SCOPES,
    )


def _build_file_summary(file_meta: dict[str, Any], workbook: ParsedWorkbook | None = None) -> dict[str, Any]:
    summary = {
        "google_file_id": str(file_meta.get("id") or ""),
        "google_file_name": str(file_meta.get("name") or file_meta.get("id") or ""),
        "mimeType": file_meta.get("mimeType"),
        "effective_file_id": str(file_meta.get("id") or ""),
        "effective_file_name": str(file_meta.get("name") or file_meta.get("id") or ""),
        "effective_mimeType": file_meta.get("effectiveMimeType"),
        "raw_rows_count": 0,
        "parsed_rows_count": 0,
        "warnings": [],
        "sheet_summaries": [],
        "status": "OK",
    }
    if workbook is not None:
        summary["effective_file_id"] = workbook.effective_file_id
        summary["effective_file_name"] = workbook.effective_file_name
        summary["effective_mimeType"] = workbook.effective_mime_type
        summary["warnings"].extend(workbook.warnings)
    return summary


def sync_wb_supplies_from_google_drive(
    *,
    folder_id: str | None = None,
    write_db: bool = True,
    drive_client: GoogleDriveClient | None = None,
    sheets_client: GoogleSheetsClient | None = None,
) -> dict[str, Any]:
    resolved_folder_id = folder_id or settings.wb_supplies_google_drive_folder_id
    if not resolved_folder_id:
        raise ValueError("WB_SUPPLIES_GOOGLE_DRIVE_FOLDER_ID is not configured.")

    drive_client = drive_client or GoogleDriveClient()
    sheets_client = sheets_client or _default_sheets_client()
    all_files = drive_client.list_folder_files(resolved_folder_id, include_all_supported=True)
    annotated_files, supported_files, unsupported_files = _classify_files(all_files)
    drive_diagnostics = build_wb_supplies_drive_diagnostics(folder_id=resolved_folder_id, drive_client=drive_client)

    summary = {
        "folder_id_configured": True,
        "files_total_in_folder": len(all_files),
        "supported_files_count": len(supported_files),
        "unsupported_files_count": len(unsupported_files),
        "files_found": len(supported_files),
        "files_processed": 0,
        "files_failed": 0,
        "total_raw_rows": 0,
        "total_parsed_rows": 0,
        "warehouses_detected": [],
        "unsupported_files": [
            {
                "google_file_id": item.get("id"),
                "google_file_name": item.get("name"),
                "mimeType": item.get("mimeType"),
                "reason": item.get("unsupported_reason"),
                "webViewLink": item.get("webViewLink"),
            }
            for item in unsupported_files
        ],
        "all_files": annotated_files,
        "file_summaries": [],
        "drive_diagnostics": drive_diagnostics,
        "files_found_zero_reason": drive_diagnostics.get("files_found_zero_reason") if not supported_files else None,
    }
    detected_warehouses: set[str] = set()

    for file_meta in supported_files:
        file_id = str(file_meta.get("id") or "")
        file_name = str(file_meta.get("name") or file_id)
        file_summary = _build_file_summary(file_meta)
        try:
            workbook = read_supply_file(
                file_meta,
                drive_client=drive_client,
                sheets_client=sheets_client,
                header_detector=detect_header_row,
            )
            file_summary = _build_file_summary(file_meta, workbook)
            parsed_rows: list[dict[str, Any]] = []
            file_detected_warehouses: set[str] = set()

            for worksheet in workbook.worksheets:
                parsed_sheet = parse_supply_sheet(
                    google_file_id=file_id,
                    google_file_name=file_name,
                    sheet_name=worksheet.sheet_name,
                    rows=worksheet.rows,
                )
                file_summary["raw_rows_count"] += parsed_sheet["raw_rows_count"]
                file_summary["parsed_rows_count"] += len(parsed_sheet["parsed_rows"])
                file_summary["warnings"].extend(parsed_sheet["warnings"])
                parsed_rows.extend(parsed_sheet["parsed_rows"])
                if parsed_sheet["detected_warehouse"]:
                    detected_warehouses.add(parsed_sheet["detected_warehouse"])
                    file_detected_warehouses.add(parsed_sheet["detected_warehouse"])
                file_summary["sheet_summaries"].append(
                    {
                        "sheet_name": worksheet.sheet_name,
                        "raw_rows_count": worksheet.raw_rows_count,
                        "parsed_rows_count": len(parsed_sheet["parsed_rows"]),
                        "detected_header_candidates": worksheet.detected_header_candidates,
                        "preview_rows": worksheet.preview_rows,
                        "warnings": parsed_sheet["warnings"],
                    }
                )

            file_summary["status"] = "OK" if file_summary["parsed_rows_count"] > 0 else "PARTIAL"
            summary["files_processed"] += 1
            summary["total_raw_rows"] += file_summary["raw_rows_count"]
            summary["total_parsed_rows"] += file_summary["parsed_rows_count"]

            if write_db:
                with session_scope() as session:
                    if parsed_rows:
                        replace_wb_supply_file_rows(session, file_id, parsed_rows)
                    upsert_wb_supply_source_file(
                        session,
                        {
                            "google_file_id": file_id,
                            "google_file_name": file_name,
                            "google_modified_time": parse_google_datetime(file_meta.get("modifiedTime")),
                            "detected_warehouse": next(iter(file_detected_warehouses), None),
                            "raw_rows_count": file_summary["raw_rows_count"],
                            "parsed_rows_count": file_summary["parsed_rows_count"],
                            "last_synced_at": datetime.now(timezone.utc),
                            "last_status": file_summary["status"],
                            "last_error": "; ".join(file_summary["warnings"][:5]) or None,
                        },
                    )
        except Exception as exc:
            summary["files_failed"] += 1
            file_summary["status"] = "FAIL"
            file_summary["error"] = str(exc)
            logger.warning("WB supplies file sync failed for %s: %s", file_name, exc)
            if write_db:
                with session_scope() as session:
                    upsert_wb_supply_source_file(
                        session,
                        {
                            "google_file_id": file_id,
                            "google_file_name": file_name,
                            "google_modified_time": parse_google_datetime(file_meta.get("modifiedTime")),
                            "detected_warehouse": detect_warehouse_name(file_name),
                            "raw_rows_count": file_summary["raw_rows_count"],
                            "parsed_rows_count": file_summary["parsed_rows_count"],
                            "last_synced_at": datetime.now(timezone.utc),
                            "last_status": "FAIL",
                            "last_error": str(exc),
                        },
                    )
        summary["file_summaries"].append(file_summary)

    summary["warehouses_detected"] = sorted(detected_warehouses)
    logger.info(
        "WB supplies sync finished: files_total_in_folder=%s supported_files_count=%s unsupported_files_count=%s files_processed=%s files_failed=%s total_raw_rows=%s total_parsed_rows=%s warehouses=%s",
        summary["files_total_in_folder"],
        summary["supported_files_count"],
        summary["unsupported_files_count"],
        summary["files_processed"],
        summary["files_failed"],
        summary["total_raw_rows"],
        summary["total_parsed_rows"],
        ", ".join(summary["warehouses_detected"]),
    )
    return summary


def build_wb_supplies_audit_report(summary: dict[str, Any]) -> str:
    diagnostics = summary.get("drive_diagnostics") or {}
    lines = [
        "# WB Supplies Google Drive Audit",
        "",
        f"- files_total_in_folder: {summary.get('files_total_in_folder', 0)}",
        f"- supported_files_count: {summary.get('supported_files_count', 0)}",
        f"- unsupported_files_count: {summary.get('unsupported_files_count', 0)}",
        f"- files_processed: {summary.get('files_processed', 0)}",
        f"- files_failed: {summary.get('files_failed', 0)}",
        f"- total_raw_rows: {summary.get('total_raw_rows', 0)}",
        f"- total_parsed_rows: {summary.get('total_parsed_rows', 0)}",
        f"- warehouses_detected: {', '.join(summary.get('warehouses_detected', [])) or 'n/a'}",
        f"- files_found_zero_reason: {summary.get('files_found_zero_reason') or 'n/a'}",
        "",
        "## Folder Access",
        "",
        f"- folder_visible: {diagnostics.get('folder_visible')}",
        f"- folder_error: {diagnostics.get('folder_error') or 'n/a'}",
        f"- direct_children_count: {diagnostics.get('direct_children_count', 0)}",
        f"- direct_supported_files_count: {diagnostics.get('direct_supported_files_count', 0)}",
        f"- direct_unsupported_files_count: {diagnostics.get('direct_unsupported_files_count', 0)}",
        f"- subfolders_count: {diagnostics.get('subfolders_count', 0)}",
        f"- nested_children_count: {diagnostics.get('nested_children_count', 0)}",
        f"- nested_supported_files_count: {diagnostics.get('nested_supported_files_count', 0)}",
        f"- nested_unsupported_files_count: {diagnostics.get('nested_unsupported_files_count', 0)}",
        "",
        "## Folder Metadata",
        "",
        json.dumps(diagnostics.get("folder_metadata"), ensure_ascii=False, indent=2, default=str) if diagnostics.get("folder_metadata") else "null",
        "",
        "## Direct Children (raw list, no mimeType filter)",
        "",
        json.dumps(diagnostics.get("direct_children") or [], ensure_ascii=False, indent=2, default=str),
        "",
        "## Unsupported Direct Files",
        "",
        json.dumps(diagnostics.get("unsupported_files") or [], ensure_ascii=False, indent=2, default=str),
        "",
        "## Nested Subfolders",
        "",
        json.dumps(diagnostics.get("subfolders") or [], ensure_ascii=False, indent=2, default=str),
        "",
        "## Nested Children",
        "",
        json.dumps(diagnostics.get("nested_children") or {}, ensure_ascii=False, indent=2, default=str),
        "",
        "## Files",
        "",
    ]
    for file_summary in summary.get("file_summaries", []):
        lines.append(f"### {file_summary.get('google_file_name', 'unknown')}")
        lines.append(f"- status: {file_summary.get('status')}")
        lines.append(f"- mimeType: {file_summary.get('mimeType') or 'n/a'}")
        lines.append(f"- effective_mimeType: {file_summary.get('effective_mimeType') or 'n/a'}")
        lines.append(f"- raw_rows_count: {file_summary.get('raw_rows_count', 0)}")
        lines.append(f"- parsed_rows_count: {file_summary.get('parsed_rows_count', 0)}")
        warnings = file_summary.get("warnings") or []
        if warnings:
            lines.append("- warnings:")
            lines.extend([f"  - {warning}" for warning in warnings[:5]])
        if file_summary.get("error"):
            lines.append(f"- error: {file_summary['error']}")
        for sheet_summary in file_summary.get("sheet_summaries") or []:
            lines.append(f"- sheet: {sheet_summary.get('sheet_name')}")
            lines.append(f"  - raw_rows_count: {sheet_summary.get('raw_rows_count', 0)}")
            lines.append(f"  - parsed_rows_count: {sheet_summary.get('parsed_rows_count', 0)}")
            lines.append(
                "  - detected_header_candidates: "
                + json.dumps(sheet_summary.get("detected_header_candidates") or [], ensure_ascii=False, default=str)
            )
            lines.append(
                "  - preview_rows: "
                + json.dumps(sheet_summary.get("preview_rows") or [], ensure_ascii=False, default=str)
            )
        lines.append("")
    return "\n".join(lines).strip() + "\n"