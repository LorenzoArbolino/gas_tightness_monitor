/* European Gas Market Monitor — static dashboard. Reads data.json produced by export_site_data.py. */

const COLORS = {
  blue: '#2563eb', lightBlue: '#93c5fd', green: '#059669', red: '#dc2626',
  purple: '#7c3aed', amber: '#d97706', grey: '#9ca3af',
};
const ROUTE_COLORS = {
  'LNG': '#2563eb', 'Norway': '#059669', 'Algeria': '#d97706', 'Russia (direct)': '#dc2626',
  'UK': '#7c3aed', 'Ukraine/Moldova': '#0891b2', 'TurkStream': '#be123c',
  'Azerbaijan (TAP)': '#65a30d', 'Libya': '#a16207', 'Switzerland': '#64748b', 'Other': '#9ca3af',
};
const BANDS_ADEQUACY = ['Very Low', 'Low', 'Normal', 'High', 'Very High'];
const BANDS_SECURITY = ['Very Fragile', 'Fragile', 'Moderate', 'Diverse', 'Very Diverse'];
const BAND_COLORS = ['#dc2626', '#d97706', '#ca8a04', '#059669', '#047857'];
const STALE_DAYS = 4;

const PLOT_CONFIG = { displayModeBar: false, responsive: true };
const BASE_LAYOUT = {
  margin: { l: 48, r: 12, t: 8, b: 32 },
  paper_bgcolor: '#ffffff',
  plot_bgcolor: '#ffffff',
  font: { family: 'system-ui, -apple-system, Segoe UI, Roboto, sans-serif', size: 12, color: '#374151' },
  hovermode: 'x unified',
  xaxis: { type: 'date', gridcolor: '#f1f5f9', linecolor: '#e5e7eb' },
  yaxis: { gridcolor: '#f1f5f9', zerolinecolor: '#e5e7eb' },
  legend: { orientation: 'h', y: 1.1, x: 0 },
  showlegend: false,
};

let DATA = null;

function layout(extra = {}) {
  const l = structuredClone(BASE_LAYOUT);
  for (const [k, v] of Object.entries(extra)) {
    l[k] = (typeof v === 'object' && !Array.isArray(v) && l[k]) ? { ...l[k], ...v } : v;
  }
  return l;
}

function bandIndex(v) { return Math.min(Math.floor(v / 20), 4); }

function bandShapes() {
  // Faint colour bands behind 0–100 index charts
  return BAND_COLORS.map((c, i) => ({
    type: 'rect', xref: 'paper', x0: 0, x1: 1, y0: i * 20, y1: (i + 1) * 20,
    fillcolor: c, opacity: 0.06, line: { width: 0 }, layer: 'below',
  }));
}

function lastValid(dates, values) {
  for (let i = values.length - 1; i >= 0; i--) {
    if (values[i] !== null) return { date: dates[i], value: values[i], index: i };
  }
  return null;
}

function rollingMean(values, window) {
  const out = [];
  let sum = 0, n = 0;
  const q = [];
  for (const v of values) {
    q.push(v);
    if (v !== null) { sum += v; n++; }
    if (q.length > window) {
      const old = q.shift();
      if (old !== null) { sum -= old; n--; }
    }
    out.push(n ? sum / n : null);
  }
  return out;
}

function fmt(v, digits = 0) {
  return v === null || v === undefined ? '–' : v.toLocaleString('en-GB', { minimumFractionDigits: digits, maximumFractionDigits: digits });
}

function fmtDate(iso) {
  return iso ? new Date(iso + 'T00:00:00Z').toLocaleDateString('en-GB', { day: 'numeric', month: 'short', year: 'numeric', timeZone: 'UTC' }) : 'n/a';
}

function daysAgo(iso) {
  return Math.floor((Date.now() - new Date(iso + 'T00:00:00Z')) / 86400000);
}

