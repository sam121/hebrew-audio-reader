from __future__ import annotations

import json
import csv
from datetime import timedelta
from decimal import Decimal
from pathlib import Path
from typing import Any

from common import (
    BALANCE_COLUMNS,
    CONFIG_DIR,
    CONTROL_TOTAL_COLUMNS,
    ISSUE_COLUMNS,
    PROCESSED_DIR,
    converted_with_fx,
    ensure_dirs,
    make_issue,
    parse_date,
    parse_decimal,
    stable_id,
    write_csv,
)


PARSER_NAME = "ingest_manual_legacy_pensions_v1"
CONFIG_FILE = CONFIG_DIR / "manual_legacy_pensions.json"
CSV_FILE = CONFIG_DIR / "manual_legacy_pensions.csv"


def load_config() -> dict[str, Any]:
    with CONFIG_FILE.open(encoding="utf-8") as f:
        return json.load(f)


def load_csv_accounts() -> dict[str, dict[str, Any]]:
    accounts: dict[str, dict[str, Any]] = {}
    with CSV_FILE.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            account_id = row["account_id"]
            item = accounts.setdefault(
                account_id,
                {
                    "owner": row["owner"],
                    "institution": row["institution"],
                    "account_id": account_id,
                    "account_name": row["account_name"],
                    "account_type": row["account_type"],
                    "currency": row["currency"],
                    "valuations": {},
                    "valuation_status": {},
                    "method": row["method"],
                },
            )
            item["valuations"][row["year"]] = row["value_gbp"]
            item["valuation_status"][row["year"]] = row.get("value_status", "confirmed")
    return accounts


def valuation_date(year: str, month_day: str) -> Any:
    return parse_date(f"{year}-{month_day}")


def decimal_values(values: dict[str, str]) -> dict[str, Decimal]:
    return {year: parse_decimal(value) for year, value in values.items()}


def standard_chartered_growth(config: dict[str, Any]) -> dict[str, Decimal]:
    standard = next(account for account in config["accounts"] if account["method"] == "stated_values")
    values = decimal_values(standard["valuations"])
    ratios: dict[str, Decimal] = {}
    years = sorted(values)
    for previous, current in zip(years, years[1:]):
        ratios[current] = values[current] / values[previous]
    return ratios


def inferred_values(account: dict[str, Any], growth: dict[str, Decimal]) -> dict[str, Decimal]:
    values = decimal_values(account["valuations"])
    all_years = [str(year) for year in range(2018, 2024)]
    for year in all_years:
        if year in values:
            continue
        previous = str(int(year) - 1)
        if previous in values and year in growth:
            values[year] = values[previous] * growth[year]
    # Recompute years after a later stated anchor using that stated anchor.
    for year in ["2021", "2022", "2023"]:
        previous = str(int(year) - 1)
        if year not in account["valuations"] and previous in values and year in growth:
            values[year] = values[previous] * growth[year]
    return values


def add_balance(rows: list[dict[str, Any]], config_path: Path, config: dict[str, Any], account: dict[str, Any], value_date: Any, balance: Decimal, confidence: str, source_row: str) -> None:
    balance_sgd, fx = converted_with_fx(balance, config["currency"], value_date)
    rows.append(
        {
            "balance_id": stable_id("bal", PARSER_NAME, account["account_id"], value_date, balance, source_row),
            "owner": config["owner"],
            "institution": account["institution"],
            "account_id": account["account_id"],
            "account_name": account["account_name"],
            "account_type": account["account_type"],
            "date": value_date,
            "balance": balance,
            "currency": config["currency"],
            "balance_sgd": balance_sgd,
            **fx,
            "balance_type": account["balance_type"],
            "confidence_status": confidence,
            "source_file": str(config_path.resolve()),
            "source_page": "",
            "source_row": source_row,
            "parser_name": PARSER_NAME,
            "parse_confidence": 1.0 if confidence == "confirmed" else 0.82,
        }
    )


