"""HTTP 路由：健康检查 + 运营台控制接口"""
from __future__ import annotations

from pathlib import Path
import asyncio
import uuid
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, Header, HTTPException
from pydantic import BaseModel, Field, field_validator

from app.auth.dependencies import get_current_user, require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.engine_manager import UserEngineContext
from app.core.path_safety import path_beneath, safe_path_component

_PROVIDERS = ["mock", "openai", "deepseek", "anthropic", "minimax", "huggingface"]

router = APIRouter()

# benchmark 任务表：job_id → {status, report, error, user_id}
# 跨用户隔离靠 user_id 字段在读取时校验，而不是拆表——量级很小，没必要拆。
_benchmark_jobs: Dict[str, Dict[str, Any]] = {}


async def _get_ctx(user: User) -> UserEngineContext:
    """惰性获取（不存在则创建）当前用户的引擎实例；并发超限时转译成 429"""
    from app.main import engine_manager
    if engine_manager is None:
        raise HTTPException(503, "引擎管理器未初始化")
    try:
        return await engine_manager.get_or_create(user.user_id)
    except RuntimeError as exc:
        raise HTTPException(429, str(exc))


def _get_existing_ctx(user: User) -> Optional[UserEngineContext]:
    """只读查询，不触发创建（避免访问一个只是想看看有没有场景的接口就意外拉起引擎）"""
    from app.main import engine_manager
    if engine_manager is None:
        return None
    return engine_manager.get_existing(user.user_id)


# ------------------------------------------------------------------
# 健康检查（保持公开，不要求登录，供进程存活探测使用）
# ------------------------------------------------------------------

@router.get("/")
async def root() -> Dict[str, Any]:
    from app.main import engine_manager
    active = len(engine_manager._contexts) if engine_manager is not None else 0
    return {"status": "ok", "active_engines": active}


# ------------------------------------------------------------------
# 运营台控制（也可以通过 WebSocket 命令发，这里提供 REST 备用）
# ------------------------------------------------------------------

class OracleRequest(BaseModel):
    target: str = "all"
    text: str
    effects: Optional[List[Dict[str, Any]]] = None


class ReplayRequest(BaseModel):
    run_id: Optional[str] = None


class AnnouncementTTSRequest(BaseModel):
    text: str = Field(min_length=1, max_length=6000)


class LocaleRequest(BaseModel):
    locale: str


