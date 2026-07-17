"""运行多模型角色轮换基准实验。

用法：
    python -m app.tools.run_benchmark benchmark.yaml
"""
from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path

import yaml

from app.benchmark.models import BenchmarkSpec
from app.benchmark.runner import BenchmarkRunner


async def _run(path: str) -> int:
    raw = yaml.safe_load(Path(path).read_text(encoding="utf-8")) or {}
    spec = BenchmarkSpec(**raw.get("benchmark", raw))
    report = await BenchmarkRunner(spec).run()
    print(json.dumps({
        "passed": report.passed,
        "benchmark_id": report.benchmark_id,
        "total_runs": report.total_runs,
        "output_dir": report.output_dir,
        "fairness": report.fairness,
        "validity": {
            "passed": report.validity.get("passed", True),
            "errors": report.validity.get("errors", []),
            "warnings": report.validity.get("warnings", []),
            "static_coverage": report.validity.get(
                "static_opportunities", {}
            ).get("coverage_rate"),
            "dynamic_coverage": report.validity.get(
                "dynamic_observability", {}
            ).get("coverage_rate"),
        },
        "competitors": [
            {
                "id": item.competitor_id,
                "wins": item.wins,
                "win_rate": item.win_rate,
                "victory_value": item.victory_value.model_dump(),
                "victory_rank": item.victory_rank.model_dump(),
            }
            for item in report.competitors
        ],
    }, ensure_ascii=False, indent=2))
    return 0 if report.passed else 1


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m app.tools.run_benchmark <benchmark.yaml>")
        return 2
    try:
        return asyncio.run(_run(sys.argv[1]))
    except Exception as exc:
        print(json.dumps(
            {"passed": False, "error": str(exc)},
            ensure_ascii=False,
            indent=2,
        ))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
