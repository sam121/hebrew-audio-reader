from __future__ import annotations

import calendar
import csv
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import report_spending_by_category as spending
from common import EXPORTS_DIR, REPORTS_DIR, html_escape, write_csv, write_html_report


SOURCE_ROOT = Path("/Users/samueltaylor/Library/Mobile Documents/com~apple~CloudDocs/Transactions")
SALARY_DIR = SOURCE_ROOT / "Sam" / "Salary"
STRIPE_TAX_DIR = SOURCE_ROOT / "Sam" / "tax_singapore" / "stripe_tax"

START_DATE = "2024-04-01"
END_DATE = "2026-03-31"
START_QUARTER = "2024Q2"
END_QUARTER = "2026Q1"


def quarter_for_date(value: str) -> str:
    year = int(value[:4])
    month = int(value[5:7])
    return f"{year}Q{((month - 1) // 3) + 1}"


def money(value: Any) -> str:
    return f"S${Decimal(str(value)):,.0f}"


def parse_money(value: str) -> Decimal:
    return Decimal(value.replace(",", ""))


def pdf_text(path: Path) -> str:
    return subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True, errors="ignore")


def quarters() -> list[str]:
    result = []
    for year in range(2024, 2027):
        for quarter in range(1, 5):
            key = f"{year}Q{quarter}"
            if START_QUARTER <= key <= END_QUARTER:
                result.append(key)
    return result


def salary_income_by_quarter() -> dict[str, Decimal]:
    salary = defaultdict(Decimal)
    parsed_months: set[str] = set()
    salary_labels = {"BASIC PAY", "Basic salary", "LIFESTYLE", "EDUCATION STIPEND - NT"}
    bonus_labels = {"COMPANY PERFORMANCE BONUS", "GTM AWARD", "EQUITY CHOICE CASH", "SPOT BONUS", "SIGN-ON BONUS"}
    month_map = {month: index for index, month in enumerate(calendar.month_name) if month}

    for path in sorted(SALARY_DIR.glob("*.pdf")):
        text = pdf_text(path)
        period_match = re.search(r"Period\s*:\s*\.([^\n]+)", text)
        if not period_match:
            continue
        parts = period_match.group(1).strip().split()
        if len(parts) < 2 or parts[0] not in month_map:
            continue
        year = int(parts[-1])
        month = month_map[parts[0]]
        if not ((2024, 4) <= (year, month) <= (2026, 3)):
            continue
        month_key = f"{year}-{month:02d}"
        quarter = f"{year}Q{((month - 1) // 3) + 1}"
        parsed_months.add(month_key)

        labels = sorted(salary_labels | bonus_labels | {"MISC DEDUCTION"}, key=len, reverse=True)
        for line in text.splitlines():
            if not re.search(r"\d[\d,]*\.\d{2}[+-]", line):
                continue
            for label in labels:
                if label not in line:
                    continue
                amount_match = re.search(r"(\d[\d,]*\.\d{2})([+-])", line.split(label, 1)[1])
                if not amount_match:
                    continue
                value = parse_money(amount_match.group(1))
                if amount_match.group(2) == "-":
                    value *= Decimal("-1")
                salary[quarter] += value

    # Some payslip PDFs are missing, so fall back to the bank salary export for those months.
    salary_path = EXPORTS_DIR / "salary_payments.csv"
    if salary_path.exists():
        with salary_path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if not (START_DATE <= row.get("date", "") <= END_DATE):
                    continue
                if "STRIPE PAYMENTS SINGAPORE" not in row.get("description", ""):
                    continue
                if row["date"][:7] in parsed_months:
                    continue
                salary[quarter_for_date(row["date"])] += Decimal(row["amount_sgd"])
    return salary


def amy_income_by_quarter() -> dict[str, Decimal]:
    amy = defaultdict(Decimal)
    salary_path = EXPORTS_DIR / "salary_payments.csv"
    if not salary_path.exists():
        return amy
    with salary_path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            if not (START_DATE <= row.get("date", "") <= END_DATE):
                continue
            if "DOVER COURT INTERNATIONAL SCHOOL" in row.get("description", ""):
                amy[quarter_for_date(row["date"])] += Decimal(row["amount_sgd"])
    return amy


