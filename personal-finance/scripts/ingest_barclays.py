from __future__ import annotations

import re
from pathlib import Path
from typing import Any

from common import (
    BALANCE_COLUMNS,
    CONTROL_TOTAL_COLUMNS,
    ISSUE_COLUMNS,
    PROCESSED_DIR,
    SOURCE_ROOT,
    TRANSACTION_COLUMNS,
    clean_description,
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


PARSER_NAME = "ingest_barclays_pdf_v1"
MONTHS = {name: idx for idx, name in enumerate(["Jan", "Feb", "Mar", "Apr", "May", "Jun", "Jul", "Aug", "Sep", "Oct", "Nov", "Dec"], start=1)}


def files() -> list[Path]:
    root = SOURCE_ROOT / "Sam" / "sam_barclays"
    return sorted(root.glob("*.pdf")) if root.exists() else []


def parse_filename(path: Path) -> tuple[str, Any, str]:
    account = ""
    statement_date = None
    account_match = re.search(r"\bAC\s+(\d+)", path.name)
    date_match = re.search(r"(\d{2}-[A-Z]{3}-\d{2})", path.name, flags=re.IGNORECASE)
    if account_match:
        account = account_match.group(1)
    if date_match:
        statement_date = parse_date(date_match.group(1))
    if path.name.startswith("Statement of Fees"):
        statement_type = "fee_statement"
    else:
        statement_type = "regular_statement" if path.name.startswith("Statement ") else "fee_statement"
    return account, statement_date, statement_type


def money_after(label: str, text: str) -> Any:
    match = re.search(label + r"\s+(?:£\s*)?(-?£?\s*[0-9,.]+)", text, flags=re.IGNORECASE)
    return parse_decimal(match.group(1)) if match else None


def money_after_last(label: str, text: str) -> Any:
    matches = re.findall(label + r"\s+(?:£\s*)?(-?£?\s*[0-9,.]+)", text, flags=re.IGNORECASE)
    return parse_decimal(matches[-1]) if matches else None


def amount_tokens(line: str) -> list[tuple[str, int]]:
    return [(match.group(1), match.start(1)) for match in re.finditer(r"(?<![\w.])(-?[0-9][0-9,]*\.\d{2})(?![\w.])", line)]


def parse_barclays_tx_date(day_month: str, statement_date: Any) -> Any:
    match = re.match(r"(\d{1,2})\s+([A-Za-z]{3})", day_month.strip())
    if not match or statement_date is None:
        return None
    day = int(match.group(1))
    month = MONTHS.get(match.group(2).title())
    if not month:
        return None
    year = statement_date.year - 1 if month > statement_date.month else statement_date.year
    return parse_date(f"{year}-{month:02d}-{day:02d}")


def barclays_category(description: str) -> tuple[str, str, bool]:
    text = description.lower()
    if any(clue in text for clue in ["payment to", "received from", "transfer", "standing order", "bank giro"]):
        return "transfer", "bank_transfer", True
    if any(clue in text for clue in ["interest"]):
        return "income", "interest", False
    if any(clue in text for clue in ["fee", "charge"]):
        return "fees", "bank_fee", False
    return "uncategorized", "bank_transaction", False


def add_transaction(
    transactions: list[dict[str, Any]],
    path: Path,
    *,
    account_id: str,
    tx_date: Any,
    description: str,
    amount: Any,
    source_row: str,
    confidence: str = "inferred",
) -> None:
    if tx_date is None or amount is None or not description:
        return
    amount_sgd, fx = converted_with_fx(amount, "GBP", tx_date)
    category, subcategory, is_transfer = barclays_category(description)
    transactions.append(
        {
            "transaction_id": stable_id("tx", "barclays", parser_source_file(path), account_id, tx_date, amount, description, source_row),
            "owner": "samuel",
            "institution": "barclays",
            "account_id": account_id,
            "account_name": f"Barclays Account {account_id}",
            "account_type": "bank",
            "date": tx_date,
            "posted_date": tx_date,
            "description_raw": description,
            "description_clean": clean_description(description).lower(),
            "merchant": clean_description(description.split("|", 1)[0]),
            "amount": amount,
            "currency": "GBP",
            "amount_sgd": amount_sgd,
            **fx,
            "direction": direction_for(amount),
            "category": category,
            "subcategory": subcategory,
            "is_transfer_candidate": is_transfer,
            "matched_transfer_id": "",
            "confidence_status": confidence,
            "source_file": parser_source_file(path),
            "source_page": "",
            "source_row": source_row,
            "parser_name": PARSER_NAME,
            "parse_confidence": 0.82 if confidence == "inferred" else 0.92,
        }
    )


def parse_transactions(path: Path, text: str, account_id: str, statement_date: Any) -> list[dict[str, Any]]:
    transactions: list[dict[str, Any]] = []
    in_table = False
    previous_balance = None
    pending: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal pending, previous_balance
        if not pending:
            return
        description = " | ".join([pending["description"], *pending["continuation"]])
        amount = pending["amount"]
        balance = pending.get("balance")
        confidence = "inferred"
        if balance is not None and previous_balance is not None:
            delta = balance - previous_balance
            if abs(abs(delta) - amount) <= parse_decimal("0.05"):
                amount = delta
                confidence = "confirmed"
        elif pending.get("amount_pos", 0) < 85:
            amount = -amount
        previous_balance = balance if balance is not None else previous_balance
        if "start balance" not in description.lower() and "end balance" not in description.lower() and "no transactions within the period" not in description.lower():
            add_transaction(
                transactions,
                path,
                account_id=account_id,
                tx_date=pending["date"],
                description=description,
                amount=amount,
                source_row=pending["source_row"],
                confidence=confidence,
            )
        pending = None

    for line_no, line in enumerate(text.splitlines(), start=1):
        if "Date" in line and "Description" in line and "Money out" in line and "Money in" in line and "Balance" in line:
            in_table = True
            continue
        if not in_table:
            continue
        if re.search(r"\b(?:Anything Wrong|Credit interest rates|Sort code|How it works)\b", line):
            flush()
            in_table = False
            continue
        row_match = re.match(r"\s*(\d{1,2}\s+[A-Za-z]{3})\s+(.+?)\s*$", line)
        if row_match:
            tokens = amount_tokens(line)
            if not tokens:
                continue
            flush()
            tx_date = parse_barclays_tx_date(row_match.group(1), statement_date)
            description = re.sub(r"\s+-?[0-9][0-9,]*\.\d{2}.*$", "", row_match.group(2)).strip()
            if "start balance" in description.lower():
                previous_balance = parse_decimal(tokens[-1][0])
                continue
            amount_text, amount_pos = tokens[0]
            balance = parse_decimal(tokens[-1][0]) if len(tokens) >= 2 else None
            pending = {
                "date": tx_date,
                "description": description,
                "amount": parse_decimal(amount_text),
                "amount_pos": amount_pos,
                "balance": balance,
                "continuation": [],
                "source_row": line_no,
            }
            continue
        if pending and line.strip():
            clean = line.strip()
            if not amount_tokens(clean) and len(clean) < 90:
                pending["continuation"].append(clean)
    flush()
    return transactions


def ingest_file(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    account_id, statement_date, statement_type = parse_filename(path)
    text = extract_pdf_text(path)
    compact = " ".join(text.split())
    transactions: list[dict[str, Any]] = []
    balances: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []

    if statement_type != "regular_statement":
        controls.append(
            {
                "control_id": stable_id("ctl", PARSER_NAME, parser_source_file(path)),
                "parser_name": PARSER_NAME,
                "source_file": parser_source_file(path),
                "owner": "samuel",
                "institution": "barclays",
                "account_id": account_id,
                "file_count": 1,
                "row_count": 0,
                "date_min": statement_date,
                "date_max": statement_date,
                "sum_credits": None,
                "sum_debits": None,
                "opening_balance": None,
                "closing_balance": None,
                "warning_count": 0,
                "failed_row_count": 0,
            }
        )
        return transactions, balances, issues, controls

    opening = money_after(r"Start balance", compact)
    money_in = money_after_last(r"Money in", compact)
    money_out = money_after_last(r"Money out", compact)
    closing = money_after_last(r"End balance", compact)
    transactions = parse_transactions(path, text, account_id, statement_date)

    if statement_date and closing is not None:
        balance_sgd, fx = converted_with_fx(closing, "GBP", statement_date)
        balances.append(
            {
                "balance_id": stable_id("bal", "barclays", parser_source_file(path), account_id, statement_date, closing),
                "owner": "samuel",
                "institution": "barclays",
                "account_id": account_id,
                "account_name": f"Barclays Account {account_id}",
                "account_type": "bank",
                "date": statement_date,
                "balance": closing,
                "currency": "GBP",
                "balance_sgd": balance_sgd,
                **fx,
                "balance_type": "statement_closing_balance",
                "confidence_status": "confirmed",
                "source_file": parser_source_file(path),
                "source_page": "1",
                "source_row": "At a glance End balance",
                "parser_name": PARSER_NAME,
                "parse_confidence": 0.93,
            }
        )
    else:
        issues.append(
            make_issue(
                "parse",
                "warning",
                "samuel",
                "barclays",
                account_id,
                "Could not find Barclays statement end balance.",
                "Inspect the PDF text and update parser for this layout.",
                value_date=statement_date,
                source_file=parser_source_file(path),
                key=f"barclays-no-ending-{path.name}",
            )
        )

    if None not in (opening, money_in, money_out, closing):
        expected = opening + money_in - money_out
        if abs(expected - closing) > parse_decimal("0.01"):
            issues.append(
                make_issue(
                    "reconciliation",
                    "warning",
                    "samuel",
                    "barclays",
                    account_id,
                    f"At-a-glance reconciliation mismatch: opening + in - out = {expected}, closing = {closing}.",
                    "Review extracted Barclays at-a-glance values against PDF.",
                    value_date=statement_date,
                    source_file=parser_source_file(path),
                    source_page="1",
                    key=f"barclays-recon-{path.name}",
                )
            )
    else:
        issues.append(
            make_issue(
                "reconciliation",
                "info",
                "samuel",
                "barclays",
                account_id,
                "Barclays at-a-glance values were only partially extracted.",
                "This file is parsed for balance, but full statement reconciliation is partial.",
                value_date=statement_date,
                source_file=parser_source_file(path),
                source_page="1",
                key=f"barclays-partial-recon-{path.name}",
            )
        )

    controls.append(
        {
            "control_id": stable_id("ctl", PARSER_NAME, parser_source_file(path)),
            "parser_name": PARSER_NAME,
            "source_file": parser_source_file(path),
            "owner": "samuel",
            "institution": "barclays",
            "account_id": account_id,
            "file_count": 1,
            "row_count": len(balances) + len(transactions),
            "date_min": statement_date,
            "date_max": statement_date,
            "sum_credits": money_in,
            "sum_debits": money_out,
            "opening_balance": opening,
            "closing_balance": closing,
            "warning_count": len(issues),
            "failed_row_count": 1 if closing is None else 0,
        }
    )
    return transactions, balances, issues, controls


def run() -> dict[str, Any]:
    ensure_dirs()
    all_balances: list[dict[str, Any]] = []
    all_transactions: list[dict[str, Any]] = []
    all_issues: list[dict[str, Any]] = []
    all_controls: list[dict[str, Any]] = []
    pdfs = files()
    for path in pdfs:
        transactions, balances, issues, controls = ingest_file(path)
        all_transactions.extend(transactions)
        all_balances.extend(balances)
        all_issues.extend(issues)
        all_controls.extend(controls)
    write_csv(PROCESSED_DIR / "barclays_transactions.csv", all_transactions, TRANSACTION_COLUMNS)
    write_csv(PROCESSED_DIR / "barclays_balances.csv", all_balances, BALANCE_COLUMNS)
    write_csv(PROCESSED_DIR / "barclays_parse_issues.csv", all_issues, ISSUE_COLUMNS)
    write_csv(PROCESSED_DIR / "barclays_control_totals.csv", all_controls, CONTROL_TOTAL_COLUMNS)
    return {"files": len(pdfs), "transactions": len(all_transactions), "balances": len(all_balances), "issues": len(all_issues)}


if __name__ == "__main__":
    print(run())
