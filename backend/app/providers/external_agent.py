"""外部 Agent Provider：阻塞等待 WebSocket decision。"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, List, Optional

from app.agent_gateway.session_bus import (
    DEFAULT_TURN_TIMEOUT_MS,
    ExternalAgentNotConnected,
    get_session_bus,
)
from app.config import AgentSlotConfig
from app.providers.base import LLMProvider

logger = logging.getLogger(__name__)


class ExternalAgentProvider(LLMProvider):
    """driver=agent 时使用；complete 等价于等待外部 WS 提交 decision。"""

    def __init__(
        self,
        cfg: AgentSlotConfig,
        *,
        user_id: str = "",
        turn_timeout_ms: int = DEFAULT_TURN_TIMEOUT_MS,
    ):
        self._cfg = cfg
        self._user_id = user_id
        self._turn_timeout_ms = int(turn_timeout_ms)
        self._run_id: str = ""
        self._tick: int = 0
        self._brief: Any = None
        self._output_contract: Optional[Dict[str, Any]] = None
        self._last_tokens: Dict[str, int] = {"prompt": 0, "completion": 0}

    def set_user_context(
        self,
        user_id: str,
        *,
        turn_timeout_ms: Optional[int] = None,
    ) -> None:
        self._user_id = user_id
        if turn_timeout_ms is not None:
            self._turn_timeout_ms = int(turn_timeout_ms)

    def prepare_turn(
        self,
        *,
        tick: int,
        run_id: str,
        brief: Any,
        output_contract: Optional[Dict[str, Any]] = None,
    ) -> None:
        self._tick = tick
        self._run_id = run_id
        self._brief = brief
        self._output_contract = output_contract

    @property
    def provider_name(self) -> str:
        return "external"

    @property
    def model_name(self) -> str:
        label = getattr(self._cfg, "extra", {}) or {}
        if isinstance(label, dict) and label.get("agent_label"):
            return str(label["agent_label"])
        return "external-agent"

    @property
    def slot_id(self) -> str:
        return self._cfg.id

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        **kwargs: Any,
    ) -> str:
        return await self._wait_decision(system_prompt, user_message)

    async def complete_with_history(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> str:
        last_user = next(
            (m["content"] for m in reversed(messages) if m.get("role") == "user"),
            "",
        )
        return await self._wait_decision(system_prompt, last_user)

    async def _wait_decision(self, system_prompt: str, user_message: str) -> str:
        if not self._user_id:
            raise ExternalAgentNotConnected("引擎未绑定 user_id")

        bus = get_session_bus()
        try:
            raw = await bus.request_decision(
                user_id=self._user_id,
                slot_id=self._cfg.id,
                run_id=self._run_id or "run_pending",
                tick=self._tick,
                system_prompt=system_prompt,
                user_message=user_message,
                output_contract=self._output_contract,
                brief=self._brief,
                turn_timeout_ms=self._turn_timeout_ms,
            )
            self._last_tokens = {"prompt": 0, "completion": len(raw) // 4}
            return raw
        except ExternalAgentNotConnected:
            raise
        except TimeoutError:
            raise
        except Exception as exc:
            logger.warning(
                "[ExternalAgentProvider] slot=%s 决策失败: %s",
                self._cfg.id, exc,
            )
            raise

    async def get_usage(self) -> Dict[str, int]:
        return dict(self._last_tokens)
