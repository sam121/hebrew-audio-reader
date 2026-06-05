from __future__ import annotations

import csv
import re
import sys
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from common import EXPORTS_DIR, PROCESSED_DIR, REPORTS_DIR, REPORT_START_DATE, SOURCE_ROOT, converted_with_fx, html_escape, parse_date, parse_decimal, write_csv, write_html_report
from pdf_utils import extract_pdf_text


PLATFORMS = ["IBKR", "Vanguard", "Endowus", "Evelyn"]
SOURCE_SAM = SOURCE_ROOT / "Sam"


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def platform_average_sgd(series_name: str) -> tuple[Decimal, str, str, int]:
    rows = read_csv(EXPORTS_DIR / "net_worth_monthly_stacked_by_account.csv")
    values: list[Decimal] = []
    months: set[str] = set()
    for row in rows:
        if row.get("series") != series_name:
            continue
        value = parse_decimal(row.get("balance_sgd")) or Decimal("0")
        if value <= 0:
            continue
        values.append(value)
        months.add(row["month"])
    if not values:
        return Decimal("0"), "", "", 0
    return sum(values) / len(values), min(months), max(months), len(months)


def vanguard_fees() -> tuple[Decimal, Decimal, list[dict[str, Any]]]:
    fees = []
    for row in read_csv(PROCESSED_DIR / "vanguard_transactions.csv"):
        row_date = parse_date(row.get("date"))
        amount = parse_decimal(row.get("amount"))
        if not row_date or row_date < REPORT_START_DATE or amount is None or amount >= 0:
            continue
        if "account fee" not in row.get("description_clean", ""):
            continue
        fees.append(row)
    fee_gbp = sum(abs(parse_decimal(row["amount"]) or Decimal("0")) for row in fees)
    fee_sgd = sum(abs(parse_decimal(row["amount_sgd"]) or Decimal("0")) for row in fees)
    details = [
        {
            "platform": "Vanguard",
            "date": row["date"],
            "fee_type": "Account Fee",
            "amount": abs(parse_decimal(row["amount"]) or Decimal("0")),
            "currency": "GBP",
            "amount_sgd": abs(parse_decimal(row["amount_sgd"]) or Decimal("0")),
            "source_file": row["source_file"],
            "source_row": row["source_row"],
        }
        for row in fees
    ]
    return fee_gbp, fee_sgd, details


def ibkr_fees() -> tuple[Decimal, Decimal, list[dict[str, Any]]]:
    path = SOURCE_SAM / "sam_ibkr" / "SAMUEL_JAMES_ADAMS_TAYLOR_Inception_April_27_2026.csv"
    header: list[str] | None = None
    fee_usd = Decimal("0")
    with path.open(newline="", encoding="utf-8") as f:
        for row in csv.reader(f):
            if row[:2] == ["Key Statistics", "Header"]:
                header = row
            if row[:2] == ["Key Statistics", "Data"] and header:
                index = header.index("Fees & Commissions")
                fee_usd = abs(Decimal(row[index]))
                break
    fee_sgd, _fx = converted_with_fx(fee_usd, "USD", date(2026, 4, 27))
    return fee_usd, fee_sgd or Decimal("0"), [
        {
            "platform": "IBKR",
            "date": "2022-02-28 to 2026-04-27",
            "fee_type": "Fees & Commissions",
            "amount": fee_usd,
            "currency": "USD",
            "amount_sgd": fee_sgd or Decimal("0"),
            "source_file": str(path),
            "source_row": "Key Statistics / Fees & Commissions",
        }
    ]


def endowus_fees() -> tuple[Decimal, Decimal, list[dict[str, Any]]]:
    details: list[dict[str, Any]] = []
    for path in sorted((SOURCE_SAM / "sam_endowus").glob("*.pdf")):
        file_match = re.search(r"_(\d{2})_(\d{2})_(\d{4})_to_", path.name)
        statement_date = date(int(file_match.group(3)), int(file_match.group(2)), int(file_match.group(1))) if file_match else None
        if statement_date and statement_date < REPORT_START_DATE:
            continue
        text = extract_pdf_text(path)
        found_summary = False
        for match in re.finditer(r"Endowus Fee paid from (cash|redemption)\s+-?S\$\(?([0-9,]+\.\d{2})\)?", text):
            amount = Decimal(match.group(2).replace(",", ""))
            if not amount:
                continue
            found_summary = True
            details.append(
                {
                    "platform": "Endowus",
                    "date": statement_date.isoformat() if statement_date else "",
                    "fee_type": f"Endowus Fee paid from {match.group(1)}",
                    "amount": amount,
                    "currency": "SGD",
                    "amount_sgd": amount,
                    "source_file": str(path),
                    "source_row": "monthly fee summary",
                }
            )
        if found_summary:
            continue
        for match in re.finditer(r"total Endowus Fee.*?amount of S\$([0-9,]+\.\d{2})", text, re.I):
            amount = Decimal(match.group(1).replace(",", ""))
            if not amount:
                continue
            details.append(
                {
                    "platform": "Endowus",
                    "date": statement_date.isoformat() if statement_date else "",
                    "fee_type": "Endowus Fee",
                    "amount": amount,
                    "currency": "SGD",
                    "amount_sgd": amount,
                    "source_file": str(path),
                    "source_row": "old-format total fee note",
                }
            )
    fee_sgd = sum(row["amount_sgd"] for row in details)
    return fee_sgd, fee_sgd, details


