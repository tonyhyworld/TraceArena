"""
L3 Agent Runtime — 大模型调用与决策

职责：
- 为每个存活 Agent 构建感知包 / 简报
- 并发调用所有 LLM Provider，限时收集动作包
- 解析 ActionPack，记录 AgentLog
- 维护 Agent 记忆摘要（防 context 爆炸）
"""
from __future__ import annotations

import asyncio
import logging
import re
import time
from typing import Any, Dict, List, Optional, Tuple

from app.core.interfaces import (
    ActionOption,
    ActionPack,
    AgentBrief,
    AgentLog,
    PerceptionPack,
)
from app.engine.scenario_boot.registry import ScenarioRuntime
from app.framework.presentation.audience_text import sanitize_audience_text

logger = logging.getLogger(__name__)

MAX_HISTORY_TURNS = 8


class AgentContext:
    """单个 Agent 的运行时上下文"""

    def __init__(self, slot_cfg: Any, role: Any):
        self.slot = slot_cfg
        self.role = role
        self.provider: Any = None  # LLMProvider
        self.history: List[Dict[str, str]] = []
        self.memory_summary: str = ""
        self.memory_buffer: List[str] = []
        # 私人备忘（note_to_self 累积）：只有本 agent 自己下一拍能看到
        self.private_notes: List[str] = []
        # 反思洞察：每 5 拍由本 agent 自己的模型提炼，置顶注入后续简报
        self.reflections: List[str] = []

    def push_history(self, user_msg: str, assistant_msg: str) -> None:
        self.history.append({"role": "user", "content": user_msg})
        self.history.append({"role": "assistant", "content": assistant_msg})
        if len(self.history) > MAX_HISTORY_TURNS * 2:
            self.history = self.history[-(MAX_HISTORY_TURNS * 2):]

    def build_system_prompt(self) -> str:
        parts = ["你是一个在 AI 世界中参与竞争的智能体。"]
        if self.role:
            if self.role.display_name:
                parts.append(f"你扮演的角色：{self.role.display_name}。请始终以此身份行事。")
            if self.role.public_persona:
                parts.append(f"你的公开身份：{self.role.public_persona}")
            if self.role.hidden_goal:
                parts.append(f"你的秘密目标（不可泄露）：{self.role.hidden_goal}")
            if self.role.system_prompt_extra:
                parts.append(self.role.system_prompt_extra)
        parts.append(
            "每回合你会收到当前局势的感知包，请查看 available_actions 列表选择行动，输出一个 JSON 对象，包含以下字段：\n"
            "  action: 行动ID（必填，必须是 available_actions 中的某个 id）\n"
            "  target: 目标 Agent ID（部分行动需要，见 available_actions 说明）\n"
            "  target_object_id: 目标世界对象ID（可选）\n"
            "  text: 公开发言或行动描述（必填）\n"
            "  character_monologue: 第一人称角色短独白（必填，不得输出分析步骤或隐藏推理）\n"
            "  declared_intent: 公开意图声明（可选）\n"
            "如感知包中存在 available_tools，可在 JSON 中额外携带：\n"
            "  attached_tool_id: 工具ID\n"
            "  code: Python 分析代码（不超过40行）"
        )
        # 长期记忆摘要：compress_memory 每 10 回合把更早的行动压缩成摘要，
        # 在此注入，让 agent 不因 history 截断（仅保留最近 8 轮）而"失忆"。
        if self.memory_summary:
            parts.append(
                f"\n【你的长期记忆摘要（更早回合的概括，用于保持策略连贯）】\n{self.memory_summary}"
            )
        return "\n".join(parts)


