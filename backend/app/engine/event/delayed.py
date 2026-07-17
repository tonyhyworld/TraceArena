"""
P1-1 DelayedEffectService — 延迟效果服务

处理延迟事件的执行，确保延迟效果仍走因果物理链路。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.interfaces import ScheduledEvent

logger = logging.getLogger(__name__)


class DelayedEffectService:
    """延迟效果：确保延迟事件触发时仍走 StateDelta 链路"""

    def __init__(self, event_queue: Any, event_bus: Any = None):
        self._queue = event_queue
        self._bus = event_bus

    async def process_due_events(self, current_tick: int) -> List[ScheduledEvent]:
        """处理当前 tick 到期的延迟事件"""
        due = self._queue.get_due_events(current_tick)
        for event in due:
            logger.info(f"[DelayedEffect] 触发延迟事件: {event.event_id} type={event.event_type}")
            if self._bus:
                await self._bus.publish(f"delayed:{event.event_type}", event.model_dump())
        return due

    def schedule_delayed_effect(
        self, tick: int, delay_ticks: int, effect_type: str,
        payload: Dict[str, Any] = None,
        source_action_id: Optional[str] = None,
        target_object_id: Optional[str] = None,
    ) -> str:
        """调度一个延迟效果"""
        event = self._queue.create_event(
            tick=tick, tick_due=tick + delay_ticks,
            event_type=effect_type, payload=payload,
            source_action_id=source_action_id,
            target_object_id=target_object_id,
        )
        return self._queue.schedule(event)