def evelyn_fees() -> tuple[Decimal, Decimal, list[dict[str, Any]]]:
    details: list[dict[str, Any]] = []
    for path in sorted((SOURCE_SAM / "sam_evelyn").glob("*.pdf")):
        text = extract_pdf_text(path)
        date_match = re.search(r"_(\d{8})_", path.name)
        statement_date = date(int(date_match.group(1)[:4]), int(date_match.group(1)[4:6]), int(date_match.group(1)[6:8])) if date_match else date(2025, 12, 31)
        for label in ["Transaction Charges", "Adviser Charges", "Management Fees", "Miscellaneous Charges"]:
            match = re.search(label + r"\s+£([0-9,]+\.\d{2})", text)
            if not match:
                continue
            amount = Decimal(match.group(1).replace(",", ""))
            if not amount:
                continue
            amount_sgd, _fx = converted_with_fx(amount, "GBP", statement_date)
            details.append(
                {
                    "platform": "Evelyn",
                    "date": statement_date.isoformat(),
                    "fee_type": label,
                    "amount": amount,
                    "currency": "GBP",
                    "amount_sgd": amount_sgd or Decimal("0"),
                    "source_file": str(path),
                    "source_row": "Charges debited during period",
                }
            )
    fee_gbp = sum(row["amount"] for row in details)
    fee_sgd = sum(row["amount_sgd"] for row in details)
    return fee_gbp, fee_sgd, details


def run() -> dict[str, Any]:
    fee_extractors = {
        "IBKR": ("USD", ibkr_fees),
        "Vanguard": ("GBP", vanguard_fees),
        "Endowus": ("SGD", endowus_fees),
        "Evelyn": ("GBP", evelyn_fees),
    }
    summary = []
    details = []
    for platform, (currency, extractor) in fee_extractors.items():
        fee_original, fee_sgd, platform_details = extractor()
        avg_sgd, start_month, end_month, active_months = platform_average_sgd(platform)
        years = Decimal(active_months) / Decimal("12") if active_months else Decimal("0")
        total_bps = fee_sgd / avg_sgd * Decimal("10000") if avg_sgd else Decimal("0")
        annualized_bps = total_bps / years if years else Decimal("0")
        recurring_run_rate_bps = annualized_bps
        if platform == "Evelyn":
            # The visible Evelyn management/custody fee covers one month
            # (01.09.25-30.09.25), debited in October. Use that as the
            # recurring run-rate rather than spreading one debit across the
            # whole active data window.
            monthly_recurring_gbp = Decimal("217.49") + Decimal("41.48")
            average_statement_value_gbp = (Decimal("254512") + Decimal("262412")) / Decimal("2")
            recurring_run_rate_bps = monthly_recurring_gbp * Decimal("12") / average_statement_value_gbp * Decimal("10000")
        summary.append(
            {
                "platform": platform,
                "fee_total_original": fee_original,
                "currency": currency,
                "fee_total_sgd": fee_sgd,
                "average_active_balance_sgd": avg_sgd,
                "active_start_month": start_month,
                "active_end_month": end_month,
                "active_months": active_months,
                "total_bps_on_average_balance": total_bps,
                "annualized_bps_on_average_balance": annualized_bps,
                "recurring_run_rate_bps": recurring_run_rate_bps,
            }
        )
        details.extend(platform_details)

    write_csv(
        EXPORTS_DIR / "platform_fees_summary.csv",
        summary,
        [
            "platform",
            "fee_total_original",
            "currency",
            "fee_total_sgd",
            "average_active_balance_sgd",
            "active_start_month",
            "active_end_month",
            "active_months",
            "total_bps_on_average_balance",
            "annualized_bps_on_average_balance",
            "recurring_run_rate_bps",
        ],
    )
    write_csv(
        EXPORTS_DIR / "platform_fees_detail.csv",
        details,
        ["platform", "date", "fee_type", "amount", "currency", "amount_sgd", "source_file", "source_row"],
    )

    def money(value: Any) -> str:
        return f"{float(value):,.2f}"

    rows = "\n".join(
        "<tr>"
        f"<td>{html_escape(row['platform'])}</td>"
        f"<td>{money(row['fee_total_original'])} {html_escape(row['currency'])}</td>"
        f"<td>S${money(row['fee_total_sgd'])}</td>"
        f"<td>S${money(row['average_active_balance_sgd'])}</td>"
        f"<td>{html_escape(row['active_start_month'])} to {html_escape(row['active_end_month'])}</td>"
        f"<td>{float(row['annualized_bps_on_average_balance']):.1f}</td>"
        f"<td>{float(row['recurring_run_rate_bps']):.1f}</td>"
        "</tr>"
        for row in summary
    )
    body = f"""
<p class="warning">Fees are extracted from local statements/exports. Paid bps are annualized against the average positive monthly platform balance in the net-worth stack. Run-rate bps uses the recurring fee evidence where available. Vanguard is explicit account fees only; underlying fund OCFs are not cash transactions. Evelyn includes transaction, management, and miscellaneous/custody charges visible in the two valuation reports; its run-rate is based on the Sep 2025 monthly management/custody fee debited in Oct 2025.</p>
<table><thead><tr><th>Platform</th><th>Total fee</th><th>Total fee SGD</th><th>Avg active balance</th><th>Active period</th><th>Paid bps</th><th>Recurring run-rate bps</th></tr></thead><tbody>{rows}</tbody></table>
"""
    write_html_report(REPORTS_DIR / "platform_fees.html", "Platform Fees", body)
    return {"platforms": len(summary), "fee_rows": len(details), "report": str(REPORTS_DIR / "platform_fees.html")}


if __name__ == "__main__":
    print(run())
