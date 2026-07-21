"""
核心接口契约（Core Interfaces）

这里定义的数据结构是四层框架之间的契约。
任何层的实现都不能破坏这些接口——场景包、Provider、Director 全部遵守。
"""
from __future__ import annotations

from typing import Any, Dict, List, Literal, Optional
from pydantic import BaseModel, Field
import time

from app.contracts.world_adapter import (
    WorldAdapterActionReceipt,
    WorldAdapterTransition,
)


# ---------------------------------------------------------------------------
# 层1 ↔ 层2：Agent Contract
# ---------------------------------------------------------------------------

class ActionOption(BaseModel):
    """世界告知 Agent 本回合可以做什么（有界行动空间）"""
    id: str
    name: str
    description: str
    requires_target: bool = False   # 是否需要指定目标
    allows_code: bool = False        # 是否可以附带工具代码
    target_kind: str = ""            # object / location / agent / evidence / ...


class PerceptionPack(BaseModel):
    """世界 → Agent：本回合 Agent 的完整感知（每人一份，互相隔离）"""
    tick: int
    agent_id: str
    scenario_name: str
    # 场景自定义字段：由场景包定义，框架透传
    perception: Dict[str, Any] = Field(default_factory=dict)
    available_actions: List[ActionOption] = Field(default_factory=list)
    # 记忆摘要：由框架维护，防止 context 爆炸
    memory_summary: str = ""
    # P0 底座协议扩展
    self_location: Optional[str] = None               # P0-1 当前位置
    reachable_locations: List[str] = Field(default_factory=list)  # P0-1 可达地点
    visible_agents: List[str] = Field(default_factory=list)       # P0-4 可见 Agent


class ActionPack(BaseModel):
    """Agent → 世界：Agent 本回合的决定（P0 结构化扩展）"""
    agent_id: str
    action_id: str
    target_agent_id: Optional[str] = None
    text: str = ""                   # 对外发言 / 方略内容（P0 兼容兜底）
    thought: str = ""                # 旧协议兼容字段；不得直接进入观众端
    character_monologue: str = ""    # 角色第一人称短独白（观众可见，不是原始思维链）
    public_reasoning_summary: str = ""  # 可公开的策略理由摘要（导演/审计使用）
    code: Optional[str] = None       # 工具代码（仅当 action.allows_code=True）
    submitted_at: float = Field(default_factory=time.time)
    # ruleworld 2.0
    target_object_id: Optional[str] = None       # 作用于哪个世界对象
    linked_evidence_ids: List[str] = Field(default_factory=list)  # 告密/举报引用的证据 id
    # ── P0 结构化行动扩展 ──
    intent: Optional[str] = None                 # investigate / improve / negotiate / defend / attack / use_tool / wait
    action_name: Optional[str] = None            # 用户可读行动名称
    plan: Optional[str] = None                   # 策略说明（P5 导演演绎素材）
    resource_commitment: Optional[float] = None  # 资源投入强度 [0.0, 1.0]
    risk_control: Optional[float] = None         # 风险控制强度 [0.0, 1.0]
    evidence_refs: List[str] = Field(default_factory=list)   # 本回合使用的证据引用
    tool_request: Optional[Dict[str, Any]] = None           # 工具请求 {tool_id, purpose}
    parameters: Dict[str, Any] = Field(default_factory=dict) # 场景动作参数，由 World Kernel 校验
    expected_effect: Optional[str] = None        # 模型预期效果
    backup_plan: Optional[str] = None            # 失败备选计划
    parsed_ok: bool = True                      # P0 解析是否成功
    parse_errors: List[str] = Field(default_factory=list)  # 解析错误列表
    raw_model_output: Optional[str] = None       # 模型原始返回（用于复盘）
    attached_tool_id: Optional[str] = None        # 本回合附带的工具 id
    declared_intent: str = ""                     # 公开意图声明（供导演/对手解读）
    category: Optional[str] = None                 # 动作语义类别（来自 action rule，供导演区分叙述）
    # 系统因 LLM 失败/超时报注入的待命动作（与 agent 主动选等待区分）
    is_system_fallback: bool = False
    # 私人备忘：只回流给该 agent 自己的下一拍（多步计划/伏笔/暗中判断）。
    # 不进公开事件流、不给裁判、不给对手、不给导演——agent 第一次拥有
    # "只有自己知道的想法"的存储权，跨拍策略连贯性由此生长。
    note_to_self: Optional[str] = None


