from __future__ import annotations

import csv
import hashlib
import html
import json
import os
import re
from calendar import monthrange
from datetime import date, datetime
from decimal import Decimal, InvalidOperation
from pathlib import Path
from typing import Any, Iterable


PROJECT_ROOT = Path(__file__).resolve().parents[1]
CONFIG_DIR = PROJECT_ROOT / "config"
DATA_DIR = PROJECT_ROOT / "data"
PROCESSED_DIR = DATA_DIR / "processed"
EXPORTS_DIR = DATA_DIR / "exports"
REPORTS_DIR = PROJECT_ROOT / "reports"
SOURCE_ROOT = Path(
    os.environ.get(
        "FINANCE_SOURCE_ROOT",
        "/Users/samueltaylor/Library/Mobile Documents/com~apple~CloudDocs/Transactions",
    )
)

DEFAULT_OWNER = "samuel"
REPORTING_CURRENCY = "SGD"
REPORT_START_DATE = date(2020, 1, 1)
FX_RATE_CACHE: dict[str, list[tuple[date, Decimal, str, str]]] | None = None


def previous_month_end(today: date | None = None) -> date:
    today = today or date.today()
    if today.month == 1:
        return date(today.year - 1, 12, 31)
    year = today.year
    month = today.month - 1
    return date(year, month, monthrange(year, month)[1])


def report_end_date() -> date:
    override = os.environ.get("FINANCE_REPORT_END_DATE")
    if override:
        return date.fromisoformat(override)
    return previous_month_end()


REPORT_END_DATE = report_end_date()

TRANSACTION_COLUMNS = [
    "transaction_id",
    "owner",
    "institution",
    "account_id",
    "account_name",
    "account_type",
    "date",
    "posted_date",
    "description_raw",
    "description_clean",
    "merchant",
    "amount",
    "currency",
    "amount_sgd",
    "fx_date",
    "fx_rate_to_sgd",
    "fx_source",
    "fx_confidence",
    "direction",
    "category",
    "subcategory",
    "is_transfer_candidate",
    "matched_transfer_id",
    "confidence_status",
    "source_file",
    "source_page",
    "source_row",
    "parser_name",
    "parse_confidence",
]

BALANCE_COLUMNS = [
    "balance_id",
    "owner",
    "institution",
    "account_id",
    "account_name",
    "account_type",
    "date",
    "balance",
    "currency",
    "balance_sgd",
    "fx_date",
    "fx_rate_to_sgd",
    "fx_source",
    "fx_confidence",
    "balance_type",
    "confidence_status",
    "source_file",
    "source_page",
    "source_row",
    "parser_name",
    "parse_confidence",
]

HOLDING_COLUMNS = [
    "holding_id",
    "owner",
    "institution",
    "account_id",
    "date",
    "symbol",
    "name",
    "asset_class",
    "quantity",
    "price",
    "market_value",
    "currency",
    "market_value_sgd",
    "fx_date",
    "fx_rate_to_sgd",
    "fx_source",
    "fx_confidence",
    "confidence_status",
    "source_file",
    "source_row",
    "parser_name",
]

TRANSFER_COLUMNS = [
    "transfer_id",
    "owner",
    "from_transaction_id",
    "to_transaction_id",
    "from_account",
    "to_account",
    "from_date",
    "to_date",
    "from_amount",
    "from_currency",
    "to_amount",
    "to_currency",
    "implied_fx_rate",
    "match_confidence",
    "match_reason",
    "status",
]

ISSUE_COLUMNS = [
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
]

SOURCE_LIMITATION_COLUMNS = [
    "owner",
    "institution",
    "account_id",
    "known_account_existed_before_available_records",
    "earliest_available_record_date",
    "likely_reason",
    "notes",
]

CONTROL_TOTAL_COLUMNS = [
    "control_id",
    "parser_name",
    "source_file",
    "owner",
    "institution",
    "account_id",
    "file_count",
    "row_count",
    "date_min",
    "date_max",
    "sum_credits",
    "sum_debits",
    "opening_balance",
    "closing_balance",
    "warning_count",
    "failed_row_count",
]

INVENTORY_COLUMNS = [
    "inventory_id",
    "path",
    "owner",
    "institution",
    "file_type",
    "parsed_date",
    "modified_at",
    "size_bytes",
    "content_hash",
    "detected_account_id",
    "statement_type",
    "statement_period_start",
    "statement_period_end",
    "duplicate_hash_group",
    "duplicate_statement_group",
    "overlap_group",
    "missing_month_candidate",
    "notes",
]


def ensure_dirs() -> None:
    for path in [DATA_DIR, PROCESSED_DIR, EXPORTS_DIR, REPORTS_DIR]:
        path.mkdir(parents=True, exist_ok=True)


