"""
宝器代码沙盒执行器

安全边界：
- 禁止网络访问（requests/httpx/socket 等被屏蔽）
- 禁止文件系统访问（open/os 被屏蔽）
- 禁止 import（仅允许白名单模块）
- 执行超时（SandboxConfig.timeout_sec）
- 只能调用 world_api 暴露的函数
"""
from __future__ import annotations

import asyncio
import traceback
from typing import Any, Callable, Dict, List, Optional

from app.core.exceptions import ArtifactPermissionError, SandboxError
from app.core.interfaces import Artifact, RuntimeSignal
from app.config import SandboxConfig


# 允许 Agent 代码 import 的安全模块白名单
_ALLOWED_IMPORTS = {"math", "random", "json", "re", "collections", "itertools"}

# 禁止访问的内置函数
_BLOCKED_BUILTINS = {
    "open", "exec", "eval", "compile", "__import__",
    "breakpoint", "input", "print",  # print 重定向到事件
}


class SandboxWorldAPI:
    """
    宝器代码可以调用的世界 API（统一接口）。

    同一份 agent 代码可在两种模式下运行：
      - 一次性测试/运行（run_code）：world_state 可为 None，主要用 emit_output/add_evidence
      - 常驻"上线"运行（run，绑定 Artifact）：每回合执行，主要用 emit_event

    框架内置基础函数，场景包可注册扩展函数。
    """

    def __init__(
        self,
        world_state_proxy: Any = None,
        owner_id: str = "",
        artifact_id: str = "",
        context: Optional[Dict[str, Any]] = None,
    ):
        self._state = world_state_proxy
        self._owner_id = owner_id
        self._artifact_id = artifact_id
        self._ctx: Dict[str, Any] = context or {}
        self._events: List[RuntimeSignal] = []
        self._outputs: List[Dict[str, Any]] = []
        self._evidence: List[str] = []
        self._extension_funcs: Dict[str, Callable] = {}

    @classmethod
    def for_artifact(cls, artifact: Artifact, world_state_proxy: Any) -> "SandboxWorldAPI":
        return cls(
            world_state_proxy=world_state_proxy,
            owner_id=artifact.owner_id,
            artifact_id=artifact.artifact_id,
        )

    def register_extension(self, name: str, func: Callable) -> None:
        """场景包注册自定义 API 函数"""
        self._extension_funcs[name] = func

    # ---- 基础内置 API ----

    def get_owner_id(self) -> str:
        """返回宝器所有者 ID"""
        return self._owner_id

    def get_tick(self) -> int:
        """返回当前回合数"""
        if self._state is not None:
            return self._state.tick
        return int(self._ctx.get("tick", 0))

    def get_alive_agents(self) -> List[str]:
        """返回所有存活 Agent ID 列表"""
        if self._state is not None:
            return list(self._state.alive_agent_ids)
        return []

    def get_target(self) -> Optional[str]:
        """返回本次工具作用的目标对象 id（一次性运行时由 context 提供）"""
        return self._ctx.get("target_object_id")

    def emit_event(self, event_type: str, summary: str, is_public: bool = False) -> None:
        """宝器触发一个世界事件（常驻运行的主要产出）"""
        self._events.append(RuntimeSignal(
            tick=self.get_tick(),
            event_type=str(event_type),
            source_id=self._owner_id,
            is_public=bool(is_public),
            summary=str(summary),
            metadata={"artifact_id": self._artifact_id},
        ))

    def emit_output(self, claim: str = "", **data: Any) -> None:
        """工具产出一条结构化输出（一次性运行的主要产出，下游会转成证据）"""
        self._outputs.append({"claim": str(claim), **data})

    def add_evidence(self, text: str) -> None:
        """工具产出一条证据声明（下游标准化为 EvidenceEntry）"""
        self._evidence.append(str(text))

    def get_events(self) -> List[RuntimeSignal]:
        return self._events

    def get_outputs(self) -> List[Dict[str, Any]]:
        return self._outputs

    def get_evidence(self) -> List[str]:
        return self._evidence

    def __getattr__(self, name: str) -> Any:
        """场景包扩展函数透传"""
        # 注意：__getattr__ 只在常规属性查找失败时触发，不会拦截上面定义的方法
        ext = self.__dict__.get("_extension_funcs", {})
        if name in ext:
            return ext[name]
        raise ArtifactPermissionError(f"宝器 API 不存在: world.{name}")


