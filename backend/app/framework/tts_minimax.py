"""
MiniMax T2A v2 语音合成封装

调用 MiniMax T2A v2 将解说文字合成为 MP3，返回 base64 字符串。
前端通过 data:audio/mp3;base64,<str> 直接播放，无需存文件。
"""
from __future__ import annotations

import base64
import os
from typing import Optional

import httpx


_T2A_URL = "https://api.minimax.chat/v1/t2a_v2"


class MinimaxTTS:
    """MiniMax T2A v2 非流式合成器"""

    def __init__(
        self,
        api_key: str = "",
        group_id: str = "",
        voice_id: str = "presenter_male",
        speed: float = 1.0,
        timeout: float = 15.0,
    ):
        self._api_key = api_key or os.environ.get("MINIMAX_API_KEY", "")
        self._group_id = group_id or os.environ.get("MINIMAX_GROUP_ID", "")
        self._voice_id = voice_id
        self._speed = speed
        self._timeout = timeout

    @property
    def is_configured(self) -> bool:
        """Whether the runtime has both credentials required by MiniMax TTS."""
        return bool(self._api_key and self._group_id)

    async def synthesize(self, text: str) -> Optional[str]:
        """
        将文字合成为 MP3，返回 base64 字符串。
        任何异常静默返回 None，不影响调用方流程。
        """
        if not text.strip() or not self.is_configured:
            return None
        try:
            return await self._call_api(text)
        except Exception as e:
            print(f"[tts] 合成失败: {e}")
            return None

    async def _call_api(self, text: str) -> Optional[str]:
        url = f"{_T2A_URL}?GroupId={self._group_id}"
        headers = {
            "Authorization": f"Bearer {self._api_key}",
            "Content-Type": "application/json",
        }
        payload = {
            "model": "speech-01-turbo",
            "text": text,
            "stream": False,
            "voice_setting": {
                "voice_id": self._voice_id,
                "speed": self._speed,
                "vol": 1.0,
                "pitch": 0,
            },
            "audio_setting": {
                "sample_rate": 32000,
                "bitrate": 128000,
                "format": "mp3",
                "channel": 1,
            },
        }
        async with httpx.AsyncClient(
            timeout=self._timeout,
            proxy=None,
            trust_env=False,
        ) as client:
            resp = await client.post(url, headers=headers, json=payload)
            resp.raise_for_status()
            data = resp.json()

        base_resp = data.get("base_resp", {})
        if base_resp.get("status_code", 0) != 0:
            print(f"[tts] API 错误: {base_resp.get('status_msg')}")
            return None

        audio_hex = data.get("data", {}).get("audio", "")
        if not audio_hex:
            return None

        # hex → bytes → base64
        audio_bytes = bytes.fromhex(audio_hex)
        return base64.b64encode(audio_bytes).decode("utf-8")
