#!/usr/bin/env python3
"""P0 behavior baseline report for an AI World run.

Reads diagnostics and ledgers from a run directory and prints a compact JSON
summary that can be compared before/after OS 2.0 P0 changes.
"""
from __future__ import annotations

import argparse
import json
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any, Dict, Iterable, Iterator, Optional


INTERACTION_ACTIONS = {
    "form_alliance",
    "accept_proposal",
    "reject_proposal",
    "private_lobby",
    "plant_evidence",
    "frame_rival",
    "steal_intelligence",
    "counter_attack",
}


def iter_jsonl(path: Path) -> Iterator[Dict[str, Any]]:
    if not path.is_file():
        return
    with path.open(encoding="utf-8") as f:
        for line in f:
            line = line.strip()
            if not line:
                continue
            try:
                obj = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(obj, dict):
                yield obj


def latest_run(root: Path) -> Path:
    candidates = [
        p for p in root.glob("**/run_*")
        if p.is_dir() and (p / "diagnostics.jsonl").exists()
    ]
    if not candidates:
        raise SystemExit(f"No run_* directory with diagnostics found under {root}")
    return max(candidates, key=lambda p: p.stat().st_mtime)


def classify_action(action: Dict[str, Any]) -> str:
    aid = str(action.get("action_id") or "")
    category = str(action.get("category") or "")
    if category == "chapter" or aid == "address_chapter":
        return "chapter"
    if aid in INTERACTION_ACTIONS or category in {"interaction", "social", "dark_strategy", "counterplay"}:
        return "interaction"
    return "strategy"


def pct(num: float, den: float) -> float:
    return round((num / den * 100.0), 2) if den else 0.0


def load_json(path: Path) -> Any:
    if not path.is_file():
        return None
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def build_report(run_dir: Path) -> Dict[str, Any]:
    diagnostics = run_dir / "diagnostics.jsonl"
    ledgers = run_dir / "ledgers"
    reports = run_dir / "reports"

    actions = Counter()
    action_ids = Counter()
    by_agent = defaultdict(Counter)
    parsed_total = 0
    parsed_ok = 0
    parse_errors = 0
    fallback_actions = 0
    tool_declared = 0
    turns = 0
    ticks = set()

    for row in iter_jsonl(diagnostics):
        if row.get("event_type") != "agent_turn_completed":
            continue
        turns += 1
        ticks.add(row.get("tick"))
        aid = str(row.get("agent_id") or "")
        action = row.get("action_pack") or {}
        if not isinstance(action, dict):
            continue
        bucket = classify_action(action)
        actions[bucket] += 1
        by_agent[aid][bucket] += 1
        action_id = str(action.get("action_id") or "")
        if action_id:
            action_ids[action_id] += 1
        parsed_total += 1
        if action.get("parsed_ok", True):
            parsed_ok += 1
        errs = action.get("parse_errors") or []
        if isinstance(errs, list) and errs:
            parse_errors += 1
        if action.get("is_system_fallback"):
            fallback_actions += 1
        if action.get("tool_request") or action.get("attached_tool_id") or action.get("code"):
            tool_declared += 1

    tool_runs = list(iter_jsonl(ledgers / "tool_runs.jsonl"))
    causal = list(iter_jsonl(ledgers / "causal_results.jsonl"))
    perception = list(iter_jsonl(ledgers / "perception_packets.jsonl"))
    assessment_cases = list(iter_jsonl(ledgers / "assessment_cases.jsonl"))

    chapter_exposures = 0
    for row in perception:
        opts = row.get("available_actions") or []
        if any(isinstance(a, dict) and a.get("id") == "address_chapter" for a in opts):
            chapter_exposures += 1

    causal_outcomes = Counter(str(r.get("outcome") or "unknown") for r in causal)
    victory = load_json(reports / "victory_attribution.json") or []

    return {
        "run_dir": str(run_dir),
        "ticks_seen": len([t for t in ticks if t is not None]),
        "agent_turns": turns,
        "action_mix": {
            "chapter": actions["chapter"],
            "strategy": actions["strategy"],
            "interaction": actions["interaction"],
            "chapter_pct": pct(actions["chapter"], turns),
            "strategy_pct": pct(actions["strategy"], turns),
            "interaction_pct": pct(actions["interaction"], turns),
        },
        "top_action_ids": action_ids.most_common(12),
        "by_agent": {agent: dict(counter) for agent, counter in sorted(by_agent.items())},
        "parser": {
            "total": parsed_total,
            "parsed_ok": parsed_ok,
            "parsed_ok_pct": pct(parsed_ok, parsed_total),
            "turns_with_parse_errors": parse_errors,
            "system_fallback_actions": fallback_actions,
        },
        "tools": {
            "declared_or_code_actions": tool_declared,
            "tool_runs": len(tool_runs),
            "tool_runs_ok": sum(1 for r in tool_runs if r.get("ok")),
            "tool_runs_failed": sum(1 for r in tool_runs if not r.get("ok")),
            "declaration_to_run_pct": pct(len(tool_runs), tool_declared),
        },
        "causal_pipeline": {
            "total": len(causal),
            "outcomes": dict(causal_outcomes),
        },
        "capability_assessment": {
            "cases": len(assessment_cases),
            "chapter_action_exposures": chapter_exposures,
            "chapter_exposure_pct_of_perceptions": pct(chapter_exposures, len(perception)),
        },
        "victory_source_mix": [
            {
                "agent_id": item.get("agent_id"),
                "name": item.get("name"),
                "rank": item.get("rank"),
                "score": item.get("score"),
                "source_mix": item.get("source_mix", {}),
            }
            for item in victory
            if isinstance(item, dict)
        ],
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("run_dir", nargs="?", help="Path to a run_* directory")
    parser.add_argument("--runs-root", default="backend/runs")
    args = parser.parse_args()

    run_dir = Path(args.run_dir) if args.run_dir else latest_run(Path(args.runs_root))
    report = build_report(run_dir)
    print(json.dumps(report, ensure_ascii=False, indent=2))


if __name__ == "__main__":
    main()