class AgentRuntime:
    """
    L3 Agent 运行时。

    并发调度所有 Agent，处理超时，返回动作包 + 日志。
    复用 app.providers.registry.build_provider 构建 LLM Provider。
    """

    def __init__(
        self,
        runtime: ScenarioRuntime,
        agent_slots: List[Any],
        strict_mode: bool = False,
        agent_workspaces: Optional[Any] = None,  # AgentWorkspaceRegistry
        user_id: str = "",
        external_turn_timeout_ms: int = 120_000,
    ):
        """
        runtime: L0 ScenarioRuntime
        agent_slots: framework.yaml 的 AgentSlotConfig 列表
        agent_workspaces: 每 agent 独立 workspace 注册表（含 charter + CoT 落盘）
        """
        from app.providers.registry import build_provider

        self._runtime = runtime
        self._strict_mode = strict_mode
        self._workspaces = agent_workspaces  # 可为 None（兼容无 workspace 场景）
        self._user_id = user_id
        self._external_turn_timeout_ms = int(external_turn_timeout_ms)
        role_map = runtime.compiled.role_index
        self._contexts: Dict[str, AgentContext] = {}
        for slot in agent_slots:
            ctx = AgentContext(slot, role_map.get(slot.id))
            ctx.provider = build_provider(slot, user_id=user_id)
            self._contexts[slot.id] = ctx

    def set_user_context(self, user_id: str, *, external_turn_timeout_ms: Optional[int] = None) -> None:
        self._user_id = user_id
        if external_turn_timeout_ms is not None:
            self._external_turn_timeout_ms = int(external_turn_timeout_ms)
        from app.providers.registry import build_provider
        from app.providers.external_agent import ExternalAgentProvider
        for slot_id, ctx in self._contexts.items():
            if isinstance(ctx.provider, ExternalAgentProvider):
                ctx.provider.set_user_context(
                    user_id,
                    turn_timeout_ms=self._external_turn_timeout_ms,
                )
            elif str(getattr(ctx.slot, "driver", "llm")).strip().lower() == "agent":
                ctx.provider = build_provider(ctx.slot, user_id=user_id)

    def set_workspaces(self, workspaces: Any) -> None:
        """初始化之后挂载 AgentWorkspaceRegistry（用于 charter 注入 + CoT 落盘）。"""
        self._workspaces = workspaces

    @property
    def agent_ids(self) -> List[str]:
        return list(self._contexts.keys())

    def get_context(self, agent_id: str) -> AgentContext:
        return self._contexts.get(agent_id)  # type: ignore

    async def collect_actions(
        self,
        state: Any,
        briefs: Dict[str, AgentBrief],
        timeout_sec: float = 8.0,
        loop_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Dict[str, Optional[ActionPack]], List[AgentLog]]:
        """并发收集所有存活 Agent 的动作包"""
        alive = getattr(state, "alive_agent_ids", []) or []
        # 淘汰活死人机制：出局角色从此不再产生任何动作——不作答、不策略、不
        # 互动。后续所有环节只处理"收集到的动作"，无动作即等于彻底退场。
        eliminated_ids = {
            entry.get("agent_id")
            for entry in (getattr(state, "eliminated", []) or [])
            if isinstance(entry, dict)
        }
        tasks = {}
        for agent_id in alive:
            if agent_id not in self._contexts:
                continue
            if agent_id in eliminated_ids:
                continue
            brief = briefs.get(agent_id)
            if brief is None:
                raise ValueError(f"missing_agent_brief:{agent_id}")
            tasks[agent_id] = asyncio.create_task(
                self._query_agent(
                    agent_id, state.tick, brief,
                    loop_context=loop_context,
                )
            )

        if not tasks:
            # 无人可行动（全员已淘汰/尚未装配）——asyncio.wait 空集合会抛错，
            # 这里直接返回空结果，交由上层终局逻辑处理，不让本拍崩溃。
            return {}, []

        done, pending = await asyncio.wait(tasks.values(), timeout=timeout_sec)
        for t in pending:
            t.cancel()

        actions: Dict[str, Optional[ActionPack]] = {}
        logs: List[AgentLog] = []
        task_to_id = {v: k for k, v in tasks.items()}

        for task in done:
            agent_id = task_to_id[task]
            try:
                action, log = task.result()
                # P0-f：LLM 调用失败时 ctx 仍可能返回 None action（如 provider
                # 重试耗尽后抛异常被上层捕获）。这里把 None 升级成"wait"兜底
                # ActionPack，避免那拍 agent 完全消失，剧情线不至于断。
                if action is None:
                    err = (log.error if log and log.error else "llm_unavailable")
                    action = self._fallback_wait_action(state.tick, agent_id, err)
                actions[agent_id] = action
                logs.append(log)
            except Exception as e:
                actions[agent_id] = self._fallback_wait_action(state.tick, agent_id, str(e))
                logs.append(self._error_log(state.tick, agent_id, str(e)))

        for task in pending:
            agent_id = task_to_id[task]
            actions[agent_id] = self._fallback_wait_action(
                state.tick, agent_id, f"timeout>{timeout_sec}s",
            )
            logs.append(self._error_log(state.tick, agent_id, f"超时（>{timeout_sec}s）"))

        return actions, logs

    async def _query_agent(
        self,
        agent_id: str,
        tick: int,
        brief: AgentBrief,
        loop_context: Optional[Dict[str, Any]] = None,
    ) -> Tuple[Optional[ActionPack], AgentLog]:
        ctx = self._contexts[agent_id]
        start = time.monotonic()
        raw_response = ""
        action: Optional[ActionPack] = None
        error: Optional[str] = None
        tokens = 0
        loop_session = None

        try:
            if brief is not None:
                # P0 简报模式
                from app.framework.prompting.prompt_assembler import PromptAssembler
                from app.framework.prompting.action_parser import ActionParser
                from app.framework.prompting.output_contract_validator import OutputContractValidator

                assembler = PromptAssembler()
                parser = ActionParser(
                    self._runtime.actions_cfg, strict_mode=self._strict_mode
                )
                validator = OutputContractValidator()

                role_extra = ctx.role.system_prompt_extra if ctx.role else ""
                if brief.raw_context is None:
                    brief.raw_context = {}
                # 压缩摘要原先只写在旧 build_system_prompt 路径，简报主路径从未注入。
                if ctx.memory_summary:
                    brief.raw_context["memory_summary"] = ctx.memory_summary
                system_prompt = assembler.assemble_system(brief, role_extra=role_extra)
                user_message = assembler.assemble_user_message(brief)

                # External-agent transport belongs to the hosted control
                # plane and is intentionally absent from the public runtime.
                # Import it only for an explicitly configured agent driver so
                # replay/mock/LLM paths remain self-contained.
                if str(getattr(ctx.slot, "driver", "llm")).strip().lower() == "agent":
                    from app.providers.external_agent import ExternalAgentProvider
                    if isinstance(ctx.provider, ExternalAgentProvider):
                        run_id = ""
                        if brief.raw_context:
                            run_id = str(brief.raw_context.get("run_id") or "")
                        ctx.provider.prepare_turn(
                            tick=tick,
                            run_id=run_id,
                            brief=brief,
                            output_contract=brief.output_contract,
                        )

                if self._should_use_agent_loop(ctx, loop_context):
                    from app.agent_os.loop import AgentLoopRunner

                    runner = AgentLoopRunner(
                        config=loop_context["config"],
                        loop_context=loop_context,
                    )
                    action, raw_response, loop_tokens, loop_session = await runner.run(
                        agent_id=agent_id,
                        tick=tick,
                        ctx=ctx,
                        brief=brief,
                        system_prompt=system_prompt,
                        base_user_message=user_message,
                        build_action_from_parsed=(
                            lambda parsed, aid, b, raw, partial=False: (
                                self._build_partial_action_pack(parsed, aid)
                                if partial
                                else self._build_action_pack_from_parsed(
                                    parsed, aid, b, raw,
                                )
                            )
                        ),
                        parse_response=lambda raw, aid: self._parse_brief_response(
                            raw, aid, brief, parser, validator,
                        ),
                    )
                    tokens = loop_tokens
                    history_user = (
                        loop_session.build_user_message(user_message)
                        if loop_session and loop_session.steps
                        else user_message
                    )
                    ctx.push_history(history_user, raw_response)
                else:
                    msgs = ctx.history + [{"role": "user", "content": user_message}]
                    # 多模态挑战：图片由 node_coordinator 预编码，用 complete_multimodal 注入。
                    # history 一并传入——否则答图题那一拍模型会丢失之前全部对话上下文。
                    _cq = brief.raw_context.get("challenge_question") if brief.raw_context else None
                    _image_urls = (_cq or {}).get("image_data_urls") or []
                    if _image_urls:
                        raw_response = await ctx.provider.complete_multimodal(
                            system_prompt, user_message, _image_urls,
                            history=ctx.history, max_tokens=4096,
                        )
                    else:
                        # 主回合要输出完整 JSON（动作+独白+策略+备选），默认 1024 tokens
                        # 对推理模型极易截断 → 解析失败 → 兜底 wait。放宽到 4096。
                        raw_response = await ctx.provider.complete_with_history(
                            system_prompt, msgs, max_tokens=4096,
                        )
                    ctx.push_history(user_message, raw_response)

                    parsed = self._parse_brief_response(
                        raw_response, agent_id, brief, parser, validator,
                    )
                    action = self._build_action_pack_from_parsed(
                        parsed, agent_id, brief, raw_response,
                    )
                    if parsed.get("note_to_self"):
                        ctx.private_notes.append(
                            f"[T{tick}] {parsed['note_to_self']}"
                        )
                        ctx.private_notes = ctx.private_notes[-12:]

                usage = await ctx.provider.get_usage()
                if not self._should_use_agent_loop(ctx, loop_context):
                    tokens = sum(usage.values())
                elif tokens == 0:
                    tokens = sum(usage.values())

                if action and action.note_to_self:
                    ctx.private_notes.append(
                        f"[T{tick}] {action.note_to_self}"
                    )
                    ctx.private_notes = ctx.private_notes[-12:]
            # 所有解析路径统一经过观众文本出口，防止旧协议或供应商解析器漏出字段名。
            if action is not None:
                terminology = (
                    brief.raw_context.get("terminology", {})
                    if brief.raw_context else {}
                )
                for field in (
                    "text",
                    "thought",
                    "character_monologue",
                    "public_reasoning_summary",
                    "action_name",
                    "plan",
                    "expected_effect",
                    "backup_plan",
                    "declared_intent",
                ):
                    value = getattr(action, field, None)
                    if isinstance(value, str):
                        # 挑战作答的 text 是结构化 JSON，sanitize 会删掉英文 key/value 导致判分失败
                        if field == "text" and value.lstrip().startswith(("{", "[")):
                            continue
                        setattr(
                            action,
                            field,
                            sanitize_audience_text(value, terminology),
                        )

            usage = await ctx.provider.get_usage()
            tokens = sum(usage.values())

            # 写入记忆缓冲（供 compress_memory 压缩）
            if action and action.parsed_ok:
                summary = f"[T{tick}] {action.action_id}"
                if action.target_object_id:
                    summary += f"→{action.target_object_id}"
                if action.public_reasoning_summary:
                    summary += f" | {action.public_reasoning_summary[:80]}"
                ctx.memory_buffer.append(summary)
        except Exception as e:
            error = str(e)
            logger.exception(
                "[AgentRuntime] agent=%s tick=%s 决策循环失败", agent_id, tick
            )

        duration_ms = int((time.monotonic() - start) * 1000)

        # 从 brief 提取感知数据填充到 perception_pack（便于调试和审计）
        pack = PerceptionPack(
            tick=tick, agent_id=agent_id,
            scenario_name=self._runtime.scenario_name,
            memory_summary=ctx.memory_summary,
        )
        if brief is not None:
            pack.perception = {
                "self_state": brief.self_state,
                "ranking": brief.ranking,
                "others_summary": brief.others_summary,
            }
            pack.available_actions = [
                ActionOption(**item)
                for item in (brief.available_actions or [])
                if isinstance(item, dict)
            ]
            pack.self_location = brief.self_location
            pack.reachable_locations = [
                r.get("location_id", "") if isinstance(r, dict) else str(r)
                for r in (brief.reachable_locations or [])
            ]
            pack.visible_agents = [
                o.get("agent_id", o.get("id", ""))
                for o in (brief.others_summary or [])
            ]

        harness_trace = None
        if loop_session is not None:
            try:
                harness_trace = loop_session.to_harness_trace(
                    run_id=str((loop_context or {}).get("run_id") or ""),
                    scenario_id=str((loop_context or {}).get("scenario_id") or ""),
                    sandbox_id=f"sandbox:{agent_id}",
                    objective=str(
                        (brief.goal or {}).get("description")
                        or (brief.goal or {}).get("goal")
                        or ""
                    ),
                )
            except Exception as exc:
                logger.warning(
                    "[AgentRuntime] HarnessTrace build failed %s tick=%s: %s",
                    agent_id, tick, exc,
                )

        log = AgentLog(
            tick=tick, agent_id=agent_id,
            provider=getattr(ctx.provider, "provider_name", "unknown"),
            model=getattr(ctx.provider, "model_name", "unknown"),
            perception_pack=pack,
            raw_llm_response=raw_response, action_pack=action,
            duration_ms=duration_ms, tokens_used=tokens, error=error,
            harness_trace=(
                harness_trace.model_dump(mode="json") if harness_trace else None
            ),
        )

        # CoT 落盘：把这次 LLM 调用的 prompt/response/decision 三件套写入 workspace
        # （system+user prompt + 原始 LLM 输出 + 解析出的结构化 action）
        try:
            ws = self._workspaces.get(agent_id) if self._workspaces else None
            if ws:
                ws.save_cot(
                    tick=tick,
                    system_prompt=locals().get("system_prompt", "") or "",
                    user_message=locals().get("user_message", "") or "",
                    raw_response=raw_response or "",
                    decision=(
                        action.model_dump(mode="json") if action and hasattr(action, "model_dump")
                        else (action if isinstance(action, dict) else None)
                    ),
                )
                if harness_trace is not None:
                    ws.save_harness_trace(tick, harness_trace)
        except Exception as exc:  # CoT 落盘失败不能拖垮主循环
            import logging
            logging.getLogger(__name__).warning(
                f"[AgentRuntime] CoT 落盘失败 {agent_id} tick={tick}: {exc}"
            )

        return action, log

    @staticmethod
    def _should_use_agent_loop(
        ctx: AgentContext,
        loop_context: Optional[Dict[str, Any]],
    ) -> bool:
        if not loop_context or not loop_context.get("config"):
            return False
        cfg = loop_context["config"]
        if not getattr(cfg, "enabled", False):
            return False
        driver = str(getattr(ctx.slot, "driver", "") or "llm").strip().lower()
        if driver == "agent":
            return False
        extra_driver = (getattr(ctx.slot, "extra", None) or {}).get("driver")
        if str(extra_driver or "").strip().lower() == "agent":
            return False
        return True

    def _parse_brief_response(
        self,
        raw_response: str,
        agent_id: str,
        brief: AgentBrief,
        parser: Any,
        validator: Any,
    ) -> Dict[str, Any]:
        parsed = parser.parse(raw_response, agent_id)
        parsed = validator.validate(parsed)

        _default_aid = self._resolve_fallback_action_id()
        raw_action_id = parsed.get(
            "action_id", parsed.get("intent", _default_aid)
        )
        valid_ids = [
            a.get("id", "")
            for a in (brief.available_actions or [])
            if a.get("id")
        ]
        if valid_ids and raw_action_id not in valid_ids:
            if self._strict_mode:
                parsed["parsed_ok"] = False
                parsed["parse_errors"] = (
                    parsed.get("parse_errors") or []
                ) + [f"action_id 不在允许列表: {raw_action_id}"]
            else:
                corrected = _fuzzy_match_action(raw_action_id, valid_ids)
                if corrected:
                    parsed["action_id"] = corrected
                    parsed["intent"] = corrected
                    parsed["parse_errors"] = (
                        parsed.get("parse_errors") or []
                    ) + [
                        f"action_id 自动修复: {raw_action_id} -> {corrected}"
                    ]
        return parsed

    @staticmethod
    def _to_str_field(val: Any, fallback: str = "") -> str:
        import json as _json

        if val is None:
            return fallback
        if isinstance(val, str):
            return val
        if isinstance(val, (dict, list)):
            try:
                return _json.dumps(val, ensure_ascii=False)
            except Exception:
                return str(val)
        return str(val)

    def _build_partial_action_pack(
        self, parsed: Dict[str, Any], agent_id: str,
    ) -> ActionPack:
        """Agent 循环中间步：仅携带工具/代码字段。"""
        return ActionPack(
            agent_id=agent_id,
            action_id=self._resolve_fallback_action_id(),
            tool_request=parsed.get("tool_request"),
            code=parsed.get("code"),
            attached_tool_id=parsed.get("attached_tool_id"),
            parsed_ok=True,
            raw_model_output="",
        )

    def _build_action_pack_from_parsed(
        self,
        parsed: Dict[str, Any],
        agent_id: str,
        brief: AgentBrief,
        raw_response: str,
    ) -> ActionPack:
        _default_aid = self._resolve_fallback_action_id()
        valid_ids = [
            a.get("id", "")
            for a in (brief.available_actions or [])
            if a.get("id")
        ]

        ee = parsed.get("expected_effect")
        if isinstance(ee, list):
            ee = "; ".join(str(x) for x in ee)
        elif ee is not None and not isinstance(ee, str):
            ee = str(ee)

        terminology = (
            brief.raw_context.get("terminology", {})
            if brief.raw_context else {}
        )

        _raw_text_str = self._to_str_field(parsed.get("text"), parsed.get("plan", ""))
        if _raw_text_str.lstrip().startswith(("{", "[")):
            raw_text = _raw_text_str
        else:
            raw_text = sanitize_audience_text(_raw_text_str, terminology)
        public_summary = sanitize_audience_text(
            self._to_str_field(parsed.get("public_reasoning_summary_text")),
            terminology,
        )
        character_monologue = sanitize_audience_text(
            self._to_str_field(parsed.get("character_monologue")),
            terminology,
        )
        raw_thought = sanitize_audience_text(
            self._to_str_field(parsed.get("thought")), terminology
        )
        raw_plan = sanitize_audience_text(
            self._to_str_field(parsed.get("plan")), terminology
        )
        if (
            character_monologue
            and public_summary
            and character_monologue == public_summary
        ):
            parsed["parse_errors"] = (
                parsed.get("parse_errors") or []
            ) + ["character_monologue 与公开策略摘要重复，已拒绝展示"]
            character_monologue = ""
        # 独白兜底：模型漏填 character_monologue 时用正文首句顶上，
        # 避免观众端"操盘思路"面板整拍空白（面板只读独白字段）。
        if not character_monologue and raw_text and not raw_text.lstrip().startswith(("{", "[")):
            head = re.split(r"(?<=[。！？!?])", raw_text.strip(), maxsplit=1)[0]
            character_monologue = head[:120]
        # 策略摘要兜底：模型常把投资判断写进 plan/text 而漏填
        # public_reasoning_summary。只用 plan（或与独白不同的 text），
        # 绝不从 character_monologue 回退，避免「投资策略」与「操盘思路」串线。
        if not public_summary:
            candidate = raw_plan
            if (
                not candidate
                and raw_text
                and raw_text != character_monologue
                and not raw_text.lstrip().startswith(("{", "["))
            ):
                candidate = raw_text
            if candidate:
                public_summary = candidate[:700]
                parsed["parse_errors"] = (
                    parsed.get("parse_errors") or []
                ) + ["public_reasoning_summary 缺失，已从 plan/text 回填"]

        _act_id = parsed.get("action_id", parsed.get("intent", _default_aid))
        if (
            _act_id == "wait"
            and _default_aid
            and _default_aid != "wait"
            and _default_aid in valid_ids
        ):
            parsed["parse_errors"] = (
                parsed.get("parse_errors") or []
            ) + [f"action_id 自动修复: wait -> {_default_aid}"]
            _act_id = _default_aid
        _act_category = (
            self._runtime.get_action_rule(_act_id) or {}
        ).get("category")
        parameters = (
            dict(parsed.get("parameters") or {})
            if isinstance(parsed.get("parameters"), dict) else {}
        )
        evidence_refs = list(parsed.get("evidence_refs", []) or [])
        price_ref = str(parameters.get("price_evidence_ref") or "").strip()
        if price_ref and price_ref not in evidence_refs:
            evidence_refs.append(price_ref)
        return ActionPack(
            agent_id=agent_id,
            action_id=_act_id,
            target_agent_id=parsed.get("target_agent_id"),
            target_object_id=parsed.get("target_object_id"),
            text=raw_text,
            thought=raw_thought,
            character_monologue=character_monologue,
            public_reasoning_summary=public_summary,
            intent=self._to_str_field(parsed.get("intent") or _act_id),
            action_name=self._to_str_field(parsed.get("action_name")),
            plan=raw_plan,
            resource_commitment=parsed.get("resource_commitment"),
            risk_control=parsed.get("risk_control"),
            evidence_refs=evidence_refs,
            tool_request=parsed.get("tool_request"),
            parameters=parameters,
            expected_effect=ee,
            backup_plan=self._to_str_field(parsed.get("backup_plan")),
            parsed_ok=parsed.get("parsed_ok", False),
            parse_errors=parsed.get("parse_errors", []),
            raw_model_output=raw_response,
            code=parsed.get("code"),
            attached_tool_id=parsed.get("attached_tool_id"),
            category=_act_category,
            note_to_self=parsed.get("note_to_self"),
        )

    def _resolve_fallback_action_id(self) -> str:
        """场景声明的 LLM 失败待命动作 id。"""
        return self._runtime.fallback_action_id() or "wait"

    def _fallback_wait_action(
        self, tick: int, agent_id: str, reason: str
    ) -> ActionPack:
        """P0-f：LLM 调用失败（429、超时、网络异常等）时的系统兜底 ActionPack。

        返回场景声明的合法待命动作而非 None，让 L4/L5 流水线继续，
        agent 那拍就当"沉吟未决"，剧情连续性优先于"严格反映模型行为"。
        character_monologue 给观众一句轻度注释（不暴露技术错误码）。
        is_system_fallback=True 供引擎跳过拖延惩罚，不依赖具体动作 id。
        """
        action_id = self._resolve_fallback_action_id()
        rule = self._runtime.get_action_rule(action_id) or {}
        action_name = str(rule.get("name") or action_id)
        return ActionPack(
            agent_id=agent_id,
            action_id=action_id,
            text="",
            character_monologue="（此刻沉吟未决，按兵不动。）",
            public_reasoning_summary=f"LLM 未响应，本拍系统兜底为 {action_id}",
            intent=str(rule.get("intent") or "wait"),
            action_name=action_name,
            category=rule.get("category"),
            parsed_ok=False,
            is_system_fallback=True,
            parse_errors=[f"llm_unavailable: {reason}"],
        )

    def _error_log(self, tick: int, agent_id: str, error: str) -> AgentLog:
        ctx = self._contexts.get(agent_id)
        return AgentLog(
            tick=tick, agent_id=agent_id,
            provider=getattr(ctx.provider, "provider_name", "unknown") if ctx else "unknown",
            model=getattr(ctx.provider, "model_name", "unknown") if ctx else "unknown",
            perception_pack=PerceptionPack(
                tick=tick, agent_id=agent_id,
                scenario_name=self._runtime.scenario_name,
            ),
            error=error,
        )

    async def compress_memory(self, agent_id: str, director_provider: Any) -> None:
        ctx = self._contexts.get(agent_id)
        if not ctx or len(ctx.memory_buffer) < 10:
            return
        events_text = "\n".join(ctx.memory_buffer)
        try:
            summary = await director_provider.complete(
                "请将以下事件压缩成不超过200字的摘要：", events_text, max_tokens=300
            )
            ctx.memory_summary = summary.strip()
            ctx.memory_buffer = []
        except Exception:
            ctx.memory_buffer = ctx.memory_buffer[-5:]

    def get_private_memory(self, agent_id: str) -> Dict[str, List[str]]:
        """该 agent 的私人备忘 + 反思洞察（只回流给它自己的简报）。"""
        ctx = self._contexts.get(agent_id)
        if not ctx:
            return {"notes": [], "reflections": []}
        return {
            "notes": list(ctx.private_notes),
            "reflections": list(ctx.reflections),
        }

    async def reflect_all(self, tick: int, timeout_sec: float = 40.0) -> None:
        """反思子回合（每 5 拍由引擎调用）：agent 用**自己的模型**读自己
        最近的行动轨迹和私人备忘，提炼 2-3 条策略洞察，置顶注入后续简报。

        与 compress_memory 的区别：压缩是导演模型做的第三方摘要（信息保
        真），反思是 agent 本人做的策略提炼（形成"我注意到乙连续三次针对
        我"这类高层判断）——跨拍策略连贯性的生长点。不消耗行动点。
        """
        async def _reflect_one(agent_id: str, ctx: AgentContext) -> None:
            material_lines = ctx.memory_buffer[-10:] + ctx.private_notes[-6:]
            if not material_lines:
                return
            material = "\n".join(material_lines)
            try:
                raw = await asyncio.wait_for(
                    ctx.provider.complete(
                        "你正在复盘自己在一场竞争对局中最近几个回合的表现。"
                        "以下是你的行动记录和私人备忘。请提炼 2-3 条对后续决策"
                        "真正有用的策略洞察（对手的行为模式、自己该坚持或放弃的"
                        "打法、下一步的伏笔），每条一行，直接写内容，不要编号"
                        "以外的格式。",
                        material,
                        max_tokens=300,
                    ),
                    timeout=timeout_sec,
                )
                insights = [
                    ln.strip().lstrip("0123456789.、- ")
                    for ln in (raw or "").splitlines()
                    if ln.strip()
                ][:3]
                if insights:
                    stamped = [f"[T{tick}反思] {s[:120]}" for s in insights]
                    ctx.reflections = (ctx.reflections + stamped)[-6:]
            except Exception as exc:
                logger.debug(f"[Reflect] {agent_id} 反思失败(跳过): {exc}")

        await asyncio.gather(
            *(
                _reflect_one(aid, ctx)
                for aid, ctx in self._contexts.items()
            ),
            return_exceptions=True,
        )

    def rebuild_provider(self, agent_id: str, slot: Any) -> None:
        ctx = self._contexts.get(agent_id)
        if ctx:
            from app.providers.registry import build_provider
            ctx.provider = build_provider(slot, user_id=self._user_id)
            ctx.slot = slot
            ctx.history = []
            ctx.memory_summary = ""
            ctx.memory_buffer = []
            ctx.private_notes = []
            ctx.reflections = []


