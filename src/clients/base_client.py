"""
Базовый класс для API-клиентов.

Предоставляет общую функциональность:
- HTTP запросы с логированием
- Обработка ошибок (401, 403, 429, 500)
- Retry на 429 с паузой
- Сохранение raw-ответов
"""
import json
import time
from abc import ABC, abstractmethod
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, Optional

import requests
from requests.exceptions import RequestException, Timeout

from src.config.settings import DATA_RAW_DIR
from src.utils.logger import get_logger


class BaseAPIClient(ABC):
    """Базовый класс для всех API клиентов."""

    def __init__(self, base_url: str, token: str, logger_name: str = None):
        """
        Инициализировать клиент.

        Args:
            base_url: Базовый URL API
            token: Токен авторизации
            logger_name: Имя для логгера
        """
        self.base_url = base_url.rstrip("/")
        self.token = token
        self.logger = get_logger(logger_name or self.__class__.__name__)
        self._retry_count = 3
        self._retry_delay = 1.0  # секунды

    def _save_raw_response(self, endpoint: str, response_data: Any) -> None:
        """
        Сохранить raw-ответ в data/raw.

        Args:
            endpoint: Название эндпоинта
            response_data: Данные ответа
        """
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        safe_endpoint = endpoint.replace("/", "_").replace("?", "_").replace("=", "_")
        filename = f"{self.__class__.__name__}_{safe_endpoint}_{timestamp}.json"
        filepath = DATA_RAW_DIR / filename

        try:
            with open(filepath, "w", encoding="utf-8") as f:
                json.dump(response_data, f, ensure_ascii=False, indent=2)
            self.logger.debug(f"Raw response saved to {filepath}")
        except Exception as e:
            self.logger.warning(f"Failed to save raw response: {e}")

    def _log_request(self, method: str, url: str, elapsed: float, status_code: int) -> None:
        """
        Логировать запрос.

        Args:
            method: HTTP метод
            url: URL запроса
            elapsed: Время выполнения в секундах
            status_code: Код статуса ответа
        """
        self.logger.info(
            f"{method} {url} | Status: {status_code} | Time: {elapsed:.3f}s"
        )

    def request(
        self,
        method: str,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        timeout: int = 30,
        save_raw: bool = True,
    ) -> Optional[Dict[str, Any]]:
        """
        Выполнить HTTP запрос с обработкой ошибок и retry.

        Args:
            method: HTTP метод (GET/POST)
            endpoint: Эндпоинт относительно base_url
            params: Query параметры
            json_data: JSON тело запроса (для POST)
            headers: Дополнительные заголовки
            timeout: Таймаут запроса в секундах
            save_raw: Сохранять ли raw-ответ

        Returns:
            Ответ API в виде dict или None при ошибке

        Raises:
            RequestException: При критических ошибках
        """
        url = f"{self.base_url}/{endpoint.lstrip('/')}"
        request_headers = self._get_default_headers()
        if headers:
            request_headers.update(headers)

        for attempt in range(self._retry_count):
            start_time = time.time()
            try:
                response = requests.request(
                    method=method.upper(),
                    url=url,
                    params=params,
                    json=json_data,
                    headers=request_headers,
                    timeout=timeout,
                )
                elapsed = time.time() - start_time
                self._log_request(method, url, elapsed, response.status_code)

                # Обработка успешного ответа
                if response.status_code == 200:
                    try:
                        data = response.json()
                        if save_raw:
                            self._save_raw_response(endpoint, data)
                        return data
                    except json.JSONDecodeError:
                        self.logger.error(f"Invalid JSON response from {endpoint}")
                        return None

                # Обработка ошибок
                if response.status_code == 401:
                    self.logger.error(f"Unauthorized (401) for {endpoint}. Check token.")
                    raise RequestException(f"Unauthorized: {response.text}")

                if response.status_code == 403:
                    self.logger.error(f"Forbidden (403) for {endpoint}. Check permissions.")
                    raise RequestException(f"Forbidden: {response.text}")

                if response.status_code == 429:
                    retry_after = int(response.headers.get("Retry-After", self._retry_delay))
                    self.logger.warning(
                        f"Rate limited (429) for {endpoint}. Retry after {retry_after}s "
                        f"(attempt {attempt + 1}/{self._retry_count})"
                    )
                    if attempt < self._retry_count - 1:
                        time.sleep(retry_after)
                        continue
                    raise RequestException(f"Rate limit exceeded after {self._retry_count} attempts")

                if response.status_code >= 500:
                    self.logger.error(
                        f"Server error ({response.status_code}) for {endpoint}: {response.text}"
                    )
                    if attempt < self._retry_count - 1:
                        time.sleep(self._retry_delay * (attempt + 1))
                        continue
                    raise RequestException(f"Server error: {response.text}")

                # Другие ошибки
                self.logger.error(
                    f"Request failed ({response.status_code}) for {endpoint}: {response.text}"
                )
                return None

            except Timeout:
                elapsed = time.time() - start_time
                self.logger.warning(
                    f"Timeout for {endpoint} after {elapsed:.3f}s "
                    f"(attempt {attempt + 1}/{self._retry_count})"
                )
                if attempt < self._retry_count - 1:
                    time.sleep(self._retry_delay * (attempt + 1))
                    continue
                raise RequestException(f"Timeout after {self._retry_count} attempts")

            except RequestException:
                raise

            except Exception as e:
                elapsed = time.time() - start_time
                self.logger.error(f"Unexpected error for {endpoint}: {e}")
                if attempt < self._retry_count - 1:
                    time.sleep(self._retry_delay * (attempt + 1))
                    continue
                raise RequestException(f"Unexpected error: {e}")

        return None

    def get(
        self,
        endpoint: str,
        params: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        """Выполнить GET запрос."""
        return self.request("GET", endpoint, params=params, headers=headers, **kwargs)

    def post(
        self,
        endpoint: str,
        json_data: Optional[Dict[str, Any]] = None,
        headers: Optional[Dict[str, str]] = None,
        **kwargs,
    ) -> Optional[Dict[str, Any]]:
        """Выполнить POST запрос."""
        return self.request("POST", endpoint, json_data=json_data, headers=headers, **kwargs)

    def _get_default_headers(self) -> Dict[str, str]:
        """Получить заголовки по умолчанию."""
        return {
            "Content-Type": "application/json",
            "Accept": "application/json",
        }

    @abstractmethod
    def health_check(self) -> bool:
        """Проверить доступность API."""
        pass
