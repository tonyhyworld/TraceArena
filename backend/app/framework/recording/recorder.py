"""OS2 run recorder.

The archive has one source of truth: WorldAction, ExternalObservation,
WorldEvent, SettlementRecord and DirectorPlan. Harness inputs, model outputs
and tool runs remain attached evidence; no parallel evaluation ledger exists.
"""
from __future__ import annotations

import json
import hashlib
import os
import tempfile
import time
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime
from typing import Any, Dict, List, Optional

from app.core.redaction import redact_structure


ENGINE_VERSION = "2.0.0"


def _dump(value: Any) -> Any:
    if hasattr(value, "model_dump"):
        return value.model_dump(mode="json")
    if hasattr(value, "__dataclass_fields__"):
        return asdict(value)
    return value


@dataclass
class TickRecord:
    tick: int
    timestamp: float
    perception_packets: List[Dict[str, Any]] = field(default_factory=list)
    agent_logs: List[Dict[str, Any]] = field(default_factory=list)
    tool_runs: List[Dict[str, Any]] = field(default_factory=list)
    assessment_cases: List[Dict[str, Any]] = field(default_factory=list)
    world_actions: List[Dict[str, Any]] = field(default_factory=list)
    external_observations: List[Dict[str, Any]] = field(default_factory=list)
    world_events: List[Dict[str, Any]] = field(default_factory=list)
    settlements: List[Dict[str, Any]] = field(default_factory=list)
    director_plan: Optional[Dict[str, Any]] = None
    director_harness_trace: Optional[Dict[str, Any]] = None
    world_snapshot: Dict[str, Any] = field(default_factory=dict)


@dataclass
class ReplayPackage:
    run_id: str
    ticks: List[Dict[str, Any]] = field(default_factory=list)
    index_by_agent: Dict[str, List[int]] = field(default_factory=dict)
    index_by_event: Dict[str, int] = field(default_factory=dict)
    index_by_settlement: Dict[str, int] = field(default_factory=dict)


