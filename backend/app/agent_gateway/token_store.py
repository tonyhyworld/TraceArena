"""外部 Agent 席位令牌（slot_token）存储与校验。"""
from __future__ import annotations

import json
import logging
import os
import secrets
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from threading import Lock
from typing import Any, Dict, Optional

from app.core.path_safety import path_beneath

logger = logging.getLogger(__name__)

_lock = Lock()
_TOKEN_PREFIX = "agk_"


@dataclass
class SlotTokenRecord:
    user_id: str
    slot_id: str
    slot_token: str
    created_at: float
    agent_label: Optional[str] = None
    run_id: Optional[str] = None

    def to_public_dict(self) -> Dict[str, Any]:
        return {
            "slot_id": self.slot_id,
            "slot_token": self.slot_token,
            "created_at": self.created_at,
            "agent_label": self.agent_label,
            "run_id": self.run_id,
            "connected": bool(self.agent_label),
        }


def _user_tokens_path(user_id: str) -> Path:
    return path_beneath("./user_data", user_id, "agent_slot_tokens.json")


def _index_path() -> Path:
    return Path("./user_data") / "_agent_token_index.json"


class AgentTokenStore:
    """按用户管理 slot_token；全局索引用于 join/ws 无 JWT 鉴权。"""

    def __init__(self) -> None:
        self._index: Dict[str, Dict[str, str]] = {}

    def _load_user_tokens(self, user_id: str) -> Dict[str, Dict[str, Any]]:
        path = _user_tokens_path(user_id)
        if not path.is_file():
            return {}
        try:
            return json.loads(path.read_text(encoding="utf-8"))
        except Exception as exc:
            logger.warning("[AgentTokenStore] 读取失败 user=%s: %s", user_id, exc)
            return {}

    def _save_user_tokens(self, user_id: str, data: Dict[str, Any]) -> None:
        path = _user_tokens_path(user_id)
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _load_index(self) -> None:
        path = _index_path()
        if not path.is_file():
            self._index = {}
            return
        try:
            self._index = json.loads(path.read_text(encoding="utf-8"))
        except Exception:
            self._index = {}

    def _save_index(self) -> None:
        path = _index_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(self._index, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, path)

    def _ensure_index(self) -> None:
        if not self._index:
            self._load_index()

    def generate(self, user_id: str, slot_id: str) -> SlotTokenRecord:
        with _lock:
            self._ensure_index()
            data = self._load_user_tokens(user_id)
            token = f"{_TOKEN_PREFIX}{secrets.token_urlsafe(18)}"
            rec = SlotTokenRecord(
                user_id=user_id,
                slot_id=slot_id,
                slot_token=token,
                created_at=time.time(),
            )
            data[slot_id] = asdict(rec)
            self._save_user_tokens(user_id, data)
            self._index[token] = {"user_id": user_id, "slot_id": slot_id}
            self._save_index()
            return rec

    def revoke(self, user_id: str, slot_id: str) -> bool:
        with _lock:
            self._ensure_index()
            data = self._load_user_tokens(user_id)
            entry = data.pop(slot_id, None)
            if not entry:
                return False
            token = str(entry.get("slot_token") or "")
            if token:
                self._index.pop(token, None)
            self._save_user_tokens(user_id, data)
            self._save_index()
            return True

    def get_by_slot(self, user_id: str, slot_id: str) -> Optional[SlotTokenRecord]:
        data = self._load_user_tokens(user_id)
        entry = data.get(slot_id)
        if not entry:
            return None
        return SlotTokenRecord(**entry)

    def _resolve_unlocked(self, slot_token: str) -> Optional[SlotTokenRecord]:
        ref = self._index.get(slot_token)
        if not ref:
            return None
        data = self._load_user_tokens(ref["user_id"])
        entry = data.get(ref["slot_id"])
        if not entry or entry.get("slot_token") != slot_token:
            return None
        return SlotTokenRecord(**entry)

    def resolve(self, slot_token: str) -> Optional[SlotTokenRecord]:
        with _lock:
            self._ensure_index()
            return self._resolve_unlocked(slot_token)

    def set_agent_label(self, slot_token: str, agent_label: Optional[str]) -> None:
        with _lock:
            self._ensure_index()
            ref = self._index.get(slot_token)
            if not ref:
                return
            data = self._load_user_tokens(ref["user_id"])
            entry = data.get(ref["slot_id"]) or {}
            entry["agent_label"] = agent_label
            data[ref["slot_id"]] = entry
            self._save_user_tokens(ref["user_id"], data)

    def bind_run_id(self, user_id: str, run_id: str) -> None:
        with _lock:
            data = self._load_user_tokens(user_id)
            changed = False
            for slot_id, entry in data.items():
                if entry.get("run_id") != run_id:
                    entry["run_id"] = run_id
                    changed = True
            if changed:
                self._save_user_tokens(user_id, data)


_token_store = AgentTokenStore()


def get_token_store() -> AgentTokenStore:
    return _token_store