# ---------------------------------------------------------------------------
# P0 Agent Briefing
# ---------------------------------------------------------------------------

class AgentBrief(BaseModel):
    """P0 为每个 Agent 每回合生成的决策简报"""
    agent_id: str
    tick: int
    identity: Dict[str, Any] = Field(default_factory=dict)        # 身份信息
    goal: Dict[str, Any] = Field(default_factory=dict)            # 终局目标
    rule_summary: List[str] = Field(default_factory=list)         # 规则摘要（自然语言）
    ranking: List[Dict[str, Any]] = Field(default_factory=list)   # 当前排名
    self_state: Dict[str, Any] = Field(default_factory=dict)      # 自身状态
    others_summary: List[Dict[str, Any]] = Field(default_factory=list)  # 对手摘要
    visible_objects: List[Dict[str, Any]] = Field(default_factory=list) # 可见世界对象
    available_actions: List[Dict[str, Any]] = Field(default_factory=list) # 可选行动
    available_tools: List[Dict[str, Any]] = Field(default_factory=list)   # 可用工具
    pressure_state: Dict[str, Any] = Field(default_factory=dict)  # 压力状态
    recent_events: List[Dict[str, Any]] = Field(default_factory=list)     # 近期事件
    output_contract: Dict[str, Any] = Field(default_factory=dict) # 输出格式要求
    raw_context: Dict[str, Any] = Field(default_factory=dict)     # 原始上下文（备用）
    hidden_info_exclusions: List[str] = Field(default_factory=list)  # L2 感知隔离：被过滤掉的不可见信息字段
    # P0 底座协议扩展
    self_location: Optional[str] = None                                  # P0-1 当前位置
    reachable_locations: List[Dict[str, Any]] = Field(default_factory=list)  # P0-1 可达地点+成本
    available_resources: Dict[str, float] = Field(default_factory=dict)  # P0-2 可用资源
    cooldown_status: Dict[str, int] = Field(default_factory=dict)        # P0-2 冷却状态
    risk_hints: List[str] = Field(default_factory=list)                  # P0-1/P0-4 风险提示
    known_evidence: List[str] = Field(default_factory=list)              # P1-2/P1-4 已知证据
    pending_proposals: List[Dict[str, Any]] = Field(default_factory=list) # 针对本 agent 的待回应互动提议
    location_locked_actions: List[Dict[str, Any]] = Field(default_factory=list)  # 因 same_location 约束被隐藏的行动（需移动到同地点才能解锁）
    measurement_opportunities: List[Dict[str, Any]] = Field(
        default_factory=list
    )  # 通用测评机会提示；内容完全由场景包声明


# ---------------------------------------------------------------------------
# 层1 → 层3：事件流（导演全知）
# ---------------------------------------------------------------------------

class RuntimeSignal(BaseModel):
    """Ephemeral engine signal; never authoritative for settlement or presentation."""
    tick: int
    event_type: str          # ally / betray / artifact_deploy / task_complete / eliminate …
    source_id: Optional[str] = None
    target_id: Optional[str] = None
    is_public: bool = True   # False = 秘密事件，不出现在其他 Agent 的感知里
    summary: str = ""        # 人类可读描述（导演/运营台显示用）
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# Tool / Artifact：Agent 部署的运行中代码实体
# "Artifact" 为旧接口名，保留兼容；新代码统一用 Tool 概念。
# ---------------------------------------------------------------------------

class Artifact(BaseModel):
    artifact_id: str
    owner_id: str
    name: str
    description: str
    code: str
    artifact_type: str       # surveillance / counter / trap / algorithm / shield
    is_active: bool = True
    tick_created: int
    last_triggered_tick: Optional[int] = None
    trigger_count: int = 0
    # 非空时 execute_artifacts 每 tick 从 agent 工作区 code/ 重载源码
    workspace_path: Optional[str] = None
    # 渲染层展示用
    visual_type: str = "orb"
    visual_color: str = "#00ff88"


# ---------------------------------------------------------------------------
# 运营台日志（Operator-only）
# ---------------------------------------------------------------------------

