"""
OpenAI-Compatible Provider

覆盖所有兼容 OpenAI Chat Completions API 的模型：
- OpenAI (gpt-4o, gpt-4-turbo ...)
- DeepSeek (deepseek-chat, deepseek-reasoner ...)
- 本地 Ollama / vLLM 等
"""
from __future__ import annotations

import asyncio
import logging
import os
from typing import Any, Dict, Optional

import httpx

from app.core.exceptions import ProviderError
from app.providers.base import LLMProvider

logger = logging.getLogger(__name__)

# P0-f：可重试错误判定 + 退避策略
_RETRYABLE_HTTP = {408, 429, 500, 502, 503, 504}
_RETRY_ATTEMPTS = 3
_RETRY_BASE_DELAY = 2.0   # 第 1 次重试等 2s，第 2 次 4s，第 3 次 8s（总 ~14s，留余量给 runtime 60s 硬上限）
# 总重试预算：runtime 对每个 agent 有 ~60s 硬超时（超时即 cancel）。
# 单次 HTTP timeout 60s × 3 次最坏可拖 3 分钟——超出硬超时的重试全是白烧钱。
# 超过预算后不再发起新的重试，直接抛出最后一次异常。
_RETRY_TOTAL_BUDGET_SEC = 45.0


class OpenAICompatProvider(LLMProvider):

    def __init__(
        self,
        model: str,
        api_key: Optional[str] = None,
        base_url: str = "https://api.openai.com/v1",
        provider_id: str = "openai",
        timeout: float = 60.0,
        supports_image_url: bool = True,
        default_temperature: float = 0.9,
        default_max_tokens: int = 1024,
    ):
        self._model = model
        self._api_key = api_key or os.environ.get("OPENAI_API_KEY", "")
        self._base_url = base_url.rstrip("/")
        self._chat_completions_url = (
            self._base_url
            if self._base_url.endswith("/chat/completions")
            else f"{self._base_url}/chat/completions"
        )
        self._provider_id = provider_id
        self._timeout = timeout
        self._supports_image_url = supports_image_url
        # 实例级采样默认值：framework.yaml 各 agent slot 的 extra 可按人设
        # 差异化（如甲 0.7 稳 / 乙 1.0 锐 / 丙 0.85），调用方 kwargs 仍可覆盖。
        self._default_temperature = float(default_temperature)
        self._default_max_tokens = int(default_max_tokens)
        self._last_usage: Dict[str, int] = {}
        # P0-f：429 / 5xx 错误计数器，便于诊断与监控
        self._429_count: int = 0
        self._5xx_count: int = 0

    @property
    def provider_name(self) -> str:
        return self._provider_id

    @property
    def model_name(self) -> str:
        return self._model

    async def _call_api(
        self,
        messages: list,
        temperature: Optional[float] = None,
        max_tokens: Optional[int] = None,
    ) -> str:
        """带 429/5xx 指数退避重试的 LLM 调用。

        防止多个角色同时遭遇 429 后持续返回空动作。
        加 retry + 错误升级日志后：偶发限流自愈，不再让 agent 单点故障拖死整局。
        """
        payload = {
            "model": self._model,
            "messages": messages,
            "temperature": (
                temperature if temperature is not None
                else self._default_temperature
            ),
            "max_tokens": (
                max_tokens if max_tokens is not None
                else self._default_max_tokens
            ),
        }
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        last_exc: Optional[Exception] = None
        _started = asyncio.get_event_loop().time()

        def _budget_left() -> bool:
            return (
                asyncio.get_event_loop().time() - _started
            ) < _RETRY_TOTAL_BUDGET_SEC

        for attempt in range(_RETRY_ATTEMPTS):
            async with httpx.AsyncClient(
                timeout=self._timeout,
                proxy=None,
                trust_env=False,
            ) as client:
                try:
                    resp = await client.post(
                        self._chat_completions_url,
                        json=payload,
                        headers=headers,
                    )
                    resp.raise_for_status()
                except httpx.HTTPStatusError as e:
                    code = e.response.status_code
                    body = e.response.text
                    # 错误升级 + 计数
                    if code == 429:
                        self._429_count += 1
                        logger.error(
                            f"[{self._provider_id}] ⚠️ HTTP 429 限流/配额 "
                            f"累计={self._429_count} 次 attempt={attempt + 1}/{_RETRY_ATTEMPTS} "
                            f"body={body[:200]}"
                        )
                    elif 500 <= code < 600:
                        self._5xx_count += 1
                        logger.error(
                            f"[{self._provider_id}] ⚠️ HTTP {code} 服务端错误 "
                            f"累计={self._5xx_count} 次 attempt={attempt + 1}/{_RETRY_ATTEMPTS}"
                        )
                    last_exc = ProviderError(
                        f"[{self._provider_id}] HTTP {code}: {body}"
                    )
                    if (
                        code in _RETRYABLE_HTTP
                        and attempt + 1 < _RETRY_ATTEMPTS
                        and _budget_left()
                    ):
                        delay = _RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            f"[{self._provider_id}] HTTP {code} 退避 {delay}s 后重试"
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise last_exc from e
                except httpx.RequestError as e:
                    last_exc = ProviderError(
                        f"[{self._provider_id}] 请求失败: type={type(e).__name__} repr={e!r}"
                    )
                    if attempt + 1 < _RETRY_ATTEMPTS and _budget_left():
                        delay = _RETRY_BASE_DELAY * (2 ** attempt)
                        logger.warning(
                            f"[{self._provider_id}] 网络异常 退避 {delay}s 后重试 ({e!r})"
                        )
                        await asyncio.sleep(delay)
                        continue
                    raise last_exc from e
                except Exception as e:
                    raise ProviderError(
                        f"[{self._provider_id}] 未知错误: type={type(e).__name__} repr={e!r}"
                    ) from e

            data = resp.json()
            usage = data.get("usage", {})
            self._last_usage = {
                "prompt_tokens": usage.get("prompt_tokens", 0),
                "completion_tokens": usage.get("completion_tokens", 0),
            }
            message = data["choices"][0]["message"]
            content = message.get("content") or ""
            # DeepSeek 等推理模型把思维链放在独立字段 reasoning_content（不在 content
            # 里，也不带 <think> 标签）。统一包成 <think>…</think> 拼到最前，让下游
            # CoT 落盘与展示层用同一套 <think> 逻辑处理 deepseek / minimax 两类模型。
            reasoning = message.get("reasoning_content") or message.get("reasoning")
            if reasoning and "<think>" not in content:
                content = f"<think>\n{str(reasoning).strip()}\n</think>\n{content}"
            return content
        # 理论上到不了这里——所有 attempt 失败的路径都 raise 了
        if last_exc:
            raise last_exc
        raise ProviderError(f"[{self._provider_id}] 重试耗尽但无明确异常")

    async def complete(self, system_prompt: str, user_message: str, **kwargs: Any) -> str:
        messages = [
            {"role": "system", "content": system_prompt},
            {"role": "user", "content": user_message},
        ]
        return await self._call_api(messages, **kwargs)

    async def complete_multimodal(
        self,
        system_prompt: str,
        user_message: str,
        image_data_urls: list,
        history: Optional[list] = None,
        **kwargs: Any,
    ) -> str:
        def _text_only_message() -> str:
            return (
                user_message
                + "\n\n[系统提示：当前模型接口不支持 image_url 图片输入，"
                "本轮已自动降级为纯文本模式；请只依据挑战材料文字和已知上下文作答。]"
            )

        if not self._supports_image_url:
            logger.warning(
                "[%s] 当前 Provider 不支持 image_url，已降级为纯文本调用 images=%s",
                self._provider_id,
                len(image_data_urls or []),
            )
            if history:
                return await self.complete_with_history(
                    system_prompt,
                    list(history) + [
                        {"role": "user", "content": _text_only_message()}
                    ],
                    **kwargs,
                )
            return await self.complete(system_prompt, _text_only_message(), **kwargs)

        content = [{"type": "text", "text": user_message}]
        content.extend({
            "type": "image_url",
            "image_url": {"url": url},
        } for url in image_data_urls)
        try:
            return await self._call_api([
                {"role": "system", "content": system_prompt},
                *(history or []),
                {"role": "user", "content": content},
            ], **kwargs)
        except ProviderError as exc:
            err = str(exc).lower()
            image_error_markers = (
                "image_url",
                "image input",
                "vision",
                "multimodal",
                "unsupported content",
                "invalid content type",
            )
            if any(marker in err for marker in image_error_markers):
                logger.warning(
                    "[%s] image_url 调用被接口拒绝，自动降级为纯文本重试: %s",
                    self._provider_id,
                    str(exc)[:240],
                )
                if history:
                    return await self.complete_with_history(
                        system_prompt,
                        list(history) + [
                            {"role": "user", "content": _text_only_message()}
                        ],
                        **kwargs,
                    )
                return await self.complete(
                    system_prompt, _text_only_message(), **kwargs
                )
            raise

    async def complete_with_history(
        self,
        system_prompt: str,
        messages: list,
        **kwargs: Any,
    ) -> str:
        """传入完整对话历史，让模型具备上下文继承能力。"""
        full_messages = [{"role": "system", "content": system_prompt}] + messages
        return await self._call_api(
            full_messages,
            temperature=kwargs.get("temperature"),
            max_tokens=kwargs.get("max_tokens"),
        )

    async def get_usage(self) -> Dict[str, int]:
        return self._last_usage


def make_deepseek(
    model: str = "deepseek-chat",
    api_key: Optional[str] = None,
    **sampling: Any,
) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        model=model,
        api_key=api_key or os.environ.get("DEEPSEEK_API_KEY"),
        base_url="https://api.deepseek.com/v1",
        provider_id="deepseek",
        supports_image_url=False,
        **sampling,
    )


def make_openai(
    model: str = "gpt-4o",
    api_key: Optional[str] = None,
    **sampling: Any,
) -> OpenAICompatProvider:
    return OpenAICompatProvider(
        model=model,
        api_key=api_key or os.environ.get("OPENAI_API_KEY"),
        base_url="https://api.openai.com/v1",
        provider_id="openai",
        **sampling,
    )
