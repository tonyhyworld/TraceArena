"""
L1 World State Kernel — 运行时世界状态唯一来源

职责：
- 持有 WorldState（tick、agent 存活、事件缓冲、内部状态）
- 提供状态查询与变更的唯一合法入口
- 推进 tick 时统一驱动 P0/P1 底座服务（资源刷新/冷却递减/延迟事件）
- 快照生成（公开信息，无秘密）

铁律：模型不能直接改世界——所有状态变更必须通过因果物理管线。
本层是状态变更的唯一合法入口：agent_locations / resources / cooldowns
等字段的修改必须通过本层的 set_* 方法，禁止外部直接赋值。

场景无关：本层不写死任何场景内容，底座服务由 L0 装配后注入。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.interfaces import (
    ActionOption,
    AgentSnapshot,
    Artifact,
    RuntimeSignal,
    WorldSnapshot,
)

logger = logging.getLogger(__name__)


class WorldState:
    """运行时世界状态容器（场景包可在 internal 中存任意数据）"""

    def __init__(self, agent_ids: List[str]):
        self.tick: int = 0
        self.is_running: bool = False
        self.is_game_over: bool = False
        self.winner_id: Optional[str] = None
        self.agent_ids: List[str] = list(agent_ids)
        self.alive_agent_ids: List[str] = list(agent_ids)
        # 淘汰名单（活死人机制）：按出局先后有序，[{agent_id, tick, reason}]。
        # 不从 alive_agent_ids 删人——只在动作收集入口拦截，避免牵动挑战轮转/
        # 独答对削弱等按人数恒定的逻辑。出局者从此不再产生任何动作。
        self.eliminated: List[Dict[str, Any]] = []
        self.artifacts: Dict[str, Artifact] = {}
        self.pending_events: List[RuntimeSignal] = []
        self.internal: Dict[str, Any] = {}
        # P0 底座协议运行时状态
        self.agent_locations: Dict[str, str] = {}           # agent_id -> location_id
        self.resources: Dict[str, Dict[str, float]] = {}    # agent_id -> {resource_id: current}
        self.cooldowns: Dict[str, Dict[str, int]] = {}      # agent_id -> {entity_id: remaining}
        self.permissions: Dict[str, List[str]] = {}         # agent_id -> [permission_id]
        self.relationships: Dict[str, Any] = {}             # 关系状态引用


class WorldStateKernel:
    """
    L1 世界状态内核。

    铁律：模型不能直接改世界——所有状态变更必须通过因果物理管线。
    本层提供：
    - 状态初始化与推进
    - tick 演化统一驱动（资源/冷却/延迟事件/记忆）
    - 状态变更的唯一合法入口
    - 快照生成（公开信息，无秘密）
    - 事件收集与广播
    """

    def __init__(self):
        self._state: Optional[WorldState] = None
        self._world_objects: Any = None  # WorldObjectRegistry（由 L5 注入）
        self._scene_state: Dict[str, Any] = {}
        # P0/P1 底座服务引用（由 EngineOS 注入）
        self._resource_service: Any = None
        self._cooldown_service: Any = None
        self._delayed_effect: Any = None
        self._memory_service: Any = None
        self._evaluation_engine: Any = None  # L5，用于能力衰减

    @property
    def state(self) -> Optional[WorldState]:
        return self._state

    def set_platform_services(
        self,
        resource_service: Any = None,
        cooldown_service: Any = None,
        delayed_effect: Any = None,
        memory_service: Any = None,
        evaluation_engine: Any = None,
    ) -> None:
        """注入 P0/P1 底座服务引用（由 EngineOS 调用）"""
        if resource_service is not None:
            self._resource_service = resource_service
        if cooldown_service is not None:
            self._cooldown_service = cooldown_service
        if delayed_effect is not None:
            self._delayed_effect = delayed_effect
        if memory_service is not None:
            self._memory_service = memory_service
        if evaluation_engine is not None:
            self._evaluation_engine = evaluation_engine

    def initialize(self, agent_ids: List[str]) -> WorldState:
        """创建初始世界状态"""
        self._state = WorldState(agent_ids)
        logger.info(f"[L1] WorldState 初始化，Agent 数量: {len(agent_ids)}")
        return self._state

    async def advance_tick(self) -> int:
        """
        推进一个 tick，统一驱动世界演化。

        场景无关：所有演化逻辑通过注入的底座服务执行，
        具体刷新/递减/衰减规则由场景包配置驱动。
        """
        if self._state is None:
            raise RuntimeError("WorldState 未初始化")

        self._state.tick += 1
        self._state.pending_events = []
        tick = self._state.tick

        # 统一驱动 P0/P1 底座服务的 tick 演化
        if self._resource_service:
            self._resource_service.set_tick(tick)
            self._resource_service.refresh_all()
        if self._cooldown_service:
            self._cooldown_service.decrement_all()
        if self._delayed_effect:
            try:
                await self._delayed_effect.process_due_events(tick)
            except Exception as e:
                logger.warning(f"[L1] 延迟事件处理异常: {e}")
        if self._memory_service:
            self._memory_service.mark_stale(tick)
        if self._evaluation_engine:
            self._evaluation_engine.advance_tick(tick)

        # 感知层必须看到本 Tick 刷新/递减后的资源和冷却，而不是上一 Tick 的镜像。
        self.sync_runtime_state()

        return tick

    def sync_runtime_state(self) -> None:
        """tick 结束后将底座服务状态同步到 WorldState"""
        if self._state is None:
            return
        if self._resource_service:
            for aid in self._state.alive_agent_ids:
                self._state.resources[aid] = self._resource_service.get_all(aid)
        if self._cooldown_service:
            for aid in self._state.alive_agent_ids:
                self._state.cooldowns[aid] = self._cooldown_service.get_status(aid)

    def set_agent_location(self, agent_id: str, location_id: str) -> None:
        """设置 agent 位置的唯一合法入口"""
        if self._state is not None:
            self._state.agent_locations[agent_id] = location_id

    def get_agent_location(self, agent_id: str) -> Optional[str]:
        if self._state is None:
            return None
        return self._state.agent_locations.get(agent_id)

    def set_game_over(self, winner_id: Optional[str] = None) -> None:
        if self._state:
            self._state.is_game_over = True
            self._state.winner_id = winner_id
            self._state.is_running = False

    def set_running(self, running: bool) -> None:
        if self._state:
            self._state.is_running = running

    def add_event(self, event: RuntimeSignal) -> None:
        if self._state:
            self._state.pending_events.append(event)

    def inject_oracle(self, target: str, text: str, agent_ids: List[str]) -> None:
        """向指定 Agent 注入神谕（观察者干预）"""
        if self._state is None:
            return
        oracles = self._state.internal.setdefault("oracles", {})
        targets = agent_ids if target == "all" else [target]
        for t in targets:
            oracles.setdefault(t, []).append(text)

    def bind_world_objects(self, objects_registry: Any) -> None:
        """绑定 WorldObjectRegistry（由 L5 评估层注入）"""
        self._world_objects = objects_registry

    def build_snapshot(
        self,
        agent_snapshots: Optional[List[AgentSnapshot]] = None,
    ) -> WorldSnapshot:
        """构建公开快照供渲染层广播"""
        if self._state is None:
            return WorldSnapshot(tick=0, is_running=False)

        agents = agent_snapshots or []
        world_objects = []
        if self._world_objects and hasattr(self._world_objects, "public_snapshot"):
            world_objects = self._world_objects.public_snapshot()

        # Agent 指标数据（从 internal.metrics 提取）
        agent_metrics = {}
        raw_metrics = getattr(self._state, "internal", {}).get("metrics", {})
        if raw_metrics and agent_snapshots:
            for snap in agent_snapshots:
                aid = snap.agent_id
                if aid in raw_metrics:
                    agent_metrics[aid] = dict(raw_metrics[aid])

        return WorldSnapshot(
            tick=self._state.tick,
            is_running=self._state.is_running,
            is_game_over=self._state.is_game_over,
            winner_id=self._state.winner_id,
            agents=agents,
            artifacts=list(self._state.artifacts.values()),
            recent_public_events=[
                e for e in self._state.pending_events if e.is_public
            ],
            world_objects=world_objects,
            scene_state=self._scene_state,
            agent_locations=dict(getattr(self._state, 'agent_locations', {}) or {}),
            agent_metrics=agent_metrics,
            eliminated=list(getattr(self._state, "eliminated", []) or []),
            victory_attribution=list(
                getattr(self._state, "internal", {}).get("victory_attribution", []) or []
            ),
        )

    def set_scene_state(self, key: str, value: Any) -> None:
        """设置场景级公开状态（前端可渲染）"""
        self._scene_state[key] = value

    def get_scene_state(self, key: str, default: Any = None) -> Any:
        return self._scene_state.get(key, default)
