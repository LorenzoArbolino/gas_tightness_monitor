"""
Fetch EU external-border gas flows from the ENTSOG Transparency Platform.

Why this exists: the old pipeline downloaded every ENTSOG point (thousands of
intra-EU interconnections, storage and distribution points) and classified them
with a hand-written substring list. Most volume ended up as "Other", so intra-EU
transit was counted as "imports" and dominated the concentration index.

Here we use ENTSOG's per-operator point metadata (operatorpointdirections) to
select only the points where gas crosses the EU-27 border or leaves an LNG
terminal, reported by the EU-side TSO, and skip rows ENTSOG flags as pipe-in-pipe
duplicates. EU net imports for a day are then sum(entries) - sum(exits) over
those points.
"""
import logging
import sys
import time
from datetime import datetime, timedelta
from pathlib import Path

import pandas as pd
import requests

sys.path.append(str(Path(__file__).parent.parent))

from config import ENTSOG_BASE_URL, REFERENCE_DATA_DIR, DB_PATH
from utils import GasMonitorDB, setup_logging

logger = logging.getLogger(__name__)

CATALOG_PATH = REFERENCE_DATA_DIR / "entsog_border_points.csv"

EU27 = {
    'AT', 'BE', 'BG', 'HR', 'CY', 'CZ', 'DK', 'EE', 'FI', 'FR', 'DE', 'GR', 'HU', 'IE',
    'IT', 'LV', 'LT', 'LU', 'MT', 'NL', 'PL', 'PT', 'RO', 'SK', 'SI', 'ES', 'SE',
}

# TAP AG is registered in Switzerland, so ENTSOG tags it as non-EU. Its gas enters
# the EU at Kipoi (Turkey -> Greece); its deliveries into Greece, Bulgaria and Italy
# are then intra-EU and must not be counted again.
TAP_OPERATOR = 'AL-TSO-0001'
TAP_KIPOI = 'ITP-00274'

# Points that duplicate another point's flows without ENTSOG flagging them:
# Dornum GASPOOL repeats Dornum / NETRA (OGE), ITP-00126; Wallbach is part of
# VIP Germany-CH, ITP-00544, and reports identical values.
DUPLICATE_POINTS = {'ITP-00525', 'ITP-00294'}

# EU-border points that ENTSOG's metadata misclassifies as in-country:
# (point_key, operator_key, direction, counterpart)
MANUAL_POINTS = [
    ('ITP-00048', 'ES-TSO-0006', 'entry', 'DZ'),   # Almería: Medgaz pipeline from Algeria
]

# Counterpart country -> supply corridor. Countries that gas transits through
# (Serbia, Belarus, Tunisia, ...) are grouped with the corridor they belong to, so
# an EU exit into a transit country nets against the later EU re-entry.
CORRIDORS = {
    'NO': 'Norway',
    'UK': 'UK',
    'DZ': 'Algeria',
    'TN': 'Algeria',      # TransMed: Algerian gas via Tunisia into Mazara del Vallo
    'MA': 'Algeria',      # Maghreb pipeline (idle since 2021, now reverse ES->MA)
    'LY': 'Libya',
    'RU': 'Russia (direct)',
    'BY': 'Russia (direct)',
    'UA': 'Ukraine/Moldova',
    'MD': 'Ukraine/Moldova',
    'RS': 'TurkStream',
    'MK': 'TurkStream',
    'CH': 'Switzerland',
}


def _corridor(counterpart: str, eu_country: str) -> str:
    if counterpart == 'LNG':
        return 'LNG'
    if counterpart == 'TR':
        # Turkey -> Greece is TANAP/TAP (Azerbaijani gas); Turkey -> Bulgaria is TurkStream
        return 'Azerbaijan (TAP)' if eu_country == 'GR' else 'TurkStream'
    return CORRIDORS.get(counterpart, 'Other')


