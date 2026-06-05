from __future__ import annotations

import csv
import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from common import (
    BALANCE_COLUMNS,
    CONTROL_TOTAL_COLUMNS,
    ISSUE_COLUMNS,
    PROCESSED_DIR,
    TRANSACTION_COLUMNS,
    clean_description,
    converted_with_fx,
    direction_for,
    ensure_dirs,
    make_issue,
    owner_for_path,
    parse_date,
    parse_decimal,
    parser_source_file,
    source_folders_for,
    stable_id,
    write_csv,
)


PARSER_NAME = "ingest_halifax_csv_v1"
CURRENCY = "GBP"


def files() -> list[Path]:
    paths: list[Path] = []
    for root in source_folders_for("halifax"):
        paths.extend(root.glob("*.csv"))
    return sorted(paths)


def account_id_from_path(path: Path) -> str:
    match = re.match(r"(\d+)_", path.name)
    return match.group(1) if match else "halifax_unknown"


def row_amount(row: dict[str, str]) -> Decimal | None:
    debit = parse_decimal(row.get("Debit Amount"))
    credit = parse_decimal(row.get("Credit Amount"))
    if debit is not None and debit != 0:
        return -abs(debit)
    if credit is not None and credit != 0:
        return abs(credit)
    return Decimal("0")


def is_transfer_candidate(description: str, tx_type: str) -> bool:
    text = f"{description} {tx_type}".lower()
    return any(clue in text for clue in ["fpi", "fpo", "transfer", "standing order", "salary", "slc receipts"])


def ingest_file(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    owner = owner_for_path(path)
    account_id = account_id_from_path(path)
    account_name = f"Halifax Current Account {account_id}"
    transactions: list[dict[str, Any]] = []
    balances: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    credit_sum = Decimal("0")
    debit_sum = Decimal("0")
    min_date = None
    max_date = None
    opening_balance = None
    closing_balance = None
    failed = 0

    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for source_row, row in enumerate(reader, start=2):
            tx_date = parse_date(row.get("Transaction Date"))
            amount = row_amount(row)
            balance = parse_decimal(row.get("Balance"))
            if tx_date is None or amount is None:
                failed += 1
                issues.append(
                    make_issue(
                        "parse",
                        "warning",
                        owner,
                        "halifax",
                        account_id,
                        "Halifax row could not be parsed into both date and amount.",
                        "Inspect the source CSV row and update the parser if the format changed.",
                        source_file=parser_source_file(path),
                        key=f"halifax-parse-{path.name}-{source_row}",
                    )
                )
                continue

            min_date = tx_date if min_date is None or tx_date < min_date else min_date
            max_date = tx_date if max_date is None or tx_date > max_date else max_date
            if amount > 0:
                credit_sum += amount
            elif amount < 0:
                debit_sum += abs(amount)

            description = clean_description(row.get("Transaction Description"))
            tx_type = clean_description(row.get("Transaction Type"))
            amount_sgd, amount_fx = converted_with_fx(amount, CURRENCY, tx_date)
            transactions.append(
                {
                    "transaction_id": stable_id("tx", "halifax", owner, account_id, tx_date, amount, description, source_row),
                    "owner": owner,
                    "institution": "halifax",
                    "account_id": account_id,
                    "account_name": account_name,
                    "account_type": "bank",
                    "date": tx_date,
                    "posted_date": tx_date,
                    "description_raw": " | ".join(part for part in [tx_type, description] if part),
                    "description_clean": description.lower(),
                    "merchant": description,
                    "amount": amount,
                    "currency": CURRENCY,
                    "amount_sgd": amount_sgd,
                    **amount_fx,
                    "direction": direction_for(amount),
                    "category": "uncategorized",
                    "subcategory": "bank_transaction",
                    "is_transfer_candidate": is_transfer_candidate(description, tx_type),
                    "matched_transfer_id": "",
                    "confidence_status": "confirmed",
                    "source_file": parser_source_file(path),
                    "source_page": "",
                    "source_row": source_row,
                    "parser_name": PARSER_NAME,
                    "parse_confidence": 0.96,
                }
            )

            if balance is not None:
                if opening_balance is None:
                    opening_balance = balance - amount
                closing_balance = balance
                balance_sgd, balance_fx = converted_with_fx(balance, CURRENCY, tx_date)
                balances.append(
                    {
                        "balance_id": stable_id("bal", "halifax", owner, account_id, tx_date, balance, source_row),
                        "owner": owner,
                        "institution": "halifax",
                        "account_id": account_id,
                        "account_name": account_name,
                        "account_type": "bank",
                        "date": tx_date,
                        "balance": balance,
                        "currency": CURRENCY,
                        "balance_sgd": balance_sgd,
                        **balance_fx,
                        "balance_type": "running_after_transaction",
                        "confidence_status": "confirmed",
                        "source_file": parser_source_file(path),
                        "source_page": "",
                        "source_row": source_row,
                        "parser_name": PARSER_NAME,
                        "parse_confidence": 0.96,
                    }
                )

    controls.append(
        {
            "control_id": stable_id("ctl", PARSER_NAME, parser_source_file(path)),
            "parser_name": PARSER_NAME,
            "source_file": parser_source_file(path),
            "owner": owner,
            "institution": "halifax",
            "account_id": account_id,
            "file_count": 1,
            "row_count": len(transactions),
            "date_min": min_date,
            "date_max": max_date,
            "sum_credits": credit_sum,
            "sum_debits": debit_sum,
            "opening_balance": opening_balance,
            "closing_balance": closing_balance,
            "warning_count": len(issues),
            "failed_row_count": failed,
        }
    )
    return transactions, balances, issues, controls


def run() -> dict[str, Any]:
    ensure_dirs()
    all_transactions: list[dict[str, Any]] = []
    all_balances: list[dict[str, Any]] = []
    all_issues: list[dict[str, Any]] = []
    all_controls: list[dict[str, Any]] = []
    csvs = files()
    for path in csvs:
        transactions, balances, issues, controls = ingest_file(path)
        all_transactions.extend(transactions)
        all_balances.extend(balances)
        all_issues.extend(issues)
        all_controls.extend(controls)

    write_csv(PROCESSED_DIR / "halifax_transactions.csv", all_transactions, TRANSACTION_COLUMNS)
    write_csv(PROCESSED_DIR / "halifax_balances.csv", all_balances, BALANCE_COLUMNS)
    write_csv(PROCESSED_DIR / "halifax_parse_issues.csv", all_issues, ISSUE_COLUMNS)
    write_csv(PROCESSED_DIR / "halifax_control_totals.csv", all_controls, CONTROL_TOTAL_COLUMNS)
    return {"files": len(csvs), "transactions": len(all_transactions), "balances": len(all_balances), "issues": len(all_issues)}


if __name__ == "__main__":
    print(run())
