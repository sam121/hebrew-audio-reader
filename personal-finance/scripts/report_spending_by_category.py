from __future__ import annotations

import csv
import json
from collections import defaultdict
from decimal import Decimal
from typing import Any

from common import EXPORTS_DIR, PROCESSED_DIR, REPORTS_DIR, REPORT_END_DATE, REPORT_START_DATE, html_escape, parse_date, parse_decimal, write_csv, write_html_report


SPENDING_EXCLUDED_CATEGORIES = {"investment", "income"}
CATEGORY_COLORS = {
    "uncategorized": "#667085",
    "fees": "#c44536",
    "transport": "#2f80ed",
    "rides_hailing": "#00a878",
    "food_dining": "#b85c38",
    "groceries": "#6a994e",
    "utilities": "#8e6c2f",
    "subscriptions_software": "#6f5aa7",
    "business_services": "#344e7a",
    "travel": "#d97706",
    "shopping": "#ad3b72",
    "tax_government": "#4b5563",
    "health": "#b42318",
    "fitness_wellness": "#0f766e",
    "insurance": "#7c3aed",
    "housing": "#8f5f3c",
    "charity_donations": "#b45309",
    "cash_atm": "#525252",
    "education": "#2563eb",
    "entertainment": "#9333ea",
    "transfer": "#7a8699",
    "other": "#6f5aa7",
}


def is_true(value: Any) -> bool:
    return str(value or "").strip().lower() == "true"


def category_for(row: dict[str, str]) -> str:
    return (row.get("category") or "uncategorized").strip().lower() or "uncategorized"


def is_assumed_one_sided_transfer(row: dict[str, str]) -> bool:
    text = " ".join([row.get("description_clean", ""), row.get("description_raw", ""), row.get("merchant", "")]).lower()
    is_card_repayment = any(token in text for token in ["dbsc-", "dbs card centre", "card centre", "auto-pyt from acct"])
    is_dbs_fixed_deposit_move = row.get("institution") == "dbs" and any(
        token in text for token in ["advice | 0120", "fixed deposit principal amount", "fixed deposit/structured deposit"]
    )
    is_wise_internal = row.get("institution") == "wise" and (
        row.get("subcategory") == "wise_internal_conversion"
        or " debit | conversion" in text
        or " credit | conversion" in text
        or "sent money to amy katherine partington" in text
    )
    is_known_barclays_internal = row.get("institution") == "barclays" and "transfer to sort code 20-36-16" in text and "account 43168786" in text
    return (
        row.get("institution") == "ibkr"
        or "endowus" in text
        or "interactive brokers" in text
        or "interactive br " in text
        or is_card_repayment
        or is_dbs_fixed_deposit_move
        or is_wise_internal
        or is_known_barclays_internal
    )


def is_spending_candidate(row: dict[str, str]) -> bool:
    if category_for(row) in SPENDING_EXCLUDED_CATEGORIES:
        return False
    if row.get("matched_transfer_id"):
        return False
    if is_assumed_one_sided_transfer(row):
        return False
    return True


def money(value: Any) -> str:
    return f"{float(value):,.0f}"


