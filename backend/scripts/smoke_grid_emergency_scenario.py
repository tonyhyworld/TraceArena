"""Run the Grid2Op-backed emergency recovery scenario with all three agents.

This is an integration smoke test, not a mocked adapter test: it loads the
scenario package contract, starts three seeded Grid2Op environments, applies
three declared scene actions, and prints the simulator's physical feedback.
"""
from __future__ import annotations

import json
from pathlib import Path

from app.contracts.world_adapter import WorldAdapterCommand
from app.engine.scenario_boot.compiler import ScenarioCompiler
from app.engine.scenario_boot.loader import ScenarioBootKernel
from app.engine.world_adapter.grid2op_adapter import Grid2OpAdapter


ROOT = Path(__file__).resolve().parents[1] / "scenarios" / "grid_emergency"


def main() -> None:
    scenario = ScenarioBootKernel.load(str(ROOT))
    ScenarioCompiler.compile(scenario)
    actor_ids = [role.agent_slot_id for role in scenario.agent_roles]
    config = dict(scenario.world_adapter_cfg.get("config", {}))
    config["actor_ids"] = actor_ids

    adapter = Grid2OpAdapter()
    try:
        adapter.initialize(config, scenario.world_adapter_cfg.get("seed"))
        observations = adapter.reset()
        actions = [
            "maintain_safe_isolation",
            "restore_fault_line",
            "deploy_reserve_redispatch",
        ]
        commands = [
            WorldAdapterCommand(
                command_id=f"smoke-{actor_id}",
                world_tick=1,
                actor_id=actor_id,
                action_type=action_id,
                parameters=(
                    {"approval_decision": "approved"}
                    if action_id == "restore_fault_line"
                    else {}
                ),
            )
            for actor_id, action_id in zip(actor_ids, actions)
        ]
        submitted = adapter.apply_actions(commands)
        transition = adapter.step(1)
        print(json.dumps({
            "scenario": scenario.manifest.scenario_id,
            "actors": actor_ids,
            "initial_observations": sorted(observations),
            "submitted": [item.status for item in submitted],
            "executed": [item.status for item in transition.receipts],
            "metrics": transition.metrics,
            "terminal": transition.terminal.model_dump(mode="json"),
            "provenance": transition.provenance.model_dump(mode="json"),
        }, ensure_ascii=False, indent=2))
    finally:
        adapter.close()


if __name__ == "__main__":
    main()
