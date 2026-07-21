"""Scene-selected world execution SPI for AI World OS.

The OS never assumes that an action belongs to a simulated physics world.
Each scene declares an execution route. Any settlement mode may optionally
use a World Adapter to advance an executable world; ``simulation`` must name
one. SettlementRuntime remains the independent authority for scoring.
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol

from app.contracts.settlement_types import (
    BUILTIN_RULEWORLD_PHYSICS,
    get_builtin_provider_factory,
    register_builtin_provider,
)
from app.core.interfaces import ActionPack, CausalPipelineResult
from app.engine.scenario_boot.registry import ScenarioRuntime
from app.engine.world_adapter import get_world_adapter_factory
from app.engine.world_adapter.provider import WorldAdapterEvaluationProvider


class EvaluationProvider(Protocol):
    def initialize(self) -> None:
        ...

    @property
    def context(self) -> Any:
        ...

    def set_judge(self, judge: Any, **opts: Any) -> None:
        ...

    def bind_state(self, state: Any) -> None:
        ...

    def advance_tick(self, tick: int) -> None:
        ...

    async def run_causal_pipeline(
        self,
        action: ActionPack,
        tick: int,
        state: Any,
        tool_result: Any = None,
    ) -> CausalPipelineResult:
        ...

    async def run_action_batch(
        self,
        actions: List[ActionPack],
        tick: int,
        state: Any,
        tool_results: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, CausalPipelineResult]:
        ...

    def export_ledgers(self) -> Dict[str, Any]:
        ...

    @property
    def tools_cfg(self) -> List[Dict[str, Any]]:
        ...

    def get_action_rule(self, action_id: str) -> Dict[str, Any]:
        ...

    def execution_route(self, action_id: str) -> Dict[str, Any]:
        ...

    def requires_simulation(self, action_id: str) -> bool:
        ...

    def observation(self, actor_id: str) -> Any:
        ...

    def close(self) -> None:
        ...


class RuleWorldEvaluationProvider:
    """Simulation-only provider backed by framework.ruleworld."""

    def __init__(self, runtime: ScenarioRuntime):
        self._runtime = runtime
        self._ctx: Any = None
        self._initialized = False

    def initialize(self) -> None:
        if self._initialized:
            return
        from app.framework.ruleworld.context import RuleWorldContext

        self._ctx = RuleWorldContext(self._runtime)
        self._initialized = True

    @property
    def context(self) -> Any:
        return self._ctx

    def set_judge(self, judge: Any, **opts: Any) -> None:
        if self._ctx is not None:
            self._ctx.set_judge(judge, **opts)

    def bind_state(self, state: Any) -> None:
        if self._ctx:
            self._ctx.bind_state(state)

    def advance_tick(self, tick: int) -> None:
        if self._ctx:
            self._ctx.advance_tick(tick)

    async def run_causal_pipeline(
        self,
        action: ActionPack,
        tick: int,
        state: Any,
        tool_result: Any = None,
    ) -> CausalPipelineResult:
        if not self._ctx:
            return CausalPipelineResult(
                tick=tick,
                action_id=f"act_{tick}_{action.agent_id}",
                agent_id=action.agent_id,
                outcome="error",
                errors=["EvaluationProvider 未初始化"],
            )
        return await self._ctx.run_causal_pipeline(
            action, tick, state, tool_result=tool_result
        )

    async def run_action_batch(
        self,
        actions: List[ActionPack],
        tick: int,
        state: Any,
        tool_results: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, CausalPipelineResult]:
        results: Dict[str, CausalPipelineResult] = {}
        for action in actions:
            results[action.agent_id] = await self.run_causal_pipeline(
                action,
                tick,
                state,
                tool_result=(tool_results or {}).get(action.agent_id),
            )
        return results

    def export_ledgers(self) -> Dict[str, Any]:
        if not self._ctx:
            return {}
        return self._ctx.export_ledgers()

    @property
    def tools_cfg(self) -> List[Dict[str, Any]]:
        if self._ctx:
            return self._ctx.tools_cfg
        return self._runtime.tools_cfg

    def get_action_rule(self, action_id: str) -> Dict[str, Any]:
        return self._runtime.get_action_rule(action_id)

    def execution_route(self, action_id: str) -> Dict[str, Any]:
        return {
            "mode": "simulation",
            "provider_id": "ruleworld",
            "action_id": action_id,
        }

    def requires_simulation(self, action_id: str) -> bool:
        return True

    def observation(self, actor_id: str) -> Any:
        return None

    def close(self) -> None:
        return None


# 把内置物理引擎登记为**一个可选的内置参考实现**，而不是 OS 的默认评价体系。
# 场景通过 simulation 路由的 provider_id 选用它；未来可注册其它 simulation
# provider，路由按 id 解析。见 docs/OS层与场景包边界约定.md 第 4.1 节。
register_builtin_provider(
    BUILTIN_RULEWORLD_PHYSICS,
    lambda runtime: RuleWorldEvaluationProvider(runtime),
)


class ScenarioExecutionRouter:
    """Routes actions strictly from the scene's execution declaration."""

    _VALID_MODES = {
        "simulation",
        "external_reality",
        "deterministic_verifier",
        "hybrid",
    }

    def __init__(self, runtime: ScenarioRuntime):
        self._runtime = runtime
        config = dict(getattr(runtime, "settlement_cfg", {}) or {})
        execution = dict(config.get("execution", {}) or {})
        self._default_route = dict(execution.get("default", {}) or {})
        self._routes = {
            str(action_id): dict(route)
            for action_id, route in dict(execution.get("routes", {}) or {}).items()
            if isinstance(route, dict)
        }
        if not self._default_route:
            raise ValueError(
                "scene settlement/manifest.yaml must declare execution.default"
            )
        self._validate_route("default", self._default_route)
        for action_id, route in self._routes.items():
            self._validate_route(action_id, route)
        uses_world_adapter = any(
            bool(route.get("world_adapter_id"))
            for route in [self._default_route, *self._routes.values()]
        )
        self._world_adapters = (
            self._resolve_world_adapters() if uses_world_adapter else {}
        )
        # Compatibility for diagnostics/tests written before the execution
        # axis was decoupled from settlement authority.
        self._simulation_providers = self._world_adapters
        # Compatibility for existing diagnostics/tests that inspect the single
        # provider. New code resolves the provider for every action route.
        self._simulation = next(
            iter(self._world_adapters.values()), None
        )

    def _resolve_world_adapters(self) -> Dict[str, Any]:
        """Resolve declared executable worlds; never silently fall back."""
        declared = {
            str(route.get("world_adapter_id") or "")
            for route in [self._default_route, *self._routes.values()]
            if route.get("world_adapter_id")
        }
        if len(declared) > 1:
            raise ValueError(
                "a scenario may declare only one world_adapter_id; "
                "compose multiple engines behind one adapter"
            )
        resolved: Dict[str, Any] = {}
        for adapter_id in sorted(declared):
            builtin_factory = get_builtin_provider_factory(adapter_id)
            if builtin_factory is not None:
                routes_for_adapter = [
                    route
                    for route in [self._default_route, *self._routes.values()]
                    if str(route.get("world_adapter_id") or "") == adapter_id
                ]
                if any(
                    str(route.get("mode") or "") != "simulation"
                    for route in routes_for_adapter
                ):
                    raise ValueError(
                        "builtin RuleWorld may only execute simulation routes"
                    )
                resolved[adapter_id] = builtin_factory(self._runtime)
                continue
            adapter_factory = get_world_adapter_factory(adapter_id)
            resolved[adapter_id] = WorldAdapterEvaluationProvider(
                self._runtime,
                adapter_factory(),
                adapter_id,
            )
        return resolved

    @classmethod
    def _validate_route(cls, action_id: str, route: Dict[str, Any]) -> None:
        mode = str(route.get("mode") or "")
        if mode not in cls._VALID_MODES:
            raise ValueError(f"invalid execution mode for {action_id}: {mode}")
        if not route.get("provider_id"):
            raise ValueError(f"execution route missing provider_id: {action_id}")
        if mode == "simulation" and not route.get("world_adapter_id"):
            raise ValueError(
                f"simulation route missing world_adapter_id: {action_id}"
            )

    def _provider_for_action(self, action_id: str) -> Any:
        route = self.execution_route(action_id)
        adapter_id = str(route.get("world_adapter_id") or "")
        provider = self._world_adapters.get(adapter_id)
        if provider is None:
            raise RuntimeError(
                f"world adapter not resolved for action {action_id}: {adapter_id}"
            )
        return provider

    def execution_route(self, action_id: str) -> Dict[str, Any]:
        route = dict(self._routes.get(action_id) or self._default_route)
        route["action_id"] = action_id
        return route

    def requires_simulation(self, action_id: str) -> bool:
        # Kept for protocol compatibility. It now means the route needs an
        # executable world pass, independently of settlement authority.
        return bool(self.execution_route(action_id).get("world_adapter_id"))

    def initialize(self) -> None:
        for provider in self._world_adapters.values():
            provider.initialize()

    @property
    def context(self) -> Any:
        return self._simulation.context if self._simulation else None

    def set_judge(self, judge: Any, **opts: Any) -> None:
        for provider in self._world_adapters.values():
            provider.set_judge(judge, **opts)

    def bind_state(self, state: Any) -> None:
        for provider in self._world_adapters.values():
            provider.bind_state(state)

    def advance_tick(self, tick: int) -> None:
        for provider in self._world_adapters.values():
            provider.advance_tick(tick)

    async def run_causal_pipeline(
        self,
        action: ActionPack,
        tick: int,
        state: Any,
        tool_result: Any = None,
    ) -> CausalPipelineResult:
        route = self.execution_route(action.action_id)
        if not route.get("world_adapter_id"):
            raise RuntimeError(
                f"action {action.action_id} is owned by settlement provider "
                f"{route.get('provider_id')}; no world adapter is declared"
            )
        provider = self._provider_for_action(action.action_id)
        return await provider.run_causal_pipeline(
            action, tick, state, tool_result=tool_result
        )

    async def run_action_batch(
        self,
        actions: List[ActionPack],
        tick: int,
        state: Any,
        tool_results: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, CausalPipelineResult]:
        grouped: Dict[str, List[ActionPack]] = {}
        for action in actions:
            route = self.execution_route(action.action_id)
            if not route.get("world_adapter_id"):
                raise RuntimeError(
                    f"action without world adapter in execution batch: "
                    f"{action.action_id}"
                )
            adapter_id = str(route.get("world_adapter_id") or "")
            grouped.setdefault(adapter_id, []).append(action)
        results: Dict[str, CausalPipelineResult] = {}
        for adapter_id, batch in grouped.items():
            provider = self._world_adapters[adapter_id]
            produced = await provider.run_action_batch(
                batch, tick, state, tool_results or {}
            )
            results.update(produced)
        return results

    def export_ledgers(self) -> Dict[str, Any]:
        merged: Dict[str, Any] = {}
        for provider in self._world_adapters.values():
            for key, value in provider.export_ledgers().items():
                if isinstance(value, list):
                    merged.setdefault(key, []).extend(value)
                else:
                    merged[key] = value
        return merged

    @property
    def tools_cfg(self) -> List[Dict[str, Any]]:
        return self._runtime.tools_cfg

    def get_action_rule(self, action_id: str) -> Dict[str, Any]:
        return self._runtime.get_action_rule(action_id)

    def observation(self, actor_id: str) -> Any:
        observations = []
        for provider in self._world_adapters.values():
            item = provider.observation(actor_id)
            if item is not None:
                observations.append(item)
        if not observations:
            return None
        if len(observations) == 1:
            return observations[0]
        return observations

    def close(self) -> None:
        for provider in self._world_adapters.values():
            close = getattr(provider, "close", None)
            if callable(close):
                close()
