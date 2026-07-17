"""
ForceBudgetCalculator：行动力预算约束

防止 Agent 靠长篇大论堆叠出无限 force_vector。
每回合行动力有上限（force_budget），超出部分按比例压缩。

预算来源（P1.5 版本）：
  base_budget            = 30（默认）
  resource_bonus         = min(estimated_cost × 0.5, 20)
  tool_bonus             = 0（P2 接入）
  evidence_bonus         = 0（P2 接入）
  validation_multiplier  = validation.force_multiplier

后续 P2 可扩展 tool_bonus / evidence_bonus。
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from app.core.interfaces import ActionEvaluation, ActionValidationResult, ForceBudgetResult


# 默认基础预算（无任何加成时，agent 最多能发出 30 点力）
_DEFAULT_BASE_BUDGET = 30.0
# 资源→力 转化率
_RESOURCE_TO_FORCE_RATE = 0.5
# 资源加成上限
_MAX_RESOURCE_BONUS = 20.0


class ForceBudgetCalculator:
    """
    计算本回合 force_budget，如超出则等比例压缩 force_vector。
    """

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        self._config = config or {}
        self._base_budget: float = float(
            self._config.get("default_force_budget", _DEFAULT_BASE_BUDGET)
        )

    def calculate(
        self,
        evaluation: ActionEvaluation,
        validation: ActionValidationResult,
        state=None,
        pressure_engine=None,   # P2: PressureEngine（可选）
        evidence_bonus: float = 0.0,  # P3: 工具净价值转化的预算加成
    ) -> ForceBudgetResult:
        force = evaluation.force_vector or {}
        force_total = sum(abs(v) for v in force.values())

        # ── 预算计算 ─────────────────────────────────────────────────────
        base = self._base_budget

        # P2：优先从压力引擎获取资源加成（反映实际资源池）
        if pressure_engine is not None:
            pmods = pressure_engine.compute_budget_modifiers(evaluation.agent_id)
            resource_bonus = pmods["resource_budget_bonus"]
        else:
            # 旧路径：从 estimated_cost 推断
            resource_bonus = min(
                evaluation.estimated_cost * _RESOURCE_TO_FORCE_RATE,
                _MAX_RESOURCE_BONUS,
            )
        tool_bonus = 0.0   # 保留扩展槽

        raw_budget = base + resource_bonus + tool_bonus + evidence_bonus

        # 乘以 validation 的 force_multiplier（惩罚系数）
        budget = raw_budget * validation.force_multiplier

        budget_sources = {
            "base": round(base, 2),
            "resource_bonus": round(resource_bonus, 2),
            "tool_bonus": round(tool_bonus, 2),
            "evidence_bonus": round(evidence_bonus, 2),
            "validation_multiplier": round(validation.force_multiplier, 4),
        }

        # ── 压缩 force_vector ────────────────────────────────────────────
        scaled = False
        scale_ratio = 1.0
        if force_total > budget and force_total > 0:
            scale_ratio = budget / force_total
            adjusted = {k: round(v * scale_ratio, 3) for k, v in force.items()}
            scaled = True
        else:
            adjusted = dict(force)

        budget_id = (
            f"budget_{evaluation.tick}_{evaluation.agent_id}"
            f"_{int(time.time() * 1000) % 10000:04d}"
        )
        return ForceBudgetResult(
            budget_id=budget_id,
            tick=evaluation.tick,
            agent_id=evaluation.agent_id,
            action_id=evaluation.action_id,
            evaluation_id=evaluation.evaluation_id,
            original_force_total=round(force_total, 2),
            force_budget=round(budget, 2),
            scaled=scaled,
            scale_ratio=round(scale_ratio, 4),
            budget_sources=budget_sources,
            adjusted_force_vector=adjusted,
        )
