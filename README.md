# European Gas Market Fundamentals Monitor

A real-time monitoring dashboard for European natural gas market fundamentals. Aggregates publicly available data on storage levels, import flows, and supply security to provide an objective view of EU gas market conditions.

## What This Tool Shows

- **EU gas storage levels and seasonal adequacy** - Compare current storage to 5-year historical baselines
- **Import flows by source and supply concentration** - Track diversification of gas supply routes
- **Historical context** - 5-year baselines for all key metrics

## Live Dashboard

https://lorenzoarbolino-gas-tightness-monitor-appdashboard-udxrec.streamlit.app/

## Methodology

### Storage Adequacy Index

Compares current storage to the same calendar period over the past 5 years.

**Formula:**
```
Storage Adequacy = (Current Storage - Historical Min) / (Historical Max - Historical Min) × 100
```

Where:
- Historical = same day-of-year ±14 days over past 5 years
- 0 = lowest historical level for this time of year
- 100 = highest historical level for this time of year

**Classification:**
- **0-20**: Very Low (🔴)
- **20-40**: Low (🟠)
- **40-60**: Normal (🟡)
- **60-80**: High (🟢)
- **80-100**: Very High (🟢)

**Interpretation:** "Storage is at the Xth percentile compared to the past 5 years for this time of year."

---

### Supply Security Index

Measures diversification of import sources using the Herfindahl-Hirschman Index (HHI).

**Formula:**
```
HHI = Σ (market_share_i²) × 10,000
Supply Security = 100 × (1 - HHI / 10,000)
```

Where:
- market_share_i = proportion of imports from source i (Norway, Algeria, LNG, etc.)
- 0 = highly concentrated (single dominant supplier)
- 100 = perfectly diversified (no dominant supplier)

**Classification:**
- **0-20**: Very Fragile (high concentration risk)
- **20-40**: Fragile
- **40-60**: Moderate
- **60-80**: Diverse
- **80-100**: Very Diverse

**Interpretation:** "EU imports are X% diversified across supply sources."

---

## Data Sources

| Data Type | Source | Update Frequency |
|-----------|--------|------------------|
| **Storage** | [AGSI+ Transparency Platform](https://agsi.gie.eu/) (GIE) | Daily |
| **Flows** | [ENTSOG Transparency Platform](https://transparency.entsog.eu/) | Daily |
| **Prices** | Yahoo Finance (TTF futures) | Daily |

All data sources are publicly available and free to access.

---

## Dashboard Structure

### 1. Key Metrics

Four headline metrics displayed at the top:
- **Storage Level**: Current EU storage in TWh and percentage of capacity
- **Storage Adequacy**: Percentile ranking vs 5-year history
- **Net Imports**: 7-day average import flow (GWh/day)
- **Supply Security**: Import diversification score (0-100)

### 2. Storage Overview

- **Storage Level Time Series**: Absolute storage (TWh) and percentage full over time
- **Storage Adequacy Index**: Percentile ranking with color-coded bands
- **Injection/Withdrawal Flows**: Daily storage changes (positive = injection, negative = withdrawal)

### 3. Import Flows

- **Net Import Trends**: Daily imports with 30-day moving average
- **Import Sources Breakdown**: Stacked area chart showing evolution of supply mix by route (Norway, Algeria, Azerbaijan, LNG, etc.)
- **Supply Security Index**: Diversification score over time with color-coded risk bands

### 4. Market Context

- **TTF Price Context**: EU gas benchmark price (EUR/MWh) for reference only

### 5. Data Summary Table

Historical comparison showing current values vs 1 week, 1 month, 1 year ago, plus 5-year min/max ranges.

---

## Installation & Local Development

### Requirements

- Python 3.9+
- pip

### Setup

1. Clone the repository:
```bash
git clone https://github.com/yourusername/gas_tightness_monitor.git
cd gas_tightness_monitor
```

2. Create virtual environment and install dependencies:
```bash
python -m venv .venv
source .venv/bin/activate  # On Windows: .venv\Scripts\activate
pip install -r requirements.txt
```

3. Create a `.env` file with your GIE API key:
```
GIE_API_KEY=your_api_key_here
```

Get a free API key at [AGSI+ Registration](https://agsi.gie.eu/#/registration).

4. Initialize the database and fetch historical data:
```bash
# Fetch storage data (last 7 days)
python src/ingest/fetch_agsi.py

# Fetch flow data (historical batch - takes ~30 mins for 5 years)
python fetch_historical_flows.py

# Fetch weather data
python src/ingest/fetch_weather.py

# Fetch TTF prices
python src/backtest/fetch_ttf_prices.py

# Compute metrics
python src/transform/compute_storage_metrics.py
python src/transform/compute_simple_indices.py
```

5. Run the dashboard:
```bash
streamlit run app/dashboard.py
```

The dashboard will open in your browser at `http://localhost:8501`.

---

## Project Structure

```
gas_tightness_monitor/
├── app/
│   └── dashboard.py           # Streamlit dashboard
├── data/
│   ├── processed/
│   │   └── gas_monitor.duckdb # DuckDB database
│   └── raw/                   # CSV exports (optional)
├── src/
│   ├── ingest/                # Data fetching scripts
│   ├── transform/             # Metric computation
│   ├── backtest/              # Historical analysis
│   └── utils/                 # Database & logging utilities
├── outputs/                   # Charts and reports
├── .env                       # API keys
├── requirements.txt           # Python dependencies
└── README.md                  # This file
```

---

## Limitations

**Please read these carefully:**

1. **Data Reflects Reported Values**: All data is sourced from public APIs and subject to revisions or reporting delays.

2. **No Demand Forecasts**: This dashboard shows current supply-side fundamentals only. It does not account for future demand changes or policy interventions.

3. **Historical Baselines May Not Reflect Structural Changes**: The 5-year lookback assumes market structure is relatively stable. Major geopolitical shifts (like the 2022 Russia-Ukraine war) can fundamentally alter what "normal" means.

4. **Supply Security Index Limitations**:
   - HHI measures concentration, not reliability (a diversified mix can still be insecure if all routes are vulnerable)
   - Does not account for spare capacity or LNG regasification limits
   - Transit risks and pipeline constraints are not modeled

5. **Price Context Only**: TTF prices are displayed for context, NOT as a predictive signal. Gas prices are influenced by many factors beyond the fundamentals shown here (speculation, policy, weather forecasts, global LNG arbitrage, etc.).

6. **Not Investment Advice**: This tool is for educational and research purposes. Do not use it to make trading or investment decisions.

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

**License**: MIT License (see LICENSE file)

**Disclaimer**: This project is provided "as is" without warranty of any kind, express or implied. The authors and contributors make no representations about the accuracy, completeness, or suitability of the information displayed. Use at your own risk. This is not investment, financial, legal, or professional advice. Always verify critical information with primary sources.

**Attribution**: Data sourced from GIE AGSI+, ENTSOG, Open-Meteo, and Yahoo Finance. All trademarks are property of their respective owners.

---

## Acknowledgments

- **GIE (Gas Infrastructure Europe)** for the AGSI+ storage transparency platform
- **ENTSOG** for the flow transparency platform
- **Open-Meteo** for freely accessible weather data
- **Yahoo Finance** for market price data

---

## Contact

For questions, issues, or suggestions:
- GitHub Issues: [github.com/LorenzoArbolino/gas_tightness_monitor/issues](#)
- Email: [lorararbo@gmail.com](#)

---

**Built with:** Python, Streamlit, DuckDB, Plotly, Pandas

**Last Updated:** 2026-01-23
