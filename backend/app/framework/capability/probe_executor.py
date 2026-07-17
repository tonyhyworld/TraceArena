"""
Probe 子回合执行器（P1-5）

当某 Agent 触碰挑战对象时，OS 发起一次「专用 LLM 子调用」——用被测模型本人作答，
但与它在主循环里的角色行动彻底隔离：

  - 隔离历史：走 provider.complete()（单轮），不写入 agent 的对话历史，
    不污染它下一步的角色决策，也不让角色闲聊混进测评。
  - 隐藏答案分离：只读 probe 的下发字段；probe 结构本就不含 ground truth，
    这里再加一道防御性断言，杜绝答案意外泄漏进提示。
  - 结构化回收：要求模型按 output_schema 输出 JSON，回收 structured_answer + tool_calls。
  - 不抛异常：超时 / 解析失败返回带 error 的 ProbeResponse，让本 tick 存活，
    交由验证器判 0 分 / 引擎走诊断路径，绝不静默吞掉。

provider_resolver 由引擎注入（agent_runtime.get_context(aid).provider），
本执行器对具体 provider 实现无感知，可用假 provider 独立测试。
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import mimetypes
from pathlib import Path
import time
from typing import Any, Awaitable, Callable, Dict, List, Optional, Tuple

from app.providers.base import LLMProvider
from app.framework.capability.assessment import (
    CapabilityProbe,
    ProbeResponse,
    ProbeToolCall,
)

logger = logging.getLogger(__name__)

# 给定 agent_id 返回其 LLMProvider（被测模型本人）
ProviderResolver = Callable[[str], LLMProvider]
ToolExecutor = Callable[
    [CapabilityProbe, ProbeToolCall],
    Awaitable[ProbeToolCall],
]
DiagnosticSink = Callable[[Dict[str, Any]], None]

_SYSTEM_PROMPT = (
    "你正处于一次独立的能力测评子回合。请只阅读下面给出的任务材料，"
    "严格按要求的 JSON 输出格式作答，不要输出格式之外的多余文字，不要解释你是谁。"
    "若需要调用工具，请在 JSON 的 tool_calls 数组中声明。"
)


class ProbeExecutionError(Exception):
    """探针下发前的硬错误（如答案泄漏），属调用方编程错误，应中止。"""


class ProbeExecutor:
    """执行单个能力探针的专用 LLM 子调用。"""

    def __init__(
        self,
        provider_resolver: ProviderResolver,
        *,
        timeout_sec: float = 60.0,
        tool_executor: Optional[ToolExecutor] = None,
        diagnostic_sink: Optional[DiagnosticSink] = None,
    ):
        self._resolve = provider_resolver
        self._timeout = timeout_sec
        self._tool_executor = tool_executor
        self._diagnostic_sink = diagnostic_sink

    async def run(self, probe: CapabilityProbe) -> ProbeResponse:
        """同步在本 tick 内执行一次探针，返回模型作答（永不抛业务异常）。"""
        self._assert_no_answer_leak(probe)
        started = time.monotonic()
        self._diagnose("probe_started", probe, {
            "provider_agent_id": probe.agent_id,
            "available_tool_ids": list(probe.available_tool_ids),
            "material_keys": sorted(probe.materials),
        })

        provider = self._resolve(probe.agent_id)
        if provider is None:
            self._diagnose("probe_failed", probe, {
                "error": "no_provider_for_agent",
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            })
            return ProbeResponse(
                probe_id=probe.probe_id, agent_id=probe.agent_id,
                error="no_provider_for_agent",
            )

        system_prompt, user_message = self._build_messages(probe)
        image_data_urls = self._load_images(probe)
        try:
            raw = await asyncio.wait_for(
                # 推理模型先吐 <think> 再给答案，给足 token 预算，避免在思考段被截断。
                (
                    provider.complete_multimodal(
                        system_prompt, user_message, image_data_urls,
                        max_tokens=4096,
                    )
                    if image_data_urls
                    else provider.complete(
                        system_prompt, user_message, max_tokens=4096
                    )
                ),
                timeout=self._timeout,
            )
        except asyncio.TimeoutError:
            logger.warning(f"[ProbeExecutor] probe={probe.probe_id} agent={probe.agent_id} 超时")
            self._diagnose("probe_failed", probe, {
                "error": "timeout",
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            })
            return ProbeResponse(
                probe_id=probe.probe_id, agent_id=probe.agent_id, error="timeout",
            )
        except Exception as e:  # provider 实现异常不应炸掉整个 tick
            logger.warning(f"[ProbeExecutor] probe={probe.probe_id} provider 异常: {e}")
            self._diagnose("probe_failed", probe, {
                "error": f"provider_error: {e}",
                "duration_ms": round((time.monotonic() - started) * 1000, 2),
            })
            return ProbeResponse(
                probe_id=probe.probe_id, agent_id=probe.agent_id,
                error=f"provider_error: {e}",
            )

        structured, tool_calls, parse_err = self._parse(raw)
        if tool_calls and self._tool_executor is not None:
            executed: List[ProbeToolCall] = []
            for call in tool_calls:
                try:
                    executed.append(await self._tool_executor(probe, call))
                except Exception as exc:
                    executed.append(call.model_copy(update={
                        "ok": False,
                        "result": {"error": str(exc)},
                    }))
            tool_calls = executed
            self._diagnose("probe_tools_completed", probe, {
                "tool_calls": [
                    call.model_dump(mode="json") for call in tool_calls
                ],
            })
            tool_context = [
                {
                    "tool_id": call.tool_id,
                    "ok": call.ok,
                    "result_ref": call.result_ref,
                    "result": call.result,
                }
                for call in tool_calls
            ]
            followup = (
                user_message
                + "\n\n【工具真实返回】\n"
                + json.dumps(tool_context, ensure_ascii=False, indent=2)
                + "\n\n请基于工具真实返回，重新输出最终 JSON 答案。"
            )
            try:
                raw_final = await asyncio.wait_for(
                    provider.complete(system_prompt, followup, max_tokens=4096),
                    timeout=self._timeout,
                )
                final_structured, _, final_err = self._parse(raw_final)
                if final_structured:
                    structured = final_structured
                    raw = f"{raw}\n\n--- tool follow-up ---\n{raw_final}"
                    parse_err = final_err
            except Exception as exc:
                parse_err = f"tool_followup_error: {exc}"
        response = ProbeResponse(
            probe_id=probe.probe_id,
            agent_id=probe.agent_id,
            raw_output=raw or "",
            structured_answer=structured,
            tool_calls=tool_calls,
            error=parse_err,
        )
        self._diagnose("probe_completed", probe, {
            "duration_ms": round((time.monotonic() - started) * 1000, 2),
            "parse_error": parse_err,
            "raw_output": raw or "",
            "structured_answer": structured,
            "tool_calls": [
                call.model_dump(mode="json") for call in tool_calls
            ],
        })
        return response

    def _diagnose(
        self,
        event_type: str,
        probe: CapabilityProbe,
        payload: Dict[str, Any],
    ) -> None:
        if self._diagnostic_sink is None:
            return
        try:
            self._diagnostic_sink({
                "event_type": event_type,
                "probe_id": probe.probe_id,
                "tick": probe.tick,
                "agent_id": probe.agent_id,
                "capability": probe.capability,
                "node_id": probe.node_id,
                "variant_id": probe.variant_id,
                **payload,
            })
        except Exception:
            logger.exception("[ProbeExecutor] 诊断日志写入失败")

    # ── 内部 ────────────────────────────────────────────────────────────────

    @staticmethod
    def _assert_no_answer_leak(probe: CapabilityProbe) -> None:
        """防御性检查：下发材料里不得出现隐藏答案键，避免送分。"""
        banned = {"ground_truth", "answer_key", "expected", "checks", "rubric"}
        leaked = banned & set(probe.materials.keys())
        if leaked:
            raise ProbeExecutionError(
                f"probe.materials 含疑似答案键 {sorted(leaked)}，拒绝下发。"
            )

    @staticmethod
    def _build_messages(probe: CapabilityProbe) -> Tuple[str, str]:
        parts: List[str] = []
        if probe.instruction:
            parts.append(f"【任务】\n{probe.instruction}")
        if probe.materials:
            visible_materials = {
                key: value for key, value in probe.materials.items()
                if key != "image_paths"
            }
            if visible_materials:
                parts.append("【材料】\n" + json.dumps(visible_materials, ensure_ascii=False, indent=2))
            if probe.materials.get("image_paths"):
                parts.append("【图像材料】已随本消息附加，请直接观察图像。")
        if probe.available_tool_ids:
            parts.append("【可用工具】\n" + ", ".join(probe.available_tool_ids))
            parts.append(
                "【工具代码约定】如调用代码/分析工具，请在 arguments.code 中提交 Python。"
                "沙盒不允许 print；必须用 world.emit_output(claim='说明', value=结果) "
                "输出结构化结果。工具执行后系统会把真实返回交给你，再生成最终答案。"
            )
        schema = dict(probe.output_schema)
        schema.setdefault("tool_calls", "可选：[{tool, arguments}] 列表")
        parts.append(
            "【输出格式】请只输出一个 JSON 对象，字段如下：\n"
            + json.dumps(schema, ensure_ascii=False, indent=2)
        )
        return _SYSTEM_PROMPT, "\n\n".join(parts)

    @staticmethod
    def _load_images(probe: CapabilityProbe) -> List[str]:
        urls: List[str] = []
        for raw_path in probe.materials.get("image_paths", []) or []:
            path = Path(str(raw_path))
            if not path.exists() or not path.is_file():
                continue
            mime = mimetypes.guess_type(path.name)[0] or "image/png"
            encoded = base64.b64encode(path.read_bytes()).decode("ascii")
            urls.append(f"data:{mime};base64,{encoded}")
        return urls

    @staticmethod
    def _parse(raw: str) -> Tuple[Dict[str, Any], List[ProbeToolCall], Any]:
        """从原始输出抽取结构化答案与工具调用；解析失败返回 error 字符串。"""
        # 推理模型（如 MiniMax-M2.7）会先吐 <think>...</think> 推理段，其中常回显材料里的
        # JSON 片段，会污染贪婪的 {..} 提取。真正的结构化答案在最后一个 </think> 之后。
        text = raw or ""
        if "</think>" in text:
            text = text.rsplit("</think>", 1)[-1]
        data = LLMProvider._extract_json(text)
        if not data:
            return {}, [], "parse_failed: no JSON object found"

        tool_calls: List[ProbeToolCall] = []
        raw_calls = data.get("tool_calls") or []
        if isinstance(raw_calls, list):
            for tc in raw_calls:
                if not isinstance(tc, dict):
                    continue
                tid = tc.get("tool") or tc.get("tool_id") or ""
                if not tid:
                    continue
                args = tc.get("arguments") or tc.get("args") or {}
                if not isinstance(args, dict):
                    args = {"value": args}
                tool_calls.append(ProbeToolCall(tool_id=str(tid), arguments=args))

        # structured_answer = 除 tool_calls 外的全部字段
        structured = {k: v for k, v in data.items() if k != "tool_calls"}
        return structured, tool_calls, None


__all__ = ["ProbeExecutor", "ProbeExecutionError", "ProviderResolver"]
