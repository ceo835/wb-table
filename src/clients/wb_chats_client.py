from __future__ import annotations

from typing import Any, Optional
from src.clients.base_client import BaseAPIClient
from src.config.settings import settings
from src.utils.logger import get_logger

class WBChatsClient(BaseAPIClient):
    """Клиент для работы с API чатов покупателей Wildberries.
    
    Документация: https://dev.wildberries.ru/ru/docs/openapi/user-communication
    """
    
    BASE_URL = "https://buyer-chat-api.wildberries.ru"

    def __init__(self, token: Optional[str] = None):
        # Используем основной WB_TOKEN проекта
        resolved_token = token or settings.wb_token
        if not resolved_token:
            raise ValueError("WB_TOKEN не найден в настройках или переменных окружения")
            
        super().__init__(
            base_url=self.BASE_URL,
            token=resolved_token,
            logger_name="wb_chats_client"
        )
        self.logger = get_logger("wb_chats_client")

    def _get_default_headers(self) -> dict[str, str]:
        headers = super()._get_default_headers()
        # Поддержка Bearer-префикса, если это необходимо
        token_str = self.token
        if not token_str.startswith("Bearer ") and len(token_str) > 100:
            token_str = f"Bearer {token_str}"
        headers["Authorization"] = token_str
        return headers

    def health_check(self) -> bool:
        """Проверить доступность API чатов."""
        try:
            # Делаем пробный запрос списка активных чатов
            res = self.fetch_current_chats()
            return res is not None
        except Exception as e:
            self.logger.error(f"Health check failed for WBChatsClient: {e}")
            return False

    def fetch_current_chats(self) -> Optional[dict[str, Any]]:
        """Получить список текущих активных чатов (последние 100 чатов).
        
        GET /api/v1/seller/chats
        """
        endpoint = "/api/v1/seller/chats"
        self.logger.info("Fetching current active WB chats")
        return self.get(endpoint)

    def fetch_events(self, next_cursor: Optional[int] = None) -> Optional[dict[str, Any]]:
        """Получить историю событий/сообщений по чатам (с поддержкой пагинации).
        
        GET /api/v1/seller/events
        """
        endpoint = "/api/v1/seller/events"
        params = {}
        if next_cursor is not None:
            params["next"] = next_cursor
        self.logger.info(f"Fetching WB chat events page, cursor: {next_cursor}")
        return self.get(endpoint, params=params)

    def send_message(self, chat_id: str, text: str, reply_sign: str) -> Optional[dict[str, Any]]:
        """Отправить текстовое сообщение в чат.
        
        POST /api/v1/seller/message
        """
        endpoint = "/api/v1/seller/message"
        payload = {
            "id": chat_id,
            "text": text,
            "replySign": reply_sign
        }
        self.logger.info(f"Sending message to WB chat {chat_id}")
        return self.post(endpoint, json_data=payload)
