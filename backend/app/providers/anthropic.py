"""Anthropic (Claude) Provider"""
from __future__ import annotations

import os
import re
from typing import Any, Dict, Optional

import httpx

from app.core.exceptions import ProviderError
from app.providers.base import LLMProvider


class AnthropicProvider(LLMProvider):

    API_URL = "https://api.anthropic.com/v1/messages"
    API_VERSION = "2023-06-01"

    def __init__(
        self, model: str = "claude-3-5-sonnet-20241022", timeout: float = 60.0,
        api_key: Optional[str] = None,
    ):
        self._model = model
        self._api_key = api_key or os.environ.get("ANTHROPIC_API_KEY", "")
        self._timeout = timeout
        self._last_usage: Dict[str, int] = {}

    @property
    def provider_name(self) -> str:
        return "anthropic"

    @property
    def model_name(self) -> str:
        return self._model

    async def complete(self, system_prompt: str, user_message: str, **kwargs: Any) -> str:
        payload = {
            "model": self._model,
            "max_tokens": kwargs.get("max_tokens", 1024),
            "system": system_prompt,
            "messages": [{"role": "user", "content": user_message}],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }

        async with httpx.AsyncClient(
            timeout=self._timeout,
            proxy=None,
            trust_env=False,
        ) as client:
            try:
                resp = await client.post(self.API_URL, json=payload, headers=headers)
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ProviderError(
                    f"[anthropic] HTTP {e.response.status_code}: {e.response.text}"
                ) from e
            except httpx.RequestError as e:
                raise ProviderError(f"[anthropic] 请求失败: {e}") from e

        data = resp.json()
        usage = data.get("usage", {})
        self._last_usage = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }
        return data["content"][0]["text"]

    async def complete_multimodal(
        self,
        system_prompt: str,
        user_message: str,
        image_data_urls: list,
        history: list = None,
        **kwargs: Any,
    ) -> str:
        content = [{"type": "text", "text": user_message}]
        for url in image_data_urls:
            match = re.match(r"data:([^;]+);base64,(.+)", url, re.DOTALL)
            if not match:
                continue
            content.append({
                "type": "image",
                "source": {
                    "type": "base64",
                    "media_type": match.group(1),
                    "data": match.group(2),
                },
            })
        payload = {
            "model": self._model,
            "max_tokens": kwargs.get("max_tokens", 1024),
            "system": system_prompt,
            "messages": [
                *(history or []),
                {"role": "user", "content": content},
            ],
        }
        headers = {
            "x-api-key": self._api_key,
            "anthropic-version": self.API_VERSION,
            "content-type": "application/json",
        }
        async with httpx.AsyncClient(
            timeout=self._timeout,
            proxy=None,
            trust_env=False,
        ) as client:
            try:
                resp = await client.post(
                    self.API_URL, json=payload, headers=headers
                )
                resp.raise_for_status()
            except httpx.HTTPStatusError as e:
                raise ProviderError(
                    f"[anthropic] HTTP {e.response.status_code}: {e.response.text}"
                ) from e
            except httpx.RequestError as e:
                raise ProviderError(f"[anthropic] 请求失败: {e}") from e
        data = resp.json()
        usage = data.get("usage", {})
        self._last_usage = {
            "input_tokens": usage.get("input_tokens", 0),
            "output_tokens": usage.get("output_tokens", 0),
        }
        return data["content"][0]["text"]

    async def get_usage(self) -> Dict[str, int]:
        return self._last_usage
