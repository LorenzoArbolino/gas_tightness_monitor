"""
Quick data verification and inspection script
"""
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent))

from config import DB_PATH
from utils import GasMonitorDB
import pandas as pd

pd.set_option('display.max_columns', None)
pd.set_option('display.width', None)


def inspect_storage_data():
    """Inspect storage data in database"""
    
    with GasMonitorDB(DB_PATH) as db:
        
        print("\n=== DATABASE INSPECTION ===\n")
        
        # Row counts
        storage_rows = db.get_row_count('storage_raw')
        print(f"Storage rows: {storage_rows}")
        
        if storage_rows == 0:
            print("⚠ No data in storage_raw table!")
            return
        
        # Date range
        latest_date = db.get_latest_date('storage_raw')
        print(f"Latest date: {latest_date}")
        
        # Get recent data
        df = db.query("""
            SELECT * FROM storage_raw 
            ORDER BY date DESC 
            LIMIT 10
        """)
        
        print("\n=== LAST 10 DAYS ===")
        print(df[['date', 'gas_in_storage_twh', 'percent_full']])
        
        # Get 2022 summer data (should show injection season)
        df_2022 = db.query("""
            SELECT * FROM storage_raw 
            WHERE date BETWEEN '2022-06-01' AND '2022-09-01'
            ORDER BY date
        """)
        
        if not df_2022.empty:
            print("\n=== 2022 SUMMER (INJECTION SEASON) ===")
            print(f"Start: {df_2022.iloc[0]['date']} - {df_2022.iloc[0]['percent_full']:.1f}% full")
            print(f"End: {df_2022.iloc[-1]['date']} - {df_2022.iloc[-1]['percent_full']:.1f}% full")
            print(f"Storage gain: {df_2022.iloc[-1]['gas_in_storage_twh'] - df_2022.iloc[0]['gas_in_storage_twh']:.1f} TWh")
        
        # Get 2022 winter data (should show withdrawal season with high stress)
        df_2022_winter = db.query("""
            SELECT * FROM storage_raw 
            WHERE date BETWEEN '2022-12-01' AND '2023-02-28'
            ORDER BY date
        """)
        
        if not df_2022_winter.empty:
            print("\n=== 2022-2023 WINTER (HIGH STRESS PERIOD) ===")
            print(f"Start: {df_2022_winter.iloc[0]['date']} - {df_2022_winter.iloc[0]['percent_full']:.1f}% full")
            print(f"End: {df_2022_winter.iloc[-1]['date']} - {df_2022_winter.iloc[-1]['percent_full']:.1f}% full")
            print(f"Storage draw: {df_2022_winter.iloc[0]['gas_in_storage_twh'] - df_2022_winter.iloc[-1]['gas_in_storage_twh']:.1f} TWh")
        
        # Data quality check
        df_all = db.query("SELECT * FROM storage_raw ORDER BY date")
        
        print("\n=== DATA QUALITY ===")
        print(f"Total rows: {len(df_all)}")
        print(f"Date range: {df_all['date'].min()} to {df_all['date'].max()}")
        print(f"Missing values:")
        print(df_all.isnull().sum())
        
        # Check for gaps in dates
        df_all['date'] = pd.to_datetime(df_all['date'])
        date_range = pd.date_range(df_all['date'].min(), df_all['date'].max(), freq='D')
        missing_dates = date_range.difference(df_all['date'])
        
        if len(missing_dates) > 0:
            print(f"\n⚠ Missing {len(missing_dates)} dates in range")
            if len(missing_dates) <= 10:
                print(f"Missing dates: {missing_dates.tolist()}")
        else:
            print("\n✓ No gaps in date sequence")
        
        print("\n✓ Inspection complete!")


if __name__ == "__main__":
    inspect_storage_data()
