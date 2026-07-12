from __future__ import annotations

import io
import json
from pathlib import Path
from typing import Any, Optional

from src.config.settings import settings
from src.utils.logger import get_logger

GOOGLE_SHEETS_MIME_TYPE = "application/vnd.google-apps.spreadsheet"
GOOGLE_FOLDER_MIME_TYPE = "application/vnd.google-apps.folder"
GOOGLE_SHORTCUT_MIME_TYPE = "application/vnd.google-apps.shortcut"
CSV_MIME_TYPES = {
    "text/csv",
    "application/csv",
}
MS_EXCEL_MIME_TYPES = {
    "application/vnd.ms-excel",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
    "application/vnd.openxmlformats-officedocument.spreadsheetml.template",
    "application/vnd.ms-excel.sheet.macroenabled.12",
}
SUPPORTED_SUPPLY_MIME_TYPES = {GOOGLE_SHEETS_MIME_TYPE, *CSV_MIME_TYPES, *MS_EXCEL_MIME_TYPES}
READ_ONLY_DRIVE_SCOPES = [
    "https://www.googleapis.com/auth/drive.readonly",
    "https://www.googleapis.com/auth/spreadsheets.readonly",
]


def get_effective_mime_type(file_item: dict[str, Any]) -> str | None:
    mime_type = file_item.get("mimeType")
    if mime_type == GOOGLE_SHORTCUT_MIME_TYPE:
        shortcut_details = file_item.get("shortcutDetails") or {}
        return shortcut_details.get("targetMimeType")
    return mime_type


def get_unsupported_supply_reason(file_item: dict[str, Any]) -> str | None:
    mime_type = file_item.get("mimeType")
    if mime_type == GOOGLE_FOLDER_MIME_TYPE:
        return "folder is not a supply file"
    if mime_type == GOOGLE_SHORTCUT_MIME_TYPE:
        shortcut_details = file_item.get("shortcutDetails") or {}
        target_id = shortcut_details.get("targetId")
        target_mime = shortcut_details.get("targetMimeType")
        if not target_id:
            return "shortcut targetId is missing"
        if target_mime not in SUPPORTED_SUPPLY_MIME_TYPES:
            return f"shortcut target mimeType is unsupported: {target_mime or 'unknown'}"
        return None

    effective_mime_type = get_effective_mime_type(file_item)
    if effective_mime_type in SUPPORTED_SUPPLY_MIME_TYPES:
        return None
    return f"unsupported mimeType: {effective_mime_type or mime_type or 'unknown'}"


def is_supported_supply_file(file_item: dict[str, Any]) -> bool:
    return get_unsupported_supply_reason(file_item) is None


