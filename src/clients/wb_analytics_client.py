"""
Клиент для Wildberries Analytics API.

API документация: https://openapi.wildberries.ru/analytics/api/ru/index.html
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union

from src.clients.base_client import BaseAPIClient
from src.config.settings import WB_ANALYTICS_TOKEN
from src.utils.logger import get_logger


class WBAnalyticsClient(BaseAPIClient):
    """Клиент для работы с Analytics API Wildberries."""

    BASE_URL = "https://analytics-api.wildberries.ru"

    def __init__(self, token: str = None):
        """
        Инициализировать клиент.

        Args:
            token: Токен авторизации (по умолчанию из env)
        """
        token = token or WB_ANALYTICS_TOKEN
        if not token:
            raise ValueError("WB_ANALYTICS_TOKEN не найден в переменных окружения")
        
        super().__init__(
            base_url=self.BASE_URL,
            token=token,
            logger_name="wb_analytics_client"
        )
        self.logger = get_logger("wb_analytics_client")

    def _get_default_headers(self) -> Dict[str, str]:
        """Получить заголовки с авторизацией."""
        headers = super()._get_default_headers()
        headers["Authorization"] = self.token
        return headers

    def health_check(self) -> bool:
        """
        Проверить доступность API.

        Returns:
            True если API доступен
        """
        try:
            # Пробуем получить данные о запасах на складах
            result = self.wb_stocks_products(date_from=datetime.now().date())
            return result is not None
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            return False

    def wb_sales_funnel_history(
        self,
        date_from: Union[date, str],
        date_to: Union[date, str],
    ) -> Optional[Dict[str, Any]]:
        """
        Получить историю воронки продаж.

        Read-only метод для получения данных о конверсиях.

        Args:
            date_from: Дата начала периода (YYYY-MM-DD)
            date_to: Дата окончания периода (YYYY-MM-DD)

        Returns:
            Ответ API с данными воронки продаж или None при ошибке
        """
        endpoint = "/ru/v1/sales/funnel/history"
        
        if isinstance(date_from, date):
            date_from = date_from.strftime("%Y-%m-%d")
        if isinstance(date_to, date):
            date_to = date_to.strftime("%Y-%m-%d")
        
        params = {
            "dateFrom": date_from,
            "dateTo": date_to,
        }
        
        self.logger.info(f"Fetching sales funnel history: {date_from} to {date_to}")
        return self.get(endpoint, params=params)

    def wb_stocks_products(
        self,
        date_from: Union[date, str],
        warehouses: Optional[List[int]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить остатки товаров на складах.

        Read-only метод для получения информации об остатках.

        Args:
            date_from: Дата начала периода (YYYY-MM-DD)
            warehouses: Список ID складов (опционально)

        Returns:
            Ответ API с данными об остатках или None при ошибке
        """
        endpoint = "/ru/v1/stocks/products"
        
        if isinstance(date_from, date):
            date_from = date_from.strftime("%Y-%m-%d")
        
        params = {"dateFrom": date_from}
        if warehouses:
            params["warehouses"] = ",".join(map(str, warehouses))
        
        self.logger.info(f"Fetching stocks products from {date_from}")
        return self.get(endpoint, params=params)

    def wb_stocks_offices(
        self,
        date_from: Union[date, str],
    ) -> Optional[Dict[str, Any]]:
        """
        Получить остатки по офисам.

        Read-only метод для получения информации об остатках в офисах.

        Args:
            date_from: Дата начала периода (YYYY-MM-DD)

        Returns:
            Ответ API с данными об остатках в офисах или None при ошибке
        """
        endpoint = "/ru/v1/stocks/offices"
        
        if isinstance(date_from, date):
            date_from = date_from.strftime("%Y-%m-%d")
        
        params = {"dateFrom": date_from}
        
        self.logger.info(f"Fetching stocks offices from {date_from}")
        return self.get(endpoint, params=params)

    def wb_region_sale(
        self,
        date_from: Union[date, str],
        date_to: Union[date, str],
    ) -> Optional[Dict[str, Any]]:
        """
        Получить продажи по регионам.

        Read-only метод для получения географии продаж.

        Args:
            date_from: Дата начала периода (YYYY-MM-DD)
            date_to: Дата окончания периода (YYYY-MM-DD)

        Returns:
            Ответ API с данными о продажах по регионам или None при ошибке
        """
        endpoint = "/ru/v1/sales/region"
        
        if isinstance(date_from, date):
            date_from = date_from.strftime("%Y-%m-%d")
        if isinstance(date_to, date):
            date_to = date_to.strftime("%Y-%m-%d")
        
        params = {
            "dateFrom": date_from,
            "dateTo": date_to,
        }
        
        self.logger.info(f"Fetching region sales: {date_from} to {date_to}")
        return self.get(endpoint, params=params)

    def wb_search_texts(
        self,
        date_from: Union[date, str],
        date_to: Union[date, str],
        limit: int = 100,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить поисковые запросы.

        Read-only метод для получения популярных поисковых запросов.

        Args:
            date_from: Дата начала периода (YYYY-MM-DD)
            date_to: Дата окончания периода (YYYY-MM-DD)
            limit: Количество записей

        Returns:
            Ответ API с поисковыми запросами или None при ошибке
        """
        endpoint = "/ru/v1/search/texts"
        
        if isinstance(date_from, date):
            date_from = date_from.strftime("%Y-%m-%d")
        if isinstance(date_to, date):
            date_to = date_to.strftime("%Y-%m-%d")
        
        params = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "limit": min(limit, 1000),
        }
        
        self.logger.info(f"Fetching search texts: {date_from} to {date_to}")
        return self.get(endpoint, params=params)

    def wb_search_orders(
        self,
        date_from: Union[date, str],
        date_to: Union[date, str],
        limit: int = 100,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить заказы из поиска.

        Read-only метод для получения информации о заказах из поиска.

        Args:
            date_from: Дата начала периода (YYYY-MM-DD)
            date_to: Дата окончания периода (YYYY-MM-DD)
            limit: Количество записей

        Returns:
            Ответ API с заказами из поиска или None при ошибке
        """
        endpoint = "/ru/v1/search/orders"
        
        if isinstance(date_from, date):
            date_from = date_from.strftime("%Y-%m-%d")
        if isinstance(date_to, date):
            date_to = date_to.strftime("%Y-%m-%d")
        
        params = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "limit": min(limit, 1000),
        }
        
        self.logger.info(f"Fetching search orders: {date_from} to {date_to}")
        return self.get(endpoint, params=params)
