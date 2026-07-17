"""AI World OS 2.0 cross-service contracts.

These records form the authoritative boundary between the Agent Harness,
World Kernel, Evaluation Runtime, Director Runtime, Render Runtime, and the operator console. They are
introduced alongside the legacy interfaces so migration can happen by dual
writing before any existing runtime path is removed.
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, model_validator


Visibility = Literal["public", "private", "restricted", "operator_only"]
SettlementMode = Literal[
    "simulation",
    "external_reality",
    "deterministic_verifier",
    "hybrid",
]


class ContractModel(BaseModel):
    """Strict, versioned base for records that cross an OS boundary."""

    model_config = ConfigDict(extra="forbid")

    schema_version: Literal["2.0"] = "2.0"


class HarnessStep(ContractModel):
    """One observable step inside an agent's private harness loop."""

    step_id: str
    index: int = Field(ge=0)
    kind: Literal[
        "perceive",
        "plan",
        "discover_tool",
        "install_tool",
        "execute_tool",
        "write_code",
        "run_code",
        "observe",
        "reflect",
        "submit_action",
    ]
    status: Literal["pending", "running", "succeeded", "failed", "blocked"]
    input_refs: List[str] = Field(default_factory=list)
    output_refs: List[str] = Field(default_factory=list)
    artifact_refs: List[str] = Field(default_factory=list)
    public_summary: str = ""
    details: Dict[str, Any] = Field(default_factory=dict)
    duration_ms: int = Field(default=0, ge=0)
    started_at: float = Field(default_factory=time.time)
    finished_at: Optional[float] = None


class HarnessTrace(ContractModel):
    """Complete agent work trace for one world tick."""

    trace_id: str
    run_id: str
    scenario_id: str
    world_tick: int = Field(ge=0)
    agent_id: str
    sandbox_id: str
    perception_ref: str
    objective: str
    status: Literal[
        "running", "completed", "failed", "blocked", "budget_exhausted"
    ] = "running"
    steps: List[HarnessStep] = Field(default_factory=list)
    final_action_ref: Optional[str] = None
    memory_write_refs: List[str] = Field(default_factory=list)
    budget: Dict[str, float] = Field(default_factory=dict)
    usage: Dict[str, float] = Field(default_factory=dict)
    started_at: float = Field(default_factory=time.time)
    finished_at: Optional[float] = None

    @model_validator(mode="after")
    def validate_completed_trace(self) -> "HarnessTrace":
        if self.status == "completed" and not self.final_action_ref:
            raise ValueError("completed HarnessTrace requires final_action_ref")
        indexes = [step.index for step in self.steps]
        if indexes != sorted(indexes) or len(indexes) != len(set(indexes)):
            raise ValueError("HarnessStep indexes must be unique and ordered")
        return self


class WorldAction(ContractModel):
    """The only command an agent harness may submit to World Kernel."""

    action_id: str
    run_id: str
    scenario_id: str
    world_tick: int = Field(ge=0)
    actor_id: str
    action_type: str
    target_ids: List[str] = Field(default_factory=list)
    parameters: Dict[str, Any] = Field(default_factory=dict)
    evidence_refs: List[str] = Field(default_factory=list)
    harness_trace_ref: str
    visibility: Visibility = "public"
    status: Literal["proposed", "accepted", "rejected", "executed", "failed"] = (
        "proposed"
    )
    rejection_reasons: List[str] = Field(default_factory=list)
    submitted_at: float = Field(default_factory=time.time)

    @model_validator(mode="after")
    def validate_rejection(self) -> "WorldAction":
        if self.status == "rejected" and not self.rejection_reasons:
            raise ValueError("rejected WorldAction requires rejection_reasons")
        return self


class ExternalObservation(ContractModel):
    """Immutable, provenance-bound observation originating outside the world."""

    observation_id: str
    run_id: str
    scenario_id: str
    world_tick: int = Field(ge=0)
    provider_id: str
    observation_type: str
    subject_id: str
    raw_value: Any
    normalized_value: Any
    unit: str = ""
    source_uri: str
    source_hash: str
    request_parameters: Dict[str, Any] = Field(default_factory=dict)
    observed_at: float
    received_at: float = Field(default_factory=time.time)
    freshness_status: Literal["fresh", "stale", "unknown"] = "unknown"
    verification_status: Literal[
        "pending", "verified", "rejected"
    ] = "pending"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)

    @model_validator(mode="after")
    def validate_provenance(self) -> "ExternalObservation":
        if not self.provider_id or not self.source_uri or not self.source_hash:
            raise ValueError(
                "ExternalObservation requires provider, source URI and hash"
            )
        if self.verification_status == "verified" and (
            self.freshness_status != "fresh" or self.confidence <= 0
        ):
            raise ValueError(
                "verified ExternalObservation must be fresh and confident"
            )
        return self


