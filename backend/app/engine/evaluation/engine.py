"""
L5 Evaluation & Causal Physics Engine — 双轨评价与因果物理裁决

职责：
- 5A：模型能力评价（面向运营后台，行为能力评分）
- 5B：因果物理裁决（面向世界运行，Action→StateDelta→Metric 全链路）

因果物理链路：
  Action → ActionEvaluator → ActionValidityGate → ForceBudgetCalculator
         → CausalPhysicsEngine → StateDeltaService → MetricDerivationService
         → CausalSequenceBuilder → CausalPipelineResult

铁律：
- 模型不能直接改世界
- 行动不能直接加分
- 所有指标从 StateDelta 派生
- 每一次变化都可回溯
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.interfaces import (
    ActionPack,
    CausalPipelineResult,
    CausalSequence,
)
from app.engine.scenario_boot.registry import ScenarioRuntime
from app.engine.evaluation.spi import (
    EvaluationProvider,
    ScenarioExecutionRouter,
)

logger = logging.getLogger(__name__)


class EvaluationEngine:
    """
    L5 评估引擎。

    封装 RuleWorldContext 的因果管线，提供统一的评估入口。
    内部委托给已有的 framework.ruleworld 服务实现。
    """

    def __init__(
        self,
        runtime: ScenarioRuntime,
        provider: Optional[EvaluationProvider] = None,
    ):
        self._runtime = runtime
        self._provider = provider or ScenarioExecutionRouter(runtime)
        self._initialized = False

    def initialize(self) -> None:
        """初始化因果物理服务（创建 RuleWorldContext）"""
        if self._initialized:
            return
        try:
            self._provider.initialize()
            self._initialized = True
            logger.info("[L5] EvaluationEngine 初始化完成")
        except Exception as e:
            logger.error(f"[L5] EvaluationEngine 初始化失败: {e}")
            raise

    @property
    def context(self) -> Any:
        return self._provider.context

    def set_judge(self, judge: Any, **opts: Any) -> None:
        """注入 L5 行动评价 LLM Judge provider。"""
        self._provider.set_judge(judge, **opts)
        logger.info("[L5] LLM Judge 已注入行动评价器")

    def bind_state(self, state: Any) -> None:
        """绑定 WorldState（world.initialize 后调用）"""
        self._provider.bind_state(state)

    def advance_tick(self, tick: int) -> None:
        self._provider.advance_tick(tick)

    async def run_causal_pipeline(
        self,
        action: ActionPack,
        tick: int,
        state: Any,
        tool_result: Any = None,
    ) -> CausalPipelineResult:
        """执行因果物理管线（核心入口），可选传入 L4 tool_result 供 SupportEvaluation 使用"""
        return await self._provider.run_causal_pipeline(
            action, tick, state, tool_result=tool_result
        )

    async def run_action_batch(
        self,
        actions: List[ActionPack],
        tick: int,
        state: Any,
        tool_results: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, CausalPipelineResult]:
        """Execute a complete world tick without advancing adapters per agent."""
        runner = getattr(self._provider, "run_action_batch", None)
        if callable(runner):
            return await runner(actions, tick, state, tool_results or {})
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
        return self._provider.export_ledgers()

    @property
    def objects(self) -> Any:
        if self.context:
            return self.context.objects
        return None

    @property
    def pressure(self) -> Any:
        if self.context:
            return self.context.pressure
        return None

    @property
    def recorder(self) -> Any:
        if self.context:
            return self.context.recorder
        return None

    @property
    def tools_cfg(self) -> List[Dict[str, Any]]:
        return self._provider.tools_cfg

    def get_action_rule(self, action_id: str) -> Dict[str, Any]:
        return self._provider.get_action_rule(action_id)

    def execution_route(self, action_id: str) -> Dict[str, Any]:
        return self._provider.execution_route(action_id)

    def requires_simulation(self, action_id: str) -> bool:
        return self._provider.requires_simulation(action_id)

    def world_observation(self, actor_id: str) -> Any:
        getter = getattr(self._provider, "observation", None)
        return getter(actor_id) if callable(getter) else None

    def close(self) -> None:
        close = getattr(self._provider, "close", None)
        if callable(close):
            close()
