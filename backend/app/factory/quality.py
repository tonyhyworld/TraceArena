"""
模块2:质量标注器(Quality Scorer)+ 可解释理由

消费模块1的 Trajectory,给出三级质量评估:
  - 步级(StepQuality):这一步做得好不好(situational_fit/outcome/parsed)
  - 链级(ChainQuality):跨拍策略连贯性(计划兑现率 = note_to_self 声明的
    多步计划,后续拍是否真的执行了)
  - 局级(TrajectoryQuality):整条轨迹能不能进数据集(解析率/错误率/
    fallback占比/动作分布熵),脏局在此被硬闸判死

双视图纪律(蓝图约束0):每个分数同时产出
  - 机器视图:quality_vector(纯数值,喂训练/筛选)
  - 人类视图:reasons(人话理由,决策卡素材)——绝不另写逻辑,理由由数值
    + judge rationale + 模板拼装,保证与数值同源、可复现。

本模块只打分与解释,不做取舍决定(选不选进数据集是模块4的事,本模块只
提供 is_clean 硬闸结果 + 分数,让下游按阈值筛)。
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional

from app.factory.trajectory import Trajectory, TrajectoryStep


# ── 硬闸阈值(脏局判死线)──
# 这些是"数据毒药"的底线,不是质量高低——低于此的局根本不该进任何数据集。
MIN_VALID_STEP_RATIO = 0.6       # 有效步(非空非兜底)占比下限
MAX_FALLBACK_RATIO = 0.4         # 兜底步占比上限
MIN_VALID_STEPS = 3              # 至少多少有效步才算一局


@dataclass
class StepQuality:
    """单步质量评估(双视图)。"""
    sample_id: str
    # 机器视图
    score: float = 0.0                       # 综合步质量 [0,1]
    situational_fit: Optional[float] = None
    outcome_score: float = 0.0               # success=1 / no_effect=0.4 / invalid=0
    is_clean: bool = True                    # 是否可用(非空非兜底非解析失败)
    # 人类视图
    reasons: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class TrajectoryQuality:
    """整条轨迹的质量评估(双视图)。"""
    run_id: str
    agent_id: str
    # ── 机器视图:quality_vector ──
    is_clean: bool = True                    # 硬闸:能否进数据集
    overall_score: float = 0.0               # 局级综合质量 [0,1]
    valid_step_ratio: float = 0.0
    fallback_ratio: float = 0.0
    parse_success_ratio: float = 0.0
    action_entropy: float = 0.0              # 动作多样性(香农熵)
    plan_fulfillment: Optional[float] = None # 计划兑现率(有 note_to_self 才算)
    mean_situational_fit: Optional[float] = None
    deterministic_ratio: float = 0.0         # deterministic 奖励步占比
    step_quality: List[StepQuality] = field(default_factory=list)
    # ── 人类视图:一句话画像 + 逐项理由 ──
    verdict: str = ""                        # 人话总评
    reasons: List[str] = field(default_factory=list)
    reject_reason: Optional[str] = None      # 若被硬闸拦下,说明原因

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["step_quality"] = [s.to_dict() for s in self.step_quality]
        return d


# ---------------------------------------------------------------------------
# 步级
# ---------------------------------------------------------------------------

_FAILED_OUTCOMES = {"invalid", "no_effect", "order_rejected", "failed"}


def score_step(step: TrajectoryStep) -> StepQuality:
    """给单步打分并生成人话理由。理由由数值+judge评语拼装,不另写逻辑。"""
    sq = StepQuality(sample_id=step.sample_id, situational_fit=step.situational_fit)

    # 空动作/兜底/解析失败 → 不可用,直接判定
    if step.is_empty_action:
        sq.is_clean = False
        sq.score = 0.0
        sq.reasons.append("模型未产出动作(LLM 失败拍),不可用于训练")
        return sq
    if step.is_fallback:
        sq.is_clean = False
        sq.score = 0.0
        sq.reasons.append(f"系统兜底动作(原因:{step.llm_error or '未知'}),不可用于训练")
        return sq
    if not step.parsed_ok:
        sq.is_clean = False
        sq.score = 0.1
        sq.reasons.append("模型输出解析失败,格式不合规")
        return sq

    # The scene settlement is authoritative. Reward is normalized only for
    # dataset selection; its raw value remains on TrajectoryStep.
    outcome_score = 0.0 if step.outcome in _FAILED_OUTCOMES else (
        0.5 + 0.5 * math.tanh(float(step.reward or 0.0))
    )
    sq.outcome_score = outcome_score
    sq.score = round(outcome_score, 3)

    # ── 人话理由(决策卡素材)──
    sq.reasons.append(
        f"场景结算：{step.outcome or '无结果'}，奖励 {step.reward:+.3f}"
    )
    if step.outcome in _FAILED_OUTCOMES:
        sq.reasons.append("场景结算确认这一步失败，可作为反面样本")
    if step.authority_provider:
        sq.reasons.append(
            f"结算权限：{step.authority_mode}/{step.authority_provider}"
        )
    return sq


# ---------------------------------------------------------------------------
# 链级:计划兑现率
# ---------------------------------------------------------------------------

def _plan_fulfillment(steps: List[TrajectoryStep]) -> Optional[float]:
    """计划兑现率:agent 在 note_to_self 里声明的多步意图,后续拍是否执行。

    近似实现(不引入 embedding 依赖,保持轻量+确定性):
    一步的 note_to_self 若提及某动作类型/目标,后续 3 拍内是否出现对应
    action_id 或 target。有 note 的步才计入分母。这是"规划能力"的代理指标,
    教多步计划比教单步反应更值钱。
    """
    noted = [(i, s) for i, s in enumerate(steps)
             if s.note_to_self and not s.is_empty_action]
    if not noted:
        return None
    hits = 0
    for i, s in noted:
        note = s.note_to_self.lower()
        window = steps[i + 1: i + 4]
        # 后续拍的动作/目标是否在 note 里被提及(粗匹配,确定性)
        fulfilled = False
        for w in window:
            if w.is_empty_action:
                continue
            aid = (w.action_id or "").lower()
            tgt = str(w.target_object_id or w.target_agent_id or "").lower()
            if aid and aid in note:
                fulfilled = True
                break
            if tgt and tgt in note:
                fulfilled = True
                break
        if fulfilled:
            hits += 1
    return round(hits / len(noted), 3)


def _action_entropy(steps: List[TrajectoryStep]) -> float:
    """动作分布香农熵(归一化到 [0,1])。低=套模板,高=多样。"""
    ids = [s.action_id for s in steps if s.action_id and not s.is_empty_action]
    if len(ids) < 2:
        return 0.0
    counts = Counter(ids)
    total = sum(counts.values())
    ent = -sum((c / total) * math.log2(c / total) for c in counts.values())
    max_ent = math.log2(len(counts)) if len(counts) > 1 else 1.0
    return round(ent / max_ent, 3) if max_ent > 0 else 0.0


# ---------------------------------------------------------------------------
# 局级 + 硬闸
# ---------------------------------------------------------------------------

def score_trajectory(traj: Trajectory) -> TrajectoryQuality:
    """给整条轨迹打三级质量分,并执行脏局硬闸。"""
    tq = TrajectoryQuality(run_id=traj.run_id, agent_id=traj.agent_id)
    steps = traj.steps
    total = len(steps)

    if total == 0:
        tq.is_clean = False
        tq.reject_reason = "轨迹为空(该 agent 没有任何拍)"
        tq.verdict = "空轨迹,不可用"
        return tq

    # 步级
    tq.step_quality = [score_step(s) for s in steps]
    valid = [s for s in steps if not s.is_empty_action and not s.is_fallback and s.parsed_ok]
    n_valid = len(valid)
    n_fallback = sum(1 for s in steps if s.is_fallback or s.is_empty_action)
    n_parsed = sum(1 for s in steps if s.parsed_ok and not s.is_empty_action)

    tq.valid_step_ratio = round(n_valid / total, 3)
    tq.fallback_ratio = round(n_fallback / total, 3)
    tq.parse_success_ratio = round(n_parsed / total, 3)
    tq.action_entropy = _action_entropy(steps)
    tq.plan_fulfillment = _plan_fulfillment(steps)

    sfs = [float(s.situational_fit) for s in valid if s.situational_fit is not None]
    tq.mean_situational_fit = round(sum(sfs) / len(sfs), 3) if sfs else None
    n_det = sum(1 for s in valid if s.reward_purity == "deterministic")
    tq.deterministic_ratio = round(n_det / n_valid, 3) if n_valid else 0.0

    # ── 硬闸:脏局判死 ──
    if n_valid < MIN_VALID_STEPS:
        tq.is_clean = False
        tq.reject_reason = f"有效步仅 {n_valid} 步(下限 {MIN_VALID_STEPS}),样本量不足"
    elif tq.valid_step_ratio < MIN_VALID_STEP_RATIO:
        tq.is_clean = False
        tq.reject_reason = (
            f"有效步占比 {tq.valid_step_ratio:.0%} 低于 {MIN_VALID_STEP_RATIO:.0%}"
            f"——大量拍是失败/兜底(如整局 API 报错),数据毒药"
        )
    elif tq.fallback_ratio > MAX_FALLBACK_RATIO:
        tq.is_clean = False
        tq.reject_reason = f"兜底步占比 {tq.fallback_ratio:.0%} 超过 {MAX_FALLBACK_RATIO:.0%}"
    else:
        tq.is_clean = True

    # 局级综合质量分(仅对干净局有意义)
    if tq.is_clean:
        step_mean = sum(sq.score for sq in tq.step_quality if sq.is_clean) / max(n_valid, 1)
        # 综合:步质量均值 × 0.5 + 有效率 × 0.2 + 多样性 × 0.15 + 计划兑现 × 0.15
        pf = tq.plan_fulfillment if tq.plan_fulfillment is not None else 0.5
        tq.overall_score = round(
            0.5 * step_mean
            + 0.2 * tq.valid_step_ratio
            + 0.15 * tq.action_entropy
            + 0.15 * pf,
            3,
        )

    # ── 人话总评(决策卡/数据卡素材)──
    tq.reasons = _build_traj_reasons(traj, tq, n_valid, total)
    tq.verdict = _build_verdict(tq)
    return tq


def _build_traj_reasons(
    traj: Trajectory, tq: TrajectoryQuality, n_valid: int, total: int,
) -> List[str]:
    reasons: List[str] = []
    reasons.append(f"{traj.provider}/{traj.model} 跑了 {total} 拍,其中 {n_valid} 拍是有效决策")
    if tq.mean_situational_fit is not None:
        reasons.append(f"平均决策契合度 {tq.mean_situational_fit:.0%}(裁判对每步切中局面程度的评估)")
    if tq.action_entropy >= 0.7:
        reasons.append(f"行为多样(动作熵 {tq.action_entropy:.2f}),不是套模板")
    elif tq.action_entropy <= 0.3 and n_valid >= 3:
        reasons.append(f"行为偏单一(动作熵 {tq.action_entropy:.2f}),可能套模板")
    if tq.plan_fulfillment is not None:
        reasons.append(
            f"计划兑现率 {tq.plan_fulfillment:.0%}"
            f"(声明的多步计划后续真正执行的比例——衡量规划能力)"
        )
    if tq.deterministic_ratio > 0:
        reasons.append(f"{tq.deterministic_ratio:.0%} 的步由真实数据或确定性验证器结算")
    if traj.victory_rank:
        reasons.append(f"终局排名第 {traj.victory_rank}"
                       + ("(已被淘汰)" if traj.eliminated else ""))
    return reasons


def _build_verdict(tq: TrajectoryQuality) -> str:
    if not tq.is_clean:
        return f"不合格:{tq.reject_reason}"
    s = tq.overall_score
    if s >= 0.7:
        return f"优质轨迹(综合 {s:.2f}):决策契合、行为多样,适合作为学习样本"
    if s >= 0.5:
        return f"合格轨迹(综合 {s:.2f}):可用,质量中等"
    return f"低质轨迹(综合 {s:.2f}):虽干净但决策平庸,建议仅作补充"
