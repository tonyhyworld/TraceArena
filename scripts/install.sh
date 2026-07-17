#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

PYTHON_BIN="${PYTHON_BIN:-python3}"
if ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "TraceArena requires Python 3.10+. Set PYTHON_BIN to a compatible interpreter." >&2
  exit 1
fi

"$PYTHON_BIN" - <<'PY'
import sys
if sys.version_info < (3, 10):
    raise SystemExit("TraceArena requires Python 3.10 or newer.")
PY

if [[ ! -d .venv ]]; then
  if ! "$PYTHON_BIN" -m venv .venv; then
    echo "TraceArena could not create a Python virtual environment. Install a Python 3.10+ distribution that includes venv/ensurepip, then retry." >&2
    exit 1
  fi
fi

source .venv/bin/activate
python -m pip install -e ".[dev]"

if ! command -v npm >/dev/null 2>&1; then
  echo "Node.js/npm is required to install the Vue frontend." >&2
  exit 1
fi

(cd frontend && npm ci)

if [[ ! -f frontend/.env.local && -f frontend/.env.example ]]; then
  cp frontend/.env.example frontend/.env.local
fi

echo
echo "TraceArena is installed."
echo "Backend venv: $ROOT_DIR/.venv"
echo "Next: source .venv/bin/activate && (cd frontend && npm run dev)"
