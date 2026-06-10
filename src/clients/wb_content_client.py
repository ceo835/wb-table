"""
Клиент для Wildberries Content API.

API документация: https://openapi.wildberries.ru/content/api/ru/index.html
"""
from __future__ import annotations

from typing import Any, Dict, Iterable, List, Optional

from src.clients.base_client import BaseAPIClient
from src.config.settings import WB_TOKEN
from src.utils.logger import get_logger


class WBContentClient(BaseAPIClient):
    """Клиент для работы с Content API Wildberries."""

    BASE_URL = "https://content-api.wildberries.ru"
    CARDS_LIST_ENDPOINT = "/content/v2/get/cards/list"

    def __init__(self, token: str = None):
        token = token or WB_TOKEN
        if not token:
            raise ValueError("WB_TOKEN не найден в переменных окружения")

        super().__init__(
            base_url=self.BASE_URL,
            token=token,
            logger_name="wb_content_client",
        )
        self.logger = get_logger("wb_content_client")

    def _get_default_headers(self) -> Dict[str, str]:
        headers = super()._get_default_headers()
        headers["Authorization"] = self.token
        return headers

    def health_check(self) -> bool:
        try:
            result = self.wb_content_cards_list(limit=1, save_raw=False)
            return result is not None
        except Exception as exc:
            self.logger.error("Health check failed: %s", exc)
            return False

    @staticmethod
    def build_cards_list_payload(
        *,
        limit: int = 100,
        cursor: Optional[Dict[str, Any]] = None,
        text_search: Optional[str] = None,
        fields: Optional[Iterable[str]] = None,
    ) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "settings": {
                "sort": {"ascending": True},
                "cursor": {"limit": max(1, min(int(limit), 100))},
                "filter": {"withPhoto": -1},
            }
        }

        if cursor:
            updated_at = cursor.get("updatedAt")
            nm_id = cursor.get("nmID")
            if updated_at:
                payload["settings"]["cursor"]["updatedAt"] = updated_at
            if nm_id not in (None, ""):
                payload["settings"]["cursor"]["nmID"] = nm_id

        if text_search:
            payload["settings"]["filter"]["textSearch"] = text_search

        fields_list = [field for field in (fields or []) if field]
        if fields_list:
            payload["settings"]["fields"] = fields_list

        return payload

    @staticmethod
    def extract_cards(payload_obj: Dict[str, Any] | None) -> List[Dict[str, Any]]:
        if not isinstance(payload_obj, dict):
            return []

        cards = payload_obj.get("cards")
        if isinstance(cards, list):
            return [item for item in cards if isinstance(item, dict)]

        data = payload_obj.get("data")
        if isinstance(data, dict):
            nested_cards = data.get("cards")
            if isinstance(nested_cards, list):
                return [item for item in nested_cards if isinstance(item, dict)]

        return []

    @staticmethod
    def extract_cursor(payload_obj: Dict[str, Any] | None, *, limit: int) -> Optional[Dict[str, Any]]:
        if not isinstance(payload_obj, dict):
            return None

        cursor = payload_obj.get("cursor")
        if not isinstance(cursor, dict):
            data = payload_obj.get("data")
            if isinstance(data, dict):
                nested_cursor = data.get("cursor")
                if isinstance(nested_cursor, dict):
                    cursor = nested_cursor
        if not isinstance(cursor, dict):
            return None

        updated_at = cursor.get("updatedAt")
        nm_id = cursor.get("nmID")
        if not updated_at or nm_id in (None, ""):
            return None

        return {
            "updatedAt": updated_at,
            "nmID": nm_id,
            "limit": max(1, min(int(limit), 100)),
            "total": cursor.get("total"),
        }

    @staticmethod
    def normalize_card(card: Dict[str, Any] | None) -> Optional[Dict[str, Any]]:
        if not isinstance(card, dict):
            return None

        raw_nm_id = card.get("nmID")
        if raw_nm_id in (None, ""):
            raw_nm_id = card.get("nmId")
        if raw_nm_id in (None, ""):
            return None

        try:
            nm_id = int(raw_nm_id)
        except (TypeError, ValueError):
            return None

        return {
            "nm_id": nm_id,
            "supplier_article": card.get("vendorCode") or card.get("supplierArticle"),
            "title": card.get("title") or card.get("name") or card.get("imtName"),
            "brand": card.get("brand") or card.get("brandName"),
            "subject": card.get("subjectName") or card.get("subject"),
            "sizes": card.get("sizes"),
            "skus": card.get("skus"),
        }

    def wb_content_cards_list(
        self,
        limit: int = 100,
        offset: int = 0,
        cursor: Optional[Dict[str, Any]] = None,
        text_search: Optional[str] = None,
        fields: Optional[List[str]] = None,
        save_raw: bool = False,
    ) -> Optional[Dict[str, Any]]:
        payload = self.build_cards_list_payload(
            limit=limit,
            cursor=cursor,
            text_search=text_search,
            fields=fields,
        )

        if cursor:
            self.logger.info(
                "Fetching cards list: limit=%s, cursor_nmID=%s, cursor_updatedAt=%s",
                payload["settings"]["cursor"].get("limit"),
                payload["settings"]["cursor"].get("nmID"),
                payload["settings"]["cursor"].get("updatedAt"),
            )
        else:
            self.logger.info("Fetching cards list: limit=%s, offset=%s", limit, offset)

        return self.post(self.CARDS_LIST_ENDPOINT, json_data=payload, save_raw=save_raw)

    def fetch_cards_catalog(
        self,
        *,
        limit: int = 100,
        max_pages: int = 100,
        text_search: Optional[str] = None,
        fields: Optional[List[str]] = None,
        save_raw: bool = False,
    ) -> List[Dict[str, Any]]:
        cards: List[Dict[str, Any]] = []
        cursor: Optional[Dict[str, Any]] = None
        pages_read = 0
        seen_cursors: set[tuple[Any, Any]] = set()
        normalized_limit = max(1, min(int(limit), 100))

        while pages_read < max_pages:
            response = self.wb_content_cards_list(
                limit=normalized_limit,
                cursor=cursor,
                text_search=text_search,
                fields=fields,
                save_raw=save_raw,
            )
            batch = self.extract_cards(response)
            cards.extend(batch)
            pages_read += 1

            self.logger.info(
                "Content cards page=%s, batch_cards=%s, total_cards=%s",
                pages_read,
                len(batch),
                len(cards),
            )

            if not batch:
                break
            if len(batch) < normalized_limit:
                break

            next_cursor = self.extract_cursor(response, limit=normalized_limit)
            if next_cursor is None:
                break

            cursor_key = (next_cursor.get("updatedAt"), next_cursor.get("nmID"))
            if cursor_key in seen_cursors:
                self.logger.warning("Stopping Content pagination because cursor repeated: %s", cursor_key)
                break
            seen_cursors.add(cursor_key)
            cursor = next_cursor

        return cards

    def wb_content_get_media(self, nm_id: int) -> Optional[Dict[str, Any]]:
        endpoint = "/content/v2/get/media"
        payload = {"nmIDs": [nm_id]}

        self.logger.info("Fetching media for nm_id=%s", nm_id)
        return self.post(endpoint, json_data=payload)

    def wb_content_get_characteristics(self, nm_ids: List[int]) -> Optional[Dict[str, Any]]:
        endpoint = "/content/v2/get/characteristics"
        payload = {"nmIDs": nm_ids}

        self.logger.info("Fetching characteristics for %s items", len(nm_ids))
        return self.post(endpoint, json_data=payload)
