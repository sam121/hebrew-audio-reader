from __future__ import annotations

import csv
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from common import (
    BALANCE_COLUMNS,
    CONFIG_DIR,
    CONTROL_TOTAL_COLUMNS,
    ISSUE_COLUMNS,
    PROCESSED_DIR,
    SOURCE_ROOT,
    add_months,
    converted_with_fx,
    ensure_dirs,
    make_issue,
    month_end,
    parse_date,
    parse_decimal,
    stable_id,
    write_csv,
)


PARSER_NAME = "ingest_manual_premium_bonds_v1"
SOURCE_CSV_FILE = SOURCE_ROOT / "Manual" / "manual_premium_bonds.csv"
FALLBACK_CSV_FILE = CONFIG_DIR / "manual_premium_bonds.csv"
END_DATE = date(2026, 4, 30)


def csv_file() -> Path:
    if SOURCE_CSV_FILE.exists():
        return SOURCE_CSV_FILE
    return FALLBACK_CSV_FILE


def load_events() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    path = csv_file()
    if not path.exists():
        return rows
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            row["event_date"] = parse_date(row.get("event_date"))
            row["amount_gbp"] = parse_decimal(row.get("amount_gbp"))
            rows.append(row)
    return rows


def monthly_dates(start: date, end: date) -> list[date]:
    cur = date(start.year, start.month, 1)
    dates = []
    while cur <= end:
        dates.append(month_end(cur.year, cur.month))
        cur = add_months(cur, 1)
    return dates


def run() -> dict[str, Any]:
    ensure_dirs()
    balances: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    input_file = csv_file()
    events = load_events()

    if not events:
        issue = make_issue(
            "parse",
            "warning",
            "samuel",
            "manual_premium_bonds",
            "premium_bonds",
            "Manual Premium Bonds asset file is missing or empty.",
            "Create Transactions/Manual/manual_premium_bonds.csv with an anchor value and cash-out event.",
            source_file=str(input_file.resolve()),
            key="manual-premium-bonds-missing",
        )
        write_csv(PROCESSED_DIR / "manual_premium_bonds_balances.csv", balances, BALANCE_COLUMNS)
        write_csv(PROCESSED_DIR / "manual_premium_bonds_parse_issues.csv", [issue], ISSUE_COLUMNS)
        write_csv(PROCESSED_DIR / "manual_premium_bonds_control_totals.csv", controls, CONTROL_TOTAL_COLUMNS)
        return {"balances": 0, "issues": 1}

    anchors = sorted([row for row in events if row["event_type"] == "anchor_asset_value"], key=lambda row: row["event_date"])
    cashouts = sorted([row for row in events if row["event_type"] == "cashout_to_barclays"], key=lambda row: row["event_date"])
    if not anchors:
        issue = make_issue(
            "parse",
            "error",
            "samuel",
            "manual_premium_bonds",
            "premium_bonds",
            "Manual Premium Bonds file has no anchor_asset_value row.",
            "Add an anchor_asset_value row with the starting Premium Bonds value.",
            source_file=str(input_file.resolve()),
            key="manual-premium-bonds-no-anchor",
        )
        write_csv(PROCESSED_DIR / "manual_premium_bonds_balances.csv", balances, BALANCE_COLUMNS)
        write_csv(PROCESSED_DIR / "manual_premium_bonds_parse_issues.csv", [issue], ISSUE_COLUMNS)
        write_csv(PROCESSED_DIR / "manual_premium_bonds_control_totals.csv", controls, CONTROL_TOTAL_COLUMNS)
        return {"balances": 0, "issues": 1}

    anchor = anchors[0]
    start_date = anchor["event_date"]
    starting_value = anchor["amount_gbp"]
    cashout_date = cashouts[0]["event_date"] if cashouts else None

    for value_date in monthly_dates(start_date, END_DATE):
        value = Decimal("0") if cashout_date and value_date >= month_end(cashout_date.year, cashout_date.month) else starting_value
        value_sgd, fx = converted_with_fx(value, "GBP", value_date)
        source_row = "manual_anchor_value"
        confidence_status = anchor.get("confidence_status") or "inferred"
        if value == 0 and cashouts:
            source_row = "cashout_to_barclays"
            confidence_status = cashouts[0].get("confidence_status") or "confirmed"
        balances.append(
            {
                "balance_id": stable_id("bal", PARSER_NAME, "premium_bonds", value_date, value),
                "owner": "samuel",
                "institution": "manual_premium_bonds",
                "account_id": "premium_bonds",
                "account_name": "NS&I Premium Bonds",
                "account_type": "investment",
                "date": value_date,
                "balance": value,
                "currency": "GBP",
                "balance_sgd": value_sgd,
                **fx,
                "balance_type": "manual_premium_bonds_value",
                "confidence_status": confidence_status,
                "source_file": str(input_file.resolve()),
                "source_page": "",
                "source_row": source_row,
                "parser_name": PARSER_NAME,
                "parse_confidence": 0.88,
            }
        )

    controls.append(
        {
            "control_id": stable_id("ctl", PARSER_NAME, input_file),
            "parser_name": PARSER_NAME,
            "source_file": str(input_file.resolve()),
            "owner": "samuel",
            "institution": "manual_premium_bonds",
            "account_id": "premium_bonds",
            "file_count": 1,
            "row_count": len(balances),
            "date_min": balances[0]["date"] if balances else None,
            "date_max": balances[-1]["date"] if balances else None,
            "sum_credits": None,
            "sum_debits": cashouts[0]["amount_gbp"] if cashouts else None,
            "opening_balance": starting_value,
            "closing_balance": balances[-1]["balance"] if balances else None,
            "warning_count": len(issues),
            "failed_row_count": 0,
        }
    )

    write_csv(PROCESSED_DIR / "manual_premium_bonds_balances.csv", balances, BALANCE_COLUMNS)
    write_csv(PROCESSED_DIR / "manual_premium_bonds_parse_issues.csv", issues, ISSUE_COLUMNS)
    write_csv(PROCESSED_DIR / "manual_premium_bonds_control_totals.csv", controls, CONTROL_TOTAL_COLUMNS)
    return {"balances": len(balances), "issues": len(issues)}


if __name__ == "__main__":
    print(run())
