"""Benchmark 测评效度诊断：静态机会、动态覆盖、角色效应与共线性。"""
from __future__ import annotations

import math
from collections import defaultdict
from typing import Any, Dict, Iterable, List, Optional, Tuple

from dataclasses import dataclass

from app.benchmark.models import BenchmarkRunResult, ValidityPolicy


@dataclass(frozen=True)
class _Axis:
    name: str


# 十个标准能力轴（与 scenario_boot._STANDARD_DIMENSIONS 一致）。
# 效度诊断只用轴名检查"场景动作/工具是否覆盖各能力轴"（读 action 的
# suitable_needs = judge 物理十维），与已删除的行为打分引擎（A）无关。
DIMENSIONS = [
    _Axis(name) for name in (
        "understanding", "memory", "reasoning", "planning", "judgment",
        "selection", "execution", "risk_control", "tool_use", "recovery",
    )
]


def build_static_opportunity_matrix(scenario: Any) -> Dict[str, Any]:
    """只消费场景声明，不识别任何场景专有 action/object ID。"""
    actions = list(scenario.actions_cfg or [])
    roles = list(scenario.agent_roles or [])
    tools = list(scenario.tools_cfg or [])
    dimensions: Dict[str, Any] = {}
    for dimension in DIMENSIONS:
        action_ids = [
            str(action.get("id"))
            for action in actions
            if dimension.name in (action.get("suitable_needs", []) or [])
        ]
        role_tool_access = {}
        if dimension.name == "tool_use":
            for role in roles:
                profile = getattr(role, "capability_profile", {}) or {}
                role_tool_access[role.agent_slot_id] = len(
                    profile.get("available_tools", []) or []
                )
        support = {
            "declared_actions": len(action_ids),
            "action_ids": action_ids,
            "declared_tools": len(tools) if dimension.name == "tool_use" else 0,
            "role_tool_access": role_tool_access,
        }
        has_direct = bool(action_ids)
        has_tool_path = (
            dimension.name == "tool_use"
            and bool(tools)
            and all(value > 0 for value in role_tool_access.values())
        )
        observable = has_direct or has_tool_path
        dimensions[dimension.name] = {
            **support,
            "observable": observable,
            "status": (
                "supported"
                if (len(action_ids) >= 2 or has_tool_path)
                else "weak" if observable else "unobservable"
            ),
        }

    observable_count = sum(
        1 for item in dimensions.values() if item["observable"]
    )
    return {
        "dimensions": dimensions,
        "observable_dimensions": observable_count,
        "total_dimensions": len(DIMENSIONS),
        "coverage_rate": round(observable_count / len(DIMENSIONS), 6),
        "unobservable_dimensions": [
            name for name, item in dimensions.items()
            if not item["observable"]
        ],
        "weak_dimensions": [
            name for name, item in dimensions.items()
            if item["status"] == "weak"
        ],
    }


def build_runtime_validity(
    runs: List[BenchmarkRunResult],
    static_matrix: Dict[str, Any],
    policy: ValidityPolicy,
) -> Dict[str, Any]:
    names = [dimension.name for dimension in DIMENSIONS]
    total_results = sum(len(run.competitors) for run in runs)
    observed = {}
    for name in names:
        sample_counts = [
            item.capability_samples.get(name, 0)
            for run in runs for item in run.competitors
        ]
        observed_runs = sum(value > 0 for value in sample_counts)
        observed[name] = {
            "observed_results": observed_runs,
            "total_results": total_results,
            "result_coverage_rate": round(
                observed_runs / total_results, 6
            ) if total_results else 0.0,
            "total_samples": sum(sample_counts),
            "mean_samples_per_result": round(
                sum(sample_counts) / total_results, 6
            ) if total_results else 0.0,
        }

    observed_dimensions = sum(
        1 for item in observed.values() if item["observed_results"] > 0
    )
    dynamic_coverage = (
        observed_dimensions / len(names) if names else 0.0
    )
    role_effects = _role_effects(runs, names)
    correlations = _dimension_correlations(runs, names)
    opportunity_funnel = _opportunity_funnel(runs, names)

    errors = []
    warnings = []
    if static_matrix["coverage_rate"] < policy.min_static_coverage:
        errors.append(
            "静态能力机会覆盖率 "
            f"{static_matrix['coverage_rate']:.3f} "
            f"< {policy.min_static_coverage:.3f}"
        )
    if dynamic_coverage < policy.min_dynamic_coverage:
        errors.append(
            f"动态能力覆盖率 {dynamic_coverage:.3f} "
            f"< {policy.min_dynamic_coverage:.3f}"
        )
    biased = [
        name for name, item in role_effects.items()
        if item.get("max_mean_gap", 0.0) > policy.max_role_mean_gap
    ]
    if biased:
        errors.append(f"角色均值差超阈值: {biased}")
    high_corr = [
        item for item in correlations
        if abs(item["correlation"]) >= policy.max_abs_correlation
    ]
    if high_corr:
        warnings.append(
            "能力维度可能共线: "
            + ", ".join(
                f"{item['left']}~{item['right']}={item['correlation']:.3f}"
                for item in high_corr
            )
        )
    never_observed = [
        name for name, item in observed.items()
        if item["observed_results"] == 0
    ]
    if never_observed:
        warnings.append(f"本次实验无动态样本维度: {never_observed}")
    for name in never_observed:
        funnel = opportunity_funnel.get(name, {})
        if funnel.get("offered", 0) == 0:
            funnel["diagnosis"] = "scenario_did_not_offer"
        elif funnel.get("selected", 0) == 0:
            funnel["diagnosis"] = "model_did_not_select"
        elif funnel.get("attempted", 0) == 0:
            funnel["diagnosis"] = "selection_rejected_before_execution"
        else:
            funnel["diagnosis"] = "detector_produced_no_signal"
    for name, dynamic in observed.items():
        funnel = opportunity_funnel.get(name, {})
        if (
            dynamic["total_samples"] > 0
            and funnel.get("signal_produced", 0) == 0
        ):
            funnel["diagnosis"] = "detector_signal_outside_declared_opportunity"
            warnings.append(
                f"{name} 的能力信号出现在预定最低机会窗口之外"
            )

    return {
        "passed": not errors,
        "policy": policy.model_dump(),
        "static_opportunities": static_matrix,
        "dynamic_observability": {
            "dimensions": observed,
            "observed_dimensions": observed_dimensions,
            "total_dimensions": len(names),
            "coverage_rate": round(dynamic_coverage, 6),
        },
        "role_effects": role_effects,
        "dimension_correlations": correlations,
        "opportunity_funnel": opportunity_funnel,
        "errors": errors,
        "warnings": warnings,
    }


