"""外部 Agent REST 路由（/agent/*）。"""
from __future__ import annotations

import logging
from typing import Any, Dict, Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from fastapi.responses import PlainTextResponse, Response
from pydantic import BaseModel, Field

from app.agent_gateway.session_bus import DEFAULT_TURN_TIMEOUT_MS, PROTOCOL_VERSION
from app.agent_gateway.skill_content import render_skill_md
from app.agent_gateway.token_store import get_token_store
from app.auth.dependencies import User, get_current_user, require_permission
from app.auth.permissions import Permission

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/agent", tags=["external-agent"])


def _base_url(request: Request) -> str:
    return str(request.base_url).rstrip("/")


def _ws_base_url(request: Request) -> str:
    base = _base_url(request)
    if base.startswith("https://"):
        return "wss://" + base[len("https://"):]
    if base.startswith("http://"):
        return "ws://" + base[len("http://"):]
    return base


class AgentDriverUpdate(BaseModel):
    driver: str = Field(..., description="llm 或 agent")
    provider: Optional[str] = None
    model: Optional[str] = None
    api_key: Optional[str] = None


@router.get("/skill.md", response_class=PlainTextResponse)
async def get_skill_md(request: Request) -> Response:
    body = render_skill_md(
        base_url=_base_url(request),
        protocol_version=PROTOCOL_VERSION,
    )
    return PlainTextResponse(
        content=body,
        media_type="text/markdown; charset=utf-8",
        headers={
            "Cache-Control": "public, max-age=3600",
            "X-Protocol-Version": PROTOCOL_VERSION,
        },
    )


@router.get("/join")
async def join_agent(request: Request, t: str) -> Dict[str, Any]:
    rec = get_token_store().resolve(t)
    if rec is None:
        raise HTTPException(404, "无效或已作废的席位令牌")

    from app.engine_manager import get_engine_manager

    engine_manager = get_engine_manager()

    role_name = rec.slot_id
    public_persona = ""
    output_contract: Dict[str, Any] = {}
    scenario_name = ""
    run_id = rec.run_id

    if engine_manager is not None:
        ctx = engine_manager.get_existing(rec.user_id)
        if ctx is not None:
            run_id = getattr(ctx.engine, "run_id", None) or run_id
            scenario_name = ctx.engine.scenario_directory_name
            slot = next((s for s in ctx.cfg.agents if s.id == rec.slot_id), None)
            if slot:
                role_name = slot.name
            try:
                role = ctx.engine._runtime.compiled.role_index.get(rec.slot_id)
                if role:
                    public_persona = str(getattr(role, "public_persona", "") or "")
            except Exception:
                pass
            try:
                output_contract = getattr(ctx.engine._loaded, "prompt_contract", {}) or {}
            except Exception:
                output_contract = {}

    ws_url = f"{_ws_base_url(request)}/agent/ws?t={t}"
    skill_url = f"{_base_url(request)}/agent/skill.md"
    return {
        "world": {
            "scenario": scenario_name,
            "run_id": run_id,
        },
        "role": {
            "slot_id": rec.slot_id,
            "display_name": role_name,
            "public_persona": public_persona,
        },
        "connect": {
            "transport": "websocket",
            "ws_url": ws_url,
            "protocol_version": PROTOCOL_VERSION,
        },
        "skill_url": skill_url,
        "turn_timeout_ms": DEFAULT_TURN_TIMEOUT_MS,
        "how_to_play": (
            "先读 skill_url 了解通用协议；连接 ws_url 后发送 ready，"
            "收到 tick_brief 后在 turn_deadline_ms 前回 decision。"
        ),
        "output_contract": output_contract,
    }


async def _get_engine_ctx(user: User):
    from app.engine_manager import get_engine_manager

    engine_manager = get_engine_manager()
    if engine_manager is None:
        raise HTTPException(503, "引擎未就绪")
    return await engine_manager.get_or_create(user.user_id)


@router.post("/slots/{slot_id}/link")
async def create_slot_link(
    slot_id: str,
    request: Request,
    user: User = Depends(require_permission(Permission.EDIT_MODEL_CONFIG)),
) -> Dict[str, Any]:
    ctx = await _get_engine_ctx(user)
    slot = next((s for s in ctx.cfg.agents if s.id == slot_id), None)
    if slot is None:
        raise HTTPException(404, f"角色 {slot_id} 不存在")

    rec = get_token_store().generate(user.user_id, slot_id)
    slot.driver = "agent"
    ctx.engine.reconfigure_agent_driver(slot_id, driver="agent")

    from app.auth.overrides_store import set_user_driver

    set_user_driver(user.user_id, slot_id, "agent")

    join_url = f"{_base_url(request)}/agent/join?t={rec.slot_token}"
    skill_url = f"{_base_url(request)}/agent/skill.md"
    return {
        "slot_id": slot_id,
        "join_url": join_url,
        "skill_url": skill_url,
        "slot_token": rec.slot_token,
        "expires_at": None,
        "protocol_version": PROTOCOL_VERSION,
        "copy_bundle": (
            f"Read {skill_url}, then connect with {join_url}"
        ),
    }


@router.delete("/slots/{slot_id}/link")
async def revoke_slot_link(
    slot_id: str,
    user: User = Depends(require_permission(Permission.EDIT_MODEL_CONFIG)),
) -> Dict[str, Any]:
    ctx = await _get_engine_ctx(user)
    ok = get_token_store().revoke(user.user_id, slot_id)
    if not ok:
        raise HTTPException(404, "该角色无有效链接")
    ctx.engine.reconfigure_agent_driver(slot_id, driver="llm")
    from app.auth.overrides_store import set_user_driver
    set_user_driver(user.user_id, slot_id, "llm")
    return {"status": "revoked", "slot_id": slot_id}


@router.get("/slots/{slot_id}/status")
async def slot_connection_status(
    slot_id: str,
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    from app.agent_gateway.session_bus import get_session_bus

    status = get_session_bus().connection_status(user.user_id, slot_id)
    rec = get_token_store().get_by_slot(user.user_id, slot_id)
    return {
        "slot_id": slot_id,
        "has_token": rec is not None,
        **status,
    }


@router.patch("/config/agents/{slot_id}/driver")
async def update_agent_driver(
    slot_id: str,
    body: AgentDriverUpdate,
    user: User = Depends(require_permission(Permission.EDIT_MODEL_CONFIG)),
) -> Dict[str, Any]:
    ctx = await _get_engine_ctx(user)
    driver = str(body.driver or "llm").strip().lower()
    if driver not in ("llm", "agent"):
        raise HTTPException(400, "driver 必须是 llm 或 agent")

    updated = ctx.engine.reconfigure_agent_driver(
        slot_id,
        driver=driver,
        provider=body.provider,
        model=body.model,
        api_key=body.api_key,
    )
    if not updated:
        raise HTTPException(404, f"角色 {slot_id} 不存在")

    from app.auth.overrides_store import set_user_driver, set_user_override

    set_user_driver(user.user_id, slot_id, driver)
    if driver == "llm" and body.provider and body.model:
        set_user_override(user.user_id, slot_id, body.provider, body.model)

    return {"status": "updated", "slot_id": slot_id, "driver": driver}
