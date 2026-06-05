from __future__ import annotations

import csv
import hashlib
import json
from collections import Counter, defaultdict
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from common import CONFIG_DIR, DATA_DIR, EXPORTS_DIR, PROCESSED_DIR, REPORTS_DIR, html_escape, html_table, read_json, write_csv, write_html_report, write_json


SNAPSHOT_FILE = DATA_DIR / "refresh_control_snapshot.json"
REPORT_FILE = REPORTS_DIR / "refresh_control_checks.html"
ACCEPTED_ISSUES_FILE = CONFIG_DIR / "refresh_control_accepted_issues.csv"

CONTROL_COLUMNS = ["check", "severity", "status", "count", "message", "suggested_action"]
DETAIL_COLUMNS = ["check", "severity", "item", "value", "message", "suggested_action"]
ACCEPTED_COLUMNS = ["check", "item", "value", "message", "accepted_on", "accepted_by", "reason"]


def read_csv_rows(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def dec(value: str | None) -> Decimal:
    if not value:
        return Decimal("0")
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return Decimal("0")


def money(value: Decimal, currency: str = "SGD") -> str:
    prefix = "S$" if currency == "SGD" else f"{currency} "
    return f"{prefix}{value:,.0f}"


def pct(value: Decimal) -> str:
    return f"{value:.1f}%"


def month_key(value: str) -> str:
    return value[:7] if value else ""


def row_hash(parts: list[Any]) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def add_control(rows: list[dict[str, Any]], check: str, severity: str, status: str, count: int, message: str, action: str = "") -> None:
    rows.append({"check": check, "severity": severity, "status": status, "count": count, "message": message, "suggested_action": action})


def add_detail(rows: list[dict[str, Any]], check: str, severity: str, item: str, value: Any, message: str, action: str = "") -> None:
    rows.append({"check": check, "severity": severity, "item": item, "value": value, "message": message, "suggested_action": action})


def accepted_key(row: dict[str, Any]) -> tuple[str, str, str, str]:
    return (
        str(row.get("check", "")),
        str(row.get("item", "")),
        str(row.get("value", "")),
        str(row.get("message", "")),
    )


def apply_accepted_issues(controls: list[dict[str, Any]], details: list[dict[str, Any]]) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    accepted_rows = read_csv_rows(ACCEPTED_ISSUES_FILE)
    accepted = {accepted_key(row) for row in accepted_rows}
    if not accepted:
        return controls, details, []

    visible_details = []
    suppressed_details = []
    for row in details:
        if accepted_key(row) in accepted:
            suppressed_details.append(row)
        else:
            visible_details.append(row)

    visible_by_check = Counter(row["check"] for row in visible_details)
    suppressed_by_check = Counter(row["check"] for row in suppressed_details)
    detail_checks = {row["check"] for row in details}
    visible_controls = []
    for row in controls:
        check = row["check"]
        if check not in detail_checks:
            visible_controls.append(row)
            continue
        visible_count = visible_by_check.get(check, 0)
        suppressed_count = suppressed_by_check.get(check, 0)
        if visible_count:
            new_row = dict(row)
            new_row["count"] = visible_count
            if suppressed_count:
                new_row["message"] = f"{visible_count} current items need review; {suppressed_count} accepted known items suppressed."
            visible_controls.append(new_row)
        elif suppressed_count:
            visible_controls.append(
                {
                    "check": check,
                    "severity": "info",
                    "status": "accepted",
                    "count": 0,
                    "message": f"All {suppressed_count} current items are accepted known issues and are suppressed from the active checklist.",
                    "suggested_action": "No action unless this recurs with new details.",
                }
            )
        else:
            visible_controls.append(row)
    return visible_controls, visible_details, suppressed_details


def inventory_file_snapshot() -> dict[str, Any]:
    rows = read_csv_rows(PROCESSED_DIR / "inventory_files.csv")
    files = {}
    for row in rows:
        key = row.get("content_hash") or row.get("path")
        if not key:
            continue
        files[key] = {
            "path": row.get("path", ""),
            "institution": row.get("institution", ""),
            "size_bytes": row.get("size_bytes", ""),
            "modified_at": row.get("modified_at", ""),
            "statement_period_start": row.get("statement_period_start", ""),
            "statement_period_end": row.get("statement_period_end", ""),
        }
    return {"file_count": len(rows), "files": files}


def transaction_history_snapshot() -> dict[str, Any]:
    rows = read_csv_rows(PROCESSED_DIR / "transactions.csv")
    groups: dict[str, dict[str, Any]] = {}
    latest_month = max((month_key(row.get("date", "")) for row in rows), default="")
    frozen_cutoff = latest_month
    for row in rows:
        month = month_key(row.get("date", ""))
        if not month or month >= frozen_cutoff:
            continue
        key = f"{month}|{row.get('institution', '')}|{row.get('account_id', '')}"
        group = groups.setdefault(key, {"count": 0, "sum_amount_sgd": Decimal("0"), "hashes": []})
        group["count"] += 1
        group["sum_amount_sgd"] += dec(row.get("amount_sgd"))
        group["hashes"].append(
            row_hash(
                [
                    row.get("transaction_id"),
                    row.get("date"),
                    row.get("institution"),
                    row.get("account_id"),
                    row.get("amount"),
                    row.get("currency"),
                    row.get("description_raw"),
                ]
            )
        )
    normalized = {}
    for key, group in groups.items():
        normalized[key] = {
            "count": group["count"],
            "sum_amount_sgd": str(group["sum_amount_sgd"].quantize(Decimal("0.01"))),
            "content_hash": row_hash(sorted(group["hashes"])),
        }
    return {"latest_month_excluded": latest_month, "groups": normalized}


def net_worth_history_snapshot() -> dict[str, Any]:
    rows = read_csv_rows(EXPORTS_DIR / "net_worth_monthly_stacked.csv")
    latest_month = max((row.get("month", "") for row in rows), default="")
    groups = {}
    for row in rows:
        month = row.get("month", "")
        if not month or month >= latest_month:
            continue
        parts = [month]
        for key in sorted(row):
            if key != "month":
                parts.append(f"{key}={row.get(key, '')}")
        groups[month] = {"total": row.get("Total", ""), "content_hash": row_hash(parts)}
    return {"latest_month_excluded": latest_month, "months": groups}


def parser_row_snapshot(latest_run: dict[str, Any]) -> dict[str, Any]:
    steps = latest_run.get("steps", {})
    tracked = {}
    for name, result in steps.items():
        tracked[name] = {
            key: result.get(key)
            for key in ["files", "transactions", "balances", "holdings", "issues", "validation_issues", "all_issues"]
            if key in result
        }
    return tracked


def compare_snapshots(previous: dict[str, Any], current: dict[str, Any], controls: list[dict[str, Any]], details: list[dict[str, Any]]) -> None:
    prev_files = previous.get("inventory", {}).get("files", {})
    curr_files = current.get("inventory", {}).get("files", {})
    new_files = [meta for key, meta in curr_files.items() if key not in prev_files]
    removed_files = [meta for key, meta in prev_files.items() if key not in curr_files]
    add_control(controls, "new_files", "info", "review", len(new_files), f"{len(new_files)} new source files detected since the previous refresh.")
    for meta in new_files[:50]:
        add_detail(details, "new_files", "info", meta.get("institution", ""), meta.get("path", ""), "New source file detected.")
    add_control(controls, "removed_files", "warning" if removed_files else "info", "review" if removed_files else "ok", len(removed_files), f"{len(removed_files)} previously seen source files are no longer present.")
    for meta in removed_files[:50]:
        add_detail(details, "removed_files", "warning", meta.get("institution", ""), meta.get("path", ""), "Previously seen source file no longer present.")

    prev_tx = previous.get("transactions", {}).get("groups", {})
    curr_tx = current.get("transactions", {}).get("groups", {})
    tx_changes = []
    for key, curr in curr_tx.items():
        prev = prev_tx.get(key)
        if prev and prev != curr:
            tx_changes.append((key, prev, curr))
    add_control(
        controls,
        "historical_transactions_changed",
        "critical" if tx_changes else "info",
        "review" if tx_changes else "ok",
        len(tx_changes),
        f"{len(tx_changes)} historical transaction month/account groups changed compared with the previous refresh.",
        "Review before trusting trend reports. This may be caused by parser changes, duplicate source files, or corrected raw data.",
    )
    for key, prev, curr in tx_changes[:100]:
        add_detail(details, "historical_transactions_changed", "critical", key, f"{prev} -> {curr}", "Historical transaction aggregate changed.")

    prev_nw = previous.get("net_worth", {}).get("months", {})
    curr_nw = current.get("net_worth", {}).get("months", {})
    nw_changes = []
    for month, curr in curr_nw.items():
        prev = prev_nw.get(month)
        if prev and prev != curr:
            nw_changes.append((month, prev, curr))
    add_control(
        controls,
        "historical_net_worth_changed",
        "critical" if nw_changes else "info",
        "review" if nw_changes else "ok",
        len(nw_changes),
        f"{len(nw_changes)} historical net worth months changed compared with the previous refresh.",
        "Review stale valuations, FX changes, duplicate files, and parser changes.",
    )
    for month, prev, curr in nw_changes[:100]:
        add_detail(details, "historical_net_worth_changed", "critical", month, f"{prev.get('total')} -> {curr.get('total')}", "Historical net worth month changed.")

    prev_parser = previous.get("parser_rows", {})
    curr_parser = current.get("parser_rows", {})
    parser_changes = []
    for step, curr in curr_parser.items():
        prev = prev_parser.get(step)
        if prev and prev != curr:
            parser_changes.append((step, prev, curr))
    add_control(controls, "parser_row_count_drift", "warning" if parser_changes else "info", "review" if parser_changes else "ok", len(parser_changes), f"{len(parser_changes)} parser step row-count summaries changed since previous refresh.")
    for step, prev, curr in parser_changes[:80]:
        add_detail(details, "parser_row_count_drift", "warning", step, f"{prev} -> {curr}", "Parser output count changed.")


def duplicate_checks(controls: list[dict[str, Any]], details: list[dict[str, Any]]) -> None:
    inventory = read_csv_rows(PROCESSED_DIR / "inventory_files.csv")
    dup_files = [row for row in inventory if row.get("duplicate_hash_group") or row.get("duplicate_statement_group")]
    overlap_files = [row for row in inventory if row.get("overlap_group")]
    add_control(controls, "duplicate_source_files", "warning" if dup_files else "info", "review" if dup_files else "ok", len(dup_files), f"{len(dup_files)} duplicate source-file candidates found.")
    for row in dup_files[:100]:
        add_detail(details, "duplicate_source_files", "warning", row.get("institution", ""), row.get("path", ""), "Duplicate hash or duplicate statement period candidate.")
    add_control(controls, "overlapping_source_periods", "warning" if overlap_files else "info", "review" if overlap_files else "ok", len(overlap_files), f"{len(overlap_files)} source files have overlapping statement/export periods.")
    for row in overlap_files[:100]:
        add_detail(details, "overlapping_source_periods", "warning", row.get("institution", ""), row.get("path", ""), "Overlapping statement/export period candidate.")

    tx_rows = read_csv_rows(PROCESSED_DIR / "transactions.csv")
    seen: defaultdict[str, list[dict[str, str]]] = defaultdict(list)
    for row in tx_rows:
        key = "|".join(
            [
                row.get("institution", ""),
                row.get("account_id", ""),
                row.get("date", ""),
                row.get("amount", ""),
                row.get("currency", ""),
                row.get("description_clean") or row.get("description_raw", ""),
            ]
        )
        seen[key].append(row)
    dup_tx = [(key, rows) for key, rows in seen.items() if len(rows) > 1]
    add_control(controls, "duplicate_transactions", "warning" if dup_tx else "info", "review" if dup_tx else "ok", len(dup_tx), f"{len(dup_tx)} duplicate transaction candidates found.")
    for key, rows in dup_tx[:100]:
        add_detail(details, "duplicate_transactions", "warning", key, len(rows), "Potential duplicate normalized transactions.")


def missing_statement_checks(controls: list[dict[str, Any]], details: list[dict[str, Any]]) -> None:
    rows = read_csv_rows(PROCESSED_DIR / "inventory_missing_months.csv")
    actionable = [row for row in rows if row.get("status") not in {"expected_gap", "known_gap", "normal"}]
    add_control(controls, "missing_expected_statements", "warning" if actionable else "info", "review" if actionable else "ok", len(actionable), f"{len(actionable)} actionable missing-statement candidates found.")
    for row in actionable[:100]:
        add_detail(details, "missing_expected_statements", "warning", row.get("institution", ""), row.get("month", ""), row.get("notes", ""), "Add statement file or mark as known gap.")


def net_worth_movement_checks(controls: list[dict[str, Any]], details: list[dict[str, Any]]) -> None:
    rows = read_csv_rows(EXPORTS_DIR / "net_worth_monthly_stacked_by_account.csv")
    months = sorted({row["month"] for row in rows})
    if len(months) < 2:
        return
    latest, previous = months[-1], months[-2]
    by_key: dict[tuple[str, str], dict[str, Decimal]] = defaultdict(lambda: defaultdict(Decimal))
    for row in rows:
        if row["month"] in {latest, previous}:
            key = (row.get("series", ""), row.get("account_id", ""))
            by_key[key][row["month"]] += dec(row.get("balance_sgd"))
    moves = []
    for (series, account), values in by_key.items():
        delta = values[latest] - values[previous]
        if abs(delta) >= Decimal("1000"):
            moves.append((abs(delta), series, account, delta))
    moves.sort(reverse=True)
    add_control(controls, "net_worth_movement_explainer", "info", "review", len(moves), f"{len(moves)} account/platform movements above S$1,000 in the latest month.")
    for _abs_delta, series, account, delta in moves[:30]:
        add_detail(details, "net_worth_movement_explainer", "info", f"{series} {account}", money(delta), f"Change from {previous} to {latest}.")


def large_transaction_checks(controls: list[dict[str, Any]], details: list[dict[str, Any]]) -> None:
    rows = read_csv_rows(PROCESSED_DIR / "categorized_transactions.csv") or read_csv_rows(PROCESSED_DIR / "transactions.csv")
    if not rows:
        return
    latest_month = max(month_key(row.get("date", "")) for row in rows if row.get("date"))
    large = []
    for row in rows:
        if month_key(row.get("date", "")) != latest_month:
            continue
        amount = abs(dec(row.get("amount_sgd")))
        if amount >= Decimal("5000"):
            large.append((amount, row))
    large.sort(reverse=True, key=lambda item: item[0])
    add_control(controls, "large_transactions_latest_month", "warning" if large else "info", "review" if large else "ok", len(large), f"{len(large)} transactions >= S$5,000 in {latest_month}.")
    for amount, row in large[:80]:
        add_detail(details, "large_transactions_latest_month", "warning", row.get("institution", ""), money(amount), f"{row.get('date')} {row.get('description_raw', '')}", "Confirm category/transfer treatment.")

    unmatched = read_csv_rows(PROCESSED_DIR / "unmatched_transfers.csv")
    big_unmatched = [row for row in unmatched if abs(dec(row.get("amount_sgd"))) >= Decimal("10000")]
    add_control(controls, "large_unmatched_transfers", "warning" if big_unmatched else "info", "review" if big_unmatched else "ok", len(big_unmatched), f"{len(big_unmatched)} unmatched transfer candidates >= S$10,000.")
    for row in big_unmatched[:80]:
        add_detail(details, "large_unmatched_transfers", "warning", row.get("institution", ""), row.get("amount_sgd", ""), f"{row.get('date')} {row.get('description_raw', '')}", "Review transfer matching/manual overrides.")


def spending_anomaly_checks(controls: list[dict[str, Any]], details: list[dict[str, Any]]) -> None:
    rows = read_csv_rows(EXPORTS_DIR / "monthly_spending_by_category.csv")
    if not rows:
        return
    months = sorted({row["month"] for row in rows})
    latest = months[-1]
    by_cat_month: defaultdict[str, dict[str, Decimal]] = defaultdict(dict)
    for row in rows:
        by_cat_month[row["category"]][row["month"]] = dec(row.get("outflow_sgd"))
    anomalies = []
    prior_months = months[-13:-1]
    for category, values in by_cat_month.items():
        latest_value = values.get(latest, Decimal("0"))
        prior_values = [values.get(month, Decimal("0")) for month in prior_months if values.get(month, Decimal("0")) > 0]
        if len(prior_values) < 3:
            continue
        avg = sum(prior_values) / len(prior_values)
        if latest_value >= Decimal("1000") and latest_value >= avg * Decimal("2"):
            anomalies.append((latest_value - avg, category, latest_value, avg))
    anomalies.sort(reverse=True)
    add_control(controls, "spending_anomalies", "warning" if anomalies else "info", "review" if anomalies else "ok", len(anomalies), f"{len(anomalies)} latest-month category spikes over 2x recent average.")
    for _delta, category, latest_value, avg in anomalies[:30]:
        add_detail(details, "spending_anomalies", "warning", category, money(latest_value), f"Latest month vs recent average {money(avg)}.", "Review transactions in this category.")


def stale_valuation_checks(controls: list[dict[str, Any]], details: list[dict[str, Any]]) -> None:
    rows = read_csv_rows(EXPORTS_DIR / "net_worth_monthly_stacked_by_account.csv")
    if not rows:
        return
    latest_month = max(row["month"] for row in rows)
    stale = []
    for row in rows:
        if row["month"] != latest_month:
            continue
        source_date = row.get("source_date", "")
        if source_date and source_date[:7] < latest_month and dec(row.get("balance_sgd")) > Decimal("1000"):
            stale.append(row)
    add_control(controls, "stale_valuations", "warning" if stale else "info", "review" if stale else "ok", len(stale), f"{len(stale)} latest net-worth rows use older source dates.")
    for row in stale[:80]:
        add_detail(details, "stale_valuations", "warning", row.get("series", ""), row.get("balance_sgd", ""), f"{row.get('account_name')} source date {row.get('source_date')}.", "Refresh source valuation or confirm carry-forward is acceptable.")


def fx_checks(latest_run: dict[str, Any], controls: list[dict[str, Any]], details: list[dict[str, Any]]) -> None:
    fx_step = latest_run.get("steps", {}).get("fetch_fx", {})
    cached = "cached" in str(fx_step.get("source", "")).lower()
    add_control(controls, "fx_freshness", "warning" if cached else "info", "review" if cached else "ok", 1 if cached else 0, f"FX source: {fx_step.get('source', '')}; latest table date: {fx_step.get('date_max_table', '')}.", "Reconnect internet and rerun if you want freshly downloaded FX." if cached else "")


def fee_sanity_checks(controls: list[dict[str, Any]], details: list[dict[str, Any]]) -> None:
    rows = read_csv_rows(EXPORTS_DIR / "fee_bps_latest_period.csv")
    if not rows:
        return
    flagged = []
    for row in rows:
        text = row.get("total_estimated_bps", "") + " " + row.get("actual_fee_basis", "")
        if "should" in text or "not available" in row.get("embedded_hidden_fee_bps", ""):
            flagged.append(row)
    add_control(controls, "fee_sanity", "warning" if flagged else "info", "review" if flagged else "ok", len(flagged), f"{len(flagged)} fee rows have schedule-vs-actual caveats or missing embedded fees.")
    for row in flagged[:50]:
        add_detail(details, "fee_sanity", "warning", f"{row.get('platform')} {row.get('investment')}", row.get("total_estimated_bps", ""), row.get("actual_fee_basis", ""), "Review if fee assumptions changed.")


def tax_wrapper_checks(controls: list[dict[str, Any]], details: list[dict[str, Any]]) -> None:
    holdings = read_csv_rows(PROCESSED_DIR / "holdings.csv")
    srs = [row for row in holdings if row.get("institution") == "endowus" and dec(row.get("market_value_sgd")) > 0]
    isa = [row for row in holdings if row.get("account_id") == "VG0040856-001" and dec(row.get("market_value_sgd")) > 0]
    pension = [row for row in holdings if row.get("account_id") == "VANGUARD_PERSONAL_PENSION" and dec(row.get("market_value_sgd")) > 0]
    add_control(controls, "tax_wrappers", "info", "review", len(srs) + len(isa) + len(pension), "Tax-wrapper holdings summarized for SRS/ISA/pension.")
    for label, rows in [("SRS", srs), ("ISA", isa), ("Pension", pension)]:
        total = sum((dec(row.get("market_value_sgd")) for row in rows), Decimal("0"))
        add_detail(details, "tax_wrappers", "info", label, money(total), f"{len(rows)} current holding rows.")


def manual_assumption_checks(controls: list[dict[str, Any]], details: list[dict[str, Any]]) -> None:
    manual_files = [
        PROCESSED_DIR / "manual_legacy_pension_balances.csv",
        PROCESSED_DIR / "manual_property_balances.csv",
        PROCESSED_DIR / "manual_premium_bonds_balances.csv",
    ]
    total_rows = 0
    for path in manual_files:
        rows = read_csv_rows(path)
        total_rows += len(rows)
        latest = max((row.get("date", "") for row in rows), default="")
        add_detail(details, "manual_assumptions", "info", path.name, len(rows), f"Latest manual/inferred row date {latest}.", "Review assumptions periodically.")
    add_control(controls, "manual_assumptions", "info", "review", total_rows, f"{total_rows} manual/inferred balance rows are included in net worth.")


def build_report(controls: list[dict[str, Any]], details: list[dict[str, Any]]) -> str:
    severity_counts = Counter(row["severity"] for row in controls)
    body = "<div class=\"metric-row\">"
    for severity in ["critical", "warning", "info"]:
        body += f"<div class=\"metric\"><strong>{severity_counts.get(severity, 0)}</strong><span>{html_escape(severity)} checks</span></div>"
    body += "</div>"
    body += "<h2>Control Summary</h2>" + html_table(controls, CONTROL_COLUMNS, limit=200)
    body += "<h2>Control Details</h2>" + html_table(details, DETAIL_COLUMNS, limit=1000)
    suppressed = read_csv_rows(EXPORTS_DIR / "refresh_control_suppressed_details.csv")
    body += "<h2>Accepted / Suppressed Known Issues</h2>" + html_table(suppressed, DETAIL_COLUMNS, limit=300)
    return body


def run() -> dict[str, Any]:
    controls: list[dict[str, Any]] = []
    details: list[dict[str, Any]] = []
    previous = read_json(SNAPSHOT_FILE, {})
    latest_run = read_json(DATA_DIR / "latest_run.json", {})
    current = {
        "created_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "inventory": inventory_file_snapshot(),
        "transactions": transaction_history_snapshot(),
        "net_worth": net_worth_history_snapshot(),
        "parser_rows": parser_row_snapshot(latest_run),
    }

    if previous:
        compare_snapshots(previous, current, controls, details)
    else:
        add_control(controls, "baseline_snapshot", "info", "ok", 1, "Created first refresh-control snapshot. Historical-change alarms begin on the next refresh.")

    duplicate_checks(controls, details)
    missing_statement_checks(controls, details)
    net_worth_movement_checks(controls, details)
    large_transaction_checks(controls, details)
    spending_anomaly_checks(controls, details)
    stale_valuation_checks(controls, details)
    fx_checks(latest_run, controls, details)
    fee_sanity_checks(controls, details)
    tax_wrapper_checks(controls, details)
    manual_assumption_checks(controls, details)

    controls, details, suppressed = apply_accepted_issues(controls, details)

    write_csv(EXPORTS_DIR / "refresh_control_checks.csv", controls, CONTROL_COLUMNS)
    write_csv(EXPORTS_DIR / "refresh_control_check_details.csv", details, DETAIL_COLUMNS)
    write_csv(EXPORTS_DIR / "refresh_control_suppressed_details.csv", suppressed, DETAIL_COLUMNS)
    write_html_report(REPORT_FILE, "Refresh Control Checks", build_report(controls, details))
    write_json(SNAPSHOT_FILE, current)
    return {
        "controls": len(controls),
        "details": len(details),
        "critical": sum(1 for row in controls if row["severity"] == "critical"),
        "warnings": sum(1 for row in controls if row["severity"] == "warning"),
        "report": str(REPORT_FILE),
    }


if __name__ == "__main__":
    print(run())
