"""Settlement plug-in owned by the Grid2Op emergency-recovery scenario.

The OS supplies immutable world facts.  This plug-in does not calculate a
power flow, manufacture a reward or reinterpret Grid2Op's physics; it only
projects the simulator's authoritative per-agent metrics into the portable
SettlementRecord contract used by rankings, replay and the operator UI.
"""
from __future__ import annotations

from typing import Any, Dict, List

from app.contracts.os2 import SettlementAuthority, SettlementRecord, WorldEvent


_PROVIDER_ID = "grid2op_simulator"
_RULE_VERSION = "grid2op.l2rpn_case14_sandbox.v1"
_VALUE_KEYS = ("cumulative_reward", "max_rho", "disconnected_lines")


def _numbers(raw: Any) -> Dict[str, float]:
    values = raw if isinstance(raw, dict) else {}
    return {
        key: float(values.get(key, 0.0) or 0.0)
        for key in _VALUE_KEYS
    }


def _authority() -> SettlementAuthority:
    return SettlementAuthority(
        mode="simulation",
        provider_id=_PROVIDER_ID,
        rule_version=_RULE_VERSION,
        reproducible=True,
        deterministic=True,
    )


class GridEmergencySettlement:
    plugin_id = "grid_emergency.grid2op_settlement.v1"

    def __init__(self) -> None:
        self._last_event_by_agent: Dict[str, str] = {}
        self._latest_metrics: Dict[str, Dict[str, float]] = {}

    def settle(
        self,
        events: List[WorldEvent],
        context: Any,
    ) -> List[SettlementRecord]:
        records: List[SettlementRecord] = []
        for event in events:
            if event.origin != "action" or not event.actor_id:
                continue
            transition = (event.deltas or {}).get("world_transition") or {}
            metrics_by_agent = transition.get("metrics") or {}
            metrics = _numbers(metrics_by_agent.get(event.actor_id))
            # Non-adapter events do not carry a Grid2Op transition and must
            # remain outside this scenario's physical result stream.
            if not metrics_by_agent or event.actor_id not in metrics_by_agent:
                continue
            actor_id = str(event.actor_id)
            self._last_event_by_agent[actor_id] = event.event_id
            self._latest_metrics[actor_id] = metrics
            receipt = (event.deltas or {}).get("world_action_receipt") or {}
            action_type = str((event.deltas or {}).get("action_type") or "")
            records.append(SettlementRecord(
                settlement_id=f"grid2op:tick:{context.world_tick}:{actor_id}",
                run_id=context.run_id,
                scenario_id=context.scenario_id,
                world_tick=context.world_tick,
                evaluator_id=self.plugin_id,
                authority=_authority(),
                kind="scenario_outcome",
                subject_ids=[actor_id],
                source_event_refs=[event.event_id],
                rule_refs=[
                    _RULE_VERSION,
                    "settlement/manifest.yaml#metric_bindings",
                ],
                outcome=str(receipt.get("status") or "executed"),
                values=metrics,
                details={
                    "display_text": (
                        f"本回合动作：{action_type or '未知'}；"
                        f"累计恢复收益 {metrics['cumulative_reward']:.2f}，"
                        f"最大线路负载率 {metrics['max_rho']:.3f}，"
                        f"断开线路 {int(metrics['disconnected_lines'])} 条。"
                    ),
                    "simulator_receipt": receipt,
                },
                explanation="数值由 Grid2Op 仿真器在同一外生故障轨迹下计算。",
                affects_world=False,
                affects_victory=False,
            ))
        return records

    def finalize(self, context: Any) -> List[SettlementRecord]:
        runtime_metrics = (
            ((context.world_state or {}).get("internal") or {})
            .get("world_adapter", {})
            .get("metrics", {})
        )
        metrics_by_agent = (
            runtime_metrics if isinstance(runtime_metrics, dict)
            else self._latest_metrics
        )
        records: List[SettlementRecord] = []
        for actor_id in list((context.world_state or {}).get("agent_ids") or []):
            actor_id = str(actor_id)
            event_id = self._last_event_by_agent.get(actor_id)
            if not event_id:
                # A final victory claim is invalid without an executed physical
                # world fact.  Returning no record keeps the OS fail-closed.
                continue
            metrics = _numbers(metrics_by_agent.get(actor_id))
            records.append(SettlementRecord(
                settlement_id=f"grid2op:final:{context.world_tick}:{actor_id}",
                run_id=context.run_id,
                scenario_id=context.scenario_id,
                world_tick=context.world_tick,
                evaluator_id=self.plugin_id,
                authority=_authority(),
                kind="scenario_outcome",
                subject_ids=[actor_id],
                source_event_refs=[event_id],
                rule_refs=[_RULE_VERSION, "settlement/manifest.yaml#victory"],
                outcome="finalized",
                values=metrics,
                details={
                    "display_text": (
                        f"终局物理结果：累计恢复收益 {metrics['cumulative_reward']:.2f}；"
                        f"最大线路负载率 {metrics['max_rho']:.3f}；"
                        f"断开线路 {int(metrics['disconnected_lines'])} 条。"
                    )
                },
                explanation="胜负按 Grid2Op 累计恢复收益排序；其他物理指标保留供审计比较。",
                affects_world=False,
                affects_victory=True,
            ))
        return records


def create_plugin() -> GridEmergencySettlement:
    return GridEmergencySettlement()
