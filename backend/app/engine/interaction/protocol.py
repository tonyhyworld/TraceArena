"""Generic interaction protocol contract.

The protocol turns scene-declared action metadata into neutral interaction
roles.  Scene packs can define proposal/response actions without EngineOS
knowing domain-specific verbs such as alliances or counter-attacks.
"""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict


@dataclass(frozen=True)
class InteractionRole:
    role: str

    @property
    def is_proposal(self) -> bool:
        return self.role == "proposal"

    @property
    def is_response(self) -> bool:
        return self.role == "response"


class InteractionProtocol:
    def classify(self, action: Any, rule: Dict[str, Any]) -> InteractionRole:
        declared = str(rule.get("interaction_role", "") or "")
        if declared in {"proposal", "response"}:
            return InteractionRole(declared)
        return InteractionRole("")
