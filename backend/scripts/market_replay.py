"""Run the deterministic no-key Market Replay through the formal EngineOS path."""
from __future__ import annotations

import argparse
import asyncio
import hashlib
import json
import sys
from pathlib import Path
from typing import Any, Dict, List

ROOT = Path(__file__).resolve().parents[2]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))

from app.config import AgentSlotConfig, FrameworkConfig  # noqa: E402
from app.engine.main import EngineOS  # noqa: E402
from app.engine.scenario_boot.loader import ScenarioBootKernel  # noqa: E402

TEXT = {
    "en-US": {
        "title": "TraceArena Market Replay",
        "action": "Replay decision",
        "monologue": "I execute only recorded and verified actions.",
        "disclaimer": "This is a deterministic synthetic replay for evaluation and education; it is not financial advice and does not imply future returns.",
    },
    "zh-CN": {
        "title": "TraceArena 市场回放",
        "action": "回放决策",
        "monologue": "我只执行已记录并核验过的动作。",
        "disclaimer": "这是用于评测和教学的确定性合成回放，不构成投资建议，也不代表未来收益。",
    },
}


def _load_fixture(path: Path) -> Dict[str, Any]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict) or not data.get("fixture_id"):
        raise ValueError("fixture must contain fixture_id")
    if str(data.get("provenance_status")) != "internal_synthetic_pending_approval":
        raise ValueError("only the reviewed internal synthetic fixture is supported")
    return data


def _observation(item: Dict[str, Any], agent_id: str, asset: str) -> Dict[str, Any]:
    value: Dict[str, Any] = {
        "asset_id": asset,
        "symbol": asset,
        "research_categories": list(item.get("categories") or []),
        "source_uri": f"fixture://market-replay/{item['run_id']}",
    }
    if item.get("price") is not None:
        value["price"] = float(item["price"])
    return {
        "run_id": str(item["run_id"]),
        "ok": True,
        "source": "verified_external",
        "owner_id": agent_id,
        "outputs": [value],
    }


def _actions(agent_id: str, spec: Dict[str, Any], asset: str, locale: str) -> List[Dict[str, Any]]:
    observations = [
        _observation(item, agent_id, asset)
        for item in (spec.get("observations") or [])
    ]
    refs = [str(item["run_id"]) for item in observations]
    result: List[Dict[str, Any]] = []
    for item in spec.get("actions") or []:
        action_id = str(item.get("action_id") or "wait_and_review")
        parameters: Dict[str, Any] = {}
        if action_id == "buy_asset":
            parameters = {
                "asset_id": asset,
                "quantity": float(item.get("quantity", 1)),
                "price_evidence_ref": str(item.get("price_evidence_ref") or refs[0]),
            }
        if not result:
            parameters["harness_observations"] = observations
        result.append({
            "action_id": action_id,
            "action_name": TEXT[locale]["action"],
            "target_object_id": "portfolio_book",
            "plan": str(item.get("reason") or "执行固定回放动作"),
            "public_reasoning_summary": str(item.get("reason") or "执行固定回放动作"),
            "character_monologue": TEXT[locale]["monologue"],
            "evidence_refs": refs,
            "parameters": parameters,
        })
    return result


