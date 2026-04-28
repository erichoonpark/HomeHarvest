#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "${ROOT_DIR}"

if [[ -x ".venv/bin/python" ]]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

if ! command -v "${PYTHON_BIN}" >/dev/null 2>&1; then
  echo "ERROR: Python runtime not found (${PYTHON_BIN})."
  exit 1
fi

if ! "${PYTHON_BIN}" -m pytest --version >/dev/null 2>&1; then
  cat <<'EOF'
ERROR: pytest is not installed for the selected Python environment.

Recommended setup:
  python3 -m venv .venv
  .venv/bin/python -m pip install -U pip
  .venv/bin/python -m pip install -e .
  .venv/bin/python -m pip install pytest

Then run:
  ./scripts/test.sh
EOF
  exit 2
fi

exec "${PYTHON_BIN}" -m pytest "$@"
