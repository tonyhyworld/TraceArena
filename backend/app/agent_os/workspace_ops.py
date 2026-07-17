"""从 ActionPack.tool_request 应用工作区写操作。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def extract_workspace_run_path(tool_request: Optional[Dict[str, Any]]) -> Optional[str]:
    if not isinstance(tool_request, dict):
        return None
    for key in ("workspace_run", "workspace_path", "run_path"):
        val = tool_request.get(key)
        if val:
            return str(val)
    return None


def extract_workspace_deploy_path(tool_request: Optional[Dict[str, Any]]) -> Optional[str]:
    """部署入口脚本路径；缺省时回退 workspace_run 等试跑路径。"""
    if not isinstance(tool_request, dict):
        return None
    for key in ("workspace_deploy", "deploy_path"):
        val = tool_request.get(key)
        if val:
            return str(val)
    return extract_workspace_run_path(tool_request)


def resolve_artifact_code(
    *,
    inline_code: str,
    agent_id: str,
    tool_request: Optional[Dict[str, Any]],
    workspace: Any,
) -> Tuple[Optional[str], Optional[str], List[str]]:
    """解析待部署源码，返回 (code, workspace_path, errors)。"""
    code = (inline_code or "").strip()
    if code:
        return code, None, []

    if workspace is None:
        return None, None, ["workspace_not_found"]

    tr = tool_request if isinstance(tool_request, dict) else {}
    path = extract_workspace_deploy_path(tr)
    if not path:
        return None, None, ["missing_workspace_path"]

    try:
        return workspace.read_code_file(str(path)).strip(), str(path), []
    except Exception as exc:
        return None, str(path), [f"workspace_read_failed: {exc}"]


def apply_workspace_writes(
    agent_id: str,
    tool_request: Optional[Dict[str, Any]],
    workspace: Any,
    *,
    max_bytes: int = 32768,
    max_files: int = 20,
) -> Tuple[List[str], List[str]]:
    """执行 workspace_write / workspace_writes，返回 (written, errors)。"""
    if workspace is None or not isinstance(tool_request, dict):
        return [], []

    writes: List[Dict[str, Any]] = []
    single = tool_request.get("workspace_write")
    if isinstance(single, dict):
        writes.append(single)
    multi = tool_request.get("workspace_writes")
    if isinstance(multi, list):
        writes.extend(item for item in multi if isinstance(item, dict))

    written: List[str] = []
    errors: List[str] = []
    for item in writes:
        path = item.get("path") or item.get("filename")
        content = item.get("content")
        if not path:
            errors.append(f"{agent_id}: workspace_write 缺少 path")
            continue
        try:
            name = workspace.write_code_file(
                str(path),
                str(content or ""),
                max_bytes=max_bytes,
                max_files=max_files,
            )
            written.append(name)
        except Exception as exc:
            errors.append(f"{agent_id}: workspace_write {path}: {exc}")
    return written, errors
