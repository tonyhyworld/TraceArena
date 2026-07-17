"""能力基线校准与跨场景模型画像。"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List

from app.benchmark.models import BenchmarkReport, CapabilityBaselineStat


def build_capability_baseline(
    reports: Iterable[BenchmarkReport],
) -> Dict[str, CapabilityBaselineStat]:
    """从历史参考实验的逐局结果建立场景能力基线。"""
    values: Dict[str, List[float]] = defaultdict(list)
    for report in reports:
        for run in report.runs:
            for competitor in run.competitors:
                for name, value in competitor.capabilities.items():
                    if competitor.capability_samples.get(name, 0) > 0:
                        values[name].append(float(value))

    baseline = {}
    for name, items in values.items():
        mean = sum(items) / len(items)
        variance = (
            sum((value - mean) ** 2 for value in items) / (len(items) - 1)
            if len(items) > 1 else 0.0
        )
        baseline[name] = CapabilityBaselineStat(
            mean=round(mean, 6),
            # 同质参考组没有区分力；保留 0，让 Runner 明确跳过 z-score。
            stddev=round(math.sqrt(variance), 6),
            samples=len(items),
        )
    return baseline


def aggregate_capability_profiles(
    reports: Iterable[BenchmarkReport],
) -> Dict[str, Any]:
    """按真实置信度加权聚合多个场景，避免无样本维度稀释画像。"""
    buckets: Dict[str, Dict[str, List[Dict[str, float]]]] = defaultdict(
        lambda: defaultdict(list)
    )
    scenario_ids = set()
    for report in reports:
        scenario_id = f"{report.scenario_name}@{report.scenario_version}"
        scenario_ids.add(scenario_id)
        for run in report.runs:
            for competitor in run.competitors:
                for name, score in competitor.capabilities.items():
                    samples = competitor.capability_samples.get(name, 0)
                    confidence = competitor.capability_confidence.get(name, 0.0)
                    if samples <= 0 or confidence <= 0:
                        continue
                    buckets[competitor.competitor_id][name].append({
                        "score": float(score),
                        "confidence": float(confidence),
                        "z_score": competitor.standardized_capabilities.get(name),
                        "samples": float(samples),
                    })

    profiles: Dict[str, Any] = {}
    for competitor_id, dimensions in buckets.items():
        profile_dimensions = {}
        for name, observations in dimensions.items():
            weight = sum(item["confidence"] for item in observations)
            calibrated = [
                item for item in observations if item["z_score"] is not None
            ]
            calibrated_weight = sum(
                item["confidence"] for item in calibrated
            )
            profile_dimensions[name] = {
                "score": round(
                    sum(
                        item["score"] * item["confidence"]
                        for item in observations
                    ) / weight,
                    6,
                ),
                "confidence": round(
                    1.0 - math.prod(
                        1.0 - min(0.999999, item["confidence"])
                        for item in observations
                    ),
                    6,
                ),
                "samples": int(sum(item["samples"] for item in observations)),
                "standardized_score": (
                    round(
                        sum(
                            item["z_score"] * item["confidence"]
                            for item in calibrated
                        ) / calibrated_weight,
                        6,
                    )
                    if calibrated_weight else None
                ),
            }
        profiles[competitor_id] = {
            "dimensions": profile_dimensions,
            "observed_dimensions": len(profile_dimensions),
        }

    return {
        "measurement_model": "confidence_weighted_cross_scenario_v1",
        "scenarios": sorted(scenario_ids),
        "scenario_count": len(scenario_ids),
        "competitors": profiles,
    }
