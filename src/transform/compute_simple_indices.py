"""
Compute simple, transparent indices for production dashboard
- Storage Adequacy Index: 0-100 percentile vs 5-year history
- Supply Security Index: 0-100 based on import diversification (HHI)
"""
import pandas as pd
import numpy as np
import logging
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from utils import GasMonitorDB, setup_logging
from config import DB_PATH

logger = logging.getLogger(__name__)


def compute_storage_adequacy(df):
    """
    Storage Adequacy Index: Compare current storage to historical range

    Formula: (current - historical_min) / (historical_max - historical_min) * 100
    Where historical = same day-of-year ±14 days over past 5 years

    Returns: 0-100 scale (0 = lowest ever, 100 = highest ever for this time of year)
    """
    logger.info("=== Computing Storage Adequacy Index ===\n")

    df = df.sort_values('date').copy()
    df['date_dt'] = pd.to_datetime(df['date'])

    # storage_pct_5y is already a 0-100 percentile
    df['storage_adequacy'] = df['storage_pct_5y']

    # Classify
    def classify_adequacy(val):
        if pd.isna(val):
            return None
        if val < 20:
            return 'Very Low'
        elif val < 40:
            return 'Low'
        elif val < 60:
            return 'Normal'
        elif val < 80:
            return 'High'
        else:
            return 'Very High'

    df['storage_adequacy_band'] = df['storage_adequacy'].apply(classify_adequacy)

    logger.info(f"Storage adequacy computed for {df['storage_adequacy'].notna().sum()} days")
    logger.info(f"  Mean: {df['storage_adequacy'].mean():.1f}")
    logger.info(f"  Range: [{df['storage_adequacy'].min():.1f}, {df['storage_adequacy'].max():.1f}]")
    logger.info(f"  Current: {df['storage_adequacy'].iloc[-1]:.1f} ({df['storage_adequacy_band'].iloc[-1]})\n")

    return df


def compute_supply_security(df, db):
    """
    Supply Security Index: Measures import diversification

    Formula: 100 * (1 - HHI/10000)
    Where HHI = Herfindahl-Hirschman Index of import concentration

    Returns: 0-100 scale (0 = highly concentrated/fragile, 100 = highly diversified/secure)
    """
    logger.info("=== Computing Supply Security Index ===\n")

    # Get flows data and aggregate by source/route
    flows = db.query("""
        SELECT
            date,
            route,
            direction,
            value_gwh
        FROM flows_raw
        WHERE route IS NOT NULL
        ORDER BY date, route
    """)

    logger.info(f"Loaded {len(flows)} flow records")

    # Calculate daily imports by source
    imports = flows[flows['direction'] == 'entry'].copy()
    daily_imports = imports.groupby(['date', 'route'])['value_gwh'].sum().reset_index()

    # Calculate HHI for each date
    def calculate_hhi(group):
        """Calculate HHI for a single day"""
        total = group['value_gwh'].sum()
        if total <= 0:
            return np.nan

        shares = group['value_gwh'] / total
        hhi = (shares ** 2).sum() * 10000
        return hhi

    daily_hhi = daily_imports.groupby('date').apply(calculate_hhi).reset_index()
    daily_hhi.columns = ['date', 'import_hhi']

    # Merge with main dataframe
    df = df.merge(daily_hhi, on='date', how='left', suffixes=('', '_new'))

    # Update import_hhi if new value exists
    if 'import_hhi_new' in df.columns:
        df['import_hhi'] = df['import_hhi_new'].fillna(df['import_hhi'])
        df = df.drop(columns=['import_hhi_new'])

    # Convert to supply security (inverted, so higher = more secure)
    df['supply_security'] = 100 * (1 - np.clip(df['import_hhi'] / 10000, 0, 1))

    # Classify
    def classify_security(val):
        if pd.isna(val):
            return None
        if val < 20:
            return 'Very Fragile'
        elif val < 40:
            return 'Fragile'
        elif val < 60:
            return 'Moderate'
        elif val < 80:
            return 'Diverse'
        else:
            return 'Very Diverse'

    df['supply_security_band'] = df['supply_security'].apply(classify_security)

    logger.info(f"Supply security computed for {df['supply_security'].notna().sum()} days")
    logger.info(f"  Mean HHI: {df['import_hhi'].mean():.0f}")
    logger.info(f"  Mean security: {df['supply_security'].mean():.1f}")
    logger.info(f"  Range: [{df['supply_security'].min():.1f}, {df['supply_security'].max():.1f}]")
    logger.info(f"  Current: {df['supply_security'].iloc[-1]:.1f} ({df['supply_security_band'].iloc[-1]})\n")

    return df


def update_database(df):
    """Update database with simple indices"""
    logger.info("=== Updating Database ===\n")

    with GasMonitorDB(DB_PATH) as db:
        # Add new columns if they don't exist
        new_columns = {
            'storage_adequacy': 'FLOAT',
            'storage_adequacy_band': 'VARCHAR',
            'supply_security': 'FLOAT',
            'supply_security_band': 'VARCHAR'
        }

        existing_cols = db.conn.execute("DESCRIBE derived_metrics").fetchdf()['column_name'].tolist()

        for col_name, col_type in new_columns.items():
            if col_name not in existing_cols:
                logger.info(f"  Adding column: {col_name}")
                db.conn.execute(f"ALTER TABLE derived_metrics ADD COLUMN {col_name} {col_type}")

        # Update values
        logger.info(f"Updating {len(df)} rows...")

        for col in new_columns.keys():
            if col in df.columns:
                df_temp = df[['date', col]].copy()
                db.conn.register('temp_update', df_temp)

                db.conn.execute(f"""
                    UPDATE derived_metrics
                    SET {col} = temp_update.{col}
                    FROM temp_update
                    WHERE derived_metrics.date = temp_update.date
                """)

                db.conn.unregister('temp_update')

        logger.info("Database updated successfully\n")


def main():
    """Main execution"""
    setup_logging()

    logger.info("=" * 70)
    logger.info("SIMPLE INDICES COMPUTATION")
    logger.info("Production-ready transparency metrics")
    logger.info("=" * 70)
    logger.info("")

    # Load data
    with GasMonitorDB(DB_PATH) as db:
        logger.info("Loading data...")
        df = db.query("SELECT * FROM derived_metrics ORDER BY date")
        logger.info(f"  Loaded {len(df)} days of metrics\n")

        # Compute indices
        df = compute_storage_adequacy(df)
        df = compute_supply_security(df, db)

    # Update database
    update_database(df)

    # Display recent results
    logger.info("=== Recent Results (Last 7 days) ===\n")
    recent = df[[
        'date',
        'storage_adequacy',
        'storage_adequacy_band',
        'supply_security',
        'supply_security_band'
    ]].tail(7)
    print(recent.to_string(index=False))

    logger.info("\n" + "=" * 70)
    logger.info("SIMPLE INDICES COMPUTED SUCCESSFULLY")
    logger.info("=" * 70)
    logger.info("\nNext: Build dashboard to display these indices\n")

    return 0


if __name__ == "__main__":
    sys.exit(main())
