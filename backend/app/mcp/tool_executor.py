"""MCP 工具执行：将 MCPToolCallResult 转为 ToolRunResult。"""
from __future__ import annotations

import json
import logging
from typing import Any, Dict, Optional

from app.core.interfaces import ActionPack, ToolRunResult
from app.framework.ruleworld.evidence import EvidenceService
from app.mcp.client import get_mcp_manager

logger = logging.getLogger(__name__)


def resolve_tool_type(tool_def: Optional[Dict[str, Any]]) -> str:
    if not tool_def:
        return "sandbox"
    return str(tool_def.get("type") or "sandbox").strip().lower()


def _tool_request_payload(action: ActionPack) -> Dict[str, Any]:
    tr = action.tool_request
    return tr if isinstance(tr, dict) else {}


def resolve_tool_id(action: ActionPack) -> str:
    if action.attached_tool_id:
        return str(action.attached_tool_id)
    tr = _tool_request_payload(action)
    tid = tr.get("tool_id")
    return str(tid) if tid else ""


def resolve_tool_arguments(action: ActionPack) -> Dict[str, Any]:
    tr = _tool_request_payload(action)
    args = tr.get("arguments")
    if isinstance(args, dict):
        return dict(args)
    return {}


async def execute_mcp_tool(
    *,
    action: ActionPack,
    tick: int,
    tool_def: Dict[str, Any],
    evidence_service: Optional[EvidenceService] = None,
) -> ToolRunResult:
    """调用 MCP Server 上的工具，返回统一 ToolRunResult。"""
    tool_id = resolve_tool_id(action) or str(tool_def.get("id") or tool_def.get("tool_id") or "")
    server_id = str(tool_def.get("mcp_server") or "")
    mcp_tool = str(tool_def.get("mcp_tool") or "")
    run_id = f"tool_run_{tick}_{action.agent_id}_{tool_id}"

    mgr = get_mcp_manager()
    if mgr is None or not mgr.enabled:
        return ToolRunResult(
            run_id=run_id,
            tool_id=tool_id,
            owner_id=action.agent_id,
            tick=tick,
            ok=False,
            errors=["mcp_disabled"],
            source="mcp",
        )

    arguments = resolve_tool_arguments(action)
    call = await mgr.call_tool(
        server_id,
        mcp_tool,
        arguments,
        timeout_sec=float(tool_def.get("timeout_sec") or 0) or None,
    )

    summary_text = call.content_text
    if not summary_text and call.structured is not None:
        try:
            summary_text = json.dumps(call.structured, ensure_ascii=False)
        except (TypeError, ValueError):
            summary_text = str(call.structured)

    outputs: list[Dict[str, Any]] = []
    if isinstance(call.structured, dict):
        structured_output = dict(call.structured)
        if summary_text:
            structured_output.setdefault("summary", summary_text)
        structured_output.setdefault("source", "mcp")
        outputs.append(structured_output)
    elif call.structured is not None:
        outputs.append({
            "summary": summary_text or str(call.structured),
            "data": call.structured,
            "source": "mcp",
        })
    elif summary_text:
        outputs.append({"summary": summary_text, "source": "mcp"})

    evidence_candidate_ids: list[str] = []
    if evidence_service and call.ok and summary_text:
        entry = evidence_service.create(
            creator_id=action.agent_id,
            target_id=action.target_object_id,
            claim=f"MCP 工具 {tool_id} 输出: {summary_text[:500]}",
            source_tool_id=tool_id,
            supporting_event_ids=[],
            confidence=0.65,
        )
        evidence_candidate_ids.append(entry.evidence_id)

    errors = list(call.errors)
    if not call.ok and not errors:
        errors = ["mcp_call_failed"]

    return ToolRunResult(
        run_id=run_id,
        tool_id=tool_id,
        owner_id=action.agent_id,
        tick=tick,
        ok=call.ok,
        outputs=outputs,
        evidence_created=[],
        evidence_candidate_ids=evidence_candidate_ids,
        trace_delta=0.1 if call.ok else 0.0,
        errors=errors,
        source="mcp",
        duration_ms=call.duration_ms,
        mcp_server_id=server_id,
        mcp_tool_name=mcp_tool,
    )
