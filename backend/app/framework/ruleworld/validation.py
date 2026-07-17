"""
ActionValidityGate：行动进入 CausalPhysicsEngine 前的合法性闸门

校验顺序：
  1. target_object_id 是否存在（required by physics）
  2. force_vector 是否有实质内容
  3. intent 是否有效（unknown → penalize）
  4. 行动点（action_points）是否充足
  5. 资源（弱校验，不强依赖场景结构）

校验结果：
  valid + allow_physics=True  → 正常进入物理
  allowed_but_penalized       → 带惩罚进入物理
  invalid + allow_physics=False → 不进入物理
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.core.interfaces import ActionEvaluation, ActionValidationResult


# 最低 force_vector 总量阈值（低于此值视为行动力不足）
_MIN_FORCE_TOTAL = 2.0
# unknown intent 的行动力惩罚系数
_UNKNOWN_INTENT_MULTIPLIER = 0.7
# 默认行动点（state 中没有 action_points 时使用）
_DEFAULT_ACTION_POINTS = 10


class ActionValidityGate:
    """
    无状态校验器：给定 ActionEvaluation，返回 ActionValidationResult。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}

    def validate(
        self,
        evaluation: ActionEvaluation,
        state=None,
        objects=None,
        pressure_engine=None,   # P2: PressureEngine（可选，优先于 state.internal）
        action_rule: Optional[Dict[str, Any]] = None,
    ) -> ActionValidationResult:
        reasons: List[str] = []
        warnings: List[str] = []
        force_multiplier = 1.0
        risk_multiplier = 1.0
        resource_penalty = 0.0
        allow_physics = True
        status = "valid"

        rule = action_rule or {}
        target_kind = str(rule.get("target_kind", "object") or "object")

        # ── 1. 按目标类型校验 ─────────────────────────────────────────────
        # location / agent / evidence 各自由对应底座服务在 L4 校验，
        # 不能再拿地点 ID 或角色 ID 去世界对象注册表中查找。
        obj_id = evaluation.target_object_id
        if obj_id and target_kind in ("object", "evidence"):
            if objects is not None:
                try:
                    target_object = objects.get(obj_id)
                    allowed_types = set(rule.get("target_types", []) or [])
                    if (
                        allowed_types
                        and "object" not in allowed_types
                        and target_object.type not in allowed_types
                    ):
                        reasons.append(
                            f"target_type_not_allowed:{target_object.type}"
                        )
                        allow_physics = False
                        status = "invalid"
                except KeyError:
                    reasons.append(f"target_object_not_found:{obj_id}")
                    allow_physics = False
                    status = "invalid"
        # target_object 不存在也允许通过（无对象的行动可以走 agent 间交互路径）
        # 但 physics 管道中若无对象，delta 为空

        # ── 2. force_vector 是否有实质内容 ────────────────────────────────
        force_total = sum(abs(v) for v in (evaluation.force_vector or {}).values())
        if force_total < _MIN_FORCE_TOTAL:
            reasons.append("empty_force_vector")
            allow_physics = False
            status = "invalid"

        # 后续检查只在 allow_physics 仍为 True 时进行
        if allow_physics:
            # ── 3. intent 有效性 ─────────────────────────────────────────
            if evaluation.intent == "unknown":
                warnings.append("unknown_intent:force_reduced")
                force_multiplier *= _UNKNOWN_INTENT_MULTIPLIER
                status = "allowed_but_penalized"

            # ── 4 & 5. 压力引擎检查（P2：优先于 state.internal）──────────
            if pressure_engine is not None:
                pmods = pressure_engine.compute_validation_modifiers(evaluation.agent_id)
                if not pmods["allow_physics"]:
                    reasons.extend(pmods["reasons"])
                    allow_physics = False
                    status = "invalid"
                else:
                    # 叠加压力系数
                    force_multiplier = round(force_multiplier * pmods["force_multiplier"], 4)
                    risk_multiplier = round(risk_multiplier * pmods["risk_multiplier"], 4)
                    if pmods["warnings"]:
                        warnings.extend(pmods["warnings"])
                        if status == "valid":
                            status = "allowed_but_penalized"
            else:
                # ── 4. 行动点检查（旧路径，无 pressure_engine 时使用）────
                if state is not None:
                    ap = state.internal.get("action_points", {})
                    agent_ap = ap.get(evaluation.agent_id, _DEFAULT_ACTION_POINTS)
                    if agent_ap <= 0:
                        reasons.append("no_action_points")
                        allow_physics = False
                        status = "invalid"

                # ── 5. 资源弱校验（旧路径）───────────────────────────────
                if allow_physics and evaluation.estimated_cost > 0 and state is not None:
                    resources = state.internal.get("resources", {})
                    agent_res = resources.get(evaluation.agent_id, 9999.0)
                    if evaluation.estimated_cost > agent_res * 2:
                        warnings.append(
                            f"insufficient_resource:cost={evaluation.estimated_cost:.0f}"
                            f",available={agent_res:.0f}"
                        )
                        force_multiplier *= max(0.3, agent_res / evaluation.estimated_cost)
                        resource_penalty = max(0.0, evaluation.estimated_cost - agent_res)
                        if status == "valid":
                            status = "allowed_but_penalized"

        valid = allow_physics and status != "invalid"
        if not allow_physics:
            valid = False
            if status == "valid":
                status = "invalid"

        val_id = f"val_{evaluation.tick}_{evaluation.agent_id}_{int(time.time() * 1000) % 10000:04d}"
        return ActionValidationResult(
            validation_id=val_id,
            tick=evaluation.tick,
            agent_id=evaluation.agent_id,
            action_id=evaluation.action_id,
            evaluation_id=evaluation.evaluation_id,
            valid=valid,
            status=status,
            reasons=reasons,
            warnings=warnings,
            force_multiplier=round(force_multiplier, 4),
            risk_multiplier=round(risk_multiplier, 4),
            resource_penalty=round(resource_penalty, 2),
            allow_physics=allow_physics,
            metadata={
                "target_kind": target_kind,
                "allowed_target_types": list(
                    rule.get("target_types", []) or []
                ),
            },
        )
