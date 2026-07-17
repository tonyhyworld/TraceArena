"""
AI World — FastAPI 入口（引擎 OS 层版本）

启动：cd backend && python -m uvicorn app.main:app --reload --port 8001 \\
  --reload-dir app --reload-dir scenarios --reload-dir skills
（只监视源码目录；勿监视整个 backend，否则 runs/ 沙箱写文件会热重启并掐断 WebSocket）
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
import os
from contextlib import asynccontextmanager
from typing import Any, Dict

from fastapi import FastAPI, Query, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles

try:
    from dotenv import load_dotenv
    load_dotenv()
except ImportError:
    pass

from app.api.routes import router
from app.api.operator_runs import router as operator_runs_router
from app.api.auth_routes import router as auth_router
from app.api.admin_routes import router as admin_router
from app.api.scenario_upload import router as scenario_upload_router
from app.api.websocket import manager
from app.auth.dependencies import decode_ws_token
from app.config import load_config
from app.engine.scenario_boot.loader import ScenarioBootKernel
from app.engine_manager import EngineManager
from app.mcp.client import get_mcp_manager, init_mcp_manager, set_mcp_manager

_log_dir = os.environ.get("AIWORLD_LOG_DIR", "./runs")
os.makedirs(_log_dir, exist_ok=True)
_log_format = logging.Formatter(
    "%(asctime)s [%(name)s] %(levelname)s %(message)s"
)
_root_logger = logging.getLogger()
_root_logger.setLevel(logging.INFO)
if not _root_logger.handlers:
    _console = logging.StreamHandler()
    _console.setFormatter(_log_format)
    _root_logger.addHandler(_console)
_runtime_log = os.path.abspath(os.path.join(_log_dir, "runtime.log"))
if not any(
    isinstance(handler, RotatingFileHandler)
    and getattr(handler, "baseFilename", "") == _runtime_log
    for handler in _root_logger.handlers
):
    _file_handler = RotatingFileHandler(
        _runtime_log,
        maxBytes=50 * 1024 * 1024,
        backupCount=5,
        encoding="utf-8",
    )
    _file_handler.setFormatter(_log_format)
    _root_logger.addHandler(_file_handler)
# httpx/httpcore 在 INFO 级会把完整请求 URL 写进日志，TTS 接口的
# ?GroupId=... query 会因此泄漏进 runtime.log；抬到 WARNING 屏蔽。
logging.getLogger("httpx").setLevel(logging.WARNING)
logging.getLogger("httpcore").setLevel(logging.WARNING)
logger = logging.getLogger(__name__)

# 多用户引擎实例池（阶段2起替代原来的全局单例 _engine）
engine_manager: EngineManager | None = None


def _make_broadcast(user_id: str):
    async def broadcast(channel: str, data: Dict[str, Any]) -> None:
        await manager.broadcast(user_id, channel, data)
    return broadcast


def _user_settings_provider(user_id: str):
    """Private hosting adapter for user overrides and BYOK secrets."""
    from app.auth.overrides_store import get_user_overrides
    from app.auth.secrets_store import get_user_secrets

    overrides = get_user_overrides(user_id)
    secrets = get_user_secrets(user_id)
    return overrides, secrets


@asynccontextmanager
async def lifespan(app: FastAPI):
    global engine_manager

    cfg_path = os.environ.get("AIWORLD_CONFIG", "./framework.yaml")
    try:
        cfg = load_config(cfg_path)
        # 启动时只验证一次场景包能正常加载（fail fast），不为此常驻一个实例——
        # 真正的引擎实例按用户惰性创建，见 EngineManager.get_or_create。
        scenario = ScenarioBootKernel.load(
            cfg.scenario_path, locale=cfg.scenario_locale
        )
        logger.info(f"[startup] 场景包: {scenario.manifest.name} v{scenario.manifest.version}")
    except Exception as e:
        logger.error(f"[startup] 配置/场景包加载失败: {e}")
        raise

    engine_manager = EngineManager(
        cfg_path,
        _make_broadcast,
        user_settings_provider=_user_settings_provider,
    )
    from app.engine_manager import register_engine_manager
    register_engine_manager(engine_manager)
    engine_manager.start_sweeper()
    logger.info("[startup] EngineManager 就绪（多用户引擎实例池，惰性创建）")

    try:
        mcp_manager = await init_mcp_manager(
            cfg.mcp.servers_path,
            enabled=cfg.mcp.enabled,
        )
        set_mcp_manager(mcp_manager)
    except Exception as exc:
        logger.warning("[startup] MCP 初始化失败（外部工具不可用）: %s", exc)
        set_mcp_manager(None)

    yield

    # 交互(WS)局不会自然走到 game_over，finalize 永不触发 →
    # 最终评测/证据账本/回放文件不落盘。服务停止时对所有活跃实例强制收尾一次。
    #
    # 开发期 uvicorn --reload 会把每次代码保存当作 shutdown，把进行中的对局
    # 在 ~tick 8 强行 finalize，导致 fire_tick=15 的安全挑战永远跑不到。
    # 设置 AIWORLD_SKIP_SHUTDOWN_FINALIZE=1 跳过收尾；生产部署不要设。
    skip_shutdown = os.environ.get(
        "AIWORLD_SKIP_SHUTDOWN_FINALIZE", ""
    ).strip().lower() in ("1", "true", "yes")
    if skip_shutdown:
        logger.info("[shutdown] AIWORLD_SKIP_SHUTDOWN_FINALIZE=1，跳过强制收尾")
    else:
        try:
            if engine_manager is not None:
                await engine_manager.shutdown_all()
        except Exception as exc:  # 收尾失败不应阻塞关闭
            logger.warning(f"[shutdown] 终局审计收尾失败: {exc}")
    mcp_mgr = get_mcp_manager()
    if mcp_mgr is not None:
        await mcp_mgr.close()
        set_mcp_manager(None)
    from app.engine_manager import register_engine_manager
    register_engine_manager(None)
    logger.info("[shutdown] 引擎关闭")


app = FastAPI(title="AI World Engine OS", lifespan=lifespan)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

app.include_router(router)
app.include_router(operator_runs_router)
app.include_router(auth_router)
app.include_router(admin_router)
app.include_router(scenario_upload_router)
from app.api.factory_routes import router as factory_router  # noqa: E402
app.include_router(factory_router)
from app.agent_gateway.routes import router as agent_gateway_router  # noqa: E402
app.include_router(agent_gateway_router)

_scenarios_root = os.path.join(os.path.dirname(os.path.dirname(__file__)), "scenarios")
if os.path.isdir(_scenarios_root):
    app.mount("/scenario-assets", StaticFiles(directory=_scenarios_root), name="scenario-assets")

from pathlib import Path as _Path
_frontend_models = _Path(__file__).parent.parent.parent / "frontend" / "public" / "models"
if _frontend_models.exists():
    app.mount("/models", StaticFiles(directory=str(_frontend_models)), name="models")


@app.websocket("/ws")
async def ws_endpoint(
    ws: WebSocket,
    channel: str = Query("viewer"),
    token: str = Query(...),
):
    user = decode_ws_token(token)
    if user is None:
        await ws.close(code=4401)
        return
    user_id = user.user_id

    # 功能权限总闸：能不能用观众端/运营台，实时数据流必经这一关。
    required_perm = "access_operator" if channel == "operator" else "access_viewer"
    if not (user.is_admin or required_perm in user.permissions):
        await ws.close(code=4403)
        return

    try:
        ctx = await engine_manager.get_or_create(user_id)
    except RuntimeError as exc:
        logger.warning(f"[ws] user={user_id} 引擎实例创建失败: {exc}")
        await ws.close(code=4503)
        return

    await manager.connect(
        ws,
        user_id,
        channel,
        permissions=set(user.permissions),
        is_admin=user.is_admin,
    )
    logger.info(f"[ws] 客户端连接 user={user_id} channel={channel}")

    if ctx.engine.state:
        snapshot = ctx.engine.build_public_snapshot()
        await manager.send_to(ws, {
            "type": "world_snapshot",
            **snapshot,
        })

    try:
        while True:
            raw = await ws.receive_text()
            await _handle_command(user_id, raw)
    except WebSocketDisconnect:
        manager.disconnect(ws, user_id)
    except RuntimeError as exc:
        # Starlette 在客户端非常快地断开时偶尔抛 RuntimeError，
        # 语义等同于 WebSocketDisconnect；吞掉即可，避免污染运行日志。
        if "WebSocket is not connected" not in str(exc):
            raise
        manager.disconnect(ws, user_id)


@app.websocket("/agent/ws")
async def external_agent_ws(ws: WebSocket, t: str = Query(...)):
    from app.agent_gateway.ws_handler import handle_agent_ws
    await handle_agent_ws(ws, t)


# WebSocket 控制命令 → 所需功能权限映射。
# 与 REST 控制接口（routes.py）的 require_permission 语义保持一致，
# 防止低权限用户绕过 REST 直接用 WebSocket 控制对局 / 注入神谕。
_WS_COMMAND_PERMISSIONS = {
    "play": "control_game",
    "pause": "control_game",
    "step": "control_game",
    "reset": "control_game",
    "replay": "control_game",
    "speed": "control_game",
    "oracle": "inject_oracle",
}


async def _handle_command(user_id: str, raw: str) -> None:
    import json
    import traceback
    if engine_manager is None:
        return
    try:
        cmd = json.loads(raw)
    except Exception:
        return

    action = cmd.get("cmd")
    # 细粒度权限校验：握手时缓存的权限快照为准（is_admin 绕过）
    required_perm = _WS_COMMAND_PERMISSIONS.get(action)
    if required_perm is not None and not manager.can(user_id, required_perm):
        logger.warning(f"[ws] user={user_id} 无权限执行 {action}（需 {required_perm}）")
        await manager.broadcast(user_id, "viewer", {
            "type": "engine_error",
            "action": action,
            "error": f"无权限: {required_perm}",
        })
        return

    try:
        ctx = await engine_manager.get_or_create(user_id)
    except RuntimeError as exc:
        await manager.broadcast(user_id, "viewer", {
            "type": "engine_error", "action": cmd.get("cmd"), "error": str(exc),
        })
        return
    engine = ctx.engine
    ctx.touch()

    try:
        if action == "play":
            await engine.start()
        elif action == "pause":
            await engine.pause()
        elif action == "step":
            await engine.step()
        elif action == "reset":
            await engine.reset()
        elif action == "replay":
            await engine.start_replay(cmd.get("run_id"))
        elif action == "oracle":
            await engine.inject_oracle(
                cmd.get("target", "all"),
                str(cmd.get("text", "")),
                effects=cmd.get("effects") or None,
            )
        elif action == "speed":
            current = engine.get_runtime_config()["tick_interval_sec"]
            engine.set_tick_interval(float(cmd.get("interval", current)))
        await manager.broadcast(user_id, "viewer", {
            "type": "command_completed",
            "action": action,
        })
    except Exception as e:
        logger.error(f"[cmd] user={user_id} {action} 失败: {e}\n{traceback.format_exc()}")
        await manager.broadcast(user_id, "viewer", {
            "type": "engine_error",
            "action": action,
            "error": str(e),
        })
