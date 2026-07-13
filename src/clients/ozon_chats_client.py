from __future__ import annotations

import os
import time
from datetime import UTC, datetime
from typing import Any, Iterable, Mapping, Optional, Sequence

import requests
from requests import Response

from src.clients.base_client import BaseAPIClient
from src.config.settings import settings
from src.utils.logger import get_logger


OZON_API_BASE_URL = "https://api-seller.ozon.ru"
KNOWN_GOOD_READONLY_ENDPOINT = "/v3/product/list"
CHAT_LIST_ENDPOINT = "/v3/chat/list"
CHAT_HISTORY_ENDPOINT = "/v1/chat/history"
FORBIDDEN_CHAT_ENDPOINTS = (
    "/v1/chat/start",
    "/v1/chat/send/message",
    "/v1/chat/send/file",
    "/v2/chat/read",
)
CHAT_ID_CANDIDATES = (
    "chat.chat_id",
    "chat_id",
    "chatId",
    "chatID",
    "dialog_id",
    "dialogId",
    "dialogID",
    "id",
)
FIRST_ACTIVITY_CANDIDATES = (
    "chat.created_at",
    "first_message_at",
    "firstMessageAt",
    "created_at",
    "createdAt",
    "create_time",
    "createTime",
    "created",
)
LAST_ACTIVITY_CANDIDATES = (
    "chat.updated_at",
    "last_message_at",
    "lastMessageAt",
    "updated_at",
    "updatedAt",
    "update_time",
    "updateTime",
    "last_event_at",
    "lastEventAt",
    "last_message.created_at",
    "lastMessage.createdAt",
    "last_message.updated_at",
    "lastMessage.updatedAt",
)
LAST_SENDER_CANDIDATES = (
    "last_sender",
    "lastSender",
    "sender_type",
    "senderType",
    "last_message.sender_type",
    "last_message.senderType",
    "lastMessage.sender_type",
    "lastMessage.senderType",
)
REPLY_CAPABLE_CANDIDATES = (
    "can_reply",
    "canReply",
    "can_send",
    "canSend",
    "reply_sign",
    "replySign",
)
PRODUCT_ID_CANDIDATES = (
    "product_id",
    "productId",
    "sku",
    "sku_id",
    "skuId",
    "offer_id",
    "offerId",
    "item.product_id",
    "item.productId",
)
ORDER_ID_CANDIDATES = (
    "posting_number",
    "postingNumber",
    "order_id",
    "orderId",
    "purchase_id",
    "purchaseId",
    "shipment_id",
    "shipmentId",
)
PAGINATION_KEYS = (
    "limit",
    "offset",
    "cursor",
    "next",
    "hasMore",
    "has_more",
    "page",
    "page_size",
    "pageSize",
    "total",
    "total_count",
)
RATE_LIMIT_HEADER_KEYWORDS = ("rate", "limit", "retry-after")
ROLE_ERROR_SNIPPET = "required role"


def type_name(value: Any) -> str:
    if value is None:
        return "null"
    if isinstance(value, bool):
        return "bool"
    if isinstance(value, int):
        return "int"
    if isinstance(value, float):
        return "float"
    if isinstance(value, str):
        return "str"
    if isinstance(value, list):
        return "list"
    if isinstance(value, Mapping):
        return "object"
    return type(value).__name__


def parse_timestamp(value: Any) -> Optional[datetime]:
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        try:
            if value > 1_000_000_000_000:
                return datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)
            if value > 1_000_000_000:
                return datetime.fromtimestamp(float(value), tz=UTC)
        except (OSError, OverflowError, ValueError):
            return None
    if isinstance(value, str):
        text = value.strip()
        if not text:
            return None
        if text.isdigit():
            return parse_timestamp(int(text))
        try:
            if text.endswith("Z"):
                return datetime.fromisoformat(text.replace("Z", "+00:00")).astimezone(UTC)
            parsed = datetime.fromisoformat(text)
            return parsed.astimezone(UTC) if parsed.tzinfo else parsed.replace(tzinfo=UTC)
        except ValueError:
            return None
    return None


def extract_nested_value(node: Mapping[str, Any], path: str) -> Any:
    current: Any = node
    for part in path.split("."):
        if not isinstance(current, Mapping):
            return None
        current = current.get(part)
        if current is None:
            return None
    return current


def extract_first_value(node: Mapping[str, Any], candidates: Iterable[str]) -> Any:
    for candidate in candidates:
        value = extract_nested_value(node, candidate) if "." in candidate else node.get(candidate)
        if value not in (None, "", [], {}):
            return value
    return None


