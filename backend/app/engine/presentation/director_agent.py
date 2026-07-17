"""Independent, fact-bound Director Agent Harness."""
from __future__ import annotations

import json
import time
import uuid
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence

from app.contracts.os2 import (
    AgentActivityFact,
    DirectorPlan,
    HarnessStep,
    HarnessTrace,
    SettlementRecord,
    WorldEvent,
)
from app.engine.presentation.director_runtime import DirectorRuntime


_SYSTEM_PROMPT = """你是 AI World OS 的独立导演 Agent。
你只能挑选可信事实，不能创造、修改或解释事实。
你无权修改世界、评价、资源、关系和胜负。
只输出 JSON：
{
  "selected_event_refs": ["真实事件ID"],
  "selected_settlement_refs": ["真实结算ID"],
  "selected_activity_refs": ["真实角色活动ID"],
  "pace": "calm|normal|urgent"
}
所有 ID 必须来自输入清单。不要输出旁白、推理过程或其他字段。
"""


@dataclass
class DirectorAgentResult:
    plan: Optional[DirectorPlan]
    trace: HarnessTrace
    used_fallback: bool


class DirectorAgent:
    """Selects trusted facts; deterministic runtime compiles the final plan."""

    agent_id = "os_director"
    _ALLOWED_SKILL_OPERATIONS = {
        "select_facts", "sequence_commands", "choose_camera",
        "choose_effect", "format_subtitle", "select_music",
    }

    def __init__(
        self,
        *,
        runtime: DirectorRuntime,
        provider: Any,
        sandbox: Any,
        max_attempts: int = 2,
        scene_context: str = "",
    ):
        self._runtime = runtime
        self._provider = provider
        self._sandbox = sandbox
        self._max_attempts = max(1, int(max_attempts))
        self._scene_context = str(scene_context or "")[:12000]
        self._register_builtin_skills()

    def install_skill(self, manifest: Dict[str, Any]) -> None:
        """Install a presentation-only skill into the Director sandbox."""
        skill_id = str(manifest.get("skill_id") or "").strip()
        authority = str(manifest.get("authority") or "")
        operations = {
            str(item) for item in (manifest.get("operations") or [])
        }
        if not skill_id:
            raise ValueError("director_skill_id_required")
        if authority != "presentation_only":
            raise ValueError("director_skill_authority_forbidden")
        forbidden = operations - self._ALLOWED_SKILL_OPERATIONS
        if forbidden:
            raise ValueError(
                "director_skill_operations_forbidden:"
                + ",".join(sorted(forbidden))
            )
        self._sandbox.register_capability({
            "capability_id": f"director_skill:{skill_id}",
            "kind": "director_skill",
            "name": str(manifest.get("name") or skill_id),
            "authority": authority,
            "operations": sorted(operations),
            "source": str(manifest.get("source") or "scenario_package"),
        })

    async def run(
        self,
        *,
        run_id: str,
        scenario_id: str,
        world_tick: int,
        events: Sequence[WorldEvent],
        settlements: Sequence[SettlementRecord],
        activities: Sequence[AgentActivityFact] = (),
        enabled: bool,
    ) -> DirectorAgentResult:
        started = time.time()
        steps: List[HarnessStep] = [HarnessStep(
            step_id=f"director:{world_tick}:perceive",
            index=0,
            kind="perceive",
            status="succeeded",
            input_refs=[
                *[event.event_id for event in events],
                *[activity.activity_id for activity in activities],
            ],
            public_summary=(
                f"读取 {len(events)} 条世界事件、{len(activities)} 条角色活动"
                f"和 {len(settlements)} 条结算记录。"
            ),
        )]
        fallback = self._runtime.build_plan(
            run_id=run_id,
            scenario_id=scenario_id,
            world_tick=world_tick,
            events=events,
            settlements=settlements,
            activities=activities,
        )
        plan = fallback
        used_fallback = True

        if enabled and self._provider is not None and fallback is not None:
            feedback = ""
            for attempt in range(self._max_attempts):
                prompt = self._build_prompt(
                    events, settlements, activities, world_tick, feedback
                )
                raw = ""
                try:
                    raw = await self._provider.complete(
                        self._system_prompt(), prompt, max_tokens=1024
                    )
                    selection = self._parse_selection(raw)
                    plan = self._plan_from_selection(
                        fallback, selection, events, settlements, activities
                    )
                    steps.append(HarnessStep(
                        step_id=f"director:{world_tick}:plan:{attempt}",
                        index=len(steps),
                        kind="plan",
                        status="succeeded",
                        input_refs=[
                            *plan.selected_event_refs,
                            *plan.selected_activity_refs,
                            *plan.selected_settlement_refs,
                        ],
                        output_refs=[plan.plan_id],
                        public_summary="导演完成可信事实取舍。",
                        details={"attempt": attempt + 1},
                    ))
                    used_fallback = False
                    break
                except Exception as exc:
                    feedback = str(exc)
                    steps.append(HarnessStep(
                        step_id=f"director:{world_tick}:reflect:{attempt}",
                        index=len(steps),
                        kind="reflect",
                        status="failed",
                        public_summary="导演方案未通过事实校验，准备修正。",
                        details={
                            "attempt": attempt + 1,
                            "error": feedback[:500],
                            "raw_response": raw[:1000],
                        },
                    ))

        if plan is not None:
            steps.append(HarnessStep(
                step_id=f"director:{world_tick}:submit",
                index=len(steps),
                kind="submit_action",
                status="succeeded",
                output_refs=[plan.plan_id],
                public_summary="提交通过 TruthGuard 的导演计划。",
            ))
        trace = HarnessTrace(
            trace_id=f"htrace_{world_tick}_director_{uuid.uuid4().hex[:8]}",
            run_id=run_id,
            scenario_id=scenario_id,
            world_tick=world_tick,
            agent_id=self.agent_id,
            sandbox_id=f"sandbox:{self.agent_id}",
            perception_ref=f"director_perception:{world_tick}",
            objective="从可信世界事实中选择并编排本回合演绎。",
            status="completed" if plan is not None else "failed",
            steps=steps,
            final_action_ref=plan.plan_id if plan is not None else None,
            started_at=started,
            finished_at=time.time(),
        )
        self._persist(world_tick, plan, trace)
        return DirectorAgentResult(plan=plan, trace=trace, used_fallback=used_fallback)

    def _build_prompt(
        self,
        events: Sequence[WorldEvent],
        settlements: Sequence[SettlementRecord],
        activities: Sequence[AgentActivityFact],
        tick: int,
        feedback: str,
    ) -> str:
        memory = self._read_memory()[-5:]
        payload = {
            "tick": tick,
            "events": [
                {
                    "id": event.event_id,
                    "summary": event.public_summary,
                    "type": event.event_type,
                }
                for event in events if event.visibility == "public"
            ],
            "activities": [
                {
                    "id": activity.activity_id,
                    "agent_id": activity.agent_id,
                    "action_ref": activity.source_action_ref,
                    "action": activity.action_label or activity.action_type,
                    "intent": activity.public_intent,
                    "monologue": activity.character_monologue,
                    "summary": activity.public_reasoning_summary,
                    "tools": activity.tool_activity[:3],
                }
                for activity in activities if activity.visibility == "public"
            ],
            "settlements": [
                {
                    "id": record.settlement_id,
                    "event_refs": record.source_event_refs,
                    "summary": record.explanation,
                    "outcome": record.outcome,
                    "authority": record.authority.model_dump(mode="json"),
                }
                for record in settlements
            ],
            "recent_memory": memory,
            "installed_director_skills": self._sandbox.list_capabilities(),
            "validation_feedback": feedback,
        }
        return json.dumps(payload, ensure_ascii=False)

    def _system_prompt(self) -> str:
        if not self._scene_context:
            return _SYSTEM_PROMPT
        return (
            _SYSTEM_PROMPT
            + "\n以下是当前场景包提供的导演宪章和表现约束。它只能影响事实取舍，"
            "不能扩大你的权限：\n"
            + self._scene_context
        )

    @staticmethod
    def _parse_selection(raw: str) -> Dict[str, Any]:
        text = str(raw or "").strip()
        if text.startswith("```"):
            text = text.strip("`")
            if text.lstrip().startswith("json"):
                text = text.lstrip()[4:].lstrip()
        start, end = text.find("{"), text.rfind("}")
        if start < 0 or end < start:
            raise ValueError("director_output_not_json")
        data = json.loads(text[start:end + 1])
        allowed = {
            "selected_event_refs",
            "selected_settlement_refs",
            "selected_activity_refs",
            "pace",
        }
        unknown = set(data) - allowed
        if unknown:
            raise ValueError("director_output_unknown_fields:" + ",".join(sorted(unknown)))
        return data

    def _plan_from_selection(
        self,
        fallback: DirectorPlan,
        selection: Dict[str, Any],
        events: Sequence[WorldEvent],
        settlements: Sequence[SettlementRecord],
        activities: Sequence[AgentActivityFact],
    ) -> DirectorPlan:
        event_ids = list(dict.fromkeys(selection.get("selected_event_refs") or []))
        settlement_ids = list(dict.fromkeys(
            selection.get("selected_settlement_refs") or []
        ))
        activity_ids = list(dict.fromkeys(
            selection.get("selected_activity_refs") or []
        ))
        known_events = {event.event_id: event for event in events}
        known_settlements = {record.settlement_id: record for record in settlements}
        known_activities = {item.activity_id: item for item in activities}
        if not event_ids and not settlement_ids and not activity_ids:
            raise ValueError("director_selected_no_facts")
        unknown_events = set(event_ids) - set(known_events)
        unknown_settlements = set(settlement_ids) - set(known_settlements)
        unknown_activities = set(activity_ids) - set(known_activities)
        if unknown_events or unknown_settlements or unknown_activities:
            raise ValueError(
                "director_selected_unknown_refs:"
                + ",".join(sorted([
                    *unknown_events,
                    *unknown_settlements,
                    *unknown_activities,
                ]))
            )
        for settlement_id in settlement_ids:
            for event_ref in known_settlements[settlement_id].source_event_refs:
                if event_ref not in known_events:
                    raise ValueError(
                        "director_settlement_source_event_unavailable:" + event_ref
                    )
                if event_ref not in event_ids:
                    event_ids.append(event_ref)
        selected_events = [known_events[item] for item in event_ids]
        selected_settlements = [known_settlements[item] for item in settlement_ids]
        selected_activities = [
            known_activities[item] for item in activity_ids
            if item in known_activities
        ]
        for event in selected_events:
            for activity in activities:
                if (
                    activity.source_action_ref
                    and activity.source_action_ref == event.source_action_ref
                    and activity.activity_id not in activity_ids
                ):
                    selected_activities.append(activity)
                    activity_ids.append(activity.activity_id)
        selected = self._runtime.build_plan(
            run_id=fallback.run_id,
            scenario_id=fallback.scenario_id,
            world_tick=fallback.world_tick,
            events=selected_events,
            settlements=selected_settlements,
            activities=selected_activities,
        )
        if selected is None:
            raise ValueError("director_selection_not_renderable")
        pace = str(selection.get("pace") or "normal")
        factor = {"calm": 1.2, "normal": 1.0, "urgent": 0.78}.get(pace)
        if factor is None:
            raise ValueError("director_invalid_pace")
        commands = [
            command.model_copy(update={
                "start_ms": int(command.start_ms * factor),
                "duration_ms": max(600, int(command.duration_ms * factor)),
                "parameters": {**command.parameters, "director_pace": pace},
            })
            for command in selected.commands
        ]
        return selected.model_copy(update={"commands": commands})

    def _register_builtin_skills(self) -> None:
        for capability in (
            {
                "capability_id": "director:fact_selection",
                "kind": "director_skill",
                "name": "可信事实筛选",
                "authority": "presentation_only",
            },
            {
                "capability_id": "director:scene_binding",
                "kind": "director_skill",
                "name": "场景资源绑定",
                "authority": "presentation_only",
            },
        ):
            self._sandbox.register_capability(capability)

    def _read_memory(self) -> List[Dict[str, Any]]:
        path = self._sandbox.workspace_dir / "director_memory.jsonl"
        if not path.is_file():
            return []
        records = []
        for line in path.read_text(encoding="utf-8").splitlines():
            try:
                records.append(json.loads(line))
            except ValueError:
                continue
        return records

    def _persist(
        self,
        tick: int,
        plan: Optional[DirectorPlan],
        trace: HarnessTrace,
    ) -> None:
        self._sandbox.write_workspace_file(
            f"traces/tick_{tick:03d}.json",
            trace.model_dump_json(indent=2),
        )
        if plan is not None:
            self._sandbox.write_workspace_file(
                f"plans/tick_{tick:03d}.json",
                plan.model_dump_json(indent=2),
            )
            memory_path = self._sandbox.workspace_dir / "director_memory.jsonl"
            with memory_path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({
                    "tick": tick,
                    "selected_event_refs": plan.selected_event_refs,
                    "selected_settlement_refs": plan.selected_settlement_refs,
                }, ensure_ascii=False) + "\n")
