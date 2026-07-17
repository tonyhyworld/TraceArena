"""OS 2.0 generic tick orchestration."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional


@dataclass
class TickContext:
    """Explicit hand-off contract shared by all phases of one world tick."""

    state: Any = None
    tick: int = 0
    briefs: Dict[str, Any] = field(default_factory=dict)
    actions: Dict[str, Any] = field(default_factory=dict)
    logs: List[Any] = field(default_factory=list)
    valid_actions: Dict[str, Any] = field(default_factory=dict)
    tool_results: Dict[str, Any] = field(default_factory=dict)
    tool_run_start_index: int = 0
    tick_tool_runs: List[Any] = field(default_factory=list)
    pipeline_results: List[Any] = field(default_factory=list)
    assessment_tick: Dict[str, Any] = field(default_factory=dict)
    completed_phases: List[str] = field(default_factory=list)
    failed_phase: Optional[str] = None


@dataclass
class TickPipeline:
    """Run the only supported OS 2.0 tick path."""

    engine: Any

    async def run(self) -> None:
        context = TickContext()
        phases = (
            ("perceive_and_decide", self.engine._phase_perceive_and_decide),
            ("execute_and_settle", self.engine._phase_execute_and_settle),
            ("assess_and_present", self.engine._phase_assess_and_present),
            ("finalize_lifecycle", self.engine._phase_finalize_lifecycle),
        )
        for name, phase in phases:
            try:
                await phase(context)
                context.completed_phases.append(name)
            except Exception:
                context.failed_phase = name
                raise
