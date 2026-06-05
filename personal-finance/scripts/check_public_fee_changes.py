from __future__ import annotations

import csv
from datetime import datetime, timezone
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any

from common import DATA_DIR, EXPORTS_DIR, REPORTS_DIR, html_table, write_csv, write_html_report


ESTIMATES_FILE = EXPORTS_DIR / "embedded_fund_fee_estimates.csv"
SNAPSHOT_FILE = DATA_DIR / "public_fee_source_snapshot.csv"
CHANGES_FILE = EXPORTS_DIR / "public_fee_source_changes.csv"
ISSUES_FILE = EXPORTS_DIR / "public_fee_source_check_issues.csv"

SNAPSHOT_COLUMNS = [
    "source_key",
    "institution",
    "account_id",
    "symbol",
    "name",
    "isin",
    "source_provider",
    "source_url",
    "fee_bps",
    "fee_percent",
    "fee_type",
    "confidence",
    "source_timestamp",
    "snapshot_timestamp",
]

CHANGE_COLUMNS = [
    "change_type",
    "source_key",
    "institution",
    "account_id",
    "symbol",
    "name",
    "isin",
    "source_provider",
    "old_fee_bps",
    "new_fee_bps",
    "old_fee_percent",
    "new_fee_percent",
    "source_url",
    "checked_at",
    "message",
]

ISSUE_COLUMNS = [
    "issue_type",
    "institution",
    "account_id",
    "symbol",
    "name",
    "source_provider",
    "source_url",
    "confidence",
    "message",
]


