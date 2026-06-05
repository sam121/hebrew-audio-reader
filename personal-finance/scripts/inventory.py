from __future__ import annotations

import csv
import re
from collections import defaultdict
from datetime import datetime
from pathlib import Path
from typing import Any

from common import (
    INVENTORY_COLUMNS,
    PROCESSED_DIR,
    SOURCE_LIMITATION_COLUMNS,
    SOURCE_ROOT,
    add_months,
    ensure_dirs,
    html_table,
    institution_from_folder,
    make_issue,
    month_iter,
    parse_date,
    parse_month_token,
    parser_source_file,
    sha256_file,
    source_path,
    stable_id,
    write_csv,
    write_html_report,
)


MISSING_MONTH_COLUMNS = [
    "owner",
    "institution",
    "account_id",
    "statement_type",
    "month",
    "status",
    "notes",
]

SOURCE_LIMITATIONS = [
    {
        "owner": "samuel",
        "institution": "wise",
        "account_id": "ALL",
        "known_account_existed_before_available_records": True,
        "earliest_available_record_date": "2019-05-16",
        "likely_reason": "Apparent 7-year Wise export/history limit.",
        "notes": "Treat 2019-05-16 as earliest exported record, not true account inception.",
    },
    {
        "owner": "samuel",
        "institution": "barclays",
        "account_id": "ALL",
        "known_account_existed_before_available_records": True,
        "earliest_available_record_date": "2019-01-01",
        "likely_reason": "Apparent 7-year Barclays download/history limit.",
        "notes": "Treat Jan 2019 as earliest downloaded record, not true account inception.",
    },
]


def detect_owner_institution(path: Path) -> tuple[str, str]:
    rel = path.relative_to(SOURCE_ROOT)
    parts = rel.parts
    owner = "samuel" if parts and parts[0] == "Sam" else (parts[0].lower() if parts else "unknown")
    institution = institution_from_folder(parts[1]) if len(parts) > 1 else "unknown"
    return owner, institution


def file_type(path: Path) -> str:
    return path.suffix.lower().lstrip(".") or "unknown"


def strip_copy_suffix(text: str) -> str:
    return re.sub(r"\s+\(\d+\)$", "", text.strip())


def parse_ibkr_analysis_period(path: Path) -> tuple[Any, Any]:
    periods = []
    try:
        with path.open(newline="", encoding="utf-8-sig") as f:
            for row in csv.reader(f):
                if len(row) >= 4 and row[1].strip() == "MetaInfo" and row[2].strip() == "Analysis Period":
                    match = re.match(r"(.+?)\s+-\s+(.+)", row[3].strip())
                    if not match:
                        continue
                    try:
                        start = datetime.strptime(match.group(1).strip(), "%B %d, %Y").date()
                        end = datetime.strptime(match.group(2).strip(), "%B %d, %Y").date()
                        periods.append((start, end))
                    except ValueError:
                        continue
    except OSError:
        return None, None
    if not periods:
        return None, None
    return min(start for start, _end in periods), max(end for _start, end in periods)


