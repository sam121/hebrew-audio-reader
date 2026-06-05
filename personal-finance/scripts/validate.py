from __future__ import annotations

from collections import defaultdict
from datetime import date
from pathlib import Path
from typing import Any

from common import (
    CONFIG_DIR,
    EXPORTS_DIR,
    BALANCE_COLUMNS,
    HOLDING_COLUMNS,
    ISSUE_COLUMNS,
    PROCESSED_DIR,
    TRANSACTION_COLUMNS,
    ensure_dirs,
    make_issue,
    parse_date,
    read_csv_dicts,
    write_csv,
)


def load_confirmed_overrides() -> list[dict[str, str]]:
    path = CONFIG_DIR / "manual_validation_overrides.yml"
    if not path.exists():
        return []
    text = path.read_text(encoding="utf-8")
    items: list[dict[str, str]] = []
    current: dict[str, str] | None = None
    in_list = False
    for raw in text.splitlines():
        line = raw.rstrip()
        stripped = line.strip()
        if stripped == "manual_validation_overrides:":
            in_list = True
            continue
        if not in_list or not stripped or stripped.startswith("#"):
            continue
        if stripped.startswith("- "):
            if current:
                items.append(current)
            current = {}
            stripped = stripped[2:]
        if current is not None and ":" in stripped and not stripped.endswith(":"):
            key, value = stripped.split(":", 1)
            current[key.strip()] = value.strip().strip('"').strip("'")
    if current:
        items.append(current)
    return [item for item in items if item.get("status") == "confirmed"]


def apply_manual_issue_overrides(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    overrides = load_confirmed_overrides()
    if not overrides:
        return rows
    for row in rows:
        for override in overrides:
            if override.get("institution") and override["institution"] != row.get("institution"):
                continue
            if override.get("issue_type") and override["issue_type"] != row.get("issue_type"):
                continue
            if override.get("account_id") and override["account_id"] != row.get("account_id"):
                continue
            if override.get("statement_date") and override["statement_date"] != row.get("date"):
                continue
            row["status"] = "confirmed"
            action = row.get("suggested_action", "")
            row["suggested_action"] = (action + " Manual confirmation recorded in config/manual_validation_overrides.yml.").strip()
            break
    return rows


def missing_columns(rows: list[dict[str, Any]], expected: list[str]) -> list[str]:
    if not rows:
        return []
    present = set(rows[0].keys())
    return [column for column in expected if column not in present]


def traceability_issues(table: str, rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    issues: list[dict[str, Any]] = []
    for idx, row in enumerate(rows, start=2):
        source_file = row.get("source_file", "")
        source_row = row.get("source_row", "")
        if not source_file or not source_row:
            issues.append(
                make_issue(
                    "traceability",
                    "error",
                    row.get("owner", "samuel"),
                    row.get("institution", table),
                    row.get("account_id", ""),
                    f"{table} row is missing source_file or source_row traceability.",
                    "Fix the relevant ingestor so every row can be traced back to source.",
                    value_date=parse_date(row.get("date")),
                    source_file=source_file,
                    source_page=row.get("source_page", ""),
                    key=f"trace-{table}-{idx}-{row.get(table[:-1] + '_id', '')}",
                )
            )
    return issues


def fx_issues(table: str, rows: list[dict[str, str]], currency_field: str, converted_field: str) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str, str, str], int] = defaultdict(int)
    for row in rows:
        currency = (row.get(currency_field) or "").upper()
        if currency and currency != "SGD" and not row.get(converted_field):
            key = (
                row.get("owner", "samuel"),
                row.get("institution", table),
                row.get("account_id", ""),
                currency,
            )
            grouped[key] += 1
    issues: list[dict[str, Any]] = []
    for (owner, institution, account_id, currency), count in sorted(grouped.items()):
        issues.append(
            make_issue(
                "fx",
                "warning",
                owner,
                institution,
                account_id,
                f"{count} {table} rows in {currency} do not have SGD conversion because no local FX rate is configured.",
                "Add audited rates to config/fx.yml or generate a local FX table before using SGD totals.",
                key=f"fx-{table}-{owner}-{institution}-{account_id}-{currency}",
            )
        )
    return issues


