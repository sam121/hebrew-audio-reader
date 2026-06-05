from __future__ import annotations

import csv
import io
import zipfile
from datetime import date, timedelta
from decimal import Decimal
from decimal import InvalidOperation
from pathlib import Path
from urllib.error import URLError
from urllib.request import urlopen

from common import PROCESSED_DIR, ensure_dirs, month_end, read_csv_dicts, reset_fx_cache, write_csv


ECB_HISTORICAL_ZIP_URL = "https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip"
FX_COLUMNS = [
    "date",
    "currency",
    "rate_to_sgd",
    "fx_source",
    "fx_confidence",
    "ecb_eur_rate",
    "ecb_sgd_rate",
    "source_url",
    "notes",
]
CORE_CURRENCIES = ["SGD", "EUR", "USD", "GBP", "CAD", "CNY", "JPY", "AUD", "HKD", "PHP"]


def download_ecb_csv() -> str:
    with urlopen(ECB_HISTORICAL_ZIP_URL, timeout=60) as response:
        payload = response.read()
    with zipfile.ZipFile(io.BytesIO(payload)) as zf:
        csv_names = [name for name in zf.namelist() if name.lower().endswith(".csv")]
        if not csv_names:
            raise RuntimeError("ECB zip did not contain a CSV file.")
        return zf.read(csv_names[0]).decode("utf-8-sig")


def parse_ecb_rates(csv_text: str) -> tuple[list[date], dict[date, dict[str, Decimal]], list[str]]:
    reader = csv.DictReader(io.StringIO(csv_text))
    headers = reader.fieldnames or []
    ecb_currencies = sorted(column for column in headers if column and column not in {"Date", "TIME_PERIOD"} and len(column) == 3)
    currencies = sorted(set(ecb_currencies + CORE_CURRENCIES + ["EUR", "SGD"]))
    by_date: dict[date, dict[str, Decimal]] = {}
    for row in reader:
        raw_date = row.get("Date") or row.get("TIME_PERIOD")
        if not raw_date:
            continue
        current_date = date.fromisoformat(raw_date)
        rates: dict[str, Decimal] = {"EUR": Decimal("1")}
        for currency in currencies:
            if currency == "EUR":
                continue
            value = (row.get(currency) or "").strip()
            if value:
                try:
                    rates[currency] = Decimal(value)
                except InvalidOperation:
                    continue
        if "SGD" in rates:
            by_date[current_date] = rates
    dates = sorted(by_date)
    return dates, by_date, currencies


def fill_daily_rates(dates: list[date], by_date: dict[date, dict[str, Decimal]], currencies: list[str]) -> list[dict[str, object]]:
    if not dates:
        return []
    start = dates[0]
    end = max(max(dates), date.today())
    current_rates: dict[str, Decimal] | None = None
    rows: list[dict[str, object]] = []
    current = start
    while current <= end:
        if current in by_date:
            current_rates = by_date[current]
            confidence = "confirmed"
            rate_date_note = "ECB business-day reference rate."
        else:
            confidence = "inferred"
            rate_date_note = "Forward-filled from latest prior ECB business-day reference rate."
        if current_rates:
            sgd_per_eur = current_rates.get("SGD")
            if sgd_per_eur:
                for currency in currencies:
                    eur_rate = current_rates.get(currency)
                    if currency == "SGD":
                        rate_to_sgd = Decimal("1")
                    elif currency == "EUR":
                        rate_to_sgd = sgd_per_eur
                    elif eur_rate:
                        # ECB quotes each currency as currency units per EUR.
                        # SGD per currency = SGD per EUR / currency units per EUR.
                        rate_to_sgd = sgd_per_eur / eur_rate
                    else:
                        continue
                    rows.append(
                        {
                            "date": current,
                            "currency": currency,
                            "rate_to_sgd": rate_to_sgd,
                            "fx_source": "ECB euro foreign exchange reference rates",
                            "fx_confidence": confidence,
                            "ecb_eur_rate": eur_rate,
                            "ecb_sgd_rate": sgd_per_eur,
                            "source_url": ECB_HISTORICAL_ZIP_URL,
                            "notes": rate_date_note,
                        }
                    )
        current += timedelta(days=1)
    return rows


def run() -> dict[str, object]:
    ensure_dirs()
    try:
        csv_text = download_ecb_csv()
    except (URLError, TimeoutError, OSError) as exc:
        cached = read_csv_dicts(PROCESSED_DIR / "fx_rates.csv")
        if cached:
            reset_fx_cache()
            return {
                "source": "cached ECB table",
                "source_url": ECB_HISTORICAL_ZIP_URL,
                "warning": f"Could not refresh FX online; using existing local table. {exc!r}",
                "rows": len(cached),
                "date_min": min(row["date"] for row in cached if row.get("date")),
                "date_max_table": max(row["date"] for row in cached if row.get("date")),
            }
        raise
    dates, by_date, currencies = parse_ecb_rates(csv_text)
    rows = fill_daily_rates(dates, by_date, currencies)
    write_csv(PROCESSED_DIR / "fx_rates.csv", rows, FX_COLUMNS)
    reset_fx_cache()
    return {
        "source": "ECB",
        "source_url": ECB_HISTORICAL_ZIP_URL,
        "currencies": len(currencies),
        "core_currencies": ",".join(CORE_CURRENCIES),
        "rows": len(rows),
        "date_min": min(dates) if dates else "",
        "date_max_ecb": max(dates) if dates else "",
        "date_max_table": max((row["date"] for row in rows), default=""),
    }


if __name__ == "__main__":
    print(run())
