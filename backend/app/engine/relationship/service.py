"""
P1-3 RelationshipService — 关系状态管理

管理 Agent 间关系：信任/敌意/合作/影响力/依赖/声誉。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

from app.core.interfaces import RelationshipState

logger = logging.getLogger(__name__)


class RelationshipService:
    """关系管理：Agent 间关系状态的 CRUD 和查询"""

    def __init__(self):
        self._relations: Dict[str, RelationshipState] = {}  # key: "src:tgt:type"

    def _key(self, src: str, tgt: str, rtype: str) -> str:
        return f"{src}:{tgt}:{rtype}"

    def initialize_pair(self, agent_a: str, agent_b: str, relation_types: List[str] = None) -> None:
        """初始化两个 Agent 之间的关系"""
        types = relation_types or ["trust", "hostility", "cooperation"]
        for rt in types:
            self._relations[self._key(agent_a, agent_b, rt)] = RelationshipState(
                source_agent_id=agent_a, target_agent_id=agent_b,
                relation_type=rt, value=0.0, visibility="private",
            )
            self._relations[self._key(agent_b, agent_a, rt)] = RelationshipState(
                source_agent_id=agent_b, target_agent_id=agent_a,
                relation_type=rt, value=0.0, visibility="private",
            )

    def get(self, src: str, tgt: str, rtype: str) -> Optional[RelationshipState]:
        return self._relations.get(self._key(src, tgt, rtype))

    def get_all_for_agent(self, agent_id: str) -> List[RelationshipState]:
        return [r for r in self._relations.values() if r.source_agent_id == agent_id]

    def update(
        self, src: str, tgt: str, rtype: str,
        delta: float, tick: int = 0, source_delta_id: Optional[str] = None,
    ) -> Optional[RelationshipState]:
        """更新关系值"""
        key = self._key(src, tgt, rtype)
        rel = self._relations.get(key)
        if not rel:
            rel = RelationshipState(
                source_agent_id=src, target_agent_id=tgt,
                relation_type=rtype,
            )
            self._relations[key] = rel
        rel.value = max(-100, min(100, rel.value + delta))
        rel.last_updated_tick = tick
        rel.source_delta_id = source_delta_id
        return rel

    def get_visible_for_agent(self, agent_id: str) -> List[RelationshipState]:
        """获取 Agent 可见的关系信息"""
        result = []
        for r in self._relations.values():
            if r.visibility == "public":
                result.append(r)
            elif r.visibility == "private" and r.source_agent_id == agent_id:
                result.append(r)
        return result
