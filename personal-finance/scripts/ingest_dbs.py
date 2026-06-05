from __future__ import annotations

import re
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
from pdf_utils import extract_pdf_text


PARSER_NAME = "ingest_dbs_pdf_v1"
VALID_CURRENCIES = {"SGD", "GBP", "USD", "EUR", "AUD", "CAD", "CNY", "JPY", "HKD", "PHP"}
DBS_ACCOUNT_NAMES = ["DBS eMulti-Currency Autosave Account", "DBS Multiplier Account"]
MONTHS = {name: idx for idx, name in enumerate(["JAN", "FEB", "MAR", "APR", "MAY", "JUN", "JUL", "AUG", "SEP", "OCT", "NOV", "DEC"], start=1)}


def files() -> list[Path]:
    paths: list[Path] = []
    for root in source_folders_for("dbs"):
        paths.extend(root.glob("*.pdf"))
    return sorted(paths)


def parse_statement_month(path: Path) -> Any:
    match = re.search(r"_([A-Za-z]{3,9}\d{4})(?: \(\d+\))?\.pdf$", path.name)
    if not match:
        return None
    start, end = __import__("common").parse_month_token(match.group(1))
    return end


def add_balance(
    balances: list[dict[str, Any]],
    path: Path,
    *,
    owner: str,
    account_id: str,
    account_name: str,
    account_type: str,
    value_date: Any,
    balance: Any,
    currency: str,
    balance_type: str,
    source_row: str,
    confidence: str = "confirmed",
) -> None:
    if value_date is None or balance is None:
        return
    balance_sgd, fx = converted_with_fx(balance, currency, value_date)
    balances.append(
        {
            "balance_id": stable_id("bal", "dbs", parser_source_file(path), account_id, currency, value_date, balance, balance_type),
            "owner": owner,
            "institution": "dbs",
            "account_id": account_id,
            "account_name": account_name,
            "account_type": account_type,
            "date": value_date,
            "balance": balance,
            "currency": currency,
            "balance_sgd": balance_sgd,
            **fx,
            "balance_type": balance_type,
            "confidence_status": confidence,
            "source_file": parser_source_file(path),
            "source_page": "1",
            "source_row": source_row,
            "parser_name": PARSER_NAME,
            "parse_confidence": 0.9,
        }
    )


def card_or_bank_category(description: str, *, account_type: str = "bank") -> tuple[str, str, bool]:
    text = description.lower()
    if any(clue in text for clue in ["supplementary retirement scheme", "uob kay hian", "investment & securities", "buy fund", "fund mgt"]):
        return "investment", "investment_transaction", True
    if any(clue in text for clue in ["autopay", "bill payment", "payment received", "payment - thank you", "funds transfer", "fast payment", "remittance transfer", "paynow transfer", "giro payments / collections via giro", "giro standing instruction", ": i-bank", "advice | 0120", "advice | 120-"]):
        return "transfer", "internal_or_payment", True
    if any(clue in text for clue in ["fee", "charge", "finance charge", "late payment"]):
        return "fees", "bank_or_card_fee", False
    if any(clue in text for clue in ["interest", "dividend"]):
        return "income", "interest", False
    if account_type == "credit_card":
        return "uncategorized", "card_spend", False
    return "uncategorized", "bank_transaction", False


def add_transaction(
    transactions: list[dict[str, Any]],
    path: Path,
    *,
    owner: str,
    account_id: str,
    account_name: str,
    account_type: str,
    tx_date: Any,
    description: str,
    amount: Any,
    currency: str,
    source_page: str,
    source_row: str,
    confidence: str = "inferred",
) -> None:
    if tx_date is None or amount is None or not description:
        return
    amount_sgd, fx = converted_with_fx(amount, currency, tx_date)
    category, subcategory, is_transfer = card_or_bank_category(description, account_type=account_type)
    description_clean = clean_description(description).lower()
    transactions.append(
        {
            "transaction_id": stable_id("tx", "dbs", parser_source_file(path), account_id, tx_date, amount, description, source_row),
            "owner": owner,
            "institution": "dbs",
            "account_id": account_id,
            "account_name": account_name,
            "account_type": account_type,
            "date": tx_date,
            "posted_date": tx_date,
            "description_raw": description,
            "description_clean": description_clean,
            "merchant": clean_description(description.split("|", 1)[0]),
            "amount": amount,
            "currency": currency,
            "amount_sgd": amount_sgd,
            **fx,
            "direction": direction_for(amount),
            "category": category,
            "subcategory": subcategory,
            "is_transfer_candidate": is_transfer,
            "matched_transfer_id": "",
            "confidence_status": confidence,
            "source_file": parser_source_file(path),
            "source_page": source_page,
            "source_row": source_row,
            "parser_name": PARSER_NAME,
            "parse_confidence": 0.78 if confidence == "inferred" else 0.9,
        }
    )


