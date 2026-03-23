#!/bin/zsh
set -euo pipefail
setopt null_glob

SOURCE_PDF="/Users/samueltaylor/Downloads/annas-arch-c9a691bed7c4 (1).pdf"
OUT_DIR="/Users/samueltaylor/Documents/New project/output/hebrew-pronunciation/pages"
SOURCE_FIRST="${1:-4}"
SOURCE_LAST="${2:-6}"
OUTPUT_START="${3:-1}"
TMP_PREFIX="${OUT_DIR}/source-page"

mkdir -p "$OUT_DIR"
rm -f -- "${OUT_DIR}"/page-*.png

if ! command -v pdftoppm >/dev/null 2>&1; then
  echo "pdftoppm is not installed yet. Install poppler first, then rerun this script."
  exit 1
fi

if [[ ! -f "$SOURCE_PDF" ]]; then
  echo "Source PDF not found: $SOURCE_PDF"
  exit 1
fi

pdftoppm -png -scale-to 2200 -f "$SOURCE_FIRST" -l "$SOURCE_LAST" "$SOURCE_PDF" "$TMP_PREFIX"

output_number="$OUTPUT_START"
for file in "${OUT_DIR}"/source-page-*.png; do
  padded=$(printf "%03d" "$output_number")
  mv "$file" "${OUT_DIR}/page-${padded}.png"
  output_number=$((output_number + 1))
done

echo "Rendered source PDF pages ${SOURCE_FIRST} through ${SOURCE_LAST} into ${OUT_DIR} as app pages ${OUTPUT_START}+."
echo "Run scripts/build_site.py afterwards to refresh the deployable site/pages copy."
