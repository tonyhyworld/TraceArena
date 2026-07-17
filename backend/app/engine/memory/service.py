"""
P1-2 MemoryService — 记忆服务

管理 Agent 的记忆：写入/查询/过期标记。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.interfaces import KnowledgeEntry

logger = logging.getLogger(__name__)


class MemoryService:
    """记忆服务：Agent 已知信息管理"""

    def __init__(self, stale_after_ticks: int = 10):
        self._entries: Dict[str, Dict[str, KnowledgeEntry]] = {}  # agent_id -> {entity_key -> entry}
        self._stale_after = stale_after_ticks

    def remember(
        self, agent_id: str, entity_type: str, entity_id: str,
        content: Dict[str, Any] = None, tick: int = 0,
    ) -> KnowledgeEntry:
        """记录 Agent 看到/知道的信息"""
        if agent_id not in self._entries:
            self._entries[agent_id] = {}
        key = f"{entity_type}:{entity_id}"
        existing = self._entries[agent_id].get(key)
        if existing:
            existing.last_seen_tick = tick
            existing.stale = False
            if content:
                existing.content.update(content)
            return existing
        entry = KnowledgeEntry(
            agent_id=agent_id, entity_type=entity_type, entity_id=entity_id,
            known_since_tick=tick, last_seen_tick=tick, content=content or {},
        )
        self._entries[agent_id][key] = entry
        return entry

    def get_knowledge(self, agent_id: str, entity_type: Optional[str] = None) -> List[KnowledgeEntry]:
        """查询 Agent 已知信息"""
        entries = list(self._entries.get(agent_id, {}).values())
        if entity_type:
            entries = [e for e in entries if e.entity_type == entity_type]
        return entries

    def mark_stale(self, current_tick: int) -> None:
        """标记过期信息"""
        for agent_entries in self._entries.values():
            for entry in agent_entries.values():
                if current_tick - entry.last_seen_tick > self._stale_after:
                    entry.stale = True

    def get_memory_summary(self, agent_id: str, max_items: int = 10) -> str:
        """生成记忆摘要（供 PerceptionPacket 使用）"""
        entries = self.get_knowledge(agent_id)
        active = [e for e in entries if not e.stale][:max_items]
        if not active:
            return "无已知信息。"
        lines = []
        for e in active:
            lines.append(f"[{e.entity_type}] {e.entity_id} (confidence={e.confidence:.1f})")
        return "; ".join(lines)

    def get_known_evidence_ids(self, agent_id: str) -> List[str]:
        """获取 Agent 已知的证据 ID"""
        entries = self.get_knowledge(agent_id, "evidence")
        return [e.entity_id for e in entries if not e.stale]
