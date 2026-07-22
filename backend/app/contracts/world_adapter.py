"""Versioned contracts for executable world adapters.

World adapters are orthogonal to settlement authority.  An adapter owns
environment execution and state transitions; the existing settlement modes
still decide which facts are authoritative for scoring and victory.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


WorldModelKind = Literal[
    "rule_based",
    "algorithmic",
    "learned",
    "simulator",
    "reality",
    "hybrid",
]
WorldModelTrustTier = Literal[
    "exploratory",
    "validated",
    "calibrated",
    "authoritative",
]


class WorldAdapterContract(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["1.0"] = "1.0"


class WorldAdapterCommand(WorldAdapterContract):
    command_id: str
    world_tick: int = Field(ge=0)
    actor_id: str
    action_type: str
    target_ids: List[str] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list)
    submitted_at: float = Field(default_factory=time.time)


class WorldAdapterActionReceipt(WorldAdapterContract):
    receipt_id: str
    command_id: str
    world_tick: int = Field(ge=0)
    actor_id: str
    action_type: str
    status: Literal[
        "accepted",
        "needs_approval",
        "rejected",
        "executed",
        "rolled_back",
        "failed",
    ]
    reasons: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)
    occurred_at: float = Field(default_factory=time.time)

    @model_validator(mode="after")
    def validate_failure_reason(self) -> "WorldAdapterActionReceipt":
        if self.status in {"rejected", "failed"} and not self.reasons:
            raise ValueError("rejected/failed adapter receipt requires reasons")
        return self


class WorldAdapterObservation(WorldAdapterContract):
    observation_id: str
    world_tick: int = Field(ge=0)
    actor_id: Optional[str] = None
    values: Dict[str, Any] = Field(default_factory=dict)
    legal_actions: List[Dict[str, Any]] = Field(default_factory=list)
    observed_at: float = Field(default_factory=time.time)


class WorldAdapterTerminal(WorldAdapterContract):
    done: bool = False
    reason: str = ""
    winner_ids: List[str] = Field(default_factory=list)
    details: Dict[str, Any] = Field(default_factory=dict)


class WorldModelAssurance(WorldAdapterContract):
    """Declared confidence boundary for facts produced by a world model.

    This is deliberately separate from settlement authority.  It tells trace
    consumers how the transition was produced and what validation supports it;
    it does not by itself decide a winner.
    """

    trust_tier: WorldModelTrustTier = "exploratory"
    confidence: Optional[float] = Field(default=None, ge=0.0, le=1.0)
    evidence_refs: List[str] = Field(default_factory=list)
    validation_refs: List[str] = Field(default_factory=list)
    assumptions: List[str] = Field(default_factory=list)
    limitations: List[str] = Field(default_factory=list)

    @model_validator(mode="after")
    def validate_elevated_trust(self) -> "WorldModelAssurance":
        if (
            self.trust_tier in {"calibrated", "authoritative"}
            and not self.validation_refs
        ):
            raise ValueError(
                "calibrated/authoritative world model requires validation_refs"
            )
        return self


class WorldAdapterProvenance(WorldAdapterContract):
    adapter_id: str
    adapter_version: str
    model_kind: WorldModelKind
    engine_name: str
    engine_version: str = ""
    config_hash: str
    seed: Optional[int] = None
    deterministic: bool = False
    source_uri: str
    assurance: WorldModelAssurance = Field(default_factory=WorldModelAssurance)
    metadata: Dict[str, Any] = Field(default_factory=dict)

    @model_validator(mode="after")
    def validate_model_specific_provenance(self) -> "WorldAdapterProvenance":
        if not self.source_uri.strip():
            raise ValueError("world model provenance requires source_uri")
        if self.model_kind == "learned":
            missing = [
                key for key in ("model_id", "model_version")
                if not str(self.metadata.get(key) or "").strip()
            ]
            if missing:
                raise ValueError(
                    "learned world model provenance missing: "
                    + ",".join(missing)
                )
            if not self.assurance.limitations:
                raise ValueError(
                    "learned world model must declare assurance limitations"
                )
        if self.model_kind == "hybrid":
            components = self.metadata.get("components")
            if not isinstance(components, list) or len(components) < 2:
                raise ValueError(
                    "hybrid world model provenance requires at least two components"
                )
        return self


class WorldAdapterTransition(WorldAdapterContract):
    transition_id: str
    world_tick: int = Field(ge=0)
    adapter_id: str
    state_before: Dict[str, Any] = Field(default_factory=dict)
    state_after: Dict[str, Any] = Field(default_factory=dict)
    deltas: Dict[str, Any] = Field(default_factory=dict)
    metrics: Dict[str, Any] = Field(default_factory=dict)
    receipts: List[WorldAdapterActionReceipt] = Field(default_factory=list)
    observations: List[WorldAdapterObservation] = Field(default_factory=list)
    terminal: WorldAdapterTerminal = Field(default_factory=WorldAdapterTerminal)
    provenance: WorldAdapterProvenance
    occurred_at: float = Field(default_factory=time.time)

    @model_validator(mode="after")
    def validate_receipt_tick(self) -> "WorldAdapterTransition":
        invalid = [
            item.receipt_id
            for item in self.receipts
            if item.world_tick != self.world_tick
        ]
        if invalid:
            raise ValueError(
                "adapter transition contains receipts from another tick: "
                + ",".join(invalid)
            )
        return self
