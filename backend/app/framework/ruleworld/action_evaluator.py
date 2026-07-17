"""
ActionEvaluator：自然语言行动 → ActionEvaluation（P1 优先级最高）

P0 结构化字段优先；文本启发式兜底；actions.yaml 规则参与评价。
统一使用 10 维认知+行动能力体系。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
import time
from typing import Any, Dict, List, Optional

from app.core.interfaces import ActionEvaluation, ActionPack

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# P1 能力维度（10 维：5 认知 + 5 行动）
# ---------------------------------------------------------------------------

# ⚠️ 以下关键词启发式仅作 LLM Judge 完全不可用时的兜底估计。
# 正常链路的评分以 Judge 语义判断为准——关键词命中不构成任何得分捷径。
_DIMENSION_HINTS: List[tuple] = [
    # ── 认知能力 ──
    (r"目标|规则|胜负|正当性|排名|差距|局势", "understanding", 12.0),
    (r"上一回合|此前|之前|连续|已经|历史|上次|前几回合|上次行动", "memory", 12.0),
    (r"因为|所以|导致|原因|推断|判断|说明|影响|关键在于", "reasoning", 12.0),
    (r"先|再|随后|长期|阶段|铺垫|布局|终局|后续|计划|步骤", "planning", 12.0),
    (r"取舍|权衡|相比|不宜|优先|当前更适合|避免|选择", "judgment", 12.0),
    # ── 行动能力 ──
    (r"选择|决定|目标对象|针对|聚焦|优先处理|应该|应当", "selection", 12.0),
    (r"执行|推进|实施|部署|清查|整顿|落实|行动|完成|投入|调拨|建设|推进|改善|治理", "execution", 15.0),
    (r"风险|预防|规避|控制|缓冲|预案|备用|审慎|谨慎|降低风险|平衡", "risk_control", 15.0),
    (r"工具|检索|证据|分析工具|风险评估|调查|数据|核查|分析", "tool_use", 12.0),
    (r"修复|恢复|补救|弥补|止损|降低损失|挽回|善后|防御|保护|加固", "recovery", 12.0),
]

# 旧维度 → 新维度映射（兼容遗留代码）
LEGACY_DIMENSION_MAP = {
    "resource": "execution",
    "information": "tool_use",
    "coordination": "selection",
    "persuasion": "selection",
    "innovation": "planning",
    "defense": "recovery",
    "attack": "selection",
    "trust_building": "selection",
    "efficiency": "execution",
}

_QUALITY_HINTS = [
    (r"\d+[%％万元人]|\d+\s*(个|次|步|轮|天|小时)", 0.15, 0.10),
    (r"首先.+其次|第一.+第二|一方面.+另一方面",     0.12, 0.08),
    (r"目标.+方法|问题.+方案|原因.+措施",           0.10, 0.05),
    (r"同时|并且|此外|另外",                         0.05, 0.05),
]

_RISK_CONTROL_HINTS = [
    r"风险|预防|规避|缓冲|预案|备用|审慎|谨慎|降低风险|控制影响",
]

_RISK_LEVEL_HINTS = [
    (r"攻击|举报|揭发|对抗|施压|背叛|做空|狙击", 0.4),
    (r"激进|全力|孤注|赌上|冒险|强行",              0.3),
    (r"联合|合作|协作",                              0.1),
]

_INTENT_HINTS: List[tuple] = [
    ("improve",     r"改善|提升|优化|推进|推动|解决|治理|修复|建设|提高|改进|增强|整顿|办差"),
    ("investigate", r"调查|分析|核查|研究|评估|收集|判断|查证"),
    ("defend",      r"降低|减少|消除|削减|压缩|缩小|防御|保护|加固|防范|规避|抵御|稳住"),
    ("attack",      r"攻击|施压|举报|揭发|打击|削弱|强硬|强行|做空|狙击"),
    ("negotiate",   r"谈判|协商|达成|协议|磋商|协调|合作"),
    ("optimize",    r"工具|检索|调用|运行|代码|分析工具"),
    ("wait",        r"等待|观望|隐忍|蛰伏|按兵不动|暂避|休整"),
]

# 允许的有效意图值
_VALID_INTENTS = {
    "improve", "reduce", "attack", "defend", "investigate",
    "build", "repair", "negotiate", "optimize", "wait", "unknown"
}

# 自定义意图 → 标准意图的映射
_INTENT_NORMALIZE_MAP = {
    # defend 系列
    "defend_assets": "defend", "defend_position": "defend", "defend_reputation": "defend",
    "protect": "defend", "secure": "defend", "preserve": "defend", "maintain": "defend",
    "ensure_stability": "defend", "consolidate": "defend", "safeguard": "defend",
    "secure_resources": "defend", "maintain_influence": "defend",
    # investigate 系列
    "gather_intelligence": "investigate", "research": "investigate", "analyze": "investigate",
    "scout": "investigate", "explore": "investigate", "probe": "investigate",
    "assess": "investigate", "monitor": "investigate",
    # improve 系列
    "enhance": "improve", "strengthen": "improve", "develop": "improve",
    "upgrade": "improve", "boost": "improve", "secure_final_victory": "improve",
    "confirm_victory": "improve", "advance": "improve", "progress": "improve",
    # attack 系列
    "challenge": "attack", "undermine": "attack", "disrupt": "attack",
    "oppose": "attack", "counter": "attack", "retaliate": "attack",
    # negotiate 系列
    "ally": "negotiate", "cooperate": "negotiate", "diplomacy": "negotiate",
    "consolidate_alliance": "negotiate", "build_alliance": "negotiate",
    "partner": "negotiate", "mediate": "negotiate",
    # optimize 系列
    "use_tool": "optimize", "utilize": "optimize", "leverage": "optimize",
    "efficiency": "optimize", "streamline": "optimize",
    # build 系列
    "construct": "build", "create": "build", "establish": "build",
    "found": "build", "setup": "build",
    # repair 系列
    "fix": "repair", "restore": "repair", "recover": "repair", "remedy": "repair",
    "heal": "repair", "rebuild": "repair",
    # reduce 系列
    "reduce": "reduce", "decrease": "reduce", "minimize": "reduce",
    "shrink": "reduce", "cut": "reduce",
    # wait 系列
    "observe": "wait", "idle": "wait", "pause": "wait",
    "hold": "wait", "delay": "wait", "standby": "wait",
}

def _normalize_intent(raw_intent: Optional[str]) -> str:
    """将自定义意图归一化为标准意图"""
    if not raw_intent:
        return ""
    raw_lower = raw_intent.lower().strip()
    if raw_lower in _VALID_INTENTS:
        return raw_lower
    return _INTENT_NORMALIZE_MAP.get(raw_lower, "")

_VALID_DIMENSIONS = {
    "understanding", "memory", "reasoning", "planning", "judgment",
    "selection", "execution", "risk_control", "tool_use", "recovery",
}


# ---------------------------------------------------------------------------
# 启发式评价函数（P0 结构化优先 + 新维度）
# ---------------------------------------------------------------------------

def _heuristic_evaluate(action: ActionPack, tick: int, action_rule: Optional[Dict[str, Any]] = None) -> ActionEvaluation:
    """
    P1 评价：P0 结构化字段优先，文本启发式兜底。
    质量参数偏保守（不夸大评分）。
    """
    # ── 文本来源：优先 P0 结构化字段 ──
    text_parts = [
        action.action_name or "",
        action.plan or "",
        action.expected_effect or "",
        action.backup_plan or "",
        action.text or "",
        action.public_reasoning_summary or "",
    ]
    text = " ".join([p for p in text_parts if p])
    text_lower = text.lower()

    # ── 1. intent：结构化优先 + 归一化 ──
    intent = (
        _normalize_intent((action_rule or {}).get("intent"))
        or _normalize_intent(action.intent)
        or _normalize_intent(action.declared_intent)
    )
    if not intent:
        for intent_name, pattern in _INTENT_HINTS:
            if re.search(pattern, text):
                intent = intent_name
                break
    if not intent:
        intent = "unknown"

    # ── 2. commitment：结构化优先 ──
    if action.resource_commitment is not None:
        commitment = max(0.0, min(0.95, float(action.resource_commitment)))
    else:
        commitment = 0.35
        for pattern, _, m_add in _QUALITY_HINTS:
            if re.search(pattern, text):
                commitment = min(0.9, commitment + m_add)

    # ── 3. risk_control：结构化优先 ──
    if action.risk_control is not None:
        risk_control = max(0.0, min(0.95, float(action.risk_control)))
    else:
        risk_control = 0.35
        for pattern in _RISK_CONTROL_HINTS:
            if re.search(pattern, text):
                risk_control = min(0.85, risk_control + 0.2)
                break

    # ── 4. clarity ──
    # （仅作 Judge 不可用时的兜底估计；已删除字数奖励——写得长不等于写得清楚，
    # 原实现的 char_count/300 加分实测鼓励模型注水。）
    clarity = 0.35
    for pattern, c_add, _ in _QUALITY_HINTS:
        if re.search(pattern, text):
            clarity = min(0.9, clarity + c_add)

    # ── 5. force_vector（只使用 10 个新维度） ──
    force_vector: Dict[str, float] = {}
    for pattern, dim, strength in _DIMENSION_HINTS:
        if re.search(pattern, text):
            force_vector[dim] = force_vector.get(dim, 0.0) + strength

    # actions.yaml 的 suitable_needs 也参与 force_vector
    if action_rule:
        suitable = action_rule.get("suitable_needs", [])
        for dim in suitable:
            if dim in _VALID_DIMENSIONS:
                force_vector[dim] = force_vector.get(dim, 0.0) + 8.0 * commitment

    # 如果完全为空，给 intent 一个最低量
    if not force_vector:
        _defaults = {
            "improve": {"execution": 8.0, "planning": 5.0},
            "investigate": {"tool_use": 10.0, "reasoning": 5.0, "understanding": 5.0},
            "defend": {"risk_control": 10.0, "recovery": 5.0},
            "attack": {"selection": 10.0, "execution": 5.0},
            "negotiate": {"selection": 8.0, "judgment": 5.0},
            "optimize": {"tool_use": 10.0, "execution": 5.0},
            "build": {"execution": 8.0, "planning": 5.0},
            "repair": {"recovery": 10.0, "execution": 5.0},
            "reduce": {"execution": 5.0, "risk_control": 5.0},
            "wait": {"risk_control": 5.0},
        }
        force_vector = dict(_defaults.get(intent, {"execution": 5.0}))

    # 映射遗留维度（确保不出现旧维度名）
    mapped = {}
    for dim, val in force_vector.items():
        if dim in _VALID_DIMENSIONS:
            mapped[dim] = val
        elif dim in LEGACY_DIMENSION_MAP:
            new_dim = LEGACY_DIMENSION_MAP[dim]
            mapped[new_dim] = max(mapped.get(new_dim, 0.0), val)
        # otherwise drop silently
    force_vector = mapped

    # ── 6. risk_level ──
    risk_level = 0.15
    for pattern, add in _RISK_LEVEL_HINTS:
        if re.search(pattern, text):
            risk_level = min(0.9, risk_level + add)

    # ── 7. estimated_cost ──
    force_total = sum(force_vector.values())
    estimated_cost = min(100.0, force_total * 0.5)

    # ── 8. execution_quality ──
    execution_quality = (clarity + commitment) / 2.0

    # ── 9. metadata（保留 P0 结构化字段） ──
    metadata: Dict[str, Any] = {
        "action_name": action.action_name,
        "plan": action.plan,
        "expected_effect": action.expected_effect,
        "backup_plan": action.backup_plan,
        "parsed_ok": action.parsed_ok,
        "parse_errors": action.parse_errors,
        "resource_commitment": action.resource_commitment,
        "risk_control_input": action.risk_control,
        "evidence_refs": action.evidence_refs,
        "tool_request": action.tool_request,
        "raw_model_output": action.raw_model_output,
    }
    if action_rule:
        metadata["base_cost"] = action_rule.get("base_cost")
        metadata["base_risk"] = action_rule.get("base_risk")
        metadata["suitable_needs"] = action_rule.get("suitable_needs")

    eval_id = f"eval_{tick}_{action.agent_id}_{int(time.time() * 1000) % 10000:04d}"
    return ActionEvaluation(
        evaluation_id=eval_id,
        tick=tick,
        agent_id=action.agent_id,
        action_id=action.action_id,
        target_object_id=action.target_object_id,
        target_agent_id=action.target_agent_id,
        intent=intent,
        force_vector=force_vector,
        clarity=round(clarity, 3),
        commitment=round(commitment, 3),
        execution_quality=round(execution_quality, 3),
        risk_control=round(risk_control, 3),
        estimated_cost=round(estimated_cost, 1),
        risk_level=round(risk_level, 3),
        raw_action_text=text[:200],
        rationale="P1 启发式评价（P0 结构化优先）",
        metadata=metadata,
    )


# ---------------------------------------------------------------------------
# ActionEvaluator 主类
# ---------------------------------------------------------------------------

class ActionEvaluator:
    """P1：ActionPack → ActionEvaluation。优先 LLM Judge，失败则启发式兜底。"""

    def __init__(
        self,
        judge=None,
        config: Optional[Dict[str, Any]] = None,
        judge_timeout: float = 20.0,
        judge_temperature: float = 0.3,
        judge_max_tokens: int = 700,
    ):
        self._judge = judge
        self._config = config or {}
        self._actions_cfg: List[Dict[str, Any]] = self._config.get("actions_cfg", [])
        self._judge_timeout = judge_timeout
        self._judge_temperature = judge_temperature
        self._judge_max_tokens = judge_max_tokens

    def set_judge(self, judge, **opts) -> None:
        """运行时注入 LLM Judge provider（由引擎在构建 director_provider 后调用）。"""
        self._judge = judge
        if "timeout" in opts and opts["timeout"]:
            self._judge_timeout = float(opts["timeout"])
        if "temperature" in opts and opts["temperature"] is not None:
            self._judge_temperature = float(opts["temperature"])
        if "max_tokens" in opts and opts["max_tokens"]:
            self._judge_max_tokens = int(opts["max_tokens"])

    def get_action_rule(self, action_id: str) -> Dict[str, Any]:
        for a in self._actions_cfg:
            if a.get("id") == action_id:
                return a
        return {}

    async def evaluate(
        self,
        action: ActionPack,
        tick: int,
        state=None,
        objects=None,
        action_rule: Optional[Dict[str, Any]] = None,
    ) -> ActionEvaluation:
        """主入口。LLM Judge → 启发式 fallback。"""
        rule = action_rule or self.get_action_rule(
            action.action_id or action.intent or ""
        )
        # 启发式结果始终先算出来：作为 Judge 缺字段时的安全基线，也是 Judge 失败时的兜底。
        baseline = _heuristic_evaluate(action, tick, action_rule=rule)

        if self._judge is not None:
            try:
                situation = _build_situation_block(action, state, objects)
                result = await self._judge_evaluate(
                    action, tick, baseline, rule, situation=situation,
                )
                if result is not None:
                    return result
            except Exception as e:
                logger.warning(f"[Judge] tick={tick} agent={action.agent_id} 评价失败，降级启发式: {e}")

        return baseline

    # ------------------------------------------------------------------
    # LLM Judge 实现
    # ------------------------------------------------------------------

    async def _judge_evaluate(
        self,
        action: ActionPack,
        tick: int,
        baseline: ActionEvaluation,
        action_rule: Optional[Dict[str, Any]],
        situation: str = "",
    ) -> Optional[ActionEvaluation]:
        """调用中立 LLM 裁判，把自然语言行动评成能力向量+质量参数。

        - 以启发式 baseline 为底，Judge 仅覆盖其返回的合法字段（保证结构完整）。
        - 维度卫生：force_vector 只保留 10 个标准维度。
        - 超时/解析失败 → 抛异常由 evaluate() 兜底到 baseline。
        - situation：局面摘要（排名/目标对象状态/近期事件）。裁判看得见局面，
          才能区分"辞藻齐备的通用模板"和"切中此刻局势的临场妙手"。
        """
        system_prompt = _JUDGE_SYSTEM
        user_message = _build_judge_user_message(
            action, tick, action_rule, situation=situation,
        )

        raw = await asyncio.wait_for(
            self._judge.complete(
                system_prompt,
                user_message,
                temperature=self._judge_temperature,
                max_tokens=self._judge_max_tokens,
            ),
            timeout=self._judge_timeout,
        )

        data = _extract_json(raw)
        if not data:
            raise ValueError("Judge 未返回可解析 JSON")

        return _merge_judge_result(baseline, data, raw)


# ---------------------------------------------------------------------------
# Judge prompt + 解析
# ---------------------------------------------------------------------------

_JUDGE_SYSTEM = """你是「AI 竞技世界」的中立行动裁判（Judge），不参赛、不偏袒任何一方。
你的唯一职责：把一名智能体本回合的自然语言行动，客观评成可计算的能力向量与质量参数。

