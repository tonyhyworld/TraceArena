#!/usr/bin/env bash
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT_DIR"

if [[ -x .venv/bin/python ]]; then
  PYTHON_BIN=".venv/bin/python"
else
  PYTHON_BIN="${PYTHON_BIN:-python3}"
fi

if [[ "$PYTHON_BIN" == */* && ! -x "$PYTHON_BIN" ]] || ! command -v "$PYTHON_BIN" >/dev/null 2>&1; then
  echo "TraceArena requires Python 3.10+. Run ./scripts/install.sh first or set PYTHON_BIN." >&2
  exit 1
fi

PYTHONPATH=backend "$PYTHON_BIN" backend/scripts/market_replay.py \
  --fixture examples/market_replay/fixture.json \
  --scenario backend/scenarios/capital_market \
  --output runs/market_replay_demo \
  "$@"

echo
echo "Replay artifacts written to runs/market_replay_demo"
echo "Read runs/market_replay_demo/summary.md and compare deterministic_replay_sha256 in run_manifest.json."
