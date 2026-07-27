"""Robust JSON extraction helpers for LLM text outputs."""
from __future__ import annotations

import json
import re
from typing import Any, List


def extract_json_candidates(text: str) -> List[Any]:
    """Extract parseable JSON objects/arrays in appearance order.

    LLMs often wrap JSON in Markdown, prepend ``<think>`` content, or emit more
    than one JSON object. Regex such as ``{.*}`` is too greedy for that shape.
    This helper uses ``JSONDecoder.raw_decode`` at every possible JSON start and
    de-duplicates semantic duplicates while preserving order.
    """
    raw = str(text or "")
    decoder = json.JSONDecoder()
    candidates: List[Any] = []
    seen: set[str] = set()

    def add(value: Any) -> None:
        if not isinstance(value, (dict, list)):
            return
        try:
            marker = json.dumps(value, ensure_ascii=False, sort_keys=True)
        except TypeError:
            return
        if marker in seen:
            return
        seen.add(marker)
        candidates.append(value)

    for match in re.finditer(
        r"```(?:json)?\s*\n(.*?)```",
        raw,
        re.DOTALL | re.IGNORECASE,
    ):
        try:
            add(json.loads(match.group(1).strip()))
        except json.JSONDecodeError:
            pass

    for idx, char in enumerate(raw):
        if char not in "{[":
            continue
        try:
            value, _ = decoder.raw_decode(raw[idx:])
        except json.JSONDecodeError:
            continue
        add(value)
    return candidates


def extract_first_json_object(text: str) -> dict[str, Any]:
    for candidate in extract_json_candidates(text):
        if isinstance(candidate, dict):
            return candidate
    return {}
