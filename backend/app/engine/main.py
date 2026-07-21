"""
AI 引擎 OS 层 — 七层架构中枢调度器

替代旧的 FrameworkEngine，将所有层串联起来驱动世界运行：
  L0 ScenarioBootKernel → L1 WorldStateKernel → L2 PerceptionKernel
  → L3 AgentRuntime → L4 ActionRuntime → L5 EvaluationEngine
  → L6 DirectorPlan/RenderCommand → 广播
  横切 TraceRecorder 贯穿所有 tick

对外暴露：start / pause / step / reset / inject_oracle
"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from pathlib import Path
from typing import Any, Callable, Coroutine, Dict, List, Optional, Set

from app.config import FrameworkConfig
from app.core.interfaces import (
    ActionPack,
    AgentLog,
    CausalPipelineResult,
    RuntimeSignal,
    WorldSnapshot,
)
from app.engine.scenario_boot.loader import ScenarioBootKernel, LoadedScenario
from app.engine.scenario_boot.registry import ScenarioRuntime
from app.engine.world_state.kernel import WorldStateKernel
from app.engine.perception.kernel import PerceptionKernel
from app.engine.agent_runtime.runtime import AgentRuntime
from app.engine.action_runtime.runtime import ActionRuntime
from app.engine.evaluation.engine import EvaluationEngine
from app.engine.tick_pipeline import TickContext, TickPipeline
from app.engine.victory.strategy import VictoryStrategy
from app.engine.interaction.protocol import InteractionProtocol
from app.engine.evaluation.opportunity import (
    MeasurementOpportunityCoordinator,
)
from app.engine.presentation.audio_runtime import PresentationAudioRuntime
from app.engine.trace.recorder import TraceRecorder
from app.engine.replay.recorder import ReplayRecorder
from app.engine.presentation_buffer import (
    PresentationBuffer,
    PresentationPlan,
    PresentationSegment,
    TickPackage,
)

logger = logging.getLogger(__name__)

BroadcastCallback = Callable[[str, Dict[str, Any]], Coroutine]
UserSettingsProvider = Callable[[str], tuple[Dict[str, Dict[str, str]], Dict[str, str]]]


def _is_network_fallback(action: Any) -> bool:
    """识别 runtime 因 LLM 失败/超时注入的系统兜底动作。

    优先认 ActionPack.is_system_fallback（系统兜底标记）；旧存档兼容仍检查
    parse_errors 中的 "llm_unavailable:" 前缀。不比具体 action_id——待命动作
    由场景 audit.fallback_action_id 声明。这类动作不应进入拖延/压力惩罚
    链路——agent 没有机会决策。
    """
    if action is None:
        return False
    if bool(getattr(action, "is_system_fallback", False)):
        return True
    for err in getattr(action, "parse_errors", []) or []:
        if isinstance(err, str) and err.startswith("llm_unavailable"):
            return True
    return False


class EngineOS:
    """
    七层 OS 架构中枢调度器。

    WebSocket 层持有此对象，通过 set_broadcast_callback 注入广播函数。
    """

    def __init__(
        self,
        cfg: FrameworkConfig,
        scenario: LoadedScenario,
        *,
        user_settings_provider: Optional[UserSettingsProvider] = None,
    ):
        self._cfg = cfg
        self._loaded = scenario
        # The generic runtime accepts user settings through an injected
        # boundary.  Authentication/storage implementations stay outside the
        # public engine package.
        self._user_settings_provider = user_settings_provider

        # 回合/时钟模型：由场景包 world/clock.yaml 声明，OS 统一算当前阶段。
        # 缺失/单阶段 → 默认同步模型，不注入阶段（等价旧行为）。
        from app.contracts.round_model import load_round_model
        self._round_model = load_round_model(scenario.scenario_dir)

        binding_errors = ScenarioBootKernel.validate_runtime_bindings(
            scenario, [slot.id for slot in cfg.agents]
        )
        if binding_errors:
            from app.core.exceptions import ScenarioLoadError
            raise ScenarioLoadError(
                "场景与模型插槽装配失败:\n- "
                + "\n- ".join(binding_errors)
            )

        # L0: 场景包加载/装配
        self._runtime: ScenarioRuntime = ScenarioBootKernel.assemble(scenario)
        logger.info(
            "[L0] 编译覆盖通过 indexes=%s required_sections=%s",
            self._runtime.compiled.consumption.passed,
            self._runtime.compiled.consumption.required_sections,
        )

        # L1: World State Kernel
        self._world_state = WorldStateKernel()

        # L2: Perception Kernel — 注入 ProjectionService 和场景配置
        self._perception = PerceptionKernel(self._runtime.scenario_name)
        self._perception.set_projection_service(self._runtime.projection_service)
        self._perception.set_action_tool_configs(
            self._runtime.actions_cfg,
            getattr(self._runtime, "tools_cfg", []),
        )

        # L3: Agent Runtime
        self._agent_runtime = AgentRuntime(
            self._runtime,
            cfg.agents,
            strict_mode=cfg.runtime_mode == "benchmark",
            external_turn_timeout_ms=int(
                getattr(cfg.external_agent, "turn_timeout_ms", 120_000)
            ),
        )
        self._user_id: str = ""

        # L4: Action Runtime
        self._action_runtime = ActionRuntime()

        # 失败反馈闭环：上一拍裁决结果（校验拒绝/无效果/反噬的人话原因），
        # 下一拍拼进该 agent 简报的"上一拍复盘"。没有反馈的探索是黑洞——
        # 试错的代价从"一拍消失"变成"一拍学费"，模型才能沿失败梯度调整打法。
        self._last_tick_verdicts: Dict[str, Dict[str, Any]] = {}

        # L5: Evaluation & Causal Physics
        self._evaluation = EvaluationEngine(self._runtime)
        from app.engine.event.ledger import WorldEventLedger
        from app.engine.event.observation import ObservationRuntime
        from app.engine.evaluation.settlement import (
            SettlementRuntime,
            load_scenario_settlement_plugin,
        )

        self._os2_event_ledger = WorldEventLedger()
        self._os2_observations = ObservationRuntime()
        self._os2_settlement = SettlementRuntime(
            load_scenario_settlement_plugin(Path(scenario.scenario_dir)),
            authority_policies=scenario.settlement_cfg,
            observations=self._os2_observations,
        )
        self._last_os2_actions: List[Any] = []
        self._last_os2_observations: List[Any] = []
        self._last_os2_agent_activities: List[Any] = []
        self._last_os2_events: List[Any] = []
        self._last_os2_settlements: List[Any] = []
        self._last_final_os2_settlements: List[Any] = []
        from app.engine.presentation.director_runtime import DirectorRuntime
        self._os2_director = DirectorRuntime(
            getattr(scenario.presentation.render, "bindings", {}) or {},
            scenario.presentation.render,
            getattr(self._runtime.vocabulary, "terminology", {}) or {},
        )
        self._last_os2_director_plan: Optional[Any] = None
        self._tick_pipeline = TickPipeline(self)
        self._victory_strategy = VictoryStrategy()
        self._interaction_protocol = InteractionProtocol()
        self._measurement_opportunities = MeasurementOpportunityCoordinator(
            scenario.measurement_opportunities
        )

        # 合并场景包的导演配置到 director_cfg
        if scenario.director_cfg:
            self._runtime.director_cfg = {**scenario.director_cfg, **self._runtime.director_cfg}

        # 横切: Trace
        self._trace = TraceRecorder(self._runtime.scenario_name)

        # TTS
        self._tts: Any = None
        if cfg.tts.enabled:
            from app.framework.tts_minimax import MinimaxTTS
            tts_runtime = MinimaxTTS(
                voice_id=cfg.tts.voice_id,
                speed=cfg.tts.speed,
                timeout=cfg.tts.timeout_sec,
            )
            if tts_runtime.is_configured:
                self._tts = tts_runtime
                logger.info("[TTS] 导演语音已启用")
            else:
                logger.error(
                    "[TTS] 场景要求导演语音，但缺少 MINIMAX_API_KEY 或 "
                    "MINIMAX_GROUP_ID；本局将明确降级为静默字幕"
                )
        self._presentation_audio = PresentationAudioRuntime(self._tts)

        # L6 初始化 Director
        from app.config import AgentSlotConfig as _SlotCfg
        director_slot = _SlotCfg(
            id="__director__", name="Director",
            provider=cfg.director.provider, model=cfg.director.model,
        )
        from app.providers.registry import build_provider
        director_provider = build_provider(director_slot)
        self._director_provider = director_provider

        self._director_charter = ""
        # P0 简报
        if cfg.agent_briefing.enabled:
            from app.framework.prompting.agent_brief_builder import AgentBriefBuilder
            _goal = self._runtime.goal_text or scenario.manifest.description
            _rules = self._runtime.rule_text
            # 排名公式从场景包 metrics.yaml 的 ranking 块读取（OS 不写死）
            _metrics_cfg = scenario.metrics_cfg if isinstance(scenario.metrics_cfg, dict) else {}
            _ranking_spec = _metrics_cfg.get("ranking") if isinstance(_metrics_cfg.get("ranking"), dict) else {}
            _builder = AgentBriefBuilder(
                goal_text=_goal,
                rule_text=_rules,
                scenario_name=self._runtime.scenario_name,
                output_contract=scenario.prompt_contract,
                ranking_spec=_ranking_spec,
            )
            self._perception.set_brief_builder(_builder)
            # 注入术语表（从 vocabulary 获取，用于翻译英文 ID 为中文名）
            _terminology = getattr(self._runtime.vocabulary, "terminology", {}) or {}
            if _terminology:
                self._perception.set_terminology(_terminology)
            # 注入 AGENT.md 宪章（来自 scenarios/<id>/agents/<aid>/AGENT.md）
            _charters = self._load_agent_charters(scenario)
            if _charters:
                _builder.set_agent_charters(_charters)
                logger.info(f"[EngineOS] 已加载 {len(_charters)} 份角色 AGENT.md")

            # 导演宪章（来自 scenarios/<id>/agents/director/AGENT.md）
            _director_charter = self._load_director_charter(scenario)
            if _director_charter:
                self._director_charter = _director_charter
                logger.info(
                    "[EngineOS] 已加载导演 AGENT.md (%s chars)",
                    len(_director_charter),
                )

        # 沙盒
        from app.sandbox.executor import SandboxExecutor
        self._action_runtime.set_sandbox(SandboxExecutor(cfg.sandbox))

        # 人格进成本曲线：roles.yaml capability_profile.personality → L4
        # （守成者走暗面 secrecy 更贵、锋芒者公开对抗 energy 更省）
        try:
            personalities: Dict[str, Dict[str, str]] = {}
            for role in self._runtime.compiled.role_index.values():
                profile = getattr(role, "capability_profile", {}) or {}
                pers = profile.get("personality")
                slot_id = getattr(role, "agent_slot_id", None)
                if slot_id and isinstance(pers, dict) and pers:
                    personalities[slot_id] = {
                        str(k): str(v) for k, v in pers.items()
                    }
            if personalities:
                self._action_runtime.set_personalities(personalities)
        except Exception as exc:
            logger.warning(f"[EngineOS] 人格成本参数注入失败(不影响运行): {exc}")

        # EvidenceService 注入到 L2（供 build_briefs 获取已知证据）和 L4（供工具产出证据）
        _ev_svc = getattr(self._evaluation.context, "evidence", None)
        if _ev_svc:
            self._action_runtime.set_evidence_service(_ev_svc)
            self._perception.set_evidence_service(_ev_svc)

        # 角色名映射
        self._role_names: Dict[str, str] = {
            r.agent_slot_id: r.display_name
            for r in self._runtime.compiled.role_index.values()
            if r.display_name
        }

        # 通用能力测评：剧情节点协调器（守卫式，无挑战内容时为空列表 → _tick 中 no-op）
        self._capability_coordinators: List[Any] = self._build_capability_coordinators()
        self._capability_result_queue: asyncio.Queue = asyncio.Queue()
        # P0-e（C方案）：当前激活但尚未由主回合答完的挑战协调器
        self._active_challenge_coord: Optional[Any] = None
        self._active_challenge_pending_agents: Set[str] = set()
        self._active_challenge_result: Optional[Any] = None
        # 挑战顺序闸门：保证挑战叙事按 challenge_order 顺序播报
        # ── 若后到挑战 challenge_order > _last_drained + 1，先 hold 住等前序挑战
        # ── 5s 超时强制释放（避免一章卡住所有后续）
        self._held_challenge_batches: List[Dict[str, Any]] = []
        self._last_drained_challenge_order: int = 0
        self._challenge_drain_timeout: float = 3.0  # 排干超时（减少链式延迟）
        self._last_challenge_closed_tick: int = 0
        self._challenge_started_tick: int = 0
        self._challenge_max_alive: int = 3   # 每项挑战最多存活 N 回合，超时强制关门
        # 独答对追踪：记录每个 capability 已经通过的 agent 集合
        # 用于"只有独答对才触发对手削弱"逻辑
        self._challenge_passed_agents: Dict[str, Set[str]] = {}
        # 内容驱动终局：所有挑战落幕的 tick（用于收尾缓冲后终局）
        self._all_challenges_done_tick: Optional[int] = None

        # Trace 初始化
        self._trace.initialize()
        self._diagnostic_dir = (
            Path(self._cfg.log_dir).resolve() / self._trace.run_id
        )
        self._diagnostic_dir.mkdir(parents=True, exist_ok=True)
        self._diagnostic_path = self._diagnostic_dir / "diagnostics.jsonl"
        self._write_run_manifest()
        self._run_log_handler: Optional[logging.Handler] = None
        self._attach_run_logfile()

        # Agent Workspace 初始化：每个 agent 一个独立文件夹
        # 写入宪章（charter.md）+ 准备 CoT 落盘目录
        from app.framework.agent_workspace import (
            AgentWorkspace, AgentWorkspaceRegistry, render_charter
        )
        self._agent_workspaces = AgentWorkspaceRegistry()
        from app.agent_os.sandbox_runtime import AgentSandboxRegistry, SandboxPolicy

        self._agent_sandboxes = AgentSandboxRegistry(
            self._diagnostic_dir / "agent_sandboxes",
            SandboxPolicy(
                backend=str(getattr(self._cfg.sandbox, "process_backend", "auto")),
                allow_network=bool(getattr(self._cfg.sandbox, "allow_network", False)),
                allow_package_install=bool(
                    getattr(self._cfg.sandbox, "allow_package_install", False)
                ),
                command_timeout_sec=float(
                    getattr(self._cfg.sandbox, "process_timeout_sec", 30.0)
                ),
                install_timeout_sec=float(
                    getattr(self._cfg.sandbox, "package_install_timeout_sec", 120.0)
                ),
                max_output_bytes=int(
                    getattr(self._cfg.sandbox, "max_process_output_bytes", 131072)
                ),
            ),
        )
        from app.engine.presentation.director_agent import DirectorAgent
        self._director_sandbox = self._agent_sandboxes.create("os_director")
        self._director_agent = DirectorAgent(
            runtime=self._os2_director,
            provider=self._director_provider,
            sandbox=self._director_sandbox,
            max_attempts=2,
            scene_context=(
                self._director_charter
                + "\n场景导演配置："
                + json.dumps(
                    self._runtime.director_cfg,
                    ensure_ascii=False,
                    default=str,
                )[:6000]
            ),
        )
        self._install_director_scene_skills(scenario)
        self._last_director_harness_trace: Optional[Any] = None
        try:
            self._build_agent_workspaces()
            # 把已建好的 workspaces 挂到 AgentRuntime（用于 prompt 注入 charter + 落盘 CoT）
            self._agent_runtime.set_workspaces(self._agent_workspaces)
        except Exception as exc:
            logger.warning(f"[EngineOS] Agent workspace 初始化失败: {exc}")

        # 运行控制
        self._running = False
        self._intro_sent = False
        self._loop_task: Optional[asyncio.Task] = None
        self._bg_tasks: Set[asyncio.Task] = set()
        self._broadcast: Optional[BroadcastCallback] = None
        self._recent_logs: List[AgentLog] = []
        self._all_logs: List[AgentLog] = []

        # 计算-缓冲模式
        self._buffer: Optional[PresentationBuffer] = None
        self._pending_package: Optional[TickPackage] = None
        self._presentation_archive: List[TickPackage] = []
        self._initial_public_snapshot: Dict[str, Any] = {}
        self._playback_mode = "live"
        self._last_actions: Dict[str, Any] = {}  # 最近 tick 的 ActionPack（供快照提取内心独白）
        playback = scenario.playback_policy or {}
        if isinstance(playback, dict) and playback:
            known_keys = {
                "buffer", "tick_pacing", "buffer_health", "on_warning",
                "on_critical", "on_overflow", "mode", "max_buffer_seconds",
                "skip_empty_ticks",
            }
            unknown = sorted(set(playback) - known_keys)
            if unknown:
                # 场景声明了 OS 不认识的键必须告警——静默忽略曾让场景作者
                # 以为自己的演绎节奏配置生效了，实际一条都没被消费。
                logger.warning(
                    "[EngineOS] playback_policy 含未知配置键，将被忽略：%s"
                    "（支持的键：%s）", unknown, sorted(known_keys),
                )
        buffer_cfg = playback.get("buffer", {}) if isinstance(playback, dict) else {}
        pacing_cfg = playback.get("tick_pacing", {}) if isinstance(playback, dict) else {}
        # 快捷键 mode: compact/live —— 面向实时局的低延迟预设，等价于
        # 手写一组更小的 buffer/tick_pacing 值；显式键优先于预设。
        compact_mode = str(playback.get("mode") or "") in ("compact", "live") \
            if isinstance(playback, dict) else False
        default_tick_ms = 1200 if compact_mode else 2000
        normal_tick_ms = int(
            pacing_cfg.get("normal_tick_duration_ms", default_tick_ms)
            or default_tick_ms
        )
        # max_buffer_seconds：场景用一个数声明"演绎最多滞后现实多少秒"。
        max_buffer_seconds = (
            playback.get("max_buffer_seconds") if isinstance(playback, dict) else None
        )
        # skip_empty_ticks：全员 wait 的拍压缩演绎时长（见 plan 组装处）。
        self._playback_skip_empty_ticks = bool(
            playback.get("skip_empty_ticks") if isinstance(playback, dict) else False
        )

        # ━━ OBS 推流模型配置 ━━
        # startup_buffer_ms: 启动时必须先攒够这么多毫秒的内容才开始播放（用户感知的等待时间）
        # max_buffer_ms:     队列容量上限（后台最多领先这么多毫秒），超出则背压
        # min_delay_ms:      消费过程中缓冲跌破此值则暂停补仓（防止抽干）
        default_startup_ms = 8000 if compact_mode else 30000
        default_max_ms = 30000 if compact_mode else 90000
        if max_buffer_seconds is not None:
            try:
                default_max_ms = max(2000, int(float(max_buffer_seconds) * 1000))
                default_startup_ms = min(default_startup_ms, default_max_ms // 2)
            except (TypeError, ValueError):
                pass
        self._startup_buffer_ms = max(
            0, int(buffer_cfg.get("startup_buffer_ms", default_startup_ms)
                   or default_startup_ms)
        )
        self._max_buffer_ms = max(
            self._startup_buffer_ms,
            int(buffer_cfg.get("max_buffer_ms", default_max_ms) or default_max_ms),
        )
        self._resume_buffer_ms = max(
            0, int(buffer_cfg.get("min_delay_ms", 8000 if not compact_mode else 3000)
                   or (8000 if not compact_mode else 3000))
        )
        # 队列 tick 数量上限（按最快可能 tick 时长推算，给足余量）
        # 真实背压由 max_buffer_ms 时长制控制
        self._buffer_max_ticks = max(
            8, min(128, int(round(self._max_buffer_ms / max(normal_tick_ms, 1) * 1.5)))
        )
        self._min_tick_duration = max(0.1, normal_tick_ms / 1000.0)
        # 兼容旧字段（弃用，保留避免 KeyError）
        self._startup_buffer_ticks = max(
            0, int(buffer_cfg.get("startup_ticks", 0) or 0)
        )
        self._playout_delay_ms = max(
            0, int(buffer_cfg.get("playout_delay_ms", 0) or 0)
        )
        health_cfg = playback.get("buffer_health", {}) if isinstance(playback, dict) else {}
        self._buffer_health_thresholds = {
            "excellent": health_cfg.get("excellent_threshold_ms", 0),
            "good": health_cfg.get("good_threshold_ms", 0),
            "warning": health_cfg.get("warning_threshold_ms", 0),
            "critical": health_cfg.get("critical_threshold_ms", 0),
            "empty": health_cfg.get("empty_threshold_ms", 0),
        }
        self._buffer_health_thresholds = {
            key: int(value)
            for key, value in self._buffer_health_thresholds.items()
            if value is not None
        }
        self._buffer_speed_policy = {
            "warning": float((playback.get("on_warning", {}) or {}).get("playback_speed", 0.8)),
            "critical": float((playback.get("on_critical", {}) or {}).get("playback_speed", 0.55)),
            "overflow": float((playback.get("on_overflow", {}) or {}).get("playback_speed", 1.15)),
        }

        # 将 EvaluationEngine 和 TraceRecorder 注入 ScenarioRuntime
        self._runtime.evaluation_engine = self._evaluation
        self._runtime.trace_recorder = self._trace

        # P0/P1 底座服务便捷引用（已在 ScenarioRuntime._init_platform_services 中初始化）
        self._location_registry = self._runtime.location_registry
        self._reachability = self._runtime.reachability_service
        self._resource_service = self._runtime.resource_service
        self._cooldown_service = self._runtime.cooldown_service
        self._permission_registry = self._runtime.permission_registry
        self._access_control = self._runtime.access_control
        self._precondition_validator = self._runtime.precondition_validator
        self._projection_service = self._runtime.projection_service
        self._event_bus = self._runtime.event_bus
        self._event_queue = self._runtime.event_queue
        self._delayed_effect = self._runtime.delayed_effect
        self._memory_service = self._runtime.memory_service
        self._relationship_service = self._runtime.relationship_service

        # L1 注入底座服务（统一驱动世界演化）
        self._world_state.set_platform_services(
            resource_service=self._resource_service,
            cooldown_service=self._cooldown_service,
            delayed_effect=self._delayed_effect,
            memory_service=self._memory_service,
            evaluation_engine=self._evaluation,
        )
        if cfg.random_seed is not None:
            from app.engine.replay.seed import RunSeedManager
            self._runtime.seed_manager = RunSeedManager(cfg.random_seed)
        self._seed_manager = self._runtime.seed_manager

        # P1-5 回放记录器
        run_id = self._trace.run_id
        self._replay_recorder = ReplayRecorder(
            run_id=run_id,
            seed=self._seed_manager.seed,
            scenario_version=self._runtime.scenario_version,
        )
        self._runtime.replay_recorder = self._replay_recorder

        export_base = str(Path(cfg.log_dir).resolve())
        self._trace.configure_run(
            export_base_dir=export_base,
            scenario_version=self._runtime.scenario_version,
            random_seed=self._seed_manager.seed,
            scenario_config={
                "scenario_name": self._runtime.scenario_name,
                "scenario_version": self._runtime.scenario_version,
                "audit": self._runtime.audit_cfg,
                "actions": self._runtime.actions_cfg,
                "metrics": self._runtime.metrics_cfg,
                "settlement": self._runtime.settlement_cfg,
                "compilation": self.get_compilation_report(),
            },
            agent_models={
                slot.id: {
                    "provider": slot.provider,
                    "model": slot.model,
                }
                for slot in cfg.agents
            },
        )

    def set_broadcast_callback(self, cb: BroadcastCallback) -> None:
        self._broadcast = cb

    @property
    def state(self):
        return self._world_state.state

    @property
    def scenario_definition(self) -> LoadedScenario:
        """只读场景定义，供 API 序列化使用。"""
        return self._loaded

    def get_compilation_report(self) -> Dict[str, Any]:
        compiled = self._runtime.compiled
        return {
            "indexes": {
                "roles": len(compiled.role_index),
                "actions": len(compiled.action_index),
                "objects": len(compiled.object_index),
                "tools": len(compiled.tool_index),
                "locations": len(compiled.location_index),
                "resources": len(compiled.resource_index),
                "metrics": len(compiled.metric_index),
            },
            "consumption": compiled.consumption.model_dump(),
            "measurement": compiled.measurement.model_dump(),
        }

    def get_director_capabilities(self) -> List[str]:
        """Return scene-installed Director skills without exposing sandbox internals."""
        sandbox = getattr(self, "_director_sandbox", None)
        if sandbox is None:
            return []
        return list(sandbox.list_capabilities())

    @property
    def scenario_directory_name(self) -> str:
        return self._loaded.scenario_dir.name

    @property
    def run_id(self) -> str:
        return self._trace.run_id

    def set_user_context(self, user_id: str) -> None:
        """绑定账户 ID，供外部 Agent 令牌/Provider 使用。"""
        self._user_id = user_id
        self._agent_runtime.set_user_context(
            user_id,
            external_turn_timeout_ms=int(
                getattr(self._cfg.external_agent, "turn_timeout_ms", 120_000)
            ),
        )
        try:
            from app.agent_gateway.token_store import get_token_store
            get_token_store().bind_run_id(user_id, self._trace.run_id)
        except Exception as exc:
            logger.warning("[EngineOS] bind_run_id 失败: %s", exc)

    def get_runtime_config(self) -> Dict[str, Any]:
        """返回脱敏后的运行配置视图。"""
        from app.agent_gateway.session_bus import get_session_bus
        from app.agent_gateway.token_store import get_token_store

        bus = get_session_bus()
        store = get_token_store()
        agents_out = []
        for slot in self._cfg.agents:
            item = {
                "id": slot.id,
                "name": slot.name,
                "provider": slot.provider,
                "model": slot.model,
                "color": slot.color,
                "driver": str(getattr(slot, "driver", "llm") or "llm"),
            }
            if self._user_id:
                item["external_status"] = bus.connection_status(self._user_id, slot.id)
                rec = store.get_by_slot(self._user_id, slot.id)
                if rec:
                    item["has_join_token"] = True
                    item["slot_token"] = rec.slot_token
            agents_out.append(item)
        return {
            "scenario_name": self.scenario_directory_name,
            "tick_interval_sec": self._cfg.tick_interval_sec,
            "agent_timeout_sec": self._cfg.agent_timeout_sec,
            "director_enabled": self._cfg.director.enabled,
            "agents": agents_out,
        }

    def get_operator_schema(self) -> Dict[str, Any]:
        """Build the operator UI contract entirely from the loaded scene."""
        scenario = self._loaded
        metrics = list((scenario.metrics_cfg or {}).get("metrics", []) or [])
        authority_labels = {
            "simulation": "模拟世界规则",
            "external_reality": "外部真实数据",
            "deterministic_verifier": "确定性验证器",
            "hybrid": "真实数据 + 确定性规则",
        }
        providers = []
        for item in (scenario.settlement_cfg or {}).get("providers", []) or []:
            if not isinstance(item, dict):
                continue
            mode = str(item.get("authority") or item.get("mode") or "")
            providers.append({
                **item,
                "mode": mode,
                "label": authority_labels.get(mode, mode),
            })
        adapter_cfg = dict(
            getattr(scenario, "world_adapter_cfg", {}) or {}
        )
        world_adapter_id = str(adapter_cfg.get("adapter_id") or "")
        if not world_adapter_id:
            execution_cfg = dict(
                (scenario.settlement_cfg or {}).get("execution", {}) or {}
            )
            declared_routes = [
                dict(execution_cfg.get("default", {}) or {}),
                *[
                    dict(item or {})
                    for item in dict(
                        execution_cfg.get("routes", {}) or {}
                    ).values()
                ],
            ]
            world_adapter_id = next((
                str(route.get("world_adapter_id") or "")
                for route in declared_routes
                if route.get("world_adapter_id")
            ), "")
        world_model_kind = str(adapter_cfg.get("model_kind") or "")
        world_adapter_capabilities: List[str] = []
        if world_adapter_id == "builtin:ruleworld_physics":
            world_model_kind = world_model_kind or "rule_based"
        elif world_adapter_id:
            try:
                from app.engine.world_adapter import (
                    get_world_adapter_descriptor,
                )
                descriptor = get_world_adapter_descriptor(world_adapter_id)
                world_model_kind = world_model_kind or descriptor.model_kind
                world_adapter_capabilities = sorted(descriptor.capabilities)
            except ValueError:
                # Scenario compilation remains the strict validation gate.
                pass
        return {
            "scenario": {
                "id": scenario.manifest.scenario_id,
                "name": scenario.manifest.name,
                "description": scenario.manifest.description,
            },
            "metrics": [{
                "id": str(item.get("id") or item.get("metric_id") or ""),
                "label": str(item.get("name") or item.get("id") or ""),
                "min": item.get("min", 0),
                "max": item.get("max", 100),
                "risk": bool(item.get("risk", False)),
                "description": str(item.get("description") or item.get("meaning") or ""),
            } for item in metrics],
            "resources": [{
                "id": str(item.get("id") or item.get("resource_id") or ""),
                "label": str(item.get("name") or item.get("label")
                             or item.get("id") or ""),
            } for item in scenario.resources_cfg],
            "actions": [{
                "id": str(item.get("id") or ""),
                "label": str(item.get("name") or item.get("label")
                             or item.get("id") or ""),
                "category": str(item.get("category") or item.get("intent") or ""),
            } for item in scenario.actions_cfg],
            "settlement_providers": providers,
            "execution": dict(
                (scenario.settlement_cfg or {}).get("execution", {}) or {}
            ),
            "world_adapter": {
                "adapter_id": world_adapter_id,
                "model_kind": world_model_kind,
                "capabilities": world_adapter_capabilities,
                "configured": bool(adapter_cfg),
            },
            "victory": dict(
                (scenario.settlement_cfg or {}).get("victory", {}) or {}
            ),
            "display_values": dict(
                (scenario.settlement_cfg or {}).get("display_values", {}) or {}
            ),
            "observations": list(
                (scenario.settlement_cfg or {}).get("observations", []) or []
            ),
            "operator_trace": dict(
                (scenario.settlement_cfg or {}).get("operator_trace", {}) or {}
            ),
            "terminology": {
                "participant": "Agent",
                "round": "世界回合",
                "result": "结算结果",
            },
        }

    def _scene_execution_route(self, action_id: str) -> Dict[str, Any]:
        """Read an action's execution owner directly from the loaded scene."""
        scene = getattr(self, "_loaded", None)
        config = dict(getattr(scene, "settlement_cfg", {}) or {})
        if not config:
            config = dict(
                getattr(getattr(self, "_runtime", None), "settlement_cfg", {})
                or {}
            )
        execution = dict(config.get("execution", {}) or {})
        route = dict(
            (execution.get("routes", {}) or {}).get(action_id)
            or execution.get("default", {})
            or {}
        )
        if not route.get("mode") or not route.get("provider_id"):
            raise RuntimeError(f"scene execution route missing: {action_id}")
        route["action_id"] = action_id
        return route

    def _scene_action_rule(self, action_id: str) -> Dict[str, Any]:
        """Read an action declaration without depending on a concrete runtime.

        ScenarioRuntime normally serves the compiled action index. Keeping the
        list fallback here also supports minimal runtimes used by replay,
        settlement verification and future scene adapters.
        """
        runtime = getattr(self, "_runtime", None)
        getter = getattr(runtime, "get_action_rule", None)
        if callable(getter):
            return dict(getter(action_id) or {})
        for item in getattr(runtime, "actions_cfg", []) or []:
            if (
                isinstance(item, dict)
                and str(item.get("id") or "") == str(action_id or "")
            ):
                return dict(item)
        return {}

    def _scene_action_rules(self) -> List[Dict[str, Any]]:
        """Return scene-declared action rules without interpreting the domain."""
        runtime = getattr(self, "_runtime", None)
        return [
            dict(item) for item in getattr(runtime, "actions_cfg", []) or []
            if isinstance(item, dict) and item.get("id")
        ]

    def _detect_declared_followup_intent(self, action: Any) -> Optional[Dict[str, Any]]:
        """Detect an unexecuted scene-declared intent from public action text.

        The OS does not know what "buy", "ally", or "deploy" means. A scene may
        mark actions with followup_when_mentioned and provide aliases. If a
        model's public text names such an action but submits another action,
        the next tick receives a pending-intent reminder.
        """
        if action is None:
            return None
        actual_id = str(getattr(action, "action_id", "") or "")
        text = "\n".join(
            str(getattr(action, field, "") or "")
            for field in (
                "text", "plan", "expected_effect", "backup_plan",
                "public_reasoning_summary", "character_monologue",
                "declared_intent", "note_to_self",
            )
        ).lower()
        if not text.strip():
            return None
        for rule in self._scene_action_rules():
            if not rule.get("followup_when_mentioned"):
                continue
            candidate_id = str(rule.get("id") or "")
            if not candidate_id or candidate_id == actual_id:
                continue
            labels = [
                candidate_id,
                str(rule.get("name") or ""),
                *[str(item) for item in (rule.get("intent_aliases") or [])],
            ]
            labels = [item.strip().lower() for item in labels if item and item.strip()]
            if any(label in text for label in labels):
                return {
                    "action_id": candidate_id,
                    "action_name": str(rule.get("name") or candidate_id),
                    "category": str(rule.get("category") or ""),
                    "target_kind": str(rule.get("target_kind") or ""),
                    "submitted_action_id": actual_id,
                    "submitted_action_name": str(
                        getattr(action, "action_name", "") or actual_id
                    ),
                    "reason": "model_declared_but_submitted_different_action",
                }
        return None

    def _update_pending_action_intents(
        self,
        *,
        state: Any,
        tick: int,
        actions: Dict[str, Any],
        valid_actions: Dict[str, Any],
        settlements: List[Any],
    ) -> None:
        pending_root = state.internal.setdefault("pending_action_intents", {})
        # Agent turns are collected concurrently. Preserve a stable per-tick
        # commit order so facts and replay do not depend on coroutine timing.
        for agent_id in sorted((actions or {}), key=str):
            action = (actions or {}).get(agent_id)
            if action is None:
                continue
            actual_id = str(getattr(action, "action_id", "") or "")
            existing = [
                item for item in list(pending_root.get(agent_id, []) or [])
                if int(item.get("expires_tick", tick) or tick) >= tick
                and str(item.get("action_id") or "") != actual_id
            ]
            pending_root[agent_id] = existing
            detected = self._detect_declared_followup_intent(action)
            if detected:
                detected.update({
                    "tick": tick,
                    "expires_tick": tick + 3,
                    "source": "model_public_output",
                    "message": (
                        f"你上一回合表达了“{detected['action_name']}”意图，"
                        f"但最终提交的是“{detected['submitted_action_name']}”。"
                    ),
                })
                pending_root.setdefault(agent_id, []).append(detected)

        for record in settlements or []:
            outcome = str(getattr(record, "outcome", "") or "")
            for agent_id in list(getattr(record, "subject_ids", []) or []):
                source_action = next(
                    (
                        action for aid, action in (valid_actions or {}).items()
                        if str(aid) == str(agent_id)
                    ),
                    None,
                )
                if source_action is None:
                    continue
                action_rule = self._scene_action_rule(
                    str(getattr(source_action, "action_id", "") or "")
                )
                followup_outcomes = {
                    str(item)
                    for item in (action_rule.get("followup_on_settlement_outcomes") or [])
                    if str(item)
                }
                if outcome not in followup_outcomes:
                    continue
                pending_root.setdefault(str(agent_id), []).append({
                    "tick": tick,
                    "expires_tick": tick + 3,
                    "action_id": str(getattr(source_action, "action_id", "") or ""),
                    "action_name": str(
                        action_rule.get("name")
                        or getattr(source_action, "action_name", "")
                        or getattr(source_action, "action_id", "")
                    ),
                    "submitted_action_id": str(
                        getattr(source_action, "action_id", "") or ""
                    ),
                    "submitted_action_name": str(
                        action_rule.get("name")
                        or getattr(source_action, "action_name", "")
                        or getattr(source_action, "action_id", "")
                    ),
                    "source": "settlement_rejection",
                    "reason": outcome or "rejected",
                    "message": str(getattr(record, "explanation", "") or "上一回合行动未完成结算。"),
                })

    def _current_round_phase(self, tick: int) -> Dict[str, Any]:
        """当前回合阶段（由 RoundModel 统一算，取代插件取模）。

        多阶段循环：返回当前阶段 flags（如 tradable）。
        单阶段模型：同样返回该阶段 flags，便于实时窗叠加。
        live_window 按**当前墙钟**判定：盘前开局后，到开盘即可交易；
        午休/收盘强制 tradable=false。与开局时刻无关。
        """
        rm = getattr(self, "_round_model", None)
        base: Dict[str, Any] = {}
        if rm is not None and rm.phases:
            phase = rm.phase_for_tick(tick) if len(rm.phases) > 1 else rm.phases[0]
            if phase is not None:
                base = {
                    **dict(phase.flags),
                    "id": phase.id,
                    "name": phase.name,
                    "description": phase.description,
                    "cycle": rm.cycle_for_tick(tick) if len(rm.phases) > 1 else 0,
                    "cycle_label": rm.cycle_label or "周期",
                }
        cfg = getattr(self, "_cfg", None)
        if rm is not None and str(getattr(cfg, "runtime_mode", "story")) == "replay":
            # Deterministic offline fixtures provide their own historical market
            # phase. Replay must not depend on the host wall clock or weekday.
            base["live_window_open"] = True
            if "tradable" not in base:
                base["tradable"] = True
        elif rm is not None:
            is_open, closed_reason = rm.live_window.is_open()
            base["live_window_open"] = bool(is_open)
            if not is_open:
                base["tradable"] = False
                base["live_window_closed_reason"] = closed_reason
                # Do not expose a generic continuous-trading label while the
                # scenario's authoritative live window is closed.
                base["name"] = "研究与观望"
                base["description"] = (
                    f"当前不可交易：{closed_reason}。可继续研究、核验数据和制定计划；"
                    "仅在交易窗口开放后才可提交可成交订单。"
                )
                # Do not leave the scenario's generic "continuous trading"
                # label visible when its authoritative live window is closed.
                # It made agents (and viewers) believe an order could fill.
                base["name"] = "研究与观望"
                base["description"] = (
                    f"当前不可交易：{closed_reason}。可继续研究、核验数据和制定计划；"
                    "仅在交易窗口开放后才可提交可成交订单。"
                )
            elif "tradable" not in base:
                # 未声明阶段 flags 时，窗口开放即视为可交易
                base["tradable"] = True
        return base

    def set_tick_interval(self, interval: float) -> float:
        self._cfg.tick_interval_sec = max(1.0, float(interval))
        return self._cfg.tick_interval_sec

    async def synthesize_announcement(self, text: str) -> List[Dict[str, Any]]:
        """使用当前 OS 的导演音色朗读场景包公告。"""
        return await self._presentation_audio.synthesize_text_chunks(text)

    def reconfigure_agent(
        self,
        agent_id: str,
        *,
        provider: str,
        model: str,
        api_key: Optional[str] = None,
    ) -> bool:
        slot = next((s for s in self._cfg.agents if s.id == agent_id), None)
        if slot is None:
            return False
        slot.provider = provider
        slot.model = model
        slot.driver = "llm"
        if api_key:
            slot.api_key_override = api_key
        self._agent_runtime.rebuild_provider(agent_id, slot)
        return True

    def reconfigure_agent_driver(
        self,
        agent_id: str,
        *,
        driver: str,
        provider: Optional[str] = None,
        model: Optional[str] = None,
        api_key: Optional[str] = None,
    ) -> bool:
        slot = next((s for s in self._cfg.agents if s.id == agent_id), None)
        if slot is None:
            return False
        slot.driver = str(driver or "llm").strip().lower()
        if provider:
            slot.provider = provider
        if model:
            slot.model = model
        if api_key:
            slot.api_key_override = api_key
        self._agent_runtime.rebuild_provider(agent_id, slot)
        return True

    def build_public_snapshot(self) -> Dict[str, Any]:
        """构建当前公开快照；API/WS 不需要了解内部状态内核。"""
        return self._collect_snapshot()

    def _display_name(self, agent_id: str) -> str:
        return getattr(self, "_role_names", {}).get(agent_id, agent_id)

    def _scene_narration(self, key: str, default: str, **values: Any) -> str:
        cfg = self._runtime.director_cfg or {}
        if isinstance(cfg.get("director"), dict):
            cfg = cfg["director"]
        templates = cfg.get("runtime_narration", {}) or {}
        template = str(templates.get(key) or default)
        try:
            return template.format(**values)
        except (KeyError, ValueError):
            return default.format(**values)

    def _load_agent_charters(self, scenario: Any) -> Dict[str, str]:
        """读取 scenarios/<id>/agents/<aid>/AGENT.md 渲染到 system prompt。

        每个 agent 一份 markdown 宪章；缺失即跳过（回退到旧 brief 拼装）。
        命名约定：文件夹名 = agent_id，文件名固定 `AGENT.md`。
        """
        charters: Dict[str, str] = {}
        try:
            scenario_dir = getattr(getattr(self, "_loaded", None), "scenario_dir", None)
            if scenario_dir is None:
                scenario_dir = getattr(scenario, "scenario_dir", None)
            if scenario_dir is None:
                return charters
            agents_dir = Path(str(scenario_dir)) / "agents"
            if not agents_dir.is_dir():
                return charters
            for aid in self._agent_runtime.agent_ids:
                charter_path = agents_dir / aid / "AGENT.md"
                if charter_path.is_file():
                    try:
                        charters[aid] = charter_path.read_text(encoding="utf-8")
                    except Exception as exc:
                        logger.warning(f"[EngineOS] 读取 {charter_path} 失败: {exc}")
        except Exception as exc:
            logger.warning(f"[EngineOS] _load_agent_charters 异常: {exc}")
        return charters

    def _install_director_scene_skills(self, scenario: Any) -> None:
        """Load presentation-only Director skills declared by the scene pack."""
        path = Path(scenario.scenario_dir) / "director" / "skills.yaml"
        if not path.is_file():
            return
        try:
            import yaml
            raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            skills = raw.get("skills", raw if isinstance(raw, list) else [])
            for manifest in skills:
                if isinstance(manifest, dict):
                    self._director_agent.install_skill(manifest)
            logger.info("[DirectorAgent] 已加载 %d 个场景导演 Skill", len(skills))
        except Exception as exc:
            raise ValueError(f"director_skill_load_failed:{path}:{exc}") from exc

    def _load_director_charter(self, scenario: Any) -> str:
        """读取 scenarios/<id>/agents/director/AGENT.md → 导演 system prompt 前置。"""
        try:
            scenario_dir = getattr(getattr(self, "_loaded", None), "scenario_dir", None)
            if scenario_dir is None:
                scenario_dir = getattr(scenario, "scenario_dir", None)
            if scenario_dir is None:
                return ""
            path = Path(str(scenario_dir)) / "agents" / "director" / "AGENT.md"
            if path.is_file():
                return path.read_text(encoding="utf-8")
        except Exception as exc:
            logger.warning(f"[EngineOS] 读取 director AGENT.md 异常: {exc}")
        return ""

    # ── 控制接口 ────────────────────────────────────────────────────────

    async def initialize(self) -> None:
        """初始化世界"""
        agent_ids = self._agent_runtime.agent_ids

        # L1: 初始化世界状态
        state = self._world_state.initialize(agent_ids)

        # L5: 初始化评估引擎 + 绑定状态
        self._evaluation.initialize()
        self._evaluation.bind_state(state)

        # P0-a 修复：EvaluationEngine.initialize() 之后 context 才被构造，
        # 所以 EvidenceService 注入必须在这之后做（之前在 __init__ 里做时
        # context 还是 None，action_runtime 拿不到 evidence_service，导致
        # 调查类动作不产证据）。
        _ev_svc = getattr(self._evaluation.context, "evidence", None)
        if _ev_svc:
            self._action_runtime.set_evidence_service(_ev_svc)
            self._perception.set_evidence_service(_ev_svc)
            logger.info("[L5] EvidenceService 已注入 action_runtime/perception")

        # L5: 注入行动评价 LLM Judge（中立第三方裁判，替代常量启发式）
        judge_cfg = getattr(self._cfg, "judge", None)
        if judge_cfg is not None and judge_cfg.enabled:
            if judge_cfg.provider:
                from app.config import AgentSlotConfig as _JSlot
                from app.providers.registry import build_provider as _build
                judge_provider = _build(_JSlot(
                    id="__judge__", name="Judge",
                    provider=judge_cfg.provider, model=judge_cfg.model,
                ))
            else:
                # 留空：复用导演 provider（中立系统模型，非参赛模型）
                judge_provider = self._director_provider
            self._evaluation.set_judge(
                judge_provider,
                timeout=judge_cfg.timeout_seconds,
                temperature=judge_cfg.temperature,
                max_tokens=judge_cfg.max_tokens,
            )

        # L1: 绑定 WorldObjectRegistry 给快照 / 感知。
        # 非 simulation 场景（如资本市场）可能没有 RuleWorldContext，
        # 但仍需把场景包 objects.yaml 暴露给感知层，否则依赖对象目标的行动会被全部滤掉。
        objects_registry = self._evaluation.objects
        if objects_registry is None and self._runtime.objects_cfg:
            from app.framework.ruleworld.objects import WorldObjectRegistry

            objects_registry = WorldObjectRegistry(self._runtime.objects_cfg)
        if objects_registry is not None:
            self._world_state.bind_world_objects(objects_registry)
            if self._evaluation.context is None:
                state.internal["world_objects"] = objects_registry.public_snapshot()

        # Trace: 注册 Agent
        self._trace.set_agents(agent_ids)

        # P0 底座协议：初始化 Agent 运行时状态
        self._init_agent_platform_state(state, agent_ids)

        self._intro_sent = False
        logger.info(f"[EngineOS] 初始化完成，Agent: {agent_ids}")
        self._initial_public_snapshot = self._collect_snapshot()
        await self._broadcast_snapshot()

        # 启动时 Provider 健康检查（异步，不阻塞）
        if self._cfg.provider_health_check:
            await self._check_provider_health()

    async def _mark_simulation_complete(self, reason: str = "game_over") -> None:
        """计算侧已经结束；播放侧可能仍在消费缓冲内容。"""
        if self._buffer:
            self._buffer.mark_source_complete()
        await self._emit("viewer", {
            "type": "simulation_complete",
            "reason": reason,
            "tick": self._world_state.state.tick if self._world_state.state else 0,
            "buffer_size": self._buffer.buffer_size if self._buffer else 0,
            "buffer_ahead_ms": (
                self._buffer.buffered_duration_ms if self._buffer else 0
            ),
        })

    async def _check_provider_health(self) -> None:
        """启动时轻量级检查 Provider 可用性（全部并行，不阻塞启动）"""
        from app.providers.mock import MockProvider
        import asyncio

        async def _check_one(slot: Any) -> None:
            ctx = self._agent_runtime.get_context(slot.id)
            if not ctx or not ctx.provider:
                return
            if isinstance(ctx.provider, MockProvider):
                return
            try:
                await asyncio.wait_for(
                    ctx.provider.complete("test", "回复OK"),
                    timeout=10.0,
                )
                logger.info(f"[EngineOS] Provider 健康检查通过: {slot.provider}/{slot.model}")
            except Exception as e:
                logger.warning(f"[EngineOS] Provider {slot.provider} 健康检查失败: {e}")
                await self._emit("viewer", {
                    "type": "engine_error",
                    "action": "provider_health_check",
                    "error": f"Provider {slot.provider} 健康检查失败: {e}",
                    "tick": 0,
                })

        # 收集所有 provider 并行检查（agent + director 共用同一 provider 时去重）
        seen = set()
        tasks = []
        for slot in self._cfg.agents:
            key = (slot.provider, slot.model)
            if key not in seen:
                seen.add(key)
                tasks.append(_check_one(slot))
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

    def _init_agent_platform_state(self, state: Any, agent_ids: List[str]) -> None:
        """P0/P1: 初始化每个 Agent 的底座运行时状态"""
        # P0-1: Agent 初始位置
        start_locations = self._runtime.permissions_cfg.get("_start_locations", {})
        for aid in agent_ids:
            loc = start_locations.get(aid)
            if not loc:
                role = self._runtime.get_agent_role(aid)
                if role:
                    loc = getattr(role, "start_location", None)
            if loc and self._location_registry and self._location_registry.exists(loc):
                state.agent_locations[aid] = loc

        # P0-2: 初始化资源
        # 演绎模式读 roles.yaml 的 capability_profile.initial_resources 做
        # 按人设的非对称覆盖（甲多影响力/乙多精力/丙多隐秘）；未声明的资源
        # 沿用 resources.yaml 对称基线。
        if self._resource_service:
            for aid in agent_ids:
                overrides = None
                role = self._runtime.get_agent_role(aid)
                if role is not None:
                    profile = getattr(role, "capability_profile", {}) or {}
                    declared = profile.get("initial_resources")
                    if isinstance(declared, dict) and declared:
                        overrides = declared
                self._resource_service.initialize_agent(aid, overrides=overrides)
            # 同步到 WorldState
            for aid in agent_ids:
                state.resources[aid] = self._resource_service.get_all(aid)

        # P0-2: 初始化冷却
        if self._cooldown_service:
            for aid in agent_ids:
                self._cooldown_service.initialize_agent(aid)

        # P0-3: 初始化权限
        if self._permission_registry:
            for aid in agent_ids:
                perms = self._runtime.permissions_cfg.get(aid, [])
                if isinstance(perms, list):
                    self._permission_registry.initialize_agent(aid, perms)
                role = self._runtime.get_agent_role(aid)
                if role and hasattr(role, "permissions") and role.permissions:
                    self._permission_registry.initialize_agent(aid, role.permissions)
                state.permissions[aid] = self._permission_registry.get_permissions(aid)

        # P1-3: 初始化关系
        if self._relationship_service and len(agent_ids) >= 2:
            for i, a in enumerate(agent_ids):
                for b in agent_ids[i+1:]:
                    self._relationship_service.initialize_pair(a, b)

        logger.info(f"[EngineOS] P0/P1 Agent 运行时状态初始化完成")

    async def start(self) -> None:
        # 回放模式：只恢复播出缓冲，绝不重新开局或再次载入 archive。
        if self._playback_mode == "replay":
            if self._buffer:
                self._buffer.resume_playback()
                self._buffer.start_playback()
            return
        # 终局后点「开始」不应静默跳进回放；必须先 reset 再开新局。
        if self._world_state.state and self._world_state.state.is_game_over:
            await self._emit("viewer", {
                "type": "engine_error",
                "action": "start_rejected",
                "error": "本局已结束，请先重置后再开始",
            })
            return
        if self._running:
            return
        # live_window 只约束「此刻能否成交」，不约束开局。
        # 允许盘前开局做研究；到开盘时刻后，每拍按墙钟把 tradable 打开。
        self._playback_mode = "live"
        if self._world_state.state is None:
            await self.initialize()
        if not self._intro_sent:
            # 开场白含 TTS 合成 + 按字数逐帧停留，全程可达 1 分钟以上。
            # 同步 await 会卡死 /control/play 和 WS 命令循环——放后台播，
            # 世界计算与蓄水（startup_buffer_ms）并行推进。
            self._intro_sent = True
            intro_task = asyncio.create_task(self._emit_intro())
            self._bg_tasks.add(intro_task)
            intro_task.add_done_callback(self._bg_tasks.discard)
        self._running = True
        self._world_state.set_running(True)

        # 初始化 buffer（若尚未创建）
        if self._buffer is None:
            self._buffer = PresentationBuffer(
                broadcast_fn=self._emit,
                max_buffer=self._buffer_max_ticks,
                max_buffer_ms=self._max_buffer_ms,
                min_tick_duration=self._min_tick_duration,
                startup_buffer_ms=self._startup_buffer_ms,
                startup_buffer_ticks=self._startup_buffer_ticks,
                resume_buffer_ms=self._resume_buffer_ms,
                health_thresholds=self._buffer_health_thresholds,
                speed_policy=self._buffer_speed_policy,
                playout_delay_ms=self._playout_delay_ms,
            )

        # 播放循环先进入“蓄水等待”，计算循环独立生产 CommittedTick。
        # 达到 startup_buffer_ms 前绝不消费，因此演绎稳定落后真实世界。
        logger.info(
            "[EngineOS] 启动延迟播出流水线 startup=%sms resume=%sms",
            self._startup_buffer_ms,
            self._resume_buffer_ms,
        )
        self._buffer.resume_playback()
        self._buffer.start_playback()

        # 立即返回给控制层；计算在后台持续蓄水，前端收到 playout_status。
        if self._loop_task is None or self._loop_task.done():
            self._loop_task = asyncio.create_task(self._compute_loop())

    async def _emit_intro(self) -> None:
        intro = self._runtime.intro or ""
        if not intro.strip():
            intro = getattr(self._loaded, "background_text", "") or ""
        if not intro.strip():
            return
        from app.contracts.os2 import WorldEvent as OS2WorldEvent

        run_id = self._trace.run_id or "run_pending"
        scenario_id = str(self._runtime.scenario_id or self._runtime.scenario_name)
        event = OS2WorldEvent(
            event_id="event:0:scene_intro",
            run_id=run_id,
            scenario_id=scenario_id,
            world_tick=0,
            event_type="scene_intro",
            origin="system",
            target_ids=list(self._agent_runtime.agent_ids),
            deltas={"source": "scenario_package"},
            visibility="public",
            public_summary=intro,
        )
        self._os2_event_ledger.extend([event])
        state = self._world_state.state
        if state is not None:
            state.internal.setdefault("os2_world_events", []).append(
                event.model_dump(mode="json")
            )
        plan = self._os2_director.build_plan(
            run_id=run_id,
            scenario_id=scenario_id,
            world_tick=0,
            events=[event],
            settlements=[],
        )
        if plan is None:
            raise RuntimeError("scene intro did not produce DirectorPlan")
        if state is not None:
            state.internal.setdefault("os2_director_plans", []).append(
                plan.model_dump(mode="json")
            )
        for segment in self._os2_director.compile_segments(plan):
            await self._emit("viewer", {
                "type": "presentation_segment",
                "tick": 0,
                "segment": {
                    "kind": segment.kind,
                    "duration_ms": segment.duration_ms,
                    "payload": segment.payload,
                },
            })
        for chunk in await self._presentation_audio.synthesize_text_chunks(
            plan.narrative_summary
        ):
            await self._emit("viewer", {
                "type": "narration_chunk",
                "tick": 0,
                "source": "director_plan",
                **chunk,
            })
        logger.info("[EngineOS] 场景开场已通过 OS2 事实链播出")

    async def pause(self) -> None:
        self._running = False
        self._world_state.set_running(False)
        if self._buffer:
            self._buffer.pause_playback()
        if self._playback_mode != "replay":
            await self._broadcast_snapshot()

    async def step(self) -> None:
        if self._playback_mode == "replay":
            if self._buffer:
                await self._buffer.step_one()
            return
        if self._world_state.state is None:
            await self.initialize()
        self._running = False
        await self._tick()
        # 单步模式：直接播放不经过队列
        if self._pending_package and self._buffer:
            self._archive_package(self._pending_package)
            await self._buffer._present_tick(self._pending_package)
            if self._world_state.state and self._world_state.state.is_game_over:
                self._persist_presentation_archive()
            self._pending_package = None
        elif self._pending_package:
            # fallback：无 buffer 时直接广播快照
            self._archive_package(self._pending_package)
            await self._broadcast_snapshot()
            if self._world_state.state and self._world_state.state.is_game_over:
                self._persist_presentation_archive()
            self._pending_package = None

    async def start_replay(self, run_id: Optional[str] = None) -> None:
        """直接播放已固化的表现时间线，不重新执行 Agent 或调用模型。"""
        archive = self._load_presentation_archive(run_id)
        packages = archive.get("packages", [])
        if not packages:
            raise ValueError("没有可回放的演出记录")

        self._running = False
        self._playback_mode = "replay"
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        if self._buffer:
            self._buffer.stop()

        replay_packages = [TickPackage.from_dict(item) for item in packages]
        self._buffer = PresentationBuffer(
            broadcast_fn=self._emit,
            max_buffer=max(1, len(replay_packages)),
            min_tick_duration=self._min_tick_duration,
            startup_buffer_ms=0,
            startup_buffer_ticks=0,
            resume_buffer_ms=0,
            health_thresholds=self._buffer_health_thresholds,
            speed_policy=self._buffer_speed_policy,
            playout_delay_ms=0,
        )
        await self._emit("viewer", {
            "type": "replay_started",
            "run_id": archive.get("run_id", ""),
            "total_ticks": len(replay_packages),
            "initial_snapshot": archive.get(
                "initial_snapshot", self._initial_public_snapshot
            ),
        })
        for package in replay_packages:
            await self._buffer.push(package)
        self._buffer.mark_source_complete()
        self._buffer.start_playback()

    def list_replays(self) -> List[Dict[str, Any]]:
        """列出当前日志目录下可直接播放的已完成 Run。"""
        base = Path(self._cfg.log_dir).resolve()
        items: List[Dict[str, Any]] = []
        if not base.exists():
            return items
        for run_dir in base.iterdir():
            if not run_dir.is_dir() or not run_dir.name.startswith("run_"):
                continue
            timeline = run_dir / "presentation_timeline.json"
            ticks_dir = run_dir / "ticks"
            if not timeline.exists() and not ticks_dir.exists():
                continue
            meta: Dict[str, Any] = {}
            try:
                meta = json.loads((run_dir / "meta.json").read_text(encoding="utf-8"))
            except Exception:
                pass
            items.append({
                "run_id": run_dir.name,
                "scenario": meta.get("scenario_id", ""),
                "started_at": meta.get("started_at"),
                "ended_at": meta.get("ended_at"),
                "has_presentation_timeline": timeline.exists(),
            })
        return sorted(items, key=lambda item: item.get("ended_at") or "", reverse=True)

    def _archive_package(self, package: TickPackage) -> None:
        if any(item.tick == package.tick for item in self._presentation_archive):
            return
        # 保留同一对象，使 30 秒后期窗口中的导演润色/TTS 能进入最终回放档案。
        self._presentation_archive.append(package)

    def _persist_presentation_archive(self) -> Optional[str]:
        run_dir = self._trace.exported_run_dir
        if not run_dir or not self._presentation_archive:
            return None
        target = Path(run_dir) / "presentation_timeline.json"
        target.write_text(
            json.dumps({
                "schema_version": "1.0",
                "run_id": self._trace.run_id,
                "scenario_name": self._runtime.scenario_name,
                "scenario_version": self._runtime.scenario_version,
                "initial_snapshot": self._initial_public_snapshot,
                "packages": [
                    package.to_dict()
                    for package in self._presentation_archive
                ],
            }, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        logger.info("[Replay] 表现时间线已固化: %s", target)
        return str(target)

    def _load_presentation_archive(
        self, run_id: Optional[str] = None
    ) -> Dict[str, Any]:
        if (
            run_id in (None, self._trace.run_id)
            and self._presentation_archive
        ):
            return {
                "run_id": self._trace.run_id,
                "initial_snapshot": self._initial_public_snapshot,
                "packages": [
                    package.to_dict()
                    for package in self._presentation_archive
                ],
            }

        if run_id:
            safe_run_id = Path(run_id).name
            if safe_run_id != run_id or not safe_run_id.startswith("run_"):
                raise ValueError("非法回放 ID")
            run_dir = Path(self._cfg.log_dir).resolve() / safe_run_id
        else:
            replays = self.list_replays()
            if not replays:
                raise ValueError("没有可回放的已完成 Run")
            run_dir = Path(self._cfg.log_dir).resolve() / replays[0]["run_id"]

        timeline = run_dir / "presentation_timeline.json"
        if timeline.exists():
            return json.loads(timeline.read_text(encoding="utf-8"))
        raise ValueError("该 Run 没有 OS2 表现时间线，不能生成可信回放")

    async def reset(self) -> None:
        """重建全部运行时服务，确保新 Run 不继承任何旧账本或对象状态。"""
        self._running = False
        if self._buffer:
            self._buffer.stop()
            self._buffer.clear()
        if self._loop_task and not self._loop_task.done():
            self._loop_task.cancel()
        for task in list(self._bg_tasks):
            if not task.done():
                task.cancel()

        # 先落盘当前账本，再重建引擎，避免已运行 tick 的数据丢失
        if self._world_state.state and self._world_state.state.tick > 0:
            try:
                self._persist_presentation_archive()
                self.force_victory_settlement("user_reset")
            except Exception as exc:
                logger.warning(f"[EngineOS] reset 前落盘失败: {exc}")

        # tick=0 时终局结算不会执行，按局日志 handler 不会被摘除；
        # __init__ 会再挂一个 → 多次 reset 后 root logger 堆积 handler。这里显式摘除。
        self._detach_run_logfile()

        # 外部模拟器可能持有进程、socket 或大量内存。重建引擎前必须关闭，
        # 不能依赖 Python 垃圾回收碰运气释放资源。
        try:
            self._evaluation.close()
        except Exception as exc:
            logger.warning("[EngineOS] world adapter 关闭失败: %s", exc)

        cfg = self._cfg
        loaded = self._loaded
        broadcast = self._broadcast
        preserved_user_id = self._user_id
        self.__init__(
            cfg,
            loaded,
            user_settings_provider=self._user_settings_provider,
        )
        if preserved_user_id:
            provider = self._user_settings_provider
            overrides, secrets = provider(preserved_user_id) if provider else ({}, {})
            for slot in self._cfg.agents:
                ov = overrides.get(slot.id)
                if ov:
                    if ov.get("driver"):
                        slot.driver = str(ov["driver"])
                    if ov.get("provider"):
                        slot.provider = str(ov["provider"])
                    if ov.get("model"):
                        slot.model = str(ov["model"])
                user_key = secrets.get(slot.id)
                if user_key:
                    slot.api_key_override = user_key
                if str(getattr(slot, "driver", "llm")).strip().lower() == "agent":
                    self._agent_runtime.rebuild_provider(slot.id, slot)
            self.set_user_context(preserved_user_id)
        if broadcast:
            self.set_broadcast_callback(broadcast)
        await self.initialize()

    async def inject_oracle(
        self, target: str, text: str,
        effects: Optional[List[Dict[str, Any]]] = None,
    ) -> None:
        """神谕注入：暂存在引擎级队列（开局时的世界状态重建不会冲掉它），
        下一 tick 开头统一落地：Agent 感知 + 导演高光帧 + 结构化效果。"""
        items = getattr(self, "_pending_oracle_items", None)
        if items is None:
            items = []
            self._pending_oracle_items = items
        items.append({
            "target": target, "text": text,
            "effects": list(effects or []),
        })
        logger.info(f"[EngineOS] oracle → {target}: {text[:50]}")

    def _flush_oracle_items(self, tick: int) -> None:
        """Inject oracle perception and queue a trusted OS2 system event."""
        if self._pending_package is None:
            return
        state = self._world_state.state
        if state is None:
            return
        pending = list(getattr(self, "_pending_oracle_items", []) or [])
        if not pending:
            return
        self._pending_oracle_items = []
        # Agent 感知：写入 oracles map，本 tick 稍后 build_briefs 即消费
        agent_ids = self._agent_runtime.agent_ids
        for item in pending:
            self._world_state.inject_oracle(
                item.get("target", "all"), str(item.get("text", "")), agent_ids,
            )
        queued = getattr(self, "_pending_os2_system_events", None)
        if queued is None:
            queued = []
            self._pending_os2_system_events = queued
        for idx, item in enumerate(pending):
            target = item.get("target", "all")
            text = str(item.get("text", "")).strip()
            if not text:
                continue
            effects = list(item.get("effects") or [])
            if target == "all":
                sub = self._scene_narration(
                    "oracle_all_subtitle", "世界发生了一项突发变化"
                )
                narration = self._scene_narration(
                    "oracle_all_narration", "突发变化：{text}", text=text
                )
            else:
                name = self._display_name(target)
                sub = self._scene_narration(
                    "oracle_private_subtitle", "{name}收到一项私人信息", name=name
                )
                narration = self._scene_narration(
                    "oracle_private_narration", "{name}收到私人信息：{text}",
                    name=name, text=text,
                )
            queued.append({
                "event_id": f"event:{tick}:oracle:{idx}",
                "event_type": "oracle_injected",
                "actor_id": target if target != "all" else None,
                "target_ids": (
                    list(self._agent_runtime.agent_ids)
                    if target == "all" else [target]
                ),
                "deltas": {"text": text, "declared_effects": effects},
                "public_summary": narration or sub,
            })

    def _queue_os2_system_event(
        self,
        *,
        event_id: str,
        event_type: str,
        public_summary: str,
        actor_id: Optional[str] = None,
        target_ids: Optional[List[str]] = None,
        deltas: Optional[Dict[str, Any]] = None,
    ) -> None:
        """Queue a system fact for the authoritative OS2 event ledger."""
        queued = getattr(self, "_pending_os2_system_events", None)
        if queued is None:
            queued = []
            self._pending_os2_system_events = queued
        queued.append({
            "event_id": event_id,
            "event_type": event_type,
            "actor_id": actor_id,
            "target_ids": list(target_ids or []),
            "deltas": dict(deltas or {}),
            "public_summary": public_summary,
        })

    # ── 主循环 ──────────────────────────────────────────────────────────

    async def _compute_loop(self) -> None:
        """
        计算循环 — 异步预计算，不阻塞播放。
        
        关键改进：
        1. 不在每次 tick 前广播 tick_computing（避免频繁闪烁）
        2. push 保序并提供背压，已提交 tick 永不丢弃
        3. 计算循环与按时间水位运行的播放循环解耦
        """
        consecutive_failures = 0
        max_consecutive_failures = 3

        rm = getattr(self, "_round_model", None)
        pacing = rm.pacing if rm is not None else None

        while self._running:
            try:
                # 墙钟节拍：实时场景让相邻 tick 起点至少间隔 tick_seconds 真实秒，
                # 使"实时数据"在 tick 之间真正变化。非墙钟场景此段为 no-op。
                if pacing is not None and pacing.is_wall_clock:
                    last = getattr(self, "_last_tick_monotonic", None)
                    if last is not None:
                        wait = pacing.tick_seconds - (time.monotonic() - last)
                        if wait > 0:
                            await asyncio.sleep(wait)
                    if getattr(self, "_run_started_monotonic", None) is None:
                        self._run_started_monotonic = time.monotonic()
                    self._last_tick_monotonic = time.monotonic()

                # 仅在 buffer 低水位时才广播"计算中"（减少闪烁）
                should_notify = self._buffer and self._buffer.buffer_size <= 1
                if should_notify:
                    current_tick = self._world_state.state.tick if self._world_state.state else 0
                    await self._emit("viewer", {
                        "type": "tick_computing",
                        "next_tick": current_tick + 1,
                        "buffer_size": self._buffer.buffer_size if self._buffer else 0,
                    })

                await self._tick()  # 计算（结果存在 self._pending_package）
                consecutive_failures = 0

                # 保序推入 buffer；队列满时由背压暂停计算，绝不丢 Tick。
                if self._pending_package and self._buffer:
                    self._archive_package(self._pending_package)
                    success = await self._buffer.push(self._pending_package)
                    if success:
                        self._pending_package = None

            except Exception as e:
                consecutive_failures += 1
                current_tick = self._world_state.state.tick if self._world_state.state else 0
                logger.error(
                    f"[EngineOS] tick 异常 (连续第 {consecutive_failures} 次): {e}",
                    exc_info=True,
                )
                await self._emit("viewer", {
                    "type": "engine_error", "action": "tick", "error": str(e),
                    "tick": current_tick,
                })

                if consecutive_failures >= max_consecutive_failures:
                    logger.error(
                        f"[EngineOS] 连续 {max_consecutive_failures} 次 tick 失败，引擎停止"
                    )
                    await self._emit("viewer", {
                        "type": "engine_error", "action": "fatal",
                        "error": f"引擎连续失败 {max_consecutive_failures} 次，已停止",
                        "tick": current_tick,
                    })
                    await self._mark_simulation_complete(reason="fatal")
                    self._running = False
                    self._world_state.set_running(False)
                    break

                # 未达到连续失败上限：暂停等待用户 play 恢复
                self._running = False
                self._world_state.set_running(False)
                return  # 退出循环但不 break，用户可通过 play 重新启动

            if self._world_state.state and self._world_state.state.is_game_over:
                await self._mark_simulation_complete(reason="game_over")
                self._persist_presentation_archive()
                self._running = False
                break
            # 注意：不再 sleep tick_interval_sec！节奏由 buffer 背压控制

    def _build_agent_workspaces(self) -> None:
        """为每个角色建立独立 workspace，渲染 charter.md 并注册。

        charter 内容来自场景包 `agents/charter_template.md`；如果场景包没有
        模板文件，则跳过——OS 完全兼容无 charter 场景。
        """
        from app.framework.agent_workspace import (
            AgentWorkspace, render_charter
        )
        # 1. 读模板
        template_path = self._loaded.scenario_dir / "agents" / "charter_template.md"
        if not template_path.is_file():
            logger.info(
                f"[AgentWorkspace] 场景包未提供 charter_template.md，跳过 charter 初始化"
            )
            template_text = ""
        else:
            template_text = template_path.read_text(encoding="utf-8")

        # 2. 收集场景元数据（填模板用）
        scenario_name = self._loaded.manifest.name
        scenario_version = self._loaded.manifest.version
        tick_limit = int(
            (self._runtime.audit_cfg or {}).get("tick_limit", 22)
        )
        locations_count = len(
            getattr(self._loaded.presentation.render, "locations", {}) or {}
        )
        objects_count = len(
            getattr(self._loaded.presentation.render, "objects", {}) or {}
        )

        # 3. 为每个 agent 建 workspace + 写 charter
        # agent 数据来自 compiled.role_index（已合并 framework.yaml + agents/roles.yaml）
        run_dir = self._diagnostic_dir
        role_map = self._runtime.compiled.role_index
        agent_ids = list(role_map.keys())
        id_to_name = {
            aid: getattr(role, "display_name", aid) for aid, role in role_map.items()
        }
        for aid, role in role_map.items():
            name = id_to_name.get(aid, aid)
            others = [
                id_to_name.get(other_id, other_id)
                for other_id in agent_ids if other_id != aid
            ]
            ws = AgentWorkspace(
                run_dir=run_dir, agent_id=aid, agent_name=name,
                long_term_root=Path(self._cfg.persistent_memory_root),
            )
            if template_text:
                hidden = getattr(role, "hidden_goal", "") or ""
                # 注入跨局长期记忆——让 agent 带着过往局的教训进新局
                long_term = ws.read_recent_long_term()
                charter = render_charter(
                    template_text,
                    agent_id=aid,
                    agent_name=name,
                    hidden_goal=hidden,
                    other_agents=others,
                    scenario_name=scenario_name,
                    scenario_version=scenario_version,
                    tick_limit=tick_limit,
                    locations_count=locations_count,
                    objects_count=objects_count,
                    long_term_excerpt=long_term,
                )
                ws.write_charter(charter)
                if long_term:
                    logger.info(
                        f"[AgentWorkspace] {aid} 注入跨局长期记忆 "
                        f"{len(long_term)} 字符"
                    )
            self._agent_workspaces.register(ws)
            self._agent_sandboxes.create(aid)
        self._action_runtime.set_workspace_registry(self._agent_workspaces)
        logger.info(
            f"[AgentWorkspace] 已初始化 {len(agent_ids)} 个 agent 工作区于 {run_dir / 'agents'}"
        )

    def _apply_workspace_code_writes(
        self,
        valid_actions: Dict[str, Any],
        tick: int,
    ) -> None:
        """将 tool_request.workspace_write 写入各 agent 代码工作区（C-PR1）。"""
        if not self._agent_workspaces:
            return
        from app.agent_os.workspace_ops import apply_workspace_writes

        max_bytes = int(getattr(self._cfg.sandbox, "code_workspace_max_bytes", 65536))
        max_files = int(getattr(self._cfg.sandbox, "code_workspace_max_files", 32))
        for agent_id in sorted(valid_actions, key=str):
            action = valid_actions[agent_id]
            if not agent_id:
                continue
            ws = self._agent_workspaces.get(agent_id)
            if ws is None:
                continue
            if isinstance(action, dict):
                tr = action.get("tool_request")
            else:
                tr = getattr(action, "tool_request", None)
            if not isinstance(tr, dict):
                continue
            if not tr.get("workspace_write") and not tr.get("workspace_writes"):
                continue
            written, errors = apply_workspace_writes(
                agent_id,
                tr,
                ws,
                max_bytes=max_bytes,
                max_files=max_files,
            )
            for path in written:
                logger.info(
                    f"[CodeWorkspace] tick={tick} agent={agent_id} wrote {path}"
                )
            for err in errors:
                logger.warning(
                    f"[CodeWorkspace] tick={tick} agent={agent_id} {err}"
                )

    def _build_capability_coordinators(self) -> List[Any]:
        """
        仅在场景清单显式启用 capability_evaluation 时装载能力任务扩展。
        目录存在不等于授权启用，避免场景遗留文件悄悄改变 OS 主循环。
        """
        coordinators: List[Any] = []
        try:
            features = getattr(self._loaded.manifest, "enabled_features", {}) or {}
            if not bool(features.get("capability_evaluation", False)):
                return coordinators
            yaml_files = list(getattr(self._loaded, "challenge_paths", []) or [])
            if not yaml_files:
                return coordinators

            from app.framework.capability import (
                CapabilityNodeCoordinator,
                ChallengeLibrary,
                ProbeExecutor,
            )
            from app.framework.capability.assessment import ProbeToolCall

            def _resolve_provider(agent_id: str):
                ctx = self._agent_runtime.get_context(agent_id)
                if ctx is None or getattr(ctx, "provider", None) is None:
                    raise KeyError(f"no provider for agent {agent_id}")
                return ctx.provider

            async def _execute_probe_tool(probe, call):
                if call.tool_id not in probe.available_tool_ids:
                    return call.model_copy(update={
                        "ok": False,
                        "result": {"error": "tool_not_allowed"},
                    })
                arguments = dict(call.arguments or {})
                code = str(arguments.get("code", "") or "")
                if not code:
                    return call.model_copy(update={
                        "ok": False,
                        "result": {"error": "tool_requires_code"},
                    })
                action = ActionPack(
                    agent_id=probe.agent_id,
                    action_id="capability_probe_tool",
                    attached_tool_id=call.tool_id,
                    code=code,
                    target_object_id=arguments.get("target_object_id"),
                    tool_request={
                        "tool_id": call.tool_id,
                        "arguments": arguments,
                    },
                )
                from app.mcp.tool_executor import resolve_tool_id

                _tid = resolve_tool_id(action)
                _tool_def = (
                    self._runtime.get_tool_rule(_tid)
                    if _tid and self._runtime
                    else {}
                )
                tool_result = await self._action_runtime.execute_tool(
                    action, probe.tick, self._world_state.state,
                    tool_def=_tool_def,
                    runtime_mode=self._cfg.runtime_mode,
                )
                if tool_result is None:
                    return call.model_copy(update={
                        "ok": False,
                        "result": {"error": "tool_not_executed"},
                    })
                return ProbeToolCall(
                    tool_id=call.tool_id,
                    arguments=arguments,
                    result_ref=tool_result.run_id,
                    ok=bool(tool_result.ok),
                    result={
                        "outputs": list(tool_result.outputs or []),
                        "evidence_created": list(
                            tool_result.evidence_created or []
                        ),
                        "errors": list(tool_result.errors or []),
                    },
                )

            probe_executor = ProbeExecutor(
                _resolve_provider,
                timeout_sec=self._cfg.agent_timeout_sec,
                tool_executor=_execute_probe_tool,
                diagnostic_sink=self._write_diagnostic,
            )

            for idx, path in enumerate(yaml_files):
                try:
                    lib = ChallengeLibrary.from_yaml(str(path))
                except Exception as e:
                    logger.warning(f"[CapabilityNode] 装载挑战内容失败 {path.name}: {e}")
                    continue
                # 节点降临时机：按文件顺序错开，避免同 tick 扎堆（可后续移到 YAML 配置）
                node_ids = list(lib._node_index.keys())  # noqa: SLF001 内部索引只读
                for node_id in node_ids:
                    node_meta = lib.node_meta(node_id)
                    fire_tick = int(
                        node_meta.get("fire_tick") or (3 + idx * 4)
                    )
                    # 内生扰动：挑战降临时机 ±1 拍抖动（每局重掷）。世界的
                    # 大事件不再是开局就能背出来的固定日程表——可预测的世界
                    # 里最优策略也可预测。第一项挑战不抖（开局节奏保护），抖动后
                    # 保底 ≥2 防止挤到 tick 0/1。
                    import random as _random
                    if fire_tick > 2:
                        fire_tick = max(2, fire_tick + _random.choice([-1, 0, 0, 1]))
                    coordinators.append(CapabilityNodeCoordinator(
                        library=lib, node_id=node_id,
                        probe_executor=probe_executor,
                        fire_tick=fire_tick,
                        trigger=node_meta.get("trigger", {}),
                        display_name=lambda a: self._role_names.get(a, a),
                    ))
            if coordinators:
                logger.info(
                    f"[CapabilityNode] 已装载 {len(coordinators)} 个剧情节点协调器 "
                    f"(来自 {len(yaml_files)} 个挑战文件)"
                )
        except Exception as e:
            logger.warning(f"[CapabilityNode] 协调器构建异常（降级为无）: {e}")
            return []
        return coordinators

    async def _maybe_run_capability_nodes(
        self,
        tick: int,
        actions: Optional[Dict[str, Any]] = None,
    ) -> Dict[str, List[Any]]:
        """调度到期节点到后台执行，并提交已完成结果；不阻塞世界 Tick。"""
        committed = self._drain_capability_results()
        if not self._capability_coordinators:
            return committed
        state = self._world_state.state
        ordered_pending = sorted(
            (
                c for c in self._capability_coordinators
                if not c.fired and c.challenge_order > 0
            ),
            key=lambda c: c.challenge_order,
        )
        next_ordered = ordered_pending[0] if ordered_pending else None
        due = [
            c for c in self._capability_coordinators
            # 带 challenge_order 的节点必须严格串联，避免高序号挑战提前触发。
            # 可能在第五回合就越过前置剧情，破坏叙事与证据因果。
            if c.challenge_order <= 0 or c is next_ordered
            if c.should_fire(
                tick,
                actions=actions,
                agent_locations=(
                    dict(state.agent_locations) if state is not None else {}
                ),
                last_challenge_closed_tick=self._last_challenge_closed_tick,
            )
        ]
        if not due:
            return committed
        if not self._should_force_challenge_actions():
            for coord in due:
                logger.info(
                    "[CapabilityNode] story mode skips forced challenge "
                    "activation node=%s tick=%s policy=%s",
                    getattr(coord, "node_id", ""),
                    tick,
                    self._challenge_delivery_policy(),
                )
            return committed
        agent_ids = list(self._agent_runtime.agent_ids)
        if not agent_ids:
            return committed

        for coord in due:
            # P0-e（C方案）：每次只允许一个挑战在主回合内被作答，避免多项挑战同时
            # 抢 brief。后到的挑战等当前挑战结束后再激活。
            if self._active_challenge_coord is not None:
                break
            self._activate_challenge(coord, tick)
            self._active_challenge_coord = coord
            self._active_challenge_pending_agents = set(agent_ids)
        await asyncio.sleep(0)
        ready = self._drain_capability_results()
        for key in committed:
            committed[key].extend(ready[key])
        return committed

    def _activate_challenge(self, coord: Any, tick: int) -> None:
        self._challenge_started_tick = tick  # 记录挑战激活时刻（用于超时强制关门）
        current = self._world_state.get_scene_state(
            "current_challenge", {}
        ) or {}
        if current.get("id") == coord.node_id:
            return
        # 推断该挑战考察的能力（取 coord 的首个 probe 的 capability，给导演用）
        capability = ""
        try:
            lib = getattr(coord, "_lib", None)
            if lib:
                node_id = getattr(coord, "node_id", "")
                variants = lib.variants_for(node_id) if node_id else []
                if variants:
                    capability = getattr(variants[0], "capability", "") or ""
        except Exception:
            capability = ""
        prior_recap = "；".join(
            self._challenge_history_summary(exclude_order=coord.challenge_order)
        )
        self._world_state.set_scene_state(
            "current_challenge",
            {
                "id": coord.node_id,
                "title": coord.title,
                "order": coord.challenge_order,
                "sequence_label": self._scene_narration(
                    "challenge_sequence_label",
                    "挑战 {order}",
                    order=coord.challenge_order,
                ),
                "started_tick": tick,
                "capability": capability,
                "just_started": True,        # 导演首句必须点出"揭幕"
                # 挑战因果钩子：前次挑战回响，导演可借此讲"连续剧"而非孤立挑战
                "prior_recap": prior_recap,
            },
        )
        challenge_started_event = RuntimeSignal(
            tick=tick,
            event_type="challenge_started",
            source_id=None,
            is_public=True,
            summary=f"{coord.title}开始，新的争夺目标进入世界。",
            metadata={
                "challenge_id": coord.node_id,
                "challenge_order": coord.challenge_order,
            },
        )
        self._world_state.add_event(challenge_started_event)

        self._queue_os2_system_event(
            event_id=f"event:{tick}:challenge:{coord.node_id}",
            event_type="challenge_started",
            public_summary=challenge_started_event.summary,
            target_ids=[coord.node_id],
            deltas={
                "challenge_id": coord.node_id,
                "challenge_order": coord.challenge_order,
                "title": coord.title,
                "capability": capability,
            },
        )
    def _get_challenge_order(self, batch: Dict[str, Any]) -> int:
        """从 batch 拿到所属挑战的 challenge_order。"""
        node_id = batch.get("node_id", "")
        coord = next(
            (c for c in self._capability_coordinators if c.node_id == node_id),
            None,
        )
        return getattr(coord, "challenge_order", 0) if coord else 0

    def _drain_capability_results(self) -> Dict[str, List[Any]]:
        """在主循环线程提交后台完成的测评结果。
        加挑战顺序闸门：保证挑战叙事按 challenge_order 顺序展示
        （避免高序号挑战先于低序号挑战播出的倒序问题）。
        """
        import time as _time
        result: Dict[str, List[Any]] = {
            "cases": [], "events": []
        }
        state = self._world_state.state
        if state is None:
            return result
        store = state.internal.setdefault("capability_assessment", {
            "cases": [], "events": [],
        })

        # 步骤 1：把队列内未处理的 + 之前 hold 的批次合并
        pending = list(self._held_challenge_batches)
        self._held_challenge_batches = []
        while True:
            try:
                batch = self._capability_result_queue.get_nowait()
            except asyncio.QueueEmpty:
                break
            batch.setdefault("first_seen_at", _time.time())
            pending.append(batch)

        # 步骤 2：按 challenge_order 排序——保证按挑战顺序处理
        pending.sort(key=self._get_challenge_order)

        # 步骤 3：顺序释放；跳号且未超时则 hold
        now = _time.time()
        for batch in pending:
            order = self._get_challenge_order(batch)
            # 无挑战序号（order=0）的任意时刻可放
            if order == 0:
                self._process_capability_batch(batch, store, result)
                continue
            # 等于“上一项挑战 + 1”时按序释放。
            if order <= self._last_drained_challenge_order + 1:
                self._process_capability_batch(batch, store, result)
                self._last_drained_challenge_order = max(
                    self._last_drained_challenge_order, order
                )
                continue
            # 跳号：检查是否超时
            waited = now - float(batch.get("first_seen_at", now))
            if waited >= self._challenge_drain_timeout:
                logger.warning(
                    f"[ChallengeDrain] 挑战 order={order} 等待前序挑战超时 "
                    f"({waited:.1f}s)，强制释放——前序挑战会用模板叙事兜底"
                )
                self._process_capability_batch(batch, store, result)
                self._last_drained_challenge_order = max(
                    self._last_drained_challenge_order, order
                )
            else:
                # 继续 hold
                self._held_challenge_batches.append(batch)

        return result

    def _process_capability_batch(
        self,
        batch: Dict[str, Any],
        store: Dict[str, Any],
        result: Dict[str, List[Any]],
    ) -> None:
        """把一个 batch 真正落到 store + result，并 emit diagnostics。"""
        def _dump_json(item: Any) -> Dict[str, Any]:
            if isinstance(item, dict):
                return item
            return item.model_dump(mode="json")

        batch_cases = [_dump_json(item) for item in batch["cases"]]
        batch_events = []
        for raw_event in batch["events"]:
            if isinstance(raw_event, dict):
                event = RuntimeSignal(**raw_event)
            else:
                event = raw_event
            committed = event
            self._world_state.add_event(committed)
            batch_events.append(committed.model_dump(mode="json"))
        store["cases"].extend(batch_cases)
        store["events"].extend(batch_events)
        for case in batch_cases:
            self._write_diagnostic({
                "event_type": "assessment_case_committed",
                "tick": case.get("tick"),
                "agent_id": case.get("agent_id"),
                "capability": case.get("capability"),
                "case_id": case.get("case_id"),
                "status": case.get("status"),
                "score": case.get("score"),
                "verification": case.get("verification"),
                "world_effect_ref": case.get("world_effect_ref"),
            })
        for event in batch_events:
            self._write_diagnostic({
                "event_type": "assessment_world_event_committed",
                "tick": event.get("tick"),
                "source_id": event.get("source_id"),
                "summary": event.get("summary"),
                "metadata": event.get("metadata"),
            })
        result["cases"].extend(batch_cases)
        result["events"].extend(batch_events)
        # Aggregator 是冗余无害的 —— 每个 batch 处理后都重算一次 profiles，保证渐进式更新
        if result["cases"]:
            from app.framework.capability import GeneralCapabilityAggregator
            store["profiles"] = GeneralCapabilityAggregator().aggregate(
                store["cases"]
            )

    def _attach_run_logfile(self) -> None:
        """给本局接一份独立 runtime 日志 runs/<run_id>/runtime.log。

        与全局 runs/runtime.log 并存：全局文件跨局连续，按局文件只含本局，
        排查某个 run_id 时不必从混写的全局日志里捞。
        """
        try:
            handler = logging.FileHandler(
                self._diagnostic_dir / "runtime.log", encoding="utf-8"
            )
            handler.setFormatter(logging.Formatter(
                "%(asctime)s [%(name)s] %(levelname)s %(message)s"
            ))
            logging.getLogger().addHandler(handler)
            self._run_log_handler = handler
        except Exception as exc:  # 日志接入失败不应阻断引擎启动
            logger.warning(f"[Trace] 按局日志接入失败: {exc}")
            self._run_log_handler = None

    def _detach_run_logfile(self) -> None:
        """收尾时摘除并关闭按局日志 handler，避免句柄泄漏与跨局串写。"""
        handler = self._run_log_handler
        if handler is None:
            return
        try:
            logging.getLogger().removeHandler(handler)
            handler.close()
        except Exception:
            pass
        finally:
            self._run_log_handler = None

    def _write_run_manifest(self) -> None:
        """写入不含密钥的运行清单，方便锁定真实模型、场景和随机种子。"""
        action_labels = {
            str(item.get("id", "") or "").strip(): str(
                item.get("name") or item.get("id") or ""
            )
            for item in (self._runtime.actions_cfg or [])
            if isinstance(item, dict) and str(item.get("id", "") or "").strip()
        }
        metric_labels = self._metric_labels_map()
        interaction_actions = sorted(
            str(item.get("id", "") or "").strip()
            for item in (self._runtime.actions_cfg or [])
            if isinstance(item, dict)
            and str(item.get("id", "") or "").strip()
            and (
                item.get("interaction_role")
                or str(item.get("target_kind", "") or "") == "agent"
            )
        )
        risky_categories = {
            str(item)
            for item in (
                (self._runtime.audit_cfg or {}).get("risky_categories", [])
                if isinstance(self._runtime.audit_cfg, dict)
                else []
            )
            if item
        }
        risk_actions = sorted(
            str(item.get("id", "") or "").strip()
            for item in (self._runtime.actions_cfg or [])
            if isinstance(item, dict)
            and str(item.get("id", "") or "").strip()
            and str(item.get("category", "") or "") in risky_categories
        )
        fallback_aid = str(
            (self._runtime.audit_cfg or {}).get("fallback_action_id") or ""
        ).strip()
        wait_actions = sorted(
            {
                str(item.get("id", "") or "").strip()
                for item in (self._runtime.actions_cfg or [])
                if isinstance(item, dict)
                and str(item.get("id", "") or "").strip()
                and (
                    str(item.get("intent") or "") == "wait"
                    or str(item.get("id") or "").strip() == fallback_aid
                )
            }
        )
        mcp_tool_ids = sorted(
            str(item.get("id") or item.get("tool_id") or "").strip()
            for item in (self._runtime.tools_cfg or [])
            if isinstance(item, dict)
            and str(item.get("type") or "").strip().lower() == "mcp"
            and str(item.get("id") or item.get("tool_id") or "").strip()
        )
        from app.mcp.client import get_mcp_manager

        mcp_mgr = get_mcp_manager()
        manifest = {
            "run_id": self._trace.run_id,
            "created_at": time.time(),
            "scenario": {
                "name": self._runtime.scenario_name,
                "version": self._runtime.scenario_version,
                "path": str(self._loaded.scenario_dir),
            },
            "runtime_mode": self._cfg.runtime_mode,
            "random_seed": self._cfg.random_seed,
            "agent_timeout_sec": self._cfg.agent_timeout_sec,
            "agents": [
                {
                    "id": slot.id,
                    "name": slot.name,
                    "provider": slot.provider,
                    "model": slot.model,
                    "extra_keys": sorted((slot.extra or {}).keys()),
                }
                for slot in self._cfg.agents
            ],
            "director": {
                "enabled": self._cfg.director.enabled,
                "provider": self._cfg.director.provider,
                "model": self._cfg.director.model,
            },
            "judge": {
                "enabled": self._cfg.judge.enabled,
                "provider": self._cfg.judge.provider,
                "model": self._cfg.judge.model,
            },
            "terminology": {
                "action_labels": action_labels,
                "metric_labels": metric_labels,
                "interaction_actions": interaction_actions,
                "risk_actions": risk_actions,
                "wait_actions": wait_actions,
                "fallback_action_id": fallback_aid,
            },
            "tts_enabled": self._tts is not None,
            "agent_os": {
                "mcp_enabled": bool(
                    self._cfg.mcp.enabled
                    and mcp_mgr is not None
                    and mcp_mgr.enabled
                ),
                "mcp_server_ids": list(mcp_mgr.server_ids) if mcp_mgr else [],
                "mcp_tool_ids": mcp_tool_ids,
                "runtime_mode": self._cfg.runtime_mode,
                "loop_enabled": bool(getattr(self._cfg.agent_loop, "enabled", False)),
                "loop_max_steps": int(getattr(self._cfg.agent_loop, "max_steps", 5)),
                "external_agent_slots": [
                    slot.id for slot in self._cfg.agents
                    if str(getattr(slot, "driver", "llm")).strip().lower() == "agent"
                ],
            },
        }
        target = self._diagnostic_dir / "run_manifest.json"
        target.write_text(
            json.dumps(manifest, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )

    def _metric_labels_map(self) -> Dict[str, str]:
        metrics_cfg = self._runtime.metrics_cfg or {}
        metrics = (
            metrics_cfg.get("metrics", [])
            if isinstance(metrics_cfg, dict)
            else []
        )
        labels: Dict[str, str] = {}
        for item in metrics:
            if not isinstance(item, dict):
                continue
            metric_id = str(item.get("id", "") or "").strip()
            if not metric_id:
                continue
            labels[metric_id] = str(item.get("name") or metric_id)
        return labels

    def _write_diagnostic(self, item: Dict[str, Any]) -> None:
        """追加结构化诊断日志；不含API Key，但保留完整模型输出。"""
        record = {
            "run_id": self._trace.run_id,
            "timestamp": time.time(),
            **dict(item),
        }
        with self._diagnostic_path.open("a", encoding="utf-8") as handle:
            handle.write(
                json.dumps(record, ensure_ascii=False, default=str) + "\n"
            )

    def _apply_interaction_metric_delta(
        self,
        *,
        agent_id: str,
        metric: str,
        delta: float,
        source_object_id: Optional[str],
        tick: int,
        linked_action_id: Optional[str],
        reason: str,
    ) -> Optional[Dict[str, Any]]:
        """将角色互动的指标反馈写成 StateDelta + MetricDerivation 证据链。"""
        if not agent_id or not metric or abs(delta) < 0.001:
            return None
        ctx = self._evaluation.context
        if ctx is None or ctx.metrics is None:
            return None

        object_id = source_object_id or ""
        if not object_id:
            matching = [
                rule for rule in getattr(ctx, "_metric_rules", [])
                if rule.get("metric") == metric and rule.get("object_id")
            ]
            if matching:
                object_id = str(matching[0]["object_id"])
        if not object_id:
            logger.warning(
                "[interaction] metric_delta 缺少可落账对象 metric=%s agent=%s",
                metric, agent_id,
            )
            return None

        try:
            world_object = ctx.objects.get(object_id)
        except KeyError:
            logger.warning("[interaction] metric_delta 对象不存在: %s", object_id)
            return None

        factor_name = "core" if "core" in world_object.factors else ""
        if not factor_name:
            factor_name = next(iter(world_object.factors), "")
        if not factor_name:
            logger.warning("[interaction] metric_delta 对象无可写因子: %s", object_id)
            return None

        # 互动的核心指标反馈通常是离散事件收益/惩罚。对象侧只记录一个
        # 小幅可审计扰动，人物指标的实际数值由 MetricDerivation 记录。
        signed = 1.0 if delta > 0 else -1.0
        factor_delta = signed * min(0.05, max(0.01, abs(delta) / 200.0))
        delta_entry = ctx.deltas.apply_delta(
            object_id=object_id,
            factor_deltas={factor_name: factor_delta},
            actor_id=agent_id,
            settlement_rule="agent_interaction_metric",
            cause_chain=[linked_action_id or "agent_interaction"],
            linked_action_id=linked_action_id,
        )
        metric_entry = ctx.metrics.derive(
            agent_id=agent_id,
            metric=metric,
            delta=delta,
            derivation_rule=f"agent_interaction:{object_id}",
            reason=reason,
            source_delta_id=delta_entry.delta_id,
        )
        return {
            "type": "metric_delta",
            "target": agent_id,
            "metric": metric,
            "delta": delta,
            "before": metric_entry.before_value,
            "after": metric_entry.after_value,
            "object_id": object_id,
            "delta_id": delta_entry.delta_id,
            "metric_update_id": metric_entry.metric_update_id,
        }

    def _resolve_interaction_outcome(
        self,
        *,
        result: CausalPipelineResult,
        rule: Dict[str, Any],
    ) -> Optional[Dict[str, Any]]:
        """把角色互动从“动作有效”细分为 success/partial/failed/exposed。"""
        resolution = rule.get("interaction_resolution")
        if not isinstance(resolution, dict):
            return None

        proposal = getattr(result, "proposal", None)
        evaluation = getattr(result, "evaluation", None)
        budget = getattr(result, "budget", None)

        if proposal is None:
            base = 0.7 if result.outcome == "success" else 0.2
            components = {
                "base": base,
                "match": base,
                "quality": base,
                "force": base,
                "impact": base,
                "risk": 0.0,
            }
        else:
            match = max(0.0, min(1.0, float(getattr(proposal, "match_score", 0.0) or 0.0)))
            impact = max(
                abs(float(getattr(proposal, "core_delta", 0.0) or 0.0)) / 10.0,
                float(getattr(proposal, "effective_impact", 0.0) or 0.0) * 10.0,
            )
            impact = max(0.0, min(1.0, impact))
            risk = max(0.0, min(1.0, float(getattr(proposal, "risk_side_effect", 0.0) or 0.0) * 4.0))

            if evaluation is not None:
                quality_values = [
                    float(getattr(evaluation, "clarity", 0.5) or 0.5),
                    float(getattr(evaluation, "execution_quality", 0.5) or 0.5),
                    float(getattr(evaluation, "commitment", 0.5) or 0.5),
                    float(getattr(evaluation, "risk_control", 0.5) or 0.5),
                ]
                quality = max(0.0, min(1.0, sum(quality_values) / len(quality_values)))
            else:
                quality = 0.5

            if budget is not None:
                force_total = sum(
                    abs(float(v)) for v in getattr(budget, "adjusted_force_vector", {}).values()
                )
            elif evaluation is not None:
                force_total = sum(
                    abs(float(v)) for v in getattr(evaluation, "force_vector", {}).values()
                )
            else:
                force_total = 50.0
            force = max(0.0, min(1.0, force_total / 100.0))
            components = {
                "match": match,
                "quality": quality,
                "force": force,
                "impact": impact,
                "risk": risk,
            }

        weights = dict(resolution.get("score_weights") or {})
        if not weights:
            weights = {
                "match": 0.30,
                "quality": 0.25,
                "force": 0.20,
                "impact": 0.20,
                "risk": -0.15,
                "base": 1.0,
            }
        score = 0.0
        used_weight = 0.0
        for key, weight in weights.items():
            if key not in components:
                continue
            weight_f = float(weight)
            score += components[key] * weight_f
            if weight_f > 0:
                used_weight += weight_f
        if used_weight and "base" not in components:
            score = score / used_weight

        if result.outcome == "no_effect":
            score = min(score, float(resolution.get("no_effect_score_cap", 0.34)))
        score = round(max(0.0, min(1.0, score)), 4)

        # 落后者机制（狗急跳墙）：暗策/对抗类动作，排名越靠后判定越宽。
        # 领先者无加成——冒险是给落后者的翻盘窗口，不是给领先者的碾压工具。
        underdog_bonus = 0.0
        if str(rule.get("category", "")) in self._risky_categories():
            underdog_bonus = self._underdog_score_bonus(result.agent_id)
            if underdog_bonus > 0:
                score = round(min(1.0, score + underdog_bonus), 4)

        # 招式疲劳（软引导多样性）：同一 agent 重复使用同一个**预设**暗招，
        # 结算分按 0.7^(N-1) 衰减——世界会对重复的套路产生免疫（被针对的人
        # 有了防备，同一手不可能一直灵）。自由类别动作（is_category_default）
        # 不衰减：每次 plan 内容不同，本来就由裁判现场评分。
        repeat_decay = 1.0
        if (
            str(rule.get("category", "")) in self._risky_categories()
            and not rule.get("is_category_default")
        ):
            state_for_decay = self._world_state.state
            if state_for_decay is not None:
                usage = state_for_decay.internal.setdefault(
                    "dark_action_usage", {}
                )
                key = f"{result.agent_id}:{rule.get('id', '')}"
                prior_uses = int(usage.get(key, 0))
                if prior_uses > 0:
                    repeat_decay = round(0.7 ** prior_uses, 4)
                    score = round(max(0.0, score * repeat_decay), 4)
                usage[key] = prior_uses + 1

        thresholds = dict(resolution.get("thresholds") or {})
        outcome = str(resolution.get("fallback_outcome", "exposed"))
        for name, threshold in (
            ("success", float(thresholds.get("success", 0.65))),
            ("partial", float(thresholds.get("partial", 0.35))),
            ("failed", float(thresholds.get("failed", 0.10))),
        ):
            if score >= threshold:
                outcome = name
                break

        return {
            "type": "interaction_resolution",
            "outcome": outcome,
            "score": score,
            "components": {k: round(float(v), 4) for k, v in components.items()},
            "pipeline_outcome": result.outcome,
            "underdog_bonus": round(underdog_bonus, 4),
            "repeat_decay": repeat_decay,
        }

    def _underdog_score_bonus(self, agent_id: str) -> float:
        """落后者暗策加成：按当前加权综合分排名给分档加成（垫底最多）。

        配置来自 pressure.yaml 的 underdog 段；缺省 last=0.10 / middle=0.05。
        已出局者与领先者均为 0。
        """
        try:
            cfg = {}
            world_config = getattr(self._runtime, "world_config", None) or {}
            pressure_cfg = world_config.get("pressure_cfg") or {}
            if isinstance(pressure_cfg, dict):
                cfg = pressure_cfg.get("underdog", {}) or {}
            bonus_last = float(cfg.get("dark_bonus_last", 0.10))
            bonus_middle = float(cfg.get("dark_bonus_middle", 0.05))

            state = self._world_state.state
            if state is None:
                return 0.0
            eliminated = {
                e.get("agent_id") for e in getattr(state, "eliminated", [])
                if isinstance(e, dict)
            }
            if agent_id in eliminated:
                return 0.0
            metrics_map = state.internal.get("metrics", {}) or {}
            scores = {
                aid: self._weighted_agent_score(mm)
                for aid, mm in metrics_map.items()
                if isinstance(mm, dict) and aid not in eliminated
            }
            if len(scores) < 2 or agent_id not in scores:
                return 0.0
            ordered = sorted(scores, key=lambda a: scores[a], reverse=True)
            pos = ordered.index(agent_id)
            if pos == 0:
                return 0.0
            if pos == len(ordered) - 1:
                return bonus_last
            return bonus_middle
        except Exception:
            return 0.0

    def _interaction_effects_for_outcome(
        self,
        *,
        rule: Dict[str, Any],
        resolution: Optional[Dict[str, Any]],
    ) -> List[Dict[str, Any]]:
        if not resolution:
            return list(rule.get("agent_effects", []) or [])
        cfg = rule.get("interaction_resolution") or {}
        outcomes = cfg.get("outcomes") if isinstance(cfg, dict) else None
        if not isinstance(outcomes, dict):
            return list(rule.get("agent_effects", []) or [])
        outcome_cfg = outcomes.get(resolution.get("outcome"), {})
        if not isinstance(outcome_cfg, dict):
            return []
        return list(outcome_cfg.get("agent_effects", []) or [])

    def _resolve_interaction_object_id(
        self, rule: Dict[str, Any], action: ActionPack,
    ) -> str:
        """暗策类动作的落账对象解析。

        预设招式（如 discredit_rival）走 actions.yaml 里写死的一对一绑定，
        行为不变。自由类别兜底动作（is_category_default=true）没有静态绑定，
        改成读模型自己声明的 target_object_id——但必须是 dark_object_types
        允许的对象类型才生效，防止自由文本随手点名一个无关对象。解析失败
        （没填、类型不对、对象不存在）时返回空字符串，调用方已有优雅降级
        （_apply_interaction_metric_delta 会丢弃这一条 metric_delta，其余
        关系变化/叙事效果照常生效），不需要抛异常。
        """
        static_id = rule.get("interaction_object_id")
        if static_id:
            return str(static_id)
        if not rule.get("is_category_default"):
            return ""
        target_object_id = getattr(action, "target_object_id", None)
        if not target_object_id:
            return ""
        allowed_types = set(rule.get("dark_object_types") or [])
        try:
            obj = self._evaluation.context.objects.get(target_object_id)
        except KeyError:
            return ""
        if allowed_types and obj.type not in allowed_types:
            return ""
        return str(target_object_id)

    def _response_settlement_effects(
        self,
        *,
        response_rule: Dict[str, Any],
        proposal: Dict[str, Any],
    ) -> List[Dict[str, Any]]:
        """读取响应动作的结算效果声明（response_effects.on_settle）。"""
        cfg = response_rule.get("response_effects") or {}
        on_settle = cfg.get("on_settle") if isinstance(cfg, dict) else None
        if not isinstance(on_settle, dict):
            return []
        proposal_action = str(proposal.get("action_id", "") or "")
        proposal_category = str(proposal.get("category", "") or "")
        if proposal_action and isinstance(on_settle.get(proposal_action), list):
            return list(on_settle.get(proposal_action) or [])
        category_key = f"category:{proposal_category}" if proposal_category else ""
        if category_key and isinstance(on_settle.get(category_key), list):
            return list(on_settle.get(category_key) or [])
        return list(on_settle.get("__default__", []) or [])

    def _scaled_metric_delta(
        self,
        *,
        effect: Dict[str, Any],
        proposal: Optional[Dict[str, Any]],
    ) -> float:
        delta = float(effect.get("delta", 0.0) or 0.0)
        if not proposal or not effect.get("scale_from_proposal_outcome"):
            return delta
        scale_map = effect.get("scale_map")
        if not isinstance(scale_map, dict):
            scale_map = {
                "success": 1.0,
                "partial": 0.65,
                "failed": 0.35,
                "exposed": 1.15,
            }
        outcome = str(proposal.get("interaction_outcome", "success") or "success")
        scale = float(scale_map.get(outcome, 1.0) or 1.0)
        return delta * scale

    def _apply_interaction_effect(
        self,
        *,
        effect: Dict[str, Any],
        applied: List[Dict[str, Any]],
        actor_id: str,
        target_id: str,
        rule: Dict[str, Any],
        action: ActionPack,
        result: CausalPipelineResult,
        tick: int,
        proposal: Optional[Dict[str, Any]] = None,
        source_object_id: str = "",
    ) -> None:
        effect_type = str(effect.get("type", ""))
        if effect_type == "relationship" and self._relationship_service:
            relation = str(effect.get("relation", "trust") or "trust")
            delta = float(effect.get("delta", 0.0) or 0.0)
            source = (
                target_id if effect.get("source") == "target"
                else actor_id
            )
            target = (
                actor_id if effect.get("target") == "actor"
                else target_id
            )
            updated = self._relationship_service.update(
                source,
                target,
                relation,
                delta,
                tick=tick,
                source_delta_id=(
                    result.deltas[0].delta_id if result.deltas else None
                ),
            )
            applied.append({
                "type": effect_type,
                "source": source,
                "target": target,
                "relation": relation,
                "delta": delta,
                "after": getattr(updated, "value", None),
            })
            return

        if effect_type == "counterplay":
            level = float(effect.get("level", 0.25) or 0.25)
            target_symbol = str(effect.get("target", "target") or "target")
            cp_target = actor_id if target_symbol == "actor" else target_id
            self._evaluation.context.pressure.signal_counterplay(
                cp_target, level
            )
            applied.append({
                "type": effect_type,
                "target": cp_target,
                "level": level,
            })
            return

        if effect_type == "information_scope":
            delta = float(effect.get("delta", -0.1) or -0.1)
            target_symbol = str(effect.get("target", "target") or "target")
            info_target = target_id if target_symbol == "target" else actor_id
            self._evaluation.context.pressure.update_information_scope(
                info_target, delta
            )
            applied.append({
                "type": effect_type,
                "target": info_target,
                "delta": delta,
            })
            return

        if effect_type == "metric_delta":
            target_symbol = str(effect.get("target", "actor") or "actor")
            targets = (
                [actor_id, target_id]
                if target_symbol == "both"
                else [target_id if target_symbol == "target" else actor_id]
            )
            for metric_target in targets:
                metric_change = self._apply_interaction_metric_delta(
                    agent_id=metric_target,
                    metric=str(effect.get("metric", "")),
                    delta=self._scaled_metric_delta(effect=effect, proposal=proposal),
                    source_object_id=str(
                        effect.get("object_id")
                        or source_object_id
                        or self._resolve_interaction_object_id(rule, action)
                        or ""
                    ),
                    tick=tick,
                    linked_action_id=result.action_id,
                    reason=str(
                        effect.get("narrative")
                        or rule.get("interaction_narrative")
                        or "角色互动触发指标变化。"
                    ),
                )
                if metric_change:
                    applied.append(metric_change)
            return

    def _deliver_conversation_message(
        self,
        *,
        actor_id: str,
        target_id: str,
        action: ActionPack,
        tick: int,
        state: Any,
    ) -> None:
        """converse 消息投递：text 原话进目标下一拍感知；同地点第三人按
        发话者隐蔽度掷点偷听。这是 agent 间第一条自由文本通道——密谋、
        离间、诈降、许诺都需要语言本身，而不是枚举值。"""
        text = str(getattr(action, "text", "") or "").strip()
        if not text:
            return
        text = text[:400]
        inbox: Dict[str, List[Dict[str, Any]]] = state.internal.setdefault(
            "incoming_messages", {}
        )
        inbox.setdefault(target_id, []).append({
            "tick": tick, "from": actor_id, "text": text, "overheard": False,
        })
        inbox[target_id] = inbox[target_id][-8:]
        # 对话全文留档（运营台/复盘可见；不进公开事件流）
        state.internal.setdefault("conversations", []).append({
            "tick": tick, "from": actor_id, "to": target_id, "text": text,
        })
        # 偷听掷点：同地点的其他存活者。发话者 secrecy 越高越不易被听到。
        import random as _random
        locations = getattr(state, "agent_locations", {}) or {}
        actor_loc = locations.get(actor_id)
        secrecy = 50.0
        try:
            secrecy = float(
                (state.resources.get(actor_id) or {}).get("secrecy", 50.0)
            )
        except Exception:
            pass
        overhear_chance = max(0.05, min(0.5, 0.4 - secrecy / 200.0))
        for other_id in getattr(state, "alive_agent_ids", []) or []:
            if other_id in (actor_id, target_id):
                continue
            if actor_loc and locations.get(other_id) != actor_loc:
                continue
            if _random.random() < overhear_chance:
                inbox.setdefault(other_id, []).append({
                    "tick": tick, "from": actor_id, "to": target_id,
                    "text": text, "overheard": True,
                })
                inbox[other_id] = inbox[other_id][-8:]
                logger.info(
                    "[Converse] tick=%s %s 偷听到 %s→%s 的交谈",
                    tick, other_id, actor_id, target_id,
                )

    def _challenge_action_brief_entry(self) -> Dict[str, Any]:
        """返回场景包声明的挑战应答动作（用于 brief 顶部注入）。"""
        for cfg in (self._runtime.actions_cfg or []):
            if not isinstance(cfg, dict):
                continue
            if str(cfg.get("category", "") or "") != "challenge":
                continue
            action_id = str(cfg.get("id", "") or "").strip()
            if not action_id:
                continue
            return {
                "id": action_id,
                "name": str(cfg.get("name") or action_id),
                "description": str(
                    cfg.get("description")
                    or "针对挑战材料给出研判与判断；text 字段必须是 JSON。"
                ),
                "requires_target": bool(cfg.get("requires_target", False)),
                "allows_code": bool(cfg.get("allows_code", False)),
                "target_kind": str(cfg.get("target_kind") or "challenge"),
            }
        raise RuntimeError("active capability challenge requires a scene-declared challenge action")

    def _is_challenge_action(self, action_id: str) -> bool:
        rule = self._scene_action_rule(action_id)
        return str(rule.get("category", "") or "") == "challenge"

    def _challenge_delivery_policy(self) -> str:
        """How capability challenges enter the main turn loop.

        - forced: old benchmark behavior, inject challenge question and require
          submit_challenge_response-style answers.
        - story_opportunity: story/data mode, keep capability probes as sidecar
          material instead of occupying the main action.
        """
        audit_cfg = self._runtime.audit_cfg or {}
        policy = str(
            audit_cfg.get("challenge_delivery_policy")
            or audit_cfg.get("capability_delivery_policy")
            or ""
        ).strip().lower()
        if policy:
            return policy
        mode = str(getattr(self._cfg, "runtime_mode", "") or "").strip().lower()
        if mode == "benchmark":
            return "forced"
        return "story_opportunity"

    def _should_force_challenge_actions(self) -> bool:
        return self._challenge_delivery_policy() in {
            "forced",
            "force",
            "benchmark",
            "main_turn",
        }

    def _apply_agent_interaction(
        self,
        *,
        action: ActionPack,
        result: CausalPipelineResult,
        tick: int,
        state: Any,
    ) -> bool:
        """结算场景声明的角色间互动，不识别任何场景专有动作。

        对象和指标变化仍由 CausalPipeline 负责；本方法只处理本来就不属于
        世界对象物理的关系、对手压力以及能力挑战污染登记。
        """
        rule = self._scene_action_rule(action.action_id)
        validation = getattr(result, "validation", None)
        if (
            str(rule.get("target_kind", "")) != "agent"
            or not action.target_agent_id
            or result.outcome in ("invalid", "backlash")
            or (validation is not None and not validation.valid)
        ):
            return False

        actor_id = action.agent_id
        target_id = action.target_agent_id
        resolution = self._resolve_interaction_outcome(result=result, rule=rule)
        effects = self._interaction_effects_for_outcome(
            rule=rule,
            resolution=resolution,
        )
        applied: List[Dict[str, Any]] = []
        if resolution:
            applied.append(resolution)
        for effect in effects:
            if not isinstance(effect, dict):
                continue
            self._apply_interaction_effect(
                effect=effect,
                applied=applied,
                actor_id=actor_id,
                target_id=target_id,
                rule=rule,
                action=action,
                result=result,
                tick=tick,
            )

        # 自由对话通道：conversation 类互动把 text 原话投递给目标下一拍感知，
        # 同地点第三人按隐蔽度掷点偷听——信息不对称、谣言与误判的来源。
        if str(rule.get("interaction_event_type", "")) == "conversation":
            self._deliver_conversation_message(
                actor_id=actor_id, target_id=target_id,
                action=action, tick=tick, state=state,
            )

        sabotage = rule.get("capability_sabotage")
        sabotage_allowed = True
        if resolution:
            resolution_cfg = rule.get("interaction_resolution") or {}
            allowed = resolution_cfg.get("sabotage_on_outcomes", ["success"])
            sabotage_allowed = str(resolution.get("outcome")) in set(allowed or [])
        if isinstance(sabotage, dict):
            from app.framework.capability.dark_side import SabotageAttempt

            node_id = str(sabotage.get("node_id", ""))
            probe_key = str(sabotage.get("probe_key", ""))
            coordinator = next(
                (
                    item for item in self._capability_coordinators
                    if getattr(item, "node_id", "") == node_id
                ),
                None,
            )
            if sabotage_allowed and coordinator is not None and probe_key:
                attempt = SabotageAttempt(
                    sabotage_id=f"sabotage_{tick}_{actor_id}_{target_id}",
                    tick=tick,
                    saboteur_id=actor_id,
                    target_id=target_id,
                    node_id=node_id,
                    probe_key=probe_key,
                    method=str(
                        sabotage.get("method", "plant_forged_evidence")
                    ),
                    corrupted_field=str(
                        sabotage.get("corrupted_field", "document")
                    ),
                    forged_value=sabotage.get("forged_value"),
                )
                coordinator.set_sabotage(attempt)
                applied.append({
                    "type": "capability_sabotage",
                    "sabotage_id": attempt.sabotage_id,
                    "node_id": node_id,
                    "probe_key": probe_key,
                    "target": target_id,
                })

        # ────────────────────────────────────────────────────────────────
        # 提议-应答闭环（OS 纯化：按动作声明的 interaction_role 识别，不再
        # 硬编码场景专有动作 id——投资/谈判等其他场景包声明同样的 role 即可
        # 复用整套队列机制）：
        #   - interaction_role: proposal 的动作 → 入对方待回应队列
        #   - interaction_role: response 的动作 → 出队 + 二次结算
        # 状态 state.internal["pending_proposals"][target_id] = [proposal_dict, ...]
        # 兼容：未声明 role 的旧场景包由 InteractionProtocol 处理旧动作 id。
        # ────────────────────────────────────────────────────────────────
        interaction_role = self._interaction_protocol.classify(action, rule)
        is_proposal_action = interaction_role.is_proposal
        is_response_action = interaction_role.is_response
        proposal_settlement: Optional[Dict[str, Any]] = None

        pending_root = state.internal.setdefault("pending_proposals", {})
        my_inbox: List[Dict[str, Any]] = pending_root.setdefault(actor_id, [])

        if is_response_action:
            # 在自己的收件箱里找最新一条来自 target_id 的提议
            matched_idx = None
            for idx in range(len(my_inbox) - 1, -1, -1):
                if my_inbox[idx].get("source_id") == target_id:
                    matched_idx = idx; break
            if matched_idx is not None:
                proposal = my_inbox.pop(matched_idx)
                proposal_settlement = {
                    "settled_proposal_id": proposal.get("proposal_id"),
                    "original_action": proposal.get("action_id"),
                    "originated_tick": proposal.get("tick"),
                    "response": action.action_id.replace("_proposal", "").replace("counter_attack", "counter"),
                }
                applied.append({"type": "proposal_settled", **proposal_settlement})
                settlement_effects = self._response_settlement_effects(
                    response_rule=rule,
                    proposal=proposal,
                )
                for effect in settlement_effects:
                    if not isinstance(effect, dict):
                        continue
                    self._apply_interaction_effect(
                        effect=effect,
                        applied=applied,
                        actor_id=actor_id,
                        target_id=target_id,
                        rule=rule,
                        action=action,
                        result=result,
                        tick=tick,
                        proposal=proposal,
                        source_object_id=str(
                            proposal.get("interaction_object_id")
                            or rule.get("interaction_object_id")
                            or ""
                        ),
                    )
            else:
                # 没有可应答的提议——该响应动作视为空响应（不计入提议结算，但仍有副作用如 relationship/cost）
                proposal_settlement = {"response": "noop"}
        elif is_proposal_action or (
            # 自由类别兜底动作（category 的 is_category_default 动作）走同一套提议队列，
            # 按风险类别判断（场景包 audit.yaml risky_categories 可配置）
            rule.get("is_category_default")
            and rule.get("category") in (
                {"relation"} | self._risky_categories()
            )
        ):
            # 注册一条待回应提议到目标方收件箱
            opp_inbox = pending_root.setdefault(target_id, [])
            opp_inbox.append({
                "proposal_id": f"prop_{tick}_{actor_id}_{action.action_id}_{target_id}",
                "tick": tick,
                "source_id": actor_id,
                "action_id": action.action_id,
                "intent": str(rule.get("intent", "")),
                "category": str(rule.get("category", "")),
                # 动态解析：预设招式用写死绑定，自由类别用模型自选的 target_object_id
                # （已按 dark_object_types 校验过类型）——这样后续反制/响应结算时
                # 读 proposal.get("interaction_object_id") 就能拿到正确落账对象
                "interaction_object_id": self._resolve_interaction_object_id(rule, action),
                "interaction_outcome": (
                    str(resolution.get("outcome")) if resolution else "unresolved"
                ),
                "interaction_score": (
                    float(resolution.get("score")) if resolution else None
                ),
            })
            # 旧提议过期清理：超过 4 tick 的自动作废
            pending_root[target_id] = [p for p in opp_inbox if (tick - int(p.get("tick", tick))) <= 4]
            applied.append({"type": "proposal_registered", "target": target_id, "action": action.action_id})

        actor_name = self._role_names.get(actor_id, actor_id)
        target_name = self._role_names.get(target_id, target_id)
        narrative = str(
            rule.get("interaction_narrative")
            or f"{actor_name}对{target_name}发起了直接博弈。"
        )
        event = RuntimeSignal(
            tick=tick,
            event_type=str(
                rule.get("interaction_event_type", "agent_interaction")
            ),
            source_id=actor_id,
            target_id=target_id,
            is_public=bool(rule.get("interaction_public", True)),
            summary=narrative.format(
                actor=actor_name,
                target=target_name,
            ),
            metadata={
                "action_id": action.action_id,
                "pipeline_action_id": result.action_id,
                "interaction_resolution": resolution,
                "applied_effects": applied,
                "proposal_settlement": proposal_settlement,
                "source_refs": [
                    result.action_id,
                    *[
                        item.delta_id for item in result.deltas
                    ],
                ],
            },
        )
        self._world_state.add_event(event)
        state.internal.setdefault("agent_interactions", []).append(
            event.model_dump(mode="json")
        )
        self._write_diagnostic({
            "event_type": "agent_interaction_committed",
            "tick": tick,
            "agent_id": actor_id,
            "target_agent_id": target_id,
            "action_id": action.action_id,
            "interaction_resolution": resolution,
            "effects": applied,
        })
        return True

    def _risky_categories(self) -> set:
        """暗面/对抗类动作类别集合（落后者加成、招式疲劳、反制结算共用）。

        类别只能由场景审计声明；OS 不提供任何领域默认值。
        """
        audit_cfg = self._runtime.audit_cfg or {}
        declared = audit_cfg.get("risky_categories")
        if isinstance(declared, list) and declared:
            return {str(c) for c in declared}
        return set()

    async def _tick(self) -> None:
        await self._tick_pipeline.run()

    async def _phase_perceive_and_decide(
        self, ctx: TickContext
    ) -> None:
        state = self._world_state.state
        assert state is not None

        # ━━ L1: 推进 tick + 统一驱动世界演化（资源/冷却/延迟事件/记忆/评估时间）━━
        tick = await self._world_state.advance_tick()
        # P2 压力：同步游戏实际资源到压力模型
        if self._evaluation.context and self._resource_service:
            gr = {}
            for aid in self._agent_runtime.agent_ids:
                gr[aid] = self._resource_service.get_all(aid)
            self._evaluation.context.pressure.advance_tick(tick, game_resource_states=gr)
        logger.info(f"[EngineOS] === Tick {tick} ===")

        # 初始化本 tick 的收集包
        self._pending_package = TickPackage(tick=tick, world_snapshot={})

        # 神谕高光帧：把上一间隔内注入的神谕广播给观众（导演当帧播报）
        self._flush_oracle_items(tick)

        # 在 Agent 决策前公布本回合到期挑战，使挑战成为当前世界冲突，
        # 而不是在角色行动之后才突然出现的后台题目。
        ordered_pending = sorted(
            (
                coord for coord in self._capability_coordinators
                if not coord.fired and coord.challenge_order > 0
            ),
            key=lambda coord: coord.challenge_order,
        )
        announced = (
            ordered_pending[0]
            if ordered_pending and ordered_pending[0].fire_tick <= tick
            else next(
                (
                    item
                    for item in sorted(
                        self._capability_coordinators,
                        key=lambda coord: coord.fire_tick,
                    )
                    if (
                        not item.fired
                        and item.challenge_order <= 0
                        and item.fire_tick <= tick
                    )
                ),
                None,
            )
        )
        if announced is not None and self._should_force_challenge_actions():
            self._activate_challenge(announced, tick)
            # P0-e（C方案）：本拍内激活通道也要登记"待答"状态，否则 brief 不会
            # 注入挑战材料、agent 收不到 challenge_question，submit_challenge_response 不会被选。
            if self._active_challenge_coord is None:
                self._active_challenge_coord = announced
                self._active_challenge_pending_agents = set(
                    self._agent_runtime.agent_ids
                )

        # ━━ L2: 感知层 — 通过 PerceptionKernel 构建简报（按地点/权限过滤）━━
        briefs: Optional[Dict] = None
        role_map = self._runtime.compiled.role_index
        briefs = self._perception.build_briefs(
            state,
            ruleworld_ctx=self._evaluation.context,
            agent_roles_map=role_map,
            agent_names=self._role_names,
        )
        # External executable worlds expose actor-scoped observations through
        # the adapter boundary. They enter the private brief verbatim; the OS
        # does not interpret domain fields or manufacture missing values.
        for actor_id, brief in briefs.items():
            adapter_observation = self._evaluation.world_observation(actor_id)
            if adapter_observation is None:
                continue
            if isinstance(adapter_observation, list):
                brief.raw_context["world_adapter_observations"] = [
                    item.model_dump(mode="json")
                    if hasattr(item, "model_dump") else item
                    for item in adapter_observation
                ]
            else:
                brief.raw_context["world_adapter_observation"] = (
                    adapter_observation.model_dump(mode="json")
                    if hasattr(adapter_observation, "model_dump")
                    else adapter_observation
                )
        current_challenge = self._world_state.get_scene_state(
            "current_challenge"
        )
        if current_challenge:
            for brief in briefs.values():
                brief.raw_context["current_challenge"] = dict(
                    current_challenge
                )

        # 本局 memory → prompt：把每个 agent 自己写下的本局关键事件
        # 在 brief 里露出，让 LLM 在长对局里依然能"记得自己的轨迹"——
        # 与 conversation history 互补（后者可能被 provider 截断）。
        for aid, brief in briefs.items():
            ws = self._agent_workspaces.get(aid)
            if ws is None:
                continue
            mem = ws.read_memory()
            if mem:
                # 只发末尾若干条，避免吃 token；同时去掉文件头标题
                lines_ = [
                    ln for ln in mem.splitlines()
                    if ln.startswith("- ")
                ]
                if lines_:
                    brief.raw_context["run_memory"] = "\n".join(lines_[-15:])
            summary = ws.workspace_summary()
            brief.raw_context["code_workspace"] = summary
            sandbox = self._agent_sandboxes.get(aid)
            if sandbox is not None:
                sandbox_snapshot = sandbox.snapshot()
                brief.raw_context["agent_sandbox"] = {
                    "sandbox_id": sandbox_snapshot["sandbox_id"],
                    "scope": sandbox_snapshot["scope"],
                    "capabilities": sandbox_snapshot["capabilities"],
                }

        # 已部署常驻宝器（Artifact）摘要，供 agent 知晓自己上线的程序
        for aid, brief in briefs.items():
            owned = [
                {
                    "artifact_id": art.artifact_id,
                    "name": art.name,
                    "description": art.description,
                    "workspace_path": art.workspace_path,
                    "trigger_count": art.trigger_count,
                }
                for art in state.artifacts.values()
                if art.owner_id == aid and art.is_active
            ]
            if owned:
                brief.raw_context["deployed_artifacts"] = owned

        # 失败反馈闭环：上一拍裁决的失败原因回流进简报（只回流最近 2 拍内的，
        # 更早的已过时）。探索的代价从"一拍黑洞"变成"一拍学费"。
        for aid, brief in briefs.items():
            verdict = self._last_tick_verdicts.get(aid)
            if verdict and brief.tick - int(verdict.get("tick", 0)) <= 2:
                brief.raw_context["last_verdict"] = str(verdict.get("text", ""))

        # 私人记忆回流：note_to_self 备忘 + 反思洞察，只给本人
        for aid, brief in briefs.items():
            private = self._agent_runtime.get_private_memory(aid)
            if private.get("notes") or private.get("reflections"):
                brief.raw_context["private_memory"] = private
            settlement_state = (
                state.internal.get("settlement_state", {}) or {}
            ).get(aid)
            if settlement_state:
                brief.raw_context["agent_settlement_state"] = settlement_state
            round_phase = self._current_round_phase(tick)
            if round_phase:
                brief.raw_context["round_phase"] = round_phase
            pending_intents = [
                item for item in (
                    state.internal.get("pending_action_intents", {}) or {}
                ).get(aid, []) or []
                if int(item.get("expires_tick", tick) or tick) >= tick
            ]
            if pending_intents:
                brief.raw_context["pending_action_intents"] = pending_intents[-4:]

        # 对话投递：converse 消息（含偷听）注入收件人感知，投递即消费
        if self._world_state.state is not None:
            inbox_map = self._world_state.state.internal.get(
                "incoming_messages", {}
            ) or {}
            name_of = self._role_names
            for aid, brief in briefs.items():
                pending_msgs = inbox_map.get(aid) or []
                if not pending_msgs:
                    continue
                rendered = []
                for msg in pending_msgs[-4:]:
                    frm = name_of.get(msg.get("from", ""), msg.get("from", ""))
                    if msg.get("overheard"):
                        to = name_of.get(msg.get("to", ""), msg.get("to", ""))
                        rendered.append(
                            f"（偷听）第 {msg.get('tick')} 拍，你无意间听到"
                            f"{frm}对{to}说：“{msg.get('text', '')}”"
                        )
                    else:
                        rendered.append(
                            f"第 {msg.get('tick')} 拍，{frm}"
                            f"（{msg.get('from', '')}）对你说：“{msg.get('text', '')}”"
                        )
                brief.raw_context["incoming_messages"] = rendered
                inbox_map[aid] = []

        # 世界状态目标：以"事"的形式呈现给角色（不展示 bonus 数值——目标
        # 的意义在于它是世界里可陈述的事实，不是又一排分数）。
        goals_cfg = self._world_goals_cfg()
        if goals_cfg:
            achieved_map = (
                self._world_state.state.internal.get("world_goals_achieved", {})
                if self._world_state.state is not None else {}
            ) or {}
            name_of = self._role_names
            for aid, brief in briefs.items():
                items = []
                for goal in goals_cfg:
                    owners = [
                        holder for holder, glist in achieved_map.items()
                        if any(g.get("id") == goal["id"] for g in glist)
                    ]
                    status = ""
                    if aid in owners:
                        status = "✅ 你已做成"
                    elif owners:
                        status = f"⚠️ 已被{ '、'.join(name_of.get(o, o) for o in owners) }抢先"
                    items.append({
                        "name": str(goal.get("name", goal["id"])),
                        "description": str(goal.get("description", "")),
                        "status": status,
                    })
                brief.raw_context["world_goals"] = items
                # 场景包自定义文案；OS 只提供中性默认。
                audit_cfg_wg = self._runtime.audit_cfg or {}
                if audit_cfg_wg.get("world_goals_title"):
                    brief.raw_context["world_goals_title"] = str(
                        audit_cfg_wg["world_goals_title"]
                    )
                if audit_cfg_wg.get("world_goals_footer"):
                    brief.raw_context["world_goals_footer"] = str(
                        audit_cfg_wg["world_goals_footer"]
                    )

        # 能力任务激活且尚有未完成角色时，向 brief 注入任务并追加场景动作。
        coord = self._active_challenge_coord
        if coord is not None and self._active_challenge_pending_agents:
            agent_ids_order = list(self._agent_runtime.agent_ids)
            for aid, brief in briefs.items():
                if aid not in self._active_challenge_pending_agents:
                    continue
                try:
                    idx = agent_ids_order.index(aid)
                except ValueError:
                    idx = 0
                question = coord.get_question_for_agent(
                    tick=tick, agent_id=aid, agent_idx=idx,
                )
                if question:
                    brief.raw_context["challenge_question"] = question
                    # 挑战因果钩子：前次挑战结果作为"前次挑战回响"进入挑战材料上下文
                    prior = self._challenge_history_summary(
                        exclude_order=int(getattr(coord, "challenge_order", 0) or 0)
                    )
                    if prior:
                        brief.raw_context["challenge_history"] = prior
                        # 前次挑战结果只形成场景声明的叙事提示，不在 OS 写业务话术。
                        my_last = self._agent_last_challenge_passed(aid)
                        if my_last is True:
                            brief.raw_context["challenge_momentum"] = (
                                self._scene_narration(
                                    "challenge_momentum_success",
                                    "你在前次挑战中通过了验证，可继续利用已经确认的事实。",
                                )
                            )
                        elif my_last is False:
                            brief.raw_context["challenge_momentum"] = (
                                self._scene_narration(
                                    "challenge_momentum_failure",
                                    "你在前次挑战中未通过验证，应根据反馈调整方法。",
                                )
                            )
                # 挑战激活时把场景包声明的 challenge 类动作置顶（而非替换），
                # 让 agent 在"先作答"和"先做策略动作"之间做真正的权衡。
                challenge_action_dict = self._challenge_action_brief_entry()
                existing = brief.available_actions or []
                brief.available_actions = [challenge_action_dict] + [
                    a for a in existing if a.get("id") != challenge_action_dict["id"]
                ]

        self._measurement_opportunities.annotate_briefs(tick, briefs)

        loop_enabled = bool(
            getattr(self._cfg.agent_loop, "enabled", False)
            and str(self._cfg.runtime_mode).strip().lower() != "benchmark"
        )
        if loop_enabled:
            for brief in briefs.values():
                brief.raw_context["agent_loop_enabled"] = True
                brief.raw_context["agent_loop_max_steps"] = int(
                    getattr(self._cfg.agent_loop, "max_steps", 5)
                )
                prompt_cfg = getattr(self._loaded, "prompt_contract", {}) or {}
                if isinstance(prompt_cfg.get("prompt_contract"), dict):
                    prompt_cfg = prompt_cfg["prompt_contract"]
                harness_policy = dict(prompt_cfg.get("harness_policy", {}) or {})
                if harness_policy:
                    validity_ticks = int(
                        (getattr(self._loaded, "settlement_cfg", {}) or {})
                        .get("evidence_validity_ticks", 0) or 0
                    )
                    research_validity = int(
                        (getattr(self._loaded, "settlement_cfg", {}) or {})
                        .get("research_evidence_validity_ticks", validity_ticks)
                        or validity_ticks
                    )
                    prior_external = []
                    for item in (
                        self._world_state.state.internal.get(
                            "os2_external_observations", []
                        ) if self._world_state.state else []
                    ):
                        if not isinstance(item, dict):
                            continue
                        raw_value = item.get("raw_value") or {}
                        owner_id = (
                            str(raw_value.get("owner_id") or "")
                            if isinstance(raw_value, dict) else ""
                        )
                        if owner_id and owner_id != brief.agent_id:
                            continue
                        age = tick - int(item.get("world_tick", tick) or tick)
                        if (
                            item.get("verification_status") == "verified"
                            and (
                                research_validity <= 0
                                or age <= research_validity
                            )
                        ):
                            prior_external.append(item)
                    if prior_external:
                        harness_policy["prior_verified_observations"] = prior_external
                        # 有历史证据时只需跳过首步 discover；研究门禁仍生效。
                        harness_policy["require_initial_capability_discovery"] = False
                        research_gate = dict(
                            harness_policy.get("research_requirements") or {}
                        )
                        if not research_gate.get("enabled"):
                            harness_policy["require_verified_external_result"] = False
                    brief.raw_context["harness_policy"] = harness_policy

        for brief in briefs.values():
            brief.raw_context["run_id"] = self._trace.run_id

        loop_context = None
        if loop_enabled:
            from app.agent_os.capability_broker import CapabilityBroker

            loop_context = {
                "config": self._cfg.agent_loop,
                "run_id": self._trace.run_id,
                "scenario_id": str(
                    getattr(self._loaded.manifest, "scenario_id", "")
                    or getattr(self._loaded.manifest, "name", "")
                ),
                "action_runtime": self._action_runtime,
                "state": state,
                "runtime_mode": self._cfg.runtime_mode,
                "get_tool_def": (
                    lambda tid: self._runtime.get_tool_rule(tid)
                    if self._runtime and tid else {}
                ),
                "workspaces": self._agent_workspaces,
                "sandbox_cfg": self._cfg.sandbox,
                "diagnostic_sink": self._write_diagnostic,
                "capability_broker": CapabilityBroker(
                    scene_tools=list(self._runtime.tools_cfg or []),
                ),
                "agent_sandboxes": self._agent_sandboxes,
            }

        # ━━ L3: Agent 运行时 — 并发收集所有 agent 动作 ━━
        ctx.tool_run_start_index = len(self._action_runtime.tool_runs)
        collect_timeout = max(
            float(self._cfg.agent_timeout_sec),
            float(getattr(self._cfg.agent_loop, "session_timeout_sec", 60.0))
            if loop_enabled else 0.0,
            float(getattr(self._cfg.external_agent, "turn_timeout_ms", 120_000)) / 1000.0
            if any(str(getattr(s, "driver", "llm")).strip().lower() == "agent" for s in self._cfg.agents)
            else 0.0,
        )
        actions, logs = await self._agent_runtime.collect_actions(
            state, briefs,
            timeout_sec=collect_timeout,
            loop_context=loop_context,
        )
        self._last_actions = actions or {}
        self._store_logs(logs)
        await self._broadcast_logs(logs)
        for log in logs:
            self._write_diagnostic({
                "event_type": "agent_turn_completed",
                "tick": tick,
                "agent_id": log.agent_id,
                "provider": log.provider,
                "model": log.model,
                "duration_ms": log.duration_ms,
                "tokens_used": log.tokens_used,
                "error": log.error,
                "perception_pack": (
                    log.perception_pack.model_dump(mode="json")
                    if log.perception_pack else None
                ),
                "raw_llm_response": log.raw_llm_response,
                "action_pack": (
                    log.action_pack.model_dump(mode="json")
                    if log.action_pack else None
                ),
            })

        # 调试日志：打印每个 agent 的 ActionPack 关键字段
        for aid, act in self._last_actions.items():
            if act:
                logger.info(
                    f"[L3] tick={tick} agent={aid} action_id={act.action_id} "
                    f"monologue='{(act.character_monologue or '')[:60]}' "
                    f"public_reasoning='{(act.public_reasoning_summary or '')[:60]}' "
                    f"text='{(act.text or '')[:60]}' plan='{(act.plan or '')[:60]}' "
                    f"parsed_ok={act.parsed_ok}"
                )
            else:
                logger.warning(f"[L3] tick={tick} agent={aid} ActionPack 为 None")

        ctx.state = state
        ctx.tick = tick
        ctx.briefs = briefs
        ctx.actions = actions or {}
        ctx.logs = logs

    async def _phase_execute_and_settle(
        self, ctx: TickContext
    ) -> None:
        state = ctx.state
        tick = ctx.tick
        briefs = ctx.briefs
        actions = ctx.actions
        logs = ctx.logs
        # ━━ L4: 动作运行时 — 前置校验 + 通用状态效果 + 工具沙盒 ━━
        tool_results: Dict[str, Any] = {}
        state_change_records: List[Any] = []
        valid_actions: Dict[str, Any] = {}  # 通过校验的 action（供 Trace 用）
        planned_transitions: List[Any] = []

        # Preserve deterministic transaction order across concurrent turns.
        for agent_id in sorted((actions or {}), key=str):
            action = (actions or {}).get(agent_id)
            if action is None:
                continue

            # P0-5: 前置校验
            agent_loc = self._world_state.get_agent_location(agent_id)
            visible_object_ids = None
            visible_agent_ids = None
            reachable_location_ids = None
            if briefs and agent_id in briefs:
                visible_object_ids = [
                    obj.get("id", obj.get("object_id", ""))
                    for obj in (briefs[agent_id].visible_objects or [])
                    if isinstance(obj, dict)
                ]
                visible_agent_ids = [
                    item.get("agent_id")
                    for item in (briefs[agent_id].others_summary or [])
                    if isinstance(item, dict) and item.get("agent_id")
                ]
                reachable_location_ids = [
                    item.get("location_id")
                    for item in (briefs[agent_id].reachable_locations or [])
                    if isinstance(item, dict) and item.get("location_id")
                ]
            action_cfg = self._scene_action_rule(action.action_id)
            if (
                action_cfg
                and action_cfg.get("target_kind") == "location"
                and action.target_object_id
                and not self._location_registry.exists(action.target_object_id)
            ):
                matched = self._match_location_by_name(action.target_object_id)
                if matched:
                    logger.info(f"[L4] 地点模糊匹配: {action.target_object_id} → {matched}")
                    action.target_object_id = matched
            if self._precondition_validator:
                precond = self._precondition_validator.validate(
                    action,
                    agent_location=agent_loc,
                    visible_object_ids=visible_object_ids,
                    visible_agent_ids=visible_agent_ids,
                    reachable_location_ids=reachable_location_ids,
                )
                if not precond.valid:
                    logger.info(f"[EngineOS] L4 前置校验拒绝 agent={agent_id} action={action.action_id}: {precond.reason_code}")
                    reason_zh = {
                        "unknown_action": "动作不存在",
                        "missing_target": "缺少目标",
                        "target_not_accessible": "目标不可见或不可及",
                        "location_not_allowed": "当前地点不允许这个动作",
                        "permission_denied": "权限不足",
                        "insufficient_resources": "资源不够支付成本",
                        "cooldown_active": "该动作还在冷却中",
                    }
                    detail = "；".join(
                        reason_zh.get(code, code)
                        for code in (precond.reason_code or "").split(",")
                        if code
                    )
                    self._last_tick_verdicts[agent_id] = {
                        "tick": tick,
                        "text": (
                            f"你上一拍尝试的「{action.action_id}」未获执行"
                            f"（{detail or '前置校验未通过'}），这一拍作废了。"
                        ),
                    }
                    continue

            valid_actions[agent_id] = action

            # L4: 通用状态效果（位置变更等，由 action 配置的 target_kind 驱动）
            if action_cfg:
                planned_transitions.append(
                    self._action_runtime.plan_state_transition(
                        action, action_cfg, state,
                    )
                )

        # L4: 一次性提交所有平台变化。资源/冷却/位置任一失败则整体回滚，
        # 随后降级为逐 agent 提交：只剔除肇事 agent，不让单人问题拖垮全拍。
        def _commit(transitions_batch):
            return self._action_runtime.commit_transitions(
                tick=tick,
                transitions=transitions_batch,
                state=state,
                world_state_kernel=self._world_state,
                resource_service=self._resource_service,
                cooldown_service=self._cooldown_service,
                location_registry=self._location_registry,
            )

        tick_transactions = state.internal.setdefault("tick_transactions", [])
        try:
            transaction = _commit(planned_transitions)
            tick_transactions.append(transaction.model_dump())
        except Exception as batch_exc:
            logger.warning(
                f"[L4] tick={tick} 平台事务整体提交失败，降级为逐 agent 提交: {batch_exc}"
            )
            for transition in planned_transitions:
                try:
                    partial = _commit([transition])
                    tick_transactions.append(partial.model_dump())
                except Exception as one_exc:
                    # 该 agent 的平台变化未落地（资源不足/未知地点等）→
                    # 撤销其本拍动作资格，其余 agent 不受影响。
                    failed_agent = transition.agent_id
                    valid_actions.pop(failed_agent, None)
                    logger.info(
                        f"[L4] tick={tick} agent={failed_agent} 平台事务被拒: {one_exc}"
                    )
        self._world_state.sync_runtime_state()

        self._apply_workspace_code_writes(valid_actions, tick)

        # 平台事务提交成功后再执行工具，避免工具观察到半提交状态。
        for agent_id in sorted(valid_actions, key=str):
            action = valid_actions[agent_id]
            try:
                from app.mcp.tool_executor import resolve_tool_id

                _tid = resolve_tool_id(action)
                _action_cfg = (
                    self._scene_action_rule(action.action_id)
                    if self._runtime else {}
                )
                _tool_def = (
                    self._runtime.get_tool_rule(_tid)
                    if _tid and self._runtime
                    else {}
                )
                if (
                    not _tid
                    and isinstance(_action_cfg, dict)
                    and str(_action_cfg.get("category", "")) == "tool_use"
                ):
                    _tool_def = _action_cfg
                tool_result = await self._action_runtime.execute_tool(
                    action, tick, state,
                    tool_def=_tool_def,
                    runtime_mode=self._cfg.runtime_mode,
                )
                if tool_result:
                    tool_results[agent_id] = tool_result
                    if getattr(tool_result, "source", "") == "mcp":
                        self._write_diagnostic({
                            "event_type": "mcp_tool_call",
                            "tick": tick,
                            "agent_id": agent_id,
                            "tool_id": tool_result.tool_id,
                            "mcp_server_id": tool_result.mcp_server_id,
                            "mcp_tool_name": tool_result.mcp_tool_name,
                            "ok": tool_result.ok,
                            "duration_ms": tool_result.duration_ms,
                            "errors": list(tool_result.errors or [])[:5],
                            "outputs_preview": [
                                o.get("summary", str(o))[:200]
                                for o in (tool_result.outputs or [])[:2]
                                if isinstance(o, dict)
                            ],
                        })
                    if getattr(tool_result, "source", "") == "tool_request":
                        self._write_diagnostic({
                            "event_type": "tool_request_recorded",
                            "tick": tick,
                            "agent_id": agent_id,
                            "tool_id": tool_result.tool_id,
                            "ok": tool_result.ok,
                            "outputs_preview": [
                                o.get("summary", str(o))[:200]
                                for o in (tool_result.outputs or [])[:2]
                                if isinstance(o, dict)
                            ],
                        })
                    if (
                        tool_result.ok
                        and action.target_object_id
                    ):
                        discoveries = state.internal.setdefault(
                            "discoveries", {}
                        ).setdefault(agent_id, [])
                        if action.target_object_id not in discoveries:
                            discoveries.append(action.target_object_id)
                    # 工具运行成功且 agent 请求上线 → 注册为常驻 Artifact
                    self._action_runtime.maybe_deploy_artifact(
                        action, tick, state, tool_result
                    )
            except Exception as e:
                logger.warning(f"[EngineOS] L4 工具执行异常 agent={agent_id}: {e}")

        # L4b: Artifact 执行（agent 开发的常驻程序在沙盒中运行）
        try:
            artifact_events = await self._action_runtime.execute_artifacts(state)
            if artifact_events:
                logger.info(f"[EngineOS] L4b Artifact 执行产出 {len(artifact_events)} 个事件")
                for evt in artifact_events:
                    state_change_records.append(evt)
        except Exception as e:
            logger.warning(f"[EngineOS] L4b Artifact 执行异常: {e}")

        # P0-e（C方案）：先处理 submit_challenge_response 动作——直接路由到当前激活挑战
        # 的协调器，跳过常规因果管线。产出的 cases/events 与原子回合
        # 路径同形态，经 _capability_result_queue → _drain_capability_results
        # → 能力 Settlement sidecar；能力结果不修改世界状态。
        self._route_submit_challenge_response_actions(valid_actions, tick)
        # 能力任务延期后果由场景淘汰配置指定指标和幅度。
        self._penalize_challenge_delay(valid_actions, tick)

        # ━━ World execution: the scene owns the route for every action ━━
        # A route may use a World Adapter regardless of settlement mode.
        # Routes without one are committed as WorldAction facts and resolved
        # by SettlementRuntime.  Adapter transitions are facts consumed by the
        # same independent settlement layer; they do not grant scoring authority.
        pipeline_results: List[CausalPipelineResult] = []
        world_execution_actions: List[ActionPack] = []
        for agent_id in sorted(valid_actions, key=str):
            action = valid_actions[agent_id]
            # challenge 类动作已在 _route_submit_challenge_response_actions 中处理完毕
            if self._is_challenge_action(action.action_id):
                continue
            execution_route = self._evaluation.execution_route(
                action.action_id
            )
            if not self._evaluation.requires_simulation(action.action_id):
                # 记忆不再写"已交由场景结算"占位——结算完成后
                # _write_settlement_memory 会把真实 outcome+理由写进记忆。
                self._write_diagnostic({
                    "event_type": "scene_execution_routed",
                    "tick": tick,
                    "agent_id": action.agent_id,
                    "action_id": action.action_id,
                    "mode": execution_route.get("mode"),
                    "provider_id": execution_route.get("provider_id"),
                })
                continue
            world_execution_actions.append(action)

        batch_results: Dict[str, CausalPipelineResult] = {}
        if world_execution_actions:
            try:
                batch_results = await self._evaluation.run_action_batch(
                    world_execution_actions,
                    tick,
                    state,
                    tool_results,
                )
            except Exception as exc:
                logger.error(
                    "[EngineOS] world execution batch 异常 tick=%s: %s",
                    tick,
                    exc,
                    exc_info=True,
                )
                from app.contracts.world_adapter import (
                    WorldAdapterActionReceipt,
                )
                for action in world_execution_actions:
                    batch_results[action.agent_id] = CausalPipelineResult(
                        tick=tick,
                        action_id=action.action_id,
                        agent_id=action.agent_id,
                        outcome="error",
                        errors=[f"world_adapter_batch_failed:{exc}"],
                        action=action,
                        world_action_receipt=WorldAdapterActionReceipt(
                            receipt_id=(
                                f"receipt:adapter-command:{tick}:"
                                f"{action.agent_id}"
                            ),
                            command_id=(
                                f"adapter-command:{tick}:{action.agent_id}"
                            ),
                            world_tick=tick,
                            actor_id=action.agent_id,
                            action_type=action.action_id,
                            status="failed",
                            reasons=["world_adapter_batch_failed"],
                            details={"error": str(exc)},
                        ),
                    )

        for action in world_execution_actions:
            try:
                result = batch_results.get(action.agent_id)
                if result is None:
                    from app.contracts.world_adapter import (
                        WorldAdapterActionReceipt,
                    )
                    result = CausalPipelineResult(
                        tick=tick,
                        action_id=action.action_id,
                        agent_id=action.agent_id,
                        outcome="error",
                        errors=["world_adapter_missing_result"],
                        action=action,
                        world_action_receipt=WorldAdapterActionReceipt(
                            receipt_id=(
                                f"receipt:adapter-command:{tick}:"
                                f"{action.agent_id}"
                            ),
                            command_id=(
                                f"adapter-command:{tick}:{action.agent_id}"
                            ),
                            world_tick=tick,
                            actor_id=action.agent_id,
                            action_type=action.action_id,
                            status="failed",
                            reasons=["world_adapter_missing_result"],
                        ),
                    )
                pipeline_results.append(result)
                self._record_tick_verdict(action, result, tick)
                interaction_applied = self._apply_agent_interaction(
                    action=action,
                    result=result,
                    tick=tick,
                    state=state,
                )
                if interaction_applied and result.outcome == "no_effect":
                    # 对角色关系、情报域或能力输入的改变本身就是世界后果。
                    # 承载对象没有数值位移，不应让导演误报为“什么也没发生”。
                    result.outcome = "success"
                action_rule = self._scene_action_rule(
                    action.action_id
                )
                # P0-a: 调查类动作成功作用于关键对象 → 产出标准 EvidenceEntry。
                self._maybe_create_investigation_evidence(
                    action=action, action_rule=action_rule, result=result,
                    tool_results=tool_results,
                )
                # P2 压力：高风险策略动作累积风险
                if (
                    action_rule
                    and action_rule.get("category") in self._risky_categories()
                ):
                    self._evaluation.context.pressure.accumulate_strategy_risk(
                        action.agent_id
                    )
                # P2 压力：调查成功涨信息域
                if (
                    action_rule and action_rule.get("category") == "investigation"
                    and getattr(result, "outcome", "") == "success"
                ):
                    self._evaluation.context.pressure.gain_information_scope(
                        action.agent_id
                    )
                # Memory hook：把本回合动作结果写进 agent 自己的 memory.md。
                # 仅记录"成败 + 简要因果"，便于 agent 后续 tick / 跨局回忆。
                try:
                    action_label = (action_rule or {}).get("name") or action.action_id
                    target_label = (
                        action.target_object_id or action.target_agent_id or ""
                    )
                    outcome_zh = {
                        "success": "成功",
                        "no_effect": "未生效",
                        "invalid": "失败/反噬",
                        "backlash": "反噬",
                        "error": "异常",
                    }.get(getattr(result, "outcome", ""), "完成")
                    mem_summary = (
                        f"{action_label}"
                        f"{(' → ' + target_label) if target_label else ''} · {outcome_zh}"
                    )
                    self._record_agent_memory(
                        agent_id=action.agent_id, tick=tick, summary=mem_summary,
                    )
                except Exception:
                    pass
                state.internal.setdefault(
                    "simulation_health_records", []
                ).append({
                    "tick": tick,
                    "agent_id": result.agent_id,
                    "action_id": action.action_id,
                    "target_kind": action_rule.get(
                        "target_kind", "object"
                    ),
                    "outcome": result.outcome,
                    "delta_count": len(result.deltas),
                    "metric_count": len(result.metrics),
                })
                self._write_diagnostic({
                    "event_type": "simulation_execution_completed",
                    "tick": tick,
                    "agent_id": result.agent_id,
                    "action_id": result.action_id,
                    "outcome": result.outcome,
                    "evaluation": (
                        result.evaluation.model_dump(mode="json")
                        if result.evaluation else None
                    ),
                    "validation": (
                        result.validation.model_dump(mode="json")
                        if result.validation else None
                    ),
                    "budget": (
                        result.budget.model_dump(mode="json")
                        if result.budget else None
                    ),
                    "proposal": (
                        result.proposal.model_dump(mode="json")
                        if result.proposal else None
                    ),
                    "deltas": [
                        item.model_dump(mode="json") for item in result.deltas
                    ],
                    "metrics": [
                        item.model_dump(mode="json") for item in result.metrics
                    ],
                    "world_action_receipt": (
                        result.world_action_receipt.model_dump(mode="json")
                        if result.world_action_receipt else None
                    ),
                    "world_transition": (
                        result.world_transition.model_dump(mode="json")
                        if result.world_transition else None
                    ),
                    "errors": list(result.errors),
                })
            except Exception as e:
                logger.error(f"[EngineOS] pipeline 异常 agent={getattr(action, 'agent_id', '?')}: {e}",
                             exc_info=True)

        self._measurement_opportunities.finalize_tick(
            tick=tick,
            actions=actions or {},
            valid_actions=valid_actions,
            pipeline_results=pipeline_results,
            state=state,
        )

        # AgentLoop 中间步骤和 L4 最终工具执行共用 ActionRuntime 账本。
        # tick 级切片保证 trace/replay/下一拍反馈都能看到完整工具链路。
        all_runtime_tool_runs = list(self._action_runtime.tool_runs)
        tick_tool_runs = all_runtime_tool_runs[ctx.tool_run_start_index:]
        seen_run_ids = {
            str(getattr(item, "run_id", "") or "")
            for item in tick_tool_runs
            if getattr(item, "run_id", None)
        }
        for tr in tool_results.values():
            run_id = str(getattr(tr, "run_id", "") or "")
            if run_id and run_id in seen_run_ids:
                continue
            tick_tool_runs.append(tr)
            if run_id:
                seen_run_ids.add(run_id)

        ctx.valid_actions = valid_actions
        ctx.tool_results = tool_results
        ctx.tick_tool_runs = tick_tool_runs
        ctx.pipeline_results = pipeline_results

    async def _phase_assess_and_present(
        self, ctx: TickContext
    ) -> None:
        state = ctx.state
        tick = ctx.tick
        briefs = ctx.briefs
        actions = ctx.actions
        logs = ctx.logs
        valid_actions = ctx.valid_actions
        tool_results = ctx.tool_results
        tick_tool_runs = ctx.tick_tool_runs or list(tool_results.values())
        pipeline_results = ctx.pipeline_results
        # L5+: 挑战超时强制关门——任一 agent 因任何原因（L4拒绝/超时/解析失败）
        # 无法提交挑战答案，挑战最多存活 _challenge_max_alive 回合后强制收官
        if self._active_challenge_coord is not None and tick - self._challenge_started_tick >= self._challenge_max_alive:
            coord_closing = self._active_challenge_coord
            logger.warning(
                f"[P0-e] 挑战《{getattr(coord_closing,'title','?')}》"
                f"存活 {tick-self._challenge_started_tick} 回合，超时强制关门，"
                f"尚未提交的 agent: {self._active_challenge_pending_agents}"
            )
            from app.framework.capability.node_coordinator import NodeResult
            if self._active_challenge_result is None:
                self._active_challenge_result = NodeResult(
                    node_id=getattr(coord_closing, "node_id", ""), tick=tick,
                )
            # 只收集本次超时新产生的弃答案例；已答者的案例在作答当拍就已入队，
            # 重推整个 result 会造成 store["cases"] 重复、聚合器双计。
            skip_events: List[Any] = []
            skip_cases: List[Any] = []
            agent_ids_order = list(self._agent_runtime.agent_ids)
            for aid in list(self._active_challenge_pending_agents):
                try:
                    idx = agent_ids_order.index(aid)
                except ValueError:
                    idx = 0
                coord_closing.commit_skipped_answer(
                    tick=tick, agent_id=aid, agent_idx=idx,
                    reason=f"挑战超时({self._challenge_max_alive}回合)",
                    event_sink=skip_events.append,
                    case_sink=skip_cases.append,
                    result=self._active_challenge_result,
                )
                self._active_challenge_pending_agents.discard(aid)
            if skip_events or skip_cases:
                await self._capability_result_queue.put({
                    "node_id": coord_closing.node_id,
                    "cases": skip_cases,
                    "events": skip_events,
                })
            # 关门即落幕：必须标记 fired，否则下一拍挑战会被重新激活，
            # 已答者重复计分且后续挑战被永久堵死。
            coord_closing.mark_fired()
            # 若本次挑战没有任何批次入队（无人作答也无弃答案例），顺序闸门会
            # 一直等它——直接把水位推进到本次挑战，让后续挑战正常放行。
            challenge_order = getattr(coord_closing, "challenge_order", 0) or 0
            if not (skip_events or skip_cases):
                self._last_drained_challenge_order = max(
                    self._last_drained_challenge_order, challenge_order
                )
            self._last_challenge_closed_tick = tick
            self._active_challenge_coord = None
            self._active_challenge_result = None

        # L5+: 通用能力测评剧情节点（守卫式；无挑战内容时 no-op）
        assessment_tick = await self._maybe_run_capability_nodes(
            tick, actions=valid_actions
        )
        if assessment_tick["cases"]:
            assessment_store = state.internal.get("capability_assessment", {})
            await self._emit("operator", {
                "type": "capability_assessment",
                "profiles": assessment_store.get("profiles", {}),
                "cases": assessment_store.get("cases", []),
                "events": assessment_store.get("events", []),
            })

        # 工具结果回流：存入 state.internal.last_tool_results 供下回合 build_briefs 读取
        if tick_tool_runs:
            if not hasattr(state, "internal") or state.internal is None:
                state.internal = {}
            last_tr = {}
            for tr in tick_tool_runs:
                aid = str(getattr(tr, "owner_id", "") or "")
                if not aid:
                    continue
                last_tr.setdefault(aid, []).append({
                    "tool_id": tr.tool_id,
                    "ok": tr.ok,
                    "source": getattr(tr, "source", "sandbox"),
                    "outputs": tr.outputs[:3] if tr.outputs else [],
                    "evidence_created": tr.evidence_created[:3] if tr.evidence_created else [],
                    "errors": tr.errors[:2] if tr.errors else [],
                })
            for aid in list(last_tr):
                last_tr[aid] = last_tr[aid][-5:]
            state.internal["last_tool_results"] = last_tr

        await self._notify_external_turn_results(tick, actions or {}, pipeline_results)

        # Commit authoritative OS2 facts before any presentation compiler runs.
        # DirectorRuntime may only consume this immutable event/settlement chain.
        self._commit_os2_tick(
            tick=tick,
            valid_actions=valid_actions,
            pipeline_results=pipeline_results,
            logs=logs,
            state=state,
        )
        self._update_pending_action_intents(
            state=state,
            tick=tick,
            actions=actions or {},
            valid_actions=valid_actions,
            settlements=self._last_os2_settlements,
        )
        self._commit_os2_assessment_facts(
            tick=tick, assessment_tick=assessment_tick, state=state
        )
        await self._run_os2_director_agent(tick=tick, state=state)

        # DirectorPlan is the only presentation source after facts commit.
        self._pending_package.presentation_plan = None
        self._os2_plan_applied = self._apply_os2_director_plan(
            self._pending_package
        )
        if not self._cfg.headless and not self._os2_plan_applied:
            raise RuntimeError(
                f"DirectorPlan missing or rejected for committed tick {tick}"
            )
        if self._os2_plan_applied:
            await self._attach_os2_tts(self._pending_package)

        # ━━ 横切 Trace: 记录 tick（传入 actions 构建 DAG）━━
        try:
            trace_snapshot = self._collect_snapshot()
            self._trace.record_tick(
                tick=tick,
                state=state,
                agent_logs=logs,
                assessment_cases=[
                    item for item in assessment_tick.get("cases", [])
                ],
                tool_runs=tick_tool_runs,
                world_snapshot=trace_snapshot,
                os2_world_actions=self._last_os2_actions,
                os2_external_observations=self._last_os2_observations,
                os2_world_events=self._last_os2_events,
                os2_settlements=self._last_os2_settlements,
                os2_director_plan=self._last_os2_director_plan,
                director_harness_trace=self._last_director_harness_trace,
            )
        except Exception as e:
            logger.warning(f"[EngineOS] trace 记录失败: {e}")

        # 每 5 拍增量导出账本：实时局中途暂停/崩溃不再丢整局复盘数据。
        if tick % 5 == 0:
            try:
                await asyncio.to_thread(self._trace.flush_partial)
            except Exception as exc:
                logger.debug(f"[EngineOS] 账本增量导出失败(不影响主循环): {exc}")

        # ━━ 收集 pending_package ━━
        try:
            ledgers = self._evaluation.export_ledgers()
            self._pending_package.ledger_snapshot = {
                "counts": {k: len(v) if isinstance(v, list) else 0 for k, v in ledgers.items()},
            }
        except Exception:
            pass

        self._pending_package.agent_logs = [log.model_dump() for log in logs]

        # 记忆压缩（每 10 tick）
        if tick % 10 == 0:
            for aid in state.alive_agent_ids:
                task = asyncio.create_task(
                    self._agent_runtime.compress_memory(aid, self._director_provider)
                )
                self._bg_tasks.add(task)
                task.add_done_callback(self._bg_tasks.discard)

        # L1: tick 结束同步运行时状态（资源/冷却）
        self._world_state.sync_runtime_state()
        # 提交快照必须晚于全部运行时状态同步；播放侧会在动作段完成后才公开它。
        self._pending_package.world_snapshot = self._collect_snapshot()
        # P2 压力：tick 末尾衰减反制（确保 Agent 在当拍 brief 中看到真实值）
        if self._evaluation.context:
            self._evaluation.context.pressure.end_tick()
        self._write_diagnostic({
            "event_type": "tick_committed",
            "tick": tick,
            "pipeline_result_count": len(pipeline_results),
            "assessment_case_count": len(assessment_tick.get("cases", [])),
            "director_plan_id": (
                self._pending_package.director_plan or {}
            ).get("plan_id"),
            "presentation_plan": (
                {
                    "tick": self._pending_package.presentation_plan.tick,
                    "estimated_duration_ms": (
                        self._pending_package
                        .presentation_plan
                        .estimated_duration_ms
                    ),
                    "segments": [
                        {
                            "kind": segment.kind,
                            "duration_ms": segment.duration_ms,
                            "payload": segment.payload,
                        }
                        for segment in (
                            self._pending_package.presentation_plan.segments
                        )
                    ],
                }
                if self._pending_package.presentation_plan else None
            ),
            "audio_chunks": [
                {
                    "index": item.get("index"),
                    "text": item.get("text"),
                    "has_audio": bool(item.get("audio_b64")),
                    "source": item.get("source"),
                }
                for item in (
                    getattr(self._pending_package, "audio_chunks", []) or []
                )
            ],
            "audio_chunk_count": len(
                getattr(self._pending_package, "audio_chunks", []) or []
            ),
            "audio_success_count": sum(
                1 for item in (
                    getattr(self._pending_package, "audio_chunks", []) or []
                )
                if item.get("audio_b64")
            ),
            "presentation_duration_ms": (
                self._pending_package.presentation_plan.estimated_duration_ms
                if self._pending_package.presentation_plan else 0
            ),
            "world_snapshot": self._pending_package.world_snapshot,
            "os2_world_actions": [
                item.model_dump(mode="json") for item in self._last_os2_actions
            ],
            "os2_world_events": [
                item.model_dump(mode="json") for item in self._last_os2_events
            ],
            "os2_external_observations": [
                item.model_dump(mode="json")
                for item in self._last_os2_observations
            ],
            "os2_settlements": [
                item.model_dump(mode="json")
                for item in self._last_os2_settlements
            ],
            "os2_director_plan": (
                self._last_os2_director_plan.model_dump(mode="json")
                if self._last_os2_director_plan else None
            ),
            "director_harness_trace": (
                self._last_director_harness_trace.model_dump(mode="json")
                if self._last_director_harness_trace else None
            ),
        })

        # P1-2: 基于本 tick 可见对象更新记忆
        if self._memory_service:
            for aid in state.alive_agent_ids:
                if briefs and aid in briefs:
                    for obj in briefs[aid].visible_objects:
                        obj_id = obj.get("id", obj.get("object_id", ""))
                        if obj_id:
                            self._memory_service.remember(aid, "object", obj_id, obj, tick)

        # P1-5: 回放记录
        if self._replay_recorder:
            self._replay_recorder.record_tick(
                tick=tick,
                world_actions=[item.model_dump(mode="json") for item in self._last_os2_actions],
                external_observations=[item.model_dump(mode="json") for item in self._last_os2_observations],
                world_events=[item.model_dump(mode="json") for item in self._last_os2_events],
                settlements=[item.model_dump(mode="json") for item in self._last_os2_settlements],
                director_plan=(
                    self._last_os2_director_plan.model_dump(mode="json")
                    if self._last_os2_director_plan else None
                ),
                tool_runs=[
                    tr.model_dump() if hasattr(tr, "model_dump") else {}
                    for tr in tick_tool_runs
                ],
            )

        ctx.assessment_tick = assessment_tick

    async def _phase_finalize_lifecycle(
        self, ctx: TickContext
    ) -> None:
        state = ctx.state
        tick = ctx.tick
        briefs = ctx.briefs
        tool_results = ctx.tool_results
        # 世界状态目标：每拍评估场景包声明的事实成就。
        # 给目标一个非分数的存在形式：agent 追求的是世界里的事，分数退回副产物。
        self._evaluate_world_goals(state, tick)

        # ── 反思子回合：每 5 拍，agent 用自己的模型复盘自己的轨迹 ──
        # 不消耗行动点，产出的策略洞察置顶注入后续简报（跨拍连贯性的生长点）
        if tick > 0 and tick % 5 == 0:
            try:
                await self._agent_runtime.reflect_all(tick)
            except Exception as exc:
                logger.warning(f"[Reflect] tick={tick} 反思子回合失败(跳过): {exc}")

        # ── 内生扰动：世界自己掷点触发变局事件（复用运营手动神谕的同一事件库）──
        self._maybe_trigger_ambient_event(state, tick)

        # ── 场景声明的淘汰条件（须在终局判定之前）──
        self._check_eliminations(tick)

        # ── 终局：满足场景终止条件后调用场景结算插件 ──
        audit_cfg = self._runtime.audit_cfg or {}
        tick_limit = int(audit_cfg.get("tick_limit", 0) or 0)
        # 终局前排干残留测评结果（原实现依赖永远为空的 _capability_tasks 集合，
        # 这段从未执行过；C 方案后结果全部走队列，直接 drain 即可）。
        if tick_limit and tick >= tick_limit:
            terminal_assessment = self._drain_capability_results()
            if terminal_assessment["cases"]:
                self._commit_os2_assessment_facts(
                    tick=tick,
                    assessment_tick=terminal_assessment,
                    state=state,
                )
                await self._run_os2_director_agent(tick=tick, state=state)
                self._apply_os2_director_plan(self._pending_package)
                logger.info(
                    "[CapabilityNode] 终局前完成剩余测评案例 %s 条",
                    len(terminal_assessment["cases"]),
                )
        self._check_terminal_settlement(state, tick)

        # 终局检查
        if state.is_game_over:
            final_records = list(
                getattr(self, "_last_final_os2_settlements", []) or []
            )
            if final_records:
                await self._run_os2_director_agent(
                    tick=tick,
                    state=state,
                    events=self._os2_event_ledger.all(),
                    settlements=final_records,
                )
                if self._pending_package is not None:
                    self._apply_os2_director_plan(self._pending_package)
            logger.info(f"[EngineOS] 游戏结束，胜者: {state.winner_id}")
            run_dir = self._trace.finalize(state)
            if run_dir and self._replay_recorder:
                from pathlib import Path
                self._replay_recorder.export_to(
                    str(Path(run_dir) / "replay_deterministic.json")
                )
            # 终局：把本局 memory 提炼成一条总结写入跨局 long_term_memory，
            # 下一局 charter 渲染时会把最近几局的总结注入 system prompt。
            self._seal_long_term_memory(state)
            self._detach_run_logfile()
            # viewer 只能从 PresentationBuffer 看到终局，禁止 simulation
            # state 越过演绎时间线提前泄露；operator 仍可从日志审计。

            # 终局广播：通知前端游戏已结束，包含 is_game_over 和 winner_id
            await self._broadcast_snapshot()
            # 回填 pending_package 的快照：_collect_snapshot 在终局结算前采集，
            # 包里嵌的是旧快照（is_game_over=false）。缓冲播放时内嵌快照会把独立广播
            # 的胜者状态覆盖掉。这里补上终局状态，保证前端不再需要刷新页面。
            if self._pending_package is not None:
                self._pending_package.world_snapshot = self._collect_snapshot()

    # ── 辅助 ────────────────────────────────────────────────────────────

    def _elimination_cfg(self) -> Dict[str, Any]:
        cfg = (self._runtime.audit_cfg or {}).get("elimination", {})
        return cfg if isinstance(cfg, dict) else {}

    def _current_suspicion(self, agent_id: str, metric: str) -> float:
        metrics = (self._world_state.state.internal.get("metrics", {})
                   if self._world_state.state else {})
        agent_metrics = metrics.get(agent_id, {}) if isinstance(metrics, dict) else {}
        try:
            return float(agent_metrics.get(metric, 0.0) or 0.0)
        except (TypeError, ValueError):
            return 0.0

    def _maybe_trigger_ambient_event(self, state: Any, tick: int) -> None:
        """内生扰动：世界自身按概率触发变局事件，不等运营手动投放。

        事件从场景包 variables.yaml（与运营台"预设变局"同一事件库）里抽，
        走 inject_oracle 通道落地（Agent 下拍以突发变故感知 + 导演高光 +
        结构化效果），完全复用现有链路。节流规则：开局 6 拍不扰动（让格局
        先自然成型）、单局最多 3 次、两次至少间隔 5 拍、每拍 12% 概率。
        一个完全可预测的世界里，最优策略也是可预测的——扰动是涌现的氧气。
        """
        if tick < 6 or state.is_game_over:
            return
        ambient = state.internal.setdefault(
            "ambient_events", {"count": 0, "last_tick": -99, "used_ids": []}
        )
        if ambient["count"] >= 3 or tick - ambient["last_tick"] < 5:
            return
        import random as _random
        if _random.random() >= 0.12:
            return
        variables = list(getattr(self._loaded, "world_variables", []) or [])
        pool = [
            v for v in variables
            if getattr(v, "id", None) not in set(ambient["used_ids"])
        ]
        if not pool:
            return
        event = _random.choice(pool)
        ambient["count"] += 1
        ambient["last_tick"] = tick
        ambient["used_ids"].append(getattr(event, "id", ""))
        text = str(getattr(event, "text", "") or "")
        effects = list(getattr(event, "effects", None) or [])
        try:
            # inject_oracle 是 async 但只做队列 append；此处在事件循环内，
            # 直接构造同样的队列项，避免嵌套 await 的调度复杂度。
            items = getattr(self, "_pending_oracle_items", None)
            if items is None:
                items = []
                self._pending_oracle_items = items
            items.append({"target": "all", "text": text, "effects": effects})
            logger.info(
                "[Ambient] tick=%s 世界内生变局触发:「%s」",
                tick, getattr(event, "label", getattr(event, "id", "?")),
            )
        except Exception as exc:
            logger.warning(f"[Ambient] 内生事件注入失败(跳过): {exc}")

    def _world_goals_cfg(self) -> List[Dict[str, Any]]:
        audit_cfg = self._runtime.audit_cfg or {}
        goals = audit_cfg.get("world_goals") or []
        return [g for g in goals if isinstance(g, dict) and g.get("id")]

    def _evaluate_world_goals(self, state: Any, tick: int) -> None:
        """每拍评估世界状态目标（audit.yaml world_goals）。

        - metric 条件：读该 agent 当前指标；
        - object_core 条件：读对象当前核心值，并按状态账本正向贡献归因
          ——把对象推过线的"主要推动者"才算达成，防止搭便车；
        - at_final=true 的条件（如"终局时某淘汰指标仍低"）留给终局审计评，
          此处跳过；
        - 达成后写入 state.internal["world_goals_achieved"]，一经达成不撤销
          （事实成就的意义就在于"做成了就是做成了"）。
        """
        goals = self._world_goals_cfg()
        if not goals:
            return
        achieved: Dict[str, List[Dict[str, Any]]] = state.internal.setdefault(
            "world_goals_achieved", {}
        )
        metrics_map = state.internal.get("metrics", {}) or {}
        ctx = self._evaluation.context

        def _already(aid: str, gid: str) -> bool:
            return any(g.get("id") == gid for g in achieved.get(aid, []))

        def _mark(aid: str, goal: Dict[str, Any]) -> None:
            achieved.setdefault(aid, []).append({
                "id": goal["id"], "name": goal.get("name", goal["id"]),
                "tick": tick, "bonus": float(goal.get("bonus", 0) or 0),
            })
            logger.info(
                "[WorldGoal] tick=%s %s 达成「%s」",
                tick, aid, goal.get("name", goal["id"]),
            )

        for goal in goals:
            cond = goal.get("condition") or {}
            if cond.get("at_final"):
                continue
            kind = str(cond.get("kind", ""))
            if kind in ("metric_gte", "metric_lte"):
                metric = str(cond.get("metric", ""))
                threshold = float(cond.get("value", 0) or 0)
                for aid in getattr(state, "alive_agent_ids", []) or []:
                    if _already(aid, goal["id"]):
                        continue
                    val = float((metrics_map.get(aid) or {}).get(metric, 0) or 0)
                    ok = val >= threshold if kind == "metric_gte" else val <= threshold
                    if ok:
                        _mark(aid, goal)
            elif kind == "object_core_gte" and ctx is not None:
                object_id = str(cond.get("object_id", ""))
                threshold = float(cond.get("value", 0) or 0)
                try:
                    obj = ctx.objects.get(object_id)
                except Exception:
                    continue
                try:
                    core = float(obj.core_value())
                except Exception:
                    continue
                if core < threshold:
                    continue
                # 归因：状态账本里对该对象的正向核心贡献之和最大者
                contributions: Dict[str, float] = {}
                try:
                    for entry in getattr(ctx.deltas, "ledger", []) or []:
                        if getattr(entry, "object_id", "") != object_id:
                            continue
                        actor = getattr(entry, "actor_id", None)
                        if not actor:
                            continue
                        gain = float(entry.after_core) - float(entry.before_core)
                        if gain > 0:
                            contributions[actor] = contributions.get(actor, 0.0) + gain
                except Exception:
                    continue
                if not contributions:
                    continue
                top_actor = max(contributions, key=contributions.get)
                if not _already(top_actor, goal["id"]):
                    _mark(top_actor, goal)

    def _check_eliminations(self, tick: int) -> None:
        """每 tick 末尾执行场景声明的指标阈值淘汰规则。"""
        state = self._world_state.state
        if state is None:
            return
        cfg = self._elimination_cfg()
        threshold = cfg.get("threshold", cfg.get("suspicion_threshold"))
        if threshold is None:
            return
        threshold = float(threshold)
        metric = str(cfg.get("metric") or cfg.get("suspicion_metric") or "")
        if not metric:
            return
        # 方向：above=指标 >= 阈值淘汰（如某淘汰指标触顶）；below=指标 <= 阈值
        # 淘汰（如组合跌破生存线清盘）。默认 above，保证既有场景零行为变化。
        direction = str(cfg.get("direction") or "above").lower()
        already = {
            e.get("agent_id") for e in state.eliminated if isinstance(e, dict)
        }
        metrics_table = state.internal.get("metrics", {}) or {}
        for agent_id in list(state.alive_agent_ids):
            if agent_id in already:
                continue
            # 阈值淘汰必须建立在"已测量到的指标"之上：若该 agent 的这项指标
            # 还没被结算写入（如开局首拍尚无任何成交/估值），一个尚未测量的
            # 值不能被判成"跌破生存线"。跳过，避免开局即误淘汰全员。
            agent_metrics = metrics_table.get(agent_id, {})
            if not isinstance(agent_metrics, dict) or metric not in agent_metrics:
                continue
            value = self._current_suspicion(agent_id, metric)
            hit = value <= threshold if direction == "below" else value >= threshold
            if hit:
                state.eliminated.append({
                    "agent_id": agent_id,
                    "tick": tick,
                    "reason": str(cfg.get("reason_code") or "metric_threshold"),
                })
                logger.warning(
                    "[elimination] agent=%s tick=%d metric=%s threshold=%.2f",
                    agent_id, tick, metric, threshold,
                )
                self._queue_elimination_event(agent_id=agent_id, tick=tick)

    def _queue_elimination_event(self, *, agent_id: str, tick: int) -> None:
        """Commit elimination through facts so the director cannot bypass truth."""
        name = self._display_name(agent_id)
        cfg = self._elimination_cfg()
        template_data = {"name": name, "agent_id": agent_id, "tick": tick}
        summary = str(
            cfg.get("subtitle_template") or "{name}触发淘汰条件，退出当前世界。"
        ).format(**template_data)
        self._queue_os2_system_event(
            event_id=f"event:{tick}:eliminated:{agent_id}",
            event_type="agent_eliminated",
            public_summary=summary,
            actor_id=agent_id,
            target_ids=[agent_id],
            deltas={"eliminated": True, "reason": "scene_elimination_rule"},
        )

    def _record_tick_verdict(
        self, action: Any, result: Any, tick: int,
    ) -> None:
        """失败反馈闭环：把本拍裁决的"为什么没成"记下来，下一拍拼进该
        agent 简报的"上一拍复盘"。只记失败类结果（invalid/no_effect/
        backlash），成功则清掉旧记录——反馈的意义在于失败可学习。"""
        agent_id = action.agent_id
        outcome = str(getattr(result, "outcome", "") or "")
        prop = getattr(result, "proposal", None)
        text = ""
        if outcome == "invalid":
            validation = getattr(result, "validation", None)
            reason = str(getattr(validation, "reason", "") or "被合法性校验拦下")
            text = f"你上一拍的「{action.action_id}」被判无效：{reason[:80]}"
        elif prop is not None and getattr(prop, "backlash", False):
            reason = str(getattr(prop, "backlash_reason", "") or "冒进反噬")
            text = f"你上一拍的「{action.action_id}」遭到反噬：{reason[:80]}"
        elif outcome == "no_effect" and prop is not None:
            reason = str(getattr(prop, "no_effect_reason", "") or "没有产生实际影响")
            text = f"你上一拍的「{action.action_id}」打了水漂：{reason[:80]}"
        if text:
            self._last_tick_verdicts[agent_id] = {"tick": tick, "text": text}
        else:
            self._last_tick_verdicts.pop(agent_id, None)

    async def _notify_external_turn_results(
        self,
        tick: int,
        actions: Dict[str, Any],
        pipeline_results: List[Any],
    ) -> None:
        if not self._user_id:
            return
        from app.agent_gateway.session_bus import get_session_bus

        bus = get_session_bus()
        results_by_agent = {pr.agent_id: pr for pr in pipeline_results}
        for slot in self._cfg.agents:
            if str(getattr(slot, "driver", "llm")).strip().lower() != "agent":
                continue
            aid = slot.id
            action = actions.get(aid)
            if action is None:
                continue
            turn_id = f"{self._trace.run_id}:t{tick}:{aid}"
            pr = results_by_agent.get(aid)
            verdict: Dict[str, Any] = {}
            if pr is not None:
                outcome = str(getattr(pr, "outcome", "") or "")
                verdict = {
                    "status": outcome or "processed",
                    "summary": str(getattr(pr, "summary", "") or "")[:200],
                }
            elif aid in self._last_tick_verdicts:
                verdict = {
                    "status": "feedback",
                    "summary": str(self._last_tick_verdicts[aid].get("text", ""))[:200],
                }
            try:
                await bus.notify_turn_result(
                    user_id=self._user_id,
                    slot_id=aid,
                    turn_id=turn_id,
                    accepted=bool(getattr(action, "parsed_ok", False)),
                    resolved_action_id=str(getattr(action, "action_id", "") or ""),
                    verdict=verdict,
                    is_system_fallback=bool(getattr(action, "is_system_fallback", False)),
                )
            except Exception as exc:
                logger.debug("[ExternalAgent] turn_result 推送失败 %s: %s", aid, exc)

    async def _notify_external_world_over(self, summary: Optional[Dict[str, Any]] = None) -> None:
        if not self._user_id:
            return
        from app.agent_gateway.session_bus import get_session_bus

        bus = get_session_bus()
        for slot in self._cfg.agents:
            if str(getattr(slot, "driver", "llm")).strip().lower() != "agent":
                continue
            try:
                await bus.notify_world_over(
                    user_id=self._user_id,
                    slot_id=slot.id,
                    summary=summary,
                )
            except Exception as exc:
                logger.debug("[ExternalAgent] world_over 推送失败 %s: %s", slot.id, exc)

    def _penalize_challenge_delay(
        self,
        valid_actions: Dict[str, Any],
        tick: int,
        penalty: float = 5.0,
    ) -> None:
        """挑战拖延惩罚：有待答挑战却未选 challenge 类动作的角色，按场景声明的惩罚指标 +penalty。

        只对本回合提交了合法动作的角色生效（超时/连接失败的角色已在其他地方
        处理，不重复惩罚）。惩罚写入正式 metric delta，可供导演叙述。
        """
        if not self._active_challenge_coord or not self._active_challenge_pending_agents:
            return
        challenge_title = getattr(self._active_challenge_coord, "title", "当前挑战")
        for aid, action in valid_actions.items():
            if aid not in self._active_challenge_pending_agents:
                continue
            if action is None or self._is_challenge_action(
                str(getattr(action, "action_id", "") or "")
            ):
                continue
            # 网络/超时兜底动作不算"主动拖延"，跳过惩罚
            if _is_network_fallback(action):
                logger.info(
                    "[challenge_delay] agent=%s tick=%d 网络兜底，跳过拖延惩罚", aid, tick,
                )
                continue
            # 角色有待处理能力任务却主动选择其他动作，应用场景声明的后果。
            elimination_cfg = self._elimination_cfg() or {}
            penalty_metric = str(
                elimination_cfg.get("metric")
                or elimination_cfg.get("suspicion_metric") or ""
            )
            if not penalty_metric:
                continue
            reason = str(
                elimination_cfg.get("delay_reason_template")
                or "延迟应对《{challenge_title}》，触发场景惩罚。"
            ).format(challenge_title=challenge_title, agent_id=aid)
            self._apply_interaction_metric_delta(
                agent_id=aid,
                metric=penalty_metric,
                delta=penalty,
                source_object_id=str(
                    elimination_cfg.get(
                        "penalty_source_object", "system"
                    )
                ),
                tick=tick,
                linked_action_id=getattr(action, "action_id", ""),
                reason=reason,
            )
            logger.info(
                "[challenge_delay] agent=%s tick=%d 拖延作答《%s》，惩罚指标 +%.0f",
                aid, tick, challenge_title, penalty,
            )
            try:
                self._record_agent_memory(
                    agent_id=aid, tick=tick,
                    summary=f"【拖延作答惩罚】未应对《{challenge_title}》，触发场景惩罚 +{penalty:.0f}",
                )
            except Exception:
                pass

    def _route_submit_challenge_response_actions(
        self,
        valid_actions: Dict[str, Any],
        tick: int,
    ) -> None:
        """P0-e（C方案）：把主回合的 challenge 类动作直接交给当前激活的
        挑战协调器评分提交，不走常规因果管线。

        - 没有激活挑战则忽略此动作（agent 不应在此时选择 challenge 类动作）。
        - 同一任务内多个角色完成后，所有 cases/events 合并成一个
          batch 推入 _capability_result_queue，与旧子回合路径完全等价。
        - 待处理角色集合排空后关闭该任务。
        """
        coord = self._active_challenge_coord
        if coord is None:
            return
        from app.framework.capability.node_coordinator import NodeResult
        if self._active_challenge_result is None:
            self._active_challenge_result = NodeResult(
                node_id=getattr(coord, "node_id", ""), tick=tick,
            )
        result = self._active_challenge_result
        events: List[Any] = []
        cases: List[Any] = []
        agent_ids_order = list(self._agent_runtime.agent_ids)
        progressed = False
        for agent_id, action in list(valid_actions.items()):
            if action is None or not self._is_challenge_action(
                str(getattr(action, "action_id", "") or "")
            ):
                continue
            if agent_id not in self._active_challenge_pending_agents:
                # 已答过：忽略重复作答
                continue
            try:
                idx = agent_ids_order.index(agent_id)
            except ValueError:
                idx = 0
            event_start = len(events)
            ok = coord.commit_external_answer(
                tick=tick, agent_id=agent_id, agent_idx=idx,
                action_pack=action,
                event_sink=events.append,
                case_sink=cases.append,
                result=result,
            )
            if ok:
                self._active_challenge_pending_agents.discard(agent_id)
                progressed = True
                # 能力事件只记录事实，不执行任何世界状态副作用。
                for event_index in range(event_start, len(events)):
                    event = events[event_index]
                    self._world_state.add_event(event)
                logger.info(
                    f"[P0-e] 挑战作答提交 node={coord.node_id} "
                    f"agent={agent_id} 剩余={len(self._active_challenge_pending_agents)}"
                )
                # Memory hook：挑战作答结果按 agent 视角记入本局 memory.md
                try:
                    last_case = (
                        result.cases[-1] if getattr(result, "cases", None) else None
                    )
                    passed = (
                        getattr(getattr(last_case, "verification", None),
                                "passed", None)
                    )
                    cap = getattr(last_case, "capability", "") if last_case else ""
                    verb = "答对" if passed else (
                        "答错" if passed is False else "应对"
                    )
                    mem = f"【{coord.title}·{cap}】{verb}"
                    self._record_agent_memory(
                        agent_id=agent_id, tick=tick, summary=mem,
                    )
                    # 挑战因果钩子：结果记入 challenge_history，供后续挑战和导演引用
                    self._record_challenge_history(
                        coord=coord, agent_id=agent_id,
                        passed=passed, tick=tick,
                    )
                except Exception:
                    pass
        if events or cases:
            # 推入与旧路径同形态的 batch；drain 时按 challenge_order 闸门统一处理
            try:
                self._capability_result_queue.put_nowait({
                    "node_id": getattr(coord, "node_id", ""),
                    "cases": cases,
                    "events": events,
                })
            except asyncio.QueueFull:
                logger.warning(
                    "[P0-e] capability_result_queue 已满，本拍挑战结果延迟"
                )
        # 全员答完 → 落幕该挑战
        if progressed and not self._active_challenge_pending_agents:
            coord.mark_fired()
            logger.info(
                f"[P0-e] 挑战《{getattr(coord,'title','')}》作答完毕，"
                f"共 {len(self._active_challenge_result.cases)} 例提交"
            )
            self._active_challenge_coord = None
            self._active_challenge_result = None
            self._last_challenge_closed_tick = tick

    def _record_challenge_history(
        self, *, coord: Any, agent_id: str, passed: Any, tick: int,
    ) -> None:
        """挑战因果钩子：把每项挑战各人作答结果记入 state.internal["challenge_history"]。

        结构：[{order, title, tick, results: {agent_id: True/False/None}}]
        后续挑战通过它渲染“前次挑战回响”，导演挑战块用它保持连续性。
        """
        state = self._world_state.state
        if state is None:
            return
        history = state.internal.setdefault("challenge_history", [])
        order = int(getattr(coord, "challenge_order", 0) or 0)
        title = str(getattr(coord, "title", "") or "")
        entry = next(
            (h for h in history if h.get("order") == order), None
        )
        if entry is None:
            entry = {"order": order, "title": title, "tick": tick, "results": {}}
            history.append(entry)
        entry["results"][agent_id] = passed

    def _agent_last_challenge_passed(self, agent_id: str) -> Any:
        """该 agent 最近一次已答挑战的对错（True/False/None）。"""
        state = self._world_state.state
        if state is None:
            return None
        history = state.internal.get("challenge_history", []) or []
        for h in sorted(history, key=lambda x: -(x.get("order", 0))):
            results = h.get("results", {}) or {}
            if agent_id in results:
                return results[agent_id]
        return None

    def _challenge_history_summary(self, exclude_order: int = 0) -> List[str]:
        """把 challenge_history 组织成可读的前次挑战回响（最近三项）。"""
        state = self._world_state.state
        if state is None:
            return []
        history = state.internal.get("challenge_history", []) or []
        lines: List[str] = []
        for h in sorted(history, key=lambda x: x.get("order", 0))[-3:]:
            if exclude_order and h.get("order") == exclude_order:
                continue
            results = h.get("results", {}) or {}
            right = [self._display_name(a) for a, p in results.items() if p is True]
            wrong = [self._display_name(a) for a, p in results.items() if p is False]
            seg = f"第{h.get('order')}章《{h.get('title')}》："
            if right:
                seg += f"{'、'.join(right)}判断正确"
            if wrong:
                seg += f"{'；' if right else ''}{'、'.join(wrong)}失手"
            if not right and not wrong:
                seg += "已落幕"
            lines.append(seg)
        return lines

    def _seal_long_term_memory(self, state: Any) -> None:
        """终局触发：把本局 memory 提炼成一条总结写入跨局 long_term_memory。

        失败不抛——长期记忆持久化不应影响主流程结束。
        """
        try:
            run_id = getattr(self._trace, "run_id", "") or ""
            winner_id = getattr(state, "winner_id", None)
            internal = getattr(state, "internal", {}) or {}
            standings = list(internal.get("victory_standings", []) or [])
            values_by_agent = {
                str(item.get("agent_id")): dict(item.get("values") or {})
                for item in standings
                if isinstance(item, dict) and item.get("agent_id")
            }
            rank_map = {
                str(item.get("agent_id")): int(item.get("rank") or 0)
                for item in standings
                if isinstance(item, dict) and item.get("agent_id")
            }
            for ws in self._agent_workspaces.all():
                aid = ws.agent_id
                outcome_note = ""
                if winner_id == aid:
                    outcome_note = "本局取胜。"
                elif winner_id:
                    outcome_note = f"本局败于 {winner_id}。"
                else:
                    outcome_note = "本局未分胜负。"
                ws.seal_to_long_term(
                    run_id=run_id,
                    victory_rank=rank_map.get(aid),
                    final_metrics=values_by_agent.get(aid),
                    outcome_note=outcome_note,
                )
            logger.info(
                f"[AgentWorkspace] 跨局长期记忆已封存 run={run_id} "
                f"winner={winner_id}"
            )
        except Exception as exc:
            logger.warning(f"[AgentWorkspace] 跨局记忆封存失败: {exc}")

    def _write_settlement_memory(self, tick: int, settlements: List[Any]) -> None:
        """把本拍结算的 outcome + 解释写入相关 agent 的本局记忆。

        通用透传：outcome/explanation 都是场景结算插件产的文本，OS 不解释。
        每个 agent 每拍至多两条、每条截断，防止记忆被高频结算刷爆。
        """
        per_agent: Dict[str, List[str]] = {}
        for record in settlements or []:
            outcome = str(getattr(record, "outcome", "") or "")
            explanation = str(getattr(record, "explanation", "") or "").strip()
            if not outcome and not explanation:
                continue
            text = outcome + (f"：{explanation[:90]}" if explanation else "")
            for subject in getattr(record, "subject_ids", []) or []:
                lines = per_agent.setdefault(str(subject), [])
                if text not in lines:
                    lines.append(text)
        for agent_id, lines in per_agent.items():
            self._record_agent_memory(
                agent_id=agent_id, tick=tick, summary="；".join(lines[:2]),
            )

    def _record_agent_memory(
        self,
        *,
        agent_id: str,
        tick: int,
        summary: str,
    ) -> None:
        """统一入口：把关键事件写入 agent 的本局 memory.md。

        Memory bug 修复（前一局 memory.md 全部为空的根因）：先前 OS 注释
        声称会"自动追加关键事件"，但 hook 从未接上。这里在因果/挑战关键节点
        统一调用，按 agent 视角写入。失败不抛，长期记忆失败不应影响主循环。
        """
        if not agent_id or not summary:
            return
        try:
            ws = self._agent_workspaces.get(agent_id)
            if ws is not None:
                ws.append_memory(tick, summary)
        except Exception as exc:
            logger.debug(
                f"[AgentWorkspace] append_memory 失败 {agent_id}: {exc}"
            )

    def _maybe_create_investigation_evidence(
        self,
        *,
        action: Any,
        action_rule: Optional[Dict[str, Any]],
        result: Any,
        tool_results: Dict[str, Any],
    ) -> None:
        """P0-a: 调查类动作成功作用于关键对象时产出标准 EvidenceEntry。

        证据是调查的世界产物：让 agent 真正「掌握证据」、导演可引用、
        TruthGuard 不再因「无证据引用」否决正向戏剧。指标仍由因果链派生，
        本函数不直接改任何指标（遵守「动作不得直接改指标」铁律）。
        """
        if getattr(result, "outcome", None) != "success":
            return
        if not action_rule or action_rule.get("category") != "investigation":
            return
        target = getattr(action, "target_object_id", None)
        if not target:
            return
        ev_svc = getattr(self._action_runtime, "_evidence_service", None)
        if ev_svc is None:
            return
        # 若该动作已通过工具产出证据，则不重复生成。
        tr = tool_results.get(getattr(action, "agent_id", None))
        if tr is not None and getattr(tr, "evidence_candidate_ids", None):
            return
        quality = 0.5
        try:
            if getattr(result, "evaluation", None) is not None:
                quality = float(
                    getattr(result.evaluation, "execution_quality", 0.5) or 0.5
                )
        except (TypeError, ValueError):
            quality = 0.5
        confidence = round(min(0.9, 0.4 + quality * 0.5), 3)
        role_name = self._role_names.get(action.agent_id, action.agent_id)
        action_name = action_rule.get("name", action.action_id)
        try:
            entry = ev_svc.create(
                creator_id=action.agent_id,
                target_id=target,
                claim=f"{role_name}通过「{action_name}」核验了{target}，获得可追溯的调查结论。",
                source_action_id=action.action_id,
                confidence=confidence,
            )
            logger.info(
                f"[L5] 调查产出证据 agent={action.agent_id} "
                f"action={action.action_id} target={target} "
                f"evidence={entry.evidence_id} conf={confidence}"
            )
        except Exception as exc:
            logger.warning(f"[L5] 调查证据生成失败 agent={action.agent_id}: {exc}")

    def _commit_os2_tick(
        self,
        *,
        tick: int,
        valid_actions: Dict[str, Any],
        pipeline_results: List[Any],
        logs: List[Any],
        state: Any,
    ) -> None:
        """Commit one tick to the authoritative OS 2.0 fact chain."""
        from app.contracts.os2 import WorldAction as OS2WorldAction
        from app.contracts.os2 import WorldEvent as OS2WorldEvent
        from app.contracts.os2 import ExternalObservation
        from app.contracts.os2 import AgentActivityFact
        from app.engine.evaluation.settlement import SettlementContext

        run_id = self._trace.run_id or "run_pending"
        scenario_id = (
            str(getattr(self._runtime, "scenario_id", "") or "")
            or self._runtime.scenario_name
        )
        results = {str(item.agent_id): item for item in pipeline_results}
        log_map = {str(item.agent_id): item for item in logs}
        world_actions: List[Any] = []
        observations: List[Any] = []
        agent_activities: List[Any] = []
        world_events: List[Any] = []
        observation_runtime = getattr(self, "_os2_observations", None)
        if observation_runtime is None:
            observation_runtime = self._os2_settlement.observations
            self._os2_observations = observation_runtime
        loaded = getattr(self, "_loaded", None)
        settlement_cfg = getattr(loaded, "settlement_cfg", {}) or {}

        for raw_event in list(
            getattr(self, "_pending_os2_system_events", []) or []
        ):
            world_events.append(OS2WorldEvent(
                event_id=str(raw_event["event_id"]),
                run_id=run_id,
                scenario_id=scenario_id,
                world_tick=tick,
                event_type=str(raw_event["event_type"]),
                origin="system",
                actor_id=raw_event.get("actor_id"),
                target_ids=list(raw_event.get("target_ids") or []),
                deltas=dict(raw_event.get("deltas") or {}),
                visibility="public",
                public_summary=str(raw_event.get("public_summary") or ""),
            ))
        self._pending_os2_system_events = []

        for agent_id in sorted(valid_actions, key=str):
            action = valid_actions[agent_id]
            if action is None:
                continue
            result = results.get(str(agent_id))
            action_ref = f"action:{tick}:{agent_id}"
            harness_ref = f"htrace:{tick}:{agent_id}"
            log = log_map.get(str(agent_id))
            if log is not None and isinstance(log.harness_trace, dict):
                harness_ref = str(log.harness_trace.get("trace_id") or harness_ref)

            targets = [
                str(item) for item in (
                    getattr(action, "target_object_id", None),
                    getattr(action, "target_agent_id", None),
                ) if item
            ]
            adapter_receipt = (
                getattr(result, "world_action_receipt", None)
                if result is not None else None
            )
            action_status = "executed"
            rejection_reasons: List[str] = []
            if adapter_receipt is not None:
                if adapter_receipt.status == "rejected":
                    action_status = "rejected"
                    rejection_reasons = list(adapter_receipt.reasons)
                elif adapter_receipt.status == "failed":
                    action_status = "failed"
                    rejection_reasons = list(adapter_receipt.reasons)
            os2_action = OS2WorldAction(
                action_id=action_ref,
                run_id=run_id,
                scenario_id=scenario_id,
                world_tick=tick,
                actor_id=str(agent_id),
                action_type=str(getattr(action, "action_id", "") or "unknown"),
                target_ids=targets,
                parameters=dict(getattr(action, "parameters", {}) or {}),
                evidence_refs=list(
                    getattr(action, "evidence_refs", [])
                    or getattr(action, "linked_evidence_ids", [])
                    or []
                ),
                harness_trace_ref=harness_ref,
                visibility="public",
                # L4 acceptance only means the OS accepted the command for
                # submission. An external world adapter may still reject or
                # fail it, and that authoritative receipt must win here.
                status=action_status,
                rejection_reasons=rejection_reasons,
            )
            world_actions.append(os2_action)
            execution_route = self._scene_execution_route(
                os2_action.action_type
            )

            observation_refs: List[str] = []
            harness_observations = list(
                os2_action.parameters.get("harness_observations", []) or []
            )
            for raw_tool_result in harness_observations:
                if not isinstance(raw_tool_result, dict) or not raw_tool_result.get("ok"):
                    continue
                observation_id = str(raw_tool_result.get("run_id") or "")
                if not observation_id or observation_runtime.get(observation_id):
                    continue
                outputs = list(raw_tool_result.get("outputs") or [])
                normalized = outputs[0] if outputs and isinstance(outputs[0], dict) else {
                    "summary": str(outputs[0]) if outputs else ""
                }
                source_name = str(raw_tool_result.get("source") or "agent_tool")
                trusted_external = source_name in {
                    "mcp", "external_reality", "verified_external"
                }
                observed_at = time.time()
                observation = ExternalObservation(
                    observation_id=observation_id,
                    run_id=run_id,
                    scenario_id=scenario_id,
                    world_tick=tick,
                    provider_id=source_name,
                    observation_type="agent_tool_result",
                    subject_id=str(normalized.get("asset_id") or normalized.get("symbol") or agent_id),
                    raw_value=dict(raw_tool_result),
                    normalized_value=dict(normalized),
                    unit=str(normalized.get("unit") or ""),
                    source_uri=str(normalized.get("source_uri") or f"agent-tool://{observation_id}"),
                    source_hash=observation_runtime.content_hash(raw_tool_result),
                    request_parameters={},
                    observed_at=observed_at,
                    freshness_status="fresh" if trusted_external else "unknown",
                    verification_status="verified" if trusted_external else "pending",
                    confidence=float(
                        normalized.get("confidence", 1.0 if trusted_external else 0.0)
                        or 0.0
                    ),
                )
                observation_runtime.append(observation)
                observations.append(observation)
                observation_refs.append(observation_id)
            for evidence_ref in os2_action.evidence_refs:
                observation_cfg: Dict[str, Any] = {}
                raw_source: Any = None
                for declared in settlement_cfg.get("observations", []) or []:
                    if not isinstance(declared, dict):
                        continue
                    registry = state.internal.get(
                        str(declared.get("registry_path") or ""), {}
                    )
                    candidate = (
                        registry.get(evidence_ref)
                        if isinstance(registry, dict) else None
                    )
                    if isinstance(candidate, dict):
                        observation_cfg = declared
                        raw_source = candidate
                        break
                if not isinstance(raw_source, dict):
                    continue
                observation_id = str(evidence_ref)
                existing = observation_runtime.get(observation_id)
                if existing is None:
                    observed_at = float(
                        raw_source.get("observed_at")
                        or raw_source.get("timestamp")
                        or time.time()
                    )
                    observation = ExternalObservation(
                        observation_id=observation_id,
                        run_id=run_id,
                        scenario_id=scenario_id,
                        world_tick=tick,
                        provider_id=str(
                            raw_source.get("provider_id")
                            or observation_cfg.get("provider_id")
                            or "verified_evidence_registry"
                        ),
                        observation_type=str(
                            observation_cfg.get("observation_type")
                            or "external_value"
                        ),
                        subject_id=str(
                            raw_source.get(str(
                                observation_cfg.get("subject_field")
                                or "subject_id"
                            ))
                            or raw_source.get("subject_id")
                            or evidence_ref
                        ),
                        raw_value=dict(raw_source),
                        normalized_value={
                            str(field): raw_source.get(str(field))
                            for field in (
                                observation_cfg.get("normalized_fields", [])
                                or []
                            )
                        } or dict(raw_source),
                        unit=str(
                            raw_source.get("unit")
                            or observation_cfg.get("unit")
                            or ""
                        ),
                        source_uri=str(
                            raw_source.get("source_uri")
                            or f"verified-registry://{evidence_ref}"
                        ),
                        source_hash=observation_runtime.content_hash(
                            raw_source
                        ),
                        request_parameters=dict(
                            raw_source.get("request_parameters") or {}
                        ),
                        observed_at=observed_at,
                        freshness_status=str(
                            raw_source.get("freshness_status") or "fresh"
                        ),
                        verification_status="verified",
                        confidence=float(
                            raw_source.get("confidence", 1.0) or 1.0
                        ),
                    )
                    observation_runtime.append(observation)
                    observations.append(observation)
                observation_refs.append(observation_id)

            tool_activity: List[Dict[str, Any]] = []
            for raw_tool_result in harness_observations[:4]:
                if not isinstance(raw_tool_result, dict):
                    continue
                source = str(raw_tool_result.get("source") or "")
                # Capability discovery is useful for the operator trace, but it
                # is not a viewer-facing activity. The director should narrate
                # actual data/tool attempts and results.
                if source == "capability_broker":
                    continue
                outputs = list(raw_tool_result.get("outputs") or [])
                summary = ""
                if outputs:
                    first = outputs[0]
                    if isinstance(first, dict):
                        summary = str(
                            first.get("summary")
                            or first.get("claim")
                            or first.get("source_uri")
                            or first
                        )
                    else:
                        summary = str(first)
                tool_activity.append({
                    "tool_id": str(raw_tool_result.get("tool_id") or ""),
                    "source": source,
                    "ok": bool(raw_tool_result.get("ok")),
                    "summary": summary[:260],
                    "output_refs": [str(raw_tool_result.get("run_id") or "")]
                    if raw_tool_result.get("run_id") else [],
                })

            object_deltas = []
            state_before: Dict[str, Any] = {}
            state_after: Dict[str, Any] = {}
            metric_deltas = []
            if result is not None:
                for delta in list(getattr(result, "deltas", []) or []):
                    dumped = (
                        delta.model_dump(mode="json")
                        if hasattr(delta, "model_dump") else dict(delta)
                    )
                    object_deltas.append(dumped)
                    object_id = str(dumped.get("object_id") or "")
                    if object_id:
                        state_before[object_id] = {
                            "core": dumped.get("before_core"),
                            "factors": dumped.get("before_factors", {}),
                        }
                        state_after[object_id] = {
                            "core": dumped.get("after_core"),
                            "factors": dumped.get("after_factors", {}),
                        }
                for metric in list(getattr(result, "metrics", []) or []):
                    metric_deltas.append(
                        metric.model_dump(mode="json")
                        if hasattr(metric, "model_dump") else dict(metric)
                    )
                adapter_transition = getattr(
                    result, "world_transition", None
                )
                if adapter_transition is not None:
                    state_before = dict(adapter_transition.state_before)
                    state_after = dict(adapter_transition.state_after)

            interaction_fact: Dict[str, Any] = {}
            for candidate in reversed(
                list(state.internal.get("agent_interactions", []) or [])
            ):
                metadata = candidate.get("metadata", {}) or {}
                if (
                    int(candidate.get("tick", -1) or -1) == tick
                    and str(candidate.get("source_id") or "") == str(agent_id)
                    and str(metadata.get("action_id") or "")
                    == os2_action.action_type
                ):
                    interaction_fact = {
                        "event_type": str(candidate.get("event_type") or ""),
                        "summary": str(candidate.get("summary") or ""),
                        "resolution": metadata.get("interaction_resolution"),
                        "applied_effects": list(
                            metadata.get("applied_effects") or []
                        ),
                        "proposal_settlement": metadata.get(
                            "proposal_settlement"
                        ),
                    }
                    break

            action_rule = self._scene_action_rule(
                os2_action.action_type
            ) or {}
            action_label = str(
                getattr(action, "action_name", "")
                or action_rule.get("name")
                or (
                    getattr(
                        getattr(self._runtime, "vocabulary", None),
                        "terminology",
                        {},
                    ) or {}
                ).get(os2_action.action_type)
                or "场景行动"
            )
            # 公开策略摘要优先取模型显式字段；若模型漏填，runtime 已从 plan/text 回填。
            # 此处不再二次从 text/plan 拼，也不从独白回退，避免与「操盘思路」串线。
            public_reasoning = str(
                getattr(action, "public_reasoning_summary", "") or ""
            ).strip()
            status = "fallback" if _is_network_fallback(action) else (
                "rejected"
                if os2_action.status in {"rejected", "failed"}
                else "executed"
            )
            try:
                activity = AgentActivityFact(
                    activity_id=f"activity:{tick}:{agent_id}",
                    run_id=run_id,
                    scenario_id=scenario_id,
                    world_tick=tick,
                    agent_id=str(agent_id),
                    source_action_ref=action_ref,
                    harness_trace_ref=harness_ref,
                    action_type=os2_action.action_type,
                    action_label=action_label,
                    target_ids=targets,
                    public_intent=str(getattr(action, "intent", "") or ""),
                    public_reasoning_summary=public_reasoning[:700],
                    character_monologue=str(
                        getattr(action, "character_monologue", "") or ""
                    )[:240],
                    tool_activity=tool_activity,
                    evidence_refs=list(os2_action.evidence_refs),
                    observation_refs=list(observation_refs),
                    status=status,
                    visibility="public",
                )
                agent_activities.append(activity)
            except Exception as exc:
                logger.warning(
                    "[OS2] AgentActivityFact build failed agent=%s tick=%s: %s",
                    agent_id,
                    tick,
                    exc,
                )
            event = OS2WorldEvent(
                event_id=f"event:{tick}:{agent_id}:{os2_action.action_type}",
                run_id=run_id,
                scenario_id=scenario_id,
                world_tick=tick,
                event_type="action_resolved",
                origin="action",
                actor_id=str(agent_id),
                target_ids=targets,
                source_action_ref=action_ref,
                evidence_refs=list(os2_action.evidence_refs),
                observation_refs=observation_refs,
                state_before=state_before,
                state_after=state_after,
                deltas={
                    "action_type": os2_action.action_type,
                    "outcome": (
                        adapter_receipt.status
                        if adapter_receipt is not None else "accepted"
                    ),
                    "execution": {
                        "mode": execution_route.get("mode"),
                        "provider_id": execution_route.get("provider_id"),
                    },
                    "parameters": dict(os2_action.parameters),
                    "target_object_id": str(
                        getattr(action, "target_object_id", "") or ""
                    ),
                    "target_agent_id": str(
                        getattr(action, "target_agent_id", "") or ""
                    ),
                    "interaction": interaction_fact or None,
                    "object_deltas": object_deltas,
                    "metric_deltas": metric_deltas,
                    "world_action_receipt": (
                        adapter_receipt.model_dump(mode="json")
                        if adapter_receipt is not None else None
                    ),
                    "world_transition": (
                        result.world_transition.model_dump(mode="json")
                        if result is not None
                        and result.world_transition is not None
                        else None
                    ),
                },
                visibility="public",
                public_summary=(interaction_fact.get("summary") or (
                    f"{self._display_name(str(agent_id))}提交了“{action_label}”。"
                )),
            )
            world_events.append(event)

        if world_events:
            self._os2_event_ledger.extend(world_events)

        cash_cfg = next(
            (
                item for item in (self._runtime.resources_cfg or [])
                if str(item.get("id") or "") == "cash"
            ),
            {},
        )
        context = SettlementContext(
            run_id=run_id,
            scenario_id=scenario_id,
            world_tick=tick,
            world_state={
                "agent_ids": list(getattr(state, "agent_ids", []) or []),
                "agent_names": {
                    agent_id: self._display_name(agent_id)
                    for agent_id in list(getattr(state, "agent_ids", []) or [])
                },
                "alive_agent_ids": list(
                    getattr(state, "alive_agent_ids", []) or []
                ),
                "resources": dict(getattr(state, "resources", {}) or {}),
                "initial_cash": float(cash_cfg.get("initial", 1_000_000.0)),
                "round_phase": self._current_round_phase(tick),
                "verified_market_prices": dict(
                    state.internal.get("verified_market_prices", {}) or {}
                ),
                "evidence_validity_ticks": int(
                    settlement_cfg.get("evidence_validity_ticks", 0) or 0
                ),
                "research_evidence_validity_ticks": int(
                    settlement_cfg.get(
                        "research_evidence_validity_ticks", 0
                    ) or 0
                ),
                "research_requirements": dict(
                    settlement_cfg.get("research_requirements") or {}
                ),
                "fx_rates": dict(settlement_cfg.get("fx_rates") or {}),
                "trading_universe": dict(
                    settlement_cfg.get("trading_universe") or {}
                ),
                "external_observations": [
                    item.model_dump(mode="json")
                    for item in observation_runtime.all()
                ],
            },
        )
        try:
            settlements = self._os2_settlement.settle_tick(world_events, context)
        except Exception as exc:
            logger.exception(
                "[SettlementRuntime] tick=%s 场景结算失败，保留世界事实: %s",
                tick,
                exc,
            )
            settlements = []
        self._apply_settlement_metric_bindings(settlements, settlement_cfg, state)
        self._last_os2_actions = world_actions
        self._last_os2_observations = observations
        self._last_os2_agent_activities = agent_activities
        self._last_os2_events = world_events
        self._last_os2_settlements = settlements
        # 记忆闭环：把本拍结算结果（含拒单理由）写回各 agent 的 memory.md。
        # 此前记忆只有"已交由场景结算"占位，agent 永远不知道订单被拒、
        # 为什么被拒，同样的错一犯到底。outcome/explanation 由场景声明，
        # OS 只按 subject 透传，不解释业务含义。
        self._write_settlement_memory(tick, settlements)
        try:
            director_runtime = getattr(self, "_os2_director", None)
            if director_runtime is None:
                from app.engine.presentation.director_runtime import DirectorRuntime
                loaded = getattr(self, "_loaded", None)
                presentation = getattr(loaded, "presentation", None)
                director_runtime = DirectorRuntime(
                    getattr(
                        getattr(presentation, "render", None),
                        "bindings",
                        {},
                    ) or {},
                    getattr(presentation, "render", None),
                    getattr(
                        getattr(self._runtime, "vocabulary", None),
                        "terminology",
                        {},
                    ) or {},
                )
                self._os2_director = director_runtime
            director_plan = director_runtime.build_plan(
                run_id=run_id,
                scenario_id=scenario_id,
                world_tick=tick,
                events=world_events,
                settlements=settlements,
                activities=agent_activities,
            )
        except Exception as exc:
            logger.exception(
                "[DirectorRuntime] tick=%s 可信导演计划生成失败: %s",
                tick,
                exc,
            )
            director_plan = None
        self._last_os2_director_plan = director_plan

        state.internal.setdefault("os2_world_actions", []).extend(
            item.model_dump(mode="json") for item in world_actions
        )
        state.internal.setdefault("os2_external_observations", []).extend(
            item.model_dump(mode="json") for item in observations
        )
        state.internal.setdefault("os2_agent_activities", []).extend(
            item.model_dump(mode="json") for item in agent_activities
        )
        state.internal.setdefault("os2_world_events", []).extend(
            item.model_dump(mode="json") for item in world_events
        )
        state.internal.setdefault("os2_settlements", []).extend(
            item.model_dump(mode="json") for item in settlements
        )
        if director_plan is not None:
            plan_payload = director_plan.model_dump(mode="json")
            state.internal.setdefault("os2_director_plans", []).append(
                plan_payload
            )
            if getattr(self, "_pending_package", None) is not None:
                self._pending_package.director_plan = plan_payload

    def _apply_settlement_metric_bindings(
        self,
        settlements: List[Any],
        settlement_cfg: Dict[str, Any],
        state: Any,
    ) -> None:
        """把场景结算记录回写到资源 / 指标 / 简报用的 settlement_state。

        资本市场等 hybrid（混合）场景没有 RuleWorld metrics 服务时，
        仍必须回写 cash（现金）和 display_text（展示文案），否则 Agent
        简报会一直显示开局本金，导致盲目加仓。
        """
        bindings = dict(settlement_cfg.get("metric_bindings", {}) or {})
        resource_bindings = dict(
            settlement_cfg.get("resource_bindings", {}) or {}
        )
        if not settlements:
            return
        # context 可能为 None（无 simulation 路由的场景）；不能因此整段跳过。
        # _evaluation 本身也可能缺席（测试用 __new__ 构造的裸引擎）。
        eval_ctx = getattr(
            getattr(self, "_evaluation", None), "context", None
        )
        metric_service = (
            getattr(eval_ctx, "metrics", None) if eval_ctx is not None else None
        )
        transforms = {
            "identity": lambda value: value,
            "one_hundred_minus": lambda value: 100.0 - value,
            "absolute": lambda value: abs(value),
        }
        resources_touched = False
        for record in settlements:
            values = dict(getattr(record, "values", {}) or {})
            for agent_id in list(getattr(record, "subject_ids", []) or []):
                aid = str(agent_id)
                for resource_id, binding in resource_bindings.items():
                    if not isinstance(binding, dict):
                        continue
                    value_key = str(binding.get("value") or "")
                    if value_key not in values or self._resource_service is None:
                        continue
                    self._resource_service.set_from_settlement(
                        agent_id=aid,
                        resource_id=str(resource_id),
                        value=float(values[value_key]),
                        settlement_ref=str(record.settlement_id),
                    )
                    resources_touched = True
                details = dict(getattr(record, "details", {}) or {})
                if details:
                    incoming = {
                        "settlement_id": str(record.settlement_id),
                        "values": dict(values),
                        **details,
                    }
                    existing = (
                        (state.internal.get("settlement_state") or {}).get(aid)
                        or {}
                    )
                    # 拒单等无 display_text 的记录不得覆盖已有的展示文案。
                    if (
                        not incoming.get("display_text")
                        and existing.get("display_text")
                    ):
                        incoming["display_text"] = existing["display_text"]
                        if "cash" not in incoming["values"] and isinstance(
                            existing.get("values"), dict
                        ):
                            merged = dict(existing["values"])
                            merged.update(incoming["values"])
                            incoming["values"] = merged
                    state.internal.setdefault("settlement_state", {})[aid] = (
                        incoming
                    )
                for metric_id, binding in bindings.items():
                    if not isinstance(binding, dict):
                        continue
                    value_key = str(binding.get("value") or "")
                    if value_key not in values:
                        continue
                    transform_name = str(binding.get("transform") or "identity")
                    transform = transforms.get(transform_name)
                    if transform is None:
                        logger.warning(
                            "[SettlementMetric] 未知 transform=%s metric=%s",
                            transform_name, metric_id,
                        )
                        continue
                    metric_value = float(transform(float(values[value_key])))
                    if metric_service is not None:
                        metric_service.set_from_settlement(
                            agent_id=aid,
                            metric=str(metric_id),
                            value=metric_value,
                            settlement_ref=str(record.settlement_id),
                            reason=(
                                f"场景结算 {record.settlement_id} 将 {value_key} "
                                f"映射为 {metric_id}"
                            ),
                        )
                    else:
                        # hybrid / external 场景无 RuleWorld metrics：直接写入
                        # state.internal，供排名与终局判定读取。
                        metrics_table = state.internal.setdefault("metrics", {})
                        agent_metrics = metrics_table.setdefault(aid, {})
                        agent_metrics[str(metric_id)] = metric_value
        # 结算当拍即同步到 WorldState.resources，下一拍简报才能读到真实现金。
        if resources_touched and self._resource_service is not None:
            for aid in list(getattr(state, "alive_agent_ids", []) or []):
                state.resources[aid] = self._resource_service.get_all(aid)

    def _commit_os2_assessment_facts(
        self,
        *,
        tick: int,
        assessment_tick: Dict[str, Any],
        state: Any,
    ) -> None:
        """Migrate capability cases into the same trusted director fact chain."""
        cases = [
            item.model_dump(mode="json")
            if hasattr(item, "model_dump") else dict(item)
            for item in (assessment_tick.get("cases", []) or [])
        ]
        if not cases:
            return
        from app.contracts.os2 import (
            SettlementAuthority,
            SettlementRecord,
            WorldEvent as OS2WorldEvent,
        )
        from app.engine.evaluation.settlement import SettlementContext

        run_id = self._trace.run_id or "run_pending"
        scenario_id = (
            str(getattr(self._runtime, "scenario_id", "") or "")
            or self._runtime.scenario_name
        )
        events = []
        records = []
        provider_cfg = next((
            item for item in (
                (self._loaded.settlement_cfg or {}).get("providers", []) or []
            )
            if isinstance(item, dict)
            and "assessment_completed" in (item.get("handles") or [])
        ), {})
        provider_id = str(
            provider_cfg.get("id") or "capability_verifier"
        )
        rule_version = str(
            provider_cfg.get("rule_version")
            or "capability.objective_case.v1"
        )
        verifier_id = str(
            provider_cfg.get("verifier_id") or provider_id
        )
        for index, case in enumerate(cases):
            case_id = str(case.get("case_id") or f"case_{tick}_{index}")
            agent_id = str(case.get("agent_id") or "")
            capability = str(
                case.get("capability_name") or case.get("capability") or "能力"
            )
            score = float(case.get("score", 0.0) or 0.0)
            passed = bool(
                case.get("passed", case.get("status") in {"passed", "measured"})
            )
            event = OS2WorldEvent(
                event_id=f"assessment_event:{case_id}",
                run_id=run_id,
                scenario_id=scenario_id,
                world_tick=tick,
                event_type="assessment_completed",
                origin="system",
                actor_id=agent_id or None,
                target_ids=[case_id],
                deltas={
                    "case_id": case_id,
                    "capability": capability,
                    "passed": passed,
                    "score": score,
                    "status": str(case.get("status") or ""),
                },
                visibility="public",
                public_summary=(
                    f"{self._display_name(agent_id)}完成了“{capability}”能力测评，"
                    f"客观判定为{'通过' if passed else '未通过'}。"
                ),
            )
            events.append(event)
            records.append(SettlementRecord(
                settlement_id=f"capability:{case_id}",
                run_id=run_id,
                scenario_id=scenario_id,
                world_tick=tick,
                evaluator_id="ai_world.capability_sidecar.v2",
                authority=SettlementAuthority(
                    mode="deterministic_verifier",
                    provider_id=provider_id,
                    verifier_id=verifier_id,
                    rule_version=rule_version,
                    reproducible=True,
                    deterministic=True,
                ),
                kind="capability_sidecar",
                subject_ids=[agent_id] if agent_id else [case_id],
                source_event_refs=[event.event_id],
                rule_refs=[rule_version],
                outcome="passed" if passed else "failed",
                values={"score": score},
                explanation=event.public_summary,
                affects_world=False,
                affects_victory=False,
            ))

        self._os2_event_ledger.extend(events)
        self._os2_settlement.observe_events(events)
        context = SettlementContext(
            run_id=run_id,
            scenario_id=scenario_id,
            world_tick=tick,
            world_state={"agent_ids": list(getattr(state, "agent_ids", []) or [])},
        )
        accepted = self._os2_settlement.record_sidecars(records, context)
        self._last_os2_events.extend(events)
        self._last_os2_settlements.extend(accepted)
        state.internal.setdefault("os2_world_events", []).extend(
            item.model_dump(mode="json") for item in events
        )
        state.internal.setdefault("os2_settlements", []).extend(
            item.model_dump(mode="json") for item in accepted
        )

    def _apply_os2_director_plan(self, package: Any) -> bool:
        """Compile the authoritative fact-bound DirectorPlan for playback."""
        plan = getattr(self, "_last_os2_director_plan", None)
        if plan is None or plan.truth_guard_status != "passed":
            return False
        monologues: Dict[str, Any] = {}
        current = getattr(package, "presentation_plan", None)
        for segment in getattr(current, "segments", []) or []:
            if segment.kind != "character_monologue":
                continue
            actor_id = str((segment.payload or {}).get("actor_id") or "")
            if actor_id:
                monologues[actor_id] = segment

        for actor_id, action in (getattr(self, "_last_actions", {}) or {}).items():
            if actor_id in monologues or action is None:
                continue
            text = (
                str(getattr(action, "character_monologue", "") or "").strip()
                or str(
                    getattr(action, "public_reasoning_summary", "") or ""
                ).strip()
            )
            if text:
                monologues[str(actor_id)] = PresentationSegment(
                    kind="character_monologue",
                    duration_ms=min(3200, max(1800, len(text) * 70)),
                    payload={
                        "actor_id": str(actor_id),
                        "character_monologue": text,
                        "importance": "normal",
                    },
                )

        compiled = self._os2_director.compile_segments(plan)
        interleaved = []
        emitted_monologues = set()
        for segment in compiled:
            command = segment.payload or {}
            if command.get("command_type") == "character":
                actor_id = str((command.get("target_ids") or [""])[0] or "")
                if actor_id in monologues and actor_id not in emitted_monologues:
                    interleaved.append(monologues[actor_id])
                    emitted_monologues.add(actor_id)
            interleaved.append(segment)

        if not interleaved:
            return False
        # skip_empty_ticks（场景 playback_policy 声明）：全员本拍都是
        # wait 类动作时把演绎时长压到秒级——没有决策就没有戏，观众不该
        # 盯着例行结算字幕看一分半（判定用场景自己声明的动作 category，
        # OS 不认识具体动作）。
        if getattr(self, "_playback_skip_empty_ticks", False):
            actions = [
                action for action in (self._last_actions or {}).values()
                if action is not None
            ]
            all_wait = bool(actions) and all(
                str(
                    (self._scene_action_rule(
                        getattr(action, "action_id", "")
                    ) or {}).get("category") or ""
                ) == "wait"
                for action in actions
            )
            if all_wait:
                for segment in interleaved:
                    segment.duration_ms = min(
                        int(segment.duration_ms or 1), 900
                    )
        package.presentation_plan = PresentationPlan(
            tick=package.tick,
            segments=interleaved,
            estimated_duration_ms=sum(
                max(1, int(segment.duration_ms or 1))
                for segment in interleaved
            ),
        )
        package.narration_comment = plan.narrative_summary
        return True

    async def _attach_os2_tts(self, package: Any) -> None:
        """Synthesize only public text emitted by the authoritative plan."""
        plan = getattr(package, "presentation_plan", None)
        texts = []
        for segment in getattr(plan, "segments", []) or []:
            if segment.kind != "render_command":
                continue
            payload = segment.payload or {}
            if str(payload.get("command_type") or "") not in {"subtitle", "ui"}:
                continue
            text = str((payload.get("parameters") or {}).get("text") or "").strip()
            if text:
                texts.append(text)
        if not texts:
            package.audio_chunks = []
            return
        synthesized = await asyncio.gather(
            *[
                self._presentation_audio.synthesize_text_chunks(text)
                for text in texts
            ],
            return_exceptions=True,
        )
        package.audio_chunks = []
        for index, (text, chunks) in enumerate(zip(texts, synthesized)):
            audio = None
            if not isinstance(chunks, Exception) and chunks:
                audio = chunks[0].get("audio_b64")
            package.audio_chunks.append({
                "index": index,
                "text": text,
                "audio_b64": audio,
                "source": "director_plan",
            })

    async def _run_os2_director_agent(
        self,
        *,
        tick: int,
        state: Any,
        events: Optional[List[Any]] = None,
        settlements: Optional[List[Any]] = None,
        activities: Optional[List[Any]] = None,
    ) -> None:
        """Run the independent Director Agent over committed trusted facts."""
        agent = getattr(self, "_director_agent", None)
        if agent is None:
            return
        run_id = self._trace.run_id or "run_pending"
        scenario_id = (
            str(getattr(self._runtime, "scenario_id", "") or "")
            or self._runtime.scenario_name
        )
        try:
            result = await agent.run(
                run_id=run_id,
                scenario_id=scenario_id,
                world_tick=tick,
                events=(events if events is not None else self._last_os2_events),
                settlements=(
                    settlements
                    if settlements is not None else self._last_os2_settlements
                ),
                activities=(
                    activities
                    if activities is not None
                    else getattr(self, "_last_os2_agent_activities", [])
                ),
                enabled=bool(
                    self._cfg.director.enabled and not self._cfg.headless
                ),
            )
        except Exception as exc:
            logger.exception(
                "[DirectorAgent] tick=%s 独立导演运行失败，保留确定性计划: %s",
                tick,
                exc,
            )
            return
        self._last_director_harness_trace = result.trace
        if result.plan is not None:
            self._last_os2_director_plan = result.plan
            payload = result.plan.model_dump(mode="json")
            plans = state.internal.setdefault("os2_director_plans", [])
            if plans and int(plans[-1].get("world_tick", -1)) == tick:
                plans[-1] = payload
            else:
                plans.append(payload)
            if self._pending_package is not None:
                self._pending_package.director_plan = payload
        trace_payload = result.trace.model_dump(mode="json")
        state.internal.setdefault("director_harness_traces", []).append(
            trace_payload
        )
        if self._pending_package is not None:
            self._pending_package.director_harness_trace = trace_payload
        self._write_diagnostic({
            "event_type": "director_agent_completed",
            "tick": tick,
            "used_fallback": result.used_fallback,
            "director_plan": (
                result.plan.model_dump(mode="json") if result.plan else None
            ),
            "harness_trace": trace_payload,
        })

    def _build_agent_snapshots(self, state) -> List:
        """从状态和最近 ActionPack 构建公开快照及契约化角色独白。"""
        from app.core.interfaces import AgentSnapshot

        snapshots = []
        slot_map = {s.id: s for s in self._cfg.agents}
        # 收集所有已知 agent_id（优先用配置的 agents，确保不会因 state 字段缺失而漏）
        agent_ids = list(slot_map.keys())
        alive_set = set(getattr(state, 'alive_agent_ids', []) or [])

        for aid in agent_ids:
            slot = slot_map.get(aid)
            # 从 state.resources 注入数值属性
            public_attrs: Dict[str, Any] = {}
            resources = getattr(state, 'resources', None)
            if resources and aid in resources:
                for k, v in resources[aid].items():
                    if isinstance(v, (int, float)):
                        public_attrs[k] = v

            snap = AgentSnapshot(
                agent_id=aid,
                name=self._display_name(aid),
                color=slot.color if slot else "#ccc",
                is_alive=aid in alive_set if alive_set else True,
                public_attrs=public_attrs,
                character_monologue="",
                public_reasoning_summary="",
                last_thought="",
                speech="",
            )
            # 角色内心只接受 LLM 显式输出的 character_monologue。
            # 禁止从公开策略、行动计划或发言回退，避免语义串线。
            # 投资策略单独走 public_reasoning_summary，不与独白混用。
            action = self._last_actions.get(aid)
            if action:
                monologue = getattr(action, 'character_monologue', '') or ""
                reasoning = getattr(action, 'public_reasoning_summary', '') or ""
                text = getattr(action, 'text', '') or ""
                snap.character_monologue = str(monologue)
                snap.public_reasoning_summary = str(reasoning).strip()
                if text:
                    snap.speech = text
                loaded = getattr(self, "_loaded", None)
                presentation = getattr(loaded, "presentation", None)
                render = getattr(presentation, "render", None)
                ui = getattr(render, "ui", None)
                thought_policy = dict(
                    getattr(ui, "thought_display_policy", {}) or {}
                )
                if isinstance(thought_policy, dict):
                    thought_policy = thought_policy.get(
                        "thought_display_policy", thought_policy
                    )
                if thought_policy.get("enabled", True) is False:
                    snap.character_monologue = ""
                    snap.public_reasoning_summary = ""
                else:
                    max_cfg = thought_policy.get("max_length", {})
                    max_chars = int(
                        max_cfg.get("per_segment_chars", 0) or 0
                    ) if isinstance(max_cfg, dict) else 0
                    if max_chars > 0:
                        snap.character_monologue = (
                            snap.character_monologue[:max_chars]
                        )
                        snap.public_reasoning_summary = (
                            snap.public_reasoning_summary[:max_chars]
                        )
                logger.debug(
                    f"[Snapshot] agent={aid} monologue='{monologue[:40]}' "
                    f"reasoning='{str(reasoning)[:40]}' "
                    f"text='{text[:40]}' "
                    f"viewer_monologue='{snap.character_monologue[:40]}'"
                )
            else:
                logger.debug(f"[Snapshot] agent={aid} 无 ActionPack（self._last_actions 为空或不含此 agent）")
            snapshots.append(snap)

        return snapshots


    def _collect_snapshot(self) -> Dict[str, Any]:
        """收集世界快照为 dict（用于打包到 TickPackage）"""
        state = self._world_state.state
        if state is None:
            return {}

        # 构建 AgentSnapshot 列表（含独立 character_monologue）
        agent_snapshots = self._build_agent_snapshots(state)

        snapshot = self._world_state.build_snapshot(agent_snapshots=agent_snapshots)
        # 用角色名/颜色覆盖
        slot_map = {s.id: s for s in self._cfg.agents}
        for agent_snap in snapshot.agents:
            slot = slot_map.get(agent_snap.agent_id)
            name = self._display_name(agent_snap.agent_id)
            if name:
                agent_snap.name = name
            if slot:
                agent_snap.color = slot.color
        result = snapshot.model_dump() if hasattr(snapshot, "model_dump") else {}
        result["settlement_standings"] = self._settlement_standings()
        return result

    def _settlement_standings(self) -> List[Dict[str, Any]]:
        """Expose the scene-declared victory value without recomputing scores."""
        state = self._world_state.state
        if state is None:
            return []
        victory = dict((self._loaded.settlement_cfg or {}).get("victory", {}) or {})
        provider_id = str(victory.get("provider_id") or "")
        value_key = str(victory.get("value") or "").strip()
        if not value_key:
            return []
        order = str(victory.get("order") or "descending").lower()
        latest: Dict[str, Dict[str, Any]] = {}
        for record in state.internal.get("os2_settlements", []) or []:
            if not isinstance(record, dict):
                continue
            authority = dict(record.get("authority") or {})
            values = dict(record.get("values") or {})
            if value_key not in values:
                continue
            for agent_id in record.get("subject_ids", []) or []:
                details = dict(record.get("details") or {})
                holdings = details.get("holdings")
                if not isinstance(holdings, list):
                    holdings = []
                latest[str(agent_id)] = {
                    "agent_id": str(agent_id),
                    "value": float(values[value_key]),
                    "values": values,
                    "details": details,
                    "holdings": holdings,
                    "settlement_id": record.get("settlement_id"),
                    "provider_id": authority.get("provider_id"),
                    "authority": authority.get("mode"),
                    "label": str(victory.get("label") or value_key),
                    "pending": False,
                }
        rows = []
        for agent_id in getattr(state, "agent_ids", []) or []:
            rows.append(latest.get(str(agent_id), {
                "agent_id": str(agent_id),
                "value": 0.0,
                "values": {},
                "details": {},
                "holdings": [],
                "settlement_id": None,
                "provider_id": provider_id,
                "authority": None,
                "label": str(victory.get("label") or value_key),
                "pending": True,
            }))
        reverse = order not in {"ascending", "asc", "lowest"}
        rows.sort(
            key=lambda item: (bool(item["pending"]), -item["value"] if reverse else item["value"])
        )
        for index, item in enumerate(rows):
            item["rank"] = index + 1
        return rows

    async def _broadcast_snapshot(self) -> None:
        state = self._world_state.state
        if state is None:
            return
        data = self._collect_snapshot()
        await self._emit("viewer", {"type": "world_snapshot", **data})
        assessment = state.internal.get("capability_assessment", {})
        if assessment:
            await self._emit("operator", {
                "type": "capability_assessment",
                "profiles": assessment.get("profiles", {}),
                "cases": assessment.get("cases", []),
                "events": assessment.get("events", []),
            })

    async def _broadcast_logs(self, logs: List[AgentLog]) -> None:
        for log in logs:
            await self._emit("operator", {"type": "agent_log", **log.model_dump()})

    async def _emit(self, channel: str, data: Dict[str, Any]) -> None:
        if self._broadcast:
            try:
                await self._broadcast(channel, data)
            except Exception as e:
                logger.warning(f"[EngineOS] 广播失败 channel={channel}: {e}")

    def _match_location_by_name(self, name: str) -> Optional[str]:
        """按中文名/别名模糊匹配地点 ID（LLM 可能返回中文名而非英文 id）"""
        if not name or not self._location_registry:
            return None
        # 精确匹配 ID
        if self._location_registry.exists(name):
            return name
        # 按地点名匹配
        for loc_id in self._location_registry.all_ids():
            loc = self._location_registry.get(loc_id)
            if not loc:
                continue
            loc_name = getattr(loc, "name", "") or ""
            if loc_name and name.strip() == loc_name.strip():
                return loc_id
        # 子串匹配
        for loc_id in self._location_registry.all_ids():
            loc = self._location_registry.get(loc_id)
            if not loc:
                continue
            loc_name = getattr(loc, "name", "") or ""
            if loc_name and (name in loc_name or loc_name in name):
                return loc_id
        return None

    def _store_logs(self, logs: List[AgentLog]) -> None:
        self._all_logs.extend(logs)
        self._recent_logs.extend(logs)
        if len(self._recent_logs) > 300:
            self._recent_logs = self._recent_logs[-300:]

    def get_recent_logs(self) -> List[AgentLog]:
        return list(self._recent_logs)

    def get_all_logs(self) -> List[AgentLog]:
        return list(self._all_logs)

    def get_benchmark_snapshot(self) -> Dict[str, Any]:
        """返回基准统计所需的只读结果，不暴露内部服务对象。"""
        state = self.state
        ledgers = self._evaluation.export_ledgers()
        return {
            "tick": state.tick if state else 0,
            "winner_id": state.winner_id if state else None,
            "victory_standings": list(
                (state.internal.get("victory_standings", []) if state else [])
            ),
            "capability_reports": dict(
                (state.internal.get("capability_reports", {}) if state else {})
            ),
            "metrics": dict(
                (state.internal.get("metrics", {}) if state else {})
            ),
            "action_ledger": list(ledgers.get("action", [])),
            "logs": [log.model_dump() for log in self._all_logs],
            "run_id": self._trace.run_id,
            "run_dir": self._trace.exported_run_dir,
            "seed": self._seed_manager.seed,
            "measurement_opportunities": self._measurement_opportunities.summary(),
            "measurement_opportunity_ledger": [
                item.model_dump()
                for item in self._measurement_opportunities.ledger
            ],
            "general_capability_profiles": dict(
                (
                    state.internal.get("capability_assessment", {})
                    .get("profiles", {})
                ) if state else {}
            ),
            "assessment_cases": list(
                (
                    state.internal.get("capability_assessment", {})
                    .get("cases", [])
                ) if state else []
            ),
        }

    def get_provider_bindings(self) -> Dict[str, Dict[str, str]]:
        return {
            agent_id: {
                "provider": context.provider.provider_name,
                "model": context.provider.model_name,
            }
            for agent_id in self._agent_runtime.agent_ids
            for context in [self._agent_runtime.get_context(agent_id)]
        }

    def force_victory_settlement(self, reason: str = "forced_end") -> None:
        """Finish a started world through its scenario settlement provider.

        A runtime may be created and retired before the first world fact (scene
        switching, idle eviction or server shutdown). Such a lifecycle event is
        not a contest result and must not manufacture a winner.
        """
        state = self.state
        if state is None or state.is_game_over:
            return
        has_world_facts = bool(
            getattr(self, "_last_os2_events", [])
            or (getattr(state, "internal", {}) or {}).get("os2_world_events")
        )
        if int(getattr(state, "tick", 0) or 0) <= 0 and not has_world_facts:
            self._detach_run_logfile()
            return
        self._settle_terminal(state, self._runtime.audit_cfg or {}, reason)
        run_dir = self._trace.finalize(state)
        if run_dir and self._replay_recorder:
            from pathlib import Path
            self._replay_recorder.export_to(
                str(Path(run_dir) / "replay_deterministic.json")
            )
        self._detach_run_logfile()

    def _check_terminal_settlement(self, state: Any, tick: int) -> None:
        """
        P0-5：终局审计接入主循环。
        检查 tick_limit / victory_rule，满足条件时设置 is_game_over + winner_id。
        """
        if state.is_game_over:
            return  # 已经结束了，不重复审计

        audit_cfg = self._runtime.audit_cfg or {}
        termination = audit_cfg.get("termination", {})
        if not isinstance(termination, dict):
            termination = {}

        coords = self._capability_coordinators
        if termination.get("end_after_all_challenges", False) and coords:
            if all(getattr(c, "fired", False) for c in coords):
                if self._all_challenges_done_tick is None:
                    self._all_challenges_done_tick = tick
                    logger.info(
                        "[EngineOS] 全部挑战已落幕于 tick=%d，进入收尾缓冲", tick
                    )

        started = getattr(self, "_run_started_monotonic", None)
        elapsed_seconds = (
            time.monotonic() - started if started is not None else None
        )
        decision = self._victory_strategy.should_end(
            state=state,
            tick=tick,
            audit_cfg=audit_cfg,
            capability_coordinators=coords,
            all_challenges_done_tick=self._all_challenges_done_tick,
            elapsed_seconds=elapsed_seconds,
        )
        if decision.should_end:
            self._settle_terminal(state, audit_cfg, reason=decision.reason)

    def _settle_terminal(self, state: Any, audit_cfg: Dict[str, Any], reason: str = "") -> None:
        """调用场景终局结算，设置 is_game_over 和 winner_id。"""
        try:
            ctx = self._evaluation.context
            from app.engine.evaluation.settlement import SettlementContext

            settlement_context = SettlementContext(
                run_id=self._trace.run_id or "run_pending",
                scenario_id=(
                    self._runtime.scenario_id or self._runtime.scenario_name
                ),
                world_tick=int(getattr(state, "tick", 0) or 0),
                world_state={
                    "agent_ids": list(getattr(state, "agent_ids", []) or []),
                    "agent_names": {
                        agent_id: self._display_name(agent_id)
                        for agent_id in list(getattr(state, "agent_ids", []) or [])
                    },
                    "alive_agent_ids": list(
                        getattr(state, "alive_agent_ids", []) or []
                    ),
                    "eliminated": list(getattr(state, "eliminated", []) or []),
                    "resources": dict(getattr(state, "resources", {}) or {}),
                    "internal": dict(getattr(state, "internal", {}) or {}),
                    "audit_cfg": dict(audit_cfg or {}),
                    "round_phase": self._current_round_phase(
                        int(getattr(state, "tick", 0) or 0)
                    ),
                    "external_observations": [
                        item.model_dump(mode="json")
                        for item in self._os2_settlement.observations.all()
                    ],
                },
            )
            final_settlements = self._os2_settlement.finalize(
                settlement_context
            )
            self._last_final_os2_settlements = list(final_settlements)
            self._last_os2_settlements.extend(final_settlements)
            standings = self._os2_settlement.rank_victory_records(
                final_settlements, state
            )
            if not standings:
                raise RuntimeError(
                    "scene settlement plugin produced no victory records"
                )
            state.internal.setdefault("os2_settlements", []).extend(
                item.model_dump(mode="json") for item in final_settlements
            )
            state.internal["victory_standings"] = [
                item.model_dump(mode="json") for item in standings
            ]

            winner = standings[0]
            winner_id = winner.agent_id
            self._world_state.set_game_over(winner_id)
            try:
                import asyncio
                asyncio.get_running_loop().create_task(
                    self._notify_external_world_over({
                        "winner_id": winner_id,
                        "reason": reason,
                    })
                )
            except RuntimeError:
                pass
            # 终局胜负溯源：每人优势来源与致命伤的可读文本（随快照广播给前端）
            try:
                state.internal["victory_attribution"] = (
                    self._build_settlement_victory_attribution(standings)
                )
            except Exception as attr_err:
                logger.warning(f"[EngineOS] 胜负溯源生成失败: {attr_err}")
            state.internal["fairness_report"] = self._build_fairness_report()
            from app.framework.ruleworld.simulation_health import (
                build_simulation_health_report,
            )
            physics_cfg = self._runtime.causal_physics_config or {}
            state.internal["simulation_health_report"] = (
                build_simulation_health_report(
                    state.internal.get("simulation_health_records", []),
                    physics_cfg.get("health_gate", {}),
                )
            )

            logger.info(
                f"[EngineOS] VictorySettlement 触发: reason={reason} "
                f"winner={state.winner_id} value={winner.value}"
            )

            # 广播审计结果给运营台
            # (实际广播由调用方的 _broadcast_snapshot 处理)
        except Exception as e:
            logger.error(f"[EngineOS] 终局场景结算失败: {e}", exc_info=True)

    def _build_settlement_victory_attribution(
        self, standings: List[Any]
    ) -> List[Dict[str, Any]]:
        output: List[Dict[str, Any]] = []
        for standing in standings:
            values = dict(getattr(standing, "values", {}) or {})
            components = [
                (key, float(value)) for key, value in values.items()
                if key != getattr(standing, "value_key", "")
                and isinstance(value, (int, float))
            ]
            strengths = [
                f"{key}：{value:.2f}"
                for key, value in sorted(
                    components, key=lambda item: abs(item[1]), reverse=True
                )[:3]
            ]
            agent_id = str(standing.agent_id)
            output.append({
                "agent_id": agent_id,
                "name": self._display_name(agent_id),
                "rank": int(standing.rank),
                "value": round(float(standing.value), 6),
                "value_key": standing.value_key,
                "label": standing.label,
                "headline": (
                    f"{self._display_name(agent_id)}最终第{standing.rank}名，"
                    f"{standing.label}{float(standing.value):.2f}"
                ),
                "strengths": strengths,
                "weaknesses": [],
                "fatal": "已被世界事件淘汰" if standing.eliminated else "",
                "source_mix": {standing.authority: 1.0},
                "settlement_ref": standing.settlement_ref,
                "provider_id": standing.provider_id,
            })
        return output

    def _build_fairness_report(self) -> Dict[str, Any]:
        """对场景初始条件做通用对称性审计，不认识任何角色或领域字段。"""
        roles = list(self._runtime.compiled.role_index.values())
        starts = [getattr(role, "start_location", None) for role in roles]
        permissions = [
            sorted(getattr(role, "permissions", []) or []) for role in roles
        ]
        def gameplay_profile(role: Any) -> Dict[str, Any]:
            profile = dict(getattr(role, "capability_profile", {}) or {})
            for presentation_key in (
                "character_id", "display_name", "asset", "model", "sprite",
            ):
                profile.pop(presentation_key, None)
            return profile

        role_profiles = [gameplay_profile(role) for role in roles]

        def symmetric(values: List[Any]) -> bool:
            if not values:
                return True
            first = values[0]
            return all(value == first for value in values[1:])

        # 允许场景包声明故意的非对称设计，避免 Benchmark 被误判为不公平
        intentional = {}
        if isinstance(self._runtime.permissions_cfg, dict):
            decl = self._runtime.permissions_cfg.get("_fairness_declarations", {}) or {}
            if isinstance(decl, dict):
                intentional = decl

        loc_sym = symmetric(starts)
        loc_status = loc_sym
        if not loc_sym and intentional.get("start_location_asymmetry") == "intentional":
            loc_status = "intentional_asymmetry"

        profile_sym = symmetric(role_profiles)
        profile_status = profile_sym
        if (
            not profile_sym
            and intentional.get("capability_profile_asymmetry") == "intentional"
        ):
            profile_status = "intentional_asymmetry"

        checks = {
            "start_location_symmetry": loc_status,
            "permission_symmetry": symmetric(permissions),
            "capability_profile_symmetry": profile_status,
            "resource_schema_shared": bool(self._runtime.resources_cfg),
            "tool_schema_shared": bool(self._runtime.tools_cfg),
        }
        passed = all(
            v is True or v == "intentional_asymmetry"
            for v in checks.values()
        )
        # 信息性检查（不参与 passed）：参赛模型视觉能力是否对称。
        # 图片挑战对不支持 image_url 的模型会降级纯文本，天然不公平——
        # 至少要在报告里可见，供排局者知情。
        vision_flags = []
        for aid in self._agent_runtime.agent_ids:
            ctx = self._agent_runtime.get_context(aid)
            provider = getattr(ctx, "provider", None) if ctx else None
            vision_flags.append(
                bool(getattr(provider, "_supports_image_url", True))
            )
        informational = {
            "vision_capability_symmetry": symmetric(vision_flags),
            "vision_capability_flags": dict(
                zip(self._agent_runtime.agent_ids, vision_flags)
            ),
        }
        return {
            "passed": passed,
            "checks": checks,
            "informational": informational,
            "agent_count": len(roles),
        }