def stable_id(prefix: str, *parts: Any) -> str:
    raw = "|".join("" if part is None else str(part) for part in parts)
    digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:20]
    return f"{prefix}_{digest}"


def sha256_file(path: Path, chunk_size: int = 1024 * 1024) -> str:
    hasher = hashlib.sha256()
    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(chunk_size), b""):
            hasher.update(chunk)
    return hasher.hexdigest()


def source_path(path: Path) -> str:
    try:
        return str(path.resolve().relative_to(SOURCE_ROOT.resolve()))
    except ValueError:
        return str(path.resolve())


def parser_source_file(path: Path) -> str:
    return str(path.resolve())


def clean_description(value: Any) -> str:
    text = "" if value is None else str(value)
    return re.sub(r"\s+", " ", text).strip()


def parse_decimal(value: Any) -> Decimal | None:
    if value is None:
        return None
    text = str(value).strip()
    if not text or text in {"-", "None"}:
        return None
    negative = False
    if text.endswith(" CR"):
        text = text[:-3].strip()
        negative = True
    if text.startswith("-"):
        negative = True
    if text.startswith("(") and text.endswith(")"):
        negative = True
        text = text[1:-1]
    text = text.replace(",", "")
    text = text.replace("S$", "").replace("$", "").replace("£", "")
    text = re.sub(r"^[A-Z]{3}\s+", "", text)
    text = text.lstrip("+").lstrip("-").strip()
    try:
        value = Decimal(text)
        return -value if negative else value
    except InvalidOperation:
        return None


def decimal_to_str(value: Decimal | None) -> str:
    if value is None:
        return ""
    return format(value, "f")


def parse_date(value: Any) -> date | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    text = str(value).strip()
    if not text or text in {"-", "None"}:
        return None
    text = text.split(" ")[0]
    formats = [
        "%Y-%m-%d",
        "%d-%m-%Y",
        "%d/%m/%Y",
        "%m/%d/%y",
        "%m/%d/%Y",
        "%Y%m%d",
        "%d-%b-%y",
        "%d-%b-%Y",
        "%d-%B-%Y",
        "%d %b %Y",
        "%d %B %Y",
    ]
    for fmt in formats:
        try:
            return datetime.strptime(text, fmt).date()
        except ValueError:
            continue
    return None


def parse_month_token(token: str) -> tuple[date, date] | tuple[None, None]:
    text = token.strip()
    for fmt in ("%b%Y", "%B%Y"):
        try:
            first = datetime.strptime(text, fmt).date().replace(day=1)
            return first, month_end(first.year, first.month)
        except ValueError:
            continue
    return None, None


def month_end(year: int, month: int) -> date:
    return date(year, month, monthrange(year, month)[1])


def parse_yyyymm(value: str) -> date | None:
    text = str(value).strip()
    if not re.fullmatch(r"\d{6}", text):
        return None
    year = int(text[:4])
    month = int(text[4:])
    if not 1 <= month <= 12:
        return None
    return month_end(year, month)


def add_months(value: date, months: int) -> date:
    month_index = value.year * 12 + value.month - 1 + months
    year = month_index // 12
    month = month_index % 12 + 1
    return date(year, month, min(value.day, monthrange(year, month)[1]))


def month_iter(start: date, end: date) -> Iterable[date]:
    cur = date(start.year, start.month, 1)
    last = date(end.year, end.month, 1)
    while cur <= last:
        yield cur
        cur = add_months(cur, 1)


def direction_for(amount: Decimal | None) -> str:
    if amount is None:
        return ""
    if amount > 0:
        return "inflow"
    if amount < 0:
        return "outflow"
    return "zero"


def rate_to_sgd(currency: str | None, value_date: date | None = None) -> Decimal | None:
    if not currency:
        return None
    currency = currency.upper()
    if currency == REPORTING_CURRENCY:
        return Decimal("1")
    if value_date is None:
        return None
    table = load_fx_rates()
    rates = table.get(currency, [])
    if not rates:
        return None
    last_rate = None
    for rate_date, rate, _source, _confidence in rates:
        if rate_date > value_date:
            break
        last_rate = rate
    return last_rate


def fx_metadata(currency: str | None, value_date: date | None = None) -> dict[str, Any]:
    if not currency:
        return {"fx_date": None, "fx_rate": None, "fx_source": "", "fx_confidence": ""}
    currency = currency.upper()
    if currency == REPORTING_CURRENCY:
        return {
            "fx_date": value_date,
            "fx_rate": Decimal("1"),
            "fx_source": "identity",
            "fx_confidence": "confirmed",
        }
    if value_date is None:
        return {"fx_date": None, "fx_rate": None, "fx_source": "", "fx_confidence": ""}
    rates = load_fx_rates().get(currency, [])
    last = None
    for item in rates:
        if item[0] > value_date:
            break
        last = item
    if last is None:
        return {"fx_date": None, "fx_rate": None, "fx_source": "", "fx_confidence": ""}
    rate_date, rate, source, confidence = last
    confidence_out = confidence if rate_date == value_date else "inferred"
    return {
        "fx_date": rate_date,
        "fx_rate": rate,
        "fx_source": source,
        "fx_confidence": confidence_out,
    }


