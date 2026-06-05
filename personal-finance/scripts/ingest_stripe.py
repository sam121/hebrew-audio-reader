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
    parse_decimal,
    parser_source_file,
    stable_id,
    write_csv,
)
from pdf_utils import extract_pdf_text


PARSER_NAME = "ingest_stripe_pdf_v1"


def files() -> list[Path]:
    roots = [SOURCE_ROOT / "Sam" / "sam_stripe", SOURCE_ROOT / "Sam" / "stripe_shareworks"]
    paths: list[Path] = []
    for root in roots:
        if not root.exists():
            continue
        paths.extend(path for path in root.rglob("*.pdf") if path.name.lower() == "statement.pdf")
    return sorted(paths)


def clean_text(text: str) -> str:
    return text.replace("\u200b", "").replace("\xa0", " ")


def parse_stripe_date(value: str):
    for fmt in ("%d-%b-%Y", "%d %b %Y", "%d-%B-%Y", "%d %B %Y"):
        try:
            return datetime.strptime(value.strip(), fmt).date()
        except ValueError:
            continue
    return None


def parse_summary_date(text: str):
    match = re.search(r"Summary Period:\s*\d{1,2}-[A-Za-z]{3}-\d{4}\s+to\s+(\d{1,2}-[A-Za-z]{3}-\d{4})", text)
    return parse_stripe_date(match.group(1)) if match else None


def parse_account_number(text: str) -> str:
    match = re.search(r"Account Number:\s*([A-Z0-9-]+)", text)
    return match.group(1) if match else "stripe_equity"


def parse_account_summary(text: str) -> dict[str, Decimal | None]:
    compact = " ".join(text.split())
    common_quantity = re.search(r"Common\s+([0-9,]+)\s+.*?Total Value\s+Available Value", compact)
    common = re.search(r"Common\s+\$([0-9,.]+)", compact)
    rsu = re.search(r"RSU\s+\$([0-9,.]+)\s+\$0\.00\s+\$([0-9,.]+)\s+\$([0-9,.]+)\s+\$([0-9,.]+)", compact)
    total = re.search(r"Total\s+\$([0-9,.]+)\s+\$0\.00\s+\$([0-9,.]+)\s+\$([0-9,.]+)\s+\$([0-9,.]+)", compact)
    return {
        "common_value": parse_decimal(common.group(1)) if common else None,
        "common_quantity": parse_decimal(common_quantity.group(1)) if common_quantity else None,
        "rsu_value": parse_decimal(rsu.group(1)) if rsu else None,
        "total_value": parse_decimal(total.group(1)) if total else None,
        "future_2026": parse_decimal(total.group(2)) if total else None,
        "future_2027": parse_decimal(total.group(3)) if total else None,
        "future_2028": parse_decimal(total.group(4)) if total else None,
    }


def add_balance(rows: list[dict[str, Any]], path: Path, account_id: str, value_date: Any, value: Decimal, balance_type: str, status: str, source_row: str) -> None:
    value_sgd, fx = converted_with_fx(value, "USD", value_date)
    rows.append(
        {
            "balance_id": stable_id("bal", "stripe", parser_source_file(path), account_id, value_date, balance_type, value),
            "owner": "samuel",
            "institution": "stripe",
            "account_id": account_id,
            "account_name": "Stripe Equity",
            "account_type": "private_equity",
            "date": value_date,
            "balance": value,
            "currency": "USD",
            "balance_sgd": value_sgd,
            **fx,
            "balance_type": balance_type,
            "confidence_status": status,
            "source_file": parser_source_file(path),
            "source_page": "1",
            "source_row": source_row,
            "parser_name": PARSER_NAME,
            "parse_confidence": 0.9,
        }
    )