class WorldEvent(ContractModel):
    """Immutable fact emitted by World Kernel after execution or progression."""

    event_id: str
    run_id: str
    scenario_id: str
    world_tick: int = Field(ge=0)
    event_type: str
    origin: Literal["action", "external", "timer", "system"]
    actor_id: Optional[str] = None
    target_ids: List[str] = Field(default_factory=list)
    source_action_ref: Optional[str] = None
    causal_event_refs: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    observation_refs: List[str] = Field(default_factory=list)
    state_before: Dict[str, Any] = Field(default_factory=dict)
    state_after: Dict[str, Any] = Field(default_factory=dict)
    deltas: Dict[str, Any] = Field(default_factory=dict)
    visibility: Visibility = "public"
    public_summary: str = ""
    occurred_at: float = Field(default_factory=time.time)

    @model_validator(mode="after")
    def validate_origin(self) -> "WorldEvent":
        if self.origin == "action" and not self.source_action_ref:
            raise ValueError("action-origin WorldEvent requires source_action_ref")
        return self


class AgentActivityFact(ContractModel):
    """Public, sanitized summary of one agent's decision process for a tick.

    This is not chain-of-thought. It is the explainable activity surface that
    Director Runtime and operator views can use without reading raw prompts or
    private reasoning.
    """

    activity_id: str
    run_id: str
    scenario_id: str
    world_tick: int = Field(ge=0)
    agent_id: str
    source_action_ref: Optional[str] = None
    harness_trace_ref: Optional[str] = None
    action_type: str = ""
    action_label: str = ""
    target_ids: List[str] = Field(default_factory=list)
    public_intent: str = ""
    public_reasoning_summary: str = ""
    character_monologue: str = ""
    tool_activity: List[Dict[str, Any]] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    observation_refs: List[str] = Field(default_factory=list)
    status: Literal["submitted", "executed", "rejected", "fallback"] = "submitted"
    visibility: Visibility = "public"
    created_at: float = Field(default_factory=time.time)

    @model_validator(mode="after")
    def validate_public_surface(self) -> "AgentActivityFact":
        if not self.agent_id:
            raise ValueError("AgentActivityFact requires agent_id")
        if self.visibility == "public" and not any(
            [
                self.public_intent,
                self.public_reasoning_summary,
                self.character_monologue,
                self.action_label,
                self.tool_activity,
            ]
        ):
            raise ValueError("public AgentActivityFact requires explainable content")
        return self


class SettlementAuthority(ContractModel):
    """Declares who is authoritative for a settlement and why."""

    mode: SettlementMode
    provider_id: str
    verifier_id: Optional[str] = None
    rule_version: str
    observation_refs: List[str] = Field(default_factory=list)
    component_modes: List[SettlementMode] = Field(default_factory=list)
    reproducible: bool = True
    deterministic: bool = True

    @model_validator(mode="after")
    def validate_mode(self) -> "SettlementAuthority":
        if not self.provider_id or not self.rule_version:
            raise ValueError(
                "SettlementAuthority requires provider and rule version"
            )
        if self.mode == "external_reality" and not self.observation_refs:
            raise ValueError(
                "external_reality authority requires observation_refs"
            )
        if self.mode == "deterministic_verifier" and (
            not self.verifier_id or not self.deterministic
        ):
            raise ValueError(
                "deterministic_verifier requires deterministic verifier_id"
            )
        if self.mode == "hybrid":
            components = set(self.component_modes)
            if len(components) < 2 or "hybrid" in components:
                raise ValueError(
                    "hybrid authority requires at least two non-hybrid modes"
                )
            if "external_reality" in components and not self.observation_refs:
                raise ValueError(
                    "hybrid authority with external reality requires observation_refs"
                )
        return self


