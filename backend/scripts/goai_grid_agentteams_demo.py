"""Run the GOAI AgentTeams-style grid recovery demo end to end."""
from __future__ import annotations

import json

from app.agent_os.skills import execute_skill
from app.integrations.agentteams_adapter import (
    AgentTeamsAction,
    AgentTeamsTeam,
    AgentTeamsWorker,
    AgentTeamsWorldBridge,
)
from app.integrations.goai_grid_gateway import GridAgentTeamsGateway


def main() -> None:
    gateway = GridAgentTeamsGateway()
    try:
        bridge = AgentTeamsWorldBridge(gateway)
        team = AgentTeamsTeam(
            team_id="goai-grid-recovery-team",
            scenario_id=gateway.scenario.manifest.scenario_id,
            goal=gateway.scenario.goal_text,
            workers=[
                AgentTeamsWorker(
                    "grid_safety_dispatcher",
                    "safety_validator",
                    ["grid_observation_assessment", "grid_safety_validation"],
                ),
                AgentTeamsWorker(
                    "restoration_planner",
                    "restoration_planner",
                    ["grid_restoration_plan"],
                ),
                AgentTeamsWorker(
                    "resilience_operator",
                    "evidence_auditor",
                    ["grid_evidence_audit"],
                ),
            ],
            metadata={"demo": "goai-agentteams-grid-v1"},
        )
        run = bridge.create_run(team)

        observation = bridge.observe(run.run_id, "grid_safety_dispatcher")
        evidence = bridge.submit_evidence(
            run.run_id,
            "grid_safety_dispatcher",
            {
                "type": "grid2op_observation",
                "source": observation["observation"]["observation"]["observation_id"],
            },
        )
        assessment = execute_skill(
            "grid_observation_assessment",
            {
                "metrics": observation["observation"]["metrics"],
                "evidence_refs": [evidence["evidence_ref"]],
            },
        )
        bridge.record_skill_receipt(
            run.run_id,
            "grid_safety_dispatcher",
            assessment.model_dump(mode="json"),
        )

        plan = execute_skill(
            "grid_restoration_plan",
            {
                "assessment": assessment.output,
                "preferred_action": "restore_fault_line",
                "snapshot_ref": "snapshot:pre-restore",
                "evidence_refs": assessment.evidence_refs,
            },
        )
        bridge.record_skill_receipt(
            run.run_id,
            "restoration_planner",
            plan.model_dump(mode="json"),
        )

        blocked = bridge.submit_action(
            run.run_id,
            "restoration_planner",
            AgentTeamsAction(
                action_id="restore-proposal-1",
                action_type="restore_fault_line",
                evidence_refs=plan.evidence_refs,
                risk_level="high",
            ),
        )
        approval_id = blocked["details"]["approval_id"]
        validation_before = execute_skill(
            "grid_safety_validation",
            {"plan": plan.output, "evidence_refs": plan.evidence_refs},
        )
        bridge.record_skill_receipt(
            run.run_id,
            "grid_safety_dispatcher",
            validation_before.model_dump(mode="json"),
        )
        approval = bridge.resolve_approval(run.run_id, approval_id, "approved")
        validation_after = execute_skill(
            "grid_safety_validation",
            {
                "plan": plan.output,
                "approval_id": approval["approval_id"],
                "evidence_refs": plan.evidence_refs,
            },
        )
        bridge.record_skill_receipt(
            run.run_id,
            "grid_safety_dispatcher",
            validation_after.model_dump(mode="json"),
        )
        executed = bridge.submit_action(
            run.run_id,
            "restoration_planner",
            AgentTeamsAction(
                action_id="restore-approved-1",
                action_type="restore_fault_line",
                parameters={"approval_decision": "approved"},
                evidence_refs=[*plan.evidence_refs, approval["approval_id"]],
                risk_level="high",
            ),
        )
        audit = execute_skill(
            "grid_evidence_audit",
            {
                "trace_refs": [run.run_id],
                "evidence_refs": [*plan.evidence_refs, approval["approval_id"]],
                "approval_history": [approval],
                "high_risk": True,
            },
        )
        bridge.record_skill_receipt(
            run.run_id,
            "resilience_operator",
            audit.model_dump(mode="json"),
        )

        print(json.dumps({
            "scenario": gateway.scenario.manifest.scenario_id,
            "run": bridge.status(run.run_id),
            "approval_gate_receipt": blocked,
            "approved_execution_receipt": executed,
            "skill_receipts": [
                assessment.model_dump(mode="json"),
                plan.model_dump(mode="json"),
                validation_before.model_dump(mode="json"),
                validation_after.model_dump(mode="json"),
                audit.model_dump(mode="json"),
            ],
            "world_transitions": gateway.transitions,
        }, ensure_ascii=False, indent=2))
    finally:
        gateway.close()


if __name__ == "__main__":
    main()
