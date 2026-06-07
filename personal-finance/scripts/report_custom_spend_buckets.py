from __future__ import annotations

import csv
import json
from collections import defaultdict
from decimal import Decimal
from typing import Any

from common import EXPORTS_DIR, PROCESSED_DIR, REPORTS_DIR, REPORT_END_DATE, REPORT_START_DATE, html_escape, parse_date, parse_decimal, write_csv, write_html_report


BUCKETS = ["Groceries", "Amazon", "Amazon Fresh", "ATM withdrawals"]
COLORS = {
    "Groceries": "#4f8f46",
    "Amazon": "#315f9d",
    "Amazon Fresh": "#0f766e",
    "ATM withdrawals": "#525252",
}


def text_for(row: dict[str, str]) -> str:
    return " ".join([row.get("merchant", ""), row.get("description_raw", ""), row.get("description_clean", "")]).lower()


def bucket_for(row: dict[str, str]) -> str | None:
    text = text_for(row)
    compact = text.replace(" ", "").replace("-", "").replace("_", "")
    if "atm cash withdrawal" in text or "atm cash" in text:
        return "ATM withdrawals"
    if "amazon fresh" in text or "amzn fresh" in text or "amazonfresh" in compact or "amznfresh" in compact:
        return "Amazon Fresh"
    grocery_tokens = [
        "fairprice",
        "cold storage",
        "coldstorage",
        "redmart",
        "marks&spencer",
        "marks and spencer",
        "marksandspencer",
        "marks & spencer",
        "foodpanda",
        "ntuc fp",
        "fp xtra",
        "sainsburys",
        "tesco",
        "waitrose",
        "carrefour",
        "franprix",
        "monop",
    ]
    if any(token in text or token in compact for token in grocery_tokens):
        return "Groceries"
    amazon_text_tokens = [
        "amazon",
        "amzn",
        "kindle svcs",
        "audible",
    ]
    amazon_compact_tokens = ["amazon", "amzn", "amznprime", "amznmktp", "amznmktplace"]
    if any(token in text for token in amazon_text_tokens) or any(token in compact for token in amazon_compact_tokens):
        return "Amazon"
    return None


