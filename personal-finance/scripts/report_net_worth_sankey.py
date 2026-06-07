from __future__ import annotations

import calendar
import csv
import json
import re
import subprocess
from collections import defaultdict
from datetime import datetime
from decimal import Decimal
from pathlib import Path
from typing import Any

import report_spending_by_category as spending
from common import EXPORTS_DIR, REPORTS_DIR, SOURCE_ROOT, html_escape, write_csv, write_html_report


START_MONTH = "2024-03"
START_LABEL = "Start: 2024-03-31"
PERIOD_START_DATE = "2024-04-01"
END_MONTH = "2026-05"
END_LABEL = "End: 2026-05-31"
SALARY_DIR = SOURCE_ROOT / "Sam" / "Salary"
STRIPE_TAX_DIR = SOURCE_ROOT / "Sam" / "tax_singapore" / "stripe_tax"


COLORS = {
    "opening": "#4b5563",
    "income": "#2563eb",
    "stock": "#635bff",
    "spending": "#c2410c",
    "ending": "#116466",
    "increase": "#0f766e",
    "investment": "#315f9d",
    "new_asset": "#0f766e",
    "fx": "#7c3aed",
    "residual": "#d97706",
    "platform": "#315f9d",
    "category": "#8f5f3c",
    "other_asset": "#667085",
}

INVESTMENT_PLATFORMS = {"IBKR", "Vanguard", "Evelyn", "Endowus", "Stripe"}


def money(value: Any) -> str:
    return f"S${Decimal(str(value)):,.0f}"


def parse_money(value: str) -> Decimal:
    return Decimal(value.replace(",", ""))


def quarter_for_date(value: str) -> str:
    year = int(value[:4])
    month = int(value[5:7])
    return f"{year}Q{((month - 1) // 3) + 1}"


def in_period(value: str) -> bool:
    return PERIOD_START_DATE <= value <= f"{END_MONTH}-31"


def pdf_text(path: Path) -> str:
    return subprocess.check_output(["pdftotext", "-layout", str(path), "-"], text=True, errors="ignore")


def income_components() -> dict[str, Decimal]:
    components: dict[str, Decimal] = defaultdict(Decimal)
    parsed_months: set[str] = set()
    salary_labels = {"BASIC PAY", "Basic salary", "LIFESTYLE", "EDUCATION STIPEND - NT"}
    bonus_labels = {"COMPANY PERFORMANCE BONUS", "GTM AWARD", "EQUITY CHOICE CASH", "SPOT BONUS", "SIGN-ON BONUS"}
    all_labels = sorted(salary_labels | bonus_labels | {"MISC DEDUCTION"}, key=len, reverse=True)
    month_map = {month: index for index, month in enumerate(calendar.month_name) if month}

    for path in sorted(SALARY_DIR.glob("*.pdf")):
        text = pdf_text(path)
        period_match = re.search(r"Period\s*:\s*\.([^\n]+)", text)
        if not period_match:
            continue
        parts = period_match.group(1).strip().split()
        if len(parts) < 2 or parts[0] not in month_map:
            continue
        year = int(parts[-1])
        month = month_map[parts[0]]
        month_key = f"{year}-{month:02d}"
        if not (PERIOD_START_DATE[:7] <= month_key <= END_MONTH):
            continue
        parsed_months.add(month_key)

        for line in text.splitlines():
            if not re.search(r"\d[\d,]*\.\d{2}[+-]", line):
                continue
            for label in all_labels:
                if label not in line:
                    continue
                amount_match = re.search(r"(\d[\d,]*\.\d{2})([+-])", line.split(label, 1)[1])
                if not amount_match:
                    continue
                value = parse_money(amount_match.group(1))
                if amount_match.group(2) == "-":
                    value *= Decimal("-1")
                if label in bonus_labels:
                    components["Samuel bonus / cash awards"] += value
                else:
                    components["Samuel salary / payroll"] += value

    salary_path = EXPORTS_DIR / "salary_payments.csv"
    if salary_path.exists():
        with salary_path.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if not in_period(row.get("date", "")):
                    continue
                description = row.get("description", "")
                value = Decimal(row["amount_sgd"])
                if "STRIPE PAYMENTS SINGAPORE" in description and row["date"][:7] not in parsed_months:
                    components["Samuel salary / payroll"] += value
                elif "DOVER COURT INTERNATIONAL SCHOOL" in description:
                    components["Amy Dover Court income"] += value

    components["Stripe stock vesting income"] += stock_vesting_income()
    return components


def stock_vesting_income() -> Decimal:
    total = Decimal("0")
    appendix_files = [
        STRIPE_TAX_DIR / "2024 Appendix 8B - 110078_PAYRUNID-1089 (1).pdf",
        STRIPE_TAX_DIR / "2025 Appendix 8B - 110078_PAYRUNID-1519.pdf",
    ]
    for path in appendix_files:
        if not path.exists():
            continue
        text = pdf_text(path)
        for line in text.splitlines():
            if "STRIPE INC" not in line or not re.search(r"\d{2}-[A-Za-z]{3}-\d{4}", line):
                continue
            dates = re.findall(r"\d{2}-[A-Za-z]{3}-\d{4}", line)
            numbers = re.findall(r"\d[\d,]*\.\d+", line)
            if len(dates) < 2 or not numbers:
                continue
            vest_date = datetime.strptime(dates[1], "%d-%b-%Y").date().isoformat()
            if in_period(vest_date):
                total += parse_money(numbers[-1])

    stripe_balances = Path("data/processed/stripe_balances.csv")
    if stripe_balances.exists():
        rows = []
        with stripe_balances.open(newline="", encoding="utf-8") as f:
            for row in csv.DictReader(f):
                if row.get("account_id") == "CS-229409-01" and row.get("balance_type") == "released_common_shares_value":
                    rows.append(row)
        previous_usd: Decimal | None = None
        for row in sorted(rows, key=lambda item: (item["date"], Decimal(item["balance"]))):
            row_date = row["date"]
            source = row.get("source_row", "").lower()
            balance_usd = Decimal(row["balance"])
            balance_sgd = Decimal(row["balance_sgd"])
            fx_rate = balance_sgd / balance_usd if balance_usd else Decimal("0")
            if row_date < "2026-01-01":
                if "release cost basis" in source or "tender offer" in source:
                    previous_usd = balance_usd
                continue
            if row_date > f"{END_MONTH}-31":
                continue
            if "release cost basis" in source:
                if previous_usd is not None and balance_usd > previous_usd:
                    total += (balance_usd - previous_usd) * fx_rate
                previous_usd = balance_usd
            elif "tender offer" in source:
                previous_usd = balance_usd
    return total


def stripe_cashouts() -> Decimal:
    total = Decimal("0")
    for row in read_transactions():
        if row.get("institution") != "stripe" or not in_period(row.get("date", "")):
            continue
        if "withdrawal" in row.get("description_raw", "").lower():
            total += -Decimal(row.get("amount_sgd") or "0")
    return total


