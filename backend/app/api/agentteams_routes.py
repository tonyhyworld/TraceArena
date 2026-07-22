"""HTTP/Webhook transport for AgentTeams-compatible runtimes."""
from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Header, HTTPException
from pydantic import BaseModel, Field

from app.agent_os.skills import execute_skill
from app.integrations.agentteams_adapter import (
    AgentTeamsAction,
    AgentTeamsTeam,
    AgentTeamsWorker,
    AgentTeamsWorldBridge,
)
from app.integrations.goai_grid_gateway import GridAgentTeamsGateway


router = APIRouter(prefix="/integrations/agentteams", tags=["agentteams"])


@dataclass
class HostedAgentTeamsRun:
    bridge: AgentTeamsWorldBridge
    gateway: GridAgentTeamsGateway


_RUNS: Dict[str, HostedAgentTeamsRun] = {}


class WorkerPayload(BaseModel):
    worker_id: str = Field(min_length=1, max_length=120)
    role: str = Field(min_length=1, max_length=120)
    capabilities: List[str] = Field(default_factory=list)


class TeamCreatePayload(BaseModel):
    team_id: str = Field(min_length=1, max_length=120)
    scenario_id: str = Field(default="grid_extreme_event_recovery_v1")
    goal: str = Field(min_length=1, max_length=20_000)
    workers: List[WorkerPayload] = Field(min_length=3)
    metadata: Dict[str, Any] = Field(default_factory=dict)


class ActionPayload(BaseModel):
    action_id: str = Field(min_length=1, max_length=160)
    action_type: str = Field(min_length=1, max_length=160)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list)
    risk_level: str = "low"


class EvidencePayload(BaseModel):
    type: str = Field(min_length=1, max_length=160)
    source: str = Field(min_length=1, max_length=500)
    payload: Dict[str, Any] = Field(default_factory=dict)


class ApprovalPayload(BaseModel):
    decision: str = Field(pattern="^(approved|rejected|rollback)$")


class SkillExecutionPayload(BaseModel):
    skill_id: str = Field(min_length=1, max_length=160)
    worker_id: str = Field(min_length=1, max_length=120)
    payload: Dict[str, Any] = Field(default_factory=dict)


class SkillReceiptPayload(BaseModel):
    worker_id: str = Field(min_length=1, max_length=120)
    receipt: Dict[str, Any] = Field(default_factory=dict)


def _require_transport_token(token: Optional[str]) -> None:
    expected = os.getenv("AGENTTEAMS_WEBHOOK_TOKEN", "").strip()
    allow_unauth = os.getenv("AIWORLD_AGENTTEAMS_ALLOW_UNAUTH", "") == "1"
    if not expected and allow_unauth:
        return
    if not expected:
        raise HTTPException(
            503,
            "AGENTTEAMS_WEBHOOK_TOKEN is not configured",
        )
    if token != expected:
        raise HTTPException(401, "invalid AgentTeams transport token")


def _hosted(run_id: str) -> HostedAgentTeamsRun:
    hosted = _RUNS.get(run_id)
    if hosted is None:
        raise HTTPException(404, "AgentTeams run not found")
    return hosted


@router.post("/runs")
async def create_run(
    req: TeamCreatePayload,
    x_agentteams_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _require_transport_token(x_agentteams_token)
    gateway = GridAgentTeamsGateway()
    bridge = AgentTeamsWorldBridge(gateway)
    try:
        run = bridge.create_run(
            AgentTeamsTeam(
                team_id=req.team_id,
                scenario_id=req.scenario_id,
                goal=req.goal,
                workers=[
                    AgentTeamsWorker(
                        worker.worker_id,
                        worker.role,
                        list(worker.capabilities),
                    )
                    for worker in req.workers
                ],
                metadata={
                    **req.metadata,
                    "transport": "http",
                    "transport_contract": "agentteams-http/v1",
                },
            )
        )
    except Exception:
        gateway.close()
        raise
    _RUNS[run.run_id] = HostedAgentTeamsRun(bridge=bridge, gateway=gateway)
    return {
        "run": run.__dict__,
        "status": bridge.status(run.run_id),
    }


@router.get("/runs/{run_id}/workers/{worker_id}/observe")
async def observe(
    run_id: str,
    worker_id: str,
    x_agentteams_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _require_transport_token(x_agentteams_token)
    return _hosted(run_id).bridge.observe(run_id, worker_id)


@router.post("/runs/{run_id}/workers/{worker_id}/evidence")
async def submit_evidence(
    run_id: str,
    worker_id: str,
    req: EvidencePayload,
    x_agentteams_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _require_transport_token(x_agentteams_token)
    return _hosted(run_id).bridge.submit_evidence(
        run_id,
        worker_id,
        {
            "type": req.type,
            "source": req.source,
            "payload": req.payload,
        },
    )


@router.post("/runs/{run_id}/workers/{worker_id}/actions")
async def submit_action(
    run_id: str,
    worker_id: str,
    req: ActionPayload,
    x_agentteams_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _require_transport_token(x_agentteams_token)
    return _hosted(run_id).bridge.submit_action(
        run_id,
        worker_id,
        AgentTeamsAction(
            action_id=req.action_id,
            action_type=req.action_type,
            parameters=req.parameters,
            evidence_refs=req.evidence_refs,
            risk_level=req.risk_level,
        ),
    )


@router.post("/runs/{run_id}/approvals/{approval_id}")
async def resolve_approval(
    run_id: str,
    approval_id: str,
    req: ApprovalPayload,
    x_agentteams_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _require_transport_token(x_agentteams_token)
    return _hosted(run_id).bridge.resolve_approval(
        run_id,
        approval_id,
        req.decision,
    )


@router.post("/runs/{run_id}/skills/execute")
async def run_skill(
    run_id: str,
    req: SkillExecutionPayload,
    x_agentteams_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _require_transport_token(x_agentteams_token)
    hosted = _hosted(run_id)
    receipt = execute_skill(req.skill_id, req.payload).model_dump(mode="json")
    hosted.bridge.record_skill_receipt(run_id, req.worker_id, receipt)
    return receipt


@router.post("/runs/{run_id}/skills/receipts")
async def record_skill_receipt(
    run_id: str,
    req: SkillReceiptPayload,
    x_agentteams_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _require_transport_token(x_agentteams_token)
    return _hosted(run_id).bridge.record_skill_receipt(
        run_id,
        req.worker_id,
        req.receipt,
    )


@router.get("/runs/{run_id}/status")
async def status(
    run_id: str,
    x_agentteams_token: Optional[str] = Header(default=None),
) -> Dict[str, Any]:
    _require_transport_token(x_agentteams_token)
    return _hosted(run_id).bridge.status(run_id)
