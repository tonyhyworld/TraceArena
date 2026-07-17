"""CodeRuntime（代码运行时）：在工作区中读写/试跑 agent 脚本。"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from app.core.interfaces import ToolRunResult

logger = logging.getLogger(__name__)


class CodeRuntime:
    """封装沙箱执行 + AgentWorkspace 代码目录。"""

    def __init__(self, sandbox: Any, workspace_registry: Any):
        self._sandbox = sandbox
        self._workspaces = workspace_registry

    async def run_once(
        self,
        agent_id: str,
        tick: int,
        *,
        inline_code: Optional[str] = None,
        workspace_path: Optional[str] = None,
        tool_id: str = "workspace",
        target_object_id: Optional[str] = None,
        context: Optional[Dict[str, Any]] = None,
    ) -> ToolRunResult:
        """试跑一段代码：inline（内联）或从工作区文件读取。"""
        run_id = f"tool_run_{tick}_{agent_id}_{tool_id}"
        code = (inline_code or "").strip()
        src_label = "inline"

        if not code and workspace_path:
            ws = self._workspaces.get(agent_id) if self._workspaces else None
            if ws is None:
                return ToolRunResult(
                    run_id=run_id,
                    tool_id=tool_id,
                    owner_id=agent_id,
                    tick=tick,
                    ok=False,
                    source="workspace",
                    errors=["workspace_not_found"],
                )
            try:
                code = ws.read_code_file(str(workspace_path)).strip()
                src_label = f"workspace:{workspace_path}"
            except Exception as exc:
                return ToolRunResult(
                    run_id=run_id,
                    tool_id=tool_id,
                    owner_id=agent_id,
                    tick=tick,
                    ok=False,
                    source="workspace",
                    errors=[f"workspace_read_failed: {exc}"],
                )

        if not code:
            return ToolRunResult(
                run_id=run_id,
                tool_id=tool_id,
                owner_id=agent_id,
                tick=tick,
                ok=False,
                source="workspace",
                errors=["empty_code"],
            )

        if not self._sandbox:
            return ToolRunResult(
                run_id=run_id,
                tool_id=tool_id,
                owner_id=agent_id,
                tick=tick,
                ok=False,
                source="workspace",
                errors=["sandbox_disabled"],
            )

        ctx = dict(context or {})
        ctx.update({
            "agent_id": agent_id,
            "tick": tick,
            "tool_id": tool_id,
            "code_source": src_label,
        })
        if target_object_id:
            ctx["target_object_id"] = target_object_id

        result = await self._sandbox.run_code(code=code, context=ctx)
        outputs = result.get("outputs", []) if isinstance(result, dict) else []
        evidence_created = (
            result.get("evidence_created", []) if isinstance(result, dict) else []
        )
        errors = result.get("errors", []) if isinstance(result, dict) else []

        return ToolRunResult(
            run_id=run_id,
            tool_id=tool_id,
            owner_id=agent_id,
            tick=tick,
            ok=not errors,
            outputs=outputs,
            evidence_created=evidence_created,
            errors=errors,
            source="workspace" if workspace_path else "sandbox",
        )
