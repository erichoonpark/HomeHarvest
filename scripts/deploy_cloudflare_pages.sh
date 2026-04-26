#!/usr/bin/env bash
set -euo pipefail

: "${CLOUDFLARE_API_TOKEN:?Set CLOUDFLARE_API_TOKEN first}"
: "${CLOUDFLARE_ACCOUNT_ID:?Set CLOUDFLARE_ACCOUNT_ID first}"
: "${CLOUDFLARE_PAGES_PROJECT:?Set CLOUDFLARE_PAGES_PROJECT first}"

PUBLISH_DIR="${1:-publish}"

if ! command -v npx >/dev/null 2>&1; then
  echo "npx is required (install Node.js >= 18)." >&2
  exit 1
fi

if [ ! -f "$PUBLISH_DIR/index.html" ]; then
  echo "Missing $PUBLISH_DIR/index.html. Run scripts/build_dashboard_publish.sh first." >&2
  exit 1
fi

npx wrangler pages deploy "$PUBLISH_DIR" \
  --project-name "$CLOUDFLARE_PAGES_PROJECT" \
  --branch "main"

echo "Deployment finished."
echo "IMPORTANT: enforce partner-only access in Cloudflare Zero Trust Access policy."
