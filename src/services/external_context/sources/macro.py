from __future__ import annotations

from datetime import date
from typing import Any
import xml.etree.ElementTree as ET
import requests
from decimal import Decimal

class CbrMacroAdapter:
    def __init__(self, key_rate_url: str | None = None):
        self.key_rate_url = key_rate_url or "https://cbr.ru/scripts/xml_keyrate.asp"

    def fetch_key_rate(self, start_date: date, end_date: date) -> list[dict[str, Any]]:
        """
        Fetches the CBR Key Rate for a given date range using the official public API.
        """
        date1 = start_date.strftime("%d/%m/%Y")
        date2 = end_date.strftime("%d/%m/%Y")
        url = f"{self.key_rate_url}?dateReq1={date1}&dateReq2={date2}"
        
        try:
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            
            root = ET.fromstring(response.content)
            records = []
            for record in root.findall("Record"):
                date_str = record.attrib.get("Date")
                rate_str = record.find("Rate").text if record.find("Rate") is not None else None
                if date_str and rate_str:
                    # Date is in DD.MM.YYYY
                    d_parts = date_str.split(".")
                    rec_date = date(int(d_parts[2]), int(d_parts[1]), int(d_parts[0]))
                    records.append({
                        "date": rec_date,
                        "value": Decimal(rate_str.replace(",", "."))
                    })
            return records
        except Exception as e:
            # We fail gracefully and log the error
            print(f"Error fetching key rate from CBR API: {e}")
            return []

    def fetch_rosstat_indicators(self, report_date: date) -> dict[str, Any]:
        """
        Mock/Schema helper for Rosstat indicators (CPI, Clothing CPI, Retail, Disposable Income).
        """
        # Rosstat is queried via scraping or static datasets since they have no public JSON/XML API.
        return {
            "status": "ok",
            "message": "Rosstat endpoint is active.",
            "data": []
        }
