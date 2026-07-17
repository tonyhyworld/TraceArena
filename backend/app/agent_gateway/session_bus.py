"""Agent 会话总线：桥接 ExternalAgentProvider 与 /agent/ws WebSocket。"""
from __future__ import annotations

import asyncio
import json
import logging
import time
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from fastapi import WebSocket

from app.agent_gateway.token_store import get_token_store

logger = logging.getLogger(__name__)

PROTOCOL_VERSION = "0.2"
DEFAULT_TURN_TIMEOUT_MS = 120_000


@dataclass
class PendingTurn:
    turn_id: str
    event: asyncio.Event = field(default_factory=asyncio.Event)
    raw_model_output: Optional[str] = None
    structured_decision: Optional[Dict[str, Any]] = None
    turn_deadline_ms: int = 0


@dataclass
class ExternalAgentSession:
    slot_token: str
    user_id: str
    slot_id: str
    ws: Optional[WebSocket] = None
    state: str = "CONNECTED"
    brief_format: str = "rendered"
    seq: int = 0
    agent_label: Optional[str] = None
    pending: Optional[PendingTurn] = None


class ExternalAgentNotConnected(Exception):
    """外部 agent 未连接或未 ready。"""


class AgentSessionBus:
    def __init__(self) -> None:
        self._sessions: Dict[str, ExternalAgentSession] = {}

    def _session_for_token(self, slot_token: str) -> Optional[ExternalAgentSession]:
        return self._sessions.get(slot_token)

    def _next_seq(self, session: ExternalAgentSession) -> int:
        session.seq += 1
        return session.seq

    def envelope(
        self, session: ExternalAgentSession, msg_type: str, payload: Dict[str, Any],
    ) -> Dict[str, Any]:
        return {
            "type": msg_type,
            "seq": self._next_seq(session),
            "ts": time.time(),
            "payload": payload,
        }

    async def attach(self, slot_token: str, ws: WebSocket) -> ExternalAgentSession:
        rec = get_token_store().resolve(slot_token)
        if rec is None:
            raise ValueError("invalid_token")

        old = self._sessions.get(slot_token)
        if old and old.ws is not None and old.ws is not ws:
            try:
                await old.ws.send_text(json.dumps(
                    self.envelope(old, "error", {
                        "code": "replaced",
                        "message": "新的连接已建立，本连接被替换",
                    }),
                    ensure_ascii=False,
                ))
                await old.ws.close(code=4401)
            except Exception:
                pass

        session = ExternalAgentSession(
            slot_token=slot_token,
            user_id=rec.user_id,
            slot_id=rec.slot_id,
            ws=ws,
            state="CONNECTED",
            agent_label=rec.agent_label,
        )
        self._sessions[slot_token] = session
        return session

    def detach(self, slot_token: str, ws: Optional[WebSocket] = None) -> None:
        session = self._sessions.get(slot_token)
        if session is None:
            return
        if ws is not None and session.ws is not ws:
            return
        session.ws = None
        session.state = "CONNECTED"
        get_token_store().set_agent_label(slot_token, None)
        if session.pending and not session.pending.event.is_set():
            session.pending.event.set()

    async def send_session_ready(
        self,
        session: ExternalAgentSession,
        *,
        run_id: str,
        role: Dict[str, Any],
        turn_timeout_ms: int,
    ) -> None:
        if session.ws is None:
            return
        await session.ws.send_text(json.dumps(
            self.envelope(session, "session_ready", {
                "protocol_version": PROTOCOL_VERSION,
                "run_id": run_id,
                "role": role,
                "turn_timeout_ms": turn_timeout_ms,
            }),
            ensure_ascii=False,
            default=str,
        ))

    async def handle_client_message(
        self, slot_token: str, message: Dict[str, Any],
    ) -> None:
        session = self._session_for_token(slot_token)
        if session is None:
            return
        msg_type = str(message.get("type") or "")
        payload = message.get("payload") or {}

        if msg_type == "ready":
            session.state = "READY"
            session.brief_format = str(
                (payload.get("brief_format") if isinstance(payload, dict) else None)
                or "rendered"
            ).strip().lower()
            label = payload.get("agent_label") if isinstance(payload, dict) else None
            if label:
                session.agent_label = str(label)
                get_token_store().set_agent_label(slot_token, session.agent_label)
            return

        if msg_type == "pong":
            return

        if msg_type == "leave":
            self.detach(slot_token, session.ws)
            if session.ws:
                await session.ws.close()
            return

        if msg_type == "decision":
            pending = session.pending
            if pending is None:
                await self._send_error(session, "no_pending_turn", "当前无待决策回合")
                return
            turn_id = str(payload.get("turn_id") or "")
            if turn_id != pending.turn_id:
                await self._send_error(
                    session, "turn_id_mismatch", f"turn_id 不匹配，期望 {pending.turn_id}",
                )
                return
            if payload.get("raw_model_output") is not None:
                pending.raw_model_output = str(payload.get("raw_model_output"))
            else:
                pending.structured_decision = dict(payload)
            pending.event.set()
            session.state = "READY"
            session.pending = None
            return

        await self._send_error(session, "unknown_type", f"未知消息类型: {msg_type}")

    async def _send_error(
        self, session: ExternalAgentSession, code: str, message: str,
    ) -> None:
        if session.ws is None:
            return
        await session.ws.send_text(json.dumps(
            self.envelope(session, "error", {"code": code, "message": message}),
            ensure_ascii=False,
        ))

    async def request_decision(
        self,
        *,
        user_id: str,
        slot_id: str,
        run_id: str,
        tick: int,
        system_prompt: str,
        user_message: str,
        output_contract: Optional[Dict[str, Any]] = None,
        brief: Optional[Any] = None,
        turn_timeout_ms: int = DEFAULT_TURN_TIMEOUT_MS,
    ) -> str:
        rec = get_token_store().get_by_slot(user_id, slot_id)
        if rec is None:
            raise ExternalAgentNotConnected("slot_token 未生成")

        session = self._sessions.get(rec.slot_token)
        if session is None or session.ws is None or session.state != "READY":
            raise ExternalAgentNotConnected("外部 agent 未连接或未 ready")

        turn_id = f"{run_id}:t{tick}:{slot_id}"
        deadline_ms = int(time.time() * 1000) + int(turn_timeout_ms)
        pending = PendingTurn(turn_id=turn_id, turn_deadline_ms=deadline_ms)
        session.pending = pending
        session.state = "AWAITING"

        brief_payload: Dict[str, Any] = {
            "turn_id": turn_id,
            "turn_deadline_ms": deadline_ms,
            "output_contract": output_contract or {},
        }
        if session.brief_format == "structured" and brief is not None:
            if hasattr(brief, "model_dump"):
                brief_payload["brief"] = brief.model_dump(mode="json")
            else:
                brief_payload["brief"] = brief
        else:
            brief_payload["system_prompt"] = system_prompt
            brief_payload["user_message"] = user_message

        await session.ws.send_text(json.dumps(
            self.envelope(session, "tick_brief", brief_payload),
            ensure_ascii=False,
            default=str,
        ))

        try:
            await asyncio.wait_for(
                pending.event.wait(),
                timeout=max(0.1, turn_timeout_ms / 1000.0),
            )
        except asyncio.TimeoutError as exc:
            session.pending = None
            session.state = "READY"
            raise TimeoutError(f"external agent decision timeout>{turn_timeout_ms}ms") from exc

        if pending.raw_model_output:
            return pending.raw_model_output

        if pending.structured_decision:
            return json.dumps(pending.structured_decision, ensure_ascii=False)

        raise TimeoutError("external agent returned empty decision")

    async def notify_turn_result(
        self,
        *,
        user_id: str,
        slot_id: str,
        turn_id: str,
        accepted: bool,
        resolved_action_id: str,
        verdict: Optional[Dict[str, Any]] = None,
        is_system_fallback: bool = False,
    ) -> None:
        rec = get_token_store().get_by_slot(user_id, slot_id)
        if rec is None:
            return
        session = self._sessions.get(rec.slot_token)
        if session is None or session.ws is None:
            return
        await session.ws.send_text(json.dumps(
            self.envelope(session, "turn_result", {
                "turn_id": turn_id,
                "accepted": accepted,
                "resolved_action_id": resolved_action_id,
                "verdict": verdict or {},
                "is_system_fallback": is_system_fallback,
            }),
            ensure_ascii=False,
            default=str,
        ))

    async def notify_world_over(
        self, *, user_id: str, slot_id: str, summary: Optional[Dict[str, Any]] = None,
    ) -> None:
        rec = get_token_store().get_by_slot(user_id, slot_id)
        if rec is None:
            return
        session = self._sessions.get(rec.slot_token)
        if session is None or session.ws is None:
            return
        await session.ws.send_text(json.dumps(
            self.envelope(session, "world_over", summary or {}),
            ensure_ascii=False,
            default=str,
        ))
        try:
            await session.ws.close()
        except Exception:
            pass
        self.detach(rec.slot_token, session.ws)

    def connection_status(self, user_id: str, slot_id: str) -> Dict[str, Any]:
        rec = get_token_store().get_by_slot(user_id, slot_id)
        if rec is None:
            return {"connected": False, "status": "no_token"}
        session = self._sessions.get(rec.slot_token)
        connected = bool(session and session.ws is not None)
        state = session.state if session else "DISCONNECTED"
        return {
            "connected": connected,
            "status": state,
            "agent_label": (session.agent_label if session else rec.agent_label),
            "slot_token": rec.slot_token,
        }


_bus = AgentSessionBus()


def get_session_bus() -> AgentSessionBus:
    return _bus
