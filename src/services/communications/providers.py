from __future__ import annotations

from abc import ABC, abstractmethod
from datetime import datetime, UTC
from typing import Any, Optional, Dict, List
import time

from sqlalchemy.orm import Session
from src.clients.wb_chats_client import WBChatsClient
from src.clients.ozon_chats_client import OzonChatsClient
from src.db.communications_models import ChatRegistry
from src.db.session import upsert_rows
from src.utils.logger import get_logger

logger = get_logger("communications_providers")


def parse_timestamp(value: Any) -> Optional[datetime]:
    """Вспомогательная функция для парсинга таймстемпов из API."""
    if value in (None, ""):
        return None
    if isinstance(value, datetime):
        return value.astimezone(UTC) if value.tzinfo else value.replace(tzinfo=UTC)
    if isinstance(value, (int, float)):
        try:
            if value > 1_000_000_000_000:  # Миллисекунды
                return datetime.fromtimestamp(float(value) / 1000.0, tz=UTC)
            if value > 1_000_000_000:  # Секунды
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


class BaseChatProvider(ABC):
    """Абстрактный класс провайдера чатов маркетплейса."""

    @abstractmethod
    def fetch_events(self, max_pages: int = 10) -> List[Dict[str, Any]]:
        """Получить события/сообщения чатов из API."""
        pass

    @abstractmethod
    def fetch_current_chats(self) -> List[Dict[str, Any]]:
        """Получить текущие активные чаты."""
        pass

    @abstractmethod
    def build_chat_registry(self, session: Session, max_event_pages: int = 10) -> int:
        """Синхронизировать чаты из API и обновить реестр ChatRegistry в БД."""
        pass

    @abstractmethod
    def send_message(self, chat_id: str, text: str, reply_sign: Optional[str] = None) -> Dict[str, Any]:
        """Отправить сообщение в чат."""
        pass


