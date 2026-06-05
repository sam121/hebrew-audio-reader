from __future__ import annotations

import csv
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
    clean_description,
    converted_with_fx,
    direction_for,
    ensure_dirs,
    make_issue,
    parse_date,
    parse_decimal,
    parse_yyyymm,
    parser_source_file,
    stable_id,
    write_csv,
)


PARSER_NAME = "ingest_ibkr_v1"


def ibkr_files() -> list[Path]:
    root = SOURCE_ROOT / "Sam" / "sam_ibkr"
    if not root.exists():
        return []
    return sorted(root.glob("*.csv"))


def read_ibkr_rows(path: Path) -> tuple[list[dict[str, Any]], dict[str, str], dict[str, str]]:
    section_headers: dict[str, list[str]] = {}
    rows: list[dict[str, Any]] = []
    meta: dict[str, str] = {}
    introduction: dict[str, str] = {}

    with path.open(newline="", encoding="utf-8-sig") as f:
        reader = csv.reader(f)
        for source_row, row in enumerate(reader, start=1):
            if len(row) < 2:
                continue
            section = row[0].strip()
            row_type = row[1].strip()
            payload = [cell.strip() for cell in row[2:]]
            if not section:
                continue
            if row_type == "Header":
                section_headers[section] = payload
                continue
            if row_type == "MetaInfo" and len(payload) >= 2:
                meta[f"{section}:{payload[0]}"] = payload[1]
                continue
            if row_type != "Data":
                continue
            headers = section_headers.get(section, [])
            data = {headers[i]: payload[i] if i < len(payload) else "" for i in range(len(headers))}
            if section == "Introduction":
                introduction.update(data)
            rows.append({"section": section, "source_row": source_row, "data": data})
    return rows, meta, introduction


def account_context(introduction: dict[str, str]) -> tuple[str, str]:
    account_id = introduction.get("Account", "").strip() or "UNKNOWN"
    currency = introduction.get("BaseCurrency", "").strip().upper() or introduction.get("Alias", "").strip().upper() or "USD"
    return account_id, currency


def build_balance(path: Path, account_id: str, currency: str, row: dict[str, Any]) -> dict[str, Any] | None:
    data = row["data"]
    value_date = parse_yyyymm(data.get("Date", "")) or parse_date(data.get("Date"))
    nav = parse_decimal(data.get("NAV"))
    if value_date is None or nav is None:
        return None
    balance_sgd, balance_fx = converted_with_fx(nav, currency, value_date)
    return {
        "balance_id": stable_id("bal", "ibkr", account_id, value_date, nav, row["source_row"]),
        "owner": "samuel",
        "institution": "ibkr",
        "account_id": account_id,
        "account_name": f"IBKR {account_id}",
        "account_type": "brokerage",
        "date": value_date,
        "balance": nav,
        "currency": currency,
        "balance_sgd": balance_sgd,
        **balance_fx,
        "balance_type": "monthly_nav",
        "confidence_status": "confirmed",
        "source_file": parser_source_file(path),
        "source_page": "",
        "source_row": row["source_row"],
        "parser_name": PARSER_NAME,
        "parse_confidence": 0.95,
    }


def build_holding(path: Path, account_id: str, row: dict[str, Any]) -> dict[str, Any] | None:
    data = row["data"]
    value_date = parse_date(data.get("Date"))
    if value_date is None:
        return None
    symbol = clean_description(data.get("Symbol")) or clean_description(data.get("FinancialInstrument"))
    market_value = parse_decimal(data.get("Value"))
    currency = clean_description(data.get("Currency")).upper() or "USD"
    if market_value is None:
        return None
    market_value_sgd, market_value_fx = converted_with_fx(market_value, currency, value_date)
    return {
        "holding_id": stable_id("hold", "ibkr", account_id, value_date, symbol, row["source_row"]),
        "owner": "samuel",
        "institution": "ibkr",
        "account_id": account_id,
        "date": value_date,
        "symbol": symbol,
        "name": clean_description(data.get("Description")),
        "asset_class": clean_description(data.get("FinancialInstrument")),
        "quantity": parse_decimal(data.get("Quantity")),
        "price": parse_decimal(data.get("ClosePrice")),
        "market_value": market_value,
        "currency": currency,
        "market_value_sgd": market_value_sgd,
        **market_value_fx,
        "confidence_status": "confirmed",
        "source_file": parser_source_file(path),
        "source_row": row["source_row"],
        "parser_name": PARSER_NAME,
    }


def transaction_row(
    path: Path,
    account_id: str,
    currency: str,
    source_row: int,
    tx_date: Any,
    amount: Any,
    description: str,
    category: str,
    subcategory: str,
    is_transfer_candidate: bool,
) -> dict[str, Any] | None:
    parsed_date = parse_date(tx_date)
    parsed_amount = parse_decimal(amount)
    if parsed_date is None or parsed_amount is None:
        return None
    amount_sgd, amount_fx = converted_with_fx(parsed_amount, currency, parsed_date)
    return {
        "transaction_id": stable_id("tx", "ibkr", account_id, source_row, parsed_date, parsed_amount, description),
        "owner": "samuel",
        "institution": "ibkr",
        "account_id": account_id,
        "account_name": f"IBKR {account_id}",
        "account_type": "brokerage",
        "date": parsed_date,
        "posted_date": parsed_date,
        "description_raw": description,
        "description_clean": clean_description(description).lower(),
        "merchant": "",
        "amount": parsed_amount,
        "currency": currency,
        "amount_sgd": amount_sgd,
        **amount_fx,
        "direction": direction_for(parsed_amount),
        "category": category,
        "subcategory": subcategory,
        "is_transfer_candidate": is_transfer_candidate,
        "matched_transfer_id": "",
        "confidence_status": "confirmed",
        "source_file": parser_source_file(path),
        "source_page": "",
        "source_row": source_row,
        "parser_name": PARSER_NAME,
        "parse_confidence": 0.94,
    }


