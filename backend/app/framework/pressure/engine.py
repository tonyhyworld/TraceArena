"""
PressureEngine：Agent 压力状态的**通用执行器**（内容由场景包声明）。

OS 不再写死"六维压力 + attack→counterplay"。压力模型（哪些维度、什么参数、
什么反应）由场景包 world/pressure.yaml 声明，经 contracts.pressure_model
解析为 PressureModel；本引擎只按维度的通用 kind 原语执行：

  budget/pool/accumulator/gauge/ramp/reactive —— 六种与场景无关的压力原语。

场景不声明 dimensions 时回退到 DEFAULT_PRESSURE_MODEL（通用默认，可被旧版
扁平参数覆盖），保证既有场景零行为变化。不同场景可声明"完全不同"的压力模型。

集成路径（不变）：
  ValidationGate ← compute_validation_modifiers() → force/risk_multiplier + allow_physics
  ForceBudgetCalculator ← compute_budget_modifiers() → resource_budget_bonus
  run_causal_pipeline 末尾 ← apply_pipeline_result() → 消耗/累积/触发声明的反应
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.contracts.pressure_model import (
    DEFAULT_PRESSURE_MODEL,
    PressureDimension,
    PressureModel,
)
from app.core.interfaces import AgentPressureState


class PressureEngine:
    """按场景声明的 PressureModel 执行；只认识通用 kind，不认识具体维度名。"""

    def __init__(
        self,
        agent_ids: Optional[List[str]] = None,
        pressure_cfg: Optional[Dict[str, Any]] = None,
        model: Optional[PressureModel] = None,
    ):
        self._cfg: Dict[str, Any] = pressure_cfg or {}
        self._model: PressureModel = model or DEFAULT_PRESSURE_MODEL
        self._dims: Dict[str, PressureDimension] = {
            d.id: d for d in self._model.dimensions
        }
        # 三个全局调参（斜坡截止、暗策基础风险、调查信息增益）来自扁平 cfg。
        self._deadline_tick = self._cfg.get("deadline_tick")
        self._strategy_risk = float(self._cfg.get("strategy_risk_per_action", 0.12))
        self._info_gain = float(self._cfg.get("investigation_info_gain", 0.08))
        # 每个 agent 的维度值：{agent_id: {dim_id: value}}
        self._states: Dict[str, Dict[str, float]] = {}
        self._tick: int = 0
        for agent_id in (agent_ids or []):
            self._states[agent_id] = self._make_initial_state()

    # ── kind 查询 ────────────────────────────────────────────────────────

    def _ids_of_kind(self, kind: str) -> List[str]:
        return [d.id for d in self._model.dimensions if d.kind == kind]

    def _make_initial_state(self) -> Dict[str, float]:
        return {d.id: float(d.initial) for d in self._model.dimensions}

    def register_agents(self, agent_ids: List[str]) -> None:
        for agent_id in agent_ids:
            if agent_id not in self._states:
                self._states[agent_id] = self._make_initial_state()

    def _s(self, agent_id: str) -> Dict[str, float]:
        if agent_id not in self._states:
            self._states[agent_id] = self._make_initial_state()
        return self._states[agent_id]

    # ── 兼容旧接口：get_state 返回 AgentPressureState（标准维度映射到具名字段）──

    def get_state(self, agent_id: str) -> AgentPressureState:
        s = self._s(agent_id)
        ap = self._dims.get("action_points")
        res = self._dims.get("resources")
        risk = self._dims.get("risk_accumulation")
        reasons = self._pressure_reasons(agent_id)
        return AgentPressureState(
            agent_id=agent_id,
            tick=self._tick,
            action_points=s.get("action_points", 0.0),
            action_points_max=float(ap.max) if ap and ap.max is not None else 10.0,
            resources=s.get("resources", 0.0),
            resources_max=float(res.max) if res and res.max is not None else 200.0,
            risk_accumulation=s.get("risk_accumulation", 0.0),
            risk_threshold=float(risk.threshold) if risk and risk.threshold is not None else 0.5,
            information_scope=s.get("information_scope", 0.0),
            deadline_pressure=s.get("deadline_pressure", 0.0),
            counterplay_level=s.get("counterplay_level", 0.0),
            is_under_pressure=bool(reasons),
            pressure_reasons=reasons,
        )

    def get_all_states(self) -> Dict[str, AgentPressureState]:
        return {aid: self.get_state(aid) for aid in self._states}

    # ── Tick 推进 ────────────────────────────────────────────────────────

    def advance_tick(
        self, tick: int,
        game_resource_states: Optional[Dict[str, Dict[str, float]]] = None,
    ) -> None:
        self._tick = tick
        for agent_id, s in self._states.items():
            gr = (game_resource_states or {}).get(agent_id)
            for dim in self._model.dimensions:
                v = s.get(dim.id, dim.initial)
                if dim.kind == "budget":
                    if gr is not None and dim.id in gr:
                        v = round(float(gr[dim.id]), 4)
                    else:
                        cap = dim.max if dim.max is not None else v
                        v = round(min(cap, v + dim.regen), 4)
                elif dim.kind == "pool":
                    if gr is not None and dim.id == "resources":
                        energy = float(gr.get("energy", 100))
                        tool_budget = float(gr.get("tool_budget", 5))
                        cap = dim.max if dim.max is not None else 200.0
                        v = round(min(cap, energy * 0.6 + tool_budget * 10.0), 4)
                    elif gr is not None and dim.id in gr:
                        cap = dim.max if dim.max is not None else v
                        v = round(min(cap, float(gr[dim.id])), 4)
                    else:
                        cap = dim.max if dim.max is not None else v
                        v = round(min(cap, v + dim.regen), 4)
                elif dim.kind == "accumulator":
                    v = round(v * (1.0 - dim.decay), 4)
                elif dim.kind == "ramp":
                    if self._deadline_tick:
                        v = round(min(1.0, tick / float(self._deadline_tick)), 4)
                # gauge / reactive 在 tick 开始不自动变（reactive 在 end_tick 衰减）
                s[dim.id] = v

    def end_tick(self) -> None:
        for s in self._states.values():
            for dim in self._model.dimensions:
                if dim.kind == "reactive":
                    s[dim.id] = round(s.get(dim.id, 0.0) * dim.decay, 4)

    # ── 状态修改 ─────────────────────────────────────────────────────────

    def consume_action_point(self, agent_id: str, cost: float = 1.0) -> bool:
        s = self._s(agent_id)
        for dim_id in self._ids_of_kind("budget"):
            if s.get(dim_id, 0.0) >= cost:
                s[dim_id] = round(s[dim_id] - cost, 4)
                return True
            s[dim_id] = 0.0
        return False

    def consume_resource(self, agent_id: str, amount: float) -> None:
        s = self._s(agent_id)
        for dim_id in self._ids_of_kind("pool"):
            s[dim_id] = round(max(0.0, s.get(dim_id, 0.0) - amount), 4)

    def accumulate_risk(self, agent_id: str, delta: float) -> None:
        if delta <= 0:
            return
        s = self._s(agent_id)
        for dim_id in self._ids_of_kind("accumulator"):
            s[dim_id] = round(min(2.0, s.get(dim_id, 0.0) + delta), 4)

    def signal_counterplay(self, agent_id: str, level: float) -> None:
        s = self._s(agent_id)
        for dim in self._model.dimensions:
            if dim.kind == "reactive":
                cap = dim.max if dim.max is not None else 1.0
                s[dim.id] = round(min(cap, s.get(dim.id, 0.0) + level), 4)

    def update_information_scope(self, agent_id: str, delta: float) -> None:
        s = self._s(agent_id)
        for dim_id in self._ids_of_kind("gauge"):
            s[dim_id] = round(max(0.0, min(1.0, s.get(dim_id, 0.0) + delta)), 4)

    def accumulate_strategy_risk(self, agent_id: str) -> None:
        self.accumulate_risk(agent_id, self._strategy_risk)

    def gain_information_scope(self, agent_id: str) -> None:
        self.update_information_scope(agent_id, self._info_gain)

    # ── 管线集成 ─────────────────────────────────────────────────────────

    def apply_pipeline_result(self, result) -> None:
        if result.evaluation is None:
            return
        agent_id = result.agent_id
        eval_ = result.evaluation

        resource_cost = round(eval_.estimated_cost * 0.1, 4)
        if resource_cost > 0:
            self.consume_resource(agent_id, resource_cost)

        if result.outcome == "backlash" and result.proposal is not None:
            self.accumulate_risk(agent_id, result.proposal.risk_side_effect)

        # 声明式反应（取代硬编码 attack→counterplay）
        for reaction in self._model.reactions:
            if not self._reaction_matches(reaction.trigger, eval_, result):
                continue
            self._apply_reaction(reaction.apply, eval_)

    @staticmethod
    def _reaction_matches(trigger: Dict[str, Any], eval_, result) -> bool:
        if "intent" in trigger and str(trigger["intent"]) != str(getattr(eval_, "intent", "")):
            return False
        if "outcome" in trigger and str(trigger["outcome"]) != str(getattr(result, "outcome", "")):
            return False
        return True

    def _apply_reaction(self, apply: Dict[str, Any], eval_) -> None:
        target_dim = str(apply.get("target") or "")
        if target_dim not in self._dims:
            return
        # 施加对象：本 agent 或动作目标 agent
        who = str(apply.get("to") or "self")
        target_agent = (
            getattr(eval_, "target_agent_id", None) if who == "target_agent"
            else eval_.agent_id
        )
        if not target_agent:
            return
        # delta：常量 delta，或从评价字段取值（delta_from）
        if "delta_from" in apply:
            raw = float(getattr(eval_, str(apply["delta_from"]), 0.0) or 0.0)
            cap = apply.get("cap")
            delta = min(float(cap), raw) if cap is not None else raw
        else:
            delta = float(apply.get("delta", 0.0))
        if delta <= 0:
            return
        # 按目标维度 kind 施加
        kind = self._dims[target_dim].kind
        if kind == "reactive":
            self.signal_counterplay(target_agent, delta)
        elif kind == "accumulator":
            self.accumulate_risk(target_agent, delta)
        elif kind == "gauge":
            self.update_information_scope(target_agent, delta)

    # ── 外部计算接口（供 Validation / Budget 调用，返回结构不变）───────────

    def compute_validation_modifiers(self, agent_id: str) -> Dict[str, Any]:
        s = self._s(agent_id)
        mods: Dict[str, Any] = {
            "allow_physics": True,
            "force_multiplier": 1.0,
            "risk_multiplier": 1.0,
            "reasons": [],
            "warnings": [],
        }
        for dim in self._model.dimensions:
            v = s.get(dim.id, 0.0)
            if dim.kind == "budget":
                cap = dim.max if dim.max is not None else 1.0
                if v <= 0:
                    mods["allow_physics"] = False
                    mods["reasons"].append(f"{dim.id}_exhausted")
                    return mods
                if v < cap * 0.3:
                    ratio = max(0.5, v / (cap * 0.3))
                    mods["force_multiplier"] *= ratio
                    mods["warnings"].append(f"{dim.id}_low:{v:.1f}/{cap:.1f}")
            elif dim.kind == "pool":
                if v < 10.0:
                    ratio = max(0.2, v / 30.0)
                    mods["force_multiplier"] *= ratio
                    mods["warnings"].append(f"{dim.id}_critical:{v:.1f}")
            elif dim.kind == "accumulator":
                thr = dim.threshold if dim.threshold is not None else 0.5
                if v > thr:
                    mods["risk_multiplier"] += round((v - thr) * 2.0, 4)
                    mods["warnings"].append(f"{dim.id}:{v:.3f}")
            elif dim.kind == "ramp":
                if v > 0.8:
                    mods["risk_multiplier"] += round((v - 0.8) * 1.5, 4)
                    mods["warnings"].append(f"{dim.id}:{v:.2f}")
            elif dim.kind == "reactive":
                if v > 0.3:
                    mods["force_multiplier"] *= round(1.0 - v * 0.3, 4)
                    mods["warnings"].append(f"{dim.id}:{v:.2f}")
        mods["force_multiplier"] = round(mods["force_multiplier"], 4)
        mods["risk_multiplier"] = round(mods["risk_multiplier"], 4)
        return mods

    def compute_budget_modifiers(self, agent_id: str) -> Dict[str, float]:
        s = self._s(agent_id)
        bonus = 0.0
        for dim_id in self._ids_of_kind("pool"):
            bonus = round(min(20.0, s.get(dim_id, 0.0) * 0.1), 2)
            break
        return {"resource_budget_bonus": bonus}

    # ── 内部工具 ─────────────────────────────────────────────────────────

    def _pressure_reasons(self, agent_id: str) -> List[str]:
        s = self._s(agent_id)
        reasons: List[str] = []
        for dim in self._model.dimensions:
            v = s.get(dim.id, 0.0)
            if dim.kind == "budget":
                cap = dim.max if dim.max is not None else 1.0
                if v <= 0:
                    reasons.append(f"{dim.id}_exhausted")
                elif v < cap * 0.3:
                    reasons.append(f"{dim.id}_low")
            elif dim.kind == "pool" and v < 20.0:
                reasons.append(f"{dim.id}_low")
            elif dim.kind == "accumulator":
                thr = dim.threshold if dim.threshold is not None else 0.5
                if v > thr:
                    reasons.append(f"{dim.id}_high:{v:.2f}")
            elif dim.kind == "ramp" and v > 0.7:
                reasons.append(f"{dim.id}:{v:.2f}")
            elif dim.kind == "reactive" and v > 0.5:
                reasons.append(f"{dim.id}:{v:.2f}")
        return reasons

    # ── 快照（运营台 / 审计 / brief）─────────────────────────────────────

    def snapshot(self) -> Dict[str, Any]:
        out: Dict[str, Any] = {}
        for aid, s in self._states.items():
            reasons = self._pressure_reasons(aid)
            entry: Dict[str, Any] = {
                dim.id: round(s.get(dim.id, 0.0), 4)
                for dim in self._model.dimensions
            }
            entry["is_under_pressure"] = bool(reasons)
            entry["pressure_reasons"] = reasons
            out[aid] = entry
        return out
