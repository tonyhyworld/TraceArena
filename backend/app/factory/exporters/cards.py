"""
决策卡构造器(人类视图)

纪律(蓝图约束0/2):决策卡纯模板拼装,禁 LLM。人话理由直接复用模块2
已生成的 StepQuality.reasons(那里已把数值+judge评语翻译成人话),这里
只做"组装成卡片结构",不重新翻译——保证与机器视图同源、两处逻辑不分叉。

一张决策卡回答企业非技术人员的三个问题:
  局面(它当时面对什么)→ 决策(它做了什么)→ 为什么好/差(值不值得学)
外加证据引用(账本溯源,可回查),让"可解释"落到可核对。
"""
from __future__ import annotations

import re
from typing import Any, Dict, List, Optional

from app.factory.trajectory import TrajectoryStep
from app.factory.quality import StepQuality


_RANKING_RE = re.compile(r"###\s*当前排名(.+?)(?:\n###|\n##|\Z)", re.DOTALL)
_METRIC_RE = re.compile(r"###\s*你的状态(.+?)(?:\n###|\n##|\Z)", re.DOTALL)


def _situation_summary(step: TrajectoryStep, max_len: int = 180) -> str:
    """从 user_brief 抽出可读的局面摘要:优先排名段+状态段,退回开头截断。

    这是模型当时真实看到的局面(诚实),清洗成一句给人读的话。
    """
    brief = step.user_brief or ""
    parts: List[str] = []
    m = _RANKING_RE.search(brief)
    if m:
        rank_txt = re.sub(r"\s+", " ", m.group(1)).strip()
        if rank_txt:
            parts.append("排名 " + rank_txt[:80])
    m = _METRIC_RE.search(brief)
    if m:
        # 只挑场景明确标注为风险的关键指标，避免整段太长。
        for line in m.group(1).splitlines():
            line = line.strip()
            if any(token in line.lower() for token in ("风险", "risk", "danger")):
                parts.append(line)
                break
    if parts:
        return " ｜ ".join(parts)[:max_len]
    # 兜底:brief 去掉 markdown 标题后的前若干字
    cleaned = re.sub(r"[#*`]", "", brief).strip()
    return cleaned[:max_len] if cleaned else "(局面信息缺失)"


def _decision_summary(step: TrajectoryStep) -> str:
    """它做了什么:动作 + plan 摘要 + 目标。"""
    bits = [f"动作={step.action_id or '未知'}"]
    tgt = step.target_object_id or step.target_agent_id
    if tgt:
        bits.append(f"目标={tgt}")
    if step.plan:
        plan = re.sub(r"\s+", " ", step.plan).strip()
        bits.append(f"做法={plan[:80]}")
    return "，".join(bits)


def _evidence_refs(step: TrajectoryStep) -> List[str]:
    """账本证据引用(可回查溯源)。"""
    return [
        *[f"世界事件：{ref}" for ref in step.source_event_refs],
        *[f"结算记录：{ref}" for ref in step.settlement_refs],
    ]


def build_decision_card(
    step: TrajectoryStep,
    quality: Optional[StepQuality] = None,
    *,
    extra: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """构造一张决策卡(人类视图)。

    quality:模块2的步质量,其 reasons 直接作为"为什么好/差"(不重新翻译)。
    extra:各 exporter 追加的上下文(如 DPO 对里的角色:chosen/rejected)。
    """
    why: List[str] = []
    if quality is not None:
        why = list(quality.reasons)
    elif step.authority_provider:
        why = [f"由 {step.authority_provider} 按场景规则结算"]

    card: Dict[str, Any] = {
        "sample_id": step.sample_id,
        "局面": _situation_summary(step),
        "决策": _decision_summary(step),
        "为什么": why,
        "证据": _evidence_refs(step),
        "元信息": {
            "action_id": step.action_id,
            "reward": step.reward,
            "situational_fit": step.situational_fit,
            "reward_purity": step.reward_purity,
        },
    }
    if extra:
        card.update(extra)
    return card
