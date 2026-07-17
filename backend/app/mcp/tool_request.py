"""tool_request（工具请求）字段归一化。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

# Harness 中间步合法载荷：不一定带 tool_id。
_HARNESS_OP_KEYS = (
    "skill_install",
    "capability_request",
    "package_install",
    "workspace_run",
    "workspace_write",
    "workspace_writes",
    "code",
    "execution_mode",
    "deploy",
)


def normalize_tool_request(
    data: Dict[str, Any],
    parse_errors: Optional[list] = None,
) -> Optional[Dict[str, Any]]:
    """合并顶层 tool_id / attached_tool_id，规范 arguments，放行 Harness 操作。

    兼容模型常见写法：
    - 标准：{"tool_id": "mcp:longport:longport_quote", "arguments": {...}}
    - 简写：{"mcp:longport:longport_candlesticks": {"symbol": "600036.SH"}}
    - 发现/安装：{"capability_request": {...}} / {"skill_install": {...}}
    """
    errors = parse_errors if parse_errors is not None else []

    raw_tr = data.get("tool_request")
    tr: Dict[str, Any] = dict(raw_tr) if isinstance(raw_tr, dict) else {}

    top_tool = (
        data.get("attached_tool_id")
        or data.get("tool_id")
        or tr.get("tool_id")
    )
    if top_tool and not tr.get("tool_id"):
        tr["tool_id"] = str(top_tool)

    _expand_mcp_shorthand(tr, errors)

    args = tr.get("arguments")
    if args is None:
        tr["arguments"] = {}
    elif not isinstance(args, dict):
        errors.append("tool_request.arguments（工具参数）必须是 JSON 对象")
        tr["arguments"] = {}

    if not tr:
        return None

    has_harness_op = any(key in tr for key in _HARNESS_OP_KEYS)
    if not tr.get("tool_id") and not has_harness_op:
        return None
    return tr


def _expand_mcp_shorthand(tr: Dict[str, Any], errors: list) -> None:
    """把 {"mcp:server:tool": {args}} 收成 tool_id + arguments。"""
    if tr.get("tool_id"):
        return
    shorthand_keys: List[str] = [
        key for key in tr.keys()
        if isinstance(key, str) and key.startswith("mcp:") and key.count(":") >= 2
    ]
    if not shorthand_keys:
        return
    key = shorthand_keys[0]
    payload = tr.get(key)
    if not isinstance(payload, dict):
        errors.append(f"tool_request 简写 {key} 的值必须是 JSON 对象")
        payload = {}
    tr["tool_id"] = key
    if "arguments" not in tr or tr.get("arguments") in (None, {}):
        tr["arguments"] = dict(payload)
    for extra in shorthand_keys:
        tr.pop(extra, None)
