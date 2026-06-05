from __future__ import annotations

import json
import sys
import time
from datetime import datetime
from pathlib import Path
from typing import Any, Callable

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
LOCAL_PYTHON = PROJECT_ROOT / ".python"
if LOCAL_PYTHON.exists() and str(LOCAL_PYTHON) not in sys.path:
    sys.path.insert(0, str(LOCAL_PYTHON))
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import DATA_DIR, SOURCE_ROOT, ensure_dirs, reset_run_warnings, write_json
from common import normalize_value

import build_net_worth
import categorize_transactions
import database
import fetch_fx
import ingest_ibkr
import ingest_barclays
import ingest_dbs
import ingest_endowus
import ingest_evelyn
import ingest_halifax
import ingest_stripe
import ingest_vanguard
import ingest_vanguard_inferred
import ingest_vanguard_pdf
import ingest_wise
import ingest_manual_legacy_pensions
import ingest_manual_property_assets
import ingest_manual_premium_bonds
import inventory
import normalize
import report
import report_source_of_funds
import reconcile_transfers
import validate


def run_step(name: str, fn: Callable[[], dict[str, Any]]) -> dict[str, Any]:
    started = time.time()
    result = fn()
    result["elapsed_seconds"] = round(time.time() - started, 3)
    return result


def run() -> dict[str, Any]:
    ensure_dirs()
    reset_run_warnings()
    summary: dict[str, Any] = {
        "started_at": datetime.now().isoformat(timespec="seconds"),
        "source_root": str(SOURCE_ROOT),
        "steps": {},
    }

    steps: list[tuple[str, Callable[[], dict[str, Any]]]] = [
        ("inventory", inventory.run),
        ("fetch_fx", fetch_fx.run),
        ("ingest_wise", ingest_wise.run),
        ("ingest_ibkr", ingest_ibkr.run),
        ("ingest_vanguard", ingest_vanguard.run),
        ("ingest_vanguard_inferred", ingest_vanguard_inferred.run),
        ("ingest_vanguard_pdf", ingest_vanguard_pdf.run),
        ("ingest_evelyn", ingest_evelyn.run),
        ("ingest_stripe", ingest_stripe.run),
        ("ingest_manual_legacy_pensions", ingest_manual_legacy_pensions.run),
        ("ingest_manual_property_assets", ingest_manual_property_assets.run),
        ("ingest_manual_premium_bonds", ingest_manual_premium_bonds.run),
        ("ingest_dbs", ingest_dbs.run),
        ("ingest_barclays", ingest_barclays.run),
        ("ingest_endowus", ingest_endowus.run),
        ("ingest_halifax", ingest_halifax.run),
        ("normalize", normalize.run),
        ("categorize_transactions", categorize_transactions.run),
        ("reconcile_transfers", reconcile_transfers.run),
        ("validate", validate.run),
        ("build_net_worth", build_net_worth.run),
        ("duckdb", database.refresh_duckdb),
    ]
    for name, fn in steps:
        summary["steps"][name] = run_step(name, fn)

    summary["finished_at"] = datetime.now().isoformat(timespec="seconds")
    write_json(DATA_DIR / "latest_run.json", summary)
    summary["steps"]["report"] = run_step("report", report.run)
    summary["steps"]["report_source_of_funds"] = run_step("report_source_of_funds", report_source_of_funds.run)
    write_json(DATA_DIR / "latest_run.json", summary)
    return summary


if __name__ == "__main__":
    result = run()
    print(json.dumps(result, indent=2, default=normalize_value))