class WBChatProvider(BaseChatProvider):
    """Провайдер чатов для Wildberries."""

    def __init__(self, token: Optional[str] = None):
        self.client = WBChatsClient(token=token)

    def fetch_events(self, max_pages: int = 10) -> List[Dict[str, Any]]:
        """Получить историю событий из API WB с пагинацией."""
        all_events = []
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
                
                # Извлекаем курсор для следующей страницы
                next_candidate = result.get("next")
                if not isinstance(next_candidate, int) or next_candidate == next_cursor:
                    break
                next_cursor = next_candidate
                time.sleep(0.1)  # Небольшая задержка
            except Exception as e:
                logger.error(f"Error fetching event page {page}: {e}")
                break
                
        return all_events

    def fetch_current_chats(self) -> List[Dict[str, Any]]:
        """Получить 100 активных чатов из API WB."""
        try:
            res = self.client.fetch_current_chats()
            if res and "result" in res:
                chats = res["result"]
                return chats if isinstance(chats, list) else []
        except Exception as e:
            logger.error(f"Error fetching current chats: {e}")
        return []

    def _extract_nm_id_from_event(self, event: Dict[str, Any]) -> Optional[int]:
        """Вспомогательный метод для извлечения nmID из события."""
        # 1. Из event.message.attachments.goodCard.nmID
        msg = event.get("message") or {}
        if isinstance(msg, dict):
            attachments = msg.get("attachments")
            if isinstance(attachments, dict):
                nm_id = attachments.get("goodCard", {}).get("nmID")
                if nm_id:
                    return int(nm_id)
            elif isinstance(attachments, list) and attachments:
                for attachment in attachments:
                    if isinstance(attachment, dict):
                        nm_id = attachment.get("goodCard", {}).get("nmID")
                        if nm_id:
                            return int(nm_id)

        # 2. Из event.goodCard.nmID (на случай другой структуры)
        nm_id = event.get("goodCard", {}).get("nmID")
        if nm_id:
            return int(nm_id)
            
        return None

    def build_chat_registry(self, session: Session, max_event_pages: int = 10) -> int:
        """Загрузить данные из API и обновить единый реестр чатов WB в БД."""
        logger.info("Starting WB chat registry sync")
        
        # 1. Получаем текущие чаты (100 штук)
        current_chats = self.fetch_current_chats()
        logger.info(f"Fetched {len(current_chats)} current active chats from API")
        
        # 2. Получаем исторические события
        events = self.fetch_events(max_pages=max_event_pages)
        logger.info(f"Fetched {len(events)} events from API")

        # 3. Агрегируем информацию
        chats_data = {}  # chat_id -> dict с данными для бд
        
        # Сначала обрабатываем исторические события
        for event in events:
            chat_id = event.get("chatID")
            if not chat_id:
                continue
                
            chat_id_str = str(chat_id)
            
            # Парсим время события
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

        # Теперь обогащаем текущими активными чатами
        for chat in current_chats:
            chat_id = chat.get("chatID")
            if not chat_id:
                continue
                
            chat_id_str = str(chat_id)
            reply_sign = chat.get("replySign")
            nm_id = chat.get("goodCard", {}).get("nmID")
            
            # Таймстемп последнего сообщения в чате
            last_msg_time = None
            last_msg = chat.get("lastMessage") or {}
            if isinstance(last_msg, dict):
                last_msg_time = parse_timestamp(last_msg.get("addTimestamp")) or parse_timestamp(last_msg.get("addTime"))
            
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

        # Формируем итоговый список строк для upsert
        rows_to_upsert = []
        for chat_id, entry in chats_data.items():
            # Превращаем set во float/int list для JSONB
            entry["product_ids"] = list(entry["product_ids"])
            rows_to_upsert.append(entry)

        if rows_to_upsert:
            count = upsert_rows(
                session,
                ChatRegistry,
                rows_to_upsert,
                conflict_columns=("marketplace", "chat_id")
            )
            logger.info(f"Prepared {len(rows_to_upsert)} records to upsert into ChatRegistry. upsert_rows returned status: {count}")
            return len(rows_to_upsert)
            
        return 0

    def send_message(self, chat_id: str, text: str, reply_sign: Optional[str] = None) -> Dict[str, Any]:
        """Отправить сообщение покупателю.
        
        Если reply_sign отсутствует, пытается получить его из актуального списка чатов.
        """
        resolved_reply_sign = reply_sign
        
        # Если подпись отсутствует, попробуем найти её через актуальные чаты
        if not resolved_reply_sign:
            logger.info(f"reply_sign is missing for chat {chat_id}, trying to fetch from current active chats")
            current_chats = self.fetch_current_chats()
            for chat in current_chats:
                if str(chat.get("chatID")) == chat_id:
                    resolved_reply_sign = chat.get("replySign")
                    logger.info(f"Found reply_sign dynamically for chat {chat_id}")
                    break
                    
        if not resolved_reply_sign:
            # Ошибка: не нашли подпись ни в аргументах, ни в активных чатах
            logger.error(f"Cannot send message to chat {chat_id}: replySign is missing and not found in active chats")
            return {
                "success": False,
                "error": "Missing replySign (chat signature). Chat must be active to receive messages."
            }

        try:
            res = self.client.send_message(chat_id=chat_id, text=text, reply_sign=resolved_reply_sign)
            if res is not None:
                # Если API вернуло ошибки
                if "errors" in res and res["errors"]:
                    return {
                        "success": False,
                        "error": "; ".join(res["errors"]),
                        "raw_response": res
                    }
                return {
                    "success": True,
                    "raw_response": res
                }
            else:
                return {
                    "success": False,
                    "error": "Empty response from Wildberries API"
                }
        except Exception as e:
            logger.error(f"Failed to send message to chat {chat_id}: {e}")
            return {
                "success": False,
                "error": str(e)
            }


class OzonChatProvider(BaseChatProvider):
    """Провайдер-заглушка для Ozon."""

    def __init__(self, token: Optional[str] = None):
        self.client = OzonChatsClient(token=token)

    def fetch_events(self, max_pages: int = 10) -> List[Dict[str, Any]]:
        raise NotImplementedError("Ozon Chat Provider is not implemented yet")

    def fetch_current_chats(self) -> List[Dict[str, Any]]:
        raise NotImplementedError("Ozon Chat Provider is not implemented yet")

    def build_chat_registry(self, session: Session, max_event_pages: int = 10) -> int:
        raise NotImplementedError("Ozon Chat Provider is not implemented yet")

    def send_message(self, chat_id: str, text: str, reply_sign: Optional[str] = None) -> Dict[str, Any]:
        raise NotImplementedError("Ozon Chat Provider is not implemented yet")
