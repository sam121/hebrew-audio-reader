from __future__ import annotations

import json
from collections import defaultdict
from decimal import Decimal
from typing import Any

from common import EXPORTS_DIR, REPORTS_DIR, REPORT_END_DATE, html_escape, write_csv, write_html_report
from report_spending_by_category import transaction_rows


GROUP_MAP = {
    "mortgage": "Mortgage",
    "housing": "Housing & rent",
    "tax_government": "Tax & government",
    "travel": "Travel",
    "food_dining": "Food & groceries",
    "groceries": "Food & groceries",
    "education": "Childcare & education",
    "transport": "Transport",
    "rides_hailing": "Transport",
    "shopping": "Shopping & lifestyle",
    "entertainment": "Shopping & lifestyle",
    "fitness_wellness": "Shopping & lifestyle",
    "health": "Health & insurance",
    "insurance": "Health & insurance",
    "utilities": "Utilities, subs & fees",
    "subscriptions_software": "Utilities, subs & fees",
    "fees": "Utilities, subs & fees",
    "business_services": "Utilities, subs & fees",
    "charity_donations": "Charity & religion",
    "religion_community": "Charity & religion",
    "cash_atm": "Cash",
    "transfer": "Transfer review",
    "uncategorized": "Uncategorized",
}

GROUP_ORDER = [
    "Mortgage",
    "Housing & rent",
    "Tax & government",
    "Travel",
    "Food & groceries",
    "Childcare & education",
    "Transport",
    "Shopping & lifestyle",
    "Health & insurance",
    "Utilities, subs & fees",
    "Charity & religion",
    "Cash",
    "Transfer review",
    "Uncategorized",
    "Other",
]

GROUP_COLORS = {
    "Mortgage": "#7f1d1d",
    "Housing & rent": "#8f5f3c",
    "Tax & government": "#4b5563",
    "Travel": "#d97706",
    "Food & groceries": "#6a994e",
    "Childcare & education": "#2563eb",
    "Transport": "#2f80ed",
    "Shopping & lifestyle": "#ad3b72",
    "Health & insurance": "#b42318",
    "Utilities, subs & fees": "#6f5aa7",
    "Charity & religion": "#b45309",
    "Cash": "#525252",
    "Transfer review": "#7a8699",
    "Uncategorized": "#667085",
    "Other": "#344e7a",
}


def quarter_for(month: str) -> str:
    year = int(month[:4])
    month_number = int(month[5:7])
    return f"{year}-Q{((month_number - 1) // 3) + 1}"


def group_for(category: str) -> str:
    return GROUP_MAP.get((category or "").strip().lower(), "Other")


def decimal_float(value: Any) -> Any:
    return float(value) if isinstance(value, Decimal) else value


def write_exports(rows: list[dict[str, Any]]) -> None:
    quarterly_group: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(lambda: {"outflow_sgd": Decimal("0"), "transaction_count": 0})
    quarterly_total: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"outflow_sgd": Decimal("0"), "transaction_count": 0})
    for row in rows:
        key = (row["quarter"], row["owner"], row["group"])
        quarterly_group[key]["outflow_sgd"] += row["amount_sgd"]
        quarterly_group[key]["transaction_count"] += 1
        total_key = (row["quarter"], row["owner"])
        quarterly_total[total_key]["outflow_sgd"] += row["amount_sgd"]
        quarterly_total[total_key]["transaction_count"] += 1
    write_csv(
        EXPORTS_DIR / "quarterly_spending_by_group.csv",
        [{"quarter": q, "owner": o, "group": g, **v} for (q, o, g), v in sorted(quarterly_group.items())],
        ["quarter", "owner", "group", "outflow_sgd", "transaction_count"],
    )
    write_csv(
        EXPORTS_DIR / "quarterly_spending_candidates.csv",
        [{"quarter": q, "owner": o, **v} for (q, o), v in sorted(quarterly_total.items())],
        ["quarter", "owner", "outflow_sgd", "transaction_count"],
    )


