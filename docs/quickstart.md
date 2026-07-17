# TraceArena Quickstart

This guide takes an external developer from a fresh checkout to a verified,
offline run. It does not require an API key, an LLM, a brokerage account, or
network access after dependencies are available.

## 1. Install the runtime

On macOS/Linux, the repository installer provisions the Python environment and
the locked Vue frontend dependencies in one command:

```bash
./scripts/install.sh
```

If `python3` points to an older or incomplete installation, select a compatible
interpreter explicitly: `PYTHON_BIN=/path/to/python3.12 ./scripts/install.sh`.
The interpreter must include the `venv`/`ensurepip` components.

Windows PowerShell:

```powershell
.\scripts\install.ps1
```

If you prefer to control each environment manually, use the following steps.

Python 3.10 or newer is required.

```bash
python3 -m venv .venv
source .venv/bin/activate       # Windows PowerShell: .venv\\Scripts\\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
```

If the repository is managed with `uv`, the equivalent is:

```bash
uv sync --extra dev
```

## 2. Run the no-key Market Replay

From the repository root:

```bash
PYTHONPATH=backend python backend/scripts/market_replay.py \
  --fixture examples/market_replay/fixture.json \
  --output ./runs/market_replay_demo
```

The command exercises the same evidence path used by the runtime:

```text
ReplayProvider → ActionPack → WorldAction → WorldEvent
              → ExternalObservation → SettlementRecord → deterministic replay
```

The output directory contains:

- `replay_deterministic.json`: the auditable event and settlement trace;
- `run_manifest.json`: fixture digest, provider, run ID, and replay digest;
- `summary.md`: a human-readable, bounded result summary.

The fixture is synthetic and marked `internal_synthetic_pending_approval`.
It is engineering evidence, not a public financial dataset. The example is
not financial advice and says nothing about future returns.

## 3. Open the full local frontend (optional)

The no-key replay is intentionally independent of authentication and model
providers. If you want to inspect the full watchable viewer and operator console,
start the public capital-market configuration locally.

Terminal 1 (backend):

```bash
cd backend
source ../.venv/bin/activate
AIWORLD_CONFIG=./framework.capital_market.yaml PYTHONPATH=. \
  python -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

Terminal 2 (local account and frontend):

```bash
cd backend
source ../.venv/bin/activate
python scripts/create_user.py
cd ../frontend
npm run dev
```

Then open `http://localhost:5173` and sign in with the local account. The
capital-market world needs your own model/tool configuration for a live agent
run; the replay path above remains the supported zero-key verification path.

## 4. Check determinism

Run the command twice with two output directories and compare the canonical
replay digest in each `run_manifest.json`. A changed digest is a useful bug
report: include the operating system, Python version, commit, command, and
both manifests when opening an issue.

## 5. Explore a scenario pack

Read [the scenario-pack guide](scenario-pack-guide.md) and inspect the
[capital-market reference pack](../backend/scenarios/capital_market/) before
creating a new pack. Keep world rules, authoritative settlement, tool
permissions, and acceptance checks explicit; a prompt collection alone is not
a scenario pack.

## 6. Use a real model or tool

Only after the offline replay works, configure a provider and tool adapter in
your own environment. Never commit API keys, customer data, private run
archives, or credentials. For a bounded evaluation with evidence and a defined
acceptance criterion, use the [Agent evaluation pilot form](../.github/ISSUE_TEMPLATE/agent-evaluation-pilot.yml).

## Troubleshooting

- `ModuleNotFoundError`: activate `.venv` and repeat the editable install.
- `only the reviewed internal synthetic fixture is supported`: use the fixture
  shipped in `examples/market_replay/fixture.json` for this no-key proof.
- `replay did not reach terminal settlement`: rerun from the repository root
  and include the command, commit, Python version, and generated logs in an
  issue.
