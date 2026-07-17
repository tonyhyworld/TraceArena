"""加载与校验 mcp_servers.yaml。"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional

import yaml

from app.mcp.config import McpServersConfig

logger = logging.getLogger(__name__)


def load_mcp_servers(path: str | Path) -> McpServersConfig:
    """读取 MCP Server 注册表；文件不存在时返回空配置。"""
    p = Path(path)
    if not p.exists():
        logger.info("[mcp] 配置文件不存在，跳过: %s", p)
        return McpServersConfig()

    with open(p, encoding="utf-8") as f:
        raw = yaml.safe_load(f) or {}

    cfg = McpServersConfig(**raw)
    # stdio server paths belong to the registry file, not the caller's cwd.
    for server in cfg.servers:
        if server.transport != "stdio":
            continue
        resolved_args = []
        for value in server.args:
            candidate = Path(value)
            local = (p.parent / candidate).resolve()
            resolved_args.append(
                str(local)
                if not candidate.is_absolute() and local.exists()
                else value
            )
        server.args = resolved_args
    ids = [s.id for s in cfg.servers]
    dupes = {x for x in ids if ids.count(x) > 1}
    if dupes:
        raise ValueError(f"mcp_servers.yaml 重复的 server id: {sorted(dupes)}")
    return cfg


def resolve_mcp_servers_path(
    explicit: Optional[str] = None,
    framework_servers_path: Optional[str] = None,
) -> Path:
    """解析 MCP 配置路径：显式参数 > framework > 默认 backend 目录。"""
    if explicit:
        return Path(explicit)
    if framework_servers_path:
        return Path(framework_servers_path)
    return Path("./mcp_servers.yaml")
