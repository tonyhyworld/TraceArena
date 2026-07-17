"""压力 / Agent 状态模型契约（P1 契约层，纯新增，尚未接线）。

对应 docs/OS层与场景包边界约定.md 第 5 节 + 第 9 节技术债 #3：
**压力维度归场景声明，OS 的 PressureEngine 只是通用状态机执行器。**

现状问题：PressureEngine 把六个维度（action_points/resources/
risk_accumulation/information_scope/deadline_pressure/counterplay_level）
和 `attack→counterplay` 反应写死在 Python 里——这是特定对抗博弈场景的
内容。场景只能调参，加不了/减不了维度。

本契约把维度与反应提升为 world/pressure.yaml 的声明：
  dimensions: 每个维度声明 initial/max/regen/decay/threshold 及如何调制力/风险
  reactions:  声明"什么触发 → 对哪个维度施加什么"（取代硬编码 attack→counterplay）

P1 只定义契约 + 加载器：
  - 新版 pressure.yaml（含 dimensions:）→ 解析为结构化 PressureModel。
  - 旧版扁平参数 / 无 pressure.yaml → 返回 None，调用方回退到现有
    PressureEngine 默认行为，保证零回归。
P2 才让 PressureEngine 按声明执行。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml

# 维度如何调制行动结果（OS 通用语义，场景在 effects 里引用）：
#   force_multiplier_down  数值低时降低行动力
#   risk_multiplier_up     数值超阈时放大风险/反噬
#   block_action           数值耗尽时直接拒绝行动
ModulationKind = str  # 通用调制类型名，见上


@dataclass(frozen=True)
class DimensionEffect:
    """维度在某条件下如何调制行动。"""

    # 触发条件：low | over_threshold | exhausted | high
    when: str
    apply: ModulationKind
    # 可选强度/参数（如 {ratio_floor: 0.5}）；OS 按 apply 类型解释。
    params: Dict[str, Any] = field(default_factory=dict)


# 维度的通用行为原语（OS 只认识这几种 kind，不认识任何具体维度名）：
#   budget      预算型：每回合恢复，行动消耗；低→降力，耗尽→拒绝行动
#   pool        资源池：恢复/消耗；低→降力；供预算加成
#   accumulator 累积型：叠加、自然衰减；超阈值→放大风险
#   gauge       量表：[0,1] 由行动增减
#   ramp        斜坡：随 tick/deadline 线性增长到 1；高→放大风险
#   reactive    反应型：被 reaction 触发抬升、每回合衰减；高→降力
DimensionKind = str


@dataclass(frozen=True)
class PressureDimension:
    """一个场景声明的压力维度。"""

    id: str
    kind: DimensionKind = "accumulator"
    initial: float = 0.0
    max: Optional[float] = None
    regen: float = 0.0        # 每回合恢复
    decay: float = 0.0        # 每回合自然衰减比例（0~1）
    threshold: Optional[float] = None
    effects: List[DimensionEffect] = field(default_factory=list)
    description: str = ""


@dataclass(frozen=True)
class PressureReaction:
    """事件触发的压力反应（取代硬编码 attack→counterplay）。

    trigger 与 apply 都是通用 dict，语义由场景声明、OS 按通用规则执行：
      trigger 例: {intent: attack}  或 {outcome: backlash}
      apply   例: {target: counterplay_level, delta: 0.3, to: target_agent}
    """

    trigger: Dict[str, Any]
    apply: Dict[str, Any]


@dataclass(frozen=True)
class PressureModel:
    dimensions: List[PressureDimension] = field(default_factory=list)
    reactions: List[PressureReaction] = field(default_factory=list)


def load_pressure_model(scenario_dir: str | Path) -> Optional[PressureModel]:
    """加载声明式压力模型。

    返回 None 表示"场景未用新版声明"——调用方应回退到现有 PressureEngine
    行为，保证零回归。只有 pressure.yaml 显式含 `dimensions:` 才解析新版。
    """
    path = Path(scenario_dir) / "world" / "pressure.yaml"
    if not path.is_file():
        return None
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data = raw.get("pressure", raw) if isinstance(raw, dict) else {}
    if not isinstance(data, dict) or "dimensions" not in data:
        # 旧版扁平参数：不识别为新模型，让调用方走旧路径。
        return None

    dimensions = [
        PressureDimension(
            id=str(item.get("id") or ""),
            kind=str(item.get("kind") or "accumulator"),
            initial=float(item.get("initial", 0.0)),
            max=(float(item["max"]) if item.get("max") is not None else None),
            regen=float(item.get("regen", 0.0)),
            decay=float(item.get("decay", 0.0)),
            threshold=(
                float(item["threshold"]) if item.get("threshold") is not None else None
            ),
            effects=[
                DimensionEffect(
                    when=str(eff.get("when") or ""),
                    apply=str(eff.get("apply") or ""),
                    params=dict(eff.get("params") or {}),
                )
                for eff in (item.get("effects") or [])
                if isinstance(eff, dict)
            ],
            description=str(item.get("description") or ""),
        )
        for item in data.get("dimensions", [])
        if isinstance(item, dict) and item.get("id")
    ]
    reactions = [
        PressureReaction(
            trigger=dict(item.get("trigger") or {}),
            apply=dict(item.get("apply") or {}),
        )
        for item in (data.get("reactions") or [])
        if isinstance(item, dict) and item.get("trigger") and item.get("apply")
    ]
    return PressureModel(dimensions=dimensions, reactions=reactions)


# OS 附带的**默认压力模型**（数据，不是硬编码逻辑）。
# 它是一套通用的竞技世界压力原语，不含任何场景专有名词；场景不声明
# world/pressure.yaml 的 dimensions 时回退到它（可用扁平参数覆盖各维度参数）。
# 场景要"完全不同"的压力模型，声明自己的 dimensions/reactions 即可。
DEFAULT_PRESSURE_MODEL = PressureModel(
    dimensions=[
        PressureDimension(id="action_points", kind="budget", initial=10.0, max=10.0, regen=3.0),
        PressureDimension(id="resources", kind="pool", initial=100.0, max=200.0, regen=2.0),
        PressureDimension(id="risk_accumulation", kind="accumulator", decay=0.15, threshold=0.5),
        PressureDimension(id="information_scope", kind="gauge", initial=0.8, max=1.0),
        PressureDimension(id="deadline_pressure", kind="ramp"),
        PressureDimension(id="counterplay_level", kind="reactive", max=1.0, decay=0.5),
    ],
    reactions=[
        # attack 意图 → 对目标发出反制信号（原硬编码，现为声明式默认反应）。
        PressureReaction(
            trigger={"intent": "attack"},
            apply={"target": "counterplay_level", "to": "target_agent",
                   "delta_from": "risk_level", "cap": 0.5},
        ),
    ],
)

# 扁平参数键 → (维度 id, 维度属性) 的映射，用于把旧版扁平 pressure.yaml 的
# 调参覆盖到默认模型对应维度上，保证既有场景零行为变化。
_FLAT_PARAM_OVERRIDES = {
    "action_points_max": ("action_points", "max"),
    "action_points_initial": ("action_points", "initial"),
    "action_points_regen": ("action_points", "regen"),
    "resources_initial": ("resources", "initial"),
    "resources_max": ("resources", "max"),
    "resources_regen": ("resources", "regen"),
    "risk_decay_rate": ("risk_accumulation", "decay"),
    "risk_threshold": ("risk_accumulation", "threshold"),
    "information_scope_initial": ("information_scope", "initial"),
    "counterplay_decay": ("counterplay_level", "decay"),
}


def resolve_pressure_model(
    scenario_dir: str | Path,
    flat_cfg: Optional[Dict[str, Any]] = None,
) -> PressureModel:
    """返回场景生效的压力模型。

    优先用 world/pressure.yaml 声明的 dimensions（场景完全自定义）；
    未声明时回退到 DEFAULT_PRESSURE_MODEL，并用扁平参数（旧版 pressure.yaml）
    覆盖对应维度参数——用旧版扁平 pressure.yaml 的既有场景由此零行为变化。
    """
    declared = load_pressure_model(scenario_dir)
    if declared is not None and declared.dimensions:
        return declared

    cfg = dict(flat_cfg or {})
    overrides: Dict[str, Dict[str, float]] = {}
    for key, (dim_id, attr) in _FLAT_PARAM_OVERRIDES.items():
        if key in cfg and cfg[key] is not None:
            overrides.setdefault(dim_id, {})[attr] = float(cfg[key])
    dims = [
        (
            PressureDimension(
                id=dim.id, kind=dim.kind,
                initial=overrides.get(dim.id, {}).get("initial", dim.initial),
                max=overrides.get(dim.id, {}).get("max", dim.max),
                regen=overrides.get(dim.id, {}).get("regen", dim.regen),
                decay=overrides.get(dim.id, {}).get("decay", dim.decay),
                threshold=overrides.get(dim.id, {}).get("threshold", dim.threshold),
                effects=dim.effects, description=dim.description,
            )
            if dim.id in overrides else dim
        )
        for dim in DEFAULT_PRESSURE_MODEL.dimensions
    ]
    return PressureModel(dimensions=dims, reactions=DEFAULT_PRESSURE_MODEL.reactions)


def model_from_pressure_cfg(cfg: Optional[Dict[str, Any]]) -> PressureModel:
    """从已加载的 pressure_cfg（world/pressure.yaml 的 pressure 块）构建模型。

    声明了 dimensions → 用场景自定义模型；否则 → 默认模型 + 扁平参数覆盖。
    供 RuleWorldContext 直接使用（无需再读盘）。
    """
    data = dict(cfg or {})
    if data.get("dimensions"):
        model = _parse_declared(data)
        if model.dimensions:
            return model
    return resolve_pressure_model(Path("."), data)


def _parse_declared(data: Dict[str, Any]) -> PressureModel:
    """把含 dimensions 的 dict 解析为 PressureModel（与 load_pressure_model 一致）。"""
    dimensions = [
        PressureDimension(
            id=str(item.get("id") or ""),
            kind=str(item.get("kind") or "accumulator"),
            initial=float(item.get("initial", 0.0)),
            max=(float(item["max"]) if item.get("max") is not None else None),
            regen=float(item.get("regen", 0.0)),
            decay=float(item.get("decay", 0.0)),
            threshold=(
                float(item["threshold"]) if item.get("threshold") is not None else None
            ),
            effects=[
                DimensionEffect(
                    when=str(eff.get("when") or ""),
                    apply=str(eff.get("apply") or ""),
                    params=dict(eff.get("params") or {}),
                )
                for eff in (item.get("effects") or [])
                if isinstance(eff, dict)
            ],
            description=str(item.get("description") or ""),
        )
        for item in data.get("dimensions", [])
        if isinstance(item, dict) and item.get("id")
    ]
    reactions = [
        PressureReaction(
            trigger=dict(item.get("trigger") or {}),
            apply=dict(item.get("apply") or {}),
        )
        for item in (data.get("reactions") or [])
        if isinstance(item, dict) and item.get("trigger") and item.get("apply")
    ]
    return PressureModel(dimensions=dimensions, reactions=reactions)
