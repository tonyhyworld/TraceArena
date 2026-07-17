"""
CausalSequenceBuilder：把账本记录串成可视化因果链（P1.5 升级版）

支持三种路径：
  成功：action → evaluation → validation → force_budget → state_delta → metric_delta
  无效：action → evaluation → validation → no_effect
  反噬：action → evaluation → validation → force_budget → backlash → negative_state_delta → negative_metric_delta
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.core.interfaces import (
    ActionEvaluation,
    ActionPack,
    ActionValidationResult,
    CausalSequence,
    CausalSequenceStep,
    ForceBudgetResult,
    MetricDerivationEntry,
    StateDeltaEntry,
    StateDeltaProposal,
)


class CausalSequenceBuilder:
    """无状态构建器：给定一次行动的完整账本记录，生成 CausalSequence。"""

    def build(
        self,
        action: ActionPack,
        evaluation: ActionEvaluation,
        delta_entries: List[StateDeltaEntry],
        metric_entries: List[MetricDerivationEntry],
        tick: int,
        validation: Optional[ActionValidationResult] = None,
        budget: Optional[ForceBudgetResult] = None,
        proposal: Optional[StateDeltaProposal] = None,
    ) -> CausalSequence:
        steps: List[CausalSequenceStep] = []

        # ── Step 1：行动原文 ─────────────────────────────────────────────
        steps.append(CausalSequenceStep(
            kind="action",
            ref_id=f"act_{tick}_{action.agent_id}",
            title="行动",
            summary=f"{action.agent_id} 执行了「{action.action_id}」：{action.text[:60]}",
            actor_id=action.agent_id,
            target_id=action.target_agent_id,
        ))

        # ── Step 2：行动评价 ─────────────────────────────────────────────
        fv_summary = ", ".join(
            f"{k}={v:.0f}" for k, v in sorted(
                evaluation.force_vector.items(), key=lambda x: x[1], reverse=True
            )[:4]
        )
        steps.append(CausalSequenceStep(
            kind="action_evaluation",
            ref_id=evaluation.evaluation_id,
            title="行动评价",
            summary=(
                f"意图={evaluation.intent}，力向量=[{fv_summary}]，"
                f"清晰度={evaluation.clarity:.2f}，风险={evaluation.risk_level:.2f}"
            ),
            actor_id=evaluation.agent_id,
        ))

        # ── Step 3：合法性校验 ───────────────────────────────────────────
        if validation:
            val_summary = f"状态={validation.status}"
            if validation.reasons:
                val_summary += "，原因：" + "；".join(validation.reasons)
            if validation.warnings:
                val_summary += "，警告：" + "；".join(validation.warnings)
            if validation.force_multiplier != 1.0:
                val_summary += f"，行动力×{validation.force_multiplier:.2f}"
            steps.append(CausalSequenceStep(
                kind="validation",
                ref_id=validation.validation_id,
                title="合法性校验",
                summary=val_summary,
                actor_id=evaluation.agent_id,
                metadata={"valid": validation.valid, "allow_physics": validation.allow_physics},
            ))

        # 行动非法：到这里就结束
        if validation and not validation.allow_physics:
            steps.append(CausalSequenceStep(
                kind="no_effect",
                ref_id=f"invalid_{tick}_{action.agent_id}",
                title="行动非法",
                summary="行动未通过合法性校验，未进入物理结算：" + "；".join(validation.reasons),
                actor_id=action.agent_id,
            ))
            return self._finalize(steps, action, tick, [], [], outcome="invalid")

        # ── Step 4：行动力预算 ───────────────────────────────────────────
        if budget:
            if budget.scaled:
                budget_summary = (
                    f"行动力 {budget.original_force_total:.0f} 超出预算 {budget.force_budget:.0f}，"
                    f"压缩至 {budget.original_force_total * budget.scale_ratio:.0f}"
                    f"（×{budget.scale_ratio:.2f}）"
                )
            else:
                budget_summary = (
                    f"行动力 {budget.original_force_total:.0f}，"
                    f"预算 {budget.force_budget:.0f}，未超限"
                )
            steps.append(CausalSequenceStep(
                kind="force_budget",
                ref_id=budget.budget_id,
                title="行动力预算",
                summary=budget_summary,
                actor_id=evaluation.agent_id,
                metadata={"scaled": budget.scaled, "scale_ratio": budget.scale_ratio},
            ))

        # ── Step 5：物理结算结果 ─────────────────────────────────────────
        if proposal:
            if proposal.outcome == "no_effect":
                steps.append(CausalSequenceStep(
                    kind="no_effect",
                    ref_id=proposal.proposal_id,
                    title="行动无效",
                    summary=f"未产生有效变化：{proposal.no_effect_reason or '影响过低'}",
                    object_id=proposal.object_id,
                    actor_id=proposal.actor_id,
                    metadata={"match_score": proposal.match_score},
                ))
                return self._finalize(steps, action, tick, delta_entries, metric_entries, outcome="no_effect")

            elif proposal.outcome in ("negative",):
                steps.append(CausalSequenceStep(
                    kind="backlash",
                    ref_id=proposal.proposal_id,
                    title="反噬",
                    summary=f"行动产生反噬：{proposal.backlash_reason or '风险副作用超过有效影响'}",
                    object_id=proposal.object_id,
                    actor_id=proposal.actor_id,
                    delta=proposal.core_delta,
                    metadata={"risk_side_effect": proposal.risk_side_effect},
                ))

        # ── Step 6：状态变化 ─────────────────────────────────────────────
        for delta in delta_entries:
            core_change = delta.after_core - delta.before_core
            direction = "↑" if core_change > 0 else "↓" if core_change < 0 else "→"
            kind = "negative_state_delta" if core_change < 0 else "state_delta"
            steps.append(CausalSequenceStep(
                kind=kind,
                ref_id=delta.delta_id,
                title="对象变化" if core_change >= 0 else "对象下降（反噬）",
                summary=(
                    f"对象 {delta.object_id} {direction} "
                    f"{delta.before_core:.1f} → {delta.after_core:.1f}"
                ),
                object_id=delta.object_id,
                actor_id=delta.actor_id,
                delta=round(core_change, 2),
            ))

        # ── Step 7：指标派生 ─────────────────────────────────────────────
        for md in metric_entries:
            direction = "↑" if md.delta > 0 else "↓"
            kind = "negative_metric_delta" if md.delta < 0 else "metric_delta"
            steps.append(CausalSequenceStep(
                kind=kind,
                ref_id=md.metric_update_id,
                title="指标派生" if md.delta >= 0 else "指标下降（反噬）",
                summary=(
                    f"{md.agent_id} 的 {md.metric_name} {direction}"
                    f"{md.before_value:.1f} → {md.after_value:.1f}"
                    f"（{md.reason}）"
                ),
                actor_id=md.agent_id,
                metric=md.metric_name,
                delta=md.delta,
            ))

        # 判断整体结果
        if delta_entries and (delta_entries[0].after_core < delta_entries[0].before_core):
            outcome = "backlash"
        else:
            outcome = "success"

        return self._finalize(steps, action, tick, delta_entries, metric_entries, outcome=outcome)

    @staticmethod
    def _finalize(
        steps: List[CausalSequenceStep],
        action: ActionPack,
        tick: int,
        delta_entries: List[StateDeltaEntry],
        metric_entries: List[MetricDerivationEntry],
        outcome: str = "success",
    ) -> CausalSequence:
        importance = sum(abs(d.after_core - d.before_core) for d in delta_entries)
        importance += sum(abs(m.delta) for m in metric_entries)

        if outcome == "invalid":
            summary = f"{action.agent_id} 的行动非法，未进入结算"
        elif outcome == "no_effect":
            summary = f"{action.agent_id} 的行动未命中对象需求，无效果"
        elif outcome == "backlash":
            summary = f"{action.agent_id} 的行动产生反噬，对象/指标下降"
        elif metric_entries:
            top = max(metric_entries, key=lambda m: abs(m.delta))
            summary = (
                f"{action.agent_id} 的行动使 {top.metric_name} "
                f"{'+' if top.delta > 0 else ''}{top.delta:.1f}"
            )
        elif delta_entries:
            top = max(delta_entries, key=lambda d: abs(d.after_core - d.before_core))
            summary = f"{action.agent_id} 影响了对象 {top.object_id}"
        else:
            summary = f"{action.agent_id} 的行动已记录"

        sequence_id = f"seq_{tick}_{action.agent_id}_{int(time.time() * 1000) % 10000:04d}"

        # 构建世界因果链自身的可追溯 metadata。
        primary_delta = delta_entries[0] if delta_entries else None
        primary_metric = metric_entries[0] if metric_entries else None
        metadata: Dict[str, Any] = {
            "outcome": outcome,
            # ── 行动评价字段（从 steps 反推，避免再引入参数）────────────────
        }
        # 从 steps 中提取各阶段 ref_id（避免额外参数）
        for step in steps:
            # 顺带提取 object_id（任何含有它的 step）
            if step.object_id and "object_id" not in metadata:
                metadata["object_id"] = step.object_id

            if step.kind == "action_evaluation":
                metadata["evaluation_id"] = step.ref_id
            elif step.kind == "validation":
                metadata["validation_id"] = step.ref_id
            elif step.kind == "force_budget":
                metadata["budget_id"] = step.ref_id
            elif step.kind in ("state_delta", "negative_state_delta"):
                if "delta_id" not in metadata:   # 取第一个
                    metadata["delta_id"] = step.ref_id
            elif step.kind in ("metric_delta", "negative_metric_delta"):
                if "metric_id" not in metadata:
                    metadata["metric_id"] = step.ref_id
            elif step.kind == "backlash":
                metadata["proposal_id"] = step.ref_id
                if step.metadata:
                    metadata["risk_side_effect"] = step.metadata.get("risk_side_effect", 0.0)
                metadata["backlash_reason"] = step.summary
            elif step.kind == "no_effect":
                metadata.setdefault("proposal_id", step.ref_id)
                metadata["no_effect_reason"] = step.summary

        # ── delta 细节 ─────────────────────────────────────────────────────
        if primary_delta is not None:
            metadata["object_id"] = primary_delta.object_id
            metadata["before_core"] = primary_delta.before_core
            metadata["after_core"] = primary_delta.after_core
            metadata["core_delta"] = round(primary_delta.after_core - primary_delta.before_core, 3)
            metadata["delta_ids"] = [d.delta_id for d in delta_entries]
        else:
            metadata["core_delta"] = 0.0

        # ── metric 细节 ─────────────────────────────────────────────────────
        if primary_metric is not None:
            metadata["metric_name"] = primary_metric.metric_name
            metadata["metric_delta"] = primary_metric.delta
            metadata["metric_before"] = primary_metric.before_value
            metadata["metric_after"] = primary_metric.after_value
            metadata["metric_ids"] = [m.metric_update_id for m in metric_entries]

        # ── 行动摘要字段 ───────────────────────────────────────────────────
        metadata["intent"] = action.action_id   # ActionPack.action_id ≈ intent

        return CausalSequence(
            sequence_id=sequence_id,
            tick=tick,
            source_action_id=f"act_{tick}_{action.agent_id}",
            actor_id=action.agent_id,
            steps=steps,
            summary=summary,
            importance=round(importance, 2),
            metadata=metadata,
        )
