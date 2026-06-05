from __future__ import annotations

from collections import defaultdict
from decimal import Decimal
from typing import Any

from common import EXPORTS_DIR, PROCESSED_DIR, REPORT_END_DATE, REPORT_START_DATE, ensure_dirs, parse_date, parse_decimal, write_csv


NET_WORTH_COLUMNS = [
    "month",
    "total_sgd_confirmed",
    "total_sgd_including_needs_review",
    "account_count",
    "missing_fx_balance_count",
    "needs_review_balance_count",
    "notes",
]

NET_WORTH_ACCOUNT_COLUMNS = [
    "month",
    "owner",
    "institution",
    "account_id",
    "account_name",
    "account_type",
    "date",
    "balance",
    "currency",
    "balance_sgd",
    "fx_date",
    "fx_rate_to_sgd",
    "fx_source",
    "fx_confidence",
    "balance_type",
    "confidence_status",
    "source_file",
    "source_page",
    "source_row",
]

NET_WORTH_CURRENCY_COLUMNS = [
    "month",
    "currency",
    "balance_original",
    "balance_sgd_known",
    "account_count",
    "missing_fx_balance_count",
]

MARCH_SNAPSHOT_COLUMNS = [
    "as_of_date",
    "total_sgd_confirmed",
    "total_sgd_including_inferred",
    "row_count",
    "notes",
]

MONTHLY_SPENDING_COLUMNS = [
    "month",
    "total_outflows_sgd_known",
    "transfer_candidate_outflows_sgd_known",
    "uncategorized_outflows_sgd_known",
    "transaction_count",
    "missing_fx_outflow_count",
    "notes",
]


def read_rows(path):
    from common import read_csv_dicts

    return read_csv_dicts(path)


def latest_monthly_balances(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    latest: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    for row in rows:
        value_date = parse_date(row.get("date"))
        if not value_date:
            continue
        month = value_date.strftime("%Y-%m")
        key = (month, row.get("owner", ""), row.get("institution", ""), row.get("account_id", ""))
        current = latest.get(key)
        if current is None or is_later_balance(row, current):
            latest[key] = row
    return [latest[key] for key in sorted(latest.keys())]


def source_row_number(row: dict[str, str]) -> int:
    try:
        return int(row.get("source_row") or 0)
    except ValueError:
        return 0


def is_later_balance(candidate: dict[str, str], current: dict[str, str]) -> bool:
    candidate_date = parse_date(candidate.get("date"))
    current_date = parse_date(current.get("date"))
    if current_date is None:
        return True
    if candidate_date is None:
        return False
    if candidate_date != current_date:
        return candidate_date > current_date
    if candidate.get("institution") == "wise":
        # Wise CSV exports are newest-first within the same day.
        return source_row_number(candidate) < source_row_number(current)
    return source_row_number(candidate) > source_row_number(current)


def filter_net_worth_balances(rows: list[dict[str, str]]) -> list[dict[str, str]]:
    filtered = []
    for row in rows:
        # Vanguard cash transaction balances are not portfolio valuations.
        if row.get("institution") == "vanguard" and row.get("balance_type") == "workbook_running_balance":
            continue
        # Samuel confirmed his DBS fixed deposits are no longer present. Amy's
        # fixed deposit statements are retained, including explicit zero rows
        # after maturity so values do not carry forward incorrectly.
        if row.get("owner") == "samuel" and row.get("institution") == "dbs" and row.get("account_type") == "fixed_deposit":
            continue
        # Samuel wants credit cards treated as spending analysis, not part of
        # the asset net-worth stack.
        if row.get("account_type") == "credit_card":
            continue
        if row.get("institution") == "stripe" and row.get("balance_type") == "future_unvested_rsu_value":
            continue
        filtered.append(row)
    return filtered


def build_net_worth_exports() -> dict[str, int]:
    balances = filter_net_worth_balances(read_rows(PROCESSED_DIR / "balances.csv"))
    latest_rows = latest_monthly_balances(balances)

    account_rows: list[dict[str, Any]] = []
    summary: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "total_sgd_confirmed": Decimal("0"),
            "total_sgd_including_needs_review": Decimal("0"),
            "account_count": 0,
            "missing_fx_balance_count": 0,
            "needs_review_balance_count": 0,
        }
    )
    by_currency: dict[tuple[str, str], dict[str, Any]] = defaultdict(
        lambda: {
            "balance_original": Decimal("0"),
            "balance_sgd_known": Decimal("0"),
            "account_count": 0,
            "missing_fx_balance_count": 0,
        }
    )

    for row in latest_rows:
        value_date = parse_date(row.get("date"))
        if not value_date:
            continue
        month = value_date.strftime("%Y-%m")
        if value_date < REPORT_START_DATE or value_date > REPORT_END_DATE:
            continue
        balance = parse_decimal(row.get("balance"))
        balance_sgd = parse_decimal(row.get("balance_sgd"))
        status = row.get("confidence_status", "")
        currency = (row.get("currency") or "").upper()
        account_rows.append(
            {
                "month": month,
                **{column: row.get(column, "") for column in NET_WORTH_ACCOUNT_COLUMNS if column != "month"},
            }
        )
        summary[month]["account_count"] += 1
        if status == "needs_review":
            summary[month]["needs_review_balance_count"] += 1
        if balance_sgd is None:
            summary[month]["missing_fx_balance_count"] += 1
        else:
            if status == "confirmed":
                summary[month]["total_sgd_confirmed"] += balance_sgd
            summary[month]["total_sgd_including_needs_review"] += balance_sgd

        ckey = (month, currency)
        by_currency[ckey]["account_count"] += 1
        if balance is not None:
            by_currency[ckey]["balance_original"] += balance
        if balance_sgd is not None:
            by_currency[ckey]["balance_sgd_known"] += balance_sgd
        else:
            by_currency[ckey]["missing_fx_balance_count"] += 1

    summary_rows = []
    for month in sorted(summary):
        if month < REPORT_START_DATE.strftime("%Y-%m"):
            continue
        item = summary[month]
        notes = []
        if item["missing_fx_balance_count"]:
            notes.append("SGD total excludes balances without local FX rates.")
        if item["needs_review_balance_count"]:
            notes.append("Some balances need review before use as valuation.")
        summary_rows.append({"month": month, **item, "notes": " ".join(notes)})

    currency_rows = [
        {"month": month, "currency": currency, **values}
        for (month, currency), values in sorted(by_currency.items())
        if month >= REPORT_START_DATE.strftime("%Y-%m")
    ]

    write_csv(EXPORTS_DIR / "net_worth_over_time.csv", summary_rows, NET_WORTH_COLUMNS)
    write_csv(EXPORTS_DIR / "net_worth_by_account.csv", account_rows, NET_WORTH_ACCOUNT_COLUMNS)
    write_csv(EXPORTS_DIR / "net_worth_by_currency.csv", currency_rows, NET_WORTH_CURRENCY_COLUMNS)
    return {
        "net_worth_months": len(summary_rows),
        "net_worth_account_rows": len(account_rows),
        "net_worth_currency_rows": len(currency_rows),
    }


