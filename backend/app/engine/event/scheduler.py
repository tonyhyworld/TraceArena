"""
P1-1 ScheduledEventQueue — 延迟事件队列

管理延迟事件的调度和触发。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.interfaces import ScheduledEvent

logger = logging.getLogger(__name__)


class ScheduledEventQueue:
    """延迟事件队列"""

    def __init__(self):
        self._queue: List[ScheduledEvent] = []
        self._seq: int = 0

    def schedule(self, event: ScheduledEvent) -> str:
        self._queue.append(event)
        logger.info(f"[Scheduler] 事件已调度: {event.event_id} due_tick={event.tick_due}")
        return event.event_id

    def create_event(
        self, tick: int, tick_due: int, event_type: str,
        payload: Dict[str, Any] = None,
        source_action_id: Optional[str] = None,
        target_object_id: Optional[str] = None,
        target_agent_id: Optional[str] = None,
    ) -> ScheduledEvent:
        self._seq += 1
        event = ScheduledEvent(
            event_id=f"sched_{tick}_{self._seq:04d}",
            tick_created=tick, tick_due=tick_due,
            event_type=event_type, payload=payload or {},
            source_action_id=source_action_id,
            target_object_id=target_object_id,
            target_agent_id=target_agent_id,
        )
        return event

    def get_due_events(self, current_tick: int) -> List[ScheduledEvent]:
        """获取当前 tick 应触发的事件"""
        due = [e for e in self._queue if e.status == "pending" and e.tick_due <= current_tick]
        for e in due:
            e.status = "triggered"
        return due

    def cancel(self, event_id: str) -> bool:
        for e in self._queue:
            if e.event_id == event_id and e.status == "pending":
                e.status = "cancelled"
                return True
        return False

    @property
    def pending_count(self) -> int:
        return sum(1 for e in self._queue if e.status == "pending")
