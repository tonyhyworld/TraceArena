"""结算类型注册表（P1 契约层，纯新增，尚未接线）。

对应 docs/OS层与场景包边界约定.md 第 4 节：
**OS 层不存在通用评价体系，只认识 4 个结算类型 ID，按类型执行；
具体输赢由场景包在 evaluation/plugin.py 约定。**

本模块把"4 类结算"从散落的 Literal + if 分支，正规化成一张
显式注册表：每个 `settlement_type_id` 声明"OS 负责什么、场景负责什么、
authority 必须满足什么"。P2 会让路由层按 ID 查执行器，取代当前
RuleWorldContext 把物理引擎当默认的写法。

设计原则：
  - `simulation` 的内置物理引擎只是**一个可选参考实现**
    （provider_id = builtin:ruleworld_physics），不是 OS 默认评价体系。
  - 任何新增结算类型必须先在本表登记；OS 用 ID 查执行器，不得场景分流。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Callable, Dict, List, Optional

from app.contracts.os2 import SettlementMode

# OS 附带的内置参考 provider（不是场景内容；是通用可复用机制）。
# 场景必须**显式声明** provider_id 才使用它——OS 不假设"模拟=必然用它"。
BUILTIN_RULEWORLD_PHYSICS = "builtin:ruleworld_physics"


@dataclass(frozen=True)
class SettlementTypeSpec:
    """一个结算类型的边界契约声明。"""

    type_id: SettlementMode
    label: str
    summary: str
    # OS 层为这一类型提供的通用能力（加载/调度/记录/追溯/校验）。
    os_provides: List[str]
    # 场景包必须提供的东西（结果的含义与公式）。
    scenario_provides: List[str]
    # authority 必须满足的硬约束（与 contracts.os2.SettlementAuthority 校验一致）。
    authority_requirements: List[str]
    # 是否允许使用 OS 内置参考 provider。
    allows_builtin_provider: bool = False
    builtin_provider_id: Optional[str] = None


SETTLEMENT_TYPES: Dict[str, SettlementTypeSpec] = {
    "simulation": SettlementTypeSpec(
        type_id="simulation",
        label="模拟世界结算",
        summary=(
            "现实没有标准答案，由 OS/场景规则充当世界物理引擎。"
            "适合权谋博弈、狼人杀、公司经营、城市治理、外交博弈。"
        ),
        os_provides=[
            "调度与记录",
            "可选内置物理引擎 builtin:ruleworld_physics（场景显式选用）",
        ],
        scenario_provides=[
            "是否使用内置物理引擎，或自写模拟规则 provider",
            "对象需求/敏感度/抗性等物理参数（world/objects.yaml）",
            "胜负公式（settlement victory policy）",
        ],
        authority_requirements=["provider_id", "rule_version"],
        allows_builtin_provider=True,
        builtin_provider_id=BUILTIN_RULEWORLD_PHYSICS,
    ),
    "external_reality": SettlementTypeSpec(
        type_id="external_reality",
        label="外部现实结算",
        summary=(
            "结果来自外部真实世界，OS 不编造结果，只调用真实数据/工具并记录。"
            "适合股票、天气、网页任务、真实工具结果。"
        ),
        os_provides=[
            "外部观测的接入、验证、ExternalObservation 落账",
            "provenance 校验（来源/hash/freshness/verification_status）",
        ],
        scenario_provides=[
            "如何把已验证观测映射成结算结果",
            "引用哪些 observation_refs",
        ],
        authority_requirements=["provider_id", "rule_version", "observation_refs"],
    ),
    "deterministic_verifier": SettlementTypeSpec(
        type_id="deterministic_verifier",
        label="确定性校验结算",
        summary=(
            "有客观标准答案或可执行判定器，不需要 LLM 参与裁判。"
            "适合考题判卷、代码测试、数学答案、格式/订单校验。"
        ),
        os_provides=["调度确定性校验器、记录、可复现性保证"],
        scenario_provides=["校验器本身（判卷/订单校验/pytest 判定等）"],
        authority_requirements=["provider_id", "rule_version", "verifier_id", "deterministic"],
    ),
    "hybrid": SettlementTypeSpec(
        type_id="hybrid",
        label="混合结算",
        summary=(
            "一部分来自现实、一部分由场景规则加工。"
            "例：投资模拟中行情来自现实，买卖/现金/收益率由场景账本模拟。"
        ),
        os_provides=["组合多类权威、authority 校验（≥2 个非 hybrid 子模式）"],
        scenario_provides=["哪部分来自现实、哪部分场景加工、如何合成结果"],
        authority_requirements=["provider_id", "rule_version", "component_modes(≥2)"],
    ),
}


# ── 内置参考 provider 注册表 ─────────────────────────────────────────────
# key = provider_id，value = 构造函数（P2 接线时填入 RuleWorld 物理引擎工厂）。
# 现在为空占位，仅提供登记入口，保证"内置引擎是被注册的一个实现，而非默认"。
_BUILTIN_PROVIDER_FACTORIES: Dict[str, Callable[..., object]] = {}


def register_builtin_provider(provider_id: str, factory: Callable[..., object]) -> None:
    """登记一个 OS 内置参考 provider（如 builtin:ruleworld_physics）。"""
    _BUILTIN_PROVIDER_FACTORIES[provider_id] = factory


def get_builtin_provider_factory(provider_id: str) -> Optional[Callable[..., object]]:
    return _BUILTIN_PROVIDER_FACTORIES.get(provider_id)


def is_valid_settlement_type(type_id: str) -> bool:
    return type_id in SETTLEMENT_TYPES


def get_settlement_type(type_id: str) -> SettlementTypeSpec:
    spec = SETTLEMENT_TYPES.get(type_id)
    if spec is None:
        raise ValueError(
            f"未知结算类型: {type_id}；合法类型: {sorted(SETTLEMENT_TYPES)}"
        )
    return spec