class RunRecorder:
    def __init__(
        self,
        scenario_name: str,
        run_id: Optional[str] = None,
        scenario_version: str = "",
        random_seed: Optional[int] = None,
    ):
        self._run_id = run_id or f"run_{uuid.uuid4().hex[:8]}"
        self._scenario_name = scenario_name
        self._scenario_version = scenario_version
        self._random_seed = random_seed
        self._started_at = datetime.utcnow().isoformat()
        self._ended_at: Optional[str] = None
        self._agent_ids: List[str] = []
        self._agent_models: Dict[str, Dict[str, Any]] = {}
        self._scenario_cfg_snapshot: Dict[str, Any] = {}
        self._ticks: List[TickRecord] = []
        self._reports: Dict[str, Any] = {}

    @property
    def run_id(self) -> str:
        return self._run_id

    def set_agents(self, agent_ids: List[str]) -> None:
        self._agent_ids = list(agent_ids)

    def set_agent_model(self, agent_id: str, model_info: Dict[str, Any]) -> None:
        self._agent_models[agent_id] = dict(model_info)

    def set_scenario_config(self, cfg: Dict[str, Any]) -> None:
        self._scenario_cfg_snapshot = dict(cfg)

    def record_tick(
        self,
        *,
        tick: int,
        state: Any = None,
        agent_logs: Optional[List[Any]] = None,
        assessment_cases: Optional[List[Any]] = None,
        tool_runs: Optional[List[Any]] = None,
        world_snapshot: Optional[Dict[str, Any]] = None,
        world_actions: Optional[List[Any]] = None,
        external_observations: Optional[List[Any]] = None,
        world_events: Optional[List[Any]] = None,
        settlements: Optional[List[Any]] = None,
        director_plan: Any = None,
        director_harness_trace: Any = None,
        **_ignored: Any,
    ) -> None:
        logs = [redact_structure(_dump(item)) for item in (agent_logs or [])]
        self._ticks.append(TickRecord(
            tick=tick,
            timestamp=time.time(),
            perception_packets=[
                dict(item.get("perception_pack") or {})
                for item in logs if item.get("perception_pack")
            ],
            agent_logs=logs,
            tool_runs=[_dump(item) for item in (tool_runs or [])],
            assessment_cases=[_dump(item) for item in (assessment_cases or [])],
            world_actions=[_dump(item) for item in (world_actions or [])],
            external_observations=[
                _dump(item) for item in (external_observations or [])
            ],
            world_events=[_dump(item) for item in (world_events or [])],
            settlements=[_dump(item) for item in (settlements or [])],
            director_plan=_dump(director_plan) if director_plan else None,
            director_harness_trace=(
                _dump(director_harness_trace)
                if director_harness_trace else None
            ),
            world_snapshot=dict(world_snapshot or {}),
        ))

    def append_terminal_settlements(
        self, tick: int, settlements: Optional[List[Any]] = None
    ) -> None:
        """Attach terminal records to the authoritative tick that produced them.

        Terminal settlement runs after the normal tick recorder has committed,
        so without this explicit append a valid winner can appear in reports
        while the replay/settlement ledger is missing its source record.
        """
        rows = [_dump(item) for item in (settlements or [])]
        if not rows:
            return
        target = next((item for item in reversed(self._ticks) if item.tick == tick), None)
        if target is None:
            target = TickRecord(tick=tick, timestamp=time.time())
            self._ticks.append(target)
        known = {str(item.get("settlement_id") or "") for item in target.settlements}
        target.settlements.extend(
            item for item in rows
            if str(item.get("settlement_id") or "") not in known
        )

    def finalize(self, state: Any) -> None:
        self._ended_at = datetime.utcnow().isoformat()
        internal = dict(getattr(state, "internal", {}) or {})
        self._reports = {
            "victory_standings": list(
                internal.get("victory_standings", []) or []
            ),
            "victory_attribution": list(
                internal.get("victory_attribution", []) or []
            ),
            "fairness_report": dict(internal.get("fairness_report", {}) or {}),
            "harness_health_report": dict(
                internal.get("harness_health_report", {}) or {}
            ),
            "measurement_opportunities": list(
                internal.get("measurement_opportunities", []) or []
            ),
            "assessment_cases": list(
                (internal.get("capability_assessment", {}) or {}).get("cases", [])
                or []
            ),
        }

    def _meta_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self._run_id,
            "started_at": self._started_at,
            "ended_at": self._ended_at,
            "engine_version": ENGINE_VERSION,
            "scenario_id": self._scenario_name,
            "scenario_version": self._scenario_version,
            "random_seed": self._random_seed,
            "agent_ids": self._agent_ids,
            "agent_models": self._agent_models,
            "scenario_config_snapshot": self._scenario_cfg_snapshot,
        }

    def export_json(self, path: str) -> str:
        _write_json(path, {
            **self._meta_dict(),
            "reports": self._reports,
            "ticks": [asdict(item) for item in self._ticks],
        })
        return path

    def export_directory(self, base_dir: str) -> str:
        run_dir = os.path.join(base_dir, self._run_id)
        ticks_dir = os.path.join(run_dir, "ticks")
        ledgers_dir = os.path.join(run_dir, "ledgers")
        reports_dir = os.path.join(run_dir, "reports")
        for directory in (ticks_dir, ledgers_dir, reports_dir):
            os.makedirs(directory, exist_ok=True)
        status_path = os.path.join(run_dir, "archive_status.json")
        target_state = "finalized" if self._ended_at is not None else "partial"
        # Invalidate the previous commit marker before replacing any artifact.
        # If the process dies midway, readers see `exporting` instead of a
        # misleading mixture of old and new snapshots.
        _write_json(status_path, {
            "schema_version": "1.0",
            "run_id": self._run_id,
            "state": "exporting",
            "target_state": target_state,
            "complete": False,
            "started_at": time.time(),
        })
        _write_json(os.path.join(run_dir, "meta.json"), self._meta_dict())
        for item in self._ticks:
            _write_json(
                os.path.join(ticks_dir, f"tick_{item.tick:03d}.json"),
                asdict(item),
            )
        self._export_ledgers(ledgers_dir)
        self._export_agents(run_dir)
        for name, payload in self._reports.items():
            _write_json(os.path.join(reports_dir, f"{name}.json"), payload)
        _write_json(
            os.path.join(run_dir, "replay.json"),
            asdict(self.build_replay_package()),
        )
        artifacts = _archive_artifact_inventory(run_dir)
        # This is the directory transaction's commit record and must remain the
        # final write in the export sequence.
        _write_json(status_path, {
            "schema_version": "1.0",
            "run_id": self._run_id,
            "state": target_state,
            "complete": True,
            "tick_count": len(self._ticks),
            "last_tick": max((item.tick for item in self._ticks), default=0),
            "reports": sorted(self._reports),
            "artifacts": artifacts,
            "ended_at": self._ended_at,
            "committed_at": time.time(),
        })
        return run_dir

    def _export_ledgers(self, ledgers_dir: str) -> None:
        fields = (
            "world_actions", "external_observations", "world_events",
            "settlements", "tool_runs", "perception_packets",
            "assessment_cases",
        )
        for field_name in fields:
            rows = [row for tick in self._ticks for row in getattr(tick, field_name)]
            _write_jsonl(os.path.join(ledgers_dir, f"{field_name}.jsonl"), rows)
        _write_jsonl(
            os.path.join(ledgers_dir, "director_plans.jsonl"),
            [item.director_plan for item in self._ticks if item.director_plan],
        )
        _write_jsonl(
            os.path.join(ledgers_dir, "director_harness_traces.jsonl"),
            [
                item.director_harness_trace for item in self._ticks
                if item.director_harness_trace
            ],
        )

    def _export_agents(self, run_dir: str) -> None:
        root = os.path.join(run_dir, "agents")
        os.makedirs(root, exist_ok=True)
        for agent_id in self._agent_ids:
            rows = [
                log for tick in self._ticks for log in tick.agent_logs
                if str(log.get("agent_id") or "") == agent_id
            ]
            directory = os.path.join(root, agent_id)
            os.makedirs(directory, exist_ok=True)
            _write_jsonl(os.path.join(directory, "harness_io.jsonl"), rows)
            actions = [
                action for tick in self._ticks for action in tick.world_actions
                if str(action.get("actor_id") or "") == agent_id
            ]
            _write_jsonl(os.path.join(directory, "world_actions.jsonl"), actions)

    def build_replay_package(self) -> ReplayPackage:
        package = ReplayPackage(run_id=self._run_id)
        for index, item in enumerate(self._ticks):
            payload = asdict(item)
            package.ticks.append(payload)
            for action in item.world_actions:
                actor_id = str(action.get("actor_id") or "")
                if actor_id:
                    package.index_by_agent.setdefault(actor_id, []).append(index)
            for event in item.world_events:
                event_id = str(event.get("event_id") or "")
                if event_id:
                    package.index_by_event[event_id] = index
            for record in item.settlements:
                record_id = str(record.get("settlement_id") or "")
                if record_id:
                    package.index_by_settlement[record_id] = index
        return package


