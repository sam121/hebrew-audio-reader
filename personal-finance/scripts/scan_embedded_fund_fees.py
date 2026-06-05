from __future__ import annotations

import csv
import re
import ssl
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from html import unescape
from pathlib import Path
from urllib.error import URLError
from urllib.request import Request, urlopen

from common import CONFIG_DIR, EXPORTS_DIR, PROCESSED_DIR, REPORTS_DIR, ensure_dirs, html_escape, html_table, write_csv, write_html_report


SOURCE_FILE = CONFIG_DIR / "fund_fee_sources.csv"
HOLDINGS_FILE = PROCESSED_DIR / "holdings.csv"

DETAIL_COLUMNS = [
    "owner",
    "institution",
    "account_id",
    "holding_date",
    "symbol",
    "name",
    "isin",
    "market_value_sgd",
    "fee_bps",
    "fee_percent",
    "estimated_annual_embedded_fee_sgd",
    "fee_type",
    "source_provider",
    "source_url",
    "source_type",
    "source_timestamp",
    "confidence",
    "matched_text",
    "notes",
]

ISSUE_COLUMNS = [
    "institution",
    "account_id",
    "symbol",
    "name",
    "issue_type",
    "message",
    "suggested_action",
]


@dataclass
class SourceSpec:
    match_symbol: str
    match_name: str
    isin: str
    source_provider: str
    source_url: str
    source_type: str
    notes: str


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def dec(value: str | None) -> Decimal:
    if not value:
        return Decimal("0")
    try:
        return Decimal(str(value).replace(",", ""))
    except InvalidOperation:
        return Decimal("0")


