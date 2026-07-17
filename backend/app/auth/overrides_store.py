"""
账户体系 · 用户级 Agent 配置覆盖（BYOK 的 provider/model 部分，非密钥）

存 user_data/<user_id>/framework_overrides.json，按 agent_id 记录该用户
自己选的 provider/model，登录后每次构建引擎实例时叠加在全局 framework.yaml
之上（全局给默认值，用户可各自覆盖）。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Dict

logger = logging.getLogger(__name__)

_lock = Lock()


def _path(user_id: str) -> Path:
    return Path("./user_data") / user_id / "framework_overrides.json"


def get_user_overrides(user_id: str) -> Dict[str, Dict[str, str]]:
    """返回 {agent_id: {"provider": ..., "model": ...}}，无覆盖则空字典"""
    p = _path(user_id)
    if not p.exists():
        return {}
    try:
        return json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[overrides] 读取覆盖配置失败 user={user_id}: {e}")
        return {}


def set_user_override(user_id: str, agent_id: str, provider: str, model: str) -> None:
    with _lock:
        p = _path(user_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = get_user_overrides(user_id)
        entry = data.get(agent_id) or {}
        entry["provider"] = provider
        entry["model"] = model
        data[agent_id] = entry
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)


def set_user_driver(user_id: str, agent_id: str, driver: str) -> None:
    with _lock:
        p = _path(user_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = get_user_overrides(user_id)
        entry = data.get(agent_id) or {}
        entry["driver"] = driver
        data[agent_id] = entry
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
