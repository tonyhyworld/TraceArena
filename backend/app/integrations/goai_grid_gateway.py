"""Reusable AgentTeams gateway for the GOAI grid emergency world."""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List

from app.contracts.world_adapter import WorldAdapterCommand
from app.engine.scenario_boot.compiler import ScenarioCompiler
from app.engine.scenario_boot.loader import ScenarioBootKernel
from app.engine.world_adapter.grid2op_adapter import Grid2OpAdapter


GRID_SCENARIO_ROOT = (
    Path(__file__).resolve().parents[2] / "scenarios" / "grid_emergency"
)


class GridAgentTeamsGateway:
    """Bridge gateway backed by the real Grid2Op adapter."""

    def __init__(self) -> None:
        self.scenario = ScenarioBootKernel.load(str(GRID_SCENARIO_ROOT))
        ScenarioCompiler.compile(self.scenario)
        self.actor_ids = [role.agent_slot_id for role in self.scenario.agent_roles]
        config = dict(self.scenario.world_adapter_cfg.get("config", {}) or {})
        config["actor_ids"] = self.actor_ids
        self.adapter = Grid2OpAdapter()
        self.adapter.initialize(config, self.scenario.world_adapter_cfg.get("seed"))
        self.adapter.reset()
        self.evidence: List[Dict[str, Any]] = []
        self.approvals: Dict[str, str] = {}
        self.transitions: List[Dict[str, Any]] = []
        self._tick = 1

    def create_world_run(
        self, scenario_id: str, goal: str, metadata: Dict[str, Any]
    ) -> str:
        del goal, metadata
        return f"goai-grid-world:{scenario_id}"

    def register_world_actor(
        self, world_run_id: str, actor_id: str, scenario_role: str
    ) -> Dict[str, Any]:
        del world_run_id
        if actor_id not in self.actor_ids:
            raise ValueError(f"unknown grid actor: {actor_id}")
        return {
            "permissions": ["observe_grid", "submit_dispatch_action"],
            "scenario_role": scenario_role,
        }

    def observe_world(self, world_run_id: str, actor_id: str) -> Dict[str, Any]:
        del world_run_id
        return {
            "observation": self.adapter.observe(actor_id).model_dump(mode="json"),
            "metrics": self.adapter.metrics().get(actor_id, {}),
        }

    def submit_world_action(
        self,
        world_run_id: str,
        actor_id: str,
        action: Dict[str, Any],
    ) -> Dict[str, Any]:
        del world_run_id
        command = WorldAdapterCommand(
            command_id=f"goai:{self._tick}:{actor_id}:{action['action_id']}",
            world_tick=self._tick,
            actor_id=actor_id,
            action_type=str(action["action_type"]),
            parameters=dict(action.get("parameters") or {}),
            evidence_refs=list(action.get("evidence_refs") or []),
        )
        submitted = self.adapter.apply_actions([command])
        receipt = submitted[0]
        if receipt.status == "accepted":
            transition = self.adapter.step(self._tick)
            self.transitions.append(transition.model_dump(mode="json"))
            receipt = next(
                item for item in transition.receipts
                if item.command_id == command.command_id
            )
            self._tick += 1
        return receipt.model_dump(mode="json")

    def submit_world_evidence(
        self,
        world_run_id: str,
        actor_id: str,
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]:
        del world_run_id
        evidence_ref = f"evidence:{len(self.evidence) + 1}"
        self.evidence.append({
            "evidence_ref": evidence_ref,
            "actor_id": actor_id,
            **evidence,
        })
        return {"evidence_ref": evidence_ref, "status": "accepted"}

    def resolve_world_approval(
        self, world_run_id: str, approval_id: str, decision: str
    ) -> Dict[str, Any]:
        del world_run_id
        self.approvals[approval_id] = decision
        return {"approval_id": approval_id, "status": decision}

    def world_status(self, world_run_id: str) -> Dict[str, Any]:
        return {
            "world_run_id": world_run_id,
            "metrics": self.adapter.metrics(),
            "terminal": self.adapter.terminal().model_dump(mode="json"),
            "evidence_count": len(self.evidence),
            "approval_count": len(self.approvals),
            "transition_count": len(self.transitions),
        }

    def close(self) -> None:
        self.adapter.close()
