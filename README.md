# European Gas Market Fundamentals Monitor

A real-time monitoring dashboard for European natural gas market fundamentals. Aggregates publicly available data on storage levels, import flows, and supply diversification to provide an objective view of EU gas market conditions.

## What This Tool Shows

- **EU gas storage levels and seasonal adequacy** - Compare current storage to 5-year historical baselines
- **Import flows by source and supply concentration** - Track diversification of gas supply routes
- **Historical context** - 5-year baselines for all key metrics

## Live Dashboard

https://lorenzoarbolino.github.io/gas_tightness_monitor/

A static page on GitHub Pages, rebuilt every day by a GitHub Actions workflow, so there is no server to fall asleep.

## Methodology

### Storage Adequacy Index

Places today's storage fill level within the range seen at the same time of year over the previous 5 years.

**Formula:**
```
Storage Adequacy = (Current % full - 5Y Min) / (5Y Max - 5Y Min) × 100
```

Where:
- 5Y Min / Max = lowest / highest % full in a ±14-day window around the same date in each of the previous 5 years
- 0 = at the 5-year low for this time of year
- 100 = at the 5-year high for this time of year
- Requires at least 3 years of history

**Classification:** 0-20 Very Low · 20-40 Low · 40-60 Normal · 60-80 High · 80-100 Very High

**Interpretation:** "Storage sits X% of the way between the 5-year low and high for this time of year." This is a position in a range, not a statistical percentile.

---

### Net Imports

Entries minus exits at every point where gas crosses the EU-27 border, plus LNG terminal send-out (GWh/day).

The set of points is derived from ENTSOG's own metadata (`operatorpointdirections`): only points whose reporting operator is in the EU and whose adjacent system is outside it, plus LNG entry points. Rows that ENTSOG flags as pipe-in-pipe duplicates are skipped. Intra-EU interconnections are excluded, and transit through non-EU countries (TurkStream gas via Serbia, Kaliningrad transit via Lithuania, Swiss transit to Italy) nets out within its corridor. See `src/ingest/fetch_border_flows.py` for the handful of hand-made corrections (TAP, Almería, two duplicate points).

Each point is assigned to a supply corridor: Norway, LNG, Algeria, Azerbaijan (TAP), TurkStream, UK, Libya, Russia (direct), Ukraine/Moldova, Switzerland.

---

### Supply Security Index

Measures diversification of supply corridors using the Herfindahl-Hirschman Index (HHI).

**Formula:**
```
HHI = Σ (share_i²) × 10,000
Supply Security = 100 × (1 - HHI / 10,000)
```

Where:
- share_i = corridor i's share of that day's positive net imports
- 0 = a single corridor supplies everything
- 100 = perfectly spread across many corridors

**Classification:** 0-20 Very Fragile · 20-40 Fragile · 40-60 Moderate · 60-80 Diverse · 80-100 Very Diverse

---

## Data Sources

