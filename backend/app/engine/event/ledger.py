"""Authoritative append-only WorldEvent ledger for AI World OS 2.0."""
from __future__ import annotations

from typing import Dict, Iterable, List, Optional

from app.contracts.os2 import WorldEvent


class WorldEventLedger:
    """Stores immutable world facts and rejects duplicate event identities."""

    def __init__(self) -> None:
        self._events: List[WorldEvent] = []
        self._index: Dict[str, WorldEvent] = {}

    def append(self, event: WorldEvent) -> None:
        if event.event_id in self._index:
            raise ValueError(f"duplicate_world_event:{event.event_id}")
        frozen = WorldEvent.model_validate(event.model_dump(mode="python"))
        self._events.append(frozen)
        self._index[frozen.event_id] = frozen

    def extend(self, events: Iterable[WorldEvent]) -> None:
        pending = list(events)
        ids = [event.event_id for event in pending]
        if len(ids) != len(set(ids)):
            raise ValueError("duplicate_world_event_in_batch")
        duplicate = next((event_id for event_id in ids if event_id in self._index), None)
        if duplicate:
            raise ValueError(f"duplicate_world_event:{duplicate}")
        for event in pending:
            self.append(event)

    def get(self, event_id: str) -> Optional[WorldEvent]:
        return self._index.get(event_id)

    def by_tick(self, world_tick: int) -> List[WorldEvent]:
        return [event for event in self._events if event.world_tick == world_tick]

    def visible_to(self, agent_id: Optional[str]) -> List[WorldEvent]:
        if agent_id is None:
            return [
                event for event in self._events
                if event.visibility in ("public", "operator_only")
            ]
        return [
            event for event in self._events
            if event.visibility == "public"
            or event.actor_id == agent_id
            or agent_id in event.target_ids
        ]

    def all(self) -> List[WorldEvent]:
        return list(self._events)