class SandboxExecutor:
    """执行宝器代码，返回触发的事件列表"""

    def __init__(self, cfg: SandboxConfig):
        self._cfg = cfg

    async def run(
        self,
        artifact: Artifact,
        world_state: Any,
        extension_funcs: Optional[Dict[str, Callable]] = None,
    ) -> List[RuntimeSignal]:
        if not self._cfg.enabled:
            return []

        api = SandboxWorldAPI.for_artifact(artifact, world_state)
        if extension_funcs:
            for name, func in extension_funcs.items():
                api.register_extension(name, func)

        try:
            await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, self._exec_code, artifact.code, api
                ),
                timeout=self._cfg.timeout_sec,
            )
        except asyncio.TimeoutError:
            raise SandboxError(
                f"宝器 '{artifact.name}' 执行超时（>{self._cfg.timeout_sec}s）"
            )
        return api.get_events()

    async def run_code(
        self,
        code: str,
        context: Optional[Dict[str, Any]] = None,
        extension_funcs: Optional[Dict[str, Callable]] = None,
    ) -> Dict[str, Any]:
        """一次性执行 agent 提交的工具代码（测试/运行），返回结构化结果。

        返回：{outputs: [dict], evidence_created: [str], events: [RuntimeSignal], errors: [str]}
        - 任何超时/越权/运行错误都被捕获为 errors，不抛出，保证不会拖垮 tick。
        """
        if not self._cfg.enabled:
            return {"outputs": [], "evidence_created": [], "events": [], "errors": ["sandbox_disabled"]}
        if not code or not code.strip():
            return {"outputs": [], "evidence_created": [], "events": [], "errors": ["empty_code"]}

        ctx = context or {}
        api = SandboxWorldAPI(owner_id=str(ctx.get("agent_id", "")), context=ctx)
        if extension_funcs:
            for name, func in extension_funcs.items():
                api.register_extension(name, func)

        try:
            await asyncio.wait_for(
                asyncio.get_event_loop().run_in_executor(
                    None, self._exec_code, code, api
                ),
                timeout=self._cfg.timeout_sec,
            )
        except asyncio.TimeoutError:
            return {"outputs": api.get_outputs(), "evidence_created": api.get_evidence(),
                    "events": api.get_events(), "errors": [f"timeout(>{self._cfg.timeout_sec}s)"]}
        except (ArtifactPermissionError, SandboxError) as e:
            return {"outputs": api.get_outputs(), "evidence_created": api.get_evidence(),
                    "events": api.get_events(), "errors": [str(e)]}
        except Exception as e:  # noqa: BLE001 — 沙盒边界，任何异常都不应外泄
            return {"outputs": api.get_outputs(), "evidence_created": api.get_evidence(),
                    "events": api.get_events(), "errors": [str(e)]}

        return {
            "outputs": api.get_outputs(),
            "evidence_created": api.get_evidence(),
            "events": api.get_events(),
            "errors": [],
        }

    def _exec_code(self, code: str, api: SandboxWorldAPI) -> None:
        """在受限环境里同步执行代码（在线程池中运行）"""
        # 检查代码行数限制
        lines = code.strip().splitlines()
        if len(lines) > self._cfg.max_code_lines:
            raise SandboxError(
                f"代码超过行数限制 {self._cfg.max_code_lines} 行"
            )

        # 构建受限 builtins
        safe_builtins = {
            k: v for k, v in __builtins__.items()
            if k not in _BLOCKED_BUILTINS
        } if isinstance(__builtins__, dict) else {
            k: getattr(__builtins__, k)
            for k in dir(__builtins__)
            if k not in _BLOCKED_BUILTINS and not k.startswith("_")
        }
        # 屏蔽 __import__，只允许白名单
        def safe_import(name: str, *args: Any, **kwargs: Any) -> Any:
            if name not in _ALLOWED_IMPORTS:
                raise ArtifactPermissionError(f"宝器代码不允许 import {name}")
            import importlib
            return importlib.import_module(name)
        safe_builtins["__import__"] = safe_import

        exec_globals = {
            "__builtins__": safe_builtins,
            "world": api,
        }

        try:
            exec(compile(code, "<artifact>", "exec"), exec_globals)  # noqa: S102
        except (ArtifactPermissionError, SandboxError):
            raise
        except Exception as e:
            raise SandboxError(f"宝器代码运行错误: {e}\n{traceback.format_exc()}") from e
