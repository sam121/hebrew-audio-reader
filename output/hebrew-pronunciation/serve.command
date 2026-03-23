#!/bin/zsh
set -euo pipefail

ROOT="/Users/samueltaylor/Documents/New project/output/hebrew-pronunciation"
SITE_ROOT="${ROOT}/site"
PORT="${1:-8765}"
URL="http://127.0.0.1:${PORT}/"
PYTHON_BIN="${ROOT}/.venv/bin/python3"

if [[ ! -x "${PYTHON_BIN}" ]]; then
  PYTHON_BIN="python3"
fi

cd "$ROOT"

"${PYTHON_BIN}" "${ROOT}/scripts/build_site.py" --allow-missing-audio

cd "$SITE_ROOT"

echo "Serving Hebrew Pronunciation Checker at ${URL}"
echo "Press Control-C in this Terminal window when you want to stop the server."

"${PYTHON_BIN}" -m http.server "$PORT" >/tmp/hebrew-pronunciation-server.log 2>&1 &
SERVER_PID=$!

cleanup() {
  kill "$SERVER_PID" >/dev/null 2>&1 || true
}

trap cleanup EXIT INT TERM

sleep 1
open "$URL"
wait "$SERVER_PID"
