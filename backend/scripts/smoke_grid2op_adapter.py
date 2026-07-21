"""Run a real two-actor smoke test against the optional Grid2Op adapter."""
from __future__ import annotations

import argparse
import json
from pathlib import Path
import sys

BACKEND_ROOT = Path(__file__).resolve().parents[1]
if str(BACKEND_ROOT) not in sys.path:
    sys.path.insert(0, str(BACKEND_ROOT))

from app.contracts.world_adapter import WorldAdapterCommand
from app.engine.world_adapter.grid2op_adapter import Grid2OpAdapter


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--environment", default="l2rpn_case14_sandbox")
    parser.add_argument("--seed", type=int, default=42)
    args = parser.parse_args()

    adapter = Grid2OpAdapter()
    adapter.initialize({
        "actor_ids": ["agent_a", "agent_b"],
        "environment": args.environment,
        "action_mapping": {"wait": {}},
    }, seed=args.seed)
    try:
        initial = adapter.reset()
        submitted = adapter.apply_actions([
            WorldAdapterCommand(
                command_id="smoke:agent_a",
                world_tick=1,
                actor_id="agent_a",
                action_type="wait",
            ),
            WorldAdapterCommand(
                command_id="smoke:agent_b",
                world_tick=1,
                actor_id="agent_b",
                action_type="wait",
            ),
        ])
        transition = adapter.step(1)
        print(json.dumps({
            "adapter_id": transition.adapter_id,
            "environment": args.environment,
            "seed": transition.provenance.seed,
            "engine_version": transition.provenance.engine_version,
            "actors": sorted(initial),
            "submitted": [item.status for item in submitted],
            "executed": [item.status for item in transition.receipts],
            "transition_id": transition.transition_id,
            "metrics": transition.metrics,
        }, ensure_ascii=False, indent=2))
    finally:
        adapter.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
