"""AgentLoopSession（Agent 循环会话）：单 tick 内多步工具/代码试跑后再提交 ActionPack。"""
from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.agent_os.loop_step import (
    compact_tool_output,
    format_step_results_for_prompt,
    is_continue_step,
    is_suspend_step,
    tool_result_to_dict,
)
from app.agent_os.workspace_ops import apply_workspace_writes
from app.core.interfaces import ActionPack, AgentBrief, AgentLog, ToolRunResult
from app.core.redaction import redact_credentials
from app.contracts.os2 import HarnessResearchEvent, HarnessStep, HarnessTrace
from app.engine.agent_runtime.runtime import AgentContext

logger = logging.getLogger(__name__)


@dataclass
class AgentLoopSession:
    """单个 agent 在一个 tick 内的循环会话状态。"""

    agent_id: str
    tick: int
    max_steps: int
    steps: List[Dict[str, Any]] = field(default_factory=list)
    intra_tick_messages: List[Dict[str, str]] = field(default_factory=list)
    final_action: Optional[ActionPack] = None
    raw_final_response: str = ""
    total_tokens: int = 0
    started_at: float = field(default_factory=time.time)
    finished_at: Optional[float] = None
    productive_steps: int = 0
    wall_attempts: int = 0
    termination_reason: str = ""
    trace_status: str = "running"
    research_id: str = ""
    resumed_from_tick: Optional[int] = None
    resume_snapshot: Dict[str, Any] = field(default_factory=dict)
    suspension_summary: str = ""
    emit_research_events: bool = False

    @property
    def has_final_action(self) -> bool:
        return self.final_action is not None

    @property
    def step_count(self) -> int:
        return len(self.steps)

    def record_step(
        self,
        *,
        step_index: int,
        kind: str,
        raw_response: str,
        tool_result: Optional[Any] = None,
        workspace_written: Optional[List[str]] = None,
        started_at: Optional[float] = None,
        finished_at: Optional[float] = None,
    ) -> None:
        ended = float(finished_at or time.time())
        duration_ms = int(
            (tool_result_to_dict(tool_result).get("duration_ms") or 0)
        )
        began = float(started_at or (ended - duration_ms / 1000.0))
        self.steps.append({
            "step_index": step_index,
            "kind": kind,
            "raw_response": raw_response,
            "tool_result": tool_result_to_dict(tool_result),
            "workspace_written": list(workspace_written or []),
            "started_at": began,
            "finished_at": ended,
        })

    def build_user_message(self, base_user_message: str) -> str:
        suffix = format_step_results_for_prompt(self.steps)
        if not suffix:
            if self.resume_snapshot:
                return (
                    base_user_message
                    + "\n\n### 上一周期挂起的研究（继续推进，不要从头开始）\n"
                    + self._format_resume_snapshot()
                )
            return base_user_message
        # The full perception pack already exists in this intra-tick history.
        # Repeating it on every tool step both inflates tokens and buries the
        # newest observation under the original final-action contract.
        return "继续完成同一回合。不要重新陈述世界上下文。" + suffix

    def _format_resume_snapshot(self) -> str:
        snapshot = self.resume_snapshot or {}
        lines = []
        if snapshot.get("summary"):
            lines.append(f"  研究状态：{snapshot['summary']}")
        evidence_refs = list(snapshot.get("evidence_refs") or [])
        if evidence_refs:
            lines.append("  已有证据：" + "、".join(str(x) for x in evidence_refs[-12:]))
        for item in list(snapshot.get("recent_steps") or [])[-6:]:
            if not isinstance(item, dict):
                continue
            summary = str(item.get("summary") or "").strip()
            if summary:
                lines.append(f"  - {summary}")
        lines.append("  请基于这些进展继续研究；只有形成完整决策时才提交世界动作。")
        return "\n".join(lines)

    def to_resume_snapshot(self) -> Dict[str, Any]:
        """Compact, public-only state used to continue research next tick."""
        evidence_refs: List[str] = [
            str(item)
            for item in (self.resume_snapshot.get("evidence_refs") or [])
            if str(item)
        ]
        recent_steps: List[Dict[str, str]] = [
            {
                "kind": str(item.get("kind") or "observe"),
                "summary": str(item.get("summary") or "")[:500],
            }
            for item in (self.resume_snapshot.get("recent_steps") or [])
            if isinstance(item, dict) and str(item.get("summary") or "").strip()
        ]
        for item in self.steps:
            result = item.get("tool_result") or {}
            run_id = str(result.get("run_id") or "")
            if result.get("ok") and run_id and run_id not in evidence_refs:
                evidence_refs.append(run_id)
            outputs = result.get("outputs") or []
            summary = ""
            if outputs:
                first = outputs[0]
                summary = str(
                    first.get("summary") or first.get("claim") or first
                    if isinstance(first, dict) else first
                )
            if not summary and result.get("errors"):
                summary = "；".join(str(x) for x in result.get("errors")[:2])
            if summary:
                recent_steps.append({
                    "kind": str(item.get("kind") or "observe"),
                    "summary": redact_credentials(summary)[:500],
                })
        return {
            "research_id": self.research_id,
            "suspended_at_tick": self.tick,
            "summary": self.suspension_summary or "研究尚未完成，等待下一周期继续。",
            "evidence_refs": evidence_refs[-24:],
            "recent_steps": recent_steps[-8:],
        }

    def to_harness_trace(
        self,
        *,
        run_id: str,
        scenario_id: str,
        sandbox_id: str,
        objective: str,
    ) -> HarnessTrace:
        """Convert the legacy loop session into the OS 2.0 trace contract."""
        trace_steps: List[HarnessStep] = []
        research_events: List[HarnessResearchEvent] = []
        trace_finished_at = self.finished_at or time.time()
        research_id = self.research_id or f"research:{self.agent_id}:{self.tick}"
        research_events.append(HarnessResearchEvent(
            event_id=f"{research_id}:tick:{self.tick}:start",
            research_id=research_id,
            run_id=run_id or "run_pending",
            scenario_id=scenario_id or "scenario_unknown",
            world_tick=self.tick,
            agent_id=self.agent_id,
            event_type=(
                "research_resumed" if self.resumed_from_tick is not None
                else "research_started"
            ),
            status="started",
            summary=(
                f"继续 T{self.resumed_from_tick} 挂起的研究"
                if self.resumed_from_tick is not None else "开始本周期研究"
            ),
            metadata={"resumed_from_tick": self.resumed_from_tick},
            occurred_at=self.started_at,
        ))
        for index, item in enumerate(self.steps):
            tool_result = item.get("tool_result") or {}
            outputs = tool_result.get("outputs") or []
            summary = ""
            if outputs:
                first = outputs[0]
                summary = redact_credentials(str(
                    first.get("summary") or first.get("claim") or first
                    if isinstance(first, dict) else first
                ))[:500]
            trace_steps.append(HarnessStep(
                step_id=f"{self.agent_id}:{self.tick}:step:{index}",
                index=index,
                kind=item.get("kind", "execute_tool"),
                status="succeeded" if tool_result.get("ok") else "failed",
                output_refs=[
                    str(tool_result.get("run_id"))
                ] if tool_result.get("run_id") else [],
                artifact_refs=list(item.get("workspace_written") or []),
                public_summary=summary,
                details={
                    "source": tool_result.get("source"),
                    "errors": [
                        redact_credentials(str(error))
                        for error in (tool_result.get("errors") or [])
                    ],
                    "raw_response_ref": (
                        f"agent://{self.agent_id}/harness/tick_{self.tick:03d}_"
                        f"step_{index + 1:03d}_response.txt"
                    ),
                },
                duration_ms=int(tool_result.get("duration_ms") or 0),
                started_at=float(item.get("started_at") or self.started_at),
                finished_at=float(item.get("finished_at") or trace_finished_at),
            ))
            kind = str(item.get("kind") or "execute_tool")
            ok = bool(tool_result.get("ok"))
            if kind == "discover_tool":
                event_type = "capability_discovered" if ok else "capability_discovery_failed"
            elif kind in {"write_code", "run_code"}:
                event_type = "research_code_completed" if ok else "research_code_failed"
            elif kind == "reflect":
                event_type = "research_reflected"
            else:
                event_type = "evidence_received" if ok else "evidence_rejected"
            run_ref = str(tool_result.get("run_id") or "")
            research_events.append(HarnessResearchEvent(
                event_id=f"{research_id}:tick:{self.tick}:event:{index}",
                research_id=research_id,
                run_id=run_id or "run_pending",
                scenario_id=scenario_id or "scenario_unknown",
                world_tick=self.tick,
                agent_id=self.agent_id,
                event_type=event_type,
                status="succeeded" if ok else "failed",
                summary=summary,
                evidence_refs=[run_ref] if ok and run_ref else [],
                tool_id=str(tool_result.get("tool_id") or ""),
                source=str(tool_result.get("source") or ""),
                metadata={"step_kind": kind},
                occurred_at=float(item.get("finished_at") or trace_finished_at),
            ))

        final_ref = None
        status = self.trace_status if self.trace_status != "running" else "failed"
        if self.final_action is not None:
            final_ref = f"action:{self.tick}:{self.agent_id}"
            trace_steps.append(HarnessStep(
                step_id=f"{self.agent_id}:{self.tick}:submit",
                index=len(trace_steps),
                kind="submit_action",
                status="succeeded",
                output_refs=[final_ref],
                public_summary=self.final_action.action_name or self.final_action.action_id,
            ))
            if self.trace_status == "running":
                status = "completed"
        terminal_type = (
            "research_suspended" if status == "suspended"
            else "research_completed" if final_ref
            else "research_interrupted"
        )
        terminal_status = (
            "suspended" if status == "suspended"
            else "completed" if final_ref
            else "failed"
        )
        research_events.append(HarnessResearchEvent(
            event_id=f"{research_id}:tick:{self.tick}:terminal",
            research_id=research_id,
            run_id=run_id or "run_pending",
            scenario_id=scenario_id or "scenario_unknown",
            world_tick=self.tick,
            agent_id=self.agent_id,
            event_type=terminal_type,
            status=terminal_status,
            summary=(
                self.suspension_summary
                if status == "suspended"
                else self.termination_reason
            ),
            metadata={"termination_reason": self.termination_reason},
            occurred_at=trace_finished_at,
        ))

        return HarnessTrace(
            trace_id=f"htrace_{self.tick}_{self.agent_id}_{uuid.uuid4().hex[:8]}",
            run_id=run_id or "run_pending",
            scenario_id=scenario_id or "scenario_unknown",
            world_tick=self.tick,
            agent_id=self.agent_id,
            sandbox_id=sandbox_id,
            perception_ref=f"perception:{self.tick}:{self.agent_id}",
            objective=objective or "Pursue the scenario goal.",
            status=status,
            termination_reason=self.termination_reason,
            steps=trace_steps,
            research_events=research_events if self.emit_research_events else [],
            final_action_ref=final_ref,
            budget={
                "max_steps": float(self.max_steps),
            },
            usage={
                "tokens": float(self.total_tokens),
                "productive_steps": float(self.productive_steps),
                "wall_attempts": float(self.wall_attempts),
            },
            started_at=self.started_at,
            finished_at=trace_finished_at,
        )


