"""
RuleWorldContext：规则世界服务容器

ruleworld_mode=true 时由引擎自动创建，注入给 World 实例。
场景层通过此容器访问所有引擎服务，禁止绕过它直接修改 state。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List

logger = logging.getLogger(__name__)


class RuleWorldContext:
    """
    持有所有规则世界服务引用的容器。
    由 FrameworkEngine 在 ruleworld_mode=True 时创建并注入给 World。
    """

    def __init__(self, scenario: Any):
        from app.framework.ruleworld.objects import WorldObjectRegistry
        from app.framework.ruleworld.deltas import StateDeltaService
        from app.framework.ruleworld.evidence import EvidenceService
        from app.framework.ruleworld.action_evaluator import ActionEvaluator
        from app.framework.ruleworld.physics import CausalPhysicsEngine

        # 从 scenario 获取 objects 配置
        objects_cfg: List[Dict[str, Any]] = []
        if hasattr(scenario, "objects_cfg") and scenario.objects_cfg:
            objects_cfg = scenario.objects_cfg
        elif isinstance(scenario.world_config.get("objects"), list):
            objects_cfg = scenario.world_config["objects"]

        self.objects = WorldObjectRegistry(objects_cfg)
        self.deltas = StateDeltaService(self.objects)
        self.evidence = EvidenceService()

        # P1 新增：因果物理闭环服务
        self._actions_cfg = self._get_actions_cfg(scenario)
        self._action_map = {
            item.get("id", ""): item
            for item in self._actions_cfg
            if isinstance(item, dict) and item.get("id")
        }
        self.evaluator = ActionEvaluator(config={"actions_cfg": self._actions_cfg})
        physics_cfg = {}
        if hasattr(scenario, "causal_physics_config"):
            physics_cfg = scenario.causal_physics_config or {}
        elif hasattr(scenario, "world_config"):
            physics_cfg = scenario.world_config.get("causal_physics") or {}
        self.physics = CausalPhysicsEngine(physics_cfg)

        # P1.5：闸门与预算服务
        from app.framework.ruleworld.validation import ActionValidityGate
        from app.framework.ruleworld.budget import ForceBudgetCalculator
        self.validity_gate = ActionValidityGate()
        self.budget_calc = ForceBudgetCalculator()

        # P2：压力引擎（压力模型由场景包声明，OS 只按通用 kind 执行）
        from app.contracts.pressure_model import model_from_pressure_cfg
        from app.framework.pressure.engine import PressureEngine
        pressure_cfg: Dict[str, Any] = {}
        if hasattr(scenario, "world_config"):
            pressure_cfg = scenario.world_config.get("pressure_cfg") or {}
        self.pressure = PressureEngine(
            pressure_cfg=pressure_cfg,
            model=model_from_pressure_cfg(pressure_cfg),
        )

        # P6：Run 记录器
        from app.framework.recording.recorder import RunRecorder
        scenario_name = getattr(scenario.manifest, "name", "unknown") if hasattr(scenario, "manifest") else "unknown"
        self.recorder = RunRecorder(scenario_name=scenario_name)

        # metrics 服务需要 state，延迟初始化（在 world.initialize 之后注入）
        self.metrics = None  # type: ignore
        self._current_tick: int = 0

        # audit_cfg
        self._audit_cfg: Dict[str, Any] = {}
        if hasattr(scenario, "audit_cfg"):
            self._audit_cfg = scenario.audit_cfg or {}

        # tools_cfg：可用工具定义（给 agent 感知包用）
        self._tools_cfg: List[Dict[str, Any]] = []
        if hasattr(scenario, "tools_cfg"):
            self._tools_cfg = scenario.tools_cfg or []

        # P1：metric_derivation_rules（来自 world/metrics.yaml → world_config["metrics_cfg"]）
        self._metric_rules: List[Dict[str, Any]] = []
        self._metric_definitions: List[Dict[str, Any]] = []
        if hasattr(scenario, "world_config"):
            metrics_cfg = scenario.world_config.get("metrics_cfg") or {}
            if isinstance(metrics_cfg, dict):
                self._metric_rules = metrics_cfg.get("metric_derivations", [])
                self._metric_definitions = metrics_cfg.get("metrics", [])
            elif isinstance(metrics_cfg, list):
                self._metric_rules = metrics_cfg

        # 行动账本：记录每次 pipeline 的 ActionPack（供 export_ledgers 使用）
        self._action_ledger: List[Dict[str, Any]] = []

    @staticmethod
    def _get_actions_cfg(scenario) -> List[Dict[str, Any]]:
        """从 scenario.world_config 提取 actions 配置"""
        compiled = getattr(scenario, "compiled", None)
        if compiled is not None:
            return list(compiled.action_index.values())
        if hasattr(scenario, "world_config"):
            raw = scenario.world_config.get("actions") or []
            if isinstance(raw, list):
                return raw
        return []

    def set_judge(self, judge: Any, **opts: Any) -> None:
        """注入 L5 行动评价 LLM Judge（由引擎在构建 director_provider 后调用）。"""
        self.evaluator.set_judge(judge, **opts)

    @property
    def actions_cfg(self) -> List[Dict[str, Any]]:
        return self._actions_cfg if hasattr(self, "_actions_cfg") else []

    def get_action_rule(self, action_id: str) -> Dict[str, Any]:
        return self._action_map.get(action_id, {})

    def bind_state(self, state) -> None:
        """world.initialize() 之后调用，绑定 WorldState 给 MetricDerivationService。"""
        from app.framework.ruleworld.metrics import MetricDerivationService
        self.metrics = MetricDerivationService(state)
        self.metrics.set_tick(self._current_tick)
        self.metrics.initialize_agents(
            getattr(state, "agent_ids", []) or [],
            self._metric_definitions,
        )
        # P2：注册已知 Agent 的初始压力状态
        agent_ids = getattr(state, "agent_ids", []) or []
        if agent_ids:
            self.pressure.register_agents(agent_ids)
        # P6：记录 Agent 列表
        if agent_ids:
            self.recorder.set_agents(agent_ids)

    def advance_tick(self, tick: int) -> None:
        """每 tick 开始时由引擎调用，推进所有服务的时间基准。"""
        self._current_tick = tick
        self.deltas.set_tick(tick)
        self.evidence.set_tick(tick)
        if self.metrics is not None:
            self.metrics.set_tick(tick)
        # P2 压力已由 EngineOS._tick 统一调用（含游戏资源同步）

    def export_ledgers(self) -> Dict[str, Any]:
        """返回所有账本数据，供运营台/审计使用。"""
        return {
            "action": list(self._action_ledger),   # 行动账本（从 pipeline 记录的 ActionPack）
            "state_delta": [e.model_dump() for e in self.deltas.ledger],
            "metric_derivation": [e.model_dump() for e in (self.metrics.ledger if self.metrics else [])],
            "evidence": [e.model_dump() for e in self.evidence.ledger],
            # 工具运行账本已由引擎直接从 ActionRuntime.tool_runs 传给 RunRecorder，
            # 不再经此容器中转（原 ToolService 版本从未被调用，账本恒空，已移除）。
            # P2：压力状态快照
            "pressure": self.pressure.snapshot(),
            # P4：能力快照（需要 state，export_ledgers 无 state 参数，故此处暂留空；
            #    RunRecorder.record_tick 直接读 state.internal["capabilities"]）
        }

    async def run_causal_pipeline(
        self,
        action,
        tick: int,
        state=None,
        tool_result=None,
    ):
        """
        P1.5 因果闭环完整管线（策略 A：场景 world.py 主动调用）。

        管线顺序：
          1. ActionEvaluator.evaluate()
          2. ActionValidityGate.validate()
          3. invalid → 返回 outcome=invalid（不进入物理）
          4. ForceBudgetCalculator.calculate()
          5. CausalPhysicsEngine.propose_delta()
          6. StateDeltaService.apply_proposal()
          7. proposal.outcome != no_effect → MetricDerivationService.derive_from_delta()
          8. CausalSequenceBuilder.build()
          9. 返回 CausalPipelineResult

        返回：CausalPipelineResult
        """
        from app.core.interfaces import CausalPipelineResult
        from app.framework.presentation.causal_sequence import CausalSequenceBuilder

        action_id = f"act_{tick}_{action.agent_id}"

        try:
            # 1. 行动评价（传入 actions.yaml 规则）
            action_rule = self.get_action_rule(action.action_id or action.intent or "")
            evaluation = await self.evaluator.evaluate(action, tick, state, self.objects, action_rule=action_rule)

            # 2. 合法性校验（P2：传入压力引擎）
            validation = self.validity_gate.validate(
                evaluation, state, self.objects,
                pressure_engine=self.pressure,
                action_rule=action_rule,
            )

            # 3. 非法 → 提前返回（AP 由游戏资源系统管理）
            if not validation.allow_physics:
                self.pressure.consume_action_point(action.agent_id, 1.0)
                seq = CausalSequenceBuilder().build(
                    action=action, evaluation=evaluation,
                    delta_entries=[], metric_entries=[],
                    tick=tick, validation=validation,
                )
                return CausalPipelineResult(
                    tick=tick, action_id=action_id, agent_id=action.agent_id,
                    action=action,
                    evaluation=evaluation, validation=validation,
                    sequence=seq, outcome="invalid",
                )

            # 工具成功执行时给予的支撑力加成（直接来自 L4 tool_result；
            # 原 toolimpact 待回填归因链从未被 register()，已移除）。
            evidence_bonus = 0.0
            if tool_result is not None and getattr(tool_result, "ok", False):
                # 工具成功：按工具输出质量给予支撑力加成
                tool_evidence_bonus = 0.1  # 基础加成
                if getattr(tool_result, "outputs", None):
                    tool_evidence_bonus += min(0.2, len(tool_result.outputs) * 0.05)
                if getattr(tool_result, "evidence_created", None):
                    tool_evidence_bonus += min(0.2, len(tool_result.evidence_created) * 0.05)
                evidence_bonus += tool_evidence_bonus

            # 4. 行动力预算（P2：传入压力引擎，P3：传入 evidence_bonus）
            budget = self.budget_calc.calculate(
                evaluation, validation, state,
                pressure_engine=self.pressure,
                evidence_bonus=evidence_bonus,
            )

            # 5. 找到目标对象并做物理结算
            delta_entries = []
            metric_entries = []
            proposal = None
            target_kind = str(action_rule.get("target_kind", "object") or "object")

            obj_id = action.target_object_id or evaluation.target_object_id
            if target_kind == "agent":
                obj_id = action_rule.get("interaction_object_id")
            if obj_id and target_kind in ("object", "evidence", "agent"):
                # 模糊匹配：如果精确匹配失败，尝试在所有对象中找最接近的
                try:
                    world_obj = self.objects.get(obj_id)
                except KeyError:
                    world_obj = self._fuzzy_match_object(obj_id)
                    if world_obj:
                        logger.info(f"[L5] 模糊匹配对象: {obj_id} → {world_obj.id}")
                if world_obj:
                    try:
                        proposal = self.physics.propose_delta(
                            evaluation, world_obj,
                            validation=validation,
                            budget=budget,
                        )
                        # 6. 落账（含 no_effect）
                        delta_entry = self.deltas.apply_proposal(proposal)
                        delta_entries.append(delta_entry)
                        # 7. 派生指标（no_effect 时 derive_from_delta 内部自动跳过）
                        if self.metrics and self._metric_rules:
                            derived = self.metrics.derive_from_delta(delta_entry, self._metric_rules)
                            metric_entries.extend(derived)
                    except Exception as e:
                        logger.warning(f"[L5] 物理结算异常 obj={world_obj.id}: {e}")

            # 8. 构建因果链
            seq = CausalSequenceBuilder().build(
                action=action, evaluation=evaluation,
                delta_entries=delta_entries, metric_entries=metric_entries,
                tick=tick, validation=validation, budget=budget, proposal=proposal,
            )

            # 9. 判断 outcome
            if target_kind == "location":
                # 地点变化已在 L4 原子事务中提交；这里把它记录为成功的平台效果，
                # 不再伪造世界对象 StateDelta。
                pipeline_outcome = "success"
            elif target_kind == "agent" and proposal is None:
                # 角色交互若没有声明承载世界后果的 interaction_object_id，
                # 仍由关系/压力服务结算，但不会伪造对象变化。
                pipeline_outcome = "success"
            elif proposal is None:
                # 检查 action 是否要求有目标对象
                requires_target = action_rule.get("requires_target", False)
                obj_id = action.target_object_id or evaluation.target_object_id
                if requires_target and not obj_id:
                    pipeline_outcome = "invalid"
                else:
                    pipeline_outcome = "no_effect"  # 无对象的行动（wait/speak）→ 不产生 delta
            elif proposal.outcome == "no_effect":
                pipeline_outcome = "no_effect"
            elif proposal.outcome == "negative":
                pipeline_outcome = "backlash"
            else:
                pipeline_outcome = "success"

            final_result = CausalPipelineResult(
                tick=tick, action_id=action_id, agent_id=action.agent_id,
                action=action,
                evaluation=evaluation, validation=validation,
                budget=budget, proposal=proposal,
                deltas=delta_entries, metrics=metric_entries,
                sequence=seq, outcome=pipeline_outcome,
            )
            if final_result.validation is not None:
                final_result.validation.metadata.update({
                    "target_kind": target_kind,
                    "settlement_route": (
                        "platform_location"
                        if target_kind == "location"
                        else (
                            "world_object"
                            if target_kind in ("object", "evidence")
                            else f"platform_{target_kind}"
                        )
                    ),
                })

            # P2：管线末尾更新压力状态（消耗 AP/资源，累积风险，发出反制信号）
            self.pressure.apply_pipeline_result(final_result)

            # 记录行动账本（供 export_ledgers 使用）
            if action is not None:
                self._action_ledger.append({
                    "action_id": action_id,
                    "tick": tick,
                    "actor_id": action.agent_id,
                    "action_type": getattr(action, "action_id", "") or getattr(action, "intent", "unknown"),
                    "target_object_id": getattr(action, "target_object_id", None),
                    "target_agent_id": getattr(action, "target_agent_id", None),
                    "raw_text": getattr(action, "text", ""),
                    "parsed_plan": {},
                    "execution_quality": evaluation.execution_quality if evaluation else 0.0,
                    "legality": "ok" if (validation and validation.valid) else "invalid",
                    "result_event_ids": [],
                })

            return final_result

        except Exception as e:
            import logging
            logging.getLogger(__name__).error(f"[pipeline] 异常 agent={action.agent_id}: {e}", exc_info=True)
            return CausalPipelineResult(
                tick=tick, action_id=action_id, agent_id=action.agent_id,
                outcome="error", errors=[str(e)],
            )

    @property
    def tools_cfg(self) -> List[Dict[str, Any]]:
        """返回场景声明的可用工具定义列表（供感知包注入给 agent）。"""
        return self._tools_cfg

    def _fuzzy_match_object(self, raw_id: str) -> Optional[Any]:
        """模糊匹配世界对象：精确/子串/关键词重叠/中文名称四级匹配"""
        if not raw_id:
            return None
        raw_lower = raw_id.lower().strip()
        all_ids = self.objects.all_ids()
        # 1. 精确匹配（大小写不敏感）
        for oid in all_ids:
            if oid.lower() == raw_lower:
                return self.objects.get(oid)
        # 2. 子串匹配
        for oid in all_ids:
            if raw_lower in oid.lower() or oid.lower() in raw_lower:
                return self.objects.get(oid)
        # 3. 关键词重叠
        raw_words = set(raw_lower.replace("_", " ").split())
        best_match = None
        best_score = 0
        for oid in all_ids:
            oid_words = set(oid.lower().replace("_", " ").split())
            overlap = len(raw_words & oid_words)
            if overlap > best_score:
                best_score = overlap
                best_match = self.objects.get(oid)
        if best_score > 0:
            return best_match
        # 4. 中文名称匹配：LLM 可能返回了中文名而非英文 id
        for oid in all_ids:
            obj = self.objects.get(oid)
            obj_name = getattr(obj, "label", "") or getattr(obj, "name", "")
            if obj_name and raw_id.strip() == obj_name.strip():
                return obj
        return None
