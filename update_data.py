"""
Automated data update script for Gas Market Monitor

Fetches recent data from all sources and recomputes metrics.
Designed to run daily via GitHub Actions or manually for testing.

Usage:
    python update_data.py              # Fetch last 14 days (catches revisions)
    python update_data.py --days 7     # Fetch last 7 days
    python update_data.py --test       # Quick test with 3 days
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta
import argparse

# Add src to path
sys.path.append(str(Path(__file__).parent / "src"))

from utils import setup_logging
from config import DB_PATH, DEFAULT_FETCH_DAYS

logger = logging.getLogger(__name__)


def run_command(description, func, *args, **kwargs):
    """
    Run a command with error handling and logging

    Args:
        description: Human-readable description of what's being run
        func: Function to execute
        *args: Positional arguments for func
        **kwargs: Keyword arguments for func

    Returns:
        bool: True if successful, False if error
    """
    logger.info(f"\n{'='*70}")
    logger.info(f"{description}")
    logger.info(f"{'='*70}\n")

    try:
        result = func(*args, **kwargs)

        # Check if function returned an error code
        if result is not None and result != 0:
            logger.error(f"✗ {description} failed with code {result}")
            return False

        logger.info(f"\n✓ {description} completed successfully\n")
        return True

    except Exception as e:
        logger.error(f"✗ {description} failed with exception: {e}")
        import traceback
        logger.error(traceback.format_exc())
        return False


def fetch_storage(days):
    """Fetch storage data from AGSI"""
    from ingest.fetch_agsi import AGSIFetcher
    from config import GIE_API_KEY

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    logger.info(f"Fetching storage data: {start_date} to {end_date}")

    fetcher = AGSIFetcher(GIE_API_KEY)
    df = fetcher.fetch_storage(
        country="EU",
        start_date=start_date,
        end_date=end_date,
        use_cache=False
    )

    if df.empty:
        logger.error("No storage data fetched")
        return 1

    # Save to database
    from utils import GasMonitorDB

    with GasMonitorDB(DB_PATH) as db:
        # Clear existing data for this date range to avoid duplicates
        db.conn.execute(
            "DELETE FROM storage_raw WHERE date BETWEEN ? AND ?",
            [df['date'].min(), df['date'].max()]
        )

        db.insert_dataframe(df, 'storage_raw', if_exists='append')

        total_rows = db.get_row_count('storage_raw')
        latest_date = db.get_latest_date('storage_raw')

        logger.info(f"✓ Saved {len(df)} rows to database")
        logger.info(f"  Total storage records: {total_rows}")
        logger.info(f"  Latest date: {latest_date}")

    return 0


def fetch_flows(days):
    """Fetch flow data from ENTSOG"""
    from ingest.fetch_entsog_batched import fetch_entsog_batched

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    logger.info(f"Fetching flow data: {start_date} to {end_date}")

    total = fetch_entsog_batched(start_date, end_date, batch_days=7)

    logger.info(f"✓ Fetched {total} flow records")

    return 0 if total > 0 else 1


def fetch_weather(days):
    """Fetch weather data and calculate HDD"""
    from ingest.fetch_weather import WeatherFetcher
    from utils import GasMonitorDB

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    logger.info(f"Fetching weather data: {start_date} to {end_date}")

    fetcher = WeatherFetcher()
    df_regional = fetcher.fetch_weather(
        start_date=start_date,
        end_date=end_date,
        use_cache=False
    )

    if df_regional.empty:
        logger.error("No weather data fetched")
        return 1

    # Save to database
    with GasMonitorDB(DB_PATH) as db:
        # Clear existing data for this date range
        min_date = df_regional['date'].min()
        max_date = df_regional['date'].max()
        db.conn.execute(
            "DELETE FROM weather_raw WHERE date BETWEEN ? AND ?",
            [min_date, max_date]
        )

        # Convert datetime to date for database insertion
        df_to_insert = df_regional.copy()
        df_to_insert['date'] = df_to_insert['date'].dt.date
        df_to_insert = df_to_insert[['date', 'region', 'temp_mean_c', 'hdd', 'population_weight']]

        db.insert_dataframe(df_to_insert, 'weather_raw', if_exists='append')

        total = db.get_row_count('weather_raw')
        latest = db.get_latest_date('weather_raw')

        logger.info(f"✓ Saved {len(df_to_insert)} regional records")
        logger.info(f"  Total weather records: {total}")
        logger.info(f"  Latest date: {latest}")

    return 0


def fetch_ttf_prices(days):
    """Fetch TTF prices from Yahoo Finance"""
    import pandas as pd
    import yfinance as yf
    from utils import GasMonitorDB

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')

    logger.info(f"Fetching TTF prices: {start_date} to {end_date}")

    try:
        ttf = yf.Ticker("TTF=F")
        df = ttf.history(start=start_date, end=end_date, interval="1d")

        if df.empty:
            logger.warning("No TTF price data received (market may be closed)")
            return 0  # Not a critical error

        # Clean and format
        df = df.reset_index()
        df = df.rename(columns={'Date': 'date', 'Close': 'price_eur_mwh'})
        df = df[['date', 'price_eur_mwh']]
        df['date'] = pd.to_datetime(df['date']).dt.date
        df = df.drop_duplicates(subset='date', keep='last')
        df = df.sort_values('date')

        logger.info(f"✓ Fetched {len(df)} days of TTF prices")
        logger.info(f"  Latest price: €{df['price_eur_mwh'].iloc[-1]:.2f}/MWh")

        # Update derived_metrics table
        with GasMonitorDB(DB_PATH) as db:
            df_metrics = db.query("SELECT * FROM derived_metrics ORDER BY date")

            if df_metrics.empty:
                logger.warning("No derived_metrics yet - skipping price update")
                return 0

            # Convert dates
            df_metrics['date'] = pd.to_datetime(df_metrics['date']).dt.date
            df['date'] = pd.to_datetime(df['date']).dt.date

            # Merge
            df_merged = df_metrics.merge(
                df[['date', 'price_eur_mwh']],
                on='date',
                how='left',
                suffixes=('', '_new')
            )

            # Update column
            if 'price_eur_mwh_new' in df_merged.columns:
                df_merged['ttf_price_eur_mwh'] = df_merged['price_eur_mwh_new'].combine_first(
                    df_merged.get('ttf_price_eur_mwh', pd.Series())
                )
                df_merged = df_merged.drop(columns=['price_eur_mwh_new'])
            else:
                df_merged['ttf_price_eur_mwh'] = df_merged['price_eur_mwh']
                df_merged = df_merged.drop(columns=['price_eur_mwh'])

            # Forward-fill for weekends
            df_merged['ttf_price_eur_mwh'] = df_merged['ttf_price_eur_mwh'].fillna(method='ffill')

            # Replace table
            db.conn.execute("DELETE FROM derived_metrics")
            db.insert_dataframe(df_merged, 'derived_metrics', if_exists='append')

            price_count = df_merged['ttf_price_eur_mwh'].notna().sum()
            logger.info(f"  Updated prices: {price_count}/{len(df_merged)} rows have prices")

        return 0

    except Exception as e:
        logger.error(f"Failed to fetch TTF prices: {e}")
        return 1


def compute_metrics():
    """Compute storage metrics"""
    from transform.compute_storage_metrics import main as compute_storage_main

    return compute_storage_main()


def compute_indices():
    """Compute simple indices (adequacy, security)"""
    from transform.compute_simple_indices import main as compute_indices_main

    return compute_indices_main()


def main():
    """Main execution"""

    parser = argparse.ArgumentParser(
        description='Update gas market monitor data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        '--days',
        type=int,
        default=14,
        help='Number of days to fetch (default: 14, to catch data revisions)'
    )
    parser.add_argument(
        '--test',
        action='store_true',
        help='Quick test mode (3 days only)'
    )
    parser.add_argument(
        '--skip-prices',
        action='store_true',
        help='Skip TTF price fetch (useful if Yahoo Finance is down)'
    )

    args = parser.parse_args()

    # Setup logging
    setup_logging()

    # Determine days to fetch
    days = 3 if args.test else args.days

    logger.info("=" * 70)
    logger.info("GAS MARKET MONITOR - AUTOMATED DATA UPDATE")
    logger.info("=" * 70)
    logger.info(f"\nMode: {'TEST' if args.test else 'PRODUCTION'}")
    logger.info(f"Fetching last {days} days of data")
    logger.info(f"Database: {DB_PATH}")
    logger.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("")

    # Track success/failure
    steps = []

    # Step 1: Fetch storage data
    steps.append(('Fetch Storage Data', run_command(
        "STEP 1/6: Fetch Storage Data (AGSI)",
        fetch_storage,
        days
    )))

    # Step 2: Fetch flow data
    steps.append(('Fetch Flow Data', run_command(
        "STEP 2/6: Fetch Flow Data (ENTSOG)",
        fetch_flows,
        days
    )))

    # Step 3: Fetch weather data
    steps.append(('Fetch Weather Data', run_command(
        "STEP 3/6: Fetch Weather Data (Open-Meteo)",
        fetch_weather,
        days
    )))

    # Step 4: Fetch TTF prices (optional)
    if not args.skip_prices:
        steps.append(('Fetch TTF Prices', run_command(
            "STEP 4/6: Fetch TTF Prices (Yahoo Finance)",
            fetch_ttf_prices,
            days
        )))
    else:
        logger.info("\nSkipping TTF prices (--skip-prices flag)\n")
        steps.append(('Fetch TTF Prices', True))  # Mark as success

    # Step 5: Compute storage metrics
    steps.append(('Compute Storage Metrics', run_command(
        "STEP 5/6: Compute Storage Metrics",
        compute_metrics
    )))

    # Step 6: Compute indices
    steps.append(('Compute Indices', run_command(
        "STEP 6/6: Compute Simple Indices",
        compute_indices
    )))

    # Summary
    logger.info("\n" + "=" * 70)
    logger.info("UPDATE SUMMARY")
    logger.info("=" * 70)

    success_count = sum(1 for _, success in steps if success)
    total_count = len(steps)

    for step_name, success in steps:
        status = "✓ PASS" if success else "✗ FAIL"
        logger.info(f"{status:8} {step_name}")

    logger.info(f"\nResult: {success_count}/{total_count} steps completed successfully")
    logger.info(f"Finished: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)

    # Return exit code
    if success_count == total_count:
        logger.info("\n✓ All updates completed successfully!")
        return 0
    else:
        logger.error(f"\n✗ {total_count - success_count} step(s) failed")
        return 1


if __name__ == "__main__":
    sys.exit(main())
