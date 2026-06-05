from __future__ import annotations

import csv
from decimal import Decimal
from pathlib import Path
from typing import Any

from common import EXPORTS_DIR, REPORTS_DIR, html_escape, parse_decimal, write_csv, write_html_report


DEC_2025_PDF = "/Users/samueltaylor/Library/Mobile Documents/com~apple~CloudDocs/Transactions/Sam/sam_evelyn/Valuation Report_FNTA0001_20251231_8547526.pdf"
SEP_2025_PDF = "/Users/samueltaylor/Library/Mobile Documents/com~apple~CloudDocs/Transactions/Sam/sam_evelyn/Valuation Report_FNTA0001_20250930_8547526.pdf"


def pct(value: Decimal) -> str:
    return f"{float(value):.2f}%"


def money(value: Decimal) -> str:
    return f"GBP {float(value):,.2f}"


def run() -> dict[str, Any]:
    # From Dec 2025 Evelyn report:
    # 21 Oct 2025 Custody Fee 01.09.25-30.09.25 FNTA0001 D GBP 41.48
    # 21 Oct 2025 Inv Man Fee 01.09.25-30.09.25 FNTA0001 D GBP 217.49
    opening_value = Decimal("254512")
    closing_value = Decimal("262412")
    average_value = (opening_value + closing_value) / Decimal("2")
    monthly_management_fee = Decimal("217.49")
    monthly_custody_fee = Decimal("41.48")
    monthly_recurring_fee = monthly_management_fee + monthly_custody_fee
    setup_transaction_charges = Decimal("138.93")

    management_bps = monthly_management_fee * Decimal("12") / average_value * Decimal("10000")
    custody_bps = monthly_custody_fee * Decimal("12") / average_value * Decimal("10000")
    recurring_bps = monthly_recurring_fee * Decimal("12") / average_value * Decimal("10000")
    total_first_visible_charges = monthly_recurring_fee + setup_transaction_charges

    rows = [
        {
            "item": "Management fee",
            "amount_gbp": monthly_management_fee,
            "covered_period": "01.09.25-30.09.25",
            "interpretation": "Monthly recurring investment management fee",
            "annualized_bps": management_bps,
            "source_file": DEC_2025_PDF,
            "source_row": "Cash Statement: Inv Man Fee 01.09.25-30.09.25; Charges: Management Fees",
        },
        {
            "item": "Custody / miscellaneous fee",
            "amount_gbp": monthly_custody_fee,
            "covered_period": "01.09.25-30.09.25",
            "interpretation": "Monthly recurring custody fee, shown in Charges as Miscellaneous Charges",
            "annualized_bps": custody_bps,
            "source_file": DEC_2025_PDF,
            "source_row": "Cash Statement: Custody Fee 01.09.25-30.09.25; Charges: Miscellaneous Charges",
        },
        {
            "item": "Total recurring visible fee",
            "amount_gbp": monthly_recurring_fee,
            "covered_period": "01.09.25-30.09.25",
            "interpretation": "Monthly recurring run-rate based on the only management/custody month visible so far",
            "annualized_bps": recurring_bps,
            "source_file": DEC_2025_PDF,
            "source_row": "Sum of management fee and custody fee",
        },
        {
            "item": "Setup transaction charges",
            "amount_gbp": setup_transaction_charges,
            "covered_period": "Jul-Sep 2025 setup trades",
            "interpretation": "One-off dealing/bargain/stamp/PTM style transaction charges, not recurring management fee",
            "annualized_bps": Decimal("0"),
            "source_file": SEP_2025_PDF,
            "source_row": "Transaction statement total charges; Charges: Transaction Charges",
        },
    ]
    write_csv(
        EXPORTS_DIR / "evelyn_fee_deep_dive.csv",
        rows,
        ["item", "amount_gbp", "covered_period", "interpretation", "annualized_bps", "source_file", "source_row"],
    )

    body = f"""
<div class="metric-row">
  <div class="metric"><strong>{money(monthly_recurring_fee)}</strong><span>Visible recurring fee for one month</span></div>
  <div class="metric"><strong>{pct(recurring_bps / Decimal("100"))}</strong><span>Annualized recurring rate</span></div>
  <div class="metric"><strong>{money(total_first_visible_charges)}</strong><span>Total visible charges so far</span></div>
  <div class="metric"><strong>{money(average_value)}</strong><span>Approx. average portfolio value used</span></div>
</div>
<p class="warning">The earlier 23 bps figure was understated because it treated one visible monthly Evelyn fee as if it were the only recurring fee across the whole active period. The Dec 2025 cash statement says the investment management and custody fees cover 01.09.25-30.09.25, so the right run-rate check is monthly fee x 12.</p>
<h2>Finding</h2>
<p>The visible recurring Evelyn fee is {money(monthly_recurring_fee)} for September 2025: {money(monthly_management_fee)} investment management plus {money(monthly_custody_fee)} custody/miscellaneous. Against an approximate average portfolio value of {money(average_value)}, this annualizes to {pct(recurring_bps / Decimal("100"))}, or {float(recurring_bps):.1f} bps.</p>
<h2>Why It Matches The 1% Concern</h2>
<p>Management alone annualizes to {float(management_bps):.1f} bps, and custody/miscellaneous adds {float(custody_bps):.1f} bps. Together they are close to a 1.2%-1.25% all-in discretionary-style run-rate.</p>
<h2>Evidence Rows</h2>
<table><thead><tr><th>Item</th><th>Amount</th><th>Covered period</th><th>Annualized bps</th><th>Interpretation</th></tr></thead><tbody>
{''.join(f"<tr><td>{html_escape(row['item'])}</td><td>{money(row['amount_gbp'])}</td><td>{html_escape(row['covered_period'])}</td><td>{float(row['annualized_bps']):.1f}</td><td>{html_escape(row['interpretation'])}</td></tr>" for row in rows)}
</tbody></table>
"""
    write_html_report(REPORTS_DIR / "evelyn_fee_deep_dive.html", "Evelyn Fee Deep Dive", body)
    return {"rows": len(rows), "recurring_bps": recurring_bps, "report": str(REPORTS_DIR / "evelyn_fee_deep_dive.html")}


if __name__ == "__main__":
    print(run())