def load_fx_rates() -> dict[str, list[tuple[date, Decimal, str, str]]]:
    global FX_RATE_CACHE
    if FX_RATE_CACHE is not None:
        return FX_RATE_CACHE
    path = PROCESSED_DIR / "fx_rates.csv"
    table: dict[str, list[tuple[date, Decimal, str, str]]] = {}
    if not path.exists():
        FX_RATE_CACHE = table
        return table
    with path.open(newline="", encoding="utf-8") as f:
        reader = csv.DictReader(f)
        for row in reader:
            currency = (row.get("currency") or "").upper()
            rate_date = parse_date(row.get("date"))
            rate = parse_decimal(row.get("rate_to_sgd"))
            if not currency or rate_date is None or rate is None:
                continue
            table.setdefault(currency, []).append(
                (
                    rate_date,
                    rate,
                    row.get("fx_source", ""),
                    row.get("fx_confidence", ""),
                )
            )
    for currency in table:
        table[currency].sort(key=lambda item: item[0])
    FX_RATE_CACHE = table
    return table


def reset_fx_cache() -> None:
    global FX_RATE_CACHE
    FX_RATE_CACHE = None


def fx_fields(currency: str | None, value_date: date | None = None) -> dict[str, Any]:
    meta = fx_metadata(currency, value_date)
    return {
        "fx_date": meta["fx_date"],
        "fx_rate_to_sgd": meta["fx_rate"],
        "fx_source": meta["fx_source"],
        "fx_confidence": meta["fx_confidence"],
    }


def converted_with_fx(amount: Decimal | None, currency: str | None, value_date: date | None = None) -> tuple[Decimal | None, dict[str, Any]]:
    meta = fx_metadata(currency, value_date)
    rate = meta["fx_rate"]
    if amount is None or rate is None:
        return None, {
            "fx_date": meta["fx_date"],
            "fx_rate_to_sgd": meta["fx_rate"],
            "fx_source": meta["fx_source"],
            "fx_confidence": meta["fx_confidence"],
        }
    return amount * rate, {
        "fx_date": meta["fx_date"],
        "fx_rate_to_sgd": meta["fx_rate"],
        "fx_source": meta["fx_source"],
        "fx_confidence": meta["fx_confidence"],
    }


def convert_to_sgd(amount: Decimal | None, currency: str | None, value_date: date | None = None) -> Decimal | None:
    converted, _fields = converted_with_fx(amount, currency, value_date)
    return converted


def make_issue(
    issue_type: str,
    severity: str,
    owner: str,
    institution: str,
    account_id: str,
    message: str,
    suggested_action: str,
    *,
    value_date: date | None = None,
    source_file: str = "",
    source_page: str = "",
    status: str = "open",
    key: str | None = None,
) -> dict[str, Any]:
    issue_key = key or f"{issue_type}|{owner}|{institution}|{account_id}|{value_date}|{source_file}|{message}"
    return {
        "issue_id": stable_id("issue", issue_key),
        "issue_type": issue_type,
        "severity": severity,
        "owner": owner,
        "institution": institution,
        "account_id": account_id,
        "date": value_date,
        "source_file": source_file,
        "source_page": source_page,
        "message": message,
        "suggested_action": suggested_action,
        "status": status,
    }


def normalize_value(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, Decimal):
        return decimal_to_str(value)
    if isinstance(value, (datetime, date)):
        return value.isoformat()
    if isinstance(value, bool):
        return "true" if value else "false"
    return str(value)


def write_csv(path: Path, rows: Iterable[dict[str, Any]], columns: list[str]) -> int:
    ensure_dirs()
    materialized = list(rows)
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as f:
        writer = csv.DictWriter(f, fieldnames=columns, extrasaction="ignore")
        writer.writeheader()
        for row in materialized:
            writer.writerow({column: normalize_value(row.get(column)) for column in columns})
    return len(materialized)


