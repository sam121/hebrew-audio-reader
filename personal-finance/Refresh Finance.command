#!/bin/zsh
set -e

PROJECT="/Users/samueltaylor/Documents/New project/personal-finance"
PYTHON="/Users/samueltaylor/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3"
LOG="$PROJECT/data/refresh_finance.log"

cd "$PROJECT"
mkdir -p "$PROJECT/data"

echo "Finance refresh started: $(date)" | tee "$LOG"
"$PYTHON" scripts/refresh_finance.py 2>&1 | tee -a "$LOG"
echo "Finance refresh finished: $(date)" | tee -a "$LOG"

echo
echo "Report opened: $PROJECT/reports/refresh_summary.html"
echo "Log written to: $LOG"
echo
echo "You can close this window."
