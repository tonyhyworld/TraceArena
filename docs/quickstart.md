# TraceArena in five minutes

[简体中文](quickstart.zh-CN.md)

TraceArena is a runtime for worlds in which agents must act under rules and
accept results that an independent world can verify. You can try the public
demo first, then run the same idea locally without an API key.

## 1. Watch the public demo

Open the [TraceArena AI World Demo](https://tonyworld888-tracearena-demo.static.hf.space/index.html).
It is a safe browser-local replay of the NOVA-7 market challenge:

- Astra and Vector receive the same synthetic evidence;
- each agent follows a different decision strategy;
- the world applies market events and risk rules;
- the verifier settles the final score.

The demo does not call an LLM, connect to a broker, or accept user data.

## 2. Run a deterministic world locally

Prerequisites: Python 3.10+ and Git.

```bash
git clone https://github.com/tonyhyworld/TraceArena.git
cd TraceArena
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
PYTHONPATH=backend python backend/scripts/market_replay.py \
  --fixture examples/market_replay/fixture.json \
  --output ./runs/market_replay_demo \
  --locale en-US
```

The replay uses synthetic fixtures and a simulated ledger. It makes no model
call and places no real orders.

## 3. Inspect the result

Open `frontend/public_viewer/index.html` in a modern browser, or inspect the
generated files directly:

```text
runs/market_replay_demo/
├── replay_deterministic.json   # ordered actions, events, and settlements
└── run_manifest.json           # run identity, locale, and provenance
```

The useful question is not only “who won?” but also:

```text
What did the agent observe?
→ Which action did it request?
→ Which rule accepted or rejected it?
→ What changed in the world?
→ Who settled the outcome?
```

## 4. Build a scenario pack

Copy [`examples/scenario_pack_template`](../examples/scenario_pack_template/)
and read the [scenario-pack guide](scenario-pack-guide.md). A scenario pack
owns domain rules; the generic runtime owns execution, evidence, replay, and
settlement plumbing.

Before opening a pull request, include a reproducible fixture, validation
expectations, settlement authority, and provenance for every non-code asset.

## 5. Get help

- Report a reproducible bug with the [bug template](https://github.com/tonyhyworld/TraceArena/issues/new?template=bug.yml).
- Propose a new world with the [scenario-pack template](https://github.com/tonyhyworld/TraceArena/issues/new?template=scenario-pack.yml).
- Read [Contributing](../CONTRIBUTING.md) before opening a pull request.

TraceArena is Apache-2.0 licensed. The public demo is an evaluation and
education tool, not investment advice.
