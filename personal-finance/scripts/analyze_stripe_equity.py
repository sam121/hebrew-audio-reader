from __future__ import annotations

import re
from collections import defaultdict
from decimal import Decimal
from pathlib import Path
from typing import Any

from common import EXPORTS_DIR, REPORTS_DIR, SOURCE_ROOT, html_escape, write_csv, write_html_report
from pdf_utils import extract_pdf_text


SOURCE_FILE = SOURCE_ROOT / "Sam" / "stripe_shareworks" / "shareworks_transaction_detail" / "statement.pdf"


def money(value: Any) -> str:
    return f"${Decimal(str(value)):,.2f}"


def number(value: Any) -> str:
    return f"{Decimal(str(value)):,.0f}"


def clean_text(text: str) -> str:
    return text.replace("\u200b", "").replace("\xa0", " ")


def parse_decimal(value: str | None) -> Decimal:
    if value is None or not value.strip():
        return Decimal("0")
    return Decimal(value.replace(",", "").replace("$", "").strip())


def extract_field(pattern: str, text: str) -> str:
    match = re.search(pattern, text, flags=re.IGNORECASE | re.DOTALL)
    return match.group(1).strip() if match else ""


def parse_release_blocks(text: str) -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    blocks = re.split(r"(?=Share Units - Release \()", text)
    for block in blocks:
        if not block.startswith("Share Units - Release"):
            continue
        release_id = extract_field(r"Share Units - Release \(([^)]+)\)", block)
        grant_name = extract_field(r"Grant Name:\s*(.*?)(?:\s{2,}(?:Delivery Method|Release Method|Grant Date:)|\n)", block)
        grant_date = extract_field(r"Grant Date:\s*(\d{1,2}-[A-Za-z]{3}-\d{4})", block)
        release_date = extract_field(r"Release Date:\s*(\d{1,2}-[A-Za-z]{3}-\d{4})", block)
        grant_price = parse_decimal(extract_field(r"Market Price at Time of Grant:\s*\$([0-9,.]+)", block))
        release_price = parse_decimal(extract_field(r"Release Price:\s*\$([0-9,.]+)", block))
        quantity_released = parse_decimal(extract_field(r"Quantity Released:\s*([0-9,]+)", block))
        withheld = parse_decimal(extract_field(r"Number of Restricted Awards Withheld:\s*([0-9,]+)", block))
        issued = parse_decimal(extract_field(r"Number of Restricted Awards Issued:\s*([0-9,]+)", block))
        disbursed = parse_decimal(extract_field(r"Number of Restricted Awards Disbursed:\s*([0-9,]+)", block))
        sold_at_release = parse_decimal(extract_field(r"Number of Restricted Awards Sold:\s*([0-9,]+)", block))
        gross_release_value = parse_decimal(extract_field(r"Gross Release Value:\s*\$([0-9,.]+)", block))
        if not disbursed and quantity_released:
            disbursed = quantity_released - withheld - sold_at_release
        rows.append(
            {
                "release_id": release_id,
                "grant_name": " ".join(grant_name.split()),
                "grant_date": grant_date,
                "release_date": release_date,
                "grant_price_usd": grant_price,
                "release_price_usd": release_price,
                "quantity_released": quantity_released,
                "shares_withheld_for_tax": withheld,
                "shares_issued_after_tax": issued,
                "shares_disbursed_after_tax": disbursed,
                "shares_sold_at_release": sold_at_release,
                "gross_release_value_usd": gross_release_value,
                "grant_price_value_usd": quantity_released * grant_price,
            }
        )
    return rows


def parse_cancelled_securities(text: str) -> list[dict[str, Any]]:
    rows = []
    pattern = re.compile(
        r"(CS-\d+)\s+Class A Common\s+Release\s+(\d{2}-[A-Za-z]{3}-\d{4})\s+(\d{2}-[A-Za-z]{3}-\d{4})\s+Tender Offer Sale\s+([0-9,]+)\s+([0-9,]+)\s+\$([0-9,.]+)",
        flags=re.IGNORECASE,
    )
    for match in pattern.finditer(text):
        rows.append(
            {
                "security_number": match.group(1),
                "release_date": match.group(2),
                "sale_date": match.group(3),
                "shares_sold": parse_decimal(match.group(4)),
                "common_equivalents": parse_decimal(match.group(5)),
                "release_cost_basis_usd": parse_decimal(match.group(6)),
            }
        )
    return rows


def parse_sale_proceeds(text: str) -> list[dict[str, Any]]:
    rows = []
    withdrawal_pattern = re.compile(
        r"Withdrawal on .*?Withdrawal Type:\s*Withdrawal of Sale Proceeds.*?Settlement Date:\s*(\d{1,2}-[A-Za-z]{3}-\d{4}).*?Proceeds:\s*\$([0-9,.]+) USD",
        flags=re.IGNORECASE | re.DOTALL,
    )
    for match in withdrawal_pattern.finditer(text):
        rows.append({"sale_date": match.group(1), "sale_proceeds_usd": parse_decimal(match.group(2))})
    return rows


