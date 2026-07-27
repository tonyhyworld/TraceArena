"""Agent 循环单步解析：区分中间步（工具/代码）与最终 ActionPack。"""
from __future__ import annotations

from typing import Any, Dict, List


_GENERIC_SUCCESS_SUFFIXES = ("读取成功", "ok", "success", "successful")


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


def is_suspend_step(parsed: Dict[str, Any]) -> bool:
    """Whether the model explicitly asks to preserve research for a later tick."""
    if not isinstance(parsed, dict):
        return False
    return str(parsed.get("agent_loop_step") or "").strip().lower() in {
        "suspend", "pause", "pending",
    }


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
                lines.append(f"  输出：{compact_tool_output(o)}")
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
                alternatives = o.get("alternative_capabilities") or []
                if isinstance(alternatives, list) and alternatives:
                    lines.append(
                        "  可替代方法：" + str([
                            {
                                "capability_id": item.get("capability_id"),
                                "invocation": item.get("invocation"),
                                "input_schema": item.get("input_schema"),
                            }
                            for item in alternatives[:5]
                            if isinstance(item, dict)
                        ])
                    )
            else:
                lines.append(f"  输出：{o}")
        for e in (tr.get("errors") or [])[:3]:
            lines.append(f"  错误：{e}")
        if not tr.get("ok") and tr.get("failure_class"):
            lines.append(
                "  恢复要求：不要重复完全相同的失败请求；先按可重试性判断，"
                "然后换参数、换数据源、换工具或缩小研究问题。"
                f" failure_class={tr.get('failure_class')}, "
                f"retryable={tr.get('retryable')}"
            )
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


