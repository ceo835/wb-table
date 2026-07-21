from __future__ import annotations

import logging
from datetime import date
from decimal import Decimal
from typing import Any
import requests

logger = logging.getLogger(__name__)

WORDSTAT_DYNAMICS_ENDPOINT = "https://searchapi.api.cloud.yandex.net/v2/wordstat/dynamics"
WORDSTAT_TOP_ENDPOINT = "https://searchapi.api.cloud.yandex.net/v2/wordstat/topRequests"

class YandexCloudWordstatAdapter:
    def __init__(self, api_key: str | None, folder_id: str | None):
        self.api_key = api_key
        self.folder_id = folder_id

    def fetch_search_demand(
        self,
        period_start: date,
        period_end: date,
        queries: list[str],
        category: str | None = None,
        region: str | None = None,
    ) -> dict[str, Any]:
        """
        Fetches search demand metrics from Yandex Cloud Search API v2 Wordstat service.
        """
        if not self.api_key or not self.folder_id:
            return {
                "status": "unavailable",
                "message": "YANDEX_SEARCH_API_KEY or YANDEX_CLOUD_FOLDER_ID is not configured.",
                "data": []
            }

        headers = {
            "Authorization": f"Api-Key {self.api_key}",
            "Content-Type": "application/json"
        }

        from datetime import timedelta
        duration_days = (period_end - period_start).days + 1
        prev_period_start = period_start - timedelta(days=duration_days)
        prev_period_end = period_end - timedelta(days=duration_days)
        # Simple date math for ISO strings
        from_date_str = f"{period_start.isoformat()}T00:00:00Z"
        to_date_str = f"{period_end.isoformat()}T23:59:59Z"

        results = []
        errors = []

        for query in queries:
            payload = {
                "folderId": self.folder_id,
                "phrase": query,
                "period": "PERIOD_WEEKLY",
                "fromDate": from_date_str,
                "toDate": to_date_str,
            }
            if region:
                try:
                    payload["regions"] = [int(region)]
                except (ValueError, TypeError):
                    pass

            try:
                response = requests.post(
                    WORDSTAT_DYNAMICS_ENDPOINT,
                    headers=headers,
                    json=payload,
                    timeout=15
                )

                if response.status_code == 200:
                    res_json = response.json()
                    dynamics = res_json.get("dynamics", []) or res_json.get("points", []) or []
                    
                    val_curr = Decimal("0")
                    val_prev = Decimal("0")

                    if len(dynamics) >= 2:
                        val_prev = Decimal(str(dynamics[-2].get("count") or dynamics[-2].get("value") or 0))
                        val_curr = Decimal(str(dynamics[-1].get("count") or dynamics[-1].get("value") or 0))
                    elif len(dynamics) == 1:
                        val_curr = Decimal(str(dynamics[0].get("count") or dynamics[0].get("value") or 0))

                    change_pct = Decimal("0")
                    if val_prev > Decimal("0"):
                        change_pct = ((val_curr - val_prev) / val_prev * Decimal("100")).quantize(Decimal("0.1"))

                    results.append({
                        "query_text": query,
                        "category": category or "general",
                        "period_start": period_start,
                        "period_end": period_end,
                        "value": val_curr,
                        "previous_value": val_prev,
                        "change_pct": change_pct,
                        "region": region,
                        "data_status": "ok",
                        "source_reference": "yandex_cloud_wordstat"
                    })

                else:
                    # Parse error details safely without revealing API key
                    try:
                        err_json = response.json()
                        err_msg = err_json.get("message") or str(err_json)
                    except Exception:
                        err_msg = response.text[:200]

                    if response.status_code == 401 or "Unknown api key" in err_msg:
                        error_type = "invalid API key"
                    elif response.status_code == 403 or "PermissionDenied" in err_msg or "permission" in err_msg.lower():
                        error_type = "permission denied"
                    elif "billing" in err_msg.lower():
                        error_type = "billing required"
                    else:
                        error_type = f"HTTP {response.status_code}"

                    errors.append(f"{query}: {error_type} ({err_msg})")
                    logger.error(f"Yandex Cloud Wordstat error for query '{query}': {error_type}")

            except requests.Timeout:
                errors.append(f"{query}: network timeout")
            except Exception as exc:
                errors.append(f"{query}: network error ({exc})")

        if not results and errors:
            return {
                "status": "error",
                "message": "; ".join(errors),
                "data": []
            }

        return {
            "status": "ok" if results else "unavailable",
            "message": "Data fetched successfully." if results else "No data received.",
            "data": results
        }