@router.post("/control/locale")
async def switch_locale(req: LocaleRequest, user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """Change presentation immediately and defer agent-language changes to reset."""
    if req.locale not in {"zh-CN", "en-US"}:
        raise HTTPException(400, "Unsupported locale")
    from app.main import engine_manager
    if engine_manager is None:
        raise HTTPException(503, "Engine manager unavailable")
    engine_manager.set_preferred_locale(user.user_id, req.locale)
    current = engine_manager.get_existing(user.user_id)
    runtime_locale = current.cfg.scenario_locale if current is not None else req.locale
    return {
        "status": "saved",
        "locale": req.locale,
        "runtime_locale": runtime_locale,
        "applies_to_current_run": runtime_locale == req.locale,
    }


@router.post("/control/play")
async def play(user: User = Depends(require_permission(Permission.CONTROL_GAME))) -> Dict[str, str]:
    ctx = await _get_ctx(user)
    await ctx.engine.start()
    return {"status": "playing"}


@router.post("/control/pause")
async def pause(user: User = Depends(require_permission(Permission.CONTROL_GAME))) -> Dict[str, str]:
    ctx = await _get_ctx(user)
    await ctx.engine.pause()
    return {"status": "paused"}


@router.post("/control/step")
async def step(user: User = Depends(require_permission(Permission.CONTROL_GAME))) -> Dict[str, str]:
    ctx = await _get_ctx(user)
    await ctx.engine.step()
    return {"status": "stepped"}


@router.post("/control/reset")
async def reset(user: User = Depends(require_permission(Permission.CONTROL_GAME))) -> Dict[str, str]:
    from app.main import engine_manager
    await engine_manager.reset_for_new_run(user.user_id)
    return {"status": "reset"}


@router.get("/replays")
async def list_replays(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    ctx = await _get_ctx(user)
    items = ctx.engine.list_replays()
    return {"count": len(items), "replays": items}


@router.post("/control/replay")
async def replay(req: ReplayRequest, user: User = Depends(require_permission(Permission.CONTROL_GAME))) -> Dict[str, Any]:
    ctx = await _get_ctx(user)
    await ctx.engine.start_replay(req.run_id)
    return {"status": "replaying", "run_id": req.run_id}


@router.post("/control/oracle")
async def oracle(req: OracleRequest, user: User = Depends(require_permission(Permission.INJECT_ORACLE))) -> Dict[str, str]:
    if not req.text.strip():
        raise HTTPException(400, "text 不能为空")
    ctx = await _get_ctx(user)
    await ctx.engine.inject_oracle(req.target, req.text, effects=req.effects)
    return {"status": "injected"}


@router.get("/logs/recent")
async def recent_logs(user: User = Depends(require_permission(Permission.ACCESS_OPERATOR))) -> Dict[str, Any]:
    ctx = await _get_ctx(user)
    logs = ctx.engine.get_all_logs()
    return {
        "count": len(logs),
        "logs": [l.model_dump() for l in logs],
    }


@router.get("/operator/live-overview")
async def operator_live_overview(
    locale: Optional[str] = None,
    user: User = Depends(require_permission(Permission.ACCESS_OPERATOR)),
) -> Dict[str, Any]:
    """运营后台首屏快照。

    WebSocket 适合增量推送，但后台刷新后不能依赖“下一条推送”才有内容。
    这个接口一次性返回当前世界、模型日志和 OS2 事实账本，
    让运营台首屏稳定可用。
    """
    ctx = await _get_ctx(user)
    engine = ctx.engine
    snapshot = engine.build_public_snapshot() or {}
    logs = engine.get_recent_logs()
    state = engine.state
    assessment = (
        (state.internal.get("capability_assessment", {}) or {})
        if state is not None else {}
    )
    internal = getattr(state, "internal", {}) or {} if state else {}
    return {
        "status": {
            "ready": state is not None,
            "is_running": bool(getattr(state, "is_running", False)) if state else False,
            "tick": int(getattr(state, "tick", 0) or 0) if state else 0,
            "is_game_over": bool(getattr(state, "is_game_over", False)) if state else False,
            "winner_id": getattr(state, "winner_id", None) if state else None,
        },
        "snapshot": snapshot,
        "logs": [log.model_dump() for log in logs],
        "assessment": {
            "profiles": assessment.get("profiles", {}),
            "cases": assessment.get("cases", []),
            "events": assessment.get("events", []),
        },
        "operator_schema": engine.get_operator_schema(locale),
        "os2": {
            "world_actions": list(
                internal.get("os2_world_actions", []) or []
            )[-300:],
            "external_observations": list(
                internal.get("os2_external_observations", []) or []
            )[-300:],
            "agent_activities": list(
                internal.get("os2_agent_activities", []) or []
            )[-300:],
            "world_events": list(
                internal.get("os2_world_events", []) or []
            )[-300:],
            "settlements": list(
                internal.get("os2_settlements", []) or []
            )[-300:],
            "director_plan": (
                list(internal.get("os2_director_plans", []) or [])[-1]
                if internal.get("os2_director_plans")
                else None
            ),
            "director_plans": list(
                internal.get("os2_director_plans", []) or []
            )[-100:],
        },
        "config": engine.get_runtime_config(),
    }


# ------------------------------------------------------------------
# 配置读写接口（前端配置面板使用）
# ------------------------------------------------------------------

@router.get("/config")
async def get_config(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """返回当前运行配置（Agent 列表 + 场景信息）"""
    ctx = await _get_ctx(user)
    return {
        **ctx.engine.get_runtime_config(),
        "available_providers": _PROVIDERS,
    }


class AgentConfigUpdate(BaseModel):
    provider: str
    model: str
    api_key: Optional[str] = None   # 留空=继续读 .env；填入则临时覆盖


class BenchmarkCompetitorRequest(BaseModel):
    id: str
    provider: str
    model: str
    extra: Dict[str, Any] = Field(default_factory=dict)
    api_key: Optional[str] = None


class BenchmarkStartRequest(BaseModel):
    scenario_name: Optional[str] = None
    competitors: List[BenchmarkCompetitorRequest]
    repeats: int = 3
    base_seed: int = 20260619
    rotate_roles: bool = True
    agent_timeout_sec: float = 30.0
    validity_policy: Dict[str, Any] = Field(default_factory=dict)

    @field_validator("scenario_name")
    @classmethod
    def validate_scenario_name(cls, value: Optional[str]) -> Optional[str]:
        if value is None:
            return None
        return safe_path_component(value, label="scenario_name")


@router.patch("/config/agents/{agent_id}")
async def update_agent_config(agent_id: str, update: AgentConfigUpdate, user: User = Depends(require_permission(Permission.EDIT_MODEL_CONFIG))) -> Dict[str, Any]:
    """运行时切换指定 Agent 的 LLM Provider / Model（BYOK：只影响当前用户自己）

    持久化到该用户私有的 user_data/<user_id>/framework_overrides.json（provider/model）
    和 secrets.json（api_key，如果填了）——不再写全局 framework.yaml，
    不影响其他用户的默认配置。
    """
    from app.auth.overrides_store import set_user_override
    from app.auth.secrets_store import set_user_secret

    ctx = await _get_ctx(user)
    updated = ctx.engine.reconfigure_agent(
        agent_id,
        provider=update.provider,
        model=update.model,
        api_key=update.api_key,
    )
    if not updated:
        raise HTTPException(404, f"Agent {agent_id} 不存在")
    set_user_override(user.user_id, agent_id, update.provider, update.model)
    if update.api_key:
        set_user_secret(user.user_id, agent_id, update.api_key)
    return {"status": "updated", "agent_id": agent_id, "provider": update.provider, "model": update.model}


@router.post("/benchmark/start")
async def start_benchmark(req: BenchmarkStartRequest, user: User = Depends(require_permission(Permission.RUN_BENCHMARK))) -> Dict[str, Any]:
    """后台启动严格基准实验，不影响当前用户的 viewer 引擎。"""
    ctx = await _get_ctx(user)
    engine = ctx.engine
    from app.benchmark.models import (
        BenchmarkSpec,
        CompetitorSpec,
        ValidityPolicy,
    )
    from app.benchmark.runner import BenchmarkRunner

    try:
        scenario_name = safe_path_component(
            req.scenario_name or engine.scenario_directory_name,
            label="scenario_name",
        )
    except ValueError as exc:
        raise HTTPException(400, "非法场景名") from exc
    scenario_path = path_beneath(
        Path(engine.scenario_definition.scenario_dir).parent, scenario_name
    )
    if not scenario_path.exists():
        raise HTTPException(404, f"场景不存在: {scenario_name}")

    job_id = f"benchjob_{uuid.uuid4().hex[:10]}"
    _benchmark_jobs[job_id] = {"status": "running", "report": None, "error": None, "user_id": user.user_id}

    async def _run() -> None:
        try:
            spec = BenchmarkSpec(
                scenario_path=str(scenario_path),
                competitors=[
                    CompetitorSpec(**item.model_dump())
                    for item in req.competitors
                ],
                repeats=req.repeats,
                base_seed=req.base_seed,
                rotate_roles=req.rotate_roles,
                agent_timeout_sec=req.agent_timeout_sec,
                validity_policy=ValidityPolicy(**req.validity_policy),
                output_dir=str(Path("./benchmark_runs").resolve()),
            )
            report = await BenchmarkRunner(spec).run()
            _benchmark_jobs[job_id] = {
                "status": "completed",
                "report": report.model_dump(),
                "error": None,
                "user_id": user.user_id,
            }
        except Exception as exc:
            _benchmark_jobs[job_id] = {
                "status": "failed",
                "report": None,
                "error": str(exc),
                "user_id": user.user_id,
            }

    asyncio.create_task(_run())
    return {"job_id": job_id, "status": "running"}


@router.get("/benchmark/{job_id}")
async def get_benchmark_job(job_id: str, user: User = Depends(get_current_user)) -> Dict[str, Any]:
    job = _benchmark_jobs.get(job_id)
    if not job or (job.get("user_id") and job["user_id"] != user.user_id and not user.is_admin):
        raise HTTPException(404, f"Benchmark 任务不存在: {job_id}")
    return {"job_id": job_id, **{k: v for k, v in job.items() if k != "user_id"}}


@router.get("/assessment")
async def get_current_assessment(user: User = Depends(require_permission(Permission.ACCESS_OPERATOR))) -> Dict[str, Any]:
    """运营/B端读取当前对局的十大能力画像与完整案例证据链。"""
    ctx = await _get_ctx(user)
    if ctx.engine.state is None:
        raise HTTPException(503, "引擎未初始化")
    store = ctx.engine.state.internal.get("capability_assessment", {}) or {}
    return {
        "profiles": store.get("profiles", {}),
        "cases": store.get("cases", []),
        "events": store.get("events", []),
    }


@router.get("/scenario")
async def get_scenario(
    locale: Optional[str] = None,
    accept_language: Optional[str] = Header(default=None),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """返回当前场景包的完整信息（前端渲染用）。

    前端据此动态渲染，不再写死任何场景内容。
    """
    ctx = await _get_ctx(user)
    requested_locale = locale or str(accept_language or "").split(",", 1)[0].strip()
    engine = ctx.engine
    sc = engine.localized_scenario(requested_locale)
    character_map = {
        item.get("id"): item
        for item in sc.characters_cfg
        if isinstance(item, dict) and item.get("id")
    }

    def _role_model(role: Any) -> str:
        if role.model_glb:
            return role.model_glb
        profile = role.capability_profile or {}
        character = character_map.get(profile.get("character_id"), {})
        model = character.get("model", {}) if isinstance(character, dict) else {}
        return model.get("asset", "") if isinstance(model, dict) else ""

    return {
        "name": sc.manifest.name,
        "locale": sc.locale,
        "dir_name": sc.scenario_dir.name,
        "presentation": sc.presentation.model_dump(),
        "world_variables": [v.model_dump() for v in sc.world_variables],
        "role_sprites": {
            r.agent_slot_id: r.sprite_image
            for r in sc.agent_roles
            if r.sprite_image
        },
        "role_models": {
            r.agent_slot_id: _role_model(r)
            for r in sc.agent_roles
            if _role_model(r)
        },
        "characters": sc.characters_cfg,
        "assets_manifest": sc.assets_manifest,
        "compilation": engine.get_compilation_report(),
        # agent 槽位信息（前端初始化时用于创建3D角色，含颜色/模型/出生位置）
        "agent_slots": [
            {
                "id": r.agent_slot_id,
                "name": r.display_name,
                "color": getattr(r, 'color', '') or '',
                "model_glb": _role_model(r),
                "start_location": r.start_location or "",
                "character_id": str(
                    (r.capability_profile or {}).get("character_id") or ""
                ),
                "role_title": getattr(r, "role_title", "") or "",
                "public_persona": getattr(r, "public_persona", "") or "",
            }
            for r in sc.agent_roles
        ],
        # 场景信息
        "scene_config": sc.scene_config,
        "scene_theme": sc.scene_theme,
        "background_text": sc.background_text,
        # 导演配置
        "director_cfg": sc.director_cfg,
        "director_skills": engine.get_director_capabilities(),
        # 播放策略
        "playback_policy": sc.playback_policy,
        # 世界规则
        "visibility_rules": sc.visibility_rules,
        "causal_physics_config": sc.causal_physics_config,
        # 通用态势 HUD：测量定义与场景结算口径，不包含运行秘密。
        "metrics_cfg": sc.metrics_cfg,
        "audit_cfg": sc.audit_cfg,
        "settlement_cfg": sc.settlement_cfg,
        # 网格地图（逻辑层地点定义）
        "world_locations": sc.presentation.render.world_locations if hasattr(sc.presentation, 'render') else [],
        # 任务目标 + 可用行动
        "goal_text": sc.goal_text or "",
        "actions_cfg": [
            {
                "id": a.get("id", ""),
                "name": a.get("name", a.get("id", "")),
                "description": a.get("description", ""),
                "requires_target": a.get("requires_target", False),
                "allows_code": a.get("allows_code", False),
                "cost": a.get("cost", {}),
            }
            for a in sc.actions_cfg if isinstance(a, dict)
        ],
    }


@router.post("/scenario/announcement/tts")
async def synthesize_scenario_announcement(
    req: AnnouncementTTSRequest,
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """使用 OS 导演 TTS 朗读从当前场景包加载的公告。"""
    ctx = await _get_ctx(user)
    chunks = await ctx.engine.synthesize_announcement(req.text.strip())
    return {"chunks": chunks, "tts_enabled": bool(chunks)}


# ------------------------------------------------------------------
# 场景包管理
# ------------------------------------------------------------------

def _dir_scenario_names(base: Path) -> List[str]:
    if not base.exists():
        return []
    return sorted(
        d.name for d in base.iterdir()
        if d.is_dir() and (d / "manifest.json").exists()
    )


@router.get("/scenarios")
async def list_scenarios(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """列出可用场景包：全局公共场景 + 该用户私有上传的场景（同名时私有优先加载）"""
    public_names = _dir_scenario_names(Path("./scenarios"))
    private_names = _dir_scenario_names(
        path_beneath("./user_data", user.user_id, "scenarios")
    )
    names = sorted(set(public_names) | set(private_names))
    ctx = _get_existing_ctx(user)  # 只读查询，避免为了列列表而拉起引擎
    current = ctx.engine.scenario_directory_name if ctx is not None else ""
    return {
        "scenarios": names,
        "private_scenarios": private_names,
        "current": current,
    }


class LoadScenarioRequest(BaseModel):
    scenario_name: str

    @field_validator("scenario_name")
    @classmethod
    def validate_scenario_name(cls, value: str) -> str:
        return safe_path_component(value, label="scenario_name")


@router.post("/control/load-scenario")
async def load_scenario_api(req: LoadScenarioRequest, user: User = Depends(require_permission(Permission.MANAGE_SCENARIO))) -> Dict[str, Any]:
    """运行时切换场景包（不重启进程，只影响当前用户自己的引擎实例）"""
    from app.main import engine_manager
    try:
        current = engine_manager.get_existing(user.user_id)
        current_locale = current.cfg.scenario_locale if current is not None else None
        await engine_manager.rebuild_engine(user.user_id, req.scenario_name, locale=current_locale)
    except Exception as e:
        raise HTTPException(500, f"场景切换失败: {e}")
    return {"status": "loaded", "scenario": req.scenario_name}
