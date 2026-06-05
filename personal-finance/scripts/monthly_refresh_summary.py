from __future__ import annotations

import csv
from collections import defaultdict
from datetime import datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from common import EXPORTS_DIR, REPORTS_DIR, REPORT_END_DATE, html_escape, write_html_report


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def dec(value: str | None) -> Decimal:
    if not value:
        return Decimal("0")
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def money(value: Decimal | str | int | float, currency: str = "SGD") -> str:
    amount = dec(str(value))
    prefix = "S$" if currency == "SGD" else f"{currency} "
    return f"{prefix}{amount:,.0f}"


def pct(value: Decimal) -> str:
    return f"{value:.1f}%"


def month_key_sort(month: str) -> tuple[int, int]:
    year, mon = month.split("-")
    return int(year), int(mon)


def previous_month(months: list[str], month: str, offset: int) -> str | None:
    if month not in months:
        return None
    idx = months.index(month) - offset
    if idx < 0:
        return None
    return months[idx]


def metric(label: str, value: str, detail: str = "") -> str:
    return (
        "<div class=\"metric\">"
        f"<strong>{html_escape(value)}</strong>"
        f"<span>{html_escape(label)}</span>"
        f"<small>{html_escape(detail)}</small>"
        "</div>"
    )


def html_table(rows: list[dict[str, Any]], columns: list[str], limit: int = 25) -> str:
    if not rows:
        return "<p class=\"muted\">No rows.</p>"
    head = "".join(f"<th>{html_escape(col)}</th>" for col in columns)
    body = []
    for row in rows[:limit]:
        body.append("<tr>" + "".join(f"<td>{html_escape(row.get(col, ''))}</td>" for col in columns) + "</tr>")
    more = f"<p class=\"muted\">Showing {limit} of {len(rows)} rows.</p>" if len(rows) > limit else ""
    return f"{more}<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def net_worth_summary() -> tuple[str, list[dict[str, Any]]]:
    rows = read_csv(EXPORTS_DIR / "net_worth_monthly_stacked.csv")
    if not rows:
        return "<p class=\"warning\">No net worth data available.</p>", []
    months = sorted([row["month"] for row in rows], key=month_key_sort)
    by_month = {row["month"]: row for row in rows}
    latest_month = months[-1]
    latest = by_month[latest_month]
    latest_total = dec(latest.get("Total"))

    cards = [metric("latest net worth", money(latest_total), latest_month)]
    comparisons = [("1 month", 1), ("quarter", 3), ("year", 12)]
    changes: list[dict[str, Any]] = []
    for label, offset in comparisons:
        prior_month = previous_month(months, latest_month, offset)
        if not prior_month:
            continue
        prior_total = dec(by_month[prior_month].get("Total"))
        delta = latest_total - prior_total
        delta_pct = delta / prior_total * Decimal("100") if prior_total else Decimal("0")
        cards.append(metric(f"net worth change, {label}", money(delta), f"{prior_month} to {latest_month}, {pct(delta_pct)}"))
        changes.append(
            {
                "period": label,
                "from": prior_month,
                "to": latest_month,
                "change_sgd": money(delta),
                "change_pct": pct(delta_pct),
            }
        )

    institution_rows = []
    for key, value in latest.items():
        if key in {"month", "Total"}:
            continue
        amount = dec(value)
        if amount:
            institution_rows.append({"institution": key, "value_sgd": money(amount), "share": pct(amount / latest_total * Decimal("100")) if latest_total else "0.0%"})
    institution_rows.sort(key=lambda row: dec(row["value_sgd"].replace("S$", "")), reverse=True)

    body = "<div class=\"metric-row\">" + "".join(cards) + "</div>"
    body += "<h2>Net Worth By Platform</h2>" + html_table(institution_rows, ["institution", "value_sgd", "share"], limit=20)
    return body, changes


def spending_summary() -> str:
    rows = read_csv(EXPORTS_DIR / "monthly_spending_by_category.csv")
    if not rows:
        return "<p class=\"warning\">No spending data available.</p>"
    months = sorted({row["month"] for row in rows}, key=month_key_sort)
    latest_month = months[-1]

    def period_months(offset: int) -> list[str]:
        idx = months.index(latest_month)
        return months[max(0, idx - offset + 1) : idx + 1]

    periods = [("last month", period_months(1)), ("last quarter", period_months(3)), ("last year", period_months(12))]
    body = ""
    for label, period in periods:
        totals: defaultdict[str, Decimal] = defaultdict(Decimal)
        counts: defaultdict[str, int] = defaultdict(int)
        for row in rows:
            if row["month"] not in period:
                continue
            totals[row["category"]] += dec(row.get("outflow_sgd"))
            counts[row["category"]] += int(dec(row.get("transaction_count")))
        total = sum(totals.values(), Decimal("0"))
        ranked = [
            {
                "category": category,
                "outflow_sgd": money(amount),
                "share": pct(amount / total * Decimal("100")) if total else "0.0%",
                "transactions": counts[category],
            }
            for category, amount in sorted(totals.items(), key=lambda item: item[1], reverse=True)
        ]
        body += f"<h2>{html_escape(label.title())} Spending</h2>"
        body += "<div class=\"metric-row\">" + metric("total spending", money(total), f"{period[0]} to {period[-1]}") + "</div>"
        body += html_table(ranked, ["category", "outflow_sgd", "share", "transactions"], limit=12)
    return body


