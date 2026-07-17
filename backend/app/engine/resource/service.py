"""
P0-2 ResourceService — 资源管理服务

初始化/查询/扣减/恢复资源，记录 ResourceDelta。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional
import copy

from app.core.interfaces import ResourceConfig, ResourceDelta, ResourceState

logger = logging.getLogger(__name__)


class ResourceService:
    """资源管理：Agent 资源的完整生命周期"""

    def __init__(self):
        self._configs: Dict[str, ResourceConfig] = {}
        self._states: Dict[str, Dict[str, ResourceState]] = {}  # agent_id -> {resource_id -> state}
        self._deltas: List[ResourceDelta] = []
        self._seq: int = 0
        self._current_tick: int = 0

    def set_tick(self, tick: int) -> None:
        self._current_tick = tick

    def load_configs(self, resources_cfg: List[Dict[str, Any]]) -> None:
        for item in resources_cfg:
            if not isinstance(item, dict):
                continue
            # 兼容 YAML 中 id 字段名 → resource_id
            if "id" in item and "resource_id" not in item:
                item = {**item, "resource_id": item["id"]}
            cfg = ResourceConfig(**item)
            self._configs[cfg.resource_id] = cfg
        logger.info(f"[ResourceService] 加载 {len(self._configs)} 种资源配置")

    def initialize_agent(
        self,
        agent_id: str,
        overrides: Optional[Dict[str, float]] = None,
    ) -> None:
        """为 Agent 初始化所有资源到初始值。

        overrides：按 agent 覆盖初始值（来自 roles.yaml 的
        capability_profile.initial_resources），用于演绎模式的非对称
        人设资源（甲多影响力/乙多精力/丙多隐秘）。Benchmark 模式不传，
        保持全员对称基线。覆盖值仍受该资源 min/max 约束。
        """
        self._states[agent_id] = {}
        for rid, cfg in self._configs.items():
            initial = cfg.initial
            if overrides and rid in overrides:
                try:
                    initial = max(cfg.min, min(cfg.max, float(overrides[rid])))
                except (TypeError, ValueError):
                    pass
            self._states[agent_id][rid] = ResourceState(
                agent_id=agent_id, resource_id=rid,
                current=initial, max=cfg.max, min=cfg.min,
            )

    def get(self, agent_id: str, resource_id: str) -> Optional[ResourceState]:
        return self._states.get(agent_id, {}).get(resource_id)

    def get_all(self, agent_id: str) -> Dict[str, float]:
        """返回 Agent 所有资源的 {resource_id: current}"""
        states = self._states.get(agent_id, {})
        return {rid: s.current for rid, s in states.items()}

    def can_afford(self, agent_id: str, cost: Dict[str, float]) -> bool:
        """检查资源是否足够支付成本"""
        states = self._states.get(agent_id, {})
        for rid, amount in cost.items():
            state = states.get(rid)
            if not state or state.current < amount:
                return False
        return True

    def deduct(self, agent_id: str, cost: Dict[str, float], reason: str = "", source_action_id: Optional[str] = None) -> List[ResourceDelta]:
        """扣减资源，返回 ResourceDelta 列表"""
        deltas = []
        states = self._states.get(agent_id, {})
        for rid, amount in cost.items():
            state = states.get(rid)
            if not state:
                continue
            before = state.current
            state.current = max(state.min, state.current - amount)
            self._seq += 1
            delta = ResourceDelta(
                delta_id=f"rdelta_{self._current_tick}_{self._seq:04d}",
                tick=self._current_tick, agent_id=agent_id, resource_id=rid,
                before=before, after=state.current, reason=reason,
                source_action_id=source_action_id,
            )
            self._deltas.append(delta)
            deltas.append(delta)
        return deltas

    def refresh_all(self) -> None:
        """每 tick 刷新资源（恢复 refresh_per_tick 量）"""
        for agent_states in self._states.values():
            for rid, state in agent_states.items():
                cfg = self._configs.get(rid)
                if cfg and cfg.refresh_per_tick > 0:
                    state.current = min(state.max, state.current + cfg.refresh_per_tick)

    def set_from_settlement(
        self,
        *,
        agent_id: str,
        resource_id: str,
        value: float,
        settlement_ref: str,
    ) -> Optional[ResourceDelta]:
        state = self._states.get(agent_id, {}).get(resource_id)
        if state is None or not settlement_ref:
            return None
        before = state.current
        state.current = max(state.min, min(state.max, float(value)))
        self._seq += 1
        delta = ResourceDelta(
            delta_id=f"rdelta_{self._current_tick}_{self._seq:04d}",
            tick=self._current_tick,
            agent_id=agent_id,
            resource_id=resource_id,
            before=before,
            after=state.current,
            reason=f"场景结算回写 {settlement_ref}",
            source_action_id=settlement_ref,
        )
        self._deltas.append(delta)
        return delta

    def snapshot(self) -> Dict[str, Any]:
        """返回可用于事务回滚的内部快照。"""
        return {
            "states": copy.deepcopy(self._states),
            "deltas": copy.deepcopy(self._deltas),
            "seq": self._seq,
            "tick": self._current_tick,
        }

    def restore(self, snapshot: Dict[str, Any]) -> None:
        """恢复事务开始前的资源状态。"""
        self._states = copy.deepcopy(snapshot.get("states", {}))
        self._deltas = copy.deepcopy(snapshot.get("deltas", []))
        self._seq = int(snapshot.get("seq", 0))
        self._current_tick = int(snapshot.get("tick", self._current_tick))

    @property
    def configs(self) -> Dict[str, ResourceConfig]:
        return dict(self._configs)

    @property
    def deltas(self) -> List[ResourceDelta]:
        return list(self._deltas)
