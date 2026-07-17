"""Benchmark Runner 数据契约。"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field, field_validator


class CompetitorSpec(BaseModel):
    id: str
    provider: str
    model: str
    extra: Dict[str, Any] = Field(default_factory=dict)
    api_key: Optional[str] = None


class CapabilityBaselineStat(BaseModel):
    """场景维度基线；由历史合格样本生成，不属于 OS 或场景规则。"""
    mean: float = 50.0
    stddev: float = 10.0
    samples: int = 0


class ValidityPolicy(BaseModel):
    min_static_coverage: float = 0.8
    min_dynamic_coverage: float = 0.7
    max_role_mean_gap: float = 15.0
    max_abs_correlation: float = 0.95
    fail_on_error: bool = False


class BenchmarkSpec(BaseModel):
    scenario_path: str
    competitors: List[CompetitorSpec]
    repeats: int = 3
    base_seed: int = 20260619
    rotate_roles: bool = True
    agent_timeout_sec: float = 30.0
    output_dir: str = "./benchmark_runs"
    capability_baseline: Dict[str, CapabilityBaselineStat] = Field(
        default_factory=dict
    )
    validity_policy: ValidityPolicy = Field(default_factory=ValidityPolicy)

    @field_validator("repeats")
    @classmethod
    def positive_repeats(cls, value: int) -> int:
        if value < 1:
            raise ValueError("repeats 必须 >= 1")
        return value


class RunAssignment(BaseModel):
    role_id: str
    competitor_id: str
    provider: str
    model: str


class CompetitorRunResult(BaseModel):
    competitor_id: str
    role_id: str
    victory_value: float = 0.0
    victory_rank: int = 0
    won: bool = False
    submitted_actions: int = 0
    parsed_actions: int = 0
    accepted_actions: int = 0
    provider_errors: int = 0
    total_tokens: int = 0
    mean_latency_ms: float = 0.0
    capabilities: Dict[str, float] = Field(default_factory=dict)
    capability_confidence: Dict[str, float] = Field(default_factory=dict)
    capability_samples: Dict[str, int] = Field(default_factory=dict)
    standardized_capabilities: Dict[str, float] = Field(default_factory=dict)
    opportunity_funnel: Dict[str, Dict[str, float]] = Field(
        default_factory=dict
    )
    general_capabilities: Dict[str, Optional[float]] = Field(default_factory=dict)
    general_capability_status: Dict[str, str] = Field(default_factory=dict)
    general_capability_confidence: Dict[str, float] = Field(default_factory=dict)
    assessment_case_count: int = 0


class BenchmarkRunResult(BaseModel):
    run_index: int
    repeat_index: int
    rotation_index: int
    seed: int
    assignments: List[RunAssignment]
    winner_role_id: Optional[str] = None
    winner_competitor_id: Optional[str] = None
    run_id: str = ""
    run_dir: Optional[str] = None
    competitors: List[CompetitorRunResult] = Field(default_factory=list)


class MetricSummary(BaseModel):
    mean: float = 0.0
    stddev: float = 0.0
    ci95_low: float = 0.0
    ci95_high: float = 0.0
    samples: int = 0


class CompetitorSummary(BaseModel):
    competitor_id: str
    runs: int
    wins: int
    win_rate: float
    victory_value: MetricSummary
    victory_rank: MetricSummary
    parsed_action_rate: MetricSummary
    accepted_action_rate: MetricSummary
    provider_error_rate: MetricSummary
    latency_ms: MetricSummary
    tokens: MetricSummary
    capabilities: Dict[str, MetricSummary] = Field(default_factory=dict)
    capability_confidence: Dict[str, MetricSummary] = Field(default_factory=dict)
    standardized_capabilities: Dict[str, MetricSummary] = Field(
        default_factory=dict
    )
    role_exposure: Dict[str, int] = Field(default_factory=dict)
    general_capabilities: Dict[str, MetricSummary] = Field(default_factory=dict)


class BenchmarkReport(BaseModel):
    benchmark_id: str
    passed: bool = True
    scenario_name: str
    scenario_version: str
    base_seed: int
    repeats: int
    rotations: int
    total_runs: int
    runs: List[BenchmarkRunResult]
    competitors: List[CompetitorSummary]
    fairness: Dict[str, Any] = Field(default_factory=dict)
    capability_measurement: Dict[str, Any] = Field(default_factory=dict)
    validity: Dict[str, Any] = Field(default_factory=dict)
    output_dir: str = ""
