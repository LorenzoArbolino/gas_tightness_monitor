"""
Fetch gas flow data from ENTSOG Transparency Platform
"""
import requests
import pandas as pd
import logging
from datetime import datetime, timedelta
from pathlib import Path
import json
import sys

sys.path.append(str(Path(__file__).parent.parent))

from config import (
    ENTSOG_BASE_URL,
    RAW_DATA_DIR,
    REFERENCE_DATA_DIR,
    DEFAULT_FETCH_DAYS
)
from utils import GasMonitorDB, setup_logging

logger = logging.getLogger(__name__)


class ENTSOGFetcher:
    """Fetch flow data from ENTSOG Transparency Platform"""
    
    def __init__(self):
        self.base_url = ENTSOG_BASE_URL
        self.cache_dir = RAW_DATA_DIR / "entsog"
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        
        # Load point mapping
        mapping_file = REFERENCE_DATA_DIR / "entsog_point_mapping.csv"
        if mapping_file.exists():
            self.point_mapping = pd.read_csv(mapping_file)
            logger.info(f"✓ Loaded {len(self.point_mapping)} point mappings")
        else:
            logger.warning(f"Point mapping file not found")
            self.point_mapping = pd.DataFrame(columns=['point_label', 'route'])
        
        self.session = requests.Session()
        self.session.headers.update({'Accept': 'application/json'})
    
    def fetch_flows(self, start_date: str, end_date: str, use_cache: bool = True) -> pd.DataFrame:
        """Fetch physical flow data"""
        
        cache_key = f"{start_date}_{end_date}_Physical_Flow"
        cache_file = self.cache_dir / f"flows_{cache_key}.json"
        
        if use_cache and cache_file.exists():
            logger.info("Loading from cache...")
            with open(cache_file, 'r') as f:
                records = json.load(f)
            logger.info(f"✓ Loaded {len(records)} records from cache")
            return self._process_flow_data(pd.DataFrame(records))
        
        logger.info("Fetching Physical Flow data from ENTSOG API...")
        logger.info(f"Date range: {start_date} to {end_date}")
        
        url = f"{self.base_url}/operationaldatas"
        params = {
            'from': start_date,
            'to': end_date,
            'indicator': 'Physical Flow',
            'periodType': 'day',
            'limit': -1,
            'timezone': 'CET'
        }
        
        logger.info(f"Requesting: {url}")
        logger.info(f"Params: {params}")
        
        try:
            response = self.session.get(url, params=params, timeout=120)
            response.raise_for_status()
            
            data = response.json()
            
            if isinstance(data, dict) and 'operationaldatas' in data:
                records = data['operationaldatas']
                logger.info(f"✓ Found {len(records)} flow records")
            else:
                logger.error(f"Unexpected response format")
                return pd.DataFrame()
            
            if not records:
                logger.warning("No records returned")
                return pd.DataFrame()
            
            with open(cache_file, 'w') as f:
                json.dump(records, f)
            logger.info(f"✓ Cached to {cache_file}")
            
            return self._process_flow_data(pd.DataFrame(records))
            
        except requests.exceptions.Timeout:
            logger.error("API request timed out")
            return pd.DataFrame()
        except requests.exceptions.RequestException as e:
            logger.error(f"API request failed: {e}")
            return pd.DataFrame()
    
    def _process_flow_data(self, df: pd.DataFrame) -> pd.DataFrame:
        """Process raw ENTSOG data"""
        
        if df.empty:
            return df
        
        logger.info(f"Processing {len(df)} raw records...")
        
        # Parse date with UTC to handle mixed timezones
        df['date'] = pd.to_datetime(df['periodFrom'], utc=True).dt.date
        
        df['point_label'] = df['pointLabel'].fillna('Unknown')
        df['operator'] = df['operatorLabel'].fillna('Unknown')
        df['direction'] = df['directionKey'].fillna('Unknown')
        df['unit'] = df['unit'].fillna('kWh/d')
        
        def parse_value(val):
            if pd.isna(val) or val == '-' or val == '':
                return None
            try:
                return float(str(val).replace(',', ''))
            except (ValueError, TypeError):
                return None
        
        df['value_raw'] = df['value'].apply(parse_value)
        
        def convert_to_gwh(row):
            if pd.isna(row['value_raw']):
                return None
            value = row['value_raw']
            unit = row['unit']
            if 'kWh' in unit:
                return value / 1_000_000
            elif 'MWh' in unit:
                return value / 1_000
            elif 'GWh' in unit:
                return value
            elif 'TWh' in unit:
                return value * 1_000
            else:
                return value / 1_000_000
        
        df['value_gwh'] = df.apply(convert_to_gwh, axis=1)
        
        # Map to routes
        df = self._map_to_routes(df)
        
        result = df[[
            'date', 'point_label', 'operator', 'direction',
            'flow_type', 'route', 'value_gwh', 'unit'
        ]].copy()
        
        result = result[result['value_gwh'].notna()].copy()
        result = result.sort_values(['date', 'route']).reset_index(drop=True)
        
        logger.info(f"✓ Processed {len(result)} valid records")
        return result
    
    def _map_to_routes(self, df: pd.DataFrame) -> pd.DataFrame:
        """Map points to routes"""
        
        df['route'] = 'Other'
        df['flow_type'] = 'pipeline'
        
        for _, mapping in self.point_mapping.iterrows():
            point = mapping['point_label']
            route = mapping['route']
            mask = df['point_label'].str.contains(point, case=False, na=False)
            df.loc[mask, 'route'] = route
            if route == 'LNG':
                df.loc[mask, 'flow_type'] = 'LNG'
        
        return df
