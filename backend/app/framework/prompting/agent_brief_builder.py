"""
AgentBriefBuilder：为每个 Agent 生成个性化决策简报（P0）

不写死场景剧情，只做标准信息组织。从引擎运行态数据中提取：
身份、目标、规则、排名、自身状态、对手摘要、可见对象、行动空间、压力、输出契约。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.interfaces import AgentBrief


class AgentBriefBuilder:
    """从引擎运行态数据生成 AgentBrief"""

    def __init__(
        self,
        goal_text: str = "",
        rule_text: str = "",
        scenario_name: str = "",
        output_contract: Optional[Dict[str, Any]] = None,
        ranking_spec: Optional[Dict[str, Any]] = None,
    ):
        self._goal_text = goal_text or "在终局时最大化自己的目标评分，争取排名第一。"
        self._rule_text = rule_text or self._default_rules()
        self._scenario_name = scenario_name
        # 排名公式：由场景包 metrics.yaml 的 ranking 块声明，OS 不写死"正向指标求和"。
        #   {mode: single_metric, by: <metric_id>, order: descending|ascending}
        #   {mode: weighted_sum, negative_metrics: [<metric_id>...], order: ...}
        self._ranking_spec: Dict[str, Any] = dict(ranking_spec or {})
        self._terminology: Dict[str, str] = {}
        # Per-agent AGENT.md 完整宪章，开局一次性灌进 system prompt（替代默认规则段）
        self._agent_charters: Dict[str, str] = {}
        raw_contract = output_contract or {}
        self._output_contract = raw_contract.get(
            "prompt_contract", raw_contract
        ) if isinstance(raw_contract, dict) else {}

    def set_terminology(self, terminology: Dict[str, str]) -> None:
        """注入术语表（用于翻译英文 ID 为中文名）"""
        self._terminology = terminology or {}

    def set_agent_charters(self, charters: Dict[str, str]) -> None:
        """注入每个 agent 的 AGENT.md 完整宪章（来自 scenarios/<id>/agents/<aid>/AGENT.md）"""
        self._agent_charters = dict(charters or {})

    # ── 公开入口 ────────────────────────────────────────────────────────────

    def build(
        self,
        agent_id: str,
        tick: int,
        *,
        role: Optional[Any] = None,
        metrics: Optional[Dict[str, Any]] = None,
        all_metrics: Optional[Dict[str, Dict[str, Any]]] = None,
        objects: Optional[List[Dict[str, Any]]] = None,
        actions: Optional[List[Dict[str, Any]]] = None,
        tools: Optional[List[Dict[str, Any]]] = None,
        pressure: Optional[Dict[str, Any]] = None,
        recent_events: Optional[List[str]] = None,
        alive_agent_ids: Optional[List[str]] = None,
        agent_names: Optional[Dict[str, str]] = None,
        public_metrics: Optional[List[str]] = None,
        agent_locations: Optional[Dict[str, str]] = None,
        resources: Optional[Dict[str, float]] = None,
        cooldowns: Optional[Dict[str, int]] = None,
        risk_hints: Optional[List[str]] = None,
        known_evidence: Optional[List[str]] = None,
        pending_proposals: Optional[List[Dict[str, Any]]] = None,
        last_tool_results: Optional[List[Dict[str, Any]]] = None,
        terminology: Optional[Dict[str, str]] = None,
        oracle_events: Optional[List[str]] = None,
    ) -> AgentBrief:
        """构建单个 Agent 的决策简报。"""
        names = agent_names or {}
        my_name = names.get(agent_id, agent_id)
        my_metrics = (metrics or {}).get(agent_id, {}) if metrics else {}
        all_m = all_metrics or {}
        alive = alive_agent_ids or []

        # L2 感知隔离：计算 hidden_info_exclusions
        hidden_exclusions: List[str] = []
        others_data = self._build_others(
            agent_id, all_m, alive, names,
            public_metrics=public_metrics,
            hidden_exclusions_out=hidden_exclusions,
            agent_locations=agent_locations,
        )

        brief = AgentBrief(
            agent_id=agent_id,
            tick=tick,
            identity=self._build_identity(agent_id, my_name, role),
            goal=self._build_goal(),
            rule_summary=self._build_rules(),
            ranking=self._build_ranking(agent_id, my_name, all_m, alive, names),
            self_state=self._build_self_state(my_name, my_metrics, pressure),
            others_summary=others_data,
            visible_objects=self._format_objects(objects or []),
            available_actions=actions or [],
            available_tools=tools or [],
            pressure_state=pressure or {},
            recent_events=self._format_events(recent_events or []),
            output_contract=self._build_output_contract(),
            raw_context={},
            hidden_info_exclusions=hidden_exclusions,
            # P0 底座协议扩展
            self_location=(agent_locations or {}).get(agent_id),
            available_resources=resources or {},
            cooldown_status=cooldowns or {},
            risk_hints=risk_hints or [],
            known_evidence=known_evidence or [],
            pending_proposals=pending_proposals or [],
        )
        # 工具运行结果、术语表、AGENT.md 宪章存入 raw_context（供 prompt_assembler 使用）
        charter = self._agent_charters.get(agent_id, "")
        if charter:
            brief.raw_context["agent_charter"] = charter
        if last_tool_results:
            brief.raw_context["last_tool_results"] = last_tool_results
        if terminology:
            brief.raw_context["terminology"] = terminology
        if oracle_events:
            brief.raw_context["oracle_events"] = list(oracle_events)
        return brief

    # ── 私有：10 类信息构建 ─────────────────────────────────────────────────

    @staticmethod
    def _build_identity(agent_id: str, name: str, role: Optional[Any]) -> Dict[str, Any]:
        info: Dict[str, Any] = {
            "agent_id": agent_id,
            "name": name,
            "description": "你是当前规则世界中的一个 Agent。你的行动会被规则系统结算，并影响最终结果。",
        }
        if role is not None:
            if getattr(role, "display_name", ""):
                info["role_name"] = role.display_name
            if getattr(role, "public_persona", ""):
                info["public_persona"] = role.public_persona
            if getattr(role, "hidden_goal", ""):
                info["hidden_goal"] = role.hidden_goal
        return info

    def _build_goal(self) -> Dict[str, Any]:
        return {
            "summary": self._goal_text,
            "scenario": self._scenario_name,
        }

    @staticmethod
    def _build_rules() -> List[str]:
        return [
            "你不能直接修改最终指标。",
            "你的行动可以作用于世界对象、地点或其他角色，但必须遵守行动声明的目标类型。",
            "世界对象变化后，才会派生目标相关指标变化。",
            "只能使用当前场景声明的行动、工具、规则和结算方式，不得假设其他世界的机制存在。",
            "系统会依据当前场景声明的合法性、世界规则和结算 Provider 处理行动结果。",
            "行动可能成功、无效或反噬。",
            "高风险行动可能带来额外风险。",
            "使用证据、调查和工具可以提高行动质量。",
            "你的目标是最大化目标评分并争取排名第一。",
        ]

    def _build_ranking(
        self,
        agent_id: str, my_name: str,
        all_metrics: Dict[str, Dict[str, Any]],
        alive: List[str], names: Dict[str, str],
    ) -> List[Dict[str, Any]]:
        # 排名分由场景包声明的公式计算，OS 不写死"正向指标求和"。
        #   single_metric：分 = 指定单一指标（如组合总资产）。
        #   weighted_sum（默认）：正向指标加、negative_metrics 里声明的指标减；
        #     未声明 negative_metrics 时全部按正向计入（向后兼容）。
        spec = self._ranking_spec or {}
        mode = str(spec.get("mode") or "weighted_sum")
        order = str(spec.get("order") or "descending")
        negatives = set(spec.get("negative_metrics") or [])

        def score(m: Dict[str, Any]) -> float:
            if not m:
                return 0.0
            if mode == "single_metric":
                value = m.get(str(spec.get("by") or ""))
                return round(float(value), 1) if isinstance(value, (int, float)) else 0.0
            total = 0.0
            for key, value in m.items():
                if not isinstance(value, (int, float)):
                    continue
                total += -value if key in negatives else value
            return round(total, 1)

        reverse = order != "ascending"   # descending = 分高者靠前（默认）
        scored = [(aid, score(all_metrics.get(aid, {}))) for aid in alive if aid in all_metrics]
        scored.sort(key=lambda x: x[1], reverse=reverse)
        ranking = []
        my_score = score(all_metrics.get(agent_id, {}))
        leader_score = scored[0][1] if scored else 0

        for i, (aid, s) in enumerate(scored):
            entry: Dict[str, Any] = {
                "rank": i + 1,
                "agent_id": aid,
                "name": names.get(aid, aid),
                "score": s,
            }
            if aid == agent_id:
                entry["is_self"] = True
                if reverse:
                    entry["gap_to_leader"] = (
                        round(leader_score - my_score, 1) if leader_score > my_score else 0
                    )
                else:
                    entry["gap_to_leader"] = (
                        round(my_score - leader_score, 1) if my_score > leader_score else 0
                    )
            ranking.append(entry)
        return ranking

    @staticmethod
    def _build_self_state(
        name: str, metrics: Dict[str, Any], pressure: Optional[Dict[str, Any]]
    ) -> Dict[str, Any]:
        state: Dict[str, Any] = {
            "name": name,
            "metrics": {k: round(v, 1) for k, v in metrics.items() if isinstance(v, (int, float))},
        }
        if pressure:
            state["pressure"] = {k: round(v, 1) if isinstance(v, float) else v for k, v in pressure.items()}
        return state

    @staticmethod
    def _build_others(
        agent_id: str, all_metrics: Dict[str, Dict[str, Any]],
        alive: List[str], names: Dict[str, str],
        public_metrics: Optional[List[str]] = None,
        hidden_exclusions_out: Optional[List[str]] = None,
        agent_locations: Optional[Dict[str, str]] = None,
    ) -> List[Dict[str, Any]]:
        """构建对手摘要，支持 L2 感知隔离。

        public_metrics: 场景包声明的公开指标名列表（None = 全部公开，预留过滤逻辑）
        hidden_exclusions_out: 被过滤掉的字段会追加到此列表（供 AgentBrief.hidden_info_exclusions 使用）
        agent_locations: 所有 agent 的位置映射，用于在对手摘要中补充位置信息
        """
        others = []
        allowed = set(public_metrics) if public_metrics else None  # None = 全部可见
        locs = agent_locations or {}
        for aid in alive:
            if aid == agent_id:
                continue
            m = all_metrics.get(aid, {})
            if allowed is not None:
                visible = {}
                for k, v in m.items():
                    if not isinstance(v, (int, float)):
                        continue
                    if k in allowed:
                        visible[k] = round(v, 1)
                    elif hidden_exclusions_out is not None:
                        tag = f"{aid}.{k}"
                        if tag not in hidden_exclusions_out:
                            hidden_exclusions_out.append(tag)
            else:
                visible = {k: round(v, 1) for k, v in m.items() if isinstance(v, (int, float))}
            entry = {
                "agent_id": aid,
                "name": names.get(aid, aid),
                "public_metrics": visible,
            }
            # 补充对手位置（公开信息）
            if aid in locs:
                entry["location"] = locs[aid]
            others.append(entry)
        return others

    @staticmethod
    def _format_objects(objects: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        formatted = []
        for obj in objects:
            entry = {
                "id": obj.get("id", obj.get("object_id", "")),
                "name": obj.get("name", obj.get("label", "")),
                "type": obj.get("type", ""),
            }
            # 对象数值
            for key in ("core_value", "severity", "standing"):
                if key in obj:
                    entry["core_value"] = round(obj[key], 1) if isinstance(obj[key], (int, float)) else obj[key]
                    break
            if "factors" in obj and isinstance(obj["factors"], dict):
                entry["factors"] = {k: round(v, 1) if isinstance(v, (int, float)) else v for k, v in obj["factors"].items()}
            if "needs" in obj:
                entry["needs"] = obj["needs"]
            if "hint" in obj:
                entry["hint"] = obj["hint"]
            # 感知投影仍需这些字段做地点/发现/权限过滤
            if "visibility" in obj:
                entry["visibility"] = obj["visibility"]
            if "permissions_required" in obj:
                entry["permissions_required"] = obj["permissions_required"]
            if "location" in obj:
                entry["location"] = obj["location"]
            formatted.append(entry)
        return formatted

    @staticmethod
    def _format_events(events: List[str]) -> List[Dict[str, Any]]:
        return [{"summary": e} for e in events[-6:]]

    def _build_output_contract(self) -> Dict[str, Any]:
        default = {
            "format": "yaml",
            "required_fields": [
                "intent", "target_object_id", "action_name",
                "plan", "resource_commitment", "risk_control", "expected_effect",
            ],
            "description": "只返回结构化行动，不要写旁白或剧情。",
        }
        if not self._output_contract:
            return default
        decision_schema = self._output_contract.get("decision_schema", {})
        # 场景可直接声明 required_fields；
        # 也可只给 decision_schema（如 sanzi_duodi），二者都要读到。
        explicit_required = self._output_contract.get("required_fields")
        if isinstance(explicit_required, list) and explicit_required:
            required = [str(item) for item in explicit_required if item]
        elif isinstance(decision_schema, dict) and decision_schema:
            required = list(decision_schema.keys())
        else:
            required = list(default["required_fields"])
        # format / output_format 两种键名并存（历史场景包不统一）
        output_format = (
            self._output_contract.get("output_format")
            or self._output_contract.get("format")
            or default["format"]
        )
        require_prs = bool(
            self._output_contract.get("require_public_reasoning_summary", False)
        )
        if "public_reasoning_summary" in required:
            require_prs = True
        return {
            **default,
            "format": output_format,
            "required_fields": required or default["required_fields"],
            "decision_schema": decision_schema,
            "require_public_reasoning_summary": require_prs,
            "require_character_monologue": self._output_contract.get(
                "require_character_monologue", True
            ),
            "forbid_raw_chain_of_thought": self._output_contract.get(
                "forbid_raw_chain_of_thought_in_viewer_channel", True
            ),
        }

    @staticmethod
    def _default_rules() -> str:
        return "行动必须作用于世界对象。成功行动会先改变世界对象，再由对象变化派生指标。"


# ── 快捷构建函数 ───────────────────────────────────────────────────────

def build_briefs(
    builder: AgentBriefBuilder,
    state,
    ruleworld_ctx=None,
    agent_roles_map=None,
    agent_names=None,
    evidence_service=None,
) -> Dict[str, AgentBrief]:
    """为所有存活 Agent 批量生成简报。"""
    briefs: Dict[str, AgentBrief] = {}
    alive = getattr(state, "alive_agent_ids", []) or []
    si = getattr(state, "internal", {}) or {}

    metrics = si.get("metrics", {})
    names = agent_names or {}
    roles = agent_roles_map or {}

    # 从 state 提取世界级数据
    agent_locations = getattr(state, "agent_locations", {}) or {}
    all_resources = getattr(state, "resources", {}) or {}
    all_cooldowns = getattr(state, "cooldowns", {}) or {}

    objects = []
    if ruleworld_ctx and hasattr(ruleworld_ctx, "objects"):
        objects = ruleworld_ctx.objects.public_snapshot()
    elif si.get("world_objects"):
        objects = si["world_objects"]

    actions = [
        {"id": a.id, "name": a.name, "description": a.description,
         "requires_target": a.requires_target, "allows_code": a.allows_code}
        for a in (si.get("_available_actions") or [])
    ]

    tools_cfg = []
    if ruleworld_ctx and hasattr(ruleworld_ctx, "tools_cfg"):
        tools_cfg = ruleworld_ctx.tools_cfg

    # 上回合工具运行结果（从 state.internal 读取）
    last_tool_results_map = si.get("last_tool_results", {}) or {}

    for aid in alive:
        role = roles.get(aid)
        pressure = {}
        risk_hints: List[str] = []
        if ruleworld_ctx and hasattr(ruleworld_ctx, "pressure"):
            try:
                ps = ruleworld_ctx.pressure.get_state(aid)
                if ps:
                    pressure = {
                        "action_points": round(getattr(ps, "action_points", 0), 1),
                        "resources": round(getattr(ps, "resources", 0), 1),
                        "risk_accumulation": round(getattr(ps, "risk_accumulation", 0), 3),
                        "information_scope": round(getattr(ps, "information_scope", 0), 2),
                        "deadline_pressure": round(getattr(ps, "deadline_pressure", 0), 2),
                        "counterplay_level": round(getattr(ps, "counterplay_level", 0), 2),
                        "is_under_pressure": getattr(ps, "is_under_pressure", False),
                        "pressure_reasons": getattr(ps, "pressure_reasons", []),
                    }
                    # 风险提示
                    risk_acc = getattr(ps, "risk_accumulation", 0)
                    if risk_acc and risk_acc > 0.5:
                        risk_hints.append(f"风险累积较高（{risk_acc:.1f}），高风险行动可能引发反噬")
                    ap = getattr(ps, "action_points", 0)
                    if ap is not None and ap < 3:
                        risk_hints.append(f"行动点不足（{ap:.0f}），部分行动可能无法执行")
                    dl = getattr(ps, "deadline_pressure", 0)
                    if dl and dl > 0.7:
                        risk_hints.append(f"截止压力高（{dl:.0%}），越临近终局行动风险越大")
                    cp = getattr(ps, "counterplay_level", 0)
                    if cp and cp > 0.3:
                        risk_hints.append(f"对手反制强度高（{cp:.0%}），行动效果可能被削弱")
                    info = getattr(ps, "information_scope", 0)
                    if info is not None and info < 0.5:
                        risk_hints.append(f"信息域偏低（{info:.0%}）")
            except Exception:
                pass

        # 该 agent 的资源
        my_resources = all_resources.get(aid, {})
        # 过滤掉 None 值
        my_resources = {k: round(v, 1) for k, v in my_resources.items() if isinstance(v, (int, float))}

        # 该 agent 的冷却状态（过滤掉已过期的）
        my_cooldowns_raw = all_cooldowns.get(aid, {}) or {}
        my_cooldowns = {k: v for k, v in my_cooldowns_raw.items() if isinstance(v, int) and v > 0}

        # 已知证据（从 EvidenceService 获取该 agent 创建的证据）
        known_evidence: List[str] = []
        if evidence_service:
            try:
                all_evidence = evidence_service.all()
                known_evidence = [
                    f"{e.claim}（置信度{e.confidence:.1f}）"
                    for e in all_evidence
                    if getattr(e, "created_by", "") == aid
                ][:8]  # 最多8条，防止 prompt 过长
            except Exception:
                pass

        events_raw = si.get("recent_summaries", []) or []

        # 针对该 agent 的待回应提议（state.internal.pending_proposals[aid]）
        pending_root = si.get("pending_proposals", {}) or {}
        my_pending: List[Dict[str, Any]] = list(pending_root.get(aid, []) or [])

        # L2 感知隔离：从场景包获取公开指标列表（None = 全部公开，预留过滤）
        public_metrics_list = None
        if ruleworld_ctx and hasattr(ruleworld_ctx, "metrics_cfg"):
            _mcfg = ruleworld_ctx.metrics_cfg
            if isinstance(_mcfg, dict):
                _pm = _mcfg.get("public_metrics")
                if isinstance(_pm, list):
                    public_metrics_list = _pm

        # 从 vocabulary 获取术语表（用于翻译地点/对象 ID 为中文名）
        terminology = {}
        if ruleworld_ctx and hasattr(ruleworld_ctx, "metrics_cfg"):
            pass  # metrics_cfg is for metric rules, not terminology
        # 术语表从 director vocabulary 获取（由 perception kernel 传入）
        if hasattr(builder, "_terminology"):
            terminology = builder._terminology or {}

        briefs[aid] = builder.build(
            agent_id=aid,
            tick=getattr(state, "tick", 0),
            role=role,
            metrics=metrics,
            all_metrics=metrics,
            objects=objects,
            actions=actions,
            tools=tools_cfg,
            pressure=pressure,
            recent_events=events_raw,
            alive_agent_ids=alive,
            agent_names=names,
            public_metrics=public_metrics_list,
            agent_locations=agent_locations,
            resources=my_resources,
            cooldowns=my_cooldowns,
            risk_hints=risk_hints,
            known_evidence=known_evidence,
            pending_proposals=my_pending,
            last_tool_results=last_tool_results_map.get(aid),
            terminology=terminology,
            oracle_events=list((si.get("oracles", {}) or {}).get(aid, []) or []),
        )
    # 神谕一次性消费：注入本回合 brief 后即清空，避免堆积与重复刺激
    oracle_map = si.get("oracles", {}) or {}
    for aid in alive:
        oracle_map.pop(aid, None)
    return briefs