def issues_summary() -> str:
    rows = read_csv(EXPORTS_DIR / "issues_full.csv")
    if not rows:
        rows = read_csv(Path(__file__).resolve().parents[1] / "data" / "processed" / "issues.csv")
    open_rows = [row for row in rows if row.get("status", "open") == "open"]
    severity: defaultdict[str, int] = defaultdict(int)
    for row in open_rows:
        severity[row.get("severity", "unknown")] += 1
    sev_rows = [{"severity": key, "count": value} for key, value in sorted(severity.items())]
    recent = open_rows[-20:]
    body = "<h2>Open Issues</h2>"
    body += "<div class=\"metric-row\">" + metric("open issues", str(len(open_rows))) + "</div>"
    body += html_table(sev_rows, ["severity", "count"])
    body += "<h2>Recent Open Issues</h2>" + html_table(
        recent,
        ["severity", "issue_type", "institution", "account_id", "date", "message", "suggested_action"],
        limit=20,
    )
    return body


def public_fee_changes_summary() -> str:
    changes = read_csv(EXPORTS_DIR / "public_fee_source_changes.csv")
    issues = read_csv(EXPORTS_DIR / "public_fee_source_check_issues.csv")
    body = "<h2>Public Fee Listing Checks</h2>"
    body += "<div class=\"metric-row\">"
    body += metric("public fee changes", str(len(changes)))
    body += metric("fee sources not refreshed", str(len(issues)))
    body += "</div>"
    if changes:
        body += html_table(changes, ["change_type", "name", "isin", "old_fee_bps", "new_fee_bps", "message"], limit=20)
    elif issues:
        body += "<p class=\"warning\">No fee changes detected, but one or more online fee sources were not refreshed. Check the public fee source report.</p>"
    else:
        body += "<p class=\"muted\">No public embedded-fee listing changes detected.</p>"
    return body


def refresh_control_summary() -> str:
    controls = read_csv(EXPORTS_DIR / "refresh_control_checks.csv")
    critical = [row for row in controls if row.get("severity") == "critical"]
    warnings = [row for row in controls if row.get("severity") == "warning"]
    body = "<h2>Refresh Control Checks</h2>"
    body += "<div class=\"metric-row\">"
    body += metric("critical checks", str(len(critical)))
    body += metric("warning checks", str(len(warnings)))
    body += metric("total controls", str(len(controls)))
    body += "</div>"
    important = critical + warnings
    if important:
        body += html_table(important, ["check", "severity", "status", "count", "message", "suggested_action"], limit=20)
    else:
        body += "<p class=\"muted\">No critical or warning control checks.</p>"
    return body


def links_summary() -> str:
    links = [
        ("Net Worth", "net_worth_stacked.html"),
        ("Spending By Category", "spending_by_category.html"),
        ("Fees", "fees_actual_vs_embedded.html"),
        ("Refresh Control Checks", "refresh_control_checks.html"),
        ("Public Fee Source Changes", "public_fee_source_changes.html"),
        ("Source Of Funds", "source_of_funds.html"),
        ("Latest Run", "latest_run.html"),
        ("Issues", "issues.html"),
    ]
    items = "".join(f"<li><a href=\"{html_escape(href)}\">{html_escape(label)}</a></li>" for label, href in links)
    return f"<h2>Useful Reports</h2><ul>{items}</ul>"


def run() -> dict[str, Any]:
    generated_at = datetime.now().isoformat(timespec="seconds")
    net_worth, _changes = net_worth_summary()
    body = f"<p class=\"muted\">Generated locally at {html_escape(generated_at)}. Reports stop at the last completed month-end: {REPORT_END_DATE.isoformat()}.</p>"
    body += net_worth
    body += spending_summary()
    body += refresh_control_summary()
    body += public_fee_changes_summary()
    body += issues_summary()
    body += links_summary()
    write_html_report(REPORTS_DIR / "refresh_summary.html", "Finance Refresh Summary", body)
    return {"report": str(REPORTS_DIR / "refresh_summary.html")}


if __name__ == "__main__":
    print(run())
