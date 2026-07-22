"""AgentTeams-to-TraceArena integration contract.

This module deliberately has no hard dependency on AgentTeams/HiClaw.  It is the
stable boundary an AgentTeams Team/Worker adapter calls through, so TraceArena
can remain responsible for the scenario world, validation, approvals, evidence
and settlement rather than reimplementing team orchestration.

The bridge is executable and covered by unit tests.  A production transport
(REST, webhook or a native AgentTeams client) only has to translate its events
into these typed calls; it does not need to redesign the world-action chain.
"""
from __future__ import annotations

from dataclasses import dataclass, field
import time
from typing import Any, Dict, List, Protocol
from uuid import uuid4


@dataclass(frozen=True)
class AgentTeamsWorker:
    """A Worker declared by an AgentTeams team template.

    ``role`` is mapped to a scenario role; ``capabilities`` are the Skills or
    tools it may request.  The bridge never grants a Worker more permissions
    than the scenario role declares.
    """

    worker_id: str
    role: str
    capabilities: List[str] = field(default_factory=list)


@dataclass(frozen=True)
class AgentTeamsTeam:
    """Minimal Team payload received from the AgentTeams collaboration layer."""

    team_id: str
    scenario_id: str
    goal: str
    workers: List[AgentTeamsWorker]
    metadata: Dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AgentTeamsAction:
    """A structured Worker action before it enters a TraceArena world."""

    action_id: str
    action_type: str
    parameters: Dict[str, Any] = field(default_factory=dict)
    evidence_refs: List[str] = field(default_factory=list)
    risk_level: str = "low"


@dataclass
class AgentTeamsRun:
    """The durable mapping between one Team and one TraceArena world run."""

    run_id: str
    team_id: str
    world_run_id: str
    scenario_id: str
    worker_roles: Dict[str, str] = field(default_factory=dict)


class TraceArenaWorldGateway(Protocol):
    """Transport-neutral gateway implemented by the TraceArena application."""

    def create_world_run(
        self, scenario_id: str, goal: str, metadata: Dict[str, Any]
    ) -> str: ...

    def register_world_actor(
        self, world_run_id: str, actor_id: str, scenario_role: str
    ) -> Dict[str, Any]: ...

    def observe_world(
        self, world_run_id: str, actor_id: str
    ) -> Dict[str, Any]: ...

    def submit_world_action(
        self,
        world_run_id: str,
        actor_id: str,
        action: Dict[str, Any],
    ) -> Dict[str, Any]: ...

    def submit_world_evidence(
        self,
        world_run_id: str,
        actor_id: str,
        evidence: Dict[str, Any],
    ) -> Dict[str, Any]: ...

    def resolve_world_approval(
        self, world_run_id: str, approval_id: str, decision: str
    ) -> Dict[str, Any]: ...

    def world_status(self, world_run_id: str) -> Dict[str, Any]: ...


