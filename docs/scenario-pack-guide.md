# Scenario-pack contribution guide

[简体中文](scenario-pack-guide.zh-CN.md)

A scenario pack supplies the domain contract; TraceArena supplies the generic
runtime. A pack should describe a world that can reject an unsupported action,
settle an accepted action, and leave enough evidence to explain the result.

## Start from the reference pack

Copy or read [`backend/scenarios/capital_market`](../backend/scenarios/capital_market).
It is the reference implementation for the currently supported scenario API
(`1.0`). Keep the runtime generic: if a rule only makes sense in your world,
it belongs in the pack rather than in `backend/app/engine`.

## Minimum authoring checklist

1. Create `manifest.json` with a stable `scenario_id`, API version, required
   OS capabilities, and entry-file map.
2. Define roles under `agents/` and actions under `world/actions.yaml` with
   explicit parameter shapes.
3. Define visibility, permissions, resources, and metrics under `world/` so
   the runtime can decide what each actor can perceive and do.
4. Choose the settlement authority under `settlement/`: deterministic verifier,
   scenario rules, externally verifiable facts, or an explicit hybrid.
5. Add validation, a sample run, and replay expectations under `tests/`.
6. Add only assets you have a right to redistribute; document provenance in an
   adjacent `PROVENANCE.md`.

## Design for auditability

For every important action, a reviewer should be able to answer:

```text
Who acted? → What was observed? → Which action was requested?
→ Which rule/evidence accepted or rejected it? → What world state changed?
```

Avoid letting natural-language narration be the only authority. Put decisive
constraints in structured validation or settlement rules, record the relevant
evidence reference, and make failure/rejection reasons part of the trace.

## Validate before opening a pull request

Run the deterministic example and the repository tests from the project root:

```bash
PYTHONPATH=backend python backend/scripts/market_replay.py \
  --fixture examples/market_replay/fixture.json \
  --output ./runs/market_replay_demo
PYTHONPATH=backend pytest backend/tests -q
```

Then open a pull request explaining your settlement authority, the fixtures
that demonstrate it, what is public-safe, and any external data or asset
licenses. See [Contributing](../CONTRIBUTING.md) for DCO and security rules.