def detect_metadata(path: Path, owner: str, institution: str) -> dict[str, Any]:
    name = path.name
    stem = path.stem
    metadata: dict[str, Any] = {
        "parsed_date": None,
        "detected_account_id": "",
        "statement_type": "",
        "statement_period_start": None,
        "statement_period_end": None,
        "notes": "",
    }

    if institution == "wise":
        match = re.match(r"statement_(?P<account>\d+)_(?P<currency>[A-Z]{3})_(?P<start>\d{4}-\d{2}-\d{2})_(?P<end>\d{4}-\d{2}-\d{2})\.csv$", name)
        if match:
            metadata.update(
                {
                    "parsed_date": parse_date(match.group("end")),
                    "detected_account_id": match.group("account"),
                    "statement_type": f"wise_{match.group('currency')}_export",
                    "statement_period_start": parse_date(match.group("start")),
                    "statement_period_end": parse_date(match.group("end")),
                    "notes": "Export date range, not true account inception.",
                }
            )
        return metadata

    if institution == "dbs":
        base = strip_copy_suffix(stem)
        if "_" in base:
            statement_type, token = base.rsplit("_", 1)
            start, end = parse_month_token(token)
            metadata.update(
                {
                    "parsed_date": end,
                    "detected_account_id": "consolidated",
                    "statement_type": statement_type,
                    "statement_period_start": start,
                    "statement_period_end": end,
                }
            )
        return metadata

    if institution == "barclays":
        date_match = re.search(r"(?P<day>\d{2}-[A-Z]{3}-\d{2})", name, flags=re.IGNORECASE)
        account_match = re.search(r"\bAC\s+(?P<account>\d+)", name)
        parsed = parse_date(date_match.group("day")) if date_match else None
        if name.startswith("Statement of Fees Covering Letter"):
            statement_type = "statement_of_fees_covering_letter"
        elif name.startswith("Statement of Fees"):
            statement_type = "statement_of_fees"
        elif name.startswith("Statement"):
            statement_type = "regular_statement"
        else:
            statement_type = "unknown_barclays_pdf"
        period_start = parsed.replace(day=1) if parsed else None
        metadata.update(
            {
                "parsed_date": parsed,
                "detected_account_id": account_match.group("account") if account_match else "",
                "statement_type": statement_type,
                "statement_period_start": period_start,
                "statement_period_end": parsed,
                "notes": "Filename statement date used as monthly period marker." if parsed else "",
            }
        )
        return metadata

    if institution == "endowus":
        match = re.match(
            r"Endowus_Statement_(?P<account>\d+)_(?P<start>\d{2}_\d{2}_\d{4})_to_(?P<end>\d{2}_\d{2}_\d{4})\.pdf$",
            name,
        )
        if match:
            start = parse_date(match.group("start").replace("_", "-"))
            end = parse_date(match.group("end").replace("_", "-"))
            metadata.update(
                {
                    "parsed_date": end,
                    "detected_account_id": match.group("account"),
                    "statement_type": "monthly_statement",
                    "statement_period_start": start,
                    "statement_period_end": end,
                }
            )
        return metadata

    if institution == "ibkr":
        period_start, period_end = parse_ibkr_analysis_period(path)
        match = re.search(r"_Inception_(?P<month>[A-Za-z]+)_(?P<day>\d{1,2})_(?P<year>\d{4})\.csv$", name)
        parsed = None
        if match:
            parsed = datetime.strptime(
                f"{match.group('month')} {match.group('day')} {match.group('year')}",
                "%B %d %Y",
            ).date()
        metadata.update(
            {
                "parsed_date": period_end or parsed,
                "detected_account_id": "",
                "statement_type": "portfolioanalyst_csv",
                "statement_period_start": period_start or parse_date("2022-02-28"),
                "statement_period_end": period_end or parsed,
                "notes": "Internal PortfolioAnalyst analysis period used." if period_start and period_end else "Filename date used; internal analysis period not found.",
            }
        )
        return metadata

    if institution == "vanguard":
        metadata.update(
            {
                "parsed_date": None,
                "detected_account_id": "",
                "statement_type": "workbook_export",
                "statement_period_start": None,
                "statement_period_end": None,
                "notes": "Workbook contains separate ISA and pension sheets.",
            }
        )
        return metadata

    return metadata


def expected_monthly_key(row: dict[str, Any]) -> tuple[str, str, str, str] | None:
    institution = row["institution"]
    account_id = row.get("detected_account_id") or ""
    statement_type = row.get("statement_type") or ""
    if institution == "endowus" and statement_type == "monthly_statement":
        return row["owner"], institution, account_id, statement_type
    if institution == "dbs" and statement_type in {"DBS_POSB Consolidated Statement", "Credit Cards Consolidated Statement"}:
        return row["owner"], institution, account_id, statement_type
    if institution == "barclays" and statement_type == "regular_statement" and account_id == "43168786":
        return row["owner"], institution, account_id, statement_type
    return None


def detect_missing_months(rows: list[dict[str, Any]]) -> list[dict[str, Any]]:
    by_key: dict[tuple[str, str, str, str], set[date]] = defaultdict(set)
    for row in rows:
        key = expected_monthly_key(row)
        period = row.get("statement_period_start")
        if key and period:
            by_key[key].add(period.replace(day=1))

    missing: list[dict[str, Any]] = []
    for (owner, institution, account_id, statement_type), months in sorted(by_key.items()):
        if not months:
            continue
        for month in month_iter(min(months), max(months)):
            if month not in months:
                missing.append(
                    {
                        "owner": owner,
                        "institution": institution,
                        "account_id": account_id,
                        "statement_type": statement_type,
                        "month": month,
                        "status": "candidate",
                        "notes": "Expected monthly statement was not found in inventory.",
                    }
                )
    return missing


