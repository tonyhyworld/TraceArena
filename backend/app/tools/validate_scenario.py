"""编译并校验一个场景包。

用法：
    python -m app.tools.validate_scenario scenarios/<scenario_name>
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

from app.engine.scenario_boot.compiler import ScenarioCompiler
from app.engine.scenario_boot.loader import ScenarioBootKernel
from app.engine.scenario_boot.validator import ScenarioValidator


def validate(path: str) -> dict:
    scenario = ScenarioBootKernel.load(path)
    structural = ScenarioValidator.validate(path, scenario)
    if not structural.passed:
        return {
            "passed": False,
            "stage": "structural_validation",
            **structural.summary(),
        }
    compiled = ScenarioCompiler.compile(scenario)
    return {
        "passed": True,
        "scenario": {
            "name": scenario.manifest.name,
            "version": scenario.manifest.version,
            "api_version": scenario.manifest.scenario_api_version,
        },
        "indexes": {
            "roles": len(compiled.role_index),
            "actions": len(compiled.action_index),
            "objects": len(compiled.object_index),
            "tools": len(compiled.tool_index),
            "locations": len(compiled.location_index),
            "resources": len(compiled.resource_index),
            "metrics": len(compiled.metric_index),
        },
        "consumption": compiled.consumption.model_dump(),
        "measurement": compiled.measurement.model_dump(),
    }


def main() -> int:
    if len(sys.argv) != 2:
        print("usage: python -m app.tools.validate_scenario <scenario_dir>")
        return 2
    path = str(Path(sys.argv[1]).resolve())
    try:
        result = validate(path)
    except Exception as exc:
        result = {
            "passed": False,
            "stage": "compile",
            "error": str(exc),
        }
    print(json.dumps(result, ensure_ascii=False, indent=2))
    return 0 if result.get("passed") else 1


if __name__ == "__main__":
    raise SystemExit(main())