def stripe_stock_appreciation(start: dict[str, Decimal], end: dict[str, Decimal], vesting_income: Decimal) -> Decimal:
    """Estimate Stripe stock appreciation net of vesting income already counted as income."""
    return end.get("Stripe", Decimal("0")) - start.get("Stripe", Decimal("0")) + stripe_cashouts() - vesting_income


def stripe_stock_appreciation_rows(start: dict[str, Decimal], end: dict[str, Decimal], vesting_income: Decimal) -> list[dict[str, Any]]:
    cashouts = stripe_cashouts()
    return [
        {"component": "Opening Stripe stock value", "value_sgd": start.get("Stripe", Decimal("0")), "note": "Opening balance sheet value."},
        {"component": "Ending Stripe stock value", "value_sgd": end.get("Stripe", Decimal("0")), "note": "Ending balance sheet value."},
        {"component": "Add Stripe stock cash-outs", "value_sgd": cashouts, "note": "Cash-outs reduce remaining stock value, so add them back to estimate total return."},
        {"component": "Less Stripe vesting income already counted", "value_sgd": -vesting_income, "note": "Already included in Sam income, so remove it to avoid double counting."},
        {"component": "Estimated Stripe stock appreciation", "value_sgd": stripe_stock_appreciation(start, end, vesting_income), "note": "Ending value - opening value + cash-outs - vesting income."},
    ]


