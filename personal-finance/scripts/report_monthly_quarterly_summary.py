from __future__ import annotations

import csv
import json
from collections import defaultdict
from decimal import Decimal, InvalidOperation
from typing import Any

from common import EXPORTS_DIR, REPORTS_DIR, html_escape, write_html_report


REPORT_FILE = REPORTS_DIR / "monthly_quarterly_summary.html"
OWNERS = ("all", "samuel", "amy")


def dec(value: Any) -> Decimal:
    try:
        return Decimal(str(value or "0"))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def money(value: Any, digits: int = 0) -> str:
    return f"S${dec(value):,.{digits}f}"


def short_money(value: Any) -> str:
    amount = dec(value)
    sign = "-" if amount < 0 else ""
    amount = abs(amount)
    if amount >= Decimal("1000000"):
        return f"{sign}S${amount / Decimal('1000000'):.2f}m"
    if amount >= Decimal("1000"):
        return f"{sign}S${amount / Decimal('1000'):.0f}k"
    return f"{sign}S${amount:.0f}"


def pct(value: Decimal | None) -> str:
    if value is None:
        return ""
    return f"{value:.1f}%"


def read_rows(name: str) -> list[dict[str, str]]:
    path = EXPORTS_DIR / name
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def month_to_quarter(month: str) -> str:
    month_num = int(month[5:7])
    return f"{month[:4]}Q{((month_num - 1) // 3) + 1}"


def normalize_quarter(value: str | None) -> str:
    return (value or "").replace("-", "")


def quarter_sort_key(quarter: str) -> tuple[int, int]:
    quarter = normalize_quarter(quarter)
    return int(quarter[:4]), int(quarter[-1])


def owner_bucket(owner: str | None) -> str:
    owner = (owner or "").strip().lower()
    if owner in {"sam", "samuel"}:
        return "samuel"
    if owner == "amy":
        return "amy"
    return owner or "unknown"


def add_to_owner_map(target: dict[str, dict[str, Decimal]], key: str, owner: str, value: Decimal) -> None:
    target.setdefault(key, {known_owner: Decimal("0") for known_owner in OWNERS})
    if owner in target[key]:
        target[key][owner] += value
        target[key]["all"] += value


def build_monthly_series() -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    spending_by_month: dict[str, dict[str, Decimal]] = {}
    for row in read_rows("monthly_spending_candidates.csv"):
        add_to_owner_map(spending_by_month, row.get("month", ""), owner_bucket(row.get("owner")), dec(row.get("outflow_sgd")))

    income_by_month: dict[str, dict[str, Decimal]] = {}
    for row in read_rows("salary_payments.csv"):
        month = (row.get("date") or "")[:7]
        description = (row.get("description") or "").upper()
        owner = "amy" if "DOVER COURT" in description else "samuel"
        add_to_owner_map(income_by_month, month, owner, dec(row.get("amount_sgd")))

    net_worth_by_month: dict[str, dict[str, Decimal]] = {}
    for row in read_rows("net_worth_monthly_stacked_by_account.csv"):
        add_to_owner_map(net_worth_by_month, row.get("month", ""), owner_bucket(row.get("owner")), dec(row.get("balance_sgd")))

    category_by_month: dict[str, dict[str, dict[str, Decimal]]] = defaultdict(lambda: defaultdict(lambda: defaultdict(Decimal)))
    for row in read_rows("monthly_spending_by_category.csv"):
        month = row.get("month", "")
        owner = owner_bucket(row.get("owner"))
        category = row.get("category", "uncategorized")
        value = dec(row.get("outflow_sgd"))
        if owner in OWNERS:
            category_by_month[month][owner][category] += value
            category_by_month[month]["all"][category] += value

    months = sorted(set(spending_by_month) | set(income_by_month) | set(net_worth_by_month))
    monthly_rows: list[dict[str, Any]] = []
    for month in months:
        row: dict[str, Any] = {"period": month, "quarter": month_to_quarter(month)}
        for owner in OWNERS:
            row[f"spending_{owner}"] = float(spending_by_month.get(month, {}).get(owner, Decimal("0")))
            row[f"income_{owner}"] = float(income_by_month.get(month, {}).get(owner, Decimal("0")))
            row[f"net_worth_{owner}"] = float(net_worth_by_month.get(month, {}).get(owner, Decimal("0")))
        monthly_rows.append(row)

    category_rows: list[dict[str, Any]] = []
    for month in sorted(category_by_month):
        for owner in OWNERS:
            total = sum(category_by_month[month][owner].values(), Decimal("0"))
            for category, value in sorted(category_by_month[month][owner].items(), key=lambda item: item[1], reverse=True):
                category_rows.append(
                    {
                        "period": month,
                        "owner": owner,
                        "category": category,
                        "amount": float(value),
                        "share": float((value / total * Decimal("100")) if total else Decimal("0")),
                    }
                )

    account_rows: list[dict[str, Any]] = []
    latest_month = months[-1] if months else ""
    if latest_month:
        for row in read_rows("net_worth_monthly_stacked_by_account.csv"):
            if row.get("month") != latest_month:
                continue
            account_rows.append(
                {
                    "owner": owner_bucket(row.get("owner")),
                    "series": row.get("series", ""),
                    "account": row.get("account_name") or row.get("account_label") or row.get("account_id", ""),
                    "currency": row.get("currency", ""),
                    "amount": float(dec(row.get("balance_sgd"))),
                    "confidence": row.get("confidence_status", ""),
                }
            )
    account_rows.sort(key=lambda item: abs(item["amount"]), reverse=True)
    return monthly_rows, category_rows, account_rows


