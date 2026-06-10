"""
Клиент для Wildberries Statistics API.

API документация: https://openapi.wildberries.ru/statistics/api/ru/index.html
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union

from src.clients.base_client import BaseAPIClient
from src.config.settings import WB_TOKEN
from src.utils.logger import get_logger


class WBStatisticsClient(BaseAPIClient):
    """Клиент для работы с Statistics API Wildberries."""

    BASE_URL = "https://statistics-api.wildberries.ru"

    def __init__(self, token: str = None):
        """
        Инициализировать клиент.

        Args:
            token: Токен авторизации (по умолчанию из env)
        """
        token = token or WB_TOKEN
        if not token:
            raise ValueError("WB_TOKEN не найден в переменных окружения")
        
        super().__init__(
            base_url=self.BASE_URL,
            token=token,
            logger_name="wb_statistics_client"
        )
        self.logger = get_logger("wb_statistics_client")

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
            # Пробуем получить данные о заказах
            result = self.wb_statistics_orders(date_from=datetime.now().date())
            return result is not None
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            return False

    def wb_statistics_orders(
        self,
        date_from: Union[date, str],
        date_to: Optional[Union[date, str]] = None,
        limit: int = 100,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить данные о заказах.

        Read-only метод для получения информации о заказах.

        Args:
            date_from: Дата начала периода (YYYY-MM-DD)
            date_to: Дата окончания периода (YYYY-MM-DD)
            limit: Количество записей (макс. 1000)

        Returns:
            Ответ API с данными о заказах или None при ошибке
        """
        endpoint = "/api/v1/supplier/orders"
        
        if isinstance(date_from, date):
            date_from = date_from.strftime("%Y-%m-%d")
        if date_to and isinstance(date_to, date):
            date_to = date_to.strftime("%Y-%m-%d")
        
        params = {
            "dateFrom": date_from,
            "limit": min(limit, 1000),
        }
        if date_to:
            params["dateTo"] = date_to
        
        self.logger.info(f"Fetching statistics orders: {date_from} to {date_to or 'now'}")
        return self.get(endpoint, params=params)

    def wb_report_detail_by_period(
        self,
        date_from: Union[date, str],
        date_to: Union[date, str],
        warehouses: Optional[List[int]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить детальный отчет за период.

        Read-only метод для получения детальной статистики продаж.

        Args:
            date_from: Дата начала периода (YYYY-MM-DD)
            date_to: Дата окончания периода (YYYY-MM-DD)
            warehouses: Список ID складов (опционально)

        Returns:
            Ответ API с детальным отчетом или None при ошибке
        """
        endpoint = "/api/v5/supplier/reportDetailByPeriod"
        
        if isinstance(date_from, date):
            date_from = date_from.strftime("%Y-%m-%d")
        if isinstance(date_to, date):
            date_to = date_to.strftime("%Y-%m-%d")
        
        params = {
            "dateFrom": date_from,
            "dateTo": date_to,
            "limit": 200,
            "rrdid": 0,
            "period": "daily",
        }
        if warehouses:
            params["warehouses"] = ",".join(map(str, warehouses))
        
        self.logger.info(f"Fetching detail report: {date_from} to {date_to}")
        return self.get(endpoint, params=params)

    def wb_statistics_stocks(
        self,
        date_from: Union[date, str],
        date_to: Optional[Union[date, str]] = None,
        limit: int = 100,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить данные об остатках.

        Read-only метод для получения информации об остатках на складах.

        Args:
            date_from: Дата начала периода (YYYY-MM-DD)
            date_to: Дата окончания периода (YYYY-MM-DD)
            limit: Количество записей (макс. 1000)

        Returns:
            Ответ API с данными об остатках или None при ошибке
        """
        endpoint = "/api/v1/stocks"
        
        if isinstance(date_from, date):
            date_from = date_from.strftime("%Y-%m-%d")
        if date_to and isinstance(date_to, date):
            date_to = date_to.strftime("%Y-%m-%d")
        
        params = {
            "dateFrom": date_from,
            "limit": min(limit, 1000),
        }
        if date_to:
            params["dateTo"] = date_to
        
        self.logger.info(f"Fetching statistics stocks: {date_from} to {date_to or 'now'}")
        return self.get(endpoint, params=params)

    def wb_statistics_income(
        self,
        date_from: Union[date, str],
        date_to: Optional[Union[date, str]] = None,
        limit: int = 100,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить данные о поступлениях.

        Read-only метод для получения информации о поступлениях товаров.

        Args:
            date_from: Дата начала периода (YYYY-MM-DD)
            date_to: Дата окончания периода (YYYY-MM-DD)
            limit: Количество записей (макс. 1000)

        Returns:
            Ответ API с данными о поступлениях или None при ошибке
        """
        endpoint = "/api/v1/income"
        
        if isinstance(date_from, date):
            date_from = date_from.strftime("%Y-%m-%d")
        if date_to and isinstance(date_to, date):
            date_to = date_to.strftime("%Y-%m-%d")
        
        params = {
            "dateFrom": date_from,
            "limit": min(limit, 1000),
        }
        if date_to:
            params["dateTo"] = date_to
        
        self.logger.info(f"Fetching statistics income: {date_from} to {date_to or 'now'}")
        return self.get(endpoint, params=params)
