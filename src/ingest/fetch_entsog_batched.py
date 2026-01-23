"""
Fetch ENTSOG flow data in batches to avoid API timeouts
"""
import logging
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))

from config import DB_PATH
from utils import GasMonitorDB, setup_logging
from ingest.fetch_entsog import ENTSOGFetcher

logger = logging.getLogger(__name__)


def fetch_entsog_batched(start_date: str, end_date: str, batch_days: int = 7):
    """
    Fetch ENTSOG data in small batches to avoid timeout
    
    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD)
        batch_days: Days per batch (default 7 - safe for ENTSOG)
    """
    
    logger.info(f"=== Batched ENTSOG Fetch ===")
    logger.info(f"Range: {start_date} to {end_date}")
    logger.info(f"Batch size: {batch_days} days\n")
    
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    
    # Calculate batches
    batches = []
    current = start
    
    while current <= end:
        batch_end = min(current + timedelta(days=batch_days - 1), end)
        batches.append((current, batch_end))
        current = batch_end + timedelta(days=1)
    
    logger.info(f"Created {len(batches)} batches:\n")
    
    # Fetch each batch
    fetcher = ENTSOGFetcher()
    total_rows = 0
    
    for i, (batch_start, batch_end) in enumerate(batches):
        logger.info(f"Batch {i+1}/{len(batches)}: {batch_start.date()} to {batch_end.date()}")
        
        df = fetcher.fetch_flows(
            start_date=batch_start.strftime('%Y-%m-%d'),
            end_date=batch_end.strftime('%Y-%m-%d'),
            use_cache=False
        )
        
        if df.empty:
            logger.warning(f"  No data returned")
            continue
        
        # Save to database
        with GasMonitorDB(DB_PATH) as db:
            # Clear this date range
            db.conn.execute(
                "DELETE FROM flows_raw WHERE date BETWEEN ? AND ?",
                [batch_start.date(), batch_end.date()]
            )
            
            db.insert_dataframe(df, 'flows_raw', if_exists='append')
        
        logger.info(f"  ✓ Saved {len(df)} rows\n")
        total_rows += len(df)
    
    return total_rows


def main():
    """Main execution"""
    
    import argparse
    
    parser = argparse.ArgumentParser(description='Fetch ENTSOG data in batches')
    parser.add_argument('--days', type=int, default=90,
                       help='Number of days to fetch')
    parser.add_argument('--batch-size', type=int, default=7,
                       help='Days per batch (default: 7)')
    
    args = parser.parse_args()
    
    setup_logging()
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')
    
    total = fetch_entsog_batched(start_date, end_date, args.batch_size)
    
    logger.info(f"\n=== Summary ===")
    logger.info(f"Total rows fetched: {total}")
    
    # Check database
    with GasMonitorDB(DB_PATH) as db:
        count = db.get_row_count('flows_raw')
        latest = db.get_latest_date('flows_raw')
        
        logger.info(f"Database now has: {count} flow records")
        logger.info(f"Latest date: {latest}")
    
    logger.info("\n✓ Complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
