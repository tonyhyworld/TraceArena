"""
P1-5 ReplayRecorder — 回放记录器

记录每 tick 的五份 OS2 权威契约，供回放使用。
"""
from __future__ import annotations

import logging
import json
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


class ReplayRecorder:
    """回放记录器：只记录可验证的 OS2 事实链。"""

    def __init__(self, run_id: str, seed: int, scenario_version: str):
        self._run_id = run_id
        self._seed = seed
        self._scenario_version = scenario_version
        self._tick_traces: List[Dict[str, Any]] = []

    def record_tick(
        self, tick: int,
        world_actions: Optional[List[Dict]] = None,
        external_observations: Optional[List[Dict]] = None,
        world_events: Optional[List[Dict]] = None,
        settlements: Optional[List[Dict]] = None,
        director_plan: Optional[Dict] = None,
        tool_runs: Optional[List[Dict]] = None,
    ) -> None:
        self._tick_traces.append({
            "tick": tick,
            "world_actions": world_actions or [],
            "external_observations": external_observations or [],
            "world_events": world_events or [],
            "settlements": settlements or [],
            "director_plan": director_plan,
            "tool_runs": tool_runs or [],
        })

    def export(self) -> Dict[str, Any]:
        return {
            "run_id": self._run_id,
            "seed": self._seed,
            "scenario_version": self._scenario_version,
            "ticks": self._tick_traces,
        }

    def export_to(self, path: str) -> str:
        target = Path(path)
        target.parent.mkdir(parents=True, exist_ok=True)
        target.write_text(
            json.dumps(self.export(), ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return str(target)
