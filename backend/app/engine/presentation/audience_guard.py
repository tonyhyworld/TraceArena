"""Public presentation projection for viewer-facing director content."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, Mapping


_TECHNICAL_TOKEN = re.compile(
    r"\b(?:metric|action|provider|settlement|event|observation|trace|rule|source)"
    r"(?:_id|_refs?|_[a-z0-9_]+)?\s*[:=]\s*[^，。；\s]+|"
    r"\b(?:metric|action|provider|settlement|event|observation|trace|rule)_"
    r"[a-z0-9_]+\b|"
    r"\b[a-z][a-z0-9]+(?:_[a-z0-9]+){2,}\b",
    re.IGNORECASE,
)
_CODE_FENCE = re.compile(r"```[\s\S]*?```", re.MULTILINE)
_JSON_OBJECT = re.compile(r"\{\s*[\"'][A-Za-z0-9_]+[\"']\s*:[\s\S]*?\}")
_URL = re.compile(r"https?://[^\s，。；]+", re.IGNORECASE)
_INTERNAL_PHRASES = re.compile(
    r"\b(?:MCP|mcp)\s*(?:arguments?|tool|server|调用|参数)?\b|"
    r"\bworkspace[_\s-]*(?:run|deploy|write|read)?\b|"
    r"\bprovider[_\s-]*(?:health|check|id|model)?\b|"
    r"\b(?:JSON|json)\b|"
    r"\b(?:ActionPack|ActionParser|DirectorPlan|RenderCommand|HarnessTrace)\b|"
    r"\b(?:action_id|target_agent_id|target_object_id|metric_id|provider_id|"
    r"settlement_id|event_id|observation_id|source_event_refs|rule_refs)\b",
    re.IGNORECASE,
)
_FALLBACK_PHRASES = re.compile(
    r"LLM\s*未响应[，,。；;\s]*本拍系统兜底为?|"
    r"模型未响应[，,。；;\s]*系统兜底为?|"
    r"系统兜底为?",
    re.IGNORECASE,
)


class AudienceTextGuard:
    """Translate known scene ids and reject remaining implementation language."""

    def __init__(self, terminology: Mapping[str, str] | None = None):
        self._terms = {
            str(key): str(value)
            for key, value in dict(terminology or {}).items()
            if key and value
        }

    def clean(self, value: Any, *, fallback: str = "") -> str:
        if isinstance(value, (dict, list, tuple)):
            value = json.dumps(value, ensure_ascii=False, default=str)
        text = re.sub(r"\s+", " ", str(value or "")).strip()
        text = _CODE_FENCE.sub("", text)
        text = _JSON_OBJECT.sub("", text)
        text = _URL.sub("公开数据来源", text)
        text = _FALLBACK_PHRASES.sub("暂时没有形成有效决策", text)
        text = _INTERNAL_PHRASES.sub("", text)
        for raw, label in sorted(
            self._terms.items(), key=lambda item: len(item[0]), reverse=True
        ):
            text = text.replace(raw, label)
        text = _TECHNICAL_TOKEN.sub("", text)
        text = _FALLBACK_PHRASES.sub("暂时没有形成有效决策", text)
        text = _INTERNAL_PHRASES.sub("", text)
        text = re.sub(r"\s*[,，;；]\s*[,，;；]+", "，", text)
        text = re.sub(r"需要提供\s*[、，,\s]*或", "需要继续调用数据源或", text)
        text = re.sub(r"（证据\s*）", "", text)
        text = re.sub(r"证据\s*[：:]\s*[）。；，,]*", "", text)
        text = re.sub(r"本回合\s+\d+\s*已", "本回合已", text)
        text = re.sub(r"[、，]\s*[、，]+", "，", text)
        text = re.sub(r"\s+", " ", text).strip(" ，。；;:：-")
        return text or fallback

    def public_parameters(
        self, command_type: str, parameters: Mapping[str, Any] | None
    ) -> Dict[str, Any]:
        """Keep only fields required by the viewer renderer."""
        raw = dict(parameters or {})
        allowed = {
            "character": {"animation", "actor_animation", "outcome"},
            "object": {"animation", "outcome", "label", "icon"},
            "camera": {"camera", "transition", "outcome"},
            "effect": {"effect", "outcome"},
            "sound": {"sound"},
            "music": {"music", "state"},
            "subtitle": {"text"},
            "ui": {"text"},
            "wait": set(),
        }.get(str(command_type), set())
        output = {key: raw[key] for key in allowed if key in raw}
        if "text" in output:
            output["text"] = self.clean(
                output["text"], fallback="本回合结果已经记录。"
            )
        return output
