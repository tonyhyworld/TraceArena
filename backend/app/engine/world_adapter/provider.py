"""Evaluation-provider bridge for executable world adapters."""
from __future__ import annotations

import asyncio
from typing import Any, Dict, List, Optional

from app.contracts.world_adapter import (
    WorldAdapterActionReceipt,
    WorldAdapterCommand,
    WorldAdapterObservation,
    WorldAdapterTransition,
)
from app.core.interfaces import (
    ActionPack,
    CausalPipelineResult,
    CausalSequence,
    CausalSequenceStep,
)
from app.engine.world_adapter.base import WorldAdapter
from app.engine.world_adapter.registry import get_world_adapter_descriptor


class _EmptyObjects:
    def public_snapshot(self) -> List[Dict[str, Any]]:
        return []

    def get(self, object_id: str) -> Any:
        raise KeyError(object_id)


class _NoopPressure:
    def get_state(self, actor_id: str) -> None:
        return None

    def advance_tick(self, *args: Any, **kwargs: Any) -> None:
        return None

    def accumulate_strategy_risk(self, *args: Any, **kwargs: Any) -> None:
        return None

    def gain_information_scope(self, *args: Any, **kwargs: Any) -> None:
        return None

    def signal_counterplay(self, *args: Any, **kwargs: Any) -> None:
        return None

    def update_information_scope(self, *args: Any, **kwargs: Any) -> None:
        return None

    def end_tick(self) -> None:
        return None


class WorldAdapterContext:
    """Compatibility surface for perception while RuleWorld is phased out."""

    def __init__(self, runtime: Any):
        self.objects = _EmptyObjects()
        self.pressure = _NoopPressure()
        self.tools_cfg = list(getattr(runtime, "tools_cfg", []) or [])
        self.metrics_cfg = dict(getattr(runtime, "metrics_cfg", {}) or {})
        self.metrics = None
        self.evidence = None