| Data Type | Source | Update Frequency |
|-----------|--------|------------------|
| **Storage** | [AGSI+ Transparency Platform](https://agsi.gie.eu/) (GIE) | Daily |
| **Flows** | [ENTSOG Transparency Platform](https://transparency.entsog.eu/) | Daily |
| **Prices** | Yahoo Finance (TTF futures) | Daily |

All data sources are publicly available and free to access.

---

## How It Runs

```
GitHub Actions (daily 22:00 UTC)
  │  download gas_monitor.duckdb from the "data" release
  ├─ fetch AGSI storage   ─┐
  ├─ fetch ENTSOG flows    ├─ from a week before the latest stored date,
  ├─ fetch TTF prices     ─┘  so outages are back-filled automatically
  ├─ compute metrics  →  derived_metrics table
  ├─ export site/data.json
  ├─ upload the database back to the "data" release
  └─ deploy site/ to GitHub Pages
```

The live database is stored as an asset of the `data` release instead of being committed every day, so the git history does not grow by a binary file a day. `data/processed/gas_monitor.duckdb` in the repo is a seed snapshot for the first run.

### One-time setup (repository owner)

1. **Add the GIE API key secret**: Settings → Secrets and variables → Actions → New repository secret, name `GIE_API_KEY`. Free key: [AGSI+ registration](https://agsi.gie.eu/account).
2. **Enable GitHub Pages**: Settings → Pages → Build and deployment → Source: **GitHub Actions**.
3. Run the workflow once by hand: Actions → *Update data and deploy dashboard* → Run workflow.

---

## Local Development

```bash
git clone https://github.com/LorenzoArbolino/gas_tightness_monitor.git
cd gas_tightness_monitor
python -m venv .venv && source .venv/bin/activate
pip install -r requirements.txt
echo "GIE_API_KEY=your_api_key_here" > .env

# Optional: start from the latest live database instead of the seed snapshot
gh release download data --pattern gas_monitor.duckdb --dir data/processed --clobber

python update_data.py                 # fetch, compute, export site/data.json
python -m http.server 8000 --directory site   # open http://localhost:8000
```

Useful one-off commands:

```bash
python src/ingest/fetch_agsi.py --batched            # full storage history from 2019
python src/ingest/fetch_border_flows.py --start 2021-01-01 --refresh-catalog   # rebuild flow history
python src/transform/compute_metrics.py               # recompute metrics only
python export_site_data.py                            # re-export dashboard JSON only
```

---

## Project Structure

```
gas_tightness_monitor/
├── site/                      # Static dashboard (GitHub Pages)
│   ├── index.html, app.js, style.css
│   └── data.json              # generated, not committed
├── data/
│   ├── processed/gas_monitor.duckdb   # seed snapshot (live copy: "data" release)
│   └── reference/entsog_border_points.csv   # EU border points and corridors
├── src/
│   ├── ingest/                # AGSI, ENTSOG and weather fetchers
│   ├── transform/compute_metrics.py
│   └── utils/                 # Database & logging utilities
├── update_data.py             # Daily pipeline entry point
├── export_site_data.py        # DuckDB → site/data.json
└── .github/workflows/update_data.yml
```

---

## Limitations

**Please read these carefully:**

1. **Data Reflects Reported Values**: All data is sourced from public APIs and subject to revisions or reporting delays.

2. **No Demand Forecasts**: This dashboard shows current supply-side fundamentals only. It does not account for future demand changes or policy interventions.

3. **Historical Baselines May Not Reflect Structural Changes**: The 5-year lookback assumes market structure is relatively stable. Major geopolitical shifts (like the 2022 Russia-Ukraine war) can fundamentally alter what "normal" means.

4. **Supply Security Index Limitations**:
   - HHI measures concentration, not reliability (a diversified mix can still be insecure if all routes are vulnerable)
   - All LNG counts as one corridor, although LNG itself comes from many countries
   - Does not account for spare capacity or LNG regasification limits
   - Transit risks and pipeline constraints are not modeled

5. **Pre-2023 Russian flows are understated**: ENTSOG's current metadata no longer lists points that were retired after 2022 (e.g. Yamal via Kondratki, Poland), so 2021-2022 net imports miss those volumes.

6. **Price Context Only**: TTF prices are displayed for context, NOT as a predictive signal. Gas prices are influenced by many factors beyond the fundamentals shown here (speculation, policy, weather forecasts, global LNG arbitrage, etc.).

7. **Not Investment Advice**: This tool is for educational and research purposes. Do not use it to make trading or investment decisions.

---

## Use Cases

### Who Is This For?

- **Energy Analysts**: Track EU gas market fundamentals in real-time
- **Journalists**: Fact-check claims about gas storage or supply security
- **Researchers**: Access structured historical data for academic studies
- **Policymakers**: Monitor market conditions with transparent, reproducible metrics
- **Curious Traders**: Understand fundamentals (but remember: prices ≠ fundamentals!)

### What This Tool Does Well

- Provides **objective, transparent metrics** based on public data
- Offers **historical context** (5-year baselines) for current conditions
- Tracks **supply diversification** and import route dependencies
- Updates **automatically** with new data (when deployed)

### What This Tool Does NOT Do

- **Predict prices** (fundamentals are just one factor among many)
- **Detect crises in advance** (real-time monitoring, not forecasting)
- **Account for policy interventions** (e.g., EU storage mandates override market signals)
- **Model demand shocks** (e.g., industrial shutdowns, cold snaps)

---

## Future Enhancements

Potential improvements for future versions:

### Near-term (with existing data)
- Add injection/withdrawal rate indicators (not just levels)
- Seasonal weighting (storage matters more in winter)
- Price momentum filters (flag extreme regime changes)

### Medium-term (new data sources)
- LNG spot price spreads (arbitrage signals)
- Pipeline utilization metrics (capacity constraints)
- Regional storage breakdown (Germany, Italy, France, etc.)

### Long-term (external signals)
- Geopolitical risk index (qualitative crisis detection)
- Policy indicator tracking (EU mandates, interventions)
- Machine learning on expanded feature set

---

## Contributing

Contributions are welcome! Please:

1. Fork the repository
2. Create a feature branch (`git checkout -b feature/YourFeature`)
3. Commit your changes (`git commit -m 'Add YourFeature'`)
4. Push to the branch (`git push origin feature/YourFeature`)
5. Open a Pull Request

---

## License & Disclaimer

**License**: MIT License

**Disclaimer**: This project is provided "as is" without warranty of any kind, express or implied. The authors and contributors make no representations about the accuracy, completeness, or suitability of the information displayed. Use at your own risk. This is not investment, financial, legal, or professional advice. Always verify critical information with primary sources.

**Attribution**: Data sourced from GIE AGSI+, ENTSOG and Yahoo Finance. All trademarks are property of their respective owners.

---

## Acknowledgments

- **GIE (Gas Infrastructure Europe)** for the AGSI+ storage transparency platform
- **ENTSOG** for the flow transparency platform
- **Yahoo Finance** for market price data

---

## Contact

For questions, issues, or suggestions:
- GitHub Issues: [github.com/LorenzoArbolino/gas_tightness_monitor/issues](https://github.com/LorenzoArbolino/gas_tightness_monitor/issues)
- Email: [lorararbo@gmail.com](mailto:lorararbo@gmail.com)

---

**Built with:** Python, DuckDB, Pandas, Plotly.js, GitHub Actions, GitHub Pages

**Last Updated:** 2026-10-29
