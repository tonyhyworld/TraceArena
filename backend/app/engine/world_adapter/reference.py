"""Small deterministic adapter used for contract tests and SDK examples."""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from app.contracts.world_adapter import (
    WorldAdapterActionReceipt,
    WorldAdapterCommand,
    WorldAdapterObservation,
    WorldAdapterProvenance,
    WorldAdapterTerminal,
    WorldAdapterTransition,
    WorldModelAssurance,
)


class DeterministicCounterAdapter:
    adapter_id = "builtin:deterministic_counter"
    adapter_version = "1.0.0"

    def __init__(self) -> None:
        self._config: Dict[str, Any] = {}
        self._seed: Optional[int] = None
        self._values: Dict[str, float] = {}
        self._pending: List[WorldAdapterCommand] = []
        self._terminal = WorldAdapterTerminal()

    def initialize(self, config: Dict[str, Any], seed: Optional[int]) -> None:
        self._config = dict(config or {})
        self._seed = seed
        actors = [str(item) for item in self._config.get("actor_ids", []) or []]
        initial = float(self._config.get("initial_value", 0.0) or 0.0)
        self._values = {actor_id: initial for actor_id in actors}

    def reset(self) -> Dict[str, WorldAdapterObservation]:
        initial = float(self._config.get("initial_value", 0.0) or 0.0)
        self._values = {actor_id: initial for actor_id in self._values}
        self._pending = []
        self._terminal = WorldAdapterTerminal()
        return {actor_id: self.observe(actor_id) for actor_id in self._values}

    def observe(self, actor_id: str) -> WorldAdapterObservation:
        self._values.setdefault(actor_id, 0.0)
        return WorldAdapterObservation(
            observation_id=f"counter:{actor_id}:{self._values[actor_id]}",
            world_tick=0,
            actor_id=actor_id,
            values={"value": self._values[actor_id]},
            legal_actions=self.legal_actions(actor_id),
        )

    def legal_actions(self, actor_id: str) -> List[Dict[str, Any]]:
        return [
            {"action_type": "increment", "parameters": {"amount": "number"}},
            {"action_type": "decrement", "parameters": {"amount": "number"}},
            {"action_type": "wait", "parameters": {}},
        ]

    def apply_actions(
        self, commands: List[WorldAdapterCommand]
    ) -> List[WorldAdapterActionReceipt]:
        receipts: List[WorldAdapterActionReceipt] = []
        self._pending = []
        for command in commands:
            if command.action_type not in {"increment", "decrement", "wait"}:
                receipts.append(WorldAdapterActionReceipt(
                    receipt_id=f"receipt:{command.command_id}",
                    command_id=command.command_id,
                    world_tick=command.world_tick,
                    actor_id=command.actor_id,
                    action_type=command.action_type,
                    status="rejected",
                    reasons=["unsupported_action"],
                ))
                continue
            self._pending.append(command)
            receipts.append(WorldAdapterActionReceipt(
                receipt_id=f"receipt:{command.command_id}",
                command_id=command.command_id,
                world_tick=command.world_tick,
                actor_id=command.actor_id,
                action_type=command.action_type,
                status="accepted",
            ))
        return receipts

    def step(self, world_tick: int) -> WorldAdapterTransition:
        before = dict(self._values)
        receipts: List[WorldAdapterActionReceipt] = []
        for command in self._pending:
            amount = float(command.parameters.get("amount", 1.0) or 1.0)
            self._values.setdefault(command.actor_id, 0.0)
            if command.action_type == "increment":
                self._values[command.actor_id] += amount
            elif command.action_type == "decrement":
                self._values[command.actor_id] -= amount
            receipts.append(WorldAdapterActionReceipt(
                receipt_id=f"receipt:{command.command_id}",
                command_id=command.command_id,
                world_tick=world_tick,
                actor_id=command.actor_id,
                action_type=command.action_type,
                status="executed",
                details={"value": self._values[command.actor_id]},
            ))
        target = self._config.get("terminal_value")
        winners = [
            actor_id for actor_id, value in self._values.items()
            if target is not None and value >= float(target)
        ]
        self._terminal = WorldAdapterTerminal(
            done=bool(winners),
            reason="target_reached" if winners else "",
            winner_ids=winners,
        )
        observations = [
            WorldAdapterObservation(
                observation_id=f"counter:{world_tick}:{actor_id}",
                world_tick=world_tick,
                actor_id=actor_id,
                values={"value": value},
                legal_actions=self.legal_actions(actor_id),
            )
            for actor_id, value in self._values.items()
        ]
        transition = WorldAdapterTransition(
            transition_id=f"counter-transition:{world_tick}",
            world_tick=world_tick,
            adapter_id=self.adapter_id,
            state_before=before,
            state_after=dict(self._values),
            deltas={
                actor_id: self._values[actor_id] - before.get(actor_id, 0.0)
                for actor_id in self._values
            },
            metrics=self.metrics(),
            receipts=receipts,
            observations=observations,
            terminal=self._terminal,
            provenance=self.provenance(),
        )
        self._pending = []
        return transition

    def metrics(self) -> Dict[str, Any]:
        return {actor_id: {"value": value} for actor_id, value in self._values.items()}

    def terminal(self) -> WorldAdapterTerminal:
        return self._terminal

    def snapshot(self) -> Dict[str, Any]:
        return {"values": dict(self._values)}

    def provenance(self) -> WorldAdapterProvenance:
        payload = json.dumps(self._config, sort_keys=True, default=str).encode()
        return WorldAdapterProvenance(
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            model_kind="algorithmic",
            engine_name="deterministic-counter",
            engine_version=self.adapter_version,
            config_hash=hashlib.sha256(payload).hexdigest(),
            seed=self._seed,
            deterministic=True,
            source_uri="tracearena://builtin/deterministic-counter",
            assurance=WorldModelAssurance(
                trust_tier="validated",
                validation_refs=["backend/tests/test_world_adapter.py"],
                limitations=["SDK contract example; not a domain model"],
            ),
        )

    def close(self) -> None:
        self._pending = []
