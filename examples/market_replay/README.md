# Offline Market Replay

[English](README.md) | [简体中文](README.zh-CN.md)

This is a deterministic, no-key proof of the AI World action pipeline. It uses
synthetic fixture data, does not connect to a brokerage, and does not call an
LLM or an MCP server.

From the repository root:

```bash
PYTHONPATH=backend python backend/scripts/market_replay.py \
  --fixture examples/market_replay/fixture.json \
  --output ./runs/market_replay_demo \
  --locale en-US
```

The command runs the formal EngineOS path:

```text
ReplayProvider → ActionPack → WorldAction → WorldEvent
              → ExternalObservation → SettlementRecord → replay_deterministic.json
```

The fixture is intentionally labelled `internal_synthetic_pending_approval`.
It is engineering evidence, not a public financial dataset. Its public asset
provenance is recorded in the scenario package; it does not turn the fixture
into financial advice or a source of market truth.

Use `--locale zh-CN` for Chinese CLI output, summary, and scripted-action
text. Locale selection does not change evidence IDs, settlement, or replay
semantics.

The demo is not financial advice and does not demonstrate future returns.
