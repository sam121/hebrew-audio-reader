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
    positive_investment_gains = {
        row["platform"]: row["estimated_gain_sgd"]
        for row in investment_rows
        if isinstance(row.get("estimated_gain_sgd"), Decimal) and row["estimated_gain_sgd"] > 0
    }
    investment_gain_total = sum(positive_investment_gains.values(), Decimal("0"))
    fx_impact, fx_rows = estimated_fx_impact()
    fx_gain = fx_impact if fx_impact > 0 else Decimal("0")
    fx_drag = abs(fx_impact) if fx_impact < 0 else Decimal("0")
    new_tracked_evelyn_funding = max(Decimal("0"), investment_cash_flows().get("Evelyn", Decimal("0")))
    residual = ending_total + spending_total + fx_drag - opening_total - income_total - investment_gain_total - fx_gain - new_tracked_evelyn_funding

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
                "source": "Investment gains",
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
            "component": "IBKR net funding not source-matched",
            "value_sgd": net_funding.get("IBKR", Decimal("0")),
            "note": "IBKR balance growth after removing estimated IBKR investment gains. This is funding/redeployment, not gain.",
        },
        {
            "component": "Vanguard net funding / pension consolidation",
            "value_sgd": net_funding.get("Vanguard", Decimal("0")),
            "note": "Vanguard balance growth after removing estimated Vanguard investment gains. Much of this should map to legacy pension transfers.",
        },
        {
            "component": "Stripe balance increase not separately modelled",
            "value_sgd": platform_change.get("Stripe", Decimal("0")),
            "note": "Stripe asset balance increased. Stripe vesting income is included in income, but the asset/value bridge is not fully modelled.",
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
            "component": "Endowus balance reduction / incomplete flows",
            "value_sgd": platform_change.get("Endowus", Decimal("0")),
            "note": "Endowus is an investment asset, but complete contribution/withdrawal flows are not currently parsed.",
        },
        {
            "component": "Legacy pensions reduction",
            "value_sgd": platform_change.get("Legacy Pensions", Decimal("0")),
            "note": "Legacy pension balances disappear when consolidated/transferred, mostly offsetting Vanguard funding.",
        },
    ]
    subtotal = sum((row["value_sgd"] for row in rows), Decimal("0"))
    rows.extend(
        [
            {
                "component": "Subtotal of not-yet-bridged platform movements",
                "value_sgd": subtotal,
                "note": "Platform changes after removing estimated IBKR/Vanguard/Evelyn gains and Evelyn funding.",
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
            "component": "Estimated investment gains",
            "value_sgd": summary["estimated_investment_gains_sgd"],
            "explanation": "Balance-derived gain estimate for platforms with usable cash-flow data.",
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
            "explanation": "Unmodelled gains/flows/data additions, including areas where platform flows are incomplete.",
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
            "step": "Estimated investment gains",
            "amount_sgd": summary["estimated_investment_gains_sgd"],
            "running_net_worth_sgd": summary["opening_net_worth_sgd"] + summary["income_minus_spending_sgd"] + summary["estimated_investment_gains_sgd"],
            "note": "Estimated gains for platforms with usable cash-flow data.",
        },
        {
            "step": "Evelyn funding / newly tracked asset",
            "amount_sgd": summary["evelyn_funding_newly_tracked_asset_sgd"],
            "running_net_worth_sgd": summary["opening_net_worth_sgd"] + summary["income_minus_spending_sgd"] + summary["estimated_investment_gains_sgd"] + summary["evelyn_funding_newly_tracked_asset_sgd"],
            "note": "Visible during the period; may be newly visible wealth rather than newly created wealth.",
        },
        {
            "step": "Estimated FX impact",
            "amount_sgd": summary["estimated_fx_impact_sgd"],
            "running_net_worth_sgd": summary["opening_net_worth_sgd"] + summary["income_minus_spending_sgd"] + summary["estimated_investment_gains_sgd"] + summary["evelyn_funding_newly_tracked_asset_sgd"] + summary["estimated_fx_impact_sgd"],
            "note": "Estimated FX revaluation on opening foreign-currency balances.",
        },
        {
            "step": "Remaining reconciliation / unclassified growth",
            "amount_sgd": summary["remaining_reconciliation_unclassified_growth_sgd"],
            "running_net_worth_sgd": summary["ending_net_worth_sgd"],
            "note": "Unmodelled gains/flows/data additions that still need cleaner source matching.",
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
  <div class="metric"><strong>{money(summary["estimated_investment_gains_sgd"])}</strong><span>Estimated investment gains</span></div>
  <div class="metric"><strong>{money(summary["estimated_fx_impact_sgd"])}</strong><span>Estimated FX impact</span></div>
</div>
<h2>Full Net Worth Bridge</h2>
<p>This is the main arithmetic: start with opening net worth, add Sam income and Amy income, subtract spending to get retained income, then add investment gains, FX, newly visible assets, and the remaining reconciliation item.</p>
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
<p>This breaks down the {money(summary["remaining_reconciliation_unclassified_growth_sgd"])} residual. The big positive lines are mostly funding/redeployment that has not yet been tied back cleanly to a source account or prior asset. The negative lines are offsets from assets that fell or disappeared.</p>
{table(residual_breakdown, ["component", "value_sgd", "note"])}
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
  if (['Investment gains'].includes(name)) return 1;
  return 0;
}};
const orderScore = n => {{
  const fixed = {{
    'Income retained after spending': -80, 'Net worth increase': -50, 'Opening net worth carried forward': -40,
    'Investment gains': -40, 'Evelyn funding / newly tracked asset': -30, 'FX revaluation gain': -20,
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
