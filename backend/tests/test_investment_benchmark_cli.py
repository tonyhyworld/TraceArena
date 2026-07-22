import json
import os
import subprocess
import sys
from pathlib import Path

import pytest


ROOT = Path(__file__).parents[2]
SCRIPT = ROOT / "backend/scripts/investment_benchmark.py"


def _run(tmp_path):
    output = tmp_path / "benchmark"
    env = dict(os.environ)
    env["PYTHONPATH"] = str(ROOT / "backend")
    result = subprocess.run(
        [sys.executable, str(SCRIPT), "--output", str(output)],
        cwd=str(ROOT), env=env, capture_output=True, text=True, timeout=30,
    )
    assert result.returncode == 0, result.stderr
    return output, result


def test_cli_builds_honest_deterministic_contract_baseline(tmp_path):
    output, result = _run(tmp_path)
    report = json.loads((output / "benchmark_report.json").read_text())
    assert report["benchmark_id"] == "tracearena.investment_agent.v1"
    assert report["benchmark_status"] == "contract_baseline"
    assert report["official_model_leaderboard"] is False
    assert all(item["model_claim"] is False for item in report["entries"])
    assert report["execution_boundary"] == {
        "network": "disabled", "brokerage": "disabled", "financial_advice": False,
    }
    assert report["entries"][0]["entrant_id"] == "investor_b"
    assert "not a model leaderboard" in result.stdout
    assert "scripted controls" in (output / "LEADERBOARD.md").read_text()


def test_report_is_stable_across_runs(tmp_path):
    first, _ = _run(tmp_path / "first")
    second, _ = _run(tmp_path / "second")
    left = json.loads((first / "benchmark_report.json").read_text())
    right = json.loads((second / "benchmark_report.json").read_text())
    assert left == right


def test_checked_in_reference_matches_generated_report(tmp_path):
    output, _ = _run(tmp_path)
    checked = ROOT / "benchmarks/investment-agent-v1"
    assert json.loads((checked / "benchmark_report.json").read_text()) == json.loads(
        (output / "benchmark_report.json").read_text()
    )
    assert (checked / "LEADERBOARD.md").read_text() == (
        output / "LEADERBOARD.md"
    ).read_text()


def test_tampered_replay_is_rejected(tmp_path):
    output, _ = _run(tmp_path)
    sys.path.insert(0, str(ROOT / "backend/scripts"))
    import investment_benchmark

    replay_path = output / "replay/replay_deterministic.json"
    replay = json.loads(replay_path.read_text())
    replay["ticks"][-1]["settlements"][0]["values"]["portfolio_value"] = 999999
    replay_path.write_text(json.dumps(replay))
    with pytest.raises(ValueError, match="integrity digest mismatch"):
        investment_benchmark.build_reference_report(output / "replay")


def test_tampered_fixture_manifest_is_rejected(tmp_path):
    output, _ = _run(tmp_path)
    sys.path.insert(0, str(ROOT / "backend/scripts"))
    import investment_benchmark

    manifest_path = output / "replay/run_manifest.json"
    manifest = json.loads(manifest_path.read_text())
    manifest["fixture_sha256"] = "0" * 64
    manifest_path.write_text(json.dumps(manifest))
    with pytest.raises(ValueError, match="fixture integrity digest mismatch"):
        investment_benchmark.build_reference_report(
            output / "replay", ROOT / "examples/market_replay/fixture.json"
        )
