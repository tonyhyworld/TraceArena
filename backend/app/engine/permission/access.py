"""
P0-3 AccessControlService — 访问控制服务

判断 Agent 能否进入地点/查看对象/执行动作/使用工具。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class AccessControlService:
    """访问控制：统一的权限判断入口"""

    def __init__(self, permission_registry: Any):
        self._pr = permission_registry

    def can_enter_location(self, agent_id: str, location_id: str, location_cfg: Any) -> Tuple[bool, str]:
        if location_cfg is None:
            return True, ""
        required = getattr(location_cfg, "permissions_required", []) if not isinstance(location_cfg, dict) else location_cfg.get("permissions_required", [])
        for pid in required:
            if not self._pr.has_permission(agent_id, pid):
                return False, f"缺少进入地点权限: {pid}"
        return True, ""

    def can_view_object(self, agent_id: str, object_cfg: Dict[str, Any]) -> Tuple[bool, str]:
        ac = object_cfg.get("access_control", {})
        if not ac:
            return True, ""
        visible_to = ac.get("visible_to", [])
        if visible_to:
            agent_perms = set(self._pr.get_permissions(agent_id))
            if not (set(visible_to) & agent_perms):
                return False, "无权限查看该对象"
        req = ac.get("requires_permission", [])
        for pid in req:
            if not self._pr.has_permission(agent_id, pid):
                return False, f"缺少查看对象权限: {pid}"
        return True, ""

    def can_execute_action(self, agent_id: str, action_cfg: Dict[str, Any]) -> Tuple[bool, str]:
        req = action_cfg.get("permissions_required", [])
        for pid in req:
            if not self._pr.has_permission(agent_id, pid):
                return False, f"缺少执行动作权限: {pid}"
        return True, ""

    def can_use_tool(self, agent_id: str, tool_cfg: Dict[str, Any]) -> Tuple[bool, str]:
        allowed = tool_cfg.get("allowed_permissions", [])
        if not allowed:
            return True, ""
        for pid in allowed:
            if self._pr.has_permission(agent_id, pid):
                return True, ""
        return False, "无权限使用该工具"
