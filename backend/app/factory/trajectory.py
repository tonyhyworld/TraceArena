"""Normalize OS2 run archives into reusable agent trajectories."""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterator, List, Optional

from app.core.path_safety import path_beneath, safe_path_component


PURITY_DETERMINISTIC = "deterministic"
PURITY_SIMULATION = "simulation"
PURITY_JUDGED = PURITY_SIMULATION


@dataclass
class TrajectoryStep:
    sample_id: str
    tick: int
    agent_id: str
    system_prompt: str = ""
    user_brief: str = ""
    action_id: str = ""
    action_category: str = ""
    intent: str = ""
    plan: str = ""
    note_to_self: str = ""
    target_object_id: Optional[str] = None
    target_agent_id: Optional[str] = None
    raw_response: str = ""
    character_monologue: str = ""
    outcome: str = ""
    reward: float = 0.0
    reward_purity: str = PURITY_SIMULATION
    source_event_refs: List[str] = field(default_factory=list)
    settlement_refs: List[str] = field(default_factory=list)
    settlement_values: Dict[str, float] = field(default_factory=dict)
    authority_mode: str = ""
    authority_provider: str = ""
    parsed_ok: bool = True
    parse_errors: List[str] = field(default_factory=list)
    is_fallback: bool = False
    is_empty_action: bool = False
    llm_error: Optional[str] = None
    # Transitional export fields. New archives never synthesize judge scores.
    judge_ten_dim: Dict[str, float] = field(default_factory=dict)
    situational_fit: Optional[float] = None
    clarity: Optional[float] = None
    commitment: Optional[float] = None
    execution_quality: Optional[float] = None
    judge_risk_control: Optional[float] = None
    judge_rationale: str = ""
    judge_weaknesses: List[str] = field(default_factory=list)
    step_metric_deltas: List[Dict[str, Any]] = field(default_factory=list)
    delta_ids: List[str] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class Trajectory:
    run_id: str
    agent_id: str
    steps: List[TrajectoryStep] = field(default_factory=list)
    scenario_id: str = ""
    scenario_version: str = ""
    engine_version: str = ""
    random_seed: Optional[int] = None
    model: str = ""
    provider: str = ""
    final_value: Optional[float] = None
    victory_rank: Optional[int] = None
    victory_label: str = ""
    victory_value_key: str = ""
    eliminated: bool = False

    def to_dict(self) -> Dict[str, Any]:
        return {**asdict(self), "steps": [item.to_dict() for item in self.steps]}


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception:
        return None


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    if not path.exists():
        return []
    rows = []
    for line in path.read_text(encoding="utf-8").splitlines():
        try:
            value = json.loads(line)
        except Exception:
            continue
        if isinstance(value, dict):
            rows.append(value)
    return rows


def _index(rows: List[Dict[str, Any]], field_name: str) -> Dict[str, Dict[str, Any]]:
    return {
        str(row.get(field_name)): row
        for row in rows if row.get(field_name)
    }


def _settlement_reward(
    records: List[Dict[str, Any]], previous_pnl: float
) -> tuple[float, float]:
    if not records:
        return 0.0, previous_pnl
    record = records[-1]
    values = dict(record.get("values") or {})
    outcome = str(record.get("outcome") or "")
    if outcome == "order_rejected":
        return -1.0, previous_pnl
    if "training_reward" in values:
        return float(values["training_reward"]), previous_pnl
    if "pnl" in values:
        pnl = float(values.get("pnl") or 0.0)
        return pnl - previous_pnl, pnl
    return (
        float(values.get("state_change_count", 0.0) or 0.0)
        + float(values.get("metric_change_count", 0.0) or 0.0),
        previous_pnl,
    )


