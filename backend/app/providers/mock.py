"""
Mock Provider：无需 API Key，用于本地调试和框架验证
"""
from __future__ import annotations

import asyncio
import json
import random
import re
from typing import Any, Dict, List, Optional

from app.core.interfaces import ActionOption, ActionPack
from app.providers.base import LLMProvider


_THOUGHTS = [
    "局势微妙，需要谨慎行事。",
    "机会来了，现在是出手的最好时机。",
    "必须先观察一下，不能急于求成。",
    "对方的意图很明显，我得提前布局。",
    "韬光养晦，静待时机。",
]


class MockProvider(LLMProvider):
    """
    本地 Mock，随机选一个可用动作返回，附带随机思维链。
    框架验证和无 Key 环境下的降级 Provider。
    """

    def __init__(
        self,
        delay: float = 0.5,
        seed: Optional[int] = None,
        model_name: str = "mock-v1",
    ):
        self._delay = delay  # 模拟网络延迟
        self._rng = random.Random(seed)
        self._model_name = model_name

    @property
    def provider_name(self) -> str:
        return "mock"

    @property
    def model_name(self) -> str:
        return self._model_name

    async def complete(self, system_prompt: str, user_message: str, **kwargs: Any) -> str:
        await asyncio.sleep(self._delay)
        action_ids = self._extract_ids(
            user_message, r"intent 字段必须是以下英文 id 之一：([^\n]+)"
        )
        object_ids = self._extract_ids(
            user_message, r"target_object_id 必须是以下英文 id 之一：([^\n]+)"
        )
        evidence_ids = self._extract_ids(
            user_message, r"(?:证据|evidence)(?:_id)? 必须是以下英文 id 之一：([^\n]+)"
        )
        reachable_location_ids = self._extract_reachable_location_ids(user_message)
        action_entries = self._extract_action_entries(user_message)
        if not action_ids:
            action_ids = [item["id"] for item in action_entries]
        if not object_ids:
            object_ids = re.findall(r"id=([a-zA-Z0-9_:-]+)", user_message)

        executable_entries = [
            entry for entry in action_entries
            if self._has_target_for_entry(
                entry,
                object_ids=object_ids,
                evidence_ids=evidence_ids,
                reachable_location_ids=reachable_location_ids,
            )
        ]
        selection_pool = executable_entries or [
            {"id": action_id, "target_kind": "", "eligible_agent_ids": []}
            for action_id in action_ids
        ]
        if self._model_name.endswith("-last"):
            chosen = selection_pool[-1] if selection_pool else {"id": "wait"}
        elif self._model_name.endswith("-random"):
            chosen = self._rng.choice(selection_pool) if selection_pool else {"id": "wait"}
        else:
            chosen = selection_pool[0] if selection_pool else {"id": "wait"}

        action_id = str(chosen.get("id") or "wait")
        target_kind = str(chosen.get("target_kind") or "")
        target_object_id = None
        target_agent_id = None
        if target_kind == "location" and reachable_location_ids:
            target_object_id = self._rng.choice(reachable_location_ids)
        elif target_kind == "agent":
            eligible = list(chosen.get("eligible_agent_ids") or [])
            if eligible:
                target_agent_id = self._rng.choice(eligible)
        elif target_kind == "evidence" and evidence_ids:
            target_object_id = self._rng.choice(evidence_ids)
        elif target_kind == "object" and object_ids:
            target_object_id = self._rng.choice(object_ids)

        return json.dumps({
            "action_id": action_id,
            "target_object_id": target_object_id,
            "target_agent_id": target_agent_id,
            "action_name": "Mock决策",
            "plan": "基于当前公开信息采取可执行行动",
            "resource_commitment": 0.5,
            "risk_control": 0.6,
            "expected_effect": "形成可审计结果",
            "public_reasoning_summary": {
                "strategy_choice": "选择当前允许的行动",
                "risk_consideration": "控制资源和失败风险",
            },
            "character_monologue": "我先稳住局面，再寻找下一步机会。",
        }, ensure_ascii=False)

    async def parse_action(
        self,
        raw_response: str,
        agent_id: str,
        available_actions: List[ActionOption],
    ) -> ActionPack:
        """Mock 直接随机选动作，忽略 raw_response"""
        chosen = self._rng.choice(available_actions) if available_actions else None
        return ActionPack(
            agent_id=agent_id,
            action_id=chosen.id if chosen else "wait",
            target_agent_id=None,
            text="（Mock 发言）",
            character_monologue=self._rng.choice(_THOUGHTS),
            public_reasoning_summary="基于当前公开信息选择可执行行动。",
        )

    @staticmethod
    def _extract_ids(text: str, pattern: str) -> List[str]:
        match = re.search(pattern, text)
        if not match:
            return []
        return [
            item.strip()
            for item in match.group(1).split(",")
            if item.strip()
        ]

    @staticmethod
    def _extract_bullets(text: str, heading: str) -> List[str]:
        if heading not in text:
            return []
        block = text.split(heading, 1)[1].split("###", 1)[0]
        return re.findall(r"^\s*-\s+([a-zA-Z0-9_:-]+)：", block, re.MULTILINE)

    @staticmethod
    def _extract_action_entries(text: str) -> List[Dict[str, Any]]:
        if "可选行动" not in text:
            return []
        block = text.split("可选行动", 1)[1].split("###", 1)[0]
        entries = []
        for line in block.splitlines():
            match = re.match(r"^\s*-\s+([a-zA-Z0-9_:-]+)：", line)
            if match:
                target_kind = ""
                if "【目标=地点ID" in line:
                    target_kind = "location"
                elif "【目标=世界对象ID" in line:
                    target_kind = "object"
                elif "【目标=证据ID" in line:
                    target_kind = "evidence"
                elif "【目标=角色ID" in line:
                    target_kind = "agent"
                eligible_match = re.search(r"可选=([a-zA-Z0-9_:,-]+)", line)
                eligible_agent_ids = (
                    [
                        item.strip()
                        for item in eligible_match.group(1).split(",")
                        if item.strip()
                    ]
                    if eligible_match else []
                )
                entries.append({
                    "id": match.group(1),
                    "target_kind": target_kind,
                    "eligible_agent_ids": eligible_agent_ids,
                })
        return entries

    @staticmethod
    def _extract_reachable_location_ids(text: str) -> List[str]:
        marker = "可到达的地点"
        if marker not in text:
            return []
        block = text.split(marker, 1)[1].split("###", 1)[0]
        return re.findall(
            r"^\s*-\s+([a-zA-Z0-9_:-]+)（",
            block,
            re.MULTILINE,
        )

    @staticmethod
    def _has_target_for_entry(
        entry: Dict[str, Any],
        *,
        object_ids: List[str],
        evidence_ids: List[str],
        reachable_location_ids: List[str],
    ) -> bool:
        target_kind = str(entry.get("target_kind") or "")
        if not target_kind:
            return True
        if target_kind == "location":
            return bool(reachable_location_ids)
        if target_kind == "agent":
            return bool(entry.get("eligible_agent_ids"))
        if target_kind == "evidence":
            return bool(evidence_ids)
        return bool(object_ids)
