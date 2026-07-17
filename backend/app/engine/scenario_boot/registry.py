"""
L0 Scenario Runtime — 装配好的可运行场景实例

ScenarioRuntime 是 L0 的输出，也是 L1-L6 的服务容器。
它持有场景包的所有静态配置引用，并提供 L1-L6 各层服务的初始化入口。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from app.engine.scenario_boot.loader import LoadedScenario
    from app.engine.scenario_boot.compiler import CompiledScenario

logger = logging.getLogger(__name__)


class ScenarioRuntime:
    """
    装配完成的运行时场景实例。

    职责：
    - 持有场景包静态配置（从 LoadedScenario 转入）
    - 持有 L1-L6 各层服务的运行时实例
    - 提供统一的服务访问接口
    """

    def __init__(self):
        # 静态配置（来自 LoadedScenario）
        self.scenario_name: str = ""
        self.scenario_id: str = ""
        self.scenario_version: str = ""
        self.scenario_dir: str = ""
        self.assets_dir: str = ""
        self.compiled: Any = None

        # L0 原始配置
        self.agent_roles: List[Any] = []
        self.world_config: Dict[str, Any] = {}
        self.objects_cfg: List[Dict[str, Any]] = []
        self.actions_cfg: List[Dict[str, Any]] = []
        self.metrics_cfg: Dict[str, Any] = {}
        self.tools_cfg: List[Dict[str, Any]] = []
        self.audit_cfg: Dict[str, Any] = {}
        self.judge_prompt: str = ""
        self.intro: str = ""
        self.goal_text: str = ""
        self.rule_text: str = ""
        self.vocabulary: Any = None
        self.director_cfg: Dict[str, Any] = {}
        self.presentation: Any = None
        self.world_variables: List[Any] = []
        self.prompt_contract: Dict[str, Any] = {}
        self.visibility_rules: List[Dict[str, Any]] = []
        self.causal_physics_config: Dict[str, Any] = {}
        self.settlement_cfg: Dict[str, Any] = {}
        self.playback_policy: Dict[str, Any] = {}

        # P0 底座协议配置
        self.locations_cfg: List[Dict[str, Any]] = []
        self.resources_cfg: List[Dict[str, Any]] = []
        self.permissions_cfg: Dict[str, Any] = {}
        self.permission_definitions: List[Dict[str, Any]] = []
        self.characters_cfg: List[Dict[str, Any]] = []
        self.assets_manifest: Dict[str, Any] = {}

        # L1 World State
        self.world_state: Any = None  # WorldStateKernel

        # L2 Perception
        self.perception_kernel: Any = None  # PerceptionKernel

        # L3 Agent Runtime
        self.agent_runner: Any = None  # AgentRuntime

        # L4 Action Runtime
        self.action_runtime: Any = None  # ActionRuntime

        # L5 Evaluation & Causal Physics
        self.evaluation_engine: Any = None  # EvaluationEngine

        # L6 Presentation

        # 横切 Trace
        self.trace_recorder: Any = None  # TraceRecorder

        # P0 底座服务
        self.location_registry: Any = None       # LocationRegistry
        self.reachability_service: Any = None    # ReachabilityService
        self.resource_service: Any = None        # ResourceService
        self.cooldown_service: Any = None        # CooldownService
        self.permission_registry: Any = None     # PermissionRegistry
        self.access_control: Any = None          # AccessControlService
        self.precondition_validator: Any = None  # ActionPreconditionValidator
        self.projection_service: Any = None      # PerceptionProjectionService

        # P1 扩展服务
        self.event_bus: Any = None               # EventBus
        self.event_queue: Any = None             # ScheduledEventQueue
        self.delayed_effect: Any = None          # DelayedEffectService
        self.memory_service: Any = None          # MemoryService
        self.relationship_service: Any = None    # RelationshipService
        self.seed_manager: Any = None            # RunSeedManager
        self.replay_recorder: Any = None         # ReplayRecorder

    @classmethod
    def from_compiled(cls, compiled: "CompiledScenario") -> "ScenarioRuntime":
        """从 CompiledScenario 装配 ScenarioRuntime。"""
        scenario = compiled.source
        rt = cls()
        rt.compiled = compiled
        rt.scenario_name = scenario.manifest.name
        rt.scenario_id = scenario.manifest.scenario_id or scenario.manifest.name
        rt.scenario_version = scenario.manifest.version
        rt.scenario_dir = str(scenario.scenario_dir)
        rt.assets_dir = str(scenario.assets_dir)

        # 静态配置转移
        rt.agent_roles = list(scenario.agent_roles)
        rt.world_config = dict(scenario.world_config)
        rt.objects_cfg = list(scenario.objects_cfg)
        rt.actions_cfg = list(scenario.actions_cfg)
        rt.metrics_cfg = dict(scenario.metrics_cfg)
        rt.tools_cfg = list(scenario.tools_cfg)
        rt.audit_cfg = dict(scenario.audit_cfg)
        rt.judge_prompt = scenario.judge_prompt
        rt.intro = scenario.intro
        rt.goal_text = scenario.goal_text
        rt.rule_text = scenario.rule_text
        rt.vocabulary = scenario.vocabulary
        rt.director_cfg = dict(scenario.director_cfg)
        rt.presentation = scenario.presentation
        rt.world_variables = list(scenario.world_variables)
        rt.prompt_contract = dict(scenario.prompt_contract)
        rt.visibility_rules = list(scenario.visibility_rules)
        rt.causal_physics_config = dict(scenario.causal_physics_config)
        rt.settlement_cfg = dict(scenario.settlement_cfg)
        rt.playback_policy = dict(scenario.playback_policy)

        # P0 底座协议配置转移
        rt.locations_cfg = list(scenario.locations_cfg)
        rt.resources_cfg = list(scenario.resources_cfg)
        rt.permissions_cfg = dict(scenario.permissions_cfg)
        rt.permission_definitions = list(scenario.permission_definitions)
        rt.characters_cfg = list(scenario.characters_cfg)
        rt.assets_manifest = dict(scenario.assets_manifest)

        # P0 底座服务初始化
        rt._init_platform_services()

        logger.info(f"[L0] ScenarioRuntime 装配完成: {rt.scenario_name} v{rt.scenario_version}")
        return rt

    @classmethod
    def from_scenario(cls, scenario: "LoadedScenario") -> "ScenarioRuntime":
        """兼容便捷入口：先编译，再装配。"""
        from app.engine.scenario_boot.compiler import ScenarioCompiler
        return cls.from_compiled(ScenarioCompiler.compile(scenario))

    def get_agent_role(self, agent_id: str) -> Optional[Any]:
        """按 agent_slot_id 查找角色配置"""
        return self.compiled.role_index.get(agent_id) if self.compiled else None

    def get_action_rule(self, action_id: str) -> Dict[str, Any]:
        """按 action_id 查找动作规则"""
        return self.compiled.action_index.get(action_id, {}) if self.compiled else {}

    def get_tool_rule(self, tool_id: str) -> Dict[str, Any]:
        """按 tool_id 查找工具规则（含 type=mcp 等扩展字段）"""
        if not self.compiled or not tool_id:
            return {}
        return dict(self.compiled.tool_index.get(tool_id) or {})

    def fallback_action_id(self) -> str:
        """场景声明的 LLM 失败待命动作 id（来自 audit.fallback_action_id）。

        解析顺序：
        1. audit.yaml 显式声明且动作存在
        2. actions 中 intent=wait 的首个动作
        3. 空字符串（调用方自行降级）
        """
        declared = ""
        if isinstance(self.audit_cfg, dict):
            declared = str(self.audit_cfg.get("fallback_action_id") or "").strip()
        action_ids = {
            str(a.get("id") or "")
            for a in (self.actions_cfg or [])
            if isinstance(a, dict) and a.get("id")
        }
        if declared and declared in action_ids:
            return declared
        for act in self.actions_cfg or []:
            if not isinstance(act, dict):
                continue
            aid = str(act.get("id") or "")
            if aid and str(act.get("intent") or "") == "wait":
                return aid
        return declared

    @property
    def agent_slot_ids(self) -> List[str]:
        """所有角色的 slot_id 列表"""
        return [r.agent_slot_id for r in self.agent_roles]

    def _init_platform_services(self) -> None:
        """初始化 P0/P1 底座服务（由 from_scenario 调用）"""
        # P0-1 地点
        from app.engine.location.registry import LocationRegistry
        from app.engine.location.reachability import ReachabilityService
        self.location_registry = LocationRegistry()
        if self.locations_cfg:
            self.location_registry.load_from_config(self.locations_cfg)
        self.reachability_service = ReachabilityService(self.location_registry)

        # P0-2 资源/冷却
        from app.engine.resource.service import ResourceService
        from app.engine.resource.cooldown import CooldownService
        self.resource_service = ResourceService()
        if self.resources_cfg:
            self.resource_service.load_configs(self.resources_cfg)
        self.cooldown_service = CooldownService()

        # P0-3 权限
        from app.engine.permission.registry import PermissionRegistry
        from app.engine.permission.access import AccessControlService
        self.permission_registry = PermissionRegistry()
        self.access_control = AccessControlService(self.permission_registry)

        # P0-5 前置校验
        from app.engine.action_runtime.precondition import ActionPreconditionValidator
        self.precondition_validator = ActionPreconditionValidator(
            actions_cfg=self.actions_cfg,
            location_registry=self.location_registry,
            resource_service=self.resource_service,
            cooldown_service=self.cooldown_service,
            access_control=self.access_control,
        )

        # P0-4 感知投影
        from app.engine.perception.projection import PerceptionProjectionService
        self.projection_service = PerceptionProjectionService(
            location_registry=self.location_registry,
            reachability=self.reachability_service,
            access_control=self.access_control,
            visibility_rules=self.visibility_rules,
        )

        # P1-1 事件
        from app.engine.event.bus import EventBus
        from app.engine.event.scheduler import ScheduledEventQueue
        from app.engine.event.delayed import DelayedEffectService
        self.event_bus = EventBus()
        self.event_queue = ScheduledEventQueue()
        self.delayed_effect = DelayedEffectService(self.event_queue, self.event_bus)

        # P1-2 记忆
        from app.engine.memory.service import MemoryService
        self.memory_service = MemoryService()

        # P1-3 关系
        from app.engine.relationship.service import RelationshipService
        self.relationship_service = RelationshipService()

        # P1-5 回放
        from app.engine.replay.seed import RunSeedManager
        self.seed_manager = RunSeedManager()

        logger.info("[L0] P0/P1 底座服务初始化完成")
