"""
P1-1 EventBus — 事件总线

注册和分发系统事件。
"""
from __future__ import annotations

import logging
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


class EventBus:
    """事件总线：发布/订阅模式"""

    def __init__(self):
        self._handlers: Dict[str, List[Callable]] = {}

    def subscribe(self, event_type: str, handler: Callable) -> None:
        self._handlers.setdefault(event_type, []).append(handler)

    async def publish(self, event_type: str, payload: Dict[str, Any]) -> None:
        for handler in self._handlers.get(event_type, []):
            try:
                result = handler(payload)
                if hasattr(result, "__await__"):
                    await result
            except Exception as e:
                logger.warning(f"[EventBus] handler 异常: {e}")
