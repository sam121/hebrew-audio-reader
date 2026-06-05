from __future__ import annotations

from collections import Counter
from pathlib import Path
from typing import Any

from common import (
    DATA_DIR,
    EXPORTS_DIR,
    PROCESSED_DIR,
    REPORTS_DIR,
    SOURCE_LIMITATION_COLUMNS,
    ensure_dirs,
    html_escape,
    html_table,
    parse_decimal,
    read_csv_dicts,
    read_json,
    source_path,
    write_html_report,
)


def metrics(items: list[tuple[str, Any]]) -> str:
    body = "<div class=\"metric-row\">"
    for label, value in items:
        body += f"<div class=\"metric\"><strong>{html_escape(value)}</strong><span>{html_escape(label)}</span></div>"
    body += "</div>"
    return body


def rows_from_counter(counter: Counter) -> list[dict[str, Any]]:
    return [{"name": key, "count": value} for key, value in sorted(counter.items())]


def inventory_report() -> None:
    rows = read_csv_dicts(PROCESSED_DIR / "inventory_files.csv")
    missing = read_csv_dicts(PROCESSED_DIR / "inventory_missing_months.csv")
    limitations = read_csv_dicts(PROCESSED_DIR / "source_limitations.csv")
    by_type = Counter(row.get("file_type", "") for row in rows)
    by_institution = Counter(row.get("institution", "") for row in rows)
    duplicates = [row for row in rows if row.get("duplicate_hash_group") or row.get("duplicate_statement_group")]
    overlaps = [row for row in rows if row.get("overlap_group")]

    duplicate_rows = [
        {
            "institution": row.get("institution", ""),
            "account": row.get("detected_account_id", ""),
            "type": row.get("statement_type", ""),
            "period_start": row.get("statement_period_start", ""),
            "period_end": row.get("statement_period_end", ""),
            "hash_group": row.get("duplicate_hash_group", ""),
            "statement_group": row.get("duplicate_statement_group", ""),
            "overlap_group": row.get("overlap_group", ""),
            "path": source_path(Path(row["path"])) if row.get("path") else "",
        }
        for row in duplicates
    ]
    overlap_rows = [
        {
            "institution": row.get("institution", ""),
            "account": row.get("detected_account_id", ""),
            "type": row.get("statement_type", ""),
            "period_start": row.get("statement_period_start", ""),
            "period_end": row.get("statement_period_end", ""),
            "overlap_group": row.get("overlap_group", ""),
            "path": source_path(Path(row["path"])) if row.get("path") else "",
        }
        for row in overlaps
    ]
    body = metrics(
        [
            ("files inventoried", len(rows)),
            ("duplicate candidates", len(duplicates)),
            ("overlap candidates", len(overlaps)),
            ("missing month candidates", len(missing)),
            ("source limitations", len(limitations)),
        ]
    )
    body += "<h2>Files by Type</h2>" + html_table(rows_from_counter(by_type), ["name", "count"])
    body += "<h2>Files by Institution</h2>" + html_table(rows_from_counter(by_institution), ["name", "count"])
    body += "<h2>Duplicate Candidates</h2>" + html_table(
        duplicate_rows,
        ["institution", "account", "type", "period_start", "period_end", "hash_group", "statement_group", "overlap_group", "path"],
    )
    body += "<h2>Overlap Candidates</h2>" + html_table(
        overlap_rows,
        ["institution", "account", "type", "period_start", "period_end", "overlap_group", "path"],
    )
    body += "<h2>Missing Month Candidates</h2>" + html_table(
        missing, ["owner", "institution", "account_id", "statement_type", "month", "status", "notes"]
    )
    body += "<h2>Source Limitations</h2>" + html_table(limitations, SOURCE_LIMITATION_COLUMNS)
    write_html_report(REPORTS_DIR / "inventory.html", "Inventory", body)


def latest_run_report() -> None:
    summary = read_json(DATA_DIR / "latest_run.json", {})
    warnings = read_json(DATA_DIR / "run_warnings.json", [])
    issues = read_csv_dicts(PROCESSED_DIR / "issues.csv")
    controls = read_csv_dicts(PROCESSED_DIR / "run_control_totals.csv")
    severity = Counter(row.get("severity", "") for row in issues)
    issue_type = Counter(row.get("issue_type", "") for row in issues)

    body = metrics(
        [
            ("pipeline steps", len(summary.get("steps", {}))),
            ("issues", len(issues)),
            ("warnings", len(warnings)),
            ("control total rows", len(controls)),
        ]
    )
    if warnings:
        body += "<h2>Run Warnings</h2>"
        body += "".join(f"<p class=\"warning\">{html_escape(warning)}</p>" for warning in warnings)
    body += "<h2>Step Summary</h2>" + html_table(
        [{"step": key, **value} for key, value in summary.get("steps", {}).items()],
        ["step", "files", "transactions", "balances", "holdings", "issues", "validation_issues", "all_issues"],
    )
    body += "<h2>Issues by Severity</h2>" + html_table(rows_from_counter(severity), ["name", "count"])
    body += "<h2>Issues by Type</h2>" + html_table(rows_from_counter(issue_type), ["name", "count"])
    body += "<h2>Recent Issues</h2>" + html_table(
        issues[-100:],
        ["severity", "issue_type", "institution", "account_id", "date", "message", "suggested_action", "status"],
        limit=100,
    )
    body += "<h2>Control Totals</h2>" + html_table(
        controls,
        [
            "parser_name",
            "institution",
            "account_id",
            "row_count",
            "date_min",
            "date_max",
            "sum_credits",
            "sum_debits",
            "opening_balance",
            "closing_balance",
            "warning_count",
            "failed_row_count",
        ],
    )
    write_html_report(REPORTS_DIR / "latest_run.html", "Latest Run", body)