def parse_current_summary(text: str) -> dict[str, Decimal]:
    compact = " ".join(text.split())
    price_match = re.search(r"STRIPE,\s*INC\.:PRIVATE_\s*US\s+\$([0-9,.]+)\s+\$([0-9,.]+)", compact, flags=re.IGNORECASE)
    common_match = re.search(r"Common\s+([0-9,]+).*?Common\s+\$([0-9,.]+)", compact, flags=re.IGNORECASE)
    current_common_shares = parse_decimal(common_match.group(1) if common_match else "0")
    current_common_value = parse_decimal(common_match.group(2) if common_match else "0")
    current_price = parse_decimal(price_match.group(2) if price_match else "0")
    if not current_price and current_common_shares:
        current_price = current_common_value / current_common_shares
    return {
        "starting_price_usd": parse_decimal(price_match.group(1) if price_match else "0"),
        "current_price_usd": current_price,
        "current_common_shares": current_common_shares,
        "current_common_value_usd": current_common_value,
    }


def by_grant_rows(releases: list[dict[str, Any]], current_price: Decimal) -> list[dict[str, Any]]:
    grouped: dict[tuple[str, str], dict[str, Any]] = {}
    for row in releases:
        key = (row["grant_name"], row["grant_date"])
        if key not in grouped:
            grouped[key] = {
                "grant_name": row["grant_name"],
                "grant_date": row["grant_date"],
                "grant_price_usd": row["grant_price_usd"],
                "current_price_usd": current_price,
                "vested_shares": Decimal("0"),
                "gross_vested_value_usd": Decimal("0"),
                "grant_price_value_usd": Decimal("0"),
                "post_tax_shares_issued": Decimal("0"),
                "shares_withheld_for_tax": Decimal("0"),
                "if_all_vested_shares_held_today_usd": Decimal("0"),
            }
        grouped[key]["vested_shares"] += row["quantity_released"]
        grouped[key]["gross_vested_value_usd"] += row["gross_release_value_usd"]
        grouped[key]["grant_price_value_usd"] += row["grant_price_value_usd"]
        grouped[key]["post_tax_shares_issued"] += row["shares_disbursed_after_tax"]
        grouped[key]["shares_withheld_for_tax"] += row["shares_withheld_for_tax"]
    for row in grouped.values():
        row["if_all_vested_shares_held_today_usd"] = row["vested_shares"] * current_price
    return sorted(grouped.values(), key=lambda row: (row["grant_date"], row["grant_name"]))