function renderHeader() {
  const a = DATA.as_of;
  document.getElementById('as-of').textContent =
    `Storage data as of ${fmtDate(a.storage)} · Flows as of ${fmtDate(a.flows)} · Prices as of ${fmtDate(a.prices)}`;

  const stale = [['Storage', a.storage], ['Flow', a.flows]]
    .filter(([, d]) => !d || daysAgo(d) > STALE_DAYS)
    .map(([name, d]) => `${name} data is ${d ? daysAgo(d) + ' days' : 'not yet'} old`);
  if (stale.length) {
    const el = document.getElementById('stale');
    el.textContent = `${stale.join('; ')}. The daily update may be failing, so treat the latest values with caution.`;
    el.hidden = false;
  }
}

function kpi(label, value, unit, sub, band) {
  const bandHtml = band ? `<div class="band" style="color:${band.color}">${band.text}</div>` : '';
  return `<div class="kpi"><div class="label">${label}</div>
    <div class="value">${value}<span class="unit">${unit}</span></div>${bandHtml}
    <div class="sub">${sub}</div></div>`;
}

function renderKpis() {
  const d = DATA.daily;
  const fill = lastValid(d.date, d.percent_full);
  const adequacy = lastValid(d.date, d.storage_adequacy);
  const security = lastValid(d.date, d.supply_security);
  const ttf = lastValid(d.date, d.ttf_eur_mwh);
  const imports = lastValid(d.date, d.net_import_gwh);
  const last7 = imports ? d.net_import_gwh.slice(Math.max(0, imports.index - 6), imports.index + 1).filter(v => v !== null) : [];
  const avg7 = last7.length ? last7.reduce((a, b) => a + b, 0) / last7.length : null;

  const tiles = [];
  if (fill) tiles.push(kpi('Storage level', fmt(fill.value, 1), '%', `${fmt(d.storage_twh[fill.index], 0)} TWh · ${fmtDate(fill.date)}`));
  if (adequacy) {
    const i = bandIndex(adequacy.value);
    tiles.push(kpi('Storage adequacy', fmt(adequacy.value, 0), '/ 100', 'position in 5-yr range',
      { text: BANDS_ADEQUACY[i], color: BAND_COLORS[i] }));
  }
  if (avg7 !== null) tiles.push(kpi('Net imports', fmt(avg7, 0), 'GWh/d', `7-day average to ${fmtDate(imports.date)}`));
  if (security) {
    const i = bandIndex(security.value);
    tiles.push(kpi('Supply security', fmt(security.value, 0), '/ 100', 'corridor diversification',
      { text: BANDS_SECURITY[i], color: BAND_COLORS[i] }));
  }
  if (ttf) tiles.push(kpi('TTF price', fmt(ttf.value, 1), '€/MWh', `front-month · ${fmtDate(DATA.as_of.prices)}`));
  document.getElementById('kpis').innerHTML = tiles.join('');
}

function sliceFrom(dates, days) {
  if (!days) return 0;
  const end = new Date(dates[dates.length - 1] + 'T00:00:00Z');
  const start = new Date(end - days * 86400000).toISOString().slice(0, 10);
  const i = dates.findIndex(x => x >= start);
  return i < 0 ? 0 : i;
}

function plot(id, traces, extraLayout) {
  Plotly.react(id, traces, layout(extraLayout), PLOT_CONFIG);
}

