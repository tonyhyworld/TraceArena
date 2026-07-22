"""Build the public Investment Agent Benchmark v1 reference report.

The bundled reference entrants are deterministic scripts.  They prove the
benchmark contract and must never be presented as model-comparison results.
"""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, Iterable, List

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

import market_replay  # noqa: E402


BENCHMARK_ID = "tracearena.investment_agent.v1"
REPORT_SCHEMA_VERSION = "1.0"
PRIMARY_METRIC = "risk_adjusted_excess_return"
REQUIRED_METRICS = (
    "portfolio_value",
    "return_pct",
    "excess_return_pct",
    "drawdown_pct",
    PRIMARY_METRIC,
    "turnover_pct",
    "total_transaction_cost",
)
REFERENCE_LABELS = {
    "investor_a": "evidence-first scripted baseline",
    "investor_b": "cash-control scripted baseline",
}


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _terminal_records(replay: Dict[str, Any]) -> List[Dict[str, Any]]:
    ticks = replay.get("ticks")
    if not isinstance(ticks, list) or not ticks:
        raise ValueError("replay must contain at least one tick")
    records = ticks[-1].get("settlements") or []
    selected = [
        item for item in records
        if item.get("outcome") == "portfolio_marked_to_market"
        and item.get("subject_ids")
    ]
    if len(selected) != 2:
        raise ValueError("terminal tick must contain exactly two portfolio settlements")
    return selected


def _rank(entries: Iterable[Dict[str, Any]]) -> List[Dict[str, Any]]:
    ordered = sorted(
        entries,
        key=lambda item: (
            -float(item["metrics"][PRIMARY_METRIC]),
            float(item["metrics"]["total_transaction_cost"]),
            item["entrant_id"],
        ),
    )
    previous_score = None
    previous_cost = None
    previous_rank = 0
    for index, item in enumerate(ordered, start=1):
        score = float(item["metrics"][PRIMARY_METRIC])
        cost = float(item["metrics"]["total_transaction_cost"])
        if score != previous_score or cost != previous_cost:
            previous_rank = index
        item["rank"] = previous_rank
        previous_score, previous_cost = score, cost
    return ordered