def build_point_catalog(session: requests.Session = None) -> pd.DataFrame:
    """Build the list of EU-border point/operator/direction combinations from ENTSOG metadata."""
    session = session or requests.Session()
    resp = session.get(f"{ENTSOG_BASE_URL}/operatorpointdirections", params={'limit': -1}, timeout=300)
    resp.raise_for_status()
    opd = pd.DataFrame(resp.json()['operatorpointdirections'])

    is_tap_entry = (opd['operatorKey'] == TAP_OPERATOR) & (opd['pointKey'] == TAP_KIPOI)
    is_border = (
        opd['tSOCountry'].isin(EU27)
        & opd['adjacentCountry'].notna()
        & ~opd['adjacentCountry'].isin(EU27)
        & opd['crossBorderPointType'].fillna('').str.startswith('Cross-Border')
        & (opd['adjacentOperatorKey'] != TAP_OPERATOR)
    )
    is_lng = (
        opd['pointKey'].str.startswith('LNG')
        & opd['tSOCountry'].isin(EU27)
        & (opd['directionKey'] == 'entry')
    )
    keep = (
        (is_border | is_lng | is_tap_entry)
        & (opd['pipeInPipeWithTsoKey'].fillna('') == '')
        & ~opd['pointKey'].isin(DUPLICATE_POINTS)
    )
    sel = opd[keep].copy()
    for point_key, operator_key, direction, counterpart in MANUAL_POINTS:
        match = ((opd['pointKey'] == point_key) & (opd['operatorKey'] == operator_key)
                 & (opd['directionKey'] == direction))
        sel = pd.concat([sel, opd[match].assign(adjacentCountry=counterpart)])

    catalog = pd.DataFrame({
        'point_key': sel['pointKey'],
        'point_label': sel['pointLabel'],
        'operator_key': sel['operatorKey'],
        'operator_label': sel['operatorLabel'],
        'direction': sel['directionKey'],
        'eu_country': sel['tSOCountry'].where(~is_tap_entry[sel.index], 'GR'),
        'counterpart': sel['adjacentCountry'].where(~is_lng[sel.index], 'LNG'),
    })
    catalog['route'] = [_corridor(c, e) for c, e in zip(catalog['counterpart'], catalog['eu_country'])]
    catalog = catalog.drop_duplicates(subset=['point_key', 'operator_key', 'direction'])
    return catalog.sort_values(['route', 'point_label', 'operator_key', 'direction']).reset_index(drop=True)


def load_point_catalog(refresh: bool = False) -> pd.DataFrame:
    """Load the cached catalog, rebuilding it from the ENTSOG API if missing or asked to."""
    if refresh or not CATALOG_PATH.exists():
        catalog = build_point_catalog()
        CATALOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        catalog.to_csv(CATALOG_PATH, index=False)
        logger.info(f"✓ Saved {len(catalog)} border points to {CATALOG_PATH}")
        return catalog
    return pd.read_csv(CATALOG_PATH)


