"""远程 Skill/Tool 注册表。

注册表只允许 HTTPS，安装前必须校验 manifest 和 SHA-256。Skill 只包含说明、
受限起始文件和可选依赖声明；不会执行远程代码。真正的依赖安装仍由每个
Agent 的沙箱策略决定。
"""
from __future__ import annotations

import hashlib
import json
import os
import tempfile
from pathlib import Path
from typing import Any, Dict, List
from urllib.parse import urlparse
from urllib.request import Request

import yaml

from app.agent_os.web_research import open_allowed, validate_url


def _get_json(url: str, timeout: float = 20.0) -> Any:
    safe = validate_url(url)
    with open_allowed(Request(safe, headers={"Accept": "application/json", "User-Agent": "TraceArena-Registry/1.0"}), timeout=timeout) as response:
        validate_url(response.geturl(), hosts={urlparse(safe).hostname or ""})
        return json.loads(response.read(2_000_000).decode(response.headers.get_content_charset() or "utf-8", errors="replace"))


def registry_url() -> str:
    return os.getenv("AIWORLD_SKILL_REGISTRY_URL", "").strip()


def list_remote_skills(url: str | None = None) -> List[Dict[str, Any]]:
    source = (url or registry_url()).strip()
    if not source:
        return []
    payload = _get_json(source)
    items = payload.get("skills", payload) if isinstance(payload, dict) else payload
    return [dict(item) for item in (items or []) if isinstance(item, dict) and item.get("skill_id")]


def install_remote_skill(entry: Dict[str, Any], skills_root: str | Path) -> Dict[str, Any]:
    skill_id = str(entry.get("skill_id") or "").strip()
    manifest_url = str(entry.get("manifest_url") or entry.get("url") or "").strip()
    if not skill_id or not manifest_url:
        raise ValueError("registry_entry_requires_skill_id_and_url")
    manifest_url = validate_url(manifest_url)
    expected = str(entry.get("sha256") or "").lower().strip()
    if len(expected) != 64 or any(c not in "0123456789abcdef" for c in expected):
        raise ValueError("registry_entry_requires_sha256")
    with open_allowed(Request(manifest_url, headers={"Accept": "text/yaml,application/yaml,application/json"}), timeout=20) as response:
        validate_url(response.geturl(), hosts={urlparse(manifest_url).hostname or ""})
        raw = response.read(512_000)
    actual = hashlib.sha256(raw).hexdigest()
    if actual != expected:
        raise ValueError("skill_manifest_sha256_mismatch")
    data = yaml.safe_load(raw.decode("utf-8", errors="replace")) or {}
    if str(data.get("skill_id") or "") != skill_id:
        raise ValueError("skill_id_mismatch")
    # 复用本地 SkillConfig 的严格字段校验，拒绝任意扩展字段。
    from app.agent_os.skills import SkillConfig
    skill = SkillConfig(**data)
    root = Path(skills_root).resolve()
    target = (root / skill.skill_id).resolve()
    if root not in target.parents:
        raise ValueError("skill_path_escape")
    target.mkdir(parents=True, exist_ok=True)
    with tempfile.NamedTemporaryFile("w", encoding="utf-8", dir=target, delete=False) as tmp:
        tmp.write(yaml.safe_dump(skill.model_dump(exclude_defaults=False), allow_unicode=True, sort_keys=False))
        tmp_path = Path(tmp.name)
    tmp_path.replace(target / "skill.yaml")
    return {"skill_id": skill.skill_id, "installed": True, "path": str(target), "sha256": actual}
