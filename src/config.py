"""
Configuration file for Europe Gas Tightness Monitor
"""
import os
from pathlib import Path
from dotenv import load_dotenv
from datetime import datetime, timedelta

# Load environment variables
load_dotenv()

# Project paths
PROJECT_ROOT = Path(__file__).parent.parent  # Go up one level from src/
DATA_DIR = PROJECT_ROOT / "data"
RAW_DATA_DIR = DATA_DIR / "raw"
PROCESSED_DATA_DIR = DATA_DIR / "processed"
REFERENCE_DATA_DIR = DATA_DIR / "reference"

# Database
DB_PATH = PROCESSED_DATA_DIR / "gas_monitor.duckdb"

# API Keys
GIE_API_KEY = os.getenv("GIE_API_KEY")
# ENTSOG API is public - no key required
ENTSOE_API_KEY = os.getenv("ENTSOE_API_KEY")  # Add when you get it

# API Endpoints
AGSI_BASE_URL = "https://agsi.gie.eu/api"
ENTSOG_BASE_URL = "https://transparency.entsog.eu/api/v1"
ENTSOE_BASE_URL = "https://web-api.tp.entsoe.eu/api"
OPENMETEO_BASE_URL = "https://archive-api.open-meteo.com/v1/archive"

# Date ranges
HISTORY_START_DATE = "2019-01-01"  # 5+ years for proper seasonality
DEFAULT_FETCH_DAYS = 7

# Storage configuration
STORAGE_COUNTRIES = ["EU"]  # Start with EU aggregate
# For v2: ["DE", "IT", "NL", "FR", "AT"]

# Flow configuration (we'll build this mapping in reference data)
KEY_IMPORT_ROUTES = [
    "Norway",
    "Algeria", 
    "Azerbaijan",
    "LNG",
    "Russia"  # Track even if zero
]

# Power generation countries (major gas consumers)
POWER_GEN_COUNTRIES = ["DE", "IT", "ES", "FR", "NL"]

# Weather regions (EU population-weighted centroids)
WEATHER_REGIONS = [
    {"name": "Northwest", "lat": 51.5, "lon": 4.5, "weight": 0.25},  # BeNeLux/North Germany
    {"name": "Germany", "lat": 50.5, "lon": 10.5, "weight": 0.20},   # Central Germany
    {"name": "France", "lat": 47.0, "lon": 2.0, "weight": 0.15},     # France
    {"name": "Italy", "lat": 42.0, "lon": 12.5, "weight": 0.15},     # Italy
    {"name": "Spain", "lat": 40.0, "lon": -4.0, "weight": 0.12},     # Spain
    {"name": "Poland", "lat": 52.0, "lon": 19.0, "weight": 0.08},    # Poland
    {"name": "CEE", "lat": 48.0, "lon": 17.0, "weight": 0.05},       # Czech/Austria/Hungary
]

# Heating degree day base temperature
HDD_BASE_TEMP = 18.0  # °C

# Tightness index parameters
ZSCORE_BANDS = {
    "very_loose": -1.5,
    "loose": -0.5,
    "neutral_low": -0.5,
    "neutral_high": 0.5,
    "tight": 1.5,
    "very_tight": float('inf')
}

FRAGILITY_BANDS = {
    "robust": 0.3,
    "moderate": 0.5,
    "elevated": 0.7,
    "fragile": float('inf')
}

# Data quality thresholds
MIN_DATA_COMPLETENESS = 0.85  # 85% of expected data points
MAX_ZSCORE_THRESHOLD = 5.0    # Flag outliers
MAX_CACHE_AGE_HOURS = 48      # Max age for cached data

# Update schedule (for future automation)
UPDATE_HOUR_CET = 21  # 21:00 CET = after AGSI updates

# Logging
LOG_LEVEL = "INFO"
LOG_FORMAT = "%(asctime)s - %(name)s - %(levelname)s - %(message)s"

# Validate critical config
if not GIE_API_KEY:
    raise ValueError("GIE_API_KEY not found in .env file")

# Suppress config prints to avoid encoding issues
# Config loaded successfully