def discover_top_level_items(payload: Any) -> list[Any]:
    if isinstance(payload, list):
        return payload
    if not isinstance(payload, Mapping):
        return []
    for key in ("result", "items", "data", "chats", "dialogs", "messages", "events", "list"):
        value = payload.get(key)
        if isinstance(value, list):
            return value
        if isinstance(value, Mapping):
            for nested_key in ("items", "list", "rows", "chats", "dialogs", "messages", "events"):
                nested_value = value.get(nested_key)
                if isinstance(nested_value, list):
                    return nested_value
    return []


def infer_pagination(payload: Any) -> dict[str, Any]:
    found: dict[str, Any] = {}

    def walk(node: Any, prefix: str = "") -> None:
        if isinstance(node, Mapping):
            for key, value in node.items():
                path = f"{prefix}.{key}" if prefix else str(key)
                if key in PAGINATION_KEYS:
                    found[path] = value
                if isinstance(value, (dict, list)):
                    walk(value, path)
        elif isinstance(node, list):
            for item in node[:3]:
                if isinstance(item, (dict, list)):
                    walk(item, prefix)

    walk(payload)
    return {
        "keys_found": sorted(found.keys()),
        "values": found,
        "has_pagination_signals": bool(found),
    }


def pick_rate_limit_headers(headers: Mapping[str, str]) -> dict[str, str]:
    result: dict[str, str] = {}
    for key, value in headers.items():
        lowered = key.lower()
        if any(keyword in lowered for keyword in RATE_LIMIT_HEADER_KEYWORDS):
            result[key] = value
    return result


def coerce_int(value: Any) -> Optional[int]:
    try:
        return int(value) if value not in (None, "") else None
    except (TypeError, ValueError):
        return None


def mask_secret(value: Any, *, prefix: int = 4, suffix: int = 2) -> str:
    text = str(value or "").strip()
    if not text:
        return "-"
    if len(text) <= prefix + suffix:
        return f"{text[:1]}...****"
    return f"{text[:prefix]}...{text[-suffix:]}"