【10 个能力维度】（force_vector 的合法键，数值 0~100，表示该行动在此维度上施加的"力度"）
认知类：understanding(理解局势) memory(运用历史) reasoning(因果推理) planning(分阶段规划) judgment(权衡取舍)
行动类：selection(目标选择) execution(执行落地) risk_control(风险控制) tool_use(工具/证据运用) recovery(止损修复)
只为行动真正体现出的维度赋值；无关维度不要出现。一个普通行动通常只覆盖 1~4 个维度。

【5 个质量参数】（0.0~1.0）
clarity：行动是否具体、可执行、目标明确（空话/口号低，含具体对象+步骤+量化高）
commitment：投入程度（敷衍/观望低，押上资源/全力推进高）
execution_quality：综合执行质量（计划与目标的契合 + 可落地性）
risk_control：风险控制意识（鲁莽无备低，有预案/缓冲/退路高）
situational_fit：局面契合度——这一步放在【当前局面】下是否高明。
  评的是"此时此刻做这件事对不对"，不是"这段话写得好不好"：
  顺风时稳固战果、逆风时敢于变招、对手露出破绽时果断抓住 → 高；
  无视局面套通用模板、对着不相干的目标空耗、明显错过更优选择 → 低。
  未提供【当前局面】时省略此字段。

