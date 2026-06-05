from __future__ import annotations

import re
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

from common import (
    BALANCE_COLUMNS,
    CONTROL_TOTAL_COLUMNS,
    HOLDING_COLUMNS,
    ISSUE_COLUMNS,
    PROCESSED_DIR,
    SOURCE_ROOT,
    TRANSACTION_COLUMNS,
    converted_with_fx,
    direction_for,
    ensure_dirs,
    make_issue,
    parse_date,
    parse_decimal,
    parser_source_file,
    stable_id,
    write_csv,
)
from pdf_utils import extract_pdf_text


PARSER_NAME = "ingest_evelyn_pdf_v1"


def files() -> list[Path]:
    root = SOURCE_ROOT / "Sam" / "sam_evelyn"
    return sorted(root.glob("*.pdf")) if root.exists() else []


def parse_filename(path: Path) -> tuple[str, Any]:
    match = re.match(r"Valuation Report_([A-Z0-9]+)_(\d{8})_\d+\.pdf$", path.name)
    if not match:
        return "UNKNOWN", None
    return match.group(1), parse_date(match.group(2))


def money_pattern() -> str:
    return r"£\s*([0-9][0-9,]*(?:\.[0-9]{2})?)"


def find_portfolio_value(text: str, value_date: Any) -> tuple[Decimal | None, str]:
    compact = " ".join(text.split())
    if value_date:
        day = value_date.day
        month_name = value_date.strftime("%B")
        year = value_date.year
        patterns = [
            rf"Portfolio Value on {day} {month_name} {year}\s+{money_pattern()}",
            rf"Closing Value for {day} {month_name} {year}\s+{money_pattern()}",
            rf"Value On {day} {month_name} {year}\s+{money_pattern()}",
        ]
        for pattern in patterns:
            match = re.search(pattern, compact, flags=re.IGNORECASE)
            if match:
                return parse_decimal(match.group(1)), match.group(0)
    match = re.search(r"Portfolio Value on .*?£\s*([0-9][0-9,]*(?:\.[0-9]{2})?)", compact, flags=re.IGNORECASE)
    if match:
        return parse_decimal(match.group(1)), match.group(0)
    match = re.search(r"Closing Value for .*?£\s*([0-9][0-9,]*(?:\.[0-9]{2})?)", compact, flags=re.IGNORECASE)
    if match:
        return parse_decimal(match.group(1)), match.group(0)
    return None, ""


def find_cash_added(text: str) -> Decimal | None:
    compact = " ".join(text.split())
    match = re.search(r"Cash Added\s+£\s*([0-9][0-9,]*(?:\.[0-9]{2})?)", compact, flags=re.IGNORECASE)
    if match:
        return parse_decimal(match.group(1))
    match = re.search(r"Contributions / \(deductions\) during period\s+£\s*([0-9][0-9,]*(?:\.[0-9]{2})?)", compact, flags=re.IGNORECASE)
    return parse_decimal(match.group(1)) if match else None


def find_funds_received(text: str) -> tuple[Any, Decimal | None, str]:
    for line in text.splitlines():
        match = re.search(
            r"(\d{1,2} \w+ \d{4})\s+FUNDS RECD\s+£\s*([0-9][0-9,]*(?:\.[0-9]{2})?)",
            line,
            flags=re.IGNORECASE,
        )
        if match:
            funding_date = datetime.strptime(match.group(1), "%d %b %Y").date()
            return funding_date, parse_decimal(match.group(2)), line.strip()
    return None, None, ""


