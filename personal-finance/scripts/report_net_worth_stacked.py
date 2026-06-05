from __future__ import annotations

import csv
import json
from collections import defaultdict
from datetime import date
from decimal import Decimal
from typing import Any

from common import EXPORTS_DIR, PROCESSED_DIR, REPORTS_DIR, REPORT_END_DATE, REPORT_START_DATE, html_escape, parse_date, write_csv, write_html_report


SERIES_COLORS = {
    "IBKR": "#315f9d",
    "Vanguard": "#116466",
    "Stripe": "#635bff",
    "Evelyn": "#2f6f4e",
    "Property": "#8f5f3c",
    "Premium Bonds": "#147a7e",
    "Legacy Pensions": "#7f4f24",
    "DBS": "#c44536",
    "Endowus": "#6f5aa7",
    "Wise": "#d99b2b",
    "Barclays": "#667085",
}


def label_for(row: dict[str, str]) -> str:
    return {
        "ibkr": "IBKR",
        "vanguard": "Vanguard",
        "stripe": "Stripe",
        "evelyn": "Evelyn",
        "manual_property": "Property",
        "manual_premium_bonds": "Premium Bonds",
        "standard_chartered": "Legacy Pensions",
        "legacy_pension": "Legacy Pensions",
        "dbs": "DBS",
        "endowus": "Endowus",
        "wise": "Wise",
        "barclays": "Barclays",
        "halifax": "Halifax",
    }.get(row.get("institution", ""), row.get("institution", "").title())


def include_in_net_worth(row: dict[str, str]) -> bool:
    if row.get("institution") == "vanguard" and row.get("balance_type") == "workbook_running_balance":
        return False
    if row.get("owner") == "samuel" and row.get("institution") == "dbs" and row.get("account_type") == "fixed_deposit":
        return False
    if row.get("account_type") == "credit_card":
        return False
    if row.get("institution") == "stripe" and row.get("balance_type") == "future_unvested_rsu_value":
        return False
    return bool(row.get("balance_sgd") and row.get("date"))


def load_balances() -> list[dict[str, str]]:
    with (PROCESSED_DIR / "balances.csv").open(newline="", encoding="utf-8") as f:
        rows = [row for row in csv.DictReader(f) if include_in_net_worth(row)]
    seen: set[tuple[str, ...]] = set()
    out = []
    for row in rows:
        key = (
            row.get("owner", ""),
            row.get("institution", ""),
            row.get("date", ""),
            row.get("account_id", ""),
            row.get("currency", ""),
            row.get("balance", ""),
            row.get("balance_type", ""),
        )
        if key in seen:
            continue
        seen.add(key)
        out.append(row)
    return out


def source_row_number(row: dict[str, str]) -> int:
    try:
        return int(row.get("source_row") or 0)
    except ValueError:
        return 0


def sort_key(row: dict[str, str]) -> tuple[str, int]:
    if row.get("institution") == "wise":
        return (row["date"], -source_row_number(row))
    return (row["date"], source_row_number(row))