class AgentLog(BaseModel):
    """每回合每个 Agent 的完整链路日志，仅运营台可见"""
    tick: int
    agent_id: str
    provider: str
    model: str
    perception_pack: PerceptionPack
    raw_llm_response: str = ""
    action_pack: Optional[ActionPack] = None
    duration_ms: int = 0
    tokens_used: int = 0
    error: Optional[str] = None
    # OS 2.0 dual-write record. Kept as JSON here so the legacy log contract
    # does not become the owner of the versioned HarnessTrace model.
    harness_trace: Optional[Dict[str, Any]] = None


# ---------------------------------------------------------------------------
# 世界快照：每 tick 广播给渲染层
# ---------------------------------------------------------------------------

class AgentSnapshot(BaseModel):
    """单个 Agent 的公开快照（渲染层用）"""
    agent_id: str
    name: str
    color: str
    is_alive: bool = True
    # 场景自定义的公开属性
    public_attrs: Dict[str, Any] = Field(default_factory=dict)
    character_monologue: str = ""  # 契约化角色独白；旧回放缺失时不做回退
    public_reasoning_summary: str = ""  # 可公开的投资策略/思维链摘要（与独白分离）
    last_thought: str = ""    # 旧快照兼容字段，观众端不再读取
    speech: str = ""          # 本回合公开发言（仅说话当回合非空，前端渲染头顶气泡，几秒后淡出）


class WorldSnapshot(BaseModel):
    """渲染层收到的世界状态快照（公开信息，无秘密）"""
    tick: int
    is_running: bool
    is_game_over: bool = False
    winner_id: Optional[str] = None
    agents: List[AgentSnapshot] = Field(default_factory=list)
    artifacts: List[Artifact] = Field(default_factory=list)
    recent_public_events: List[RuntimeSignal] = Field(default_factory=list)
    # 公开世界对象（规则世界的公开状态，含 core_state 与子因子；具体对象由场景包定义）
    world_objects: List[Dict[str, Any]] = Field(default_factory=list)
    # 场景自定义的全局公开状态
    scene_state: Dict[str, Any] = Field(default_factory=dict)
    # Agent 位置映射（agent_id → location_id），供前端渲染 agent 移动
    agent_locations: Dict[str, str] = Field(default_factory=dict)
    # Agent 指标数据（agent_id → {metric_name: value}），供前端展示目标进展
    agent_metrics: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    # 指标来源分解（agent_id → {source: {metric_name: value}}），供前端三色堆叠条
    # 淘汰名单（按出局先后有序），供前端渲染场景声明的退出状态。
    eliminated: List[Dict[str, Any]] = Field(default_factory=list)
    # 终局胜负溯源（game_over 后填充）：每人优势来源与致命伤的可读文本
    victory_attribution: List[Dict[str, Any]] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# 规则世界证据链：六本账本（开放规则场景设计范式 v1.0）
#
# 铁律：人物指标必须从世界对象状态变化派生，每一次变化都要可回溯。
# 这些模型是通用的——账本里装什么对象/指标由场景包定义，框架只负责记账。
# ---------------------------------------------------------------------------

class ActionLedgerEntry(BaseModel):
    """ActionLedger：每一次行动的原始记录与解析结果"""
    action_id: str
    tick: int
    actor_id: str
    action_type: str
    target_object_id: Optional[str] = None
    target_agent_id: Optional[str] = None
    raw_text: str = ""
    parsed_plan: Dict[str, Any] = Field(default_factory=dict)  # 裁判解析出的结构化方案
    execution_quality: float = 0.0                              # 裁判给出的执行质量 [0,1]
    legality: str = "ok"
    result_event_ids: List[str] = Field(default_factory=list)


class StateDeltaEntry(BaseModel):
    """StateDeltaLedger：世界对象状态变化（指标派生的唯一合法来源）"""
    delta_id: str
    tick: int
    object_id: str
    core_state: str                                   # 如 severity
    before_core: float
    after_core: float
    factor_deltas: Dict[str, float] = Field(default_factory=dict)  # 子因子变化量
    cause_chain: str = ""                             # 人类可读的因果说明
    execution_quality: float = 0.0
    linked_action_id: Optional[str] = None
    actor_id: Optional[str] = None
    # ruleworld 2.0 新增
    before_factors: Dict[str, float] = Field(default_factory=dict)  # 变化前各子因子值
    after_factors: Dict[str, float] = Field(default_factory=dict)   # 变化后各子因子值
    cause_chain_ids: List[str] = Field(default_factory=list)        # 因果链 id 列表
    # P1.5 新增：物理计算元数据（outcome / match_score 等）
    metadata: Dict[str, Any] = Field(default_factory=dict)


