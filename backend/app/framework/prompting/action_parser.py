"""
ActionParser：解析 LLM 返回的结构化行动（P0）

支持 JSON / YAML / 带代码块的混合文本。
解析失败不抛异常，返回 parsed_ok=False + 原始文本。
"""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

import yaml

from app.mcp.tool_request import normalize_tool_request

class ActionParser:
    """从 LLM 原始输出中提取结构化行动字段"""

    def __init__(
        self,
        actions_cfg: Optional[List[Dict[str, Any]]] = None,
        *,
        strict_mode: bool = False,
    ):
        # strict_mode（严格模式）：benchmark 基准测量时开启。关闭一切"动作空间松绑"
        # ——不做模糊匹配、不路由到类别兜底——让模型输出注册表之外的 id 时如实
        # 保留原样，交由上层按"不在允许列表"判为解析失败，保证解析成功率可信。
        self._strict_mode = strict_mode
        self._actions_map: Dict[str, str] = {}
        # 自由类别兜底动作（is_category_default=true 的 category 动作）。
        # 模型自创的全新动作 id 优先路由到这里，而不是被 unknown_action 打回。
        self._category_defaults: List[str] = []
        self._challenge_action_ids: set[str] = set()
        if actions_cfg:
            for a in actions_cfg:
                aid = a.get("id", "")
                if aid:
                    self._actions_map[aid] = aid
                    if str(a.get("category", "") or "") == "challenge":
                        self._challenge_action_ids.add(str(aid))
                    if a.get("is_category_default"):
                        self._category_defaults.append(aid)
                    # 下划线缩写: wait_and_prepare → wait
                    parts = aid.split("_")
                    if len(parts) >= 2:
                        short = parts[0]
                        if short not in self._actions_map:
                            self._actions_map[short] = aid

    def _normalize_action_id(self, action_id: str) -> tuple:
        """归一化 action_id，返回 (归一化后的 id, 越界记录或 None)。

        越界可见化：模型输出注册表之外的 id（自由的最直接证据）时——
        1. 模糊匹配命中 → 仍然 snap，但记录原始 id（原实现静默吞掉，
           导致"模型从不越界"可能只是解析器制造的假象，行为数据被污染）；
        2. 完全没匹配且存在自由类别兜底 → 路由到类别兜底动作而非打回
           unknown_action，模型的越界萌芽自然流入自由文本通道。
        """
        if not action_id or not self._actions_map:
            return action_id, None
        if action_id in self._actions_map:
            return self._actions_map[action_id], None
        # 严格模式：不做任何修复/路由，原样返回，让上层判为"不在允许列表"。
        if self._strict_mode:
            return action_id, None
        # 编辑距离 ≤2 的模糊匹配
        import difflib
        matches = difflib.get_close_matches(action_id, list(self._actions_map.keys()), n=1, cutoff=0.7)
        if matches:
            snapped = self._actions_map.get(matches[0], action_id)
            return snapped, f"fuzzy_matched: {action_id} → {snapped}"
        if self._category_defaults:
            routed = self._category_defaults[0]
            return routed, f"novel_action_routed: {action_id} → {routed}"
        return action_id, None

    def parse(self, raw: str, agent_id: str) -> Dict[str, Any]:
        """
        返回包含所有 P0 字段的字典。
        若无法解析，parsed_ok=False，保留 raw_output 供 fallback。
        """
        base: Dict[str, Any] = {
            "agent_id": agent_id,
            "parsed_ok": False,
            "raw_model_output": raw,
            "parse_errors": [],
        }

        if not raw or not raw.strip():
            base["parse_errors"].append("模型返回为空")
            return base

        stripped = raw.strip()

        # 尝试顺序：YAML → JSON → 启发式提取
        data = None

        # 1) 提取代码块中的内容
        block = self._extract_block(stripped)
        if block:
            data = self._try_yaml(block) or self._try_json(block)

        # 2) 直接尝试整段文本
        if data is None:
            data = self._try_yaml(stripped) or self._try_json(stripped)

        # 模型常会在 <think> 里先写一个“格式示例”代码块，再在最后输出正式
        # Action JSON。第一段示例可能包含「第一人称角色短独白」这类占位符；
        # 解析时应优先选择最后一个真正带 action_id/intent 的候选。
        data = self._prefer_final_action_candidate(stripped, data)

        # 3) 启发式提取
        if data is None:
            data = self._heuristic_extract(stripped)
            base["parse_errors"].append("结构化解析失败，使用启发式提取")

        if data is None:
            base["parse_errors"].append("无法从模型输出中提取任何结构化信息")
            return base

        # 映射字段
        base["intent"] = data.get("intent") or data.get("action_id")
        base["target_object_id"] = data.get("target_object_id")
        base["target_agent_id"] = data.get("target_agent_id")
        # 旧契约的 target_id 默认仍视为对象；角色目标动作必须显式返回
        # target_agent_id，避免把角色 ID 误送进对象注册表。
        if not base["target_object_id"] and not base["target_agent_id"]:
            base["target_object_id"] = data.get("target_id")
        base["action_name"] = data.get("action_name")
        public_summary = data.get("public_reasoning_summary")
        if isinstance(public_summary, dict):
            public_summary_text = "；".join(
                str(v) for v in public_summary.values() if v not in (None, "")
            )
        else:
            public_summary_text = str(public_summary or "")
        # 模型常漏填该字段却把策略写进 plan；解析层先落到 text 槽，供 runtime 展示。
        if not public_summary_text.strip():
            plan_fallback = data.get("plan")
            if isinstance(plan_fallback, str) and plan_fallback.strip():
                public_summary_text = plan_fallback.strip()
        base["public_reasoning_summary_text"] = public_summary_text
        base["plan"] = data.get("plan") or public_summary_text
        base["text"] = data.get("text") or data.get("plan") or public_summary_text
        if isinstance(base["text"], (dict, list)):
            base["text"] = json.dumps(base["text"], ensure_ascii=False)
        # 三类文本严格分离：
        # - public_reasoning_summary：公开策略依据，供导演/审计使用；
        # - character_monologue：角色化第一人称短独白，供观众卡片使用；
        # - thought：旧协议原样保留，但不再回退到公开摘要。
        base["character_monologue"] = data.get("character_monologue") or ""
        base["thought"] = data.get("thought") or ""
        base["expected_effect"] = data.get("expected_effect")
        base["backup_plan"] = data.get("backup_plan")
        parameters = (
            dict(data.get("parameters") or {})
            if isinstance(data.get("parameters"), dict) else {}
        )
        # Structured action arguments belong to the scene contract. Preserve
        # common top-level arguments too, since providers do not always nest
        # them despite receiving the same JSON schema.
        for key in ("asset_id", "quantity", "price_evidence_ref"):
            if key in data and key not in parameters:
                parameters[key] = data[key]
        base["parameters"] = parameters
        # 私人备忘：只回流给 agent 自己，不进任何公开链路
        nts = data.get("note_to_self")
        if isinstance(nts, str) and nts.strip():
            base["note_to_self"] = nts.strip()[:500]

        # resource_commitment / risk_control：容错转换
        for key in ("resource_commitment", "risk_control"):
            val = data.get(key)
            if val is not None:
                try:
                    base[key] = float(val)
                except (TypeError, ValueError):
                    label = "资源投入" if key == "resource_commitment" else "风险控制"
                    base["parse_errors"].append(f"{label}数值格式异常：{val}")

        # evidence_refs
        ev_refs = data.get("evidence_refs", data.get("linked_evidence_ids"))
        base["evidence_refs"] = ev_refs if isinstance(ev_refs, list) else []

        # Harness 中间步标记：必须原样保留，否则 continue 会被当成空最终动作。
        loop_step = data.get("agent_loop_step")
        if isinstance(loop_step, str) and loop_step.strip():
            base["agent_loop_step"] = loop_step.strip()

        # tool_request（工具请求）
        base["tool_request"] = normalize_tool_request(
            data,
            parse_errors=base["parse_errors"],
        )
        if base["tool_request"] and base["tool_request"].get("tool_id"):
            if not base.get("attached_tool_id"):
                base["attached_tool_id"] = str(base["tool_request"]["tool_id"])

        # code + attached_tool_id（工具沙箱）
        code_val = data.get("code")
        if code_val and isinstance(code_val, str):
            base["code"] = code_val
        attached_tool = data.get("attached_tool_id") or data.get("tool_id")
        if attached_tool and isinstance(attached_tool, str):
            base["attached_tool_id"] = attached_tool

        # action_id 映射：新契约优先 action_id，旧契约兼容 intent。
        action_id = data.get("action_id") or base.get("intent")
        if action_id:
            normalized, boundary_note = self._normalize_action_id(str(action_id))
            base["action_id"] = normalized
            if boundary_note:
                # 越界记录进 parse_errors（运营台可见），novel 路由额外把
                # 原始意图前置到 plan——裁判按模型真正想做的事打分。
                base["parse_errors"].append(boundary_note)
                if boundary_note.startswith("novel_action_routed"):
                    original = str(action_id)
                    base["plan"] = (
                        f"【自创动作：{original}】" + str(base.get("plan") or "")
                    )

        self._repair_challenge_action_text(base, data, stripped)
        if self._is_challenge_action(base.get("action_id")):
            # 挑战作答只绑定当前激活挑战；模型乱填的对象/角色目标会污染导演叙事。
            base["target_object_id"] = None
            base["target_agent_id"] = None

        # 从 plan/text 文本推断模型未填的可选字段，给 Judge 更多评分信号
        self._infer_missing_fields(base)

        base["parsed_ok"] = True
        return base

    # ── 私有 ────────────────────────────────────────────────────────────────

    def _prefer_final_action_candidate(
        self,
        raw: str,
        current: Optional[Dict[str, Any]],
    ) -> Optional[Dict[str, Any]]:
        candidates = [
            item for item in self._extract_json_candidates(raw)
            if isinstance(item, dict) and (item.get("action_id") or item.get("intent"))
        ]
        if not candidates:
            return current
        final = candidates[-1]
        if current is None:
            return final
        current_score = self._action_candidate_score(current)
        repaired_score = self._action_candidate_score(final)
        current_mono = str(current.get("character_monologue") or "").strip()
        if repaired_score >= current_score or self._is_placeholder_monologue(current_mono):
            return final
        return current

    @staticmethod
    def _action_candidate_score(data: Dict[str, Any]) -> int:
        score = 0
        for key in (
            "action_id",
            "intent",
            "text",
            "public_reasoning_summary",
            "character_monologue",
        ):
            if data.get(key) not in (None, "", {}):
                score += 1
        return score

    @staticmethod
    def _is_placeholder_monologue(text: str) -> bool:
        if not text:
            return False
        placeholders = (
            "第一人称角色短独白",
            "角色短独白",
            "在此填写",
            "<",
        )
        return any(item in text for item in placeholders)

    def _is_challenge_action(self, action_id: Any) -> bool:
        if not action_id:
            return False
        if self._challenge_action_ids:
            return str(action_id) in self._challenge_action_ids
        return False

    def _repair_challenge_action_text(
        self,
        base: Dict[str, Any],
        data: Dict[str, Any],
        raw: str,
    ) -> None:
        """挑战响应必须把结构化结果放进 text，供场景验证器读取。

        有些模型会先返回一个行动 JSON，再在后续代码块里返回正式答案 JSON。
        旧逻辑只吃第一个 JSON，导致判卷器拿到公开理由而不是答案。
        """
        if not self._is_challenge_action(base.get("action_id")):
            return

        explicit_text = data.get("text")
        if isinstance(explicit_text, (dict, list)):
            base["text"] = json.dumps(explicit_text, ensure_ascii=False)
            return
        if isinstance(explicit_text, str) and explicit_text.strip():
            base["text"] = explicit_text.strip()
            return

        answer = self._find_trailing_answer_json(raw)
        if answer is not None:
            base["text"] = json.dumps(answer, ensure_ascii=False)

    def _find_trailing_answer_json(self, raw: str) -> Optional[Any]:
        for candidate in self._extract_json_candidates(raw):
            if not isinstance(candidate, dict):
                continue
            if candidate.get("action_id") or candidate.get("intent"):
                continue
            # The response schema belongs to the scenario package, so the OS
            # must not enumerate domain answer keys. Any non-action object
            # after the action envelope is a candidate challenge response;
            # the scene validator remains authoritative for its schema.
            if candidate:
                return candidate
        return None

    @staticmethod
    def _extract_json_candidates(text: str) -> List[Any]:
        """按出现顺序提取文本中所有可解析 JSON 候选。"""
        decoder = json.JSONDecoder()
        candidates: List[Any] = []
        seen: set[str] = set()

        def add(value: Any) -> None:
            if not isinstance(value, (dict, list)):
                return
            try:
                marker = json.dumps(value, ensure_ascii=False, sort_keys=True)
            except TypeError:
                return
            if marker in seen:
                return
            seen.add(marker)
            candidates.append(value)

        for match in re.finditer(
            r"```(?:json)?\s*\n(.*?)```",
            text,
            re.DOTALL | re.IGNORECASE,
        ):
            block = match.group(1).strip()
            try:
                add(json.loads(block))
            except json.JSONDecodeError:
                pass

        for idx, char in enumerate(text):
            if char not in "{[":
                continue
            try:
                value, _ = decoder.raw_decode(text[idx:])
            except json.JSONDecodeError:
                continue
            add(value)

        return candidates

    def _infer_missing_fields(self, base: Dict[str, Any]) -> None:
        """模型未填的可选字段给中性默认值，交给 Judge 按内容语义评。

        （原实现按关键词正则发糖——写"全力/押上"得 0.85、写"预案/审慎"得
        0.75——实测训练出模型往 plan 里堆魔法词而不是想策略，已拆除。
        缺什么就是中性默认，评分回归 Judge 的语义判断。）
        """
        if base.get("resource_commitment") is None:
            base["resource_commitment"] = 0.5
        if base.get("risk_control") is None:
            base["risk_control"] = 0.5

    @staticmethod
    def _extract_block(text: str) -> Optional[str]:
        patterns = [
            r"```(?:yaml|yml)\s*\n(.*?)```",
            r"```(?:json)\s*\n(.*?)```",
            r"```\s*\n(.*?)```",
        ]
        for pat in patterns:
            m = re.search(pat, text, re.DOTALL | re.IGNORECASE)
            if m:
                return m.group(1).strip()
        return None

    @staticmethod
    def _try_yaml(text: str) -> Optional[Dict[str, Any]]:
        try:
            data = yaml.safe_load(text)
            if isinstance(data, dict):
                return data
        except Exception:
            pass
        return None

    @staticmethod
    def _try_json(text: str) -> Optional[Dict[str, Any]]:
        # 尝试找 JSON 对象
        m = re.search(r"\{.*\}", text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except json.JSONDecodeError:
                pass
        try:
            return json.loads(text)
        except json.JSONDecodeError:
            pass
        return None

    @staticmethod
    def _heuristic_extract(text: str) -> Optional[Dict[str, Any]]:
        """从自然语言中提取关键字段（兜底）。"""
        patterns = {
            "intent": r"(?:intent|意图|行动类型)\s*[:：]\s*(\w+)",
            "target_object_id": r"(?:target_object_id|目标对象)\s*[:：]\s*([\w_]+)",
            "action_name": r"(?:action_name|行动名称)\s*[:：]\s*(.+)",
            "plan": r"(?:plan|策略|方案)\s*[:：]\s*(.+)",
            "character_monologue": r"(?:character_monologue|角色独白)\s*[:：]\s*(.+)",
            "expected_effect": r"(?:expected_effect|预期效果|预期影响)\s*[:：]\s*(.+)",
        }
        result: Dict[str, Any] = {}
        for field, pat in patterns.items():
            m = re.search(pat, text, re.IGNORECASE)
            if m:
                result[field] = m.group(1).strip()

        # 资本市场订单字段：结构化失败时尽量保住 asset_id / quantity
        parameters: Dict[str, Any] = {}
        asset = re.search(
            r"(?:asset_id|标的|代码)\s*[:：=]\s*([0-9]{1,6}\.(?:SH|SS|SZ|HK)|[A-Z]{1,5})",
            text,
            re.IGNORECASE,
        )
        if not asset:
            asset = re.search(
                r"\b([0-9]{5,6}\.(?:SH|SS|SZ)|[0-9]{4,5}\.HK)\b",
                text,
                re.IGNORECASE,
            )
        if asset:
            parameters["asset_id"] = asset.group(1).upper().replace(".SS", ".SH")
        qty = re.search(
            r"(?:quantity|数量)\s*[:：=]\s*([0-9]+(?:\.[0-9]+)?)",
            text,
            re.IGNORECASE,
        )
        if not qty:
            qty = re.search(r"([0-9]+(?:\.[0-9]+)?)\s*股", text)
        if qty:
            try:
                parameters["quantity"] = float(qty.group(1))
            except ValueError:
                pass
        pref = re.search(
            r"(?:price_evidence_ref|证据)\s*[:：=]\s*([A-Za-z0-9_:\-]+)",
            text,
            re.IGNORECASE,
        )
        if pref:
            parameters["price_evidence_ref"] = pref.group(1)
        if parameters:
            result["parameters"] = parameters

        if re.search(
            r"(?:buy_asset|买入建仓|买入|建仓|加仓)",
            text,
            re.IGNORECASE,
        ):
            result.setdefault("action_id", "buy_asset")
            result.setdefault("intent", "buy_asset")
        elif re.search(
            r"(?:sell_asset|卖出减仓|卖出|减仓|止损)",
            text,
            re.IGNORECASE,
        ):
            result.setdefault("action_id", "sell_asset")
            result.setdefault("intent", "sell_asset")

        return result if result else None