def ingest_file(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    section_rows, meta, introduction = read_ibkr_rows(path)
    account_id, currency = account_context(introduction)
    transactions: list[dict[str, Any]] = []
    balances: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    credit_sum = Decimal("0")
    debit_sum = Decimal("0")
    min_date = None
    max_date = None

    for row in section_rows:
        section = row["section"]
        data = row["data"]
        if section == "Allocation by Asset Class":
            balance = build_balance(path, account_id, currency, row)
            if balance:
                balances.append(balance)
        elif section == "Open Position Summary":
            holding = build_holding(path, account_id, row)
            if holding:
                holdings.append(holding)
        elif section == "Deposits And Withdrawals":
            tx = transaction_row(
                path,
                account_id,
                currency,
                row["source_row"],
                data.get("Date"),
                data.get("Amount"),
                f"{data.get('Type', '')} | {data.get('Description', '')}",
                "transfer",
                "brokerage_cash_flow",
                True,
            )
            if tx:
                transactions.append(tx)
        elif section == "Dividends":
            tx = transaction_row(
                path,
                account_id,
                currency,
                row["source_row"],
                data.get("PayDate"),
                data.get("Amount"),
                f"Dividend | {data.get('Symbol', '')}",
                "income",
                "dividend",
                False,
            )
            if tx:
                transactions.append(tx)
        elif section == "Interest Details":
            amount = parse_decimal(data.get("Amount"))
            tx = transaction_row(
                path,
                account_id,
                currency,
                row["source_row"],
                data.get("Date"),
                data.get("Amount"),
                f"Interest | {data.get('Description', '')}",
                "income" if amount is None or amount >= 0 else "fees",
                "interest",
                False,
            )
            if tx:
                transactions.append(tx)

    for tx in transactions:
        tx_date = parse_date(tx.get("date"))
        amount = parse_decimal(tx.get("amount"))
        if tx_date:
            min_date = tx_date if min_date is None or tx_date < min_date else min_date
            max_date = tx_date if max_date is None or tx_date > max_date else max_date
        if amount is not None:
            if amount > 0:
                credit_sum += amount
            elif amount < 0:
                debit_sum += abs(amount)

    if not account_id or account_id == "UNKNOWN":
        issues.append(
            make_issue(
                "parse",
                "warning",
                "samuel",
                "ibkr",
                "UNKNOWN",
                "Could not identify IBKR account ID from Introduction section.",
                "Inspect the IBKR PortfolioAnalyst CSV Introduction rows.",
                source_file=parser_source_file(path),
                key=f"ibkr-missing-account-{path}",
            )
        )

    controls.append(
        {
            "control_id": stable_id("ctl", PARSER_NAME, parser_source_file(path)),
            "parser_name": PARSER_NAME,
            "source_file": parser_source_file(path),
            "owner": "samuel",
            "institution": "ibkr",
            "account_id": account_id,
            "file_count": 1,
            "row_count": len(transactions),
            "date_min": min_date,
            "date_max": max_date,
            "sum_credits": credit_sum,
            "sum_debits": debit_sum,
            "opening_balance": None,
            "closing_balance": balances[-1]["balance"] if balances else None,
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
    files = ibkr_files()

    for path in files:
        transactions, balances, holdings, issues, controls = ingest_file(path)
        all_transactions.extend(transactions)
        all_balances.extend(balances)
        all_holdings.extend(holdings)
        all_issues.extend(issues)
        all_controls.extend(controls)

    if not files:
        all_issues.append(
            make_issue(
                "parse",
                "error",
                "samuel",
                "ibkr",
                "ALL",
                "No IBKR CSV files were found.",
                "Check source folder path and IBKR export location.",
                key="ibkr-no-files",
            )
        )

    write_csv(PROCESSED_DIR / "ibkr_transactions.csv", all_transactions, TRANSACTION_COLUMNS)
    write_csv(PROCESSED_DIR / "ibkr_balances.csv", all_balances, BALANCE_COLUMNS)
    write_csv(PROCESSED_DIR / "ibkr_holdings.csv", all_holdings, HOLDING_COLUMNS)
    write_csv(PROCESSED_DIR / "ibkr_parse_issues.csv", all_issues, ISSUE_COLUMNS)
    write_csv(PROCESSED_DIR / "ibkr_control_totals.csv", all_controls, CONTROL_TOTAL_COLUMNS)
    return {
        "files": len(files),
        "transactions": len(all_transactions),
        "balances": len(all_balances),
        "holdings": len(all_holdings),
        "issues": len(all_issues),
    }


if __name__ == "__main__":
    print(run())