class MetricDerivationEntry(BaseModel):
    """MetricDerivationLedger：人物指标如何从 StateDelta 派生而来"""
    metric_update_id: str
    tick: int
    agent_id: str
    metric_name: str
    delta: float
    source_object_id: Optional[str] = None
    source_delta_id: Optional[str] = None
    derivation_rule: str = ""                         # 触发的派生规则描述
    reason: str = ""
    # ruleworld 2.0 新增
    source_evidence_id: Optional[str] = None
    source_tool_impact_id: Optional[str] = None
    before_value: float = 0.0
    after_value: float = 0.0


class ToolLedgerEntry(BaseModel):
    """ToolLedger：模型自主开发的工具（Phase 2 充实，先占位以固定契约）"""
    tool_id: str
    owner_id: str
    name: str = ""
    purpose: str = ""
    run_count: int = 0
    net_value: float = 0.0
    status: str = "active"


class ToolRunResult(BaseModel):
    """工具运行结果（ruleworld 2.0 新增）"""
    run_id: str
    tool_id: str
    owner_id: str
    tick: int
    ok: bool
    outputs: List[Dict[str, Any]] = Field(default_factory=list)   # 结构化输出
    evidence_created: List[str] = Field(default_factory=list)     # 产生的 evidence_id（沙盒声称的字符串 id，兼容旧接口）
    evidence_candidate_ids: List[str] = Field(default_factory=list)  # 标准化 EvidenceEntry id（由 EvidenceService 生成）
    trace_delta: float = 0.0                                       # 痕迹代价
    errors: List[str] = Field(default_factory=list)
    events: List[RuntimeSignal] = Field(default_factory=list)     # 非权威运行信号
    net_value: float = 0.0                                        # 净价值（引擎结算后填写）
    source: str = "sandbox"                                       # sandbox / mcp
    duration_ms: Optional[float] = None                           # MCP 等外部调用耗时
    mcp_server_id: Optional[str] = None                           # MCP 服务端标识
    mcp_tool_name: Optional[str] = None                           # MCP 工具名


class EvidenceEntry(BaseModel):
    """EvidenceLedger：行动/工具产生的证据（完整版）"""
    evidence_id: str
    created_by: str
    target_id: Optional[str] = None
    claim: str = ""
    # 来源
    source_action_id: Optional[str] = None
    source_tool_id: Optional[str] = None
    supporting_event_ids: List[str] = Field(default_factory=list)
    supporting_object_states: Dict[str, Any] = Field(default_factory=dict)
    # 生命周期
    verification_status: str = "unverified"  # verified/weak/contradicted/expired/unverified_hypothesis
    used_by_actions: List[str] = Field(default_factory=list)
    impact_score: float = 0.0
    confidence: float = 0.5
    tick_created: int = 0
    # P1-4 证据可见性
    visibility: str = "private"                          # public / private / restricted
    visible_to_agents: List[str] = Field(default_factory=list)  # 可见 Agent 列表（空=仅创建者）
    expires_tick: Optional[int] = None                   # 过期 tick（None=永不过期）


class ActionStateTransition(BaseModel):
    """动作通过前置校验后，由 L4 规划的通用平台状态变化。"""
    agent_id: str
    action_id: str
    resource_cost: Dict[str, float] = Field(default_factory=dict)
    cooldown_ticks: int = 0
    location_from: Optional[str] = None
    location_to: Optional[str] = None


class TickTransactionRecord(BaseModel):
    """单个 Tick 的事务记录，用于审计、回放和失败恢复。"""
    tick: int
    status: Literal["planned", "committed", "rolled_back"] = "planned"
    transitions: List[ActionStateTransition] = Field(default_factory=list)
    resource_delta_ids: List[str] = Field(default_factory=list)
    errors: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# P1 因果物理闭环：ActionEvaluation → StateDeltaProposal → CausalSequence
# ---------------------------------------------------------------------------

