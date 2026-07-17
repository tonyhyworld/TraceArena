"""
账户体系 · 引擎实例池

每个登录用户拥有独立的 EngineOS 实例，真正并发（不排队）。
惰性创建：登录不建实例，第一次访问（连 WS / 调用控制接口）才建。
空闲回收：后台任务周期扫描，超时且未在运行的实例会被收尾并释放，
下次访问重新惰性创建即可，落盘数据不受影响。

不引入 Redis/多进程——进程内一个字典足够内部团队规模使用。
"""
from __future__ import annotations

import asyncio
import copy
import logging
import time
from dataclasses import dataclass, field
from pathlib import Path
from typing import Awaitable, Callable, Dict, Optional
from app.config import AgentSlotConfig, FrameworkConfig, load_config
from app.engine.main import EngineOS, UserSettingsProvider
from app.engine.scenario_boot.loader import ScenarioBootKernel

logger = logging.getLogger(__name__)

BroadcastFactory = Callable[[str], Callable[[str, Dict], Awaitable[None]]]


@dataclass
class UserEngineContext:
    user_id: str
    engine: EngineOS
    cfg: FrameworkConfig
    last_active: float = field(default_factory=time.time)
    lock: asyncio.Lock = field(default_factory=asyncio.Lock)

    def touch(self) -> None:
        self.last_active = time.time()