def parse_dbs_date(text: str, statement_date: Any) -> Any:
    text = text.strip()
    parsed = parse_date(text)
    if parsed:
        return parsed
    match = re.match(r"(\d{1,2})\s+([A-Za-z]{3})$", text)
    if not match or statement_date is None:
        return None
    day = int(match.group(1))
    month = MONTHS.get(match.group(2).upper())
    if not month:
        return None
    year = statement_date.year - 1 if month > statement_date.month else statement_date.year
    return parse_date(f"{year}-{month:02d}-{day:02d}")


def amount_tokens(line: str) -> list[tuple[str, int]]:
    return [(match.group(1), match.start(1)) for match in re.finditer(r"(?<![\w.])(-?[0-9][0-9,]*\.\d{2})(?:\s+CR)?(?![\w.])", line)]


def parse_posb_transactions(path: Path, text: str, value_date: Any, owner: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    transactions: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    current_account = ""
    current_account_name = ""
    current_currency = "SGD"
    previous_balance = None
    pending: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal pending, previous_balance
        if not pending:
            return
        amount = pending["amount"]
        balance = pending.get("balance")
        if balance is not None and previous_balance is not None:
            delta = balance - previous_balance
            if abs(abs(delta) - amount) <= parse_decimal("0.05"):
                amount = delta
        elif pending.get("amount_pos", 0) < 198:
            amount = -amount
        previous_balance = balance if balance is not None else previous_balance
        add_transaction(
            transactions,
            path,
            owner=owner,
            account_id=f"{current_account}:{current_currency}",
            account_name=current_account_name or f"DBS Account {current_account}",
            account_type="bank",
            tx_date=pending["date"],
            description=" | ".join([pending["description"], *pending["continuation"]]),
            amount=amount,
            currency=current_currency,
            source_page=pending.get("page", ""),
            source_row=pending["source_row"],
            confidence="confirmed" if balance is not None and previous_balance is not None else "inferred",
        )
        pending = None

    for line_no, line in enumerate(text.splitlines(), start=1):
        account_match = re.search(r"(DBS eMulti-Currency Autosave Account|DBS Multiplier Account)\s+Account No\.\s+([0-9-]+)", line)
        if account_match:
            flush()
            current_account_name = account_match.group(1)
            current_account = account_match.group(2)
            previous_balance = None
            continue
        currency_match = re.search(r"CURRENCY:\s+([A-Z ]+)", line)
        if currency_match:
            flush()
            label = currency_match.group(1).strip().upper()
            current_currency = {
                "SINGAPORE DOLLAR": "SGD",
                "US DOLLAR": "USD",
                "UNITED STATES DOLLAR": "USD",
                "POUND STERLING": "GBP",
                "STERLING POUND": "GBP",
                "EURO": "EUR",
                "AUSTRALIAN DOLLAR": "AUD",
                "CANADIAN DOLLAR": "CAD",
                "CHINESE YUAN": "CNY",
                "JAPANESE YEN": "JPY",
                "HONG KONG DOLLAR": "HKD",
                "PHILIPPINE PESO": "PHP",
            }.get(label, current_currency)
            previous_balance = None
            continue
        brought = re.search(r"Balance Brought Forward\s+(?:[A-Z]{3}\s+)?(-?[0-9,]+\.\d{2})", line)
        if brought:
            previous_balance = parse_decimal(brought.group(1))
            continue
        carried = re.search(r"Balance Carried Forward\s+(?:[A-Z]{3}\s+)?(-?[0-9,]+\.\d{2})", line)
        if carried:
            flush()
            previous_balance = parse_decimal(carried.group(1))
            continue
        row_match = re.match(r"\s*(\d{2}/\d{2}/\d{4}|\d{1,2}\s+[A-Za-z]{3})\s+(.+?)\s*$", line)
        if row_match and current_account:
            tokens = amount_tokens(line)
            if not tokens:
                continue
            flush()
            tx_date = parse_dbs_date(row_match.group(1), value_date)
            # The right-most value is the running balance when two or more
            # money tokens are present. Single-token wrapped rows are kept with
            # an inferred sign from their column position.
            amount_text, amount_pos = tokens[0]
            balance = parse_decimal(tokens[-1][0]) if len(tokens) >= 2 else None
            pending = {
                "date": tx_date,
                "description": re.sub(r"\s+-?[0-9][0-9,]*\.\d{2}.*$", "", row_match.group(2)).strip(),
                "amount": parse_decimal(amount_text),
                "amount_pos": amount_pos,
                "balance": balance,
                "continuation": [],
                "source_row": line_no,
            }
            continue
        if pending and line.strip() and not re.search(r"^(?:SG400|Page \d+|Transaction Details|Date\s+Description)", line.strip()):
            clean = line.strip()
            if not amount_tokens(clean) and len(clean) < 100:
                pending["continuation"].append(clean)
    flush()
    return transactions, issues


def parse_posb(path: Path, text: str, value_date: Any, owner: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    balances: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    compact = " ".join(text.split())

    summary_text = re.split(r"\b(?:Transaction Details|ACCOUNT DETAILS)\b", text, maxsplit=1, flags=re.IGNORECASE)[0]
    summary_lines = [line.strip() for line in summary_text.splitlines() if line.strip()]
    account_pattern = re.compile(r"(" + "|".join(re.escape(name) for name in DBS_ACCOUNT_NAMES) + r")\s+([0-9-]+)(.*)")
    currency_row_pattern = re.compile(
        r"\b(" + "|".join(sorted(VALID_CURRENCIES)) + r")\b\s+(-?[0-9,]+\.\d{2})(?:\s+(-?[0-9,]+\.\d{2}))?"
    )

    for idx, line in enumerate(summary_lines):
        match = account_pattern.search(line)
        if not match:
            continue
        account_name = match.group(1)
        account_no = match.group(2)
        block_lines = [match.group(3)]
        for next_line in summary_lines[idx + 1 :]:
            if account_pattern.search(next_line):
                break
            if re.search(r"\b(?:Supplementary Retirement Scheme|Fixed Deposit|TOTAL DEPOSITS|Account Summary as of|Page \d+ of \d+)\b", next_line):
                break
            block_lines.append(next_line)

        seen_currencies: set[str] = set()
        for block_line in block_lines:
            for currency, original, _sgd_equivalent in currency_row_pattern.findall(block_line):
                if currency in seen_currencies:
                    continue
                seen_currencies.add(currency)
                add_balance(
                    balances,
                    path,
                    owner=owner,
                    account_id=f"{account_no}:{currency}",
                    account_name=account_name,
                    account_type="bank",
                    value_date=value_date,
                    balance=parse_decimal(original),
                    currency=currency,
                    balance_type="statement_account_summary",
                    source_row=f"{account_name} {currency}",
                )

    # Fixed deposits can hold more than one currency under the same account no.
    fixed_match = re.search(r"FIXED DEPOSIT\s+([0-9-]+)\s+(.+?)(?:Supplementary Retirement Scheme|Account Summary as of|Page \d+)", " ".join(summary_text.split()))
    if fixed_match:
        account_no = fixed_match.group(1)
        segment = fixed_match.group(2)
        found_currency_rows = False
        for currency, original, _sgd_equiv in re.findall(r"\b([A-Z]{3})\s+([\-0-9,]+\.\d{2})\s+([\-0-9,]+\.\d{2})", segment):
            if currency not in VALID_CURRENCIES:
                continue
            found_currency_rows = True
            add_balance(
                balances,
                path,
                owner=owner,
                account_id=f"{account_no}:{currency}",
                account_name="DBS Fixed Deposit",
                account_type="fixed_deposit",
                value_date=value_date,
                balance=parse_decimal(original),
                currency=currency,
                balance_type="statement_account_summary",
                source_row=f"FIXED DEPOSIT {currency}",
            )
        if not found_currency_rows and re.search(r"\b0\.00\s+0\.00\b", segment):
            add_balance(
                balances,
                path,
                owner=owner,
                account_id=f"{account_no}:GBP",
                account_name="DBS Fixed Deposit",
                account_type="fixed_deposit",
                value_date=value_date,
                balance=parse_decimal("0.00"),
                currency="GBP",
                balance_type="statement_account_summary",
                source_row="FIXED DEPOSIT zero balance",
                confidence="inferred",
            )

    srs_match = re.search(r"Supplementary Retirement Scheme Account Total:\s+SGD\s+([\-0-9,]+\.\d{2})", compact)
    if srs_match:
        add_balance(
            balances,
            path,
            owner=owner,
            account_id="0120-226610-0-223",
            account_name="DBS SRS Account",
            account_type="srs",
            value_date=value_date,
            balance=parse_decimal(srs_match.group(1)),
            currency="SGD",
            balance_type="statement_account_summary",
            source_row="Supplementary Retirement Scheme Account Total",
        )

    if not balances:
        issues.append(
            make_issue(
                "parse",
                "warning",
                owner,
                "dbs",
                "consolidated",
                "No DBS/POSB account-summary balances were extracted.",
                "Inspect the statement layout and update DBS parser.",
                value_date=value_date,
                source_file=parser_source_file(path),
                key=f"dbs-posb-no-balances-{path.name}",
            )
        )
    return balances, issues


def parse_card_tx_date(day_month: str, statement_date: Any) -> Any:
    match = re.match(r"(\d{1,2})\s+([A-Za-z]{3})", day_month.strip())
    if not match or statement_date is None:
        return None
    day = int(match.group(1))
    month = MONTHS.get(match.group(2).upper())
    if not month:
        return None
    year = statement_date.year - 1 if month > statement_date.month else statement_date.year
    return parse_date(f"{year}-{month:02d}-{day:02d}")


def parse_credit_card_transactions(path: Path, text: str, statement_date: Any, owner: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    transactions: list[dict[str, Any]] = []
    current_card = "dbs_credit_card"
    in_rows = False
    pending: dict[str, Any] | None = None

    def flush() -> None:
        nonlocal pending
        if not pending:
            return
        amount = pending["amount"]
        if not pending["is_credit"]:
            amount = -amount
        add_transaction(
            transactions,
            path,
            owner=owner,
            account_id=current_card,
            account_name="DBS Credit Card",
            account_type="credit_card",
            tx_date=pending["date"],
            description=" | ".join([pending["description"], *pending["continuation"]]),
            amount=amount,
            currency="SGD",
            source_page="",
            source_row=pending["source_row"],
            confidence="confirmed",
        )
        pending = None

    for line_no, line in enumerate(text.splitlines(), start=1):
        card_match = re.search(r"CARD NO\.:\s*([0-9 ]{12,})", line)
        if card_match:
            current_card = re.sub(r"\s+", "", card_match.group(1))
            in_rows = True
            continue
        if re.search(r"\b(?:SUB-TOTAL:|TOTAL:|GRAND TOTAL|INSTALMENT PLANS SUMMARY)\b", line):
            flush()
            in_rows = False
            continue
        if not in_rows:
            continue
        row_match = re.match(r"\s*(\d{2}\s+[A-Za-z]{3})\s+(.+?)\s+([0-9][0-9,]*\.\d{2})(\s+CR)?\s*$", line)
        if row_match:
            flush()
            pending = {
                "date": parse_card_tx_date(row_match.group(1), statement_date),
                "description": row_match.group(2).strip(),
                "amount": parse_decimal(row_match.group(3)),
                "is_credit": bool(row_match.group(4)),
                "continuation": [],
                "source_row": line_no,
            }
            continue
        if pending and line.strip() and not re.match(r"^(?:PDS_|Credit Cards|Statement of Account|\d+ of \d+)", line.strip()):
            clean = line.strip()
            if len(clean) < 80 and not re.search(r"\b(?:DATE|DESCRIPTION|AMOUNT)\b", clean):
                pending["continuation"].append(clean)
    flush()
    return transactions, []


def parse_credit_card(path: Path, text: str, fallback_date: Any, owner: str) -> tuple[list[dict[str, Any]], list[dict[str, Any]], Any]:
    compact = " ".join(text.split())
    statement_date = fallback_date
    date_match = re.search(r"STATEMENT DATE\s+CREDIT LIMIT.*?(\d{1,2}\s+[A-Za-z]{3}\s+\d{4})", compact)
    if date_match:
        statement_date = parse_date(date_match.group(1)) or fallback_date
    grand_total = None
    match = re.search(r"GRAND TOTAL FOR ALL CARD ACCOUNTS:\s+([\-0-9,]+\.\d{2})", compact)
    if match:
        grand_total = parse_decimal(match.group(1))
    balances: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    if grand_total is not None and statement_date:
        add_balance(
            balances,
            path,
            owner=owner,
            account_id="dbs_credit_cards_consolidated",
            account_name="DBS Credit Cards Consolidated",
            account_type="credit_card",
            value_date=statement_date,
            balance=-grand_total,
            currency="SGD",
            balance_type="statement_grand_total_liability",
            source_row="GRAND TOTAL FOR ALL CARD ACCOUNTS",
        )
    else:
        issues.append(
            make_issue(
                "parse",
                "warning",
                owner,
                "dbs",
                "dbs_credit_cards_consolidated",
                "Could not find DBS credit-card grand total.",
                "Inspect credit-card statement layout and update parser.",
                value_date=statement_date,
                source_file=parser_source_file(path),
                key=f"dbs-card-no-grand-total-{path.name}",
            )
        )
    return balances, issues, statement_date


def ingest_file(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    owner = owner_for_path(path)
    text = extract_pdf_text(path)
    value_date = parse_statement_month(path)
    if path.name.startswith("Credit Cards Consolidated Statement"):
        balances, issues, statement_date = parse_credit_card(path, text, value_date, owner)
        transactions, tx_issues = parse_credit_card_transactions(path, text, statement_date, owner)
        issues.extend(tx_issues)
        statement_type = "credit_card"
    else:
        balances, issues = parse_posb(path, text, value_date, owner)
        transactions, tx_issues = parse_posb_transactions(path, text, value_date, owner)
        issues.extend(tx_issues)
        statement_type = "dbs_posb"
    controls = [
        {
            "control_id": stable_id("ctl", PARSER_NAME, parser_source_file(path)),
            "parser_name": PARSER_NAME,
            "source_file": parser_source_file(path),
            "owner": owner,
            "institution": "dbs",
            "account_id": statement_type,
            "file_count": 1,
            "row_count": len(balances) + len(transactions),
            "date_min": value_date,
            "date_max": value_date,
            "sum_credits": None,
            "sum_debits": None,
            "opening_balance": None,
            "closing_balance": None,
            "warning_count": len(issues),
            "failed_row_count": 1 if issues else 0,
        }
    ]
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
    write_csv(PROCESSED_DIR / "dbs_transactions.csv", all_transactions, TRANSACTION_COLUMNS)
    write_csv(PROCESSED_DIR / "dbs_balances.csv", all_balances, BALANCE_COLUMNS)
    write_csv(PROCESSED_DIR / "dbs_parse_issues.csv", all_issues, ISSUE_COLUMNS)
    write_csv(PROCESSED_DIR / "dbs_control_totals.csv", all_controls, CONTROL_TOTAL_COLUMNS)
    return {"files": len(pdfs), "transactions": len(all_transactions), "balances": len(all_balances), "issues": len(all_issues)}


if __name__ == "__main__":
    print(run())