class ActionEvaluation(BaseModel):
    """
    ActionEvaluator 的输出：把 ActionPack 解析成可计算的行动评价。
    LLM 或启发式均可生成此结构，但不得直接包含指标加分。
    """
    evaluation_id: str
    tick: int
    agent_id: str
    action_id: str

    # 行动目标
    target_object_id: Optional[str] = None
    target_agent_id: Optional[str] = None

    # 行动意图（通用抽象，不绑定场景）
    intent: Literal[
        "improve", "reduce", "attack", "defend", "investigate",
        "build", "repair", "negotiate", "optimize", "wait", "unknown"
    ] = "unknown"

    # 行动力向量：通用维度，数值为 0~100 的强度
    force_vector: Dict[str, float] = Field(default_factory=dict)

    # 行动质量参数（0~1）
    clarity: float = 0.5           # 行动是否具体可执行
    commitment: float = 0.5        # 投入程度
    execution_quality: float = 0.5 # 执行质量
    risk_control: float = 0.5      # 风险控制意识
    # 局面契合度（0~1，None=裁判未评）：这一步在当前局势下是否高明。
    # 评分函数看得见局面，"读懂局势的临场妙手"才能拿到高于通用模板的回报。
    situational_fit: Optional[float] = None

    # 成本与风险估计
    estimated_cost: float = 0.0
    risk_level: float = 0.0
    trace_level: float = 0.0       # 行动可见度/留痕程度

    # 可解释信息
    rationale: str = ""
    weaknesses: List[str] = Field(default_factory=list)
    raw_action_text: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)


class StateDeltaProposal(BaseModel):
    """
    CausalPhysicsEngine 的输出：行动评价作用于世界对象后的状态变化建议。
    不直接修改对象，必须经 StateDeltaService.apply_proposal() 落账。
    """
    proposal_id: str
    tick: int

    source_action_id: str
    source_evaluation_id: str
    actor_id: str
    object_id: str

    factor_deltas: Dict[str, float] = Field(default_factory=dict)
    core_delta: float = 0.0

    # 物理计算中间值（用于审计和可视化）
    effective_impact: float = 0.0
    match_score: float = 0.0
    resistance_loss: float = 0.0
    risk_side_effect: float = 0.0
    resource_penalty: float = 0.0

    explanation: str = ""
    metadata: Dict[str, Any] = Field(default_factory=dict)

    # P1.5 新增：结算结果
    outcome: Literal["positive", "no_effect", "negative", "invalid"] = "positive"
    no_effect_reason: Optional[str] = None
    backlash: bool = False
    backlash_reason: Optional[str] = None


class CausalSequenceStep(BaseModel):
    """因果链中的单步记录"""
    kind: str   # action / action_evaluation / state_delta / metric_delta / evidence / tool
    ref_id: str
    title: str = ""
    summary: str = ""
    actor_id: Optional[str] = None
    target_id: Optional[str] = None
    object_id: Optional[str] = None
    metric: Optional[str] = None
    delta: Optional[float] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class CausalSequence(BaseModel):
    """
    一次行动的完整因果链：
    action → evaluation → state_delta → metric_delta
    供导演层、解说层、前端可视化消费；只引用账本中真实存在的记录。
    """
    sequence_id: str
    tick: int
    source_action_id: str
    actor_id: str
    steps: List[CausalSequenceStep] = Field(default_factory=list)
    summary: str = ""
    importance: float = 0.0
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# P1.5 闸门与预算协议
# ---------------------------------------------------------------------------

class ActionValidationResult(BaseModel):
    """ActionValidityGate 的输出：行动进入物理结算前的合法性校验结果"""
    validation_id: str
    tick: int
    agent_id: str
    action_id: str
    evaluation_id: Optional[str] = None

    valid: bool = True
    status: Literal["valid", "invalid", "warning", "allowed_but_penalized"] = "valid"

    reasons: List[str] = Field(default_factory=list)
    warnings: List[str] = Field(default_factory=list)

    # 惩罚系数（乘进 physics 计算）
    force_multiplier: float = 1.0   # < 1 = 降低行动力
    risk_multiplier: float = 1.0    # > 1 = 放大风险
    resource_penalty: float = 0.0

    # 是否允许继续进入物理结算
    allow_physics: bool = True

    metadata: Dict[str, Any] = Field(default_factory=dict)


class ForceBudgetResult(BaseModel):
    """ForceBudgetCalculator 的输出：预算计算及 force_vector 压缩结果"""
    budget_id: str
    tick: int
    agent_id: str
    action_id: str
    evaluation_id: str

    original_force_total: float
    force_budget: float
    scaled: bool = False
    scale_ratio: float = 1.0

    budget_sources: Dict[str, float] = Field(default_factory=dict)
    adjusted_force_vector: Dict[str, float] = Field(default_factory=dict)

    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# P2 压力引擎：Agent 六维压力状态