def table(rows: list[dict[str, Any]], columns: list[str]) -> str:
    head = "".join(f"<th>{html_escape(column)}</th>" for column in columns)
    body = []
    for row in rows:
        cells = []
        for column in columns:
            value = row.get(column, "")
            if isinstance(value, Decimal):
                if "shares" in column or column == "quantity_released":
                    value = number(value)
                else:
                    value = money(value)
            cells.append(f"<td>{html_escape(value)}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def run() -> dict[str, Any]:
    text = clean_text(extract_pdf_text(SOURCE_FILE))
    summary = parse_current_summary(text)
    releases = parse_release_blocks(text)
    cancelled = parse_cancelled_securities(text)
    sales = parse_sale_proceeds(text)
    current_price = summary["current_price_usd"]

    total_vested_shares = sum((row["quantity_released"] for row in releases), Decimal("0"))
    gross_vested_value = sum((row["gross_release_value_usd"] for row in releases), Decimal("0"))
    grant_price_value = sum((row["grant_price_value_usd"] for row in releases), Decimal("0"))
    post_tax_issued_shares = sum((row["shares_disbursed_after_tax"] for row in releases), Decimal("0"))
    shares_withheld = sum((row["shares_withheld_for_tax"] for row in releases), Decimal("0"))
    tender_sold_shares = sum((row["shares_sold"] for row in cancelled), Decimal("0"))
    tender_sale_proceeds = sum((row["sale_proceeds_usd"] for row in sales), Decimal("0"))
    current_shares = summary["current_common_shares"]

    summary_rows = [
        {"metric": "Current Shareworks FMV", "value": current_price, "note": "Latest 409A/current FMV in 29-May-2026 statement."},
        {"metric": "Gross vested shares ever released", "value": total_vested_shares, "note": "Pre-tax released shares, including shares withheld for tax."},
        {"metric": "Gross vested value at release prices", "value": gross_vested_value, "note": "Sum of gross release values at each release price."},
        {"metric": "Gross vested value at grant prices", "value": grant_price_value, "note": "Released shares multiplied by Market Price at Time of Grant from each release block."},
        {"metric": "Shares withheld for tax", "value": shares_withheld, "note": "Released but withheld/sold to cover tax at vest."},
        {"metric": "Post-tax shares issued/disbursed", "value": post_tax_issued_shares, "note": "Shares actually delivered after withholding."},
        {"metric": "Tender-sold shares", "value": tender_sold_shares, "note": "Shares later cancelled via tender offer sale."},
        {"metric": "Tender sale proceeds", "value": tender_sale_proceeds, "note": "Sale proceeds rows, excluding ad-hoc tax withholding cash withdrawals."},
        {"metric": "Current common shares still held", "value": current_shares, "note": "Account Summary Common quantity."},
        {"metric": "If all gross vested shares were held today", "value": total_vested_shares * current_price, "note": "Pre-tax counterfactual: all released shares at current FMV."},
        {"metric": "If all post-tax issued shares were held today", "value": post_tax_issued_shares * current_price, "note": "More practical counterfactual: excludes shares withheld for tax."},
        {"metric": "Current value of remaining shares", "value": summary["current_common_value_usd"], "note": "Current common shares multiplied by current FMV."},
    ]

    grant_rows = by_grant_rows(releases, current_price)
    sales_by_date: dict[str, Decimal] = defaultdict(Decimal)
    for row in sales:
        sales_by_date[row["sale_date"]] += row["sale_proceeds_usd"]
    cancelled_by_date: dict[str, Decimal] = defaultdict(Decimal)
    for row in cancelled:
        cancelled_by_date[row["sale_date"]] += row["shares_sold"]
    sale_rows = [
        {
            "sale_date": date,
            "shares_sold": cancelled_by_date.get(date, Decimal("0")),
            "sale_proceeds_usd": proceeds,
            "average_sale_price_usd": proceeds / cancelled_by_date[date] if cancelled_by_date.get(date) else Decimal("0"),
        }
        for date, proceeds in sorted(sales_by_date.items())
    ]

    write_csv(
        EXPORTS_DIR / "stripe_equity_summary.csv",
        summary_rows,
        ["metric", "value", "note"],
    )
    write_csv(
        EXPORTS_DIR / "stripe_equity_releases.csv",
        releases,
        [
            "release_id",
            "grant_name",
            "grant_date",
            "release_date",
            "grant_price_usd",
            "release_price_usd",
            "quantity_released",
            "shares_withheld_for_tax",
            "shares_disbursed_after_tax",
            "gross_release_value_usd",
            "grant_price_value_usd",
        ],
    )
    write_csv(
        EXPORTS_DIR / "stripe_equity_by_grant.csv",
        grant_rows,
        [
            "grant_name",
            "grant_date",
            "grant_price_usd",
            "current_price_usd",
            "vested_shares",
            "gross_vested_value_usd",
            "grant_price_value_usd",
            "post_tax_shares_issued",
            "shares_withheld_for_tax",
            "if_all_vested_shares_held_today_usd",
        ],
    )
    write_csv(
        EXPORTS_DIR / "stripe_equity_sales.csv",
        sale_rows,
        ["sale_date", "shares_sold", "sale_proceeds_usd", "average_sale_price_usd"],
    )

    body = f"""
<p class="warning">Source: {html_escape(str(SOURCE_FILE))}. Current FMV is taken from the 29-May-2026 Shareworks statement. Values are in USD.</p>
<div class="metric-row">
  <div class="metric"><strong>{number(total_vested_shares)}</strong><span>Gross vested shares</span></div>
  <div class="metric"><strong>{money(gross_vested_value)}</strong><span>Vested value at release</span></div>
  <div class="metric"><strong>{money(tender_sale_proceeds)}</strong><span>Tender sale proceeds</span></div>
  <div class="metric"><strong>{money(total_vested_shares * current_price)}</strong><span>Gross never-sold value today</span></div>
  <div class="metric"><strong>{money(post_tax_issued_shares * current_price)}</strong><span>Post-tax never-sold value today</span></div>
</div>
<h2>Summary</h2>
{table(summary_rows, ["metric", "value", "note"])}
<h2>By Grant</h2>
{table(grant_rows, ["grant_name", "grant_date", "grant_price_usd", "current_price_usd", "vested_shares", "gross_vested_value_usd", "grant_price_value_usd", "post_tax_shares_issued", "shares_withheld_for_tax", "if_all_vested_shares_held_today_usd"])}
<h2>Sales</h2>
{table(sale_rows, ["sale_date", "shares_sold", "sale_proceeds_usd", "average_sale_price_usd"])}
"""
    write_html_report(REPORTS_DIR / "stripe_equity_analysis.html", "Stripe Equity Analysis", body)
    return {
        "releases": len(releases),
        "gross_vested_shares": str(total_vested_shares),
        "gross_vested_value_usd": str(gross_vested_value),
        "tender_sale_proceeds_usd": str(tender_sale_proceeds),
        "gross_never_sold_value_today_usd": str(total_vested_shares * current_price),
        "post_tax_never_sold_value_today_usd": str(post_tax_issued_shares * current_price),
    }


if __name__ == "__main__":
    print(run())
