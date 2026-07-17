"""
EvidenceService：证据生命周期管理

铁律：所有证据必须有来源，无来源的证据标记为 unverified_hypothesis。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.interfaces import EvidenceEntry


class EvidenceService:
    """管理证据的创建、验证和使用。"""

    def __init__(self):
        self._ledger: List[EvidenceEntry] = []
        self._index: Dict[str, EvidenceEntry] = {}
        self._current_tick: int = 0
        self._seq: int = 0

    def set_tick(self, tick: int) -> None:
        self._current_tick = tick

    def create(
        self,
        creator_id: str,
        target_id: Optional[str],
        claim: str,
        source_action_id: Optional[str] = None,
        source_tool_id: Optional[str] = None,
        supporting_event_ids: List[str] = [],
        supporting_object_states: Dict[str, Any] = {},
        confidence: float = 0.5,
    ) -> EvidenceEntry:
        """
        创建证据条目。没有任何来源的证据 verification_status = "unverified_hypothesis"。
        """
        has_source = any([
            source_action_id,
            source_tool_id,
            supporting_event_ids,
        ])
        verification_status = "unverified" if has_source else "unverified_hypothesis"

        self._seq += 1
        evidence_id = f"evid_{self._current_tick}_{self._seq:04d}"

        entry = EvidenceEntry(
            evidence_id=evidence_id,
            created_by=creator_id,
            target_id=target_id,
            claim=claim,
            source_action_id=source_action_id,
            source_tool_id=source_tool_id,
            supporting_event_ids=list(supporting_event_ids),
            supporting_object_states=dict(supporting_object_states),
            verification_status=verification_status,
            used_by_actions=[],
            impact_score=0.0,
            confidence=confidence,
            tick_created=self._current_tick,
        )
        self._ledger.append(entry)
        self._index[evidence_id] = entry
        return entry

    def verify(self, evidence_id: str) -> None:
        """将证据标记为已验证。"""
        entry = self._index.get(evidence_id)
        if entry:
            entry.verification_status = "verified"

    def mark_used(self, evidence_id: str, action_id: str) -> None:
        """记录证据被某行动使用。"""
        entry = self._index.get(evidence_id)
        if entry and action_id not in entry.used_by_actions:
            entry.used_by_actions.append(action_id)

    def get(self, evidence_id: str) -> Optional[EvidenceEntry]:
        return self._index.get(evidence_id)

    def is_visible_to(self, agent_id: str, evidence_id: str, current_tick: Optional[int] = None) -> bool:
        """P1-4: 判断证据对指定 Agent 是否可见"""
        entry = self._index.get(evidence_id)
        if not entry:
            return False
        # 过期检查
        if entry.expires_tick is not None and current_tick is not None:
            if current_tick > entry.expires_tick:
                return False
        # 可见性规则
        if entry.visibility == "public":
            return True
        if entry.visibility == "private":
            return entry.created_by == agent_id
        if entry.visibility == "restricted":
            return agent_id in entry.visible_to_agents or entry.created_by == agent_id
        return entry.created_by == agent_id

    def get_visible_evidence(self, agent_id: str, current_tick: Optional[int] = None) -> List[str]:
        """P1-4: 返回 Agent 可见的证据 ID 列表"""
        result = []
        for entry in self._ledger:
            if self.is_visible_to(agent_id, entry.evidence_id, current_tick):
                result.append(entry.evidence_id)
        return result

    @property
    def ledger(self) -> List[EvidenceEntry]:
        return self._ledger