# ---------------------------------------------------------------------------

class AgentPressureState(BaseModel):
    """
    单个 Agent 的运行时压力状态（P2 新增）。

    六个维度：
      action_points      行动点（每 tick 有上限，行动消耗，tick 末恢复）
      resources          资源池（投入型，消耗后慢慢恢复）
      risk_accumulation  累积风险（高风险行动叠加，自然衰减；超阈值放大副作用）
      information_scope  信息域 [0,1]（调查行动提升，被干扰/封锁降低）
      deadline_pressure  截止压力 [0,1]（随 tick 推进自动增长）
      counterplay_level  对手反制强度 [0,1]（本 tick 来袭，下 tick 重置）
    """
    agent_id: str
    tick: int = 0

    # 行动点
    action_points: float = 10.0
    action_points_max: float = 10.0
    action_points_regen: float = 3.0       # 每 tick 恢复量

    # 资源
    resources: float = 100.0
    resources_max: float = 200.0
    resources_regen: float = 10.0          # 每 tick 恢复量

    # 风险累积
    risk_accumulation: float = 0.0
    risk_decay_rate: float = 0.15          # 每 tick 乘以 (1 - decay_rate) 衰减
    risk_threshold: float = 0.5            # 超阈值后 risk_multiplier 放大

    # 信息域 [0, 1]
    information_scope: float = 0.8

    # 截止压力 [0, 1]
    deadline_pressure: float = 0.0
    deadline_tick: Optional[int] = None    # None = 无截止

    # 对手反制 [0, 1]
    counterplay_level: float = 0.0

    # 综合压力标记
    is_under_pressure: bool = False
    pressure_reasons: List[str] = Field(default_factory=list)


class CausalPipelineResult(BaseModel):
    """run_causal_pipeline 的完整返回结果（P1.5 升级自 tuple）"""
    tick: int
    action_id: str
    agent_id: str

    evaluation: Optional[ActionEvaluation] = None
    validation: Optional[ActionValidationResult] = None
    budget: Optional[ForceBudgetResult] = None
    proposal: Optional[StateDeltaProposal] = None

    deltas: List[StateDeltaEntry] = Field(default_factory=list)
    metrics: List[MetricDerivationEntry] = Field(default_factory=list)
    sequence: Optional[CausalSequence] = None

    outcome: Literal["success", "invalid", "no_effect", "backlash", "error"] = "success"
    errors: List[str] = Field(default_factory=list)

    # 原始动作保留用于可追溯世界事实转换。
    action: Optional[ActionPack] = None

    # 外部可执行世界的权威回执。RuleWorld 旧路径保持为 None；外部适配器
    # 必须返回结构化 transition，OS 不根据 LLM 文本猜测世界变化。
    world_action_receipt: Optional[WorldAdapterActionReceipt] = None
    world_transition: Optional[WorldAdapterTransition] = None


# ---------------------------------------------------------------------------
# 测评机会漏斗协议（B：考题/剧情节点系统用）
# 注：原 P4「十维行为能力评分」协议（CapabilityEvidenceRef /
# CapabilityObservation / BehaviorCapabilityScore / AgentBehaviorCapabilityReport）
# 已随行为打分引擎删除。
# ---------------------------------------------------------------------------

class MeasurementOpportunityRecord(BaseModel):
    """一次测评机会漏斗记录，不代表能力得分。"""
    opportunity_id: str
    tick: int
    agent_id: str
    capability: str
    eligible_action_ids: List[str] = Field(default_factory=list)
    eligible_tool_ids: List[str] = Field(default_factory=list)
    disclosed: bool = False
    offered: bool = False
    selected: bool = False
    attempted: bool = False
    signal_produced: bool = False
    selected_action_id: Optional[str] = None
    selected_tool_id: Optional[str] = None
    outcome: Optional[str] = None
    signal_count: int = 0
    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# P6 运行记录协议
# ---------------------------------------------------------------------------