def _fuzzy_match_action(raw_id: str, valid_ids: list) -> str:
    """模糊匹配 action_id：LLM 可能返回语义近似的名称而非精确 id。
    匹配策略：
    1. 精确匹配（大小写不敏感）
    2. 子串包含（任一方向）
    3. 关键词重叠（token 交集）
    返回最佳匹配的 valid id，无匹配则返回空字符串。
    """
    if not raw_id or not valid_ids:
        return ""

    raw_lower = raw_id.lower().strip()

    # 1. 精确匹配（大小写不敏感）
    for vid in valid_ids:
        if vid.lower() == raw_lower:
            return vid

    # 2. 子串包含
    for vid in valid_ids:
        vl = vid.lower()
        if raw_lower in vl or vl in raw_lower:
            return vid

    # 3. 关键词重叠 — 将下划线分割的 token 集合做交集
    import re as _re
    raw_tokens = set(_re.split(r"[_\s]+", raw_lower))
    raw_tokens.discard("")
    best_score = 0
    best_match = ""
    for vid in valid_ids:
        vl = vid.lower()
        vid_tokens = set(_re.split(r"[_]+", vl))
        vid_tokens.discard("")
        overlap = len(raw_tokens & vid_tokens)
        if overlap > best_score:
            best_score = overlap
            best_match = vid

    # 至少要有 1 个 token 重叠才算匹配
    if best_score > 0:
        return best_match

    return ""
