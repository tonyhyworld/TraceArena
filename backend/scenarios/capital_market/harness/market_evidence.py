"""Capital-market evidence classification and order identity policy.

This module deliberately lives in the scenario package.  The Agent OS owns
loop mechanics; ticker formats, quotes and trade research gates are domain
policy and must not leak into the generic Harness implementation.
"""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

from app.core.interfaces import AgentBrief


class CapitalMarketEvidencePolicy:
    @staticmethod
    def _quote_tool_tokens(brief: AgentBrief) -> List[str]:
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        tokens = [
            str(item).strip().lower()
            for item in (
                policy.get("quote_tools")
                or policy.get("preferred_quote_tools")
                or []
            )
            if str(item).strip()
        ]
        for extra in ("quote", "candlestick"):
            if extra not in tokens:
                tokens.append(extra)
        return tokens

    @classmethod
    def _step_looks_like_quote(
        cls, step: Dict[str, Any], brief: AgentBrief,
    ) -> bool:
        result = step.get("tool_result") or {}
        if not result.get("ok") or str(result.get("source") or "") not in {
            "mcp", "external_reality", "verified_external",
        }:
            return False
        hay = (
            f"{result.get('tool_id') or ''} "
            f"{result.get('mcp_tool_name') or ''}"
        ).lower()
        if any(token in hay for token in cls._quote_tool_tokens(brief)):
            return True
        return any(
            "last_done" in json.dumps(output, ensure_ascii=False).lower()
            or '"quotes"' in json.dumps(output, ensure_ascii=False).lower()
            for output in (result.get("outputs") or [])
            if isinstance(output, dict)
        )

    @classmethod
    def _has_quote_evidence(cls, brief: AgentBrief, session: Any) -> bool:
        return any(
            cls._step_looks_like_quote(step, brief) for step in session.steps
        )

    @staticmethod
    def _normalize_ticker(code: object) -> Tuple[str, str]:
        value = str(code or "").strip().upper()
        if not value:
            return ("", "")
        number, _, suffix = value.partition(".")
        number = number.lstrip("0") or "0"
        market = {
            "SS": "SH", "SH": "SH", "SZ": "SZ", "HK": "HK",
        }.get(suffix, suffix)
        return (number, market)

    @classmethod
    def _ticker_matches(cls, left: object, right: object) -> bool:
        (ln, lm), (rn, rm) = (
            cls._normalize_ticker(left), cls._normalize_ticker(right)
        )
        return bool(ln and rn and ln == rn and not (lm and rm and lm != rm))

    @classmethod
    def _result_assets(cls, result: Dict[str, Any]) -> set[str]:
        values: List[Any] = []
        for output in result.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            values.extend((
                output.get("subject_id"), output.get("symbol"),
                output.get("asset_id"),
            ))
            values.extend(output.get("symbols") or [])
            for row in output.get("quotes") or []:
                if isinstance(row, dict):
                    values.extend((row.get("symbol"), row.get("asset_id")))
        arguments = result.get("arguments") or result.get("request_parameters") or {}
        if isinstance(arguments, dict):
            values.append(arguments.get("symbol"))
            values.extend(arguments.get("symbols") or [])
        return {
            str(item).strip().upper()
            for item in values if item not in (None, "")
        }

    @classmethod
    def _result_matches_asset(
        cls, result: Dict[str, Any], asset_id: str,
    ) -> bool:
        if not asset_id:
            return True
        assets = cls._result_assets(result)
        return not assets or any(
            cls._ticker_matches(item, asset_id) for item in assets
        )

    @staticmethod
    def _ordered_asset_id(parsed: Dict[str, Any]) -> str:
        parameters = parsed.get("parameters") if isinstance(
            parsed.get("parameters"), dict,
        ) else {}
        return str(parameters.get("asset_id") or "").strip().upper()

    @classmethod
    def _research_categories_from_result(
        cls, result: Dict[str, Any], brief: AgentBrief, *, asset_id: str = "",
    ) -> set[str]:
        if not isinstance(result, dict) or not result.get("ok"):
            return set()
        if str(result.get("source") or "") not in {
            "mcp", "external_reality", "verified_external",
        } or (asset_id and not cls._result_matches_asset(result, asset_id)):
            return set()
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        token_map = dict(policy.get("research_category_tokens") or {})
        blob = json.dumps(result, ensure_ascii=False, default=str).lower()
        categories: set[str] = set()
        for output in result.get("outputs") or []:
            if not isinstance(output, dict):
                continue
            declared = output.get("research_categories") or []
            if isinstance(declared, str):
                declared = [declared]
            categories.update(str(item).strip() for item in declared if str(item).strip())
        for category, raw_tokens in token_map.items():
            tokens = raw_tokens if isinstance(raw_tokens, list) else [raw_tokens]
            if any(str(token).lower() in blob for token in tokens if str(token)):
                categories.add(str(category))
        if cls._step_looks_like_quote({"tool_result": result}, brief):
            categories.add("quote")
        return categories

    @classmethod
    def _prior_observation_matches_asset(
        cls, observation: Dict[str, Any], asset_id: str,
    ) -> bool:
        if not asset_id:
            return True
        subject = str(observation.get("subject_id") or "").strip()
        if not subject or cls._ticker_matches(subject, asset_id):
            return True
        normalized = observation.get("normalized_value") or {}
        if not isinstance(normalized, dict):
            return False
        assets = {
            str(item).strip().upper()
            for item in (
                [normalized.get("symbol"), normalized.get("asset_id")]
                + list(normalized.get("symbols") or [])
            )
            if item not in (None, "")
        }
        return bool(assets) and any(
            cls._ticker_matches(item, asset_id) for item in assets
        )

    @classmethod
    def _research_categories(
        cls, brief: AgentBrief, session: Any, *, asset_id: str = "",
    ) -> set[str]:
        categories: set[str] = set()
        for step in session.steps:
            categories.update(cls._research_categories_from_result(
                step.get("tool_result") or {}, brief, asset_id=asset_id,
            ))
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        for observation in policy.get("prior_verified_observations") or []:
            if not isinstance(observation, dict) or not cls._prior_observation_matches_asset(
                observation, asset_id,
            ):
                continue
            raw = observation.get("raw_value")
            if isinstance(raw, dict):
                categories.update(cls._research_categories_from_result(
                    raw, brief, asset_id=asset_id,
                ))
            normalized = observation.get("normalized_value") or {}
            if isinstance(normalized, dict):
                declared = normalized.get("research_categories") or []
                if isinstance(declared, str):
                    declared = [declared]
                categories.update(
                    str(item).strip() for item in declared if str(item).strip()
                )
        return categories

    @classmethod
    def _missing_research_categories(
        cls, parsed: Dict[str, Any], brief: AgentBrief, session: Any,
    ) -> List[str]:
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        requirements = dict(policy.get("research_requirements") or {})
        if not requirements.get("enabled"):
            return []
        action_id = str(parsed.get("action_id") or parsed.get("intent") or "").strip()
        trade_actions = {
            str(item) for item in (
                requirements.get("trade_actions") or ["buy_asset"]
            )
        }
        if action_id not in trade_actions:
            return []
        asset_id = cls._ordered_asset_id(parsed)
        categories = cls._research_categories(brief, session, asset_id=asset_id)
        missing: List[str] = []
        if requirements.get("require_quote") and "quote" not in categories:
            missing.append("quote")
        role_rules = dict(
            (requirements.get("by_agent") or {}).get(brief.agent_id) or {}
        )
        for category in role_rules.get("required") or []:
            if str(category) and str(category) not in categories:
                missing.append(str(category))
        for group in role_rules.get("any_of") or []:
            options = [str(item) for item in (group or []) if str(item)]
            if options and not any(item in categories for item in options):
                missing.append(options[0])
        declared = set(str(item) for item in (policy.get("research_category_tokens") or {}))
        non_quote = {
            item for item in categories
            if item != "quote" and (not declared or item in declared)
        }
        minimum = max(0, int(requirements.get("minimum_non_quote_categories", 0) or 0))
        if len(non_quote) < minimum:
            missing.append(f"non_quote_{minimum}")
        minimum_results = max(0, int(requirements.get("minimum_non_quote_results", 0) or 0))
        result_count = sum(
            bool(cls._research_categories_from_result(
                step.get("tool_result") or {}, brief, asset_id=asset_id,
            ) - {"quote"})
            for step in session.steps
        )
        for observation in policy.get("prior_verified_observations") or []:
            if not isinstance(observation, dict) or not cls._prior_observation_matches_asset(
                observation, asset_id,
            ):
                continue
            normalized = observation.get("normalized_value") or {}
            declared_categories = (
                normalized.get("research_categories") or []
                if isinstance(normalized, dict) else []
            )
            if isinstance(declared_categories, str):
                declared_categories = [declared_categories]
            prior = {str(item) for item in declared_categories if str(item)}
            raw = observation.get("raw_value") or {}
            if isinstance(raw, dict):
                prior.update(cls._research_categories_from_result(
                    raw, brief, asset_id=asset_id,
                ))
            if prior - {"quote"}:
                result_count += 1
        if result_count < minimum_results:
            missing.append(f"non_quote_results_{minimum_results}")
        return list(dict.fromkeys(missing))

    @classmethod
    def _verified_quote_identity(
        cls, brief: AgentBrief, session: Any, asset_id: str,
    ) -> Dict[str, Any]:
        if not asset_id:
            return {}
        name, price = "", None
        for step in session.steps:
            if not cls._step_looks_like_quote(step, brief):
                continue
            result = step.get("tool_result") or {}
            if not cls._result_matches_asset(result, asset_id):
                continue
            for output in result.get("outputs") or []:
                if not isinstance(output, dict):
                    continue
                rows = [row for row in output.get("quotes") or [] if isinstance(row, dict)]
                rows.append(output)
                for row in rows:
                    symbol = str(row.get("symbol") or row.get("asset_id") or "").strip()
                    if symbol and not cls._ticker_matches(symbol, asset_id):
                        continue
                    for key in ("name_cn", "name_zh", "name", "name_en", "display_name"):
                        candidate = str(row.get(key) or "").strip()
                        if candidate and not cls._ticker_matches(candidate, asset_id):
                            name = candidate
                            break
                    for key in ("last_done", "price", "current_price", "regularMarketPrice", "close"):
                        raw = row.get(key)
                        if raw in (None, ""):
                            continue
                        try:
                            price = float(raw)
                        except (TypeError, ValueError):
                            continue
                        break
        return {
            key: value for key, value in (("name", name), ("price", price))
            if value not in (None, "")
        }

    @staticmethod
    def _names_compatible(claimed: object, verified: object) -> bool:
        left, right = str(claimed or "").strip(), str(verified or "").strip()
        if not left or not right or left == right or left in right or right in left:
            return True
        for suffix in ("股份有限公司", "有限公司", "股份公司", "股份", "集团", "控股"):
            if left.endswith(suffix):
                left = left[:-len(suffix)]
            if right.endswith(suffix):
                right = right[:-len(suffix)]
        left, right = left.strip(), right.strip()
        return bool(left and right and (left == right or left in right or right in left))

    @classmethod
    def _trade_identity_mismatch(
        cls, parsed: Dict[str, Any], brief: AgentBrief, session: Any,
    ) -> str:
        action_id = str(parsed.get("action_id") or parsed.get("intent") or "").strip()
        if action_id not in {"buy_asset", "sell_asset"}:
            return ""
        parameters = parsed.get("parameters") if isinstance(parsed.get("parameters"), dict) else {}
        asset_id = cls._ordered_asset_id(parsed)
        if not asset_id:
            return ""
        quote = cls._verified_quote_identity(brief, session, asset_id)
        claimed_name = next((
            str(parameters.get(key) or "").strip()
            for key in ("asset_name", "name", "name_cn", "display_name", "security_name")
            if str(parameters.get(key) or "").strip()
        ), "")
        verified_name = str(quote.get("name") or "").strip()
        if claimed_name and verified_name and not cls._names_compatible(claimed_name, verified_name):
            return "asset_identity_mismatch"
        expected_price = None
        for key in ("expected_price", "limit_price", "reference_price"):
            try:
                if parameters.get(key) not in (None, ""):
                    expected_price = float(parameters[key])
                    break
            except (TypeError, ValueError):
                continue
        try:
            verified_price = float(quote.get("price") or 0)
        except (TypeError, ValueError):
            verified_price = 0.0
        if (
            expected_price is not None and verified_price > 0
            and abs(expected_price - verified_price) / verified_price > 0.08
        ):
            return "asset_price_identity_mismatch"
        return ""

    @classmethod
    def _degrade_trade_for_identity_mismatch(
        cls, parsed: Dict[str, Any], brief: AgentBrief, session: Any,
    ) -> None:
        reason_code = cls._trade_identity_mismatch(parsed, brief, session)
        if not reason_code:
            return
        english = str(
            (brief.raw_context or {}).get("scenario_locale")
            or (brief.raw_context or {}).get("audience_language")
            or ""
        ).lower().startswith("en")
        if reason_code == "asset_identity_mismatch":
            reason = (
                "The order company name does not match the verified quote; "
                "the system downgraded the action to wait to avoid buying the wrong asset."
                if english else "本拍下单的公司名称与已验证行情不一致，系统降级为观望，避免买错标的。"
            )
        else:
            reason = (
                "The order reference price is too far from the verified quote; "
                "the system downgraded the action to wait. Recalculate the quantity from the latest quote."
                if english else "本拍下单参考价与已验证行情偏差过大，系统降级为观望，请按最新行情重新估算数量。"
            )
        cls._degrade(parsed, reason)

    @classmethod
    def _ready_for_auto_quote(
        cls, parsed: Dict[str, Any], brief: AgentBrief, session: Any,
    ) -> bool:
        requirements = dict(
            ((brief.raw_context or {}).get("harness_policy", {}) or {}).get(
                "research_requirements"
            ) or {}
        )
        if not requirements.get("enabled"):
            return True
        action_id = str(parsed.get("action_id") or parsed.get("intent") or "").strip()
        if action_id not in {
            str(item) for item in (requirements.get("trade_actions") or ["buy_asset"])
        }:
            return False
        missing = cls._missing_research_categories(parsed, brief, session)
        return not missing or missing == ["quote"]

    @classmethod
    def _degrade_trade_for_missing_research(
        cls, parsed: Dict[str, Any], brief: AgentBrief, session: Any,
    ) -> None:
        missing = cls._missing_research_categories(parsed, brief, session)
        if missing:
            english = str(
                (brief.raw_context or {}).get("scenario_locale")
                or (brief.raw_context or {}).get("audience_language")
                or ""
            ).lower().startswith("en")
            cls._degrade(
                parsed,
                (
                    "Research evidence is incomplete this cycle (missing: "
                    + ", ".join(missing)
                    + "); the system downgraded the action to wait to prevent an unsupported trade."
                ) if english else (
                    "本拍研究证据未齐（缺少: " + "、".join(missing)
                    + "），系统降级为观望，避免无研究下单。"
                ),
            )

    @staticmethod
    def _degrade(parsed: Dict[str, Any], reason: str) -> None:
        parsed.update({
            "agent_loop_step": "final",
            "action_id": "wait_and_review",
            "intent": "wait_and_review",
            "text": reason,
            "character_monologue": reason[:40],
            "plan": reason,
        })