def ingest_file(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    account_id, value_date = parse_filename(path)
    account_name = f"Evelyn GIA {account_id} D"
    text = extract_pdf_text(path)
    balances: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []

    portfolio_value, source_row = find_portfolio_value(text, value_date)
    if value_date and portfolio_value is not None:
        balance_sgd, fx = converted_with_fx(portfolio_value, "GBP", value_date)
        balances.append(
            {
                "balance_id": stable_id("bal", "evelyn", parser_source_file(path), account_id, value_date, portfolio_value),
                "owner": "samuel",
                "institution": "evelyn",
                "account_id": account_id,
                "account_name": account_name,
                "account_type": "investment",
                "date": value_date,
                "balance": portfolio_value,
                "currency": "GBP",
                "balance_sgd": balance_sgd,
                **fx,
                "balance_type": "portfolio_valuation",
                "confidence_status": "confirmed",
                "source_file": parser_source_file(path),
                "source_page": "",
                "source_row": source_row or "Portfolio Value",
                "parser_name": PARSER_NAME,
                "parse_confidence": 0.94,
            }
        )
    else:
        issues.append(
            make_issue(
                "parse",
                "warning",
                "samuel",
                "evelyn",
                account_id,
                "Could not find Evelyn portfolio valuation.",
                "Inspect valuation report text and update parser pattern if the layout changed.",
                value_date=value_date,
                source_file=parser_source_file(path),
                key=f"evelyn-no-valuation-{path.name}",
            )
        )

    funding_date, funding_amount, funding_source_row = find_funds_received(text)
    if funding_date and funding_amount is not None:
        amount_sgd, fx = converted_with_fx(funding_amount, "GBP", funding_date)
        transactions.append(
            {
                "transaction_id": stable_id("tx", "evelyn", parser_source_file(path), account_id, funding_date, funding_amount, "FUNDS RECD"),
                "owner": "samuel",
                "institution": "evelyn",
                "account_id": account_id,
                "account_name": account_name,
                "account_type": "investment",
                "date": funding_date,
                "posted_date": funding_date,
                "description_raw": "FUNDS RECD",
                "description_clean": "funds received",
                "merchant": "",
                "amount": funding_amount,
                "currency": "GBP",
                "amount_sgd": amount_sgd,
                **fx,
                "direction": direction_for(funding_amount),
                "category": "transfer",
                "subcategory": "investment_funding",
                "is_transfer_candidate": True,
                "matched_transfer_id": "",
                "confidence_status": "confirmed",
                "source_file": parser_source_file(path),
                "source_page": "Cash Statement",
                "source_row": funding_source_row,
                "parser_name": PARSER_NAME,
                "parse_confidence": 0.95,
            }
        )

    cash_added = find_cash_added(text)
    controls.append(
        {
            "control_id": stable_id("ctl", PARSER_NAME, parser_source_file(path)),
            "parser_name": PARSER_NAME,
            "source_file": parser_source_file(path),
            "owner": "samuel",
            "institution": "evelyn",
            "account_id": account_id,
            "file_count": 1,
            "row_count": len(balances) + len(transactions),
            "date_min": value_date,
            "date_max": value_date,
            "sum_credits": cash_added,
            "sum_debits": None,
            "opening_balance": None,
            "closing_balance": portfolio_value,
            "warning_count": len(issues),
            "failed_row_count": 0,
        }
    )
    return transactions, balances, holdings, issues, controls


def run() -> dict[str, Any]:
    ensure_dirs()
    all_transactions: list[dict[str, Any]] = []
    all_balances: list[dict[str, Any]] = []
    all_holdings: list[dict[str, Any]] = []
    all_issues: list[dict[str, Any]] = []
    all_controls: list[dict[str, Any]] = []
    for path in files():
        transactions, balances, holdings, issues, controls = ingest_file(path)
        all_transactions.extend(transactions)
        all_balances.extend(balances)
        all_holdings.extend(holdings)
        all_issues.extend(issues)
        all_controls.extend(controls)

    if not files():
        all_issues.append(
            make_issue(
                "parse",
                "warning",
                "samuel",
                "evelyn",
                "",
                "No Evelyn PDF files found.",
                "Check source folder path and Evelyn report location.",
                source_file=str(SOURCE_ROOT / "Sam" / "sam_evelyn"),
                key="evelyn-no-files",
            )
        )
    write_csv(PROCESSED_DIR / "evelyn_transactions.csv", all_transactions, TRANSACTION_COLUMNS)
    write_csv(PROCESSED_DIR / "evelyn_balances.csv", all_balances, BALANCE_COLUMNS)
    write_csv(PROCESSED_DIR / "evelyn_holdings.csv", all_holdings, HOLDING_COLUMNS)
    write_csv(PROCESSED_DIR / "evelyn_parse_issues.csv", all_issues, ISSUE_COLUMNS)
    write_csv(PROCESSED_DIR / "evelyn_control_totals.csv", all_controls, CONTROL_TOTAL_COLUMNS)
    return {
        "files": len(files()),
        "transactions": len(all_transactions),
        "balances": len(all_balances),
        "holdings": len(all_holdings),
        "issues": len(all_issues),
    }


if __name__ == "__main__":
    print(run())