LoopExecutor = Callable[
    [ActionPack, int, Optional[List[str]]],
    Any,
]


class AgentLoopRunner:
    """驱动 AgentLoopSession：多轮 LLM → 中间步执行 → 最终 ActionPack。"""

    def __init__(
        self,
        *,
        config: Any,
        loop_context: Dict[str, Any],
    ):
        self._config = config
        self._ctx = loop_context
        self._tool_failure_counts: Dict[str, int] = {}
        self._failed_request_counts: Dict[str, int] = {}

    def _max_steps(self, runtime_mode: str) -> int:
        if str(runtime_mode).strip().lower() == "benchmark":
            return 1
        return max(1, int(getattr(self._config, "max_steps", 5)))

    def _is_suspendable(self) -> bool:
        return (
            str(getattr(self._config, "completion_mode", "require_action"))
            == "suspendable"
            and str(getattr(self._config, "on_budget_exhausted", "fallback"))
            == "suspend"
        )

    @staticmethod
    def _suspension_summary(parsed: Optional[Dict[str, Any]] = None) -> str:
        parsed = parsed or {}
        return str(
            parsed.get("public_reasoning_summary_text")
            or parsed.get("plan")
            or parsed.get("text")
            or "研究尚未完成，已保留证据和进度，下一周期继续。"
        )[:500]

    def _suspend_session(
        self,
        session: AgentLoopSession,
        *,
        parsed: Optional[Dict[str, Any]] = None,
        reason: str,
        tokens: int,
        productive_steps: int,
        wall_attempts: int,
    ) -> None:
        session.final_action = None
        session.raw_final_response = session.raw_final_response or ""
        session.total_tokens = tokens
        session.productive_steps = productive_steps
        session.wall_attempts = wall_attempts
        session.finished_at = time.time()
        session.trace_status = "suspended"
        session.termination_reason = reason
        session.suspension_summary = self._suspension_summary(parsed)

    async def run(
        self,
        *,
        agent_id: str,
        tick: int,
        ctx: AgentContext,
        brief: AgentBrief,
        system_prompt: str,
        base_user_message: str,
        build_action_from_parsed: Callable[..., ActionPack],
        parse_response: Callable[[str, str], Dict[str, Any]],
    ) -> Tuple[Optional[ActionPack], str, int, AgentLoopSession]:
        """返回 (action, last_raw_response, tokens, session)。"""
        self._active_brief = brief
        session = AgentLoopSession(
            agent_id=agent_id,
            tick=tick,
            max_steps=self._max_steps(self._ctx.get("runtime_mode", "")),
            emit_research_events=(
                str(
                    getattr(
                        self._config, "completion_mode", "require_action"
                    )
                ) == "suspendable"
            ),
        )
        resume_snapshot = dict(
            getattr(ctx, "pending_harness_research", None) or {}
        )
        if resume_snapshot:
            session.resume_snapshot = resume_snapshot
            session.research_id = str(
                resume_snapshot.get("research_id")
                or f"research:{agent_id}:{tick}"
            )
            prior_tick = resume_snapshot.get("suspended_at_tick")
            if prior_tick is not None:
                session.resumed_from_tick = int(prior_tick)
        else:
            session.research_id = f"research:{agent_id}:{tick}:{uuid.uuid4().hex[:8]}"
        timeout_sec = float(getattr(self._config, "session_timeout_sec", 60.0))
        deadline = time.monotonic() + timeout_sec
        last_raw = ""
        last_parsed: Dict[str, Any] = {}
        tokens = 0
        # max_steps counts productive work (tool/code/discover/final), not
        # harness_policy reflections. Policy nacks used to burn the budget and
        # abort multi-step research before the agent could finish.
        productive_steps = 0
        wall_attempts = 0
        max_wall_attempts = max(session.max_steps * 3, session.max_steps + 8)
        # 连续策略驳回封顶：同一提醒重复 3 次模型仍未产出合规中间步，说明
        # 继续驳回只会原地烧 LLM 调用（真实发生过：单 tick 35 次驳回）。
        # 达到上限后放行走强制终局——订单的真实性由结算层兜底校验，
        # 无证据或无权限的最终行动会在权威结算层被拒绝并给出理由。
        consecutive_policy_nacks = 0
        max_policy_nacks = 3
        policy_nack_capped = False

        while (
            productive_steps < session.max_steps
            and wall_attempts < max_wall_attempts
        ):
            wall_attempts += 1
            session.wall_attempts = wall_attempts
            remaining = deadline - time.monotonic()
            if remaining <= 0:
                logger.info(
                    f"[AgentLoop] {agent_id} tick={tick} 会话超时 {timeout_sec}s"
                )
                session.termination_reason = "session_timeout"
                session.trace_status = "budget_exhausted"
                break

            user_message = session.build_user_message(base_user_message)
            msgs = (
                ctx.history
                + session.intra_tick_messages
                + [{"role": "user", "content": user_message}]
            )

            _cq = brief.raw_context.get("challenge_question") if brief.raw_context else None
            _image_urls = (_cq or {}).get("image_data_urls") or []
            configured_step_timeout = float(
                getattr(self._config, "step_timeout_sec", 0.0) or 0.0
            )
            call_timeout = min(
                remaining,
                configured_step_timeout if configured_step_timeout > 0 else remaining,
            )
            try:
                if _image_urls:
                    raw_response = await asyncio.wait_for(
                        ctx.provider.complete_multimodal(
                            system_prompt, user_message, _image_urls,
                            history=ctx.history + session.intra_tick_messages,
                            max_tokens=4096,
                        ),
                        timeout=call_timeout,
                    )
                else:
                    raw_response = await asyncio.wait_for(
                        ctx.provider.complete_with_history(
                            system_prompt, msgs, max_tokens=4096,
                        ),
                        timeout=call_timeout,
                    )
            except asyncio.TimeoutError:
                session.termination_reason = "llm_step_timeout"
                session.trace_status = "budget_exhausted"
                logger.warning(
                    "[AgentLoop] %s tick=%s LLM step timeout %.2fs",
                    agent_id, tick, call_timeout,
                )
                break
            last_raw = raw_response or ""
            session.intra_tick_messages.append(
                {"role": "user", "content": user_message}
            )
            session.intra_tick_messages.append(
                {
                    "role": "assistant",
                    "content": AgentContext._compact_history_content(
                        last_raw, strip_private_reasoning=True,
                    ),
                }
            )

            usage = await ctx.provider.get_usage()
            tokens += sum(usage.values())

            parsed = parse_response(last_raw, agent_id)
            last_parsed = parsed
            session.raw_final_response = last_raw
            if is_suspend_step(parsed) and self._is_suspendable():
                self._suspend_session(
                    session,
                    parsed=parsed,
                    reason="research_suspended_by_agent",
                    tokens=tokens,
                    productive_steps=productive_steps,
                    wall_attempts=wall_attempts,
                )
                return None, last_raw, tokens, session
            self._apply_scene_harness_policy(parsed, brief, session)
            self._promote_declared_tool_action(parsed, brief, session)
            step_no = len(session.steps) + 1
            if self._requires_more_harness_work(parsed, brief, session):
                consecutive_policy_nacks += 1
                if consecutive_policy_nacks >= max_policy_nacks:
                    logger.info(
                        f"[AgentLoop] {agent_id} tick={tick} 连续 "
                        f"{consecutive_policy_nacks} 次策略驳回无进展，"
                        "放行降级提交（由结算层兜底校验）"
                    )
                    policy_nack_capped = True
                    session.termination_reason = "policy_nack_capped"
                    session.trace_status = "blocked"
                    break
                feedback = ToolRunResult(
                    run_id=f"policy_{tick}_{agent_id}_{step_no}",
                    tool_id="harness_policy",
                    owner_id=agent_id,
                    tick=tick,
                    ok=False,
                    outputs=[{
                        "summary": self._policy_feedback_summary(
                            session, brief, parsed,
                            attempt=consecutive_policy_nacks,
                        )
                    }],
                    errors=["minimum_harness_steps_not_reached"],
                    source="scenario_harness_policy",
                )
                session.record_step(
                    step_index=step_no,
                    kind="reflect",
                    raw_response=last_raw,
                    tool_result=feedback,
                )
                self._emit_step_diagnostic(
                    agent_id, tick, step_no,
                    self._build_policy_placeholder(agent_id), feedback, [],
                )
                continue
            consecutive_policy_nacks = 0
            if (
                is_continue_step(parsed)
                and (
                    productive_steps < session.max_steps - 1
                    or (
                        self._is_suspendable()
                        and productive_steps < session.max_steps
                    )
                )
            ):
                pack = build_action_from_parsed(
                    parsed, agent_id, brief, last_raw, partial=True,
                )
                step_started = time.time()
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    session.termination_reason = "session_timeout"
                    session.trace_status = "budget_exhausted"
                    break
                configured_step_timeout = float(
                    getattr(self._config, "step_timeout_sec", 0.0) or 0.0
                )
                tool_timeout = min(
                    remaining,
                    configured_step_timeout
                    if configured_step_timeout > 0 else remaining,
                )
                try:
                    written, tool_result = await asyncio.wait_for(
                        self._execute_continue_step_resilient(
                            pack, tick, step_no,
                        ),
                        timeout=tool_timeout,
                    )
                except asyncio.TimeoutError:
                    written = []
                    tool_result = ToolRunResult(
                        run_id=f"timeout_{tick}_{agent_id}_{step_no}",
                        tool_id=(pack.attached_tool_id or "harness_tool"),
                        owner_id=agent_id,
                        tick=tick,
                        ok=False,
                        errors=[f"harness_step_timeout>{tool_timeout:.2f}s"],
                        source="harness",
                        duration_ms=int(tool_timeout * 1000),
                    )
                self._record_loop_tool_result(tool_result)
                step_kind = self._classify_step_kind(pack, written)
                session.record_step(
                    step_index=step_no,
                    kind=step_kind,
                    raw_response=last_raw,
                    tool_result=tool_result,
                    workspace_written=written,
                    started_at=step_started,
                    finished_at=time.time(),
                )
                self._emit_step_diagnostic(
                    agent_id, tick, step_no, pack, tool_result, written,
                )
                productive_steps += 1
                session.productive_steps = productive_steps
                continue

            if is_continue_step(parsed) and not self._is_suspendable():
                logger.info(
                    "[AgentLoop] %s tick=%s 到达最后一步仍请求 continue，"
                    "转为预算耗尽终局动作",
                    agent_id,
                    tick,
                )
                productive_steps += await self._run_budget_exhausted_hook(
                    agent_id=agent_id,
                    tick=tick,
                    parsed=parsed,
                    brief=brief,
                    session=session,
                    productive_steps=productive_steps,
                )
                self._ensure_degraded_final_payload(parsed, brief, session)
                session.termination_reason = "continue_on_final_step_finalized"
                session.trace_status = "budget_exhausted"
            self._prepare_domain_final(parsed, brief, session)
            action = build_action_from_parsed(
                parsed, agent_id, brief, last_raw, partial=False,
            )
            # 同步回写到已构建的 ActionPack parameters
            if isinstance(parsed.get("parameters"), dict) and getattr(action, "parameters", None) is not None:
                for key, value in parsed["parameters"].items():
                    if key not in action.parameters or action.parameters[key] in (None, ""):
                        action.parameters[key] = value
            self._attach_harness_observations(action, session)
            session.final_action = action
            session.raw_final_response = last_raw
            session.total_tokens = tokens
            session.finished_at = time.time()
            session.trace_status = "completed"
            session.termination_reason = "final_action_submitted"
            session.productive_steps = productive_steps
            session.wall_attempts = wall_attempts
            return action, last_raw, tokens, session

        if (
            not self._is_suspendable()
            and session.final_action is None and session.steps and (
            policy_nack_capped or self._policy_satisfied(brief, session)
            )
        ):
            logger.info(
                f"[AgentLoop] {agent_id} tick={tick} 步数用尽，强制最终解析"
            )
            parsed = parse_response(last_raw, agent_id)
            self._backfill_parameters_from_session(
                parsed, session, parse_response, agent_id,
            )
            productive_steps += await self._run_budget_exhausted_hook(
                agent_id=agent_id,
                tick=tick,
                parsed=parsed,
                brief=brief,
                session=session,
                productive_steps=productive_steps,
            )
            self._ensure_degraded_final_payload(parsed, brief, session)
            self._prepare_domain_final(parsed, brief, session)
            action = build_action_from_parsed(
                parsed, agent_id, brief, last_raw, partial=False,
            )
            self._ensure_degraded_action_text(action)
            self._attach_harness_observations(action, session)
            session.final_action = action
            session.raw_final_response = last_raw

        if self._is_suspendable() and session.final_action is None:
            reason = session.termination_reason
            if not reason or reason in {"policy_nack_capped", "max_steps_exhausted"}:
                reason = "research_suspended_budget_exhausted"
            self._suspend_session(
                session,
                parsed=last_parsed,
                reason=reason,
                tokens=tokens,
                productive_steps=productive_steps,
                wall_attempts=wall_attempts,
            )

        if session.trace_status == "running":
            if productive_steps >= session.max_steps:
                session.trace_status = "budget_exhausted"
                session.termination_reason = "max_steps_exhausted"
            elif wall_attempts >= max_wall_attempts:
                session.trace_status = "budget_exhausted"
                session.termination_reason = "max_wall_attempts_exhausted"
            elif session.final_action is not None:
                session.trace_status = "completed"
                session.termination_reason = "final_action_submitted"
            else:
                session.trace_status = "failed"
                session.termination_reason = "no_final_action"

        session.total_tokens = tokens
        session.productive_steps = productive_steps
        session.wall_attempts = wall_attempts
        session.finished_at = time.time()
        return session.final_action, last_raw, tokens, session

    def _policy_feedback_summary(
        self,
        session: AgentLoopSession,
        brief: AgentBrief,
        parsed: Optional[Dict[str, Any]] = None,
        attempt: int = 1,
    ) -> str:
        """Return policy feedback without teaching the OS domain vocabulary."""
        adapter = self._ctx.get("harness_policy_adapter")
        feedback = getattr(adapter, "feedback_summary", None)
        if callable(feedback):
            try:
                return str(feedback(self, session, brief, parsed, attempt))
            except Exception as exc:
                self._report_policy_error("feedback_summary", exc, session)

        failures: List[str] = []
        for step in reversed(session.steps):
            result = step.get("tool_result") or {}
            if str(result.get("source") or "") == "scenario_harness_policy":
                continue
            errors = list(result.get("errors") or [])
            if errors:
                failures.append(
                    "上一步工具失败：" + "；".join(str(item) for item in errors[:3])
                )
            break
        capabilities = [
            item for item in (
                ((brief.raw_context or {}).get("agent_sandbox") or {}).get(
                    "capabilities"
                ) or []
            )
            if isinstance(item, dict)
            and str(item.get("status") or "") == "ready"
            and str((item.get("invocation") or {}).get("operation") or "")
            != "install_skill"
        ]
        example = ""
        if capabilities:
            capability = capabilities[0]
            tool_id = str(
                (capability.get("invocation") or {}).get("tool_id")
                or capability.get("capability_id") or ""
            )
            schema = capability.get("input_schema") or {}
            arguments = {
                name: f"<请填写 {name}>"
                for name in (schema.get("required") or [])
            }
            example = json.dumps({
                "agent_loop_step": "continue",
                "tool_request": {"tool_id": tool_id, "arguments": arguments},
            }, ensure_ascii=False)
        parts = list(failures)
        if attempt >= 2:
            parts.append(
                f"第 {attempt} 次提醒：同一路线连续失败时应切换可用工具。"
            )
        parts.append(
            "当前尚未满足 Harness 策略要求，请继续取得可验证结果，"
            "再提交最终行动。"
        )
        if example:
            parts.append("可直接调用：" + example)
        else:
            parts.append("请先发现并调用状态为 ready 的能力。")
        return " ".join(parts)
    @classmethod
    def _has_trusted_external(cls, brief: AgentBrief, session: AgentLoopSession) -> bool:
        trusted_sources = {"mcp", "external_reality", "verified_external"}
        return any(
            (item.get("tool_result") or {}).get("ok")
            and str((item.get("tool_result") or {}).get("source") or "")
            in trusted_sources
            for item in session.steps
        )

    def _policy_satisfied(
        self, brief: AgentBrief, session: AgentLoopSession,
    ) -> bool:
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        if not policy.get("require_verified_external_result"):
            return True
        adapter = self._ctx.get("harness_policy_adapter")
        policy_check = getattr(adapter, "policy_satisfied", None)
        if callable(policy_check):
            try:
                return bool(policy_check(self, brief, session))
            except Exception as exc:
                self._report_policy_error("policy_satisfied", exc, session)
                return False
        return self._has_trusted_external(brief, session)

    def _requires_more_harness_work(
        self,
        parsed: Dict[str, Any],
        brief: AgentBrief,
        session: AgentLoopSession,
    ) -> bool:
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        minimum = max(0, int(policy.get("minimum_steps_before_final", 0) or 0))
        completed = sum(
            1 for item in session.steps
            if item.get("kind") != "reflect"
            and (item.get("tool_result") or {}).get("ok")
        )
        if minimum > 0 and completed < minimum:
            return not is_continue_step(parsed)
        if policy.get("require_verified_external_result"):
            if not self._has_trusted_external(brief, session):
                return not is_continue_step(parsed)
        adapter = self._ctx.get("harness_policy_adapter")
        if adapter is not None:
            try:
                if adapter.requires_more_work(self, parsed, brief, session):
                    return not is_continue_step(parsed)
            except Exception as exc:
                self._report_policy_error("requires_more_work", exc, session)
        return False

    def _prepare_domain_final(
        self, parsed: Dict[str, Any], brief: AgentBrief,
        session: AgentLoopSession,
    ) -> None:
        adapter = self._ctx.get("harness_policy_adapter")
        if adapter is not None:
            try:
                adapter.prepare_final(self, parsed, brief, session)
            except Exception as exc:
                self._report_policy_error("prepare_final", exc, session)

    async def _run_budget_exhausted_hook(
        self, *, agent_id: str, tick: int, parsed: Dict[str, Any],
        brief: AgentBrief,
        session: AgentLoopSession, productive_steps: int,
    ) -> int:
        adapter = self._ctx.get("harness_policy_adapter")
        hook = getattr(adapter, "on_budget_exhausted", None)
        if not callable(hook):
            return 0
        try:
            added = await hook(
                self,
                agent_id=agent_id,
                tick=tick,
                parsed=parsed,
                brief=brief,
                session=session,
                productive_steps=productive_steps,
            )
        except Exception as exc:
            self._report_policy_error("on_budget_exhausted", exc, session)
            return 0
        return max(0, int(added or 0))

    def _ensure_degraded_final_payload(
        self,
        parsed: Dict[str, Any],
        brief: AgentBrief,
        session: AgentLoopSession,
    ) -> None:
        """封顶/强制终局时补齐空动作，避免 L3 空独白空正文。"""
        if is_continue_step(parsed) and not (
            parsed.get("action_id") or parsed.get("intent")
        ):
            parsed["agent_loop_step"] = "final"
            parsed["action_id"] = "wait_and_review"
            parsed["intent"] = "wait_and_review"
        action_id = str(parsed.get("action_id") or parsed.get("intent") or "").strip()
        if not action_id:
            parsed["action_id"] = "wait_and_review"
            parsed["intent"] = "wait_and_review"
            action_id = "wait_and_review"
        adapter = self._ctx.get("harness_policy_adapter")
        reason_hook = getattr(adapter, "degraded_final_reason", None)
        english = str(
            (brief.raw_context or {}).get("scenario_locale")
            or (brief.raw_context or {}).get("audience_language")
            or ""
        ).lower().startswith("en")
        reason = (
            "The execution budget for this cycle was exhausted, so the system "
            "submitted a safe fallback action and will continue next cycle."
            if english else
            "本轮执行预算已用尽，系统提交安全降级动作，等待下一轮继续。"
        )
        if callable(reason_hook):
            try:
                reason = str(reason_hook(self, brief, session))
            except Exception as exc:
                self._report_policy_error("degraded_final_reason", exc, session)
        if not str(parsed.get("text") or "").strip():
            parsed["text"] = reason
        if not str(parsed.get("character_monologue") or "").strip():
            parsed["character_monologue"] = reason[:40]
        if not str(parsed.get("plan") or "").strip():
            parsed["plan"] = reason

    @staticmethod
    def _ensure_degraded_action_text(action: ActionPack) -> None:
        reason = "本轮执行预算已用尽，系统提交安全降级动作。"
        if not str(getattr(action, "text", "") or "").strip():
            action.text = reason
        if not str(getattr(action, "character_monologue", "") or "").strip():
            action.character_monologue = reason[:40]
        if not str(getattr(action, "plan", "") or "").strip():
            action.plan = reason
        if not str(getattr(action, "action_id", "") or "").strip():
            action.action_id = "wait_and_review"


    @staticmethod
    def _backfill_parameters_from_session(
        parsed: Dict[str, Any],
        session: AgentLoopSession,
        parse_response: Callable[[str, str], Dict[str, Any]],
        agent_id: str,
    ) -> None:
        """强制终局时，用本回合早先响应里同一动作的结构化参数补齐缺失键。

        步数用尽的最后一份回复可能只剩自然语言而缺少结构化参数。
        只补缺失键、不覆盖已有值；只回捞与最终动作同 action/intent 的响应。
        """
        target_action = str(
            parsed.get("action_id") or parsed.get("intent") or ""
        ).strip()
        if not target_action:
            return
        merged = dict(parsed.get("parameters") or {})
        for step in reversed(session.steps):
            raw = str(step.get("raw_response") or "")
            if not raw:
                continue
            try:
                earlier = parse_response(raw, agent_id)
            except Exception:
                continue
            earlier_action = str(
                earlier.get("action_id") or earlier.get("intent") or ""
            ).strip()
            if earlier_action != target_action:
                continue
            earlier_params = earlier.get("parameters")
            if not isinstance(earlier_params, dict):
                continue
            for key, value in earlier_params.items():
                if key not in merged or merged[key] in (None, ""):
                    merged[key] = value
        if merged:
            parsed["parameters"] = merged


    @staticmethod
    def _build_policy_placeholder(agent_id: str) -> ActionPack:
        return ActionPack(
            agent_id=agent_id,
            action_id="harness_policy_feedback",
            parsed_ok=True,
        )

    @staticmethod
    def _apply_scene_harness_policy(
        parsed: Dict[str, Any],
        brief: AgentBrief,
        session: AgentLoopSession,
    ) -> None:
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        if session.steps or not policy.get("require_initial_capability_discovery"):
            return
        existing_request = parsed.get("tool_request") or {}
        if AgentLoopRunner._discovery_request(existing_request):
            return
        # 场景可要求首步先检查完整能力目录，不能用直接调用绕过发现。
        query = str(
            policy.get("discovery_query")
            or parsed.get("text")
            or parsed.get("plan")
            or "完成当前目标所需的外部能力"
        )
        capability_request: Dict[str, Any] = {
            "operation": "discover",
            "query": query,
            "max_results": int(policy.get("max_results", 8) or 8),
        }
        preferred = policy.get("preferred_tools")
        if isinstance(preferred, list) and preferred:
            capability_request["preferred_tools"] = list(preferred)
        parsed["agent_loop_step"] = "continue"
        parsed["tool_request"] = {
            "capability_request": capability_request,
        }

    @staticmethod
    def _promote_declared_tool_action(
        parsed: Dict[str, Any],
        brief: AgentBrief,
        session: AgentLoopSession,
    ) -> None:
        """Translate a scene-declared tool action into a Harness step.

        Models often express the correct intent and purpose without reproducing
        the transport envelope. The scene category is the authoritative signal;
        the OS supplies the generic capability-discovery envelope once.
        """
        if parsed.get("tool_request"):
            return
        action_id = str(parsed.get("action_id") or parsed.get("intent") or "")
        action_def = next(
            (
                item for item in (brief.available_actions or [])
                if isinstance(item, dict) and str(item.get("id") or "") == action_id
            ),
            None,
        )
        if not action_def or str(action_def.get("category") or "") != "tool_use":
            return
        query = str(
            parsed.get("text")
            or parsed.get("plan")
            or parsed.get("expected_effect")
            or action_def.get("description")
            or action_id
        )
        parsed["agent_loop_step"] = "continue"
        declared_tool = str(action_def.get("harness_tool_id") or "")
        if bool(action_def.get("harness_discovery_only")):
            parsed["tool_request"] = {
                "capability_request": {
                    "operation": "discover",
                    "query": query,
                    "max_results": 8,
                }
            }
        elif session.steps and declared_tool:
            parsed["tool_request"] = {
                "tool_id": declared_tool,
                "arguments": {"question": query, "purpose": query},
            }
        else:
            parsed["tool_request"] = {
                "capability_request": {
                    "operation": "discover",
                    "query": query,
                    "max_results": 8,
                }
            }

    def _attach_harness_observations(
        self,
        action: ActionPack,
        session: AgentLoopSession,
    ) -> None:
        """Carry successful tool facts into the committed world action."""
        observations = []
        refs = list(action.evidence_refs or [])
        for step in session.steps:
            result = step.get("tool_result") or {}
            if not result.get("ok") or not result.get("run_id"):
                continue
            ref = str(result["run_id"])
            if ref not in refs:
                refs.append(ref)
            observations.append(result)
        action.evidence_refs = refs
        if observations:
            action.parameters = dict(action.parameters or {})
            action.parameters["harness_observations"] = observations
        adapter = self._ctx.get("harness_policy_adapter")
        enrich = getattr(adapter, "enrich_final_action", None)
        if callable(enrich):
            try:
                enrich(self, action, session)
            except Exception as exc:
                self._report_policy_error("enrich_final_action", exc, session)

    def _report_policy_error(
        self, hook: str, exc: Exception, session: AgentLoopSession,
    ) -> None:
        """Isolate a trusted scenario extension failure from loop mechanics."""
        logger.exception(
            "[AgentLoop] scenario policy hook failed hook=%s agent=%s tick=%s",
            hook, session.agent_id, session.tick,
        )
        sink = self._ctx.get("diagnostic_sink")
        if callable(sink):
            sink({
                "event_type": "harness_policy_error",
                "hook": hook,
                "agent_id": session.agent_id,
                "tick": session.tick,
                "error_type": type(exc).__name__,
                "error": str(exc)[:500],
            })

    @staticmethod
    def _classify_step_kind(action: ActionPack, written: List[str]) -> str:
        request = action.tool_request if isinstance(action.tool_request, dict) else {}
        if AgentLoopRunner._discovery_request(request) is not None:
            return "discover_tool"
        if AgentLoopRunner._package_install_request(request) is not None:
            return "install_tool"
        if AgentLoopRunner._skill_install_request(request) is not None:
            return "install_tool"
        if AgentLoopRunner._inline_code_request(request) is not None:
            return "run_code"
        if request.get("workspace_run"):
            return "run_code"
        if written:
            return "write_code"
        return "execute_tool"

    async def _execute_continue_step(
        self,
        action: ActionPack,
        tick: int,
        step_index: int,
    ) -> Tuple[List[str], Optional[ToolRunResult]]:
        agent_id = action.agent_id
        written: List[str] = []
        tr = action.tool_request
        ws = self._workspaces.get(agent_id) if self._workspaces else None
        if ws and isinstance(tr, dict):
            sb = self._ctx.get("sandbox_cfg")
            max_bytes = int(getattr(sb, "code_workspace_max_bytes", 32768))
            max_files = int(getattr(sb, "code_workspace_max_files", 20))
            written, errors = apply_workspace_writes(
                agent_id, tr, ws,
                max_bytes=max_bytes, max_files=max_files,
            )
            if errors:
                logger.warning(
                    f"[AgentLoop] step={step_index} agent={agent_id} "
                    f"workspace errors: {errors}"
                )
        discovery = self._discovery_request(tr)
        if discovery is not None:
            broker = self._ctx.get("capability_broker")
            if broker is None:
                return written, ToolRunResult(
                    run_id=f"discover_{tick}_{agent_id}_{step_index}",
                    tool_id="capability_broker",
                    owner_id=agent_id,
                    tick=tick,
                    ok=False,
                    errors=["capability_broker_missing"],
                    source="capability_broker",
                )
            preferred = list(discovery.get("preferred_tools") or [])
            if not preferred:
                policy = dict(
                    (getattr(self, "_active_brief", None).raw_context or {}).get(
                        "harness_policy", {}
                    )
                    if getattr(self, "_active_brief", None) is not None
                    else {}
                )
                preferred = [
                    str(item).strip()
                    for item in (policy.get("preferred_tools") or [])
                    if str(item).strip()
                ]
            candidates = await broker.discover(
                discovery["query"],
                max_results=discovery["max_results"],
                preferred_tools=preferred,
            )
            registry = self._ctx.get("agent_sandboxes")
            sandbox = registry.get(agent_id) if registry is not None else None
            if sandbox is not None:
                for item in candidates:
                    payload = item.model_dump(mode="json")
                    # 发现 ≠ 可用：MCP/场景工具即刻可调用（ready）；skill 与
                    # python 包必须安装后才可用（discovered）。此前一律注册
                    # 导致"未安装的 skill 看起来已就绪"，agent 直接 import
                    # 未安装的库然后全程失败。
                    if item.kind in ("skill", "python_package"):
                        payload["status"] = "discovered"
                        payload["usage_note"] = (
                            "尚未安装——须先执行 skill_install/依赖安装并成功，"
                            "才能在代码中使用"
                        )
                    else:
                        payload["status"] = "ready"
                    sandbox.register_capability(payload)
            return written, ToolRunResult(
                run_id=f"discover_{tick}_{agent_id}_{step_index}",
                tool_id="capability_broker",
                owner_id=agent_id,
                tick=tick,
                ok=True,
                outputs=[
                    {
                        "summary": (
                            f"发现能力 {item.name}: {item.description}"
                        ),
                        "capability": item.model_dump(mode="json"),
                    }
                    for item in candidates
                ],
                source="capability_broker",
            )
        install = self._package_install_request(tr)
        if install is not None:
            registry = self._ctx.get("agent_sandboxes")
            sandbox = registry.get(agent_id) if registry is not None else None
            if sandbox is None:
                return written, ToolRunResult(
                    run_id=f"install_{tick}_{agent_id}_{step_index}",
                    tool_id="python_package_installer",
                    owner_id=agent_id,
                    tick=tick,
                    ok=False,
                    errors=["agent_process_sandbox_missing"],
                    source="agent_sandbox",
                )
            installed = await sandbox.install_python(install)
            return written, ToolRunResult(
                run_id=f"install_{tick}_{agent_id}_{step_index}",
                tool_id="python_package_installer",
                owner_id=agent_id,
                tick=tick,
                ok=installed.ok,
                outputs=[{
                    "summary": (
                        f"Python 依赖安装完成：{', '.join(install)}"
                        if installed.ok else "Python 依赖安装失败"
                    ),
                    "stdout": installed.stdout[-2000:],
                    "stderr": installed.stderr[-2000:],
                }],
                errors=installed.errors,
                duration_ms=installed.duration_ms,
                source="agent_sandbox",
            )
        skill_id = self._skill_install_request(tr)
        if skill_id is not None:
            return written, await self._install_skill(
                agent_id, tick, step_index, skill_id,
            )
        inline_code = self._inline_code_request(tr)
        if inline_code is not None:
            registry = self._ctx.get("agent_sandboxes")
            sandbox = registry.get(agent_id) if registry is not None else None
            if sandbox is None:
                return written, ToolRunResult(
                    run_id=f"inline_process_{tick}_{agent_id}_{step_index}",
                    tool_id=self._tool_request_id(tr) or "agent_python_runtime",
                    owner_id=agent_id,
                    tick=tick,
                    ok=False,
                    errors=["agent_process_sandbox_missing"],
                    source="agent_sandbox",
                )
            filename = f"inline_step_{tick}_{step_index}.py"
            try:
                sandbox.write_workspace_file(filename, inline_code)
                executed = await sandbox.run_python_file(filename)
            except Exception as exc:
                return written, ToolRunResult(
                    run_id=f"inline_process_{tick}_{agent_id}_{step_index}",
                    tool_id=self._tool_request_id(tr) or "agent_python_runtime",
                    owner_id=agent_id,
                    tick=tick,
                    ok=False,
                    errors=[str(exc)],
                    source="agent_sandbox",
                )
            summary = executed.stdout[-4000:] or "脚本执行完成，无标准输出。"
            if not executed.ok:
                error_text = "；".join(executed.errors or [])
                stderr = (executed.stderr or "").strip()[-800:]
                summary = (
                    f"脚本运行失败（{error_text or '未知错误'}）。"
                    "请根据错误修改代码、安装缺少依赖，或改用能力目录中已发现的外部数据工具。"
                )
                if stderr:
                    summary += f" 末尾错误信息：{stderr}"
            return written + [filename], ToolRunResult(
                run_id=f"inline_process_{tick}_{agent_id}_{step_index}",
                tool_id=self._tool_request_id(tr) or "agent_python_runtime",
                owner_id=agent_id,
                tick=tick,
                ok=executed.ok,
                outputs=[{
                    "summary": summary,
                    "stdout": executed.stdout[-4000:],
                    "stderr": executed.stderr[-2000:],
                    "workspace_file": filename,
                }],
                errors=executed.errors,
                duration_ms=executed.duration_ms,
                source="agent_sandbox",
            )
        process_run = self._process_run_request(tr)
        if process_run is not None:
            registry = self._ctx.get("agent_sandboxes")
            sandbox = registry.get(agent_id) if registry is not None else None
            if sandbox is None or ws is None:
                return written, ToolRunResult(
                    run_id=f"process_{tick}_{agent_id}_{step_index}",
                    tool_id="agent_python_runtime",
                    owner_id=agent_id,
                    tick=tick,
                    ok=False,
                    errors=["agent_process_sandbox_or_workspace_missing"],
                    source="agent_sandbox",
                )
            try:
                source = ws.read_code_file(process_run)
                sandbox.write_workspace_file(process_run, source)
                executed = await sandbox.run_python_file(process_run)
            except Exception as exc:
                return written, ToolRunResult(
                    run_id=f"process_{tick}_{agent_id}_{step_index}",
                    tool_id="agent_python_runtime",
                    owner_id=agent_id,
                    tick=tick,
                    ok=False,
                    errors=[str(exc)],
                    source="agent_sandbox",
                )
            summary = executed.stdout[-4000:] or "脚本执行完成，无标准输出。"
            if not executed.ok:
                error_text = "；".join(executed.errors or [])
                stderr = (executed.stderr or "").strip()[-800:]
                summary = (
                    f"脚本运行失败（{error_text or '未知错误'}）。"
                    "请根据错误修改代码、安装缺少依赖，或改用能力目录中已发现的外部数据工具。"
                )
                if stderr:
                    summary += f" 末尾错误信息：{stderr}"
            return written, ToolRunResult(
                run_id=f"process_{tick}_{agent_id}_{step_index}",
                tool_id="agent_python_runtime",
                owner_id=agent_id,
                tick=tick,
                ok=executed.ok,
                outputs=[{
                    "summary": summary,
                    "stdout": executed.stdout[-4000:],
                    "stderr": executed.stderr[-2000:],
                }],
                errors=executed.errors,
                duration_ms=executed.duration_ms,
                source="agent_sandbox",
            )
        dynamic_mcp = self._dynamic_mcp_request(tr)
        if dynamic_mcp is not None:
            from app.mcp.client import get_mcp_manager

            manager = get_mcp_manager()
            if manager is None:
                return written, ToolRunResult(
                    run_id=f"mcp_{tick}_{agent_id}_{step_index}",
                    tool_id=dynamic_mcp["tool_id"],
                    owner_id=agent_id,
                    tick=tick,
                    ok=False,
                    errors=["mcp_disabled"],
                    source="mcp",
                )
            called = await manager.call_tool(
                dynamic_mcp["server_id"],
                dynamic_mcp["tool_name"],
                dynamic_mcp["arguments"],
            )
            output = called.structured
            if output is None:
                output = {"summary": called.content_text}
            elif not isinstance(output, dict):
                output = {"summary": str(output)}
            return written, ToolRunResult(
                run_id=f"mcp_{tick}_{agent_id}_{step_index}",
                tool_id=dynamic_mcp["tool_id"],
                owner_id=agent_id,
                tick=tick,
                ok=called.ok,
                outputs=[output],
                errors=called.errors,
                duration_ms=called.duration_ms,
                mcp_server_id=dynamic_mcp["server_id"],
                mcp_tool_name=dynamic_mcp["tool_name"],
                source="mcp",
                failure_class=(
                    str(output.get("failure_class") or "") or None
                    if isinstance(output, dict) else None
                ),
                retryable=(
                    bool(output.get("retryable"))
                    if isinstance(output, dict) and "retryable" in output
                    else None
                ),
            )
        action_runtime = self._ctx.get("action_runtime")
        state = self._ctx.get("state")
        if action_runtime is None:
            return written, ToolRunResult(
                run_id=f"loop_{tick}_{agent_id}_{step_index}",
                tool_id=action.attached_tool_id or "unknown",
                owner_id=agent_id,
                tick=tick,
                ok=False,
                errors=["action_runtime_missing"],
                source="loop",
            )

        from app.mcp.tool_executor import resolve_tool_id

        tid = resolve_tool_id(action)
        tool_def = {}
        get_tool_def = self._ctx.get("get_tool_def")
        if tid and callable(get_tool_def):
            tool_def = get_tool_def(tid) or {}

        result = await action_runtime.execute_tool(
            action,
            tick,
            state,
            tool_def=tool_def,
            runtime_mode=str(self._ctx.get("runtime_mode") or "entertainment"),
        )
        return written, result

    async def _execute_continue_step_resilient(
        self,
        action: ActionPack,
        tick: int,
        step_index: int,
    ) -> Tuple[List[str], Optional[ToolRunResult]]:
        """Retry transient read-side failures and open a per-session circuit.

        Harness intermediate operations are observations; final world actions
        never pass through this method, so they are never replayed.
        """
        key = self._tool_reliability_key(action)
        fingerprint = self._tool_request_fingerprint(action)
        if self._failed_request_counts.get(fingerprint, 0) > 0:
            repeated = ToolRunResult(
                run_id=f"repeat_{tick}_{action.agent_id}_{step_index}",
                tool_id=key,
                owner_id=action.agent_id,
                tick=tick,
                ok=False,
                errors=[f"repeated_failed_method:{key}"],
                source="harness",
                failure_class="method_exhausted",
                retryable=False,
                request_fingerprint=fingerprint,
            )
            return [], await self._attach_tool_recovery(
                action, repeated, failure_class="method_exhausted",
                retryable=False,
            )
        threshold = max(
            1, int(getattr(
                self._config, "tool_circuit_breaker_threshold", 3,
            ) or 3),
        )
        if self._tool_failure_counts.get(key, 0) >= threshold:
            circuit = ToolRunResult(
                run_id=f"circuit_{tick}_{action.agent_id}_{step_index}",
                tool_id=key,
                owner_id=action.agent_id,
                tick=tick,
                ok=False,
                errors=[f"tool_circuit_open:{key}"],
                source="harness",
                failure_class="method_exhausted",
                retryable=False,
                request_fingerprint=fingerprint,
            )
            return [], await self._attach_tool_recovery(
                action, circuit, failure_class="method_exhausted",
                retryable=False,
            )

        attempts = max(
            1, int(getattr(self._config, "tool_max_attempts", 2) or 2),
        )
        backoff = max(
            0.0,
            float(getattr(
                self._config, "tool_retry_backoff_sec", 0.25,
            ) or 0.0),
        )
        last_written: List[str] = []
        last_result: Optional[ToolRunResult] = None
        for attempt in range(1, attempts + 1):
            last_written, last_result = await self._execute_continue_step(
                action, tick, step_index,
            )
            if last_result is None or last_result.ok:
                self._tool_failure_counts[key] = 0
                return last_written, last_result
            failure_class, retryable = self._classify_tool_failure(last_result)
            if not retryable:
                self._tool_failure_counts[key] = (
                    self._tool_failure_counts.get(key, 0) + 1
                )
                self._failed_request_counts[fingerprint] = (
                    self._failed_request_counts.get(fingerprint, 0) + 1
                )
                last_result.request_fingerprint = fingerprint
                return last_written, await self._attach_tool_recovery(
                    action, last_result,
                    failure_class=failure_class, retryable=False,
                )
            if attempt < attempts:
                sink = self._ctx.get("diagnostic_sink")
                if callable(sink):
                    sink({
                        "event_type": "agent_loop_tool_retry",
                        "tick": tick,
                        "agent_id": action.agent_id,
                        "step_index": step_index,
                        "tool_id": key,
                        "attempt": attempt,
                        "errors": list(last_result.errors or [])[:5],
                    })
                if backoff:
                    await asyncio.sleep(backoff * (2 ** (attempt - 1)))

        self._tool_failure_counts[key] = (
            self._tool_failure_counts.get(key, 0) + 1
        )
        if last_result is not None:
            self._failed_request_counts[fingerprint] = (
                self._failed_request_counts.get(fingerprint, 0) + 1
            )
            last_result.request_fingerprint = fingerprint
            failure_class, retryable = self._classify_tool_failure(last_result)
            last_result = await self._attach_tool_recovery(
                action, last_result,
                failure_class=failure_class, retryable=retryable,
            )
        return last_written, last_result

    @staticmethod
    def _tool_reliability_key(action: ActionPack) -> str:
        request = action.tool_request if isinstance(
            action.tool_request, dict,
        ) else {}
        nested = request.get("capability_request") or {}
        return str(
            action.attached_tool_id
            or request.get("tool_id")
            or nested.get("operation")
            or "harness_tool"
        )

    @staticmethod
    def _classify_tool_failure(
        result: ToolRunResult,
    ) -> Tuple[str, bool]:
        """Classify a failed observation without importing domain semantics."""
        if result.failure_class:
            return str(result.failure_class), bool(result.retryable)
        source = str(result.source or "").lower()
        blob = " ".join(str(item).lower() for item in result.errors or [])
        if any(marker in blob for marker in (
            "invalid_response_json", "expecting value", "jsondecode",
            "content_type", "empty_response", "response_contract",
        )):
            return "data_format", False
        if any(marker in blob for marker in (
            "url_not_allowed", "invalid argument", "invalid symbol",
            "required", "unknown_tool", "unsupported",
        )):
            return "invalid_request", False
        if any(marker in blob for marker in (
            "401", "403", "credential", "unauthorized", "forbidden",
            "permission", "api key",
        )):
            return "permission", False
        if any(marker in blob for marker in (
            "not found", "404", "no data", "empty dataset",
        )):
            return "data_unavailable", False
        transient_markers = (
            "timeout", "timed out", "readtimeout", "connect", "eof",
            "temporar", "rate_limit", "429", "502", "503", "504",
            "connection reset", "connection aborted",
        )
        retryable = (
            source in {
                "mcp", "capability_broker", "external_reality",
                "verified_external",
            }
            and any(marker in blob for marker in transient_markers)
        )
        return ("transient_transport", True) if retryable else (
            "tool_execution", False
        )

    @classmethod
    def _is_transient_tool_failure(cls, result: ToolRunResult) -> bool:
        """Backward-compatible predicate used by existing health tests."""
        return cls._classify_tool_failure(result)[1]

    @staticmethod
    def _tool_request_fingerprint(action: ActionPack) -> str:
        request = action.tool_request if isinstance(
            action.tool_request, dict,
        ) else {}
        canonical = json.dumps(
            {
                "tool": AgentLoopRunner._tool_reliability_key(action),
                "arguments": request.get("arguments") or {},
                "operation": (
                    (request.get("capability_request") or {}).get("operation")
                    if isinstance(request.get("capability_request"), dict)
                    else None
                ),
            },
            ensure_ascii=False,
            sort_keys=True,
            default=str,
        )
        return hashlib.sha256(canonical.encode("utf-8")).hexdigest()[:20]

    async def _attach_tool_recovery(
        self,
        action: ActionPack,
        result: ToolRunResult,
        *,
        failure_class: str,
        retryable: bool,
    ) -> ToolRunResult:
        """Expose executable alternatives so the next Agent step can re-plan."""
        result.failure_class = failure_class
        result.retryable = retryable
        failed_id = self._tool_reliability_key(action)
        alternatives: List[Dict[str, Any]] = []
        broker = self._ctx.get("capability_broker")
        if broker is not None:
            brief = getattr(self, "_active_brief", None)
            policy = dict(
                ((getattr(brief, "raw_context", None) or {}).get(
                    "harness_policy"
                ) or {})
            )
            preferred = [
                str(item) for item in policy.get("preferred_tools") or []
                if str(item)
            ]
            try:
                candidates = await broker.discover(
                    failed_id,
                    max_results=max(8, len(preferred)),
                    preferred_tools=preferred,
                )
                for candidate in candidates:
                    payload = (
                        candidate.model_dump(mode="json")
                        if hasattr(candidate, "model_dump") else dict(candidate)
                    )
                    capability_id = str(
                        payload.get("capability_id") or ""
                    )
                    invocation = payload.get("invocation") or {}
                    invocation_tool = str(invocation.get("tool_id") or "")
                    if failed_id in {capability_id, invocation_tool}:
                        continue
                    alternatives.append(payload)
                    if len(alternatives) >= 5:
                        break
            except Exception as exc:
                logger.info(
                    "[AgentLoop] alternative discovery skipped tool=%s: %s",
                    failed_id, exc,
                )
        result.alternative_tool_ids = [
            str(item.get("capability_id") or "")
            for item in alternatives if item.get("capability_id")
        ]
        result.outputs.append({
            "summary": (
                f"The method {failed_id} failed ({failure_class}). "
                "Do not repeat the identical request. "
                + (
                    "Retry only with changed parameters or switch method."
                    if retryable else
                    "Switch data source, tool, parameters, or narrow the research question."
                )
            ),
            "failure_class": failure_class,
            "retryable": retryable,
            "failed_method": failed_id,
            "alternative_capabilities": alternatives,
        })
        sink = self._ctx.get("diagnostic_sink")
        if callable(sink):
            sink({
                "event_type": "agent_loop_tool_recovery",
                "tick": result.tick,
                "agent_id": result.owner_id,
                "tool_id": failed_id,
                "failure_class": failure_class,
                "retryable": retryable,
                "alternative_tool_ids": result.alternative_tool_ids,
            })
        return result

    def _record_loop_tool_result(self, result: Optional[ToolRunResult]) -> None:
        """Mirror AgentLoop intermediate tool results into the unified L4 ledger."""
        if result is None:
            return
        action_runtime = self._ctx.get("action_runtime")
        runs = getattr(action_runtime, "_tool_runs", None)
        if not isinstance(runs, list):
            return
        run_id = str(getattr(result, "run_id", "") or "")
        if run_id and any(str(getattr(item, "run_id", "") or "") == run_id for item in runs):
            return
        runs.append(result)

    @staticmethod
    def _discovery_request(tool_request: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(tool_request, dict):
            return None
        nested = tool_request.get("capability_request")
        data = nested if isinstance(nested, dict) else tool_request
        operation = str(data.get("operation") or "").strip().lower()
        if operation != "discover" and not data.get("discover"):
            return None
        query = str(data.get("query") or data.get("discover") or "").strip()
        preferred = data.get("preferred_tools")
        out: Dict[str, Any] = {
            "query": query,
            "max_results": max(1, min(20, int(data.get("max_results") or 8))),
        }
        if isinstance(preferred, list) and preferred:
            out["preferred_tools"] = [
                str(item).strip() for item in preferred if str(item).strip()
            ]
        return out

    @staticmethod
    def _package_install_request(tool_request: Any) -> Optional[List[str]]:
        if not isinstance(tool_request, dict):
            return None
        raw = tool_request.get("package_install")
        data = raw if isinstance(raw, dict) else tool_request
        operation = str(data.get("operation") or "").strip().lower()
        if raw is None and operation != "install":
            return None
        packages = data.get("packages") if isinstance(data, dict) else None
        if isinstance(raw, list):
            packages = raw
        if isinstance(packages, str):
            packages = [packages]
        return [str(item) for item in (packages or [])]

    @staticmethod
    def _process_run_request(tool_request: Any) -> Optional[str]:
        if not isinstance(tool_request, dict):
            return None
        mode = str(tool_request.get("execution_mode") or "").strip().lower()
        path = tool_request.get("workspace_run")
        if mode != "agent_process" or not path:
            return None
        return str(path)

    @staticmethod
    def _skill_install_request(tool_request: Any) -> Optional[str]:
        """解析"安装 skill"请求：{skill_install:{skill_id}} 或 {operation:install_skill, skill_id}。"""
        if not isinstance(tool_request, dict):
            return None
        raw = tool_request.get("skill_install")
        data = raw if isinstance(raw, dict) else tool_request
        operation = str(data.get("operation") or "").strip().lower()
        if raw is None and operation != "install_skill":
            return None
        skill_id = str(
            data.get("skill_id")
            or (raw if isinstance(raw, str) else "")
            or ""
        ).strip()
        return skill_id or None

    async def _install_skill(
        self, agent_id: str, tick: int, step_index: int, skill_id: str,
    ) -> ToolRunResult:
        """安装一个 skill：装依赖 + 写起始代码 + 注册能力 + 回流说明书。"""
        from app.agent_os.skills import get_skill_registry

        run_id = f"skill_{tick}_{agent_id}_{step_index}"
        skill = get_skill_registry().index().get(skill_id)
        if skill is None:
            return ToolRunResult(
                run_id=run_id, tool_id=f"skill:{skill_id}", owner_id=agent_id,
                tick=tick, ok=False, errors=[f"unknown_skill:{skill_id}"],
                source="skill",
            )
        registry = self._ctx.get("agent_sandboxes")
        sandbox = registry.get(agent_id) if registry is not None else None
        if sandbox is None:
            return ToolRunResult(
                run_id=run_id, tool_id=f"skill:{skill_id}", owner_id=agent_id,
                tick=tick, ok=False, errors=["agent_process_sandbox_missing"],
                source="skill",
            )
        errors: List[str] = []
        if skill.python_packages:
            installed = await sandbox.install_python(list(skill.python_packages))
            if not installed.ok:
                errors.extend(installed.errors)
        written_files: List[str] = []
        for path, content in (skill.files or {}).items():
            try:
                sandbox.write_workspace_file(str(path), str(content))
                written_files.append(str(path))
            except Exception as exc:  # noqa: BLE001
                errors.append(f"skill_file_write_failed:{path}:{exc}")
        sandbox.register_capability({
            "capability_id": f"skill:{skill.skill_id}",
            "kind": "skill",
            "name": skill.name,
            "source": "skill",
            "files": written_files,
            # 依赖装失败时如实标注，agent 不会误以为库已可 import。
            "status": "installed" if not errors else "install_failed",
        })
        summary = (
            f"已安装 skill「{skill.name}」，工作区新增文件：{written_files}。\n"
            f"{skill.instructions}"
        )
        return ToolRunResult(
            run_id=run_id, tool_id=f"skill:{skill.skill_id}", owner_id=agent_id,
            tick=tick, ok=not errors,
            outputs=[{
                "summary": summary,
                "installed_files": written_files,
                "capability": {
                    "capability_id": f"skill:{skill.skill_id}",
                    "name": skill.name,
                },
            }],
            errors=errors, source="skill",
        )

    @staticmethod
    def _inline_code_request(tool_request: Any) -> Optional[str]:
        if not isinstance(tool_request, dict):
            return None
        arguments = (
            tool_request.get("arguments")
            if isinstance(tool_request.get("arguments"), dict)
            else {}
        )
        code = tool_request.get("code") or arguments.get("code")
        if not isinstance(code, str):
            return None
        stripped = code.strip()
        return stripped or None

    @staticmethod
    def _tool_request_id(tool_request: Any) -> Optional[str]:
        if not isinstance(tool_request, dict):
            return None
        arguments = (
            tool_request.get("arguments")
            if isinstance(tool_request.get("arguments"), dict)
            else {}
        )
        for key in ("tool_id", "attached_tool_id", "capability_id"):
            value = tool_request.get(key) or arguments.get(key)
            if value:
                return str(value)
        return None

    @staticmethod
    def _dynamic_mcp_request(tool_request: Any) -> Optional[Dict[str, Any]]:
        if not isinstance(tool_request, dict):
            return None
        tool_id = str(tool_request.get("tool_id") or "").strip()
        server_id = str(tool_request.get("mcp_server") or "").strip()
        tool_name = str(tool_request.get("mcp_tool") or "").strip()
        if tool_id.startswith("mcp:") and (not server_id or not tool_name):
            parts = tool_id.split(":", 2)
            if len(parts) == 3:
                _, server_id, tool_name = parts
        if not server_id or not tool_name:
            return None
        arguments = tool_request.get("arguments")
        return {
            "tool_id": tool_id or f"mcp:{server_id}:{tool_name}",
            "server_id": server_id,
            "tool_name": tool_name,
            "arguments": dict(arguments or {}) if isinstance(arguments, dict) else {},
        }

    @property
    def _workspaces(self) -> Any:
        return self._ctx.get("workspaces")

    def _emit_step_diagnostic(
        self,
        agent_id: str,
        tick: int,
        step_index: int,
        action: ActionPack,
        tool_result: Optional[ToolRunResult],
        written: List[str],
    ) -> None:
        sink = self._ctx.get("diagnostic_sink")
        if not callable(sink):
            return
        tr = tool_result_to_dict(tool_result)
        sink({
            "event_type": "agent_loop_step",
            "tick": tick,
            "agent_id": agent_id,
            "step_index": step_index,
            "tool_id": action.attached_tool_id or (
                (action.tool_request or {}).get("tool_id")
                if isinstance(action.tool_request, dict) else None
            ),
            "source": tr.get("source"),
            "ok": tr.get("ok"),
            "errors": tr.get("errors", [])[:5],
            "outputs_preview": [
                str(
                    compact_tool_output(o) if isinstance(o, dict) else o
                )[:200]
                for o in (tr.get("outputs") or [])[:2]
            ],
            "workspace_written": written,
        })
