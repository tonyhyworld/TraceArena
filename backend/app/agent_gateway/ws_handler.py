"""外部 Agent WebSocket 处理器（/agent/ws）。"""
from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Dict, Optional

from fastapi import WebSocket, WebSocketDisconnect

from app.agent_gateway.session_bus import (
    DEFAULT_TURN_TIMEOUT_MS,
    get_session_bus,
)
from app.agent_gateway.token_store import get_token_store

logger = logging.getLogger(__name__)


async def handle_agent_ws(ws: WebSocket, slot_token: str) -> None:
    rec = get_token_store().resolve(slot_token)
    if rec is None:
        await ws.close(code=4401)
        return

    bus = get_session_bus()
    try:
        await ws.accept()
        session = await bus.attach(slot_token, ws)
    except ValueError:
        await ws.close(code=4401)
        return

    run_id = rec.run_id or "run_pending"
    role_name = rec.slot_id
    public_persona = ""

    from app.engine_manager import get_engine_manager

    engine_manager = get_engine_manager()

    if engine_manager is not None:
        ctx = engine_manager.get_existing(rec.user_id)
        if ctx is not None:
            run_id = getattr(ctx.engine, "run_id", None) or run_id
            slot = next((s for s in ctx.cfg.agents if s.id == rec.slot_id), None)
            if slot:
                role_name = slot.name
            try:
                role = ctx.engine._runtime.compiled.role_index.get(rec.slot_id)
                if role:
                    public_persona = str(getattr(role, "public_persona", "") or "")
            except Exception:
                pass

    await bus.send_session_ready(
        session,
        run_id=run_id,
        role={
            "slot_id": rec.slot_id,
            "display_name": role_name,
            "public_persona": public_persona,
        },
        turn_timeout_ms=DEFAULT_TURN_TIMEOUT_MS,
    )

    ping_task: Optional[asyncio.Task] = None

    async def _ping_loop() -> None:
        while True:
            await asyncio.sleep(30)
            if session.ws is None:
                break
            try:
                await session.ws.send_text(json.dumps({
                    "type": "ping",
                    "seq": bus._next_seq(session),
                    "ts": __import__("time").time(),
                    "payload": {},
                }))
            except Exception:
                break

    ping_task = asyncio.create_task(_ping_loop())

    try:
        while True:
            raw = await ws.receive_text()
            try:
                msg = json.loads(raw)
            except json.JSONDecodeError:
                await bus._send_error(session, "invalid_json", "消息必须是 JSON")
                continue
            if not isinstance(msg, dict):
                continue
            if msg.get("type") == "ping":
                await ws.send_text(json.dumps({
                    "type": "pong",
                    "seq": bus._next_seq(session),
                    "ts": __import__("time").time(),
                    "payload": {},
                }))
                continue
            await bus.handle_client_message(slot_token, msg)
    except WebSocketDisconnect:
        pass
    except RuntimeError as exc:
        if "WebSocket is not connected" not in str(exc):
            raise
    finally:
        if ping_task:
            ping_task.cancel()
        bus.detach(slot_token, ws)
