"""十大通用能力案例聚合器。"""
from __future__ import annotations

from collections import defaultdict
from math import exp
from typing import Any, Dict, Iterable, List

from app.framework.capability.general_capabilities import (
    GENERAL_CAPABILITIES,
    MeasurementStatus,
)


class GeneralCapabilityAggregator:
    """只聚合 AssessmentCase；绝不消费旧 behavioral_signal。"""

    def aggregate(self, cases: Iterable[Dict[str, Any]]) -> Dict[str, Any]:
        buckets: Dict[str, Dict[str, List[Dict[str, Any]]]] = defaultdict(
            lambda: defaultdict(list)
        )
        invalidated: Dict[str, Dict[str, int]] = defaultdict(
            lambda: defaultdict(int)
        )
        for raw in cases:
            agent_id = str(raw.get("agent_id", ""))
            capability = str(raw.get("capability", ""))
            if not agent_id or not capability:
                continue
            if raw.get("axis", "neutral") != "neutral":
                continue
            if raw.get("status") == MeasurementStatus.INVALIDATED.value:
                invalidated[agent_id][capability] += 1
                continue
            buckets[agent_id][capability].append(raw)

        profiles: Dict[str, Any] = {}
        agent_ids = sorted(set(buckets) | set(invalidated))
        for agent_id in agent_ids:
            dimensions = {}
            for cap in GENERAL_CAPABILITIES:
                items = buckets[agent_id].get(cap.cid, [])
                sample_count = len(items)
                effective_n = sum(max(0.0, float(i.get("weight", 1.0))) for i in items)
                weighted = sum(
                    max(0.0, min(1.0, float(i.get("score", 0.0))))
                    * max(0.0, float(i.get("weight", 1.0)))
                    for i in items
                )
                score = (100.0 * weighted / effective_n) if effective_n else None
                if effective_n <= 0:
                    status = MeasurementStatus.UNMEASURED
                elif sample_count < cap.min_trials:
                    status = MeasurementStatus.INSUFFICIENT
                else:
                    status = MeasurementStatus.MEASURED
                confidence = 1.0 - exp(-effective_n / max(1.0, cap.min_trials))
                dimensions[cap.cid] = {
                    "label": cap.label,
                    "status": status.value,
                    "score": round(score, 2) if score is not None else None,
                    "confidence": round(confidence, 4) if effective_n else 0.0,
                    "sample_count": sample_count,
                    "effective_sample_size": round(effective_n, 3),
                    "invalidated_count": invalidated[agent_id].get(cap.cid, 0),
                    "case_ids": [item.get("case_id") for item in items],
                }
            profiles[agent_id] = {"dimensions": dimensions}
        return {
            "measurement_model": "assessment_case_weighted_v1",
            "profiles": profiles,
        }


__all__ = ["GeneralCapabilityAggregator"]
