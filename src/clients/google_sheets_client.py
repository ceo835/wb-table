"""
Клиент для Google Sheets API.

Использует Google Sheets API v4 для работы с таблицами.
Требуется файл credentials.json с сервисными данными.
"""
import os
import sys
from pathlib import Path
from typing import Any, Dict, List, Optional

# Добавляем src в path для корректного импорта
src_path = Path(__file__).parent.parent
sys.path.insert(0, str(src_path))

from config.settings import GOOGLE_APPLICATION_CREDENTIALS, GOOGLE_SHEET_ID
from utils.logger import get_logger


class GoogleSheetsClient:
    """Клиент для работы с Google Sheets."""

    def __init__(
        self,
        credentials_path: str = None,
        spreadsheet_id: str = None,
    ):
        """
        Инициализировать клиент.

        Args:
            credentials_path: Путь к файлу credentials.json
            spreadsheet_id: ID таблицы (опционально)
        """
        self.logger = get_logger("google_sheets_client")
        self.credentials_path = credentials_path or GOOGLE_APPLICATION_CREDENTIALS
        self.spreadsheet_id = spreadsheet_id or GOOGLE_SHEET_ID
        self._service = None
        self._credentials = None

    def _get_credentials(self):
        """Получить credentials для авторизации."""
        if self._credentials is None:
            try:
                from google.oauth2 import service_account
                from googleapiclient.discovery import build
                
                SCOPES = [
                    "https://www.googleapis.com/auth/spreadsheets",
                    "https://www.googleapis.com/auth/drive",
                ]
                
                creds_path = Path(self.credentials_path) if self.credentials_path else None
                
                if not creds_path or not creds_path.exists():
                    self.logger.warning(
                        f"Credentials file not found: {self.credentials_path}. "
                        "Google Sheets functionality will be limited."
                    )
                    return None
                
                self._credentials = service_account.Credentials.from_service_account_file(
                    str(creds_path), scopes=SCOPES
                )
                self._service = build("sheets", "v4", credentials=self._credentials)
                
            except ImportError:
                self.logger.warning(
                    "Google API libraries not installed. "
                    "Install with: pip install google-api-python-client google-auth-httplib2 google-auth-oauthlib"
                )
                return None
            except Exception as e:
                self.logger.error(f"Failed to load credentials: {e}")
                return None
        
        return self._credentials

    def health_check(self) -> bool:
        """
        Проверить доступность API.

        Returns:
            True если API доступен
        """
        try:
            if self._get_credentials() is None:
                return False
            
            # Пробуем получить метаданные таблицы
            if self.spreadsheet_id:
                self.get_spreadsheet_info()
            return True
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            return False

    def create_spreadsheet(
        self,
        title: str,
        worksheet_titles: Optional[List[str]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Создать новую таблицу.

        Read-write метод для создания новой Google таблицы.

        Args:
            title: Название таблицы
            worksheet_titles: Названия листов (опционально)

        Returns:
            Информация о созданной таблице или None при ошибке
        """
        try:
            from googleapiclient.discovery import build
            
            if self._get_credentials() is None:
                return None
            
            service = build("sheets", "v4", credentials=self._credentials)
            
            spreadsheet_body = {
                "properties": {"title": title},
            }
            
            if worksheet_titles:
                sheets = []
                for i, ws_title in enumerate(worksheet_titles):
                    sheet = {
                        "properties": {
                            "title": ws_title,
                            "index": i,
                        }
                    }
                    sheets.append(sheet)
                spreadsheet_body["sheets"] = sheets
            
            request = service.spreadsheets().create(body=spreadsheet_body)
            response = request.execute()
            
            self.logger.info(f"Created spreadsheet '{title}' with ID: {response['spreadsheetId']}")
            return response
            
        except Exception as e:
            self.logger.error(f"Failed to create spreadsheet: {e}")
            return None

    def create_or_clear_worksheet(
        self,
        spreadsheet_id: str,
        worksheet_title: str,
    ) -> Optional[bool]:
        """
        Создать новый лист или очистить существующий.

        Args:
            spreadsheet_id: ID таблицы
            worksheet_title: Название листа

        Returns:
            True если успешно, None при ошибке
        """
        try:
            from googleapiclient.discovery import build
            from googleapiclient.errors import HttpError
            
            if self._get_credentials() is None:
                return None
            
            service = build("sheets", "v4", credentials=self._credentials)
            
            # Получаем информацию о таблице
            spreadsheet = service.spreadsheets().get(
                spreadsheetId=spreadsheet_id
            ).execute()
            
            # Проверяем существует ли лист
            sheet_id = None
            for sheet in spreadsheet.get("sheets", []):
                if sheet["properties"]["title"] == worksheet_title:
                    sheet_id = sheet["properties"]["sheetId"]
                    break
            
            if sheet_id is not None:
                # Лист существует - очищаем его
                clear_request = service.spreadsheets().values().clear(
                    spreadsheetId=spreadsheet_id,
                    range=f"{worksheet_title}!A:Z",
                )
                clear_request.execute()
                self.logger.info(f"Cleared existing worksheet '{worksheet_title}'")
            else:
                # Лист не существует - создаем
                body = {
                    "requests": [
                        {
                            "addSheet": {
                                "properties": {
                                    "title": worksheet_title,
                                }
                            }
                        }
                    ]
                }
                service.spreadsheets().batchUpdate(
                    spreadsheetId=spreadsheet_id,
                    body=body,
                ).execute()
                self.logger.info(f"Created new worksheet '{worksheet_title}'")
            
            return True
            
        except Exception as e:
            # Handle both HttpError and other exceptions
            error_name = type(e).__name__
            self.logger.error(f"Google API error ({error_name}): {e}")
            return None

    def ensure_worksheet(
        self,
        spreadsheet_id: str,
        worksheet_title: str,
    ) -> Optional[bool]:
        """
        Ensure worksheet exists without clearing any data.

        Args:
            spreadsheet_id: Spreadsheet ID
            worksheet_title: Worksheet title

        Returns:
            True if worksheet exists or was created, None on error
        """
        try:
            from googleapiclient.discovery import build

            if self._get_credentials() is None:
                return None

            service = build("sheets", "v4", credentials=self._credentials)
            spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()

            for sheet in spreadsheet.get("sheets", []):
                if sheet["properties"]["title"] == worksheet_title:
                    self.logger.info(f"Worksheet '{worksheet_title}' already exists")
                    return True

            body = {
                "requests": [
                    {
                        "addSheet": {
                            "properties": {
                                "title": worksheet_title,
                            }
                        }
                    }
                ]
            }
            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body=body,
            ).execute()
            self.logger.info(f"Created worksheet '{worksheet_title}' without clearing existing sheets")
            return True
        except Exception as e:
            error_name = type(e).__name__
            self.logger.error(f"Google API error ({error_name}): {e}")
            return None

    def get_worksheet_titles(
        self,
        spreadsheet_id: str,
    ) -> Optional[List[str]]:
        """
        Get worksheet titles for a spreadsheet.

        Args:
            spreadsheet_id: Spreadsheet ID

        Returns:
            List of worksheet titles or None on error
        """
        try:
            from googleapiclient.discovery import build

            if self._get_credentials() is None:
                return None

            service = build("sheets", "v4", credentials=self._credentials)
            spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            return [sheet["properties"]["title"] for sheet in spreadsheet.get("sheets", [])]
        except Exception as e:
            error_name = type(e).__name__
            self.logger.error(f"Google API error ({error_name}): {e}")
            return None

    def get_header_row(
        self,
        spreadsheet_id: str,
        worksheet_title: str,
    ) -> Optional[List[str]]:
        """
        Read the first row from a worksheet.

        Args:
            spreadsheet_id: Spreadsheet ID
            worksheet_title: Worksheet title

        Returns:
            Header row values or None on error
        """
        values = self.read_range(spreadsheet_id, f"{worksheet_title}!1:1")
        if values is None:
            return None
        return [str(value) for value in values[0]] if values else []

    def update_header_row(
        self,
        spreadsheet_id: str,
        worksheet_title: str,
        headers: List[str],
    ) -> Optional[bool]:
        """
        Update header row only, preserving other rows.

        Args:
            spreadsheet_id: Spreadsheet ID
            worksheet_title: Worksheet title
            headers: Header values for row 1

        Returns:
            True if updated successfully, None on error
        """
        return self.write_rows(
            spreadsheet_id=spreadsheet_id,
            worksheet_title=worksheet_title,
            rows=[headers],
            start_row=1,
            start_col=1,
        )

    def write_dataframe(
        self,
        spreadsheet_id: str,
        worksheet_title: str,
        dataframe,
        start_row: int = 1,
        start_col: int = 1,
        include_header: bool = True,
    ) -> Optional[bool]:
        """
        Записать DataFrame в таблицу.

        Args:
            spreadsheet_id: ID таблицы
            worksheet_title: Название листа
            dataframe: pandas DataFrame для записи
            start_row: Начальная строка (1-based)
            start_col: Начальный столбец (1-based)
            include_header: Включать ли заголовки

        Returns:
            True если успешно, None при ошибке
        """
        try:
            import pandas as pd
            
            if not isinstance(dataframe, pd.DataFrame):
                self.logger.error("Input must be a pandas DataFrame")
                return None
            
            # Конвертируем DataFrame в список списков
            values = []
            if include_header:
                values.append([str(h) for h in dataframe.columns])
            
            for _, row in dataframe.iterrows():
                values.append([str(v) for v in row.values])
            
            return self.write_rows(
                spreadsheet_id=spreadsheet_id,
                worksheet_title=worksheet_title,
                rows=values,
                start_row=start_row,
                start_col=start_col,
            )
            
        except ImportError:
            self.logger.error("pandas not installed. Install with: pip install pandas")
            return None
        except Exception as e:
            self.logger.error(f"Failed to write DataFrame: {e}")
            return None

    def write_rows(
        self,
        spreadsheet_id: str,
        worksheet_title: str,
        rows: List[List[Any]],
        start_row: int = 1,
        start_col: int = 1,
    ) -> Optional[bool]:
        """
        Записать строки в таблицу.

        Args:
            spreadsheet_id: ID таблицы
            worksheet_title: Название листа
            rows: Список строк (список списков)
            start_row: Начальная строка (1-based)
            start_col: Начальный столбец (1-based)

        Returns:
            True если успешно, None при ошибке
        """
        try:
            from googleapiclient.discovery import build
            
            if self._get_credentials() is None:
                return None
            
            service = build("sheets", "v4", credentials=self._credentials)
            
            # Конвертируем колонки из 1-based в буквенные
            start_col_letter = self._col_num_to_letter(start_col)
            range_name = f"{worksheet_title}!{start_col_letter}{start_row}"
            
            body = {
                "values": rows,
            }
            
            request = service.spreadsheets().values().update(
                spreadsheetId=spreadsheet_id,
                range=range_name,
                valueInputOption="USER_ENTERED",
                body=body,
            )
            request.execute()
            
            self.logger.info(
                f"Wrote {len(rows)} rows to {spreadsheet_id}/{worksheet_title}"
            )
            return True
            
        except Exception as e:
            error_name = type(e).__name__
            self.logger.error(f"Google API error ({error_name}): {e}")
            return None

    def clear_range(
        self,
        spreadsheet_id: str,
        range_name: str,
    ) -> Optional[bool]:
        """
        Clear values from a range without deleting the sheet.

        Args:
            spreadsheet_id: Spreadsheet ID
            range_name: Range in A1 notation

        Returns:
            True if cleared successfully, None on error
        """
        try:
            from googleapiclient.discovery import build

            if self._get_credentials() is None:
                return None

            service = build("sheets", "v4", credentials=self._credentials)
            request = service.spreadsheets().values().clear(
                spreadsheetId=spreadsheet_id,
                range=range_name,
            )
            request.execute()
            self.logger.info(f"Cleared range {range_name} in {spreadsheet_id}")
            return True
        except Exception as e:
            error_name = type(e).__name__
            self.logger.error(f"Google API error ({error_name}): {e}")
            return None

    def format_number_ranges(
        self,
        spreadsheet_id: str,
        worksheet_title: str,
        ranges: List[tuple[int, int, int, int]],
        pattern: str = "0.##",
    ) -> Optional[bool]:
        """
        Apply a plain numeric format to one or more ranges without touching values.

        Args:
            spreadsheet_id: Spreadsheet ID
            worksheet_title: Worksheet title
            ranges: List of (start_row, start_col, end_row, end_col) tuples, 1-based and inclusive
            pattern: Google Sheets number format pattern

        Returns:
            True if formatting was applied successfully, None on error
        """
        try:
            from googleapiclient.discovery import build

            if self._get_credentials() is None:
                return None

            service = build("sheets", "v4", credentials=self._credentials)
            spreadsheet = service.spreadsheets().get(spreadsheetId=spreadsheet_id).execute()
            sheet_id = None
            for sheet in spreadsheet.get("sheets", []):
                if sheet.get("properties", {}).get("title") == worksheet_title:
                    sheet_id = sheet["properties"]["sheetId"]
                    break

            if sheet_id is None:
                self.logger.error(f"Worksheet not found: {worksheet_title}")
                return None

            requests = []
            for start_row, start_col, end_row, end_col in ranges:
                requests.append(
                    {
                        "repeatCell": {
                            "range": {
                                "sheetId": sheet_id,
                                "startRowIndex": max(start_row - 1, 0),
                                "endRowIndex": end_row,
                                "startColumnIndex": max(start_col - 1, 0),
                                "endColumnIndex": end_col,
                            },
                            "cell": {
                                "userEnteredFormat": {
                                    "numberFormat": {
                                        "type": "NUMBER",
                                        "pattern": pattern,
                                    }
                                }
                            },
                            "fields": "userEnteredFormat.numberFormat",
                        }
                    }
                )

            if not requests:
                return True

            service.spreadsheets().batchUpdate(
                spreadsheetId=spreadsheet_id,
                body={"requests": requests},
            ).execute()
            self.logger.info(f"Applied numeric format to {worksheet_title} ranges: {ranges}")
            return True
        except Exception as e:
            error_name = type(e).__name__
            self.logger.error(f"Google API error ({error_name}): {e}")
            return None

    def read_range(
        self,
        spreadsheet_id: str,
        range_name: str,
    ) -> Optional[List[List[Any]]]:
        """
        Прочитать данные из диапазона.

        Read-only метод для чтения данных из таблицы.

        Args:
            spreadsheet_id: ID таблицы
            range_name: Диапазон в формате 'Лист!A1:B10'

        Returns:
            Данные в виде списка списков или None при ошибке
        """
        try:
            from googleapiclient.discovery import build
            
            if self._get_credentials() is None:
                return None
            
            service = build("sheets", "v4", credentials=self._credentials)
            
            request = service.spreadsheets().values().get(
                spreadsheetId=spreadsheet_id,
                range=range_name,
            )
            response = request.execute()
            
            return response.get("values", [])
            
        except Exception as e:
            error_name = type(e).__name__
            self.logger.error(f"Google API error ({error_name}): {e}")
            return None

    def get_spreadsheet_info(self) -> Optional[Dict[str, Any]]:
        """
        Получить информацию о таблице.

        Read-only метод для получения метаданных таблицы.

        Returns:
            Информация о таблице или None при ошибке
        """
        try:
            from googleapiclient.discovery import build
            
            if not self.spreadsheet_id:
                self.logger.error("Spreadsheet ID not set")
                return None
            
            if self._get_credentials() is None:
                return None
            
            service = build("sheets", "v4", credentials=self._credentials)
            
            request = service.spreadsheets().get(
                spreadsheetId=self.spreadsheet_id
            )
            response = request.execute()
            
            self.logger.info(f"Got info for spreadsheet: {response.get('properties', {}).get('title')}")
            return response
            
        except Exception as e:
            self.logger.error(f"Failed to get spreadsheet info: {e}")
            return None

    @staticmethod
    def _col_num_to_letter(col_num: int) -> str:
        """
        Конвертировать номер колонки в буквенное обозначение.

        Args:
            col_num: Номер колонки (1-based)

        Returns:
            Буквенное обозначение (A, B, C, ..., AA, AB, ...)
        """
        letters = ""
        while col_num > 0:
            col_num -= 1
            letters = chr(65 + col_num % 26) + letters
            col_num //= 26
        return letters
