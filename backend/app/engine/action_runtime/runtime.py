"""
L4 Action/Sandbox Runtime — 动作/工具/脚本执行

职责：
- 接收 Agent 的 ActionPack
- 前置校验（委托 ActionPreconditionValidator）
- 通用状态变更处理（如位置变更，由 action 配置的 target_kind 驱动，不写死 action_id）
- 工具代码在沙盒中执行（不直接改世界）
- 产出 ToolRunResult 供 L5 评价层消费
- 所有工具运行结果必须可追溯到账本

场景无关：位置变更等通用效果由 action 配置中的通用字段
（target_kind / category / state_effects）驱动，不写死任何 action_id。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.interfaces import (
    ActionPack,
    ActionStateTransition,
    TickTransactionRecord,
    ToolRunResult,
    RuntimeSignal,
)
from app.framework.ruleworld.evidence import EvidenceService

logger = logging.getLogger(__name__)


class ActionRuntime:
    """
    L4 动作/沙盒运行时。

    铁律：行动不能直接加分——所有影响必须经过 L5 因果物理裁决。
    本层负责：
    - 前置校验（委托 ActionPreconditionValidator）
    - 通用状态变更（位置变更等，由 action 配置的通用字段驱动）
    - 工具代码沙盒执行
    - 工具运行结果记录
    - 产出 ToolRunResult 供 L5 消费
    """

    def __init__(self):
        self._sandbox: Any = None
        self._evidence_service: Optional[EvidenceService] = None
        self._workspaces: Any = None
        self._tool_runs: List[ToolRunResult] = []
        # agent_id → personality（roles.yaml capability_profile.personality）。
        # 人格不只是提示词装饰——它进成本曲线：同一动作对不同性情的人代价
        # 不同，同一局面下的理性最优解因此分化（对称人=对称解）。
        self._personalities: Dict[str, Dict[str, str]] = {}

    def set_personalities(
        self, personalities: Dict[str, Dict[str, str]]
    ) -> None:
        self._personalities = dict(personalities or {})

    def set_sandbox(self, sandbox: Any) -> None:
        self._sandbox = sandbox

    def set_evidence_service(self, evidence_service: EvidenceService) -> None:
        self._evidence_service = evidence_service

    def set_workspace_registry(self, registry: Any) -> None:
        self._workspaces = registry

    def _personality_cost_multipliers(
        self, agent_id: str, action_cfg: Dict[str, Any],
    ) -> Dict[str, float]:
        """按人格差异化动作成本，返回 {resource_id: multiplier}。

        保守起步，只做两条最能拉开打法的规则：
        - 守成持重（risk_preference=low）走暗面（intent=attack 且带 secrecy
          成本）心理负担重 → secrecy 消耗 ×1.3；
        - 锋芒毕露（aggressiveness=high）做公开对抗（intent=attack 且不带
          secrecy 成本）如鱼得水 → energy 消耗 ×0.8。
        """
        pers = self._personalities.get(agent_id) or {}
        if not pers:
            return {}
        multipliers: Dict[str, float] = {}
        intent = str(action_cfg.get("intent", ""))
        cost = action_cfg.get("cost", {}) or {}
        is_covert = "secrecy" in cost
        if (
            pers.get("risk_preference") == "low"
            and intent == "attack" and is_covert
        ):
            multipliers["secrecy"] = 1.3
        if (
            pers.get("aggressiveness") == "high"
            and intent == "attack" and not is_covert
        ):
            multipliers["energy"] = 0.8
        return multipliers

    def plan_state_transition(
        self,
        action: ActionPack,
        action_cfg: Dict[str, Any],
        state: Any,
    ) -> ActionStateTransition:
        """仅规划通用平台变化，不在此处修改任何状态。"""
        location_to = None
        location_from = None
        if action_cfg.get("target_kind") == "location" and action.target_object_id:
            location_from = getattr(state, "agent_locations", {}).get(action.agent_id)
            location_to = action.target_object_id
        cost_multipliers = self._personality_cost_multipliers(
            action.agent_id, action_cfg,
        )
        return ActionStateTransition(
            agent_id=action.agent_id,
            action_id=action.action_id,
            resource_cost={
                str(k): round(float(v) * cost_multipliers.get(str(k), 1.0), 2)
                for k, v in (action_cfg.get("cost", {}) or {}).items()
            },
            cooldown_ticks=max(0, int(action_cfg.get("cooldown", 0) or 0)),
            location_from=location_from,
            location_to=location_to,
        )

    def commit_transitions(
        self,
        tick: int,
        transitions: List[ActionStateTransition],
        state: Any,
        world_state_kernel: Any,
        resource_service: Any,
        cooldown_service: Any,
        location_registry: Any,
    ) -> TickTransactionRecord:
        """原子提交资源、冷却和位置变化；任一步失败则恢复。"""
        tx = TickTransactionRecord(tick=tick, transitions=list(transitions))
        resource_snapshot = resource_service.snapshot() if resource_service else None
        cooldown_snapshot = cooldown_service.snapshot() if cooldown_service else None
        location_snapshot = dict(getattr(state, "agent_locations", {}) or {})
        try:
            for transition in transitions:
                if resource_service and transition.resource_cost:
                    if not resource_service.can_afford(
                        transition.agent_id, transition.resource_cost
                    ):
                        raise ValueError(
                            f"resource_conflict:{transition.agent_id}:{transition.action_id}"
                        )
                    deltas = resource_service.deduct(
                        transition.agent_id,
                        transition.resource_cost,
                        reason="action_cost",
                        source_action_id=transition.action_id,
                    )
                    tx.resource_delta_ids.extend(d.delta_id for d in deltas)

                if cooldown_service and transition.cooldown_ticks > 0:
                    cooldown_service.set_cooldown(
                        transition.agent_id,
                        transition.action_id,
                        "action",
                        transition.cooldown_ticks + 1,
                    )

                if transition.location_to:
                    if not location_registry or not location_registry.exists(
                        transition.location_to
                    ):
                        raise ValueError(
                            f"unknown_location:{transition.location_to}"
                        )
                    world_state_kernel.set_agent_location(
                        transition.agent_id, transition.location_to
                    )

            tx.status = "committed"
            return tx
        except Exception as exc:
            if resource_service and resource_snapshot is not None:
                resource_service.restore(resource_snapshot)
            if cooldown_service and cooldown_snapshot is not None:
                cooldown_service.restore(cooldown_snapshot)
            state.agent_locations = location_snapshot
            tx.status = "rolled_back"
            tx.errors.append(str(exc))
            raise

    async def execute_tool(
        self,
        action: ActionPack,
        tick: int,
        state: Any,
        tool_def: Optional[Dict[str, Any]] = None,
        runtime_mode: str = "entertainment",
    ) -> Optional[ToolRunResult]:
        """执行工具：sandbox 代码路径或 MCP 外部工具路径。"""
        from app.mcp.tool_executor import (
            execute_mcp_tool,
            resolve_tool_id,
            resolve_tool_type,
        )

        tool_id = (
            resolve_tool_id(action)
            or str((tool_def or {}).get("id") or (tool_def or {}).get("tool_id") or "")
        )
        if not tool_id:
            return None

        rule = dict(tool_def or {})
        tool_type = resolve_tool_type(rule)

        if tool_type == "mcp":
            if str(runtime_mode).strip().lower() == "benchmark":
                run_id = f"tool_run_{tick}_{action.agent_id}_{tool_id}"
                return ToolRunResult(
                    run_id=run_id,
                    tool_id=tool_id,
                    owner_id=action.agent_id,
                    tick=tick,
                    ok=False,
                    source="mcp",
                    errors=["mcp_disabled_in_benchmark"],
                )
            run_result = await execute_mcp_tool(
                action=action,
                tick=tick,
                tool_def=rule,
                evidence_service=self._evidence_service,
            )
            run_result.source = "mcp"
            self._tool_runs.append(run_result)
            logger.info(
                f"[L4] MCP 工具执行: {tool_id} ok={run_result.ok} "
                f"evidence_candidates={len(run_result.evidence_candidate_ids)}"
            )
            return run_result

        attached = action.attached_tool_id or tool_id
        code = (action.code or "").strip()
        code_source = "inline"
        tr = action.tool_request or {}
        run_path = (
            tr.get("workspace_run")
            or tr.get("workspace_path")
            or tr.get("run_path")
        )
        if not code and run_path:
            ws = self._workspaces.get(action.agent_id) if self._workspaces else None
            if ws is None:
                run_id = f"tool_run_{tick}_{action.agent_id}_{attached}"
                return ToolRunResult(
                    run_id=run_id,
                    tool_id=attached,
                    owner_id=action.agent_id,
                    tick=tick,
                    ok=False,
                    source="workspace",
                    errors=["workspace_not_found"],
                )
            try:
                code = ws.read_code_file(str(run_path)).strip()
                code_source = f"workspace:{run_path}"
            except Exception as exc:
                run_id = f"tool_run_{tick}_{action.agent_id}_{attached}"
                return ToolRunResult(
                    run_id=run_id,
                    tool_id=attached,
                    owner_id=action.agent_id,
                    tick=tick,
                    ok=False,
                    source="workspace",
                    errors=[f"workspace_read_failed: {exc}"],
                )

        if not code and attached and isinstance(tr, dict):
            run_id = f"tool_run_{tick}_{action.agent_id}_{attached}"
            run_result = ToolRunResult(
                run_id=run_id,
                tool_id=attached,
                owner_id=action.agent_id,
                tick=tick,
                ok=True,
                outputs=[{
                    "summary": (
                        "已记录研究需求，但尚未产生外部数据。"
                        "下一步需要真正调用数据源，或运行能返回结果的分析脚本。"
                    ),
                    "request": {
                        k: v for k, v in tr.items()
                        if k not in {"api_key", "secret", "token"}
                    },
                    "next_step_hint": (
                        "如果要真正获取数据，请选择已发现的外部数据工具，"
                        "或写入并运行分析脚本。"
                    ),
                }],
                source="tool_request",
            )
            self._tool_runs.append(run_result)
            logger.info(
                f"[L4] 工具申请已记录: {attached} agent={action.agent_id}"
            )
            return run_result

        if not code or not attached:
            return None
        if not self._sandbox:
            logger.warning(f"[L4] 沙盒未配置，跳过工具执行 agent={action.agent_id}")
            return None

        tool_id = attached
        run_id = f"tool_run_{tick}_{action.agent_id}_{tool_id}"
        exec_source = "workspace" if run_path and not (action.code or "").strip() else "sandbox"

        try:
            result = await self._sandbox.run_code(
                code=code,
                context={
                    "agent_id": action.agent_id,
                    "tick": tick,
                    "tool_id": tool_id,
                    "target_object_id": action.target_object_id,
                    "code_source": code_source,
                },
            )

            outputs = result.get("outputs", []) if isinstance(result, dict) else []
            evidence_created = result.get("evidence_created", []) if isinstance(result, dict) else []
            errors = result.get("errors", []) if isinstance(result, dict) else []

            # Tool→Evidence 标准化：为每个 evidence_created 字符串生成标准 EvidenceEntry
            evidence_candidate_ids: List[str] = []
            if self._evidence_service and evidence_created:
                for raw_eid in evidence_created:
                    entry = self._evidence_service.create(
                        creator_id=action.agent_id,
                        target_id=action.target_object_id,
                        claim=f"工具 {tool_id} 产生证据: {raw_eid}",
                        source_tool_id=tool_id,
                        supporting_event_ids=[],
                        confidence=0.6,
                    )
                    evidence_candidate_ids.append(entry.evidence_id)

            # 为每个 output 也生成 EvidenceEntry（输出即证据）
            if self._evidence_service and outputs:
                for i, output in enumerate(outputs):
                    claim_text = str(output.get("claim", output.get("summary", f"tool_output_{i}")))
                    entry = self._evidence_service.create(
                        creator_id=action.agent_id,
                        target_id=action.target_object_id,
                        claim=f"工具 {tool_id} 输出: {claim_text}",
                        source_tool_id=tool_id,
                        supporting_event_ids=[],
                        confidence=0.5,
                    )
                    evidence_candidate_ids.append(entry.evidence_id)

            run_result = ToolRunResult(
                run_id=run_id,
                tool_id=tool_id,
                owner_id=action.agent_id,
                tick=tick,
                ok=not errors,
                outputs=outputs,
                evidence_created=evidence_created,
                evidence_candidate_ids=evidence_candidate_ids,
                trace_delta=0.1,
                errors=errors,
                source=exec_source,
            )
            self._tool_runs.append(run_result)
            logger.info(
                f"[L4] 工具执行完成: {tool_id} ok={run_result.ok} "
                f"evidence_candidates={len(evidence_candidate_ids)}"
            )
            return run_result

        except Exception as e:
            run_result = ToolRunResult(
                run_id=run_id,
                tool_id=tool_id,
                owner_id=action.agent_id,
                tick=tick,
                ok=False,
                errors=[str(e)],
                source="sandbox",
            )
            self._tool_runs.append(run_result)
            logger.warning(f"[L4] 工具执行失败: {tool_id}: {e}")
            return run_result

    def maybe_deploy_artifact(
        self,
        action: ActionPack,
        tick: int,
        state: Any,
        tool_result: Optional[ToolRunResult],
    ) -> Optional[Any]:
        """Agent 显式请求"上线"时，把工具代码注册为常驻 Artifact。

        触发条件（全部满足）：
        - 本回合工具一次性运行成功（tool_result.ok）
        - 携带 attached_tool_id（或 tool_request.tool_id）及可解析源码
          （inline code 或工作区 workspace_deploy / workspace_run 路径）
        - tool_request 中 deploy 为真（agent 主动选择上线，而非仅测试）

        常驻 Artifact 由 execute_artifacts() 每回合在沙盒中运行（emit_event）。
        从工作区部署时写入 workspace_path，后续每 tick 重载最新脚本。
        受 max_artifacts_per_agent 上限约束；同一 (owner, tool_id) 重复上线视为更新代码。
        """
        if tool_result is None or not getattr(tool_result, "ok", False):
            return None
        tr = action.tool_request or {}
        if not (isinstance(tr, dict) and tr.get("deploy")):
            return None

        tool_id = str(action.attached_tool_id or tr.get("tool_id") or "").strip()
        if not tool_id:
            return None

        from app.agent_os.workspace_ops import resolve_artifact_code

        ws = self._workspaces.get(action.agent_id) if self._workspaces else None
        code, workspace_path, resolve_errors = resolve_artifact_code(
            inline_code=action.code or "",
            agent_id=action.agent_id,
            tool_request=tr,
            workspace=ws,
        )
        if not code:
            if resolve_errors:
                logger.info(
                    f"[L4] {action.agent_id} 部署 {tool_id} 失败: "
                    f"{'; '.join(resolve_errors)}"
                )
            return None

        artifacts = getattr(state, "artifacts", None)
        if artifacts is None:
            return None

        artifact_id = f"artifact_{action.agent_id}_{tool_id}"
        if artifact_id in artifacts:
            art = artifacts[artifact_id]
            art.code = code
            art.is_active = True
            art.workspace_path = workspace_path
            if tr.get("purpose"):
                art.description = str(tr.get("purpose"))[:120]
            logger.info(
                f"[L4] 工具重新上线（更新代码）: {artifact_id}"
                + (f" from {workspace_path}" if workspace_path else "")
            )
            return art

        cap = 3
        cfg = getattr(self._sandbox, "_cfg", None)
        if cfg is not None:
            cap = int(getattr(cfg, "max_artifacts_per_agent", 3))
        owned = sum(1 for a in artifacts.values() if a.owner_id == action.agent_id)
        if owned >= cap:
            logger.info(
                f"[L4] {action.agent_id} 已达 artifact 上限 {cap}，"
                f"拒绝上线 {tool_id}"
            )
            return None

        from app.core.interfaces import Artifact
        art = Artifact(
            artifact_id=artifact_id,
            owner_id=action.agent_id,
            name=tool_id,
            description=str(tr.get("purpose") or "")[:120],
            code=code,
            artifact_type="algorithm",
            tick_created=tick,
            workspace_path=workspace_path,
        )
        artifacts[artifact_id] = art
        logger.info(
            f"[L4] 工具上线: {artifact_id} owner={action.agent_id}"
            + (f" workspace={workspace_path}" if workspace_path else "")
        )
        return art

    async def execute_artifacts(
        self,
        state: Any,
        sandbox: Any = None,
    ) -> List[RuntimeSignal]:
        """执行所有 active artifact（旧接口兼容）"""
        events: List[RuntimeSignal] = []
        _sandbox = sandbox or self._sandbox
        if not _sandbox:
            return events
        for artifact in list(getattr(state, "artifacts", {}).values()):
            if not artifact.is_active:
                continue
            if artifact.workspace_path and self._workspaces:
                ws = self._workspaces.get(artifact.owner_id)
                if ws is not None:
                    try:
                        artifact.code = ws.read_code_file(
                            artifact.workspace_path
                        ).strip()
                    except Exception as exc:
                        events.append(RuntimeSignal(
                            tick=state.tick,
                            event_type="artifact_error",
                            source_id=artifact.owner_id,
                            is_public=False,
                            summary=(
                                f"工具 {artifact.name} 工作区重载失败 "
                                f"({artifact.workspace_path}): {exc}"
                            ),
                        ))
                        continue
            try:
                result_events = await _sandbox.run(artifact, state)
                artifact.last_triggered_tick = state.tick
                artifact.trigger_count += 1
                events.extend(result_events)
            except Exception as e:
                events.append(RuntimeSignal(
                    tick=state.tick,
                    event_type="artifact_error",
                    source_id=artifact.owner_id,
                    is_public=False,
                    summary=f"工具 {artifact.name} 执行失败: {e}",
                ))
        return events

    @property
    def tool_runs(self) -> List[ToolRunResult]:
        return list(self._tool_runs)
