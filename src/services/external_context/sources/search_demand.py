from __future__ import annotations

from datetime import date
from typing import Any
import requests

class YandexDirectSearchDemandAdapter:
    def __init__(self, token: str | None, client_login: str | None):
        self.token = token
        self.client_login = client_login

    def fetch_search_demand(
        self,
        period_start: date,
        period_end: date,
        queries: list[str],
        region: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetches search demand metrics from Yandex Direct Keyword selection API.
        """
        if not self.token:
            return {
                "status": "unavailable",
                "message": "YANDEX_DIRECT_TOKEN is not configured.",
                "data": []
            }
        
        # Real API request to Yandex Direct
        headers = {
            "Authorization": f"Bearer {self.token}",
            "Accept-Language": "ru",
            "Content-Type": "application/json; charset=utf-8"
        }
        if self.client_login:
            headers["Client-Login"] = self.client_login
            
        payload = {
            "method": "createNewWordstatReport",
            "params": {
                "Phrases": queries,
            }
        }
        
        try:
            # Note: Wordstat report creation is asynchronous in Yandex Direct.
            # This is a schema illustration of the API endpoint.
            response = requests.post(
                "https://api.direct.yandex.com/v5/wordstat",
                json=payload,
                headers=headers,
                timeout=15
            )
            response.raise_for_status()
            res_json = response.json()
            if "error" in res_json:
                return {
                    "status": "error",
                    "message": res_json["error"].get("error_detail") or res_json["error"].get("error_str"),
                    "data": []
                }
            
            return {
                "status": "ok",
                "message": "Data fetched successfully from Yandex Direct Wordstat API.",
                "data": res_json.get("result", [])
            }
        except Exception as e:
            return {
                "status": "error",
                "message": f"HTTP request failed: {e}",
                "data": []
            }