def duplicate_transaction_issues(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = (
            row.get("owner", ""),
            row.get("institution", ""),
            row.get("account_id", ""),
            row.get("date", ""),
            row.get("amount", ""),
            row.get("currency", ""),
            row.get("description_clean", ""),
        )
        grouped[key].append(row)
    issues: list[dict[str, Any]] = []
    for key, group in grouped.items():
        if len(group) <= 1:
            continue
        sample = group[0]
        issues.append(
            make_issue(
                "duplicate_transaction",
                "warning",
                sample.get("owner", "samuel"),
                sample.get("institution", ""),
                sample.get("account_id", ""),
                f"{len(group)} possible duplicate transactions share account/date/amount/currency/description.",
                "Review duplicates before using transaction-level spending totals.",
                value_date=parse_date(sample.get("date")),
                source_file=sample.get("source_file", ""),
                source_page=sample.get("source_page", ""),
                key=f"duptx-{'|'.join(key)}",
            )
        )
    return issues


def duplicate_balance_issues(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        key = (
            row.get("owner", ""),
            row.get("institution", ""),
            row.get("account_id", ""),
            row.get("date", ""),
            row.get("balance", ""),
            row.get("currency", ""),
            row.get("balance_type", ""),
        )
        grouped[key].append(row)
    issues: list[dict[str, Any]] = []
    for key, group in grouped.items():
        if len(group) <= 1:
            continue
        sample = group[0]
        issues.append(
            make_issue(
                "duplicate_balance",
                "warning",
                sample.get("owner", "samuel"),
                sample.get("institution", ""),
                sample.get("account_id", ""),
                f"{len(group)} possible duplicate balances share account/date/value/currency/type.",
                "Review overlapping or duplicate source files before using balance trends.",
                value_date=parse_date(sample.get("date")),
                source_file=sample.get("source_file", ""),
                source_page=sample.get("source_page", ""),
                key=f"dupbal-{'|'.join(key)}",
            )
        )
    return issues


def duplicate_holding_issues(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, ...], list[dict[str, str]]] = defaultdict(list)
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
        )
        grouped[key].append(row)
    issues: list[dict[str, Any]] = []
    for key, group in grouped.items():
        if len(group) <= 1:
            continue
        sample = group[0]
        issues.append(
            make_issue(
                "duplicate_holding",
                "warning",
                sample.get("owner", "samuel"),
                sample.get("institution", ""),
                sample.get("account_id", ""),
                f"{len(group)} possible duplicate holdings share account/date/symbol/quantity/value.",
                "Review overlapping or duplicate source files before using holding-level reports.",
                value_date=parse_date(sample.get("date")),
                source_file=sample.get("source_file", ""),
                key=f"duphold-{'|'.join(key)}",
            )
        )
    return issues


def source_period_overlap_issues(rows: list[dict[str, str]]) -> list[dict[str, Any]]:
    grouped: dict[str, list[dict[str, str]]] = defaultdict(list)
    for row in rows:
        group_id = row.get("overlap_group", "")
        if group_id:
            grouped[group_id].append(row)
    issues: list[dict[str, Any]] = []
    for group_id, group in grouped.items():
        sample = group[0]
        files = len(group)
        period_start = min((parse_date(row.get("statement_period_start")) for row in group if parse_date(row.get("statement_period_start"))), default=None)
        period_end = max((parse_date(row.get("statement_period_end")) for row in group if parse_date(row.get("statement_period_end"))), default=None)
        issues.append(
            make_issue(
                "source_period_overlap",
                "warning",
                sample.get("owner", "samuel"),
                sample.get("institution", ""),
                sample.get("detected_account_id", ""),
                f"{files} source files have overlapping statement/export periods.",
                "Confirm these are intentional, or keep only one authoritative export/statement for the overlap.",
                value_date=period_end or period_start,
                source_file=sample.get("path", ""),
                key=f"overlap-{group_id}",
            )
        )
    return issues


