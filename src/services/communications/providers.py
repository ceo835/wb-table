from __future__ import annotations

import json
from abc import ABC, abstractmethod
from datetime import UTC, datetime
from typing import Any, Dict, List, Mapping, Optional
import time

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from src.clients.ozon_chats_client import (
    CHAT_ID_CANDIDATES,
    CHAT_STATUS_CANDIDATES,
    CHAT_TYPE_CANDIDATES,
    FIRST_ACTIVITY_CANDIDATES,
    FIRST_UNREAD_MESSAGE_ID_CANDIDATES,
    LAST_ACTIVITY_CANDIDATES,
    LAST_MESSAGE_ID_CANDIDATES,
    LAST_MESSAGE_TEXT_CANDIDATES,
    LAST_SENDER_CANDIDATES,
    OFFER_ID_CANDIDATES,
    ORDER_ID_CANDIDATES,
    PRODUCT_NAME_CANDIDATES,
    PRODUCT_NUMERIC_ID_CANDIDATES,
    REPLY_CAPABLE_CANDIDATES,
    UNREAD_COUNT_CANDIDATES,
    VENDOR_CODE_CANDIDATES,
    OzonChatsClient,
    coerce_int,
    discover_top_level_items,
    extract_first_value,
    mask_secret,
)
from src.clients.wb_chats_client import WBChatsClient
from src.config.settings import settings
from src.db.communications_models import ChatRegistry
from src.db.session import upsert_rows
from src.utils.logger import get_logger

logger = get_logger("communications_providers")


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


OZON_REGISTRY_META_PREFIX = "__ozon_meta__:"
OZON_OPEN_STATUSES = {"OPENED", "OPEN", "ACTIVE"}
OZON_CLOSED_STATUSES = {"CLOSED", "CLOSE", "ARCHIVED", "ARCHIVE", "DONE"}


def _clean_text(value: Any) -> Optional[str]:
    if value in (None, ""):
        return None
    text = str(value).strip()
    return text or None


def serialize_ozon_registry_meta(meta: Mapping[str, Any]) -> Optional[str]:
    cleaned: dict[str, Any] = {}
    for key, value in dict(meta).items():
        if value in (None, "", [], {}):
            continue
        cleaned[str(key)] = value
    if not cleaned:
        return None
    return OZON_REGISTRY_META_PREFIX + json.dumps(cleaned, ensure_ascii=False, sort_keys=True, default=str)


def parse_ozon_registry_meta(raw_value: Any) -> dict[str, Any]:
    text_value = str(raw_value or "").strip()
    if not text_value:
        return {}
    if text_value.startswith(OZON_REGISTRY_META_PREFIX):
        try:
            parsed = json.loads(text_value[len(OZON_REGISTRY_META_PREFIX):])
        except json.JSONDecodeError:
            return {"raw_meta": text_value}
        return parsed if isinstance(parsed, dict) else {"raw_meta": text_value}
    return {"legacy_reply_sign": text_value, "can_reply": True}


def ozon_registry_status_key(meta: Mapping[str, Any]) -> str:
    status_value = str(meta.get("chat_status") or "").strip().upper()
    if status_value in OZON_OPEN_STATUSES:
        return "opened"
    if status_value in OZON_CLOSED_STATUSES:
        return "closed"
    return "other"


def ozon_registry_can_reply(meta: Mapping[str, Any]) -> bool:
    explicit = meta.get("can_reply")
    if isinstance(explicit, bool):
        return explicit
    if explicit not in (None, ""):
        return str(explicit).strip().lower() not in {"false", "0", "no", "off"}
    return ozon_registry_status_key(meta) == "opened"


def _merge_ozon_registry_meta(existing: Mapping[str, Any], incoming: Mapping[str, Any]) -> dict[str, Any]:
    merged = dict(existing)
    for key, value in dict(incoming).items():
        if value in (None, "", [], {}):
            continue
        if key == "can_reply":
            merged[key] = bool(merged.get(key)) or bool(value)
            continue
        if key == "unread_count":
            current = coerce_int(merged.get(key)) or 0
            candidate = coerce_int(value) or 0
            merged[key] = max(current, candidate)
            continue
        merged[key] = value
    if "chat_status" in merged:
        merged["chat_status"] = str(merged["chat_status"]).strip().upper()
    merged["can_reply"] = ozon_registry_can_reply(merged)
    return merged