class WorldAdapterEvaluationProvider:
    """Expose a WorldAdapter through the existing EvaluationEngine boundary."""

    def __init__(
        self,
        runtime: Any,
        adapter: WorldAdapter,
        adapter_id: str,
    ):
        self._runtime = runtime
        self._adapter = adapter
        self._adapter_id = adapter_id
        self._context = WorldAdapterContext(runtime)
        self._state: Any = None
        self._tick = 0
        self._initialized = False
        self._transitions: List[WorldAdapterTransition] = []
        self._receipts: List[WorldAdapterActionReceipt] = []

    def initialize(self) -> None:
        if self._initialized:
            return
        cfg = dict(getattr(self._runtime, "world_adapter_cfg", {}) or {})
        configured_id = str(cfg.get("adapter_id") or "")
        if configured_id and configured_id != self._adapter_id:
            raise ValueError(
                f"world adapter config mismatch: route={self._adapter_id}, "
                f"config={configured_id}"
            )
        adapter_config = dict(cfg.get("config", {}) or {})
        adapter_config.setdefault(
            "actor_ids", list(getattr(self._runtime, "agent_slot_ids", []) or [])
        )
        seed_manager = getattr(self._runtime, "seed_manager", None)
        seed = getattr(seed_manager, "seed", None)
        if cfg.get("seed") is not None:
            seed = int(cfg["seed"])
        self._adapter.initialize(adapter_config, seed)
        self._adapter.reset()
        provenance = self._adapter.provenance()
        descriptor = get_world_adapter_descriptor(self._adapter_id)
        configured_kind = str(cfg.get("model_kind") or "").strip()
        if provenance.adapter_id != self._adapter_id:
            raise ValueError(
                "world adapter provenance mismatch: "
                f"route={self._adapter_id}, provenance={provenance.adapter_id}"
            )
        if provenance.model_kind != descriptor.model_kind:
            raise ValueError(
                "world model kind mismatch: "
                f"registry={descriptor.model_kind}, "
                f"provenance={provenance.model_kind}"
            )
        if configured_kind and configured_kind != descriptor.model_kind:
            raise ValueError(
                "world model kind mismatch: "
                f"config={configured_kind}, registry={descriptor.model_kind}"
            )
        self._initialized = True

    @property
    def context(self) -> WorldAdapterContext:
        return self._context

    def set_judge(self, judge: Any, **opts: Any) -> None:
        # External simulators, not an LLM judge, own world transitions.
        return None

    def bind_state(self, state: Any) -> None:
        self._state = state
        self._sync_state()

    def advance_tick(self, tick: int) -> None:
        self._tick = tick

    async def run_causal_pipeline(
        self,
        action: ActionPack,
        tick: int,
        state: Any,
        tool_result: Any = None,
    ) -> CausalPipelineResult:
        results = await self.run_action_batch(
            [action], tick, state, {action.agent_id: tool_result}
        )
        return results[action.agent_id]

    async def run_action_batch(
        self,
        actions: List[ActionPack],
        tick: int,
        state: Any,
        tool_results: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, CausalPipelineResult]:
        if not self._initialized:
            raise RuntimeError(f"world adapter not initialized: {self._adapter_id}")
        commands = [self._command(action, tick) for action in actions]
        # Professional simulators are usually synchronous and CPU-heavy.
        # Keep their step out of FastAPI's event loop.
        submitted = await asyncio.to_thread(
            self._adapter.apply_actions, commands
        )
        transition = await asyncio.to_thread(self._adapter.step, tick)
        self._transitions.append(transition)
        effective = {
            item.command_id: item for item in [*submitted, *transition.receipts]
        }
        self._receipts.extend(effective.values())
        self._state = state
        self._sync_state(transition)

        results: Dict[str, CausalPipelineResult] = {}
        for action, command in zip(actions, commands):
            receipt = effective.get(command.command_id)
            if receipt is None:
                receipt = WorldAdapterActionReceipt(
                    receipt_id=f"receipt:{command.command_id}",
                    command_id=command.command_id,
                    world_tick=tick,
                    actor_id=command.actor_id,
                    action_type=command.action_type,
                    status="failed",
                    reasons=["adapter_missing_receipt"],
                )
            outcome = {
                "accepted": "success",
                "executed": "success",
                "rejected": "invalid",
                "failed": "error",
            }[receipt.status]
            sequence = CausalSequence(
                sequence_id=f"adapter-sequence:{tick}:{action.agent_id}",
                tick=tick,
                source_action_id=action.action_id,
                actor_id=action.agent_id,
                steps=[
                    CausalSequenceStep(
                        kind="world_adapter",
                        ref_id=transition.transition_id,
                        title=self._adapter_id,
                        summary=(
                            f"{receipt.action_type}: {receipt.status}"
                        ),
                        actor_id=action.agent_id,
                        metadata={
                            "adapter_id": self._adapter_id,
                            "receipt_id": receipt.receipt_id,
                            "provenance": transition.provenance.model_dump(
                                mode="json"
                            ),
                        },
                    )
                ],
                summary=f"世界适配器已返回 {receipt.status} 回执",
                metadata={"adapter_id": self._adapter_id},
            )
            results[action.agent_id] = CausalPipelineResult(
                tick=tick,
                action_id=action.action_id,
                agent_id=action.agent_id,
                sequence=sequence,
                outcome=outcome,
                errors=list(receipt.reasons),
                action=action,
                world_action_receipt=receipt,
                world_transition=transition,
            )
        return results

    def export_ledgers(self) -> Dict[str, Any]:
        return {
            "world_adapter_transitions": [
                item.model_dump(mode="json") for item in self._transitions
            ],
            "world_adapter_receipts": [
                item.model_dump(mode="json") for item in self._receipts
            ],
        }

    @property
    def tools_cfg(self) -> List[Dict[str, Any]]:
        return list(getattr(self._runtime, "tools_cfg", []) or [])

    def get_action_rule(self, action_id: str) -> Dict[str, Any]:
        return self._runtime.get_action_rule(action_id)

    def execution_route(self, action_id: str) -> Dict[str, Any]:
        return {
            "mode": "simulation",
            "provider_id": self._adapter_id,
            "world_adapter_id": self._adapter_id,
            "action_id": action_id,
        }

    def requires_simulation(self, action_id: str) -> bool:
        return True

    def observation(self, actor_id: str) -> Optional[WorldAdapterObservation]:
        if not self._initialized:
            return None
        return self._adapter.observe(actor_id)

    def close(self) -> None:
        self._adapter.close()

    @staticmethod
    def _command(action: ActionPack, tick: int) -> WorldAdapterCommand:
        targets = [
            str(item)
            for item in (action.target_object_id, action.target_agent_id)
            if item
        ]
        return WorldAdapterCommand(
            command_id=f"adapter-command:{tick}:{action.agent_id}",
            world_tick=tick,
            actor_id=action.agent_id,
            action_type=action.action_id,
            target_ids=targets,
            parameters=dict(action.parameters or {}),
            evidence_refs=list(
                action.evidence_refs or action.linked_evidence_ids or []
            ),
        )

    def _sync_state(
        self, transition: Optional[WorldAdapterTransition] = None
    ) -> None:
        if self._state is None:
            return
        actor_ids = list(getattr(self._state, "agent_ids", []) or [])
        observations: Dict[str, Any] = {}
        for actor_id in actor_ids:
            try:
                observations[actor_id] = self._adapter.observe(
                    actor_id
                ).model_dump(mode="json")
            except Exception:
                continue
        payload = {
            "adapter_id": self._adapter_id,
            "snapshot": self._adapter.snapshot(),
            "metrics": self._adapter.metrics(),
            "terminal": self._adapter.terminal().model_dump(mode="json"),
            "provenance": self._adapter.provenance().model_dump(mode="json"),
            "observations": observations,
        }
        if transition is not None:
            payload["last_transition"] = transition.model_dump(mode="json")
        self._state.internal["world_adapter"] = payload
        terminal = self._adapter.terminal()
        if terminal.done:
            self._state.is_game_over = True
            self._state.winner_id = (
                terminal.winner_ids[0] if terminal.winner_ids else None
            )
