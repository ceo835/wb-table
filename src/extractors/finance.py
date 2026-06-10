"""
Extractor for WB Statistics API - Finance and Orders Report.
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from src.clients.wb_statistics_client import WBStatisticsClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class FinanceExtractor:
    """Extractor for finance data from Wildberries Statistics API."""

    def __init__(self, output_dir: str = "data/raw"):
        self.client = WBStatisticsClient()
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def extract_statistics_orders(
        self,
        date_from: str,
        date_to: str,
        nm_ids: Optional[List[int]] = None,
    ) -> dict:
        """
        Extract statistics orders data.
        
        Args:
            date_from: Start date (YYYY-MM-DD).
            date_to: End date (YYYY-MM-DD).
            nm_ids: List of article IDs (nmID) to filter.
            
        Returns:
            Dictionary with extracted data and metadata.
        """
        logger.info(f"Starting extraction of statistics orders from {date_from} to {date_to}")
        
        try:
            response = self.client.wb_statistics_orders(
                date_from=date_from,
                date_to=date_to,
                nm_ids=nm_ids,
            )
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"wb_statistics_orders_{date_from}_{date_to}_{timestamp}.json"
            filepath = os.path.join(self.output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(response, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Saved raw data to {filepath}")
            
            records_count = 0
            if isinstance(response, dict):
                data = response.get('data', [])
                records_count = len(data) if isinstance(data, list) else 0
            
            return {
                "source": "wb_statistics_orders",
                "records_count": records_count,
                "file_path": filepath,
                "date_from": date_from,
                "date_to": date_to,
                "status": "success",
                "timestamp": timestamp,
            }
            
        except Exception as e:
            logger.error(f"Error extracting statistics orders: {e}")
            return {
                "source": "wb_statistics_orders",
                "records_count": 0,
                "error": str(e),
                "date_from": date_from,
                "date_to": date_to,
                "status": "failed",
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            }

    def extract_report_detail_by_period(
        self,
        date_from: str,
        date_to: str,
        nm_ids: Optional[List[int]] = None,
    ) -> dict:
        """
        Extract detailed report by period (finance data).
        
        Args:
            date_from: Start date (YYYY-MM-DD).
            date_to: End date (YYYY-MM-DD).
            nm_ids: List of article IDs (nmID) to filter.
            
        Returns:
            Dictionary with extracted data and metadata.
        """
        logger.info(f"Starting extraction of report detail by period from {date_from} to {date_to}")
        
        try:
            response = self.client.wb_report_detail_by_period(
                date_from=date_from,
                date_to=date_to,
                nm_ids=nm_ids,
            )
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"wb_report_detail_by_period_{date_from}_{date_to}_{timestamp}.json"
            filepath = os.path.join(self.output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(response, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Saved raw data to {filepath}")
            
            records_count = 0
            if isinstance(response, dict):
                data = response.get('data', [])
                records_count = len(data) if isinstance(data, list) else 0
            
            return {
                "source": "wb_report_detail_by_period",
                "records_count": records_count,
                "file_path": filepath,
                "date_from": date_from,
                "date_to": date_to,
                "status": "success",
                "timestamp": timestamp,
            }
            
        except Exception as e:
            logger.error(f"Error extracting report detail by period: {e}")
            return {
                "source": "wb_report_detail_by_period",
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
    Run all finance extractions.
    
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
    
    extractor = FinanceExtractor(output_dir=output_dir)
    
    results = {
        "statistics_orders": extractor.extract_statistics_orders(
            date_from=date_from, date_to=date_to, nm_ids=nm_ids
        ),
        "report_detail_by_period": extractor.extract_report_detail_by_period(
            date_from=date_from, date_to=date_to, nm_ids=nm_ids
        ),
    }
    
    return results


if __name__ == "__main__":
    result = run_extraction()
    print(json.dumps(result, indent=2, ensure_ascii=False))
