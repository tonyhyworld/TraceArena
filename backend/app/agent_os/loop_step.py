"""Agent 循环单步解析：区分中间步（工具/代码）与最终 ActionPack。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Tuple


def is_continue_step(parsed: Dict[str, Any]) -> bool:
    """模型是否请求在本 tick 内继续（调工具/试跑），而非提交最终行动。"""
    if not isinstance(parsed, dict):
        return False
    step = str(parsed.get("agent_loop_step") or "").strip().lower()
    if step in ("continue", "tool", "code", "step"):
        return True
    if step in ("final", "done", "submit"):
        return False

    has_action = bool(
        str(parsed.get("action_id") or parsed.get("intent") or "").strip()
    )
    has_toolish = bool(
        parsed.get("tool_request")
        or parsed.get("code")
        or parsed.get("attached_tool_id")
        or _has_workspace_op(parsed.get("tool_request"))
    )
    # Tool-bearing payloads are execution steps even when the model also
    # filled action_id. The model must explicitly submit a final step after it
    # has observed the tool result.
    return has_toolish


def _has_workspace_op(tool_request: Any) -> bool:
    if not isinstance(tool_request, dict):
        return False
    return bool(
        tool_request.get("workspace_write")
        or tool_request.get("workspace_writes")
        or tool_request.get("workspace_run")
    )


def format_step_results_for_prompt(steps: List[Dict[str, Any]]) -> str:
    """把本 tick 已完成的循环步结果格式化为追加观察文本。"""
    if not steps:
        return ""
    lines = ["\n### 本回合 Agent 循环中间步结果（仅供继续推理，勿重复执行）"]
    for item in steps:
        idx = item.get("step_index", "?")
        kind = item.get("kind", "tool")
        lines.append(f"\n**Step {idx}** ({kind})")
        tr = item.get("tool_result") or {}
        if tr.get("ok"):
            lines.append("  状态：成功")
        else:
            lines.append("  状态：失败")
        src = tr.get("source")
        if src:
            lines.append(f"  来源：{src}")
        if tr.get("run_id"):
            lines.append(f"  可引用证据：{tr['run_id']}")
        for o in (tr.get("outputs") or [])[:3]:
            if isinstance(o, dict):
                lines.append(f"  输出：{o.get('claim', o.get('summary', o))}")
                capability = o.get("capability")
                if isinstance(capability, dict):
                    invocation = capability.get("invocation") or {}
                    schema = capability.get("input_schema") or {}
                    lines.append(
                        "  调用契约：" + str({
                            "capability_id": capability.get("capability_id"),
                            "invocation": invocation,
                            "input_schema": schema,
                        })
                    )
            else:
                lines.append(f"  输出：{o}")
        for e in (tr.get("errors") or [])[:3]:
            lines.append(f"  错误：{e}")
        written = item.get("workspace_written") or []
        if written:
            lines.append(f"  工作区已写入：{', '.join(written)}")
    lines.append(
        "\n若信息已足够，请输出最终行动 JSON（含 action_id）；"
        "需要引用工具事实时，把上面的证据 ID 放进 evidence_refs；"
        "若仍需调工具/试跑，下一条回复只能输出一个 JSON 对象："
        "{\"agent_loop_step\": \"continue\", \"tool_request\": {...}}，"
        "此时不要输出最终行动 YAML、intent 或 action_id。"
    )
    return "\n".join(lines)


def tool_result_to_dict(result: Any) -> Dict[str, Any]:
    if result is None:
        return {"ok": False, "errors": ["no_result"]}
    if hasattr(result, "model_dump"):
        d = result.model_dump(mode="json")
    elif isinstance(result, dict):
        d = dict(result)
    else:
        d = {"ok": bool(getattr(result, "ok", False))}
    d.setdefault("ok", False)
    d.setdefault("outputs", [])
    d.setdefault("errors", [])
    d.setdefault("source", getattr(result, "source", None))
    return d
