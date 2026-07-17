"""
CapabilityProbe / AssessmentCase 核心协议（P0-2）

这是十大通用能力测评的事实底座。一次完整测量的证据链：

    触发 → 模型输入(Probe) → 原始输出(ProbeResponse) → 工具调用
         → 验证(VerificationResult) → 世界后果 → 不可变案例(AssessmentCase)

设计要求：
  - 全通用：同一套结构覆盖十项能力、任意角色、攻/守两轴、三级验证。
  - 不可变追加：所有结构 frozen，案例一旦提交不可改；纠错靠追加新案例，不靠原地修改。
  - invalidated 归因：破坏导致的失败必须可区分、可重测、可归因到破坏者。
  - 隐藏答案分离：下发给模型的 Probe 不含 ground truth 明文，只留 ground_truth_ref。

本协议刻意独立于 interfaces.py 中的旧行为能力结构（CapabilityObservation 等）——
那是「策略行为信号」体系，本协议是「通用能力测评」体系，两套结果不可混淆。
"""
from __future__ import annotations

import time
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, ConfigDict, Field

from app.framework.capability.general_capabilities import (
    CapabilityAxis,
    MeasurementStatus,
    VerificationTier,
)


class _Frozen(BaseModel):
    """不可变基类：提交后不可原地修改（追加式）。"""
    model_config = ConfigDict(frozen=True)


# ---------------------------------------------------------------------------
# 1. 触发 → 模型输入
# ---------------------------------------------------------------------------

class CapabilityProbe(_Frozen):
    """
    一次能力探针：OS 在某个 Agent 触碰挑战对象时发起的专用 LLM 子调用任务。

    关键：ground_truth 不放入本结构下发给模型，只保留 ground_truth_ref 指向隐藏答案库。
    """
    probe_id: str
    tick: int
    agent_id: str                      # 被测角色/模型
    capability: str                    # 十大能力 cid
    node_id: str                       # 剧情节点
    variant_id: str = ""               # 等价变体 id（防串题/防记忆作弊）
    axis: CapabilityAxis = CapabilityAxis.NEUTRAL
    expected_tier: VerificationTier = VerificationTier.DETERMINISTIC

    instruction: str = ""              # 任务说明（下发给模型）
    materials: Dict[str, Any] = Field(default_factory=dict)   # 任务材料（长文/图/账册等）
    output_schema: Dict[str, Any] = Field(default_factory=dict)  # 要求的结构化输出形态
    available_tool_ids: List[str] = Field(default_factory=list)

    ground_truth_ref: str = ""         # 隐藏答案引用（绝不下发明文）
    created_at: float = Field(default_factory=time.time)


# ---------------------------------------------------------------------------
# 2. 原始输出 + 工具调用
# ---------------------------------------------------------------------------

class ProbeToolCall(_Frozen):
    """模型在探针子回合内的一次工具调用记录。"""
    tool_id: str
    arguments: Dict[str, Any] = Field(default_factory=dict)
    result_ref: str = ""               # 工具返回结果的账本引用
    ok: bool = True
    result: Dict[str, Any] = Field(default_factory=dict)  # 工具真实返回，供复核与二次作答


class ProbeResponse(_Frozen):
    """模型对探针的作答（原始 + 结构化），保留全部原始痕迹。"""
    probe_id: str
    agent_id: str
    raw_output: str = ""               # 模型原始输出（含 <think> 等）
    structured_answer: Dict[str, Any] = Field(default_factory=dict)
    tool_calls: List[ProbeToolCall] = Field(default_factory=list)
    error: Optional[str] = None        # 子回合失败（超时/解析失败）时填写
    received_at: float = Field(default_factory=time.time)


# ---------------------------------------------------------------------------
# 3. 验证判定
# ---------------------------------------------------------------------------

class RubricPoint(_Frozen):
    """二级验证的单个评分点。"""
    key: str
    description: str = ""
    weight: float = 1.0
    awarded: float = 0.0               # 实际得分 [0, weight]


class VerificationResult(_Frozen):
    """验证器对一次作答的判定结果。"""
    probe_id: str
    capability: str
    tier_used: VerificationTier
    verifier_id: str                   # 验证器标识（确定性器/rubric器/盲评裁判 id）
    passed: bool = False
    score: float = 0.0                 # 归一化 [0, 1]
    rubric: List[RubricPoint] = Field(default_factory=list)
    rationale: str = ""
    evidence_refs: List[str] = Field(default_factory=list)   # 支撑判定的账本引用
    blind: bool = False                # 是否对裁判隐藏了被测身份


# ---------------------------------------------------------------------------
# 4. 破坏归因（暗面）
# ---------------------------------------------------------------------------

class InvalidationInfo(_Frozen):
    """
    一次测量被暗面破坏污染时的作废与归因信息。

    用于区分两种失败：
      - A 失败因为 A 弱  → 有效证据，不需要本结构
      - A 失败因为 B 搞破坏 → 作废本案例并填写本结构，把破坏归因给 B
    """
    reason: str                        # 对抗性干预方式
    saboteur_agent_id: str             # 破坏者
    sabotage_case_id: str = ""         # 破坏者攻击侧的 AssessmentCase id
    corrupted_input_ref: str = ""      # 被污染的输入材料引用
    retest_case_id: str = ""           # 补测产生的新案例 id（重测后回填）


# ---------------------------------------------------------------------------
# 5. 不可变案例（证据链原子）
# ---------------------------------------------------------------------------

class AssessmentCase(_Frozen):
    """
    一次能力测量的完整、不可变证据链记录——B 端可审计的最小单元。

    一个 case 串起：Probe(输入) + ProbeResponse(原始输出+工具) + VerificationResult(验证)
    + world_effect_ref(世界后果) + 可选 invalidation(破坏归因)。

    status 语义：
      MEASURED      → 有效证据，计入聚合评分。
      INSUFFICIENT  → 有效但单点信息量低（如部分得分），计入但权重看 score。
      INVALIDATED   → 被污染作废，不计入被测者评分；破坏归因到 saboteur。
    """
    case_id: str
    tick: int
    agent_id: str                      # 被测角色/模型
    capability: str                    # 十大能力 cid
    node_id: str
    variant_id: str = ""
    axis: CapabilityAxis = CapabilityAxis.NEUTRAL

    status: MeasurementStatus = MeasurementStatus.MEASURED
    tier_used: VerificationTier = VerificationTier.DETERMINISTIC
    score: float = 0.0                 # 归一化 [0, 1]
    weight: float = 1.0                # 难度/信息量权重

    probe: CapabilityProbe
    response: ProbeResponse
    verification: VerificationResult

    world_effect_ref: str = ""         # 世界后果事件 id（原子事务中同版本提交）
    invalidation: Optional[InvalidationInfo] = None

    created_at: float = Field(default_factory=time.time)

    @property
    def counts_for_subject(self) -> bool:
        """本案例是否计入被测者的能力评分（被作废的不计）。"""
        return self.status != MeasurementStatus.INVALIDATED


__all__ = [
    "CapabilityProbe",
    "ProbeToolCall",
    "ProbeResponse",
    "RubricPoint",
    "VerificationResult",
    "InvalidationInfo",
    "AssessmentCase",
]
