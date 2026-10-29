"""
Export the dashboard data from DuckDB to site/data.json for the static
GitHub Pages dashboard (site/index.html).

Usage:
    python export_site_data.py
"""
import json
import logging
import math
import sys
from datetime import datetime, timezone
from pathlib import Path

sys.path.append(str(Path(__file__).parent / "src"))

from config import DB_PATH, PROJECT_ROOT
from utils import GasMonitorDB, setup_logging
from transform.compute_metrics import compute_flow_metrics

logger = logging.getLogger(__name__)

OUTPUT_PATH = PROJECT_ROOT / "site" / "data.json"
START_DATE = '2021-01-01'


def column(series, digits):
    """Round a pandas Series to a JSON-safe list (NaN -> null)."""
    return [None if v is None or (isinstance(v, float) and math.isnan(v)) else round(float(v), digits)
            for v in series]


def main():
    with GasMonitorDB(DB_PATH) as db:
        metrics = db.query(f"""
            SELECT m.date, s.percent_full, s.gas_in_storage_twh, s.injection_twh, s.withdrawal_twh,
                   m.hist_min_pct, m.hist_max_pct, m.hist_mean_pct, m.storage_adequacy,
                   m.net_import_gwh, m.supply_security, m.ttf_price_eur_mwh
            FROM derived_metrics m
            LEFT JOIN storage_raw s USING (date)
            WHERE m.date >= '{START_DATE}'
            ORDER BY m.date
        """)
        _, routes = compute_flow_metrics(db)
        last_price = db.get_latest_date('prices')

    if metrics.empty:
        logger.error("No metrics to export")
        return 1

    def last_date(col):
        valid = metrics.loc[metrics[col].notna(), 'date']
        return valid.max().strftime('%Y-%m-%d') if not valid.empty else None

    routes = routes[routes['date'] >= START_DATE]
    pivot = routes.pivot(index='date', columns='route', values='net_gwh').fillna(0).sort_index()
    # Largest corridors first so the stacked chart reads bottom-up by size
    order = pivot.clip(lower=0).sum().sort_values(ascending=False).index.tolist()

    payload = {
        'generated_at': datetime.now(timezone.utc).strftime('%Y-%m-%dT%H:%M:%SZ'),
        'as_of': {
            'storage': last_date('percent_full'),
            'flows': last_date('net_import_gwh'),
            'prices': last_price,
        },
        'daily': {
            'date': metrics['date'].dt.strftime('%Y-%m-%d').tolist(),
            'percent_full': column(metrics['percent_full'], 2),
            'storage_twh': column(metrics['gas_in_storage_twh'], 1),
            'injection_twh': column(metrics['injection_twh'], 3),
            'withdrawal_twh': column(metrics['withdrawal_twh'], 3),
            'hist_min_pct': column(metrics['hist_min_pct'], 2),
            'hist_max_pct': column(metrics['hist_max_pct'], 2),
            'hist_mean_pct': column(metrics['hist_mean_pct'], 2),
            'storage_adequacy': column(metrics['storage_adequacy'], 1),
            'net_import_gwh': column(metrics['net_import_gwh'], 0),
            'supply_security': column(metrics['supply_security'], 1),
            'ttf_eur_mwh': column(metrics['ttf_price_eur_mwh'], 2),
        },
        'routes': {
            'date': [d.strftime('%Y-%m-%d') for d in pivot.index],
            'series': {route: column(pivot[route], 0) for route in order},
        },
    }

    OUTPUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUTPUT_PATH.write_text(json.dumps(payload, separators=(',', ':')))
    logger.info(f"✓ Wrote {OUTPUT_PATH} ({OUTPUT_PATH.stat().st_size / 1024:.0f} KB), as of {payload['as_of']}")
    return 0


if __name__ == "__main__":
    setup_logging()
    sys.exit(main())