def _opportunity_funnel(
    runs: List[BenchmarkRunResult], names: Iterable[str]
) -> Dict[str, Any]:
    result = {}
    for name in names:
        records = [
            item.opportunity_funnel.get(name, {})
            for run in runs for item in run.competitors
            if name in item.opportunity_funnel
        ]
        offered = sum(int(item.get("offered", 0)) for item in records)
        selected = sum(int(item.get("selected", 0)) for item in records)
        attempted = sum(int(item.get("attempted", 0)) for item in records)
        signaled = sum(
            int(item.get("signal_produced", 0)) for item in records
        )
        result[name] = {
            "offered": offered,
            "selected": selected,
            "attempted": attempted,
            "signal_produced": signaled,
            "selection_rate": round(selected / offered, 6)
            if offered else 0.0,
            "attempt_rate": round(attempted / selected, 6)
            if selected else 0.0,
            "signal_conversion_rate": round(signaled / attempted, 6)
            if attempted else 0.0,
        }
    return result


def _role_effects(
    runs: List[BenchmarkRunResult], names: Iterable[str]
) -> Dict[str, Any]:
    values: Dict[str, Dict[str, List[float]]] = defaultdict(
        lambda: defaultdict(list)
    )
    for run in runs:
        for item in run.competitors:
            for name in names:
                if item.capability_samples.get(name, 0) > 0:
                    values[name][item.role_id].append(
                        item.capabilities[name]
                    )
    result = {}
    for name, by_role in values.items():
        means = {
            role: round(sum(items) / len(items), 6)
            for role, items in by_role.items() if items
        }
        result[name] = {
            "role_means": means,
            "role_samples": {
                role: len(items) for role, items in by_role.items()
            },
            "max_mean_gap": (
                round(max(means.values()) - min(means.values()), 6)
                if len(means) >= 2 else 0.0
            ),
        }
    return result


def _dimension_correlations(
    runs: List[BenchmarkRunResult], names: List[str]
) -> List[Dict[str, Any]]:
    rows = [
        item for run in runs for item in run.competitors
    ]
    result = []
    for left_index, left in enumerate(names):
        for right in names[left_index + 1:]:
            pairs = [
                (item.capabilities[left], item.capabilities[right])
                for item in rows
                if item.capability_samples.get(left, 0) > 0
                and item.capability_samples.get(right, 0) > 0
            ]
            correlation = _pearson(pairs)
            if correlation is not None:
                result.append({
                    "left": left,
                    "right": right,
                    "correlation": round(correlation, 6),
                    "samples": len(pairs),
                })
    return sorted(
        result, key=lambda item: abs(item["correlation"]), reverse=True
    )


def _pearson(pairs: List[Tuple[float, float]]) -> Optional[float]:
    if len(pairs) < 3:
        return None
    xs = [float(pair[0]) for pair in pairs]
    ys = [float(pair[1]) for pair in pairs]
    # 同质或近同质参考组没有相关性辨识力；浮点尾差不应制造 ±1。
    if len({round(value, 6) for value in xs}) < 3:
        return None
    if len({round(value, 6) for value in ys}) < 3:
        return None
    x_mean = sum(xs) / len(xs)
    y_mean = sum(ys) / len(ys)
    numerator = sum(
        (x - x_mean) * (y - y_mean) for x, y in zip(xs, ys)
    )
    x_var = sum((x - x_mean) ** 2 for x in xs)
    y_var = sum((y - y_mean) ** 2 for y in ys)
    if x_var / len(xs) < 1e-6 or y_var / len(ys) < 1e-6:
        return None
    denominator = math.sqrt(x_var * y_var)
    return numerator / denominator if denominator > 0 else None
