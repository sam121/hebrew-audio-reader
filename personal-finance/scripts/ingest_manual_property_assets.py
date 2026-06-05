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


PARSER_NAME = "ingest_manual_property_assets_v1"
SOURCE_CSV_FILE = SOURCE_ROOT / "Manual" / "manual_property_assets.csv"
FALLBACK_CSV_FILE = CONFIG_DIR / "manual_property_assets.csv"
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


def interpolate(start_date: date, start_value: Decimal, end_date: date, end_value: Decimal, current: date) -> Decimal:
    if current <= start_date:
        return start_value
    if current >= end_date:
        return end_value
    total_days = Decimal((end_date - start_date).days)
    elapsed = Decimal((current - start_date).days)
    return start_value + (end_value - start_value) * elapsed / total_days


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
            "amy",
            "manual_property",
            "6_stanley_terrace",
            "Manual property asset file is missing or empty.",
            "Create Transactions/Manual/manual_property_assets.csv with property anchor values and payoff events.",
            source_file=str(input_file.resolve()),
            key="manual-property-assets-missing",
        )
        write_csv(PROCESSED_DIR / "manual_property_balances.csv", balances, BALANCE_COLUMNS)
        write_csv(PROCESSED_DIR / "manual_property_parse_issues.csv", [issue], ISSUE_COLUMNS)
        write_csv(PROCESSED_DIR / "manual_property_control_totals.csv", controls, CONTROL_TOTAL_COLUMNS)
        return {"balances": 0, "issues": 1}

    anchors = sorted([row for row in events if row["event_type"] == "anchor_net_equity"], key=lambda row: row["event_date"])
    payoffs = sorted([row for row in events if row["event_type"] == "mortgage_payoff"], key=lambda row: row["event_date"])
    first = anchors[0]
    second = anchors[-1]
    start_date = first["event_date"]
    end_anchor_date = second["event_date"]
    start_value = first["amount_gbp"]
    end_value = second["amount_gbp"]

    for value_date in monthly_dates(start_date, END_DATE):
        base_value = interpolate(start_date, start_value, end_anchor_date, end_value, value_date)
        payoff_total = sum((row["amount_gbp"] for row in payoffs if row["event_date"] <= value_date), Decimal("0"))
        value = base_value + payoff_total
        status = "inferred"
        source_file = str(input_file.resolve())
        source_row = "linear_interpolation_between_user_anchors"
        if payoff_total:
            source_row += "_plus_confirmed_mortgage_payoffs"
        value_sgd, fx = converted_with_fx(value, "GBP", value_date)
        balances.append(
            {
                "balance_id": stable_id("bal", PARSER_NAME, "6_stanley_terrace", value_date, value),
                "owner": "amy",
                "institution": "manual_property",
                "account_id": "6_stanley_terrace",
                "account_name": "6 Stanley Terrace Liverpool L18 5EE",
                "account_type": "property",
                "date": value_date,
                "balance": value,
                "currency": "GBP",
                "balance_sgd": value_sgd,
                **fx,
                "balance_type": "manual_net_property_equity",
                "confidence_status": status,
                "source_file": source_file,
                "source_page": "",
                "source_row": source_row,
                "parser_name": PARSER_NAME,
                "parse_confidence": 0.82,
            }
        )

    controls.append(
        {
            "control_id": stable_id("ctl", PARSER_NAME, input_file),
            "parser_name": PARSER_NAME,
            "source_file": str(input_file.resolve()),
            "owner": "amy",
            "institution": "manual_property",
            "account_id": "6_stanley_terrace",
            "file_count": 1,
            "row_count": len(balances),
            "date_min": balances[0]["date"] if balances else None,
            "date_max": balances[-1]["date"] if balances else None,
            "sum_credits": sum((row["amount_gbp"] for row in payoffs), Decimal("0")),
            "sum_debits": None,
            "opening_balance": start_value,
            "closing_balance": balances[-1]["balance"] if balances else None,
            "warning_count": len(issues),
            "failed_row_count": 0,
        }
    )

    write_csv(PROCESSED_DIR / "manual_property_balances.csv", balances, BALANCE_COLUMNS)
    write_csv(PROCESSED_DIR / "manual_property_parse_issues.csv", issues, ISSUE_COLUMNS)
    write_csv(PROCESSED_DIR / "manual_property_control_totals.csv", controls, CONTROL_TOTAL_COLUMNS)
    return {"balances": len(balances), "issues": len(issues)}


if __name__ == "__main__":
    print(run())