def run() -> dict[str, Any]:
    ensure_dirs()
    balances: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    controls: list[dict[str, Any]] = []

    if not CONFIG_FILE.exists() or not CSV_FILE.exists():
        issue = make_issue(
            "parse",
            "error",
            "samuel",
            "manual_legacy_pensions",
            "ALL",
            "Manual legacy pension config files are missing.",
            "Create config/manual_legacy_pensions.json and config/manual_legacy_pensions.csv with annual pension valuation points.",
            source_file=str((CSV_FILE if not CSV_FILE.exists() else CONFIG_FILE).resolve()),
            key="manual-legacy-pensions-config-missing",
        )
        write_csv(PROCESSED_DIR / "manual_legacy_pension_balances.csv", balances, BALANCE_COLUMNS)
        write_csv(PROCESSED_DIR / "manual_legacy_pension_parse_issues.csv", [issue], ISSUE_COLUMNS)
        write_csv(PROCESSED_DIR / "manual_legacy_pension_control_totals.csv", controls, CONTROL_TOTAL_COLUMNS)
        return {"files": 0, "balances": 0, "issues": 1}

    config = load_config()
    csv_accounts = load_csv_accounts()
    config["owner"] = next(iter(csv_accounts.values()))["owner"]
    config["currency"] = next(iter(csv_accounts.values()))["currency"]
    for account in config["accounts"]:
        if account["account_id"] in csv_accounts:
            csv_account = csv_accounts[account["account_id"]]
            account["institution"] = csv_account["institution"]
            account["account_name"] = csv_account["account_name"]
            account["account_type"] = csv_account["account_type"]
            account["valuations"] = csv_account["valuations"]
            account["valuation_status"] = csv_account["valuation_status"]
    growth = standard_chartered_growth(config)
    transfer_date = parse_date(config["transfer_to_vanguard_date"])
    flat_until = transfer_date - timedelta(days=1)

    for account in config["accounts"]:
        values = decimal_values(account["valuations"]) if account["method"] == "stated_values" else inferred_values(account, growth)
        for year in sorted(values):
            value_date = valuation_date(year, config["valuation_month_day"])
            source_row = f"{account['method']} {year}"
            confidence = account.get("valuation_status", {}).get(year) or ("confirmed" if year in account["valuations"] else "inferred")
            add_balance(balances, CSV_FILE, config, account, value_date, values[year], confidence, source_row)

        last_value = values["2023"]
        add_balance(balances, CSV_FILE, config, account, valuation_date("2024", config["valuation_month_day"]), last_value, "inferred", "flat_carry_2024_april")
        add_balance(balances, CSV_FILE, config, account, flat_until, last_value, "inferred", "flat_carry_until_vanguard_transfer")
        add_balance(balances, CSV_FILE, config, account, transfer_date, Decimal("0"), "confirmed", "transferred_to_vanguard_zero_balance")

        controls.append(
            {
                "control_id": stable_id("ctl", PARSER_NAME, account["account_id"]),
                "parser_name": PARSER_NAME,
                "source_file": str(CONFIG_FILE.resolve()),
                "owner": config["owner"],
                "institution": account["institution"],
                "account_id": account["account_id"],
                "file_count": 1,
                "row_count": len([row for row in balances if row["account_id"] == account["account_id"]]),
                "date_min": min(row["date"] for row in balances if row["account_id"] == account["account_id"]),
                "date_max": max(row["date"] for row in balances if row["account_id"] == account["account_id"]),
                "sum_credits": None,
                "sum_debits": None,
                "opening_balance": None,
                "closing_balance": 0,
                "warning_count": 0,
                "failed_row_count": 0,
            }
        )

    for note_idx, note in enumerate(config.get("assumptions", []), start=1):
        issues.append(
            make_issue(
                "manual_assumption",
                "info",
                config["owner"],
                "manual_legacy_pensions",
                "ALL",
                note,
                "Review if more precise pension statements become available.",
                source_file=str(CONFIG_FILE.resolve()),
                status="confirmed",
                key=f"manual-legacy-pension-assumption-{note_idx}",
            )
        )

    write_csv(PROCESSED_DIR / "manual_legacy_pension_balances.csv", balances, BALANCE_COLUMNS)
    write_csv(PROCESSED_DIR / "manual_legacy_pension_parse_issues.csv", issues, ISSUE_COLUMNS)
    write_csv(PROCESSED_DIR / "manual_legacy_pension_control_totals.csv", controls, CONTROL_TOTAL_COLUMNS)
    return {"files": 1, "balances": len(balances), "issues": len(issues)}


if __name__ == "__main__":
    print(run())