def clean_text(raw: str) -> str:
    text = re.sub(r"<script\b.*?</script>", " ", raw, flags=re.I | re.S)
    text = re.sub(r"<style\b.*?</style>", " ", text, flags=re.I | re.S)
    text = re.sub(r"<[^>]+>", " ", text)
    text = unescape(text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def fetch_text(url: str, timeout: int = 25) -> tuple[str, str]:
    request = Request(
        url,
        headers={
            "User-Agent": "personal-finance-local-fee-scanner/1.0",
            "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        },
    )
    context = ssl.create_default_context()
    with urlopen(request, timeout=timeout, context=context) as response:
        content_type = response.headers.get_content_charset() or "utf-8"
        body = response.read().decode(content_type, errors="replace")
    return clean_text(body), datetime.now(timezone.utc).isoformat(timespec="seconds")


def percent_to_bps(value: str) -> Decimal:
    return Decimal(value.replace(",", "")) * Decimal("100")


def first_fee_match(text: str) -> tuple[Decimal | None, str, str]:
    patterns = [
        ("ongoing_charge", r"Ongoing charge \(%\)\s*\|?\s*([0-9]+(?:\.[0-9]+)?)"),
        ("ongoing_charge", r"Ongoing Charge\s*(?:\||:)?\s*([0-9]+(?:\.[0-9]+)?)%"),
        ("ongoing_charges_figure", r"Ongoing Charges Figure \(OCF\).*?([0-9]+(?:\.[0-9]+)?)%"),
        ("fund_fee", r"Fund fees\s*(?:\[Button: Fund fees\])?\s*([0-9]+(?:\.[0-9]+)?)%\s*p\.a\."),
        ("expense_ratio", r"Expense Ratio\s*(?:\||:)?\s*([0-9]+(?:\.[0-9]+)?)%"),
        ("ter", r"(?:TER|Total Expense Ratio)\s*(?:of|is|:|\|)?\s*([0-9]+(?:\.[0-9]+)?)%"),
        ("product_charge", r"Product charges.*?Ongoing charge \(%\).*?([0-9]+(?:\.[0-9]+)?)",),
    ]
    for fee_type, pattern in patterns:
        match = re.search(pattern, text, flags=re.I | re.S)
        if not match:
            continue
        value = match.group(1)
        start = max(0, match.start() - 80)
        end = min(len(text), match.end() + 80)
        snippet = text[start:end]
        return percent_to_bps(value), fee_type, snippet
    return None, "", ""


def load_sources() -> list[SourceSpec]:
    specs = []
    for row in read_csv(SOURCE_FILE):
        specs.append(
            SourceSpec(
                match_symbol=row.get("match_symbol", "").strip(),
                match_name=row.get("match_name", "").strip(),
                isin=row.get("isin", "").strip(),
                source_provider=row.get("source_provider", "").strip(),
                source_url=row.get("source_url", "").strip(),
                source_type=row.get("source_type", "").strip(),
                notes=row.get("notes", "").strip(),
            )
        )
    return specs


def find_source(row: dict[str, str], specs: list[SourceSpec]) -> SourceSpec | None:
    symbol = row.get("symbol", "").strip().lower()
    name = row.get("name", "").strip().lower()
    for spec in specs:
        if spec.match_symbol and spec.match_symbol.lower() == symbol:
            return spec
    for spec in specs:
        if spec.match_name and (spec.match_name.lower() in name or name in spec.match_name.lower()):
            return spec
    return None


def latest_holdings() -> list[dict[str, str]]:
    rows = read_csv(HOLDINGS_FILE)
    latest: dict[tuple[str, str, str, str, str], dict[str, str]] = {}
    for row in rows:
        asset_class = row.get("asset_class", "").lower()
        if asset_class in {"cash", "private_equity"}:
            continue
        name = row.get("name", "").strip()
        symbol = row.get("symbol", "").strip()
        if not name and not symbol:
            continue
        key = (
            row.get("owner", ""),
            row.get("institution", ""),
            row.get("account_id", ""),
            symbol,
            name,
        )
        existing = latest.get(key)
        if not existing or row.get("date", "") > existing.get("date", ""):
            latest[key] = row
    return sorted(latest.values(), key=lambda r: (r.get("institution", ""), r.get("account_id", ""), r.get("name", "")))


def build_report(rows: list[dict[str, str]], issues: list[dict[str, str]]) -> str:
    total_embedded = sum(dec(row.get("estimated_annual_embedded_fee_sgd")) for row in rows)
    matched = sum(1 for row in rows if row.get("confidence", "").startswith("online"))
    body = f"""
<div class="metric-row">
  <div class="metric"><strong>{len(rows)}</strong><span>fund holdings reviewed</span></div>
  <div class="metric"><strong>{matched}</strong><span>online fee matches</span></div>
  <div class="metric"><strong>S${total_embedded:,.2f}</strong><span>estimated annual embedded fund cost</span></div>
  <div class="metric"><strong>{len(issues)}</strong><span>issues / missing sources</span></div>
</div>
<p class="warning">Embedded fund costs are estimates: they are deducted inside fund NAV/performance, not visible as cash transactions. This report uses the latest parsed holding value multiplied by the latest online OCF/TER/fund-fee percentage found from the configured public source.</p>
<h2>Embedded Fee Estimates</h2>
{html_table(rows, ["institution", "account_id", "name", "symbol", "isin", "market_value_sgd", "fee_percent", "estimated_annual_embedded_fee_sgd", "source_provider", "confidence"], limit=300)}
<h2>Issues</h2>
{html_table(issues, ISSUE_COLUMNS, limit=300)}
<h2>Source Detail</h2>
{html_table(rows, ["institution", "name", "fee_type", "matched_text", "source_url", "notes"], limit=300)}
"""
    return body


def main() -> int:
    ensure_dirs()
    specs = load_sources()
    if not specs:
        print(f"No fund fee source specs found at {SOURCE_FILE}", file=sys.stderr)
        return 1

    fee_cache: dict[str, tuple[Decimal | None, str, str, str, str]] = {}
    output_rows: list[dict[str, str]] = []
    issues: list[dict[str, str]] = []

    for holding in latest_holdings():
        source = find_source(holding, specs)
        if not source:
            issues.append(
                {
                    "institution": holding.get("institution", ""),
                    "account_id": holding.get("account_id", ""),
                    "symbol": holding.get("symbol", ""),
                    "name": holding.get("name", ""),
                    "issue_type": "missing_source",
                    "message": "No configured public fee source for this holding.",
                    "suggested_action": "Add a row to config/fund_fee_sources.csv with an ISIN and public source URL.",
                }
            )
            continue

        if source.source_url not in fee_cache:
            try:
                text, timestamp = fetch_text(source.source_url)
                fee_bps, fee_type, snippet = first_fee_match(text)
                if fee_bps is None:
                    issues.append(
                        {
                            "institution": holding.get("institution", ""),
                            "account_id": holding.get("account_id", ""),
                            "symbol": holding.get("symbol", ""),
                            "name": holding.get("name", ""),
                            "issue_type": "fee_not_found",
                            "message": f"Fetched {source.source_provider} but no OCF/TER/fund-fee pattern was found.",
                            "suggested_action": "Use a more specific fund costs page or add a parser pattern.",
                        }
                    )
                fee_cache[source.source_url] = (fee_bps, fee_type, snippet, timestamp, "online_extracted" if fee_bps is not None else "needs_review")
            except URLError as exc:
                fee_cache[source.source_url] = (None, "", "", datetime.now(timezone.utc).isoformat(timespec="seconds"), "fetch_failed")
                issues.append(
                    {
                        "institution": holding.get("institution", ""),
                        "account_id": holding.get("account_id", ""),
                        "symbol": holding.get("symbol", ""),
                        "name": holding.get("name", ""),
                        "issue_type": "fetch_failed",
                        "message": f"Could not fetch public source: {exc}",
                        "suggested_action": "Rerun with network access or check the source URL.",
                    }
                )

        fee_bps, fee_type, snippet, timestamp, confidence = fee_cache[source.source_url]
        market_value_sgd = dec(holding.get("market_value_sgd"))
        estimated = Decimal("0")
        fee_percent = ""
        if fee_bps is not None:
            estimated = market_value_sgd * fee_bps / Decimal("10000")
            fee_percent = str(fee_bps / Decimal("100"))

        output_rows.append(
            {
                "owner": holding.get("owner", ""),
                "institution": holding.get("institution", ""),
                "account_id": holding.get("account_id", ""),
                "holding_date": holding.get("date", ""),
                "symbol": holding.get("symbol", ""),
                "name": holding.get("name", ""),
                "isin": source.isin,
                "market_value_sgd": f"{market_value_sgd:.6f}",
                "fee_bps": "" if fee_bps is None else f"{fee_bps:.4f}",
                "fee_percent": fee_percent,
                "estimated_annual_embedded_fee_sgd": f"{estimated:.6f}",
                "fee_type": fee_type,
                "source_provider": source.source_provider,
                "source_url": source.source_url,
                "source_type": source.source_type,
                "source_timestamp": timestamp,
                "confidence": confidence,
                "matched_text": snippet[:500],
                "notes": source.notes,
            }
        )

    write_csv(EXPORTS_DIR / "embedded_fund_fee_estimates.csv", output_rows, DETAIL_COLUMNS)
    write_csv(EXPORTS_DIR / "embedded_fund_fee_issues.csv", issues, ISSUE_COLUMNS)
    write_html_report(REPORTS_DIR / "embedded_fund_fees.html", "Embedded Fund Fee Scanner", build_report(output_rows, issues))
    print(
        {
            "rows": len(output_rows),
            "issues": len(issues),
            "report": str(REPORTS_DIR / "embedded_fund_fees.html"),
        }
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