class AgentTeamsWorldBridge:
    """Maps AgentTeams collaboration events onto TraceArena world operations.

    AgentTeams remains the collaboration baseline: its Manager decomposes work
    and delegates to Workers.  This bridge provides the complementary world
    contract: role-scoped observation, structured action validation, evidence
    capture, approval/rollback gates and world status feedback.
    """

    _ALLOWED_RISK_LEVELS = {"low", "medium", "high", "critical"}

    def __init__(self, gateway: TraceArenaWorldGateway) -> None:
        self._gateway = gateway
        self._runs: Dict[str, AgentTeamsRun] = {}
        self._events: Dict[str, List[Dict[str, Any]]] = {}

    def create_run(self, team: AgentTeamsTeam) -> AgentTeamsRun:
        if not team.team_id.strip():
            raise ValueError("AgentTeams team_id is required")
        if not team.scenario_id.strip():
            raise ValueError("scenario_id is required")
        if not team.goal.strip():
            raise ValueError("world goal is required")
        if len(team.workers) < 3:
            raise ValueError("AgentTeams integration requires at least three Workers")

        seen = set()
        for worker in team.workers:
            if not worker.worker_id.strip() or not worker.role.strip():
                raise ValueError("every Worker requires worker_id and role")
            if worker.worker_id in seen:
                raise ValueError("Worker ids must be unique")
            seen.add(worker.worker_id)

        world_run_id = self._gateway.create_world_run(
            team.scenario_id,
            team.goal,
            {
                **team.metadata,
                "agentteams_team_id": team.team_id,
                "integration_contract": "agentteams-world-bridge/v1",
            },
        )
        run = AgentTeamsRun(
            run_id=f"atr-{uuid4().hex}",
            team_id=team.team_id,
            world_run_id=world_run_id,
            scenario_id=team.scenario_id,
        )
        self._runs[run.run_id] = run
        self._events[run.run_id] = []
        self._record(run.run_id, "run_created", {
            "team_id": team.team_id,
            "scenario_id": team.scenario_id,
            "worker_count": len(team.workers),
        })
        for worker in team.workers:
            self.sync_worker(run.run_id, worker)
        return run

    def sync_worker(self, run_id: str, worker: AgentTeamsWorker) -> Dict[str, Any]:
        run = self._run(run_id)
        if worker.worker_id in run.worker_roles:
            if run.worker_roles[worker.worker_id] != worker.role:
                raise ValueError("a Worker cannot change scenario role during a run")
            return {"actor_id": worker.worker_id, "role": worker.role, "synced": True}
        registration = self._gateway.register_world_actor(
            run.world_run_id, worker.worker_id, worker.role
        )
        run.worker_roles[worker.worker_id] = worker.role
        self._record(run.run_id, "worker_synced", {
            "worker_id": worker.worker_id,
            "role": worker.role,
            "capabilities": list(worker.capabilities),
        })
        return {"actor_id": worker.worker_id, "role": worker.role, **registration}

    def observe(self, run_id: str, worker_id: str) -> Dict[str, Any]:
        run = self._run(run_id)
        self._require_worker(run, worker_id)
        observation = self._gateway.observe_world(run.world_run_id, worker_id)
        self._record(run.run_id, "world_observed", {
            "worker_id": worker_id,
            "role": run.worker_roles[worker_id],
        })
        return {
            "run_id": run.run_id,
            "worker_id": worker_id,
            "scenario_role": run.worker_roles[worker_id],
            "observation": observation,
        }

    def submit_action(
        self, run_id: str, worker_id: str, action: AgentTeamsAction
    ) -> Dict[str, Any]:
        run = self._run(run_id)
        self._require_worker(run, worker_id)
        if action.risk_level not in self._ALLOWED_RISK_LEVELS:
            raise ValueError("unknown risk_level")
        if not action.action_id.strip() or not action.action_type.strip():
            raise ValueError("structured action_id and action_type are required")

        receipt = self._gateway.submit_world_action(
            run.world_run_id,
            worker_id,
            {
                "action_id": action.action_id,
                "action_type": action.action_type,
                "parameters": action.parameters,
                "evidence_refs": action.evidence_refs,
                "risk_level": action.risk_level,
                "source": "agentteams",
            },
        )
        # A high-risk request must never silently become executed.  The world
        # owns the final policy, while the bridge rejects an unsafe receipt.
        approval_decision = str(
            action.parameters.get("approval_decision") or ""
        ).strip().lower()
        if (
            action.risk_level in {"high", "critical"}
            and receipt.get("status") == "executed"
            and approval_decision != "approved"
        ):
            raise ValueError("high-risk actions require an approval gate before execution")
        self._record(run.run_id, "action_submitted", {
            "worker_id": worker_id,
            "action_id": action.action_id,
            "action_type": action.action_type,
            "risk_level": action.risk_level,
            "status": receipt.get("status"),
        })
        return receipt

    def submit_evidence(
        self, run_id: str, worker_id: str, evidence: Dict[str, Any]
    ) -> Dict[str, Any]:
        run = self._run(run_id)
        self._require_worker(run, worker_id)
        if not evidence.get("type") or not evidence.get("source"):
            raise ValueError("evidence requires type and source")
        receipt = self._gateway.submit_world_evidence(
            run.world_run_id,
            worker_id,
            {**evidence, "source_runtime": "agentteams"},
        )
        self._record(run.run_id, "evidence_submitted", {
            "worker_id": worker_id,
            "evidence_type": evidence.get("type"),
            "source": evidence.get("source"),
            "evidence_ref": receipt.get("evidence_ref"),
        })
        return receipt

    def resolve_approval(
        self, run_id: str, approval_id: str, decision: str
    ) -> Dict[str, Any]:
        if decision not in {"approved", "rejected", "rollback"}:
            raise ValueError("approval decision must be approved, rejected or rollback")
        run = self._run(run_id)
        receipt = self._gateway.resolve_world_approval(
            run.world_run_id, approval_id, decision
        )
        self._record(run.run_id, "approval_resolved", {
            "approval_id": approval_id,
            "decision": decision,
            "status": receipt.get("status"),
        })
        return receipt

    def record_skill_receipt(
        self,
        run_id: str,
        worker_id: str,
        skill_receipt: Dict[str, Any],
    ) -> Dict[str, Any]:
        run = self._run(run_id)
        self._require_worker(run, worker_id)
        self._record(run_id, "skill_executed", {
            "worker_id": worker_id,
            "skill_id": skill_receipt.get("skill_id"),
            "status": skill_receipt.get("status"),
            "evidence_refs": list(skill_receipt.get("evidence_refs") or []),
            "errors": list(skill_receipt.get("errors") or []),
        })
        return {
            "run_id": run_id,
            "worker_id": worker_id,
            "recorded": True,
        }

    def status(self, run_id: str) -> Dict[str, Any]:
        run = self._run(run_id)
        return {
            "run_id": run.run_id,
            "team_id": run.team_id,
            "scenario_id": run.scenario_id,
            "workers": run.worker_roles,
            "world": self._gateway.world_status(run.world_run_id),
            "observability": self._observability(run_id),
            "timeline": list(self._events.get(run_id, [])),
        }

    def _run(self, run_id: str) -> AgentTeamsRun:
        try:
            return self._runs[run_id]
        except KeyError as exc:
            raise ValueError("unknown AgentTeams run") from exc

    @staticmethod
    def _require_worker(run: AgentTeamsRun, worker_id: str) -> None:
        if worker_id not in run.worker_roles:
            raise ValueError("Worker is not mapped to this world run")

    def _record(self, run_id: str, event_type: str, payload: Dict[str, Any]) -> None:
        self._events.setdefault(run_id, []).append({
            "seq": len(self._events.get(run_id, [])) + 1,
            "event_type": event_type,
            "occurred_at": time.time(),
            **payload,
        })

    def _observability(self, run_id: str) -> Dict[str, Any]:
        events = self._events.get(run_id, [])
        counts: Dict[str, int] = {}
        for item in events:
            event_type = str(item.get("event_type") or "")
            counts[event_type] = counts.get(event_type, 0) + 1
        started = events[0]["occurred_at"] if events else time.time()
        ended = events[-1]["occurred_at"] if events else started
        return {
            "event_counts": counts,
            "duration_ms": int(max(0.0, ended - started) * 1000),
            "skill_success_count": sum(
                1 for item in events
                if item.get("event_type") == "skill_executed"
                and item.get("status") not in {"error", "fail"}
            ),
            "approval_count": counts.get("approval_resolved", 0),
            "action_count": counts.get("action_submitted", 0),
        }
