"""
Клиент для Wildberries Promotion API.

API документация: https://openapi.wildberries.ru/promotion/api/ru/index.html
"""
from datetime import date, datetime
from typing import Any, Dict, List, Optional, Union

from src.clients.base_client import BaseAPIClient
from src.config.settings import WB_TOKEN
from src.utils.logger import get_logger


class WBPromotionClient(BaseAPIClient):
    """Клиент для работы с Promotion API Wildberries."""

    BASE_URL = "https://advert-api.wildberries.ru"

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
            logger_name="wb_promotion_client"
        )
        self.logger = get_logger("wb_promotion_client")

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
            # Пробуем получить количество кампаний
            result = self.wb_promotion_count()
            return result is not None
        except Exception as e:
            self.logger.error(f"Health check failed: {e}")
            return False

    def wb_promotion_count(self) -> Optional[Dict[str, Any]]:
        """
        Получить количество рекламных кампаний.

        Read-only метод для получения информации о количестве кампаний.

        Returns:
            Ответ API с количеством кампаний или None при ошибке
        """
        endpoint = "/adv/v1/count"
        
        self.logger.info("Fetching promotion count")
        return self.get(endpoint)

    def wb_adv_costs(
        self,
        date_from: Union[date, str],
        date_to: Union[date, str],
    ) -> Optional[Dict[str, Any]]:
        """
        Получить данные о расходах на рекламу.

        Read-only метод для получения информации о затратах на рекламу.

        Args:
            date_from: Дата начала периода (YYYY-MM-DD)
            date_to: Дата окончания периода (YYYY-MM-DD)

        Returns:
            Ответ API с данными о расходах или None при ошибке
        """
        endpoint = "/adv/v1/costs"
        
        if isinstance(date_from, date):
            date_from = date_from.strftime("%Y-%m-%d")
        if isinstance(date_to, date):
            date_to = date_to.strftime("%Y-%m-%d")
        
        params = {
            "dateFrom": date_from,
            "dateTo": date_to,
        }
        
        self.logger.info(f"Fetching adv costs: {date_from} to {date_to}")
        return self.get(endpoint, params=params)

    def wb_adv_fullstats(
        self,
        date_from: Union[date, str],
        date_to: Union[date, str],
        campaign_ids: Optional[List[int]] = None,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить полную статистику по рекламным кампаниям.

        Read-only метод для получения детальной статистики рекламы.

        Args:
            date_from: Дата начала периода (YYYY-MM-DD)
            date_to: Дата окончания периода (YYYY-MM-DD)
            campaign_ids: Список ID кампаний (опционально)

        Returns:
            Ответ API с полной статистикой или None при ошибке
        """
        endpoint = "/adv/v1/fullstats"
        
        if isinstance(date_from, date):
            date_from = date_from.strftime("%Y-%m-%d")
        if isinstance(date_to, date):
            date_to = date_to.strftime("%Y-%m-%d")
        
        params = {
            "dateFrom": date_from,
            "dateTo": date_to,
        }
        if campaign_ids:
            params["campaignIds"] = ",".join(map(str, campaign_ids))
        
        self.logger.info(f"Fetching adv fullstats: {date_from} to {date_to}")
        return self.get(endpoint, params=params)

    def wb_adv_campaigns_list(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> Optional[Dict[str, Any]]:
        """
        Получить список рекламных кампаний.

        Read-only метод для получения списка кампаний.

        Args:
            limit: Количество записей
            offset: Смещение

        Returns:
            Ответ API со списком кампаний или None при ошибке
        """
        endpoint = "/adv/v1/campaigns/list"
        
        params = {
            "limit": min(limit, 1000),
            "offset": offset,
        }
        
        self.logger.info(f"Fetching campaigns list: limit={limit}, offset={offset}")
        return self.get(endpoint, params=params)

    def wb_adv_stats_summary(
        self,
        date_from: Union[date, str],
        date_to: Union[date, str],
    ) -> Optional[Dict[str, Any]]:
        """
        Получить сводную статистику по рекламе.

        Read-only метод для получения сводных данных.

        Args:
            date_from: Дата начала периода (YYYY-MM-DD)
            date_to: Дата окончания периода (YYYY-MM-DD)

        Returns:
            Ответ API со сводной статистикой или None при ошибке
        """
        endpoint = "/adv/v1/stats/summary"
        
        if isinstance(date_from, date):
            date_from = date_from.strftime("%Y-%m-%d")
        if isinstance(date_to, date):
            date_to = date_to.strftime("%Y-%m-%d")
        
        params = {
            "dateFrom": date_from,
            "dateTo": date_to,
        }
        
        self.logger.info(f"Fetching adv stats summary: {date_from} to {date_to}")
        return self.get(endpoint, params=params)
