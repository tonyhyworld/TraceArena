"""OS 级结构化长期记忆。

与运行轨迹分开存储，按 user/scenario/agent 隔离。记忆是追加式 JSONL，便于
审计和灾备；检索使用轻量关键词匹配，未来可替换向量索引而不改变契约。
"""
from __future__ import annotations

import datetime as dt
import hashlib
import json
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.redaction import redact_credentials, redact_structure


class PersistentMemoryStore:
    def __init__(self, root: str | Path):
        self.root = Path(root)
        self.root.mkdir(parents=True, exist_ok=True)

    @staticmethod
    def _safe(value: str, default: str = "default") -> str:
        raw = str(value or "").strip()
        if not raw:
            return default
        clean = re.sub(r"[^a-zA-Z0-9_.-]+", "_", raw).strip("._-")
        clean = clean or default
        if clean == raw and len(raw) <= 120:
            return clean
        digest = hashlib.sha256(raw.encode("utf-8")).hexdigest()[:12]
        return f"{clean[:100]}_{digest}"

    def _path(self, user_id: str, agent_id: str, scenario_id: str) -> Path:
        return self.root / self._safe(user_id) / self._safe(scenario_id) / f"{self._safe(agent_id)}.jsonl"

    def append(self, *, user_id: str, agent_id: str, scenario_id: str, text: str, kind: str = "observation", metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        value = redact_credentials(str(text or "").strip())
        if not value:
            raise ValueError("memory_text_empty")
        record = {
            "timestamp": dt.datetime.now(dt.timezone.utc).isoformat(),
            "user_id": user_id,
            "agent_id": agent_id,
            "scenario_id": scenario_id,
            "kind": kind,
            "text": value[:20_000],
            "metadata": redact_structure(dict(metadata or {})),
        }
        path = self._path(user_id, agent_id, scenario_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps(record, ensure_ascii=False, default=str) + "\n")
        return record

    def list(self, *, user_id: str, agent_id: str = "", scenario_id: str = "", limit: int = 100) -> List[Dict[str, Any]]:
        base = self.root / self._safe(user_id)
        if agent_id and scenario_id:
            paths = [self._path(user_id, agent_id, scenario_id)]
        else:
            paths = list(base.glob("**/*.jsonl")) if base.is_dir() else []
        records: List[Dict[str, Any]] = []
        for path in sorted(paths):
            if not path.is_file():
                continue
            for line in path.read_text(encoding="utf-8").splitlines():
                try:
                    item = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if agent_id and item.get("agent_id") != agent_id:
                    continue
                if scenario_id and item.get("scenario_id") != scenario_id:
                    continue
                records.append(item)
        return records[-max(1, min(1000, int(limit))):]

    def search(self, *, user_id: str, query: str, agent_id: str = "", scenario_id: str = "", limit: int = 20) -> List[Dict[str, Any]]:
        terms = [x.lower() for x in re.findall(r"[\w\u4e00-\u9fff]+", query or "") if len(x) > 1]
        items = self.list(user_id=user_id, agent_id=agent_id, scenario_id=scenario_id, limit=1000)
        if not terms:
            return items[-max(1, min(100, int(limit))):]
        ranked = [(sum(term in str(item.get("text", "")).lower() for term in terms), item) for item in items]
        return [item for score, item in sorted(ranked, key=lambda pair: (pair[0], pair[1].get("timestamp", "")), reverse=True) if score > 0][:max(1, min(100, int(limit)))]
