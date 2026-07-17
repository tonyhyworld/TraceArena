"""AgentLoopSession（Agent 循环会话）：单 tick 内多步工具/代码试跑后再提交 ActionPack。"""
from __future__ import annotations

import json
import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.agent_os.loop_step import (
    format_step_results_for_prompt,
    is_continue_step,
    tool_result_to_dict,
)
from app.agent_os.workspace_ops import apply_workspace_writes
from app.core.interfaces import ActionPack, AgentBrief, AgentLog, ToolRunResult
from app.contracts.os2 import HarnessStep, HarnessTrace
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
    ) -> None:
        self.steps.append({
            "step_index": step_index,
            "kind": kind,
            "raw_response": raw_response,
            "tool_result": tool_result_to_dict(tool_result),
            "workspace_written": list(workspace_written or []),
        })

    def build_user_message(self, base_user_message: str) -> str:
        suffix = format_step_results_for_prompt(self.steps)
        if not suffix:
            return base_user_message
        # The full perception pack already exists in this intra-tick history.
        # Repeating it on every tool step both inflates tokens and buries the
        # newest observation under the original final-action contract.
        return "继续完成同一回合。不要重新陈述世界上下文。" + suffix

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
        for index, item in enumerate(self.steps):
            tool_result = item.get("tool_result") or {}
            outputs = tool_result.get("outputs") or []
            summary = ""
            if outputs:
                first = outputs[0]
                summary = str(
                    first.get("summary") or first.get("claim") or first
                    if isinstance(first, dict) else first
                )[:500]
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
                    "errors": list(tool_result.get("errors") or []),
                    "raw_response_ref": (
                        f"agent://{self.agent_id}/cot/tick_{self.tick:03d}_response.txt"
                    ),
                },
                duration_ms=int(tool_result.get("duration_ms") or 0),
            ))

        final_ref = None
        status = "failed"
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
            status = "completed"

        finished_at = self.finished_at or time.time()
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
            steps=trace_steps,
            final_action_ref=final_ref,
            usage={"tokens": float(self.total_tokens)},
            started_at=self.started_at,
            finished_at=finished_at,
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

    def _max_steps(self, runtime_mode: str) -> int:
        if str(runtime_mode).strip().lower() == "benchmark":
            return 1
        return max(1, int(getattr(self._config, "max_steps", 5)))

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
        )
        timeout_sec = float(getattr(self._config, "session_timeout_sec", 60.0))
        deadline = time.monotonic() + timeout_sec
        last_raw = ""
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
        # 无证据的交易在那里会被如实拒单并给出理由。
        consecutive_policy_nacks = 0
        max_policy_nacks = 3
        policy_nack_capped = False

        while (
            productive_steps < session.max_steps
            and wall_attempts < max_wall_attempts
        ):
            wall_attempts += 1
            if time.monotonic() > deadline:
                logger.info(
                    f"[AgentLoop] {agent_id} tick={tick} 会话超时 {timeout_sec}s"
                )
                break

            user_message = session.build_user_message(base_user_message)
            msgs = (
                ctx.history
                + session.intra_tick_messages
                + [{"role": "user", "content": user_message}]
            )

            _cq = brief.raw_context.get("challenge_question") if brief.raw_context else None
            _image_urls = (_cq or {}).get("image_data_urls") or []
            if _image_urls:
                raw_response = await ctx.provider.complete_multimodal(
                    system_prompt, user_message, _image_urls,
                    history=ctx.history + session.intra_tick_messages,
                    max_tokens=4096,
                )
            else:
                raw_response = await ctx.provider.complete_with_history(
                    system_prompt, msgs, max_tokens=4096,
                )
            last_raw = raw_response or ""
            session.intra_tick_messages.append(
                {"role": "user", "content": user_message}
            )
            session.intra_tick_messages.append(
                {"role": "assistant", "content": last_raw}
            )

            usage = await ctx.provider.get_usage()
            tokens += sum(usage.values())

            parsed = parse_response(last_raw, agent_id)
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
                and productive_steps < session.max_steps - 1
            ):
                pack = build_action_from_parsed(
                    parsed, agent_id, brief, last_raw, partial=True,
                )
                written, tool_result = await self._execute_continue_step(
                    pack, tick, step_no,
                )
                self._record_loop_tool_result(tool_result)
                step_kind = self._classify_step_kind(pack, written)
                session.record_step(
                    step_index=step_no,
                    kind=step_kind,
                    raw_response=last_raw,
                    tool_result=tool_result,
                    workspace_written=written,
                )
                self._emit_step_diagnostic(
                    agent_id, tick, step_no, pack, tool_result, written,
                )
                productive_steps += 1
                continue

            action = build_action_from_parsed(
                parsed, agent_id, brief, last_raw, partial=False,
            )
            self._backfill_trade_fields_from_text(parsed)
            # 同步回写到已构建的 ActionPack parameters
            if isinstance(parsed.get("parameters"), dict) and getattr(action, "parameters", None) is not None:
                for key, value in parsed["parameters"].items():
                    if key not in action.parameters or action.parameters[key] in (None, ""):
                        action.parameters[key] = value
            if str(getattr(action, "action_id", "") or "") in {"buy_asset", "sell_asset"}:
                params = getattr(action, "parameters", {}) or {}
                if params.get("quantity") in (None, "") or not str(params.get("asset_id") or "").strip():
                    self._sanitize_incomplete_trade_final(parsed)
                    action = build_action_from_parsed(
                        parsed, agent_id, brief, last_raw, partial=False,
                    )
            self._attach_harness_observations(action, session)
            session.final_action = action
            session.raw_final_response = last_raw
            session.total_tokens = tokens
            session.finished_at = time.time()
            return action, last_raw, tokens, session

        if session.final_action is None and session.steps and (
            policy_nack_capped or self._policy_satisfied(brief, session)
        ):
            logger.info(
                f"[AgentLoop] {agent_id} tick={tick} 步数用尽，强制最终解析"
            )
            parsed = parse_response(last_raw, agent_id)
            self._backfill_parameters_from_session(
                parsed, session, parse_response, agent_id,
            )
            self._backfill_trade_fields_from_text(parsed)
            # 自动行情只在「非行情研究已齐、仅差报价」时注入，避免研究未完成却被行情短路。
            if (
                not self._has_quote_evidence(brief, session)
                and self._ready_for_auto_quote(parsed, brief, session)
            ):
                injected = await self._try_inject_preferred_quote(
                    agent_id=agent_id,
                    tick=tick,
                    brief=brief,
                    session=session,
                    productive_steps=productive_steps,
                )
                if injected:
                    productive_steps += 1
            self._ensure_degraded_final_payload(parsed, brief, session)
            self._sanitize_incomplete_trade_final(parsed)
            if self._missing_research_categories(parsed, brief, session):
                self._degrade_trade_for_missing_research(parsed, brief, session)
            action = build_action_from_parsed(
                parsed, agent_id, brief, last_raw, partial=False,
            )
            self._ensure_degraded_action_text(action)
            self._attach_harness_observations(action, session)
            session.final_action = action
            session.raw_final_response = last_raw

        session.total_tokens = tokens
        session.finished_at = time.time()
        return session.final_action, last_raw, tokens, session

    @staticmethod
    def _policy_feedback_summary(
        session: AgentLoopSession,
        brief: AgentBrief,
        parsed: Optional[Dict[str, Any]] = None,
        attempt: int = 1,
    ) -> str:
        examples: List[str] = []
        failures: List[str] = []
        sandbox_failed = False

        def _add_capability_example(
            capability: Dict[str, Any],
            *,
            allow_install: bool = True,
        ) -> None:
            invocation = capability.get("invocation") or {}
            if str(invocation.get("operation") or "") == "install_skill":
                if not allow_install:
                    return
                skill_id = str(invocation.get("skill_id") or "")
                if skill_id:
                    examples.append(json.dumps({
                        "agent_loop_step": "continue",
                        "tool_request": {"skill_install": {"skill_id": skill_id}},
                    }, ensure_ascii=False))
                return
            tool_id = str(
                invocation.get("tool_id")
                or capability.get("capability_id")
                or ""
            )
            if not tool_id:
                return
            schema = capability.get("input_schema") or {}
            required = list(schema.get("required") or [])
            arguments = {name: f"<请填写 {name}>" for name in required}
            # 行情工具给可抄作业的默认 symbols，降低模型不会填参的概率。
            if "quote" in tool_id.lower() and "symbols" in (
                schema.get("properties") or {}
            ):
                arguments["symbols"] = ["600036.SH", "00700.HK"]
            elif "quote" in tool_id.lower() and "symbol" in (
                schema.get("properties") or {}
            ):
                arguments["symbol"] = "600036.SH"
            examples.append(json.dumps({
                "agent_loop_step": "continue",
                "tool_request": {"tool_id": tool_id, "arguments": arguments},
            }, ensure_ascii=False))

        def _is_quote_capability(capability: Dict[str, Any]) -> bool:
            hay = (
                f"{capability.get('capability_id') or ''} "
                f"{capability.get('name') or ''} "
                f"{(capability.get('invocation') or {}).get('tool_id') or ''}"
            ).lower()
            return any(token in hay for token in ("quote", "candlestick", "行情"))

        def _is_install_capability(capability: Dict[str, Any]) -> bool:
            invocation = capability.get("invocation") or {}
            return str(invocation.get("operation") or "") == "install_skill"

        missing_categories = AgentLoopRunner._missing_research_categories(
            parsed or {}, brief, session,
        )
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        category_tokens = dict(policy.get("research_category_tokens") or {})

        def _matches_missing(capability: Dict[str, Any]) -> bool:
            if not missing_categories:
                return False
            hay = (
                f"{capability.get('capability_id') or ''} "
                f"{capability.get('name') or ''} "
                f"{capability.get('description') or ''} "
                f"{(capability.get('invocation') or {}).get('tool_id') or ''}"
            ).lower()
            for category in missing_categories:
                tokens = category_tokens.get(category) or [category]
                if any(str(token).lower() in hay for token in tokens):
                    return True
            return False

        # 1) 优先：sandbox 里 status=ready 且能补齐当前研究缺口的 MCP。
        sandbox_info = (brief.raw_context or {}).get("agent_sandbox") or {}
        ready_caps = [
            item for item in (sandbox_info.get("capabilities") or [])
            if isinstance(item, dict)
            and str(item.get("status") or "") == "ready"
            and not _is_install_capability(item)
        ]
        ready_quotes = [item for item in ready_caps if _is_quote_capability(item)]
        ready_missing = [item for item in ready_caps if _matches_missing(item)]
        if any(
            item != "quote" and not item.startswith("non_quote_")
            for item in missing_categories
        ):
            ready_missing.sort(
                key=lambda item: 1 if _is_quote_capability(item) else 0
            )
        for capability in ready_missing + ready_quotes + ready_caps:
            _add_capability_example(capability, allow_install=False)
            if examples:
                break

        # 2) 场景 preferred_tools 兜底示例（即使尚未 discover 成功）。
        if not examples:
            for token in policy.get("preferred_tools") or []:
                name = str(token).strip()
                if not name:
                    continue
                tool_id = (
                    name if name.startswith("mcp:")
                    else f"mcp:longport:{name}"
                )
                examples.append(json.dumps({
                    "agent_loop_step": "continue",
                    "tool_request": {
                        "tool_id": tool_id,
                        "arguments": {"symbols": ["600036.SH", "00700.HK"]},
                    },
                }, ensure_ascii=False))
                break

        # 3) 从最近真实步骤的发现结果取例；跳过未安装 skill，除非没有 MCP。
        if not examples:
            discovered_caps: List[Dict[str, Any]] = []
            for step in reversed(session.steps):
                result = step.get("tool_result") or {}
                if str(result.get("source") or "") == "scenario_harness_policy":
                    continue
                errors = result.get("errors") or []
                if errors:
                    failures.append(
                        f"上一步 {result.get('source') or '工具'} 失败："
                        + "；".join(str(item) for item in errors[:3])
                    )
                    if str(result.get("source") or "") == "agent_sandbox":
                        sandbox_failed = True
                for output in result.get("outputs") or []:
                    capability = (
                        output.get("capability") if isinstance(output, dict) else None
                    )
                    if isinstance(capability, dict):
                        discovered_caps.append(capability)
                if discovered_caps or failures:
                    break
            non_install = [
                item for item in discovered_caps if not _is_install_capability(item)
            ]
            missing_first = sorted(
                non_install,
                key=lambda item: (
                    0 if _matches_missing(item) else 1,
                    0 if _is_quote_capability(item) else 1,
                ),
            )
            for capability in missing_first:
                _add_capability_example(capability, allow_install=False)
                if examples:
                    break
            if not examples:
                for capability in discovered_caps:
                    _add_capability_example(capability, allow_install=True)
                    if examples:
                        break

        # 4) 沙箱失败时再次强调 ready MCP。
        if sandbox_failed and isinstance(sandbox_info, dict) and ready_caps:
            examples = []
            _add_capability_example(
                (ready_quotes or ready_caps)[0], allow_install=False,
            )

        suffix = (
            " 可直接按这个 JSON 调用已发现能力：" + examples[0]
            if examples else " 请先搜索能力目录、调用外部工具、安装依赖，或编写并运行代码。"
        )
        failure_text = (" ".join(failures[:1]) + " ") if failures else ""
        attempt_text = (
            f"（第 {attempt} 次提醒，同样的路线连续失败就换一条：改用工具目录里"
            "即刻可用的外部数据工具，优先 longport_quote 行情。）"
            if attempt >= 2 else ""
        )
        sandbox_hint = (
            "你的沙箱代码运行环境本身可能有故障（脚本瞬间退出、无任何输出时"
            "尤其如此）——这不是你的代码写错了，请改走外部工具路线。"
            if sandbox_failed else ""
        )
        missing_hint = ""
        if missing_categories:
            labels = dict(policy.get("research_category_labels") or {})
            names = [str(labels.get(item) or item) for item in missing_categories]
            missing_hint = (
                "当前交易研究仍缺少：" + "、".join(names)
                + "。必须调用对应外部工具取得可验证结果，不能只重复查行情。"
            )
        return (
            failure_text
            + attempt_text
            + sandbox_hint
            + missing_hint
            +
            "当前还没有可信的外部事实，不能结束研究。发现能力只说明工具存在，"
            "不等于已经取得行情、新闻或验证结果；沙箱自行假设的数据也不能替代现实来源。"
            + suffix
            + " 拿到带来源、时间和证据 ID 的结果后，再提交最终世界行动。"
        )

    @staticmethod
    def _quote_tool_tokens(brief: AgentBrief) -> List[str]:
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        tokens = [
            str(item).strip().lower()
            for item in (
                policy.get("quote_tools")
                or policy.get("preferred_quote_tools")
                or []
            )
            if str(item).strip()
        ]
        if not tokens:
            tokens = ["quote", "candlestick"]
        # 始终把 quote 语义算进去，避免 preferred 写全名时漏匹配。
        for extra in ("quote", "candlestick"):
            if extra not in tokens:
                tokens.append(extra)
        return tokens

    @classmethod
    def _step_looks_like_quote(cls, step: Dict[str, Any], brief: AgentBrief) -> bool:
        result = step.get("tool_result") or {}
        if not result.get("ok"):
            return False
        if str(result.get("source") or "") not in {
            "mcp", "external_reality", "verified_external",
        }:
            return False
        hay = (
            f"{result.get('tool_id') or ''} "
            f"{result.get('mcp_tool_name') or ''}"
        ).lower()
        tokens = cls._quote_tool_tokens(brief)
        if any(token in hay for token in tokens):
            return True
        # 输出里带 last_done / quotes 也算行情证据。
        for output in result.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            blob = json.dumps(output, ensure_ascii=False).lower()
            if "last_done" in blob or '"quotes"' in blob:
                return True
        return False

    @classmethod
    def _has_quote_evidence(cls, brief: AgentBrief, session: AgentLoopSession) -> bool:
        return any(cls._step_looks_like_quote(step, brief) for step in session.steps)

    @classmethod
    def _research_categories_from_result(
        cls,
        result: Dict[str, Any],
        brief: AgentBrief,
    ) -> set[str]:
        """Classify a verified tool result into scenario-declared research domains."""
        if not isinstance(result, dict) or not result.get("ok"):
            return set()
        if str(result.get("source") or "") not in {
            "mcp", "external_reality", "verified_external",
        }:
            return set()
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        token_map = dict(policy.get("research_category_tokens") or {})
        blob = json.dumps(result, ensure_ascii=False, default=str).lower()
        categories: set[str] = set()
        # 新工具会显式返回 research_categories；仍保留 token 匹配兼容旧工具。
        for output in result.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            declared = output.get("research_categories") or []
            if isinstance(declared, str):
                declared = [declared]
            categories.update(
                str(item).strip()
                for item in declared
                if str(item).strip()
            )
        for category, raw_tokens in token_map.items():
            tokens = raw_tokens if isinstance(raw_tokens, list) else [raw_tokens]
            if any(str(token).lower() in blob for token in tokens if str(token)):
                categories.add(str(category))
        if cls._step_looks_like_quote({"tool_result": result}, brief):
            categories.add("quote")
        return categories

    @classmethod
    def _research_categories(
        cls,
        brief: AgentBrief,
        session: AgentLoopSession,
    ) -> set[str]:
        categories: set[str] = set()
        for step in session.steps:
            categories.update(
                cls._research_categories_from_result(
                    step.get("tool_result") or {}, brief,
                )
            )
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        for observation in policy.get("prior_verified_observations") or []:
            if not isinstance(observation, dict):
                continue
            raw = observation.get("raw_value")
            if isinstance(raw, dict):
                categories.update(cls._research_categories_from_result(raw, brief))
            normalized = observation.get("normalized_value") or {}
            if isinstance(normalized, dict):
                declared = normalized.get("research_categories") or []
                if isinstance(declared, str):
                    declared = [declared]
                categories.update(
                    str(item).strip()
                    for item in declared
                    if str(item).strip()
                )
        return categories

    @classmethod
    def _missing_research_categories(
        cls,
        parsed: Dict[str, Any],
        brief: AgentBrief,
        session: AgentLoopSession,
    ) -> List[str]:
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        requirements = dict(policy.get("research_requirements") or {})
        if not requirements.get("enabled"):
            return []
        action_id = str(
            parsed.get("action_id") or parsed.get("intent") or ""
        ).strip()
        trade_actions = set(
            str(item) for item in (
                requirements.get("trade_actions") or ["buy_asset"]
            )
        )
        if action_id not in trade_actions:
            return []
        categories = cls._research_categories(brief, session)
        missing: List[str] = []
        if requirements.get("require_quote") and "quote" not in categories:
            missing.append("quote")
        by_agent = dict(requirements.get("by_agent") or {})
        role_rules = dict(by_agent.get(brief.agent_id) or {})
        for category in role_rules.get("required") or []:
            category = str(category)
            if category and category not in categories:
                missing.append(category)
        for group in role_rules.get("any_of") or []:
            options = [str(item) for item in (group or []) if str(item)]
            if options and not any(item in categories for item in options):
                # 反馈列出首选项；满足组内任意一类即可。
                missing.append(options[0])
        declared_domains = set(
            str(item) for item in (
                policy.get("research_category_tokens") or {}
            )
        )
        non_quote = {
            item for item in categories
            if item != "quote" and (
                not declared_domains or item in declared_domains
            )
        }
        minimum = max(
            0, int(requirements.get("minimum_non_quote_categories", 0) or 0)
        )
        if len(non_quote) < minimum:
            missing.append(f"non_quote_{minimum}")
        minimum_results = max(
            0, int(requirements.get("minimum_non_quote_results", 0) or 0)
        )
        non_quote_results = 0
        for step in session.steps:
            result_categories = cls._research_categories_from_result(
                step.get("tool_result") or {}, brief,
            )
            if result_categories - {"quote"}:
                non_quote_results += 1
        for observation in policy.get("prior_verified_observations") or []:
            if not isinstance(observation, dict):
                continue
            normalized = observation.get("normalized_value") or {}
            declared = (
                normalized.get("research_categories") or []
                if isinstance(normalized, dict) else []
            )
            if isinstance(declared, str):
                declared = [declared]
            raw = observation.get("raw_value") or {}
            prior_categories = set(str(item) for item in declared if str(item))
            if isinstance(raw, dict):
                prior_categories.update(
                    cls._research_categories_from_result(raw, brief)
                )
            if prior_categories - {"quote"}:
                non_quote_results += 1
        if non_quote_results < minimum_results:
            missing.append(f"non_quote_results_{minimum_results}")
        return list(dict.fromkeys(missing))

    @classmethod
    def _ready_for_auto_quote(
        cls,
        parsed: Dict[str, Any],
        brief: AgentBrief,
        session: AgentLoopSession,
    ) -> bool:
        """自动补行情仅在交易意图已齐非行情研究时放行。"""
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        requirements = dict(policy.get("research_requirements") or {})
        if not requirements.get("enabled"):
            return True
        action_id = str(
            parsed.get("action_id") or parsed.get("intent") or ""
        ).strip()
        trade_actions = set(
            str(item) for item in (
                requirements.get("trade_actions") or ["buy_asset"]
            )
        )
        if action_id not in trade_actions:
            return False
        missing = cls._missing_research_categories(parsed, brief, session)
        return (not missing) or missing == ["quote"]

    @classmethod
    def _degrade_trade_for_missing_research(
        cls,
        parsed: Dict[str, Any],
        brief: AgentBrief,
        session: AgentLoopSession,
    ) -> None:
        missing = cls._missing_research_categories(parsed, brief, session)
        if not missing:
            return
        reason = (
            "本拍研究证据未齐（缺少: "
            + "、".join(missing)
            + "），系统降级为观望，避免无研究下单。"
        )
        parsed["agent_loop_step"] = "final"
        parsed["action_id"] = "wait_and_review"
        parsed["intent"] = "wait_and_review"
        parsed["text"] = reason
        parsed["character_monologue"] = reason[:40]
        parsed["plan"] = reason

    @classmethod
    def _has_trusted_external(cls, brief: AgentBrief, session: AgentLoopSession) -> bool:
        trusted_sources = {"mcp", "external_reality", "verified_external"}
        return any(
            (item.get("tool_result") or {}).get("ok")
            and str((item.get("tool_result") or {}).get("source") or "")
            in trusted_sources
            for item in session.steps
        )

    @staticmethod
    def _policy_satisfied(brief: AgentBrief, session: AgentLoopSession) -> bool:
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        if not policy.get("require_verified_external_result"):
            return True
        # 强制终局路径无法再可靠判断模型最终会否下单；保持严格兜底，
        # 只有已取得行情才允许从步数耗尽状态提交。
        if policy.get("require_verified_quote"):
            return AgentLoopRunner._has_quote_evidence(brief, session)
        return AgentLoopRunner._has_trusted_external(brief, session)

    @classmethod
    def _requires_more_harness_work(
        cls,
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
            if not cls._has_trusted_external(brief, session):
                return not is_continue_step(parsed)
        action_id = str(
            parsed.get("action_id") or parsed.get("intent") or ""
        ).strip()
        if (
            policy.get("require_verified_quote")
            and action_id in {"buy_asset", "sell_asset"}
            and not cls._has_quote_evidence(brief, session)
        ):
            return not is_continue_step(parsed)
        if cls._missing_research_categories(parsed, brief, session):
            return not is_continue_step(parsed)
        return False

    @staticmethod
    def _ensure_degraded_final_payload(
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
        reason = (
            "本拍未能取得有效期内已验证行情，系统降级为观望，保留现金等待下一拍。"
            if not AgentLoopRunner._has_quote_evidence(brief, session)
            else "本拍研究步骤已达上限，按已有证据提交当前决策。"
        )
        if not str(parsed.get("text") or "").strip():
            parsed["text"] = reason
        if not str(parsed.get("character_monologue") or "").strip():
            parsed["character_monologue"] = reason[:40]
        if not str(parsed.get("plan") or "").strip():
            parsed["plan"] = reason

    @staticmethod
    def _ensure_degraded_action_text(action: ActionPack) -> None:
        reason = "本拍未能取得有效期内已验证行情，系统降级为观望。"
        if not str(getattr(action, "text", "") or "").strip():
            action.text = reason
        if not str(getattr(action, "character_monologue", "") or "").strip():
            action.character_monologue = reason[:40]
        if not str(getattr(action, "plan", "") or "").strip():
            action.plan = reason
        if not str(getattr(action, "action_id", "") or "").strip():
            action.action_id = "wait_and_review"

    async def _try_inject_preferred_quote(
        self,
        *,
        agent_id: str,
        tick: int,
        brief: AgentBrief,
        session: AgentLoopSession,
        productive_steps: int,
    ) -> bool:
        """封顶后 OS 代跑一次 preferred quote，避免空 wait 浪费整拍。"""
        if productive_steps >= session.max_steps:
            return False
        tool_id, arguments = self._resolve_preferred_quote_call(brief, session)
        if not tool_id:
            return False
        pack = ActionPack(
            agent_id=agent_id,
            action_id="harness_auto_quote",
            parsed_ok=True,
            tool_request={"tool_id": tool_id, "arguments": arguments},
            attached_tool_id=tool_id,
        )
        step_no = len(session.steps) + 1
        written, tool_result = await self._execute_continue_step(
            pack, tick, step_no,
        )
        self._record_loop_tool_result(tool_result)
        session.record_step(
            step_index=step_no,
            kind="execute_tool",
            raw_response="[os_injected_preferred_quote]",
            tool_result=tool_result,
            workspace_written=written,
        )
        self._emit_step_diagnostic(
            agent_id, tick, step_no, pack, tool_result, written,
        )
        ok = bool(tool_result and tool_result.ok)
        logger.info(
            f"[AgentLoop] {agent_id} tick={tick} 封顶后注入 {tool_id} "
            f"{'成功' if ok else '失败'}"
        )
        return ok

    @classmethod
    def _resolve_preferred_quote_call(
        cls,
        brief: AgentBrief,
        session: AgentLoopSession,
    ) -> Tuple[str, Dict[str, Any]]:
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        preferred = [
            str(item).strip()
            for item in (
                policy.get("quote_tools")
                or policy.get("preferred_quote_tools")
                or ["longport_quote"]
            )
            if str(item).strip()
        ]
        sandbox_info = (brief.raw_context or {}).get("agent_sandbox") or {}
        ready = [
            item for item in (sandbox_info.get("capabilities") or [])
            if isinstance(item, dict) and str(item.get("status") or "") == "ready"
        ]
        for token in preferred:
            token_l = token.lower()
            for item in ready:
                hay = (
                    f"{item.get('capability_id') or ''} "
                    f"{item.get('name') or ''} "
                    f"{(item.get('invocation') or {}).get('tool_id') or ''}"
                ).lower()
                if token_l not in hay and "quote" not in hay:
                    continue
                tool_id = str(
                    (item.get("invocation") or {}).get("tool_id")
                    or item.get("capability_id")
                    or ""
                )
                if not tool_id:
                    continue
                schema = item.get("input_schema") or {}
                props = schema.get("properties") or {}
                if "symbols" in props:
                    return tool_id, {"symbols": ["600036.SH", "00700.HK"]}
                if "symbol" in props:
                    return tool_id, {"symbol": "600036.SH"}
                return tool_id, {}
        # 无 ready 目录时仍尝试默认 longport_quote。
        for token in preferred:
            name = token if ":" in token else f"mcp:longport:{token}"
            if "quote" in name.lower() or token.lower().endswith("quote"):
                return name, {"symbols": ["600036.SH", "00700.HK"]}
        return "", {}

    @staticmethod
    def _backfill_parameters_from_session(
        parsed: Dict[str, Any],
        session: AgentLoopSession,
        parse_response: Callable[[str, str], Dict[str, Any]],
        agent_id: str,
    ) -> None:
        """强制终局时，用本回合早先响应里同一动作的结构化参数补齐缺失键。

        步数用尽的最后一份回复常常只剩散文（模型在重压下不再输出参数块），
        导致"文本里明说买 100 股、parameters 却缺 quantity"而被拒单。
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
    def _backfill_trade_fields_from_text(parsed: Dict[str, Any]) -> None:
        """从独白/正文里捞 asset_id / quantity，补齐残缺买单。"""
        action_id = str(parsed.get("action_id") or parsed.get("intent") or "")
        if action_id not in {"buy_asset", "sell_asset"}:
            return
        params = dict(parsed.get("parameters") or {})
        blob = " ".join(
            str(parsed.get(key) or "")
            for key in ("text", "plan", "character_monologue", "public_reasoning")
        )
        if not params.get("asset_id"):
            import re
            match = re.search(
                r"\b(\d{5,6}\.(?:SH|SZ|SS|HK)|0?\d{3,4}\.HK)\b",
                blob,
                flags=re.IGNORECASE,
            )
            if match:
                code = match.group(1).upper()
                if code.endswith(".SS"):
                    code = code[:-3] + ".SH"
                params["asset_id"] = code
        if params.get("quantity") in (None, ""):
            import re
            match = re.search(
                r"(?:买入|卖出|加仓|减仓|建仓|数量|qty|quantity)\s*"
                r"[：:]?\s*(\d+(?:\.\d+)?)\s*股",
                blob,
                flags=re.IGNORECASE,
            )
            if not match:
                match = re.search(r"(\d+(?:\.\d+)?)\s*股", blob)
            if match:
                try:
                    params["quantity"] = float(match.group(1))
                except (TypeError, ValueError):
                    pass
        if params:
            parsed["parameters"] = params

    @staticmethod
    def _sanitize_incomplete_trade_final(parsed: Dict[str, Any]) -> None:
        """残缺买卖单不得作为最终动作放行——降级为观望，避免 quantity_missing 空转。"""
        action_id = str(parsed.get("action_id") or parsed.get("intent") or "")
        if action_id not in {"buy_asset", "sell_asset"}:
            return
        params = parsed.get("parameters") if isinstance(parsed.get("parameters"), dict) else {}
        has_qty = params.get("quantity") not in (None, "")
        has_asset = bool(str(params.get("asset_id") or "").strip())
        if has_qty and has_asset:
            return
        reason = (
            "本拍买卖指令缺少标的或数量，系统降级为观望，避免无效拒单。"
        )
        parsed["action_id"] = "wait_and_review"
        parsed["intent"] = "wait_and_review"
        parsed["agent_loop_step"] = "final"
        parsed["parameters"] = {}
        parsed["text"] = reason
        parsed["character_monologue"] = reason[:40]
        parsed["plan"] = reason

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
        # 首步必须先看完整研究能力目录；直接请求报价也不能跳过发现。
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

    @staticmethod
    def _attach_harness_observations(
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
            # 买卖单若未显式带 price_evidence_ref，默认挂上本回合最近一次
            # 行情类 MCP 观测，避免「查到了价却忘了引用」导致拒单。
            action_id = str(getattr(action, "action_id", "") or "")
            if (
                action_id in {"buy_asset", "sell_asset"}
                and not str(action.parameters.get("price_evidence_ref") or "").strip()
            ):
                chosen = ""
                for obs in reversed(observations):
                    tool_id = str(obs.get("tool_id") or "").lower()
                    source = str(obs.get("source") or "").lower()
                    if source not in {"mcp", "external_reality", "verified_external"}:
                        continue
                    if any(
                        key in tool_id
                        for key in ("quote", "candlestick", "chart", "price")
                    ) or source in {"external_reality", "verified_external"}:
                        chosen = str(obs.get("run_id") or "")
                        if chosen:
                            break
                if not chosen:
                    for obs in reversed(observations):
                        if str(obs.get("source") or "") in {
                            "mcp", "external_reality", "verified_external"
                        }:
                            chosen = str(obs.get("run_id") or "")
                            if chosen:
                                break
                if chosen:
                    action.parameters["price_evidence_ref"] = chosen
                    if chosen not in action.evidence_refs:
                        action.evidence_refs = list(action.evidence_refs or []) + [
                            chosen
                        ]

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
                    (o.get("claim") or o.get("summary") or o)
                    if isinstance(o, dict) else o
                )[:200]
                for o in (tr.get("outputs") or [])[:2]
            ],
            "workspace_written": written,
        })
