"""Billable provider canary built on the real generic AgentLoopRunner."""
from __future__ import annotations

import json
import time
from pathlib import Path
from types import SimpleNamespace
from typing import Any, Dict, List

from app.agent_os.health import evaluate_production_gate, summarize_harness_health
from app.agent_os.loop import AgentLoopRunner
from app.core.atomic_io import atomic_write_text
from app.core.interfaces import ActionPack, AgentBrief, ToolRunResult
from app.core.redaction import redact_credentials, redact_structure
from app.framework.prompting.action_parser import ActionParser


_SYSTEM_PROMPT = """You are a production Harness canary agent.
Return exactly one JSON object and no markdown.
On the first request, submit:
{"agent_loop_step":"continue","action_id":"inspect","tool_request":{"tool_id":"canary:read","arguments":{"probe":"health"}}}
After the tool observation appears in history, submit:
{"agent_loop_step":"final","action_id":"complete","text":"canary verified"}
Never include credentials or private reasoning."""


async def run_provider_canary(
    provider: Any,
    *,
    turns: int = 30,
    agent_id: str = "provider_canary",
    output_dir: Path,
) -> Dict[str, Any]:
    if turns < 1:
        raise ValueError("turns must be positive")
    records: List[Dict[str, Any]] = []
    started_at = time.time()
    run_id = output_dir.name
    parser = ActionParser(actions_cfg=[
        {"id": "inspect"},
        {"id": "complete"},
    ])

    for tick in range(1, turns + 1):
        runner = AgentLoopRunner(
            config=SimpleNamespace(
                max_steps=3,
                session_timeout_sec=120.0,
                step_timeout_sec=60.0,
                tool_max_attempts=1,
                tool_retry_backoff_sec=0.0,
                tool_circuit_breaker_threshold=3,
            ),
            loop_context={},
        )

        async def execute(
            action: ActionPack, world_tick: int, step: int,
        ) -> tuple[List[str], ToolRunResult]:
            return [], ToolRunResult(
                run_id=f"canary_tool_{world_tick}_{step}",
                tool_id="canary:read",
                owner_id=action.agent_id,
                tick=world_tick,
                ok=True,
                source="canary",
                outputs=[{"summary": "provider and loop observation verified"}],
            )

        runner._execute_continue_step = execute  # type: ignore[method-assign]
        try:
            action, _raw, tokens, session = await runner.run(
                agent_id=agent_id,
                tick=tick,
                ctx=SimpleNamespace(history=[], provider=provider),
                brief=AgentBrief(agent_id=agent_id, tick=tick),
                system_prompt=_SYSTEM_PROMPT,
                base_user_message="Run the required canary sequence.",
                parse_response=parser.parse,
                build_action_from_parsed=lambda parsed, agent, _brief, _raw,
                partial=False: ActionPack(
                    agent_id=agent,
                    action_id=str(parsed.get("action_id") or "complete"),
                    parsed_ok=True,
                    text=str(parsed.get("text") or ""),
                    tool_request=dict(parsed.get("tool_request") or {}),
                    attached_tool_id=str(
                        (parsed.get("tool_request") or {}).get("tool_id") or ""
                    ) or None,
                ),
            )
            trace = session.to_harness_trace(
                run_id=run_id,
                scenario_id="generic_provider_canary",
                sandbox_id=f"sandbox:{agent_id}",
                objective="verify live provider through the generic Harness loop",
            )
            records.append({
                "tick": tick,
                "agent_id": agent_id,
                "provider": getattr(provider, "provider_name", "unknown"),
                "model": getattr(provider, "model_name", "unknown"),
                "tokens_used": tokens,
                "error": None if action is not None else "missing_final_action",
                "harness_trace": trace.model_dump(mode="json"),
            })
        except Exception as exc:
            records.append({
                "tick": tick,
                "agent_id": agent_id,
                "provider": getattr(provider, "provider_name", "unknown"),
                "model": getattr(provider, "model_name", "unknown"),
                "tokens_used": 0,
                "error": redact_credentials(
                    f"{type(exc).__name__}:{exc}"
                )[:1000],
                "harness_trace": None,
            })

    result = evaluate_production_gate(summarize_harness_health(records))
    result["canary"] = {
        "run_id": run_id,
        "provider": getattr(provider, "provider_name", "unknown"),
        "model": getattr(provider, "model_name", "unknown"),
        "turns_requested": turns,
        "started_at": started_at,
        "finished_at": time.time(),
    }
    safe_records = redact_structure(records)
    agent_dir = output_dir / "agents" / agent_id
    agent_dir.mkdir(parents=True, exist_ok=True)
    atomic_write_text(
        agent_dir / "harness_io.jsonl",
        "".join(
            json.dumps(row, ensure_ascii=False, default=str) + "\n"
            for row in safe_records
        ),
    )
    atomic_write_text(
        output_dir / "canary_result.json",
        json.dumps(
            redact_structure(result), ensure_ascii=False, indent=2, default=str
        ),
    )
    return result
