"""
PromptAssembler：将 AgentBrief 转换为最终发给 LLM 的 prompt（P0）

不写死场景文案，只做标准模板拼装。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.interfaces import AgentBrief
from app.framework.presentation.audience_text import audience_label


class PromptAssembler:
    """将 AgentBrief 组装为 system prompt + user message"""

    def assemble_system(self, brief: AgentBrief, role_extra: str = "") -> str:
        """生成 system prompt（角色人设 + 规则）。

        优先使用场景包提供的 AGENT.md 宪章（来自 scenarios/<id>/agents/<aid>/AGENT.md）。
        若缺失则回退到旧的"身份 + 规则摘要"组装路径。
        """
        # 路径 A：场景包提供了 AGENT.md → 直接作为完整 system prompt
        charter = (brief.raw_context or {}).get("agent_charter", "")
        if charter and isinstance(charter, str) and charter.strip():
            parts_a = [charter.strip()]
            if role_extra:
                parts_a.append(role_extra)
            return "\n\n".join(parts_a)

        # 路径 B（兼容旧场景包）：用 brief 字段拼装
        parts: List[str] = []

        # 1. 身份
        identity = brief.identity
        parts.append(
            f"你是 {identity.get('name', identity.get('agent_id', 'Agent'))}。"
            f"你正在参与一个多智能体规则世界：{brief.goal.get('scenario', '')}。"
        )
        if identity.get("public_persona"):
            parts.append(f"你的公开身份：{identity['public_persona']}")
        if identity.get("hidden_goal"):
            parts.append(f"你的秘密目标（不可泄露）：{identity['hidden_goal']}")

        # 场景包追加的额外提示
        if role_extra:
            parts.append(role_extra)

        # 2. 终局目标
        parts.append(f"\n## 终局目标\n{brief.goal.get('summary', '争取目标评分排名第一。')}")

        # 3. 规则摘要
        rules = brief.rule_summary
        if rules:
            parts.append("\n## 规则摘要")
            for i, r in enumerate(rules, 1):
                parts.append(f"{i}. {r}")

        # 4-10 在 user message 里
        return "\n".join(parts)

    def assemble_user_message(self, brief: AgentBrief) -> str:
        """生成 user message（局势 + 行动空间 + 输出格式）"""
        lines: List[str] = []
        terminology = (
            brief.raw_context.get("terminology", {})
            if brief.raw_context else {}
        )
        # 可选行动列表提前取出：挑战材料段和行动列表共用这一份。
        # 作答动作 id,而"可选行动"渲染段在后部——两处共用这一份。
        actions = brief.available_actions
        lines.append(f"## Tick {brief.tick} 局势简报\n")

        # 神谕注入（观察者干预）：本回合突发变故，最高优先级感知
        oracle_events = (
            brief.raw_context.get("oracle_events")
            if brief.raw_context else None
        )
        if oracle_events:
            lines.append("### ⚡ 突发变故（最高优先级）")
            for evt in oracle_events:
                lines.append(f"  {evt}")
            lines.append(
                "  以上是本回合刚刚发生的重大变故，真实有效。"
                "评估它对你的处境和策略的影响，优先纳入本回合决策。"
            )
            lines.append("")

        current_challenge = (
            brief.raw_context.get("current_challenge")
            if brief.raw_context else None
        )
        if current_challenge:
            lines.append("### 当前世界挑战")
            sequence_label = str(
                current_challenge.get("sequence_label")
                or f"挑战 {current_challenge.get('order', '?')}"
            )
            lines.append(
                f"  {sequence_label}："
                f"{current_challenge.get('title', '新的挑战')}"
            )
            lines.append(
                "  本次挑战目标会被世界规则真实裁决。你可以正面解决、"
                "与对手合作，也可以在承担暴露和反噬风险的前提下破坏对手。"
            )

        # 挑战因果钩子：前次挑战回响 + 本人作答惯性
        challenge_history = (
            brief.raw_context.get("challenge_history")
            if brief.raw_context else None
        )
        if challenge_history:
            lines.append("### 前次挑战回响（剧情连续，公开信息）")
            for seg in challenge_history:
                lines.append(f"  - {seg}")
        challenge_momentum = (
            brief.raw_context.get("challenge_momentum")
            if brief.raw_context else None
        )
        if challenge_momentum:
            lines.append(f"  ※ {challenge_momentum}")

        # 挑战激活时把材料和响应格式直接给到 agent。
        # agent 必须选 challenge 类动作，并把 JSON 答案写到 ActionPack.text。
        challenge_actions = [
            a for a in (actions or [])
            if isinstance(a, dict) and str(a.get("category", "") or "") == "challenge"
        ]
        challenge_action_id = str(
            (challenge_actions[0].get("id") if challenge_actions else "") or ""
        )
        challenge_action_name = str(
            (challenge_actions[0].get("name") if challenge_actions else "提交挑战响应")
            or "提交挑战响应"
        )
        challenge_question = (
            brief.raw_context.get("challenge_question")
            if brief.raw_context else None
        )
        if challenge_question and challenge_action_id:
            import json as _json
            lines.append("\n### 本次挑战（必须应对）")
            lines.append(
                f"  能力维度：{challenge_question.get('capability_label','')}"
            )
            lines.append(
                f"  任务要求：{challenge_question.get('instruction','')}"
            )
            materials = challenge_question.get("materials") or {}
            if materials:
                lines.append("  挑战材料：")
                for k, v in materials.items():
                    if k == "image_paths":
                        count = len(v) if isinstance(v, list) else 1
                        lines.append(f"    - 附图：共 {count} 张，已通过视觉接口送达，请直接观察图像内容作答")
                        continue
                    try:
                        v_str = _json.dumps(v, ensure_ascii=False) if not isinstance(v, str) else v
                    except Exception:
                        v_str = str(v)
                    lines.append(f"    - {k}: {v_str}")
            schema = challenge_question.get("output_schema") or {}
            if schema:
                # 填空范式：把 schema 的 key 与"含义说明"并列，明确告诉 LLM
                # 要保留 key 名原样、只替换 <...> 占位为实际答案。
                lines.append("  作答必须是 JSON，**严格保留以下 key 名**（双引号内字符串原样不变），")
                lines.append("  把 <...> 占位文本替换为你的实际答案：")
                template_lines: List[str] = ["{"]
                items = list(schema.items())
                for i, (k, desc) in enumerate(items):
                    sep = "," if i < len(items) - 1 else ""
                    template_lines.append(
                        f'  "{k}": "<在此填入：{desc}>"{sep}'
                    )
                template_lines.append("}")
                for tl in template_lines:
                    lines.append(f"    {tl}")
                # 再给一个反面警示，避免上一局观察到的"空 key"失误
                lines.append(
                    "  ⚠️ 绝不可输出空 key（例如 {\"\": \"答案\"} 是错误的），"
                    "key 名必须与上方完全一致。"
                )
            lines.append(
                f"  **本回合你只能选择 {challenge_action_name}（{challenge_action_id}）动作；text 字段必须是上述 JSON "
                "（可以在前面加 <think> 段思考，但最终要给出完整 JSON）；character_monologue "
                "用来写第一人称研判过程，会作为观众可见叙事素材。**"
            )
            lines.append(
                f"  {challenge_action_name}（{challenge_action_id}）是全局挑战响应，不作用于任何普通对象或角色；"
                "target_id、target_object_id、target_agent_id 都必须填 null。"
            )

        # 2c. 世界状态目标（以"事"呈现，不是分数）。
        # 标题/尾注由场景包 audit.yaml 的 world_goals_title / world_goals_footer
        # 标题与尾注由场景包提供，缺省使用中性表述。
        world_goals = (
            brief.raw_context.get("world_goals") if brief.raw_context else None
        )
        if world_goals:
            goals_title = str(
                (brief.raw_context or {}).get("world_goals_title")
                or "世界目标（做成的事会计入终局裁定）"
            )
            goals_footer = str(
                (brief.raw_context or {}).get("world_goals_footer")
                or "这些是可载入终局裁定的事实成就，不是每拍刷的数字。"
                "选一两件深耕，比处处撒网更有效。"
            )
            lines.append(f"\n### {goals_title}")
            for g in world_goals:
                status = f" {g['status']}" if g.get("status") else ""
                lines.append(f"  - {g['name']}：{g['description']}{status}")
            lines.append(f"  {goals_footer}")

        # 2d. 私下交谈（自由对话通道）：对手的原话 + 偷听到的风声
        incoming = (
            brief.raw_context.get("incoming_messages") if brief.raw_context else None
        )
        if incoming:
            lines.append("\n### 私下交谈")
            for msg in incoming:
                lines.append(f"  {msg}")
            lines.append(
                "  对方的话可能是真心也可能是圈套，信几分由你判断。想回话就"
                "选 converse 动作（target_agent_id 填对方 id，要说的话写进 text），"
                "也可以装作无事发生。"
            )

        # 3a. 上一拍复盘（失败反馈闭环）：为什么没成，让模型能沿失败调整打法
        last_verdict = (
            brief.raw_context.get("last_verdict") if brief.raw_context else ""
        )
        if last_verdict:
            lines.append("\n### 上一拍复盘")
            lines.append(f"  {last_verdict}")
            lines.append("  想想为什么，换个思路，别在同一处跌倒两次。")

        pending_action_intents = (
            brief.raw_context.get("pending_action_intents")
            if brief.raw_context else None
        )
        if pending_action_intents:
            lines.append("\n### 待完成的行动意图")
            for item in pending_action_intents:
                if not isinstance(item, dict):
                    continue
                action_name = item.get("action_name") or item.get("action_id")
                message = item.get("message") or "上一回合有行动意图尚未落地。"
                lines.append(f"  - {message}")
                lines.append(
                    f"    本回合请明确选择：执行「{action_name}」、缩小方案，"
                    "或者放弃并说明原因；不要无故重做同一份研究。"
                )

        # 回合阶段由场景 clock.yaml 声明、OS 统一算并注入 round_phase。
        # OS 只透传阶段名与场景描述，不自行解读任何标志（如是否可交易）——
        # 那由场景在 description 里表达。
        round_phase = (
            brief.raw_context.get("round_phase") if brief.raw_context else None
        )
        if isinstance(round_phase, dict) and round_phase:
            phase_name = round_phase.get("name") or round_phase.get("id") or "当前阶段"
            cycle_label = round_phase.get("cycle_label") or "周期"
            cycle = round_phase.get("cycle")
            desc = round_phase.get("description") or ""
            lines.append("\n### 当前阶段")
            lines.append(f"  - {cycle_label}{cycle} · {phase_name}")
            if desc:
                lines.append(f"  - {desc}")

        # 你的结算状态：业务含义与展示文案由场景结算插件提供（display_text）。
        # OS 只透传，不认识任何具体业务字段（这些由场景自己在文案里表达）。
        settlement_state = (
            brief.raw_context.get("agent_settlement_state") if brief.raw_context else None
        )
        if isinstance(settlement_state, dict) and settlement_state:
            display_text = str(settlement_state.get("display_text") or "").strip()
            if display_text:
                lines.append("\n### 你的当前状态")
                for text_line in display_text.splitlines():
                    lines.append(f"  {text_line}" if text_line.strip() else "")
            else:
                scalars = [
                    (k, v) for k, v in (settlement_state.get("values") or {}).items()
                    if isinstance(v, (int, float))
                ]
                if scalars:
                    lines.append("\n### 你的当前状态")
                    lines.append(
                        "  - " + "，".join(f"{k}: {v}" for k, v in scalars[:6])
                    )

        # 3a2. 私人记忆：你的反思洞察（置顶）+ 备忘（note_to_self 累积）
        private_memory = (
            brief.raw_context.get("private_memory") if brief.raw_context else None
        )
        if private_memory:
            reflections = private_memory.get("reflections") or []
            notes = private_memory.get("notes") or []
            if reflections or notes:
                lines.append("\n### 你的私人记忆（只有你自己看得到）")
                for r in reflections:
                    lines.append(f"  💭 {r}")
                for n in notes[-6:]:
                    lines.append(f"  📝 {n}")

        # 3b. 本局回忆——OS 自动记录的你过去几拍的关键事件（你视角）
        run_memory = (
            brief.raw_context.get("run_memory") if brief.raw_context else ""
        )
        if run_memory:
            lines.append("\n### 你的本局回忆（OS 记录）")
            for ln in run_memory.splitlines():
                lines.append(f"  {ln}")

        # 3c. 更早回合的压缩摘要（history 被截断后的兜底）
        memory_summary = (
            brief.raw_context.get("memory_summary") if brief.raw_context else ""
        )
        if memory_summary:
            lines.append("\n### 你的长期记忆摘要（更早回合概括）")
            lines.append(f"  {memory_summary}")

        # 4. 当前排名
        # （V1 感知降喂：只给名次与原始分数，不再替模型算"落后领先者 N 分"
        # 这类结论——差距多大、谁是威胁、该追谁防谁，让模型自己判断。
        # 判断的空间就是智能的空间。）
        ranking = brief.ranking
        if ranking:
            lines.append("### 当前排名")
            for r in ranking:
                tag = " ← 你" if r.get("is_self") else ""
                lines.append(f"  {r['rank']}. {r['name']}：{r['score']}{tag}")

        # 5. 自身状态
        self_state = brief.self_state
        if self_state:
            lines.append("\n### 你的状态")
            metrics = self_state.get("metrics", {})
            if metrics:
                lines.append("  核心指标：")
                for k, v in metrics.items():
                    lines.append(f"    {audience_label(k, terminology)}: {v}")
            pressure = self_state.get("pressure", {})
            if pressure:
                lines.append("  压力状态：")
                for k, v in pressure.items():
                    if v is not None:
                        lines.append(f"    {audience_label(k, terminology)}: {v}")

        # 5b. 可用资源
        if brief.available_resources:
            lines.append("\n### 你的资源")
            res_str = ", ".join(
                f"{audience_label(k, terminology)}={v}"
                for k, v in brief.available_resources.items()
            )
            lines.append(f"  {res_str}")

        # 5c. 冷却状态
        if brief.cooldown_status:
            lines.append("\n### 冷却中（本回合不可用）")
            for action_id, remaining in brief.cooldown_status.items():
                lines.append(f"  {action_id}：还需 {remaining} 回合")

        # 5d. 风险提示
        if brief.risk_hints:
            lines.append("\n### ⚠️ 风险提示")
            for hint in brief.risk_hints:
                lines.append(f"  - {hint}")

        # 5e. 已知证据
        if brief.known_evidence:
            lines.append("\n### 你掌握的证据")
            for i, ev in enumerate(brief.known_evidence, 1):
                lines.append(f"  {i}. {ev}")

        # 5f. 待回应提议（同地点对手在前几拍对你发起的定向动作）
        if brief.pending_proposals:
            lines.append("\n### 针对你的待回应提议（对手前几拍对你发起的定向动作）")
            terminology = (brief.raw_context.get("terminology", {}) if brief.raw_context else {}) or {}
            agent_names = {}
            for o in (brief.others_summary or []):
                agent_names[o.get("agent_id")] = o.get("name") or o.get("agent_id")
            for p in brief.pending_proposals[-5:]:
                src = p.get("source_id", "?")
                src_name = agent_names.get(src, src)
                act_label = terminology.get(p.get("action_id", ""), p.get("action_id", ""))
                tick_ago = brief.tick - int(p.get("tick", brief.tick))
                # 降喂：只陈述事实（谁、何时、什么动作），怎么回应、要不要
                # 回应、代价如何权衡——可选行动列表里有工具，判断留给模型。
                lines.append(
                    f"  - 第 {p.get('tick')} 拍 {src_name}（{src}）对你发起「{act_label}」"
                    f"（{tick_ago} 拍前）。不回应则会在 4 拍后自动过期。"
                )

        # （V0 拿走量表：原"可选能力展示机会"整节已移除——把能力考点和对应
        # 动作 id 直接喂给模型，等于每拍提醒它"现在表演这几项有记录"，训练出
        # 的是应试不是策略。测评机会的登记照常在引擎侧进行，只是不再向 agent
        # 广播。）

        # 6. 对手摘要
        others = brief.others_summary
        if others:
            lines.append("\n### 对手公开态势")
            for o in others:
                name = o.get("name", o.get("agent_id", "?"))
                loc = o.get("location", "")
                # 将地点 ID 翻译为中文名
                loc_display = loc
                if loc and brief.raw_context and "terminology" in brief.raw_context:
                    loc_display = brief.raw_context["terminology"].get(loc, loc)
                metrics = o.get("public_metrics", {})
                top_items = sorted(metrics.items(), key=lambda x: x[1] if isinstance(x[1], (int, float)) else 0, reverse=True)[:4]
                summary = ", ".join(
                    f"{audience_label(k, terminology)}={v}"
                    for k, v in top_items
                )
                loc_str = f" 位置={loc_display}" if loc_display else ""
                lines.append(f"  {name}：{summary}{loc_str}")

        # 7. 可见世界对象
        # （V1 感知降喂：不再直接给"关键程度"数值和因子明细——对象到底
        # 值不值得投入，需要用 inspect / 工具去探。探索重新变成必要行为，
        # 语法层信息（合法 id 列表）保持完整。）
        objects = brief.visible_objects
        if objects:
            lines.append("\n### 可见世界对象（target_object_id 必须填英文 id，不是中文名称）")
            for obj in objects:
                oid = obj.get("id", "?")
                name = obj.get("name", oid)
                object_type = obj.get("type", "object")
                hint = obj.get("hint", "")
                lines.append(f"  - id={oid}（{name}）类型={object_type}")
                if hint:
                    lines.append(f"    提示：{hint}")
            valid_obj_ids = [o.get("id", "") for o in objects if o.get("id")]
            if valid_obj_ids:
                has_required_object_target = any(
                    a.get("requires_target")
                    and a.get("target_kind") == "object"
                    and not a.get("target_optional_for_settlement")
                    for a in (actions or [])
                )
                if has_required_object_target:
                    lines.append(f"\n  ⚠️ 需要场景对象目标的行动，target_object_id 必须是以下英文 id 之一：{', '.join(valid_obj_ids)}")
                    lines.append("  ⚠️ 不可填中文名称，不可自创 id，否则行动将被系统忽略。")
                else:
                    lines.append(
                        "\n  提示：当前若选择现实交易类行动，真实标的请填写在 "
                        "parameters.asset_id 中；target_object_id 可以留空。"
                    )

        # 8. 可选行动（actions 已在函数开头取出）
        if actions:
            has_freeform = any(
                str(a.get("id", "")).startswith("category:") for a in actions
            )
            lines.append("\n### 可选行动（从以下 id 中选择一个，不可自创新 id）")
            for a in actions:
                aid = a.get("id", "?")
                name = a.get("name", aid)
                desc = a.get("description", "")
                target_kind = a.get("target_kind", "")
                target_types = list(a.get("target_types", []) or [])
                allows_code = a.get("allows_code", False)
                is_freeform = str(aid).startswith("category:")
                target_hint = ""
                if target_kind == "location":
                    target_hint = "【目标=地点ID】"
                elif target_kind == "object":
                    eligible = a.get("eligible_target_objects", []) or []
                    if a.get("target_optional_for_settlement"):
                        target_hint = (
                            "【目标=可留空；真实交易/现实目标请填 parameters 中的字段"
                            + (
                                f"；若要引用场景对象可选={','.join(eligible)}"
                                if eligible else ""
                            )
                            + "】"
                        )
                    else:
                        target_hint = (
                            "【目标=世界对象ID"
                            + (
                                f"；可选={','.join(eligible)}"
                                if eligible else ""
                            )
                            + "】"
                        )
                elif target_kind == "evidence":
                    target_hint = "【目标=证据ID】"
                elif target_kind == "agent":
                    eligible = a.get("eligible_target_agents", []) or []
                    target_hint = (
                        "【目标=角色ID；填写 target_agent_id"
                        + (
                            f"；可选={','.join(eligible)}"
                            if eligible else ""
                        )
                        + "】"
                    )
                code_hint = " [可附带代码]" if allows_code else ""
                type_hint = (
                    f"【允许类型={','.join(target_types)}】"
                    if target_types and "object" not in target_types else ""
                )
                freeform_hint = (
                    "【这是一个自由类别：action_id 就填这个类别标签本身，"
                    "不套模板，在 plan 字段用自然语言写清楚你具体打算做什么、"
                    "对谁、用什么手段、承担什么风险——裁判会按你写的内容打分，"
                    "不是按固定套路扣分。如果你想触发某个隐藏对象的效果，"
                    "把 target_object_id 填成那个对象的真实 id。】"
                    if is_freeform else ""
                )
                parameter_schema = a.get("parameters_schema") or {}
                parameter_hint = ""
                if isinstance(parameter_schema, dict) and parameter_schema:
                    required = list(parameter_schema.get("required") or [])
                    properties = parameter_schema.get("properties") or {}
                    fields = []
                    for field_name, field_cfg in properties.items():
                        marker = "必填" if field_name in required else "可选"
                        description = (
                            str(field_cfg.get("description") or "")
                            if isinstance(field_cfg, dict) else ""
                        )
                        fields.append(f"{field_name}（{marker}：{description}）")
                    parameter_hint = "【parameters=" + "；".join(fields) + "】"
                lines.append(
                    f"  - {aid}：{name} — {desc} "
                    f"{target_hint}{type_hint}{code_hint}{parameter_hint}{freeform_hint}"
                )
            if has_freeform:
                lines.append(
                    "\n  💡 提示：暗面手段既可以选一个预设招式（省心，但同一预设"
                    "招式重复使用会让对手产生防备，效果一次比一次差），也可以选"
                    "自由类别 + 自己写 plan（每次手法不同就没有疲劳衰减，效果由"
                    "裁判按你的具体做法和当下局面现场评分）。两条路都合法，"
                    "选哪条看你的策略。"
                )

            # 告知 LLM 可以附带工具代码
            code_actions = [a for a in actions if a.get("allows_code", False)]
            if code_actions:
                tools = brief.available_tools
                if tools:
                    lines.append("\n### 工具代码（可选）")
                    lines.append("  如果选择了标注 [可附带代码] 的行动，可以在输出中额外携带：")
                    lines.append("    attached_tool_id: 工具ID（从以下可用工具中选择）")
                    lines.append("    code: Python 分析代码（不超过40行，在沙盒中执行）")
                    lines.append("  代码中可调用：world.emit_output(结论, **数据)、world.add_evidence(证据文本)、world.emit_event(类型, 描述)。")
                    lines.append("  仅允许 import math/random/json/re/collections/itertools，禁止网络与文件。")
                    lines.append("  工具代码运行结果会在下回合反馈给你，帮助你做进一步决策。")
                    lines.append("  若希望该程序“上线”常驻运行（每回合自动执行），在输出中加 tool_request: {\"deploy\": true, \"purpose\": \"...\"}。")

        # 8b. 当前位置和可达地点（移动行动的关键上下文）
        if brief.self_location:
            lines.append(f"\n### 你的位置")
            lines.append(f"  当前地点：{brief.self_location}")
            reachable = brief.reachable_locations
            if reachable:
                location_action_ids = [
                    a.get("id", "")
                    for a in (actions or [])
                    if a.get("target_kind") == "location"
                ]
                action_hint = (
                    f"（适用于地点目标行动：{', '.join(location_action_ids)}）"
                    if location_action_ids else ""
                )
                lines.append(f"  可到达的地点 {action_hint}：")
                for r in reachable:
                    loc_id = r.get("location_id", "")
                    loc_name = r.get("name", loc_id)
                    cost = r.get("travel_cost", "")
                    cost_str = f"（消耗 {cost}）" if cost else ""
                    lines.append(f"    - {loc_id}（{loc_name}）{cost_str}")

        # 8c. 位置锁定行动（因 same_location 约束当前不可用的行动）
        locked = brief.location_locked_actions
        if locked:
            terminology = (
                brief.raw_context.get("terminology", {})
                if brief.raw_context else {}
            ) or {}
            lines.append("\n### 需接近才能执行的行动")
            lines.append("  以下行动要求你与目标处于同一地点，当前因位置不同而锁定。")
            lines.append("  移动到对手所在地点后即可解锁：")
            for la in locked:
                action_name = la.get("action_name", la.get("action_id", ""))
                required_locs = la.get("required_locations", [])
                # 翻译地点 ID 为中文名
                loc_names = [terminology.get(loc, loc) for loc in required_locs]
                loc_str = "、".join(loc_names) if loc_names else "未知"
                lines.append(f"  - {action_name}：需要前往 [{loc_str}]")

        # 9. 可用工具
        tools = brief.available_tools
        if tools:
            lines.append("\n### 可用工具")
            has_mcp = False
            for t in tools:
                if isinstance(t, dict):
                    tid = str(t.get("id") or t.get("tool_id") or "?")
                    name = str(t.get("name") or tid)
                    desc = str(t.get("description") or "")
                    tool_type = str(t.get("type") or "sandbox").strip().lower()
                    suffix = ""
                    if tool_type == "mcp":
                        has_mcp = True
                        ms = t.get("mcp_server") or "?"
                        mt = t.get("mcp_tool") or "?"
                        suffix = f" [外部 MCP 工具，mcp_server（服务端）={ms}，mcp_tool（工具名）={mt}]"
                    schema = t.get("input_schema")
                    if isinstance(schema, dict):
                        props = schema.get("properties")
                        if isinstance(props, dict) and props:
                            arg_names = ", ".join(str(k) for k in props.keys())
                            suffix += f" 参数（arguments）: {arg_names}"
                    lines.append(f"  - {tid}：{name} — {desc}{suffix}")
                else:
                    lines.append(f"  - {t}")
            lines.append(
                "\n  调用方式（三选一，每回合只选一种主路径）："
            )
            lines.append(
                "  ① MCP/外部工具：tool_request 带 tool_id + arguments，无需 code。"
            )
            lines.append(
                '     {"tool_request": {"tool_id": "<工具id>", "arguments": {...}}}'
            )
            lines.append(
                "  ② 沙箱内联：attached_tool_id + code（一次性试跑，≤40行）。"
            )
            lines.append(
                "  ③ 工作区脚本：workspace_write 写入 code/，workspace_run 试跑；"
                "确认无误后加 deploy 上线常驻（见「代码工作区」）。"
            )
            lines.append(
                "  ⚠️ 不要混用：MCP 调用不要附带 code；工作区路径不要写 inline code。"
            )
            if has_mcp:
                lines.append(
                    "  MCP 工具走 ①；arguments 的键见各工具 input_schema（输入模式）。"
                )
            lines.append(
                '  常驻上线：试跑成功后 tool_request 加 '
                '{"deploy": true, "purpose": "用途说明"}。'
            )
            lines.append(
                "  内联 code 路径直接 deploy；工作区路径用 workspace_run 试跑后 deploy，"
                "或显式 workspace_deploy 指定入口文件。"
            )

        # 8d. 代码工作区（C-PR1）：持久化 .py 脚本，可写入后试跑
        code_ws = (
            brief.raw_context.get("code_workspace") if brief.raw_context else None
        )
        if code_ws:
            files = code_ws.get("files") or []
            lines.append("\n### 代码工作区（code/）")
            lines.append(
                f"  目录：{code_ws.get('root', 'code/')}；"
                f"已有脚本：{', '.join(files) if files else '（空）'}"
            )
            lines.append(
                "  ③ 工作区脚本：先写入 .py，再指定 workspace_run 试跑（无需 inline code）。"
            )
            lines.append(
                '     "tool_request": {'
            )
            lines.append(
                '       "workspace_write": {"path": "scout.py", "content": "..."},'
            )
            lines.append(
                '       "workspace_run": "scout.py",'
            )
            lines.append(
                '       "tool_id": "<可用工具id>"'
            )
            lines.append(
                "     }"
            )
            lines.append(
                "  同一回合可先 workspace_write 再 workspace_run；"
                "试跑成功后在 tool_request 中加 deploy: true 即可常驻上线。"
            )
            lines.append(
                '  部署示例：{"workspace_write": {...}, "workspace_run": "scout.py", '
                '"tool_id": "tool_probe", "deploy": true, "purpose": "每回合自动侦察"}'
            )
            lines.append(
                "  文件名仅允许单层 *.py，禁止路径穿越。"
            )
            hint = code_ws.get("hint")
            if hint:
                lines.append(f"  {hint}")

        deployed = (
            brief.raw_context.get("deployed_artifacts") if brief.raw_context else None
        )
        if deployed:
            lines.append("\n### 已部署常驻程序（本局自动每回合运行）")
            for art in deployed:
                name = art.get("name") or art.get("artifact_id") or "?"
                desc = art.get("description") or ""
                wp = art.get("workspace_path")
                extra = f"（工作区 {wp}）" if wp else ""
                lines.append(f"  - {name}{extra}：{desc or '无说明'}")
            lines.append(
                "  修改工作区源文件后重新 deploy 可更新；"
                "绑定工作区路径的宝器每回合自动重载最新脚本。"
            )

        agent_sandbox = (
            brief.raw_context.get("agent_sandbox") if brief.raw_context else None
        )
        if isinstance(agent_sandbox, dict):
            capabilities = agent_sandbox.get("capabilities") or []
            lines.append("\n### 你的独立 Agent Sandbox")
            lines.append(
                f"  Sandbox：{agent_sandbox.get('sandbox_id', '?')}；"
                "这里的文件、依赖和能力只属于你。"
            )
            if capabilities:
                lines.append("  你已经发现或安装的私有能力：")
                status_labels = {
                    "ready": "可直接调用",
                    "installed": "已安装",
                    "discovered": "⚠ 仅发现、尚未安装",
                    "install_failed": "⚠ 安装失败、不可用",
                }
                for item in capabilities[-12:]:
                    if not isinstance(item, dict):
                        continue
                    cid = item.get("capability_id") or item.get("name") or "?"
                    name = item.get("name") or cid
                    status = status_labels.get(str(item.get("status") or ""), "")
                    note = str(item.get("usage_note") or "")
                    suffix = f"（{status}）" if status else ""
                    line = f"  - {cid}：{name}{suffix}"
                    if note:
                        line += f" —— {note}"
                    lines.append(line)

        if brief.raw_context and brief.raw_context.get("agent_loop_enabled"):
            max_steps = brief.raw_context.get("agent_loop_max_steps", 5)
            lines.append("\n### Agent 循环（本回合可多步推理）")
            lines.append(
                f"  本回合启用 Agent 循环，最多 {max_steps} 步。"
                "你可以先调工具/试跑代码，再提交最终行动。"
            )
            lines.append(
                "  只要你需要外部事实、计算结果或缺少某项能力，就必须先输出中间步；"
                "不要把申请工具伪装成场景最终行动，也不要在尚未取得结果时直接提交行动。"
            )
            lines.append(
                '  中间步 JSON：{"agent_loop_step": "continue", "tool_request": {...}}'
            )
            lines.append(
                "  如果现有能力不足，先向能力目录搜索，不要猜测工具 ID："
            )
            lines.append(
                '  {"agent_loop_step": "continue", "tool_request": '
                '{"capability_request": {"operation": "discover", '
                '"query": "你要解决的问题或所需能力"}}}'
            )
            lines.append(
                "  发现需要 Python 依赖时，可申请安装到你自己的隔离环境："
            )
            lines.append(
                '  {"agent_loop_step": "continue", "tool_request": '
                '{"package_install": {"packages": ["package_name==version"]}}}'
            )
            lines.append(
                "  安装后运行工作区脚本时，指定 execution_mode=agent_process；"
                "脚本通过标准输出返回观察结果，不能直接修改世界。"
            )
            lines.append(
                '  或：{"agent_loop_step": "continue", "attached_tool_id": "...", "code": "..."}'
            )
            lines.append(
                "  最终步：正常行动 JSON（必须含 action_id），"
                "不要重复附带已在中间步执行过的 tool_request。"
            )

        # 10. 输出格式
        contract = brief.output_contract
        if contract:
            lines.append("\n### 输出格式要求")
            lines.append(f"  {contract.get('description', '请返回结构化行动')}")
            fields = contract.get("required_fields", [])
            if fields:
                lines.append("  必填字段：")
                for f in fields:
                    lines.append(f"    {f}")

            # 强提示：intent 必须是可选行动列表中的 id
            valid_ids = [a.get("id", "") for a in (actions or []) if a.get("id")]
            if valid_ids:
                lines.append(f"\n  ⚠️ intent 字段必须是以下英文 id 之一：{', '.join(valid_ids)}")
            lines.append(
                "  若行动需要数量、价格、期限或其他场景参数，统一放入 parameters 对象；"
                "不得把参数只写在自然语言 text 中。"
            )

            # 强提示：target_object_id 必须是英文 id
            obj_ids = [o.get("id", "") for o in (objects or []) if o.get("id")]
            if obj_ids:
                obj_example_id = obj_ids[0]
                obj_example_name = ""
                try:
                    first_obj = next(
                        (o for o in (objects or []) if o.get("id") == obj_example_id),
                        None,
                    )
                    if isinstance(first_obj, dict):
                        obj_example_name = str(first_obj.get("name") or terminology.get(obj_example_id) or obj_example_id)
                except Exception:
                    obj_example_name = terminology.get(obj_example_id, obj_example_id)
                lines.append(f"  ⚠️ target_object_id 必须是以下英文 id 之一：{', '.join(obj_ids)}")
                lines.append(f"  ⚠️ target_object_id 填英文 id（如 {obj_example_id}），不填中文名称（如 {obj_example_name}）")
                lines.append("  ⚠️ 不可自创 action id，否则行动将被系统拒绝。")
            agent_target_ids = sorted({
                agent_id
                for action in (actions or [])
                for agent_id in (
                    action.get("eligible_target_agents", []) or []
                )
            })
            if agent_target_ids:
                lines.append(
                    "  ⚠️ 如果所选行动的目标是角色，必须填写 "
                    f"target_agent_id，且只能是：{', '.join(agent_target_ids)}"
                )
                lines.append(
                    "  ⚠️ 角色目标行动不要把角色 ID 填入 target_id。"
                )

            output_format = str(contract.get("format", "yaml")).lower()
            lines.append(f"\n  示例格式（{output_format.upper()}）：")
            lines.append(f"  ```{output_format}")
            # 示例 intent 动态从场景包取第一个合法 id，不写死
            sample_intent = valid_ids[0] if valid_ids else "<从可选行动中选一个>"
            need_prs = (
                "public_reasoning_summary" in fields
                or bool(contract.get("require_public_reasoning_summary"))
            )
            decision_schema = contract.get("decision_schema") or {}
            prs_schema = str(
                decision_schema.get("public_reasoning_summary") or ""
            ).lower() if isinstance(decision_schema, dict) else ""
            prs_as_object = "object" in prs_schema
            if output_format == "json":
                lines.append("  {")
                lines.append(f'    "action_id": "{sample_intent}",')
                lines.append('    "target_id": "从可见目标中选择",')
                lines.append('    "target_agent_id": null,')
                lines.append('    "tool_id": null,')
                lines.append('    "tool_request": null,')
                lines.append('    "parameters": {},')
                if need_prs and prs_as_object:
                    lines.append('    "public_reasoning_summary": {')
                    lines.append('      "strategy_choice": "公开策略摘要",')
                    lines.append('      "risk_consideration": "公开风险考虑"')
                    lines.append("    },")
                else:
                    lines.append(
                        '    "public_reasoning_summary": '
                        '"公开策略摘要（勿留空）",'
                    )
                lines.append('    "character_monologue": "第一人称角色短独白，不超过80字",')
                lines.append('    "plan": "（建议填写）你具体打算怎么做——裁判按内容和局面评分",')
                lines.append('    "note_to_self": "（可选）只写给未来的你自己看的私人备忘：多步计划、伏笔、对某人的暗中判断。不会给裁判、对手或观众看"')
                lines.append("  }")
            else:
                lines.append(f"  intent: {sample_intent}")
                lines.append("  target_object_id: obj_xxx")
                lines.append("  action_name: 你的行动名称")
                lines.append("  plan: 说明策略")
                if need_prs:
                    lines.append(
                        "  public_reasoning_summary: 公开策略摘要（勿留空）"
                    )
                lines.append("  resource_commitment: 0.6")
                lines.append("  risk_control: 0.7")
                lines.append("  evidence_refs: []")
                lines.append("  expected_effect: 预期影响")
                lines.append("  backup_plan: 备选方案")
                lines.append("  character_monologue: 我需要先稳住局面，再寻找突破口。")
                lines.append("  note_to_self: （可选）只写给未来的你自己看的私人备忘——多步计划、伏笔、对某人的暗中判断。不会给裁判、对手或观众看。")
            lines.append("  ```")
            lines.append(f"  只返回上述 {output_format.upper()}，不要写旁白或剧情。")
            if need_prs:
                lines.append(
                    "  ⚠️ public_reasoning_summary 必填：写给观众看的投资策略短摘要；"
                    "禁止留空，也禁止只把内容写在 plan/text 里。"
                )

        # ── 输出语言约束（区分 ID 字段和文本字段）────────────────
        lines.append("\n### ⚠️ 输出语言约束（非常重要）")
        lines.append("  - intent / target_object_id 字段：必须使用英文 id（从上面的列表中选择）")
        lines.append("  - text / character_monologue / plan / public_reasoning_summary / action_name / expected_effect 字段：必须使用纯中文")
        lines.append("  - character_monologue 必须是第一人称角色短独白，只表达当下目标、顾虑或取舍，不得输出分析步骤或隐藏推理")
        lines.append("  - public_reasoning_summary 是给观众看的投资策略短摘要，与 character_monologue 分工不同，两者都要填且内容不要完全相同")
        lines.append("  - text/character_monologue/plan 中绝对禁止出现任何英文 id，包括括号内也不行")
        lines.append("  - 指标只能使用上方显示的中文名；禁止写 public_trust、governance_score 等内部字段名")
        lines.append("  - 英文 id 仅允许出现在 action_id、target_id、tool_id 等结构化控制字段中")
        # 动态示例：优先从当前场景可见对象/可达地点/可用工具中取一个
        loc_example_id = ""
        loc_example_name = ""
        try:
            reachable = getattr(brief, "reachable_locations", None) or []
            if reachable:
                r0 = reachable[0] if isinstance(reachable[0], dict) else {}
                loc_example_id = str(r0.get("location_id") or "")
                loc_example_name = str(r0.get("name") or terminology.get(loc_example_id) or loc_example_id)
        except Exception:
            pass
        tool_example_id = ""
        tool_example_name = ""
        try:
            if tools:
                if isinstance(tools[0], dict):
                    tool_example_id = str(tools[0].get("id") or "")
                    tool_example_name = str(tools[0].get("name") or tool_example_id)
                else:
                    tool_example_id = str(tools[0])
                    tool_example_name = tool_example_id
        except Exception:
            pass
        obj_ids = [o.get("id", "") for o in (objects or []) if o.get("id")]
        obj_example_id = obj_ids[0] if obj_ids else "obj_xxx"
        obj_example_name = terminology.get(obj_example_id) if isinstance(terminology, dict) else None
        if not obj_example_name:
            obj_example_name = obj_example_id
        if loc_example_id:
            lines.append(f"  - 错误示例：'前往 {loc_example_name}（{loc_example_id}）' ← 禁止这样写")
            lines.append(f"  - 正确写法：'前往{loc_example_name}' ← 只写中文")
        else:
            lines.append("  - 错误示例：'前往某地点（location_id）' ← 禁止这样写")
            lines.append("  - 正确写法：'前往某地点' ← 只写中文")
        lines.append(f"  - 错误示例：'{obj_example_name}（{obj_example_id}）' ← 禁止这样写")
        lines.append(f"  - 正确写法：'{obj_example_name}' ← 只写中文")
        if tool_example_id:
            lines.append(f"  - 错误示例：'使用 {tool_example_id}' ← 禁止这样写")
            lines.append(f"  - 正确写法：'使用 {tool_example_name}' ← 只写中文")
        else:
            lines.append("  - 错误示例：'使用 tool_id' ← 禁止这样写")
            lines.append("  - 正确写法：'使用工具中文名' ← 只写中文")
        lines.append("  - 如果需要提及对象，使用上述「可见世界对象」中的中文名称")
        lines.append("  - 如果需要提及工具，使用上述「可用工具」中的中文名称")

        # 近期事件
        recent = brief.recent_events
        if recent:
            lines.append("\n### 近期事件")
            for ev in recent[-4:]:
                lines.append(f"  - {ev.get('summary', str(ev))}")

        # 上回合工具运行结果（回流给 agent）
        last_tool_results = brief.raw_context.get("last_tool_results") if brief.raw_context else None
        if last_tool_results:
            lines.append("\n### 上回合工具运行结果")
            for tr in last_tool_results:
                tool_id = tr.get("tool_id", "?")
                ok = tr.get("ok", False)
                status = "成功" if ok else "失败"
                outputs = tr.get("outputs", [])
                errors = tr.get("errors", [])
                evidence = tr.get("evidence_created", [])
                lines.append(f"  工具 {tool_id} 运行{status}：")
                src = tr.get("source")
                if src:
                    lines.append(f"    来源：{src}")
                if outputs:
                    for o in outputs[:3]:
                        claim = o.get("claim", o.get("summary", str(o))) if isinstance(o, dict) else str(o)
                        lines.append(f"    输出：{claim}")
                if evidence:
                    lines.append(f"    产生证据：{', '.join(evidence[:3])}")
                if errors:
                    for e in errors[:2]:
                        lines.append(f"    错误：{e}")

        return "\n".join(lines)