def fetch_border_flows(start_date: str, end_date: str, catalog: pd.DataFrame = None,
                       chunk_size: int = 40) -> pd.DataFrame:
    """Fetch daily physical flows (GWh/d) at the EU border points between two dates (inclusive)."""
    catalog = catalog if catalog is not None else load_point_catalog()
    keys = (catalog['operator_key'] + catalog['point_key'] + catalog['direction']).tolist()

    session = requests.Session()
    session.headers.update({'Accept': 'application/json'})
    records = []

    # ENTSOG's "to" bound is exclusive at day granularity
    to_date = (datetime.strptime(end_date, '%Y-%m-%d') + timedelta(days=1)).strftime('%Y-%m-%d')

    for i in range(0, len(keys), chunk_size):
        params = {
            'from': start_date,
            'to': to_date,
            'indicator': 'Physical Flow',
            'periodType': 'day',
            'timezone': 'CET',
            'limit': -1,
            'pointDirection': ','.join(keys[i:i + chunk_size]),
        }
        for attempt in range(3):
            resp = session.get(f"{ENTSOG_BASE_URL}/operationaldatas", params=params, timeout=300)
            # ENTSOG answers 404 "No result found" when none of the points have data
            if resp.status_code == 404:
                break
            if resp.status_code < 500:
                resp.raise_for_status()
                records.extend(resp.json().get('operationaldatas', []))
                break
            logger.warning(f"ENTSOG returned {resp.status_code}, retrying ({attempt + 1}/3)")
            time.sleep(10 * (attempt + 1))
        else:
            resp.raise_for_status()

    if not records:
        return pd.DataFrame()

    df = pd.DataFrame(records)
    df['value'] = pd.to_numeric(df['value'], errors='coerce')
    df = df[df['value'].notna()]

    scale = {'kWh/d': 1e-6, 'MWh/d': 1e-3, 'GWh/d': 1.0}
    unknown = set(df['unit']) - set(scale)
    if unknown:
        logger.warning(f"Dropping rows with unexpected units: {unknown}")
        df = df[df['unit'].isin(scale)]

    out = pd.DataFrame({
        # Gas day starts 06:00 local; the CET calendar date of periodFrom is the gas day
        'date': pd.to_datetime(df['periodFrom'].str[:10]).dt.date,
        'point_key': df['pointKey'],
        'operator_key': df['operatorKey'],
        'direction': df['directionKey'],
        'value_gwh': df['value'] * df['unit'].map(scale),
    })
    out = out.merge(catalog[['point_key', 'operator_key', 'direction', 'route']],
                    on=['point_key', 'operator_key', 'direction'], how='inner')
    # A point can be reported in several rows (e.g. per capacity type); keep one per day
    out = out.groupby(['date', 'point_key', 'operator_key', 'direction', 'route'],
                      as_index=False)['value_gwh'].max()
    out = out[(out['date'] >= pd.to_datetime(start_date).date())
              & (out['date'] <= pd.to_datetime(end_date).date())]
    return out


def save_border_flows(df: pd.DataFrame, start_date: str, end_date: str):
    """Replace the given date range in the border_flows table."""
    with GasMonitorDB(DB_PATH) as db:
        db.init_schema()
        db.conn.execute("DELETE FROM border_flows WHERE date BETWEEN ? AND ?", [start_date, end_date])
        if not df.empty:
            db.insert_dataframe(df, 'border_flows', if_exists='append')


def fetch_and_save(start_date: str, end_date: str, batch_days: int = 120) -> int:
    """Fetch a (possibly long) date range in batches and store it. Returns rows saved."""
    catalog = load_point_catalog()
    start = datetime.strptime(start_date, '%Y-%m-%d')
    end = datetime.strptime(end_date, '%Y-%m-%d')
    total = 0
    while start <= end:
        batch_end = min(start + timedelta(days=batch_days - 1), end)
        s, e = start.strftime('%Y-%m-%d'), batch_end.strftime('%Y-%m-%d')
        df = fetch_border_flows(s, e, catalog)
        save_border_flows(df, s, e)
        logger.info(f"  {s} → {e}: {len(df)} rows")
        total += len(df)
        start = batch_end + timedelta(days=1)
    return total


def main():
    import argparse

    parser = argparse.ArgumentParser(description='Fetch EU border gas flows from ENTSOG')
    parser.add_argument('--start', default=None, help='Start date YYYY-MM-DD (default: --days ago)')
    parser.add_argument('--days', type=int, default=14)
    parser.add_argument('--refresh-catalog', action='store_true',
                        help='Rebuild the border point list from ENTSOG metadata')
    args = parser.parse_args()

    setup_logging()
    if args.refresh_catalog:
        load_point_catalog(refresh=True)

    end_date = datetime.now().strftime('%Y-%m-%d')
    start_date = args.start or (datetime.now() - timedelta(days=args.days)).strftime('%Y-%m-%d')
    total = fetch_and_save(start_date, end_date)
    logger.info(f"✓ Saved {total} border flow rows")
    return 0 if total > 0 else 1


if __name__ == "__main__":
    sys.exit(main())
