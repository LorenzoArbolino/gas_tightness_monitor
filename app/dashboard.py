"""
European Gas Market Fundamentals Monitor
Production dashboard - Simple, transparent metrics
"""
import streamlit as st
import pandas as pd
import plotly.graph_objects as go
from plotly.subplots import make_subplots
from datetime import datetime, timedelta
import sys
from pathlib import Path

sys.path.append(str(Path(__file__).parent.parent / "src"))

from utils.db import GasMonitorDB

DB_PATH = Path(__file__).parent.parent / "data" / "processed" / "gas_monitor.duckdb"

# Page config
st.set_page_config(
    page_title="European Gas Market Monitor",
    page_icon="⚡",
    layout="wide",
    initial_sidebar_state="collapsed"
)

# Custom CSS
st.markdown("""
<style>
    .main-header {
        font-size: 2.5rem;
        font-weight: 700;
        color: #1f2937;
        margin-bottom: 0.25rem;
    }
    .sub-header {
        font-size: 1rem;
        color: #6b7280;
        margin-bottom: 0.5rem;
    }
    .data-sources {
        font-size: 0.85rem;
        color: #9ca3af;
        margin-bottom: 2rem;
    }
    .metric-label {
        font-size: 0.9rem;
        color: #6b7280;
        font-weight: 600;
        text-transform: uppercase;
        letter-spacing: 0.05em;
    }

    .metric-value {
        font-size: 2.5rem;
        font-weight: 400;
        line-height: 1;
        margin: 0.25rem 0;
        color: #111827;
    }
    .metric-value-suffix {
        font-size: 1.05rem;
        color: #6b7280;
        margin-left: 0.35rem;
        font-weight: 400;
    }
    .metric-subvalue {
        font-size: 0.95rem;
        color: #6b7280;
        margin-bottom: 0.5rem;
        font-weight: 400;
    }
    .metric-note {
        font-size: 0.85rem;
        color: #9ca3af;
        font-weight: 400;
    }
</style>
""", unsafe_allow_html=True)

# Title
st.markdown('<div class="main-header">⚡ EUROPEAN GAS MARKET MONITOR</div>', unsafe_allow_html=True)
st.markdown('<div class="sub-header">Real-time fundamentals tracking for European natural gas</div>', unsafe_allow_html=True)

# Load data
@st.cache_data(ttl=3600)
def load_data():
    with GasMonitorDB(DB_PATH) as db:
        # Main metrics
        df = db.query("""
            SELECT
                date,
                storage_adequacy,
                storage_adequacy_band,
                supply_security,
                supply_security_band,
                net_import_gwh,
                ttf_price_eur_mwh
            FROM derived_metrics
            WHERE date >= '2021-01-01'
            ORDER BY date
        """)

        # Storage data
        storage = db.query("""
            SELECT
                date,
                percent_full,
                gas_in_storage_twh,
                injection_twh,
                withdrawal_twh
            FROM storage_raw
            WHERE date >= '2021-01-01'
            ORDER BY date
        """)

        # Flow data by source
        flows = db.query("""
            SELECT
                date,
                route,
                direction,
                value_gwh
            FROM flows_raw
            WHERE direction = 'entry' AND route IS NOT NULL
            ORDER BY date, route
        """)

        # Remove known outlier dates in flows data
        outlier_dates = ['2023-03-01', '2023-12-04', '2025-08-21']
        flows = flows[~flows['date'].isin(outlier_dates)]

        # Remove outliers from net_import_gwh in df by interpolating
        df['date'] = pd.to_datetime(df['date'])
        for outlier_date in outlier_dates:
            if outlier_date in df['date'].astype(str).values:
                df.loc[df['date'] == outlier_date, 'net_import_gwh'] = None
        df['net_import_gwh'] = df['net_import_gwh'].interpolate(method='linear')


    return df, storage, flows

def _ordinal_suffix(n: int) -> str:
    # 1st, 2nd, 3rd, 4th ... with 11/12/13 as special cases
    if 10 <= (n % 100) <= 13:
        return "th"
    return {1: "st", 2: "nd", 3: "rd"}.get(n % 10, "th")


