"""
CausalPhysicsEngine：行动评价 × 世界对象 → StateDeltaProposal

P1.5 升级：
  - 接受 validation（force_multiplier / risk_multiplier）和 budget（adjusted_force_vector）
  - 加入 intent_multiplier（来自对象的 intent_effects）
  - 支持 no_effect（低匹配 / 低影响）
  - 支持 negative / backlash（risk_side_effect 超过 effective_impact，或 intent 反噬）

三类输出：
  positive  → StateDelta progress 上升
  no_effect → StateDelta before == after（但仍落账）
  negative  → StateDelta progress 下降（反噬）

不直接修改任何对象。
"""
from __future__ import annotations

import time
from typing import Any, Dict, Optional

from app.core.interfaces import (
    ActionEvaluation,
    ActionValidationResult,
    ForceBudgetResult,
    StateDeltaProposal,
)
from app.framework.objects import WorldObjectRuntime


# force_vector 各维度的满分（能力维度 0-100），用于把力归一到 [0,1]
_FORCE_SCALE = 100.0

# 无效阈值
# match_score：力在对象需求维度上的"加权满足度"，0~1。1.0=所有所需维度满力命中
# core_delta：净影响 ×100，0.08 对应约 0.08% 对象变化，过滤数值噪声
_MIN_MATCH_THRESHOLD = 0.05
_MIN_DELTA_THRESHOLD = 0.08

# 反噬阈值（标定：反噬应是例外而非常态）
# 旧逻辑 risk_side_effect > effective_impact*1.10 在"有效影响本就微弱"时会让低风险
# 行动被误判反噬 → 世界全是 backlash、指标平躺。改为：风险须既显著(>=floor)
# 又明确(以绝对 margin)压过有效影响，才触发反噬。
_BACKLASH_MIN_RISK = 0.12
_BACKLASH_MARGIN = 0.08


