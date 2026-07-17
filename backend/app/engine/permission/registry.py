"""
P0-3 PermissionRegistry — 权限注册表

管理权限的注册和授予。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Set

from app.core.interfaces import PermissionGrant

logger = logging.getLogger(__name__)


class PermissionRegistry:
    """权限注册表：管理 Agent 权限的授予和查询"""

    def __init__(self):
        self._grants: Dict[str, List[PermissionGrant]] = {}  # agent_id -> [grants]

    def initialize_agent(self, agent_id: str, permissions: List[str], tick: int = 0) -> None:
        """为 Agent 初始化权限（通常从 roles.yaml 读取）"""
        self._grants[agent_id] = []
        for pid in permissions:
            self._grants[agent_id].append(PermissionGrant(
                agent_id=agent_id, permission_id=pid, source="role", tick_granted=tick,
            ))
        logger.info(f"[PermissionRegistry] Agent {agent_id} 获得 {len(permissions)} 个权限")

    def has_permission(self, agent_id: str, permission_id: str) -> bool:
        grants = self._grants.get(agent_id, [])
        return any(g.permission_id == permission_id for g in grants)

    def get_permissions(self, agent_id: str) -> List[str]:
        return [g.permission_id for g in self._grants.get(agent_id, [])]

    def grant(self, agent_id: str, permission_id: str, source: str = "event", tick: int = 0) -> None:
        if agent_id not in self._grants:
            self._grants[agent_id] = []
        if not self.has_permission(agent_id, permission_id):
            self._grants[agent_id].append(PermissionGrant(
                agent_id=agent_id, permission_id=permission_id, source=source, tick_granted=tick,
            ))

    def revoke(self, agent_id: str, permission_id: str) -> None:
        grants = self._grants.get(agent_id, [])
        self._grants[agent_id] = [g for g in grants if g.permission_id != permission_id]
