"""
Automated data update script for Gas Market Monitor

Fetches recent data from all sources, recomputes metrics and exports the JSON
used by the static dashboard. Designed to run daily via GitHub Actions or
manually for testing.

Each source is fetched from a few days before its latest stored date (or the
last --days, whichever is earlier), so revisions are picked up and a gap left
by an outage is filled automatically on the next run.

Usage:
    python update_data.py              # Normal daily update
    python update_data.py --days 30    # Re-fetch at least the last 30 days
    python update_data.py --skip-prices
"""

import sys
import logging
from pathlib import Path
from datetime import datetime, timedelta
import argparse

# Add src to path
sys.path.append(str(Path(__file__).parent / "src"))

from utils import setup_logging, GasMonitorDB
from config import DB_PATH

logger = logging.getLogger(__name__)

# How many days before the latest stored date to re-fetch (reporting revisions)
REVISION_DAYS = 7


def fetch_start(table: str, days: int) -> str:
    """Earlier of (latest stored date - REVISION_DAYS) and (today - days)."""
    with GasMonitorDB(DB_PATH) as db:
        db.init_schema()
        latest = db.get_latest_date(table)
    start = datetime.now() - timedelta(days=days)
    if latest:
        start = min(start, datetime.strptime(latest, '%Y-%m-%d') - timedelta(days=REVISION_DAYS))
    return start.strftime('%Y-%m-%d')


def run_command(description, func, *args, **kwargs):
    """Run a step, log the outcome and return True on success."""
    logger.info(f"\n{'='*70}\n{description}\n{'='*70}\n")

    try:
        result = func(*args, **kwargs)
        if result is not None and result != 0:
            logger.error(f"✗ {description} failed with code {result}")
            return False
        logger.info(f"\n✓ {description} completed successfully\n")
        return True
    except Exception as e:
        logger.exception(f"✗ {description} failed with exception: {e}")
        return False


def fetch_storage(days):
    """Fetch storage data from AGSI"""
    from ingest.fetch_agsi import AGSIFetcher
    from config import GIE_API_KEY

    start_date = fetch_start('storage_raw', days)
    end_date = datetime.now().strftime('%Y-%m-%d')
    logger.info(f"Fetching storage data: {start_date} to {end_date}")

    fetcher = AGSIFetcher(GIE_API_KEY)
    df = fetcher.fetch_storage(country="EU", start_date=start_date, end_date=end_date, use_cache=False)

    if df.empty:
        logger.error("No storage data fetched")
        return 1

    with GasMonitorDB(DB_PATH) as db:
        db.conn.execute(
            "DELETE FROM storage_raw WHERE date BETWEEN ? AND ?",
            [df['date'].min(), df['date'].max()]
        )
        db.insert_dataframe(df, 'storage_raw', if_exists='append')
        logger.info(f"✓ Saved {len(df)} rows, latest date: {db.get_latest_date('storage_raw')}")

    return 0


def fetch_flows(days):
    """Fetch EU border flows from ENTSOG"""
    from ingest.fetch_border_flows import fetch_and_save

    start_date = fetch_start('border_flows', days)
    end_date = datetime.now().strftime('%Y-%m-%d')
    logger.info(f"Fetching border flows: {start_date} to {end_date}")

    total = fetch_and_save(start_date, end_date)
    logger.info(f"✓ Fetched {total} flow records")
    return 0 if total > 0 else 1


def fetch_ttf_prices(days):
    """Fetch TTF front-month prices from Yahoo Finance"""
    import pandas as pd
    import yfinance as yf

    start_date = fetch_start('prices', days)
    # yfinance's end bound is exclusive
    end_date = (datetime.now() + timedelta(days=1)).strftime('%Y-%m-%d')
    logger.info(f"Fetching TTF prices: {start_date} to {end_date}")

    df = yf.Ticker("TTF=F").history(start=start_date, end=end_date, interval="1d")
    if df.empty:
        logger.warning("No TTF price data received")
        return 1

    df = df.reset_index()
    df = pd.DataFrame({
        'date': pd.to_datetime(df['Date']).dt.date,
        'ttf_eur_mwh': df['Close'],
    }).drop_duplicates(subset='date', keep='last')

    with GasMonitorDB(DB_PATH) as db:
        db.conn.execute(
            "DELETE FROM prices WHERE date BETWEEN ? AND ?",
            [df['date'].min(), df['date'].max()]
        )
        db.insert_dataframe(df, 'prices', if_exists='append')

    logger.info(f"✓ Saved {len(df)} prices, latest €{df['ttf_eur_mwh'].iloc[-1]:.2f}/MWh")
    return 0


def compute_metrics():
    from transform.compute_metrics import main as compute_main
    return compute_main()


def export_site():
    from export_site_data import main as export_main
    return export_main()


def main():
    parser = argparse.ArgumentParser(
        description='Update gas market monitor data',
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument('--days', type=int, default=14,
                        help='Re-fetch at least this many days (default: 14, to catch revisions)')
    parser.add_argument('--skip-prices', action='store_true',
                        help='Skip TTF price fetch (useful if Yahoo Finance is down)')
    args = parser.parse_args()

    setup_logging()

    logger.info("=" * 70)
    logger.info("GAS MARKET MONITOR - AUTOMATED DATA UPDATE")
    logger.info(f"Database: {DB_PATH}")
    logger.info(f"Started: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 70)

    # (name, success, required). Prices are context only: a Yahoo outage or rate
    # limit should not mark the whole run as failed.
    steps = [
        ('Fetch Storage Data (AGSI)', run_command("Fetch Storage Data (AGSI)", fetch_storage, args.days), True),
        ('Fetch Border Flows (ENTSOG)', run_command("Fetch Border Flows (ENTSOG)", fetch_flows, args.days), True),
    ]
    if args.skip_prices:
        logger.info("\nSkipping TTF prices (--skip-prices flag)\n")
    else:
        steps.append(('Fetch TTF Prices (Yahoo)',
                      run_command("Fetch TTF Prices (Yahoo)", fetch_ttf_prices, args.days), False))
    steps.append(('Compute Metrics', run_command("Compute Metrics", compute_metrics), True))
    steps.append(('Export Site Data', run_command("Export Site Data", export_site), True))

    logger.info("\n" + "=" * 70 + "\nUPDATE SUMMARY\n" + "=" * 70)
    for name, success, required in steps:
        status = "✓ PASS" if success else ("✗ FAIL" if required else "⚠ WARN")
        logger.info(f"{status:8} {name}")

    failed = [name for name, success, required in steps if required and not success]
    if failed:
        logger.error(f"\n✗ {len(failed)} required step(s) failed: {', '.join(failed)}")
        return 1
    logger.info("\n✓ All required updates completed successfully!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