def parse_security_events(text: str) -> list[dict[str, Any]]:
    events: list[dict[str, Any]] = []
    current_re = re.compile(
        r"(CS-\d+)\s+Class A Common\s+Release\s+(\d{2}-[A-Za-z]{3}-\d{4})\s+([0-9,]+)\s+([0-9,]+)\s+\$([0-9,.]+)\s+\$([0-9,.]+)",
        flags=re.IGNORECASE,
    )
    cancelled_re = re.compile(
        r"(CS-\d+)\s+Class A Common\s+Release\s+(\d{2}-[A-Za-z]{3}-\d{4})\s+(\d{2}-[A-Za-z]{3}-\d{4})\s+Tender Offer Sale\s+([0-9,]+)\s+([0-9,]+)\s+\$([0-9,.]+)",
        flags=re.IGNORECASE,
    )
    for match in current_re.finditer(text):
        release_date = parse_stripe_date(match.group(2))
        quantity = parse_decimal(match.group(3))
        cost_basis = parse_decimal(match.group(5))
        if release_date and quantity is not None and cost_basis is not None:
            events.append(
                {
                    "date": release_date,
                    "quantity_delta": quantity,
                    "value_delta": cost_basis,
                    "source": f"{match.group(1)} release cost basis",
                }
            )
    for match in cancelled_re.finditer(text):
        release_date = parse_stripe_date(match.group(2))
        cancel_date = parse_stripe_date(match.group(3))
        quantity = parse_decimal(match.group(4))
        cost_basis = parse_decimal(match.group(6))
        if release_date and quantity is not None and cost_basis is not None:
            events.append(
                {
                    "date": release_date,
                    "quantity_delta": quantity,
                    "value_delta": cost_basis,
                    "source": f"{match.group(1)} release cost basis",
                }
            )
        if cancel_date and quantity is not None and cost_basis is not None:
            events.append(
                {
                    "date": cancel_date,
                    "quantity_delta": -quantity,
                    "value_delta": -cost_basis,
                    "source": f"{match.group(1)} tender offer sale/cancellation",
                }
            )
    return sorted(events, key=lambda event: (event["date"], event["source"]))


def add_historical_balance_snapshots(rows: list[dict[str, Any]], path: Path, account_id: str, text: str, current_value_date: Any) -> None:
    events = parse_security_events(text)
    if not events:
        return
    quantity = Decimal("0")
    value = Decimal("0")
    by_date: dict[Any, list[str]] = {}
    for event in events:
        event_date = event["date"]
        if current_value_date and event_date >= current_value_date:
            continue
        quantity += event["quantity_delta"]
        value += event["value_delta"]
        by_date.setdefault(event_date, []).append(event["source"])
        if quantity < 0:
            quantity = Decimal("0")
        if value < 0:
            value = Decimal("0")
        value_sgd, fx = converted_with_fx(value, "USD", event_date)
        rows.append(
            {
                "balance_id": stable_id("bal", "stripe", parser_source_file(path), account_id, event_date, "historical", value),
                "owner": "samuel",
                "institution": "stripe",
                "account_id": account_id,
                "account_name": "Stripe Equity",
                "account_type": "private_equity",
                "date": event_date,
                "balance": value,
                "currency": "USD",
                "balance_sgd": value_sgd,
                **fx,
                "balance_type": "released_common_shares_value",
                "confidence_status": "inferred",
                "source_file": parser_source_file(path),
                "source_page": "Summary of Securities",
                "source_row": "; ".join(by_date[event_date]),
                "parser_name": PARSER_NAME,
                "parse_confidence": 0.78,
            }
        )


def parse_holdings(path: Path, account_id: str, value_date: Any, summary: dict[str, Decimal | None]) -> list[dict[str, Any]]:
    holdings: list[dict[str, Any]] = []
    quantity = summary.get("common_quantity")
    market_value = summary.get("common_value")
    if quantity and market_value:
        price = market_value / quantity if quantity and market_value else None
        market_value_sgd, fx = converted_with_fx(market_value, "USD", value_date)
        holdings.append(
            {
                "holding_id": stable_id("hold", "stripe", account_id, value_date, "STRIPE_PRIVATE_COMMON"),
                "owner": "samuel",
                "institution": "stripe",
                "account_id": account_id,
                "date": value_date,
                "symbol": "STRIPE_PRIVATE",
                "name": "Stripe Inc. Class A Common",
                "asset_class": "private_equity",
                "quantity": quantity,
                "price": price,
                "market_value": market_value,
                "currency": "USD",
                "market_value_sgd": market_value_sgd,
                **fx,
                "confidence_status": "confirmed",
                "source_file": parser_source_file(path),
                "source_row": "Account Summary Common",
                "parser_name": PARSER_NAME,
            }
        )
    return holdings