def read_csv(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def dec(value: str | None) -> Decimal | None:
    if not value:
        return None
    try:
        return Decimal(str(value).replace(",", ""))
    except (InvalidOperation, ValueError):
        return None


def source_key(row: dict[str, str]) -> str:
    isin = row.get("isin", "").strip()
    if isin:
        return f"isin:{isin}"
    parts = [
        row.get("institution", ""),
        row.get("account_id", ""),
        row.get("symbol", ""),
        row.get("name", ""),
        row.get("source_url", ""),
    ]
    return "holding:" + "|".join(parts)


def current_online_rows() -> tuple[list[dict[str, str]], list[dict[str, str]]]:
    rows = read_csv(ESTIMATES_FILE)
    online: list[dict[str, str]] = []
    issues: list[dict[str, str]] = []
    for row in rows:
        confidence = row.get("confidence", "")
        fee_bps = dec(row.get("fee_bps"))
        if confidence.startswith("online") and fee_bps is not None:
            normalized = {column: row.get(column, "") for column in SNAPSHOT_COLUMNS}
            normalized["source_key"] = source_key(row)
            normalized["snapshot_timestamp"] = datetime.now(timezone.utc).isoformat(timespec="seconds")
            online.append(normalized)
        else:
            issues.append(
                {
                    "issue_type": "public_fee_not_refreshed",
                    "institution": row.get("institution", ""),
                    "account_id": row.get("account_id", ""),
                    "symbol": row.get("symbol", ""),
                    "name": row.get("name", ""),
                    "source_provider": row.get("source_provider", ""),
                    "source_url": row.get("source_url", ""),
                    "confidence": confidence,
                    "message": "This public fee source was not refreshed online, so it was not used to update the fee-change snapshot.",
                }
            )
    return online, issues


def build_report(changes: list[dict[str, str]], issues: list[dict[str, str]], current_rows: list[dict[str, str]]) -> str:
    body = f"""
<div class="metric-row">
  <div class="metric"><strong>{len(changes)}</strong><span>fee listing changes</span></div>
  <div class="metric"><strong>{len(current_rows)}</strong><span>public fee sources refreshed</span></div>
  <div class="metric"><strong>{len(issues)}</strong><span>sources not refreshed</span></div>
</div>
<p class="warning">This check compares public OCF/TER/fund-fee percentages extracted online against the last saved local snapshot. It only updates the snapshot for rows that were successfully refreshed online.</p>
<h2>Changes</h2>
{html_table(changes, CHANGE_COLUMNS, limit=300)}
<h2>Not Refreshed</h2>
{html_table(issues, ISSUE_COLUMNS, limit=300)}
<h2>Current Snapshot Rows</h2>
{html_table(current_rows, SNAPSHOT_COLUMNS, limit=300)}
"""
    return body


def run() -> dict[str, Any]:
    checked_at = datetime.now(timezone.utc).isoformat(timespec="seconds")
    current_rows, issues = current_online_rows()
    previous_rows = read_csv(SNAPSHOT_FILE)
    previous_by_key = {row["source_key"]: row for row in previous_rows if row.get("source_key")}
    current_by_key = {row["source_key"]: row for row in current_rows}

    changes: list[dict[str, str]] = []
    for key, current in current_by_key.items():
        previous = previous_by_key.get(key)
        old_bps = dec(previous.get("fee_bps")) if previous else None
        new_bps = dec(current.get("fee_bps"))
        if previous is None:
            changes.append(
                {
                    "change_type": "new_source",
                    "source_key": key,
                    "institution": current.get("institution", ""),
                    "account_id": current.get("account_id", ""),
                    "symbol": current.get("symbol", ""),
                    "name": current.get("name", ""),
                    "isin": current.get("isin", ""),
                    "source_provider": current.get("source_provider", ""),
                    "old_fee_bps": "",
                    "new_fee_bps": current.get("fee_bps", ""),
                    "old_fee_percent": "",
                    "new_fee_percent": current.get("fee_percent", ""),
                    "source_url": current.get("source_url", ""),
                    "checked_at": checked_at,
                    "message": "New public fee source added to the local snapshot.",
                }
            )
        elif old_bps is not None and new_bps is not None and old_bps != new_bps:
            changes.append(
                {
                    "change_type": "fee_bps_changed",
                    "source_key": key,
                    "institution": current.get("institution", ""),
                    "account_id": current.get("account_id", ""),
                    "symbol": current.get("symbol", ""),
                    "name": current.get("name", ""),
                    "isin": current.get("isin", ""),
                    "source_provider": current.get("source_provider", ""),
                    "old_fee_bps": previous.get("fee_bps", ""),
                    "new_fee_bps": current.get("fee_bps", ""),
                    "old_fee_percent": previous.get("fee_percent", ""),
                    "new_fee_percent": current.get("fee_percent", ""),
                    "source_url": current.get("source_url", ""),
                    "checked_at": checked_at,
                    "message": "Public embedded fee percentage changed online.",
                }
            )

    for key, previous in previous_by_key.items():
        if key not in current_by_key:
            changes.append(
                {
                    "change_type": "source_missing_from_current_holdings",
                    "source_key": key,
                    "institution": previous.get("institution", ""),
                    "account_id": previous.get("account_id", ""),
                    "symbol": previous.get("symbol", ""),
                    "name": previous.get("name", ""),
                    "isin": previous.get("isin", ""),
                    "source_provider": previous.get("source_provider", ""),
                    "old_fee_bps": previous.get("fee_bps", ""),
                    "new_fee_bps": "",
                    "old_fee_percent": previous.get("fee_percent", ""),
                    "new_fee_percent": "",
                    "source_url": previous.get("source_url", ""),
                    "checked_at": checked_at,
                    "message": "A previously tracked public fee source is no longer in current parsed holdings.",
                }
            )

    write_csv(CHANGES_FILE, changes, CHANGE_COLUMNS)
    write_csv(ISSUES_FILE, issues, ISSUE_COLUMNS)
    if current_rows:
        write_csv(SNAPSHOT_FILE, current_rows, SNAPSHOT_COLUMNS)
    write_html_report(REPORTS_DIR / "public_fee_source_changes.html", "Public Fee Source Changes", build_report(changes, issues, current_rows))
    return {
        "changes": len(changes),
        "issues": len(issues),
        "sources_refreshed": len(current_rows),
        "snapshot_updated": bool(current_rows),
        "report": str(REPORTS_DIR / "public_fee_source_changes.html"),
    }


if __name__ == "__main__":
    print(run())
