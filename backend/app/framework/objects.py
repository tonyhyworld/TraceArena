"""
通用世界对象运行时（规则世界的承重墙）

设计范式铁律：人物指标不得直接 +X，必须从世界对象的子因子变化派生。
本模块只提供「装任意对象」的通用容器——具体有哪些对象、子因子、需求结构，
全部由场景包的 world/objects.yaml 声明，框架不认识具体场景内容。

对象模型（P1 升级后）：
  core_value = Σ 子因子 × 权重
  needs_weights：行动维度 → 权重 float（供 CausalPhysicsEngine 计算 match_score）
  needs_factors：行动维度 → 影响的子因子列表（可选，供旧版分配逻辑使用）
  resistance / sensitivity / inertia / risk：物理参数（0~1）
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional


class WorldObjectRuntime:
    """单个世界对象的运行时状态（从配置实例化）。"""

    def __init__(self, cfg: Dict[str, Any]):
        self.id: str = cfg["id"]
        self.type: str = cfg.get("type", "generic")
        self.label: str = cfg.get("name", cfg.get("label", self.id))
        self.core_state: str = cfg.get("core_state", "severity")
        self.public: bool = bool(cfg.get("public", True))
        self.initial_core: Optional[float] = cfg.get("initial_core")
        self.location: Optional[str] = cfg.get("location")
        self.visibility_config: Dict[str, Any] = (
            dict(cfg.get("visibility", {}))
            if isinstance(cfg.get("visibility"), dict)
            else {"default": cfg.get("visibility", "visible")}
        )
        self.permissions_required: List[str] = list(
            cfg.get("permissions_required", []) or []
        )

        factors = cfg.get("factors", {}) or {}
        # 子因子当前值 + 权重
        # 兼容两种格式：
        #   dict 格式：{stability: {value: 0.5, weight: 0.25}}
        #   float 格式：{stability: 0.5}  → 权重均分（1/n）
        self.factors: Dict[str, float] = {
            k: float(v.get("value", 0) if isinstance(v, dict) else v)
            for k, v in factors.items()
        }
        inferred_unit_scale = bool(self.factors) and all(
            0.0 <= value <= 1.0 for value in self.factors.values()
        )
        self.factor_min: float = float(cfg.get("factor_min", 0.0))
        self.factor_max: float = float(
            cfg.get("factor_max", 1.0 if inferred_unit_scale else 100.0)
        )
        n_factors = len(self.factors) if self.factors else 0
        self.weights: Dict[str, float] = {
            k: float(v.get("weight", 0) if isinstance(v, dict) else (1.0 / n_factors if n_factors > 0 else 0))
            for k, v in factors.items()
        }

        # P1：needs 支持两种格式
        #   新格式（P1）：{"resource": 0.25, "information": 0.20, ...}  float 权重
        #   旧格式（legacy）：{"grain": ["food_shortage", "price_spike"]}  列表
        raw_needs = cfg.get("needs", {}) or {}
        self.needs_weights: Dict[str, float] = {}   # 用于 CausalPhysicsEngine 匹配
        self.needs_factors: Dict[str, List[str]] = {}  # 用于旧版因子分配

        for k, v in raw_needs.items():
            if isinstance(v, (int, float)):
                self.needs_weights[k] = float(v)
            elif isinstance(v, list):
                # 旧格式：等权重推断
                self.needs_factors[k] = list(v)
                self.needs_weights[k] = 1.0 / len(raw_needs) if raw_needs else 0.0
            else:
                self.needs_weights[k] = 0.0

        # 归一化 needs_weights（确保和为 1）
        total_w = sum(self.needs_weights.values())
        if total_w > 0:
            self.needs_weights = {k: v / total_w for k, v in self.needs_weights.items()}

        # P1：物理参数（缺省安全值）
        # resistance 可能是 float 或 {base, inertia, uncertainty, protection} dict
        _res = cfg.get("resistance", 0.5)
        if isinstance(_res, dict):
            _res = _res.get("base", 0.5)
        self.resistance: float = float(_res)   # 抵抗外部影响的程度
        # sensitivity 可能是 float 或 dict
        _sens = cfg.get("sensitivity", 0.5)
        if isinstance(_sens, dict):
            _sens = _sens.get("base", 0.5)
        self.sensitivity: float = float(_sens)  # 对有效行动的响应幅度
        _inertia = cfg.get("inertia", 0.2)
        if isinstance(_inertia, dict):
            _inertia = _inertia.get("base", 0.2)
        self.inertia: float = float(_inertia)         # 自然衰减/恢复倾向
        self.risk: float = float(cfg.get("risk", 0.2))               # 高风险行动的副作用放大系数
        self.visibility: str = str(cfg.get("visibility", "public"))  # public / hidden

        # P1：阈值（供胜负判断或触发事件用）
        thresholds = cfg.get("thresholds", {}) or {}
        self.thresholds: Dict[str, float] = {k: float(v) for k, v in thresholds.items()}

        # P1.5：intent 兼容性配置
        self.allowed_intents: Optional[List[str]] = cfg.get("allowed_intents")  # None = 全部允许
        self.disallowed_intents: List[str] = list(cfg.get("disallowed_intents", []) or [])
        # intent_effects: intent → {multiplier: float, backlash_risk: float}
        raw_ie = cfg.get("intent_effects", {}) or {}
        self.intent_effects: Dict[str, Dict] = {
            k: dict(v) if isinstance(v, dict) else {"multiplier": float(v)}
            for k, v in raw_ie.items()
        }

        # 向后兼容：旧代码读 .needs 的，仍能拿到 needs_weights
        self.needs = self.needs_weights

    def core_value(self) -> float:
        """core_state 由子因子加权计算，绝不允许被直接赋值。"""
        if not self.weights:
            # 没有子因子权重时，尝试 initial_core fallback
            if self.initial_core is not None:
                return round(float(self.initial_core), 2)
            # 尝试 factors["state"] 或 factors["core"]
            for key in ("state", "core"):
                if key in self.factors:
                    return round(self.factors[key], 2)
            # 有因子值但没有权重：返回平均值
            if self.factors:
                return round(sum(self.factors.values()) / len(self.factors), 2)
            return 0.0
        return round(sum(self.factors.get(f, 0) * w for f, w in self.weights.items()), 2)

    def snapshot_factors(self) -> Dict[str, float]:
        return {k: round(v, 3) for k, v in self.factors.items()}

    def get_intent_multiplier(self, intent: str) -> float:
        """
        返回指定 intent 对本对象的效果倍率。
        > 0：正向作用；< 0：反噬；= 0：完全无效。
        """
        if intent in self.intent_effects:
            return float(self.intent_effects[intent].get("multiplier", 1.0))
        # disallowed：默认无效（倍率 0）
        if intent in self.disallowed_intents:
            return 0.0
        # allowed_intents 声明了白名单：
        if self.allowed_intents is not None and intent not in self.allowed_intents:
            # unknown → 降权而不是完全拒绝（评价器识别失败不等于行动非法）
            if intent == "unknown":
                return 0.4
            return 0.0
        return 1.0

    def is_intent_allowed(self, intent: str) -> bool:
        """是否允许该 intent 对本对象施加正向影响（倍率 > 0）。"""
        return self.get_intent_multiplier(intent) > 0

    def public_view(self) -> Dict[str, Any]:
        """喂给感知包 / 渲染层的公开视图。"""
        return {
            "object_id": self.id,
            "name": self.label,
            "type": self.type,
            "core_state": self.core_state,
            "core_value": self.core_value(),
            "factors": self.snapshot_factors(),
            "needs": list(self.needs_weights.keys()),
            "location": self.location,
            "visibility": dict(self.visibility_config),
            "permissions_required": list(self.permissions_required),
        }
