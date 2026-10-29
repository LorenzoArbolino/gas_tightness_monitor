"""
DuckDB database utilities
"""
import duckdb
import pandas as pd
from pathlib import Path
from typing import Optional, List
import logging

logger = logging.getLogger(__name__)


class GasMonitorDB:
    """Context manager for DuckDB database operations"""
    
    def __init__(self, db_path: Path):
        self.db_path = db_path
        self.conn = None
        
    def __enter__(self):
        # Ensure directory exists
        self.db_path.parent.mkdir(parents=True, exist_ok=True)
        self.conn = duckdb.connect(str(self.db_path))
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if self.conn:
            self.conn.close()
    
    def init_schema(self):
        """Initialize database schema"""
        
        # Storage raw data
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS storage_raw (
                date DATE PRIMARY KEY,
                gas_in_storage_twh FLOAT,
                percent_full FLOAT,
                injection_twh FLOAT,
                withdrawal_twh FLOAT,
                working_gas_volume_twh FLOAT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        
        # Flows at EU external border points and LNG terminals (see ingest/fetch_border_flows.py)
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS border_flows (
                date DATE,
                point_key VARCHAR,
                operator_key VARCHAR,
                direction VARCHAR,
                route VARCHAR,
                value_gwh DOUBLE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date, point_key, operator_key, direction)
            )
        """)

        # Daily TTF front-month settlement
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS prices (
                date DATE PRIMARY KEY,
                ttf_eur_mwh DOUBLE,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Weather raw data
        self.conn.execute("""
            CREATE TABLE IF NOT EXISTS weather_raw (
                date DATE,
                region VARCHAR,
                temp_mean_c FLOAT,
                hdd FLOAT,
                population_weight FLOAT,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
                PRIMARY KEY (date, region)
            )
        """)
        
        # derived_metrics is rebuilt from scratch by transform/compute_metrics.py

        logger.info("✓ Database schema initialized")
    
    def insert_dataframe(self, df: pd.DataFrame, table: str, if_exists: str = 'append'):
        """Insert pandas DataFrame into table"""
        
        # Add updated_at timestamp if not present
        if 'updated_at' not in df.columns:
            df = df.copy()
            df['updated_at'] = pd.Timestamp.now()
        
        if if_exists == 'replace':
            self.conn.execute(f"DELETE FROM {table}")
            # For replace, insert all columns
            self.conn.execute(f"INSERT INTO {table} SELECT * FROM df")
        else:
            # For append, use explicit column list to handle partial updates
            cols = ', '.join(df.columns)
            
            # Use INSERT with explicit columns (allows partial column inserts).
            # Callers delete the date range first; a duplicate key here is a real error
            # (DuckDB rejects the whole batch, so swallowing it would silently lose data).
            self.conn.execute(f"INSERT INTO {table} ({cols}) SELECT {cols} FROM df")
        
        logger.info(f"✓ Inserted {len(df)} rows into {table}")
    
    def query(self, sql: str) -> pd.DataFrame:
        """Execute query and return DataFrame"""
        return self.conn.execute(sql).df()
    
    def get_latest_date(self, table: str, date_column: str = 'date') -> Optional[str]:
        """Get the most recent date in a table"""
        result = self.conn.execute(
            f"SELECT MAX({date_column}) as max_date FROM {table}"
        ).fetchone()
        
        if result and result[0]:
            return result[0].strftime('%Y-%m-%d')
        return None
    
    def get_row_count(self, table: str, where: str = "") -> int:
        """Get row count for a table"""
        where_clause = f"WHERE {where}" if where else ""
        result = self.conn.execute(
            f"SELECT COUNT(*) FROM {table} {where_clause}"
        ).fetchone()
        return result[0] if result else 0


def initialize_database(db_path: Path):
    """Initialize database with schema"""
    with GasMonitorDB(db_path) as db:
        db.init_schema()
    logger.info(f"✓ Database initialized at {db_path}")
