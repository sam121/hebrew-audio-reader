from __future__ import annotations

from pathlib import Path
from typing import Any

from common import (
    BALANCE_COLUMNS,
    CONTROL_TOTAL_COLUMNS,
    HOLDING_COLUMNS,
    ISSUE_COLUMNS,
    PROCESSED_DIR,
    TRANSACTION_COLUMNS,
    TRANSFER_COLUMNS,
    ensure_dirs,
    read_csv_dicts,
    write_csv,
)


def concat(paths: list[Path]) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in paths:
        rows.extend(read_csv_dicts(path))
    return rows


def dedupe_by(rows: list[dict[str, Any]], key: str) -> list[dict[str, Any]]:
    seen: set[str] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        value = row.get(key, "")
        if value and value in seen:
            continue
        if value:
            seen.add(value)
        out.append(row)
    return out


def dedupe_transactions(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop rows repeated by duplicate PDF statement copies.

    The source file can differ for duplicate statement downloads, so the key is
    the parsed transaction content plus parser row location. Repeated same-day
    merchant purchases on different statement rows are preserved.
    """
    seen: set[tuple[str, ...]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = (
            row.get("owner", ""),
            row.get("institution", ""),
            row.get("account_id", ""),
            row.get("date", ""),
            row.get("amount", ""),
            row.get("currency", ""),
            row.get("description_clean", ""),
            row.get("source_row", ""),
            row.get("parser_name", ""),
        )
        if all(key) and key in seen:
            continue
        if all(key):
            seen.add(key)
        out.append(row)
    return out


def dedupe_balances(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop exact repeated valuation rows from duplicate/overlapping sources.

    The key keeps balance value and balance_type, so different sub-accounts or
    genuinely different valuation rows on the same date are preserved.
    """
    seen: set[tuple[str, ...]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = (
            row.get("owner", ""),
            row.get("institution", ""),
            row.get("account_id", ""),
            row.get("date", ""),
            row.get("balance", ""),
            row.get("currency", ""),
            row.get("balance_type", ""),
            row.get("parser_name", ""),
        )
        if all(key) and key in seen:
            continue
        if all(key):
            seen.add(key)
        out.append(row)
    return out


def dedupe_holdings(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Drop exact repeated holding rows from duplicate/overlapping sources."""
    seen: set[tuple[str, ...]] = set()
    out: list[dict[str, Any]] = []
    for row in rows:
        key = (
            row.get("owner", ""),
            row.get("institution", ""),
            row.get("account_id", ""),
            row.get("date", ""),
            row.get("symbol", ""),
            row.get("quantity", ""),
            row.get("market_value", ""),
            row.get("currency", ""),
            row.get("parser_name", ""),
        )
        if all(key) and key in seen:
            continue
        if all(key):
            seen.add(key)
        out.append(row)
    return out


def run() -> dict[str, Any]:
    ensure_dirs()
    transactions = dedupe_transactions(
        concat(
            [
                PROCESSED_DIR / "wise_transactions.csv",
                PROCESSED_DIR / "ibkr_transactions.csv",
                PROCESSED_DIR / "vanguard_transactions.csv",
                PROCESSED_DIR / "evelyn_transactions.csv",
                PROCESSED_DIR / "stripe_transactions.csv",
                PROCESSED_DIR / "dbs_transactions.csv",
                PROCESSED_DIR / "barclays_transactions.csv",
                PROCESSED_DIR / "endowus_transactions.csv",
                PROCESSED_DIR / "halifax_transactions.csv",
            ]
        )
    )
    balances = dedupe_balances(concat(
        [
            PROCESSED_DIR / "wise_balances.csv",
            PROCESSED_DIR / "ibkr_balances.csv",
            PROCESSED_DIR / "vanguard_balances.csv",
            PROCESSED_DIR / "vanguard_inferred_balances.csv",
            PROCESSED_DIR / "vanguard_pdf_balances.csv",
            PROCESSED_DIR / "evelyn_balances.csv",
            PROCESSED_DIR / "stripe_balances.csv",
            PROCESSED_DIR / "manual_legacy_pension_balances.csv",
            PROCESSED_DIR / "manual_property_balances.csv",
            PROCESSED_DIR / "manual_premium_bonds_balances.csv",
            PROCESSED_DIR / "dbs_balances.csv",
            PROCESSED_DIR / "barclays_balances.csv",
            PROCESSED_DIR / "endowus_balances.csv",
            PROCESSED_DIR / "halifax_balances.csv",
        ]
    ))
    holdings = dedupe_holdings(concat([
            PROCESSED_DIR / "ibkr_holdings.csv",
            PROCESSED_DIR / "evelyn_holdings.csv",
            PROCESSED_DIR / "stripe_holdings.csv",
            PROCESSED_DIR / "endowus_holdings.csv",
            PROCESSED_DIR / "vanguard_inferred_holdings.csv",
            PROCESSED_DIR / "vanguard_pdf_holdings.csv",
        ]))
    parse_issues = dedupe_by(
        concat(
            [
                PROCESSED_DIR / "inventory_issues.csv",
                PROCESSED_DIR / "wise_parse_issues.csv",
                PROCESSED_DIR / "ibkr_parse_issues.csv",
                PROCESSED_DIR / "vanguard_parse_issues.csv",
                PROCESSED_DIR / "vanguard_inferred_parse_issues.csv",
                PROCESSED_DIR / "vanguard_pdf_parse_issues.csv",
                PROCESSED_DIR / "evelyn_parse_issues.csv",
                PROCESSED_DIR / "stripe_parse_issues.csv",
                PROCESSED_DIR / "manual_legacy_pension_parse_issues.csv",
                PROCESSED_DIR / "manual_property_parse_issues.csv",
                PROCESSED_DIR / "manual_premium_bonds_parse_issues.csv",
                PROCESSED_DIR / "dbs_parse_issues.csv",
                PROCESSED_DIR / "barclays_parse_issues.csv",
                PROCESSED_DIR / "endowus_parse_issues.csv",
                PROCESSED_DIR / "halifax_parse_issues.csv",
            ]
        ),
        "issue_id",
    )
    controls = concat(
        [
            PROCESSED_DIR / "wise_control_totals.csv",
            PROCESSED_DIR / "ibkr_control_totals.csv",
            PROCESSED_DIR / "vanguard_control_totals.csv",
            PROCESSED_DIR / "vanguard_inferred_control_totals.csv",
            PROCESSED_DIR / "vanguard_pdf_control_totals.csv",
            PROCESSED_DIR / "evelyn_control_totals.csv",
            PROCESSED_DIR / "stripe_control_totals.csv",
            PROCESSED_DIR / "manual_legacy_pension_control_totals.csv",
            PROCESSED_DIR / "manual_property_control_totals.csv",
            PROCESSED_DIR / "manual_premium_bonds_control_totals.csv",
            PROCESSED_DIR / "dbs_control_totals.csv",
            PROCESSED_DIR / "barclays_control_totals.csv",
            PROCESSED_DIR / "endowus_control_totals.csv",
            PROCESSED_DIR / "halifax_control_totals.csv",
        ]
    )

    write_csv(PROCESSED_DIR / "transactions.csv", transactions, TRANSACTION_COLUMNS)
    write_csv(PROCESSED_DIR / "balances.csv", balances, BALANCE_COLUMNS)
    write_csv(PROCESSED_DIR / "holdings.csv", holdings, HOLDING_COLUMNS)
    write_csv(PROCESSED_DIR / "parse_issues.csv", parse_issues, ISSUE_COLUMNS)
    write_csv(PROCESSED_DIR / "run_control_totals.csv", controls, CONTROL_TOTAL_COLUMNS)
    write_csv(PROCESSED_DIR / "transfers.csv", [], TRANSFER_COLUMNS)
    write_csv(PROCESSED_DIR / "unmatched_transfers.csv", [], TRANSACTION_COLUMNS)
    return {
        "transactions": len(transactions),
        "balances": len(balances),
        "holdings": len(holdings),
        "parse_issues": len(parse_issues),
        "control_totals": len(controls),
    }


if __name__ == "__main__":
    print(run())
