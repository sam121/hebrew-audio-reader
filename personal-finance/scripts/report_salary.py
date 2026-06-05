from __future__ import annotations

import csv
import json
from collections import defaultdict
from decimal import Decimal
from typing import Any

from common import EXPORTS_DIR, PROCESSED_DIR, REPORTS_DIR, REPORT_END_DATE, REPORT_START_DATE, html_escape, html_table, parse_date, parse_decimal, write_csv, write_html_report


MONTHLY_COLUMNS = ["month", "salary_sgd", "payment_count", "source_institutions", "notes"]
DETAIL_COLUMNS = ["date", "institution", "account_id", "description", "amount", "currency", "amount_sgd", "source_file", "source_row"]


def read_transactions() -> list[dict[str, str]]:
    with (PROCESSED_DIR / "categorized_transactions.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def is_salary(row: dict[str, str]) -> bool:
    amount_sgd = parse_decimal(row.get("amount_sgd"))
    if amount_sgd is None or amount_sgd <= 0:
        return False
    text = " ".join([row.get("description_raw", ""), row.get("description_clean", ""), row.get("merchant", "")]).lower()
    if "stripe payments singapore" in text:
        return True
    if "giro salary" in text or "salary" in text:
        return True
    return False


def money(value: Any) -> str:
    return f"S${Decimal(str(value)):,.0f}"


def build_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    monthly: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "salary_sgd": Decimal("0"),
            "payment_count": 0,
            "institutions": set(),
        }
    )
    details: list[dict[str, Any]] = []
    for row in read_transactions():
        tx_date = parse_date(row.get("date"))
        amount_sgd = parse_decimal(row.get("amount_sgd"))
        if not tx_date or amount_sgd is None:
            continue
        if tx_date < REPORT_START_DATE or tx_date > REPORT_END_DATE:
            continue
        if not is_salary(row):
            continue
        month = tx_date.strftime("%Y-%m")
        monthly[month]["salary_sgd"] += amount_sgd
        monthly[month]["payment_count"] += 1
        monthly[month]["institutions"].add(row.get("institution", ""))
        details.append(
            {
                "date": tx_date.isoformat(),
                "institution": row.get("institution", ""),
                "account_id": row.get("account_id", ""),
                "description": row.get("description_raw", ""),
                "amount": row.get("amount", ""),
                "currency": row.get("currency", ""),
                "amount_sgd": amount_sgd,
                "source_file": row.get("source_file", ""),
                "source_row": row.get("source_row", ""),
            }
        )

    monthly_rows = [
        {
            "month": month,
            "salary_sgd": values["salary_sgd"],
            "payment_count": values["payment_count"],
            "source_institutions": ", ".join(sorted(item for item in values["institutions"] if item)),
            "notes": "",
        }
        for month, values in sorted(monthly.items())
    ]
    details.sort(key=lambda row: row["date"])
    return monthly_rows, details


def render_chart(monthly_rows: list[dict[str, Any]]) -> str:
    payload = json.dumps(
        [
            {
                "month": row["month"],
                "salary": float(row["salary_sgd"]),
                "count": int(row["payment_count"]),
            }
            for row in monthly_rows
        ]
    )
    return f"""
<svg id="salaryChart" viewBox="0 0 1180 520" role="img" aria-label="Salary by month" style="width:100%;height:auto;background:#fff;border:1px solid var(--line);border-radius:6px"></svg>
<script>
const rows = {payload};
const svg = document.getElementById('salaryChart');
const W = 1180, H = 520, L = 78, R = 28, T = 34, B = 72;
const maxY = Math.max(...rows.map(r => r.salary), 1);
const barW = (W - L - R) / Math.max(rows.length, 1);
function x(i) {{ return L + i * barW; }}
function y(v) {{ return H - B - (v / maxY) * (H - T - B); }}
function el(name, attrs) {{
  const node = document.createElementNS('http://www.w3.org/2000/svg', name);
  for (const [k, v] of Object.entries(attrs)) node.setAttribute(k, v);
  svg.appendChild(node);
  return node;
}}
el('rect', {{x:0,y:0,width:W,height:H,fill:'#fff'}});
for (let i = 0; i <= 4; i++) {{
  const val = maxY * i / 4;
  const yy = y(val);
  el('line', {{x1:L,y1:yy,x2:W-R,y2:yy,stroke:'#d9e0e7','stroke-width':1}});
  el('text', {{x:L-10,y:yy+4,'text-anchor':'end','font-size':12,fill:'#5f6b7a'}}).textContent = 'S$' + Math.round(val/1000) + 'k';
}}
rows.forEach((row, i) => {{
  const h = H - B - y(row.salary);
  const rect = el('rect', {{x:x(i)+2,y:y(row.salary),width:Math.max(barW-4,2),height:h,fill:'#116466'}});
  rect.appendChild(el('title', {{}})).textContent = row.month + ': S$' + row.salary.toLocaleString(undefined, {{maximumFractionDigits:0}});
  if (i % Math.ceil(rows.length / 12) === 0 || i === rows.length - 1) {{
    el('text', {{x:x(i)+barW/2,y:H-42,'text-anchor':'middle','font-size':11,fill:'#5f6b7a',transform:`rotate(-35 ${{x(i)+barW/2}} ${{H-42}})`}}).textContent = row.month;
  }}
}});
el('line', {{x1:L,y1:H-B,x2:W-R,y2:H-B,stroke:'#1d2733','stroke-width':1}});
el('line', {{x1:L,y1:T,x2:L,y2:H-B,stroke:'#1d2733','stroke-width':1}});
</script>
"""


def run() -> dict[str, Any]:
    monthly_rows, details = build_rows()
    write_csv(EXPORTS_DIR / "salary_by_month.csv", monthly_rows, MONTHLY_COLUMNS)
    write_csv(EXPORTS_DIR / "salary_payments.csv", details, DETAIL_COLUMNS)
    latest = monthly_rows[-1] if monthly_rows else {}
    average = sum((row["salary_sgd"] for row in monthly_rows), Decimal("0")) / Decimal(len(monthly_rows)) if monthly_rows else Decimal("0")
    body = f"""
<div class="metric-row">
  <div class="metric"><strong>{html_escape(latest.get('month', ''))}</strong><span>Latest salary month</span></div>
  <div class="metric"><strong>{money(latest.get('salary_sgd', 0))}</strong><span>Latest monthly salary</span></div>
  <div class="metric"><strong>{money(average)}</strong><span>Average over detected months</span></div>
  <div class="metric"><strong>{len(monthly_rows)}</strong><span>Detected salary months</span></div>
</div>
<p class="warning">Salary is detected from positive inflows containing salary wording, including Stripe Payments Singapore. Review salary_payments.csv if bonuses, reimbursements, or employer payments need separate treatment.</p>
{render_chart(monthly_rows)}
<h2>Monthly Salary</h2>
{html_table(monthly_rows, MONTHLY_COLUMNS)}
<h2>Salary Payments</h2>
{html_table(details, DETAIL_COLUMNS)}
"""
    write_html_report(REPORTS_DIR / "salary.html", "Salary By Month", body)
    return {
        "months": len(monthly_rows),
        "payments": len(details),
        "latest_month": latest.get("month", ""),
        "latest_salary_sgd": latest.get("salary_sgd", Decimal("0")),
        "report": str(REPORTS_DIR / "salary.html"),
    }


if __name__ == "__main__":
    print(run())
