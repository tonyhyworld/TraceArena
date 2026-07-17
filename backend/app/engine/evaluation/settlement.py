"""Scenario-owned settlement runtime.

Evaluation Runtime provides orchestration and authority checks. The scenario
plugin owns the meaning of success and the actual settlement formula.
"""
from __future__ import annotations

import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional, Protocol, Sequence, Set

from app.contracts.os2 import SettlementRecord, VictoryStanding, WorldEvent
from app.engine.event.observation import ObservationRuntime


@dataclass(frozen=True)
class SettlementContext:
    run_id: str
    scenario_id: str
    world_tick: int
    world_state: Dict[str, Any]


class SettlementPlugin(Protocol):
    plugin_id: str

    def settle(
        self,
        events: Sequence[WorldEvent],
        context: SettlementContext,
    ) -> List[SettlementRecord]: ...

    def finalize(self, context: SettlementContext) -> List[SettlementRecord]: ...


class SettlementRuntime:
    """Runs scenario settlement plugins against authoritative world facts."""

    def __init__(
        self,
        plugins: Sequence[SettlementPlugin] = (),
        *,
        authority_policies: Optional[Dict[str, Any]] = None,
        observations: Optional[ObservationRuntime] = None,
    ):
        self._plugins = list(plugins)
        raw_config = dict(authority_policies or {})
        self._victory_policy = dict(raw_config.get("victory", {}) or {})
        raw_policies = (authority_policies or {}).get(
            "providers", authority_policies or {}
        )
        self._authority_policies = {
            str(item.get("id")): dict(item)
            for item in raw_policies
            if isinstance(item, dict) and item.get("id")
        } if isinstance(raw_policies, list) else dict(raw_policies or {})
        self._observations = observations or ObservationRuntime()
        self._records: List[SettlementRecord] = []
        self._record_ids: Set[str] = set()
        self._known_event_ids: Set[str] = set()
        self._known_events: Dict[str, WorldEvent] = {}

    def register(self, plugin: SettlementPlugin) -> None:
        self._plugins.append(plugin)

    def observe_events(self, events: Sequence[WorldEvent]) -> None:
        """Register authoritative events that do not invoke scenario plugins."""
        self._known_event_ids.update(event.event_id for event in events)
        self._known_events.update({event.event_id: event for event in events})

    def record_sidecars(
        self,
        records: Sequence[SettlementRecord],
        context: SettlementContext,
    ) -> List[SettlementRecord]:
        """Persist capability reports with no world or victory authority."""
        accepted: List[SettlementRecord] = []
        for record in records:
            if record.kind != "capability_sidecar":
                raise ValueError("record_sidecars_requires_capability_sidecar")
            self._validate_record(record, context, self._known_event_ids)
            if record.settlement_id in self._record_ids:
                raise ValueError(
                    f"duplicate_settlement:{record.settlement_id}"
                )
            self._record_ids.add(record.settlement_id)
            self._records.append(record)
            accepted.append(record)
        return accepted

    def settle_tick(
        self,
        events: Sequence[WorldEvent],
        context: SettlementContext,
    ) -> List[SettlementRecord]:
        event_ids = {event.event_id for event in events}
        self._known_event_ids.update(event_ids)
        self._known_events.update({event.event_id: event for event in events})
        plugin_context = self._with_observation_facts(context)
        records: List[SettlementRecord] = []
        for plugin in self._plugins:
            produced = plugin.settle(events, plugin_context)
            for record in produced:
                self._validate_record(record, context, event_ids)
                if record.settlement_id in self._record_ids:
                    raise ValueError(
                        f"duplicate_settlement:{record.settlement_id}"
                    )
                self._record_ids.add(record.settlement_id)
                self._records.append(record)
                records.append(record)
        return records

    def finalize(self, context: SettlementContext) -> List[SettlementRecord]:
        plugin_context = self._with_observation_facts(context)
        records: List[SettlementRecord] = []
        for plugin in self._plugins:
            produced = plugin.finalize(plugin_context)
            for record in produced:
                self._validate_record(
                    record, context, self._known_event_ids
                )
                if record.settlement_id in self._record_ids:
                    raise ValueError(
                        f"duplicate_settlement:{record.settlement_id}"
                    )
                self._record_ids.add(record.settlement_id)
                self._records.append(record)
                records.append(record)
        return records

    def all_records(self) -> List[SettlementRecord]:
        return list(self._records)

    @property
    def observations(self) -> ObservationRuntime:
        return self._observations

    def rank_victory_records(
        self,
        records: Sequence[SettlementRecord],
        state: Any,
    ) -> List[VictoryStanding]:
        """Rank final settlements using the scene-declared victory policy."""
        latest: Dict[str, SettlementRecord] = {}
        expected_provider = str(self._victory_policy.get("provider_id") or "")
        for record in records:
            if not record.affects_victory:
                continue
            if expected_provider and record.authority.provider_id != expected_provider:
                continue
            for subject_id in record.subject_ids:
                latest[str(subject_id)] = record
        eliminated = {
            str(item.get("agent_id"))
            for item in (getattr(state, "eliminated", []) or [])
            if isinstance(item, dict) and item.get("agent_id")
        }
        value_key = str(self._victory_policy.get("value") or "")
        if not value_key:
            raise ValueError("scene victory policy requires value")
        order_raw = str(self._victory_policy.get("order") or "descending").lower()
        order = (
            "ascending"
            if order_raw in {"ascending", "asc", "lowest"}
            else "descending"
        )
        label = str(self._victory_policy.get("label") or value_key)
        candidates = []
        for agent_id in getattr(state, "agent_ids", []) or []:
            record = latest.get(str(agent_id))
            if record is None:
                raise ValueError(f"victory settlement missing for agent:{agent_id}")
            if value_key not in record.values:
                raise ValueError(
                    f"victory value {value_key} missing in {record.settlement_id}"
                )
            candidates.append(
                (str(agent_id), record, float(record.values[value_key]))
            )
        if order == "descending":
            candidates.sort(
                key=lambda item: (item[0] in eliminated, -item[2])
            )
        else:
            candidates.sort(
                key=lambda item: (item[0] in eliminated, item[2])
            )
        return [
            VictoryStanding(
                standing_id=f"standing:{record.settlement_id}",
                run_id=record.run_id,
                scenario_id=record.scenario_id,
                world_tick=record.world_tick,
                agent_id=agent_id,
                rank=index,
                value_key=value_key,
                value=value,
                label=label,
                order=order,
                settlement_ref=record.settlement_id,
                provider_id=record.authority.provider_id,
                authority=record.authority.mode,
                values=dict(record.values),
                eliminated=agent_id in eliminated,
            )
            for index, (agent_id, record, value) in enumerate(
                candidates, start=1
            )
        ]

    def _with_observation_facts(
        self,
        context: SettlementContext,
    ) -> SettlementContext:
        """Expose verified reality observations to scenario-owned settlement."""
        observed = [
            item.model_dump(mode="json")
            for item in self._observations.all()
            if item.run_id == context.run_id
            and item.scenario_id == context.scenario_id
            and item.world_tick <= context.world_tick
        ]
        if not observed:
            return context
        world_state = dict(context.world_state or {})
        existing = world_state.get("external_observations") or []
        existing_ids = {
            str(item.get("observation_id") or "")
            for item in existing
            if isinstance(item, dict)
        }
        merged = list(existing)
        for item in observed:
            if str(item.get("observation_id") or "") not in existing_ids:
                merged.append(item)
        world_state["external_observations"] = merged
        return SettlementContext(
            run_id=context.run_id,
            scenario_id=context.scenario_id,
            world_tick=context.world_tick,
            world_state=world_state,
        )

    def _validate_record(
        self,
        record: SettlementRecord,
        context: SettlementContext,
        current_event_ids: Optional[Set[str]],
    ) -> None:
        if record.run_id != context.run_id:
            raise ValueError("settlement_run_mismatch")
        if record.scenario_id != context.scenario_id:
            raise ValueError("settlement_scenario_mismatch")
        if record.world_tick != context.world_tick:
            raise ValueError("settlement_tick_mismatch")
        if current_event_ids is not None:
            unknown = set(record.source_event_refs) - current_event_ids
            if unknown:
                raise ValueError(
                    "settlement_unknown_event_refs:" + ",".join(sorted(unknown))
                )

        authority = record.authority
        policy = self._authority_policies.get(authority.provider_id)
        if self._authority_policies and policy is None:
            raise ValueError(
                "settlement_provider_not_declared:" + authority.provider_id
            )
        if policy:
            declared_mode = str(policy.get("authority") or policy.get("mode") or "")
            if declared_mode != authority.mode:
                raise ValueError(
                    "settlement_authority_mode_mismatch:"
                    f"{authority.provider_id}:{authority.mode}!={declared_mode}"
                )
            declared_rule = str(policy.get("rule_version") or "")
            if declared_rule and declared_rule != authority.rule_version:
                raise ValueError(
                    "settlement_rule_version_mismatch:"
                    f"{authority.provider_id}:{authority.rule_version}!={declared_rule}"
                )
        # 观测既可挂在 observation_refs，也可作为下单 price_evidence 挂在
        # evidence_refs（跨拍行情证据常见）。场景插件成交时会把 selected_ref
        # 记入 authority，必须与事件上已声明的证据/观测并集对齐，否则整拍
        # 结算被一刀切清空（见 run_84005e99 tick=22）。
        event_observation_refs = {
            ref
            for event in self._events_for_refs(record.source_event_refs)
            for ref in (
                list(event.observation_refs or [])
                + list(getattr(event, "evidence_refs", None) or [])
            )
            if ref
        }
        if not set(authority.observation_refs).issubset(event_observation_refs):
            raise ValueError("settlement_observation_not_linked_from_event")
        unknown_observations = (
            set(authority.observation_refs)
            - self._observations.verified_ids()
        )
        if unknown_observations:
            raise ValueError(
                "settlement_unverified_observations:"
                + ",".join(sorted(unknown_observations))
            )

    def _events_for_refs(self, refs: Sequence[str]) -> List[WorldEvent]:
        # SettlementRuntime only needs observation links for validation; keep
        # a compact immutable event index alongside the ID set.
        return [self._known_events[ref] for ref in refs if ref in self._known_events]


def load_scenario_settlement_plugin(scenario_dir: Path) -> List[SettlementPlugin]:
    """Load a trusted scenario plugin through the public settlement contract."""
    path = Path(scenario_dir) / "evaluation" / "plugin.py"
    if not path.is_file():
        return []
    module_name = f"aiworld_scenario_settlement_{abs(hash(path.resolve()))}"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"settlement_plugin_load_failed:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    factory = getattr(module, "create_plugin", None)
    if not callable(factory):
        raise ValueError(f"settlement plugin requires create_plugin(): {path}")
    created = factory()
    plugins = list(created) if isinstance(created, (list, tuple)) else [created]
    for plugin in plugins:
        if not getattr(plugin, "plugin_id", None) or not callable(
            getattr(plugin, "settle", None)
        ):
            raise TypeError(f"invalid settlement plugin: {path}")
    return plugins
