"""Capital-market order parsing and final-payload safety policy."""
from __future__ import annotations

import re
from typing import Any, Dict


class CapitalMarketOrderPolicy:
    @staticmethod
    def _backfill_trade_fields_from_text(parsed: Dict[str, Any]) -> None:
        action_id = str(parsed.get("action_id") or parsed.get("intent") or "")
        if action_id not in {"buy_asset", "sell_asset"}:
            return
        parameters = dict(parsed.get("parameters") or {})
        blob = " ".join(
            str(parsed.get(key) or "")
            for key in ("text", "plan", "character_monologue", "public_reasoning")
        )
        code_pattern = r"(?:\d{5,6}\.(?:SH|SZ|SS|HK)|0?\d{3,4}\.HK)"
        if not parameters.get("asset_id"):
            match = re.search(rf"\b({code_pattern})\b", blob, flags=re.IGNORECASE)
            if match:
                code = match.group(1).upper()
                parameters["asset_id"] = (
                    code[:-3] + ".SH" if code.endswith(".SS") else code
                )
        if not parameters.get("asset_name"):
            name = ""
            patterns = (
                rf"(?:买入|卖出|加仓|减仓|建仓)\s*([一-龥]{{2,8}})\s*[（(]\s*{code_pattern}",
                rf"{code_pattern}\s*[（(]\s*([一-龥]{{2,8}})",
                rf"([一-龥]{{2,8}})\s*[（(]\s*{code_pattern}",
                r"(?:买入|卖出|加仓|减仓|建仓)\s*([一-龥]{2,8})",
            )
            for index, pattern in enumerate(patterns):
                match = re.search(pattern, blob, flags=re.IGNORECASE)
                if not match:
                    continue
                candidate = match.group(1).strip()
                if index == 2 and any(
                    token in candidate
                    for token in ("买入", "卖出", "加仓", "减仓", "建仓", "约", "按", "元", "股")
                ):
                    continue
                name = candidate
                break
            for suffix in ("股票", "股份", "股"):
                if name.endswith(suffix) and len(name) > len(suffix) + 1:
                    name = name[:-len(suffix)]
            if name:
                parameters["asset_name"] = name
        if parameters.get("expected_price") in (None, "") and parameters.get(
            "limit_price"
        ) in (None, ""):
            match = re.search(
                r"(?:约|按|单价|现价|价格)\s*[：:]?\s*(\d+(?:\.\d+)?)\s*元",
                blob,
            )
            if match:
                try:
                    parameters["expected_price"] = float(match.group(1))
                except (TypeError, ValueError):
                    pass
        if parameters.get("quantity") in (None, ""):
            match = re.search(
                r"(?:买入|卖出|加仓|减仓|建仓|数量|qty|quantity)\s*"
                r"[：:]?\s*(\d+(?:\.\d+)?)\s*股",
                blob,
                flags=re.IGNORECASE,
            ) or re.search(r"(\d+(?:\.\d+)?)\s*股", blob)
            if match:
                try:
                    parameters["quantity"] = float(match.group(1))
                except (TypeError, ValueError):
                    pass
        if parameters:
            parsed["parameters"] = parameters

    @staticmethod
    def _sanitize_incomplete_trade_final(parsed: Dict[str, Any]) -> None:
        action_id = str(parsed.get("action_id") or parsed.get("intent") or "")
        if action_id not in {"buy_asset", "sell_asset"}:
            return
        parameters = parsed.get("parameters") if isinstance(
            parsed.get("parameters"), dict,
        ) else {}
        if (
            parameters.get("quantity") not in (None, "")
            and str(parameters.get("asset_id") or "").strip()
        ):
            return
        reason = "本拍买卖指令缺少标的或数量，系统降级为观望，避免无效拒单。"
        parsed.update({
            "action_id": "wait_and_review",
            "intent": "wait_and_review",
            "agent_loop_step": "final",
            "parameters": {},
            "text": reason,
            "character_monologue": reason[:40],
            "plan": reason,
        })