def build_quarterly_series(monthly_rows: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    quarter_income = {normalize_quarter(row.get("quarter")): row for row in read_rows("quarterly_income_spending.csv")}
    quarter_nw: dict[str, dict[str, float]] = {}
    for row in monthly_rows:
        quarter_nw[row["quarter"]] = row

    quarterly_rows: list[dict[str, Any]] = []
    for quarter in sorted(set(quarter_income) | set(quarter_nw), key=quarter_sort_key):
        income_row = quarter_income.get(quarter, {})
        nw_row = quarter_nw.get(quarter, {})
        quarterly_rows.append(
            {
                "period": quarter,
                "income": float(dec(income_row.get("income_sgd"))),
                "spending": float(dec(income_row.get("spending_sgd"))),
                "net": float(dec(income_row.get("net_sgd"))),
                "net_worth_all": float(nw_row.get("net_worth_all", 0)),
                "net_worth_samuel": float(nw_row.get("net_worth_samuel", 0)),
                "net_worth_amy": float(nw_row.get("net_worth_amy", 0)),
            }
        )

    group_rows: list[dict[str, Any]] = []
    group_totals: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(lambda: {owner: Decimal("0") for owner in OWNERS})
    for row in read_rows("quarterly_spending_by_group.csv"):
        quarter = normalize_quarter(row.get("quarter"))
        group = row.get("group", "")
        owner = owner_bucket(row.get("owner"))
        value = dec(row.get("outflow_sgd"))
        if owner in OWNERS:
            group_totals[(quarter, group)][owner] += value
            group_totals[(quarter, group)]["all"] += value
    for (quarter, group), values in sorted(group_totals.items()):
        for owner in OWNERS:
            group_rows.append({"period": quarter, "owner": owner, "group": group, "amount": float(values[owner])})
    return quarterly_rows, group_rows


def top_categories(category_rows: list[dict[str, Any]], owner: str, months_back: int = 12) -> list[dict[str, Any]]:
    periods = sorted({row["period"] for row in category_rows})
    period_set = set(periods[-months_back:])
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for row in category_rows:
        if row["owner"] == owner and row["period"] in period_set:
            totals[row["category"]] += dec(row["amount"])
    total = sum(totals.values(), Decimal("0"))
    out = []
    for category, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True)[:6]:
        out.append({"label": category.replace("_", " ").title(), "amount": float(amount), "share": float(amount / total * Decimal("100")) if total else 0})
    return out


def build_payload() -> dict[str, Any]:
    monthly_rows, category_rows, account_rows = build_monthly_series()
    quarterly_rows, group_rows = build_quarterly_series(monthly_rows)
    latest_month = monthly_rows[-1] if monthly_rows else {}
    previous_month = monthly_rows[-2] if len(monthly_rows) > 1 else {}
    latest_quarter = next((row for row in reversed(quarterly_rows) if row.get("income") or row.get("spending")), {})

    latest_nw = dec(latest_month.get("net_worth_all"))
    previous_nw = dec(previous_month.get("net_worth_all"))
    latest_spending = dec(latest_month.get("spending_all"))
    latest_income = dec(latest_month.get("income_all"))
    latest_quarter_income = dec(latest_quarter.get("income"))
    latest_quarter_spending = dec(latest_quarter.get("spending"))
    latest_quarter_net = dec(latest_quarter.get("net"))
    savings_rate = None
    if latest_quarter_income:
        savings_rate = latest_quarter_net / latest_quarter_income * Decimal("100")

    return {
        "generatedFrom": {
            "netWorth": "data/exports/net_worth_monthly_stacked_by_account.csv",
            "spending": "data/exports/monthly_spending_by_category.csv",
            "income": "data/exports/quarterly_income_spending.csv and salary_payments.csv",
        },
        "headline": {
            "latestMonth": latest_month.get("period", ""),
            "latestQuarter": latest_quarter.get("period", ""),
            "netWorth": float(latest_nw),
            "netWorthChange": float(latest_nw - previous_nw),
            "monthlySpending": float(latest_spending),
            "monthlyCashIncome": float(latest_income),
            "quarterIncome": float(latest_quarter_income),
            "quarterSpending": float(latest_quarter_spending),
            "quarterNet": float(latest_quarter_net),
            "quarterSavingsRate": float(savings_rate) if savings_rate is not None else None,
        },
        "monthly": monthly_rows,
        "quarterly": quarterly_rows,
        "monthlyCategories": category_rows,
        "quarterlyGroups": group_rows,
        "latestAccounts": account_rows[:18],
        "topCategories": {owner: top_categories(category_rows, owner) for owner in OWNERS},
    }


