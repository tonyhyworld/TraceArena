"""Deterministic no-network endurance exercise for the generic Harness core."""
from __future__ import annotations

import asyncio
import json
from types import SimpleNamespace
from typing import Any, Dict, List

from app.agent_os.health import evaluate_production_gate, summarize_harness_health
from app.agent_os.loop import AgentLoopRunner
from app.core.interfaces import ActionPack, AgentBrief, ToolRunResult


class _SoakProvider:
    provider_name = "harness_soak"
    model_name = "deterministic"

    def __init__(self) -> None:
        self.calls = 0

    async def complete_with_history(self, *_args: Any, **_kwargs: Any) -> str:
        await asyncio.sleep(0)
        self.calls += 1
        if self.calls == 1:
            return json.dumps({
                "agent_loop_step": "continue",
                "action_id": "inspect",
                "tool_request": {
                    "tool_id": "mcp:soak:read",
                    "arguments": {"subject": "health"},
                },
            })
        return json.dumps({
            "agent_loop_step": "final",
            "action_id": "complete",
            "text": "verified",
        })

    async def get_usage(self) -> Dict[str, int]:
        return {"tokens": self.calls * 5}


async def run_harness_soak(
    turns: int = 100, concurrency: int = 1,
) -> Dict[str, Any]:
    """Run transient-recovery turns and evaluate them with production gates."""
    if turns < 1:
        raise ValueError("turns must be positive")
    if concurrency < 1 or concurrency > 256:
        raise ValueError("concurrency must be between 1 and 256")
    semaphore = asyncio.Semaphore(concurrency)
    active = 0
    peak_concurrency = 0

    async def run_turn(tick: int) -> tuple[Dict[str, Any], int]:
        nonlocal active, peak_concurrency
        async with semaphore:
            active += 1
            peak_concurrency = max(peak_concurrency, active)
            try:
                return await _run_turn(tick)
            finally:
                active -= 1

    async def _run_turn(tick: int) -> tuple[Dict[str, Any], int]:
        diagnostics: List[Dict[str, Any]] = []
        agent_id = f"soak_agent_{(tick - 1) % max(1, concurrency):03d}"
        runner = AgentLoopRunner(
            config=SimpleNamespace(
                max_steps=3,
                session_timeout_sec=2.0,
                step_timeout_sec=1.0,
                tool_max_attempts=2,
                tool_retry_backoff_sec=0.0,
                tool_circuit_breaker_threshold=3,
            ),
            loop_context={"diagnostic_sink": diagnostics.append},
        )
        attempts = 0

        async def execute(
            action: ActionPack, world_tick: int, _step: int,
        ) -> tuple[List[str], ToolRunResult]:
            nonlocal attempts
            await asyncio.sleep(0)
            attempts += 1
            recovered = attempts > 1
            return [], ToolRunResult(
                run_id=f"soak_tool_{world_tick}_{attempts}",
                tool_id="mcp:soak:read",
                owner_id=action.agent_id,
                tick=world_tick,
                ok=recovered,
                source="mcp",
                outputs=[{"summary": "verified health fact"}] if recovered else [],
                errors=[] if recovered else ["temporary ReadTimeout"],
            )

        runner._execute_continue_step = execute  # type: ignore[method-assign]
        provider = _SoakProvider()
        action, _, tokens, session = await runner.run(
            agent_id=agent_id,
            tick=tick,
            ctx=SimpleNamespace(history=[], provider=provider),
            brief=AgentBrief(agent_id=agent_id, tick=tick),
            system_prompt="generic harness soak",
            base_user_message="verify then complete",
            parse_response=lambda raw, _agent: json.loads(raw),
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
            run_id="harness_soak",
            scenario_id="generic_soak",
            sandbox_id=f"sandbox:{agent_id}",
            objective="verify generic harness endurance",
        )
        record = {
            "tick": tick,
            "agent_id": agent_id,
            "tokens_used": tokens,
            "error": None if action is not None else "missing_final_action",
            "harness_trace": trace.model_dump(mode="json"),
        }
        retries = sum(
            item.get("event_type") == "agent_loop_tool_retry"
            for item in diagnostics
        )
        return record, retries

    outcomes = await asyncio.gather(
        *(run_turn(tick) for tick in range(1, turns + 1))
    )
    records = [record for record, _retries in outcomes]
    retry_events = sum(retries for _record, retries in outcomes)
    result = evaluate_production_gate(summarize_harness_health(records))
    result["soak"] = {
        "turns_requested": turns,
        "concurrency_requested": concurrency,
        "peak_concurrency": peak_concurrency,
        "retry_events": retry_events,
        "all_transient_failures_recovered": retry_events == turns,
        "concurrency_exercised": (
            peak_concurrency == min(turns, concurrency)
        ),
    }
    result["passed"] = bool(
        result["passed"]
        and result["soak"]["all_transient_failures_recovered"]
        and result["soak"]["concurrency_exercised"]
    )
    return result
