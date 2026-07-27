"""Objective health metrics and production gates for Agent Harness runs."""
from __future__ import annotations

import json
from collections import Counter
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any, Dict, Iterable, List


@dataclass(frozen=True)
class HarnessHealthThresholds:
    min_turns: int = 30
    min_traces: int = 30
    min_real_steps: int = 30
    min_trace_completion_rate: float = 0.98
    min_tool_success_rate: float = 0.90
    max_turn_error_rate: float = 0.01
    max_timeout_rate: float = 0.01
    max_blocked_rate: float = 0.05
    min_token_consistency_rate: float = 0.99


def read_harness_records(root: str | Path) -> List[Dict[str, Any]]:
    records: List[Dict[str, Any]] = []
    for path in Path(root).glob("**/agents/*/harness_io.jsonl"):
        for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
            try:
                item = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(item, dict):
                records.append(item)
    return records


def summarize_harness_health(
    records: Iterable[Dict[str, Any]],
) -> Dict[str, Any]:
    raw_rows = list(records)
    unique_rows: Dict[tuple[Any, ...], Dict[str, Any]] = {}
    anonymous_rows: List[Dict[str, Any]] = []
    for row in raw_rows:
        trace = row.get("harness_trace") or {}
        identity = (
            trace.get("run_id"),
            trace.get("agent_id") or row.get("agent_id"),
            trace.get("world_tick") or row.get("tick"),
        )
        if all(value is not None and value != "" for value in identity):
            unique_rows[identity] = row
        else:
            anonymous_rows.append(row)
    rows = list(unique_rows.values()) + anonymous_rows
    traces = [row.get("harness_trace") for row in rows if row.get("harness_trace")]
    real_steps = [
        step
        for trace in traces
        for step in (trace.get("steps") or [])
        if step.get("kind") not in {"reflect", "submit_action"}
    ]
    timeouts = [
        row for row in rows
        if any(token in str(row.get("error") or "").lower()
               for token in ("timeout", "timed out", "readtimeout", "超时"))
        or str((row.get("harness_trace") or {}).get(
            "termination_reason", ""
        )) in {"session_timeout", "llm_step_timeout"}
    ]
    comparable_tokens = []
    for row in rows:
        trace_tokens = (
            ((row.get("harness_trace") or {}).get("usage") or {}).get("tokens")
        )
        log_tokens = row.get("tokens_used")
        if trace_tokens is not None and log_tokens is not None:
            comparable_tokens.append(float(trace_tokens) == float(log_tokens))

    def failure_category(value: Any) -> str:
        text = str(value or "").lower()
        if not text:
            return "none"
        if any(token in text for token in ("timeout", "timed out", "超时")):
            return "timeout"
        if any(token in text for token in ("quota", "rate_limit", "429", "余额")):
            return "quota_or_rate_limit"
        if any(token in text for token in ("unauthorized", "forbidden", "401", "403", "api key")):
            return "authentication"
        if any(token in text for token in ("connect", "network", "dns", "eof")):
            return "network"
        if any(token in text for token in ("parse", "json", "structured")):
            return "response_contract"
        if any(token in text for token in ("cancel", "shutdown")):
            return "cancelled"
        return "other"

    turn_failures = Counter(
        failure_category(row.get("error"))
        for row in rows if row.get("error")
    )
    terminations = Counter(
        str(trace.get("termination_reason") or "unspecified")
        for trace in traces
    )
    failed_tool_sources = Counter(
        str((step.get("details") or {}).get("source") or "unknown")
        for step in real_steps if step.get("status") != "succeeded"
    )
    failed_tool_categories = Counter(
        failure_category(" ".join(
            str(item) for item in ((step.get("details") or {}).get("errors") or [])
        ))
        for step in real_steps if step.get("status") != "succeeded"
    )

    def rate(numerator: int, denominator: int) -> float:
        return numerator / denominator if denominator else 1.0

    metrics = {
        "raw_turns": len(raw_rows),
        "duplicate_turns": len(raw_rows) - len(rows),
        "turns": len(rows),
        "traces": len(traces),
        "real_steps": len(real_steps),
        "trace_completion_rate": rate(
            sum(
                trace.get("status") in {"completed", "suspended"}
                for trace in traces
            ),
            len(traces),
        ),
        "research_suspended_rate": rate(
            sum(trace.get("status") == "suspended" for trace in traces),
            len(traces),
        ),
        "tool_success_rate": rate(
            sum(step.get("status") == "succeeded" for step in real_steps),
            len(real_steps),
        ),
        "turn_error_rate": rate(
            sum(bool(row.get("error")) for row in rows), len(rows),
        ),
        "timeout_rate": rate(len(timeouts), len(rows)),
        "blocked_rate": rate(
            sum(trace.get("status") in {"blocked", "budget_exhausted"}
                for trace in traces),
            len(traces),
        ),
        "token_consistency_rate": rate(
            sum(comparable_tokens), len(comparable_tokens),
        ),
        "turn_failure_breakdown": dict(turn_failures.most_common()),
        "termination_breakdown": dict(terminations.most_common()),
        "tool_failure_source_breakdown": dict(
            failed_tool_sources.most_common()
        ),
        "tool_failure_category_breakdown": dict(
            failed_tool_categories.most_common()
        ),
    }
    return metrics


def evaluate_production_gate(
    metrics: Dict[str, Any],
    thresholds: HarnessHealthThresholds | None = None,
) -> Dict[str, Any]:
    cfg = thresholds or HarnessHealthThresholds()
    checks = {
        "minimum_turns": metrics.get("turns", 0) >= cfg.min_turns,
        "minimum_traces": metrics.get("traces", 0) >= cfg.min_traces,
        "minimum_real_steps": metrics.get("real_steps", 0) >= cfg.min_real_steps,
        "trace_completion_rate": metrics.get("trace_completion_rate", 0.0)
        >= cfg.min_trace_completion_rate,
        "tool_success_rate": metrics.get("tool_success_rate", 0.0)
        >= cfg.min_tool_success_rate,
        "turn_error_rate": metrics.get("turn_error_rate", 1.0)
        <= cfg.max_turn_error_rate,
        "timeout_rate": metrics.get("timeout_rate", 1.0)
        <= cfg.max_timeout_rate,
        "blocked_rate": metrics.get("blocked_rate", 1.0)
        <= cfg.max_blocked_rate,
        "token_consistency_rate": metrics.get("token_consistency_rate", 0.0)
        >= cfg.min_token_consistency_rate,
    }
    return {
        "passed": all(checks.values()),
        "checks": checks,
        "metrics": dict(metrics),
        "thresholds": asdict(cfg),
    }
