"""
Fetch weather data and calculate Heating Degree Days (HDD) for EU
"""
import requests
import pandas as pd
import numpy as np
import logging
from datetime import datetime, timedelta
from pathlib import Path
import json
import sys

sys.path.append(str(Path(__file__).parent.parent))

from config import (
    OPENMETEO_BASE_URL,
    RAW_DATA_DIR,
    WEATHER_REGIONS,
    HDD_BASE_TEMP,
    HISTORY_START_DATE,
    DEFAULT_FETCH_DAYS
)
from utils import GasMonitorDB, setup_logging
from utils.db import initialize_database

logger = logging.getLogger(__name__)


class WeatherFetcher:
    """Fetch weather data and calculate HDD"""
    
    def __init__(self):
        self.base_url = OPENMETEO_BASE_URL
        self.cache_dir = RAW_DATA_DIR / "weather"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        self.regions = WEATHER_REGIONS
        logger.info(f"✓ Configured {len(self.regions)} weather regions")
        
        self.session = requests.Session()
        self.session.headers.update({
            'Accept': 'application/json'
        })
    
    def fetch_weather(
        self,
        start_date: str,
        end_date: str,
        use_cache: bool = True
    ) -> pd.DataFrame:
        """
        Fetch temperature data for all EU regions
        
        Args:
            start_date: Start date (YYYY-MM-DD)
            end_date: End date (YYYY-MM-DD)
            use_cache: Whether to use cached data
        
        Returns:
            DataFrame with HDD by region
        """
        
        all_data = []
        
        for region in self.regions:
            logger.info(f"Fetching {region['name']}...")
            
            cache_file = self.cache_dir / f"{region['name']}_{start_date}_{end_date}.json"
            
            # Check cache
            if use_cache and cache_file.exists():
                logger.info(f"  Loading from cache...")
                with open(cache_file, 'r') as f:
                    cached = json.load(f)
                df_region = pd.DataFrame(cached)
                df_region['date'] = pd.to_datetime(df_region['date'])
            else:
                # Fetch from API
                df_region = self._fetch_region(
                    region['name'],
                    region['lat'],
                    region['lon'],
                    start_date,
                    end_date
                )
                
                if df_region.empty:
                    logger.warning(f"  No data for {region['name']}")
                    continue
                
                # Cache (convert dates to strings for JSON)
                cache_data = df_region.copy()
                cache_data['date'] = cache_data['date'].astype(str)
                with open(cache_file, 'w') as f:
                    json.dump(cache_data.to_dict('records'), f)
            
            # Add region metadata
            df_region['region'] = region['name']
            df_region['population_weight'] = region['weight']
            
            all_data.append(df_region)
            logger.info(f"  ✓ {len(df_region)} days")
        
        if not all_data:
            logger.error("No weather data fetched!")
            return pd.DataFrame()
        
        # Combine all regions
        df = pd.concat(all_data, ignore_index=True)
        
        logger.info(f"\n✓ Combined: {len(df)} total records")
        logger.info(f"  Date range: {df['date'].min()} to {df['date'].max()}")
        logger.info(f"  Regions: {df['region'].nunique()}")
        
        return df
    
    def _fetch_region(
        self,
        name: str,
        lat: float,
        lon: float,
        start_date: str,
        end_date: str
    ) -> pd.DataFrame:
        """Fetch temperature data for one region from Open-Meteo"""
        
        url = self.base_url
        
        params = {
            'latitude': lat,
            'longitude': lon,
            'start_date': start_date,
            'end_date': end_date,
            'daily': 'temperature_2m_mean',
            'timezone': 'Europe/Brussels'
        }
        
        try:
            response = self.session.get(url, params=params, timeout=30)
            response.raise_for_status()
            
            data = response.json()
            
            if 'daily' not in data:
                logger.error(f"Unexpected response format for {name}")
                return pd.DataFrame()
            
            daily = data['daily']
            
            df = pd.DataFrame({
                'date': pd.to_datetime(daily['time']),
                'temp_mean_c': daily['temperature_2m_mean']
            })
            
            # Calculate HDD
            df['hdd'] = df['temp_mean_c'].apply(
                lambda t: max(0, HDD_BASE_TEMP - t) if pd.notna(t) else None
            )
            
            return df
            
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed for {name}: {e}")
            return pd.DataFrame()
    
    def aggregate_eu_hdd(self, df: pd.DataFrame) -> pd.DataFrame:
        """
        Aggregate regional HDD to EU-wide weighted average
        
        Args:
            df: Regional HDD data
        
        Returns:
            DataFrame with EU aggregate HDD by date
        """
        
        if df.empty:
            return df
        
        # Calculate weighted HDD
        df['weighted_hdd'] = df['hdd'] * df['population_weight']
        
        # Aggregate by date
        eu_agg = (
            df.groupby('date')
            .agg({
                'weighted_hdd': 'sum',
                'temp_mean_c': lambda x: np.average(x, weights=df.loc[x.index, 'population_weight'])
            })
            .reset_index()
        )
        
        eu_agg.columns = ['date', 'eu_hdd', 'eu_temp_mean_c']
        
        logger.info(f"\n✓ EU aggregate computed:")
        logger.info(f"  Latest HDD: {eu_agg['eu_hdd'].iloc[-1]:.1f}")
        logger.info(f"  Latest temp: {eu_agg['eu_temp_mean_c'].iloc[-1]:.1f}°C")
        logger.info(f"  Mean HDD (period): {eu_agg['eu_hdd'].mean():.1f}")
        
        return eu_agg


