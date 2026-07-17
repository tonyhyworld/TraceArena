"""
OutputContractValidator：校验模型返回是否满足最低结构要求（P0）

缺失字段时尝试修复或标记 parsed_ok=False。
"""
from __future__ import annotations

from typing import Any, Dict, List


class OutputContractValidator:
    """校验解析后的行动是否符合输出契约"""

    REQUIRED_FIELDS = [
        "intent",
        "target_object_id",
        "action_name",
        "plan",
        "resource_commitment",
        "risk_control",
        "expected_effect",
    ]

    # 缺字段提示面向运营台展示，用中文名（英文字段名观众/运营看不懂）
    FIELD_ZH = {
        "intent": "行动意图",
        "target_object_id": "目标对象",
        "target_agent_id": "目标角色",
        "action_id": "动作类型",
        "action_name": "动作名称",
        "plan": "行动计划",
        "resource_commitment": "资源投入",
        "risk_control": "风险控制",
        "expected_effect": "预期效果",
        "text": "正文",
    }

    def validate(self, parsed: Dict[str, Any]) -> Dict[str, Any]:
        """
        校验并补全缺失字段。
        返回修复后的 parsed 字典。
        """
        errors: List[str] = []
        for field in self.REQUIRED_FIELDS:
            if parsed.get(field) is None or parsed.get(field) == "":
                errors.append(f"缺少{self.FIELD_ZH.get(field, field)}")
                # 补默认值
                if field in ("resource_commitment", "risk_control"):
                    parsed[field] = 0.5
                elif field == "intent":
                    # 语义意图默认值（场景无关）；具体待命动作 id 由 runtime 按
                    # audit.fallback_action_id 解析，不得在此写死场景动作。
                    parsed[field] = "wait"
                elif field in ("target_object_id",):
                    parsed[field] = None  # 保持 None，让 P1 fallback
                elif field in ("action_name", "plan", "expected_effect"):
                    parsed[field] = ""

        if errors:
            parsed["parse_errors"] = (parsed.get("parse_errors") or []) + errors
            # 不影响 parsed_ok，字段已补默认值
        return parsed
