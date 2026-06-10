"""
Клиент для MPStats API.

API документация: https://mpstats.io/api
"""
from typing import Any, Dict, List, Optional

from src.clients.base_client import BaseAPIClient
from src.config.settings import MPSTATS_API_TOKEN
from src.utils.logger import get_logger


class MPStatsClient(BaseAPIClient):
    """Клиент для работы с MPStats API."""

    BASE_URL = "https://mpstats.io/api/wb/get"

    def __init__(self, token: str = None):
        """
        Инициализировать клиент.

        Args:
            token: Токен авторизации (по умолчанию из env)
        """
        token = token or MPSTATS_API_TOKEN
        if not token:
            raise ValueError("MPSTATS_API_TOKEN не найден в переменных окружения")
        
        super().__init__(
            base_url=self.BASE_URL,
            token=token,
            logger_name="mpstats_client"
        )
        self.logger = get_logger("mpstats_client")

    def _get_default_headers(self) -> Dict[str, str]:
        """Получить заголовки с авторизацией."""
        headers = super()._get_default_headers()
        headers["X-Mpstats"] = self.token
        return headers

    def health_check(self) -> bool:
        """
        Проверить доступность API.

        Returns:
            True если API доступен
        """
        try:
            # Пробуем получить данные о товаре
            result = self.mpstats_item_full(item_id=1)
            return result is not None
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            return False

    def mpstats_item_full(
        self,
        item_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить полные данные о товаре.

        Read-only метод для получения детальной информации о товаре.

        Args:
            item_id: ID товара в MPStats

        Returns:
            Ответ API с данными о товаре или None при ошибке
        """
        endpoint = f"/item/{item_id}"
        
        self.logger.info(f"Fetching full item data for item_id={item_id}")
        return self.get(endpoint)

    def mpstats_item_sales(
        self,
        item_id: int,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить данные о продажах товара.

        Read-only метод для получения истории продаж товара.

        Args:
            item_id: ID товара в MPStats
            date_from: Дата начала периода (YYYY-MM-DD, опционально)
            date_to: Дата окончания периода (YYYY-MM-DD, опционально)

        Returns:
            Ответ API с данными о продажах или None при ошибке
        """
        endpoint = f"/item/{item_id}/sales"
        
        params = {}
        if date_from:
            params["dateFrom"] = date_from
        if date_to:
            params["dateTo"] = date_to
        
        self.logger.info(f"Fetching item sales for item_id={item_id}")
        return self.get(endpoint, params=params)

    def mpstats_item_by_category(
        self,
        category_id: int,
        limit: int = 100,
        offset: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить товары по категории.

        Read-only метод для получения списка товаров в категории.

        Args:
            category_id: ID категории
            limit: Количество записей
            offset: Смещение

        Returns:
            Ответ API со списком товаров или None при ошибке
        """
        endpoint = f"/category/{category_id}/items"
        
        params = {
            "limit": min(limit, 1000),
            "offset": offset,
        }
        
        self.logger.info(
            f"Fetching items by category={category_id}, limit={limit}, offset={offset}"
        )
        return self.get(endpoint, params=params)

    def mpstats_category_analytics(
        self,
        category_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить аналитику по категории.

        Read-only метод для получения статистики категории.

        Args:
            category_id: ID категории

        Returns:
            Ответ API с аналитикой категории или None при ошибке
        """
        endpoint = f"/category/{category_id}/analytics"
        
        self.logger.info(f"Fetching category analytics for category_id={category_id}")
        return self.get(endpoint)

    def mpstats_seller_info(
        self,
        seller_id: int,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить информацию о продавце.

        Read-only метод для получения данных о продавце.

        Args:
            seller_id: ID продавца

        Returns:
            Ответ API с информацией о продавце или None при ошибке
        """
        endpoint = f"/seller/{seller_id}"
        
        self.logger.info(f"Fetching seller info for seller_id={seller_id}")
        return self.get(endpoint)

    def mpstats_keywords(
        self,
        query: str,
        limit: int = 100,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить данные по ключевым словам.

        Read-only метод для получения статистики поисковых запросов.

        Args:
            query: Поисковый запрос
            limit: Количество записей

        Returns:
            Ответ API с данными по ключевым словам или None при ошибке
        """
        endpoint = "/keywords"
        
        params = {
            "query": query,
            "limit": min(limit, 1000),
        }
        
        self.logger.info(f"Fetching keywords for query='{query}'")
        return self.get(endpoint, params=params)
