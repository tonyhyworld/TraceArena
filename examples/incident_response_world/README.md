# Incident Response World

This is a small, deterministic, non-financial example of an AI World.
Two agents share the same synthetic incident facts, but have different
responsibilities: one coordinates containment and the other protects service
continuity. The world accepts only structured actions with evidence references.

The authoritative result is intentionally simple and inspectable:

- the incident must be acknowledged before mitigation;
- a mitigation must cite the observed service symptom and affected component;
- a resolution claim is accepted only after a health check passes;
- the settlement records accepted actions, rejected actions, and the final
  service-health state.

This pack is a contract example, not a production incident-management system.
It uses synthetic facts and has no access to real infrastructure.

## What to inspect

```text
evidence → structured action → world event → deterministic settlement → replay
```

Copy the pack, replace the fixture and rules, and run the scenario validator
from a repository checkout:

```bash
PYTHONPATH=backend python -m app.tools.validate_scenario \
  examples/incident_response_world
```

Run the deterministic fixture and its focused test:

```bash
python3 examples/incident_response_world/scripts/replay.py \
  examples/incident_response_world/tests/fixture.json
python3 -m unittest discover -s examples/incident_response_world/tests \
  -p 'test_*.py'
```

See the [scenario-pack guide](../../docs/scenario-pack-guide.md) before adding
domain-specific rules to a contribution.