def carried_account_rows(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    row_months = sorted({row["date"][:7] for row in rows if row.get("date")})
    if not row_months:
        return []
    start = max(date.fromisoformat(row_months[0] + "-01"), REPORT_START_DATE.replace(day=1))
    end = min(date.fromisoformat(row_months[-1] + "-01"), REPORT_END_DATE.replace(day=1))
    months = []
    cur = start
    while cur <= end:
        months.append(cur.strftime("%Y-%m"))
        cur = date(cur.year + (1 if cur.month == 12 else 0), 1 if cur.month == 12 else cur.month + 1, 1)

    keys = sorted({
        (row.get("owner", ""), row.get("institution", ""), row.get("account_id", ""), row.get("currency", ""), row.get("balance_type", ""))
        for row in rows
    })
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        grouped[(row.get("owner", ""), row.get("institution", ""), row.get("account_id", ""), row.get("currency", ""), row.get("balance_type", ""))].append(row)
    for key in grouped:
        grouped[key].sort(key=sort_key)

    idx = {key: 0 for key in keys}
    carry: dict[tuple[str, ...], dict[str, str] | None] = {key: None for key in keys}
    out = []
    for month in months:
        for key in keys:
            account_rows = grouped[key]
            while idx[key] < len(account_rows) and account_rows[idx[key]]["date"][:7] <= month:
                carry[key] = account_rows[idx[key]]
                idx[key] += 1
            row = carry[key]
            if not row:
                continue
            value = Decimal(row["balance_sgd"])
            series = label_for(row)
            account_label = f"{row.get('owner','').title()} | {series} | {row.get('account_name') or row.get('account_id')} | {row.get('currency')}"
            out.append(
                {
                    "month": month,
                    "owner": row.get("owner", ""),
                    "series": series,
                    "institution": row.get("institution", ""),
                    "account_id": row.get("account_id", ""),
                    "account_name": row.get("account_name", ""),
                    "account_label": account_label,
                    "currency": row.get("currency", ""),
                    "balance_sgd": value,
                    "source_date": row.get("date", ""),
                    "confidence_status": row.get("confidence_status", ""),
                    "balance_type": row.get("balance_type", ""),
                    "source_file": row.get("source_file", ""),
                }
            )
    return out


def money(value: Any) -> str:
    return f"{float(value):,.0f}"


def run() -> dict[str, Any]:
    account_rows = carried_account_rows(load_balances())
    months = sorted({row["month"] for row in account_rows})
    series = sorted({row["series"] for row in account_rows})
    summary_rows = []
    for month in months:
        values = {name: Decimal("0") for name in series}
        for row in account_rows:
            if row["month"] == month:
                values[row["series"]] += row["balance_sgd"]
        summary_rows.append({"month": month, **values, "Total": sum(values.values(), Decimal("0"))})

    write_csv(EXPORTS_DIR / "net_worth_monthly_stacked.csv", summary_rows, ["month", *series, "Total"])
    write_csv(
        EXPORTS_DIR / "net_worth_monthly_stacked_by_account.csv",
        account_rows,
        ["month", "owner", "series", "institution", "account_id", "account_name", "account_label", "currency", "balance_sgd", "source_date", "confidence_status", "balance_type", "source_file"],
    )

    latest_total = summary_rows[-1]["Total"] if summary_rows else Decimal("0")
    payload = json.dumps(
        {
            "months": months,
            "series": series,
            "owners": sorted({row["owner"] for row in account_rows}),
            "accounts": sorted({row["account_label"] for row in account_rows}),
            "colors": {**SERIES_COLORS, "Halifax": "#0f766e"},
            "rows": [{k: float(v) if isinstance(v, Decimal) else v for k, v in row.items()} for row in account_rows],
        }
    )
    body = """
<div class="metric-row">
  <div class="metric"><strong>__LATEST_MONTH__</strong><span>Latest month</span></div>
  <div class="metric"><strong>SGD __LATEST_TOTAL__</strong><span>Latest total in current data</span></div>
  <div class="metric"><strong>__MONTH_COUNT__</strong><span>Monthly snapshots</span></div>
  <div class="metric"><strong>__ACCOUNT_COUNT__</strong><span>Constituent account rows</span></div>
</div>
<p class="warning">Use the filters to reshape the graph locally. Values stop at the last completed month-end (__REPORT_END__) and carry forward each account's latest known balance. Credit cards are excluded from net worth and handled in spending.</p>
<div class="controls">
  <label>Owner <select id="ownerFilter"><option value="__all__">Samuel + Amy</option></select></label>
  <label>Group by <select id="groupBy"><option value="series">Platform</option><option value="owner">Owner</option><option value="account_label">Account / component</option></select></label>
  <label>View <select id="mode"><option value="value">SGD value</option><option value="percent">100% composition</option></select></label>
  <label>Start <input id="startDate" type="date"></label>
  <label>End <input id="endDate" type="date"></label>
  <label>Month <select id="monthSelect"></select></label>
  <button id="resetBtn" type="button">Reset</button>
</div>
<div class="filter-panel">
  <strong>Platforms</strong><div id="seriesChecks"></div>
  <strong>Accounts / components</strong><div id="accountChecks"></div>
</div>
<div id="metrics" class="metric-row"></div>
<svg id="chart" viewBox="0 0 1180 620" role="img" aria-label="Interactive net worth explorer" style="width:100%;height:auto;background:#fff;border:1px solid var(--line);border-radius:6px;touch-action:none"></svg>
<h2>Selected Month Breakdown</h2>
<div id="breakdown"></div>
<script>
const data = __PAYLOAD__;
const svg = document.getElementById('chart');
const ownerFilter = document.getElementById('ownerFilter');
const groupBy = document.getElementById('groupBy');
const mode = document.getElementById('mode');
const startDate = document.getElementById('startDate');
const endDate = document.getElementById('endDate');
const monthSelect = document.getElementById('monthSelect');
const seriesChecks = document.getElementById('seriesChecks');
const accountChecks = document.getElementById('accountChecks');
const metrics = document.getElementById('metrics');
const breakdown = document.getElementById('breakdown');
const W=1180,H=620,L=84,R=30,T=36,B=76;
const html = v => String(v ?? '').replace(/[&<>"']/g, c => ({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt = v => 'S$' + Math.round(v || 0).toLocaleString();
const pct = v => (100*(v || 0)).toFixed(1) + '%';
const clear = n => { while(n.firstChild) n.removeChild(n.firstChild); };
const el = (name, attrs, text) => { const node=document.createElementNS('http://www.w3.org/2000/svg',name); for(const [k,v] of Object.entries(attrs||{})) node.setAttribute(k,v); if(text!==undefined) node.textContent=text; svg.appendChild(node); return node; };
const minDate = data.months.length ? data.months[0] + '-01' : '';
const maxDate = data.months.length ? data.months[data.months.length-1] + '-01' : '';
if(minDate){ startDate.min=minDate; startDate.max=maxDate; endDate.min=minDate; endDate.max=maxDate; startDate.value=minDate; endDate.value=maxDate; }
data.owners.forEach(o => ownerFilter.insertAdjacentHTML('beforeend', `<option value="${html(o)}">${html(o[0].toUpperCase()+o.slice(1))}</option>`));
function checks(container, values, prefix) {
  container.innerHTML = values.map(v => `<label><input type="checkbox" data-prefix="${prefix}" value="${html(v)}" checked> ${html(v)}</label>`).join('');
}
checks(seriesChecks, data.series, 'series');
checks(accountChecks, data.accounts, 'account');
function selected(container) { return new Set([...container.querySelectorAll('input:checked')].map(i => i.value)); }
function normalizedRange(){ let start=startDate.value||minDate,end=endDate.value||maxDate; if(start&&end&&start>end){ const swap=start; start=end; end=swap; } return {start,end}; }
function activeMonths(){ const {start,end}=normalizedRange(); const startMonth=(start||'0000-00-00').slice(0,7), endMonth=(end||'9999-99-99').slice(0,7); return data.months.filter(m => m>=startMonth && m<=endMonth); }
function refreshMonthOptions(months){ const previous=monthSelect.value; monthSelect.innerHTML=months.map(m=>`<option value="${m}">${m}</option>`).join(''); if(months.includes(previous)) monthSelect.value=previous; else monthSelect.value=months[months.length-1]||''; }
function filteredRows() {
  const owner = ownerFilter.value;
  const s = selected(seriesChecks), a = selected(accountChecks);
  return data.rows.filter(r => (owner === '__all__' || r.owner === owner) && s.has(r.series) && a.has(r.account_label));
}
function pivot(rows, months) {
  const key = groupBy.value;
  const groups = [...new Set(rows.map(r => r[key]))].sort();
  const byMonth = months.map(month => {
    const row = {month, Total:0};
    groups.forEach(g => row[g]=0);
    rows.filter(r => r.month === month).forEach(r => { row[r[key]] += r.balance_sgd; row.Total += r.balance_sgd; });
    return row;
  });
  return {groups, byMonth};
}
function colorFor(group, i) {
  if (data.colors[group]) return data.colors[group];
  const palette=['#315f9d','#c44536','#116466','#6f5aa7','#d99b2b','#667085','#8f5f3c','#0f766e','#ad3b72','#344e7a'];
  return palette[i % palette.length];
}
function render() {
  clear(svg);
  const months = activeMonths();
  refreshMonthOptions(months);
  const rows = filteredRows();
  const {groups, byMonth} = pivot(rows, months);
  const selectedMonth = monthSelect.value;
  const chartRows = byMonth;
  const maxY = mode.value === 'percent' ? 1 : Math.max(1, ...chartRows.map(r => r.Total)) * 1.08;
  const x = i => L + i / Math.max(1, chartRows.length-1) * (W-L-R);
  const y = v => T + (maxY - v) / maxY * (H-T-B);
  for(let i=0;i<=6;i++){ const val=maxY*i/6, yy=y(val); el('line',{x1:L,y1:yy,x2:W-R,y2:yy,stroke:'#d9e0e7'}); el('text',{x:L-10,y:yy+4,'text-anchor':'end','font-size':12,fill:'#5f6b7a'}, mode.value==='percent'?pct(val):fmt(val)); }
  let lower = chartRows.map(_=>0);
  groups.forEach((g, gi) => {
    const upper = chartRows.map((r,i) => lower[i] + (mode.value === 'percent' ? (r.Total ? (r[g]||0)/r.Total : 0) : (r[g]||0)));
    const top = chartRows.map((r,i) => `${i?'L':'M'} ${x(i).toFixed(2)} ${y(upper[i]).toFixed(2)}`).join(' ');
    const bottom = chartRows.slice().reverse().map((r,j) => { const i=chartRows.length-1-j; return `L ${x(i).toFixed(2)} ${y(lower[i]).toFixed(2)}`; }).join(' ');
    el('path',{d:top+' '+bottom+' Z',fill:colorFor(g,gi),opacity:.86,stroke:'#fff','stroke-width':.8});
    lower = upper;
  });
  const idx = Math.max(0, chartRows.findIndex(r => r.month === selectedMonth));
  if(chartRows.length){ const sx = x(idx); el('line',{x1:sx,y1:T,x2:sx,y2:H-B,stroke:'#1d2733','stroke-width':1.5,'stroke-dasharray':'4 4'}); }
  el('text',{x:L,y:24,'font-size':16,fill:'#1d2733','font-weight':700},'Net Worth Explorer');
  chartRows.forEach((r,i)=>{ const rect=el('rect',{x:x(i)-7,y:T,width:14,height:H-T-B,fill:'transparent',style:'cursor:pointer'}); rect.addEventListener('click',()=>{monthSelect.value=r.month; render();}); });
  renderTables(rows, groups, chartRows[idx] || {month:selectedMonth,Total:0});
}
function renderTables(rows, groups, monthRow) {
  const monthRows = rows.filter(r => r.month === monthRow.month);
  const {start,end}=normalizedRange();
  metrics.innerHTML = `<div class="metric"><strong>${html(start)} to ${html(end)}</strong><span>Date range</span></div><div class="metric"><strong>${html(monthRow.month||'-')}</strong><span>Selected month</span></div><div class="metric"><strong>${fmt(monthRow.Total)}</strong><span>Filtered total</span></div><div class="metric"><strong>${monthRows.length}</strong><span>Account/component rows</span></div><div class="metric"><strong>${html(groupBy.options[groupBy.selectedIndex].text)}</strong><span>Current grouping</span></div>`;
  const grouped = groups.map(g => ({name:g, value:monthRow[g]||0, count:monthRows.filter(r => r[groupBy.value] === g).length})).filter(x => x.value || x.count).sort((a,b)=>b.value-a.value);
  breakdown.innerHTML = `<table><thead><tr><th>component</th><th>value</th><th>share</th><th>rows</th></tr></thead><tbody>${grouped.map((g,i)=>`<tr><td><span style="display:inline-block;width:10px;height:10px;background:${colorFor(g.name,i)};border-radius:2px;margin-right:7px"></span>${html(g.name)}</td><td>${fmt(g.value)}</td><td>${monthRow.Total?pct(g.value/monthRow.Total):'0.0%'}</td><td>${g.count}</td></tr>`).join('')}</tbody></table>`;
}
[ownerFilter,groupBy,mode,startDate,endDate,monthSelect,seriesChecks,accountChecks].forEach(node => node.addEventListener('change', render));
document.getElementById('resetBtn').addEventListener('click', () => { ownerFilter.value='__all__'; groupBy.value='series'; mode.value='value'; startDate.value=minDate; endDate.value=maxDate; monthSelect.value=data.months[data.months.length-1]||''; seriesChecks.querySelectorAll('input').forEach(i=>i.checked=true); accountChecks.querySelectorAll('input').forEach(i=>i.checked=true); render(); });
render();
</script>
<style>
.controls{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin:18px 0;padding:14px;background:#fff;border:1px solid var(--line);border-radius:6px}.controls label{display:grid;gap:5px;font-size:13px;color:var(--muted)}.controls select,.controls input,.controls button{padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink);font-size:14px}.filter-panel{display:grid;grid-template-columns:1fr;gap:10px;margin:16px 0}.filter-panel div{display:flex;gap:8px;flex-wrap:wrap}.filter-panel label{font-size:12px;background:#fff;border:1px solid var(--line);border-radius:6px;padding:6px 8px}
</style>
"""
    body = (
        body.replace("__PAYLOAD__", payload)
        .replace("__LATEST_MONTH__", html_escape(months[-1] if months else ""))
        .replace("__LATEST_TOTAL__", money(latest_total))
        .replace("__MONTH_COUNT__", str(len(months)))
        .replace("__ACCOUNT_COUNT__", str(len(account_rows)))
        .replace("__REPORT_END__", REPORT_END_DATE.isoformat())
    )
    write_html_report(REPORTS_DIR / "net_worth_stacked.html", "Net Worth Explorer", body)
    return {"months": len(months), "accounts": len({row["account_label"] for row in account_rows}), "report": str(REPORTS_DIR / "net_worth_stacked.html")}


if __name__ == "__main__":
    print(run())
