"""商业级多模型基准实验 Runner。"""
from __future__ import annotations

import json
import uuid
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, List

from app.benchmark.models import (
    BenchmarkReport,
    BenchmarkRunResult,
    BenchmarkSpec,
    CompetitorRunResult,
    CompetitorSummary,
    RunAssignment,
)
from app.benchmark.statistics import summarize
from app.benchmark.validity import (
    build_runtime_validity,
    build_static_opportunity_matrix,
)
from app.config import AgentSlotConfig, FrameworkConfig
from app.engine.main import EngineOS
from app.engine.scenario_boot.loader import ScenarioBootKernel


class BenchmarkRunner:
    def __init__(self, spec: BenchmarkSpec):
        self.spec = spec

    async def run(self) -> BenchmarkReport:
        initial = ScenarioBootKernel.load(self.spec.scenario_path)
        role_ids = [role.agent_slot_id for role in initial.agent_roles]
        if len(self.spec.competitors) != len(role_ids):
            raise ValueError(
                "competitors 数量必须等于场景角色数量，"
                f"当前 {len(self.spec.competitors)} != {len(role_ids)}"
            )

        rotations = len(role_ids) if self.spec.rotate_roles else 1
        benchmark_id = f"bench_{uuid.uuid4().hex[:10]}"
        output_dir = Path(self.spec.output_dir).resolve() / benchmark_id
        output_dir.mkdir(parents=True, exist_ok=True)

        run_results: List[BenchmarkRunResult] = []
        run_index = 0
        for repeat_index in range(self.spec.repeats):
            for rotation_index in range(rotations):
                seed = self.spec.base_seed + run_index
                assignments = self._assign(
                    role_ids, rotation_index, seed
                )
                result = await self._run_once(
                    run_index=run_index,
                    repeat_index=repeat_index,
                    rotation_index=rotation_index,
                    seed=seed,
                    assignments=assignments,
                    output_dir=output_dir,
                )
                run_results.append(result)
                run_index += 1

        validity = build_runtime_validity(
            run_results,
            build_static_opportunity_matrix(initial),
            self.spec.validity_policy,
        )
        report = BenchmarkReport(
            benchmark_id=benchmark_id,
            passed=(
                validity["passed"]
                or not self.spec.validity_policy.fail_on_error
            ),
            scenario_name=initial.manifest.name,
            scenario_version=initial.manifest.version,
            base_seed=self.spec.base_seed,
            repeats=self.spec.repeats,
            rotations=rotations,
            total_runs=len(run_results),
            runs=run_results,
            competitors=self._summarize(run_results),
            fairness=self._fairness(run_results, role_ids),
            capability_measurement={
                "model": "bayesian_weighted_binary_v1",
                "neutral_prior_score": 50.0,
                "standardization": (
                    "scenario_baseline_z_score"
                    if self.spec.capability_baseline
                    else "not_calibrated"
                ),
                "baseline": {
                    name: value.model_dump()
                    for name, value in self.spec.capability_baseline.items()
                },
            },
            validity=validity,
            output_dir=str(output_dir),
        )
        (output_dir / "benchmark_report.json").write_text(
            report.model_dump_json(indent=2),
            encoding="utf-8",
        )
        return report

    def _assign(
        self, role_ids: List[str], rotation_index: int, seed: int
    ) -> List[RunAssignment]:
        competitors = self.spec.competitors
        return [
            RunAssignment(
                role_id=role_id,
                competitor_id=competitors[
                    (index + rotation_index) % len(competitors)
                ].id,
                provider=competitors[
                    (index + rotation_index) % len(competitors)
                ].provider,
                model=competitors[
                    (index + rotation_index) % len(competitors)
                ].model,
            )
            for index, role_id in enumerate(role_ids)
        ]

    async def _run_once(
        self,
        *,
        run_index: int,
        repeat_index: int,
        rotation_index: int,
        seed: int,
        assignments: List[RunAssignment],
        output_dir: Path,
    ) -> BenchmarkRunResult:
        scenario = ScenarioBootKernel.load(self.spec.scenario_path)
        competitor_map = {item.id: item for item in self.spec.competitors}
        slots = []
        for assignment in assignments:
            competitor = competitor_map[assignment.competitor_id]
            extra = dict(competitor.extra)
            extra.setdefault("seed", seed)
            slots.append(AgentSlotConfig(
                id=assignment.role_id,
                name=assignment.competitor_id,
                provider=assignment.provider,
                model=assignment.model,
                extra=extra,
                api_key_override=competitor.api_key,
            ))

        cfg = FrameworkConfig(
            scenario_path=self.spec.scenario_path,
            agents=slots,
            agent_timeout_sec=self.spec.agent_timeout_sec,
            runtime_mode="benchmark",
            random_seed=seed,
            headless=True,
            provider_health_check=False,
            director={"provider": "mock", "model": "mock-v1", "enabled": False},
            tts={"enabled": False},
            log_dir=str(output_dir / "runs"),
        )
        engine = EngineOS(cfg, scenario)
        actual_bindings = engine.get_provider_bindings()
        for assignment in assignments:
            actual = actual_bindings[assignment.role_id]
            if (
                assignment.provider != "mock"
                and actual["provider"] == "mock"
            ):
                raise RuntimeError(
                    f"Benchmark 禁止 Provider 静默降级: "
                    f"{assignment.competitor_id} 请求 {assignment.provider}/"
                    f"{assignment.model}，实际得到 mock"
                )
        await engine.initialize()
        tick_limit = self._tick_limit(scenario.audit_cfg)
        for _ in range(tick_limit):
            if engine.state.is_game_over:
                break
            await engine.step()
        if not engine.state.is_game_over:
            engine.force_victory_settlement("benchmark_forced_end")

        snapshot = engine.get_benchmark_snapshot()
        role_to_competitor = {
            item.role_id: item.competitor_id for item in assignments
        }
        winner_role = snapshot["winner_id"]
        winner_competitor = role_to_competitor.get(winner_role)
        standings = {
            item["agent_id"]: item
            for item in snapshot["victory_standings"]
        }
        accepted = Counter(
            item.get("actor_id") for item in snapshot["action_ledger"]
        )
        logs_by_role: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
        for log in snapshot["logs"]:
            logs_by_role[log["agent_id"]].append(log)
        opportunities_by_role: Dict[str, List[Dict[str, Any]]] = defaultdict(
            list
        )
        for record in snapshot.get("measurement_opportunity_ledger", []):
            opportunities_by_role[record["agent_id"]].append(record)

        competitor_results = []
        for assignment in assignments:
            role_id = assignment.role_id
            logs = logs_by_role[role_id]
            submitted = sum(1 for log in logs if log.get("action_pack"))
            parsed = sum(
                1 for log in logs
                if (log.get("action_pack") or {}).get("parsed_ok")
            )
            errors = sum(1 for log in logs if log.get("error"))
            # 十维行为能力打分（A）已移除；能力评价改由 B（考题）与结局承担。
            capabilities: Dict[str, Any] = {}
            capability_confidence: Dict[str, float] = {}
            capability_samples: Dict[str, int] = {}
            standardized_capabilities: Dict[str, float] = {}
            opportunity_funnel: Dict[str, Dict[str, float]] = {}
            general_capabilities: Dict[str, Any] = {}
            general_status: Dict[str, str] = {}
            general_confidence: Dict[str, float] = {}
            by_capability: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
            for record in opportunities_by_role[role_id]:
                by_capability[record["capability"]].append(record)
            for name, records in by_capability.items():
                offered = sum(bool(item.get("offered")) for item in records)
                selected = sum(bool(item.get("selected")) for item in records)
                attempted = sum(bool(item.get("attempted")) for item in records)
                signaled = sum(
                    bool(item.get("signal_produced")) for item in records
                )
                opportunity_funnel[name] = {
                    "offered": offered,
                    "selected": selected,
                    "attempted": attempted,
                    "signal_produced": signaled,
                }
            profile = (
                snapshot.get("general_capability_profiles", {})
                .get("profiles", {})
                .get(role_id, {})
                .get("dimensions", {})
            )
            for name, item in profile.items():
                general_capabilities[name] = item.get("score")
                general_status[name] = item.get("status", "unmeasured")
                general_confidence[name] = float(item.get("confidence", 0.0))
            competitor_results.append(CompetitorRunResult(
                competitor_id=assignment.competitor_id,
                role_id=role_id,
                victory_value=float(
                    (standings.get(role_id) or {}).get("value", 0.0)
                ),
                victory_rank=int(
                    (standings.get(role_id) or {}).get("rank", 0)
                ),
                won=role_id == winner_role,
                submitted_actions=submitted,
                parsed_actions=parsed,
                accepted_actions=int(accepted.get(role_id, 0)),
                provider_errors=errors,
                total_tokens=sum(int(log.get("tokens_used", 0)) for log in logs),
                mean_latency_ms=(
                    sum(float(log.get("duration_ms", 0)) for log in logs)
                    / len(logs) if logs else 0.0
                ),
                capabilities=capabilities,
                capability_confidence=capability_confidence,
                capability_samples=capability_samples,
                standardized_capabilities=standardized_capabilities,
                opportunity_funnel=opportunity_funnel,
                general_capabilities=general_capabilities,
                general_capability_status=general_status,
                general_capability_confidence=general_confidence,
                assessment_case_count=sum(
                    1 for item in snapshot.get("assessment_cases", [])
                    if item.get("agent_id") == role_id
                ),
            ))

        return BenchmarkRunResult(
            run_index=run_index,
            repeat_index=repeat_index,
            rotation_index=rotation_index,
            seed=seed,
            assignments=assignments,
            winner_role_id=winner_role,
            winner_competitor_id=winner_competitor,
            run_id=snapshot["run_id"],
            run_dir=snapshot["run_dir"],
            competitors=competitor_results,
        )

    @staticmethod
    def _tick_limit(audit_cfg: Dict[str, Any]) -> int:
        limit = int(audit_cfg.get("tick_limit", 0) or 0)
        for condition in audit_cfg.get("termination", {}).get("any", []):
            if condition.get("type") == "tick_limit":
                limit = int(condition.get("value", limit) or limit)
        return limit or 1

    def _summarize(
        self, runs: List[BenchmarkRunResult]
    ) -> List[CompetitorSummary]:
        grouped: Dict[str, List[CompetitorRunResult]] = defaultdict(list)
        for run in runs:
            for result in run.competitors:
                grouped[result.competitor_id].append(result)

        summaries = []
        for competitor in self.spec.competitors:
            items = grouped[competitor.id]
            capability_names = sorted({
                key for item in items for key in item.capabilities
            })
            general_names = sorted({
                key for item in items for key, value in item.general_capabilities.items()
                if value is not None
            })
            summaries.append(CompetitorSummary(
                competitor_id=competitor.id,
                runs=len(items),
                wins=sum(1 for item in items if item.won),
                win_rate=round(
                    sum(1 for item in items if item.won) / len(items), 6
                ) if items else 0.0,
                victory_value=summarize(item.victory_value for item in items),
                victory_rank=summarize(item.victory_rank for item in items),
                parsed_action_rate=summarize(
                    item.parsed_actions / item.submitted_actions
                    if item.submitted_actions else 0.0
                    for item in items
                ),
                accepted_action_rate=summarize(
                    item.accepted_actions / item.submitted_actions
                    if item.submitted_actions else 0.0
                    for item in items
                ),
                provider_error_rate=summarize(
                    item.provider_errors / max(item.submitted_actions, 1)
                    for item in items
                ),
                latency_ms=summarize(item.mean_latency_ms for item in items),
                tokens=summarize(item.total_tokens for item in items),
                capabilities={
                    name: summarize(
                        item.capabilities.get(name, 0.0) for item in items
                    )
                    for name in capability_names
                },
                capability_confidence={
                    name: summarize(
                        item.capability_confidence.get(name, 0.0)
                        for item in items
                    )
                    for name in capability_names
                },
                standardized_capabilities={
                    name: summarize(
                        item.standardized_capabilities[name]
                        for item in items
                        if name in item.standardized_capabilities
                    )
                    for name in capability_names
                    if any(
                        name in item.standardized_capabilities
                        for item in items
                    )
                },
                role_exposure=dict(Counter(item.role_id for item in items)),
                general_capabilities={
                    name: summarize(
                        float(item.general_capabilities[name])
                        for item in items
                        if item.general_capabilities.get(name) is not None
                    )
                    for name in general_names
                },
            ))
        return summaries

    @staticmethod
    def _fairness(
        runs: List[BenchmarkRunResult], role_ids: List[str]
    ) -> Dict[str, Any]:
        exposure: Dict[str, Counter] = defaultdict(Counter)
        for run in runs:
            for assignment in run.assignments:
                exposure[assignment.competitor_id][assignment.role_id] += 1
        balanced = all(
            len(set(counter.get(role, 0) for role in role_ids)) <= 1
            for counter in exposure.values()
        )
        return {
            "role_rotation_balanced": balanced,
            "role_exposure": {
                competitor: dict(counter)
                for competitor, counter in exposure.items()
            },
            "unique_seeds": len({run.seed for run in runs}) == len(runs),
        }
