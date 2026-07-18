# Incident Response World — Benchmark Card v0

## Summary

This benchmark measures whether an agent can carry a decision through an
evidence-constrained, stateful incident rather than merely describe a good
response in prose.

The public fixture is synthetic and intentionally small. Two roles share the
same observation bundle:

- **Incident Commander** — owns acknowledgement, sequencing, and evidence
  quality.
- **Service Owner** — proposes a bounded mitigation and challenges unsupported
  closure.

The reference episode is available in
[`examples/incident_response_world/tests/fixture.json`](../../examples/incident_response_world/tests/fixture.json).

## Evaluation question

Can an agent:

1. cite an observation before acting;
2. respect action dependencies;
3. recover from or expose a rejected action;
4. wait for an authoritative health check before claiming resolution; and
5. leave a replay that explains both accepted and rejected actions?

## Contract

| Component | Public definition |
| --- | --- |
| World state | Synthetic incident, affected component, service health, response status |
| Evidence | Versioned `signal_001` and `health_002` fixture records |
| Actions | Acknowledge, propose mitigation, run health check, declare resolved |
| Invalid path | Declaring resolved before a passing health check |
| Authority | Deterministic verifier `incident_response_verifier` |
| Terminal outcome | `incident_status=resolved`, `service_health=100` |

## Metrics

- **Evidence quality** — whether accepted actions cite valid fixture evidence;
- **Response progress** — whether the dependency chain is respected;
- **Service health** — the authoritative terminal state;
- **Failure explanation** — the recorded reason for every rejected action.

The current fixture is a contract test, not a model leaderboard. It does not
claim that one model is better than another and does not measure production
incident response skill.

## Reproduction

```bash
python3 examples/incident_response_world/scripts/replay.py \
  examples/incident_response_world/tests/fixture.json
python3 -m unittest discover -s examples/incident_response_world/tests \
  -p 'test_*.py'
```

The expected rejection is `passing_health_check_required`; the final synthetic
settlement is a resolved incident with service health 100.

## Next research extensions

- add multiple incident fixtures with controlled evidence omissions;
- compare scripted, tool-using, and model-backed agents under the same contract;
- publish per-step failure categories and replay digests;
- add an independent verifier implementation to test settlement portability.

## Limitations and provenance

All facts are synthetic, no production system is contacted, and no private or
licensed operational data is included. The scenario pack and this card are
released under Apache-2.0 with the rest of the public TraceArena candidate.