class BaseChatProvider(ABC):
    @abstractmethod
    def fetch_events(self, max_pages: int = 10) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def fetch_current_chats(self) -> List[Dict[str, Any]]:
        pass

    @abstractmethod
    def build_chat_registry(self, session: Session, max_event_pages: int = 10) -> int:
        pass

    @abstractmethod
    def send_message(self, chat_id: str, text: str, reply_sign: Optional[str] = None) -> Dict[str, Any]:
        pass


class WBChatProvider(BaseChatProvider):
    def __init__(self, token: Optional[str] = None):
        self.client = WBChatsClient(token=token)

    def fetch_events(self, max_pages: int = 10) -> List[Dict[str, Any]]:
        all_events: List[Dict[str, Any]] = []
        next_cursor = None
        for page in range(1, max_pages + 1):
            try:
                res = self.client.fetch_events(next_cursor=next_cursor)
                if not res or "result" not in res:
                    logger.warning(f"Failed to fetch events page {page} or response empty")
                    break
                result = res["result"]
                events = result.get("events")
                if not isinstance(events, list) or not events:
                    logger.info(f"No more events found on page {page}")
                    break
                all_events.extend(events)
                next_candidate = result.get("next")
                if not isinstance(next_candidate, int) or next_candidate == next_cursor:
                    break
                next_cursor = next_candidate
                time.sleep(0.1)
            except Exception as exc:
                logger.error(f"Error fetching event page {page}: {exc}")
                break
        return all_events

    def fetch_current_chats(self) -> List[Dict[str, Any]]:
        try:
            res = self.client.fetch_current_chats()
            if res and "result" in res:
                chats = res["result"]
                return chats if isinstance(chats, list) else []
        except Exception as exc:
            logger.error(f"Error fetching current chats: {exc}")
        return []

    def _extract_nm_id_from_event(self, event: Dict[str, Any]) -> Optional[int]:
        msg = event.get("message") or {}
        if isinstance(msg, dict):
            attachments = msg.get("attachments")
            if isinstance(attachments, dict):
                nm_id = attachments.get("goodCard", {}).get("nmID")
                if nm_id:
                    return int(nm_id)
            elif isinstance(attachments, list):
                for attachment in attachments:
                    if isinstance(attachment, dict):
                        nm_id = attachment.get("goodCard", {}).get("nmID")
                        if nm_id:
                            return int(nm_id)
        nm_id = event.get("goodCard", {}).get("nmID")
        return int(nm_id) if nm_id else None

    def build_chat_registry(self, session: Session, max_event_pages: int = 10) -> int:
        logger.info("Starting WB chat registry sync")
        current_chats = self.fetch_current_chats()
        events = self.fetch_events(max_pages=max_event_pages)
        chats_data: dict[str, dict[str, Any]] = {}

        for event in events:
            chat_id = event.get("chatID")
            if not chat_id:
                continue
            chat_id_str = str(chat_id)
            evt_time = parse_timestamp(event.get("addTimestamp")) or parse_timestamp(event.get("addTime"))
            sender = event.get("sender")
            nm_id = self._extract_nm_id_from_event(event)
            if chat_id_str not in chats_data:
                chats_data[chat_id_str] = {
                    "marketplace": "wb",
                    "chat_id": chat_id_str,
                    "first_activity_at": evt_time,
                    "last_activity_at": evt_time,
                    "last_sender": sender,
                    "reply_sign": None,
                    "current_chat_exists": False,
                    "product_ids": set(),
                    "source": "events",
                }
            else:
                entry = chats_data[chat_id_str]
                if evt_time:
                    if not entry["first_activity_at"] or evt_time < entry["first_activity_at"]:
                        entry["first_activity_at"] = evt_time
                    if not entry["last_activity_at"] or evt_time > entry["last_activity_at"]:
                        entry["last_activity_at"] = evt_time
                        entry["last_sender"] = sender
            if nm_id:
                chats_data[chat_id_str]["product_ids"].add(nm_id)

        for chat in current_chats:
            chat_id = chat.get("chatID")
            if not chat_id:
                continue
            chat_id_str = str(chat_id)
            reply_sign = chat.get("replySign")
            nm_id = chat.get("goodCard", {}).get("nmID")
            last_msg = chat.get("lastMessage") or {}
            last_msg_time = parse_timestamp(last_msg.get("addTimestamp")) or parse_timestamp(last_msg.get("addTime")) if isinstance(last_msg, dict) else None
            if chat_id_str not in chats_data:
                chats_data[chat_id_str] = {
                    "marketplace": "wb",
                    "chat_id": chat_id_str,
                    "first_activity_at": last_msg_time,
                    "last_activity_at": last_msg_time,
                    "last_sender": None,
                    "reply_sign": reply_sign,
                    "current_chat_exists": True,
                    "product_ids": set(),
                    "source": "chats",
                }
            else:
                entry = chats_data[chat_id_str]
                entry["current_chat_exists"] = True
                entry["reply_sign"] = reply_sign
                if last_msg_time and (not entry["last_activity_at"] or last_msg_time > entry["last_activity_at"]):
                    entry["last_activity_at"] = last_msg_time
            if nm_id:
                chats_data[chat_id_str]["product_ids"].add(int(nm_id))

        rows_to_upsert = []
        for entry in chats_data.values():
            entry["product_ids"] = list(entry["product_ids"])
            rows_to_upsert.append(entry)
        if rows_to_upsert:
            upsert_rows(session, ChatRegistry, rows_to_upsert, conflict_columns=("marketplace", "chat_id"))
            return len(rows_to_upsert)
        return 0

    def send_message(self, chat_id: str, text: str, reply_sign: Optional[str] = None) -> Dict[str, Any]:
        resolved_reply_sign = reply_sign
        if not resolved_reply_sign:
            current_chats = self.fetch_current_chats()
            for chat in current_chats:
                if str(chat.get("chatID")) == chat_id:
                    resolved_reply_sign = chat.get("replySign")
                    break
        if not resolved_reply_sign:
            return {"success": False, "error": "Missing replySign (chat signature). Chat must be active to receive messages."}
        try:
            res = self.client.send_message(chat_id=chat_id, text=text, reply_sign=resolved_reply_sign)
            if res is not None and not res.get("errors"):
                return {"success": True, "raw_response": res}
            return {"success": False, "error": "; ".join(res.get("errors", [])) if isinstance(res, dict) else "Empty response", "raw_response": res}
        except Exception as exc:
            logger.error(f"Failed to send message to chat {chat_id}: {exc}")
            return {"success": False, "error": str(exc)}


