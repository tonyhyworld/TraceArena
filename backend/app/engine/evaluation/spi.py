"""Scene-selected world execution SPI for AI World OS.

The OS never assumes that an action belongs to a simulated physics world.
Each scene declares an execution route. Only ``simulation`` routes may load
RuleWorld; reality and deterministic routes flow directly into the scene's
SettlementRuntime.
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
        uses_simulation = any(
            str(route.get("mode") or "") == "simulation"
            for route in [self._default_route, *self._routes.values()]
        )
        self._simulation = (
            self._resolve_simulation_provider() if uses_simulation else None
        )

    def _resolve_simulation_provider(self) -> Any:
        """从内置注册表解析 simulation provider（内置物理引擎不是硬编码默认）。

        优先按 simulation 路由声明的 provider_id 从注册表解析；未注册的
        provider_id（如场景自命名的 provider）回退到内置参考物理引擎——
        当前唯一内置。这样 OS 不假设"simulation=必然用某个类"，且为将来注册
        其它 simulation provider 留出通道。
        """
        declared = [
            str(route.get("provider_id") or "")
            for route in [self._default_route, *self._routes.values()]
            if str(route.get("mode") or "") == "simulation"
        ]
        for provider_id in declared:
            factory = get_builtin_provider_factory(provider_id)
            if factory is not None:
                return factory(self._runtime)
        factory = get_builtin_provider_factory(BUILTIN_RULEWORLD_PHYSICS)
        if factory is not None:
            return factory(self._runtime)
        return RuleWorldEvaluationProvider(self._runtime)

    @classmethod
    def _validate_route(cls, action_id: str, route: Dict[str, Any]) -> None:
        mode = str(route.get("mode") or "")
        if mode not in cls._VALID_MODES:
            raise ValueError(f"invalid execution mode for {action_id}: {mode}")
        if not route.get("provider_id"):
            raise ValueError(f"execution route missing provider_id: {action_id}")

    def execution_route(self, action_id: str) -> Dict[str, Any]:
        route = dict(self._routes.get(action_id) or self._default_route)
        route["action_id"] = action_id
        return route

    def requires_simulation(self, action_id: str) -> bool:
        return self.execution_route(action_id).get("mode") == "simulation"

    def initialize(self) -> None:
        if self._simulation:
            self._simulation.initialize()

    @property
    def context(self) -> Any:
        return self._simulation.context if self._simulation else None

    def set_judge(self, judge: Any, **opts: Any) -> None:
        if self._simulation:
            self._simulation.set_judge(judge, **opts)

    def bind_state(self, state: Any) -> None:
        if self._simulation:
            self._simulation.bind_state(state)

    def advance_tick(self, tick: int) -> None:
        if self._simulation:
            self._simulation.advance_tick(tick)

    async def run_causal_pipeline(
        self,
        action: ActionPack,
        tick: int,
        state: Any,
        tool_result: Any = None,
    ) -> CausalPipelineResult:
        route = self.execution_route(action.action_id)
        if route.get("mode") != "simulation" or self._simulation is None:
            raise RuntimeError(
                f"action {action.action_id} is owned by settlement provider "
                f"{route.get('provider_id')}; simulation pipeline is forbidden"
            )
        return await self._simulation.run_causal_pipeline(
            action, tick, state, tool_result=tool_result
        )

    def export_ledgers(self) -> Dict[str, Any]:
        return self._simulation.export_ledgers() if self._simulation else {}

    @property
    def tools_cfg(self) -> List[Dict[str, Any]]:
        return self._runtime.tools_cfg

    def get_action_rule(self, action_id: str) -> Dict[str, Any]:
        return self._runtime.get_action_rule(action_id)