def run() -> dict[str, Any]:
    monthly: dict[tuple[str, str, str], dict[str, Any]] = defaultdict(lambda: {"amount_sgd": Decimal("0"), "transaction_count": 0})
    details: list[dict[str, Any]] = []
    with (PROCESSED_DIR / "categorized_transactions.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tx_date = parse_date(row.get("date"))
            amount = parse_decimal(row.get("amount"))
            amount_sgd = parse_decimal(row.get("amount_sgd"))
            if not tx_date or tx_date < REPORT_START_DATE or tx_date > REPORT_END_DATE:
                continue
            if amount is None or amount >= 0 or amount_sgd is None:
                continue
            bucket = bucket_for(row)
            if bucket is None:
                continue
            spend = abs(amount_sgd)
            month = tx_date.strftime("%Y-%m")
            owner = row.get("owner") or "unknown"
            monthly[(month, owner, bucket)]["amount_sgd"] += spend
            monthly[(month, owner, bucket)]["transaction_count"] += 1
            details.append(
                {
                    "date": tx_date.isoformat(),
                    "month": month,
                    "owner": owner,
                    "bucket": bucket,
                    "merchant": row.get("merchant", ""),
                    "institution": row.get("institution", ""),
                    "amount_sgd": spend,
                    "description": row.get("description_raw", ""),
                    "source_file": row.get("source_file", ""),
                    "source_row": row.get("source_row", ""),
                }
            )

    monthly_rows = [{"month": m, "owner": o, "bucket": b, **v} for (m, o, b), v in sorted(monthly.items())]
    write_csv(EXPORTS_DIR / "custom_spend_buckets_monthly.csv", monthly_rows, ["month", "owner", "bucket", "amount_sgd", "transaction_count"])
    write_csv(EXPORTS_DIR / "custom_spend_buckets_detail.csv", details, ["date", "month", "owner", "bucket", "merchant", "institution", "amount_sgd", "description", "source_file", "source_row"])

    months = sorted({row["month"] for row in details})
    owners = sorted({row["owner"] for row in details})
    total = sum((row["amount_sgd"] for row in details), Decimal("0"))
    bucket_totals = {
        bucket: sum((row["amount_sgd"] for row in details if row["bucket"] == bucket), Decimal("0"))
        for bucket in BUCKETS
    }
    payload = json.dumps(
        {
            "months": months,
            "owners": owners,
            "buckets": BUCKETS,
            "colors": COLORS,
            "rows": [{k: float(v) if isinstance(v, Decimal) else v for k, v in row.items()} for row in details],
        }
    )
    body = """
<div class="metric-row">
  <div class="metric"><strong>SGD __TOTAL__</strong><span>Total selected bucket spend</span></div>
  <div class="metric"><strong>__MONTHS__</strong><span>Months</span></div>
  <div class="metric"><strong>__TXS__</strong><span>Transactions</span></div>
</div>
<p class="warning">This focused view is merchant-text based. Amazon Fresh is separated before ordinary Amazon; ATM withdrawals are detected from raw descriptions, including rows previously categorized elsewhere. Report stops at __REPORT_END__.</p>
<div class="controls">
  <label>Owner <select id="ownerFilter"><option value="__all__">Samuel + Amy</option></select></label>
  <label>View <select id="mode"><option value="stacked">Stacked by category</option><option value="lines">Lines by category</option></select></label>
  <label>Start <select id="startMonth"></select></label>
  <label>End <select id="endMonth"></select></label>
  <label>Selected month <select id="monthSelect"></select></label>
  <button id="resetBtn" type="button">Reset</button>
</div>
<div class="filter-panel">
  <div class="filter-heading"><strong>Categories</strong><span><button class="bulk-filter" type="button" data-checked="true">Select all</button><button class="bulk-filter" type="button" data-checked="false">Deselect all</button></span></div>
  <div id="bucketChecks"></div>
</div>
<div id="metrics" class="metric-row"></div>
<svg id="chart" viewBox="0 0 1180 620" role="img" aria-label="Focused monthly spend buckets" style="width:100%;height:auto;background:#fff;border:1px solid var(--line);border-radius:6px;touch-action:none"></svg>
<h2>Bucket Totals</h2>
<div id="breakdown"></div>
<h2>Transactions</h2>
<div id="transactions"></div>
<script>
const data=__PAYLOAD__;
const ownerFilter=document.getElementById('ownerFilter'), mode=document.getElementById('mode'), startMonth=document.getElementById('startMonth'), endMonth=document.getElementById('endMonth'), monthSelect=document.getElementById('monthSelect'), bucketChecks=document.getElementById('bucketChecks'), metrics=document.getElementById('metrics'), breakdown=document.getElementById('breakdown'), transactions=document.getElementById('transactions'), svg=document.getElementById('chart');
const W=1180,H=620,L=88,R=160,T=42,B=86;
const html=v=>String(v??'').replace(/[&<>"']/g,c=>({'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}[c]));
const fmt=v=>'S$'+Math.round(v||0).toLocaleString();
const fmt2=v=>'S$'+Number(v||0).toLocaleString(undefined,{minimumFractionDigits:2,maximumFractionDigits:2});
const clear=n=>{while(n.firstChild)n.removeChild(n.firstChild);};
const el=(name,attrs,text)=>{const node=document.createElementNS('http://www.w3.org/2000/svg',name);for(const[k,v]of Object.entries(attrs||{}))node.setAttribute(k,v);if(text!==undefined)node.textContent=text;svg.appendChild(node);return node;};
data.owners.forEach(o=>ownerFilter.insertAdjacentHTML('beforeend',`<option value="${html(o)}">${html(o[0].toUpperCase()+o.slice(1))}</option>`));
function monthOptions(node, months=data.months){node.innerHTML=months.map(m=>`<option value="${m}">${m}</option>`).join('');}
monthOptions(startMonth); monthOptions(endMonth); monthOptions(monthSelect); if(data.months.length){startMonth.value=data.months[0];endMonth.value=data.months[data.months.length-1];monthSelect.value=data.months[data.months.length-1];}
bucketChecks.innerHTML=data.buckets.map(b=>`<label><input type="checkbox" value="${html(b)}" checked> ${html(b)}</label>`).join('');
function selectedBuckets(){return new Set([...bucketChecks.querySelectorAll('input:checked')].map(i=>i.value));}
function activeMonths(){let s=startMonth.value,e=endMonth.value;if(s>e){const t=s;s=e;e=t;}return data.months.filter(m=>m>=s&&m<=e);}
function refreshSelectedMonth(months){const prev=monthSelect.value;monthOptions(monthSelect,months);monthSelect.value=months.includes(prev)?prev:(months[months.length-1]||'');}
function filteredRows(){const owner=ownerFilter.value,buckets=selectedBuckets(),months=new Set(activeMonths());return data.rows.filter(r=>months.has(r.month)&&(owner==='__all__'||r.owner===owner)&&buckets.has(r.bucket));}
function pivot(rows,months){const buckets=data.buckets.filter(b=>selectedBuckets().has(b));const byMonth=months.map(m=>{const out={month:m,Total:0};buckets.forEach(b=>out[b]=0);rows.filter(r=>r.month===m).forEach(r=>{out[r.bucket]+=r.amount_sgd;out.Total+=r.amount_sgd;});return out;});return{buckets,byMonth};}
function x(i,n){return L+i/Math.max(1,n-1)*(W-L-R);}
function color(b){return data.colors[b]||'#667085';}
function render(){clear(svg);const months=activeMonths();refreshSelectedMonth(months);const rows=filteredRows();const {buckets,byMonth}=pivot(rows,months);const maxY=Math.max(1,...byMonth.map(r=>mode.value==='stacked'?r.Total:Math.max(...buckets.map(b=>r[b]||0))))*1.08;const y=v=>T+(maxY-v)/maxY*(H-T-B);for(let i=0;i<=6;i++){const val=maxY*i/6,yy=y(val);el('line',{x1:L,y1:yy,x2:W-R,y2:yy,stroke:'#d9e0e7'});el('text',{x:L-10,y:yy+4,'text-anchor':'end','font-size':12,fill:'#5f6b7a'},fmt(val));}byMonth.forEach((r,i)=>{if(i%Math.ceil(Math.max(1,byMonth.length/14))===0)el('text',{x:x(i,byMonth.length),y:H-B+30,'text-anchor':'middle','font-size':12,fill:'#5f6b7a'},r.month);});
if(mode.value==='stacked'){let lower=byMonth.map(_=>0);buckets.forEach(b=>{const upper=byMonth.map((r,i)=>lower[i]+(r[b]||0));const top=byMonth.map((r,i)=>`${i?'L':'M'} ${x(i,byMonth.length).toFixed(2)} ${y(upper[i]).toFixed(2)}`).join(' ');const bottom=byMonth.slice().reverse().map((r,j)=>{const i=byMonth.length-1-j;return`L ${x(i,byMonth.length).toFixed(2)} ${y(lower[i]).toFixed(2)}`;}).join(' ');el('path',{d:top+' '+bottom+' Z',fill:color(b),opacity:.84,stroke:'#fff','stroke-width':1});lower=upper;});}else{buckets.forEach(b=>{const path=byMonth.map((r,i)=>`${i?'L':'M'} ${x(i,byMonth.length).toFixed(2)} ${y(r[b]||0).toFixed(2)}`).join(' ');el('path',{d:path,fill:'none',stroke:color(b),'stroke-width':3});byMonth.forEach((r,i)=>{if(r[b])el('circle',{cx:x(i,byMonth.length),cy:y(r[b]),r:3,fill:color(b)});});});}
const selectedIndex=Math.max(0,byMonth.findIndex(r=>r.month===monthSelect.value));if(byMonth.length){const sx=x(selectedIndex,byMonth.length);el('line',{x1:sx,y1:T,x2:sx,y2:H-B,stroke:'#1d2733','stroke-width':1.6,'stroke-dasharray':'4 4'});el('text',{x:sx,y:T-12,'text-anchor':'middle','font-size':12,fill:'#1d2733'},monthSelect.value);}byMonth.forEach((r,i)=>{const width=Math.max(18,(W-L-R)/Math.max(1,byMonth.length));const hit=el('rect',{x:x(i,byMonth.length)-width/2,y:T,width,height:H-T-B,fill:'transparent',style:'cursor:pointer'});hit.addEventListener('click',()=>{monthSelect.value=r.month;render();});hit.addEventListener('mouseenter',()=>hit.setAttribute('fill','rgba(29,39,51,0.06)'));hit.addEventListener('mouseleave',()=>hit.setAttribute('fill','transparent'));});
buckets.forEach((b,i)=>{el('rect',{x:W-R+20,y:T+i*24,width:12,height:12,fill:color(b)});el('text',{x:W-R+38,y:T+10+i*24,'font-size':12,fill:'#1d2733'},b);});el('text',{x:L,y:26,'font-size':16,fill:'#1d2733','font-weight':700},'Monthly Spend: Groceries, Amazon, Amazon Fresh, ATM');renderTables(rows,buckets);}
function renderTables(rows,buckets){const total=rows.reduce((s,r)=>s+r.amount_sgd,0);const monthRows=rows.filter(r=>r.month===monthSelect.value);const monthTotal=monthRows.reduce((s,r)=>s+r.amount_sgd,0);metrics.innerHTML=`<div class="metric"><strong>${html(startMonth.value)} to ${html(endMonth.value)}</strong><span>Month range</span></div><div class="metric"><strong>${fmt(total)}</strong><span>Range spend</span></div><div class="metric"><strong>${html(monthSelect.value||'-')}</strong><span>Selected month</span></div><div class="metric"><strong>${fmt(monthTotal)}</strong><span>Selected month spend</span></div><div class="metric"><strong>${monthRows.length}</strong><span>Selected month transactions</span></div>`;const grouped=buckets.map(b=>({bucket:b,value:monthRows.filter(r=>r.bucket===b).reduce((s,r)=>s+r.amount_sgd,0),count:monthRows.filter(r=>r.bucket===b).length})).filter(g=>g.value||g.count).sort((a,b)=>b.value-a.value);breakdown.innerHTML=`<table><thead><tr><th>category</th><th>amount</th><th>transactions</th></tr></thead><tbody>${grouped.map(g=>`<tr><td><span style="display:inline-block;width:10px;height:10px;background:${color(g.bucket)};border-radius:2px;margin-right:7px"></span>${html(g.bucket)}</td><td>${fmt2(g.value)}</td><td>${g.count}</td></tr>`).join('')}</tbody></table>`;transactions.innerHTML=`<table><thead><tr><th>date</th><th>owner</th><th>category</th><th>merchant</th><th>amount</th><th>institution</th><th>description</th></tr></thead><tbody>${monthRows.sort((a,b)=>b.amount_sgd-a.amount_sgd).slice(0,400).map(r=>`<tr><td>${html(r.date)}</td><td>${html(r.owner)}</td><td>${html(r.bucket)}</td><td>${html(r.merchant)}</td><td>${fmt2(r.amount_sgd)}</td><td>${html(r.institution)}</td><td>${html(r.description)}</td></tr>`).join('')}</tbody></table>`;}
[ownerFilter,mode,startMonth,endMonth,monthSelect,bucketChecks].forEach(n=>n.addEventListener('change',render));
document.getElementById('resetBtn').addEventListener('click',()=>{ownerFilter.value='__all__';mode.value='stacked';startMonth.value=data.months[0]||'';endMonth.value=data.months[data.months.length-1]||'';monthSelect.value=data.months[data.months.length-1]||'';bucketChecks.querySelectorAll('input').forEach(i=>i.checked=true);render();});
document.querySelectorAll('.bulk-filter').forEach(btn=>btn.addEventListener('click',()=>{const checked=btn.dataset.checked==='true';bucketChecks.querySelectorAll('input').forEach(i=>i.checked=checked);render();}));
render();
</script>
<style>
.controls{display:flex;gap:12px;align-items:end;flex-wrap:wrap;margin:18px 0;padding:14px;background:#fff;border:1px solid var(--line);border-radius:6px}.controls label{display:grid;gap:5px;font-size:13px;color:var(--muted)}.controls select,.controls button{padding:8px 10px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink);font-size:14px}.filter-panel{display:grid;gap:10px;margin:16px 0}.filter-panel div{display:flex;gap:8px;flex-wrap:wrap}.filter-panel label{font-size:12px;background:#fff;border:1px solid var(--line);border-radius:6px;padding:6px 8px}.filter-heading{display:flex;align-items:center;justify-content:space-between;gap:12px}.filter-heading span{display:flex;gap:8px}.bulk-filter{padding:6px 9px;border:1px solid var(--line);border-radius:6px;background:#fff;color:var(--ink);font-size:12px;cursor:pointer}
</style>
"""
    body = (
        body.replace("__PAYLOAD__", payload)
        .replace("__TOTAL__", f"{float(total):,.0f}")
        .replace("__MONTHS__", str(len(months)))
        .replace("__TXS__", str(len(details)))
        .replace("__REPORT_END__", REPORT_END_DATE.isoformat())
    )
    write_html_report(REPORTS_DIR / "custom_spend_buckets.html", "Focused Spend Buckets", body)
    return {
        "report": str(REPORTS_DIR / "custom_spend_buckets.html"),
        "transactions": len(details),
        "total_sgd": str(total),
        "bucket_totals": {k: str(v) for k, v in bucket_totals.items()},
    }


if __name__ == "__main__":
    print(run())
