from __future__ import annotations

import csv
import json
from collections import defaultdict
from decimal import Decimal
from typing import Any

from common import EXPORTS_DIR, PROCESSED_DIR, REPORTS_DIR, REPORT_END_DATE, REPORT_START_DATE, html_escape, parse_date, parse_decimal, write_csv, write_html_report


def money(value: Any) -> str:
    return f"{float(value):,.2f}"


def is_jimmy_monkey(row: dict[str, str]) -> bool:
    text = " ".join(
        [
            row.get("description_raw", ""),
            row.get("description_clean", ""),
            row.get("merchant", ""),
        ]
    ).lower()
    normalized = text.replace(" ", "").replace("-", "")
    return ("jimmy" in text and "monkey" in text) or "jimmymonkey" in normalized


def run() -> dict[str, Any]:
    monthly: dict[str, dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    transactions = []
    with (PROCESSED_DIR / "categorized_transactions.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tx_date = parse_date(row.get("date"))
            amount = parse_decimal(row.get("amount"))
            amount_sgd = parse_decimal(row.get("amount_sgd"))
            if not tx_date or tx_date < REPORT_START_DATE or tx_date > REPORT_END_DATE:
                continue
            if amount is None or amount >= 0 or amount_sgd is None:
                continue
            if not is_jimmy_monkey(row):
                continue
            owner = row.get("owner") or "unknown"
            month = tx_date.strftime("%Y-%m")
            spend = abs(amount_sgd)
            monthly[month][owner] += spend
            monthly[month]["total"] += spend
            transactions.append(
                {
                    "date": tx_date,
                    "month": month,
                    "owner": owner,
                    "institution": row.get("institution", ""),
                    "amount": row.get("amount", ""),
                    "currency": row.get("currency", ""),
                    "amount_sgd": spend,
                    "description": row.get("description_raw", ""),
                    "source_file": row.get("source_file", ""),
                    "source_row": row.get("source_row", ""),
                }
            )

    owners = sorted({key for values in monthly.values() for key in values if key != "total"})
    months = sorted(monthly)
    rows = []
    for month in months:
        item = {"month": month}
        for owner in owners:
            item[f"{owner}_sgd"] = monthly[month].get(owner, Decimal("0"))
        item["total_sgd"] = monthly[month].get("total", Decimal("0"))
        rows.append(item)

    total = sum((row["total_sgd"] for row in rows), Decimal("0"))
    owner_totals = {owner: sum((row[f"{owner}_sgd"] for row in rows), Decimal("0")) for owner in owners}
    write_csv(EXPORTS_DIR / "jimmy_monkey_monthly_spend.csv", rows, ["month", *[f"{owner}_sgd" for owner in owners], "total_sgd"])
    write_csv(
        EXPORTS_DIR / "jimmy_monkey_transaction_detail.csv",
        transactions,
        ["date", "month", "owner", "institution", "amount", "currency", "amount_sgd", "description", "source_file", "source_row"],
    )

    payload = json.dumps(
        {
            "owners": owners,
            "rows": [{key: (float(value) if isinstance(value, Decimal) else value) for key, value in row.items()} for row in rows],
        }
    )
    latest = rows[-1] if rows else {"month": "", "total_sgd": Decimal("0")}
    owner_cards = "".join(
        f"""<div class="metric"><strong>S${money(value)}</strong><span>{html_escape(owner.title())}</span></div>"""
        for owner, value in owner_totals.items()
    )
    body = f"""
<div class="metric-row">
  <div class="metric"><strong>S${money(total)}</strong><span>Total Jimmy Monkey spend across both of you</span></div>
  {owner_cards}
  <div class="metric"><strong>{html_escape(latest['month'])}</strong><span>Latest month with matched spend: S${money(latest['total_sgd'])}</span></div>
</div>
<p class="muted">Net outflows only, converted to SGD using the local FX table. Matches are based on parsed merchant/description text containing Jimmy Monkey/JimmyMonkey. Date range follows the report window: {REPORT_START_DATE.isoformat()} to {REPORT_END_DATE.isoformat()}.</p>
<svg id="chart" viewBox="0 0 1100 520" role="img" aria-label="Jimmy Monkey monthly spend across both owners" style="width:100%;height:auto;background:#fff;border:1px solid var(--line);border-radius:6px"></svg>
<script>
const data = {payload};
const svg = document.getElementById('chart');
const W = 1100, H = 520, L = 70, R = 30, T = 36, B = 82;
const colors = {{samuel:'#116466', amy:'#c44536', unknown:'#667085'}};
const rows = data.rows;
const maxY = Math.max(1, ...rows.map(r => r.total_sgd));
const xBand = (W - L - R) / Math.max(1, rows.length);
const y = v => T + (1 - v / (maxY * 1.12)) * (H - T - B);
const el = (name, attrs, text) => {{
  const node = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [k,v] of Object.entries(attrs || {{}})) node.setAttribute(k, v);
  if (text !== undefined) node.textContent = text;
  svg.appendChild(node);
  return node;
}};
const fmt = v => 'S$' + Math.round(v).toLocaleString();
for (let i=0;i<=5;i++) {{
  const val = maxY * i / 5;
  const yy = y(val);
  el('line', {{x1:L, y1:yy, x2:W-R, y2:yy, stroke:'#d9e0e7'}});
  el('text', {{x:L-10, y:yy+4, 'text-anchor':'end', 'font-size':12, fill:'#5f6b7a'}}, fmt(val));
}}
rows.forEach((row, i) => {{
  let bottom = 0;
  const x = L + i * xBand + 2;
  const width = Math.max(2, xBand - 4);
  for (const owner of data.owners) {{
    const value = row[owner + '_sgd'] || 0;
    if (!value) continue;
    const yTop = y(bottom + value);
    const yBottom = y(bottom);
    const rect = el('rect', {{x, y:yTop, width, height:Math.max(1, yBottom-yTop), fill:colors[owner] || colors.unknown}});
    const title = document.createElementNS('http://www.w3.org/2000/svg', 'title');
    title.textContent = `${{row.month}} ${{owner}}: ${{fmt(value)}}`;
    rect.appendChild(title);
    bottom += value;
  }}
  if (i % Math.ceil(rows.length / 12 || 1) === 0) {{
    el('text', {{x:x+width/2, y:H-48, 'text-anchor':'end', 'font-size':11, fill:'#5f6b7a', transform:`rotate(-45 ${{x+width/2}} ${{H-48}})`}}, row.month);
  }}
}});
let lx = L, ly = H - 24;
for (const owner of data.owners) {{
  el('rect', {{x:lx, y:ly-12, width:14, height:14, fill:colors[owner] || colors.unknown}});
  el('text', {{x:lx+20, y:ly, 'font-size':13, fill:'#1d2733'}}, owner.charAt(0).toUpperCase() + owner.slice(1));
  lx += 110;
}}
el('text', {{x:L, y:24, 'font-size':16, fill:'#1d2733', 'font-weight':700}}, 'Jimmy Monkey Monthly Spend, SGD');
</script>
"""
    report = REPORTS_DIR / "jimmy_monkey_monthly_spend.html"
    write_html_report(report, "Jimmy Monkey Monthly Spend", body)
    return {"transactions": len(transactions), "months": len(rows), "total_sgd": str(total), "report": str(report)}


if __name__ == "__main__":
    print(run())
