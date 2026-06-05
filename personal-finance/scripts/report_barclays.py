from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from common import PROCESSED_DIR, REPORTS_DIR, REPORT_END_DATE, REPORT_START_DATE, html_escape, parse_date, write_html_report


def money(value: Decimal | float) -> str:
    return f"{float(value):,.2f}"


def build_data() -> tuple[list[dict[str, Any]], dict[str, list[dict[str, Any]]]]:
    rows = []
    with (PROCESSED_DIR / "balances.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row_date = parse_date(row.get("date"))
            if row.get("institution") == "barclays" and row_date and REPORT_START_DATE <= row_date <= REPORT_END_DATE and row.get("balance_sgd"):
                rows.append(row)

    seen: set[tuple[str, str, str, str]] = set()
    clean = []
    for row in rows:
        key = (row["date"], row["account_id"], row["currency"], row["balance"])
        if key in seen:
            continue
        seen.add(key)
        clean.append(row)

    totals: dict[str, Decimal] = defaultdict(Decimal)
    series: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for row in clean:
        value = Decimal(row["balance_sgd"])
        totals[row["date"]] += value
        series[f"{row['account_id']} {row['currency']}"][row["date"]] += value

    total_points = [{"date": d, "value": float(v)} for d, v in sorted(totals.items())]
    series_points = {
        name: [{"date": d, "value": float(v)} for d, v in sorted(values.items())]
        for name, values in sorted(series.items())
    }
    return total_points, series_points


def run() -> dict[str, Any]:
    total_points, series_points = build_data()
    latest = total_points[-1] if total_points else {"date": "", "value": 0}
    peak = max(total_points, key=lambda item: item["value"]) if total_points else {"date": "", "value": 0}
    trough = min(total_points, key=lambda item: item["value"]) if total_points else {"date": "", "value": 0}
    payload = json.dumps({"total": total_points, "series": series_points})
    body = f"""
<div class="metric-row">
  <div class="metric"><strong>{html_escape(latest['date'])}</strong><span>Latest Barclays snapshot</span></div>
  <div class="metric"><strong>SGD {money(latest['value'])}</strong><span>Latest total</span></div>
  <div class="metric"><strong>SGD {money(peak['value'])}</strong><span>Peak total on {html_escape(peak['date'])}</span></div>
  <div class="metric"><strong>SGD {money(trough['value'])}</strong><span>Lowest total on {html_escape(trough['date'])}</span></div>
</div>
<p class="muted">Totals stop at the last completed month-end ({REPORT_END_DATE.isoformat()}) and use parsed Barclays statement closing balances converted to SGD using the local ECB-derived FX table. Duplicate statement copies are deduplicated for this chart by date/account/currency/balance.</p>
<svg id="chart" viewBox="0 0 1100 520" role="img" aria-label="Barclays total balance over time" style="width:100%;height:auto;background:#fff;border:1px solid var(--line);border-radius:6px"></svg>
<h2>Series</h2>
<div id="legend" class="metric-row"></div>
<script>
const data = {payload};
const svg = document.getElementById('chart');
const legend = document.getElementById('legend');
const W = 1100, H = 520, L = 72, R = 28, T = 34, B = 64;
const parseDate = d => new Date(d + 'T00:00:00');
const all = data.total.map(p => ({{...p, t: parseDate(p.date).getTime()}}));
const minT = Math.min(...all.map(p => p.t));
const maxT = Math.max(...all.map(p => p.t));
const vals = all.map(p => p.value);
const minY = Math.min(0, ...vals);
const maxY = Math.max(...vals);
const padY = (maxY - minY) * 0.08 || 1;
const y0 = minY - padY, y1 = maxY + padY;
const x = t => L + (t - minT) / (maxT - minT || 1) * (W - L - R);
const y = v => T + (y1 - v) / (y1 - y0 || 1) * (H - T - B);
const el = (name, attrs, text) => {{
  const node = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [k,v] of Object.entries(attrs || {{}})) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  svg.appendChild(node);
  return node;
}};
const fmt = v => 'S$' + Math.round(v).toLocaleString();
for (let i=0;i<=5;i++) {{
  const val = y0 + (y1-y0)*i/5;
  const yy = y(val);
  el('line', {{x1:L, y1:yy, x2:W-R, y2:yy, stroke:'#d9e0e7', 'stroke-width':1}});
  el('text', {{x:L-10, y:yy+4, 'text-anchor':'end', 'font-size':12, fill:'#5f6b7a'}}, fmt(val));
}}
const years = [...new Set(all.map(p => new Date(p.t).getFullYear()))];
for (const yr of years) {{
  const tt = new Date(yr + '-01-01T00:00:00').getTime();
  if (tt < minT || tt > maxT) continue;
  const xx = x(tt);
  el('line', {{x1:xx, y1:T, x2:xx, y2:H-B, stroke:'#edf1f4', 'stroke-width':1}});
  el('text', {{x:xx, y:H-32, 'text-anchor':'middle', 'font-size':12, fill:'#5f6b7a'}}, yr);
}}
el('line', {{x1:L, y1:y(0), x2:W-R, y2:y(0), stroke:'#8a96a3', 'stroke-width':1.2}});
const path = all.map((p,i) => `${{i?'L':'M'}} ${{x(p.t).toFixed(2)}} ${{y(p.value).toFixed(2)}}`).join(' ');
el('path', {{d:path, fill:'none', stroke:'#116466', 'stroke-width':3, 'stroke-linejoin':'round', 'stroke-linecap':'round'}});
for (const p of all) {{
  const c = el('circle', {{cx:x(p.t), cy:y(p.value), r:3, fill:'#116466'}});
  const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
  title.textContent = `${{p.date}}: ${{fmt(p.value)}}`;
  c.appendChild(title);
}}
el('text', {{x:L, y:22, 'font-size':16, fill:'#1d2733', 'font-weight':700}}, 'Barclays Total Balance, SGD');
for (const [name, pts] of Object.entries(data.series)) {{
  const latest = pts[pts.length - 1];
  const div = document.createElement('div');
  div.className = 'metric';
  div.innerHTML = `<strong>${{name}}</strong><span>${{latest.date}}: ${{fmt(latest.value)}}</span>`;
  legend.appendChild(div);
}}
</script>
"""
    write_html_report(REPORTS_DIR / "barclays_balances.html", "Barclays Balances", body)
    return {"points": len(total_points), "series": len(series_points), "report": str(REPORTS_DIR / "barclays_balances.html")}


if __name__ == "__main__":
    print(run())
