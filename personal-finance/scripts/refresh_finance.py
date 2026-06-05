from __future__ import annotations

import importlib
import json
import subprocess
import sys
from pathlib import Path
from typing import Any

SCRIPT_DIR = Path(__file__).resolve().parent
PROJECT_ROOT = SCRIPT_DIR.parent
if str(SCRIPT_DIR) not in sys.path:
    sys.path.insert(0, str(SCRIPT_DIR))

from common import REPORTS_DIR, normalize_value

import monthly_refresh_summary
import run_pipeline


OPTIONAL_REPORT_MODULES = [
    "report_barclays",
    "report_vanguard",
    "report_net_worth_stacked",
    "report_income_spending_quarterly",
    "report_net_worth_sankey",
    "report_spending_by_category",
    "report_salary",
    "report_platform_fee_review",
    "report_platform_fees",
    "report_evelyn_fee_deep_dive",
    "report_source_of_funds",
    "scan_embedded_fund_fees",
    "check_public_fee_changes",
    "refresh_control_checks",
]


def run_optional_reports() -> dict[str, Any]:
    results: dict[str, Any] = {}
    for module_name in OPTIONAL_REPORT_MODULES:
        try:
            module = importlib.import_module(module_name)
            fn = getattr(module, "run", None) or getattr(module, "main", None)
            if not fn:
                results[module_name] = {"status": "skipped", "reason": "no run/main function"}
                continue
            result = fn()
            results[module_name] = {"status": "ok", "result": result}
        except Exception as exc:  # Keep the refresh useful even if one auxiliary report fails.
            results[module_name] = {"status": "failed", "error": repr(exc)}
    return results


def open_report(path: Path) -> None:
    try:
        subprocess.run(["open", str(path)], check=False)
    except Exception:
        pass


def run(open_browser: bool = True) -> dict[str, Any]:
    pipeline = run_pipeline.run()
    optional = run_optional_reports()
    summary = monthly_refresh_summary.run()
    report_path = REPORTS_DIR / "refresh_summary.html"
    if open_browser:
        open_report(report_path)
    return {
        "pipeline": pipeline,
        "optional_reports": optional,
        "summary": summary,
        "open_report": str(report_path),
    }


if __name__ == "__main__":
    result = run(open_browser="--no-open" not in sys.argv)
    print(json.dumps(result, indent=2, default=normalize_value))
