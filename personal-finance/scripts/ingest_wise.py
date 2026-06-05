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


PARSER_NAME = "ingest_wise_v1"


def wise_files() -> list[Path]:
    paths: list[Path] = []
    for root in source_folders_for("wise"):
        paths.extend(root.rglob("*.csv"))
    return sorted(paths)


def parse_filename(path: Path) -> tuple[str, str, str, str]:
    match = re.match(r"statement_(?P<account>\d+)_(?P<currency>[A-Z]{3})_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$", path.name)
    if not match:
        return "", "", "", ""
    return match.group("account"), match.group("currency"), match.group("start"), match.group("end")


def is_transfer_candidate(row: dict[str, str]) -> bool:
    fields = " ".join(
        [
            row.get("Description", ""),
            row.get("Transaction Type", ""),
            row.get("Transaction Details Type", ""),
            row.get("Exchange From", ""),
            row.get("Exchange To", ""),
            row.get("Payer Name", ""),
            row.get("Payee Name", ""),
        ]
    ).lower()
    clues = ["transfer", "conversion", "exchange", "deposit", "withdrawal", "sent", "received", "funding"]
    return any(clue in fields for clue in clues)


def description(row: dict[str, str]) -> str:
    parts = [
        row.get("Description"),
        row.get("Payment Reference"),
        row.get("Transaction Type"),
        row.get("Transaction Details Type"),
    ]
    return " | ".join(clean_description(part) for part in parts if clean_description(part))


def ingest_file(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    account_id, account_currency, export_start, export_end = parse_filename(path)
    owner = owner_for_path(path)
    transactions: list[dict[str, Any]] = []
    balances: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    control_rows: list[dict[str, Any]] = []
    account_name = f"Wise {account_currency} {account_id}".strip()
    credit_sum = Decimal("0")
    debit_sum = Decimal("0")
    min_date = None
    max_date = None
    opening_balance = None
    closing_balance = None
    failed = 0
    warning_count = 0

    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.DictReader(f)
        for source_row, row in enumerate(reader, start=2):
            tx_date = parse_date(row.get("Date"))
            amount = parse_decimal(row.get("Amount"))
            currency = (row.get("Currency") or account_currency).strip().upper()
            running = parse_decimal(row.get("Running Balance"))

            if tx_date is None or amount is None:
                failed += 1
                issues.append(
                    make_issue(
                        "parse",
                        "warning",
                        owner,
                        "wise",
                        account_id,
                        "Wise row could not be parsed into both date and amount.",
                        "Inspect the source CSV row and update the parser if the format changed.",
                        source_file=parser_source_file(path),
                        source_page="",
                        key=f"wise-parse-{path}-{source_row}",
                    )
                )
                continue

            min_date = tx_date if min_date is None or tx_date < min_date else min_date
            max_date = tx_date if max_date is None or tx_date > max_date else max_date
            if amount > 0:
                credit_sum += amount
            elif amount < 0:
                debit_sum += abs(amount)

            raw_description = description(row)
            amount_sgd, amount_fx = converted_with_fx(amount, currency, tx_date)
            transaction_id = stable_id("tx", "wise", account_id, row.get("TransferWise ID"), source_row, amount, tx_date)
            transactions.append(
                {
                    "transaction_id": transaction_id,
                    "owner": owner,
                    "institution": "wise",
                    "account_id": account_id,
                    "account_name": account_name,
                    "account_type": "multi_currency_account",
                    "date": tx_date,
                    "posted_date": parse_date(row.get("Date Time")) or tx_date,
                    "description_raw": raw_description,
                    "description_clean": clean_description(raw_description).lower(),
                    "merchant": clean_description(row.get("Merchant")),
                    "amount": amount,
                    "currency": currency,
                    "amount_sgd": amount_sgd,
                    **amount_fx,
                    "direction": direction_for(amount),
                    "category": "uncategorized",
                    "subcategory": "",
                    "is_transfer_candidate": is_transfer_candidate(row),
                    "matched_transfer_id": "",
                    "confidence_status": "confirmed",
                    "source_file": parser_source_file(path),
                    "source_page": "",
                    "source_row": source_row,
                    "parser_name": PARSER_NAME,
                    "parse_confidence": 0.98,
                }
            )

            if running is not None:
                balance_sgd, balance_fx = converted_with_fx(running, currency, tx_date)
                if opening_balance is None:
                    opening_balance = running - amount
                closing_balance = running
                balances.append(
                    {
                        "balance_id": stable_id("bal", "wise", account_id, source_row, tx_date, running),
                        "owner": owner,
                        "institution": "wise",
                        "account_id": account_id,
                        "account_name": account_name,
                        "account_type": "multi_currency_account",
                        "date": tx_date,
                        "balance": running,
                        "currency": currency,
                        "balance_sgd": balance_sgd,
                        **balance_fx,
                        "balance_type": "running_after_transaction",
                        "confidence_status": "confirmed",
                        "source_file": parser_source_file(path),
                        "source_page": "",
                        "source_row": source_row,
                        "parser_name": PARSER_NAME,
                        "parse_confidence": 0.98,
                    }
                )

    control_rows.append(
        {
            "control_id": stable_id("ctl", PARSER_NAME, parser_source_file(path)),
            "parser_name": PARSER_NAME,
            "source_file": parser_source_file(path),
            "owner": owner,
            "institution": "wise",
            "account_id": account_id,
            "file_count": 1,
            "row_count": len(transactions),
            "date_min": min_date,
            "date_max": max_date,
            "sum_credits": credit_sum,
            "sum_debits": debit_sum,
            "opening_balance": opening_balance,
            "closing_balance": closing_balance,
            "warning_count": warning_count,
            "failed_row_count": failed,
        }
    )
    return transactions, balances, issues, control_rows


def run() -> dict[str, Any]:
    ensure_dirs()
    all_transactions: list[dict[str, Any]] = []
    all_balances: list[dict[str, Any]] = []
    all_issues: list[dict[str, Any]] = []
    all_controls: list[dict[str, Any]] = []

    files = wise_files()
    for path in files:
        transactions, balances, issues, controls = ingest_file(path)
        all_transactions.extend(transactions)
        all_balances.extend(balances)
        all_issues.extend(issues)
        all_controls.extend(controls)

    if not files:
        all_issues.append(
            make_issue(
                "parse",
                "error",
                "unknown",
                "wise",
                "ALL",
                "No Wise CSV files were found.",
                "Check source folder path and Wise export location.",
                key="wise-no-files",
            )
        )

    write_csv(PROCESSED_DIR / "wise_transactions.csv", all_transactions, TRANSACTION_COLUMNS)
    write_csv(PROCESSED_DIR / "wise_balances.csv", all_balances, BALANCE_COLUMNS)
    write_csv(PROCESSED_DIR / "wise_parse_issues.csv", all_issues, ISSUE_COLUMNS)
    write_csv(PROCESSED_DIR / "wise_control_totals.csv", all_controls, CONTROL_TOTAL_COLUMNS)
    return {
        "files": len(files),
        "transactions": len(all_transactions),
        "balances": len(all_balances),
        "issues": len(all_issues),
    }


if __name__ == "__main__":
    print(run())