function renderCharts(days) {
  const d = DATA.daily;
  const i0 = sliceFrom(d.date, days);
  const x = d.date.slice(i0);
  const s = key => d[key].slice(i0);

  plot('chart-storage', [
    { x, y: s('hist_min_pct'), mode: 'lines', line: { width: 0 }, hoverinfo: 'skip', showlegend: false },
    { x, y: s('hist_max_pct'), mode: 'lines', line: { width: 0 }, fill: 'tonexty',
      fillcolor: 'rgba(147,197,253,0.35)', name: '5-yr range', hovertemplate: 'max %{y:.1f}%<extra></extra>' },
    { x, y: s('hist_mean_pct'), mode: 'lines', name: '5-yr mean', line: { color: COLORS.grey, width: 1, dash: 'dot' },
      hovertemplate: 'mean %{y:.1f}%<extra></extra>' },
    { x, y: s('percent_full'), mode: 'lines', name: 'Current', line: { color: COLORS.blue, width: 2 },
      hovertemplate: '<b>%{y:.1f}%</b><extra></extra>' },
  ], { yaxis: { range: [0, 100], ticksuffix: '%' }, showlegend: true });

  plot('chart-adequacy', [
    { x, y: s('storage_adequacy'), mode: 'lines', line: { color: COLORS.blue, width: 2 },
      hovertemplate: '%{y:.0f}<extra></extra>' },
  ], { yaxis: { range: [0, 100] }, shapes: bandShapes() });

  plot('chart-injection', [
    { x, y: s('injection_twh'), type: 'bar', name: 'Injection', marker: { color: COLORS.green },
      hovertemplate: '+%{y:.2f} TWh<extra>Injection</extra>' },
    { x, y: s('withdrawal_twh').map(v => v === null ? null : -v), type: 'bar', name: 'Withdrawal',
      marker: { color: COLORS.red }, hovertemplate: '%{y:.2f} TWh<extra>Withdrawal</extra>' },
  ], { barmode: 'relative', bargap: 0, showlegend: true });

  const imports = s('net_import_gwh');
  plot('chart-imports', [
    { x, y: imports, mode: 'lines', name: 'Daily', line: { color: COLORS.lightBlue, width: 1 },
      hovertemplate: '%{y:,.0f} GWh/d<extra>Daily</extra>' },
    { x, y: rollingMean(imports, 30), mode: 'lines', name: '30-day avg', line: { color: COLORS.blue, width: 2 },
      hovertemplate: '%{y:,.0f} GWh/d<extra>30-day avg</extra>' },
  ], { showlegend: true, yaxis: { rangemode: 'tozero' } });

  plot('chart-security', [
    { x, y: s('supply_security'), mode: 'lines', line: { color: COLORS.purple, width: 2 },
      hovertemplate: '%{y:.0f}<extra></extra>' },
  ], { yaxis: { range: [0, 100] }, shapes: bandShapes() });

  const r = DATA.routes;
  const j0 = sliceFrom(r.date, days);
  const rx = r.date.slice(j0);
  const routeTraces = Object.entries(r.series).map(([route, values]) => ({
    x: rx,
    // Corridors that are net exporters (e.g. to Ukraine) are drawn at zero in the stack
    y: rollingMean(values, 7).slice(j0).map(v => v === null ? null : Math.max(0, v)),
    name: route, mode: 'lines', stackgroup: 'one',
    line: { width: 0.5, color: ROUTE_COLORS[route] || COLORS.grey },
    hovertemplate: `%{y:,.0f}<extra>${route}</extra>`,
  }));
  plot('chart-routes', routeTraces, { showlegend: true, legend: { orientation: 'h', y: -0.15 },
    margin: { l: 48, r: 12, t: 8, b: 64 } });

  plot('chart-ttf', [
    { x, y: s('ttf_eur_mwh'), mode: 'lines', line: { color: COLORS.amber, width: 2 }, connectgaps: false,
      fill: 'tozeroy', fillcolor: 'rgba(217,119,6,0.08)', hovertemplate: '€%{y:.1f}/MWh<extra></extra>' },
  ], { yaxis: { rangemode: 'tozero' } });
}

function setupRange() {
  const buttons = document.querySelectorAll('.range button');
  buttons.forEach(btn => btn.addEventListener('click', () => {
    buttons.forEach(b => b.classList.toggle('active', b === btn));
    renderCharts(Number(btn.dataset.days));
  }));
}

async function init() {
  try {
    const res = await fetch('data.json', { cache: 'no-cache' });
    if (!res.ok) throw new Error(`HTTP ${res.status}`);
    DATA = await res.json();
  } catch (err) {
    document.getElementById('as-of').textContent = `Could not load data (${err.message}).`;
    return;
  }
  renderHeader();
  renderKpis();
  setupRange();
  renderCharts(Number(document.querySelector('.range button.active').dataset.days));
}

init();