【其他】
risk_level：该行动本身的激进/暴露程度 0.0~1.0（攻击举报对抗类偏高）
intent：从 [improve, reduce, attack, defend, investigate, build, repair, negotiate, optimize, wait, unknown] 中选最贴切的一个
weaknesses：1~3 条该行动的薄弱点（可空）
rationale：一句话评分依据

【评分原则】
- 拉开区分度：优秀行动该高就高，敷衍行动该低就低，不要一律给中间值。
- 除 situational_fit 外，只依据行动文本与其声明评分；situational_fit 必须结合【当前局面】评。
- 辞藻堆砌不加分：关键词多不代表策略好，看的是内容是否切中要害。
- 严格输出 JSON，不要任何解释性文字、不要 markdown 代码块以外的内容。

输出格式（仅输出此 JSON）：
{
  "intent": "improve",
  "clarity": 0.0,
  "commitment": 0.0,
  "execution_quality": 0.0,
  "risk_control": 0.0,
  "situational_fit": 0.0,
  "risk_level": 0.0,
  "force_vector": {"execution": 0, "planning": 0},
  "weaknesses": [],
  "rationale": ""
}"""


def _build_situation_block(action: ActionPack, state: Any, objects: Any) -> str:
    """构造 ≤300 字局面摘要，供裁判评 situational_fit。全程防御式取值，
    任何字段缺失都静默跳过——局面摘要是增强项，不能反过来拖垮评价链路。"""
    parts: List[str] = []
    # 目标对象现状
    if objects is not None and action.target_object_id:
        try:
            obj = objects.get(action.target_object_id)
            frag = f"目标对象「{getattr(obj, 'name', obj.id)}」类型={obj.type}"
            core = getattr(obj, "core_value", None)
            if core is not None:
                frag += f"，当前核心值={float(core):.2f}"
            frag += f"，阻力={float(getattr(obj, 'resistance', 0.0)):.2f}"
            parts.append(frag)
        except Exception:
            pass
    if state is not None:
        loc = (getattr(state, "agent_locations", {}) or {}).get(action.agent_id)
        if loc:
            parts.append(f"行动者当前位置={loc}")
        res = (getattr(state, "resources", {}) or {}).get(action.agent_id) or {}
        if res:
            parts.append(
                "行动者资源: " + ", ".join(f"{k}={v}" for k, v in res.items())
            )
        # 最近公开事件（含行动者自己前几拍做了什么）
        try:
            events = list(getattr(state, "events", []) or [])
            recent = [e for e in events if getattr(e, "is_public", False)][-4:]
            for e in recent:
                summary = str(getattr(e, "summary", ""))[:60]
                if summary:
                    parts.append(f"近期公开事件[T{getattr(e, 'tick', '?')}]: {summary}")
        except Exception:
            pass
    return "\n".join(parts)[:600]


def _build_judge_user_message(
    action: ActionPack, tick: int, action_rule: Optional[Dict[str, Any]],
    situation: str = "",
) -> str:
    parts: List[str] = [f"回合 tick={tick}", f"智能体={action.agent_id}"]
    if situation:
        parts.append(f"【当前局面】\n{situation}")
    if action.action_name or action.action_id:
        parts.append(f"行动={action.action_name or action.action_id}")
    if action.declared_intent:
        parts.append(f"公开声明意图={action.declared_intent}")
    if action.target_object_id:
        parts.append(f"作用对象={action.target_object_id}")
    if action.target_agent_id:
        parts.append(f"目标对手={action.target_agent_id}")
    if action.plan:
        parts.append(f"策略说明：{action.plan}")
    if action.expected_effect:
        parts.append(f"预期效果：{action.expected_effect}")
    if action.backup_plan:
        parts.append(f"失败备选：{action.backup_plan}")
    if action.text:
        parts.append(f"对外发言/方略：{action.text}")
    if action.public_reasoning_summary:
        parts.append(f"公开策略依据：{action.public_reasoning_summary}")

    # 行动规则提示（让裁判知道该行动设计上适合哪些维度）
    if action_rule:
        suitable = action_rule.get("suitable_needs")
        if suitable:
            parts.append(f"（参考）该行动设计上适合的维度：{suitable}")
        if action_rule.get("description"):
            parts.append(f"（参考）行动定义：{action_rule.get('description')}")

    parts.append("请按系统要求输出 JSON 评价。")
    return "\n".join(parts)


def _extract_json(text: str) -> Dict[str, Any]:
    """从模型输出里提取第一个 JSON 对象，容忍 markdown 代码块包装。"""
    if not text:
        return {}
    # 剔除推理模型的 <think> 标签，避免其中的花括号干扰 JSON 匹配
    cleaned = re.sub(r"<think>.*?</think>", "", text, flags=re.DOTALL)
    cleaned = re.sub(r"```(?:json)?\s*", "", cleaned).replace("```", "")
    match = re.search(r"\{.*\}", cleaned, re.DOTALL)
    if not match:
        return {}
    try:
        result = json.loads(match.group())
        return result if isinstance(result, dict) else {}
    except json.JSONDecodeError:
        return {}


def _clamp01(value: Any, default: float) -> float:
    try:
        return max(0.0, min(1.0, float(value)))
    except (TypeError, ValueError):
        return default


def _merge_judge_result(
    baseline: ActionEvaluation, data: Dict[str, Any], raw: str
) -> ActionEvaluation:
    """以启发式 baseline 为底，用 Judge 返回的合法字段覆盖之。"""
    # 质量参数：缺失则保留 baseline
    clarity = _clamp01(data.get("clarity"), baseline.clarity)
    commitment = _clamp01(data.get("commitment"), baseline.commitment)
    risk_control = _clamp01(data.get("risk_control"), baseline.risk_control)
    risk_level = _clamp01(data.get("risk_level"), baseline.risk_level)
    execution_quality = _clamp01(
        data.get("execution_quality"), (clarity + commitment) / 2.0
    )

    # 局面契合度：Judge 未给（如无局面摘要）则保持 None，physics 会退回三项均值
    situational_fit = None
    if data.get("situational_fit") is not None:
        situational_fit = _clamp01(data.get("situational_fit"), 0.5)

    # intent 归一化
    intent = _normalize_intent(data.get("intent")) or baseline.intent

    # force_vector：维度卫生 + 区间约束（0~100）
    force_vector: Dict[str, float] = {}
    raw_fv = data.get("force_vector")
    if isinstance(raw_fv, dict):
        for dim, val in raw_fv.items():
            key = str(dim).strip()
            if key in LEGACY_DIMENSION_MAP:
                key = LEGACY_DIMENSION_MAP[key]
            if key not in _VALID_DIMENSIONS:
                continue
            try:
                num = max(0.0, min(100.0, float(val)))
            except (TypeError, ValueError):
                continue
            if num > 0:
                force_vector[key] = max(force_vector.get(key, 0.0), num)
    # Judge 没给出任何合法维度 → 回退 baseline 的 force_vector
    if not force_vector:
        force_vector = dict(baseline.force_vector)

    weaknesses = data.get("weaknesses")
    if not isinstance(weaknesses, list):
        weaknesses = []
    weaknesses = [str(w)[:120] for w in weaknesses][:3]

    rationale = str(data.get("rationale") or "LLM Judge 评价")[:200]

    estimated_cost = min(100.0, sum(force_vector.values()) * 0.5)

    metadata = dict(baseline.metadata)
    metadata["evaluator"] = "llm_judge"
    metadata["judge_raw"] = raw[:500]

    return ActionEvaluation(
        evaluation_id=baseline.evaluation_id,
        tick=baseline.tick,
        agent_id=baseline.agent_id,
        action_id=baseline.action_id,
        target_object_id=baseline.target_object_id,
        target_agent_id=baseline.target_agent_id,
        intent=intent,
        force_vector=force_vector,
        clarity=round(clarity, 3),
        commitment=round(commitment, 3),
        execution_quality=round(execution_quality, 3),
        risk_control=round(risk_control, 3),
        situational_fit=(
            round(situational_fit, 3) if situational_fit is not None else None
        ),
        estimated_cost=round(estimated_cost, 1),
        risk_level=round(risk_level, 3),
        raw_action_text=baseline.raw_action_text,
        rationale=rationale,
        weaknesses=weaknesses,
        metadata=metadata,
    )