def full_issues_report() -> None:
    issues = read_csv_dicts(PROCESSED_DIR / "issues.csv")
    body = metrics(
        [
            ("open issues", len([row for row in issues if row.get("status") == "open"])),
            ("total issues", len(issues)),
        ]
    )
    body += "<h2>All Issues</h2>" + html_table(
        issues,
        [
            "severity",
            "issue_type",
            "owner",
            "institution",
            "account_id",
            "date",
            "source_file",
            "source_page",
            "message",
            "suggested_action",
            "status",
        ],
        limit=10000,
    )
    write_html_report(REPORTS_DIR / "issues.html", "Issues", body)


def net_worth_report() -> None:
    over_time = read_csv_dicts(EXPORTS_DIR / "net_worth_over_time.csv")
    by_account = read_csv_dicts(EXPORTS_DIR / "net_worth_by_account.csv")
    by_currency = read_csv_dicts(EXPORTS_DIR / "net_worth_by_currency.csv")
    latest = over_time[-1] if over_time else {}
    body = metrics(
        [
            ("months", len(over_time)),
            ("latest month", latest.get("month", "")),
            ("latest confirmed SGD", latest.get("total_sgd_confirmed", "")),
            ("missing FX balances", latest.get("missing_fx_balance_count", "")),
        ]
    )
    body += (
        "<p class=\"warning\">Confirmed SGD totals only include balances that have local SGD conversion. "
        "Non-SGD balances are preserved by currency and flagged until FX rates are configured. "
        "Vanguard balance rows are marked needs_review until the Balance column semantics are confirmed.</p>"
    )
    body += "<h2>Net Worth Over Time</h2>" + html_table(over_time, list(over_time[0].keys()) if over_time else [])
    body += "<h2>By Currency</h2>" + html_table(by_currency, list(by_currency[0].keys()) if by_currency else [])
    body += "<h2>By Account</h2>" + html_table(
        by_account,
        [
            "month",
            "institution",
            "account_id",
            "account_name",
            "date",
            "balance",
            "currency",
            "balance_sgd",
            "confidence_status",
            "balance_type",
        ],
    )
    write_html_report(REPORTS_DIR / "net_worth.html", "Net Worth", body)


def spending_report() -> None:
    spending = read_csv_dicts(EXPORTS_DIR / "monthly_spending.csv")
    latest = spending[-1] if spending else {}
    body = metrics(
        [
            ("months", len(spending)),
            ("latest month", latest.get("month", "")),
            ("latest known SGD outflows", latest.get("total_outflows_sgd_known", "")),
            ("missing FX outflow rows", latest.get("missing_fx_outflow_count", "")),
        ]
    )
    body += (
        "<p class=\"warning\">This is a draft spending view from structured sources only. "
        "Transfer candidates are visible but not automatically excluded until reconciliation is implemented and reviewed.</p>"
    )
    body += "<h2>Monthly Spending Draft</h2>" + html_table(spending, list(spending[0].keys()) if spending else [])
    write_html_report(REPORTS_DIR / "spending.html", "Spending", body)


def reconciliation_report() -> None:
    transfers = read_csv_dicts(PROCESSED_DIR / "transfers.csv")
    transactions = read_csv_dicts(PROCESSED_DIR / "transactions.csv")
    candidates = [row for row in transactions if str(row.get("is_transfer_candidate", "")).lower() == "true"]
    by_institution = Counter(row.get("institution", "") for row in candidates)
    body = metrics(
        [
            ("matched transfers", len(transfers)),
            ("transfer candidates", len(candidates)),
            ("institutions with candidates", len(by_institution)),
        ]
    )
    body += (
        "<p class=\"warning\">Transfers are matched conservatively using same-currency equal-amount pairs within a short date window. "
        "Large unmatched transfer candidates remain listed for review.</p>"
    )
    body += "<h2>Candidates by Institution</h2>" + html_table(rows_from_counter(by_institution), ["name", "count"])
    body += "<h2>Matched Transfers</h2>" + html_table(transfers, list(transfers[0].keys()) if transfers else [])
    write_html_report(REPORTS_DIR / "reconciliation.html", "Reconciliation", body)


def run() -> dict[str, Any]:
    ensure_dirs()
    inventory_report()
    latest_run_report()
    full_issues_report()
    net_worth_report()
    spending_report()
    reconciliation_report()
    return {"reports": 6}


if __name__ == "__main__":
    print(run())