class SettlementRecord(ContractModel):
    """Reproducible result from deterministic, scenario, or sidecar evaluation."""

    settlement_id: str
    run_id: str
    scenario_id: str
    world_tick: int = Field(ge=0)
    evaluator_id: str
    authority: SettlementAuthority
    kind: Literal["deterministic", "scenario_outcome", "capability_sidecar"]
    subject_ids: List[str]
    source_event_refs: List[str]
    rule_refs: List[str]
    outcome: str
    values: Dict[str, float] = Field(default_factory=dict)
    details: Dict[str, Any] = Field(default_factory=dict)
    explanation: str = ""
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    affects_world: bool = False
    affects_victory: bool = False
    created_at: float = Field(default_factory=time.time)

    @model_validator(mode="after")
    def validate_authority(self) -> "SettlementRecord":
        if not self.source_event_refs:
            raise ValueError("SettlementRecord requires source_event_refs")
        if not self.rule_refs:
            raise ValueError("SettlementRecord requires rule_refs")
        if self.authority.rule_version not in self.rule_refs:
            raise ValueError(
                "SettlementAuthority rule_version must appear in rule_refs"
            )
        if self.kind == "capability_sidecar" and (
            self.affects_world or self.affects_victory
        ):
            raise ValueError("capability sidecar cannot change world or victory")
        return self


class VictoryStanding(ContractModel):
    """Terminal rank derived only from scene-owned victory settlements."""

    standing_id: str
    run_id: str
    scenario_id: str
    world_tick: int = Field(ge=0)
    agent_id: str
    rank: int = Field(ge=1)
    value_key: str
    value: float
    label: str
    order: Literal["ascending", "descending"]
    settlement_ref: str
    provider_id: str
    authority: SettlementMode
    values: Dict[str, float] = Field(default_factory=dict)
    eliminated: bool = False


class RenderCommand(ContractModel):
    """Scenario-neutral command consumed by Render Runtime."""

    command_id: str
    command_type: Literal[
        "character",
        "object",
        "camera",
        "subtitle",
        "sound",
        "music",
        "effect",
        "ui",
        "wait",
    ]
    semantic_action: str
    source_event_refs: List[str] = Field(default_factory=list)
    source_settlement_refs: List[str] = Field(default_factory=list)
    source_activity_refs: List[str] = Field(default_factory=list)
    target_ids: List[str] = Field(default_factory=list)
    binding_id: Optional[str] = None
    parameters: Dict[str, Any] = Field(default_factory=dict)
    start_ms: int = Field(default=0, ge=0)
    duration_ms: int = Field(default=0, ge=0)
    skippable: bool = True

    @model_validator(mode="after")
    def validate_sources(self) -> "RenderCommand":
        if (
            not self.source_event_refs
            and not self.source_settlement_refs
            and not self.source_activity_refs
        ):
            raise ValueError(
                "RenderCommand requires event, settlement or activity source refs"
            )
        return self


class DirectorPlan(ContractModel):
    """Fact-bound presentation plan produced by Director Runtime."""

    plan_id: str
    run_id: str
    scenario_id: str
    world_tick: int = Field(ge=0)
    director_id: str
    selected_event_refs: List[str] = Field(default_factory=list)
    selected_settlement_refs: List[str] = Field(default_factory=list)
    selected_activity_refs: List[str] = Field(default_factory=list)
    narrative_summary: str
    commands: List[RenderCommand] = Field(default_factory=list)
    omitted_event_refs: List[str] = Field(default_factory=list)
    truth_guard_status: Literal["pending", "passed", "rejected"] = "pending"
    truth_guard_reasons: List[str] = Field(default_factory=list)
    created_at: float = Field(default_factory=time.time)

    @model_validator(mode="after")
    def validate_fact_binding(self) -> "DirectorPlan":
        if (
            not self.selected_event_refs
            and not self.selected_settlement_refs
            and not self.selected_activity_refs
        ):
            raise ValueError(
                "DirectorPlan requires selected event, settlement or activity refs"
            )
        selected_events = set(self.selected_event_refs)
        missing_events = {
            ref
            for command in self.commands
            for ref in command.source_event_refs
            if ref not in selected_events
        }
        selected_settlements = set(self.selected_settlement_refs)
        missing_settlements = {
            ref
            for command in self.commands
            for ref in command.source_settlement_refs
            if ref not in selected_settlements
        }
        if missing_events:
            raise ValueError(
                "RenderCommand references events not selected by DirectorPlan: "
                + ", ".join(sorted(missing_events))
            )
        if missing_settlements:
            raise ValueError(
                "RenderCommand references settlements not selected by DirectorPlan: "
                + ", ".join(sorted(missing_settlements))
            )
        selected_activities = set(self.selected_activity_refs)
        missing_activities = {
            ref
            for command in self.commands
            for ref in command.source_activity_refs
            if ref not in selected_activities
        }
        if missing_activities:
            raise ValueError(
                "RenderCommand references activities not selected by DirectorPlan: "
                + ", ".join(sorted(missing_activities))
            )
        if self.truth_guard_status == "rejected" and not self.truth_guard_reasons:
            raise ValueError("rejected DirectorPlan requires truth_guard_reasons")
        return self
