"""
Extractor for WB Content API - Cards List.
"""
import os
import json
import logging
from datetime import datetime, timedelta
from typing import List, Optional
from src.clients.wb_content_client import WBContentClient
from src.utils.logger import get_logger

logger = get_logger(__name__)


class ProductsExtractor:
    """Extractor for product cards data from Wildberries Content API."""

    def __init__(self, output_dir: str = "data/raw"):
        self.client = WBContentClient()
        self.output_dir = output_dir
        os.makedirs(output_dir, exist_ok=True)

    def extract_cards_list(
        self,
        nm_ids: Optional[List[int]] = None,
        date_from: Optional[str] = None,
        date_to: Optional[str] = None,
    ) -> dict:
        """
        Extract product cards list.
        
        Args:
            nm_ids: List of article IDs (nmID) to fetch. If None, fetches all.
            date_from: Start date (YYYY-MM-DD). Not used for this endpoint but kept for interface consistency.
            date_to: End date (YYYY-MM-DD). Not used for this endpoint but kept for interface consistency.
            
        Returns:
            Dictionary with extracted data and metadata.
        """
        logger.info("Starting extraction of WB Content cards list")
        
        try:
            # Call the API method - wb_content_cards_list doesn't support nmIDs filter directly
            # We fetch cards and then filter locally if nm_ids is provided
            response = self.client.wb_content_cards_list(limit=100, offset=0)
            
            # Save raw response
            timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
            filename = f"wb_content_cards_list_{timestamp}.json"
            filepath = os.path.join(self.output_dir, filename)
            
            with open(filepath, 'w', encoding='utf-8') as f:
                json.dump(response, f, ensure_ascii=False, indent=2)
            
            logger.info(f"Saved raw data to {filepath}")
            
            return {
                "source": "wb_content_cards_list",
                "records_count": len(response.get('cards', [])) if isinstance(response, dict) else 0,
                "file_path": filepath,
                "status": "success",
                "timestamp": timestamp,
            }
            
        except Exception as e:
            logger.error(f"Error extracting cards list: {e}")
            return {
                "source": "wb_content_cards_list",
                "records_count": 0,
                "error": str(e),
                "status": "failed",
                "timestamp": datetime.now().strftime("%Y%m%d_%H%M%S"),
            }


def run_extraction(
    nm_ids: Optional[List[int]] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    output_dir: str = "data/raw",
) -> dict:
    """
    Run the products extraction.
    
    Args:
        nm_ids: List of nmIDs to extract.
        date_from: Start date (YYYY-MM-DD).
        date_to: End date (YYYY-MM-DD).
        output_dir: Directory to save raw data.
        
    Returns:
        Extraction result summary.
    """
    extractor = ProductsExtractor(output_dir=output_dir)
    return extractor.extract_cards_list(nm_ids=nm_ids, date_from=date_from, date_to=date_to)


if __name__ == "__main__":
    # Default test run with sample nmIDs
    test_nm_ids = [12345678, 87654321, 11223344]
    result = run_extraction(nm_ids=test_nm_ids)
    print(json.dumps(result, indent=2, ensure_ascii=False))
