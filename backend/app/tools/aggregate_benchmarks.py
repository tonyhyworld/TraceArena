"""从多个 benchmark_report.json 生成基线或跨场景能力画像。"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.benchmark.capability_profile import (
    aggregate_capability_profiles,
    build_capability_baseline,
)
from app.benchmark.models import BenchmarkReport


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("reports", nargs="+")
    parser.add_argument(
        "--mode", choices=("profile", "baseline"), default="profile"
    )
    parser.add_argument("--output")
    args = parser.parse_args()

    reports = [
        BenchmarkReport.model_validate_json(Path(path).read_text("utf-8"))
        for path in args.reports
    ]
    if args.mode == "baseline":
        payload = {
            name: stat.model_dump()
            for name, stat in build_capability_baseline(reports).items()
        }
    else:
        payload = aggregate_capability_profiles(reports)
    text = json.dumps(payload, ensure_ascii=False, indent=2)
    if args.output:
        Path(args.output).write_text(text, encoding="utf-8")
    else:
        print(text)


if __name__ == "__main__":
    main()
