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


PARSER_NAME = "ingest_vanguard_pdf_v1"
CURRENCY = "GBP"


def files() -> list[Path]:
    paths: list[Path] = []
    for root in source_folders_for("vanguard"):
        paths.extend(path for path in root.rglob("*") if path.suffix.lower() == ".pdf")
    return sorted(paths)


def parse_money(text: str) -> Decimal | None:
    return parse_decimal(text.replace("£", "").replace(",", "").strip())


def statement_end(text: str) -> Any:
    compact = " ".join(text.split())
    match = re.search(r"Your Vanguard Statement\s+for\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}\s+to\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", compact)
    if not match:
        match = re.search(r"for\s+\d{1,2}\s+[A-Za-z]+\s+\d{4}\s+to\s+(\d{1,2}\s+[A-Za-z]+\s+\d{4})", compact)
    if not match:
        return None
    value = match.group(1)
    for fmt in ("%d %B %Y", "%d %b %Y"):
        try:
            return datetime.strptime(value, fmt).date()
        except ValueError:
            continue
    return parse_date(value)


def product_rows(compact: str, end_date: Any) -> list[tuple[str, Decimal]]:
    rows: list[tuple[str, Decimal]] = []
    for product in ["ISA", "General Account", "Personal Pension", "Pension"]:
        match = re.search(rf"\b{re.escape(product)}\b\s+£[0-9,]+\.\d{{2}}\s+£([0-9,]+\.\d{{2}})", compact)
        if match:
            rows.append((product, parse_money(match.group(1)) or Decimal("0")))
    if not rows:
        match = re.search(r"Account total\s+£[0-9,]+\.\d{2}\s+£([0-9,]+\.\d{2})", compact)
        if match:
            rows.append(("Vanguard Account", parse_money(match.group(1)) or Decimal("0")))
    return rows


def holding_rows(text: str) -> list[tuple[str, Decimal, Decimal, Decimal]]:
    rows: list[tuple[str, Decimal, Decimal, Decimal]] = []
    pattern = re.compile(
        r"(Vanguard .+? (?:Fund|Shares))\s+([0-9,]+\.\d+)\s+£([0-9,]+\.\d+)\s+£([0-9,]+\.\d{2})",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in pattern.finditer(" ".join(text.split())):
        name = re.sub(r"\s+", " ", match.group(1)).strip()
        quantity = parse_decimal(match.group(2)) or Decimal("0")
        price = parse_money(match.group(3)) or Decimal("0")
        value = parse_money(match.group(4)) or Decimal("0")
        rows.append((name, quantity, price, value))
    return rows


def ingest_file(path: Path) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    owner = owner_for_path(path)
    text = extract_pdf_text(path)
    compact = " ".join(text.split())
    end_date = statement_end(text)
    account_match = re.search(r"Account number:\s*([A-Z0-9]+)", text)
    account_root = account_match.group(1) if account_match else "vanguard_unknown"
    balances: list[dict[str, Any]] = []
    holdings: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []

    products = product_rows(compact, end_date)
    if not end_date or not products:
        issues.append(
            make_issue(
                "parse",
                "warning",
                owner,
                "vanguard",
                account_root,
                "Could not extract Vanguard PDF statement end date and product values.",
                "Inspect statement layout and update parser if this is a different Vanguard PDF format.",
                source_file=parser_source_file(path),
                key=f"vanguard-pdf-no-value-{path.name}",
            )
        )
    for product, value in products:
        if not end_date:
            continue
        account_id = f"{account_root}:{product.lower().replace(' ', '_')}"
        account_type = "isa" if product == "ISA" else ("pension" if "Pension" in product else "investment")
        value_sgd, fx = converted_with_fx(value, CURRENCY, end_date)
        balances.append(
            {
                "balance_id": stable_id("bal", PARSER_NAME, owner, account_id, end_date, value),
                "owner": owner,
                "institution": "vanguard",
                "account_id": account_id,
                "account_name": f"Vanguard {product}",
                "account_type": account_type,
                "date": end_date,
                "balance": value,
                "currency": CURRENCY,
                "balance_sgd": value_sgd,
                **fx,
                "balance_type": "statement_product_value",
                "confidence_status": "confirmed",
                "source_file": parser_source_file(path),
                "source_page": "1",
                "source_row": product,
                "parser_name": PARSER_NAME,
                "parse_confidence": 0.96,
            }
        )

    for name, quantity, price, value in holding_rows(text):
        value_sgd, fx = converted_with_fx(value, CURRENCY, end_date)
        holdings.append(
            {
                "holding_id": stable_id("hold", PARSER_NAME, owner, account_root, end_date, name, value),
                "owner": owner,
                "institution": "vanguard",
                "account_id": account_root,
                "date": end_date,
                "symbol": "",
                "name": name,
                "asset_class": "fund",
                "quantity": quantity,
                "price": price,
                "market_value": value,
                "currency": CURRENCY,
                "market_value_sgd": value_sgd,
                **fx,
                "confidence_status": "confirmed",
                "source_file": parser_source_file(path),
                "source_row": "Your investments",
                "parser_name": PARSER_NAME,
            }
        )

    controls.append(
        {
            "control_id": stable_id("ctl", PARSER_NAME, parser_source_file(path)),
            "parser_name": PARSER_NAME,
            "source_file": parser_source_file(path),
            "owner": owner,
            "institution": "vanguard",
            "account_id": account_root,
            "file_count": 1,
            "row_count": len(balances) + len(holdings),
            "date_min": end_date,
            "date_max": end_date,
            "sum_credits": None,
            "sum_debits": None,
            "opening_balance": None,
            "closing_balance": sum((value for _product, value in products), Decimal("0")) if products else None,
            "warning_count": len(issues),
            "failed_row_count": 1 if issues else 0,
        }
    )
    return balances, holdings, issues, controls


def run() -> dict[str, Any]:
    ensure_dirs()
    all_balances: list[dict[str, Any]] = []
    all_holdings: list[dict[str, Any]] = []
    all_issues: list[dict[str, Any]] = []
    all_controls: list[dict[str, Any]] = []
    pdfs = files()
    for path in pdfs:
        balances, holdings, issues, controls = ingest_file(path)
        all_balances.extend(balances)
        all_holdings.extend(holdings)
        all_issues.extend(issues)
        all_controls.extend(controls)

    write_csv(PROCESSED_DIR / "vanguard_pdf_balances.csv", all_balances, BALANCE_COLUMNS)
    write_csv(PROCESSED_DIR / "vanguard_pdf_holdings.csv", all_holdings, HOLDING_COLUMNS)
    write_csv(PROCESSED_DIR / "vanguard_pdf_parse_issues.csv", all_issues, ISSUE_COLUMNS)
    write_csv(PROCESSED_DIR / "vanguard_pdf_control_totals.csv", all_controls, CONTROL_TOTAL_COLUMNS)
    return {"files": len(pdfs), "balances": len(all_balances), "holdings": len(all_holdings), "issues": len(all_issues)}


if __name__ == "__main__":
    print(run())