def _write_json(path: str, payload: Any) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(
                redact_structure(payload), handle,
                ensure_ascii=False, indent=2, default=str,
            )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _write_jsonl(path: str, rows: List[Any]) -> None:
    directory = os.path.dirname(os.path.abspath(path))
    os.makedirs(directory, exist_ok=True)
    descriptor, temporary = tempfile.mkstemp(
        prefix=f".{os.path.basename(path)}.", suffix=".tmp", dir=directory,
    )
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            for row in rows:
                handle.write(
                    json.dumps(
                        redact_structure(row), ensure_ascii=False, default=str,
                    ) + "\n"
                )
            handle.flush()
            os.fsync(handle.fileno())
        os.replace(temporary, path)
    except Exception:
        try:
            os.unlink(temporary)
        except OSError:
            pass
        raise


def _sha256_file(path: str) -> str:
    digest = hashlib.sha256()
    with open(path, "rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def _archive_artifact_inventory(run_dir: str) -> Dict[str, Dict[str, Any]]:
    root = os.path.abspath(run_dir)
    paths: List[str] = []
    for name in ("meta.json", "replay.json"):
        path = os.path.join(root, name)
        if os.path.isfile(path):
            paths.append(path)
    for subdir in ("ticks", "ledgers", "reports"):
        directory = os.path.join(root, subdir)
        if not os.path.isdir(directory):
            continue
        for current, _dirs, files in os.walk(directory):
            paths.extend(
                os.path.join(current, name)
                for name in files if not name.startswith(".")
            )
    agents_root = os.path.join(root, "agents")
    if os.path.isdir(agents_root):
        for agent_id in os.listdir(agents_root):
            directory = os.path.join(agents_root, agent_id)
            if not os.path.isdir(directory):
                continue
            paths.extend(
                os.path.join(directory, name)
                for name in os.listdir(directory)
                if name.endswith(".jsonl")
                and os.path.isfile(os.path.join(directory, name))
            )
    inventory: Dict[str, Dict[str, Any]] = {}
    for path in sorted(set(paths)):
        relative = os.path.relpath(path, root)
        inventory[relative] = {
            "sha256": _sha256_file(path),
            "size": os.path.getsize(path),
        }
    return inventory


def verify_archive_directory(run_dir: str) -> Dict[str, Any]:
    """Verify a committed recorder snapshot without trusting its contents."""
    root = os.path.abspath(run_dir)
    status_path = os.path.join(root, "archive_status.json")
    if not os.path.isfile(status_path):
        return {
            "available": False,
            "passed": None,
            "errors": ["archive_status_missing"],
            "artifacts_checked": 0,
        }
    try:
        with open(status_path, encoding="utf-8") as handle:
            status = json.load(handle)
    except (OSError, ValueError) as exc:
        return {
            "available": True,
            "passed": False,
            "errors": [f"archive_status_invalid:{type(exc).__name__}"],
            "artifacts_checked": 0,
        }
    errors: List[str] = []
    if not status.get("complete"):
        errors.append(f"archive_not_committed:{status.get('state') or 'unknown'}")
    artifacts = status.get("artifacts")
    if not isinstance(artifacts, dict) or not artifacts:
        errors.append("artifact_inventory_missing")
        artifacts = {}
    checked = 0
    for relative, expected in artifacts.items():
        relative = str(relative)
        target = os.path.abspath(os.path.join(root, relative))
        if os.path.commonpath((root, target)) != root:
            errors.append(f"artifact_path_escape:{relative}")
            continue
        if os.path.islink(target):
            errors.append(f"artifact_symlink_forbidden:{relative}")
            continue
        if not os.path.isfile(target):
            errors.append(f"artifact_missing:{relative}")
            continue
        checked += 1
        expected = expected if isinstance(expected, dict) else {}
        if os.path.getsize(target) != expected.get("size"):
            errors.append(f"artifact_size_mismatch:{relative}")
            continue
        if _sha256_file(target) != expected.get("sha256"):
            errors.append(f"artifact_hash_mismatch:{relative}")
    return {
        "available": True,
        "passed": not errors,
        "errors": errors,
        "artifacts_checked": checked,
        "state": status.get("state"),
    }
