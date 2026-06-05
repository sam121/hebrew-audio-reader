from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import date
from decimal import Decimal
from pathlib import Path
from typing import Any

from common import EXPORTS_DIR, PROCESSED_DIR, REPORTS_DIR, REPORT_START_DATE, SOURCE_ROOT, converted_with_fx, html_escape, parse_date, parse_decimal, write_csv, write_html_report
from pdf_utils import extract_pdf_text


SOURCE_SAM = SOURCE_ROOT / "Sam"
DETAIL_COLUMNS = [
    "platform",
    "date",
    "covered_period",
    "fee_type",
    "amount",
    "currency",
    "amount_sgd",
    "charge_method",
    "recurring_status",
    "confidence",
    "source_file",
    "source_row",
    "notes",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def money(value: Any, currency: str = "SGD") -> str:
    prefix = "S$" if currency == "SGD" else f"{currency} "
    return f"{prefix}{float(value):,.2f}"


def extract_vanguard() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for row in read_csv(PROCESSED_DIR / "vanguard_transactions.csv"):
        row_date = parse_date(row.get("date"))
        amount = parse_decimal(row.get("amount"))
        if not row_date or row_date < REPORT_START_DATE or amount is None or amount >= 0:
            continue
        desc = row.get("description_raw", "")
        if "Account Fee" not in desc:
            continue
        match = re.search(r"period\s+(.+)$", desc, re.I)
        rows.append(
            {
                "platform": "Vanguard",
                "date": row_date,
                "covered_period": match.group(1) if match else "",
                "fee_type": "Account Fee",
                "amount": abs(amount),
                "currency": "GBP",
                "amount_sgd": abs(parse_decimal(row.get("amount_sgd")) or Decimal("0")),
                "charge_method": "cash account debit; sometimes preceded by sale of investments to fund fee",
                "recurring_status": "recurring quarterly platform/account fee",
                "confidence": "confirmed",
                "source_file": row.get("source_file", ""),
                "source_row": row.get("source_row", ""),
                "notes": "Underlying Vanguard fund management costs/OCFs are embedded in fund NAV and not separately debited here.",
            }
        )
    return rows


def extract_ibkr() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    path = SOURCE_SAM / "sam_ibkr" / "SAMUEL_JAMES_ADAMS_TAYLOR_Inception_April_27_2026.csv"
    header: list[str] | None = None
    with path.open(newline="", encoding="utf-8") as f:
        for csv_row in csv.reader(f):
            if csv_row[:2] == ["Key Statistics", "Header"]:
                header = csv_row
            elif csv_row[:2] == ["Key Statistics", "Data"] and header:
                fee = abs(Decimal(csv_row[header.index("Fees & Commissions")]))
                fee_sgd, _ = converted_with_fx(fee, "USD", date(2026, 4, 27))
                rows.append(
                    {
                        "platform": "IBKR",
                        "date": "2022-02-28 to 2026-04-27",
                        "covered_period": "2022-02-28 to 2026-04-27",
                        "fee_type": "Fees & Commissions",
                        "amount": fee,
                        "currency": "USD",
                        "amount_sgd": fee_sgd or Decimal("0"),
                        "charge_method": "aggregate PortfolioAnalyst field",
                        "recurring_status": "activity-based trading/commission costs",
                        "confidence": "confirmed aggregate; no dated ledger in this export",
                        "source_file": str(path),
                        "source_row": "Key Statistics / Fees & Commissions",
                        "notes": "The export does not provide a dated fee/commission ledger. Use a full IBKR activity statement for trade-by-trade commission audit.",
                    }
                )
                other = Decimal(csv_row[header.index("Other")])
                if other:
                    other_sgd, _ = converted_with_fx(abs(other), "USD", date(2026, 4, 27))
                    rows.append(
                        {
                            "platform": "IBKR",
                            "date": "2022-02-28 to 2026-04-27",
                            "covered_period": "2022-02-28 to 2026-04-27",
                            "fee_type": "Other - not classified as fee",
                            "amount": abs(other),
                            "currency": "USD",
                            "amount_sgd": other_sgd or Decimal("0"),
                            "charge_method": "aggregate PortfolioAnalyst field",
                            "recurring_status": "not treated as platform fee",
                            "confidence": "needs_review",
                            "source_file": str(path),
                            "source_row": "Key Statistics / Other",
                            "notes": "Included for visibility only; not added to fee totals.",
                        }
                    )
            elif csv_row[:2] == ["Interest Details", "Data"]:
                description = csv_row[3]
                amount = Decimal(csv_row[4])
                if amount >= 0 or "Debit Interest Paid" not in description:
                    continue
                row_date = date(int(csv_row[2][:4]), int(csv_row[2][4:6]), int(csv_row[2][6:8]))
                currency = description.split(" ", 1)[0]
                amount_sgd, _ = converted_with_fx(abs(amount), currency, row_date)
                rows.append(
                    {
                        "platform": "IBKR",
                        "date": row_date,
                        "covered_period": description,
                        "fee_type": "Debit Interest Paid",
                        "amount": abs(amount),
                        "currency": currency,
                        "amount_sgd": amount_sgd or Decimal("0"),
                        "charge_method": "cash interest debit",
                        "recurring_status": "financing cost, not platform fee",
                        "confidence": "confirmed",
                        "source_file": str(path),
                        "source_row": "Interest Details",
                        "notes": "Shown separately from platform fees/commissions.",
                    }
                )
    return rows


def statement_date_from_endowus_name(path: Path) -> date | None:
    match = re.search(r"_(\d{2})_(\d{2})_(\d{4})_to_", path.name)
    if not match:
        return None
    return date(int(match.group(3)), int(match.group(2)), int(match.group(1)))


def extract_endowus() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    for path in sorted((SOURCE_SAM / "sam_endowus").glob("*.pdf")):
        statement_date = statement_date_from_endowus_name(path)
        if statement_date and statement_date < REPORT_START_DATE:
            continue
        text = extract_pdf_text(path)
        found = False
        for match in re.finditer(r"Endowus Fee paid from (cash|redemption)\s+-?S\$\(?([0-9,]+\.\d{2})\)?", text):
            amount = Decimal(match.group(2).replace(",", ""))
            if not amount:
                continue
            found = True
            rows.append(
                {
                    "platform": "Endowus",
                    "date": statement_date or "",
                    "covered_period": "statement month; fee is usually charged after quarter end",
                    "fee_type": f"Endowus Fee paid from {match.group(1)}",
                    "amount": amount,
                    "currency": "SGD",
                    "amount_sgd": amount,
                    "charge_method": f"paid from {match.group(1)}",
                    "recurring_status": "recurring quarterly/periodic advisory-platform fee",
                    "confidence": "confirmed",
                    "source_file": str(path),
                    "source_row": "monthly fee summary",
                    "notes": "Fund TER is embedded in fund NAV. Endowus states trailer fees are rebated as cashback when applicable.",
                }
            )
        if found:
            continue
        for match in re.finditer(r"total Endowus Fee.*?amount of S\$([0-9,]+\.\d{2})", text, re.I):
            amount = Decimal(match.group(1).replace(",", ""))
            if not amount:
                continue
            rows.append(
                {
                    "platform": "Endowus",
                    "date": statement_date or "",
                    "covered_period": "old-format statement fee note",
                    "fee_type": "Endowus Fee",
                    "amount": amount,
                    "currency": "SGD",
                    "amount_sgd": amount,
                    "charge_method": "fee note / likely cash or redemption",
                    "recurring_status": "recurring quarterly/periodic advisory-platform fee",
                    "confidence": "confirmed from old-format fee note",
                    "source_file": str(path),
                    "source_row": "old-format total fee note",
                    "notes": "Old-format statements sometimes show cumulative fee tables, so this uses the explicit total fee note where present.",
                }
            )
    return rows


def extract_evelyn() -> list[dict[str, Any]]:
    rows: list[dict[str, Any]] = []
    specs = [
        (
            SOURCE_SAM / "sam_evelyn" / "Valuation Report_FNTA0001_20250930_8547526.pdf",
            date(2025, 9, 30),
            [
                ("Transaction Charges", Decimal("138.93"), "1 July 2025 to 30 September 2025", "setup/dealing charges", "one-off setup trading costs"),
            ],
        ),
        (
            SOURCE_SAM / "sam_evelyn" / "Valuation Report_FNTA0001_20251231_8547526.pdf",
            date(2025, 12, 31),
            [
                ("Management Fees", Decimal("217.49"), "01.09.25-30.09.25", "cash account debit", "monthly recurring investment management fee"),
                ("Miscellaneous Charges / Custody Fee", Decimal("41.48"), "01.09.25-30.09.25", "cash account debit", "monthly recurring custody/miscellaneous fee"),
            ],
        ),
    ]
    for path, row_date, items in specs:
        for fee_type, amount, covered_period, charge_method, recurring_status in items:
            amount_sgd, _ = converted_with_fx(amount, "GBP", row_date)
            rows.append(
                {
                    "platform": "Evelyn",
                    "date": row_date,
                    "covered_period": covered_period,
                    "fee_type": fee_type,
                    "amount": amount,
                    "currency": "GBP",
                    "amount_sgd": amount_sgd or Decimal("0"),
                    "charge_method": charge_method,
                    "recurring_status": recurring_status,
                    "confidence": "confirmed",
                    "source_file": str(path),
                    "source_row": "Charges page / Cash Statement",
                    "notes": "Performance note says performance is net of investment management fees debited from the portfolio. Underlying fund costs may be embedded in holdings' NAV and are not separately itemised here.",
                }
            )
    return rows


def summarize(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    summary = []
    by_platform: dict[str, list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        if row["fee_type"] == "Other - not classified as fee":
            continue
        by_platform[row["platform"]].append(row)
    for platform, items in sorted(by_platform.items()):
        platform_fee_items = [
            row for row in items
            if not (row["platform"] == "IBKR" and row["fee_type"] == "Debit Interest Paid")
        ]
        sgd_total = sum((parse_decimal(str(row["amount_sgd"])) or Decimal("0")) for row in platform_fee_items)
        original_by_currency: dict[str, Decimal] = defaultdict(Decimal)
        for row in platform_fee_items:
            original_by_currency[row["currency"]] += parse_decimal(str(row["amount"])) or Decimal("0")
        summary.append(
            {
                "platform": platform,
                "fee_total_sgd": sgd_total,
                "fee_total_original": "; ".join(f"{currency} {amount}" for currency, amount in sorted(original_by_currency.items())),
                "fee_row_count": len(platform_fee_items),
                "first_fee_date": min(str(row["date"]) for row in platform_fee_items),
                "last_fee_date": max(str(row["date"]) for row in platform_fee_items),
                "notes": notes_for(platform),
            }
        )
    return summary


def notes_for(platform: str) -> str:
    return {
        "IBKR": "PortfolioAnalyst gives aggregate fees/commissions only; debit interest is separately visible and excluded from platform fee total.",
        "Vanguard": "Explicit account/platform fees only; fund OCFs are embedded in NAV and not separately debited.",
        "Endowus": "Endowus advisory/platform fees are explicit; fund TER is embedded in NAV and trailer fee cashback is handled inside Endowus reporting.",
        "Evelyn": "Visible recurring run-rate is monthly management plus custody; setup transaction charges are one-off.",
    }.get(platform, "")


def run() -> dict[str, Any]:
    rows = extract_ibkr() + extract_vanguard() + extract_endowus() + extract_evelyn()
    rows.sort(key=lambda row: (row["platform"], str(row["date"]), row["fee_type"], str(row["amount"])))
    summary = summarize(rows)
    write_csv(EXPORTS_DIR / "platform_fee_review_detail.csv", rows, DETAIL_COLUMNS)
    write_csv(
        EXPORTS_DIR / "platform_fee_review_summary.csv",
        summary,
        ["platform", "fee_total_sgd", "fee_total_original", "fee_row_count", "first_fee_date", "last_fee_date", "notes"],
    )

    summary_rows = "".join(
        "<tr>"
        f"<td>{html_escape(row['platform'])}</td>"
        f"<td>{money(row['fee_total_sgd'])}</td>"
        f"<td>{html_escape(row['fee_total_original'])}</td>"
        f"<td>{row['fee_row_count']}</td>"
        f"<td>{html_escape(row['first_fee_date'])} to {html_escape(row['last_fee_date'])}</td>"
        f"<td>{html_escape(row['notes'])}</td>"
        "</tr>"
        for row in summary
    )
    detail_rows = "".join(
        "<tr>"
        f"<td>{html_escape(row['platform'])}</td>"
        f"<td>{html_escape(row['date'])}</td>"
        f"<td>{html_escape(row['covered_period'])}</td>"
        f"<td>{html_escape(row['fee_type'])}</td>"
        f"<td>{html_escape(str(row['amount']))} {html_escape(row['currency'])}</td>"
        f"<td>{money(row['amount_sgd'])}</td>"
        f"<td>{html_escape(row['charge_method'])}</td>"
        f"<td>{html_escape(row['recurring_status'])}</td>"
        "</tr>"
        for row in rows
    )
    body = f"""
<p class="warning">This review separates explicit debited fees from embedded fund costs. Embedded fund TER/OCF costs are generally already reflected in fund NAV/performance and are not available as dated cash charges in the current source exports.</p>
<h2>Summary</h2>
<table><thead><tr><th>Platform</th><th>Explicit fee total SGD</th><th>Original total</th><th>Rows</th><th>Date range</th><th>Notes</th></tr></thead><tbody>{summary_rows}</tbody></table>
<h2>Detailed Fee Ledger</h2>
<table><thead><tr><th>Platform</th><th>Date</th><th>Covered period</th><th>Fee type</th><th>Amount</th><th>SGD</th><th>Charge method</th><th>Status</th></tr></thead><tbody>{detail_rows}</tbody></table>
"""
    write_html_report(REPORTS_DIR / "platform_fee_review.html", "Platform Fee Review", body)
    return {"detail_rows": len(rows), "summary_rows": len(summary), "report": str(REPORTS_DIR / "platform_fee_review.html")}


if __name__ == "__main__":
    print(run())