def build_reference_report(
    replay_dir: Path,
    fixture_path: Path | None = None,
) -> Dict[str, Any]:
    replay_path = replay_dir / "replay_deterministic.json"
    manifest_path = replay_dir / "run_manifest.json"
    if not replay_path.is_file() or not manifest_path.is_file():
        raise FileNotFoundError("replay directory must contain replay_deterministic.json and run_manifest.json")

    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    integrity_digest, semantic_digest = market_replay._replay_digests(replay)
    if manifest.get("canonical_replay_sha256") != integrity_digest:
        raise ValueError("replay integrity digest mismatch")
    if manifest.get("deterministic_replay_sha256") != semantic_digest:
        raise ValueError("replay semantic digest mismatch")
    if manifest.get("provider") != "replay":
        raise ValueError("reference report only accepts the replay provider")
    if manifest.get("network") != "disabled" or manifest.get("brokerage") != "disabled":
        raise ValueError("reference report requires network and brokerage to be disabled")

    fixture = None
    if fixture_path is not None:
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        if manifest.get("fixture_id") != fixture.get("fixture_id"):
            raise ValueError("fixture identity mismatch")
        if manifest.get("fixture_sha256") != _sha256(fixture_path):
            raise ValueError("fixture integrity digest mismatch")

    entries = []
    terminal_records = _terminal_records(replay)
    scenario_ids = {str(item.get("scenario_id") or "") for item in terminal_records}
    if len(scenario_ids) != 1 or not next(iter(scenario_ids)):
        raise ValueError("terminal settlements must agree on scenario_id")
    for record in terminal_records:
        authority = record.get("authority") or {}
        if not authority.get("reproducible") or not authority.get("deterministic"):
            raise ValueError("all reference settlements must be reproducible and deterministic")
        values = record.get("values") or {}
        missing = [name for name in REQUIRED_METRICS if name not in values]
        if missing:
            raise ValueError(f"settlement is missing required metrics: {missing}")
        entrant_id = str(record["subject_ids"][0])
        details = record.get("details") or {}
        entries.append({
            "entrant_id": entrant_id,
            "label": REFERENCE_LABELS.get(entrant_id, entrant_id),
            "entrant_type": "deterministic_script",
            "model_claim": False,
            "provider": "replay",
            "model": "replay-v1",
            "metrics": {name: float(values[name]) for name in REQUIRED_METRICS},
            "accepted_order_count": len(details.get("orders") or []),
            "authority": {
                "mode": authority.get("mode"),
                "verifier_id": authority.get("verifier_id"),
                "rule_version": authority.get("rule_version"),
            },
        })

    report = {
        "schema_version": REPORT_SCHEMA_VERSION,
        "benchmark_id": BENCHMARK_ID,
        "benchmark_status": "contract_baseline",
        "official_model_leaderboard": False,
        "claim_scope": (
            "Deterministic protocol proof only; these entries are scripted controls, "
            "not model-comparison results."
        ),
        "scenario_id": next(iter(scenario_ids)),
        "scenario_version": replay.get("scenario_version"),
        "fixture_id": manifest.get("fixture_id"),
        "fixture_sha256": manifest.get("fixture_sha256"),
        "fixture_provenance_status": (
            fixture.get("provenance_status") if fixture else "not_revalidated"
        ),
        "fixture_license": fixture.get("license") if fixture else "not_revalidated",
        "deterministic_replay_sha256": semantic_digest,
        "execution_boundary": {
            "network": "disabled",
            "brokerage": "disabled",
            "financial_advice": False,
        },
        "ranking": {
            "primary_metric": PRIMARY_METRIC,
            "order": "descending",
            "tie_breaker": "total_transaction_cost ascending",
            "formula": "excess_return_pct - 0.5 * max_drawdown_pct",
        },
        "entries": _rank(entries),
    }
    canonical = json.dumps(report, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    report["report_sha256"] = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    return report


def render_leaderboard(report: Dict[str, Any]) -> str:
    rows = []
    for item in report["entries"]:
        metrics = item["metrics"]
        rows.append(
            f"| {item['rank']} | {item['label']} | {metrics[PRIMARY_METRIC]:.6f} | "
            f"{metrics['return_pct']:.6f}% | {metrics['drawdown_pct']:.6f}% | "
            f"{metrics['total_transaction_cost']:.6f} |"
        )
    return "\n".join([
        "# Investment Agent Benchmark v1 — Contract Baseline",
        "",
        "> This is a deterministic protocol proof, not a model leaderboard. Both entrants are scripted controls.",
        "",
        "| Rank | Entrant | Risk-adjusted excess return | Return | Max drawdown | Transaction cost |",
        "| ---: | --- | ---: | ---: | ---: | ---: |",
        *rows,
        "",
        f"- Fixture: `{report['fixture_id']}`",
        f"- Semantic replay SHA-256: `{report['deterministic_replay_sha256']}`",
        f"- Report SHA-256: `{report['report_sha256']}`",
        "- Network: disabled; brokerage: disabled; no financial advice.",
        "",
    ])


async def _run(args: argparse.Namespace) -> int:
    output_dir = Path(args.output).resolve()
    replay_dir = output_dir / "replay"
    replay_args = argparse.Namespace(
        fixture=args.fixture,
        scenario=args.scenario,
        output=str(replay_dir),
        locale="en-US",
    )
    await market_replay._run(replay_args)
    report = build_reference_report(replay_dir, Path(args.fixture).resolve())
    output_dir.mkdir(parents=True, exist_ok=True)
    (output_dir / "benchmark_report.json").write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )
    (output_dir / "LEADERBOARD.md").write_text(
        render_leaderboard(report), encoding="utf-8"
    )
    print(f"benchmark: {BENCHMARK_ID}")
    print("status: contract_baseline (not a model leaderboard)")
    print(f"verification: passed ({report['report_sha256']})")
    print(f"output: {output_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default=str(ROOT / "examples/market_replay/fixture.json"))
    parser.add_argument("--scenario", default=str(BACKEND / "scenarios/capital_market"))
    parser.add_argument("--output", default=str(ROOT / "runs/investment_agent_benchmark_v1"))
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
