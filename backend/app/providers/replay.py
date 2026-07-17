"""Deterministic provider for offline, auditable replay runs.

The provider is deliberately not an LLM and never reaches the network.  A
scenario or CLI supplies a per-agent action script; each call returns the next
scripted structured decision, while preserving fixture observations in the
action parameters so EngineOS can turn them into authoritative observations.
"""
from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from typing import Any, Dict, List, Optional

from app.providers.base import LLMProvider


class ReplayProvider(LLMProvider):
    """Fixed action script provider used by no-key replay examples."""

    def __init__(
        self,
        *,
        actions: Optional[List[Dict[str, Any]]] = None,
        model_name: str = "replay-v1",
        delay: float = 0.0,
    ) -> None:
        self._actions = [
            deepcopy(item) for item in (actions or []) if isinstance(item, dict)
        ]
        self._model_name = model_name
        self._delay = max(0.0, float(delay))
        self._cursor = 0

    @property
    def provider_name(self) -> str:
        return "replay"

    @property
    def model_name(self) -> str:
        return self._model_name

    @property
    def cursor(self) -> int:
        return self._cursor

    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        **kwargs: Any,
    ) -> str:
        del system_prompt, user_message, kwargs
        if self._delay:
            await asyncio.sleep(self._delay)
        if self._cursor < len(self._actions):
            payload = deepcopy(self._actions[self._cursor])
        else:
            payload = {
                "action_id": "wait_and_review",
                "action_name": "Replay wait",
                "plan": "No scripted action remains; preserve the recorded state.",
                "public_reasoning_summary": "No scripted action remains.",
                "character_monologue": "I hold the recorded state.",
                "parameters": {},
                "evidence_refs": [],
            }
        self._cursor += 1
        return json.dumps(payload, ensure_ascii=False)

    def reset(self) -> None:
        self._cursor = 0