def main():
    """Main execution"""
    
    import argparse
    
    parser = argparse.ArgumentParser(description='Fetch weather data and calculate HDD')
    parser.add_argument('--days', type=int, default=DEFAULT_FETCH_DAYS,
                       help=f'Number of days to fetch (default: {DEFAULT_FETCH_DAYS})')
    parser.add_argument('--full-history', action='store_true',
                       help=f'Fetch full history from {HISTORY_START_DATE}')
    parser.add_argument('--no-cache', action='store_true',
                       help='Ignore cached data')
    parser.add_argument('--test', action='store_true',
                       help='Test with 7 days only')
    
    args = parser.parse_args()
    
    setup_logging()
    logger.info("=== Weather Data Fetch (HDD Calculation) ===")
    
    from config import DB_PATH
    initialize_database(DB_PATH)
    
    # Date range
    if args.test:
        days = 7
    elif args.full_history:
        # Open-Meteo allows up to ~1 year of history in free tier
        # For longer history, we'll batch or use cached data
        days = 365
    else:
        days = args.days
    
    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = (datetime.now() - timedelta(days=days)).strftime('%Y-%m-%d')
    logger.info(f"Fetching {days} days: {start_date} to {end_date}\n")
    
    # Fetch
    fetcher = WeatherFetcher()
    df_regional = fetcher.fetch_weather(
        start_date=start_date,
        end_date=end_date,
        use_cache=not args.no_cache
    )
    
    if df_regional.empty:
        logger.error("No weather data fetched!")
        return 1
    
    # Save regional data to database
    logger.info(f"\nSaving {len(df_regional)} regional records to database...")

    with GasMonitorDB(DB_PATH) as db:
        # Clear existing data for date range
        min_date = df_regional['date'].min()
        max_date = df_regional['date'].max()
        db.conn.execute(
            "DELETE FROM weather_raw WHERE date BETWEEN ? AND ?",
            [min_date, max_date]
        )
        logger.info(f"  Cleared existing data for {min_date} to {max_date}")

        # Convert datetime to date for database insertion
        df_to_insert = df_regional.copy()
        df_to_insert['date'] = df_to_insert['date'].dt.date

        # Reorder columns to match database schema (without updated_at, which is added by insert_dataframe)
        df_to_insert = df_to_insert[['date', 'region', 'temp_mean_c', 'hdd', 'population_weight']]

        db.insert_dataframe(df_to_insert, 'weather_raw', if_exists='append')
        
        total = db.get_row_count('weather_raw')
        latest = db.get_latest_date('weather_raw')
        
        logger.info(f"✓ Database: {total} weather records")
        logger.info(f"✓ Latest: {latest}")
    
    # Also compute and show EU aggregate (we'll use this in transforms)
    logger.info("\n=== Computing EU Aggregate ===")
    df_eu = fetcher.aggregate_eu_hdd(df_regional)
    
    logger.info("\n✓ Weather fetch complete!")
    logger.info(f"\nSample EU HDD (last 7 days):")
    print(df_eu.tail(7)[['date', 'eu_hdd', 'eu_temp_mean_c']])
    
    return 0


if __name__ == "__main__":
    sys.exit(main())