def net_worth_rows() -> list[dict[str, str]]:
    with (EXPORTS_DIR / "net_worth_monthly_stacked.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def net_worth_by_month() -> dict[str, dict[str, Decimal]]:
    rows = net_worth_rows()
    out = {}
    for row in rows:
        out[row["month"]] = {key: Decimal(value or "0") for key, value in row.items() if key != "month"}
    return out


def spending_components() -> dict[str, Decimal]:
    totals: dict[str, Decimal] = defaultdict(Decimal)
    for row in spending.transaction_rows():
        if in_period(row["date"]):
            totals[row["category"]] += Decimal(str(row["amount_sgd"]))
    return totals


def grouped_spending_components() -> dict[str, Decimal]:
    grouped: dict[str, Decimal] = defaultdict(Decimal)
    for category, value in spending_components().items():
        if category == "housing":
            grouped["House"] += value
        elif category == "travel":
            grouped["Travel"] += value
        elif category == "tax_government":
            grouped["Tax"] += value
        else:
            grouped["Other spending"] += value
    return grouped


def investment_cash_flows() -> dict[str, Decimal]:
    """Dedup external-looking investment cash flows for gain estimates."""
    platform_for_institution = {
        "ibkr": "IBKR",
        "vanguard": "Vanguard",
        "evelyn": "Evelyn",
    }
    flows: dict[str, Decimal] = defaultdict(Decimal)
    seen: set[tuple[str, str, str, str, str]] = set()
    with Path("data/processed/transactions.csv").open(newline="", encoding="utf-8") as f:
        for row in csv.DictReader(f):
            institution = row.get("institution", "")
            platform = platform_for_institution.get(institution)
            if not platform or not in_period(row.get("date", "")):
                continue
            text = row.get("description_raw", "").lower()
            external = False
            if institution == "ibkr":
                external = "deposit" in text or "withdrawal" in text
            elif institution == "evelyn":
                external = "funds recd" in text or "withdraw" in text
            elif institution == "vanguard":
                external = "pension transfer in" in text or "transfer in" in text or "contribution" in text
            if not external:
                continue
            key = (institution, row.get("date", ""), row.get("amount", ""), row.get("currency", ""), row.get("description_raw", ""))
            if key in seen:
                continue
            seen.add(key)
            flows[platform] += Decimal(row.get("amount_sgd") or "0")
    return flows


def read_transactions() -> list[dict[str, str]]:
    with Path("data/processed/transactions.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def read_transfers() -> list[dict[str, str]]:
    with Path("data/processed/transfers.csv").open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def ibkr_cash_flow_rows() -> list[dict[str, str]]:
    rows = []
    seen: set[tuple[str, str, str, str]] = set()
    for row in read_transactions():
        if row.get("institution") != "ibkr" or not in_period(row.get("date", "")):
            continue
        text = row.get("description_raw", "").lower()
        if "deposit" not in text and "withdrawal" not in text:
            continue
        key = (row.get("date", ""), row.get("amount", ""), row.get("currency", ""), row.get("description_raw", ""))
        if key in seen:
            continue
        seen.add(key)
        rows.append(row)
    return sorted(rows, key=lambda row: (row["date"], Decimal(row["amount"])))


def trace_ibkr_funding() -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    transactions = read_transactions()
    transaction_by_id = {row["transaction_id"]: row for row in transactions}
    transfers = read_transfers()
    status_priority = {"confirmed": 0, "probable": 1, "needs_review": 2, "": 3}
    institution_priority = {"dbs": 0, "barclays": 1, "wise": 2, "halifax": 3, "stripe": 4, "ibkr": 5}

    def transfer_matches(flow: dict[str, str]) -> list[tuple[dict[str, str], dict[str, str]]]:
        amount = Decimal(flow["amount"])
        currency = flow["currency"]
        flow_date = flow["date"]
        flow_id = flow["transaction_id"]
        is_deposit = amount > 0
        matches = []
        for transfer in transfers:
            if is_deposit:
                matched = transfer.get("to_transaction_id") == flow_id or (
                    transfer.get("to_account", "").startswith("ibkr:")
                    and transfer.get("to_date") == flow_date
                    and transfer.get("to_currency") == currency
                    and Decimal(transfer.get("to_amount") or "0") == amount
                )
                if matched:
                    matches.append((transfer, transaction_by_id.get(transfer.get("from_transaction_id", ""), {})))
            else:
                matched = transfer.get("from_transaction_id") == flow_id or (
                    transfer.get("from_account", "").startswith("ibkr:")
                    and transfer.get("from_date") == flow_date
                    and transfer.get("from_currency") == currency
                    and Decimal(transfer.get("from_amount") or "0") == amount
                )
                if matched:
                    matches.append((transfer, transaction_by_id.get(transfer.get("to_transaction_id", ""), {})))
        deduped = []
        seen_ids = set()
        for transfer, other in matches:
            if transfer["transfer_id"] in seen_ids:
                continue
            seen_ids.add(transfer["transfer_id"])
            deduped.append((transfer, other))
        deduped.sort(
            key=lambda item: (
                status_priority.get(item[0].get("status", ""), 9),
                institution_priority.get(item[1].get("institution", ""), 9),
                -abs(Decimal(item[1].get("amount_sgd") or "0")),
            )
        )
        return deduped

    def nearby_bank_match(flow: dict[str, str]) -> tuple[dict[str, str], Decimal] | None:
        flow_date = datetime.strptime(flow["date"], "%Y-%m-%d").date()
        flow_sgd = Decimal(flow.get("amount_sgd") or "0")
        candidates = []
        for row in transactions:
            if row.get("institution") not in {"dbs", "barclays", "wise"}:
                continue
            try:
                row_date = datetime.strptime(row["date"], "%Y-%m-%d").date()
            except ValueError:
                continue
            day_gap = abs((row_date - flow_date).days)
            if day_gap > 7:
                continue
            row_sgd = Decimal(row.get("amount_sgd") or "0")
            if flow_sgd == 0 or row_sgd == 0 or (flow_sgd > 0) == (row_sgd > 0):
                continue
            gap = abs(abs(flow_sgd) - abs(row_sgd))
            tolerance = max(Decimal("1000"), abs(flow_sgd) * Decimal("0.015"))
            if gap <= tolerance:
                text = row.get("description_raw", "").lower()
                score = (
                    day_gap,
                    gap,
                    0 if "outward telegraphic transfer" in text or "interactive" in text or "ibkr" in text or "u8508174" in text else 1,
                )
                candidates.append((score, row, gap))
        if not candidates:
            return None
        candidates.sort(key=lambda item: item[0])
        return candidates[0][1], candidates[0][2]

    rows = []
    for flow in ibkr_cash_flow_rows():
        matches = transfer_matches(flow)
        flow_amount_sgd = Decimal(flow["amount_sgd"])
        if matches:
            transfer, source = matches[0]
            rows.append(
                {
                    "ibkr_date": flow["date"],
                    "ibkr_amount": Decimal(flow["amount"]),
                    "ibkr_currency": flow["currency"],
                    "ibkr_amount_sgd": flow_amount_sgd,
                    "source_date": source.get("date", ""),
                    "source_owner": source.get("owner", ""),
                    "source_institution": source.get("institution", ""),
                    "source_account_id": source.get("account_id", ""),
                    "source_amount": Decimal(source.get("amount") or "0") if source.get("amount") else "",
                    "source_currency": source.get("currency", ""),
                    "source_amount_sgd": Decimal(source.get("amount_sgd") or "0") if source.get("amount_sgd") else "",
                    "match_status": transfer.get("status", ""),
                    "match_reason": transfer.get("match_reason", ""),
                    "source_description": source.get("description_raw", ""),
                }
            )
            continue
        nearby = nearby_bank_match(flow)
        if nearby:
            source, gap = nearby
            rows.append(
                {
                    "ibkr_date": flow["date"],
                    "ibkr_amount": Decimal(flow["amount"]),
                    "ibkr_currency": flow["currency"],
                    "ibkr_amount_sgd": flow_amount_sgd,
                    "source_date": source.get("date", ""),
                    "source_owner": source.get("owner", ""),
                    "source_institution": source.get("institution", ""),
                    "source_account_id": source.get("account_id", ""),
                    "source_amount": Decimal(source.get("amount") or "0") if source.get("amount") else "",
                    "source_currency": source.get("currency", ""),
                    "source_amount_sgd": Decimal(source.get("amount_sgd") or "0") if source.get("amount_sgd") else "",
                    "match_status": "probable",
                    "match_reason": f"nearby opposite-signed bank transfer within 7 days; SGD gap {money(gap)}; likely FX/TT route",
                    "source_description": source.get("description_raw", ""),
                }
            )
            continue
        rows.append(
            {
                "ibkr_date": flow["date"],
                "ibkr_amount": Decimal(flow["amount"]),
                "ibkr_currency": flow["currency"],
                "ibkr_amount_sgd": flow_amount_sgd,
                "source_date": "",
                "source_owner": "",
                "source_institution": "unmatched",
                "source_account_id": "",
                "source_amount": "",
                "source_currency": "",
                "source_amount_sgd": "",
                "match_status": "unmatched",
                "match_reason": "No transfer row or nearby opposite-signed DBS/Barclays/Wise amount found.",
                "source_description": flow.get("description_raw", ""),
            }
        )

    summary: dict[tuple[str, str], Decimal] = defaultdict(Decimal)
    for row in rows:
        summary[(row["source_institution"], row["match_status"])] += row["ibkr_amount_sgd"]
    summary_rows = [
        {"source_institution": institution, "match_status": status, "ibkr_net_amount_sgd": value}
        for (institution, status), value in sorted(summary.items())
    ]
    summary_rows.append(
        {
            "source_institution": "total",
            "match_status": "all IBKR cash-flow rows",
            "ibkr_net_amount_sgd": sum((row["ibkr_amount_sgd"] for row in rows), Decimal("0")),
        }
    )
    return rows, summary_rows


def investment_gain_rows(start: dict[str, Decimal], end: dict[str, Decimal]) -> list[dict[str, Any]]:
    flows = investment_cash_flows()
    rows = []
    for platform in ["IBKR", "Vanguard", "Evelyn"]:
        start_value = start.get(platform, Decimal("0"))
        end_value = end.get(platform, Decimal("0"))
        net_funding = flows.get(platform, Decimal("0"))
        gain = end_value - start_value - net_funding
        rows.append(
            {
                "platform": platform,
                "start_sgd": start_value,
                "end_sgd": end_value,
                "net_cash_funding_sgd": net_funding,
                "estimated_gain_sgd": gain,
                "method": "ending value - opening value - deduped external-looking cash flows",
            }
        )
    for platform in ["Endowus", "Stripe"]:
        rows.append(
            {
                "platform": platform,
                "start_sgd": start.get(platform, Decimal("0")),
                "end_sgd": end.get(platform, Decimal("0")),
                "net_cash_funding_sgd": "",
                "estimated_gain_sgd": "",
                "method": "not estimated here because complete contribution/withdrawal flow data is not available in the parsed platform rows",
            }
        )
    return rows


def estimated_fx_impact() -> tuple[Decimal, list[dict[str, Any]]]:
    rows = []
    with (EXPORTS_DIR / "net_worth_by_account.csv").open(newline="", encoding="utf-8") as f:
        all_rows = list(csv.DictReader(f))
    start_rows = [row for row in all_rows if row.get("month") == START_MONTH]
    end_rows = [row for row in all_rows if row.get("month") == END_MONTH]

    end_rates_by_currency: dict[str, list[Decimal]] = defaultdict(list)
    end_rate_by_key: dict[tuple[str, str, str, str, str], Decimal] = {}
    for row in end_rows:
        if not row.get("fx_rate_to_sgd"):
            continue
        rate = Decimal(row["fx_rate_to_sgd"])
        end_rates_by_currency[row.get("currency", "")].append(rate)
        key = (row.get("owner", ""), row.get("institution", ""), row.get("account_id", ""), row.get("currency", ""), row.get("balance_type", ""))
        end_rate_by_key[key] = rate
    currency_average = {currency: sum(values) / Decimal(len(values)) for currency, values in end_rates_by_currency.items() if values}

    total = Decimal("0")
    by_currency: dict[str, Decimal] = defaultdict(Decimal)
    for row in start_rows:
        currency = row.get("currency", "")
        if currency == "SGD" or not row.get("balance") or not row.get("fx_rate_to_sgd"):
            continue
        start_balance = Decimal(row["balance"])
        if start_balance == 0:
            continue
        start_rate = Decimal(row["fx_rate_to_sgd"])
        key = (row.get("owner", ""), row.get("institution", ""), row.get("account_id", ""), currency, row.get("balance_type", ""))
        end_rate = end_rate_by_key.get(key, currency_average.get(currency))
        if end_rate is None:
            continue
        impact = start_balance * (end_rate - start_rate)
        by_currency[currency] += impact
        total += impact
    for currency, value in sorted(by_currency.items()):
        rows.append(
            {
                "currency": currency,
                "estimated_fx_impact_sgd": value,
                "method": "opening foreign-currency balance multiplied by end FX rate minus start FX rate",
            }
        )
    return total, rows


def sankey_payload(links: list[dict[str, Any]]) -> dict[str, Any]:
    nodes: dict[str, dict[str, Any]] = {}
    for link in links:
        for endpoint in ["source", "target"]:
            name = link[endpoint]
            if name not in nodes:
                nodes[name] = {"name": name, "group": link.get(endpoint + "_group", link.get("group", "other"))}
    return {"nodes": list(nodes.values()), "links": links}


def build_rows() -> tuple[list[dict[str, Any]], list[dict[str, Any]], tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]], dict[str, Decimal]]:
    nw = net_worth_by_month()
    start = nw[START_MONTH]
    end = nw[END_MONTH]
    opening_total = start["Total"]
    ending_total = end["Total"]
    income = income_components()
    spending_totals = grouped_spending_components()
    income_total = sum(income.values(), Decimal("0"))
    amy_income_total = income.get("Amy Dover Court income", Decimal("0"))
    sam_income_total = income_total - amy_income_total
    spending_total = sum(spending_totals.values(), Decimal("0"))
    investment_rows = investment_gain_rows(start, end)
    investment_cash_flow_totals = investment_cash_flows()
    legacy_pension_opening = start.get("Legacy Pensions", Decimal("0"))
    vanguard_transfer_funding = investment_cash_flow_totals.get("Vanguard", Decimal("0"))
    legacy_pension_consolidated = min(legacy_pension_opening, vanguard_transfer_funding)
    legacy_pension_transfer_uplift = max(Decimal("0"), vanguard_transfer_funding - legacy_pension_consolidated)
    positive_investment_gains = {
        row["platform"]: row["estimated_gain_sgd"]
        for row in investment_rows
        if isinstance(row.get("estimated_gain_sgd"), Decimal) and row["estimated_gain_sgd"] > 0
    }
    investment_gain_total = sum(positive_investment_gains.values(), Decimal("0")) + legacy_pension_transfer_uplift
    stripe_vesting_income = income.get("Stripe stock vesting income", Decimal("0"))
    stock_appreciation = max(Decimal("0"), stripe_stock_appreciation(start, end, stripe_vesting_income))
    fx_impact, fx_rows = estimated_fx_impact()
    fx_gain = fx_impact if fx_impact > 0 else Decimal("0")
    fx_drag = abs(fx_impact) if fx_impact < 0 else Decimal("0")
    new_tracked_evelyn_funding = max(Decimal("0"), investment_cash_flow_totals.get("Evelyn", Decimal("0")))
    residual = ending_total + spending_total + fx_drag - opening_total - income_total - investment_gain_total - stock_appreciation - fx_gain - new_tracked_evelyn_funding

    net_worth_increase = ending_total - opening_total
    links: list[dict[str, Any]] = []
    links.append(
        {
            "source": "Income retained after spending",
            "target": "Net worth increase",
            "value_sgd": income_total - spending_total,
            "source_group": "income",
            "target_group": "increase",
        }
    )
    if investment_gain_total > 0:
        links.append(
            {
                "source": "Investment gains and pension revaluation",
                "target": "Net worth increase",
                "value_sgd": investment_gain_total,
                "source_group": "investment",
                "target_group": "increase",
            }
        )
    if new_tracked_evelyn_funding > 0:
        links.append(
            {
                "source": "Evelyn funding / newly tracked asset",
                "target": "Net worth increase",
                "value_sgd": new_tracked_evelyn_funding,
                "source_group": "new_asset",
                "target_group": "increase",
            }
        )
    if stock_appreciation > 0:
        links.append(
            {
                "source": "Stripe stock appreciation",
                "target": "Net worth increase",
                "value_sgd": stock_appreciation,
                "source_group": "stock",
                "target_group": "increase",
            }
        )
    if fx_gain > 0:
        links.append(
            {
                "source": "FX revaluation gain",
                "target": "Net worth increase",
                "value_sgd": fx_gain,
                "source_group": "fx",
                "target_group": "increase",
            }
        )
    if residual >= 0:
        links.append(
            {
                "source": "Remaining reconciliation / unclassified growth",
                "target": "Net worth increase",
                "value_sgd": residual,
                "source_group": "residual",
                "target_group": "increase",
            }
        )
    else:
        links.append(
            {
                "source": "Net worth increase",
                "target": "Remaining reconciliation / unclassified growth",
                "value_sgd": abs(residual),
                "source_group": "increase",
                "target_group": "residual",
            }
        )

    links.extend(
        [
            {"source": "Opening net worth carried forward", "target": END_LABEL, "value_sgd": opening_total, "source_group": "opening", "target_group": "ending"},
            {"source": "Net worth increase", "target": END_LABEL, "value_sgd": net_worth_increase, "source_group": "increase", "target_group": "ending"},
        ]
    )
    if fx_drag > 0:
        links.append(
            {
                "source": "Net worth increase",
                "target": "FX revaluation drag",
                "value_sgd": fx_drag,
                "source_group": "increase",
                "target_group": "fx",
            }
        )
    platform_rows = []
    for platform in sorted(k for k in end.keys() if k != "Total"):
        start_value = start.get(platform, Decimal("0"))
        end_value = end.get(platform, Decimal("0"))
        platform_rows.append(
            {
                "platform": platform,
                "start_sgd": start_value,
                "end_sgd": end_value,
                "change_sgd": end_value - start_value,
            }
        )
    platform_rows.sort(key=lambda row: row["change_sgd"], reverse=True)

    summary = {
        "opening_net_worth_sgd": opening_total,
        "ending_net_worth_sgd": ending_total,
        "net_worth_change_sgd": ending_total - opening_total,
        "income_sgd": income_total,
        "sam_income_sgd": sam_income_total,
        "amy_income_sgd": amy_income_total,
        "spending_sgd": spending_total,
        "income_minus_spending_sgd": income_total - spending_total,
        "estimated_investment_gains_sgd": investment_gain_total,
        "stripe_stock_appreciation_sgd": stock_appreciation,
        "stripe_stock_vesting_income_already_counted_sgd": stripe_vesting_income,
        "stripe_stock_cashouts_sgd": stripe_cashouts(),
        "legacy_pension_consolidated_from_opening_sgd": legacy_pension_consolidated,
        "legacy_pension_transfer_uplift_sgd": legacy_pension_transfer_uplift,
        "evelyn_funding_newly_tracked_asset_sgd": new_tracked_evelyn_funding,
        "estimated_fx_impact_sgd": fx_impact,
        "remaining_reconciliation_unclassified_growth_sgd": residual,
    }
    extra_rows = (
        [{"component": key, "value_sgd": value} for key, value in summary.items()],
        investment_rows,
        fx_rows,
    )
    return links, platform_rows, extra_rows, summary


