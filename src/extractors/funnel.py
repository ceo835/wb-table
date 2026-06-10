"""
Extractor for WB Analytics API - Sales Funnel History.
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from src.clients.wb_analytics_client import WBAnalyticsClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class FunnelExtractor:
    """Extractor for sales funnel data from Wildberries Analytics API."""

    def __init__(self, output_dir: str = "data/raw"):
        self.client = WBAnalyticsClient()
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def extract_sales_funnel_history(
        self,
        date_from: str,
        date_to: str,
        nm_ids: Optional[List[int]] = None,
    ) -> dict:
        """
        Extract sales funnel history.
        
        Args:
            date_from: Start date (YYYY-MM-DD).
            date_to: End date (YYYY-MM-DD).
            nm_ids: List of article IDs (nmID) to filter. If None, fetches all.
            
        Returns:
            Dictionary with extracted data and metadata.
        """
        logger.info(f"Starting extraction of sales funnel history from {date_from} to {date_to}")
        
        try:
            # Call the API method with correct method name
            response = self.client.wb_sales_funnel_history(
                date_from=date_from,
                date_to=date_to,
            )
            
            # Save raw response
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"wb_sales_funnel_history_{date_from}_{date_to}_{timestamp}.json"
            filepath = os.path.join(self.output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(response, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Saved raw data to {filepath}")
            
            # Count records if possible
            records_count = 0
            if isinstance(response, dict):
                data = response.get('data', [])
                records_count = len(data) if isinstance(data, list) else 0
            
            return {
                "source": "wb_sales_funnel_history",
                "records_count": records_count,
                "file_path": filepath,
                "date_from": date_from,
                "date_to": date_to,
                "status": "success",
                "timestamp": timestamp,
            }
            
        except Exception as e:
            logger.error(f"Error extracting sales funnel history: {e}")
            return {
                "source": "wb_sales_funnel_history",
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
    Run the funnel extraction.
    
    Args:
        date_from: Start date (YYYY-MM-DD). Defaults to 2 days ago.
        date_to: End date (YYYY-MM-DD). Defaults to today.
        nm_ids: List of nmIDs to extract.
        output_dir: Directory to save raw data.
        
    Returns:
        Extraction result summary.
    """
    # Default to last 2 days if not specified
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    if not date_from:
        date_from = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    
    extractor = FunnelExtractor(output_dir=output_dir)
    return extractor.extract_sales_funnel_history(
        date_from=date_from,
        date_to=date_to,
        nm_ids=nm_ids,
    )


if __name__ == "__main__":
    # Default test run for last 2 days
    result = run_extraction()
    print(json.dumps(result, indent=2, ensure_ascii=False))
