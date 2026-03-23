#!/bin/zsh
set -euo pipefail
setopt null_glob

PDF="/Users/samueltaylor/Downloads/Learn Hebrew Today (Adult Hebrew book) (1).pdf"
OUT_DIR="/Users/samueltaylor/Documents/New project/output/hebrew-pronunciation/pages"
FIRST="${1:-1}"
LAST="${2:-3}"
TMP_PREFIX="${OUT_DIR}/page"

mkdir -p "$OUT_DIR"
rm -f -- "${OUT_DIR}"/page-*.png

if ! command -v pdftoppm >/dev/null 2>&1; then
  echo "pdftoppm is not installed yet. Install poppler first, then rerun this script."
  exit 1
fi

pdftoppm -png -scale-to 2200 -f "$FIRST" -l "$LAST" "$PDF" "$TMP_PREFIX"

for file in "${OUT_DIR}"/page-*.png; do
  base="${file:t}"
  page_number="${base#page-}"
  page_number="${page_number%.png}"
  padded=$(printf "%03d" "$page_number")
  mv "$file" "${OUT_DIR}/page-${padded}.png"
done

echo "Rendered pages ${FIRST} through ${LAST} into ${OUT_DIR}."
echo "Run scripts/build_site.py afterwards to refresh the deployable site/pages copy."
