"""Run the synthetic incident-response fixture without external dependencies."""
from __future__ import annotations

import json
import sys
from pathlib import Path
from typing import Any


def settle(payload: dict[str, Any]) -> dict[str, Any]:
    evidence = payload["evidence"]
    status = "open"
    acknowledged = False
    mitigated = False
    health_check_passed = False
    health = 40
    progress = 0
    evidence_quality = 0
    events: list[dict[str, Any]] = []

    def event(action: dict[str, Any], accepted: bool, reason: str) -> None:
        events.append({
            "tick": action["tick"],
            "actor": action["actor"],
            "action_id": action["id"],
            "accepted": accepted,
            "reason": reason,
        })

    for action in payload["actions"]:
        action_id = action["id"]
        params = action.get("parameters", {})
        ref = params.get("evidence_ref")
        if ref not in evidence:
            event(action, False, "evidence_not_found")
            continue
        if action_id == "acknowledge_incident":
            acknowledged = True
            status, progress, evidence_quality = "acknowledged", 25, 25
            event(action, True, "acknowledged")
        elif action_id == "propose_mitigation":
            observed = evidence[ref]
            if not acknowledged:
                event(action, False, "acknowledgement_required")
            elif params.get("affected_component") != observed.get("affected_component"):
                event(action, False, "affected_component_mismatch")
            else:
                mitigated = True
                status, health, progress, evidence_quality = "mitigated", 70, 55, 50
                event(action, True, "mitigation_accepted")
        elif action_id == "run_health_check":
            if not mitigated:
                event(action, False, "mitigation_required")
            elif params.get("status") != "pass":
                event(action, False, "health_check_failed")
            else:
                health_check_passed = True
                health, progress, evidence_quality = 100, 85, 75
                event(action, True, "health_check_passed")
        elif action_id == "declare_resolved":
            if not health_check_passed:
                event(action, False, "passing_health_check_required")
            else:
                status, progress, evidence_quality = "resolved", 100, 100
                event(action, True, "incident_resolved")
        else:
            event(action, False, "unknown_action")

    return {
        "scenario_id": payload["scenario_id"],
        "events": events,
        "settlement": {
            "incident_status": status,
            "service_health": health,
            "response_progress": progress,
            "evidence_quality": evidence_quality,
        },
    }


def main() -> int:
    fixture = Path(sys.argv[1]) if len(sys.argv) > 1 else Path(__file__).resolve().parent.parent / "tests" / "fixture.json"
    result = settle(json.loads(fixture.resolve().read_text(encoding="utf-8")))
    print(json.dumps(result, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