def load_trajectory(
    run_dir: Path | str,
    agent_id: str,
    *,
    meta: Optional[Dict[str, Any]] = None,
    victory_standings: Optional[List[Dict[str, Any]]] = None,
    **_ignored: Any,
) -> Trajectory:
    root = Path(run_dir)
    agent_id = safe_path_component(agent_id, label="agent_id")
    meta = meta or _read_json(root / "meta.json") or {}
    model_info = (meta.get("agent_models") or {}).get(agent_id, {}) or {}
    trajectory = Trajectory(
        run_id=root.name,
        agent_id=agent_id,
        scenario_id=str(meta.get("scenario_id") or ""),
        scenario_version=str(meta.get("scenario_version") or ""),
        engine_version=str(meta.get("engine_version") or ""),
        random_seed=meta.get("random_seed"),
        model=str(model_info.get("model") or ""),
        provider=str(model_info.get("provider") or ""),
    )
    standings = victory_standings if victory_standings is not None else (
        _read_json(root / "reports" / "victory_standings.json") or []
    )
    for item in standings if isinstance(standings, list) else []:
        if str(item.get("agent_id") or "") != agent_id:
            continue
        trajectory.final_value = float(item.get("value", 0.0) or 0.0)
        trajectory.victory_rank = int(item.get("rank", 0) or 0) or None
        trajectory.victory_label = str(item.get("label") or "")
        trajectory.victory_value_key = str(item.get("value_key") or "")
        trajectory.eliminated = bool(item.get("eliminated", False))

    actions = [
        item for item in _read_jsonl(root / "ledgers" / "world_actions.jsonl")
        if str(item.get("actor_id") or "") == agent_id
    ]
    events_by_action: Dict[str, List[Dict[str, Any]]] = {}
    for event in _read_jsonl(root / "ledgers" / "world_events.jsonl"):
        ref = str(event.get("source_action_ref") or "")
        if ref:
            events_by_action.setdefault(ref, []).append(event)
    settlements_by_event: Dict[str, List[Dict[str, Any]]] = {}
    for record in _read_jsonl(root / "ledgers" / "settlements.jsonl"):
        for ref in record.get("source_event_refs") or []:
            settlements_by_event.setdefault(str(ref), []).append(record)
    logs = _read_jsonl(path_beneath(root, "agents", agent_id, "harness_io.jsonl"))
    logs_by_tick = {int(item.get("tick", -1)): item for item in logs}
    actions_by_tick = {
        int(item.get("world_tick", 0) or 0): item for item in actions
    }
    previous_pnl = 0.0
    for tick in sorted(set(actions_by_tick) | set(logs_by_tick)):
        action = actions_by_tick.get(tick, {})
        log = logs_by_tick.get(tick, {})
        pack = dict(log.get("action_pack") or {})
        events = events_by_action.get(str(action.get("action_id") or ""), [])
        records = [
            record for event in events
            for record in settlements_by_event.get(str(event.get("event_id") or ""), [])
            if agent_id in (record.get("subject_ids") or [])
        ]
        reward, previous_pnl = _settlement_reward(records, previous_pnl)
        primary = records[-1] if records else {}
        authority = dict(primary.get("authority") or {})
        mode = str(authority.get("mode") or "")
        parse_errors = list(pack.get("parse_errors") or [])
        llm_error = str(log.get("error") or "") or None
        fallback = (
            bool(pack.get("is_system_fallback"))
            or bool(llm_error)
            or not bool(action)
        )
        perception = dict(log.get("perception_pack") or {})
        trajectory.steps.append(TrajectoryStep(
            sample_id=f"{root.name}:{agent_id}:t{tick}",
            tick=tick,
            agent_id=agent_id,
            system_prompt=str(perception.get("system_prompt") or ""),
            user_brief=json.dumps(perception, ensure_ascii=False),
            action_id=str(action.get("action_type") or pack.get("action_id") or ""),
            action_category=str(pack.get("category") or ""),
            intent=str(pack.get("intent") or ""),
            plan=str(pack.get("plan") or ""),
            note_to_self=str(pack.get("note_to_self") or ""),
            target_object_id=pack.get("target_object_id"),
            target_agent_id=pack.get("target_agent_id"),
            raw_response=str(log.get("raw_llm_response") or ""),
            character_monologue=str(pack.get("character_monologue") or ""),
            outcome=str(primary.get("outcome") or (events[-1].get("event_type") if events else "")),
            reward=round(reward, 6),
            reward_purity=(
                PURITY_SIMULATION if mode == "simulation" else PURITY_DETERMINISTIC
            ),
            source_event_refs=[str(item.get("event_id")) for item in events],
            settlement_refs=[str(item.get("settlement_id")) for item in records],
            settlement_values=dict(primary.get("values") or {}),
            authority_mode=mode,
            authority_provider=str(authority.get("provider_id") or ""),
            parsed_ok=not parse_errors and not fallback,
            parse_errors=parse_errors,
            is_fallback=fallback,
            is_empty_action=not bool(action.get("action_type")),
            llm_error=llm_error,
            step_metric_deltas=[
                {"metric": key, "delta": value, "reason": primary.get("explanation", "")}
                for key, value in dict(primary.get("values") or {}).items()
            ],
            delta_ids=[str(item.get("event_id")) for item in events],
        ))
    return trajectory


def iter_trajectories(run_dir: Path | str) -> Iterator[Trajectory]:
    root = Path(run_dir)
    meta = _read_json(root / "meta.json") or {}
    standings = _read_json(root / "reports" / "victory_standings.json") or []
    for agent_id in meta.get("agent_ids") or []:
        yield load_trajectory(
            root,
            str(agent_id),
            meta=meta,
            victory_standings=standings,
        )