def stale_balance_issues(rows: list[dict[str, str]], as_of: date | None = None) -> list[dict[str, Any]]:
    today = as_of or date.today()
    latest: dict[tuple[str, str, str], dict[str, str]] = {}
    for row in rows:
        if row.get("owner") == "samuel" and row.get("institution") == "dbs" and row.get("account_type") == "fixed_deposit":
            continue
        if row.get("institution") == "vanguard" and row.get("balance_type") == "workbook_running_balance":
            continue
        row_date = parse_date(row.get("date"))
        if not row_date:
            continue
        key = (row.get("owner", ""), row.get("institution", ""), row.get("account_id", ""))
        current = latest.get(key)
        current_date = parse_date(current.get("date")) if current else None
        if current is None or current_date is None or row_date > current_date:
            latest[key] = row
    issues: list[dict[str, Any]] = []
    for (owner, institution, account_id), row in latest.items():
        row_date = parse_date(row.get("date"))
        if not row_date:
            continue
        days_old = (today - row_date).days
        if days_old > 60:
            issues.append(
                make_issue(
                    "stale_valuation",
                    "warning",
                    owner,
                    institution,
                    account_id,
                    f"Latest balance snapshot is {days_old} days old.",
                    "Confirm whether a newer statement/export is expected for this account.",
                    value_date=row_date,
                    source_file=row.get("source_file", ""),
                    source_page=row.get("source_page", ""),
                    key=f"stale-{owner}-{institution}-{account_id}-{row_date}",
                )
            )
    return issues


def run() -> dict[str, Any]:
    ensure_dirs()
    transactions = read_csv_dicts(PROCESSED_DIR / "transactions.csv")
    balances = read_csv_dicts(PROCESSED_DIR / "balances.csv")
    holdings = read_csv_dicts(PROCESSED_DIR / "holdings.csv")
    parse_issues = read_csv_dicts(PROCESSED_DIR / "parse_issues.csv")
    inventory = read_csv_dicts(PROCESSED_DIR / "inventory_files.csv")

    issues: list[dict[str, Any]] = []
    for table_name, rows, columns in [
        ("transactions", transactions, TRANSACTION_COLUMNS),
        ("balances", balances, BALANCE_COLUMNS),
        ("holdings", holdings, HOLDING_COLUMNS),
    ]:
        missing = missing_columns(rows, columns)
        if missing:
            issues.append(
                make_issue(
                    "schema",
                    "error",
                    "samuel",
                    table_name,
                    "ALL",
                    f"{table_name} is missing required columns: {', '.join(missing)}.",
                    "Fix normalize.py or the relevant ingestor column list.",
                    key=f"schema-{table_name}",
                )
            )

    issues.extend(traceability_issues("transactions", transactions))
    issues.extend(traceability_issues("balances", balances))
    issues.extend(traceability_issues("holdings", holdings))
    issues.extend(fx_issues("transactions", transactions, "currency", "amount_sgd"))
    issues.extend(fx_issues("balances", balances, "currency", "balance_sgd"))
    issues.extend(fx_issues("holdings", holdings, "currency", "market_value_sgd"))
    issues.extend(duplicate_transaction_issues(transactions))
    issues.extend(duplicate_balance_issues(balances))
    issues.extend(duplicate_holding_issues(holdings))
    issues.extend(source_period_overlap_issues(inventory))
    issues.extend(stale_balance_issues(balances))

    # Keep parse and validation issue tables separate, then publish a combined issue table.
    issues = apply_manual_issue_overrides(issues)
    write_csv(PROCESSED_DIR / "validation_issues.csv", issues, ISSUE_COLUMNS)
    combined: dict[str, dict[str, Any]] = {}
    for row in parse_issues + issues:
        issue_id = row.get("issue_id")
        if issue_id:
            combined[issue_id] = row
    combined_rows = apply_manual_issue_overrides(list(combined.values()))
    write_csv(PROCESSED_DIR / "issues.csv", combined_rows, ISSUE_COLUMNS)
    write_csv(EXPORTS_DIR / "issues_full.csv", combined_rows, ISSUE_COLUMNS)
    return {
        "validation_issues": len(issues),
        "all_issues": len(combined),
    }


if __name__ == "__main__":
    print(run())