def stock_vesting_by_quarter() -> dict[str, Decimal]:
    stock = defaultdict(Decimal)
    appendix_files = [
        STRIPE_TAX_DIR / "2024 Appendix 8B - 110078_PAYRUNID-1089 (1).pdf",
        STRIPE_TAX_DIR / "2025 Appendix 8B - 110078_PAYRUNID-1519.pdf",
    ]
    for path in appendix_files:
        if not path.exists():
            continue
        text = pdf_text(path)
        for line in text.splitlines():
            if "STRIPE INC" not in line or not re.search(r"\d{2}-[A-Za-z]{3}-\d{4}", line):
                continue
            dates = re.findall(r"\d{2}-[A-Za-z]{3}-\d{4}", line)
            numbers = re.findall(r"\d[\d,]*\.\d+", line)
            if len(dates) < 2 or not numbers:
                continue
            vest_date = datetime.strptime(dates[1], "%d-%b-%Y").date().isoformat()
            if START_DATE <= vest_date <= END_DATE:
                stock[quarter_for_date(vest_date)] += parse_money(numbers[-1])

    # Estimate 2026 stock vesting from local Stripe release-cost rows until the tax form exists.
    stripe_balances = Path("data/processed/stripe_balances.csv")
    if stripe_balances.exists():
        rows = []
        with stripe_balances.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("account_id") == "CS-229409-01" and row.get("balance_type") == "released_common_shares_value":
                    rows.append(row)
        previous_usd: Decimal | None = None
        for row in sorted(rows, key=lambda item: (item["date"], Decimal(item["balance"]))):
            date = row["date"]
            source = row.get("source_row", "").lower()
            balance_usd = Decimal(row["balance"])
            balance_sgd = Decimal(row["balance_sgd"])
            fx_rate = balance_sgd / balance_usd if balance_usd else Decimal("0")
            if date < "2026-01-01":
                if "release cost basis" in source or "tender offer" in source:
                    previous_usd = balance_usd
                continue
            if date > END_DATE:
                continue
            if "release cost basis" in source:
                if previous_usd is not None and balance_usd > previous_usd:
                    stock[quarter_for_date(date)] += (balance_usd - previous_usd) * fx_rate
                previous_usd = balance_usd
            elif "tender offer" in source:
                previous_usd = balance_usd
    return stock


def spending_by_quarter() -> dict[str, Decimal]:
    totals = defaultdict(Decimal)
    for row in spending.transaction_rows():
        if START_DATE <= row["date"] <= END_DATE:
            totals[quarter_for_date(row["date"])] += Decimal(str(row["amount_sgd"]))
    return totals


def chart_svg(rows: list[dict[str, Any]]) -> str:
    width, height = 1120, 600
    left, right, top, bottom = 82, 44, 44, 78
    plot_w = width - left - right
    plot_h = height - top - bottom
    values = [Decimal(str(row["income_sgd"])) for row in rows] + [Decimal(str(row["spending_sgd"])) for row in rows]
    max_y = max(values) * Decimal("1.12")

    def x_pos(index: int) -> Decimal:
        if len(rows) == 1:
            return Decimal(left) + Decimal(plot_w) / 2
        return Decimal(left) + Decimal(index) * Decimal(plot_w) / Decimal(len(rows) - 1)

    def y_pos(value: Decimal) -> Decimal:
        return Decimal(top) + (max_y - value) / max_y * Decimal(plot_h)

    income_points = [(x_pos(i), y_pos(Decimal(str(row["income_sgd"])))) for i, row in enumerate(rows)]
    spending_points = [(x_pos(i), y_pos(Decimal(str(row["spending_sgd"])))) for i, row in enumerate(rows)]

    def points_attr(points: list[tuple[Decimal, Decimal]]) -> str:
        return " ".join(f"{float(x):.2f},{float(y):.2f}" for x, y in points)

    def lerp(point_a: tuple[Decimal, Decimal], point_b: tuple[Decimal, Decimal], ratio: Decimal) -> tuple[Decimal, Decimal]:
        return (point_a[0] + (point_b[0] - point_a[0]) * ratio, point_a[1] + (point_b[1] - point_a[1]) * ratio)

    area_parts = []
    for index in range(len(rows) - 1):
        net_a = Decimal(str(rows[index]["net_sgd"]))
        net_b = Decimal(str(rows[index + 1]["net_sgd"]))
        segments: list[tuple[Decimal, Decimal, Decimal, Decimal, Decimal]] = []
        if net_a == 0 or net_b == 0 or (net_a > 0) == (net_b > 0):
            segments.append((Decimal("0"), Decimal("1"), net_a, net_b, (net_a + net_b) / 2))
        else:
            cross = abs(net_a) / (abs(net_a) + abs(net_b))
            segments.append((Decimal("0"), cross, net_a, Decimal("0"), net_a / 2))
            segments.append((cross, Decimal("1"), Decimal("0"), net_b, net_b / 2))

        for start_ratio, end_ratio, _start_net, _end_net, segment_net in segments:
            income_start = lerp(income_points[index], income_points[index + 1], start_ratio)
            income_end = lerp(income_points[index], income_points[index + 1], end_ratio)
            spending_start = lerp(spending_points[index], spending_points[index + 1], start_ratio)
            spending_end = lerp(spending_points[index], spending_points[index + 1], end_ratio)
            polygon = [income_start, income_end, spending_end, spending_start]
            fill = "#d9eadf" if segment_net >= 0 else "#f6d6d2"
            area_parts.append(f'<polygon points="{points_attr(polygon)}" fill="{fill}" opacity="0.95"></polygon>')

    grid_parts = []
    for tick in range(0, 6):
        value = max_y * Decimal(tick) / Decimal(5)
        y = y_pos(value)
        label = f"S${value / Decimal(1000):,.0f}k"
        grid_parts.append(f'<line x1="{left}" y1="{float(y):.2f}" x2="{width-right}" y2="{float(y):.2f}" stroke="#d7dee8" />')
        grid_parts.append(
            f'<text x="{left-12}" y="{float(y)+4:.2f}" text-anchor="end" font-size="12" fill="#607086">{html_escape(label)}</text>'
        )

    label_parts = []
    for index, row in enumerate(rows):
        x = x_pos(index)
        label_parts.append(
            f'<text x="{float(x):.2f}" y="{height-38}" text-anchor="middle" font-size="13" fill="#405064">{html_escape(row["quarter"])}</text>'
        )

    point_parts = []
    for points, color in [(income_points, "#2563eb"), (spending_points, "#c2410c")]:
        for x, y in points:
            point_parts.append(f'<circle cx="{float(x):.2f}" cy="{float(y):.2f}" r="4.5" fill="{color}" stroke="#fff" stroke-width="2" />')

    income_line = f'<polyline points="{points_attr(income_points)}" fill="none" stroke="#2563eb" stroke-width="3.5" />'
    spending_line = f'<polyline points="{points_attr(spending_points)}" fill="none" stroke="#c2410c" stroke-width="3.5" />'
    return f"""
<svg viewBox="0 0 {width} {height}" role="img" aria-label="Quarterly income versus spending" class="chart">
  <rect x="0" y="0" width="{width}" height="{height}" fill="#ffffff" />
  {''.join(grid_parts)}
  {''.join(area_parts)}
  {income_line}
  {spending_line}
  {''.join(point_parts)}
  {''.join(label_parts)}
  <text x="{left}" y="28" font-size="18" font-weight="700" fill="#1f2937">Quarterly Income vs Spending</text>
  <text x="{width-right}" y="28" text-anchor="end" font-size="13" fill="#607086">SGD, pooled Samuel + Amy, 2024Q2-2026Q1</text>
  <g transform="translate({left}, {height-16})">
    <circle cx="0" cy="0" r="5" fill="#2563eb" /><text x="12" y="4" font-size="13" fill="#405064">Income</text>
    <circle cx="86" cy="0" r="5" fill="#c2410c" /><text x="98" y="4" font-size="13" fill="#405064">Spending</text>
    <rect x="190" y="-6" width="14" height="12" fill="#d9eadf" /><text x="212" y="4" font-size="13" fill="#405064">Net surplus</text>
    <rect x="310" y="-6" width="14" height="12" fill="#f6d6d2" /><text x="332" y="4" font-size="13" fill="#405064">Net deficit</text>
  </g>
</svg>
"""


