"""
LLM Provider 抽象基类

新增模型 = 继承 LLMProvider，实现 complete()，在 registry 注册一行。
框架其余代码完全不感知具体模型。
"""
from __future__ import annotations

import json
import re
from abc import ABC, abstractmethod
from typing import Any, Dict, List, Optional

from app.core.interfaces import ActionOption, ActionPack


class LLMProvider(ABC):
    """所有 LLM Provider 的统一接口"""

    @property
    @abstractmethod
    def provider_name(self) -> str:
        """Provider 标识符，如 'openai' / 'deepseek' / 'mock'"""
        ...

    @property
    @abstractmethod
    def model_name(self) -> str:
        """当前使用的模型名"""
        ...

    @abstractmethod
    async def complete(
        self,
        system_prompt: str,
        user_message: str,
        **kwargs: Any,
    ) -> str:
        """
        调用模型（单轮），返回原始文本响应。
        框架负责超时控制，Provider 只管调用。
        """
        ...

    async def complete_with_history(
        self,
        system_prompt: str,
        messages: List[Dict[str, str]],
        **kwargs: Any,
    ) -> str:
        """
        多轮对话调用，携带历史上下文。
        messages 格式：[{"role": "user", "content": "..."}, {"role": "assistant", "content": "..."}, ...]
        末尾必须是 role=user 的当前输入。

        默认实现：降级为单轮（只取最后一条 user 消息），
        OpenAI-compat 等 Provider 应覆盖此方法传完整 messages 列表。
        """
        last_user = next(
            (m["content"] for m in reversed(messages) if m["role"] == "user"), ""
        )
        return await self.complete(system_prompt, last_user, **kwargs)

    async def complete_multimodal(
        self,
        system_prompt: str,
        user_message: str,
        image_data_urls: List[str],
        history: Optional[List[Dict[str, str]]] = None,
        **kwargs: Any,
    ) -> str:
        """多模态调用；不支持视觉的 Provider 明确降级为文本（history 一并保留）。"""
        degraded = (
            user_message
            + "\n\n[系统提示：当前 Provider 不支持图像输入，无法可靠完成视觉任务。]"
        )
        if history:
            return await self.complete_with_history(
                system_prompt,
                list(history) + [{"role": "user", "content": degraded}],
                **kwargs,
            )
        return await self.complete(system_prompt, degraded, **kwargs)

    async def get_usage(self) -> Dict[str, int]:
        """返回最近一次调用的 token 用量，不支持的 Provider 返回空"""
        return {}

    # ------------------------------------------------------------------
    # ActionPack 解析（可覆盖，默认用通用 JSON 解析）
    # ------------------------------------------------------------------

    async def parse_action(
        self,
        raw_response: str,
        agent_id: str,
        available_actions: List[ActionOption],
    ) -> ActionPack:
        """
        把 LLM 原始输出解析成 ActionPack。
        默认策略：在响应里找第一个合法 JSON 块。
        场景包或子类可覆盖此方法实现自定义解析逻辑。
        """
        data = self._extract_json(raw_response)
        action_id = data.get("action", "")
        valid_ids = {a.id for a in available_actions}

        # 如果模型给的 action_id 不在菜单里，fallback 到 wait（如果有）
        if action_id not in valid_ids:
            fallback = next((a.id for a in available_actions if a.id == "wait"), None)
            if fallback is None and available_actions:
                fallback = available_actions[0].id
            action_id = fallback or "wait"

        # v2.0 新增字段
        linked_evidence_ids = data.get("linked_evidence_ids", [])
        if not isinstance(linked_evidence_ids, list):
            linked_evidence_ids = []

        # P0-e（C方案）：当 text 是 dict/list（挑战作答用 JSON 结构），
        # 用 json.dumps 保留为合法 JSON 字符串；用 str() 会变成 Python repr
        # （单引号），下游 json.loads 无法解析，挑战判分全失败。
        raw_text = data.get("text", "")
        if isinstance(raw_text, (dict, list)):
            text_field = json.dumps(raw_text, ensure_ascii=False)
        else:
            text_field = str(raw_text)
        return ActionPack(
            agent_id=agent_id,
            action_id=action_id,
            target_agent_id=data.get("target") or None,
            text=text_field,
            thought=str(data.get("thought", "")),
            character_monologue=str(data.get("character_monologue", "")),
            public_reasoning_summary=str(
                data.get("public_reasoning_summary", "")
            ),
            code=str(data.get("code", "")).strip(),
            # v2.0
            target_object_id=data.get("target_object_id") or None,
            linked_evidence_ids=linked_evidence_ids,
            attached_tool_id=data.get("attached_tool_id") or None,
            declared_intent=str(data.get("declared_intent", "")),
        )

    @staticmethod
    def _extract_json(text: str) -> Dict[str, Any]:
        """从任意文本里提取第一个 JSON 对象，容忍 markdown 代码块"""
        # 去掉 ```json ... ``` 包装
        text = re.sub(r"```(?:json)?\s*", "", text).replace("```", "")
        match = re.search(r"\{.*\}", text, re.DOTALL)
        if not match:
            return {}
        try:
            return json.loads(match.group())
        except json.JSONDecodeError:
            return {}