class EngineManager:
    """按 user_id 惰性创建/持有/回收 EngineOS 实例"""

    def __init__(
        self,
        base_cfg_path: str,
        make_broadcast: BroadcastFactory,
        *,
        idle_timeout_sec: int = 1800,
        max_instances: int = 20,
        sweep_interval_sec: int = 300,
        user_settings_provider: Optional[UserSettingsProvider] = None,
    ):
        self._base_cfg_path = base_cfg_path
        self._make_broadcast = make_broadcast
        self._idle_timeout = idle_timeout_sec
        self._max_instances = max_instances
        self._sweep_interval = sweep_interval_sec
        self._user_settings_provider = user_settings_provider
        self._contexts: Dict[str, UserEngineContext] = {}
        # Python 3.9 binds asyncio primitives to the current loop at creation
        # time.  Test runners and short-lived CLI tasks may have closed that
        # loop already, so ensure a usable loop before constructing the lock.
        try:
            asyncio.get_event_loop()
        except RuntimeError:
            asyncio.set_event_loop(asyncio.new_event_loop())
        self._creation_lock = asyncio.Lock()
        self._sweep_task: Optional[asyncio.Task] = None

    # ------------------------------------------------------------------
    def _load_base_cfg(self) -> FrameworkConfig:
        return load_config(self._base_cfg_path)

    def _load_scenario_cfg(self, scenario_path: Optional[str] = None) -> FrameworkConfig:
        """Compose framework settings with the selected scenario package.

        A scenario may provide ``runtime/framework.yaml`` for execution defaults.
        Role identity still comes from ``agents/roles.yaml`` and is assembled below,
        so switching worlds never carries role ids from the previous world.

        When ``scenario_path`` is omitted, resolve it from the base framework
        config and still prefer that scenario's runtime profile. Otherwise a
        global ``agent_loop.max_steps`` leftover can silently override the
        scene package (e.g. capital market declaring 12 while base stays at 5).
        """
        if not scenario_path:
            scenario_path = self._load_base_cfg().scenario_path
        root = Path(scenario_path).resolve()
        runtime_cfg = root / "runtime" / "framework.yaml"
        cfg = load_config(str(runtime_cfg)) if runtime_cfg.is_file() else self._load_base_cfg()
        cfg.scenario_path = str(root)
        return cfg

    @staticmethod
    def _assemble_agent_slots(
        cfg: FrameworkConfig,
        scenario: object,
    ) -> None:
        """Bind model profiles to the role slots declared by the scene package."""
        roles = list(getattr(scenario, "agent_roles", []) or [])
        configured = {slot.id: slot for slot in cfg.agents}
        templates = list(cfg.agents)
        slots = []
        for index, role in enumerate(roles):
            role_id = str(getattr(role, "agent_slot_id", "") or "")
            if not role_id:
                continue
            template = configured.get(role_id)
            if template is None and index < len(templates):
                template = templates[index]
            if template is None:
                template = AgentSlotConfig(
                    id=role_id,
                    name=str(getattr(role, "display_name", "") or role_id),
                    provider="mock",
                    model="mock",
                )
            payload = copy.deepcopy(template.model_dump())
            payload.update({
                "id": role_id,
                "name": str(getattr(role, "display_name", "") or role_id),
                "color": str(getattr(role, "color", "") or template.color),
            })
            slots.append(AgentSlotConfig(**payload))
        cfg.agents = slots

    async def _build_context(self, user_id: str, scenario_path: Optional[str] = None) -> UserEngineContext:
        # Always resolve through scenario runtime profile (see _load_scenario_cfg).
        cfg = self._load_scenario_cfg(scenario_path)
        scenario = ScenarioBootKernel.load(
            cfg.scenario_path, locale=cfg.scenario_locale
        )
        self._assemble_agent_slots(cfg, scenario)
        # 每用户独立落盘目录：engine/main.py 内部写盘逻辑零改动，
        # 只靠 log_dir / persistent_memory_root 指向不同路径就实现了数据隔离。
        cfg.log_dir = str(Path("./runs") / user_id)
        cfg.persistent_memory_root = str(Path("./agents_persistent") / user_id)
        Path(cfg.log_dir).mkdir(parents=True, exist_ok=True)
        Path(cfg.persistent_memory_root).mkdir(parents=True, exist_ok=True)

        # User-specific settings are supplied by the hosting boundary.  The
        # generic manager does not import authentication or secret storage.
        provider = self._user_settings_provider
        overrides, secrets = provider(user_id) if provider else ({}, {})
        for slot in cfg.agents:
            ov = overrides.get(slot.id)
            if ov:
                slot.provider = ov.get("provider", slot.provider)
                slot.model = ov.get("model", slot.model)
                if ov.get("driver"):
                    slot.driver = str(ov["driver"])
            user_key = secrets.get(slot.id)
            if user_key:
                slot.api_key_override = user_key

        engine = EngineOS(
            cfg,
            scenario,
            user_settings_provider=self._user_settings_provider,
        )
        engine.set_user_context(user_id)
        broadcast = self._make_broadcast(user_id)
        engine.set_broadcast_callback(broadcast)
        await engine.initialize()
        logger.info(f"[EngineManager] 为用户 {user_id} 创建引擎实例")
        return UserEngineContext(user_id=user_id, engine=engine, cfg=cfg)

    async def get_or_create(self, user_id: str) -> UserEngineContext:
        ctx = self._contexts.get(user_id)
        if ctx is not None:
            ctx.touch()
            return ctx
        async with self._creation_lock:
            # 双重检查：等锁期间可能已被别的并发请求创建
            ctx = self._contexts.get(user_id)
            if ctx is not None:
                ctx.touch()
                return ctx
            if len(self._contexts) >= self._max_instances:
                evicted = await self._evict_one_idle()
                if not evicted:
                    raise RuntimeError(
                        f"当前并发对局数已达上限（{self._max_instances}），请稍后再试"
                    )
            ctx = await self._build_context(user_id)
            self._contexts[user_id] = ctx
            return ctx

    def _resolve_scenario_path(self, user_id: str, scenario_name: str) -> str:
        """场景包优先在该用户私有目录找，找不到再退回全局公共目录"""
        private_path = Path("./user_data") / user_id / "scenarios" / scenario_name
        if (private_path / "manifest.json").is_file():
            return str(private_path)
        base_cfg = self._load_base_cfg()
        public_path = Path(base_cfg.scenario_path).parent / scenario_name
        return str(public_path)

    async def rebuild_engine(self, user_id: str, scenario_name: str) -> UserEngineContext:
        """构建成功后再原子替换，切换窗口内读请求始终看到完整旧实例。"""
        async with self._creation_lock:
            old = self._contexts.get(user_id)
            new_scenario_path = self._resolve_scenario_path(user_id, scenario_name)
            # 构建失败时保留旧世界；绝不能先 pop 后让并发轮询创建默认场景。
            ctx = await self._build_context(user_id, scenario_path=new_scenario_path)
            self._contexts[user_id] = ctx
        if old is not None:
            try:
                await old.engine.pause()
            except Exception:
                pass
            await self._retire(old, reason="scenario_replaced")
        return ctx

    def get_existing(self, user_id: str) -> Optional[UserEngineContext]:
        """只读查询，不触发创建（用于健康检查等不想意外拉起引擎的场景）"""
        return self._contexts.get(user_id)

    # ------------------------------------------------------------------
    async def _evict_one_idle(self) -> bool:
        """淘汰一个最久未活动且未在运行的实例，为新实例腾位置"""
        now = time.time()
        candidates = [
            ctx for ctx in self._contexts.values()
            if not bool(getattr(ctx.engine.state, "is_running", False))
        ]
        if not candidates:
            return False
        victim = min(candidates, key=lambda c: c.last_active)
        await self._retire(victim, reason="capacity_evict")
        return True

    async def _retire(self, ctx: UserEngineContext, *, reason: str) -> None:
        user_id = str(getattr(ctx, "user_id", "") or "")
        try:
            finalize = getattr(ctx.engine, "force_victory_settlement", None)
            if callable(finalize):
                finalize(reason)
        except Exception as exc:
            logger.warning(f"[EngineManager] 收尾用户 {user_id or 'unknown'} 引擎失败: {exc}")
        # A scenario rebuild installs the new context before retiring the old
        # one. Never let cleanup of the replaced instance remove its successor.
        if user_id and self._contexts.get(user_id) is ctx:
            self._contexts.pop(user_id, None)
        logger.info(f"[EngineManager] 释放用户 {user_id or 'unknown'} 的引擎实例（{reason}）")

    async def _sweep_idle(self) -> None:
        while True:
            await asyncio.sleep(self._sweep_interval)
            now = time.time()
            idle_victims = [
                ctx for ctx in list(self._contexts.values())
                if now - ctx.last_active > self._idle_timeout
                and not bool(getattr(ctx.engine.state, "is_running", False))
            ]
            for ctx in idle_victims:
                await self._retire(ctx, reason="idle_timeout")

    def start_sweeper(self) -> None:
        if self._sweep_task is None:
            self._sweep_task = asyncio.create_task(self._sweep_idle())

    async def shutdown_all(self) -> None:
        if self._sweep_task is not None:
            self._sweep_task.cancel()
        for ctx in list(self._contexts.values()):
            await self._retire(ctx, reason="server_shutdown")


_global_engine_manager: Optional["EngineManager"] = None


def register_engine_manager(mgr: Optional["EngineManager"]) -> None:
    """由 app.main lifespan 注册全局 EngineManager 实例。"""
    global _global_engine_manager
    _global_engine_manager = mgr


def get_engine_manager() -> Optional["EngineManager"]:
    return _global_engine_manager
