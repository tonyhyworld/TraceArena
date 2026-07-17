"""
P0-1 ReachabilityService — 可达性服务

判断 Agent 能否到达目标地点、计算移动成本、输出可达地点列表。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.core.interfaces import LocationConfig

logger = logging.getLogger(__name__)


class ReachabilityService:
    """可达性服务：基于 LocationRegistry 判断移动可行性"""

    def __init__(self, registry: Any):
        self._registry = registry

    def is_reachable(self, from_id: str, to_id: str) -> bool:
        """判断 from_id 是否直接连接到 to_id"""
        loc = self._registry.get(from_id)
        if not loc:
            return False
        return to_id in loc.connected_to

    def travel_cost(self, from_id: str, to_id: str) -> Dict[str, float]:
        """计算移动成本，不可达时返回空"""
        if not self.is_reachable(from_id, to_id):
            return {}
        target = self._registry.get(to_id)
        if not target:
            return {}
        return dict(target.travel_cost)

    def reachable_locations(self, agent_location: str) -> List[Tuple[str, Dict[str, float]]]:
        """返回从 agent_location 可达的地点列表及成本"""
        loc = self._registry.get(agent_location)
        if not loc:
            return []
        result = []
        for conn_id in loc.connected_to:
            target = self._registry.get(conn_id)
            if target:
                result.append((conn_id, dict(target.travel_cost)))
        return result

    def check_entry_permission(self, agent_permissions: List[str], location_id: str) -> Tuple[bool, str]:
        """检查 Agent 是否有进入地点的权限"""
        loc = self._registry.get(location_id)
        if not loc:
            return False, f"地点不存在: {location_id}"
        if not loc.permissions_required:
            return True, ""
        for req in loc.permissions_required:
            if req not in agent_permissions:
                return False, f"缺少权限: {req}"
        return True, ""

    def can_afford(self, agent_resources: Dict[str, float], from_id: str, to_id: str) -> Tuple[bool, str]:
        """检查资源是否足够支付移动成本"""
        cost = self.travel_cost(from_id, to_id)
        for rid, amount in cost.items():
            available = agent_resources.get(rid, 0)
            if available < amount:
                return False, f"资源不足: {rid} 需要 {amount}，当前 {available}"
        return True, ""
