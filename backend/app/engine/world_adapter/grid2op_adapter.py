"""Optional Grid2Op adapter.

Each competing actor receives an isolated environment created from the same
configuration and seed. This compares strategies fairly; agents do not mutate
one shared power grid sequentially within a TraceArena tick.
"""
from __future__ import annotations

import hashlib
import json
from typing import Any, Dict, List, Optional

from app.contracts.world_adapter import (
    WorldAdapterActionReceipt,
    WorldAdapterCommand,
    WorldAdapterObservation,
    WorldAdapterProvenance,
    WorldAdapterTerminal,
    WorldAdapterTransition,
    WorldModelAssurance,
)


def _jsonable(value: Any) -> Any:
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, dict):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple)):
        return [_jsonable(item) for item in value]
    tolist = getattr(value, "tolist", None)
    if callable(tolist):
        return _jsonable(tolist())
    return str(value)


class Grid2OpAdapter:
    adapter_id = "builtin:grid2op"
    adapter_version = "0.1.0"

    def __init__(self) -> None:
        self._grid2op: Any = None
        self._config: Dict[str, Any] = {}
        self._seed: Optional[int] = None
        self._envs: Dict[str, Any] = {}
        self._observations: Dict[str, Any] = {}
        self._pending: Dict[str, Dict[str, Any]] = {}
        self._pending_approvals: Dict[str, Dict[str, Any]] = {}
        self._rewards: Dict[str, float] = {}
        self._done: Dict[str, bool] = {}
        self._done_reasons: Dict[str, str] = {}
        self._tick = 0

    def initialize(self, config: Dict[str, Any], seed: Optional[int]) -> None:
        try:
            import grid2op  # type: ignore
        except ModuleNotFoundError as exc:
            if exc.name == "grid2op":
                raise RuntimeError(
                    "Grid2Op adapter requires optional dependencies; install "
                    "backend/requirements-grid2op.txt"
                ) from exc
            raise RuntimeError(
                f"Grid2Op dependency is incomplete: {exc}"
            ) from exc
        except Exception as exc:
            raise RuntimeError(
                f"Grid2Op import failed in this runtime: {exc}"
            ) from exc
        self._grid2op = grid2op
        self._config = dict(config or {})
        self._seed = seed
        actor_ids = [str(item) for item in self._config.get("actor_ids", []) or []]
        if not actor_ids:
            raise ValueError("Grid2Op adapter requires config.actor_ids")
        for actor_id in actor_ids:
            env = self._make_env()
            # Every competitor receives the same exogenous trajectory. Different
            # seeds would make environment luck indistinguishable from strategy.
            actor_seed = None if seed is None else int(seed)
            if actor_seed is not None and hasattr(env, "seed"):
                env.seed(actor_seed)
            self._envs[actor_id] = env
            self._rewards[actor_id] = 0.0
            self._done[actor_id] = False
            self._done_reasons[actor_id] = ""

    def _make_env(self) -> Any:
        env_name = str(
            self._config.get("environment") or "l2rpn_case14_sandbox"
        )
        kwargs = dict(self._config.get("make_kwargs", {}) or {})
        return self._grid2op.make(env_name, **kwargs)

    def reset(self) -> Dict[str, WorldAdapterObservation]:
        self._pending = {}
        self._pending_approvals = {}
        self._tick = 0
        # Grid2Op has a rich, simulator-native reset contract: a scenario can
        # choose a chronological point, an initial simulated outage, thermal
        # limits, etc.  Keep this as a generic adapter option rather than
        # encoding any electricity-domain event in the OS.  The scenario pack
        # owns the values under ``world/adapter.yaml``.
        reset_options = self._config.get("reset_options") or {}
        if not isinstance(reset_options, dict):
            raise ValueError("Grid2Op adapter config.reset_options must be a mapping")
        for actor_id, env in self._envs.items():
            # Grid2Op can mutate nested input collections while building an
            # initial action, so each competitor receives a fresh deep copy.
            options = json.loads(json.dumps(reset_options))
            actor_seed = None if self._seed is None else int(self._seed)
            try:
                self._observations[actor_id] = env.reset(
                    seed=actor_seed,
                    options=options or None,
                )
            except TypeError:
                # Keep compatibility with older Grid2Op releases (and minimal
                # test doubles) that predate reset(seed=..., options=...).
                # The initial seed was already applied in initialize().
                if options:
                    try:
                        self._observations[actor_id] = env.reset(options=options)
                    except TypeError as exc:
                        raise RuntimeError(
                            "Grid2Op runtime does not support the scenario's "
                            "declared reset_options"
                        ) from exc
                else:
                    self._observations[actor_id] = env.reset()
            self._rewards[actor_id] = 0.0
            self._done[actor_id] = False
            self._done_reasons[actor_id] = ""
        return {actor_id: self.observe(actor_id) for actor_id in self._envs}

    def observe(self, actor_id: str) -> WorldAdapterObservation:
        if actor_id not in self._observations:
            raise KeyError(f"unknown Grid2Op actor: {actor_id}")
        return WorldAdapterObservation(
            observation_id=f"grid2op:{self._tick}:{actor_id}",
            world_tick=self._tick,
            actor_id=actor_id,
            values=self._observation_values(self._observations[actor_id]),
            legal_actions=self.legal_actions(actor_id),
        )

    def legal_actions(self, actor_id: str) -> List[Dict[str, Any]]:
        mappings = dict(self._config.get("action_mapping", {}) or {})
        declared = [
            {"action_type": action_type, "payload": _jsonable(payload)}
            for action_type, payload in mappings.items()
        ]
        declared.append({
            "action_type": "wait",
            "payload": {},
            "description": "submit the Grid2Op do-nothing action",
        })
        return declared

    def apply_actions(
        self, commands: List[WorldAdapterCommand]
    ) -> List[WorldAdapterActionReceipt]:
        self._pending = {}
        receipts: List[WorldAdapterActionReceipt] = []
        mappings = dict(self._config.get("action_mapping", {}) or {})
        for command in commands:
            if command.actor_id not in self._envs:
                receipts.append(self._receipt(
                    command, "rejected", ["unknown_actor"]
                ))
                continue
            if self._done.get(command.actor_id):
                receipts.append(self._receipt(
                    command, "rejected", ["environment_already_terminal"]
                ))
                continue
            action_risk = self._risk_level(command.action_type)
            approval_decision = str(
                command.parameters.get("approval_decision") or ""
            ).strip().lower()
            if action_risk in {"high", "critical"} and approval_decision != "approved":
                approval_id = f"approval:{command.world_tick}:{command.actor_id}:{command.action_type}"
                self._pending_approvals[approval_id] = {
                    "command": command,
                    "risk_level": action_risk,
                    "rollback_ref": f"snapshot:{command.world_tick}:{command.actor_id}",
                }
                status = "rolled_back" if approval_decision == "rollback" else "needs_approval"
                reasons = ["approval_required"] if status == "needs_approval" else []
                receipts.append(self._receipt(
                    command,
                    status,
                    reasons,
                    {
                        "approval_id": approval_id,
                        "risk_level": action_risk,
                        "rollback_ref": f"snapshot:{command.world_tick}:{command.actor_id}",
                        "policy": "high_risk_world_action_requires_approval",
                    },
                ))
                continue
            payload = command.parameters.get("grid2op_action")
            if payload is None:
                payload = mappings.get(command.action_type)
            if payload is None and command.action_type == "wait":
                payload = {}
            if not isinstance(payload, dict):
                receipts.append(self._receipt(
                    command, "rejected", ["grid2op_action_mapping_missing"]
                ))
                continue
            try:
                action = self._envs[command.actor_id].action_space(dict(payload))
            except Exception as exc:
                receipts.append(self._receipt(
                    command,
                    "rejected",
                    ["invalid_grid2op_action"],
                    {"error": str(exc)},
                ))
                continue
            self._pending[command.actor_id] = {
                "command": command,
                "action": action,
                "payload": dict(payload),
            }
            receipts.append(self._receipt(
                command,
                "accepted",
                details={"payload": _jsonable(payload), "risk_level": action_risk},
            ))
        return receipts

    def step(self, world_tick: int) -> WorldAdapterTransition:
        before = self.snapshot()
        receipts: List[WorldAdapterActionReceipt] = []
        observations: List[WorldAdapterObservation] = []
        for actor_id, item in self._pending.items():
            command = item["command"]
            try:
                observation, reward, done, info = self._envs[actor_id].step(
                    item["action"]
                )
                self._observations[actor_id] = observation
                self._rewards[actor_id] += float(reward or 0.0)
                self._done[actor_id] = bool(done)
                if done:
                    self._done_reasons[actor_id] = str(
                        (info or {}).get("exception") or "grid2op_terminal"
                    )
                receipts.append(self._receipt(
                    command,
                    "executed",
                    details={
                        "reward": float(reward or 0.0),
                        "done": bool(done),
                        "info": _jsonable(info or {}),
                    },
                ))
            except Exception as exc:
                self._done[actor_id] = True
                self._done_reasons[actor_id] = f"step_failed:{exc}"
                receipts.append(self._receipt(
                    command,
                    "failed",
                    ["grid2op_step_failed"],
                    {"error": str(exc)},
                ))
        self._tick = world_tick
        observations.extend(self.observe(actor_id) for actor_id in self._envs)
        after = self.snapshot()
        transition = WorldAdapterTransition(
            transition_id=f"grid2op-transition:{world_tick}",
            world_tick=world_tick,
            adapter_id=self.adapter_id,
            state_before=before,
            state_after=after,
            deltas={
                "actors_advanced": sorted(self._pending),
                "reward_delta": {
                    item.actor_id: float(item.details.get("reward", 0.0) or 0.0)
                    for item in receipts
                },
            },
            metrics=self.metrics(),
            receipts=receipts,
            observations=observations,
            terminal=self.terminal(),
            provenance=self.provenance(),
        )
        self._pending = {}
        return transition

    def metrics(self) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for actor_id, observation in self._observations.items():
            rho = _jsonable(getattr(observation, "rho", []))
            numeric_rho = [float(item) for item in rho] if isinstance(rho, list) else []
            line_status = _jsonable(
                getattr(observation, "line_status", [])
            )
            if not isinstance(line_status, list):
                line_status = []
            result[actor_id] = {
                "cumulative_reward": self._rewards.get(actor_id, 0.0),
                "max_rho": max(numeric_rho) if numeric_rho else 0.0,
                "disconnected_lines": sum(
                    1 for item in line_status if not bool(item)
                ),
                "done": self._done.get(actor_id, False),
            }
        return result

    def terminal(self) -> WorldAdapterTerminal:
        done = bool(self._done) and all(self._done.values())
        winners: List[str] = []
        if done and self._rewards:
            best = max(self._rewards.values())
            winners = [
                actor_id for actor_id, reward in self._rewards.items()
                if reward == best
            ]
        return WorldAdapterTerminal(
            done=done,
            reason="all_actor_environments_terminal" if done else "",
            winner_ids=winners,
            details={"actor_reasons": dict(self._done_reasons)},
        )

    def snapshot(self) -> Dict[str, Any]:
        return {
            "tick": self._tick,
            "actors": {
                actor_id: self._observation_values(observation)
                for actor_id, observation in self._observations.items()
            },
            "metrics": self.metrics(),
        }

    def provenance(self) -> WorldAdapterProvenance:
        payload = json.dumps(self._config, sort_keys=True, default=str).encode()
        return WorldAdapterProvenance(
            adapter_id=self.adapter_id,
            adapter_version=self.adapter_version,
            model_kind="simulator",
            engine_name="Grid2Op",
            engine_version=str(getattr(self._grid2op, "__version__", "")),
            config_hash=hashlib.sha256(payload).hexdigest(),
            seed=self._seed,
            deterministic=self._seed is not None,
            source_uri="https://github.com/Grid2op/grid2op",
            assurance=WorldModelAssurance(
                trust_tier="validated",
                validation_refs=["backend/scripts/smoke_grid2op_adapter.py"],
                assumptions=[
                    "each actor receives an isolated environment with the same seed"
                ],
                limitations=[
                    "simulation results do not by themselves establish real-grid outcomes"
                ],
            ),
            metadata={
                "environment": str(
                    self._config.get("environment")
                    or "l2rpn_case14_sandbox"
                ),
                "isolated_environment_per_actor": True,
                "reset_options_declared": bool(
                    self._config.get("reset_options")
                ),
            },
        )

    def close(self) -> None:
        for env in self._envs.values():
            close = getattr(env, "close", None)
            if callable(close):
                close()
        self._envs = {}
        self._observations = {}
        self._pending = {}

    @staticmethod
    def _receipt(
        command: WorldAdapterCommand,
        status: str,
        reasons: Optional[List[str]] = None,
        details: Optional[Dict[str, Any]] = None,
    ) -> WorldAdapterActionReceipt:
        return WorldAdapterActionReceipt(
            receipt_id=f"receipt:{command.command_id}",
            command_id=command.command_id,
            world_tick=command.world_tick,
            actor_id=command.actor_id,
            action_type=command.action_type,
            status=status,
            reasons=list(reasons or []),
            details=dict(details or {}),
        )

    def _risk_level(self, action_type: str) -> str:
        policy = self._config.get("approval_policy") or {}
        if isinstance(policy, dict):
            action_levels = policy.get("action_risk_levels") or {}
            if isinstance(action_levels, dict):
                level = str(action_levels.get(action_type) or "").strip().lower()
                if level in {"low", "medium", "high", "critical"}:
                    return level
        return "low"

    @staticmethod
    def _observation_values(observation: Any) -> Dict[str, Any]:
        fields = (
            "current_step",
            "max_step",
            "rho",
            "line_status",
            "topo_vect",
            "gen_p",
            "load_p",
            "actual_dispatch",
            "target_dispatch",
            "time_before_cooldown_line",
            "time_before_cooldown_sub",
        )
        return {
            field: _jsonable(getattr(observation, field))
            for field in fields
            if hasattr(observation, field)
        }
