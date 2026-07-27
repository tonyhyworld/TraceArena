"""Capital-market evidence and order normalization owned by this scenario."""
from __future__ import annotations

import json
from typing import Any, Dict, Optional

from app.core.interfaces import ActionPack
from app.core.interfaces import AgentBrief
from .market_evidence import CapitalMarketEvidencePolicy
from .market_order import CapitalMarketOrderPolicy


class CapitalMarketHarnessPolicy(
    CapitalMarketEvidencePolicy, CapitalMarketOrderPolicy,
):
    plugin_id = "capital_market_us.harness.v1"

    @staticmethod
    def _fallback_tool_id(token: str) -> str:
        token = str(token or "").strip()
        if token.startswith("mcp:"):
            return token
        aliases = {
            "us_quote": "mcp:longport:longport_quote",
            "us_valuation_metrics": "mcp:longport:longport_calc_indexes",
            "us_financial_statements": "mcp:us_market_research:us_financial_statements",
            "us_sec_filings": "mcp:us_market_research:us_sec_filings",
            "us_company_news": "mcp:us_market_research:us_company_material_events",
            "us_earnings_calendar": "mcp:us_market_research:us_earnings_calendar",
            "us_macro_indicators": "mcp:us_market_research:us_macro_indicators",
            "us_sector_indicators": "mcp:longport:longport_quote",
            "us_options_chain": "mcp:longport:longport_option_chain",
        }
        return aliases.get(token, f"mcp:longport:{token}")

    @staticmethod
    def _english(brief: AgentBrief) -> bool:
        return str(
            (brief.raw_context or {}).get("scenario_locale")
            or (brief.raw_context or {}).get("audience_language")
            or ""
        ).lower().startswith("en")

    def requires_more_work(
        self, runner: Any, parsed: Dict[str, Any],
        brief: AgentBrief, session: Any,
    ) -> bool:
        action_id = str(
            parsed.get("action_id") or parsed.get("intent") or ""
        ).strip()
        if (
            (brief.raw_context or {}).get("harness_policy", {}).get(
                "require_verified_quote"
            )
            and action_id in {"buy_asset", "sell_asset"}
            and not self._has_quote_evidence(brief, session)
        ):
            return True
        if action_id == "buy_asset" and not self._has_investment_plan(
            parsed, brief
        ):
            return True
        return bool(
            self._missing_research_categories(parsed, brief, session)
            or self._trade_identity_mismatch(parsed, brief, session)
        )

    def prepare_final(
        self, runner: Any, parsed: Dict[str, Any],
        brief: AgentBrief, session: Any,
    ) -> None:
        self._backfill_trade_fields_from_text(parsed)
        if self._missing_research_categories(parsed, brief, session):
            self._degrade_trade_for_missing_research(parsed, brief, session)
        if self._trade_identity_mismatch(parsed, brief, session):
            self._degrade_trade_for_identity_mismatch(parsed, brief, session)
        self._sanitize_incomplete_trade_final(parsed)

    def policy_satisfied(
        self, runner: Any, brief: AgentBrief, session: Any,
    ) -> bool:
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        if policy.get("require_verified_quote"):
            return self._has_quote_evidence(brief, session)
        return runner._has_trusted_external(brief, session)

    async def on_budget_exhausted(
        self, runner: Any, *, agent_id: str, tick: int,
        parsed: Dict[str, Any], brief: AgentBrief, session: Any,
        productive_steps: int,
    ) -> int:
        if (
            not self._has_quote_evidence(brief, session)
            and self._ready_for_auto_quote(parsed, brief, session)
            and await self._inject_preferred_quote(
                runner,
                agent_id=agent_id,
                tick=tick,
                brief=brief,
                session=session,
                productive_steps=productive_steps,
            )
        ):
            return 1
        return 0

    async def _inject_preferred_quote(
        self, runner: Any, *, agent_id: str, tick: int,
        brief: AgentBrief, session: Any, productive_steps: int,
    ) -> bool:
        if productive_steps >= session.max_steps:
            return False
        tool_id, arguments = self._resolve_preferred_quote_call(brief)
        if not tool_id:
            return False
        action = ActionPack(
            agent_id=agent_id,
            action_id="harness_auto_observation",
            parsed_ok=True,
            tool_request={"tool_id": tool_id, "arguments": arguments},
            attached_tool_id=tool_id,
        )
        step_no = len(session.steps) + 1
        written, result = await runner._execute_continue_step_resilient(
            action, tick, step_no,
        )
        runner._record_loop_tool_result(result)
        session.record_step(
            step_index=step_no,
            kind="execute_tool",
            raw_response="[scenario_injected_observation]",
            tool_result=result,
            workspace_written=written,
        )
        runner._emit_step_diagnostic(
            agent_id, tick, step_no, action, result, written,
        )
        return bool(result and result.ok)

    @staticmethod
    def _planned_symbols(brief: AgentBrief) -> list[str]:
        settlement = dict(
            (brief.raw_context or {}).get("agent_settlement_state") or {}
        )
        book = dict(settlement.get("investment_book") or {})
        theses = dict(book.get("theses") or {})
        return [
            str(asset_id) for asset_id, thesis in theses.items()
            if str(asset_id)
            and str((thesis or {}).get("status") or "")
            not in {"invalidated", "closed"}
        ]

    @classmethod
    def _resolve_preferred_quote_call(
        cls, brief: AgentBrief,
    ) -> tuple[str, Dict[str, Any]]:
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        preferred = [
            str(item).strip()
            for item in (
                policy.get("quote_tools")
                or policy.get("preferred_quote_tools")
                or ["longport_quote"]
            )
            if str(item).strip()
        ]
        capabilities = [
            item for item in (
                ((brief.raw_context or {}).get("agent_sandbox") or {}).get(
                    "capabilities"
                ) or []
            )
            if isinstance(item, dict)
            and str(item.get("status") or "") == "ready"
        ]
        symbols = cls._planned_symbols(brief)
        if not symbols:
            return "", {}
        for token in preferred:
            for capability in capabilities:
                hay = json.dumps(capability, ensure_ascii=False).lower()
                if token.lower() not in hay and "quote" not in hay:
                    continue
                tool_id = str(
                    (capability.get("invocation") or {}).get("tool_id")
                    or capability.get("capability_id") or ""
                )
                properties = (
                    (capability.get("input_schema") or {}).get("properties") or {}
                )
                if "symbols" in properties:
                    return tool_id, {"symbols": symbols[:4]}
                if "symbol" in properties:
                    return tool_id, {"symbol": symbols[0]}
                return tool_id, {}
        for token in preferred:
            name = cls._fallback_tool_id(token)
            if "quote" in name.lower():
                return name, {"symbols": symbols[:4]}
        return "", {}

    @staticmethod
    def _has_investment_plan(
        parsed: Dict[str, Any], brief: AgentBrief
    ) -> bool:
        parameters = dict(parsed.get("parameters") or {})
        asset_id = str(parameters.get("asset_id") or "")
        if not asset_id:
            return False
        settlement = dict(
            (brief.raw_context or {}).get("agent_settlement_state") or {}
        )
        theses = dict(
            (settlement.get("investment_book") or {}).get("theses") or {}
        )
        thesis = dict(theses.get(asset_id) or {})
        return bool(
            thesis
            and str(thesis.get("status") or "")
            not in {"invalidated", "closed"}
        )

    def degraded_final_reason(
        self, runner: Any, brief: AgentBrief, session: Any,
    ) -> str:
        if not self._has_quote_evidence(brief, session):
            if self._english(brief):
                return (
                    "No valid verified quote was obtained in this cycle; "
                    "the system downgraded the action to wait and preserved cash "
                    "for the next cycle."
                )
            return "本拍未能取得有效期内已验证行情，系统降级为观望，保留现金等待下一拍。"
        if self._english(brief):
            return (
                "The research step budget was reached; submit the current "
                "decision using the available evidence."
            )
        return "本拍研究步骤已达上限，按已有证据提交当前决策。"

    def enrich_final_action(
        self, runner: Any, action: Any, session: Any,
    ) -> None:
        parameters = dict(getattr(action, "parameters", None) or {})
        action_id = str(getattr(action, "action_id", "") or "")
        if action_id not in {"buy_asset", "sell_asset"}:
            return
        observations = list(parameters.get("harness_observations") or [])
        trusted = {"mcp", "external_reality", "verified_external"}
        chosen = str(parameters.get("price_evidence_ref") or "").strip()
        asset_id = str(parameters.get("asset_id") or "").strip()
        quote_identity: Dict[str, Any] = {}
        for observation in reversed(observations):
            tool_id = str(observation.get("tool_id") or "").lower()
            source = str(observation.get("source") or "").lower()
            if source not in trusted:
                continue
            if any(key in tool_id for key in ("quote", "candlestick", "chart", "price")):
                quote_identity = self._quote_identity_from_observation(
                    observation, asset_id,
                )
                chosen = chosen or str(observation.get("run_id") or "")
                if chosen and quote_identity:
                    break
        if not chosen:
            for observation in reversed(observations):
                if str(observation.get("source") or "") in trusted:
                    quote_identity = self._quote_identity_from_observation(
                        observation, asset_id,
                    )
                    chosen = str(observation.get("run_id") or "")
                    if chosen:
                        break
        if chosen:
            parameters["price_evidence_ref"] = chosen
            if chosen not in (action.evidence_refs or []):
                action.evidence_refs = list(action.evidence_refs or []) + [chosen]
        if quote_identity:
            if (
                quote_identity.get("name")
                and not str(parameters.get("asset_name") or "").strip()
            ):
                parameters["asset_name"] = str(quote_identity["name"])[:48]
            if (
                quote_identity.get("price") is not None
                and all(
                    parameters.get(key) in (None, "")
                    for key in ("expected_price", "limit_price", "reference_price")
                )
            ):
                parameters["expected_price"] = quote_identity["price"]
        action.parameters = parameters

    @classmethod
    def _quote_identity_from_observation(
        cls, observation: Dict[str, Any], asset_id: str,
    ) -> Dict[str, Any]:
        outputs = list(observation.get("outputs") or [])
        normalized = observation.get("normalized_value")
        if isinstance(normalized, dict):
            outputs.append(normalized)
        for output in reversed(outputs):
            if not isinstance(output, dict):
                continue
            identity = cls._quote_identity_from_payload(output, asset_id)
            if identity:
                return identity
        return {}

    @classmethod
    def _quote_identity_from_payload(
        cls, payload: Dict[str, Any], asset_id: str,
    ) -> Dict[str, Any]:
        for row in cls._iter_quote_rows(payload):
            row_asset = str(
                row.get("asset_id")
                or row.get("symbol")
                or row.get("subject_id")
                or row.get("id")
                or ""
            ).strip()
            if asset_id and row_asset and not cls._ticker_matches(row_asset, asset_id):
                continue
            price = cls._row_price(row)
            name = cls._row_name(row)
            if price is None and not name:
                continue
            identity: Dict[str, Any] = {}
            if price is not None:
                try:
                    identity["price"] = float(price)
                except (TypeError, ValueError):
                    pass
            if name:
                identity["name"] = name
            if identity:
                return identity
        return {}

    @classmethod
    def _iter_quote_rows(cls, value: Any, *, depth: int = 0) -> list[Dict[str, Any]]:
        if depth > 4:
            return []
        rows: list[Dict[str, Any]] = []
        if isinstance(value, dict):
            if cls._row_price(value) is not None:
                rows.append(value)
            for key in (
                "quotes", "securities", "static_info", "items", "data",
                "result", "results", "candlesticks",
            ):
                child = value.get(key)
                if isinstance(child, (dict, list)):
                    rows.extend(cls._iter_quote_rows(child, depth=depth + 1))
        elif isinstance(value, list):
            for item in value:
                if isinstance(item, (dict, list)):
                    rows.extend(cls._iter_quote_rows(item, depth=depth + 1))
        return rows

    @staticmethod
    def _row_price(row: Dict[str, Any]) -> Any:
        for key in (
            "price",
            "last_done",
            "current_price",
            "regularMarketPrice",
            "close",
        ):
            if row.get(key) is not None:
                return row.get(key)
        return None

    @staticmethod
    def _row_name(row: Dict[str, Any]) -> str:
        for key in (
            "name_cn",
            "name_zh",
            "name",
            "name_en",
            "shortName",
            "longName",
            "display_name",
        ):
            text = str(row.get(key) or "").strip()
            if text:
                return text
        return ""

    def feedback_summary(
        self, runner: Any, session: Any, brief: AgentBrief,
        parsed: Optional[Dict[str, Any]], attempt: int,
    ) -> str:
        policy = dict((brief.raw_context or {}).get("harness_policy", {}) or {})
        missing = self._missing_research_categories(parsed or {}, brief, session)
        failures = []
        sandbox_failed = False
        for step in reversed(session.steps):
            result = step.get("tool_result") or {}
            if str(result.get("source") or "") == "scenario_harness_policy":
                continue
            if result.get("errors"):
                failures.append(
                    "上一步 " + str(result.get("source") or "工具") + " 失败："
                    + "；".join(str(item) for item in result["errors"][:3])
                )
                sandbox_failed = str(result.get("source") or "") == "agent_sandbox"
            break
        capabilities = [
            item for item in (
                ((brief.raw_context or {}).get("agent_sandbox") or {}).get(
                    "capabilities"
                ) or []
            )
            if isinstance(item, dict)
            and str(item.get("status") or "") == "ready"
            and str((item.get("invocation") or {}).get("operation") or "")
            != "install_skill"
        ]
        example = ""
        if capabilities:
            capability = next((
                item for item in capabilities
                if "quote" in json.dumps(item, ensure_ascii=False).lower()
            ), capabilities[0])
            tool_id = str(
                (capability.get("invocation") or {}).get("tool_id")
                or capability.get("capability_id") or ""
            )
            schema = capability.get("input_schema") or {}
            properties = schema.get("properties") or {}
            arguments = {
                key: f"<请填写 {key}>" for key in schema.get("required") or []
            }
            symbols = self._planned_symbols(brief)
            if "symbols" in properties and symbols:
                arguments["symbols"] = symbols[:4]
            elif "symbol" in properties and symbols:
                arguments["symbol"] = symbols[0]
            elif "symbols" in properties:
                arguments["symbols"] = ["AAPL.US"]
            elif "symbol" in properties:
                arguments["symbol"] = "AAPL.US"
            example = json.dumps({
                "agent_loop_step": "continue",
                "tool_request": {"tool_id": tool_id, "arguments": arguments},
            }, ensure_ascii=False)
        elif policy.get("preferred_tools") and self._planned_symbols(brief):
            name = str(policy["preferred_tools"][0])
            tool_id = self._fallback_tool_id(name)
            example = json.dumps({
                "agent_loop_step": "continue",
                "tool_request": {
                    "tool_id": tool_id,
                    "arguments": {
                        "symbols": self._planned_symbols(brief)[:4]
                    },
                },
            }, ensure_ascii=False)
        identity = self._trade_identity_mismatch(parsed or {}, brief, session)
        role_policy = dict(
            (
                ((brief.raw_context or {}).get("investment_policy") or {})
                .get("by_agent") or {}
            ).get(brief.agent_id) or {}
        )
        hints = []
        english = self._english(brief)
        if failures:
            hints.append(failures[0])
        if attempt >= 2:
            hints.append((
                f"Reminder {attempt}: if the same path keeps failing, switch to "
                "another immediately available tool."
            ) if english else (
                f"第 {attempt} 次提醒：同一路线连续失败时应切换到其他即刻可用工具。"
            ))
        if sandbox_failed:
            hints.append(
                "The sandbox may be unavailable; use discovered external tools."
                if english else "沙箱运行环境可能故障，请改用已发现的外部工具。"
            )
        if missing:
            labels = dict(policy.get("research_category_labels") or {})
            missing_text = ", ".join(str(labels.get(item) or item) for item in missing)
            hints.append(
                f"Current trade research is still missing: {missing_text}."
                if english else "当前交易研究仍缺少：" + missing_text.replace(", ", "、") + "。"
            )
        elif runner._has_trusted_external(brief, session):
            hints.append((
                "This cycle already has trusted external facts; if the thesis, "
                "counter-evidence, sizing, entry trigger, exit discipline, and "
                "style check are complete, submit the final action."
            ) if english else (
                "本拍已有可信外部事实；如果论点、反证、仓位、入场触发、"
                "退出条件和风格自检已经完整，可以提交最终行动。"
            ))
            if self._planned_symbols(brief):
                hints.append((
                    "If an InvestmentBook thesis is active, monitoring, or "
                    "entry-ready, and the verified quote satisfies entry_price_max "
                    "inside the simulated trading window, submit buy_asset with "
                    "asset_id, quantity, and the quote evidence reference. Do not "
                    "repeat update_investment_plan or wait_and_review when the "
                    "entry trigger is already met."
                ) if english else (
                    "如果 InvestmentBook 论点已处于 active、monitoring 或待入场状态，"
                    "且已验证行情满足 entry_price_max，并且在模拟交易窗口内，"
                    "应提交 buy_asset，写明 asset_id、quantity 和行情证据引用；"
                    "入场触发已满足时不要重复 update_investment_plan 或 wait_and_review。"
                ))
        if identity == "asset_identity_mismatch":
            hints.append(
                "The order company name does not match the verified quote; check the ticker and name."
                if english else "订单公司名称与已验证行情不一致，请核对代码与名称。"
            )
        elif identity == "asset_price_identity_mismatch":
            hints.append(
                "The order reference price is too far from the verified quote; recalculate from the latest price."
                if english else "订单参考价与已验证行情偏差过大，请按最新现价重新估算。"
            )
        if (
            str((parsed or {}).get("action_id") or "") == "buy_asset"
            and not self._has_investment_plan(parsed or {}, brief)
        ):
            hints.append((
                "This asset has no authoritative InvestmentBook plan yet; submit "
                "update_investment_plan first with thesis, counter-evidence, "
                "target weight, entry trigger, exit condition, and style check. "
                "Place any buy order in a later cycle."
            ) if english else (
                "该标的尚无权威 InvestmentBook 计划；本拍应先提交 "
                "update_investment_plan，结构化写入论点、反证、目标仓位、"
                "入场触发、退出条件与风格自检，下一拍再下单。"
            ))
        if not runner._has_trusted_external(brief, session):
            hints.append((
                "There are not enough trusted external facts yet; continue research "
                "until the result has source, timestamp, and evidence ID."
            ) if english else (
                "当前还没有满足策略要求的可信外部事实，不能结束研究；"
                "取得带来源、时间和证据 ID 的结果后再提交最终行动。"
            ))
        hints.append((
            "Investment plan status accepts candidate / monitoring / active / "
            "invalidated / closed. Natural words such as watch/research/prepare_buy "
            "are normalized by the ledger, but target_weight_pct must stay within "
            "this role's single-position limit."
        ) if english else (
            "投资计划 status 可用标准值 candidate / monitoring / active / "
            "invalidated / closed；自然词 watch/research/prepare_buy 会被账本归一化，"
            "但 target_weight_pct 必须不超过本角色单票上限。"
        ))
        if role_policy:
            limits = []
            if role_policy.get("style"):
                limits.append(
                    f"style={role_policy['style']}" if english
                    else f"策略风格={role_policy['style']}"
                )
            if role_policy.get("max_single_position_pct") is not None:
                limits.append((
                    f"single-position limit={role_policy['max_single_position_pct']}%"
                    if english else f"单票上限={role_policy['max_single_position_pct']}%"
                ))
            if role_policy.get("min_cash_pct") is not None:
                limits.append(
                    f"minimum cash={role_policy['min_cash_pct']}%" if english
                    else f"最低现金={role_policy['min_cash_pct']}%"
                )
            if limits:
                hints.append(
                    "Current role hard limits: " + ", ".join(limits) + "."
                    if english else "当前角色硬约束：" + "，".join(limits) + "。"
                )
        if example:
            hints.append(("You can call directly: " if english else "可直接调用：") + example)
        return " ".join(hints)


def create_plugin() -> CapitalMarketHarnessPolicy:
    return CapitalMarketHarnessPolicy()
