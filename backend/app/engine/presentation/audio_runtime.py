"""Scenario-neutral audio adapter for fact-bound DirectorPlan output."""
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List


class PresentationAudioRuntime:
    """Synthesizes public director text without owning narrative decisions."""

    def __init__(self, tts: Any = None):
        self._tts = tts

    async def synthesize_text_chunks(
        self,
        text: str,
        max_chars: int = 105,
    ) -> List[Dict[str, Any]]:
        if not self._tts:
            return []
        normalized = re.sub(r"\s+", " ", str(text or "")).strip()
        if not normalized:
            return []
        sentences = [
            item.strip()
            for item in re.split(r"(?<=[。！？；])", normalized)
            if item.strip()
        ] or [normalized]
        texts: List[str] = []
        current = ""
        for sentence in sentences:
            if current and len(current) + len(sentence) > max_chars:
                texts.append(current)
                current = ""
            while len(sentence) > max_chars:
                room = max_chars - len(current)
                current += sentence[:room]
                texts.append(current)
                current = ""
                sentence = sentence[room:]
            current += sentence
        if current:
            texts.append(current)
        results = await asyncio.gather(
            *[self._tts.synthesize(item) for item in texts],
            return_exceptions=True,
        )
        return [
            {
                "index": index,
                "text": chunk_text,
                "audio_b64": None if isinstance(result, Exception) else result,
            }
            for index, (chunk_text, result) in enumerate(zip(texts, results))
        ]
