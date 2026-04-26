#!/usr/bin/env bash
set -euo pipefail

INPUT_PATH="${1:-examples/zips/coc_scorecard.xlsx}"
OUTPUT_DIR="${2:-publish}"
TOP_N="${TOP_N:-5}"
HOMES_LIMIT="${HOMES_LIMIT:-100}"

mkdir -p "$OUTPUT_DIR"

python - <<'PY'
import importlib.util
import sys
if importlib.util.find_spec("openpyxl") is None:
    sys.exit("Missing dependency: openpyxl. Install with: pip install openpyxl")
PY

python examples/coc_dashboard.py \
  --input "$INPUT_PATH" \
  --output "$OUTPUT_DIR/index.html" \
  --top-n "$TOP_N" \
  --homes-limit "$HOMES_LIMIT"

cat > "$OUTPUT_DIR/_headers" <<'HEADERS'
/*
  X-Content-Type-Options: nosniff
  X-Frame-Options: DENY
  Referrer-Policy: strict-origin-when-cross-origin
  Permissions-Policy: geolocation=(), microphone=(), camera=()
  Strict-Transport-Security: max-age=31536000; includeSubDomains; preload
  Content-Security-Policy: default-src 'self'; script-src 'self' 'unsafe-inline'; style-src 'self' 'unsafe-inline'; img-src 'self' data: https:; font-src 'self' data:; connect-src 'self'; frame-ancestors 'none'; base-uri 'none'; form-action 'self'
HEADERS

cat > "$OUTPUT_DIR/robots.txt" <<'ROBOTS'
User-agent: *
Disallow: /
ROBOTS

echo "Built secure publish bundle in $OUTPUT_DIR"
