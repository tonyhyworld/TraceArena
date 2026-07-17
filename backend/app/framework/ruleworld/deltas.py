"""
StateDeltaService：世界对象状态变化的唯一入口

铁律：所有世界对象因子变化必须经此服务，自动记录 before/after。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from app.core.interfaces import StateDeltaEntry
from app.framework.ruleworld.objects import WorldObjectRegistry


class StateDeltaService:
    """所有世界对象状态变化的唯一合法入口。"""

    def __init__(self, registry: WorldObjectRegistry):
        self._registry = registry
        self._ledger: List[StateDeltaEntry] = []
        self._current_tick: int = 0
        self._seq: int = 0

    def set_tick(self, tick: int) -> None:
        self._current_tick = tick

    def apply_delta(
        self,
        object_id: str,
        factor_deltas: Dict[str, float],
        actor_id: str,
        settlement_rule: str,
        cause_chain: List[str] = [],
        linked_action_id: Optional[str] = None,
        linked_tool_id: Optional[str] = None,
    ) -> StateDeltaEntry:
        """
        对世界对象施加因子变化，记录 before/after，返回 StateDeltaEntry。
        delta_id 可被后续 MetricDerivationService.derive() 引用。
        """
        obj = self._registry.get(object_id)

        # 记录变化前
        before_factors = dict(obj.factors)
        before_core = obj.core_value()

        # 应用变化
        for factor, delta in factor_deltas.items():
            if factor in obj.factors:
                obj.factors[factor] = round(
                    max(
                        obj.factor_min,
                        min(obj.factor_max, obj.factors[factor] + delta),
                    ),
                    4,
                )

        # 记录变化后
        after_factors = dict(obj.factors)
        after_core = obj.core_value()

        self._seq += 1
        delta_id = f"delta_{self._current_tick}_{self._seq:04d}"

        cause_desc = settlement_rule
        if cause_chain:
            cause_desc = f"{settlement_rule} [{', '.join(cause_chain)}]"

        entry = StateDeltaEntry(
            delta_id=delta_id,
            tick=self._current_tick,
            object_id=object_id,
            core_state=obj.core_state,
            before_core=before_core,
            after_core=after_core,
            factor_deltas=factor_deltas,
            cause_chain=cause_desc,
            execution_quality=0.0,
            linked_action_id=linked_action_id,
            actor_id=actor_id,
            # 新增字段
            before_factors=before_factors,
            after_factors=after_factors,
            cause_chain_ids=list(cause_chain),
        )
        self._ledger.append(entry)
        return entry

    def apply_proposal(self, proposal) -> StateDeltaEntry:
        """
        P1.5：把 StateDeltaProposal 落账为 StateDeltaEntry。
        支持 no_effect（factor_deltas 为空，before==after）和 negative（负向 delta）。
        """
        # no_effect 时 factor_deltas 为空，apply_delta 会产生 before==after 的条目
        entry = self.apply_delta(
            object_id=proposal.object_id,
            factor_deltas=proposal.factor_deltas,   # no_effect 时为 {}
            actor_id=proposal.actor_id,
            settlement_rule="causal_physics",
            cause_chain=[proposal.source_evaluation_id],
            linked_action_id=proposal.source_action_id,
        )
        # 把 P1.5 物理结果写入 metadata（不破坏已有字段）
        entry.metadata = {
            "proposal_id": proposal.proposal_id,
            "outcome": proposal.outcome,
            "match_score": proposal.match_score,
            "effective_impact": proposal.effective_impact,
            "risk_side_effect": proposal.risk_side_effect,
            "resource_penalty": proposal.resource_penalty,
            "backlash": proposal.backlash,
            "no_effect_reason": proposal.no_effect_reason,
            "backlash_reason": proposal.backlash_reason,
            "explanation": proposal.explanation,
        }
        return entry

    @property
    def ledger(self) -> List[StateDeltaEntry]:
        return self._ledger