def build_inventory(source_root: Path = SOURCE_ROOT) -> tuple[list[dict[str, Any]], list[dict[str, Any]]]:
    rows: list[dict[str, Any]] = []
    issues: list[dict[str, Any]] = []
    if not source_root.exists():
        issues.append(
            make_issue(
                "inventory",
                "error",
                "samuel",
                "all",
                "ALL",
                f"Source folder does not exist: {source_root}",
                "Confirm FINANCE_SOURCE_ROOT or the iCloud folder location.",
            )
        )
        return rows, issues

    files = [
        p
        for p in source_root.rglob("*")
        if p.is_file() and not p.name.startswith(".") and not p.name.startswith("~$")
    ]
    for path in sorted(files):
        owner, institution = detect_owner_institution(path)
        metadata = detect_metadata(path, owner, institution)
        try:
            stat = path.stat()
        except FileNotFoundError:
            continue
        row = {
            "inventory_id": stable_id("inv", parser_source_file(path), stat.st_size, stat.st_mtime_ns),
            "path": parser_source_file(path),
            "owner": owner,
            "institution": institution,
            "file_type": file_type(path),
            "parsed_date": metadata["parsed_date"],
            "modified_at": datetime.fromtimestamp(stat.st_mtime).isoformat(timespec="seconds"),
            "size_bytes": stat.st_size,
            "content_hash": sha256_file(path),
            "detected_account_id": metadata["detected_account_id"],
            "statement_type": metadata["statement_type"],
            "statement_period_start": metadata["statement_period_start"],
            "statement_period_end": metadata["statement_period_end"],
            "duplicate_hash_group": "",
            "duplicate_statement_group": "",
            "overlap_group": "",
            "missing_month_candidate": False,
            "notes": metadata["notes"],
        }
        rows.append(row)

    by_hash: dict[str, list[dict[str, Any]]] = defaultdict(list)
    by_statement: dict[tuple[Any, ...], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        by_hash[row["content_hash"]].append(row)
        key = (
            row["owner"],
            row["institution"],
            row["detected_account_id"],
            row["statement_type"],
            row["statement_period_start"],
            row["statement_period_end"],
        )
        if row["statement_period_start"] or row["statement_period_end"]:
            by_statement[key].append(row)

    for digest, group in by_hash.items():
        if len(group) > 1:
            group_id = stable_id("duphash", digest)
            for row in group:
                row["duplicate_hash_group"] = group_id

    for key, group in by_statement.items():
        if len(group) > 1:
            group_id = stable_id("dupstmt", *key)
            for row in group:
                row["duplicate_statement_group"] = group_id

    mark_overlapping_periods(rows)
    return rows, issues


def period_sort_value(value: Any) -> datetime:
    parsed = parse_date(value)
    if parsed:
        return datetime(parsed.year, parsed.month, parsed.day)
    return datetime.max


def mark_overlapping_periods(rows: list[dict[str, Any]]) -> None:
    """Mark source files whose declared statement/export periods overlap."""
    grouped: dict[tuple[str, str, str, str], list[dict[str, Any]]] = defaultdict(list)
    for row in rows:
        start = parse_date(row.get("statement_period_start"))
        end = parse_date(row.get("statement_period_end"))
        if not start or not end:
            continue
        key = (
            row.get("owner", ""),
            row.get("institution", ""),
            row.get("detected_account_id", ""),
            row.get("statement_type", ""),
        )
        grouped[key].append(row)

    for key, group in grouped.items():
        ordered = sorted(
            group,
            key=lambda row: (
                period_sort_value(row.get("statement_period_start")),
                period_sort_value(row.get("statement_period_end")),
                row.get("path", ""),
            ),
        )
        active: list[dict[str, Any]] = []
        group_index = 0
        for row in ordered:
            start = parse_date(row.get("statement_period_start"))
            end = parse_date(row.get("statement_period_end"))
            if not start or not end:
                continue
            active = [
                other
                for other in active
                if parse_date(other.get("statement_period_end")) and parse_date(other.get("statement_period_end")) >= start
            ]
            if active:
                overlapping = active + [row]
                existing = next((item.get("overlap_group") for item in overlapping if item.get("overlap_group")), "")
                if existing:
                    group_id = existing
                else:
                    group_index += 1
                    group_id = stable_id("overlap", *key, group_index)
                for item in overlapping:
                    item["overlap_group"] = group_id
            active.append(row)


def write_inventory_report(rows: list[dict[str, Any]], missing: list[dict[str, Any]], issues: list[dict[str, Any]]) -> None:
    counts: dict[str, int] = defaultdict(int)
    by_inst: dict[str, int] = defaultdict(int)
    duplicates = [row for row in rows if row.get("duplicate_hash_group") or row.get("duplicate_statement_group")]
    overlaps = [row for row in rows if row.get("overlap_group")]
    for row in rows:
        counts[row["file_type"]] += 1
        by_inst[row["institution"]] += 1

    metric_html = "<div class=\"metric-row\">"
    metric_html += f"<div class=\"metric\"><strong>{len(rows)}</strong><span>Files inventoried</span></div>"
    metric_html += f"<div class=\"metric\"><strong>{len(duplicates)}</strong><span>Duplicate candidates</span></div>"
    metric_html += f"<div class=\"metric\"><strong>{len(overlaps)}</strong><span>Overlap candidates</span></div>"
    metric_html += f"<div class=\"metric\"><strong>{len(missing)}</strong><span>Missing month candidates</span></div>"
    metric_html += f"<div class=\"metric\"><strong>{len(issues)}</strong><span>Inventory issues</span></div>"
    metric_html += "</div>"

    body = metric_html
    body += "<h2>Files by Type</h2>" + html_table([{"file_type": k, "count": v} for k, v in sorted(counts.items())], ["file_type", "count"])
    body += "<h2>Files by Institution</h2>" + html_table([{"institution": k, "count": v} for k, v in sorted(by_inst.items())], ["institution", "count"])
    body += "<h2>Duplicate Candidates</h2>" + html_table(
        [
            {
                "path": source_path(Path(row["path"])),
                "institution": row["institution"],
                "account": row["detected_account_id"],
                "period_start": row["statement_period_start"],
                "period_end": row["statement_period_end"],
                "hash_group": row["duplicate_hash_group"],
                "statement_group": row["duplicate_statement_group"],
                "overlap_group": row["overlap_group"],
            }
            for row in duplicates
        ],
        ["institution", "account", "period_start", "period_end", "hash_group", "statement_group", "overlap_group", "path"],
    )
    body += "<h2>Overlap Candidates</h2>" + html_table(
        [
            {
                "path": source_path(Path(row["path"])),
                "institution": row["institution"],
                "account": row["detected_account_id"],
                "type": row["statement_type"],
                "period_start": row["statement_period_start"],
                "period_end": row["statement_period_end"],
                "overlap_group": row["overlap_group"],
            }
            for row in overlaps
        ],
        ["institution", "account", "type", "period_start", "period_end", "overlap_group", "path"],
    )
    body += "<h2>Missing Month Candidates</h2>" + html_table(missing, MISSING_MONTH_COLUMNS)
    body += "<h2>Source Limitations</h2>" + html_table(SOURCE_LIMITATIONS, SOURCE_LIMITATION_COLUMNS)
    write_html_report(PROCESSED_DIR.parent.parent / "reports" / "inventory.html", "Inventory", body)


def run() -> dict[str, Any]:
    ensure_dirs()
    rows, issues = build_inventory(SOURCE_ROOT)
    missing = detect_missing_months(rows)
    write_csv(PROCESSED_DIR / "inventory_files.csv", rows, INVENTORY_COLUMNS)
    write_csv(PROCESSED_DIR / "inventory_missing_months.csv", missing, MISSING_MONTH_COLUMNS)
    write_csv(PROCESSED_DIR / "source_limitations.csv", SOURCE_LIMITATIONS, SOURCE_LIMITATION_COLUMNS)
    write_csv(PROCESSED_DIR / "inventory_issues.csv", issues, [
        "issue_id",
        "issue_type",
        "severity",
        "owner",
        "institution",
        "account_id",
        "date",
        "source_file",
        "source_page",
        "message",
        "suggested_action",
        "status",
    ])
    write_inventory_report(rows, missing, issues)
    return {"files": len(rows), "missing_months": len(missing), "issues": len(issues)}


if __name__ == "__main__":
    print(run())
