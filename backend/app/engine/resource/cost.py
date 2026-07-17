"""
P0-2 CostValidator — 成本校验器

校验 action/tool/movement 成本是否可支付。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger(__name__)


class CostValidator:
    """成本校验：判断 Agent 是否有足够资源执行动作/工具/移动"""

    def __init__(self, resource_service: Any):
        self._rs = resource_service

    def validate_action(self, agent_id: str, action_cfg: Dict[str, Any]) -> Tuple[bool, str]:
        cost = action_cfg.get("cost", {})
        if not cost:
            return True, ""
        if self._rs.can_afford(agent_id, cost):
            return True, ""
        return False, f"资源不足执行动作 {action_cfg.get('id', '?')}"

    def validate_tool(self, agent_id: str, tool_cfg: Dict[str, Any]) -> Tuple[bool, str]:
        cost = tool_cfg.get("cost", {})
        if not cost:
            return True, ""
        if self._rs.can_afford(agent_id, cost):
            return True, ""
        return False, f"资源不足使用工具 {tool_cfg.get('tool_id', tool_cfg.get('id', '?'))}"

    def validate_movement(self, agent_id: str, travel_cost: Dict[str, float]) -> Tuple[bool, str]:
        if not travel_cost:
            return True, ""
        if self._rs.can_afford(agent_id, travel_cost):
            return True, ""
        return False, "资源不足以支付移动成本"