def transaction_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    with (PROCESSED_DIR / "categorized_transactions.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tx_date = parse_date(row.get("date"))
            amount = parse_decimal(row.get("amount"))
            amount_sgd = parse_decimal(row.get("amount_sgd"))
            if not tx_date or amount is None or amount >= 0 or amount_sgd is None:
                continue
            if tx_date < REPORT_START_DATE or tx_date > REPORT_END_DATE:
                continue
            if not is_spending_candidate(row):
                continue
            rows.append(
                {
                    "month": tx_date.strftime("%Y-%m"),
                    "date": tx_date.isoformat(),
                    "owner": row.get("owner", ""),
                    "category": category_for(row),
                    "institution": row.get("institution", ""),
                    "account": row.get("account_name", "") or row.get("account_id", ""),
                    "merchant": row.get("merchant", ""),
                    "description": row.get("description_raw", ""),
                    "amount_sgd": abs(amount_sgd),
                    "source_file": row.get("source_file", ""),
                    "source_row": row.get("source_row", ""),
                    "confidence": row.get("confidence_status", ""),
                }
            )
    rows.sort(key=lambda item: (item["month"], item["date"], -item["amount_sgd"]))
    return rows


def write_exports(rows: list[dict[str, Any]]) -> None:
    monthly_category: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(lambda: {"outflow_sgd": Decimal("0"), "transaction_count": 0})
    monthly_total: dict[tuple[str, str], dict[str, Any]] = defaultdict(lambda: {"outflow_sgd": Decimal("0"), "transaction_count": 0})
    for row in rows:
        monthly_category[(row["month"], row["owner"], row["category"])]["outflow_sgd"] += row["amount_sgd"]
        monthly_category[(row["month"], row["owner"], row["category"])]["transaction_count"] += 1
        monthly_total[(row["month"], row["owner"])]["outflow_sgd"] += row["amount_sgd"]
        monthly_total[(row["month"], row["owner"])]["transaction_count"] += 1
    write_csv(
        EXPORTS_DIR / "monthly_spending_by_category.csv",
        [{"month": m, "owner": o, "category": c, **v} for (m, o, c), v in sorted(monthly_category.items())],
        ["month", "owner", "category", "outflow_sgd", "transaction_count"],
    )
    write_csv(
        EXPORTS_DIR / "monthly_spending_candidates.csv",
        [{"month": m, "owner": o, **v} for (m, o), v in sorted(monthly_total.items())],
        ["month", "owner", "outflow_sgd", "transaction_count"],
    )


def run() -> dict[str, Any]:
    rows = transaction_rows()
    write_exports(rows)
    months = sorted({row["month"] for row in rows})
    owners = sorted({row["owner"] for row in rows})
    categories = sorted({row["category"] for row in rows})
    institutions = sorted({row["institution"] for row in rows})
    latest_month = months[-1] if months else ""
    latest_total = sum((row["amount_sgd"] for row in rows if row["month"] == latest_month), Decimal("0"))
    payload = json.dumps(
        {
            "months": months,
            "owners": owners,
            "categories": categories,
            "institutions": institutions,
            "colors": CATEGORY_COLORS,
            "rows": [{k: float(v) if isinstance(v, Decimal) else v for k, v in row.items()} for row in rows],
        }
    )
    body = """
<div class="metric-row">
  <div class="metric"><strong>__LATEST_MONTH__</strong><span>Latest month</span></div>
  <div class="metric"><strong>SGD __LATEST_TOTAL__</strong><span>Latest filtered-spend baseline</span></div>
  <div class="metric"><strong>__MONTH_COUNT__</strong><span>Months</span></div>
  <div class="metric"><strong>__TX_COUNT__</strong><span>Spending transactions</span></div>
</div>
<p class="warning">Spending candidates exclude investments, income, matched transfers, and manually assumed one-sided transfers such as Endowus funding rows. Other unmatched transfer-looking rows remain visible for review. Report stops at the last completed month-end (__REPORT_END__). Categories are rule-based and can still need review.</p>
<div class="controls">
  <label>Owner <select id="ownerFilter"><option value="__all__">Samuel + Amy</option></select></label>
  <label>Group by <select id="groupBy"><option value="category">Category</option><option value="owner">Owner</option><option value="institution">Institution</option></select></label>
  <label>View <select id="mode"><option value="value">SGD value</option><option value="percent">100% composition</option></select></label>
  <label>Start <input id="startDate" type="date"></label>
  <label>End <input id="endDate" type="date"></label>
  <label>Month <select id="monthSelect"></select></label>
  <button id="resetBtn" type="button">Reset</button>
</div>
<div class="filter-panel">
  <div class="filter-heading"><strong>Categories</strong><span><button class="bulk-filter" type="button" data-target="categoryChecks" data-checked="true">Select all</button><button class="bulk-filter" type="button" data-target="categoryChecks" data-checked="false">Deselect all</button></span></div><div id="categoryChecks"></div>
  <div class="filter-heading"><strong>Institutions</strong><span><button class="bulk-filter" type="button" data-target="institutionChecks" data-checked="true">Select all</button><button class="bulk-filter" type="button" data-target="institutionChecks" data-checked="false">Deselect all</button></span></div><div id="institutionChecks"></div>
</div>
<div id="metrics" class="metric-row"></div>
<svg id="chart" viewBox="0 0 1180 620" role="img" aria-label="Interactive monthly spending explorer" style="width:100%;height:auto;background:#fff;border:1px solid var(--line);border-radius:6px;touch-action:none"></svg>
<h2>Selected Month Breakdown</h2>
<div id="breakdown"></div>
<h2>Transactions</h2>
<div id="transactions"></div>
<script>
const data = __PAYLOAD__;
const ownerFilter=document.getElementById('ownerFilter'), groupBy=document.getElementById('groupBy'), mode=document.getElementById('mode'), startDate=document.getElementById('startDate'), endDate=document.getElementById('endDate'), monthSelect=document.getElementById('monthSelect');
const categoryChecks=document.getElementById('categoryChecks'), institutionChecks=document.getElementById('institutionChecks'), metrics=document.getElementById('metrics'), breakdown=document.getElementById('breakdown'), transactions=document.getElementById('transactions'), svg=document.getElementById('chart');
const W=1180,H=620,L=84,R=30,T=36,B=76;
const html=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=v=>'S$'+Math.round(v||0).toLocaleString();
const fmt2=v=>'S$'+Number(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const pct=v=>(100*(v||0)).toFixed(1)+'%';
const clear=n=>{while(n.firstChild)n.removeChild(n.firstChild);};
const el=(name,attrs,text)=>{const node=document.createElementNS('http://www.w3.org/2000/svg',name);for(const[k,v]of Object.entries(attrs||{}))node.setAttribute(k,v);if(text!==undefined)node.textContent=text;svg.appendChild(node);return node;};
const allDates=data.rows.map(r=>r.date).filter(Boolean).sort();
const minDate=allDates[0]||'', maxDate=allDates[allDates.length-1]||'';
data.owners.forEach(o=>ownerFilter.insertAdjacentHTML('beforeend',`<option value="${html(o)}">${html(o[0].toUpperCase()+o.slice(1))}</option>`));
if(minDate){startDate.min=minDate;startDate.max=maxDate;endDate.min=minDate;endDate.max=maxDate;startDate.value=minDate;endDate.value=maxDate;}
function checks(container, values){container.innerHTML=values.map(v=>`<label><input type="checkbox" value="${html(v)}" checked> ${html(v)}</label>`).join('');}
checks(categoryChecks,data.categories); checks(institutionChecks,data.institutions);
function selected(container){return new Set([...container.querySelectorAll('input:checked')].map(i=>i.value));}
function normalizedRange(){let start=startDate.value||minDate,end=endDate.value||maxDate;if(start&&end&&start>end){const swap=start;start=end;end=swap;}return{start,end};}
function activeMonths(){const {start,end}=normalizedRange();const startMonth=(start||'0000-00-00').slice(0,7),endMonth=(end||'9999-99-99').slice(0,7);return data.months.filter(m=>m>=startMonth&&m<=endMonth);}
function refreshMonthOptions(months){const previous=monthSelect.value;monthSelect.innerHTML=months.map(m=>`<option value="${m}">${m}</option>`).join('');if(months.includes(previous))monthSelect.value=previous;else monthSelect.value=months[months.length-1]||'';}
function filteredRows(){const owner=ownerFilter.value,cats=selected(categoryChecks),insts=selected(institutionChecks),{start,end}=normalizedRange();return data.rows.filter(r=>(!start||r.date>=start)&&(!end||r.date<=end)&&(owner==='__all__'||r.owner===owner)&&cats.has(r.category)&&insts.has(r.institution));}
function pivot(rows,months){const key=groupBy.value;const groups=[...new Set(rows.map(r=>r[key]))].sort();const byMonth=months.map(month=>{const out={month,Total:0};groups.forEach(g=>out[g]=0);rows.filter(r=>r.month===month).forEach(r=>{out[r[key]]+=r.amount_sgd;out.Total+=r.amount_sgd;});return out;});return{groups,byMonth};}
function colorFor(group,i){if(data.colors[group])return data.colors[group];const p=['#315f9d','#c44536','#116466','#6f5aa7','#d99b2b','#667085','#8f5f3c','#0f766e','#ad3b72','#344e7a'];return p[i%p.length];}
function render(){clear(svg);const months=activeMonths();refreshMonthOptions(months);const rows=filteredRows();const {groups,byMonth}=pivot(rows,months);const maxY=mode.value==='percent'?1:Math.max(1,...byMonth.map(r=>r.Total))*1.08;const x=i=>L+i/Math.max(1,byMonth.length-1)*(W-L-R);const y=v=>T+(maxY-v)/maxY*(H-T-B);for(let i=0;i<=6;i++){const val=maxY*i/6,yy=y(val);el('line',{x1:L,y1:yy,x2:W-R,y2:yy,stroke:'#d9e0e7'});el('text',{x:L-10,y:yy+4,'text-anchor':'end','font-size':12,fill:'#5f6b7a'},mode.value==='percent'?pct(val):fmt(val));}let lower=byMonth.map(_=>0);groups.forEach((g,gi)=>{const upper=byMonth.map((r,i)=>lower[i]+(mode.value==='percent'?(r.Total?(r[g]||0)/r.Total:0):(r[g]||0)));const top=byMonth.map((r,i)=>`${i?'L':'M'} ${x(i).toFixed(2)} ${y(upper[i]).toFixed(2)}`).join(' ');const bottom=byMonth.slice().reverse().map((r,j)=>{const i=byMonth.length-1-j;return`L ${x(i).toFixed(2)} ${y(lower[i]).toFixed(2)}`;}).join(' ');el('path',{d:top+' '+bottom+' Z',fill:colorFor(g,gi),opacity:.86,stroke:'#fff','stroke-width':.8});lower=upper;});const idx=Math.max(0,byMonth.findIndex(r=>r.month===monthSelect.value));if(byMonth.length){const sx=x(idx);el('line',{x1:sx,y1:T,x2:sx,y2:H-B,stroke:'#1d2733','stroke-width':1.5,'stroke-dasharray':'4 4'});}el('text',{x:L,y:24,'font-size':16,fill:'#1d2733','font-weight':700},'Monthly Spending Explorer');byMonth.forEach((r,i)=>{const rect=el('rect',{x:x(i)-7,y:T,width:14,height:H-T-B,fill:'transparent',style:'cursor:pointer'});rect.addEventListener('click',()=>{monthSelect.value=r.month;render();});});renderTables(rows,groups,byMonth[idx]||{month:monthSelect.value,Total:0});}
function renderTables(rows,groups,monthRow){const monthRows=rows.filter(r=>r.month===monthRow.month);const totalRange=rows.reduce((sum,r)=>sum+(r.amount_sgd||0),0);const {start,end}=normalizedRange();metrics.innerHTML=`<div class="metric"><strong>${html(start)} to ${html(end)}</strong><span>Date range</span></div><div class="metric"><strong>${fmt(totalRange)}</strong><span>Range spend</span></div><div class="metric"><strong>${html(monthRow.month||'-')}</strong><span>Selected month</span></div><div class="metric"><strong>${fmt(monthRow.Total)}</strong><span>Selected month spend</span></div><div class="metric"><strong>${rows.length}</strong><span>Range transactions</span></div><div class="metric"><strong>${monthRows.length}</strong><span>Selected month transactions</span></div>`;const grouped=groups.map(g=>({name:g,value:monthRow[g]||0,count:monthRows.filter(r=>r[groupBy.value]===g).length})).filter(x=>x.value||x.count).sort((a,b)=>b.value-a.value);breakdown.innerHTML=`<table><thead><tr><th>group</th><th>amount</th><th>share</th><th>transactions</th></tr></thead><tbody>${grouped.map((g,i)=>`<tr><td><span style="display:inline-block;width:10px;height:10px;background:${colorFor(g.name,i)};border-radius:2px;margin-right:7px"></span>${html(g.name)}</td><td>${fmt2(g.value)}</td><td>${monthRow.Total?pct(g.value/monthRow.Total):'0.0%'}</td><td>${g.count}</td></tr>`).join('')}</tbody></table>`;transactions.innerHTML=`<table><thead><tr><th>date</th><th>owner</th><th>category</th><th>merchant</th><th>amount</th><th>institution</th><th>description</th></tr></thead><tbody>${monthRows.sort((a,b)=>b.amount_sgd-a.amount_sgd).slice(0,250).map(r=>`<tr><td>${html(r.date)}</td><td>${html(r.owner)}</td><td>${html(r.category)}</td><td>${html(r.merchant)}</td><td>${fmt2(r.amount_sgd)}</td><td>${html(r.institution)}</td><td>${html(r.description)}</td></tr>`).join('')}</tbody></table>`;}
[ownerFilter,groupBy,mode,startDate,endDate,monthSelect,categoryChecks,institutionChecks].forEach(n=>n.addEventListener('change',render));
document.getElementById('resetBtn').addEventListener('click',()=>{ownerFilter.value='__all__';groupBy.value='category';mode.value='value';startDate.value=minDate;endDate.value=maxDate;categoryChecks.querySelectorAll('input').forEach(i=>i.checked=true);institutionChecks.querySelectorAll('input').forEach(i=>i.checked=true);monthSelect.value=data.months[data.months.length-1]||'';render();});
document.querySelectorAll('.bulk-filter').forEach(btn=>btn.addEventListener('click',()=>{const target=document.getElementById(btn.dataset.target);const checked=btn.dataset.checked==='true';target.querySelectorAll('input[type="checkbox"]').forEach(input=>input.checked=checked);render();}));
render();
</script>
<style>
.controls{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin:18px 0;padding:14px;background:#fff;border:1px solid var(--line);border-radius:6px}.controls label{display:grid;gap:5px;font-size:13px;color:var(--muted)}.controls select,.controls input,.controls button{padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink);font-size:14px}.filter-panel{display:grid;grid-template-columns:1fr;gap:10px;margin:16px 0}.filter-panel div{display:flex;gap:8px;flex-wrap:wrap}.filter-panel label{font-size:12px;background:#fff;border:1px solid var(--line);border-radius:6px;padding:6px 8px}
.filter-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.filter-heading span{display:flex;gap:8px}.bulk-filter{padding:6px 9px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink);font-size:12px;cursor:pointer}
</style>
"""
    body = (
        body.replace("__PAYLOAD__", payload)
        .replace("__LATEST_MONTH__", html_escape(latest_month))
        .replace("__LATEST_TOTAL__", money(latest_total))
        .replace("__MONTH_COUNT__", str(len(months)))
        .replace("__TX_COUNT__", str(len(rows)))
        .replace("__REPORT_END__", REPORT_END_DATE.isoformat())
    )
    write_html_report(REPORTS_DIR / "spending_by_category.html", "Monthly Spending Explorer", body)
    return {"months": len(months), "transactions": len(rows), "report": str(REPORTS_DIR / "spending_by_category.html")}


if __name__ == "__main__":
    print(run())
