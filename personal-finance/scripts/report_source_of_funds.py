from __future__ import annotations

import csv
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from common import (
    CONFIG_DIR,
    EXPORTS_DIR,
    PROCESSED_DIR,
    REPORTS_DIR,
    converted_with_fx,
    html_escape,
    html_table,
    parse_date,
    parse_decimal,
    read_csv_dicts,
    write_csv,
    write_html_report,
)


INPUT_FILE = CONFIG_DIR / "manual_source_of_funds.csv"

OUTPUT_COLUMNS = [
    "date",
    "owner",
    "event_type",
    "source_group",
    "source_name",
    "institution",
    "account_id",
    "account_name",
    "amount",
    "currency",
    "amount_sgd",
    "fx_date",
    "fx_rate_to_sgd",
    "fx_source",
    "fx_confidence",
    "confidence_status",
    "source_file",
    "source_page",
    "source_row",
    "notes",
]


def money(value: Any, currency: str = "SGD", places: int = 0) -> str:
    amount = Decimal(str(value or "0"))
    return f"{currency} {amount:,.{places}f}"


def load_rows() -> list[dict[str, Any]]:
    if not INPUT_FILE.exists():
        return []
    rows: list[dict[str, Any]] = []
    with INPUT_FILE.open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            value_date = parse_date(row.get("date"))
            amount = parse_decimal(row.get("amount"))
            amount_sgd, fx = converted_with_fx(amount, row.get("currency"), value_date)
            rows.append(
                {
                    **row,
                    "amount": amount,
                    "amount_sgd": amount_sgd,
                    **fx,
                }
            )
    rows.sort(key=lambda row: (str(row.get("date", "")), str(row.get("source_name", ""))))
    return rows


def load_evelyn_funding_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tx in read_csv_dicts(PROCESSED_DIR / "evelyn_transactions.csv"):
        if tx.get("description_clean") != "funds received":
            continue
        value_date = parse_date(tx.get("date"))
        amount = parse_decimal(tx.get("amount"))
        amount_sgd, fx = converted_with_fx(amount, tx.get("currency"), value_date)
        rows.append(
            {
                "date": tx.get("date"),
                "owner": tx.get("owner"),
                "event_type": "investment_funding",
                "source_group": "evelyn",
                "source_name": "Funds received into Evelyn GIA",
                "institution": tx.get("institution"),
                "account_id": tx.get("account_id"),
                "account_name": tx.get("account_name"),
                "amount": amount,
                "currency": tx.get("currency"),
                "amount_sgd": amount_sgd,
                **fx,
                "confidence_status": tx.get("confidence_status"),
                "source_file": tx.get("source_file"),
                "source_page": tx.get("source_page"),
                "source_row": tx.get("source_row"),
                "notes": "Funding into Evelyn investment account. This is shown separately from family/source cash because the originating bank/source still needs transfer matching.",
            }
        )
    return rows


def load_stripe_cashout_rows() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for tx in read_csv_dicts(PROCESSED_DIR / "stripe_transactions.csv"):
        if tx.get("description_clean") != "stripe equity cashout":
            continue
        value_date = parse_date(tx.get("date"))
        amount = abs(parse_decimal(tx.get("amount")) or Decimal("0"))
        amount_sgd, fx = converted_with_fx(amount, tx.get("currency"), value_date)
        rows.append(
            {
                "date": tx.get("date"),
                "owner": tx.get("owner"),
                "event_type": "employment_equity_cashout",
                "source_group": "stripe",
                "source_name": "Stripe equity cash-out",
                "institution": tx.get("institution"),
                "account_id": tx.get("account_id"),
                "account_name": tx.get("account_name"),
                "amount": amount,
                "currency": tx.get("currency"),
                "amount_sgd": amount_sgd,
                **fx,
                "confidence_status": tx.get("confidence_status"),
                "source_file": tx.get("source_file"),
                "source_page": tx.get("source_page"),
                "source_row": tx.get("source_row"),
                "notes": "Cash withdrawal from Stripe equity plan, shown as a source-of-funds cash-in to personal finances. Bank receipt still needs transfer matching.",
            }
        )
    return rows


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["event_type"], row["source_group"], row["currency"])
        item = buckets.setdefault(
            key,
            {
                "event_type": row["event_type"],
                "source_group": row["source_group"],
                "currency": row["currency"],
                "amount": Decimal("0"),
                "amount_sgd": Decimal("0"),
                "row_count": 0,
            },
        )
        item["amount"] += row.get("amount") or Decimal("0")
        item["amount_sgd"] += row.get("amount_sgd") or Decimal("0")
        item["row_count"] += 1
    return sorted(buckets.values(), key=lambda row: (row["event_type"], row["source_group"], row["currency"]))


