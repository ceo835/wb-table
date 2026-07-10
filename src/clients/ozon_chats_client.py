from __future__ import annotations

from typing import Any, Optional
from src.utils.logger import get_logger

class OzonChatsClient:
    """Заглушка для Ozon Chats API. Будет реализована после аудита API Ozon."""
    
    def __init__(self, token: Optional[str] = None):
        self.token = token
        self.logger = get_logger("ozon_chats_client")

    def health_check(self) -> bool:
        return False

    def fetch_current_chats(self) -> Optional[dict[str, Any]]:
        raise NotImplementedError("Ozon Chats API fetch_current_chats is not implemented yet")

    def fetch_events(self, next_cursor: Optional[int] = None) -> Optional[dict[str, Any]]:
        raise NotImplementedError("Ozon Chats API fetch_events is not implemented yet")

    def send_message(self, chat_id: str, text: str, reply_sign: str) -> Optional[dict[str, Any]]:
        raise NotImplementedError("Ozon Chats API send_message is not implemented yet")
