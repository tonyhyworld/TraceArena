"""
P1-2 KnowledgeState — Agent 已知信息状态

区分 WorldState / Perception / Memory / KnowledgeState / EvidenceState。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class KnowledgeState:
    """Agent 已知信息状态（基于 MemoryService 的上层抽象）"""

    def __init__(self, memory_service: Any):
        self._memory = memory_service

    def update_from_perception(self, agent_id: str, perception_data: Dict[str, Any], tick: int) -> None:
        """从感知数据更新已知信息"""
        for obj in perception_data.get("visible_objects", []):
            obj_id = obj.get("id", obj.get("object_id", ""))
            if obj_id:
                self._memory.remember(agent_id, "object", obj_id, content=obj, tick=tick)

        for ev in perception_data.get("known_evidence", []):
            if isinstance(ev, str):
                self._memory.remember(agent_id, "evidence", ev, tick=tick)
            elif isinstance(ev, dict):
                eid = ev.get("evidence_id", "")
                if eid:
                    self._memory.remember(agent_id, "evidence", eid, content=ev, tick=tick)

    def get_beliefs(self, agent_id: str) -> Dict[str, Any]:
        """获取 Agent 当前信念（已知且未过期的信息）"""
        entries = self._memory.get_knowledge(agent_id)
        beliefs = {}
        for e in entries:
            if not e.stale:
                key = f"{e.entity_type}:{e.entity_id}"
                beliefs[key] = {
                    "content": e.content,
                    "confidence": e.confidence,
                    "last_seen": e.last_seen_tick,
                }
        return beliefs
