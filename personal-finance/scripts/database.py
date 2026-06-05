from __future__ import annotations

from pathlib import Path
import sys
from typing import Any

from common import DATA_DIR, PROCESSED_DIR, PROJECT_ROOT, append_run_warning


TABLE_SOURCES = {
    "transactions": PROCESSED_DIR / "transactions.csv",
    "balances": PROCESSED_DIR / "balances.csv",
    "holdings": PROCESSED_DIR / "holdings.csv",
    "transfers": PROCESSED_DIR / "transfers.csv",
    "source_limitations": PROCESSED_DIR / "source_limitations.csv",
    "issues": PROCESSED_DIR / "issues.csv",
    "inventory_files": PROCESSED_DIR / "inventory_files.csv",
    "run_control_totals": PROCESSED_DIR / "run_control_totals.csv",
    "fx_rates": PROCESSED_DIR / "fx_rates.csv",
}


def csv_has_data_rows(path: Path) -> bool:
    if not path.exists():
        return False
    with path.open(encoding="utf-8") as f:
        next(f, None)
        return next(f, None) is not None


def refresh_duckdb() -> dict[str, Any]:
    local_python = PROJECT_ROOT / ".python"
    if local_python.exists() and str(local_python) not in sys.path:
        sys.path.insert(0, str(local_python))
    try:
        import duckdb
    except ImportError:
        append_run_warning(
            "DuckDB Python package is not installed. CSV outputs were generated, but data/finance.duckdb was not refreshed."
        )
        return {"duckdb": "skipped_missing_package"}

    db_path = DATA_DIR / "finance.duckdb"
    schema_path = PROJECT_ROOT / "scripts" / "schema.sql"
    loaded: dict[str, int] = {}
    with duckdb.connect(str(db_path)) as con:
        for table in TABLE_SOURCES:
            con.execute(f"DROP TABLE IF EXISTS {table}")
        con.execute(schema_path.read_text(encoding="utf-8"))
        for table, csv_path in TABLE_SOURCES.items():
            if not csv_has_data_rows(csv_path):
                loaded[table] = 0
                continue
            escaped = str(csv_path).replace("'", "''")
            try:
                con.execute(
                    f"INSERT INTO {table} BY NAME "
                    f"SELECT * FROM read_csv_auto('{escaped}', header=true, nullstr='', ignore_errors=false)"
                )
                loaded[table] = con.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            except Exception as exc:
                append_run_warning(f"DuckDB load failed for {table}: {exc}")
                loaded[table] = -1
    return {"duckdb": str(db_path), "loaded": loaded}


if __name__ == "__main__":
    print(refresh_duckdb())
