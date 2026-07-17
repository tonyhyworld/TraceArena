"""
MetricDerivationService：人物指标变化的唯一入口

铁律：每次指标变化必须引用 delta_id / evidence_id / tool_impact_id 之一，
否则抛 RuleWorldViolation。
"""
from __future__ import annotations

from typing import List, Optional

from app.core.interfaces import MetricDerivationEntry
from app.framework.ruleworld.exceptions import RuleWorldViolation
from typing import Any


class MetricDerivationService:
    """所有人物指标变化的唯一合法入口。"""

    def __init__(self, state: Any):
        self._state = state
        self._ledger: List[MetricDerivationEntry] = []
        self._current_tick: int = 0
        self._seq: int = 0
        self._bounds: dict[str, tuple[float, float]] = {}

    def set_tick(self, tick: int) -> None:
        self._current_tick = tick

    def initialize_agents(
        self,
        agent_ids: List[str],
        metric_definitions: List[dict],
    ) -> None:
        """按场景声明初始化指标，避免把所有指标隐式初始化为零。"""
        metrics_map = self._state.internal.setdefault("metrics", {})
        for agent_id in agent_ids:
            agent_metrics = metrics_map.setdefault(agent_id, {})
            for definition in metric_definitions:
                if not isinstance(definition, dict):
                    continue
                if definition.get("owner_type", "agent") != "agent":
                    continue
                metric_id = definition.get("metric_id", definition.get("id", ""))
                if not metric_id:
                    continue
                initial = float(definition.get("initial", 0.0))
                minimum = float(definition.get("min", 0.0))
                maximum = float(definition.get("max", 100.0))
                self._bounds[str(metric_id)] = (minimum, maximum)
                agent_metrics.setdefault(
                    metric_id, max(minimum, min(maximum, initial))
                )

    def derive(
        self,
        agent_id: str,
        metric: str,
        delta: float,
        derivation_rule: str,
        reason: str,
        source_delta_id: str,
    ) -> MetricDerivationEntry:
        """
        修改 state.internal["metrics"][agent_id][metric]，并记录派生来源。
        强制：source_delta_id 必填，指标只能从 StateDelta 派生。
        """
        if not source_delta_id:
            raise RuleWorldViolation(
                f"指标派生必须引用 StateDelta（source_delta_id 必填），"
                f"agent={agent_id} metric={metric} rule={derivation_rule}"
            )

        si = self._state.internal
        metrics = si.setdefault("metrics", {})
        agent_metrics = metrics.setdefault(agent_id, {})

        before_value = float(agent_metrics.get(metric, 0.0))
        new_value = round(max(0.0, min(100.0, before_value + delta)), 2)
        agent_metrics[metric] = new_value
        after_value = new_value

        self._seq += 1
        entry = MetricDerivationEntry(
            metric_update_id=f"mderiv_{self._current_tick}_{self._seq:04d}",
            tick=self._current_tick,
            agent_id=agent_id,
            metric_name=metric,
            delta=round(delta, 3),
            source_delta_id=source_delta_id,
            derivation_rule=derivation_rule,
            reason=reason,
            before_value=before_value,
            after_value=after_value,
        )
        self._ledger.append(entry)
        return entry

    def set_from_settlement(
        self,
        *,
        agent_id: str,
        metric: str,
        value: float,
        settlement_ref: str,
        reason: str,
    ) -> MetricDerivationEntry:
        """Set an agent metric from a trusted scenario settlement value."""
        if not settlement_ref:
            raise RuleWorldViolation("结算指标回写必须引用 SettlementRecord")
        metrics = self._state.internal.setdefault("metrics", {})
        agent_metrics = metrics.setdefault(agent_id, {})
        before_value = float(agent_metrics.get(metric, 0.0))
        minimum, maximum = self._bounds.get(metric, (0.0, 100.0))
        after_value = round(max(minimum, min(maximum, float(value))), 6)
        agent_metrics[metric] = after_value
        self._seq += 1
        entry = MetricDerivationEntry(
            metric_update_id=f"mderiv_{self._current_tick}_{self._seq:04d}",
            tick=self._current_tick,
            agent_id=agent_id,
            metric_name=metric,
            delta=round(after_value - before_value, 6),
            source_delta_id=settlement_ref,
            derivation_rule="scenario_settlement_binding",
            reason=reason,
            before_value=before_value,
            after_value=after_value,
        )
        self._ledger.append(entry)
        return entry

    def derive_from_delta(
        self,
        delta_entry,
        derivation_rules: List[dict],
    ) -> List[MetricDerivationEntry]:
        """
        P1：根据场景声明的 metric_derivations 规则，从 StateDeltaEntry 自动派生指标。

        derivation_rules 格式（来自 world/metrics.yaml）：
          - object_type: generic_problem   # 或 object_id: obj_xxx（精确匹配）
            factor: "*"                     # "*" = 任意因子，或具体因子名
            metric: effectiveness
            target_agent: actor             # actor=行动者 / all=所有存活 agent
            coefficient: 0.5
            direction: positive             # positive=对象改善→指标增加，negative=反向

        返回本次派生产生的 MetricDerivationEntry 列表。
        """
        # no_effect 不派生指标
        outcome = getattr(delta_entry, "metadata", {}) or {}
        if outcome.get("outcome") == "no_effect":
            return []
        if getattr(delta_entry, "outcome", None) == "no_effect":
            return []
        # 用 before_core / after_core 计算核心变化量（StateDeltaEntry 无 core_delta 字段）
        raw_core_delta = (
            getattr(delta_entry, "after_core", 0.0)
            - getattr(delta_entry, "before_core", 0.0)
        )
        if abs(raw_core_delta) < 0.001:
            return []

        results = []
        for rule in derivation_rules:
            # ── 严格匹配规则（P3 修复）──
            rule_object_id = rule.get("object_id")
            rule_object_type = rule.get("object_type")
            is_global = rule.get("global", False)

            if rule_object_id:
                # 精确 object_id 匹配
                if rule_object_id != delta_entry.object_id:
                    continue
            elif rule_object_type:
                # object_type 匹配：从 delta_entry 或 metadata 取
                delta_obj_type = getattr(delta_entry, "object_type", None)
                if not delta_obj_type and hasattr(delta_entry, "metadata"):
                    delta_obj_type = (delta_entry.metadata or {}).get("object_type")
                if not delta_obj_type:
                    continue
                if rule_object_type != delta_obj_type:
                    continue
            else:
                # 既没 object_id 也没 object_type → 必须 global=true
                if not is_global:
                    continue

            factor_rule = rule.get("factor", "*")
            metric_name = rule.get("metric", "")
            coefficient = float(rule.get("coefficient", 0.5))
            direction = rule.get("direction", "positive")
            target_agent_rule = rule.get("target_agent", "actor")

            if not metric_name:
                continue

            # 计算指标变化量
            if factor_rule in ("*", "core"):
                # 使用 after_core - before_core（core 表示对象整体核心值变化）
                raw_delta = (
                    getattr(delta_entry, "after_core", 0.0)
                    - getattr(delta_entry, "before_core", 0.0)
                )
            else:
                raw_delta = delta_entry.factor_deltas.get(factor_rule, 0.0)

            metric_delta = raw_delta * coefficient
            if direction == "negative":
                metric_delta = -metric_delta

            if abs(metric_delta) < 0.001:
                continue

            # 确定派生目标 agent
            target_agents: List[str] = []
            if target_agent_rule == "actor" and delta_entry.actor_id:
                target_agents = [delta_entry.actor_id]
            elif target_agent_rule == "all":
                # 从 state 拿存活列表
                alive = list(self._state.alive_agent_ids)
                target_agents = alive
            elif target_agent_rule:
                target_agents = [target_agent_rule]

            for agent_id in target_agents:
                entry = self.derive(
                    agent_id=agent_id,
                    metric=metric_name,
                    delta=metric_delta,
                    derivation_rule=f"causal_delta:{rule.get('object_id') or rule.get('object_type','*')}:{factor_rule}",
                    reason=f"对象 {delta_entry.object_id} 变化 {raw_delta:+.1f} × coeff={coefficient}",
                    source_delta_id=delta_entry.delta_id,
                )
                results.append(entry)

        return results

    @property
    def ledger(self) -> List[MetricDerivationEntry]:
        return self._ledger
