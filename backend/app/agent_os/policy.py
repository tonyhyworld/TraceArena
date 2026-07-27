"""Trusted scenario extension boundary for Agent Harness policy.

The OS owns loop control, budgets, tools and traces.  A scenario may own
domain-specific evidence gates and final-payload normalization through this
small contract; the generic loop must not learn domain vocabulary.
"""
from __future__ import annotations

import importlib.util
import sys
import types
from pathlib import Path
from typing import Any, Dict, Optional, Protocol

from app.core.interfaces import AgentBrief


class HarnessPolicyAdapter(Protocol):
    plugin_id: str

    def requires_more_work(
        self, runner: Any, parsed: Dict[str, Any],
        brief: AgentBrief, session: Any,
    ) -> bool: ...

    def prepare_final(
        self, runner: Any, parsed: Dict[str, Any],
        brief: AgentBrief, session: Any,
    ) -> None: ...

    def policy_satisfied(
        self, runner: Any, brief: AgentBrief, session: Any,
    ) -> bool: ...

    async def on_budget_exhausted(
        self, runner: Any, *, agent_id: str, tick: int,
        parsed: Dict[str, Any], brief: AgentBrief, session: Any,
        productive_steps: int,
    ) -> int: ...

    def degraded_final_reason(
        self, runner: Any, brief: AgentBrief, session: Any,
    ) -> str: ...

    def enrich_final_action(
        self, runner: Any, action: Any, session: Any,
    ) -> None: ...

    def feedback_summary(
        self, runner: Any, session: Any, brief: AgentBrief,
        parsed: Optional[Dict[str, Any]], attempt: int,
    ) -> str: ...


def load_scenario_harness_policy(
    scenario_dir: str | Path,
) -> Optional[HarnessPolicyAdapter]:
    """Load a trusted scenario adapter through the public Harness contract."""
    path = Path(scenario_dir) / "harness" / "plugin.py"
    if not path.is_file():
        return None
    package_name = f"tracearena_scenario_harness_{abs(hash(path.parent.resolve()))}"
    package = types.ModuleType(package_name)
    package.__path__ = [str(path.parent)]  # type: ignore[attr-defined]
    package.__package__ = package_name
    sys.modules[package_name] = package
    module_name = f"{package_name}.plugin"
    spec = importlib.util.spec_from_file_location(module_name, path)
    if spec is None or spec.loader is None:
        raise RuntimeError(f"harness_policy_plugin_load_failed:{path}")
    module = importlib.util.module_from_spec(spec)
    sys.modules[module_name] = module
    spec.loader.exec_module(module)
    factory = getattr(module, "create_plugin", None)
    if not callable(factory):
        raise ValueError(f"harness policy requires create_plugin(): {path}")
    plugin = factory()
    if (
        not getattr(plugin, "plugin_id", None)
        or not callable(getattr(plugin, "requires_more_work", None))
        or not callable(getattr(plugin, "prepare_final", None))
    ):
        raise TypeError(f"invalid harness policy plugin: {path}")
    return plugin
