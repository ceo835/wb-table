"""
Extractor for MPStats API - Item Full, Sales, and Category Data.
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from src.clients.mpstat_client import MPStatsClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class MPStatExtractor:
    """Extractor for data from MPStats API."""

    def __init__(self, output_dir: str = "data/raw"):
        self.client = MPStatsClient()
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def extract_item_full(
        self,
        nm_ids: List[int],
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict:
        """
        Extract full item data from MPStats.
        
        Args:
            nm_ids: List of article IDs (nmID) to fetch.
            date_from: Start date (YYYY-MM-DD). Optional.
            date_to: End date (YYYY-MM-DD). Optional.
            
        Returns:
            Dictionary with extracted data and metadata.
        """
        logger.info(f"Starting extraction of MPStats item full for {len(nm_ids)} items")
        
        try:
            response = self.client.mpstats_item_full(item_id=nm_ids[0] if nm_ids else 1)
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"mpstats_item_full_{timestamp}.json"
            filepath = os.path.join(self.output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(response, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Saved raw data to {filepath}")
            
            records_count = 0
            if isinstance(response, dict):
                data = response.get('data', [])
                records_count = len(data) if isinstance(data, list) else 0
            
            return {
                "source": "mpstats_item_full",
                "records_count": records_count,
                "file_path": filepath,
                "nm_ids_count": len(nm_ids),
                "status": "success",
                "timestamp": timestamp,
            }
            
        except Exception as e:
            logger.error(f"Error extracting MPStats item full: {e}")
            return {
                "source": "mpstats_item_full",
                "records_count": 0,
                "error": str(e),
                "nm_ids_count": len(nm_ids),
                "status": "failed",
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            }

    def extract_item_sales(
        self,
        nm_ids: List[int],
        date_from: str,
        date_to: str,
    ) -> dict:
        """
        Extract item sales data from MPStats.
        
        Args:
            nm_ids: List of article IDs (nmID) to fetch.
            date_from: Start date (YYYY-MM-DD).
            date_to: End date (YYYY-MM-DD).
            
        Returns:
            Dictionary with extracted data and metadata.
        """
        logger.info(f"Starting extraction of MPStats item sales from {date_from} to {date_to}")
        
        try:
            # MPStats API требует item_id, а не список nm_ids
            # Для демонстрации берем первый nmID из списка
            item_id = nm_ids[0] if nm_ids else 1
            response = self.client.mpstats_item_sales(
                item_id=item_id,
                date_from=date_from,
                date_to=date_to,
            )
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"mpstats_item_sales_{date_from}_{date_to}_{timestamp}.json"
            filepath = os.path.join(self.output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(response, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Saved raw data to {filepath}")
            
            records_count = 0
            if isinstance(response, dict):
                data = response.get('data', [])
                records_count = len(data) if isinstance(data, list) else 0
            
            return {
                "source": "mpstats_item_sales",
                "records_count": records_count,
                "file_path": filepath,
                "nm_ids_count": len(nm_ids),
                "date_from": date_from,
                "date_to": date_to,
                "status": "success",
                "timestamp": timestamp,
            }
            
        except Exception as e:
            logger.error(f"Error extracting MPStats item sales: {e}")
            return {
                "source": "mpstats_item_sales",
                "records_count": 0,
                "error": str(e),
                "nm_ids_count": len(nm_ids),
                "date_from": date_from,
                "date_to": date_to,
                "status": "failed",
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            }

    def extract_item_by_category(
        self,
        category_id: int,
        date_from: str,
        date_to: str,
        nm_ids: Optional[List[int]] = None,
    ) -> dict:
        """
        Extract item data by category from MPStats.
        
        Args:
            category_id: Category ID to fetch.
            date_from: Start date (YYYY-MM-DD).
            date_to: End date (YYYY-MM-DD).
            nm_ids: Optional list of article IDs to filter.
            
        Returns:
            Dictionary with extracted data and metadata.
        """
        logger.info(f"Starting extraction of MPStats item by category {category_id}")
        
        try:
            response = self.client.mpstats_item_by_category(
                category_id=category_id,
                limit=100,
                offset=0,
            )
            
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"mpstats_item_by_category_{category_id}_{date_from}_{date_to}_{timestamp}.json"
            filepath = os.path.join(self.output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(response, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Saved raw data to {filepath}")
            
            records_count = 0
            if isinstance(response, dict):
                data = response.get('data', [])
                records_count = len(data) if isinstance(data, list) else 0
            
            return {
                "source": "mpstats_item_by_category",
                "records_count": records_count,
                "file_path": filepath,
                "category_id": category_id,
                "date_from": date_from,
                "date_to": date_to,
                "status": "success",
                "timestamp": timestamp,
            }
            
        except Exception as e:
            logger.error(f"Error extracting MPStats item by category: {e}")
            return {
                "source": "mpstats_item_by_category",
                "records_count": 0,
                "error": str(e),
                "category_id": category_id,
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
    category_id: int = 1234,  # Default test category
) -> dict:
    """
    Run all MPStats extractions.
    
    Args:
        date_from: Start date (YYYY-MM-DD). Defaults to 2 days ago.
        date_to: End date (YYYY-MM-DD). Defaults to today.
        nm_ids: List of nmIDs to extract.
        output_dir: Directory to save raw data.
        category_id: Category ID for category-based extraction.
        
    Returns:
        Dictionary with results from all extractions.
    """
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    if not date_from:
        date_from = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    
    # Default test nmIDs if not provided
    if not nm_ids:
        nm_ids = [12345678, 87654321, 11223344, 55667788, 99887766]
    
    extractor = MPStatExtractor(output_dir=output_dir)
    
    results = {
        "item_full": extractor.extract_item_full(nm_ids=nm_ids),
        "item_sales": extractor.extract_item_sales(
            nm_ids=nm_ids,
            date_from=date_from,
            date_to=date_to,
        ),
        "item_by_category": extractor.extract_item_by_category(
            category_id=category_id,
            date_from=date_from,
            date_to=date_to,
            nm_ids=nm_ids,
        ),
    }
    
    return results


if __name__ == "__main__":
    result = run_extraction()
    print(json.dumps(result, indent=2, ensure_ascii=False))
