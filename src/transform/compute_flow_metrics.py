"""
Compute flow-based tightness metrics
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


def compute_flow_metrics():
    """Compute all flow metrics"""
    
    logger.info("=== Computing Flow Metrics ===\n")
    
    # Load flow data
    with GasMonitorDB(DB_PATH) as db:
        df = db.query("""
            SELECT 
                date,
                route,
                direction,
                SUM(value_gwh) as total_gwh
            FROM flows_raw
            GROUP BY date, route, direction
            ORDER BY date
        """)
    
    if df.empty:
        logger.error("No flow data!")
        return pd.DataFrame()
    
    logger.info(f"Loaded {len(df)} flow records")
    logger.info(f"Range: {df['date'].min()} to {df['date'].max()}")
    logger.info(f"Routes: {df['route'].nunique()}")
    logger.info(f"Directions: {df['direction'].unique().tolist()}\n")
    
    # Aggregate to daily net imports by route
    logger.info("Aggregating net imports by route...")
    
    # Pivot to get entry and exit for each route
    df_pivot = df.pivot_table(
        index=['date', 'route'],
        columns='direction',
        values='total_gwh',
        fill_value=0
    ).reset_index()
    
    # Calculate net imports (entry - exit)
    df_pivot['net_import_gwh'] = df_pivot.get('entry', 0) - df_pivot.get('exit', 0)
    
    # Total net imports per day
    df_daily = df_pivot.groupby('date').agg({
        'net_import_gwh': 'sum'
    }).reset_index()
    
    logger.info(f"✓ Aggregated to {len(df_daily)} days")
    logger.info(f"  Current net imports: {df_daily['net_import_gwh'].iloc[-1]:.0f} GWh/day\n")
    
    # Add seasonal features
    df_daily = add_seasonal_features(df_daily, date_column='date')
    
    # Compute z-score using ISO week matching
    logger.info("Computing import z-scores...")
    
    zscores = []
    
    for idx, row in df_daily.iterrows():
        week = row['iso_week']
        year = row['iso_year']
        
        # Get same week from past 5 years
        hist = df_daily[
            (df_daily['iso_week'] == week) & 
            (df_daily['iso_year'] >= year-5) & 
            (df_daily['iso_year'] < year)
        ]
        
        # Widen if needed
        if len(hist) < 10:
            hist = df_daily[
                (df_daily['iso_week'].isin([week-1, week, week+1])) & 
                (df_daily['iso_year'] >= year-5) & 
                (df_daily['iso_year'] < year)
            ]
        
        if len(hist) < 5:
            z = 0.0  # Not enough history
        else:
            mean = hist['net_import_gwh'].mean()
            std = hist['net_import_gwh'].std()
            
            if std < 1:  # Avoid division by zero
                z = 0.0
            else:
                z = (row['net_import_gwh'] - mean) / std
        
        zscores.append({
            'date': row['date'],
            'import_zscore': z,
            'n_hist': len(hist)
        })
        
        if idx % 100 == 0 and idx > 0:
            logger.info(f"  {idx}/{len(df_daily)}...")
    
    df_z = pd.DataFrame(zscores)
    df_daily = df_daily.merge(df_z, on='date', how='left')
    
    logger.info(f"\n✓ Computed z-scores")
    logger.info(f"  Current z-score: {df_daily['import_zscore'].iloc[-1]:.2f}")
    logger.info(f"  Avg historical points: {df_daily['n_hist'].mean():.0f}\n")
    
    # Compute route concentration (HHI)
    logger.info("Computing import route concentration (HHI)...")
    
    # For each date, calculate HHI
    hhi_list = []
    
    for date in df_pivot['date'].unique():
        day_data = df_pivot[df_pivot['date'] == date]
        
        # Only consider entry flows (imports)
        entry_data = df[
            (df['date'] == date) & 
            (df['direction'] == 'entry')
        ]
        
        if entry_data.empty:
            hhi_list.append({'date': date, 'import_hhi': 0.0})
            continue
        
        # Calculate market share for each route
        total_imports = entry_data['total_gwh'].sum()
        
        if total_imports < 1:
            hhi_list.append({'date': date, 'import_hhi': 0.0})
            continue
        
        shares = entry_data['total_gwh'] / total_imports
        hhi = (shares ** 2).sum() * 10000  # HHI scale
        
        hhi_list.append({'date': date, 'import_hhi': hhi})
    
    df_hhi = pd.DataFrame(hhi_list)
    df_daily = df_daily.merge(df_hhi, on='date', how='left')
    
    logger.info(f"✓ Computed HHI")
    logger.info(f"  Current HHI: {df_daily['import_hhi'].iloc[-1]:.0f}")
    logger.info(f"  (0=perfect diversity, 10000=single source)\n")
    
    return df_daily


def main():
    """Main execution"""
    
    setup_logging()
    logger.info("=== Flow Metrics Calculation ===\n")
    
    df = compute_flow_metrics()
    
    if df.empty:
        return 1
    
    # Merge with existing derived_metrics
    logger.info("Merging with existing metrics...")
    
    with GasMonitorDB(DB_PATH) as db:
        # Load existing metrics
        df_existing = db.query("SELECT * FROM derived_metrics")
        
        if df_existing.empty:
            logger.warning("No existing metrics - only saving flow metrics")
            metrics_to_save = df[['date', 'net_import_gwh', 'import_zscore', 'import_hhi']].copy()
        else:
            # Merge flow metrics into existing
            df_merged = df_existing.merge(
                df[['date', 'net_import_gwh', 'import_zscore', 'import_hhi']],
                on='date',
                how='left',
                suffixes=('', '_new')
            )
            
            # Update flow columns with new values where available
            if 'net_import_gwh_new' in df_merged.columns:
                df_merged['net_import_gwh'] = df_merged['net_import_gwh_new'].fillna(df_merged.get('net_import_gwh', None))
                df_merged['import_zscore'] = df_merged['import_zscore_new'].fillna(df_merged.get('import_zscore', None))
                df_merged['import_hhi'] = df_merged['import_hhi_new'].fillna(df_merged.get('import_hhi', None))
                df_merged = df_merged.drop(columns=['net_import_gwh_new', 'import_zscore_new', 'import_hhi_new'])
            
            metrics_to_save = df_merged
        
        # Replace entire table
        db.conn.execute("DELETE FROM derived_metrics")
        db.insert_dataframe(metrics_to_save, 'derived_metrics', if_exists='append')
        
        logger.info(f"✓ Updated {len(metrics_to_save)} rows")
    
    # Show recent
    logger.info("\n=== Recent Metrics (Last 10 days) ===")
    recent = df[['date', 'net_import_gwh', 'import_zscore', 'import_hhi', 'n_hist']].tail(10)
    print(recent.to_string(index=False))
    
    logger.info("\n✓ Complete!")
    return 0


if __name__ == "__main__":
    sys.exit(main())
