"""
Date and time utilities
"""
from datetime import datetime, timedelta, date
from typing import Tuple, List
import pandas as pd


def get_date_range(start_date: str, end_date: str = None, days: int = None) -> Tuple[str, str]:
    """
    Get date range for data fetching
    
    Args:
        start_date: Start date (YYYY-MM-DD)
        end_date: End date (YYYY-MM-DD), optional
        days: Number of days to fetch, optional
    
    Returns:
        Tuple of (start_date, end_date) strings
    """
    start = datetime.strptime(start_date, '%Y-%m-%d')
    
    if end_date:
        end = datetime.strptime(end_date, '%Y-%m-%d')
    elif days:
        end = datetime.now()
        start = end - timedelta(days=days)
    else:
        end = datetime.now()
    
    return start.strftime('%Y-%m-%d'), end.strftime('%Y-%m-%d')


def get_iso_week(date_obj: datetime) -> int:
    """Get ISO week number for a date"""
    return date_obj.isocalendar()[1]


def get_iso_year(date_obj: datetime) -> int:
    """Get ISO year for a date"""
    return date_obj.isocalendar()[0]


def get_day_of_year(date_obj: datetime) -> int:
    """Get day of year (1-366)"""
    return date_obj.timetuple().tm_yday


def get_season(date_obj: datetime) -> str:
    """
    Get meteorological season
    - Winter: Dec, Jan, Feb
    - Spring: Mar, Apr, May
    - Summer: Jun, Jul, Aug
    - Fall: Sep, Oct, Nov
    """
    month = date_obj.month
    
    if month in [12, 1, 2]:
        return "winter"
    elif month in [3, 4, 5]:
        return "spring"
    elif month in [6, 7, 8]:
        return "summer"
    else:
        return "fall"


def get_storage_season(date_obj: datetime) -> str:
    """
    Get storage season (injection vs withdrawal)
    - Injection: Apr 1 - Oct 31
    - Withdrawal: Nov 1 - Mar 31
    """
    month = date_obj.month
    
    if 4 <= month <= 10:
        return "injection"
    else:
        return "withdrawal"


def add_seasonal_features(df: pd.DataFrame, date_column: str = 'date') -> pd.DataFrame:
    """
    Add seasonal features to a DataFrame
    
    Args:
        df: DataFrame with date column
        date_column: Name of date column
    
    Returns:
        DataFrame with added seasonal features
    """
    df = df.copy()
    df[date_column] = pd.to_datetime(df[date_column])
    
    df['iso_week'] = df[date_column].apply(lambda x: get_iso_week(x))
    df['iso_year'] = df[date_column].apply(lambda x: get_iso_year(x))
    df['day_of_year'] = df[date_column].apply(lambda x: get_day_of_year(x))
    df['season'] = df[date_column].apply(lambda x: get_season(x))
    df['storage_season'] = df[date_column].apply(lambda x: get_storage_season(x))
    df['month'] = df[date_column].dt.month
    df['year'] = df[date_column].dt.year
    
    return df


def get_last_n_days(n: int = 7) -> List[str]:
    """Get list of last N days as YYYY-MM-DD strings"""
    today = datetime.now()
    return [(today - timedelta(days=i)).strftime('%Y-%m-%d') for i in range(n-1, -1, -1)]


def is_weekend(date_obj: datetime) -> bool:
    """Check if date is weekend"""
    return date_obj.weekday() >= 5


def get_current_week_monday() -> str:
    """Get Monday of current ISO week"""
    today = datetime.now()
    monday = today - timedelta(days=today.weekday())
    return monday.strftime('%Y-%m-%d')