def read_csv_dicts(path: Path) -> list[dict[str, str]]:
    if not path.exists():
        return []
    with path.open(newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def write_json(path: Path, data: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        json.dump(data, f, indent=2, default=normalize_value)


def read_json(path: Path, default: Any) -> Any:
    if not path.exists():
        return default
    with path.open(encoding="utf-8") as f:
        return json.load(f)


def append_run_warning(message: str) -> None:
    path = DATA_DIR / "run_warnings.json"
    warnings = read_json(path, [])
    if message not in warnings:
        warnings.append(message)
    write_json(path, warnings)


def reset_run_warnings() -> None:
    write_json(DATA_DIR / "run_warnings.json", [])


def html_escape(value: Any) -> str:
    return html.escape("" if value is None else str(value))


def html_table(rows: list[dict[str, Any]], columns: list[str], limit: int = 200) -> str:
    if not rows:
        return "<p>No rows.</p>"
    head = "".join(f"<th>{html_escape(col)}</th>" for col in columns)
    body_rows = []
    for row in rows[:limit]:
        cells = "".join(f"<td>{html_escape(row.get(col, ''))}</td>" for col in columns)
        body_rows.append(f"<tr>{cells}</tr>")
    more = ""
    if len(rows) > limit:
        more = f"<p class=\"muted\">Showing {limit} of {len(rows)} rows.</p>"
    return f"{more}<table><thead><tr>{head}</tr></thead><tbody>{''.join(body_rows)}</tbody></table>"


def page(title: str, body: str) -> str:
    return f"""<!doctype html>
<html lang="en">
<head>
  <meta charset="utf-8">
  <meta name="viewport" content="width=device-width, initial-scale=1">
  <title>{html_escape(title)}</title>
  <style>
    :root {{
      color-scheme: light;
      --ink: #1d2733;
      --muted: #5f6b7a;
      --line: #d9e0e7;
      --paper: #fbfcfd;
      --accent: #116466;
      --warn: #9a5b00;
      --bad: #9c2f2f;
    }}
    body {{
      margin: 0;
      font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif;
      color: var(--ink);
      background: var(--paper);
      line-height: 1.45;
    }}
    header {{
      padding: 28px 32px 18px;
      border-bottom: 1px solid var(--line);
      background: #ffffff;
    }}
    main {{
      max-width: 1180px;
      padding: 24px 32px 48px;
    }}
    h1 {{
      margin: 0 0 6px;
      font-size: 28px;
      letter-spacing: 0;
    }}
    h2 {{
      margin: 28px 0 10px;
      font-size: 18px;
      letter-spacing: 0;
    }}
    p, li {{
      color: var(--muted);
    }}
    table {{
      border-collapse: collapse;
      width: 100%;
      background: #ffffff;
      border: 1px solid var(--line);
      font-size: 13px;
    }}
    th, td {{
      border-bottom: 1px solid var(--line);
      padding: 8px 9px;
      text-align: left;
      vertical-align: top;
    }}
    th {{
      background: #eef4f5;
      color: var(--ink);
      position: sticky;
      top: 0;
    }}
    .metric-row {{
      display: grid;
      grid-template-columns: repeat(auto-fit, minmax(170px, 1fr));
      gap: 12px;
      margin: 18px 0;
    }}
    .metric {{
      border-top: 3px solid var(--accent);
      background: #ffffff;
      padding: 12px 14px;
      border-radius: 6px;
      box-shadow: 0 1px 2px rgba(29, 39, 51, .06);
    }}
    .metric strong {{
      display: block;
      font-size: 24px;
      margin-bottom: 4px;
    }}
    .muted {{
      color: var(--muted);
    }}
    .warning {{
      border-left: 4px solid var(--warn);
      padding: 10px 12px;
      background: #fff7e8;
      color: #5d3a00;
    }}
    .bad {{
      border-left-color: var(--bad);
      background: #fff0f0;
      color: #6e1f1f;
    }}
  </style>
</head>
<body>
<header>
  <h1>{html_escape(title)}</h1>
  <p>Generated locally from traceable source files.</p>
</header>
<main>
{body}
</main>
</body>
</html>
"""


def write_html_report(path: Path, title: str, body: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(page(title, body), encoding="utf-8")


def owner_from_parts(parts: tuple[str, ...]) -> str:
    if parts and parts[0].lower() == "sam":
        return DEFAULT_OWNER
    return parts[0].lower() if parts else DEFAULT_OWNER


def institution_from_folder(folder: str) -> str:
    lower = folder.lower()
    if lower.startswith("sam_"):
        return lower.replace("sam_", "", 1)
    if lower.startswith("amy_"):
        return lower.replace("amy_", "", 1)
    return lower


def owner_for_path(path: Path) -> str:
    try:
        parts = path.resolve().relative_to(SOURCE_ROOT.resolve()).parts
    except ValueError:
        return DEFAULT_OWNER
    return owner_from_parts(parts)


def source_folders_for(institution: str) -> list[Path]:
    folders: list[Path] = []
    if not SOURCE_ROOT.exists():
        return folders
    for owner_dir in sorted(path for path in SOURCE_ROOT.iterdir() if path.is_dir()):
        for child in sorted(path for path in owner_dir.iterdir() if path.is_dir()):
            if institution_from_folder(child.name) == institution:
                folders.append(child)
    return folders
