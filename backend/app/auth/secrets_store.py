"""
账户体系 · 用户私有 API Key 存储（BYOK）

每个用户的 key 按 agent_id 存一份（与现有 AgentConfigUpdate/reconfigure_agent
的粒度一致——每个角色槽位可以配置不同 provider/model/key），写入
user_data/<user_id>/secrets.json，权限收紧到仅本用户可读，且该目录整体
在 .gitignore 里，绝不会进 git。

落盘的 key 值均经 crypto.encrypt 静态加密（Fernet）。为兼容历史明文文件，
读取时解密失败会回退按明文处理，并在下次写入时自动迁移为密文。
"""
from __future__ import annotations

import json
import logging
import os
from pathlib import Path
from threading import Lock
from typing import Dict, Optional

from app.auth import crypto

logger = logging.getLogger(__name__)

_lock = Lock()


def _path(user_id: str) -> Path:
    return Path("./user_data") / user_id / "secrets.json"


def _load(user_id: str) -> Dict[str, str]:
    """返回 {agent_id: 明文 key}。密文自动解密，历史明文原样回退。"""
    p = _path(user_id)
    if not p.exists():
        return {}
    try:
        raw = json.loads(p.read_text(encoding="utf-8"))
    except Exception as e:
        logger.warning(f"[secrets] 读取密钥文件失败 user={user_id}: {e}")
        return {}
    out: Dict[str, str] = {}
    for agent_id, stored in raw.items():
        if not isinstance(stored, str):
            continue
        decrypted = crypto.decrypt(stored)
        # 解密成功 → 密文；失败 → 视为历史明文，原样保留（下次写入时迁移加密）
        out[agent_id] = decrypted if decrypted is not None else stored
    return out


def get_user_secret(user_id: str, agent_id: str) -> Optional[str]:
    return _load(user_id).get(agent_id)


def get_user_secrets(user_id: str) -> Dict[str, str]:
    """Return all decrypted user keys for the hosting adapter."""
    return _load(user_id)


def set_user_secret(user_id: str, agent_id: str, api_key: str) -> None:
    with _lock:
        p = _path(user_id)
        p.parent.mkdir(parents=True, exist_ok=True)
        data = _load(user_id)
        data[agent_id] = api_key
        # 全部字段统一加密落盘（顺带把历史明文迁移为密文）
        encrypted = {aid: crypto.encrypt(v) for aid, v in data.items()}
        tmp = p.with_suffix(".tmp")
        tmp.write_text(json.dumps(encrypted, ensure_ascii=False, indent=2), encoding="utf-8")
        os.replace(tmp, p)
        p.chmod(0o600)