def run() -> dict[str, Any]:
    salary = salary_income_by_quarter()
    amy = amy_income_by_quarter()
    stock = stock_vesting_by_quarter()
    spend = spending_by_quarter()

    rows = []
    for quarter in quarters():
        income = salary[quarter] + amy[quarter] + stock[quarter]
        spending_total = spend[quarter]
        rows.append(
            {
                "quarter": quarter,
                "income_sgd": income,
                "spending_sgd": spending_total,
                "net_sgd": income - spending_total,
            }
        )

    write_csv(EXPORTS_DIR / "quarterly_income_spending.csv", rows, ["quarter", "income_sgd", "spending_sgd", "net_sgd"])

    table_rows = "\n".join(
        f"<tr><td>{html_escape(row['quarter'])}</td><td>{money(row['income_sgd'])}</td><td>{money(row['spending_sgd'])}</td><td>{money(row['net_sgd'])}</td></tr>"
        for row in rows
    )
    body = f"""
<p class="warning">Income includes Samuel Stripe payroll, estimated/tax-form Stripe stock vesting income, and Amy Dover Court salary. Spending uses the cleaned spending report logic. 2026Q2 is excluded.</p>
<div class="metric-row">
  <div class="metric"><strong>{money(sum(row['income_sgd'] for row in rows))}</strong><span>Total income</span></div>
  <div class="metric"><strong>{money(sum(row['spending_sgd'] for row in rows))}</strong><span>Total spending</span></div>
  <div class="metric"><strong>{money(sum(row['net_sgd'] for row in rows))}</strong><span>Net surplus</span></div>
</div>
{chart_svg(rows)}
<h2>Quarterly Values</h2>
<table>
  <thead><tr><th>Quarter</th><th>Income</th><th>Spending</th><th>Net</th></tr></thead>
  <tbody>{table_rows}</tbody>
</table>
<style>
.chart{{width:100%;height:auto;border:1px solid var(--line);border-radius:6px;background:#fff;margin:18px 0}}
</style>
<script type="application/json" id="quarterly-data">{json.dumps([{k: float(v) if isinstance(v, Decimal) else v for k, v in row.items()} for row in rows])}</script>
"""
    write_html_report(REPORTS_DIR / "income_vs_spending_quarterly.html", "Quarterly Income vs Spending", body)
    return {"quarters": len(rows), "report": str(REPORTS_DIR / "income_vs_spending_quarterly.html")}


if __name__ == "__main__":
    print(run())