def build_report() -> str:
    payload = build_payload()
    data_json = json.dumps(payload, separators=(",", ":")).replace("</", "<\\/")
    headline = payload["headline"]
    return f"""
<style>
  :root {{
    --bg: #f4f7f8;
    --panel: #ffffff;
    --panel-soft: #f8fbfb;
    --ink-strong: #18222f;
    --ink: #263544;
    --muted: #667385;
    --line: #dbe4e8;
    --green: #176b5f;
    --green-2: #46906e;
    --blue: #355f96;
    --sky: #e8f1f6;
    --amber: #c98522;
    --red: #b94d45;
    --shadow: 0 10px 28px rgba(23, 48, 58, .08);
  }}
  body {{ background: var(--bg); }}
  header {{ display: none; }}
  main {{ max-width: none; padding: 0; }}
  .dashboard {{ min-height: 100vh; color: var(--ink); }}
  .hero {{
    padding: 28px clamp(18px, 3vw, 42px) 18px;
    background: linear-gradient(180deg, #ffffff 0%, #f6faf9 100%);
    border-bottom: 1px solid var(--line);
  }}
  .topbar {{ display: flex; justify-content: space-between; gap: 18px; align-items: flex-start; margin-bottom: 18px; }}
  .kicker {{ margin: 0 0 5px; color: var(--green); font-weight: 750; font-size: 13px; text-transform: uppercase; letter-spacing: .06em; }}
  .hero h1 {{ margin: 0; font-size: clamp(30px, 4vw, 52px); line-height: 1.02; color: var(--ink-strong); letter-spacing: 0; }}
  .hero-sub {{ max-width: 720px; margin: 10px 0 0; color: var(--muted); font-size: 17px; }}
  .asof {{ text-align: right; color: var(--muted); font-size: 13px; min-width: 200px; }}
  .asof strong {{ display: block; color: var(--ink-strong); font-size: 16px; margin-bottom: 2px; }}
  .hero-metrics {{ display: grid; grid-template-columns: repeat(4, minmax(190px, 1fr)); gap: 12px; }}
  .hero-card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 10px; padding: 16px; box-shadow: var(--shadow); }}
  .hero-card span {{ display: block; color: var(--muted); font-size: 13px; margin-bottom: 8px; }}
  .hero-card strong {{ display: block; color: var(--ink-strong); font-size: clamp(24px, 2.5vw, 34px); line-height: 1; letter-spacing: 0; }}
  .delta {{ display: inline-flex; align-items: center; gap: 5px; margin-top: 10px; border-radius: 999px; padding: 4px 8px; font-size: 12px; font-weight: 750; background: #eef6f2; color: var(--green); }}
  .delta.down {{ background: #fff0ee; color: var(--red); }}
  .controls {{ position: sticky; top: 0; z-index: 5; display: flex; justify-content: space-between; align-items: center; gap: 12px; padding: 12px clamp(18px, 3vw, 42px); background: rgba(244, 247, 248, .94); backdrop-filter: blur(10px); border-bottom: 1px solid var(--line); }}
  .segmented {{ display: flex; flex-wrap: wrap; gap: 6px; padding: 4px; background: #eaf1f2; border: 1px solid var(--line); border-radius: 10px; }}
  .segmented button {{ border: 0; border-radius: 7px; padding: 9px 13px; background: transparent; color: var(--muted); font-weight: 760; cursor: pointer; }}
  .segmented button.active {{ background: var(--panel); color: var(--green); box-shadow: 0 1px 4px rgba(23, 48, 58, .12); }}
  .content {{ padding: 20px clamp(18px, 3vw, 42px) 44px; }}
  .panel-grid {{ display: grid; grid-template-columns: minmax(0, 1.5fr) minmax(340px, .8fr); gap: 16px; align-items: start; }}
  .card {{ background: var(--panel); border: 1px solid var(--line); border-radius: 12px; box-shadow: var(--shadow); overflow: hidden; }}
  .card-head {{ display: flex; justify-content: space-between; align-items: flex-start; gap: 12px; padding: 16px 18px 6px; }}
  .card h2, .card h3 {{ margin: 0; color: var(--ink-strong); letter-spacing: 0; }}
  .card h2 {{ font-size: 20px; }}
  .card h3 {{ font-size: 16px; }}
  .hint {{ color: var(--muted); font-size: 13px; margin: 5px 0 0; }}
  .chart-wrap {{ padding: 6px 12px 14px; }}
  .chart {{ width: 100%; height: 330px; display: block; }}
  .chart.short {{ height: 260px; }}
  .axis {{ stroke: #d9e3e7; stroke-width: 1; }}
  .grid {{ stroke: #edf2f4; stroke-width: 1; }}
  .axis-text {{ fill: #748193; font-size: 11px; }}
  .line-net {{ fill: none; stroke: var(--green); stroke-width: 3; }}
  .area-net {{ fill: rgba(23, 107, 95, .12); }}
  .line-income {{ fill: none; stroke: var(--blue); stroke-width: 3; }}
  .line-spend {{ fill: none; stroke: var(--amber); stroke-width: 3; }}
  .bar-spend {{ fill: #5f9a7b; opacity: .9; }}
  .bar-positive {{ fill: #4f906a; }}
  .bar-negative {{ fill: #c65b50; }}
  .dot {{ fill: var(--panel); stroke: currentColor; stroke-width: 2; }}
  .chart-hit {{ cursor: pointer; }}
  .chart-hit:hover {{ opacity: .86; }}
  .selected-marker {{ stroke: #1d2733; stroke-width: 1.5; stroke-dasharray: 4 4; opacity: .7; pointer-events: none; }}
  .selected-dot {{ fill: var(--green); stroke: #ffffff; stroke-width: 3; }}
  .selected-bar {{ stroke: #1d2733; stroke-width: 2; }}
  .legend {{ display: flex; gap: 12px; align-items: center; flex-wrap: wrap; color: var(--muted); font-size: 12px; }}
  .legend i {{ width: 10px; height: 10px; border-radius: 999px; display: inline-block; margin-right: 4px; vertical-align: -1px; }}
  .insight-list {{ display: grid; gap: 10px; padding: 14px 18px 18px; }}
  .insight {{ border: 1px solid var(--line); border-radius: 10px; padding: 12px; background: var(--panel-soft); }}
  .insight small {{ display: block; color: var(--muted); font-size: 12px; margin-bottom: 5px; }}
  .insight strong {{ color: var(--ink-strong); font-size: 18px; }}
  .split {{ display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 16px; margin-top: 16px; }}
  .table-card {{ grid-column: 1 / -1; }}
  table {{ border: 0; background: transparent; }}
  th {{ background: #f1f6f6; position: static; }}
  td, th {{ border-bottom: 1px solid var(--line); padding: 10px 12px; }}
  td.num, th.num {{ text-align: right; }}
  tbody tr:hover {{ background: #f7faf9; }}
  tbody tr.selected {{ background: #eaf5f1; }}
  tbody tr.clickable {{ cursor: pointer; }}
  .link-strip {{ display: flex; flex-wrap: wrap; gap: 8px; margin: 0 0 16px; }}
  .link-strip a {{ text-decoration: none; border: 1px solid var(--line); border-radius: 9px; padding: 9px 11px; background: var(--panel); color: var(--green); font-weight: 750; box-shadow: 0 1px 2px rgba(23, 48, 58, .04); }}
  .source-note {{ margin-top: 18px; color: var(--muted); font-size: 12px; }}
  .tooltip {{
    position: fixed;
    z-index: 50;
    max-width: 260px;
    padding: 9px 10px;
    border-radius: 8px;
    background: rgba(24, 34, 47, .95);
    color: #fff;
    font-size: 12px;
    line-height: 1.35;
    white-space: pre-line;
    pointer-events: none;
    box-shadow: 0 10px 28px rgba(24, 34, 47, .22);
    opacity: 0;
    transform: translate(-50%, calc(-100% - 12px));
    transition: opacity .12s ease;
  }}
  .tooltip.visible {{ opacity: 1; }}
  @media (max-width: 1100px) {{
    .hero-metrics {{ grid-template-columns: repeat(2, minmax(180px, 1fr)); }}
    .panel-grid {{ grid-template-columns: 1fr; }}
  }}
  @media (max-width: 720px) {{
    .topbar, .controls {{ flex-direction: column; align-items: stretch; }}
    .asof {{ text-align: left; }}
    .hero-metrics, .split {{ grid-template-columns: 1fr; }}
    .chart {{ height: 270px; }}
  }}
</style>
<div class="dashboard">
  <section class="hero">
    <div class="topbar">
      <div>
        <p class="kicker">Household finance dashboard</p>
        <h1>Monthly and quarterly money picture</h1>
        <p class="hero-sub">A cleaner front door for spending, net worth, and income versus spending across Samuel and Amy.</p>
      </div>
      <div class="asof">
        <strong>Through {html_escape(headline.get("latestMonth", ""))}</strong>
        Local static report, refreshed from exports
      </div>
    </div>
    <div class="hero-metrics">
      <div class="hero-card"><span>Household net worth</span><strong>{html_escape(short_money(headline["netWorth"]))}</strong><b id="nwDelta" class="delta">...</b></div>
      <div class="hero-card"><span>Latest month spending</span><strong>{html_escape(short_money(headline["monthlySpending"]))}</strong><b class="delta">Current rules</b></div>
      <div class="hero-card"><span>Latest month cash income</span><strong>{html_escape(short_money(headline["monthlyCashIncome"]))}</strong><b class="delta">Detected deposits</b></div>
      <div class="hero-card"><span>{html_escape(headline.get("latestQuarter", ""))} income less spending</span><strong>{html_escape(short_money(headline["quarterNet"]))}</strong><b id="savingRate" class="delta">...</b></div>
    </div>
  </section>

  <section class="controls">
    <div class="segmented" aria-label="View">
      <button class="active" data-period="monthly">Monthly</button>
      <button data-period="quarterly">Quarterly</button>
    </div>
    <div class="segmented" aria-label="Owner">
      <button class="active" data-owner="all">Household</button>
      <button data-owner="samuel">Samuel</button>
      <button data-owner="amy">Amy</button>
    </div>
  </section>

  <main class="content">
    <div class="link-strip">
      <a href="spending_by_category.html">Explore spending detail</a>
      <a href="net_worth_stacked.html">Explore net worth detail</a>
      <a href="income_vs_spending_quarterly.html">Income vs spending detail</a>
      <a href="custom_spend_buckets.html">Focused spend buckets</a>
      <a href="net_worth_sankey.html">Net worth bridge</a>
    </div>

    <section class="panel-grid">
      <div class="card">
        <div class="card-head">
          <div>
            <h2 id="primaryTitle">Net worth over time</h2>
            <p class="hint" id="primaryHint">End-of-month total by selected owner.</p>
          </div>
          <div class="legend" id="primaryLegend"></div>
        </div>
        <div class="chart-wrap"><svg id="primaryChart" class="chart"></svg></div>
      </div>
      <aside class="card">
        <div class="card-head"><div><h2>At a glance</h2><p class="hint" id="glanceHint">Selected owner and period.</p></div></div>
        <div class="insight-list" id="insights"></div>
      </aside>
    </section>

    <section class="split">
      <div class="card">
        <div class="card-head"><div><h2 id="spendingTitle">Spending trend</h2><p class="hint">Known transfers and investments are excluded.</p></div></div>
        <div class="chart-wrap"><svg id="spendingChart" class="chart short"></svg></div>
      </div>
      <div class="card">
        <div class="card-head"><div><h2 id="mixTitle">What made up spending</h2><p class="hint">Largest groups in the selected view.</p></div></div>
        <div class="chart-wrap"><svg id="mixChart" class="chart short"></svg></div>
      </div>
      <div class="card table-card">
        <div class="card-head"><div><h2 id="tableTitle">Recent detail</h2><p class="hint">Rounded SGD amounts, sourced from local exports.</p></div></div>
        <div id="detailTable"></div>
      </div>
    </section>

    <p class="source-note">
      Sources: {html_escape(payload["generatedFrom"]["netWorth"])}, {html_escape(payload["generatedFrom"]["spending"])}, {html_escape(payload["generatedFrom"]["income"])}.
      Quarterly income uses the fuller income model; monthly income is detected cash deposits only.
    </p>
  </main>
</div>
<script id="dashboardData" type="application/json">{data_json}</script>
<script>
(() => {{
  const rawData = document.getElementById('dashboardData').textContent
    .replaceAll('&quot;', '"')
    .replaceAll('&amp;', '&')
    .replaceAll('&lt;', '<')
    .replaceAll('&gt;', '>');
  const data = JSON.parse(rawData);
  const state = {{ period: 'monthly', owner: 'all', selectedPeriod: data.headline.latestMonth }};
  const ownerLabel = {{ all: 'Household', samuel: 'Samuel', amy: 'Amy' }};
  const fmt = new Intl.NumberFormat('en-SG', {{ style: 'currency', currency: 'SGD', maximumFractionDigits: 0 }});
  const tooltip = document.createElement('div');
  tooltip.className = 'tooltip';
  document.body.appendChild(tooltip);
  const shortFmt = value => {{
    const sign = value < 0 ? '-' : '';
    const amount = Math.abs(value || 0);
    if (amount >= 1_000_000) return `${{sign}}S$${{(amount / 1_000_000).toFixed(2)}}m`;
    if (amount >= 1_000) return `${{sign}}S$${{Math.round(amount / 1_000)}}k`;
    return `${{sign}}S$${{Math.round(amount)}}`;
  }};
  const clean = value => String(value || '').replaceAll('_', ' ').replace(/\\b\\w/g, s => s.toUpperCase());
  const rowsForState = () => state.period === 'monthly' ? data.monthly : data.quarterly;
  const visibleRowsForState = () => state.period === 'quarterly' ? rowsForState().filter(row => row.income || row.spending || row.net_worth_all) : rowsForState();
  const valueFor = (row, metric) => {{
    if (state.period === 'quarterly' && metric === 'income') return row.income || 0;
    if (state.period === 'quarterly' && metric === 'net') return row.net || 0;
    return row[`${{metric}}_${{state.owner}}`] || 0;
  }};
  const ensureSelected = () => {{
    const rows = visibleRowsForState();
    if (!rows.length) return null;
    let row = rows.find(item => item.period === state.selectedPeriod);
    if (!row) {{
      row = rows[rows.length - 1];
      state.selectedPeriod = row.period;
    }}
    return row;
  }};
  const selectPeriod = period => {{
    state.selectedPeriod = period;
    render();
  }};
  const showTooltip = (event, lines) => {{
    tooltip.textContent = lines.filter(Boolean).join('\\n');
    tooltip.style.left = `${{event.clientX}}px`;
    tooltip.style.top = `${{event.clientY}}px`;
    tooltip.classList.add('visible');
  }};
  const moveTooltip = event => {{
    tooltip.style.left = `${{event.clientX}}px`;
    tooltip.style.top = `${{event.clientY}}px`;
  }};
  const hideTooltip = () => tooltip.classList.remove('visible');
  const chartBox = svg => {{
    const width = Math.max(640, svg.clientWidth || 900);
    const height = svg.classList.contains('short') ? 260 : 330;
    svg.setAttribute('viewBox', `0 0 ${{width}} ${{height}}`);
    svg.innerHTML = '';
    return {{ width, height, left: 62, right: 20, top: 22, bottom: 42 }};
  }};
  const scaled = (values, box, includeZero = true) => {{
    let min = Math.min(...values, includeZero ? 0 : Infinity);
    let max = Math.max(...values, includeZero ? 0 : -Infinity);
    if (!Number.isFinite(min)) min = 0;
    if (!Number.isFinite(max)) max = 1;
    if (min === max) max = min + 1;
    const plotW = box.width - box.left - box.right;
    const plotH = box.height - box.top - box.bottom;
    return {{
      min, max, plotW, plotH,
      x: i => box.left + (values.length <= 1 ? plotW / 2 : plotW * i / (values.length - 1)),
      y: v => box.top + ((max - v) / (max - min)) * plotH,
      barX: i => box.left + plotW * i / values.length,
      barW: Math.max(4, plotW / Math.max(values.length, 1) * .62)
    }};
  }};
  const el = (svg, name, attrs = {{}}, text = '') => {{
    const node = document.createElementNS('http://www.w3.org/2000/svg', name);
    for (const [key, value] of Object.entries(attrs)) node.setAttribute(key, value);
    if (text) node.textContent = text;
    svg.appendChild(node);
    return node;
  }};
  const drawAxes = (svg, box, scale, labels) => {{
    for (let i = 0; i <= 3; i++) {{
      const y = box.top + scale.plotH * i / 3;
      el(svg, 'line', {{ x1: box.left, y1: y, x2: box.width - box.right, y2: y, class: 'grid' }});
      const value = scale.max - (scale.max - scale.min) * i / 3;
      el(svg, 'text', {{ x: 10, y: y + 4, class: 'axis-text' }}, shortFmt(value));
    }}
    const tickCount = Math.min(7, labels.length);
    const step = Math.max(1, Math.floor((labels.length - 1) / Math.max(tickCount - 1, 1)));
    const ticks = new Set();
    for (let i = 0; i < labels.length; i += step) ticks.add(i);
    ticks.add(labels.length - 1);
    [...ticks].sort((a, b) => a - b).forEach(i => {{
      el(svg, 'text', {{ x: scale.x(i), y: box.height - 14, class: 'axis-text', 'text-anchor': 'middle' }}, labels[i]);
    }});
  }};
  const drawLineChart = (svgId, series, options = {{}}) => {{
    const svg = document.getElementById(svgId);
    const box = chartBox(svg);
    const labels = series.map(d => d.period);
    const values = series.map(d => d.value || 0);
    const scale = scaled(values, box, options.includeZero !== false);
    drawAxes(svg, box, scale, labels);
    const zeroY = scale.y(0);
    const points = values.map((v, i) => `${{scale.x(i).toFixed(1)}},${{scale.y(v).toFixed(1)}}`).join(' ');
    if (options.area !== false) {{
      el(svg, 'polygon', {{ points: `${{box.left}},${{zeroY}} ${{points}} ${{box.width - box.right}},${{zeroY}}`, class: 'area-net' }});
    }}
    const selectedIndex = labels.indexOf(state.selectedPeriod);
    if (selectedIndex >= 0) {{
      const x = scale.x(selectedIndex);
      el(svg, 'line', {{ x1: x, y1: box.top, x2: x, y2: box.height - box.bottom, class: 'selected-marker' }});
    }}
    el(svg, 'polyline', {{ points, class: options.lineClass || 'line-net' }});
    values.forEach((v, i) => {{
      const dot = el(svg, 'circle', {{ cx: scale.x(i), cy: scale.y(v), r: labels[i] === state.selectedPeriod ? 5 : 3, class: labels[i] === state.selectedPeriod ? 'selected-dot chart-hit' : 'dot chart-hit', style: `color:${{options.color || '#176b5f'}}` }});
      const tip = [`${{labels[i]}}`, `${{options.tooltipLabel || 'Value'}}: ${{fmt.format(v)}}`, 'Click to select'];
      dot.addEventListener('mouseenter', event => showTooltip(event, tip));
      dot.addEventListener('mousemove', moveTooltip);
      dot.addEventListener('mouseleave', hideTooltip);
      dot.addEventListener('click', () => selectPeriod(labels[i]));
      const hit = el(svg, 'circle', {{ cx: scale.x(i), cy: scale.y(v), r: 10, fill: 'transparent', class: 'chart-hit' }});
      hit.addEventListener('mouseenter', event => showTooltip(event, tip));
      hit.addEventListener('mousemove', moveTooltip);
      hit.addEventListener('mouseleave', hideTooltip);
      hit.addEventListener('click', () => selectPeriod(labels[i]));
    }});
  }};
  const drawBarChart = (svgId, series, options = {{}}) => {{
    const svg = document.getElementById(svgId);
    const box = chartBox(svg);
    const labels = series.map(d => d.period || d.label);
    const values = series.map(d => d.value || d.amount || 0);
    const scale = scaled(values, box, true);
    drawAxes(svg, box, scale, labels);
    const zeroY = scale.y(0);
    values.forEach((v, i) => {{
      const h = Math.abs(zeroY - scale.y(v));
      const rect = el(svg, 'rect', {{
        x: scale.barX(i) + (scale.plotW / values.length - scale.barW) / 2,
        y: Math.min(zeroY, scale.y(v)),
        width: scale.barW,
        height: Math.max(1, h),
        rx: 3,
        class: `${{v < 0 ? 'bar-negative' : (options.positiveNegative ? 'bar-positive' : 'bar-spend')}} chart-hit ${{labels[i] === state.selectedPeriod ? 'selected-bar' : ''}}`
      }});
      const tip = [`${{labels[i]}}`, `${{options.tooltipLabel || 'Amount'}}: ${{fmt.format(v)}}`, 'Click to select'];
      rect.addEventListener('mouseenter', event => showTooltip(event, tip));
      rect.addEventListener('mousemove', moveTooltip);
      rect.addEventListener('mouseleave', hideTooltip);
      rect.addEventListener('click', () => selectPeriod(labels[i]));
    }});
  }};
  const drawHorizontalBars = (svgId, rows) => {{
    const svg = document.getElementById(svgId);
    const box = chartBox(svg);
    const max = Math.max(...rows.map(r => r.amount), 1);
    const rowH = Math.min(34, (box.height - 34) / Math.max(rows.length, 1));
    rows.forEach((row, i) => {{
      const y = 22 + i * rowH;
      const w = (box.width - 210) * row.amount / max;
      el(svg, 'text', {{ x: 14, y: y + 17, class: 'axis-text' }}, row.label);
      const rect = el(svg, 'rect', {{ x: 150, y: y + 4, width: Math.max(2, w), height: 18, rx: 5, fill: i === 0 ? '#176b5f' : '#6c8fb9', class: 'chart-hit' }});
      rect.addEventListener('mouseenter', event => showTooltip(event, [row.label, fmt.format(row.amount), row.share ? `${{row.share.toFixed(1)}}% of selected spending` : '']));
      rect.addEventListener('mousemove', moveTooltip);
      rect.addEventListener('mouseleave', hideTooltip);
      el(svg, 'text', {{ x: 158 + w, y: y + 18, class: 'axis-text' }}, shortFmt(row.amount));
    }});
  }};
  const renderInsights = () => {{
    const rows = rowsForState();
    const selected = ensureSelected() || {{}};
    const selectedIndex = rows.findIndex(row => row.period === selected.period);
    const previous = selectedIndex > 0 ? rows[selectedIndex - 1] : {{}};
    const nw = valueFor(selected, 'net_worth');
    const priorNw = valueFor(previous, 'net_worth');
    const periodSpendingGroups = state.period === 'quarterly'
      ? data.quarterlyGroups.filter(row => row.period === selected.period && row.owner === state.owner)
      : [];
    const ownerQuarterSpend = periodSpendingGroups.reduce((sum, row) => sum + row.amount, 0);
    const spend = state.period === 'quarterly' ? (state.owner === 'all' ? (selected.spending || 0) : ownerQuarterSpend) : valueFor(selected, 'spending');
    const income = state.period === 'quarterly' ? (selected.income || 0) : valueFor(selected, 'income');
    const retained = income - spend;
    document.getElementById('glanceHint').textContent = `${{ownerLabel[state.owner]}} · selected ${{state.period === 'monthly' ? 'month' : 'quarter'}}`;
    document.getElementById('insights').innerHTML = `
      <div class="insight"><small>${{selected.period || ''}} net worth</small><strong>${{fmt.format(nw)}}</strong></div>
      <div class="insight"><small>Change from prior period</small><strong>${{fmt.format(nw - priorNw)}}</strong></div>
      <div class="insight"><small>${{state.period === 'monthly' ? 'Detected income less spending' : (state.owner === 'all' ? 'Income less spending' : 'Household income less selected spending')}}</small><strong>${{fmt.format(retained)}}</strong></div>
      <div class="insight"><small>Spending in period</small><strong>${{fmt.format(spend)}}</strong></div>
    `;
  }};
  const selectedMixRows = () => {{
    const selected = ensureSelected() || {{}};
    if (state.period === 'monthly') {{
      return data.monthlyCategories
        .filter(row => row.period === selected.period && row.owner === state.owner)
        .sort((a, b) => b.amount - a.amount)
        .slice(0, 8)
        .map(row => ({{ label: clean(row.category), amount: row.amount, share: row.share }}));
    }}
    return data.quarterlyGroups
      .filter(row => row.period === selected.period && row.owner === state.owner)
      .sort((a, b) => b.amount - a.amount)
      .slice(0, 8)
      .map(row => ({{ label: row.group, amount: row.amount }}));
  }};
  const renderTable = () => {{
    const selected = ensureSelected() || {{}};
    if (state.period === 'monthly') {{
      const rows = data.monthly.slice(-12).reverse();
      document.getElementById('tableTitle').textContent = `Monthly detail · ${{selected.period || ''}}`;
      document.getElementById('detailTable').innerHTML = `<table><thead><tr><th>Month</th><th class="num">Income</th><th class="num">Spending</th><th class="num">Net worth</th><th class="num">Change</th></tr></thead><tbody>${{rows.map((row, index) => {{
        const next = rows[index + 1] || {{}};
        const nw = valueFor(row, 'net_worth');
        const prior = valueFor(next, 'net_worth');
        return `<tr class="clickable ${{row.period === state.selectedPeriod ? 'selected' : ''}}" data-select-period="${{row.period}}"><td>${{row.period}}</td><td class="num">${{fmt.format(valueFor(row, 'income'))}}</td><td class="num">${{fmt.format(valueFor(row, 'spending'))}}</td><td class="num">${{fmt.format(nw)}}</td><td class="num">${{fmt.format(nw - prior)}}</td></tr>`;
      }}).join('')}}</tbody></table>`;
    }} else {{
      const rows = data.quarterly.filter(r => r.income || r.spending).slice().reverse();
      document.getElementById('tableTitle').textContent = `Quarterly detail · ${{selected.period || ''}}`;
      document.getElementById('detailTable').innerHTML = `<table><thead><tr><th>Quarter</th><th class="num">Income</th><th class="num">Spending</th><th class="num">Net</th><th class="num">End net worth</th></tr></thead><tbody>${{rows.map(row => `<tr class="clickable ${{row.period === state.selectedPeriod ? 'selected' : ''}}" data-select-period="${{row.period}}"><td>${{row.period}}</td><td class="num">${{fmt.format(row.income)}}</td><td class="num">${{fmt.format(row.spending)}}</td><td class="num">${{fmt.format(row.net)}}</td><td class="num">${{fmt.format(valueFor(row, 'net_worth'))}}</td></tr>`).join('')}}</tbody></table>`;
    }}
    document.querySelectorAll('[data-select-period]').forEach(row => row.addEventListener('click', () => selectPeriod(row.dataset.selectPeriod)));
  }};
  const render = () => {{
    ensureSelected();
    document.querySelectorAll('[data-period]').forEach(btn => btn.classList.toggle('active', btn.dataset.period === state.period));
    document.querySelectorAll('[data-owner]').forEach(btn => btn.classList.toggle('active', btn.dataset.owner === state.owner));
    const rows = visibleRowsForState();
    const nwSeries = rows.map(row => ({{ period: row.period, value: valueFor(row, 'net_worth') }}));
    document.getElementById('primaryTitle').textContent = state.period === 'monthly' ? 'Net worth over time' : 'Quarter-end net worth';
    document.getElementById('primaryHint').textContent = `${{ownerLabel[state.owner]}} total, shown in SGD. Click a point to inspect that period.`;
    document.getElementById('primaryLegend').innerHTML = '<span><i style="background:#176b5f"></i>Net worth</span><span>Click points/bars to select</span>';
    drawLineChart('primaryChart', nwSeries, {{ includeZero: false, tooltipLabel: 'Net worth' }});
    if (state.period === 'monthly') {{
      document.getElementById('spendingTitle').textContent = 'Monthly spending';
      drawBarChart('spendingChart', rows.map(row => ({{ period: row.period, value: valueFor(row, 'spending') }})), {{ tooltipLabel: 'Spending' }});
      document.getElementById('mixTitle').textContent = `Spending mix · ${{state.selectedPeriod}}`;
      drawHorizontalBars('mixChart', selectedMixRows());
    }} else {{
      document.getElementById('spendingTitle').textContent = 'Income less spending';
      drawBarChart('spendingChart', rows.filter(row => row.income || row.spending).map(row => ({{ period: row.period, value: row.net }})), {{ positiveNegative: true, tooltipLabel: 'Income less spending' }});
      document.getElementById('mixTitle').textContent = `Spending groups · ${{state.selectedPeriod}}`;
      drawHorizontalBars('mixChart', selectedMixRows());
    }}
    renderInsights();
    renderTable();
  }};
  document.querySelectorAll('[data-period]').forEach(btn => btn.addEventListener('click', () => {{
    state.period = btn.dataset.period;
    state.selectedPeriod = state.period === 'monthly' ? data.headline.latestMonth : data.headline.latestQuarter;
    render();
  }}));
  document.querySelectorAll('[data-owner]').forEach(btn => btn.addEventListener('click', () => {{ state.owner = btn.dataset.owner; render(); }}));
  const nwDelta = data.headline.netWorthChange || 0;
  const nwNode = document.getElementById('nwDelta');
  nwNode.textContent = `${{nwDelta >= 0 ? '+' : ''}}${{shortFmt(nwDelta)}} vs prior month`;
  nwNode.classList.toggle('down', nwDelta < 0);
  const rate = data.headline.quarterSavingsRate;
  const savingNode = document.getElementById('savingRate');
  savingNode.textContent = Number.isFinite(rate) ? `${{rate.toFixed(1)}}% retained` : 'Quarterly view';
  savingNode.classList.toggle('down', (data.headline.quarterNet || 0) < 0);
  render();
  window.addEventListener('resize', () => render());
}})();
</script>
"""


def run() -> dict[str, str]:
    body = build_report()
    write_html_report(REPORT_FILE, "Monthly and Quarterly Summary", body)
    return {"report": str(REPORT_FILE)}


if __name__ == "__main__":
    print(run())
