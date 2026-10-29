"""
Compute the dashboard metrics and rebuild the derived_metrics table.

- Storage Adequacy: where today's fill level sits within the min-max range of the
  same calendar window (±14 days) in each of the previous 5 years (0 = at the
  5-year low, 100 = at the 5-year high).
- Net imports: sum of entries minus exits at EU external border points and LNG
  terminals (see ingest/fetch_border_flows.py).
- Supply Security: 100 * (1 - HHI/10000), where HHI is computed on the shares of
  each supply corridor in that day's positive net imports.
"""
import logging
import sys
from pathlib import Path

import pandas as pd

sys.path.append(str(Path(__file__).parent.parent))

from config import DB_PATH
from utils import GasMonitorDB, setup_logging

logger = logging.getLogger(__name__)

HISTORY_YEARS = 5
WINDOW_DAYS = 14
MIN_HISTORY_YEARS = 3
# A day of flow data counts as complete once this share of the usual rows is in
COMPLETENESS_THRESHOLD = 0.9


def compute_storage_metrics(db: GasMonitorDB) -> pd.DataFrame:
    df = db.query(f"""
        WITH hist AS (
            SELECT
                a.date,
                MIN(b.percent_full) AS hist_min_pct,
                MAX(b.percent_full) AS hist_max_pct,
                AVG(b.percent_full) AS hist_mean_pct,
                COUNT(DISTINCT k.k) AS hist_years
            FROM storage_raw a
            CROSS JOIN range(1, {HISTORY_YEARS + 1}) AS k(k)
            JOIN storage_raw b
              ON b.date BETWEEN a.date - INTERVAL (k.k) YEAR - INTERVAL {WINDOW_DAYS} DAY
                            AND a.date - INTERVAL (k.k) YEAR + INTERVAL {WINDOW_DAYS} DAY
            GROUP BY a.date
        )
        SELECT s.date, s.gas_in_storage_twh, s.percent_full, s.injection_twh, s.withdrawal_twh,
               h.hist_min_pct, h.hist_max_pct, h.hist_mean_pct, COALESCE(h.hist_years, 0) AS hist_years
        FROM storage_raw s
        LEFT JOIN hist h USING (date)
        ORDER BY s.date
    """)

    span = df['hist_max_pct'] - df['hist_min_pct']
    adequacy = (100 * (df['percent_full'] - df['hist_min_pct']) / span).clip(0, 100)
    enough = (df['hist_years'] >= MIN_HISTORY_YEARS) & (span > 0.1)
    df['storage_adequacy'] = adequacy.where(enough)

    logger.info(f"Storage metrics: {len(df)} days, latest adequacy "
                f"{df['storage_adequacy'].iloc[-1]:.1f} ({df['date'].iloc[-1]})")
    return df


def compute_flow_metrics(db: GasMonitorDB) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Returns (daily totals, daily net imports by route), complete days only."""
    routes = db.query("""
        SELECT date, route,
               SUM(CASE WHEN direction = 'entry' THEN value_gwh ELSE -value_gwh END) AS net_gwh
        FROM border_flows
        GROUP BY date, route
        ORDER BY date, route
    """)
    counts = db.query("SELECT date, COUNT(*) AS n FROM border_flows GROUP BY date ORDER BY date")

    if routes.empty:
        return pd.DataFrame(), pd.DataFrame()

    # Trailing days are often only partly reported; drop them rather than show a fake dip
    usual = counts['n'].rolling(30, min_periods=1).median()
    complete = counts.loc[counts['n'] >= COMPLETENESS_THRESHOLD * usual, 'date']
    dropped = len(counts) - len(complete)
    if dropped:
        logger.info(f"Skipping {dropped} incomplete flow day(s), e.g. "
                    f"{sorted(set(counts['date']) - set(complete))[-3:]}")
    routes = routes[routes['date'].isin(complete)]

    pivot = routes.pivot(index='date', columns='route', values='net_gwh').fillna(0)
    positive = pivot.clip(lower=0)
    shares = positive.div(positive.sum(axis=1), axis=0)
    hhi = (shares ** 2).sum(axis=1) * 10000

    daily = pd.DataFrame({
        'date': pivot.index,
        'net_import_gwh': pivot.sum(axis=1).values,
        'import_hhi': hhi.values,
        'supply_security': (100 * (1 - hhi / 10000)).values,
    })

    logger.info(f"Flow metrics: {len(daily)} days, latest net imports "
                f"{daily['net_import_gwh'].iloc[-1]:.0f} GWh/d, security "
                f"{daily['supply_security'].iloc[-1]:.1f} ({daily['date'].iloc[-1]})")
    return daily, routes


def band(value, labels):
    if pd.isna(value):
        return None
    return labels[min(int(value // 20), 4)]


ADEQUACY_BANDS = ['Very Low', 'Low', 'Normal', 'High', 'Very High']
SECURITY_BANDS = ['Very Fragile', 'Fragile', 'Moderate', 'Diverse', 'Very Diverse']


def main():
    setup_logging()

    with GasMonitorDB(DB_PATH) as db:
        db.init_schema()
        storage = compute_storage_metrics(db)
        flows, _ = compute_flow_metrics(db)
        prices = db.query("SELECT date, ttf_eur_mwh AS ttf_price_eur_mwh FROM prices")

        df = storage[['date', 'storage_adequacy', 'hist_min_pct', 'hist_max_pct', 'hist_mean_pct']]
        df = df.merge(flows, on='date', how='outer') if not flows.empty else df
        df = df.merge(prices, on='date', how='left').sort_values('date')
        # TTF does not trade on weekends/holidays: carry the last settlement forward,
        # but only across short gaps so a broken price feed shows as missing, not flat
        df['ttf_price_eur_mwh'] = df['ttf_price_eur_mwh'].ffill(limit=4)
        df['storage_adequacy_band'] = df['storage_adequacy'].apply(band, labels=ADEQUACY_BANDS)
        df['supply_security_band'] = df['supply_security'].apply(band, labels=SECURITY_BANDS)
        df['updated_at'] = pd.Timestamp.now()

        db.conn.register('metrics_df', df)
        db.conn.execute("CREATE OR REPLACE TABLE derived_metrics AS SELECT * FROM metrics_df ORDER BY date")
        db.conn.unregister('metrics_df')
        logger.info(f"✓ derived_metrics rebuilt: {len(df)} rows")

    return 0


if __name__ == "__main__":
    sys.exit(main())
