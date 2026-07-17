"""无第三方依赖的基础统计。"""
from __future__ import annotations

import math
from typing import Iterable

from app.benchmark.models import MetricSummary


def summarize(values: Iterable[float]) -> MetricSummary:
    data = [float(value) for value in values]
    count = len(data)
    if not data:
        return MetricSummary()
    mean = sum(data) / count
    if count > 1:
        variance = sum((value - mean) ** 2 for value in data) / (count - 1)
        stddev = math.sqrt(variance)
        margin = 1.96 * stddev / math.sqrt(count)
    else:
        stddev = 0.0
        margin = 0.0
    return MetricSummary(
        mean=round(mean, 6),
        stddev=round(stddev, 6),
        ci95_low=round(mean - margin, 6),
        ci95_high=round(mean + margin, 6),
        samples=count,
    )