def compact_tool_output(output: Dict[str, Any]) -> str:
    """Return a prompt-facing summary that preserves numeric market facts.

    Many scenario MCP tools include a generic ``summary`` such as
    ``longport_quote 读取成功`` while the actionable values live in nested fields.
    If we surface only the generic summary, investment agents conclude that the
    tool result was truncated. Keep the line compact, but expose quote,
    valuation, and financial statement facts needed for a domain decision.
    """
    pieces: List[str] = []
    summary = str(output.get("claim") or output.get("summary") or "").strip()
    if summary and not _looks_generic_success(summary):
        pieces.append(summary[:240])

    for row in _iter_dicts(output.get("quotes"))[:4]:
        symbol = _first(row, "symbol", "asset_id", "code")
        name = _first(row, "name_cn", "name", "证券名称")
        price = _first(row, "last_done", "price", "current_price", "close")
        prev = _first(row, "prev_close", "previous_close")
        ts = _first(row, "timestamp", "time", "datetime")
        fields = []
        if symbol:
            fields.append(f"symbol={symbol}")
        if name:
            fields.append(f"name={name}")
        if price is not None:
            fields.append(f"last_done={price}")
        if prev is not None:
            fields.append(f"prev_close={prev}")
        if ts:
            fields.append(f"timestamp={ts}")
        if fields:
            pieces.append("行情 " + " ".join(str(x) for x in fields))

    for row in _iter_dicts(output.get("data"))[:4]:
        symbol = _first(row, "symbol", "asset_id", "code")
        fields = []
        if symbol:
            fields.append(f"symbol={symbol}")
        for key in (
            "last_done", "change_rate", "pe_ttm_ratio", "pb_ratio",
            "dividend_ratio_ttm", "turnover_rate", "volume_ratio",
            "ytd_change_rate",
        ):
            value = row.get(key)
            if value is not None:
                fields.append(f"{key}={value}")
        if fields:
            pieces.append("估值指标 " + " ".join(str(x) for x in fields))

    statement = output.get("statement")
    records = _iter_dicts(output.get("records"))
    if records:
        first = records[0]
        project = first.get("项目")
        metrics = []
        if isinstance(project, dict):
            for key in (
                "营业收入", "营运收入", "营业额", "净利润", "股东应占溢利",
                "每股收益", "每股基本盈利", "总资产", "总负债",
                "现金及等价物", "经营活动产生的现金流量净额",
            ):
                value = project.get(key)
                if value is not None:
                    metrics.append(f"{key}={value}")
                if len(metrics) >= 5:
                    break
        header = []
        for key in ("symbol", "subject_id", "query_code"):
            value = output.get(key)
            if value:
                header.append(f"{key}={value}")
                break
        report_date = first.get("报告日")
        security_name = first.get("证券名称")
        if security_name:
            header.append(f"name={security_name}")
        if report_date:
            header.append(f"报告日={report_date}")
        if statement:
            header.append(f"statement={statement}")
        if metrics:
            pieces.append("财务报表 " + " ".join(header + metrics))

    normalized_metrics = output.get("metrics")
    if isinstance(normalized_metrics, dict):
        facts = []
        for name, fact in list(normalized_metrics.items())[:10]:
            if not isinstance(fact, dict):
                continue
            value = fact.get("val")
            if value is None:
                continue
            facts.append(
                f"{name}={value} {fact.get('unit') or ''}"
                f" end={fact.get('end') or ''}"
                f" filed={fact.get('filed') or ''}"
            )
        if facts:
            pieces.append("SEC facts " + " | ".join(facts))

    filings = _iter_dicts(output.get("filings"))
    if filings:
        rows = [
            " ".join(str(value) for value in (
                row.get("form"), row.get("filingDate"),
                row.get("items"), row.get("primaryDocDescription"),
            ) if value not in (None, ""))
            for row in filings[:5]
        ]
        pieces.append("SEC filings " + " | ".join(rows))

    material_events = _iter_dicts(output.get("material_events"))
    if material_events:
        rows = [
            " ".join(str(value) for value in (
                row.get("form"), row.get("filingDate"),
                row.get("items"), row.get("primaryDocDescription"),
            ) if value not in (None, ""))
            for row in material_events[:5]
        ]
        pieces.append("Material events " + " | ".join(rows))

    earnings = _iter_dicts(output.get("earnings"))
    if earnings:
        rows = [
            " ".join(
                f"{key}={row.get(key)}"
                for key in (
                    "symbol", "time", "fiscalQuarterEnding",
                    "epsForecast", "noOfEsts", "lastYearEPS",
                )
                if row.get(key) not in (None, "")
            )
            for row in earnings[:5]
        ]
        pieces.append("Earnings calendar " + " | ".join(rows))

    observations = _iter_dicts(output.get("observations"))
    if observations:
        rows = [
            " ".join(
                f"{key}={row.get(key)}"
                for key in (
                    "indicator", "series_id", "observation_date", "value",
                )
                if row.get(key) not in (None, "")
            )
            for row in observations[:8]
        ]
        pieces.append("Macro " + " | ".join(rows))

    option_chain = _iter_dicts(output.get("option_chain"))
    if option_chain:
        strikes = [
            str(row.get("price"))
            for row in option_chain[:12]
            if row.get("price") is not None
        ]
        pieces.append(
            "Options "
            f"expiry={output.get('expiry_date') or ''} "
            f"sample_strikes={','.join(strikes)} "
            f"contracts={len(option_chain)}"
        )

    categories = output.get("research_categories")
    if isinstance(categories, list) and categories:
        pieces.append("研究类别=" + ",".join(str(item) for item in categories[:6]))

    if pieces:
        return "；".join(pieces)[:900]
    if summary:
        return summary[:240]
    return str(output)[:900]


def _looks_generic_success(summary: str) -> bool:
    lowered = summary.strip().lower()
    return any(lowered.endswith(suffix) for suffix in _GENERIC_SUCCESS_SUFFIXES)


def _iter_dicts(value: Any) -> List[Dict[str, Any]]:
    if isinstance(value, dict):
        return [value]
    if not isinstance(value, list):
        return []
    return [item for item in value if isinstance(item, dict)]


def _first(row: Dict[str, Any], *keys: str) -> Any:
    for key in keys:
        value = row.get(key)
        if value is not None and value != "":
            return value
    return None


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