class OzonChatsClient(BaseAPIClient):
    """Read-only Ozon chat client limited to confirmed endpoints only."""

    def __init__(
        self,
        client_id: Optional[str] = None,
        api_key: Optional[str] = None,
        base_url: str = OZON_API_BASE_URL,
        timeout: int = 30,
    ) -> None:
        resolved_client_id = (client_id or settings.ozon_client_id or "").strip()
        resolved_api_key = (api_key or settings.ozon_api_key or "").strip()
        super().__init__(base_url=base_url, token=resolved_api_key, logger_name="ozon_chats_client")
        self.client_id = resolved_client_id
        self.api_key = resolved_api_key
        self.timeout = timeout
        self.session = requests.Session()
        self.session.trust_env = False
        self.logger = get_logger("ozon_chats_client")
        self.last_known_good_result: dict[str, Any] | None = None
        self.last_chat_list_result: dict[str, Any] | None = None
        self.last_history_results: list[dict[str, Any]] = []

    def _get_default_headers(self) -> dict[str, str]:
        headers = super()._get_default_headers()
        headers.update(
            {
                "Client-Id": self.client_id,
                "Api-Key": self.api_key,
            }
        )
        return headers

    def has_credentials(self) -> bool:
        return bool(self.client_id and self.api_key)

    def _decode_response_payload(self, response: Response) -> Any:
        if not response.content:
            return {}
        try:
            return response.json()
        except ValueError:
            return {"_raw_text": response.text[:1000]}

    def _ensure_allowed_endpoint(self, endpoint: str) -> None:
        allowed = {
            KNOWN_GOOD_READONLY_ENDPOINT,
            CHAT_LIST_ENDPOINT,
            CHAT_HISTORY_ENDPOINT,
        }
        if endpoint in allowed:
            return
        if endpoint in FORBIDDEN_CHAT_ENDPOINTS:
            raise ValueError(f"Forbidden write endpoint blocked: {endpoint}")
        raise ValueError(f"Unconfirmed Ozon chat endpoint blocked: {endpoint}")

    def _build_result(
        self,
        *,
        operation: str,
        endpoint: str,
        payload_sent: dict[str, Any],
        response: Response | None,
        payload: Any,
        elapsed_ms: int,
        error: str,
    ) -> dict[str, Any]:
        status_code = response.status_code if response is not None else None
        top_level_keys = sorted(payload.keys()) if isinstance(payload, Mapping) else []
        items = discover_top_level_items(payload)
        error_lower = (error or "").lower()
        result = {
            "operation": operation,
            "endpoint": endpoint,
            "status_code": status_code,
            "elapsed_ms": elapsed_ms,
            "payload_sent": payload_sent,
            "payload": payload,
            "response_top_level_type": type_name(payload),
            "response_top_level_keys": top_level_keys,
            "item_count": len(items) if isinstance(items, list) else 0,
            "pagination": infer_pagination(payload),
            "rate_limit_headers": pick_rate_limit_headers(response.headers) if response is not None else {},
            "error": error,
            "is_success": status_code == 200,
            "is_role_error": ROLE_ERROR_SNIPPET in error_lower,
            "is_not_found": status_code == 404,
            "is_bad_request": status_code == 400,
            "is_auth_error": status_code in {401, 403},
        }
        return result

    def _post_json(self, *, endpoint: str, payload: dict[str, Any], operation: str) -> dict[str, Any]:
        self._ensure_allowed_endpoint(endpoint)
        if not self.has_credentials():
            return self._build_result(
                operation=operation,
                endpoint=endpoint,
                payload_sent=payload,
                response=None,
                payload=None,
                elapsed_ms=0,
                error="Missing OZON_CLIENT_ID / OZON_API_KEY credentials",
            )

        start = time.time()
        response: Response | None = None
        payload_data: Any = None
        error = ""
        try:
            response = self.session.post(
                f"{self.base_url}{endpoint}",
                json=payload,
                headers=self._get_default_headers(),
                timeout=self.timeout,
            )
            elapsed_ms = int((time.time() - start) * 1000)
            payload_data = self._decode_response_payload(response)
            self._log_request("POST", f"{self.base_url}{endpoint}", elapsed_ms / 1000.0, response.status_code)
            if response.status_code >= 400:
                if isinstance(payload_data, Mapping):
                    error = str(
                        payload_data.get("message")
                        or payload_data.get("error")
                        or payload_data.get("description")
                        or payload_data.get("detail")
                        or ""
                    )
                if not error:
                    error = response.text[:1000]
            return self._build_result(
                operation=operation,
                endpoint=endpoint,
                payload_sent=payload,
                response=response,
                payload=payload_data,
                elapsed_ms=elapsed_ms,
                error=error,
            )
        except Exception as exc:
            elapsed_ms = int((time.time() - start) * 1000)
            self.logger.warning(f"Ozon POST {endpoint} failed during {operation}: {exc}")
            return self._build_result(
                operation=operation,
                endpoint=endpoint,
                payload_sent=payload,
                response=response,
                payload=payload_data,
                elapsed_ms=elapsed_ms,
                error=str(exc),
            )

    def validate_known_good_access(self) -> dict[str, Any]:
        result = self._post_json(
            endpoint=KNOWN_GOOD_READONLY_ENDPOINT,
            payload={
                "filter": {"visibility": "ALL"},
                "limit": 1,
                "last_id": "",
            },
            operation="known_good_readonly_check",
        )
        self.last_known_good_result = result
        return result

    def _chat_list_payloads(self) -> tuple[dict[str, Any], ...]:
        return (
            {},
            {"limit": 100},
            {"limit": 100, "offset": 0},
        )

    def _chat_history_payloads(self, chat_id: str) -> tuple[dict[str, Any], ...]:
        return (
            {"chat_id": chat_id},
            {"chat_id": chat_id, "limit": 100},
        )

    def _run_payload_variants(
        self,
        *,
        endpoint: str,
        operation: str,
        payload_variants: Sequence[dict[str, Any]],
    ) -> dict[str, Any]:
        attempts: list[dict[str, Any]] = []
        best_result: dict[str, Any] | None = None
        for payload in payload_variants:
            result = self._post_json(endpoint=endpoint, payload=payload, operation=operation)
            attempts.append(result)
            if best_result is None:
                best_result = result
            if result["status_code"] == 200:
                best_result = result
                break
            if result["is_not_found"]:
                best_result = result
                break
            if result["is_role_error"]:
                best_result = result
                break
            if result["is_auth_error"]:
                best_result = result
                break
        return {
            "operation": operation,
            "endpoint": endpoint,
            "attempts": attempts,
            "result": best_result or self._build_result(
                operation=operation,
                endpoint=endpoint,
                payload_sent={},
                response=None,
                payload=None,
                elapsed_ms=0,
                error="No attempts executed",
            ),
        }

    def list_chats(self) -> dict[str, Any]:
        summary = self._run_payload_variants(
            endpoint=CHAT_LIST_ENDPOINT,
            operation="chat_list",
            payload_variants=self._chat_list_payloads(),
        )
        self.last_chat_list_result = summary
        return summary

    def get_chat_history(self, chat_id: str) -> dict[str, Any]:
        summary = self._run_payload_variants(
            endpoint=CHAT_HISTORY_ENDPOINT,
            operation="chat_history",
            payload_variants=self._chat_history_payloads(chat_id),
        )
        self.last_history_results.append(summary)
        return summary

    def _build_runtime_diagnostics(self) -> dict[str, Any]:
        env_client_id = (os.getenv("OZON_CLIENT_ID") or "").strip()
        env_api_key = (os.getenv("OZON_API_KEY") or "").strip()
        env_api_token = (os.getenv("OZON_API_TOKEN") or "").strip()
        effective_env_api_key = env_api_key or env_api_token
        return {
            "credentials_present": self.has_credentials(),
            "masked_client_id": mask_secret(self.client_id),
            "base_url": self.base_url,
            "known_good_endpoint": KNOWN_GOOD_READONLY_ENDPOINT,
            "chat_list_endpoint": CHAT_LIST_ENDPOINT,
            "chat_history_endpoint": CHAT_HISTORY_ENDPOINT,
            "chat_list_payload_variants": [dict(payload) for payload in self._chat_list_payloads()],
            "settings_loader": "src.config.settings -> load_dotenv(BASE_DIR/.env) + os.getenv; Ozon credentials are not read from st.secrets",
            "env_ozon_client_id_present": bool(env_client_id),
            "env_ozon_api_key_present": bool(env_api_key),
            "env_ozon_api_token_present": bool(env_api_token),
            "settings_client_id_matches_env": bool(self.client_id and env_client_id and self.client_id == env_client_id),
            "settings_api_key_matches_env": bool(self.api_key and effective_env_api_key and self.api_key == effective_env_api_key),
        }

    def probe_readonly_access(self, *, history_chat_ids: Optional[Sequence[str]] = None) -> dict[str, Any]:
        known_good = self.validate_known_good_access()
        chat_list = self.list_chats()
        list_items = discover_top_level_items(chat_list["result"].get("payload") or {})
        discovered_chat_ids: list[str] = []
        for row in list_items:
            if not isinstance(row, Mapping):
                continue
            value = extract_first_value(row, CHAT_ID_CANDIDATES)
            if value in (None, ""):
                continue
            discovered_chat_ids.append(str(value))
            if len(discovered_chat_ids) >= 3:
                break
        requested_chat_ids = list(history_chat_ids or discovered_chat_ids)
        history_results: list[dict[str, Any]] = []
        for chat_id in requested_chat_ids[:3]:
            summary = self.get_chat_history(chat_id)
            history_results.append(summary)
            result = summary.get("result", {})
            if result.get("status_code") == 404 or result.get("is_role_error") or result.get("is_auth_error"):
                break
        return {
            "credentials": {
                "client_id_present": bool(self.client_id),
                "api_key_present": bool(self.api_key),
            },
            "runtime": self._build_runtime_diagnostics(),
            "known_good": known_good,
            "chat_list": chat_list,
            "chat_history": history_results,
            "chat_count": len(list_items) if isinstance(list_items, list) else 0,
            "sample_chat_ids": requested_chat_ids[:3],
        }

    def health_check(self) -> bool:
        result = self.validate_known_good_access()
        return bool(result.get("status_code") == 200)

    def fetch_current_chats(self) -> Optional[dict[str, Any]]:
        summary = self.list_chats()
        result = summary.get("result") or {}
        payload = result.get("payload")
        return payload if isinstance(payload, Mapping) else None

    def fetch_events(self, next_cursor: Optional[int] = None, chat_id: Optional[str] = None) -> Optional[dict[str, Any]]:
        _ = next_cursor
        if not chat_id:
            return None
        summary = self.get_chat_history(chat_id)
        result = summary.get("result") or {}
        payload = result.get("payload")
        return payload if isinstance(payload, Mapping) else None

    def send_message(self, chat_id: str, text: str, reply_sign: str) -> Optional[dict[str, Any]]:
        raise RuntimeError(
            "Ozon real send is disabled. Endpoints start/send/file/read are blocked in audit stage."
        )
