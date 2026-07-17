"""场景驱动的测评机会调度器与效度账本。"""
from __future__ import annotations

from collections import defaultdict
from typing import Any, Dict, List, Optional

from app.core.interfaces import MeasurementOpportunityRecord


class MeasurementOpportunityCoordinator:
    """只标记真实可用机会，不放宽任何世界约束。"""

    def __init__(self, config: Dict[str, Any]):
        raw = config.get("measurement_opportunities", config) or {}
        self._policy = raw.get("policy", {}) or {}
        self._dimensions = raw.get("dimensions", {}) or {}
        self._ledger: List[MeasurementOpportunityRecord] = []
        self._pending: Dict[int, Dict[str, List[MeasurementOpportunityRecord]]] = (
            defaultdict(lambda: defaultdict(list))
        )

    @property
    def enabled(self) -> bool:
        return bool(self._dimensions)

    @property
    def ledger(self) -> List[MeasurementOpportunityRecord]:
        return list(self._ledger)

    def annotate_briefs(
        self, tick: int, briefs: Dict[str, Any]
    ) -> None:
        for agent_id, brief in briefs.items():
            available_actions = {
                item.get("id") for item in (brief.available_actions or [])
                if isinstance(item, dict) and item.get("id")
            }
            available_tools = {
                item.get("id", item.get("tool_id"))
                for item in (brief.available_tools or [])
                if isinstance(item, dict)
                and item.get("id", item.get("tool_id"))
            }
            deficits = self._dimension_deficits(agent_id)
            candidates = sorted(
                self._dimensions.items(),
                key=lambda pair: (-deficits.get(pair[0], 0), pair[0]),
            )
            max_per_tick = int(
                self._policy.get("max_disclosed_per_tick", 2) or 2
            )
            disclosed_count = 0
            for capability, spec in candidates:
                if not self._active_on_tick(spec, tick):
                    continue
                if (
                    deficits.get(capability, 0) <= 0
                    and not spec.get("continuous", False)
                ):
                    continue
                eligible_actions = sorted(
                    available_actions
                    & set(spec.get("eligible_actions", []) or [])
                )
                eligible_tools = sorted(
                    available_tools
                    & set(spec.get("eligible_tools", []) or [])
                )
                offered = bool(eligible_actions or eligible_tools)
                if not offered:
                    continue
                disclosed = bool(spec.get("disclosed", False))
                if disclosed and disclosed_count >= max_per_tick:
                    disclosed = False
                record = MeasurementOpportunityRecord(
                    opportunity_id=(
                        f"opp_{tick}_{agent_id}_{capability}_"
                        f"{len(self._ledger)}"
                    ),
                    tick=tick,
                    agent_id=agent_id,
                    capability=capability,
                    eligible_action_ids=eligible_actions,
                    eligible_tool_ids=eligible_tools,
                    disclosed=disclosed,
                    offered=True,
                    metadata={
                        "minimum_trials": int(
                            spec.get("minimum_trials", 1) or 1
                        ),
                        "availability_policy": "respect_world",
                    },
                )
                self._ledger.append(record)
                self._pending[tick][agent_id].append(record)
                if disclosed:
                    disclosed_count += 1
                    brief.measurement_opportunities.append({
                        "capability": capability,
                        "eligible_action_ids": eligible_actions,
                        "eligible_tool_ids": eligible_tools,
                        "hint": spec.get("prompt_hint", ""),
                    })

    def finalize_tick(
        self,
        tick: int,
        actions: Dict[str, Any],
        valid_actions: Dict[str, Any],
        pipeline_results: List[Any],
        state: Any,
    ) -> None:
        outcomes = {
            result.agent_id: result.outcome for result in pipeline_results
        }
        observations = (
            getattr(state, "internal", {})
            .get("capability_observations", {})
        )
        for agent_id, records in self._pending.pop(tick, {}).items():
            action = actions.get(agent_id)
            valid_action = valid_actions.get(agent_id)
            selected_action = getattr(action, "action_id", None)
            selected_tool = (
                getattr(action, "attached_tool_id", None)
                or (
                    (getattr(action, "tool_request", None) or {}).get("tool_id")
                    if action else None
                )
            )
            for record in records:
                record.selected_action_id = selected_action
                record.selected_tool_id = selected_tool
                record.selected = (
                    selected_action in record.eligible_action_ids
                    or selected_tool in record.eligible_tool_ids
                )
                record.attempted = bool(
                    record.selected and valid_action is not None
                )
                record.outcome = (
                    outcomes.get(agent_id) if record.attempted else None
                )
                signal_count = (
                    sum(
                        1
                        for item in observations
                        .get(agent_id, {})
                        .get(record.capability, [])
                        if int(item.get("tick", -1)) == tick
                    )
                    if record.attempted else 0
                )
                record.signal_count = signal_count
                record.signal_produced = signal_count > 0

        state.internal["measurement_opportunities"] = [
            item.model_dump() for item in self._ledger
        ]

    def summary(self) -> Dict[str, Any]:
        dimensions = {}
        for capability in self._dimensions:
            records = [
                item for item in self._ledger
                if item.capability == capability
            ]
            offered = sum(item.offered for item in records)
            selected = sum(item.selected for item in records)
            attempted = sum(item.attempted for item in records)
            signaled = sum(item.signal_produced for item in records)
            dimensions[capability] = {
                "offered": offered,
                "selected": selected,
                "attempted": attempted,
                "signal_produced": signaled,
                "selection_rate": round(selected / offered, 6)
                if offered else 0.0,
                "attempt_rate": round(attempted / selected, 6)
                if selected else 0.0,
                "signal_conversion_rate": round(signaled / attempted, 6)
                if attempted else 0.0,
            }
        return {
            "availability_policy": "respect_world",
            "dimensions": dimensions,
            "records": len(self._ledger),
        }

    def _dimension_deficits(self, agent_id: str) -> Dict[str, int]:
        counts = defaultdict(int)
        for item in self._ledger:
            if item.agent_id == agent_id and item.offered:
                counts[item.capability] += 1
        return {
            capability: max(
                0,
                int(spec.get("minimum_trials", 1) or 1)
                - counts[capability],
            )
            for capability, spec in self._dimensions.items()
        }

    @staticmethod
    def _active_on_tick(spec: Dict[str, Any], tick: int) -> bool:
        start = int(spec.get("start_tick", 1) or 1)
        end = spec.get("end_tick")
        return tick >= start and (end is None or tick <= int(end))
