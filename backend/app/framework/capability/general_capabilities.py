"""
十大通用 LLM 能力注册表与测量状态（P0-1）

注意：本模块与 dimensions.py 中的「旧十维行为能力」是两套独立体系。
  - dimensions.py：策略 Agent 在场景规则下的行为信号（关键词/动作代理推断），后续降级为
    behavioral_signal，保留用于物理结算。
  - 本模块：用户定义的「十大通用 LLM 能力」，由真任务投递 → 模型作答 → 验证器判定的
    AssessmentCase 证据链直接测量，跨场景可比。

两者仅 reasoning / tool_use 名义重叠，但测量来源完全不同，不可混用。

设计原则（与产品双表现层对齐）：
  - 能力画像（本模块）≠ 世界胜负，≠ 场景专属策略能力。三套结果相互独立。
  - 测量状态显式区分「没测过」与「测过得分低」，杜绝 unmeasured 默认 50 分的假象。
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Dict, List, Optional


class VerificationTier(str, Enum):
    """三级验证可信度，由高到低。"""
    DETERMINISTIC = "deterministic"   # 一级：确定性对答案（代码测试/JSON/数学/事实/引用/权限）
    RUBRIC = "rubric"                 # 二级：Rubric 评分点（结构化半客观）
    BLIND_JUDGE = "blind_judge"       # 三级：盲评 LLM 裁判（隐藏身份+固定 rubric）


class MeasurementStatus(str, Enum):
    """单个模型在单项能力上的测量状态。"""
    UNMEASURED = "unmeasured"       # 尚未投递任何有效任务——不给分
    INSUFFICIENT = "insufficient"   # 样本不足——低置信度临时估计
    MEASURED = "measured"           # 达到最小有效样本——分数+置信度
    INVALIDATED = "invalidated"     # 本次测量被暗面破坏污染——作废重测，归因到破坏者


class CapabilityAxis(str, Enum):
    """能力轴向：常规测量 / 暗面攻防的攻侧 / 守侧。"""
    NEUTRAL = "neutral"   # 常规正向能力测量
    OFFENSE = "offense"   # 攻：制造或利用对抗性信息
    DEFENSE = "defense"   # 守：识别污染输入和越权诱导


@dataclass(frozen=True)
class GeneralCapability:
    """一项通用 LLM 能力的定义。"""
    cid: str                          # 稳定标识符（写入 AssessmentCase.capability）
    label: str                        # 中文标签（展示用）
    description: str                  # 含义说明
    primary_tier: VerificationTier    # 主验证方式
    min_trials: int = 3               # 进入 measured 所需的最小有效样本


# ── 十大通用能力注册表 ────────────────────────────────────────────────────────
# cid 必须稳定，不可随意改名——它是 AssessmentCase 跨场景聚合的主键。

GENERAL_CAPABILITIES: List[GeneralCapability] = [
    GeneralCapability(
        cid="language_understanding",
        label="语言理解",
        description="准确理解自然语言文本的含义、指代、歧义与言外之意。",
        primary_tier=VerificationTier.DETERMINISTIC,
    ),
    GeneralCapability(
        cid="knowledge",
        label="知识问答",
        description="基于事实知识作答，含引用核实与防幻觉。",
        primary_tier=VerificationTier.DETERMINISTIC,
    ),
    GeneralCapability(
        cid="reasoning",
        label="推理",
        description="多步逻辑推演、因果与反事实推断、从矛盾证据中得出正确结论。",
        primary_tier=VerificationTier.DETERMINISTIC,
    ),
    GeneralCapability(
        cid="coding",
        label="Coding",
        description="编写可运行、通过测试的代码（由 OS 真实运行核验）。",
        primary_tier=VerificationTier.DETERMINISTIC,
    ),
    GeneralCapability(
        cid="instruction_following",
        label="指令遵循",
        description="严格遵守约束、格式与边界条件，不擅自越界或漏项。",
        primary_tier=VerificationTier.DETERMINISTIC,
    ),
    GeneralCapability(
        cid="long_context",
        label="长上下文",
        description="在大量材料中定位、整合并使用分散于上下文的关键信息。",
        primary_tier=VerificationTier.DETERMINISTIC,
    ),
    GeneralCapability(
        cid="writing",
        label="写作表达",
        description="生成结构清晰、表达得体、有说服力的文本。",
        primary_tier=VerificationTier.BLIND_JUDGE,  # 唯一真正需要裁判的能力
    ),
    GeneralCapability(
        cid="multimodal",
        label="多模态",
        description="解析图像/印信/布防图等非文本材料并据此作答。",
        primary_tier=VerificationTier.DETERMINISTIC,
    ),
    GeneralCapability(
        cid="tool_use",
        label="工具调用",
        description="正确选择并调用工具、组装参数、利用返回结果完成任务。",
        primary_tier=VerificationTier.DETERMINISTIC,
    ),
    GeneralCapability(
        cid="safety",
        label="安全稳健",
        description="抵抗注入和越权诱导，识别污染输入并保持稳定。",
        primary_tier=VerificationTier.DETERMINISTIC,
    ),
]

CAPABILITY_MAP: Dict[str, GeneralCapability] = {c.cid: c for c in GENERAL_CAPABILITIES}

CAPABILITY_IDS: List[str] = [c.cid for c in GENERAL_CAPABILITIES]


def get_capability(cid: str) -> Optional[GeneralCapability]:
    """按 cid 取能力定义；未知 cid 返回 None。"""
    return CAPABILITY_MAP.get(cid)


def is_general_capability(cid: str) -> bool:
    """判定一个标识符是否属于十大通用能力（用于隔离旧行为维度）。"""
    return cid in CAPABILITY_MAP


def resolve_status(effective_n: float, min_trials: int, invalidated: bool = False) -> MeasurementStatus:
    """
    根据有效样本量推导测量状态（纯函数，不依赖具体评分）。

    invalidated 优先级最高：只要本能力当前有效证据被暗面污染且尚未补测达标，即判 INVALIDATED。
    """
    if invalidated:
        return MeasurementStatus.INVALIDATED
    if effective_n <= 0:
        return MeasurementStatus.UNMEASURED
    if effective_n < min_trials:
        return MeasurementStatus.INSUFFICIENT
    return MeasurementStatus.MEASURED
