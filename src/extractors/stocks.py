"""
Extractor for WB Analytics API - Stocks (Products and Offices).
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from src.clients.wb_analytics_client import WBAnalyticsClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class StocksExtractor:
    """Extractor for stocks data from Wildberries Analytics API."""

    def __init__(self, output_dir: str = "data/raw"):
        self.client = WBAnalyticsClient()
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def extract_stocks_products(
        self,
        date_from: str,
        date_to: str,
        nm_ids: Optional[List[int]] = None,
    ) -> dict:
        """
        Extract stocks products data.
        
        Args:
            date_from: Start date (YYYY-MM-DD).
            date_to: End date (YYYY-MM-DD).
            nm_ids: List of article IDs (nmID) to filter.
            
        Returns:
            Dictionary with extracted data and metadata.
        """
        logger.info(f"Starting extraction of stocks products from {date_from} to {date_to}")
        
        try:
            response = self.client.wb_stocks_products(
                date_from=date_from,
                date_to=date_to,
                nm_ids=nm_ids,
            )
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"wb_stocks_products_{date_from}_{date_to}_{timestamp}.json"
            filepath = os.path.join(self.output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(response, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Saved raw data to {filepath}")
            
            records_count = 0
            if isinstance(response, dict):
                data = response.get('data', [])
                records_count = len(data) if isinstance(data, list) else 0
            
            return {
                "source": "wb_stocks_products",
                "records_count": records_count,
                "file_path": filepath,
                "date_from": date_from,
                "date_to": date_to,
                "status": "success",
                "timestamp": timestamp,
            }
            
        except Exception as e:
            logger.error(f"Error extracting stocks products: {e}")
            return {
                "source": "wb_stocks_products",
                "records_count": 0,
                "error": str(e),
                "date_from": date_from,
                "date_to": date_to,
                "status": "failed",
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            }

    def extract_stocks_offices(
        self,
        date_from: str,
        date_to: str,
        nm_ids: Optional[List[int]] = None,
    ) -> dict:
        """
        Extract stocks offices data.
        
        Args:
            date_from: Start date (YYYY-MM-DD).
            date_to: End date (YYYY-MM-DD).
            nm_ids: List of article IDs (nmID) to filter.
            
        Returns:
            Dictionary with extracted data and metadata.
        """
        logger.info(f"Starting extraction of stocks offices from {date_from} to {date_to}")
        
        try:
            response = self.client.wb_stocks_offices(
                date_from=date_from,
                date_to=date_to,
                nm_ids=nm_ids,
            )
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"wb_stocks_offices_{date_from}_{date_to}_{timestamp}.json"
            filepath = os.path.join(self.output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(response, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Saved raw data to {filepath}")
            
            records_count = 0
            if isinstance(response, dict):
                data = response.get('data', [])
                records_count = len(data) if isinstance(data, list) else 0
            
            return {
                "source": "wb_stocks_offices",
                "records_count": records_count,
                "file_path": filepath,
                "date_from": date_from,
                "date_to": date_to,
                "status": "success",
                "timestamp": timestamp,
            }
            
        except Exception as e:
            logger.error(f"Error extracting stocks offices: {e}")
            return {
                "source": "wb_stocks_offices",
                "records_count": 0,
                "error": str(e),
                "date_from": date_from,
                "date_to": date_to,
                "status": "failed",
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            }

    def extract_stock_history_daily_csv(
        self,
        date_from: str,
        date_to: str,
        nm_ids: Optional[List[int]] = None,
    ) -> dict:
        """
        Extract stock history daily CSV (if available).
        
        Args:
            date_from: Start date (YYYY-MM-DD).
            date_to: End date (YYYY-MM-DD).
            nm_ids: List of article IDs (nmID) to filter.
            
        Returns:
            Dictionary with extracted data and metadata.
        """
        logger.info(f"Starting extraction of stock history daily CSV from {date_from} to {date_to}")
        
        try:
            # Try to call the method if it exists
            if not hasattr(self.client, 'stock_history_daily_csv'):
                logger.warning("stock_history_daily_csv method not available in client")
                return {
                    "source": "wb_stock_history_daily_csv",
                    "records_count": 0,
                    "error": "Method not available",
                    "date_from": date_from,
                    "date_to": date_to,
                    "status": "skipped",
                    "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
                }
            
            response = self.client.wb_stock_history_daily_csv(
                date_from=date_from,
                date_to=date_to,
                nm_ids=nm_ids,
            )
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"wb_stock_history_daily_csv_{date_from}_{date_to}_{timestamp}.csv"
            filepath = os.path.join(self.output_dir, filename)
            
            # Handle CSV response
            if isinstance(response, str):
                with open(filepath, 'w', encoding='utf-8') as f:
                    f.write(response)
            else:
                with open(filepath, 'w', encoding='utf-8') as f:
                    json.dump(response, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Saved raw data to {filepath}")
            
            return {
                "source": "wb_stock_history_daily_csv",
                "file_path": filepath,
                "date_from": date_from,
                "date_to": date_to,
                "status": "success",
                "timestamp": timestamp,
            }
            
        except Exception as e:
            logger.error(f"Error extracting stock history daily CSV: {e}")
            return {
                "source": "wb_stock_history_daily_csv",
                "records_count": 0,
                "error": str(e),
                "date_from": date_from,
                "date_to": date_to,
                "status": "failed",
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            }


def run_extraction(
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    nm_ids: Optional[List[int]] = None,
    output_dir: str = "data/raw",
) -> dict:
    """
    Run all stocks extractions.
    
    Args:
        date_from: Start date (YYYY-MM-DD). Defaults to 2 days ago.
        date_to: End date (YYYY-MM-DD). Defaults to today.
        nm_ids: List of nmIDs to extract.
        output_dir: Directory to save raw data.
        
    Returns:
        Dictionary with results from all extractions.
    """
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    if not date_from:
        date_from = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    
    extractor = StocksExtractor(output_dir=output_dir)
    
    results = {
        "stocks_products": extractor.extract_stocks_products(
            date_from=date_from, date_to=date_to, nm_ids=nm_ids
        ),
        "stocks_offices": extractor.extract_stocks_offices(
            date_from=date_from, date_to=date_to, nm_ids=nm_ids
        ),
        "stock_history_daily_csv": extractor.extract_stock_history_daily_csv(
            date_from=date_from, date_to=date_to, nm_ids=nm_ids
        ),
    }
    
    return results


if __name__ == "__main__":
    result = run_extraction()
    print(json.dumps(result, indent=2, ensure_ascii=False))
