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


def ingest_file(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    account_id, start, end = parse_filename(path)
    owner = owner_for_path(path)
    text = extract_pdf_text(path)
    compact = " ".join(text.split())
    balances: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []
    transactions: list[dict[str, Any]] = []

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
            "row_count": len(balances) + len(holdings),
            "date_min": start,
            "date_max": end,
            "sum_credits": None,
            "sum_debits": None,
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
    write_csv(PROCESSED_DIR / "endowus_transactions.csv", all_transactions, [
        "transaction_id","owner","institution","account_id","account_name","account_type","date","posted_date","description_raw","description_clean","merchant","amount","currency","amount_sgd","fx_date","fx_rate_to_sgd","fx_source","fx_confidence","direction","category","subcategory","is_transfer_candidate","matched_transfer_id","confidence_status","source_file","source_page","source_row","parser_name","parse_confidence"
    ])
    write_csv(PROCESSED_DIR / "endowus_balances.csv", all_balances, BALANCE_COLUMNS)
    write_csv(PROCESSED_DIR / "endowus_holdings.csv", all_holdings, HOLDING_COLUMNS)
    write_csv(PROCESSED_DIR / "endowus_parse_issues.csv", all_issues, ISSUE_COLUMNS)
    write_csv(PROCESSED_DIR / "endowus_control_totals.csv", all_controls, CONTROL_TOTAL_COLUMNS)
    return {"files": len(pdfs), "balances": len(all_balances), "holdings": len(all_holdings), "issues": len(all_issues)}


if __name__ == "__main__":
    print(run())