def run() -> dict[str, Any]:
    rows = []
    for row in transaction_rows():
        enriched = dict(row)
        enriched["quarter"] = quarter_for(row["month"])
        enriched["group"] = group_for(row["category"])
        rows.append(enriched)
    write_exports(rows)

    quarters = sorted({row["quarter"] for row in rows})
    owners = sorted({row["owner"] for row in rows})
    groups = [group for group in GROUP_ORDER if any(row["group"] == group for row in rows)]
    latest_quarter = quarters[-1] if quarters else ""
    latest_total = sum((row["amount_sgd"] for row in rows if row["quarter"] == latest_quarter), Decimal("0"))
    payload = json.dumps(
        {
            "quarters": quarters,
            "owners": owners,
            "groups": groups,
            "colors": GROUP_COLORS,
            "rows": [{k: decimal_float(v) for k, v in row.items()} for row in rows],
        }
    )
    body = """
<div class="metric-row">
  <div class="metric"><strong>__LATEST_QUARTER__</strong><span>Latest quarter</span></div>
  <div class="metric"><strong>SGD __LATEST_TOTAL__</strong><span>Latest quarter spend</span></div>
  <div class="metric"><strong>__QUARTER_COUNT__</strong><span>Quarters</span></div>
  <div class="metric"><strong>__TX_COUNT__</strong><span>Transactions</span></div>
</div>
<p class="warning">Quarterly view uses the same spending-candidate logic as the monthly report, but combines categories into fewer decision-level groups. It excludes investments, income, matched transfers, and assumed one-sided internal transfers. Unmatched transfer-looking rows are grouped under Transfer review. Report stops at __REPORT_END__.</p>
<div class="controls">
  <label>Owner <select id="ownerFilter"><option value="__all__">Samuel + Amy</option></select></label>
  <label>View <select id="mode"><option value="value">SGD value</option><option value="percent">100% composition</option></select></label>
  <label>Start quarter <select id="startQuarter"></select></label>
  <label>End quarter <select id="endQuarter"></select></label>
  <label>Selected quarter <select id="quarterSelect"></select></label>
  <button id="resetBtn" type="button">Reset</button>
</div>
<div class="filter-panel">
  <div class="filter-heading"><strong>Groups</strong><span><button class="bulk-filter" type="button" data-checked="true">Select all</button><button class="bulk-filter" type="button" data-checked="false">Deselect all</button></span></div>
  <div id="groupChecks"></div>
</div>
<div id="metrics" class="metric-row"></div>
<svg id="chart" viewBox="0 0 1180 620" role="img" aria-label="Quarterly spending by grouped category" style="width:100%;height:auto;background:#fff;border:1px solid var(--line);border-radius:6px;touch-action:none"></svg>
<h2>Selected Quarter Breakdown</h2>
<div id="breakdown"></div>
<h2>Selected Quarter Transactions</h2>
<div id="transactions"></div>
<script>
const data = __PAYLOAD__;
const ownerFilter=document.getElementById('ownerFilter'), mode=document.getElementById('mode'), startQuarter=document.getElementById('startQuarter'), endQuarter=document.getElementById('endQuarter'), quarterSelect=document.getElementById('quarterSelect'), groupChecks=document.getElementById('groupChecks'), metrics=document.getElementById('metrics'), breakdown=document.getElementById('breakdown'), transactions=document.getElementById('transactions'), svg=document.getElementById('chart');
const W=1180,H=620,L=88,R=36,T=42,B=86;
const html=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=v=>'S$'+Math.round(v||0).toLocaleString();
const fmt2=v=>'S$'+Number(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const pct=v=>(100*(v||0)).toFixed(1)+'%';
const clear=n=>{while(n.firstChild)n.removeChild(n.firstChild);};
const el=(name,attrs,text)=>{const node=document.createElementNS('http://www.w3.org/2000/svg',name);for(const[k,v]of Object.entries(attrs||{}))node.setAttribute(k,v);if(text!==undefined)node.textContent=text;svg.appendChild(node);return node;};
data.owners.forEach(o=>ownerFilter.insertAdjacentHTML('beforeend',`<option value="${html(o)}">${html(o[0].toUpperCase()+o.slice(1))}</option>`));
function quarterOptions(node){node.innerHTML=data.quarters.map(q=>`<option value="${q}">${q}</option>`).join('');}
quarterOptions(startQuarter); quarterOptions(endQuarter); quarterOptions(quarterSelect);
if(data.quarters.length){startQuarter.value=data.quarters[0];endQuarter.value=data.quarters[data.quarters.length-1];quarterSelect.value=data.quarters[data.quarters.length-1];}
groupChecks.innerHTML=data.groups.map(g=>`<label><input type="checkbox" value="${html(g)}" checked> ${html(g)}</label>`).join('');
function selectedGroups(){return new Set([...groupChecks.querySelectorAll('input:checked')].map(i=>i.value));}
function activeQuarters(){let s=startQuarter.value,e=endQuarter.value;if(s>e){const tmp=s;s=e;e=tmp;}return data.quarters.filter(q=>q>=s&&q<=e);}
function refreshSelectedQuarter(quarters){const prev=quarterSelect.value;quarterSelect.innerHTML=quarters.map(q=>`<option value="${q}">${q}</option>`).join('');quarterSelect.value=quarters.includes(prev)?prev:(quarters[quarters.length-1]||'');}
function filteredRows(){const owner=ownerFilter.value, groups=selectedGroups(), quarters=new Set(activeQuarters());return data.rows.filter(r=>quarters.has(r.quarter)&&(owner==='__all__'||r.owner===owner)&&groups.has(r.group));}
function pivot(rows,quarters){const groups=data.groups.filter(g=>selectedGroups().has(g));const byQuarter=quarters.map(q=>{const out={quarter:q,Total:0};groups.forEach(g=>out[g]=0);rows.filter(r=>r.quarter===q).forEach(r=>{out[r.group]+=r.amount_sgd;out.Total+=r.amount_sgd;});return out;});return{groups,byQuarter};}
function colorFor(g){return data.colors[g]||'#344e7a';}
function render(){clear(svg);const quarters=activeQuarters();refreshSelectedQuarter(quarters);const rows=filteredRows();const {groups,byQuarter}=pivot(rows,quarters);const maxY=mode.value==='percent'?1:Math.max(1,...byQuarter.map(r=>r.Total))*1.08;const x=i=>L+i/Math.max(1,byQuarter.length-1)*(W-L-R);const y=v=>T+(maxY-v)/maxY*(H-T-B);for(let i=0;i<=6;i++){const val=maxY*i/6, yy=y(val);el('line',{x1:L,y1:yy,x2:W-R,y2:yy,stroke:'#d9e0e7'});el('text',{x:L-10,y:yy+4,'text-anchor':'end','font-size':12,fill:'#5f6b7a'},mode.value==='percent'?pct(val):fmt(val));}let lower=byQuarter.map(_=>0);groups.forEach(g=>{const upper=byQuarter.map((r,i)=>lower[i]+(mode.value==='percent'?(r.Total?(r[g]||0)/r.Total:0):(r[g]||0)));const top=byQuarter.map((r,i)=>`${i?'L':'M'} ${x(i).toFixed(2)} ${y(upper[i]).toFixed(2)}`).join(' ');const bottom=byQuarter.slice().reverse().map((r,j)=>{const i=byQuarter.length-1-j;return`L ${x(i).toFixed(2)} ${y(lower[i]).toFixed(2)}`;}).join(' ');el('path',{d:top+' '+bottom+' Z',fill:colorFor(g),opacity:.86,stroke:'#fff','stroke-width':1});lower=upper;});byQuarter.forEach((r,i)=>{if(i%Math.ceil(Math.max(1,byQuarter.length/14))===0)el('text',{x:x(i),y:H-B+30,'text-anchor':'middle','font-size':12,fill:'#5f6b7a'},r.quarter);const hit=el('rect',{x:x(i)-12,y:T,width:24,height:H-T-B,fill:'transparent',style:'cursor:pointer'});hit.addEventListener('click',()=>{quarterSelect.value=r.quarter;render();});});const idx=Math.max(0,byQuarter.findIndex(r=>r.quarter===quarterSelect.value));if(byQuarter.length){const sx=x(idx);el('line',{x1:sx,y1:T,x2:sx,y2:H-B,stroke:'#1d2733','stroke-width':1.6,'stroke-dasharray':'4 4'});}el('text',{x:L,y:26,'font-size':16,fill:'#1d2733','font-weight':700},'Quarterly Spending by Group');renderTables(rows,groups,byQuarter[idx]||{quarter:quarterSelect.value,Total:0});}
function renderTables(rows,groups,quarterRow){const quarterRows=rows.filter(r=>r.quarter===quarterRow.quarter);const totalRange=rows.reduce((sum,r)=>sum+(r.amount_sgd||0),0);metrics.innerHTML=`<div class="metric"><strong>${html(startQuarter.value)} to ${html(endQuarter.value)}</strong><span>Quarter range</span></div><div class="metric"><strong>${fmt(totalRange)}</strong><span>Range spend</span></div><div class="metric"><strong>${html(quarterRow.quarter||'-')}</strong><span>Selected quarter</span></div><div class="metric"><strong>${fmt(quarterRow.Total)}</strong><span>Quarter spend</span></div><div class="metric"><strong>${rows.length}</strong><span>Range transactions</span></div><div class="metric"><strong>${quarterRows.length}</strong><span>Quarter transactions</span></div>`;const grouped=groups.map(g=>({name:g,value:quarterRow[g]||0,count:quarterRows.filter(r=>r.group===g).length})).filter(x=>x.value||x.count).sort((a,b)=>b.value-a.value);breakdown.innerHTML=`<table><thead><tr><th>group</th><th>amount</th><th>share</th><th>transactions</th></tr></thead><tbody>${grouped.map(g=>`<tr><td><span style="display:inline-block;width:10px;height:10px;background:${colorFor(g.name)};border-radius:2px;margin-right:7px"></span>${html(g.name)}</td><td>${fmt2(g.value)}</td><td>${quarterRow.Total?pct(g.value/quarterRow.Total):'0.0%'}</td><td>${g.count}</td></tr>`).join('')}</tbody></table>`;transactions.innerHTML=`<table><thead><tr><th>date</th><th>owner</th><th>group</th><th>category</th><th>merchant</th><th>amount</th><th>institution</th><th>description</th></tr></thead><tbody>${quarterRows.sort((a,b)=>b.amount_sgd-a.amount_sgd).slice(0,300).map(r=>`<tr><td>${html(r.date)}</td><td>${html(r.owner)}</td><td>${html(r.group)}</td><td>${html(r.category)}</td><td>${html(r.merchant)}</td><td>${fmt2(r.amount_sgd)}</td><td>${html(r.institution)}</td><td>${html(r.description)}</td></tr>`).join('')}</tbody></table>`;}
[ownerFilter,mode,startQuarter,endQuarter,quarterSelect,groupChecks].forEach(n=>n.addEventListener('change',render));
document.getElementById('resetBtn').addEventListener('click',()=>{ownerFilter.value='__all__';mode.value='value';startQuarter.value=data.quarters[0]||'';endQuarter.value=data.quarters[data.quarters.length-1]||'';quarterSelect.value=data.quarters[data.quarters.length-1]||'';groupChecks.querySelectorAll('input').forEach(i=>i.checked=true);render();});
document.querySelectorAll('.bulk-filter').forEach(btn=>btn.addEventListener('click',()=>{const checked=btn.dataset.checked==='true';groupChecks.querySelectorAll('input[type="checkbox"]').forEach(input=>input.checked=checked);render();}));
render();
</script>
<style>
.controls{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin:18px 0;padding:14px;background:#fff;border:1px solid var(--line);border-radius:6px}.controls label{display:grid;gap:5px;font-size:13px;color:var(--muted)}.controls select,.controls button{padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink);font-size:14px}.filter-panel{display:grid;gap:10px;margin:16px 0}.filter-panel div{display:flex;gap:8px;flex-wrap:wrap}.filter-panel label{font-size:12px;background:#fff;border:1px solid var(--line);border-radius:6px;padding:6px 8px}.filter-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.filter-heading span{display:flex;gap:8px}.bulk-filter{padding:6px 9px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink);font-size:12px;cursor:pointer}
</style>
"""
    body = (
        body.replace("__PAYLOAD__", payload)
        .replace("__LATEST_QUARTER__", html_escape(latest_quarter))
        .replace("__LATEST_TOTAL__", f"{float(latest_total):,.0f}")
        .replace("__QUARTER_COUNT__", str(len(quarters)))
        .replace("__TX_COUNT__", str(len(rows)))
        .replace("__REPORT_END__", REPORT_END_DATE.isoformat())
    )
    write_html_report(REPORTS_DIR / "spending_quarterly.html", "Quarterly Spending by Group", body)
    return {"quarters": len(quarters), "transactions": len(rows), "report": str(REPORTS_DIR / "spending_quarterly.html")}


if __name__ == "__main__":
    print(run())