def build_spending_export() -> dict[str, int]:
    transactions = read_rows(PROCESSED_DIR / "transactions.csv")
    monthly: dict[str, dict[str, Any]] = defaultdict(
        lambda: {
            "total_outflows_sgd_known": Decimal("0"),
            "transfer_candidate_outflows_sgd_known": Decimal("0"),
            "uncategorized_outflows_sgd_known": Decimal("0"),
            "transaction_count": 0,
            "missing_fx_outflow_count": 0,
        }
    )
    for row in transactions:
        tx_date = parse_date(row.get("date"))
        amount = parse_decimal(row.get("amount"))
        amount_sgd = parse_decimal(row.get("amount_sgd"))
        if not tx_date or amount is None or amount >= 0:
            continue
        if tx_date < REPORT_START_DATE or tx_date > REPORT_END_DATE:
            continue
        month = tx_date.strftime("%Y-%m")
        monthly[month]["transaction_count"] += 1
        if amount_sgd is None:
            monthly[month]["missing_fx_outflow_count"] += 1
            continue
        outflow = abs(amount_sgd)
        monthly[month]["total_outflows_sgd_known"] += outflow
        if str(row.get("is_transfer_candidate", "")).lower() == "true":
            monthly[month]["transfer_candidate_outflows_sgd_known"] += outflow
        if row.get("category") == "uncategorized":
            monthly[month]["uncategorized_outflows_sgd_known"] += outflow

    rows = []
    for month in sorted(monthly):
        item = monthly[month]
        notes = []
        if item["missing_fx_outflow_count"]:
            notes.append("Some outflows lack SGD FX conversion.")
        if item["transfer_candidate_outflows_sgd_known"]:
            notes.append("Transfer candidates are shown separately and not excluded yet.")
        rows.append({"month": month, **item, "notes": " ".join(notes)})
    write_csv(EXPORTS_DIR / "monthly_spending.csv", rows, MONTHLY_SPENDING_COLUMNS)
    return {"monthly_spending_rows": len(rows)}


def build_as_of_snapshot(as_of_text: str | None = None) -> dict[str, int]:
    as_of = parse_date(as_of_text) if as_of_text else REPORT_END_DATE
    balances = filter_net_worth_balances(read_rows(PROCESSED_DIR / "balances.csv"))
    latest: dict[tuple[str, str, str, str], dict[str, str]] = {}
    for row in balances:
        row_date = parse_date(row.get("date"))
        if not row_date or row_date > as_of:
            continue
        key = (row.get("owner", ""), row.get("institution", ""), row.get("account_id", ""), row.get("currency", ""), row.get("balance_type", ""))
        current = latest.get(key)
        if current is None or is_later_balance(row, current):
            latest[key] = row

    rows = []
    confirmed = Decimal("0")
    including = Decimal("0")
    for row in sorted(latest.values(), key=lambda r: (r.get("owner", ""), r.get("institution", ""), r.get("account_id", ""), r.get("currency", ""))):
        value = parse_decimal(row.get("balance_sgd"))
        if value is None:
            continue
        including += value
        if row.get("confidence_status") == "confirmed":
            confirmed += value
        rows.append({"as_of_date": as_of, **row})

    suffix = as_of.isoformat()
    write_csv(EXPORTS_DIR / f"net_worth_as_of_{suffix}_by_account.csv", rows, ["as_of_date"] + NET_WORTH_ACCOUNT_COLUMNS[1:])
    write_csv(
        EXPORTS_DIR / f"net_worth_as_of_{suffix}.csv",
        [
            {
                "as_of_date": as_of,
                "total_sgd_confirmed": confirmed,
                "total_sgd_including_inferred": including,
                "row_count": len(rows),
                "notes": "DBS fixed deposits excluded after Samuel confirmed they are no longer present. Vanguard uses inferred units x latest workbook transaction price.",
            }
        ],
        MARCH_SNAPSHOT_COLUMNS,
    )
    return {"as_of_snapshot_date": suffix, "as_of_snapshot_rows": len(rows)}


def run() -> dict[str, Any]:
    ensure_dirs()
    out = {}
    out.update(build_net_worth_exports())
    out.update(build_spending_export())
    out.update(build_as_of_snapshot())
    return out


if __name__ == "__main__":
    print(run())
