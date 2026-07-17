"""Scenario-neutral director runtime for the OS 2.0 fact chain."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Sequence

from app.contracts.os2 import (
    AgentActivityFact,
    DirectorPlan,
    RenderCommand,
    SettlementRecord,
    WorldEvent,
)
from app.engine.presentation.audience_guard import AudienceTextGuard


class DirectorRuntime:
    """Compile immutable world events into a verifiable presentation plan."""

    director_id = "ai_world.director_runtime.v2"

    def __init__(
        self,
        render_bindings: Optional[Dict[str, Any]] = None,
        render_config: Optional[Any] = None,
        terminology: Optional[Dict[str, str]] = None,
    ):
        self._bindings = dict(render_bindings or {})
        if hasattr(render_config, "model_dump"):
            render_config = render_config.model_dump(mode="json")
        self._render = dict(render_config or {})
        self._audience = AudienceTextGuard(terminology)
        self._terms = dict(terminology or {})

    def _binding(self, section: str, semantic_id: str) -> Optional[str]:
        values = self._bindings.get(section, {}) or {}
        return str(values.get(semantic_id) or "") or None

    @staticmethod
    def _is_presentation_silent(record: SettlementRecord) -> bool:
        """零变化账本快照不进入观众叙事（内部结算仍保留）。"""
        details = dict(getattr(record, "details", {}) or {})
        if details.get("silent") or details.get("presentation_silent"):
            return True
        return not str(getattr(record, "explanation", "") or "").strip()

    def _action_render(self, binding_id: Optional[str]) -> Dict[str, Any]:
        if not binding_id:
            return {}
        value = (self._render.get("actions", {}) or {}).get(binding_id, {})
        if hasattr(value, "model_dump"):
            value = value.model_dump(mode="json")
        return dict(value or {})

    def _append_render_layers(
        self,
        commands: List[RenderCommand],
        *,
        command_prefix: str,
        semantic_action: str,
        source_event_refs: List[str],
        source_settlement_refs: Optional[List[str]] = None,
        target_ids: Optional[List[str]] = None,
        render: Optional[Dict[str, Any]] = None,
        start_ms: int = 0,
        include_character: bool = False,
        parameters: Optional[Dict[str, Any]] = None,
        binding_id: Optional[str] = None,
    ) -> None:
        render = dict(render or {})
        targets = list(target_ids or [])
        common = {
            "source_event_refs": source_event_refs,
            "source_settlement_refs": list(source_settlement_refs or []),
            "target_ids": targets,
            "start_ms": start_ms,
        }
        if include_character and targets:
            commands.append(RenderCommand(
                command_id=f"{command_prefix}:character",
                command_type="character",
                semantic_action=semantic_action,
                binding_id=binding_id,
                parameters=dict(parameters or {}),
                duration_ms=int(render.get("duration_ms") or 1400),
                **common,
            ))
        for command_type, field in (
            ("camera", "camera"),
            ("effect", "effect"),
            ("sound", "sound"),
            ("music", "music"),
        ):
            semantic = str(render.get(field) or "")
            if not semantic or semantic == "none":
                continue
            commands.append(RenderCommand(
                command_id=f"{command_prefix}:{command_type}",
                command_type=command_type,
                semantic_action=semantic,
                parameters=dict(parameters or {}),
                duration_ms=(
                    int(render.get("duration_ms") or 1400)
                    if command_type in {"camera", "effect"} else 1
                ),
                **common,
            ))

    def build_plan(
        self,
        *,
        run_id: str,
        scenario_id: str,
        world_tick: int,
        events: Sequence[WorldEvent],
        settlements: Sequence[SettlementRecord] = (),
        activities: Sequence[AgentActivityFact] = (),
    ) -> Optional[DirectorPlan]:
        visible = [event for event in events if event.visibility == "public"]
        visible_activities = [
            activity for activity in activities
            if activity.visibility == "public"
        ]
        visible_settlements = [
            record for record in settlements
            if set(record.source_event_refs).issubset(
                {event.event_id for event in visible}
            )
            and not self._is_presentation_silent(record)
        ]
        if not visible and not visible_settlements and not visible_activities:
            return None

        selected_refs = [event.event_id for event in visible]
        selected_activity_refs = [
            activity.activity_id for activity in visible_activities
        ]
        commands: List[RenderCommand] = []
        summaries: List[str] = []
        activities_by_event: Dict[str, List[AgentActivityFact]] = {}
        activities_without_event: List[AgentActivityFact] = []
        for activity in visible_activities:
            if activity.source_action_ref:
                activities_by_event.setdefault(activity.source_action_ref, []).append(
                    activity
                )
            else:
                activities_without_event.append(activity)

        for index, activity in enumerate(activities_without_event):
            text = self._activity_text(activity)
            if not text:
                continue
            summaries.append(text)
            commands.append(RenderCommand(
                command_id=f"render:{world_tick}:activity:{index}",
                command_type="subtitle",
                semantic_action="show_agent_activity",
                source_activity_refs=[activity.activity_id],
                target_ids=[activity.agent_id],
                parameters={
                    "text": text,
                    "activity": activity.model_dump(mode="json"),
                },
                start_ms=index * 1400,
                duration_ms=max(1600, min(4600, len(text) * 90)),
            ))

        for index, event in enumerate(visible):
            summary = self._audience.clean(
                event.public_summary,
                fallback="本回合行动已经完成，世界已记录结果。",
            )
            if summary:
                summaries.append(summary)
            semantic_action = str(
                event.deltas.get("action_type") or event.event_type
            )
            targets = [
                item for item in [event.actor_id, *event.target_ids] if item
            ]
            binding_id = self._binding("actions", semantic_action)
            render = self._action_render(binding_id)
            event_start = index * 1800
            for activity_index, activity in enumerate(
                activities_by_event.get(event.source_action_ref or "", [])
            ):
                activity_text = self._activity_text(activity)
                if not activity_text:
                    continue
                summaries.append(activity_text)
                commands.append(RenderCommand(
                    command_id=(
                        f"render:{world_tick}:{index}:activity:{activity_index}"
                    ),
                    command_type="subtitle",
                    semantic_action="show_agent_activity",
                    source_event_refs=[event.event_id],
                    source_activity_refs=[activity.activity_id],
                    target_ids=[activity.agent_id],
                    parameters={
                        "text": activity_text,
                        "activity": activity.model_dump(mode="json"),
                    },
                    start_ms=event_start,
                    duration_ms=max(1600, min(4600, len(activity_text) * 90)),
                ))
            if targets:
                commands.append(RenderCommand(
                    command_id=f"render:{world_tick}:{index}:character",
                    command_type="character",
                    semantic_action=semantic_action,
                    source_event_refs=[event.event_id],
                    target_ids=targets,
                    binding_id=binding_id,
                    parameters={
                        "event_type": event.event_type,
                        "outcome": event.deltas.get("outcome", ""),
                    },
                    start_ms=event_start,
                    duration_ms=1400,
                ))
            object_id = str(event.deltas.get("target_object_id") or "")
            if object_id:
                commands.append(RenderCommand(
                    command_id=f"render:{world_tick}:{index}:object",
                    command_type="object",
                    semantic_action="focus_world_object",
                    source_event_refs=[event.event_id],
                    target_ids=[
                        item for item in (event.actor_id, object_id) if item
                    ],
                    binding_id=self._binding("objects", object_id),
                    parameters={"outcome": event.deltas.get("outcome", "")},
                    start_ms=event_start,
                    duration_ms=1400,
                ))
            self._append_render_layers(
                commands,
                command_prefix=f"render:{world_tick}:{index}",
                semantic_action=semantic_action,
                source_event_refs=[event.event_id],
                target_ids=targets,
                render=render,
                start_ms=event_start,
                parameters={"outcome": event.deltas.get("outcome", "")},
            )
            if summary:
                commands.append(RenderCommand(
                    command_id=f"render:{world_tick}:{index}:subtitle",
                    command_type="subtitle",
                    semantic_action="show_world_fact",
                    source_event_refs=[event.event_id],
                    target_ids=targets,
                    parameters={"text": summary},
                    start_ms=event_start,
                    duration_ms=max(1400, min(4200, len(summary) * 90)),
                ))

        settlement_refs: List[str] = []
        event_order = {event.event_id: index for index, event in enumerate(visible)}
        for offset, record in enumerate(visible_settlements, start=len(visible)):
            settlement_refs.append(record.settlement_id)
            summary = self._audience.clean(
                record.explanation,
                fallback="本回合结算已经完成。",
            )
            if summary:
                summaries.append(summary)
            outcome_binding = self._binding("outcomes", record.outcome)
            outcome_render = self._action_render(outcome_binding)
            settlement_start = (
                max(
                    [event_order.get(ref, 0) for ref in record.source_event_refs]
                    or [offset]
                ) * 1800 + 1450
            )
            self._append_render_layers(
                commands,
                command_prefix=f"render:{world_tick}:{offset}:outcome",
                semantic_action=record.outcome,
                source_event_refs=list(record.source_event_refs),
                source_settlement_refs=[record.settlement_id],
                target_ids=list(record.subject_ids),
                render=outcome_render,
                start_ms=settlement_start,
                include_character=True,
                parameters={
                    "outcome": record.outcome,
                    "values": dict(record.values),
                },
                binding_id=outcome_binding,
            )
            commands.append(RenderCommand(
                command_id=f"render:{world_tick}:{offset}:settlement",
                command_type="ui",
                semantic_action="show_settlement_result",
                source_event_refs=list(record.source_event_refs),
                source_settlement_refs=[record.settlement_id],
                target_ids=list(record.subject_ids),
                binding_id=outcome_binding,
                parameters={
                    "text": summary,
                    "outcome": record.outcome,
                    "values": dict(record.values),
                    "rule_refs": list(record.rule_refs),
                },
                start_ms=settlement_start,
                duration_ms=max(1600, min(4800, len(summary) * 90)),
            ))
        narrative = " ".join(summaries) or (
            f"第 {world_tick} 回合产生了 {len(visible)} 条公开世界事件。"
        )
        plan = DirectorPlan(
            plan_id=f"director_plan:{world_tick}",
            run_id=run_id,
            scenario_id=scenario_id,
            world_tick=world_tick,
            director_id=self.director_id,
            selected_event_refs=selected_refs,
            selected_settlement_refs=settlement_refs,
            selected_activity_refs=selected_activity_refs,
            narrative_summary=narrative,
            commands=commands,
            truth_guard_status="passed",
        )
        self.validate_plan(plan, visible, visible_settlements, visible_activities)
        return plan

    def _activity_text(self, activity: AgentActivityFact) -> str:
        # 观众活动字幕只播角色独白；研报正文/MCP 套话留给卡片与结算字幕。
        actor = self._label(activity.agent_id)
        monologue = self._audience.clean(activity.character_monologue)
        if monologue:
            return self._audience.clean(f"{actor}说：{monologue}", fallback="")
        fallback = activity.public_intent or activity.action_label
        if fallback:
            return self._audience.clean(
                f"{actor}准备执行：{self._label(fallback)}",
                fallback="",
            )
        return ""

    def _label(self, value: Any) -> str:
        raw = str(value or "")
        return self._terms.get(raw, raw)

    @staticmethod
    def validate_plan(
        plan: DirectorPlan,
        events: Sequence[WorldEvent],
        settlements: Sequence[SettlementRecord] = (),
        activities: Sequence[AgentActivityFact] = (),
    ) -> None:
        known = {event.event_id for event in events}
        unknown = set(plan.selected_event_refs) - known
        if unknown:
            raise ValueError(
                "director_plan_unknown_event_refs:" + ",".join(sorted(unknown))
            )
        known_settlements = {record.settlement_id for record in settlements}
        unknown_settlements = (
            set(plan.selected_settlement_refs) - known_settlements
        )
        if unknown_settlements:
            raise ValueError(
                "director_plan_unknown_settlement_refs:"
                + ",".join(sorted(unknown_settlements))
            )
        known_activities = {item.activity_id for item in activities}
        unknown_activities = set(plan.selected_activity_refs) - known_activities
        if unknown_activities:
            raise ValueError(
                "director_plan_unknown_activity_refs:"
                + ",".join(sorted(unknown_activities))
            )
        if plan.truth_guard_status != "passed":
            raise ValueError("director_plan_truth_guard_not_passed")

    def compile_segments(self, plan: DirectorPlan) -> list:
        """Adapt OS2 render commands to the existing buffered timeline."""
        from app.engine.presentation_buffer import PresentationSegment

        return [
            PresentationSegment(
                kind="render_command",
                # Camera/effect/audio/character commands start work immediately;
                # only narrative/wait commands own timeline time. This preserves
                # parallel commands without making the legacy sequential buffer
                # play every visual layer back-to-back.
                duration_ms=(
                    max(1, int(command.duration_ms or 1))
                    if command.command_type in {"subtitle", "ui", "wait"}
                    else 1
                ),
                payload={
                    **command.model_dump(
                        mode="json",
                        exclude={"parameters"},
                    ),
                    "parameters": self._audience.public_parameters(
                        command.command_type, command.parameters
                    ),
                },
            )
            for command in sorted(
                plan.commands,
                key=lambda item: (item.start_ms, item.command_id),
            )
        ]
