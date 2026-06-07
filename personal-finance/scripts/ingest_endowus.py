from __future__ import annotations

import re
from decimal import Decimal
from pathlib import Path
from typing import Any

from common import (
    BALANCE_COLUMNS,
    CONTROL_TOTAL_COLUMNS,
    HOLDING_COLUMNS,
    ISSUE_COLUMNS,
    PROCESSED_DIR,
    converted_with_fx,
    ensure_dirs,
    clean_description,
    direction_for,
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


PARSER_NAME = "ingest_endowus_pdf_v1"
TX_COLUMNS = [
    "transaction_id","owner","institution","account_id","account_name","account_type","date","posted_date","description_raw","description_clean","merchant","amount","currency","amount_sgd","fx_date","fx_rate_to_sgd","fx_source","fx_confidence","direction","category","subcategory","is_transfer_candidate","matched_transfer_id","confidence_status","source_file","source_page","source_row","parser_name","parse_confidence"
]


def files() -> list[Path]:
    paths: list[Path] = []
    for root in source_folders_for("endowus"):
        paths.extend(root.glob("*.pdf"))
    return sorted(paths)


def parse_filename(path: Path) -> tuple[str, Any, Any]:
    match = re.match(r"Endowus_Statement_(\d+)_(\d{2}_\d{2}_\d{4})_to_(\d{2}_\d{2}_\d{4})\.pdf$", path.name)
    if not match:
        return "UNKNOWN", None, None
    return match.group(1), parse_date(match.group(2).replace("_", "-")), parse_date(match.group(3).replace("_", "-"))


def money_after(label: str, text: str) -> Decimal | None:
    match = re.search(label + r".{0,120}?S\$(-?\(?[0-9,.]+\)?)", text, flags=re.IGNORECASE)
    return parse_decimal(match.group(1)) if match else None


def cash_transaction_category(tx_type: str) -> tuple[int, str, str, bool]:
    normalized = tx_type.strip().lower()
    if normalized == "withdrawal":
        return -1, "transfer", "endowus_withdrawal", True
    if normalized == "deposit":
        return 1, "transfer", "endowus_deposit", True
    if normalized == "endowus fee":
        return -1, "fees", "platform_fee", False
    if normalized == "investment":
        return -1, "investment", "endowus_cash_invested", False
    if normalized == "redemption":
        return 1, "investment", "endowus_redemption_to_cash", False
    if normalized == "cashback received":
        return 1, "income", "cashback", False
    return 1, "uncategorized", "", False


def parse_cash_transactions(path: Path, text: str, owner: str, account_id: str) -> list[dict[str, Any]]:
    if "Cash Transactions for All Goals" not in text:
        return []
    section = text.split("Cash Transactions for All Goals", 1)[1]
    section = section.split("Understanding Your Statement", 1)[0]
    rows: list[dict[str, Any]] = []
    source_file = parser_source_file(path)
    current_page = ""
    for line_no, line in enumerate(section.splitlines(), start=1):
        page_match = re.search(r"Page\s+(\d+)\s+out\s+of\s+\d+", line)
        if page_match:
            current_page = page_match.group(1)
            continue
        match = re.match(
            r"^\s*(\d{2}\s+[A-Za-z]{3}\s+\d{4})\s+"
            r"(Investment|Deposit|Endowus Fee|Redemption|Withdrawal|Cashback received)\s+"
            r"(.+?)\s{2,}(SGD Cash|SRS|CPF(?:\s+[A-Z]+)?)\s+"
            r"S\$([0-9,]+\.\d{2})\s*$",
            line,
        )
        if not match:
            continue
        tx_date = parse_date(match.group(1).replace(" ", "-"))
        tx_type = match.group(2)
        details = clean_description(match.group(3))
        funding_source = clean_description(match.group(4))
        amount = parse_decimal(match.group(5))
        if tx_date is None or amount is None:
            continue
        sign, category, subcategory, is_transfer = cash_transaction_category(tx_type)
        signed_amount = amount * Decimal(sign)
        amount_sgd, fx = converted_with_fx(signed_amount, "SGD", tx_date)
        description = f"{tx_type} | {details} | {funding_source}"
        rows.append(
            {
                "transaction_id": stable_id("tx", "endowus", source_file, account_id, tx_date, line_no, tx_type, details, signed_amount),
                "owner": owner,
                "institution": "endowus",
                "account_id": account_id,
                "account_name": "Endowus Cash Transactions",
                "account_type": "investment",
                "date": tx_date,
                "posted_date": tx_date,
                "description_raw": description,
                "description_clean": clean_description(description).lower(),
                "merchant": details,
                "amount": signed_amount,
                "currency": "SGD",
                "amount_sgd": amount_sgd,
                **fx,
                "direction": direction_for(signed_amount),
                "category": category,
                "subcategory": subcategory,
                "is_transfer_candidate": is_transfer,
                "matched_transfer_id": "",
                "confidence_status": "confirmed",
                "source_file": source_file,
                "source_page": current_page,
                "source_row": f"Cash Transactions for All Goals line {line_no}",
                "parser_name": PARSER_NAME,
                "parse_confidence": 0.9,
            }
        )
    return aggregate_cash_transfer_rows(rows)


def aggregate_cash_transfer_rows(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[Any, ...], list[dict[str, Any]]] = {}
    passthrough: list[dict[str, Any]] = []
    for row in rows:
        if row["category"] == "transfer":
            key = (
                row["owner"],
                row["account_id"],
                row["date"],
                row["posted_date"],
                row["description_raw"],
                row["currency"],
                row["source_file"],
            )
            grouped.setdefault(key, []).append(row)
        else:
            passthrough.append(row)
    aggregated: list[dict[str, Any]] = []
    for group in grouped.values():
        if len(group) == 1:
            aggregated.append(group[0])
            continue
        base = dict(group[0])
        amount = sum((row["amount"] for row in group), Decimal("0"))
        amount_sgd = sum((row["amount_sgd"] for row in group if row["amount_sgd"] is not None), Decimal("0"))
        base["amount"] = amount
        base["amount_sgd"] = amount_sgd
        base["direction"] = direction_for(amount)
        base["transaction_id"] = stable_id("tx", "endowus", base["source_file"], base["account_id"], base["date"], base["description_raw"], amount)
        base["source_page"] = ";".join(sorted({str(row.get("source_page", "")) for row in group if row.get("source_page")}))
        base["source_row"] = "; ".join(str(row.get("source_row", "")) for row in group)
        base["parse_confidence"] = 0.88
        aggregated.append(base)
    return sorted(passthrough + aggregated, key=lambda row: (str(row["date"]), str(row["description_raw"]), str(row["amount"])))


def ingest_file(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    account_id, start, end = parse_filename(path)
    owner = owner_for_path(path)
    text = extract_pdf_text(path)
    compact = " ".join(text.split())
    balances: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = parse_cash_transactions(path, text, owner, account_id)

    ending = (
        money_after(r"Investment Ending Balance", compact)
        or money_after(r"Ending Investment Value", compact)
        or money_after(r"Total Account Value", compact)
        or money_after(r"Ending balance", compact)
    )
    starting = money_after(r"Investment Starting Balance", compact) or money_after(r"Starting Investment Value", compact) or money_after(r"Starting balance", compact)
    if end and ending is not None:
        balance_sgd, fx = converted_with_fx(ending, "SGD", end)
        balances.append(
            {
                "balance_id": stable_id("bal", "endowus", parser_source_file(path), account_id, end, ending),
                "owner": owner,
                "institution": "endowus",
                "account_id": account_id,
                "account_name": "Endowus All Investment Goals",
                "account_type": "investment",
                "date": end,
                "balance": ending,
                "currency": "SGD",
                "balance_sgd": balance_sgd,
                **fx,
                "balance_type": "statement_ending_investment_balance",
                "confidence_status": "confirmed",
                "source_file": parser_source_file(path),
                "source_page": "2",
                "source_row": "Investment Ending Balance",
                "parser_name": PARSER_NAME,
                "parse_confidence": 0.93,
            }
        )
    else:
        issues.append(
            make_issue(
                "parse",
                "warning",
                owner,
                "endowus",
                account_id,
                "Could not find Endowus ending investment balance.",
                "Inspect statement text/layout and update parser.",
                value_date=end,
                source_file=parser_source_file(path),
                key=f"endowus-no-ending-{path.name}",
            )
        )

    holding_match = re.search(
        r"(Amundi Index MSCI World Fund)\s+Equity Fund\s+SRS\s+([0-9,.]+)\s+S\$([0-9,.]+)\s+S\$([0-9,.]+)\s+S\$([0-9,.]+)",
        compact,
        flags=re.IGNORECASE,
    )
    if holding_match and end:
        name = holding_match.group(1)
        quantity = parse_decimal(holding_match.group(2))
        price = parse_decimal(holding_match.group(3))
        market_value = parse_decimal(holding_match.group(5))
        market_value_sgd, fx = converted_with_fx(market_value, "SGD", end)
        holdings.append(
            {
                "holding_id": stable_id("hold", "endowus", account_id, end, name),
                "owner": owner,
                "institution": "endowus",
                "account_id": account_id,
                "date": end,
                "symbol": "",
                "name": name,
                "asset_class": "Equity Fund",
                "quantity": quantity,
                "price": price,
                "market_value": market_value,
                "currency": "SGD",
                "market_value_sgd": market_value_sgd,
                **fx,
                "confidence_status": "confirmed",
                "source_file": parser_source_file(path),
                "source_row": "page 3",
                "parser_name": PARSER_NAME,
            }
        )

    controls.append(
        {
            "control_id": stable_id("ctl", PARSER_NAME, parser_source_file(path)),
            "parser_name": PARSER_NAME,
            "source_file": parser_source_file(path),
            "owner": owner,
            "institution": "endowus",
            "account_id": account_id,
            "file_count": 1,
            "row_count": len(transactions) + len(balances) + len(holdings),
            "date_min": start,
            "date_max": end,
            "sum_credits": sum((row["amount"] for row in transactions if row["amount"] > 0), Decimal("0")),
            "sum_debits": sum((abs(row["amount"]) for row in transactions if row["amount"] < 0), Decimal("0")),
            "opening_balance": starting,
            "closing_balance": ending,
            "warning_count": len(issues),
            "failed_row_count": 1 if ending is None else 0,
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
    pdfs = files()
    for path in pdfs:
        tx, balances, holdings, issues, controls = ingest_file(path)
        all_transactions.extend(tx)
        all_balances.extend(balances)
        all_holdings.extend(holdings)
        all_issues.extend(issues)
        all_controls.extend(controls)
    write_csv(PROCESSED_DIR / "endowus_transactions.csv", all_transactions, TX_COLUMNS)
    write_csv(PROCESSED_DIR / "endowus_balances.csv", all_balances, BALANCE_COLUMNS)
    write_csv(PROCESSED_DIR / "endowus_holdings.csv", all_holdings, HOLDING_COLUMNS)
    write_csv(PROCESSED_DIR / "endowus_parse_issues.csv", all_issues, ISSUE_COLUMNS)
    write_csv(PROCESSED_DIR / "endowus_control_totals.csv", all_controls, CONTROL_TOTAL_COLUMNS)
    return {"files": len(pdfs), "transactions": len(all_transactions), "balances": len(all_balances), "holdings": len(all_holdings), "issues": len(all_issues)}


if __name__ == "__main__":
    print(run())