class OzonChatProvider(BaseChatProvider):
    def __init__(self, client_id: Optional[str] = None, api_key: Optional[str] = None):
        self.client = OzonChatsClient(client_id=client_id, api_key=api_key)
        self.last_sync_diagnostics: dict[str, Any] = {}

    def fetch_current_chats(self) -> List[Dict[str, Any]]:
        summary = self.client.list_all_chats(max_pages=50)
        return [item for item in summary.get("items", []) if isinstance(item, dict)]

    def fetch_events(self, max_pages: int = 10) -> List[Dict[str, Any]]:
        current_chats = self.fetch_current_chats()
        all_events: List[Dict[str, Any]] = []
        seen_fingerprints: set[str] = set()
        for row in current_chats[:max_pages]:
            chat_id = extract_first_value(row, CHAT_ID_CANDIDATES)
            if chat_id in (None, ""):
                continue
            summary = self.client.get_chat_history(str(chat_id), context=row)
            payload = summary.get("result", {}).get("payload")
            for item in discover_top_level_items(payload or {}):
                if not isinstance(item, dict):
                    continue
                fingerprint = repr(sorted(item.items()))
                if fingerprint in seen_fingerprints:
                    continue
                seen_fingerprints.add(fingerprint)
                if extract_first_value(item, CHAT_ID_CANDIDATES) in (None, ""):
                    item = dict(item)
                    item["chat_id"] = str(chat_id)
                all_events.append(item)
        return all_events

    def _extract_product_ids(self, row: Mapping[str, Any]) -> List[int]:
        values: set[int] = set()
        direct_value = extract_first_value(row, PRODUCT_NUMERIC_ID_CANDIDATES)
        direct_int = coerce_int(direct_value)
        if direct_int is not None:
            values.add(direct_int)
        for key in ("products", "items", "goods"):
            nested = row.get(key)
            if isinstance(nested, list):
                for item in nested:
                    if not isinstance(item, Mapping):
                        continue
                    nested_value = extract_first_value(item, PRODUCT_NUMERIC_ID_CANDIDATES)
                    nested_int = coerce_int(nested_value)
                    if nested_int is not None:
                        values.add(nested_int)
        return sorted(values)

    def _extract_order_tokens(self, row: Mapping[str, Any]) -> List[str]:
        tokens: set[str] = set()
        direct = extract_first_value(row, ORDER_ID_CANDIDATES)
        if direct not in (None, ""):
            tokens.add(str(direct))
        for key in ("posting", "order", "purchase"):
            nested = row.get(key)
            if isinstance(nested, Mapping):
                nested_value = extract_first_value(nested, ORDER_ID_CANDIDATES)
                if nested_value not in (None, ""):
                    tokens.add(str(nested_value))
        return sorted(tokens)

    def _extract_meta_from_row(self, row: Mapping[str, Any], *, source: str) -> dict[str, Any]:
        meta = {
            "chat_status": _clean_text(extract_first_value(row, CHAT_STATUS_CANDIDATES)),
            "chat_type": _clean_text(extract_first_value(row, CHAT_TYPE_CANDIDATES)),
            "can_reply": self._is_reply_capable(row),
            "unread_count": coerce_int(extract_first_value(row, UNREAD_COUNT_CANDIDATES)),
            "last_message_id": _clean_text(extract_first_value(row, LAST_MESSAGE_ID_CANDIDATES)),
            "first_unread_message_id": _clean_text(extract_first_value(row, FIRST_UNREAD_MESSAGE_ID_CANDIDATES)),
            "offer_id": _clean_text(extract_first_value(row, OFFER_ID_CANDIDATES)),
            "product_id": coerce_int(extract_first_value(row, ("product_id", "productId"))),
            "sku": coerce_int(extract_first_value(row, ("sku", "sku_id", "skuId"))),
            "product_name": _clean_text(extract_first_value(row, PRODUCT_NAME_CANDIDATES)),
            "vendor_code": _clean_text(extract_first_value(row, VENDOR_CODE_CANDIDATES)),
            "last_message_preview": _clean_text(extract_first_value(row, LAST_MESSAGE_TEXT_CANDIDATES)),
            "source_endpoint": source,
        }
        if meta.get("chat_status"):
            meta["chat_status"] = str(meta["chat_status"]).upper()
        meta["can_reply"] = ozon_registry_can_reply(meta)
        return meta

    def _is_reply_capable(self, row: Mapping[str, Any]) -> bool:
        value = extract_first_value(row, REPLY_CAPABLE_CANDIDATES)
        if isinstance(value, bool):
            return value
        if isinstance(value, str):
            normalized = value.strip().lower()
            if normalized in {"", "false", "0", "no", "off"}:
                return False
            return True
        status_value = _clean_text(extract_first_value(row, CHAT_STATUS_CANDIDATES))
        return str(status_value or "").upper() in OZON_OPEN_STATUSES

    def _row_to_registry_entry(self, row: Mapping[str, Any], *, source: str) -> Optional[dict[str, Any]]:
        chat_id = extract_first_value(row, CHAT_ID_CANDIDATES)
        if chat_id in (None, ""):
            return None
        first_activity = parse_timestamp(extract_first_value(row, FIRST_ACTIVITY_CANDIDATES))
        last_activity = parse_timestamp(extract_first_value(row, LAST_ACTIVITY_CANDIDATES)) or first_activity
        meta = self._extract_meta_from_row(row, source=source)
        return {
            "marketplace": "ozon",
            "chat_id": str(chat_id),
            "first_activity_at": first_activity,
            "last_activity_at": last_activity,
            "last_sender": extract_first_value(row, LAST_SENDER_CANDIDATES),
            "reply_sign": serialize_ozon_registry_meta(meta),
            "current_chat_exists": True,
            "product_ids": set(self._extract_product_ids(row)),
            "source": source,
        }

    def build_chat_registry(self, session: Session, max_event_pages: int = 10) -> int:
        logger.info("Starting Ozon read-only chat registry sync")
        chat_list_summary = self.client.list_all_chats(max_pages=50)
        chat_list_result = chat_list_summary.get("result", {})
        chat_list_status = chat_list_result.get("status_code")
        current_chats = [item for item in chat_list_summary.get("items", []) if isinstance(item, dict)]

        chats_data: dict[str, dict[str, Any]] = {}
        chats_with_order_linkage: set[str] = set()
        replyable_chat_ids: set[str] = set()
        chats_with_product_linkage = 0
        history_status_codes: list[int | None] = []
        history_event_rows = 0

        for row in current_chats:
            entry = self._row_to_registry_entry(row, source="v3_chat_list")
            if not entry:
                continue
            chats_data[entry["chat_id"]] = entry
            meta = parse_ozon_registry_meta(entry.get("reply_sign"))
            if entry["product_ids"]:
                chats_with_product_linkage += 1
            if self._extract_order_tokens(row):
                chats_with_order_linkage.add(entry["chat_id"])
            if ozon_registry_can_reply(meta):
                replyable_chat_ids.add(entry["chat_id"])

        chat_context_by_id = {entry["chat_id"]: row for entry, row in [
            (self._row_to_registry_entry(row, source="v3_chat_list"), row) for row in current_chats
        ] if entry}
        chat_ids_for_history = list(chats_data.keys())[:max_event_pages]
        for chat_id in chat_ids_for_history:
            history_summary = self.client.get_chat_history(chat_id, context=chat_context_by_id.get(chat_id))
            history_result = history_summary.get("result", {})
            history_status = history_result.get("status_code")
            history_status_codes.append(history_status)
            payload = history_result.get("payload")
            for event in discover_top_level_items(payload or {}):
                if not isinstance(event, dict):
                    continue
                history_event_rows += 1
                entry = self._row_to_registry_entry(event, source="v1_chat_history")
                if not entry:
                    continue
                existing = chats_data.get(entry["chat_id"])
                if existing is None:
                    chats_data[entry["chat_id"]] = entry
                    if entry["product_ids"]:
                        chats_with_product_linkage += 1
                else:
                    if entry["first_activity_at"] and (
                        not existing["first_activity_at"] or entry["first_activity_at"] < existing["first_activity_at"]
                    ):
                        existing["first_activity_at"] = entry["first_activity_at"]
                    if entry["last_activity_at"] and (
                        not existing["last_activity_at"] or entry["last_activity_at"] > existing["last_activity_at"]
                    ):
                        existing["last_activity_at"] = entry["last_activity_at"]
                        if entry["last_sender"]:
                            existing["last_sender"] = entry["last_sender"]
                    existing["product_ids"].update(entry["product_ids"])
                    merged_meta = _merge_ozon_registry_meta(
                        parse_ozon_registry_meta(existing.get("reply_sign")),
                        parse_ozon_registry_meta(entry.get("reply_sign")),
                    )
                    existing["reply_sign"] = serialize_ozon_registry_meta(merged_meta)
                    if existing.get("source") != entry.get("source"):
                        existing["source"] = "v3_chat_list+v1_chat_history"
                if self._extract_order_tokens(event):
                    chats_with_order_linkage.add(entry["chat_id"])
                if ozon_registry_can_reply(parse_ozon_registry_meta(entry.get("reply_sign"))):
                    replyable_chat_ids.add(entry["chat_id"])
            if history_status == 404 or history_result.get("is_role_error") or history_result.get("is_auth_error"):
                break

        rows_to_upsert: List[dict[str, Any]] = []
        min_last_activity = None
        max_last_activity = None
        for entry in chats_data.values():
            entry["product_ids"] = sorted(entry["product_ids"])
            if entry.get("last_activity_at") is not None:
                last_activity = entry["last_activity_at"]
                min_last_activity = last_activity if min_last_activity is None else min(min_last_activity, last_activity)
                max_last_activity = last_activity if max_last_activity is None else max(max_last_activity, last_activity)
            rows_to_upsert.append(entry)

        if rows_to_upsert:
            upsert_rows(session, ChatRegistry, rows_to_upsert, conflict_columns=("marketplace", "chat_id"))

        ozon_registry_count = session.scalar(
            select(func.count()).select_from(ChatRegistry).where(ChatRegistry.marketplace == "ozon")
        )
        first_history_status = history_status_codes[0] if history_status_codes else None
        history_attempted = bool(chat_ids_for_history)
        self.last_sync_diagnostics = {
            "fetched_pages": chat_list_summary.get("fetched_pages", 0),
            "fetched_chats_raw": chat_list_summary.get("fetched_chats_raw", len(current_chats)),
            "unique_chats": chat_list_summary.get("unique_chats", len(current_chats)),
            "chat_list_stop_reason": chat_list_summary.get("stop_reason"),
            "repeated_cursor": chat_list_summary.get("repeated_cursor", False),
            "fetched_chats_count": chat_list_summary.get("unique_chats", len(current_chats)),
            "prepared_records_count": len(rows_to_upsert),
            "committed": False,
            "chat_registry_marketplace": "ozon",
            "chat_registry_count_ozon": ozon_registry_count,
            "known_good_status_code": None,
            "chat_list_status_code": chat_list_status,
            "chat_list_endpoint": "/v3/chat/list",
            "chat_list_payload_sent": chat_list_result.get("payload_sent"),
            "chat_list_response_preview": chat_list_result.get("response_text_preview", ""),
            "credentials_present": self.client.has_credentials(),
            "masked_client_id": mask_secret(self.client.client_id),
            "base_url": self.client.base_url,
            "history_status_codes": history_status_codes,
            "history_status": first_history_status,
            "history_confirmed": first_history_status == 200,
            "skipped_history": bool(chat_list_status != 200 or not history_attempted or (first_history_status is not None and first_history_status != 200)),
            "current_chats_fetched": len(current_chats),
            "events_fetched": history_event_rows,
            "chats_with_product_linkage": chats_with_product_linkage,
            "chats_with_order_linkage": len(chats_with_order_linkage),
            "reply_capable_chat_count": len(replyable_chat_ids),
            "min_last_activity_at": min_last_activity.isoformat() if min_last_activity else None,
            "max_last_activity_at": max_last_activity.isoformat() if max_last_activity else None,
            "used_chat_list_probe": "POST /v3/chat/list",
            "used_chat_events_probe": "POST /v1/chat/history",
        }
        logger.info(
            "Ozon chat registry sync diagnostics: "
            f"fetched_pages={self.last_sync_diagnostics['fetched_pages']}, "
            f"fetched_chats_raw={self.last_sync_diagnostics['fetched_chats_raw']}, "
            f"unique_chats={self.last_sync_diagnostics['unique_chats']}, "
            f"prepared={self.last_sync_diagnostics['prepared_records_count']}, "
            f"registry_ozon={self.last_sync_diagnostics['chat_registry_count_ozon']}, "
            f"chat_list_status={self.last_sync_diagnostics['chat_list_status_code']}, "
            f"history_status={self.last_sync_diagnostics['history_status']}, "
            f"history_confirmed={self.last_sync_diagnostics['history_confirmed']}, "
            f"skipped_history={self.last_sync_diagnostics['skipped_history']}, "
            f"stop_reason={self.last_sync_diagnostics['chat_list_stop_reason']}"
        )
        return len(rows_to_upsert)

    def send_message(self, chat_id: str, text: str, reply_sign: Optional[str] = None) -> Dict[str, Any]:
        if not settings.ozon_comm_real_send_enabled:
            return {
                "success": False,
                "error": "Ozon real send is disabled by OZON_COMM_REAL_SEND_ENABLED=false; start/send/file/read are blocked.",
            }
        raise RuntimeError("Ozon send flow is intentionally not implemented in the audit stage")
