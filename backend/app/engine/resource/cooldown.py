"""
P0-2 CooldownService — 冷却服务

管理 action/tool/location 的冷却状态。
"""
from __future__ import annotations

import logging
import copy
from typing import Any, Dict, List, Optional, Tuple

from app.core.interfaces import CooldownState

logger = logging.getLogger(__name__)


class CooldownService:
    """冷却管理：检查/写入/递减冷却状态"""

    def __init__(self):
        self._cooldowns: Dict[str, Dict[str, CooldownState]] = {}  # agent_id -> {entity_id -> state}

    def initialize_agent(self, agent_id: str) -> None:
        self._cooldowns[agent_id] = {}

    def is_cooling(self, agent_id: str, entity_id: str) -> Tuple[bool, int]:
        """检查是否在冷却中，返回 (is_cooling, remaining_ticks)"""
        cd = self._cooldowns.get(agent_id, {}).get(entity_id)
        if cd and cd.remaining_ticks > 0:
            return True, cd.remaining_ticks
        return False, 0

    def set_cooldown(self, agent_id: str, entity_id: str, entity_type: str, ticks: int) -> None:
        """设置冷却"""
        if agent_id not in self._cooldowns:
            self._cooldowns[agent_id] = {}
        self._cooldowns[agent_id][entity_id] = CooldownState(
            agent_id=agent_id, entity_id=entity_id,
            entity_type=entity_type, remaining_ticks=ticks,
        )

    def decrement_all(self) -> None:
        """每 tick 递减所有冷却"""
        for agent_cds in self._cooldowns.values():
            expired = []
            for eid, cd in agent_cds.items():
                cd.remaining_ticks -= 1
                if cd.remaining_ticks <= 0:
                    expired.append(eid)
            for eid in expired:
                del agent_cds[eid]

    def get_status(self, agent_id: str) -> Dict[str, int]:
        """返回 Agent 当前冷却状态 {entity_id: remaining_ticks}"""
        return {eid: cd.remaining_ticks for eid, cd in self._cooldowns.get(agent_id, {}).items()}

    def snapshot(self) -> Dict[str, Dict[str, CooldownState]]:
        return copy.deepcopy(self._cooldowns)

    def restore(self, snapshot: Dict[str, Dict[str, CooldownState]]) -> None:
        self._cooldowns = copy.deepcopy(snapshot)