class CausalPhysicsEngine:
    """无状态计算引擎。给定评价 + 对象（+ 可选 validation/budget），返回 Proposal。"""

    def __init__(self, config: Optional[Dict[str, Any]] = None):
        cfg = config or {}
        self._object_type_profiles = dict(
            cfg.get("object_type_profiles", {}) or {}
        )
        thresholds = cfg.get("thresholds", {}) if isinstance(cfg, dict) else {}
        self._min_match_threshold = float(
            thresholds.get("no_effect_match", _MIN_MATCH_THRESHOLD)
        )
        # 场景包 no_effect 通常表达最终影响阈值；内部 core_delta 为百分制，
        # 因此仅在显式 no_effect_core_delta 时覆盖，避免单位猜测。
        self._min_delta_threshold = float(
            thresholds.get("no_effect_core_delta", _MIN_DELTA_THRESHOLD)
        )
        self._backlash_min_risk = float(
            thresholds.get("backlash_min_risk", _BACKLASH_MIN_RISK)
        )
        self._backlash_margin = float(
            thresholds.get("backlash_margin", _BACKLASH_MARGIN)
        )
        # 三个尺度显式配置，避免把 [0,1] 对象状态、[0,100] 行动力和风险值
        # 混在同一个隐式倍率里。
        self._impact_scale = float(cfg.get("impact_scale", 1.0))
        self._risk_scale = float(cfg.get("risk_scale", 1.0))
        self._core_delta_scale = float(cfg.get("core_delta_scale", 100.0))

    def propose_delta(
        self,
        evaluation: ActionEvaluation,
        world_object: WorldObjectRuntime,
        available_resource: float = 9999.0,
        resource_penalty_rate: float = 0.3,
        validation: Optional[ActionValidationResult] = None,
        budget: Optional[ForceBudgetResult] = None,
    ) -> StateDeltaProposal:

        # ── 确定实际使用的 force_vector ──────────────────────────────────
        # 优先用 budget 压缩后的，其次用 validation 乘后的，最后用原始
        if budget is not None:
            force = budget.adjusted_force_vector
        elif validation is not None and validation.force_multiplier != 1.0:
            force = {k: v * validation.force_multiplier for k, v in (evaluation.force_vector or {}).items()}
        else:
            force = evaluation.force_vector or {}

        type_profile = dict(
            self._object_type_profiles.get(world_object.type, {}) or {}
        )
        profile_needs = type_profile.get("needs")
        needs = (
            {
                str(key): float(value)
                for key, value in profile_needs.items()
            }
            if isinstance(profile_needs, dict) and profile_needs
            else world_object.needs_weights
        )
        needs_total = sum(abs(value) for value in needs.values()) or 1.0
        needs = {
            key: value / needs_total for key, value in needs.items()
        }
        sensitivity = float(
            type_profile.get("sensitivity", world_object.sensitivity)
        )
        resistance = float(
            type_profile.get("resistance", world_object.resistance)
        )
        object_risk = float(type_profile.get("risk", world_object.risk))
        force_total = sum(abs(v) for v in force.values()) or 1.0

        # ── 1. 需求匹配度 ─────────────────────────────────────────────────
        # 力先按满分(_FORCE_SCALE)归一到 [0,1]，再用 needs 权重做加权满足度，
        # 并对 needs 权重总和归一（权重通常 Σ=1，但兜底防止配置不齐）。
        # 旧式 raw_match/force_total 会把"力的总量"当分母，导致 match 被力的
        # 绝对大小稀释、结构性恒在 0.1 量级，再强再准的动作也打水漂。
        needs_weight_total = sum(abs(w) for w in needs.values()) or 1.0
        raw_match = sum(
            (force.get(dim, 0.0) / _FORCE_SCALE) * w for dim, w in needs.items()
        )
        weighted_match = max(0.0, min(1.0, raw_match / needs_weight_total))
        # 峰值命中：动作在对象"主需求维度"（权重≥0.1）上打出的最强单点。
        # 纯加权平均会把单维极强的专精动作稀释在 9 个未命中维度里，数学上
        # 恒输给"十维平庸"的模板——峰值项让"一招打在要害上"重新可行。
        peak_match = max(
            (
                min(force.get(dim, 0.0) / _FORCE_SCALE, 1.0)
                for dim, w in needs.items()
                if w >= 0.1
            ),
            default=0.0,
        )
        match_score = max(
            0.0, min(1.0, 0.6 * weighted_match + 0.4 * peak_match)
        )

        # ── 2. Intent 兼容性倍率 ─────────────────────────────────────────
        intent_multiplier = world_object.get_intent_multiplier(evaluation.intent)
        # intent_multiplier < 0 → 反噬；= 0 → 无效

        # ── 3. 基础力 ─────────────────────────────────────────────────────
        base_force = min(force_total, 100.0) / 100.0

        # ── 4. 质量因子（均值，不连乘）──────────────────────────────────
        # situational_fit（局面契合度，Judge 结合局面摘要评出）参与均值：
        # 同一段模板文本在贴合局面时和无视局面时物理效果不同——这是
        # "临场妙手打得过通用模板"的落账通道。Judge 未评（None）时退回
        # 三项均值，向后兼容。
        fit = getattr(evaluation, "situational_fit", None)
        if fit is not None:
            quality_factor = (
                evaluation.clarity
                + evaluation.execution_quality
                + evaluation.commitment
                + float(fit)
            ) / 4.0
        else:
            quality_factor = (
                evaluation.clarity
                + evaluation.execution_quality
                + evaluation.commitment
            ) / 3.0

        # ── 5. 有效影响 ───────────────────────────────────────────────────
        effective_impact = (
            base_force
            * match_score
            * quality_factor
            * sensitivity
            * (1.0 - resistance)
            * self._impact_scale
        )

        # ── 6. 资源不足惩罚 ───────────────────────────────────────────────
        resource_penalty = 0.0
        if evaluation.estimated_cost > available_resource:
            shortfall = evaluation.estimated_cost - available_resource
            resource_penalty = min(effective_impact * 0.5, shortfall * resource_penalty_rate / 100.0)

        # ── 7. 风险副作用（validation 可放大 risk_multiplier）────────────
        risk_mult = validation.risk_multiplier if validation else 1.0
        risk_side_effect = (
            evaluation.risk_level
            * object_risk
            * (1.0 - evaluation.risk_control)
            * risk_mult
            * self._risk_scale
        )

        # ── 8. 最终核心变化（带 intent 倍率）────────────────────────────
        net_impact = effective_impact - resource_penalty - risk_side_effect
        core_delta = net_impact * intent_multiplier * self._core_delta_scale
        core_delta = round(core_delta, 2)

        # ── 9. 判断 outcome ──────────────────────────────────────────────
        outcome = "positive"
        no_effect_reason: Optional[str] = None
        backlash = False
        backlash_reason: Optional[str] = None

        if intent_multiplier == 0.0:
            # intent 完全被对象排斥
            outcome = "no_effect"
            no_effect_reason = "这类行动意图被该对象排斥，作用不上去"
            core_delta = 0.0
        elif match_score < self._min_match_threshold:
            # 行动维度完全不命中对象需求
            outcome = "no_effect"
            no_effect_reason = (
                f"行动与对象需求的契合度仅 {match_score:.0%}，"
                f"低于生效门槛 {self._min_match_threshold:.0%}——没打中要害"
            )
            core_delta = 0.0
        elif abs(core_delta) < self._min_delta_threshold:
            # 计算出的影响太微弱
            outcome = "no_effect"
            no_effect_reason = (
                f"实际推动幅度仅 {abs(core_delta):.3f}，"
                f"未达生效门槛 {self._min_delta_threshold}——力道太轻，局面纹丝不动"
            )
            core_delta = 0.0
        elif intent_multiplier < 0:
            # intent 的 multiplier 为负 → 反噬
            outcome = "negative"
            backlash = True
            backlash_reason = "这类意图对该对象适得其反，行动遭到反噬"
        elif (
            risk_side_effect >= self._backlash_min_risk
            and risk_side_effect > effective_impact + self._backlash_margin
        ):
            # 反噬：风险副作用既显著(>=min_risk)又以绝对 margin 压过有效影响。
            # 避免"有效影响本就微弱"的低风险行动被误判反噬。
            outcome = "negative"
            backlash = True
            backlash_reason = (
                f"风险副作用（{risk_side_effect:.2f}）明显压过了有效影响"
                f"（{effective_impact:.2f}），冒进的代价反噬到自己身上"
            )
        elif core_delta < 0:
            # 净影响为负但风险不足以判定反噬 → 行动"打了水漂"，归为 no_effect 而非夸张的反噬
            outcome = "no_effect"
            no_effect_reason = "这一手净效果为负、但还不足以酿成反噬——等于打了水漂"
            core_delta = 0.0

        # ── 10. 子因子分配（no_effect 时返回空）─────────────────────────
        if outcome == "no_effect":
            factor_deltas: Dict[str, float] = {}
        else:
            factor_deltas = self._allocate_to_factors(world_object, evaluation, core_delta)

        # ── 11. 解释文本 ─────────────────────────────────────────────────
        explanation = (
            f"match={match_score:.2f} intent_mult={intent_multiplier:.2f} "
            f"quality={quality_factor:.2f} impact={effective_impact:.3f} "
            f"risk_fx={risk_side_effect:.3f} → core_delta={core_delta:+.1f} "
            f"[{outcome}]"
        )
        if no_effect_reason:
            explanation += f" | {no_effect_reason}"
        if backlash_reason:
            explanation += f" | {backlash_reason}"

        proposal_id = (
            f"prop_{evaluation.tick}_{evaluation.agent_id}"
            f"_{int(time.time() * 1000) % 10000:04d}"
        )
        return StateDeltaProposal(
            proposal_id=proposal_id,
            tick=evaluation.tick,
            source_action_id=f"act_{evaluation.tick}_{evaluation.agent_id}",
            source_evaluation_id=evaluation.evaluation_id,
            actor_id=evaluation.agent_id,
            object_id=world_object.id,
            factor_deltas=factor_deltas,
            core_delta=core_delta,
            effective_impact=round(effective_impact, 4),
            match_score=round(match_score, 4),
            resistance_loss=round(resistance * effective_impact, 4),
            risk_side_effect=round(risk_side_effect, 4),
            resource_penalty=round(resource_penalty, 4),
            explanation=explanation,
            outcome=outcome,
            no_effect_reason=no_effect_reason,
            backlash=backlash,
            backlash_reason=backlash_reason,
            metadata={
                "object_type": world_object.type,
                "physics_profile": world_object.type,
                "sensitivity": sensitivity,
                "resistance": resistance,
                "risk": object_risk,
                "needs": needs,
            },
        )

    @staticmethod
    def _allocate_to_factors(
        world_object: WorldObjectRuntime,
        evaluation: ActionEvaluation,
        core_delta: float,
    ) -> Dict[str, float]:
        factors = world_object.factors
        if not factors:
            return {"state": round(core_delta, 2)}

        force = evaluation.force_vector or {}
        targeted: Dict[str, float] = {}
        for dim, factor_list in world_object.needs_factors.items():
            dim_strength = force.get(dim, 0.0)
            if dim_strength > 0:
                for f in factor_list:
                    if f in factors:
                        targeted[f] = targeted.get(f, 0.0) + dim_strength

        if not targeted:
            weight_sum = sum(world_object.weights.values()) or 1.0
            targeted = {
                f: world_object.weights.get(f, 0.0) / weight_sum
                for f in factors
            }

        total = sum(targeted.values()) or 1.0
        shares = {factor: weight / total for factor, weight in targeted.items()}
        # core_value = Σ factor × factor_weight。先计算按 shares 分摊后
        # 对核心值的实际贡献，再反向缩放，保证声明的 core_delta 与落账后
        # 的核心变化处于同一尺度。
        weighted_contribution = sum(
            share * world_object.weights.get(factor, 0.0)
            for factor, share in shares.items()
        )
        if weighted_contribution <= 0:
            weighted_contribution = 1.0
        scale = core_delta / weighted_contribution
        return {
            factor: round(share * scale, 4)
            for factor, share in shares.items()
        }
