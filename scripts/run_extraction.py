#!/usr/bin/env python3
"""
Main script to run all data extractors.

Usage:
    python scripts/run_extraction.py [--date-from YYYY-MM-DD] [--date-to YYYY-MM-DD] [--nm-ids 123,456,789] [--output-dir data/raw]

Example:
    python scripts/run_extraction.py --date-from 2025-05-26 --date-to 2025-05-28 --nm-ids 12345678,87654321,11223344
"""
import os
import sys
import json
import argparse
from datetime import datetime, timedelta
from typing import List, Optional

# Add src to path
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.utils.logger import get_logger
from src.extractors.products import run_extraction as run_products_extraction
from src.extractors.funnel import run_extraction as run_funnel_extraction
from src.extractors.stocks import run_extraction as run_stocks_extraction
from src.extractors.ads import run_extraction as run_ads_extraction
from src.extractors.search_queries import run_extraction as run_search_extraction
from src.extractors.finance import run_extraction as run_finance_extraction
from src.extractors.mpstat import run_extraction as run_mpstat_extraction

logger = get_logger(__name__)


def parse_args() -> argparse.Namespace:
    """Parse command line arguments."""
    parser = argparse.ArgumentParser(description="Run all data extractors")
    
    parser.add_argument(
        "--date-from",
        type=str,
        default=None,
        help="Start date (YYYY-MM-DD). Defaults to 2 days ago."
    )
    parser.add_argument(
        "--date-to",
        type=str,
        default=None,
        help="End date (YYYY-MM-DD). Defaults to today."
    )
    parser.add_argument(
        "--nm-ids",
        type=str,
        default=None,
        help="Comma-separated list of nmIDs. Defaults to test IDs."
    )
    parser.add_argument(
        "--output-dir",
        type=str,
        default="data/raw",
        help="Directory to save raw data. Defaults to data/raw."
    )
    
    return parser.parse_args()


def main():
    """Main entry point."""
    args = parse_args()
    
    # Parse dates
    date_from = args.date_from
    date_to = args.date_to
    
    if not date_to:
        date_to = datetime.now().strftime("%Y-%m-%d")
    if not date_from:
        date_from = (datetime.now() - timedelta(days=2)).strftime("%Y-%m-%d")
    
    # Parse nmIDs
    nm_ids = None
    if args.nm_ids:
        try:
            nm_ids = [int(x.strip()) for x in args.nm_ids.split(",")]
        except ValueError:
            logger.error("Invalid nmIDs format. Use comma-separated integers.")
            sys.exit(1)
    else:
        # Default test nmIDs (3-5 as per requirements)
        nm_ids = [12345678, 87654321, 11223344, 55667788, 99887766]
    
    output_dir = args.output_dir
    os.makedirs(output_dir, exist_ok=True)
    
    logger.info(f"Starting extraction process")
    logger.info(f"Date range: {date_from} to {date_to}")
    logger.info(f"nmIDs: {nm_ids}")
    logger.info(f"Output directory: {output_dir}")
    
    results = {}
    
    # Run all extractors
    logger.info("=" * 50)
    logger.info("Running Products Extractor (wb_content_cards_list)")
    results["products"] = run_products_extraction(
        nm_ids=nm_ids,
        date_from=date_from,
        date_to=date_to,
        output_dir=output_dir,
    )
    
    logger.info("=" * 50)
    logger.info("Running Funnel Extractor (wb_sales_funnel_history)")
    results["funnel"] = run_funnel_extraction(
        date_from=date_from,
        date_to=date_to,
        nm_ids=nm_ids,
        output_dir=output_dir,
    )
    
    logger.info("=" * 50)
    logger.info("Running Stocks Extractor (wb_stocks_products, wb_stocks_offices)")
    results["stocks"] = run_stocks_extraction(
        date_from=date_from,
        date_to=date_to,
        nm_ids=nm_ids,
        output_dir=output_dir,
    )
    
    logger.info("=" * 50)
    logger.info("Running Ads Extractor (wb_adv_costs, wb_adv_fullstats)")
    results["ads"] = run_ads_extraction(
        date_from=date_from,
        date_to=date_to,
        nm_ids=nm_ids,
        output_dir=output_dir,
    )
    
    logger.info("=" * 50)
    logger.info("Running Search Queries Extractor (wb_search_texts, wb_search_orders)")
    results["search_queries"] = run_search_extraction(
        date_from=date_from,
        date_to=date_to,
        nm_ids=nm_ids,
        output_dir=output_dir,
    )
    
    logger.info("=" * 50)
    logger.info("Running Finance Extractor (wb_statistics_orders, wb_report_detail_by_period)")
    results["finance"] = run_finance_extraction(
        date_from=date_from,
        date_to=date_to,
        nm_ids=nm_ids,
        output_dir=output_dir,
    )
    
    logger.info("=" * 50)
    logger.info("Running MPStats Extractor (mpstats_item_full, item_sales, item_by_category)")
    results["mpstat"] = run_mpstat_extraction(
        date_from=date_from,
        date_to=date_to,
        nm_ids=nm_ids,
        output_dir=output_dir,
    )
    
    # Save summary report
    summary = generate_summary(results, date_from, date_to, nm_ids, output_dir)
    
    summary_path = os.path.join(output_dir, f"extraction_summary_{datetime.now().strftime('%Y%m%d_%H%M%S')}.json")
    with open(summary_path, 'w', encoding='utf-8') as f:
        json.dump(summary, f, ensure_ascii=False, indent=2)
    
    logger.info(f"Summary saved to {summary_path}")
    
    # Print final status
    print("\n" + "=" * 60)
    print("EXTRACTION COMPLETE")
    print("=" * 60)
    print(json.dumps(summary, indent=2, ensure_ascii=False))
    
    return summary


def generate_summary(results: dict, date_from: str, date_to: str, nm_ids: List[int], output_dir: str) -> dict:
    """Generate extraction summary."""
    total_success = 0
    total_failed = 0
    total_skipped = 0
    files_created = []
    
    def process_result(source: str, result: dict):
        nonlocal total_success, total_failed, total_skipped, files_created
        
        if isinstance(result, dict):
            status = result.get("status", "unknown")
            if status == "success":
                total_success += 1
            elif status == "failed":
                total_failed += 1
            elif status == "skipped":
                total_skipped += 1
            
            if "file_path" in result and result["file_path"]:
                files_created.append(result["file_path"])
            
            # Handle nested results (like stocks, ads, etc.)
            for key, value in result.items():
                if isinstance(value, dict) and key not in ["source", "status", "file_path", "error"]:
                    process_result(f"{source}.{key}", value)
        elif isinstance(result, dict):
            for key, value in result.items():
                if isinstance(value, dict):
                    process_result(f"{source}.{key}", value)
    
    for extractor_name, result in results.items():
        process_result(extractor_name, result)
    
    return {
        "execution_date": datetime.now().isoformat(),
        "parameters": {
            "date_from": date_from,
            "date_to": date_to,
            "nm_ids": nm_ids,
            "output_dir": output_dir,
        },
        "summary": {
            "total_success": total_success,
            "total_failed": total_failed,
            "total_skipped": total_skipped,
            "files_created_count": len(files_created),
        },
        "files_created": files_created,
        "detailed_results": results,
    }


if __name__ == "__main__":
    main()
