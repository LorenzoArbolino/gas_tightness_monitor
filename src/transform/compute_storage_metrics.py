"""
Compute storage-based tightness metrics
Robust to gaps in historical data
"""
import pandas as pd
import numpy as np
import logging
from pathlib import Path
import sys

sys.path.append(str(Path(__file__).parent.parent))

from config import DB_PATH
from utils import GasMonitorDB, setup_logging, add_seasonal_features

logger = logging.getLogger(__name__)


def compute_storage_metrics():
    """Compute storage metrics - robust to data gaps"""
    
    logger.info("=== Computing Storage Metrics ===\n")
    
    with GasMonitorDB(DB_PATH) as db:
        df = db.query("SELECT date, gas_in_storage_twh, percent_full FROM storage_raw ORDER BY date")
    
    if df.empty:
        return pd.DataFrame()
    
    logger.info(f"Loaded {len(df)} days: {df['date'].min()} to {df['date'].max()}\n")
    
    df = add_seasonal_features(df, date_column='date')
    
    logger.info("Computing seasonal percentiles (day-of-year ±14 day window)...")
    
    percentiles = []
    
    for idx, row in df.iterrows():
        current_date = pd.Timestamp(row['date'])
        current_doy = current_date.dayofyear
        
        # Find all historical data within ±14 days seasonally
        historical = []
        for i, h_row in df.iterrows():
            if i >= idx:
                break
            
            h_date = pd.Timestamp(h_row['date'])
            h_doy = h_date.dayofyear
            
            # Day-of-year distance (handle year wrap)
            dist = min(abs(current_doy - h_doy), 365 - abs(current_doy - h_doy))
            
            if dist <= 14:
                historical.append(h_row['percent_full'])
        
        n = len(historical)
        
        if n < 5:
            pct, mn, mx = 50.0, row['percent_full'], row['percent_full']
        else:
            hist = np.array(historical)
            mn, mx = hist.min(), hist.max()
            pct = 50.0 if mx - mn < 0.1 else max(0, min(100, 100 * (row['percent_full'] - mn) / (mx - mn)))
        
        percentiles.append({'date': row['date'], 'storage_pct_5y': pct, 'n_hist': n, 
                           'storage_min_5y': mn, 'storage_max_5y': mx})
        
        if idx % 500 == 0:
            logger.info(f"  {idx}/{len(df)}...")
    
    df = df.merge(pd.DataFrame(percentiles), on='date', how='left')
    
    logger.info(f"\n✓ Unique percentiles: {df['storage_pct_5y'].nunique()}")
    logger.info(f"  Avg hist points: {df['n_hist'].mean():.0f}")
    logger.info(f"  Current: {df['storage_pct_5y'].iloc[-1]:.1f}% (range: {df['storage_min_5y'].iloc[-1]:.1f}%-{df['storage_max_5y'].iloc[-1]:.1f}%)\n")
    
    df['storage_zscore'] = (df['storage_pct_5y'] - 50) / 20
    df['storage_draw_actual_twh'] = -df['gas_in_storage_twh'].diff(7)
    
    logger.info(f"✓ Current z-score: {df['storage_zscore'].iloc[-1]:.2f}\n")
    
    return df


def main():
    setup_logging()
    logger.info("=== Storage Metrics ===\n")
    
    df = compute_storage_metrics()
    if df.empty:
        return 1
    
    logger.info("Saving...")
    with GasMonitorDB(DB_PATH) as db:
        db.conn.execute("DELETE FROM derived_metrics")
        db.insert_dataframe(
            df[['date', 'storage_pct_5y', 'storage_zscore', 'storage_draw_actual_twh']],
            'derived_metrics', if_exists='append'
        )
        logger.info(f"✓ Saved {len(df)} rows")
    
    logger.info("\n=== Last 14 days ===")
    print(df[['date', 'percent_full', 'storage_pct_5y', 'storage_zscore', 'n_hist']].tail(14).to_string(index=False))
    
    logger.info("\n✓ Complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
