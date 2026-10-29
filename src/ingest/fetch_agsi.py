"""
Fetch storage data from AGSI+ (GIE) API
"""
import requests
import pandas as pd
import logging
from datetime import datetime, timedelta
from pathlib import Path
import json
import sys
from typing import Optional

# Add parent directory to path for imports
sys.path.append(str(Path(__file__).parent.parent))

from config import (
    AGSI_BASE_URL,
    GIE_API_KEY,
    RAW_DATA_DIR,
    STORAGE_COUNTRIES,
    HISTORY_START_DATE,
    DEFAULT_FETCH_DAYS
)
from utils import GasMonitorDB, setup_logging, get_date_range
from utils.db import initialize_database

logger = logging.getLogger(__name__)


class AGSIFetcher:
    """Fetch storage data from AGSI+ API"""
    
    def __init__(self, api_key: str):
        if not api_key:
            raise ValueError(
                "GIE_API_KEY is not set. Add it to .env locally, or as a repository "
                "secret (Settings → Secrets and variables → Actions) for the workflow."
            )
        self.api_key = api_key
        self.base_url = AGSI_BASE_URL
        self.cache_dir = RAW_DATA_DIR / "agsi"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.session = requests.Session()
        self.session.headers.update({
            'x-key': self.api_key,
            'Accept': 'application/json'
        })
    
    def fetch_storage(
        self, 
        country: str = "EU",
        start_date: str = None,
        end_date: str = None,
        use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Fetch storage data for a country
        
        Args:
            country: Country code (e.g., 'EU', 'DE', 'IT')
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            use_cache: Whether to use cached data
        
        Returns:
            DataFrame with storage data
        """
        
        # Check cache first
        cache_file = self.cache_dir / f"{country}_storage.json"
        
        if use_cache and cache_file.exists():
            logger.info(f"Loading {country} storage from cache...")
            with open(cache_file, 'r') as f:
                cached_data = json.load(f)
                df = pd.DataFrame(cached_data)
                
                # Filter by date if specified
                if start_date or end_date:
                    df['date'] = pd.to_datetime(df['gasDayStart'])
                    if start_date:
                        df = df[df['date'] >= start_date]
                    if end_date:
                        df = df[df['date'] <= end_date]
                
                if not df.empty:
                    logger.info(f"✓ Loaded {len(df)} days from cache")
                    return self._process_storage_data(df)
        
        # Fetch from API
        logger.info(f"Fetching {country} storage data from AGSI API...")
        
        # For EU aggregate, use /data/EU endpoint which returns time series
        if country == "EU":
            url = f"{self.base_url}/data/{country}"
        else:
            url = f"{self.base_url}/{country}"
        
        # AGSI pages its results (at most 300 rows per page); walk all pages
        params = {'size': 300, 'page': 1}
        if start_date:
            params['from'] = start_date
        if end_date:
            params['to'] = end_date

        logger.info(f"Requesting: {url}")
        logger.info(f"Params: {params}")

        records = []
        try:
            while True:
                response = self.session.get(url, params=params, timeout=60)
                response.raise_for_status()
                data = response.json()

                if isinstance(data, list):
                    records.extend(data)
                    break
                if not isinstance(data, dict) or 'data' not in data:
                    logger.error(f"Unexpected response: {str(data)[:200]}")
                    return pd.DataFrame()
                if data.get('error'):
                    # AGSI answers HTTP 200 with an error body, e.g. for a missing/invalid key
                    logger.error(f"AGSI API error: {data.get('error')} - {data.get('message')}")
                    return pd.DataFrame()

                records.extend(data['data'])
                if params['page'] >= int(data.get('last_page') or 1):
                    break
                params['page'] += 1
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            return pd.DataFrame()

        if not records:
            logger.warning(f"No records returned for {country}")
            return pd.DataFrame()

        df = pd.DataFrame(records)
        logger.info(f"✓ Fetched {len(df)} days for {country}")

        with open(cache_file, 'w') as f:
            json.dump(records, f)
        logger.info(f"✓ Cached to {cache_file}")

        return self._process_storage_data(df)

    def _process_storage_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Process raw AGSI data into standardized format
        
        Expected AGSI fields:
        - gasDayStart: Date string
        - gasInStorage: TWh (text or numeric)
        - full: Percentage full (text or numeric)
        - injection: GWh/d (converted to TWh/d below)
        - withdrawal: GWh/d (converted to TWh/d below)
        - workingGasVolume: TWh
        """
        
        if df.empty:
            return df
        
        # Parse date
        df['date'] = pd.to_datetime(df['gasDayStart']).dt.date
        
        # Convert storage values (they may come as strings with units)
        def parse_storage_value(val):
            """Parse storage values that may be strings like '845.23 TWh' or just numbers"""
            if pd.isna(val) or val == '-' or val == '':
                return None
            if isinstance(val, (int, float)):
                return float(val)
            # Remove units and convert
            val_str = str(val).replace(' TWh', '').replace(',', '').strip()
            if val_str == '' or val_str == '-':
                return None
            try:
                return float(val_str)
            except ValueError:
                return None
        
        def parse_percentage(val):
            """Parse percentage values that may be strings like '73.42 %'"""
            if pd.isna(val) or val == '-' or val == '':
                return None
            if isinstance(val, (int, float)):
                return float(val)
            val_str = str(val).replace(' %', '').replace('%', '').replace(',', '').strip()
            if val_str == '' or val_str == '-':
                return None
            try:
                return float(val_str)
            except ValueError:
                return None
        
        # Process columns with safety checks for missing fields
        df['gas_in_storage_twh'] = df['gasInStorage'].apply(parse_storage_value)
        df['percent_full'] = df['full'].apply(parse_percentage)
        
        # These fields might not exist in all responses
        # AGSI reports injection/withdrawal in GWh/d, unlike gasInStorage (TWh)
        if 'injection' in df.columns:
            df['injection_twh'] = pd.to_numeric(df['injection'].apply(parse_storage_value), errors='coerce') / 1000
        else:
            df['injection_twh'] = None

        if 'withdrawal' in df.columns:
            df['withdrawal_twh'] = pd.to_numeric(df['withdrawal'].apply(parse_storage_value), errors='coerce') / 1000
        else:
            df['withdrawal_twh'] = None
            
        if 'workingGasVolume' in df.columns:
            df['working_gas_volume_twh'] = df['workingGasVolume'].apply(parse_storage_value)
        else:
            df['working_gas_volume_twh'] = None
        
        # Select and order columns - ensure all required columns exist
        result = df[[
            'date',
            'gas_in_storage_twh',
            'percent_full',
            'injection_twh',
            'withdrawal_twh',
            'working_gas_volume_twh'
        ]].copy()
        
        # Sort by date
        result = result.sort_values('date').reset_index(drop=True)
        
        # Data quality checks
        null_counts = result.isnull().sum()
        if null_counts.any():
            logger.warning(f"Null values detected:\n{null_counts[null_counts > 0]}")
        
        # Check for duplicates
        duplicates = result[result.duplicated(subset=['date'], keep=False)]
        if not duplicates.empty:
            logger.warning(f"Found {len(duplicates)} duplicate dates, keeping last")
            result = result.drop_duplicates(subset=['date'], keep='last')
        
        # Log sample of processed data
        logger.info(f"Processed data sample:")
        logger.info(f"  Date range: {result['date'].min()} to {result['date'].max()}")
        logger.info(f"  Latest storage: {result['gas_in_storage_twh'].iloc[-1]:.1f} TWh ({result['percent_full'].iloc[-1]:.1f}% full)")
        
        return result
    
    def fetch_all_countries(
        self,
        countries: list = None,
        start_date: str = None,
        end_date: str = None
    ) -> dict:
        """Fetch storage data for multiple countries"""
        
        countries = countries or STORAGE_COUNTRIES
        results = {}
        
        for country in countries:
            logger.info(f"Fetching {country}...")
            df = self.fetch_storage(country, start_date, end_date)
            results[country] = df
        
        return results


def fetch_full_history_batched():
    """Fetch full history in yearly batches to get around API limits"""
    
    setup_logging()
    logger.info("=== AGSI Full History Fetch (Batched) ===\n")
    
    from config import DB_PATH
    initialize_database(DB_PATH)
    
    fetcher = AGSIFetcher(GIE_API_KEY)
    
    # Fetch in yearly chunks from 2019 to present
    start_year = 2019
    end_year = datetime.now().year
    
    all_data = []
    
    for year in range(start_year, end_year + 1):
        start_date = f"{year}-01-01"
        end_date = f"{year}-12-31" if year < end_year else datetime.now().strftime('%Y-%m-%d')
        
        logger.info(f"\nFetching year {year}: {start_date} to {end_date}")
        
        df = fetcher.fetch_storage(
            country="EU",
            start_date=start_date,
            end_date=end_date,
            use_cache=False  # Force fresh fetch for each year
        )
        
        if not df.empty:
            all_data.append(df)
            logger.info(f"  ✓ Got {len(df)} days for {year}")
        else:
            logger.warning(f"  ⚠ No data for {year}")
    
    if not all_data:
        logger.error("No data fetched!")
        return 1
    
    # Combine all years
    df_combined = pd.concat(all_data, ignore_index=True)
    df_combined = df_combined.drop_duplicates(subset=['date']).sort_values('date').reset_index(drop=True)
    
    logger.info(f"\n=== Combined Results ===")
    logger.info(f"Total days: {len(df_combined)}")
    logger.info(f"Date range: {df_combined['date'].min()} to {df_combined['date'].max()}")
    logger.info(f"Years covered: {df_combined['date'].min().year} - {df_combined['date'].max().year}")
    
    # Save to database
    logger.info(f"\nSaving to database...")
    
    with GasMonitorDB(DB_PATH) as db:
        # Clear all existing storage data
        db.conn.execute("DELETE FROM storage_raw")
        logger.info("  Cleared existing data")
        
        db.insert_dataframe(df_combined, 'storage_raw', if_exists='append')
        
        total_rows = db.get_row_count('storage_raw')
        latest_date = db.get_latest_date('storage_raw')
        
        logger.info(f"✓ Database now contains {total_rows} rows")
        logger.info(f"✓ Latest date: {latest_date}")
    
    logger.info("\n✓ Batched fetch complete!")
    return 0


def main():
    """Main execution function"""
    
    import argparse
    
    parser = argparse.ArgumentParser(description='Fetch AGSI storage data')
    parser.add_argument('--days', type=int, default=DEFAULT_FETCH_DAYS,
                       help=f'Number of days to fetch (default: {DEFAULT_FETCH_DAYS})')
    parser.add_argument('--full-history', action='store_true',
                       help=f'Fetch full history from {HISTORY_START_DATE}')
    parser.add_argument('--batched', action='store_true',
                       help='Fetch full history in yearly batches (more data)')
    parser.add_argument('--country', type=str, default='EU',
                       help='Country code (default: EU)')
    parser.add_argument('--no-cache', action='store_true',
                       help='Ignore cached data')
    
    args = parser.parse_args()
    
    # Special mode: batched historical fetch
    if args.batched:
        return fetch_full_history_batched()
    
    # Setup logging
    setup_logging()
    logger.info("=== AGSI Storage Data Fetch ===")
    
    # Initialize database
    from config import DB_PATH
    initialize_database(DB_PATH)
    
    # Determine date range
    if args.full_history:
        start_date = HISTORY_START_DATE
        end_date = datetime.now().strftime('%Y-%m-%d')
        logger.info(f"Fetching full history: {start_date} to {end_date}")
    else:
        end_date = datetime.now().strftime('%Y-%m-%d')
        start_date = (datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')
        logger.info(f"Fetching last {args.days} days: {start_date} to {end_date}")
    
    # Fetch data
    fetcher = AGSIFetcher(GIE_API_KEY)
    df = fetcher.fetch_storage(
        country=args.country,
        start_date=start_date,
        end_date=end_date,
        use_cache=not args.no_cache
    )
    
    if df.empty:
        logger.error("No data fetched!")
        return 1
    
    # Save to database
    logger.info(f"Saving {len(df)} rows to database...")
    
    with GasMonitorDB(DB_PATH) as db:
        db.conn.execute(
            "DELETE FROM storage_raw WHERE date BETWEEN ? AND ?",
            [df['date'].min(), df['date'].max()]
        )
        db.insert_dataframe(df, 'storage_raw', if_exists='append')
        
        # Check what's in the database
        total_rows = db.get_row_count('storage_raw')
        latest_date = db.get_latest_date('storage_raw')
        
        logger.info(f"✓ Database now contains {total_rows} rows")
        logger.info(f"✓ Latest date in database: {latest_date}")
    
    # Summary statistics
    logger.info("\n=== Data Summary ===")
    logger.info(f"Date range: {df['date'].min()} to {df['date'].max()}")
    logger.info(f"Current storage: {df['gas_in_storage_twh'].iloc[-1]:.1f} TWh ({df['percent_full'].iloc[-1]:.1f}% full)")
    
    # Calculate 7-day change if we have enough data
    if len(df) >= 8:
        logger.info(f"Storage change (last 7 days): {df['gas_in_storage_twh'].iloc[-1] - df['gas_in_storage_twh'].iloc[-8]:.2f} TWh")
    elif len(df) >= 2:
        logger.info(f"Storage change (period): {df['gas_in_storage_twh'].iloc[-1] - df['gas_in_storage_twh'].iloc[0]:.2f} TWh")
    
    logger.info("\n✓ AGSI fetch complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