class GoogleDriveClient:
    def __init__(
        self,
        *,
        credentials_path: str | None = None,
        service_account_json: str | None = None,
        scopes: list[str] | None = None,
    ) -> None:
        self.logger = get_logger("google_drive_client")
        self.credentials_path = credentials_path or settings.google_application_credentials
        self.service_account_json = service_account_json or settings.google_service_account_json
        self.scopes = scopes or READ_ONLY_DRIVE_SCOPES
        self._credentials = None
        self._service = None

    def _get_credentials(self):
        if self._credentials is not None:
            return self._credentials

        if self.service_account_json:
            info = json.loads(self.service_account_json)
            from google.oauth2 import service_account

            self._credentials = service_account.Credentials.from_service_account_info(
                info,
                scopes=self.scopes,
            )
            return self._credentials

        creds_path = Path(self.credentials_path) if self.credentials_path else None
        if creds_path and creds_path.exists():
            from google.oauth2 import service_account

            self._credentials = service_account.Credentials.from_service_account_file(
                str(creds_path),
                scopes=self.scopes,
            )
            return self._credentials

        raise RuntimeError("Google service account credentials are not configured.")

    def _get_service(self):
        if self._service is None:
            from googleapiclient.discovery import build

            credentials = self._get_credentials()
            self._service = build("drive", "v3", credentials=credentials)
        return self._service

    @staticmethod
    def _normalize_file_item(item: dict[str, Any]) -> dict[str, Any]:
        shortcut_details = item.get("shortcutDetails") or None
        size_raw = item.get("size")
        try:
            size_value = int(size_raw) if size_raw is not None else None
        except (TypeError, ValueError):
            size_value = None
        normalized = {
            "id": item.get("id"),
            "name": item.get("name"),
            "mimeType": item.get("mimeType"),
            "parents": list(item.get("parents") or []),
            "trashed": bool(item.get("trashed", False)),
            "modifiedTime": item.get("modifiedTime"),
            "size": size_value,
            "webViewLink": item.get("webViewLink"),
            "shortcutDetails": shortcut_details,
        }
        normalized["effectiveMimeType"] = get_effective_mime_type(normalized)
        return normalized

    def _list_files(self, *, query: str, page_size: int = 100) -> list[dict[str, Any]]:
        service = self._get_service()
        results: list[dict[str, Any]] = []
        page_token: Optional[str] = None
        fields = (
            "nextPageToken, "
            "files(id, name, mimeType, parents, trashed, modifiedTime, size, webViewLink, "
            "shortcutDetails(targetId,targetMimeType,targetResourceKey))"
        )

        while True:
            response = (
                service.files()
                .list(
                    q=query,
                    fields=fields,
                    pageSize=page_size,
                    pageToken=page_token,
                    orderBy="name",
                    supportsAllDrives=True,
                    includeItemsFromAllDrives=True,
                )
                .execute()
            )
            results.extend(self._normalize_file_item(item) for item in response.get("files", []))
            page_token = response.get("nextPageToken")
            if not page_token:
                break

        return results

    def get_file_metadata(self, file_id: str) -> dict[str, Any]:
        if not file_id:
            raise ValueError("Google Drive file id is not configured.")

        service = self._get_service()
        response = (
            service.files()
            .get(
                fileId=file_id,
                fields=(
                    "id, name, mimeType, parents, trashed, modifiedTime, size, webViewLink, "
                    "shortcutDetails(targetId,targetMimeType,targetResourceKey)"
                ),
                supportsAllDrives=True,
            )
            .execute()
        )
        return self._normalize_file_item(response)

    def list_folder_children(self, folder_id: str, *, mime_type: str | None = None) -> list[dict[str, Any]]:
        if not folder_id:
            raise ValueError("Google Drive folder id is not configured.")

        query = f"'{folder_id}' in parents and trashed = false"
        if mime_type:
            query += f" and mimeType = '{mime_type}'"
        return self._list_files(query=query)

    def list_folder_files(self, folder_id: str, include_all_supported: bool = True) -> list[dict[str, Any]]:
        files = self.list_folder_children(folder_id)
        if include_all_supported:
            return files
        return [file_item for file_item in files if is_supported_supply_file(file_item)]

    def list_google_sheets_files(self, folder_id: str) -> list[dict[str, Any]]:
        return [file_item for file_item in self.list_folder_children(folder_id) if file_item.get("mimeType") == GOOGLE_SHEETS_MIME_TYPE]

    def resolve_shortcut_target(self, file_item: dict[str, Any]) -> dict[str, Any]:
        if file_item.get("mimeType") != GOOGLE_SHORTCUT_MIME_TYPE:
            return file_item

        shortcut_details = file_item.get("shortcutDetails") or {}
        target_id = shortcut_details.get("targetId")
        if not target_id:
            raise RuntimeError("Shortcut targetId is missing.")

        target_metadata = self.get_file_metadata(target_id)
        target_metadata["shortcutSource"] = {
            "id": file_item.get("id"),
            "name": file_item.get("name"),
            "mimeType": file_item.get("mimeType"),
            "shortcutDetails": shortcut_details,
        }
        return target_metadata

    def download_file_bytes(self, file_id: str) -> bytes:
        if not file_id:
            raise ValueError("Google Drive file id is not configured.")

        from googleapiclient.http import MediaIoBaseDownload

        service = self._get_service()
        request = service.files().get_media(fileId=file_id)
        buffer = io.BytesIO()
        downloader = MediaIoBaseDownload(buffer, request)
        done = False
        while not done:
            _, done = downloader.next_chunk()
        return buffer.getvalue()

    def audit_folder_access(self, folder_id: str) -> dict[str, Any]:
        diagnostics: dict[str, Any] = {
            "folder_id": folder_id,
            "folder_visible": False,
            "folder_metadata": None,
            "folder_error": None,
            "direct_children": [],
            "subfolders": [],
            "nested_children": {},
        }

        try:
            diagnostics["folder_metadata"] = self.get_file_metadata(folder_id)
            diagnostics["folder_visible"] = True
        except Exception as exc:
            diagnostics["folder_error"] = str(exc)
            return diagnostics

        direct_children = self.list_folder_files(folder_id, include_all_supported=True)
        diagnostics["direct_children"] = direct_children
        subfolders = [item for item in direct_children if item.get("mimeType") == GOOGLE_FOLDER_MIME_TYPE]
        diagnostics["subfolders"] = subfolders

        nested_children: dict[str, list[dict[str, Any]]] = {}
        for folder in subfolders:
            child_folder_id = str(folder.get("id") or "")
            if not child_folder_id:
                continue
            nested_children[child_folder_id] = self.list_folder_files(child_folder_id, include_all_supported=True)
        diagnostics["nested_children"] = nested_children
        return diagnostics
