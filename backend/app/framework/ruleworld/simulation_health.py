"""仿真运行健康度报告。

判断的是规则世界是否真的产生了可观看、可归因的变化，不评价模型优劣。
阈值全部由场景包 causal_physics.health_gate 声明。
"""
from __future__ import annotations

from collections import Counter
from typing import Any, Dict, Iterable, Optional


def build_simulation_health_report(
    records: Iterable[Dict[str, Any]],
    config: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    rows = list(records)
    cfg = config or {}
    total = len(rows)
    outcomes = Counter(str(item.get("outcome", "error")) for item in rows)
    object_actions = [
        item for item in rows
        if item.get("target_kind") in ("object", "evidence")
    ]
    object_effects = [
        item for item in object_actions
        if item.get("outcome") in ("success", "backlash")
        and int(item.get("delta_count", 0) or 0) > 0
    ]

    def ratio(count: int, denominator: int = total) -> float:
        return round(count / denominator, 4) if denominator else 0.0

    metrics = {
        "total_actions": total,
        "success_rate": ratio(outcomes["success"]),
        "invalid_rate": ratio(outcomes["invalid"]),
        "no_effect_rate": ratio(outcomes["no_effect"]),
        "backlash_rate": ratio(outcomes["backlash"]),
        "object_effect_rate": ratio(
            len(object_effects), len(object_actions)
        ),
        "world_delta_count": sum(
            int(item.get("delta_count", 0) or 0) for item in rows
        ),
        "metric_update_count": sum(
            int(item.get("metric_count", 0) or 0) for item in rows
        ),
    }
    thresholds = {
        "min_success_rate": float(cfg.get("min_success_rate", 0.35)),
        "max_invalid_rate": float(cfg.get("max_invalid_rate", 0.15)),
        "max_no_effect_rate": float(cfg.get("max_no_effect_rate", 0.50)),
        "min_object_effect_rate": float(
            cfg.get("min_object_effect_rate", 0.35)
        ),
        "min_world_delta_count": int(cfg.get("min_world_delta_count", 1)),
    }
    checks = {
        "success_rate": (
            metrics["success_rate"] >= thresholds["min_success_rate"]
        ),
        "invalid_rate": (
            metrics["invalid_rate"] <= thresholds["max_invalid_rate"]
        ),
        "no_effect_rate": (
            metrics["no_effect_rate"] <= thresholds["max_no_effect_rate"]
        ),
        "object_effect_rate": (
            metrics["object_effect_rate"]
            >= thresholds["min_object_effect_rate"]
        ),
        "world_delta_count": (
            metrics["world_delta_count"]
            >= thresholds["min_world_delta_count"]
        ),
    }
    return {
        "passed": bool(total) and all(checks.values()),
        "metrics": metrics,
        "thresholds": thresholds,
        "checks": checks,
        "outcomes": dict(outcomes),
    }