def parse_withdrawals(path: Path, text: str, account_id: str) -> list[dict[str, Any]]:
    transactions: list[dict[str, Any]] = []
    pattern = re.compile(
        r"Withdrawal on ([A-Za-z]+ \d{1,2}, \d{4}|[A-Za-z]+ \d{1,2} \d{4}).{0,1500}?Settlement Date:\s*(\d{1,2}-[A-Za-z]{3}-\d{4}).{0,360}?Proceeds:\s*\$([0-9,.]+) USD.{0,1500}?Net Proceeds:\s*\$([0-9,.]+) USD",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(text):
        settlement_date = parse_stripe_date(match.group(2))
        gross = parse_decimal(match.group(3))
        net = parse_decimal(match.group(4))
        if not settlement_date or net is None:
            continue
        amount_sgd, fx = converted_with_fx(-net, "USD", settlement_date)
        transactions.append(
            {
                "transaction_id": stable_id("tx", "stripe", parser_source_file(path), account_id, settlement_date, net, match.group(0)[:80]),
                "owner": "samuel",
                "institution": "stripe",
                "account_id": account_id,
                "account_name": "Stripe Equity",
                "account_type": "private_equity",
                "date": settlement_date,
                "posted_date": settlement_date,
                "description_raw": f"Withdrawal / cash-out, gross USD {gross}, net USD {net}",
                "description_clean": "stripe equity cashout",
                "merchant": "Stripe",
                "amount": -net,
                "currency": "USD",
                "amount_sgd": amount_sgd,
                **fx,
                "direction": direction_for(-net),
                "category": "income",
                "subcategory": "equity_cashout",
                "is_transfer_candidate": True,
                "matched_transfer_id": "",
                "confidence_status": "confirmed",
                "source_file": parser_source_file(path),
                "source_page": "",
                "source_row": " ".join(match.group(0).split())[:240],
                "parser_name": PARSER_NAME,
                "parse_confidence": 0.88,
            }
        )
    return transactions


def ingest_file(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    text = clean_text(extract_pdf_text(path))
    value_date = parse_summary_date(text)
    account_id = parse_account_number(text)
    summary = parse_account_summary(text)
    balances: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []

    if value_date and summary.get("common_value") is not None:
        add_historical_balance_snapshots(balances, path, account_id, text, value_date)
        add_balance(balances, path, account_id, value_date, summary["common_value"], "released_common_shares_value", "confirmed", "Account Summary Common Total Value")
    else:
        issues.append(
            make_issue(
                "parse",
                "warning",
                "samuel",
                "stripe",
                account_id,
                "Could not find Stripe released common share value.",
                "Inspect Stripe statement account summary.",
                value_date=value_date,
                source_file=parser_source_file(path),
                key=f"stripe-no-common-{path.name}",
            )
        )
    if value_date and summary.get("rsu_value") is not None:
        add_balance(balances, path, account_id, value_date, summary["rsu_value"], "future_unvested_rsu_value", "excluded", "Account Summary RSU Future Available Value")

    holdings = parse_holdings(path, account_id, value_date, summary)
    transactions = parse_withdrawals(path, text, account_id)
    controls = [
        {
            "control_id": stable_id("ctl", PARSER_NAME, parser_source_file(path)),
            "parser_name": PARSER_NAME,
            "source_file": parser_source_file(path),
            "owner": "samuel",
            "institution": "stripe",
            "account_id": account_id,
            "file_count": 1,
            "row_count": len(transactions) + len(balances) + len(holdings),
            "date_min": value_date,
            "date_max": value_date,
            "sum_credits": sum((abs(tx["amount"]) for tx in transactions), Decimal("0")),
            "sum_debits": None,
            "opening_balance": None,
            "closing_balance": summary.get("common_value"),
            "warning_count": len(issues),
            "failed_row_count": 0,
        }
    ]
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
                "stripe",
                "",
                "No Stripe PDF files found.",
                "Check source folder path and Stripe statement location.",
                source_file=str(SOURCE_ROOT / "Sam" / "stripe_shareworks"),
                key="stripe-no-files",
            )
        )
    write_csv(PROCESSED_DIR / "stripe_transactions.csv", all_transactions, TRANSACTION_COLUMNS)
    write_csv(PROCESSED_DIR / "stripe_balances.csv", all_balances, BALANCE_COLUMNS)
    write_csv(PROCESSED_DIR / "stripe_holdings.csv", all_holdings, HOLDING_COLUMNS)
    write_csv(PROCESSED_DIR / "stripe_parse_issues.csv", all_issues, ISSUE_COLUMNS)
    write_csv(PROCESSED_DIR / "stripe_control_totals.csv", all_controls, CONTROL_TOTAL_COLUMNS)
    return {
        "files": len(files()),
        "transactions": len(all_transactions),
        "balances": len(all_balances),
        "holdings": len(all_holdings),
        "issues": len(all_issues),
    }


if __name__ == "__main__":
    print(run())