def summarize_by_name(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    buckets: dict[tuple[str, str], dict[str, Any]] = {}
    for row in rows:
        key = (row["event_type"], row["source_name"])
        item = buckets.setdefault(
            key,
            {
                "event_type": row["event_type"],
                "source_name": row["source_name"],
                "currency": row["currency"],
                "amount": Decimal("0"),
                "amount_sgd": Decimal("0"),
                "row_count": 0,
            },
        )
        item["amount"] += row.get("amount") or Decimal("0")
        item["amount_sgd"] += row.get("amount_sgd") or Decimal("0")
        item["row_count"] += 1
    return sorted(buckets.values(), key=lambda row: (row["event_type"], -row["amount_sgd"]))


def run() -> dict[str, Any]:
    rows = load_rows() + load_evelyn_funding_rows() + load_stripe_cashout_rows()
    rows.sort(key=lambda row: (str(row.get("date", "")), str(row.get("source_name", ""))))
    write_csv(EXPORTS_DIR / "source_of_funds.csv", rows, OUTPUT_COLUMNS)
    summary = summarize(rows)
    by_name = summarize_by_name(rows)
    write_csv(
        EXPORTS_DIR / "source_of_funds_summary.csv",
        summary,
        ["event_type", "source_group", "currency", "amount", "amount_sgd", "row_count"],
    )
    write_csv(
        EXPORTS_DIR / "source_of_funds_by_name.csv",
        by_name,
        ["event_type", "source_name", "currency", "amount", "amount_sgd", "row_count"],
    )

    cash_rows = [row for row in rows if row.get("event_type") == "cash_inflow"]
    asset_rows = [row for row in rows if row.get("event_type") == "asset_valuation"]
    funding_rows = [row for row in rows if row.get("event_type") == "investment_funding"]
    stripe_cashout_rows = [row for row in rows if row.get("event_type") == "employment_equity_cashout"]
    cash_total_gbp = sum((row.get("amount") or Decimal("0")) for row in cash_rows if row.get("currency") == "GBP")
    cash_total_sgd = sum((row.get("amount_sgd") or Decimal("0")) for row in cash_rows)
    asset_total_gbp = sum((row.get("amount") or Decimal("0")) for row in asset_rows if row.get("currency") == "GBP")
    asset_total_sgd = sum((row.get("amount_sgd") or Decimal("0")) for row in asset_rows)
    funding_total_gbp = sum((row.get("amount") or Decimal("0")) for row in funding_rows if row.get("currency") == "GBP")
    funding_total_sgd = sum((row.get("amount_sgd") or Decimal("0")) for row in funding_rows)
    stripe_cashout_total_usd = sum((row.get("amount") or Decimal("0")) for row in stripe_cashout_rows if row.get("currency") == "USD")
    stripe_cashout_total_sgd = sum((row.get("amount_sgd") or Decimal("0")) for row in stripe_cashout_rows)

    body = f"""
<div class="metric-row">
  <div class="metric"><strong>{money(cash_total_gbp, "GBP", 2)}</strong><span>Confirmed family cash inflows, Sep 2022-Dec 2023</span></div>
  <div class="metric"><strong>{money(cash_total_sgd)}</strong><span>Same cash inflows converted to SGD using local FX table</span></div>
  <div class="metric"><strong>{money(asset_total_gbp, "GBP", 2)}</strong><span>Standard Chartered pension value included separately</span></div>
  <div class="metric"><strong>{money(asset_total_sgd)}</strong><span>Standard Chartered converted to SGD</span></div>
  <div class="metric"><strong>{money(funding_total_gbp, "GBP", 2)}</strong><span>Evelyn funding found in valuation reports</span></div>
  <div class="metric"><strong>{money(funding_total_sgd)}</strong><span>Evelyn funding converted to SGD</span></div>
  <div class="metric"><strong>{money(stripe_cashout_total_usd, "USD", 2)}</strong><span>Stripe equity cash-outs / withdrawals</span></div>
  <div class="metric"><strong>{money(stripe_cashout_total_sgd)}</strong><span>Stripe cash-outs converted to SGD</span></div>
</div>
<p class="warning">Premium Bonds / NS&amp;I: searched parsed transactions and raw Barclays/DBS PDF text for NS&amp;I, National Savings, Premium Bonds, NSANDI, ERNIE, and prize-payment wording. No explicit cash-out line was found, so no Premium Bonds row has been added yet. If the cash-out arrived under a family/trust name, it is already included only under that visible statement description.</p>
<p class="warning">Standard Chartered is an asset valuation, not cash received into a bank account. It is kept separate from cash inflows so the report does not double-count pension value as income.</p>
<p class="warning">Evelyn funding is a destination-side investment funding event. It confirms £250,000 entered the Evelyn GIA on 30 July 2025, but does not by itself identify the original source of those funds.</p>
<p class="warning">Stripe cash-outs are parsed from the Stripe equity plan withdrawal pages. They are source-of-funds inflows from employment equity, but the matching bank receipts still need reconciliation.</p>
<h2>Summary</h2>
{html_table(summary, ["event_type", "source_group", "currency", "amount", "amount_sgd", "row_count"])}
<h2>By Source Name</h2>
{html_table(by_name, ["event_type", "source_name", "currency", "amount", "amount_sgd", "row_count"])}
<h2>Traceable Rows</h2>
{html_table(rows, OUTPUT_COLUMNS, limit=300)}
"""
    write_html_report(REPORTS_DIR / "source_of_funds.html", "Source Of Funds", body)
    return {
        "rows": len(rows),
        "cash_total_gbp": cash_total_gbp,
        "cash_total_sgd": cash_total_sgd,
        "asset_total_gbp": asset_total_gbp,
        "asset_total_sgd": asset_total_sgd,
        "funding_total_gbp": funding_total_gbp,
        "funding_total_sgd": funding_total_sgd,
        "stripe_cashout_total_usd": stripe_cashout_total_usd,
        "stripe_cashout_total_sgd": stripe_cashout_total_sgd,
        "report": str(REPORTS_DIR / "source_of_funds.html"),
    }


if __name__ == "__main__":
    print(run())