try:
    df, storage, flows = load_data()

    if df.empty:
        st.error("No data available")
        st.stop()

    latest = df.iloc[-1]
    latest_storage = storage.iloc[-1]
    latest_date = pd.to_datetime(latest['date'])

    # ========== SECTION 1: KEY METRICS ==========
    st.markdown("---")

    col1, col2, col3, col4 = st.columns(4)

    with col1:
        storage_level = latest_storage['gas_in_storage_twh']
        storage_pct = latest_storage['percent_full']

        st.markdown(f"""
        <div style="text-align: left;">
            <div class="metric-label">Storage Level</div>
            <div class="metric-value">{storage_pct:.1f}%</div>
            <div class="metric-subvalue">{storage_level:.1f} TWh</div>
        </div>
        """, unsafe_allow_html=True)

    with col2:
        adequacy = latest['storage_adequacy']

        # Get week-ago value for comparison
        week_ago = df.iloc[-8] if len(df) >= 8 else df.iloc[0]
        adequacy_change = adequacy - week_ago['storage_adequacy']

        # Determine color and text based on adequacy level
        if adequacy < 20:
            status_color = "#ef4444"
            status_text = "Very Low"
        elif adequacy < 40:
            status_color = "#f59e0b"
            status_text = "Low"
        elif adequacy < 60:
            status_color = "#eab308"
            status_text = "Normal"
        elif adequacy < 80:
            status_color = "#10b981"
            status_text = "High"
        else:
            status_color = "#10b981"
            status_text = "Very High"

        # Arrow direction based on change
        arrow = "↑" if adequacy_change > 0 else "↓" if adequacy_change < 0 else "→"
        arrow_color = "#10b981" if adequacy_change > 0 else "#ef4444" if adequacy_change < 0 else "#6b7280"

        adeq_int = int(round(float(adequacy)))
        suffix = _ordinal_suffix(adeq_int)

        st.markdown(f"""
        <div style="text-align: left;">
            <div class="metric-label">Storage Adequacy</div>
            <div class="metric-value">{adeq_int}<span class="metric-value-suffix">{suffix} percentile</span></div>
            <div style="font-size: 0.95rem; color: {status_color}; margin-bottom: 0.25rem; font-weight: 400;">{status_text}</div>
        </div>
        """, unsafe_allow_html=True)
        #<div style="font-size: 0.85rem; color: {arrow_color}; font-weight: 400;">{arrow} {abs(adequacy_change):.1f} pts vs last week</div>

    with col3:
        # Calculate 7-day average net imports
        last_7_days = df.tail(7)
        avg_imports = last_7_days['net_import_gwh'].mean()

        st.markdown(f"""
        <div style="text-align: left;">
            <div class="metric-label">Net Imports</div>
            <div class="metric-value">{avg_imports:.0f}<span class="metric-value-suffix">GWh/day</span></div>
            <div class="metric-subvalue">7-day average</div>
        </div>
        """, unsafe_allow_html=True)

    with col4:
        security = latest['supply_security']

        # Get week-ago value for comparison
        week_ago_security = df.iloc[-8]['supply_security'] if len(df) >= 8 else df.iloc[0]['supply_security']
        security_change = security - week_ago_security

        # Determine color based on security level
        if security < 20:
            status_color = "#ef4444"
            status_text = "Very Fragile"
        elif security < 40:
            status_color = "#f59e0b"
            status_text = "Fragile"
        elif security < 60:
            status_color = "#eab308"
            status_text = "Moderate"
        elif security < 80:
            status_color = "#10b981"
            status_text = "Diverse"
        else:
            status_color = "#10b981"
            status_text = "Very Diverse"

        # Arrow direction based on change
        arrow = "↑" if security_change > 0 else "↓" if security_change < 0 else "→"
        arrow_color = "#10b981" if security_change > 0 else "#ef4444" if security_change < 0 else "#6b7280"

        sec_int = int(round(float(security)))

        st.markdown(f"""
        <div style="text-align: left;">
            <div class="metric-label">Supply Security</div>
            <div class="metric-value">{sec_int}</div>
            <div style="font-size: 0.95rem; color: {status_color}; margin-bottom: 0.25rem; font-weight: 400;">{status_text}</div>
        </div>
        """, unsafe_allow_html=True)
            #<div style="font-size: 0.85rem; color: {arrow_color}; font-weight: 400;">{arrow} {abs(security_change):.1f} pts vs last week</div>


    st.markdown("---")

    # ========== SECTION 2: STORAGE OVERVIEW ==========
    st.subheader("📦 STORAGE OVERVIEW")

    # Time range selector (shared for all charts in this section)
    time_range = st.selectbox(
        "Time Range",
        options=["3Y", "1Y", "1M", "1W"],
        index=0,
        key="storage_time_range"
    )

    # Filter data based on time range
    days_map = {"1W": 7, "1M": 30, "1Y": 365, "3Y": 1095}
    end_date = pd.Timestamp(latest_date)
    start_date = end_date - timedelta(days=days_map[time_range])

    storage_filtered = storage[(storage['date'] >= start_date) & (storage['date'] <= end_date)]
    df_filtered = df[(df['date'] >= start_date) & (df['date'] <= end_date)]

    # Chart 1: Storage Level Time Series
    col_a, col_b = st.columns([1, 1])

    with col_a:

        st.markdown("**Storage Level**")

        fig1 = go.Figure()

        fig1.add_trace(
            go.Scatter(
                x=storage_filtered['date'],
                y=storage_filtered['percent_full'],
                name="Percent Full",
                mode='lines',
                line=dict(color='#3b82f6', width=2),
                hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Fill: %{y:.1f}%<extra></extra>'
            )
        )

        fig1.update_layout(
            height=350,
            margin=dict(l=0, r=0, t=10, b=0),
            hovermode='x unified',
            plot_bgcolor='white',
            paper_bgcolor='white',
            showlegend=False,
            xaxis_title="",
            yaxis_title="Percent Full (%)",
            yaxis=dict(range=[0, 100])
        )

        st.plotly_chart(fig1, use_container_width=True)

    with col_b:
        st.markdown("**Storage Adequacy Index**")

        fig2 = go.Figure()

        # Add colored background bands
        fig2.add_hrect(y0=0, y1=20, fillcolor="red", opacity=0.1, line_width=0)
        fig2.add_hrect(y0=20, y1=40, fillcolor="orange", opacity=0.1, line_width=0)
        fig2.add_hrect(y0=40, y1=60, fillcolor="yellow", opacity=0.1, line_width=0)
        fig2.add_hrect(y0=60, y1=80, fillcolor="lightgreen", opacity=0.1, line_width=0)
        fig2.add_hrect(y0=80, y1=100, fillcolor="green", opacity=0.1, line_width=0)

        fig2.add_trace(
            go.Scatter(
                x=df_filtered['date'],
                y=df_filtered['storage_adequacy'],
                mode='lines',
                line=dict(color='#3b82f6', width=2),
                hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Adequacy: %{y:.0f}<extra></extra>'
            )
        )

        fig2.add_hline(y=50, line_dash="dash", line_color="gray", opacity=0.5)

        fig2.update_layout(
            height=350,
            margin=dict(l=0, r=0, t=10, b=0),
            hovermode='x unified',
            showlegend=False,
            plot_bgcolor='white',
            paper_bgcolor='white',
            xaxis_title="",
            yaxis_title="Percentile (0-100)",
            yaxis=dict(range=[0, 100])
        )

        st.plotly_chart(fig2, use_container_width=True)

    # Chart 3: Injection/Withdrawal Flows
    st.markdown("**Daily Injection/Withdrawal Flows**")

    # Calculate 7-day moving average
    storage_filtered_copy = storage_filtered.copy()
    storage_filtered_copy['injection_ma7'] = storage_filtered_copy['injection_twh'].rolling(7, min_periods=1).mean()
    storage_filtered_copy['withdrawal_ma7'] = storage_filtered_copy['withdrawal_twh'].rolling(7, min_periods=1).mean()

    fig3 = go.Figure()

    # Bar chart for injection (positive) and withdrawal (negative)
    fig3.add_trace(
        go.Bar(
            x=storage_filtered_copy['date'],
            y=storage_filtered_copy['injection_twh'],
            name="Injection",
            marker_color='#10b981',
            hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Injection: %{y:.3f} TWh<extra></extra>'
        )
    )

    fig3.add_trace(
        go.Bar(
            x=storage_filtered_copy['date'],
            y=-storage_filtered_copy['withdrawal_twh'],
            name="Withdrawal",
            marker_color='#ef4444',
            hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Withdrawal: %{y:.3f} TWh<extra></extra>'
        )
    )

    fig3.update_layout(
        height=300,
        margin=dict(l=0, r=0, t=10, b=0),
        hovermode='x unified',
        plot_bgcolor='white',
        paper_bgcolor='white',
        xaxis_title="",
        yaxis_title="TWh/day",
        barmode='relative',
        legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
    )

    st.plotly_chart(fig3, use_container_width=True)

    st.markdown("---")

    # ========== SECTION 3: IMPORT FLOWS ==========
    st.subheader("🌊 IMPORT FLOWS")

    # Time range selector for flows
    time_range_flows = st.selectbox(
        "Time Range",
        options=["3Y", "1Y", "1M", "1W"],
        index=0,
        key="flows_time_range"
    )

    start_date_flows = end_date - timedelta(days=days_map[time_range_flows])
    df_flows_filtered = df[(df['date'] >= start_date_flows) & (df['date'] <= end_date)]

    # Chart 4: Net Import Trends
    col_c, col_d = st.columns([1, 1])

    with col_c:
        st.markdown("**Net Import Trends**")

        # Calculate 30-day moving average
        df_flows_copy = df_flows_filtered.copy()
        df_flows_copy['net_import_ma30'] = df_flows_copy['net_import_gwh'].rolling(30, min_periods=1).mean()

        fig4 = go.Figure()

        fig4.add_trace(
            go.Scatter(
                x=df_flows_copy['date'],
                y=df_flows_copy['net_import_gwh'],
                mode='lines',
                name='Daily',
                line=dict(color='#60a5fa', width=1),
                opacity=0.5,
                hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Net Import: %{y:.0f} GWh<extra></extra>'
            )
        )

        fig4.add_trace(
            go.Scatter(
                x=df_flows_copy['date'],
                y=df_flows_copy['net_import_ma30'],
                mode='lines',
                name='30-day MA',
                line=dict(color='#3b82f6', width=2),
                hovertemplate='<b>%{x|%Y-%m-%d}</b><br>30-day avg: %{y:.0f} GWh<extra></extra>'
            )
        )

        fig4.update_layout(
            height=350,
            margin=dict(l=0, r=0, t=10, b=0),
            hovermode='x unified',
            plot_bgcolor='white',
            paper_bgcolor='white',
            xaxis_title="",
            yaxis_title="GWh/day",
            legend=dict(orientation="h", yanchor="bottom", y=1.02, xanchor="right", x=1)
        )

        st.plotly_chart(fig4, use_container_width=True)

    with col_d:
        st.markdown("**Supply Security Index**")

        fig6 = go.Figure()

        # Add colored background bands
        fig6.add_hrect(y0=0, y1=20, fillcolor="red", opacity=0.1, line_width=0)
        fig6.add_hrect(y0=20, y1=40, fillcolor="orange", opacity=0.1, line_width=0)
        fig6.add_hrect(y0=40, y1=60, fillcolor="yellow", opacity=0.1, line_width=0)
        fig6.add_hrect(y0=60, y1=80, fillcolor="lightgreen", opacity=0.1, line_width=0)
        fig6.add_hrect(y0=80, y1=100, fillcolor="green", opacity=0.1, line_width=0)

        fig6.add_trace(
            go.Scatter(
                x=df_flows_filtered['date'],
                y=df_flows_filtered['supply_security'],
                mode='lines',
                line=dict(color='#8b5cf6', width=2),
                hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Security: %{y:.0f}<extra></extra>'
            )
        )

        fig6.add_hline(y=50, line_dash="dash", line_color="gray", opacity=0.5)

        fig6.update_layout(
            height=350,
            margin=dict(l=0, r=0, t=10, b=0),
            hovermode='x unified',
            showlegend=False,
            plot_bgcolor='white',
            paper_bgcolor='white',
            xaxis_title="",
            yaxis_title="Diversification (0-100)",
            yaxis=dict(range=[0, 100])
        )

        st.plotly_chart(fig6, use_container_width=True)

    # Chart 5: Import Sources Breakdown
    st.markdown("**Import Sources Breakdown**")

    # Aggregate flows by date and route
    flows_filtered = flows[(flows['date'] >= start_date_flows) & (flows['date'] <= end_date)]
    flows_daily = flows_filtered.groupby(['date', 'route'])['value_gwh'].sum().reset_index()

    # Pivot to get routes as columns
    flows_pivot = flows_daily.pivot(index='date', columns='route', values='value_gwh').fillna(0)

    # Select top routes by total volume
    top_routes = flows_pivot.sum().nlargest(8).index.tolist()
    flows_pivot_top = flows_pivot[top_routes]

    fig5 = go.Figure()

    # Color palette
    colors = ['#3b82f6', '#10b981', '#f59e0b', '#ef4444', '#8b5cf6', '#ec4899', '#14b8a6', '#6366f1']

    for i, route in enumerate(flows_pivot_top.columns):
        fig5.add_trace(
            go.Scatter(
                x=flows_pivot_top.index,
                y=flows_pivot_top[route],
                mode='lines',
                name=route,
                stackgroup='one',
                fillcolor=colors[i % len(colors)],
                line=dict(width=0.5, color=colors[i % len(colors)]),
                hovertemplate='<b>%{x|%Y-%m-%d}</b><br>' + route + ': %{y:.0f} GWh<extra></extra>'
            )
        )

    fig5.update_layout(
        height=350,
        margin=dict(l=0, r=0, t=10, b=0),
        hovermode='x unified',
        plot_bgcolor='white',
        paper_bgcolor='white',
        xaxis_title="",
        yaxis_title="GWh/day",
        legend=dict(orientation="v", yanchor="top", y=1, xanchor="left", x=1.02)
    )

    st.plotly_chart(fig5, use_container_width=True)

    st.markdown("---")

    # ========== SECTION 4: MARKET CONTEXT ==========
    st.subheader("💰 MARKET CONTEXT")

    # Time range selector for context
    time_range_context = st.selectbox(
        "Time Range",
        options=["3Y", "1Y", "1M", "1W"],
        index=0,
        key="context_time_range"
    )

    start_date_context = end_date - timedelta(days=days_map[time_range_context])
    df_context_filtered = df[(df['date'] >= start_date_context) & (df['date'] <= end_date)]

    st.markdown("**TFF price**")

    fig7 = go.Figure()

    fig7.add_trace(
        go.Scatter(
            x=df_context_filtered['date'],
            y=df_context_filtered['ttf_price_eur_mwh'],
            mode='lines',
            line=dict(color='#f59e0b', width=2),
            fill='tozeroy',
            fillcolor='rgba(245, 158, 11, 0.1)',
            hovertemplate='<b>%{x|%Y-%m-%d}</b><br>Price: €%{y:.1f}/MWh<extra></extra>'
        )
    )

    fig7.update_layout(
        height=300,
        margin=dict(l=0, r=0, t=10, b=0),
        hovermode='x unified',
        showlegend=False,
        plot_bgcolor='white',
        paper_bgcolor='white',
        xaxis_title="",
        yaxis_title="EUR/MWh"
    )

    st.plotly_chart(fig7, use_container_width=True)


    st.markdown("---")

    # ========== SECTION 5: DATA SUMMARY TABLE ==========
    st.subheader("📊 DATA SUMMARY")

    # Get values for 1W, 1M, 1Y ago
    def get_value_ago(df, days_ago, column):
        target_date = end_date - timedelta(days=days_ago)
        closest = df.iloc[(df['date'] - target_date).abs().argsort()[:1]]
        if len(closest) > 0:
            val = closest[column].iloc[0]
            return f"{val:.1f}" if pd.notna(val) else "N/A"
        return "N/A"

    def get_storage_value_ago(storage, days_ago, column):
        target_date = end_date - timedelta(days=days_ago)
        closest = storage.iloc[(storage['date'] - target_date).abs().argsort()[:1]]
        if len(closest) > 0:
            val = closest[column].iloc[0]
            return f"{val:.1f}" if pd.notna(val) else "N/A"
        return "N/A"

    summary_data = {
        "Metric": [
            "Storage (TWh)",
            "Storage (%)",
            "Net Imports (GWh/d)",
            "Supply Security"
        ],
        "Current": [
            f"{latest_storage['gas_in_storage_twh']:.1f}",
            f"{latest_storage['percent_full']:.1f}",
            f"{latest['net_import_gwh']:.1f}",
            f"{latest['supply_security']:.1f}"
        ],
        "1W Ago": [
            get_storage_value_ago(storage, 7, 'gas_in_storage_twh'),
            get_storage_value_ago(storage, 7, 'percent_full'),
            get_value_ago(df, 7, 'net_import_gwh'),
            get_value_ago(df, 7, 'supply_security')
        ],
        "1M Ago": [
            get_storage_value_ago(storage, 30, 'gas_in_storage_twh'),
            get_storage_value_ago(storage, 30, 'percent_full'),
            get_value_ago(df, 30, 'net_import_gwh'),
            get_value_ago(df, 30, 'supply_security')
        ],
        "1Y Ago": [
            get_storage_value_ago(storage, 365, 'gas_in_storage_twh'),
            get_storage_value_ago(storage, 365, 'percent_full'),
            get_value_ago(df, 365, 'net_import_gwh'),
            get_value_ago(df, 365, 'supply_security')
        ],
        "5Y Min/Max": [
            f"{storage['gas_in_storage_twh'].min():.1f} / {storage['gas_in_storage_twh'].max():.1f}",
            f"{storage['percent_full'].min():.1f} / {storage['percent_full'].max():.1f}",
            f"{df['net_import_gwh'].min():.1f} / {df['net_import_gwh'].max():.1f}",
            f"{df['supply_security'].min():.1f} / {df['supply_security'].max():.1f}"
        ]
    }

    summary_df = pd.DataFrame(summary_data)
    st.dataframe(summary_df, hide_index=True, use_container_width=True)

    st.markdown("---")

    # Data sources
    st.markdown("### Data Sources")
    st.markdown(f"""
    **Last updated:** {latest_date.strftime('%Y-%m-%d')}

    - **Storage data:** AGSI+ (Gas Infrastructure Europe)
    - **Flow data:** ENTSOG (European Network of Transmission System Operators for Gas)
    - **Price data:** Yahoo Finance (TTF front-month futures)
    """)

    st.markdown("---")

    # Footer
    st.markdown(
        f"<div style='text-align: center; color: #6b7280; font-size: 0.875rem; margin-top: 2rem;'>"
        f"<strong>European Gas Market Monitor</strong> | "
        f"Updated: {datetime.now().strftime('%Y-%m-%d %H:%M UTC')} | "
        f"Built with Streamlit + DuckDB + Plotly<br>"
        f"Not investment advice. For informational and educational purposes only."
        f"</div>",
        unsafe_allow_html=True
    )

except Exception as e:
    st.error(f"Error loading data: {e}")
    import traceback
    st.code(traceback.format_exc())
