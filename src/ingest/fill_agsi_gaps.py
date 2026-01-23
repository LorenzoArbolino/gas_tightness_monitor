"""
Fill gaps in AGSI storage data
"""
import pandas as pd
import logging
from datetime import datetime, timedelta
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))

from config import DB_PATH, HISTORY_START_DATE
from utils import GasMonitorDB, setup_logging
from ingest.fetch_agsi import AGSIFetcher

logger = logging.getLogger(__name__)


def find_gaps(df: pd.DataFrame) -> list:
    """Find date gaps in the data"""
    
    df = df.sort_values('date').copy()
    df['date'] = pd.to_datetime(df['date'])
    
    # Create full date range
    full_range = pd.date_range(df['date'].min(), df['date'].max(), freq='D')
    existing_dates = set(df['date'])
    
    gaps = []
    for date in full_range:
        if date not in existing_dates:
            gaps.append(date)
    
    return sorted(gaps)


def fill_gaps_in_batches(gaps: list, batch_size: int = 90):
    """Fill gaps by fetching data in batches"""
    
    if not gaps:
        logger.info("No gaps to fill!")
        return
    
    logger.info(f"Found {len(gaps)} missing dates")
    logger.info(f"  First gap: {gaps[0]}")
    logger.info(f"  Last gap: {gaps[-1]}\n")
    
    # Group consecutive gaps into batches
    batches = []
    current_batch_start = gaps[0]
    current_batch_end = gaps[0]
    
    for i in range(1, len(gaps)):
        if (gaps[i] - gaps[i-1]).days <= 1:
            # Consecutive gap
            current_batch_end = gaps[i]
        else:
            # New batch
            batches.append((current_batch_start, current_batch_end))
            current_batch_start = gaps[i]
            current_batch_end = gaps[i]
    
    # Add last batch
    batches.append((current_batch_start, current_batch_end))
    
    logger.info(f"Grouped into {len(batches)} batches:")
    for i, (start, end) in enumerate(batches):
        days = (end - start).days + 1
        logger.info(f"  Batch {i+1}: {start.date()} to {end.date()} ({days} days)")
    
    # Fetch each batch
    from config import GIE_API_KEY
    fetcher = AGSIFetcher(GIE_API_KEY)
    
    for i, (start, end) in enumerate(batches):
        logger.info(f"\nFetching batch {i+1}/{len(batches)}...")
        
        df = fetcher.fetch_storage(
            country='EU',
            start_date=start.strftime('%Y-%m-%d'),
            end_date=end.strftime('%Y-%m-%d'),
            use_cache=False  # Force fresh fetch
        )
        
        if df.empty:
            logger.warning(f"  No data returned for batch {i+1}")
            continue
        
        # Save to database
        with GasMonitorDB(DB_PATH) as db:
            # Clear this date range first
            db.conn.execute(
                "DELETE FROM storage_raw WHERE date BETWEEN ? AND ?",
                [start.date(), end.date()]
            )
            
            db.insert_dataframe(df, 'storage_raw', if_exists='append')
        
        logger.info(f"  ✓ Saved {len(df)} days")


def main():
    """Main execution"""
    
    setup_logging()
    logger.info("=== AGSI Data Gap Filler ===\n")
    
    # Load current data
    with GasMonitorDB(DB_PATH) as db:
        df = db.query("SELECT date FROM storage_raw ORDER BY date")
    
    if df.empty:
        logger.error("No storage data found! Run fetch_agsi.py first.")
        return 1
    
    logger.info(f"Current data: {len(df)} days")
    logger.info(f"Range: {df['date'].min()} to {df['date'].max()}\n")
    
    # Find gaps
    gaps = find_gaps(df)
    
    if not gaps:
        logger.info("✓ No gaps found - data is complete!")
        return 0
    
    # Fill gaps
    fill_gaps_in_batches(gaps)
    
    # Verify
    logger.info("\n=== Verification ===")
    with GasMonitorDB(DB_PATH) as db:
        df_new = db.query("SELECT date FROM storage_raw ORDER BY date")
    
    gaps_after = find_gaps(df_new)
    
    logger.info(f"Data now: {len(df_new)} days")
    logger.info(f"Remaining gaps: {len(gaps_after)}")
    
    if gaps_after:
        logger.warning(f"\nStill have {len(gaps_after)} gaps - may need manual intervention")
        logger.warning("First 10 missing dates:")
        for gap in gaps_after[:10]:
            logger.warning(f"  {gap.date()}")
    else:
        logger.info("\n✓ All gaps filled!")
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