class RunMeta(BaseModel):
    """Run 的元信息，冻结运行配置快照。"""
    run_id: str
    started_at: str
    ended_at: Optional[str] = None

    engine_version: str = "0.6.0"
    scenario_id: str = ""
    scenario_version: str = ""
    random_seed: Optional[int] = None

    agent_models: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    framework_config_snapshot: Dict[str, Any] = Field(default_factory=dict)
    scenario_config_snapshot: Dict[str, Any] = Field(default_factory=dict)

    metadata: Dict[str, Any] = Field(default_factory=dict)


# ---------------------------------------------------------------------------
# P0 底座协议：地图 / 资源 / 权限 / 前置校验
# ---------------------------------------------------------------------------

class LocationConfig(BaseModel):
    """P0-1 地点配置（场景包 world/locations.yaml）"""
    location_id: str
    name: str
    type: str = "public"                                  # public / private / restricted
    connected_to: List[str] = Field(default_factory=list)
    travel_cost: Dict[str, float] = Field(default_factory=dict)  # {resource_id: cost}
    risk_level: str = "low"                               # low / medium / high
    visible_objects: List[str] = Field(default_factory=list)
    available_actions: List[str] = Field(default_factory=list)
    available_tools: List[str] = Field(default_factory=list)
    permissions_required: List[str] = Field(default_factory=list)
    causal_modifiers: Dict[str, float] = Field(default_factory=dict)
    render_binding: str = ""


class ResourceConfig(BaseModel):
    """P0-2 资源配置（场景包 world/resources.yaml）"""
    resource_id: str
    name: str
    owner_type: str = "agent"                             # agent / global
    initial: float = 0
    min: float = 0
    max: float = 100
    refresh_per_tick: float = 0


class ResourceState(BaseModel):
    """P0-2 Agent 资源运行时状态"""
    agent_id: str
    resource_id: str
    current: float
    max: float
    min: float


class ResourceDelta(BaseModel):
    """P0-2 资源变化记录"""
    delta_id: str
    tick: int
    agent_id: str
    resource_id: str
    before: float
    after: float
    reason: str = ""
    source_action_id: Optional[str] = None


class CooldownState(BaseModel):
    """P0-2 冷却状态"""
    agent_id: str
    entity_id: str
    entity_type: str                                      # action / tool / location
    remaining_ticks: int


class PermissionGrant(BaseModel):
    """P0-3 权限授予记录"""
    agent_id: str
    permission_id: str
    source: str = "role"                                  # role / event / temporary
    tick_granted: int = 0


class ActionPreconditionResult(BaseModel):
    """P0-5 动作前置校验结果"""
    valid: bool
    status: str                                           # valid / invalid / warning
    reason_code: str = ""
    reason_detail: str = ""
    action_id: str
    agent_id: str
    resource_sufficient: bool = True
    cooldown_allowed: bool = True
    location_allowed: bool = True
    permission_allowed: bool = True
    target_accessible: bool = True


# ---------------------------------------------------------------------------
# P1 扩展协议：事件 / 记忆 / 关系 / 回放
# ---------------------------------------------------------------------------

class ScheduledEvent(BaseModel):
    """P1-1 延迟事件"""
    event_id: str
    tick_created: int
    tick_due: int
    event_type: str                                       # delayed_effect / conditional / timed
    source_action_id: Optional[str] = None
    target_object_id: Optional[str] = None
    target_agent_id: Optional[str] = None
    payload: Dict[str, Any] = Field(default_factory=dict)
    status: str = "pending"                               # pending / triggered / cancelled / expired


class KnowledgeEntry(BaseModel):
    """P1-2 Agent 已知信息条目"""
    agent_id: str
    entity_type: str                                      # object / agent / event / evidence
    entity_id: str
    known_since_tick: int
    last_seen_tick: int
    confidence: float = 1.0
    stale: bool = False
    content: Dict[str, Any] = Field(default_factory=dict)


class RelationshipState(BaseModel):
    """P1-3 Agent 间关系状态"""
    source_agent_id: str
    target_agent_id: str
    relation_type: str                                    # trust / hostility / cooperation / influence / dependency / reputation
    value: float = 0.0
    visibility: str = "private"                           # public / private / restricted
    last_updated_tick: int = 0
    source_delta_id: Optional[str] = None


class RunSeed(BaseModel):
    """P1-5 可复现回放种子"""
    run_id: str
    seed: int
    scenario_version: str
    initial_state_hash: str = ""
    decisions: List[Dict[str, Any]] = Field(default_factory=list)
