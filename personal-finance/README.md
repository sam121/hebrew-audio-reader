# Private Personal Finance Pipeline

This project builds local, repeatable financial reports for Samuel Taylor from statement exports stored on disk.

The pipeline is privacy-first:

- Raw source files are read in place and never modified.
- Raw PDFs, CSVs, XLSX files, processed data, database files, and HTML reports are ignored by Git.
- Every normalized row carries source traceability fields.
- Uncertainty is explicit through `confirmed`, `inferred`, `needs_review`, and `excluded` statuses.

## Source Folder

Default source root:

```text
/Users/samueltaylor/Library/Mobile Documents/com~apple~CloudDocs/Transactions
```

Override with:

```bash
export FINANCE_SOURCE_ROOT="/path/to/Transactions"
```

## Run

Use the bundled Codex Python runtime if available because it already includes `openpyxl`:

```bash
/Users/samueltaylor/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 scripts/run_pipeline.py
```

For full DuckDB and Parquet support, install the packages in `requirements.txt` in a local virtual environment. Without `duckdb`, the pipeline still writes CSV outputs and DuckDB schema SQL, but `data/finance.duckdb` is skipped with a visible run warning.

This project also supports project-local package installs:

```bash
/Users/samueltaylor/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 -m pip install --target .python duckdb
```

`scripts/run_pipeline.py` automatically adds `.python` to `sys.path` when that directory exists.

## FX Standard

The pipeline builds a local daily FX table from the public ECB euro foreign exchange reference-rate history:

```text
https://www.ecb.europa.eu/stats/eurofxref/eurofxref-hist.zip
```

ECB rates are quoted as currency units per EUR. The pipeline triangulates each available currency into SGD:

```text
SGD per currency = ECB SGD per EUR / ECB currency per EUR
```

Rows from ECB business days are marked `confirmed`. Weekends, holidays, and dates after the latest ECB publication are forward-filled from the latest prior ECB business day and marked `inferred`. Each converted transaction, balance, and holding includes `fx_date`, `fx_rate_to_sgd`, `fx_source`, and `fx_confidence`.

## Milestone 1 Coverage

Implemented:

- Source inventory with hashes, statement period detection, duplicate candidates, known gaps, and source limitations.
- DuckDB schema in `scripts/schema.sql`.
- Structured ingestors for Wise CSV, IBKR CSV, and Vanguard XLSX.
- Normalized `transactions`, `balances`, `holdings`, `issues`, and `source_limitations` CSV tables.
- First net-worth draft from structured balance snapshots.
- Local HTML reports for inventory, latest run, net worth, spending draft, and reconciliation status.

Not yet implemented:

- DBS, Barclays, and Endowus PDF transaction parsers.
- Statement-level PDF reconciliation.
- Full transfer reconciliation and manual review workflow.
- External or historical FX feeds. Only explicit local FX rates are used.

## Adding Another Owner

Add another owner to `config/accounts.yml`, then place that owner's files in a parallel source subfolder. For example:

```text
Transactions/
  Sam/
  Wife/
```

Extend the owner mapping in `scripts/common.py` or move it into a richer config loader when the second owner is added. The normalized schema already includes `owner` on transactions, balances, holdings, transfers, limitations, and issues.