def spending_loss_rows() -> list[dict[str, Any]]:
    return [
        {"component": label, "value_sgd": value}
        for label, value in sorted(grouped_spending_components().items(), key=lambda item: item[1], reverse=True)
    ]


def residual_breakdown_rows(summary: dict[str, Decimal], platform_rows: list[dict[str, Any]], investment_rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    platform_change = {row["platform"]: row["change_sgd"] for row in platform_rows}
    investment_gain = {
        row["platform"]: row["estimated_gain_sgd"]
        for row in investment_rows
        if isinstance(row.get("estimated_gain_sgd"), Decimal)
    }
    net_funding = {
        row["platform"]: row["net_cash_funding_sgd"]
        for row in investment_rows
        if isinstance(row.get("net_cash_funding_sgd"), Decimal)
    }
    rows = [
        {
            "component": "IBKR net funding destination, now source-traced",
            "value_sgd": net_funding.get("IBKR", Decimal("0")),
            "note": "This is where cash ended up, not new wealth. The IBKR funding trace below ties it to DBS/Wise transfers, including the Dec 2024 DBS GBP fixed-deposit/telegraphic-transfer chain.",
        },
        {
            "component": "Vanguard gross pension consolidation into Vanguard",
            "value_sgd": net_funding.get("Vanguard", Decimal("0")),
            "note": "Gross transfer/contribution-looking Vanguard cash flow. This is not treated as new wealth by itself.",
        },
        {
            "component": "Less opening legacy pension wealth consolidated into Vanguard",
            "value_sgd": -summary["legacy_pension_consolidated_from_opening_sgd"],
            "note": "This pension wealth was already in opening net worth, so it is netted off the Vanguard transfer.",
        },
        {
            "component": "Less legacy pension pre-transfer uplift already counted",
            "value_sgd": -summary["legacy_pension_transfer_uplift_sgd"],
            "note": "The excess of the Vanguard transfer over opening legacy pension value is now counted as pension revaluation/investment gain, not residual.",
        },
        {
            "component": "Stripe balance increase",
            "value_sgd": platform_change.get("Stripe", Decimal("0")),
            "note": "Stripe asset balance increased. Vesting income is already counted in Sam income; stock appreciation is now counted separately below.",
        },
        {
            "component": "Less Stripe stock appreciation now counted",
            "value_sgd": -summary["stripe_stock_appreciation_sgd"],
            "note": "Estimated as ending Stripe value minus opening Stripe value plus cash-outs minus Stripe vesting income already counted as income.",
        },
        {
            "component": "DBS cash/bank balance increase",
            "value_sgd": platform_change.get("DBS", Decimal("0")),
            "note": "Net increase in DBS balances after all visible transactions and transfers.",
        },
        {
            "component": "Other cash/property increases",
            "value_sgd": platform_change.get("Halifax", Decimal("0")) + platform_change.get("Property", Decimal("0")) + platform_change.get("Barclays", Decimal("0")),
            "note": "Halifax, property, and Barclays net increases.",
        },
        {
            "component": "Wise balance reduction",
            "value_sgd": platform_change.get("Wise", Decimal("0")),
            "note": "Offset from Wise balances falling over the period.",
        },
        {
            "component": "Premium Bonds reduction",
            "value_sgd": platform_change.get("Premium Bonds", Decimal("0")),
            "note": "Premium Bonds asset disappears as it is cashed out/transferred.",
        },
        {
            "component": "Endowus net withdrawal / redeployment",
            "value_sgd": platform_change.get("Endowus", Decimal("0")),
            "note": "User-confirmed as money put into Endowus and then withdrawn/redeployed, not an unexplained investment loss.",
        },
    ]
    subtotal = sum((row["value_sgd"] for row in rows), Decimal("0"))
    rows.extend(
        [
            {
                "component": "Subtotal of not-yet-bridged platform movements",
                "value_sgd": subtotal,
                "note": "Destination/platform movements after removing estimated platform gains, Evelyn funding, and the pension consolidation reclassification.",
            },
            {
                "component": "Less income retained already counted",
                "value_sgd": -summary["income_minus_spending_sgd"],
                "note": "This part is already included as income minus spending in the main bridge.",
            },
            {
                "component": "Less FX impact already counted",
                "value_sgd": -summary["estimated_fx_impact_sgd"],
                "note": "FX impact is already included separately in the main bridge.",
            },
            {
                "component": "Remaining reconciliation / unclassified growth",
                "value_sgd": subtotal - summary["income_minus_spending_sgd"] - summary["estimated_fx_impact_sgd"],
                "note": "This equals the residual bridge item.",
            },
        ]
    )
    return rows


def table(rows: list[dict[str, Any]], columns: list[str], limit: int | None = None) -> str:
    rows = rows if limit is None else rows[:limit]
    body = []
    for row in rows:
        cells = []
        for column in columns:
            value = row.get(column, "")
            if isinstance(value, Decimal):
                value = money(value)
            cells.append(f"<td>{html_escape(value)}</td>")
        body.append(f"<tr>{''.join(cells)}</tr>")
    head = "".join(f"<th>{html_escape(column)}</th>" for column in columns)
    return f"<table><thead><tr>{head}</tr></thead><tbody>{''.join(body)}</tbody></table>"


def bridge_rows(summary: dict[str, Decimal]) -> list[dict[str, Any]]:
    rows = [
        {
            "component": "Income retained after spending",
            "value_sgd": summary["income_minus_spending_sgd"],
            "explanation": "Income minus spending/outflows in the period.",
        },
        {
            "component": "Estimated investment gains and pension revaluation",
            "value_sgd": summary["estimated_investment_gains_sgd"],
            "explanation": "Balance-derived gain estimate for platforms with usable cash-flow data, plus the legacy pension uplift before it was consolidated into Vanguard.",
        },
        {
            "component": "Stripe stock appreciation",
            "value_sgd": summary["stripe_stock_appreciation_sgd"],
            "explanation": "Estimated Stripe stock appreciation after removing vesting income already counted as Sam income and adding back cash-outs.",
        },
        {
            "component": "Evelyn funding / newly tracked asset",
            "value_sgd": summary["evelyn_funding_newly_tracked_asset_sgd"],
            "explanation": "Evelyn appears during the period; this may be a newly visible asset rather than newly created wealth.",
        },
        {
            "component": "Estimated FX impact",
            "value_sgd": summary["estimated_fx_impact_sgd"],
            "explanation": "Estimated FX revaluation on opening foreign-currency balances.",
        },
        {
            "component": "Remaining reconciliation / unclassified growth",
            "value_sgd": summary["remaining_reconciliation_unclassified_growth_sgd"],
            "explanation": "Unmodelled gains/flows/data additions after source-tracing IBKR funding and netting pension consolidation.",
        },
    ]
    rows.append(
        {
            "component": "Net worth increase",
            "value_sgd": sum((row["value_sgd"] for row in rows), Decimal("0")),
            "explanation": "This should equal ending net worth minus opening net worth.",
        }
    )
    return rows


def full_net_worth_bridge_rows(summary: dict[str, Decimal]) -> list[dict[str, Any]]:
    rows = [
        {
            "step": "Opening net worth",
            "amount_sgd": summary["opening_net_worth_sgd"],
            "running_net_worth_sgd": summary["opening_net_worth_sgd"],
            "note": "Starting balance at 2024-03-31.",
        },
        {
            "step": "Sam income",
            "amount_sgd": summary["sam_income_sgd"],
            "running_net_worth_sgd": None,
            "note": "Samuel salary, bonus/cash awards, and Stripe stock vesting income.",
        },
        {
            "step": "Amy income",
            "amount_sgd": summary["amy_income_sgd"],
            "running_net_worth_sgd": None,
            "note": "Amy Dover Court income found in the transaction data.",
        },
        {
            "step": "Total spending / outflows",
            "amount_sgd": -summary["spending_sgd"],
            "running_net_worth_sgd": None,
            "note": "Cleaned spending/outflow candidates, excluding internal transfers.",
        },
        {
            "step": "Net income retained",
            "amount_sgd": summary["income_minus_spending_sgd"],
            "running_net_worth_sgd": summary["opening_net_worth_sgd"] + summary["income_minus_spending_sgd"],
            "note": "Sam income + Amy income - total spending.",
        },
        {
            "step": "Estimated investment gains and pension revaluation",
            "amount_sgd": summary["estimated_investment_gains_sgd"],
            "running_net_worth_sgd": summary["opening_net_worth_sgd"] + summary["income_minus_spending_sgd"] + summary["estimated_investment_gains_sgd"],
            "note": "Estimated gains for platforms with usable cash-flow data, including the uplift on legacy pensions before Vanguard consolidation.",
        },
        {
            "step": "Stripe stock appreciation",
            "amount_sgd": summary["stripe_stock_appreciation_sgd"],
            "running_net_worth_sgd": summary["opening_net_worth_sgd"] + summary["income_minus_spending_sgd"] + summary["estimated_investment_gains_sgd"] + summary["stripe_stock_appreciation_sgd"],
            "note": "Estimated appreciation on Stripe stock after excluding vesting income already counted as income.",
        },
        {
            "step": "Evelyn funding / newly tracked asset",
            "amount_sgd": summary["evelyn_funding_newly_tracked_asset_sgd"],
            "running_net_worth_sgd": summary["opening_net_worth_sgd"] + summary["income_minus_spending_sgd"] + summary["estimated_investment_gains_sgd"] + summary["stripe_stock_appreciation_sgd"] + summary["evelyn_funding_newly_tracked_asset_sgd"],
            "note": "Visible during the period; may be newly visible wealth rather than newly created wealth.",
        },
        {
            "step": "Estimated FX impact",
            "amount_sgd": summary["estimated_fx_impact_sgd"],
            "running_net_worth_sgd": summary["opening_net_worth_sgd"] + summary["income_minus_spending_sgd"] + summary["estimated_investment_gains_sgd"] + summary["stripe_stock_appreciation_sgd"] + summary["evelyn_funding_newly_tracked_asset_sgd"] + summary["estimated_fx_impact_sgd"],
            "note": "Estimated FX revaluation on opening foreign-currency balances.",
        },
        {
            "step": "Remaining reconciliation / unclassified growth",
            "amount_sgd": summary["remaining_reconciliation_unclassified_growth_sgd"],
            "running_net_worth_sgd": summary["ending_net_worth_sgd"],
            "note": "Unmodelled gains/flows/data additions after IBKR funding trace and pension consolidation netting.",
        },
        {
            "step": "Ending net worth",
            "amount_sgd": summary["ending_net_worth_sgd"],
            "running_net_worth_sgd": summary["ending_net_worth_sgd"],
            "note": "Ending balance at 2026-05-31.",
        },
    ]
    return rows


def run() -> dict[str, Any]:
    links, platform_rows, extra_rows, summary = build_rows()
    summary_rows, investment_rows, fx_rows = extra_rows
    bridge = bridge_rows(summary)
    full_bridge = full_net_worth_bridge_rows(summary)
    spending_losses = spending_loss_rows()
    residual_breakdown = residual_breakdown_rows(summary, platform_rows, investment_rows)
    ibkr_trace, ibkr_trace_summary = trace_ibkr_funding()
    platform_by_name = {row["platform"]: row for row in platform_rows}
    stripe_appreciation = stripe_stock_appreciation_rows(
        {"Stripe": platform_by_name.get("Stripe", {}).get("start_sgd", Decimal("0"))},
        {"Stripe": platform_by_name.get("Stripe", {}).get("end_sgd", Decimal("0"))},
        summary["stripe_stock_vesting_income_already_counted_sgd"],
    )
    flow_rows = [
        {**row, "value_sgd": row["value_sgd"]}
        for row in links
    ]
    write_csv(EXPORTS_DIR / "net_worth_sankey_flows.csv", flow_rows, ["source", "target", "value_sgd", "source_group", "target_group"])
    write_csv(EXPORTS_DIR / "net_worth_sankey_summary.csv", summary_rows, ["component", "value_sgd"])
    write_csv(EXPORTS_DIR / "net_worth_full_bridge.csv", full_bridge, ["step", "amount_sgd", "running_net_worth_sgd", "note"])
    write_csv(EXPORTS_DIR / "net_worth_change_bridge.csv", bridge, ["component", "value_sgd", "explanation"])
    write_csv(EXPORTS_DIR / "net_worth_spending_losses.csv", spending_losses, ["component", "value_sgd"])
    write_csv(EXPORTS_DIR / "net_worth_residual_breakdown.csv", residual_breakdown, ["component", "value_sgd", "note"])
    write_csv(EXPORTS_DIR / "stripe_stock_appreciation_estimate.csv", stripe_appreciation, ["component", "value_sgd", "note"])
    write_csv(
        EXPORTS_DIR / "ibkr_funding_trace.csv",
        ibkr_trace,
        [
            "ibkr_date",
            "ibkr_amount",
            "ibkr_currency",
            "ibkr_amount_sgd",
            "source_date",
            "source_owner",
            "source_institution",
            "source_account_id",
            "source_amount",
            "source_currency",
            "source_amount_sgd",
            "match_status",
            "match_reason",
            "source_description",
        ],
    )
    write_csv(
        EXPORTS_DIR / "ibkr_funding_trace_summary.csv",
        ibkr_trace_summary,
        ["source_institution", "match_status", "ibkr_net_amount_sgd"],
    )
    write_csv(EXPORTS_DIR / "net_worth_change_by_platform.csv", platform_rows, ["platform", "start_sgd", "end_sgd", "change_sgd"])
    write_csv(
        EXPORTS_DIR / "net_worth_investment_gain_estimates.csv",
        investment_rows,
        ["platform", "start_sgd", "end_sgd", "net_cash_funding_sgd", "estimated_gain_sgd", "method"],
    )
    write_csv(EXPORTS_DIR / "net_worth_fx_estimate.csv", fx_rows, ["currency", "estimated_fx_impact_sgd", "method"])

    payload = json.dumps(
        {
            **sankey_payload([{**link, "value_sgd": float(link["value_sgd"])} for link in links]),
            "colors": COLORS,
        }
    )
    body = f"""
<p class="warning">This is a net-worth bridge for {START_LABEL} to {END_LABEL}. The Sankey itself now only shows the balance sheet bridge: opening net worth plus the net worth increase equals ending net worth. Spending is shown separately below as a red loss breakdown, not as a gain or as part of the Sankey scale. Internal transfers are not treated as spending. Investment gains are estimated from platform balance changes less deduped external-looking cash flows where available; Endowus is grouped as an investment asset, but its gain is not estimated because the parsed Endowus flow rows are incomplete.</p>
<div class="metric-row">
  <div class="metric"><strong>{money(summary["opening_net_worth_sgd"])}</strong><span>Opening net worth</span></div>
  <div class="metric"><strong>{money(summary["net_worth_change_sgd"])}</strong><span>Left bridge: net worth increase</span></div>
  <div class="metric"><strong>{money(summary["ending_net_worth_sgd"])}</strong><span>Ending net worth</span></div>
  <div class="metric"><strong>{money(summary["income_minus_spending_sgd"])}</strong><span>Income minus spending</span></div>
  <div class="metric"><strong>{money(summary["estimated_investment_gains_sgd"])}</strong><span>Estimated investment gains/revaluation</span></div>
  <div class="metric"><strong>{money(summary["stripe_stock_appreciation_sgd"])}</strong><span>Stripe stock appreciation</span></div>
  <div class="metric"><strong>{money(summary["estimated_fx_impact_sgd"])}</strong><span>Estimated FX impact</span></div>
</div>
<h2>Full Net Worth Bridge</h2>
<p>This is the main arithmetic: start with opening net worth, add Sam income and Amy income, subtract spending to get retained income, then add investment gains, Stripe stock appreciation, FX, newly visible assets, and the remaining reconciliation item.</p>
{table(full_bridge, ["step", "amount_sgd", "running_net_worth_sgd", "note"])}
<div id="sankeyWrap">
  <svg id="sankey" viewBox="0 0 1180 980" role="img" aria-label="Sankey diagram of net worth change" style="width:100%;height:auto;background:#fff;border:1px solid var(--line);border-radius:6px"></svg>
  <div id="tip" class="tip"></div>
</div>
<h2>Spending Losses Not Included In The Bridge</h2>
<p>Gross income was {money(summary["income_sgd"])} and spending/outflows were {money(summary["spending_sgd"])}, leaving {money(summary["income_minus_spending_sgd"])} retained into net worth. The spending below is deliberately outside the Sankey so the bridge totals are visually comparable.</p>
{table(spending_losses, ["component", "value_sgd"])}
<h2>Reconciliation</h2>
<p>The net worth bridge is the signed version of the Sankey: income has to be netted against spending, then gains, FX, newly visible assets, and the remaining reconciliation item are added.</p>
{table(bridge, ["component", "value_sgd", "explanation"])}
<h2>Residual Breakdown</h2>
<p>This breaks down the {money(summary["remaining_reconciliation_unclassified_growth_sgd"])} residual. IBKR is shown here as a destination movement, but the table below traces the funding back to DBS/Wise rather than treating it as new wealth. Vanguard pension consolidation is netted against opening legacy pension wealth. Stripe appreciation is now separated from vesting income, and Endowus is treated as a contribution/withdrawal cycle rather than an unexplained platform loss.</p>
{table(residual_breakdown, ["component", "value_sgd", "note"])}
<h2>Stripe Stock Appreciation</h2>
<p>This separates Stripe stock appreciation from Stripe vesting income. Vesting income is already in Sam income, while appreciation is the extra mark-to-market/cash-out return.</p>
{table(stripe_appreciation, ["component", "value_sgd", "note"])}
<h2>IBKR Funding Trace</h2>
<p>The IBKR net funding line is {money(ibkr_trace_summary[-1]["ibkr_net_amount_sgd"])} across the period. The trace below checks the actual IBKR cash-flow rows against transfer matches and nearby DBS/Barclays/Wise rows. The large 23 Dec 2024 IBKR deposit is matched as probable to the 21 Dec 2024 DBS GBP outward telegraphic transfer that followed a GBP fixed-deposit maturity in the same DBS statement.</p>
{table(ibkr_trace_summary, ["source_institution", "match_status", "ibkr_net_amount_sgd"])}
{table(ibkr_trace, ["ibkr_date", "ibkr_amount", "ibkr_currency", "ibkr_amount_sgd", "source_date", "source_institution", "source_account_id", "source_amount", "source_currency", "source_amount_sgd", "match_status", "match_reason"], limit=40)}
<h2>Sources and Uses Totals</h2>
{table(summary_rows, ["component", "value_sgd"])}
<h2>Investment Gain Estimates</h2>
{table(investment_rows, ["platform", "start_sgd", "end_sgd", "net_cash_funding_sgd", "estimated_gain_sgd", "method"])}
<h2>FX Estimate</h2>
{table(fx_rows, ["currency", "estimated_fx_impact_sgd", "method"])}
<h2>Platform Change</h2>
{table(platform_rows, ["platform", "start_sgd", "end_sgd", "change_sgd"])}
<script type="application/json" id="sankey-data">{payload}</script>
<script>
const data = JSON.parse(document.getElementById('sankey-data').textContent);
const svg = document.getElementById('sankey');
const tip = document.getElementById('tip');
const W=1180,H=980,L=36,R=36,T=58,B=42,nodeW=16,gap=16;
const groups = data.colors;
const fmt = v => 'S$' + Math.round(v || 0).toLocaleString();
const html = v => String(v ?? '').replace(/[&<>"']/g,c=>({{'&':'&amp;','<':'&lt;','>':'&gt;','"':'&quot;',"'":'&#39;'}}[c]));
const nodeMap = new Map(data.nodes.map(n => [n.name, {{...n, in:0, out:0, sourceLinks:[], targetLinks:[]}}]));
data.links.forEach(l => {{
  const s=nodeMap.get(l.source), t=nodeMap.get(l.target);
  s.out += l.value_sgd; t.in += l.value_sgd;
  s.sourceLinks.push(l); t.targetLinks.push(l);
}});
nodeMap.forEach(n => n.value = Math.max(n.in, n.out));
const colFor = name => {{
  if (name === '{END_LABEL}') return 3;
  if (name === 'Net worth increase' || name === 'Opening net worth carried forward' || name === 'FX revaluation drag') return 2;
  if (['Investment gains and pension revaluation', 'Stripe stock appreciation'].includes(name)) return 1;
  return 0;
}};
const orderScore = n => {{
  const fixed = {{
    'Income retained after spending': -80, 'Net worth increase': -50, 'Opening net worth carried forward': -40,
    'Investment gains and pension revaluation': -45, 'Stripe stock appreciation': -40, 'Evelyn funding / newly tracked asset': -30, 'FX revaluation gain': -20,
    'Remaining reconciliation / unclassified growth': -10,
    '{END_LABEL}': -10
  }};
  return fixed[n.name] ?? -n.value;
}};
const cols = [[],[],[],[]];
nodeMap.forEach(n => {{ n.col=colFor(n.name); cols[n.col].push(n); }});
cols.forEach(c => c.sort((a,b)=>orderScore(a)-orderScore(b)));
const plotH=H-T-B;
const scale = Math.min(...cols.filter(c=>c.length).map(c => (plotH - gap*(c.length-1)) / c.reduce((s,n)=>s+n.value,0)));
const xFor = col => L + col * ((W-L-R-nodeW)/3);
cols.forEach((c,col) => {{
  const used = c.reduce((s,n)=>s+n.value*scale,0) + gap*(c.length-1);
  let y = T + Math.max(0,(plotH-used)/2);
  c.forEach(n => {{ n.x=xFor(col); n.y=y; n.h=Math.max(2,n.value*scale); n.sy=0; n.ty=0; y += n.h + gap; }});
}});
function color(group) {{ return groups[group] || '#667085'; }}
function pathBetween(s,t,sw,tw) {{
  const x0=s.x+nodeW, x1=t.x, y0=s.y+sw, y1=t.y+tw;
  const mx=(x0+x1)/2;
  return `M ${{x0}} ${{y0}} C ${{mx}} ${{y0}}, ${{mx}} ${{y1}}, ${{x1}} ${{y1}}`;
}}
function add(name, attrs, text) {{
  const el=document.createElementNS('http://www.w3.org/2000/svg',name);
  for (const [k,v] of Object.entries(attrs||{{}})) el.setAttribute(k,v);
  if (text !== undefined) el.textContent=text;
  svg.appendChild(el);
  return el;
}}
data.links.sort((a,b)=>b.value_sgd-a.value_sgd).forEach(l => {{
  const s=nodeMap.get(l.source), t=nodeMap.get(l.target);
  const width=Math.max(1,l.value_sgd*scale);
  const sy=s.sy+width/2, ty=t.ty+width/2;
  s.sy += width; t.ty += width;
  const p=add('path', {{d:pathBetween(s,t,sy,ty), fill:'none', stroke:color(l.source_group || l.target_group), 'stroke-width':width, 'stroke-opacity':0.24}});
  p.addEventListener('mousemove', e => {{
    tip.style.display='block'; tip.style.left=(e.offsetX+18)+'px'; tip.style.top=(e.offsetY+18)+'px';
    tip.innerHTML=`<strong>${{html(l.source)}} -> ${{html(l.target)}}</strong><br>${{fmt(l.value_sgd)}}`;
  }});
  p.addEventListener('mouseleave', () => tip.style.display='none');
}});
function wrapLabel(text, maxChars) {{
  const words = text.split(/\\s+/);
  const lines = [];
  let current = '';
  words.forEach(word => {{
    if ((current + ' ' + word).trim().length > maxChars && current) {{
      lines.push(current);
      current = word;
    }} else {{
      current = (current + ' ' + word).trim();
    }}
  }});
  if (current) lines.push(current);
  return lines.slice(0, 3);
}}
function addLabel(n) {{
  const leftSide = n.col < 3;
  const label = n.name.replace('Spend: ','');
  const lines = wrapLabel(label, leftSide ? 30 : 24);
  const valueLine = fmt(n.value);
  const allLines = [...lines, valueLine];
  const maxLen = Math.max(...allLines.map(line => line.length));
  const boxW = Math.min(leftSide ? 250 : 220, Math.max(96, maxLen * 7 + 18));
  const lineH = 15;
  const boxH = 14 + allLines.length * lineH;
  const tx = leftSide ? n.x + nodeW + 10 : n.x - 10;
  const boxX = leftSide ? tx : tx - boxW;
  let boxY = n.y + Math.min(n.h / 2, 28) - boxH / 2;
  boxY = Math.max(T + 4, Math.min(H - B - boxH, boxY));
  add('rect', {{x:boxX,y:boxY,width:boxW,height:boxH,rx:5,fill:'#ffffff','fill-opacity':0.92,stroke:'#d9e0e7','stroke-width':0.8}});
  allLines.forEach((line, i) => {{
    add('text', {{
      x:leftSide ? boxX + 9 : boxX + boxW - 9,
      y:boxY + 19 + i * lineH,
      'text-anchor':leftSide ? 'start' : 'end',
      'font-size':i === allLines.length - 1 ? 11 : 12,
      fill:i === allLines.length - 1 ? '#5f6b7a' : '#1d2733'
    }}, line);
  }});
}}
nodeMap.forEach(n => {{
  add('rect', {{x:n.x,y:n.y,width:nodeW,height:n.h,rx:3,fill:color(n.group),stroke:'#fff','stroke-width':1}});
}});
nodeMap.forEach(n => addLabel(n));
add('text', {{x:L,y:18,'font-size':16,'font-weight':700,fill:'#1d2733'}}, 'Net worth bridge: {money(summary["net_worth_change_sgd"])} increase flows into {money(summary["ending_net_worth_sgd"])} ending net worth');
add('text', {{x:W-R,y:18,'text-anchor':'end','font-size':12,fill:'#5f6b7a'}}, 'SGD; pooled Samuel + Amy; through May 2026');
</script>
<style>
#sankeyWrap{{position:relative;margin:18px 0}}.tip{{display:none;position:absolute;z-index:5;pointer-events:none;background:#1d2733;color:#fff;padding:8px 10px;border-radius:6px;font-size:12px;box-shadow:0 5px 18px rgba(29,39,51,.22)}}.tip strong{{color:#fff}}table td:nth-child(n+2){{font-variant-numeric:tabular-nums}}
</style>
"""
    write_html_report(REPORTS_DIR / "net_worth_sankey.html", "Net Worth Change Sankey", body)
    return {
        "report": str(REPORTS_DIR / "net_worth_sankey.html"),
        "flows": len(links),
        "net_worth_change_sgd": str(summary["net_worth_change_sgd"]),
    }


if __name__ == "__main__":
    print(run())