async def _run(args: argparse.Namespace) -> int:
    locale = str(args.locale)
    fixture_path = Path(args.fixture).resolve()
    fixture = _load_fixture(fixture_path)
    scenario_path = Path(args.scenario).resolve()
    scenario = ScenarioBootKernel.load(str(scenario_path))
    ticks = int(fixture.get("ticks") or 2)
    scenario.audit_cfg["tick_limit"] = ticks
    termination = scenario.audit_cfg.get("termination") or {}
    for item in termination.get("any", []) if isinstance(termination, dict) else []:
        if isinstance(item, dict) and item.get("type") == "tick_limit":
            item["value"] = ticks
    scenario.settlement_cfg["research_requirements"]["enabled"] = True

    slots = []
    for agent_id, spec in (fixture.get("agents") or {}).items():
        slots.append(AgentSlotConfig(
            id=str(agent_id),
            name=f"Replay {agent_id}",
            provider="replay",
            model="replay-v1",
            extra={"actions": _actions(str(agent_id), spec, str(fixture["asset"]), locale)},
        ))
    if len(slots) != 2:
        raise ValueError("fixture must define exactly two replay agents")

    cfg = FrameworkConfig(
        scenario_path=str(scenario_path),
        runtime_mode="replay",
        tick_interval_sec=1.0,
        agent_timeout_sec=10.0,
        agents=slots,
        director={"enabled": False, "provider": "mock", "model": "mock-v1"},
        judge={"enabled": False},
        sandbox={"enabled": False},
        mcp={"enabled": False},
        tts={"enabled": False},
        agent_loop={"enabled": False},
        headless=True,
        provider_health_check=False,
        log_dir=str(Path(args.output).resolve().parent / "engine_runs"),
    )
    engine = EngineOS(cfg, scenario)
    await engine.initialize()
    for _ in range(ticks):
        await engine.step()
    terminal_settled = bool(getattr(engine, "_last_os2_settlements", None))
    if engine.state is None or (not engine.state.is_game_over and not terminal_settled):
        current_tick = engine.state.tick if engine.state is not None else None
        raise RuntimeError(
            f"replay did not reach terminal settlement (tick={current_tick}, "
            f"audit={engine.scenario_definition.audit_cfg})"
        )
    if engine.state is not None and not engine.state.is_game_over:
        # A bounded replay may finish its final settlement record on the last
        # step without the background loop's terminal audit pass. Finalize
        # through the public EngineOS settlement boundary so the replay file
        # is still produced by the authoritative scenario provider.
        engine.force_victory_settlement("replay_tick_limit")
    await engine.pause()

    run_dir = Path(cfg.log_dir) / engine.run_id
    replay_path = run_dir / "replay_deterministic.json"
    if not replay_path.is_file():
        raise FileNotFoundError(f"missing replay artifact: {replay_path}")
    output_dir = Path(args.output).resolve()
    output_dir.mkdir(parents=True, exist_ok=True)
    replay = json.loads(replay_path.read_text(encoding="utf-8"))
    canonical = json.dumps(replay, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
    digest = hashlib.sha256(canonical.encode("utf-8")).hexdigest()
    (output_dir / "replay_deterministic.json").write_text(
        json.dumps(replay, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    (output_dir / "run_manifest.json").write_text(json.dumps({
        "fixture_id": fixture["fixture_id"],
        "fixture_sha256": hashlib.sha256(fixture_path.read_bytes()).hexdigest(),
        "provider": "replay",
        "brokerage": "disabled",
        "network": "disabled",
        "locale": locale,
        "run_id": engine.run_id,
        "canonical_replay_sha256": digest,
    }, ensure_ascii=False, indent=2), encoding="utf-8")
    (output_dir / "summary.md").write_text(
        f"# {TEXT[locale]['title']}\n\n"
        f"- fixture: `{fixture['fixture_id']}`\n"
        f"- provider: `replay`\n"
        "- brokerage: disabled\n"
        "- network: disabled\n"
        f"- canonical replay SHA-256: `{digest}`\n\n"
        f"{TEXT[locale]['disclaimer']}\n",
        encoding="utf-8",
    )
    print(TEXT[locale]["title"])
    print(f"fixture: {fixture['fixture_id']}")
    print("provider: replay")
    print("brokerage: disabled")
    print("network: disabled")
    print(f"ticks: {ticks}")
    print(f"verification: passed ({digest})")
    print(f"output: {output_dir}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--fixture", default=str(ROOT / "examples/market_replay/fixture.json"))
    parser.add_argument("--scenario", default=str(BACKEND / "scenarios/capital_market"))
    parser.add_argument("--output", default=str(ROOT / "runs/market_replay_demo"))
    # Kept for compatibility with the public replay server and CLI docs. The
    # authoritative replay data remains deterministic regardless of locale.
    parser.add_argument("--locale", choices=("en-US", "zh-CN"), default="en-US")
    return asyncio.run(_run(parser.parse_args()))


if __name__ == "__main__":
    raise SystemExit(main())
