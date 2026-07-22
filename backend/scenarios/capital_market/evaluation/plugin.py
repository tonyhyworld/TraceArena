"""Capital-market settlement owned by the scenario, not AI World OS."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.contracts.os2 import SettlementAuthority, SettlementRecord, WorldEvent
from app.engine.evaluation.settlement import SettlementContext


@dataclass
class PortfolioAccount:
    cash: float
    initial_value: float
    peak_value: float
    max_drawdown_pct: float = 0.0
    positions: Dict[str, float] = field(default_factory=dict)
    orders: List[Dict[str, object]] = field(default_factory=list)


class CapitalMarketSettlementPlugin:
    plugin_id = "capital_market.portfolio.v2"

    def __init__(self) -> None:
        self._accounts: Dict[str, PortfolioAccount] = {}
        self._prices: Dict[str, float] = {}
        self._asset_names: Dict[str, str] = {}
        self._last_event_refs: List[str] = []
        self._event_observations: Dict[str, List[str]] = {}
        # 上一拍面向展示的账本快照：用于识别「零变化」静默结算
        self._last_presentation_snapshot: Dict[str, Tuple[Any, ...]] = {}

    def settle(
        self,
        events: Sequence[WorldEvent],
        context: SettlementContext,
    ) -> List[SettlementRecord]:
        if not events:
            return []
        self._ensure_accounts(context)
        for event in events:
            if event.event_id not in self._last_event_refs:
                self._last_event_refs.append(event.event_id)
            self._event_observations[event.event_id] = list(
                event.observation_refs
            )
        verified_refs = self._ingest_verified_prices(context)
        affected = set()
        filled = set()
        rejected: List[SettlementRecord] = []
        has_market_close = False
        for event in events:
            if event.event_type == "trade_executed" and event.actor_id:
                self._apply_trade(event)
                affected.add(event.actor_id)
                filled.add(str(event.actor_id))
            elif event.event_type == "action_resolved" and event.actor_id:
                applied, reason = self._apply_resolved_action(event, context)
                if applied:
                    affected.add(event.actor_id)
                    filled.add(str(event.actor_id))
                elif str(event.deltas.get("action_type") or "") in {
                    "buy_asset", "sell_asset"
                }:
                    rejected.append(self._rejection_record(event, reason, context))
            elif event.event_type == "market_price_closed":
                self._apply_market_close(event)
                has_market_close = True
        if has_market_close or verified_refs:
            affected.update(self._accounts)
        if not affected:
            return rejected

        refs = [event.event_id for event in events]
        return rejected + [
            self._record(
                agent_id,
                refs,
                context,
                final=False,
                had_fill=str(agent_id) in filled,
            )
            for agent_id in sorted(affected)
            if agent_id in self._accounts
        ]

    def _apply_resolved_action(
        self, event: WorldEvent, context: SettlementContext
    ) -> Tuple[bool, str]:
        action_type = str(event.deltas.get("action_type") or "")
        outcome = str(event.deltas.get("outcome") or "")
        if action_type not in ("buy_asset", "sell_asset") or outcome != "accepted":
            return False, "not_trade_action"
        parameters = event.deltas.get("parameters") or {}
        if not isinstance(parameters, dict):
            return False, "parameters_missing"
        quantity = parameters.get("quantity")
        price_evidence_ref = str(parameters.get("price_evidence_ref") or "")
        clock_phase = self._market_phase(context)
        if clock_phase and not bool(clock_phase.get("tradable", False)):
            return False, "trading_window_closed"
        verified_prices = dict(context.world_state.get("verified_market_prices", {}) or {})
        validity_ticks = int(context.world_state.get("evidence_validity_ticks", 0) or 0)
        for observation in context.world_state.get("external_observations", []) or []:
            if not isinstance(observation, dict):
                continue
            if observation.get("verification_status") != "verified":
                continue
            observed_tick = int(observation.get("world_tick", -1) or -1)
            if validity_ticks > 0:
                if observed_tick < context.world_tick - validity_ticks:
                    continue
                if observed_tick > context.world_tick:
                    continue
            elif observed_tick != context.world_tick:
                continue
            normalized = observation.get("normalized_value") or {}
            observation_id = str(observation.get("observation_id") or "")
            if observation_id:
                verified_prices[observation_id] = normalized
        requested_asset = str(
            parameters.get("asset_id")
            or (event.target_ids[0] if event.target_ids else "")
        )
        universe = dict(context.world_state.get("trading_universe") or {})
        allowed_markets = {
            str(item).strip().upper()
            for item in (universe.get("allowed_markets") or [])
            if str(item).strip()
        }
        if allowed_markets:
            _, requested_market = self._normalize_ticker(requested_asset)
            if requested_market not in allowed_markets:
                return False, str(
                    universe.get("reject_reason") or "asset_market_not_allowed"
                )
        verified_quote = (
            verified_prices.get(price_evidence_ref)
            if isinstance(verified_prices, dict) and price_evidence_ref else None
        )
        selected_ref = price_evidence_ref
        if isinstance(verified_quote, dict):
            if (
                price_evidence_ref not in event.evidence_refs
                and price_evidence_ref not in event.observation_refs
            ):
                return False, "verified_price_evidence_missing"
        else:
            selected_ref, verified_quote = self._latest_verified_quote_for_asset(
                context, requested_asset,
            )
        if not isinstance(verified_quote, dict):
            return False, "verified_price_evidence_missing"
        selected_quote = self._select_quote(verified_quote, requested_asset)
        # 指定证据解析不出标的价时，回退到有效期内该标的最近一条可解析行情
        if selected_quote.get("price") is None and requested_asset:
            alt_ref, alt_payload = self._latest_verified_quote_for_asset(
                context, requested_asset,
            )
            if isinstance(alt_payload, dict):
                alt_selected = self._select_quote(alt_payload, requested_asset)
                if alt_selected.get("price") is not None:
                    selected_ref = alt_ref or selected_ref
                    verified_quote = alt_payload
                    selected_quote = alt_selected
        price = selected_quote.get("price")
        asset_id = str(selected_quote.get("asset_id") or requested_asset)
        if quantity is None:
            return False, "quantity_missing"
        if not asset_id:
            return False, "asset_missing"
        if price is None:
            # 价格证据里没有能和下单代码对上的价格（多为代码格式不一致）
            return False, "price_lookup_failed"
        identity_reason = self._asset_identity_mismatch(
            parameters, selected_quote, asset_id,
        )
        if identity_reason:
            return False, identity_reason
        try:
            signed_quantity = float(quantity)
        except (TypeError, ValueError):
            return False, "quantity_not_numeric"
        if signed_quantity <= 0:
            return False, "quantity_must_be_positive"
        account = self._accounts.get(str(event.actor_id))
        if account is None:
            return False, "portfolio_account_missing"
        requirements = dict(
            context.world_state.get("research_requirements") or {}
        )
        if action_type == "buy_asset" and requirements.get("enabled"):
            apply_to_new = bool(
                requirements.get("apply_to_new_positions", True)
            )
            needs_gate = (
                account.positions.get(asset_id, 0.0) <= 0
                if apply_to_new else not account.positions
            )
            if needs_gate:
                missing, research_refs = self._research_evidence_gaps(
                    event, context, asset_id, requirements,
                )
                if missing:
                    return False, "research_evidence_missing:" + ",".join(missing)
                if research_refs:
                    linked = list(event.observation_refs or [])
                    for ref in research_refs:
                        if ref not in linked:
                            linked.append(ref)
                    try:
                        event.observation_refs = linked
                    except Exception:
                        pass
        reference_price = float(price)
        fx = self._fx_multiplier(asset_id, context)
        costs = dict(context.world_state.get("transaction_costs") or {})
        commission_bps = float(costs.get("commission_bps", 0.0) or 0.0)
        slippage_bps = float(costs.get("slippage_bps", 0.0) or 0.0)
        minimum_commission = float(costs.get("minimum_commission", 0.0) or 0.0)
        slippage_rate = slippage_bps / 10000.0
        fill_price = reference_price * (
            1.0 + slippage_rate if action_type == "buy_asset"
            else 1.0 - slippage_rate
        )
        gross_notional = signed_quantity * fill_price * fx
        commission = max(
            minimum_commission,
            gross_notional * commission_bps / 10000.0,
        )
        if action_type == "buy_asset" and gross_notional + commission > account.cash:
            return False, "insufficient_cash"
        if action_type == "sell_asset":
            if signed_quantity > account.positions.get(asset_id, 0.0):
                return False, "insufficient_position"
            signed_quantity = -signed_quantity
        if selected_ref:
            refs = self._event_observations.setdefault(event.event_id, [])
            if selected_ref not in refs:
                refs.append(selected_ref)
            # 同步挂到事件 observation_refs，供 SettlementRuntime 校验子集关系
            linked = list(event.observation_refs or [])
            if selected_ref not in linked:
                linked.append(selected_ref)
                try:
                    event.observation_refs = linked
                except Exception:
                    pass
        cash_change = (
            -(gross_notional + commission)
            if action_type == "buy_asset"
            else gross_notional - commission
        )
        synthetic = event.model_copy(update={
            "event_type": "trade_executed",
            "target_ids": [asset_id],
            "observation_refs": list(
                dict.fromkeys(
                    list(event.observation_refs or [])
                    + ([selected_ref] if selected_ref else [])
                )
            ),
            "deltas": {
                "asset_id": asset_id,
                "action_type": action_type,
                "quantity_change": signed_quantity,
                "price": fill_price,
                "reference_price": reference_price,
                "mark_price": reference_price,
                "cash_change": cash_change,
                "fx_multiplier": fx,
                "gross_notional": gross_notional,
                "commission": commission,
                "slippage_cost": abs(fill_price - reference_price)
                * abs(signed_quantity) * fx,
                "slippage_bps": slippage_bps,
                "price_evidence_ref": selected_ref,
                "market_phase": clock_phase,
            },
        })
        self._apply_trade(synthetic)
        return True, ""

    @staticmethod
    def _observation_research_categories(
        observation: Dict[str, Any],
        requirements: Dict[str, Any],
    ) -> set[str]:
        normalized = observation.get("normalized_value") or {}
        categories: set[str] = set()
        if isinstance(normalized, dict):
            declared = normalized.get("research_categories") or []
            if isinstance(declared, str):
                declared = [declared]
            categories.update(
                str(item).strip() for item in declared if str(item).strip()
            )
        blob = str(observation).lower()
        for category, raw_tokens in dict(
            requirements.get("category_tokens") or {}
        ).items():
            tokens = raw_tokens if isinstance(raw_tokens, list) else [raw_tokens]
            if any(str(token).lower() in blob for token in tokens if str(token)):
                categories.add(str(category))
        declared_domains = set(
            str(item) for item in (
                requirements.get("category_tokens") or {}
            )
        )
        return (
            {item for item in categories if item in declared_domains}
            if declared_domains else categories
        )

    @staticmethod
    def _observation_assets(observation: Dict[str, Any]) -> set[str]:
        values: List[Any] = [observation.get("subject_id")]
        normalized = observation.get("normalized_value") or {}
        if isinstance(normalized, dict):
            values.extend([
                normalized.get("subject_id"),
                normalized.get("symbol"),
                normalized.get("asset_id"),
            ])
            values.extend(normalized.get("symbols") or [])
        out = {
            str(value).strip().upper()
            for value in values
            if value not in (None, "")
        }
        return {
            item[:-3] + ".SH" if item.endswith(".SS") else item
            for item in out
        }

    def _research_evidence_gaps(
        self,
        event: WorldEvent,
        context: SettlementContext,
        asset_id: str,
        requirements: Dict[str, Any],
    ) -> Tuple[List[str], List[str]]:
        actor_id = str(event.actor_id or "")
        current_tick = int(context.world_tick)
        validity = int(
            context.world_state.get("research_evidence_validity_ticks", 0) or 0
        )
        linked_refs = set(event.evidence_refs or []) | set(
            event.observation_refs or []
        )
        categories: set[str] = set()
        used_refs: List[str] = []
        result_count = 0
        asset_bound = {
            "financials", "cash_flow", "valuation", "news",
            "catalyst", "fund_flow",
        }
        requested = asset_id.upper().replace(".SS", ".SH")
        for observation in (
            context.world_state.get("external_observations", []) or []
        ):
            if not isinstance(observation, dict):
                continue
            if observation.get("verification_status") != "verified":
                continue
            age = current_tick - int(
                observation.get("world_tick", current_tick) or current_tick
            )
            if age < 0 or (validity > 0 and age > validity):
                continue
            raw = observation.get("raw_value") or {}
            owner_id = (
                str(raw.get("owner_id") or "")
                if isinstance(raw, dict) else ""
            )
            observation_id = str(observation.get("observation_id") or "")
            if owner_id and owner_id != actor_id:
                continue
            if not owner_id and observation_id not in linked_refs:
                continue
            found = self._observation_research_categories(
                observation, requirements,
            ) - {"quote"}
            assets = self._observation_assets(observation)
            # 研究工具常返回无后缀代码（002185），订单用 002185.SZ——必须软匹配
            if assets and not any(
                self._ticker_matches(item, requested) for item in assets
            ):
                found -= asset_bound
            if not found:
                continue
            categories.update(found)
            result_count += 1
            if observation_id:
                used_refs.append(observation_id)

        role_rules = dict(
            (requirements.get("by_agent") or {}).get(actor_id) or {}
        )
        missing: List[str] = []
        for category in role_rules.get("required") or []:
            category = str(category)
            if category and category not in categories:
                missing.append(category)
        for group in role_rules.get("any_of") or []:
            options = [str(item) for item in (group or []) if str(item)]
            if options and not any(item in categories for item in options):
                missing.append(options[0])
        minimum_categories = max(
            0, int(requirements.get("minimum_non_quote_categories", 0) or 0)
        )
        if len(categories) < minimum_categories:
            missing.append(f"non_quote_{minimum_categories}")
        minimum_results = max(
            0, int(requirements.get("minimum_non_quote_results", 0) or 0)
        )
        if result_count < minimum_results:
            missing.append(f"non_quote_results_{minimum_results}")
        return list(dict.fromkeys(missing)), list(dict.fromkeys(used_refs))

    def _ingest_verified_prices(self, context: SettlementContext) -> List[str]:
        refs: List[str] = []
        for observation in context.world_state.get("external_observations", []) or []:
            if not isinstance(observation, dict):
                continue
            if observation.get("verification_status") != "verified":
                continue
            validity_ticks = int(context.world_state.get("evidence_validity_ticks", 0) or 0)
            observed_tick = int(observation.get("world_tick", -1) or -1)
            if validity_ticks > 0:
                if observed_tick < context.world_tick - validity_ticks:
                    continue
                if observed_tick > context.world_tick:
                    continue
            elif observed_tick != context.world_tick:
                continue
            observation_id = str(observation.get("observation_id") or "")
            normalized = observation.get("normalized_value") or {}
            if not observation_id or not isinstance(normalized, dict):
                continue
            ingested = False
            for quote in self._extract_quotes(normalized, ""):
                asset_id = str(quote.get("asset_id") or "")
                price = quote.get("price")
                if asset_id and price is not None:
                    self._prices[asset_id] = float(price)
                    ingested = True
                if asset_id and quote.get("name"):
                    self._remember_asset_name(asset_id, quote.get("name"))
            self._ingest_asset_names(normalized)
            if ingested:
                refs.append(observation_id)
        return refs

    def _remember_asset_name(self, asset_id: str, name: object) -> None:
        cleaned = self._clean_asset_name(name, asset_id)
        if cleaned:
            self._asset_names[str(asset_id)] = cleaned

    def _lookup_asset_name(self, asset_id: str) -> str:
        direct = self._asset_names.get(asset_id)
        if direct:
            return direct
        for known_id, name in self._asset_names.items():
            if self._ticker_matches(known_id, asset_id):
                return name
        return ""

    @classmethod
    def _clean_asset_name(cls, name: object, asset_id: str = "") -> str:
        text = str(name or "").strip()
        if not text:
            return ""
        aid = str(asset_id or "").strip()
        if aid and text.upper() == aid.upper():
            return ""
        if aid and cls._ticker_matches(text, aid):
            return ""
        return text[:48]

    @classmethod
    def _row_name(cls, row: Dict[str, object]) -> str:
        for key in (
            "name_cn",
            "name_zh",
            "name",
            "name_en",
            "shortName",
            "longName",
            "display_name",
        ):
            val = row.get(key)
            cleaned = cls._clean_asset_name(val)
            if cleaned:
                return cleaned
        return ""

    def _ingest_asset_names(self, payload: Dict[str, object]) -> None:
        if not isinstance(payload, dict):
            return
        names = payload.get("names")
        if isinstance(names, dict):
            for asset_id, name in names.items():
                self._remember_asset_name(str(asset_id), name)
        for key in ("static_info", "securities"):
            rows = payload.get(key)
            if not isinstance(rows, list):
                continue
            for row in rows:
                if not isinstance(row, dict):
                    continue
                asset_id = self._row_asset(row)
                name = self._row_name(row)
                if asset_id and name:
                    self._remember_asset_name(asset_id, name)
        meta = None
        data = payload.get("data")
        if isinstance(data, dict):
            chart = data.get("chart")
            if isinstance(chart, dict):
                results = chart.get("result") or []
                if results and isinstance(results[0], dict):
                    meta = results[0].get("meta")
        if isinstance(meta, dict):
            asset_id = str(meta.get("symbol") or "")
            name = self._row_name(meta)
            if asset_id and name:
                self._remember_asset_name(asset_id, name)

    def _rejection_record(
        self,
        event: WorldEvent,
        reason: str,
        context: SettlementContext,
    ) -> SettlementRecord:
        raw_order = dict(event.deltas.get("parameters") or {})
        # 拒单详情只保留订单字段；harness 工具原文另有观测链路可追溯
        order = {
            key: raw_order.get(key)
            for key in (
                "asset_id",
                "asset_name",
                "quantity",
                "expected_price",
                "limit_price",
                "price_evidence_ref",
            )
            if key in raw_order
        }
        account = self._accounts.get(str(event.actor_id))
        req_code = order.get("asset_id") or "?"
        labels = {
            "parameters_missing": "订单缺少 parameters",
            "verified_price_evidence_missing": (
                "订单没有引用有效期内的已验证行情——请先获取该标的实时价格再下单"
            ),
            "price_lookup_failed": (
                f"找不到与下单代码 {req_code} 匹配的已验证价格。请核对代码格式"
                "（A股用 600036.SH / 000858.SZ，港股用 00700.HK），"
                "或先为该标的取一条实时行情作为价格证据"
            ),
            "quantity_missing": "订单缺少数量 quantity",
            "asset_missing": "订单缺少标的代码 asset_id",
            "quantity_not_numeric": "订单数量不是有效数字",
            "quantity_must_be_positive": "订单数量必须大于零",
            "portfolio_account_missing": "组合账户不存在",
            "insufficient_cash": (
                f"现金不足，订单未成交（当前可用现金 {account.cash:.0f}）。请减小数量或选更低价标的"
                if account else "现金不足，订单未成交"
            ),
            "insufficient_position": "持仓不足，卖单未成交",
            "trading_window_closed": (
                "当前是盘前或收盘阶段，不能下单——请在开盘或盘中交易窗口提交订单"
            ),
            "asset_market_not_allowed": (
                "订单标的不在本场景允许的 A 股/港股交易范围内，订单未成交"
            ),
            "asset_identity_mismatch": (
                f"订单声称的公司名称与代码 {req_code} 的已验证行情不一致，"
                "请核对代码与名称后再下单"
            ),
            "asset_price_identity_mismatch": (
                f"订单参考价与代码 {req_code} 的已验证行情偏差过大，"
                "请按最新行情重新估算数量后再下单"
            ),
        }
        if reason.startswith("research_evidence_missing:"):
            raw_missing = reason.partition(":")[2].split(",")
            category_labels = {
                "financials": "目标公司的结构化财务报表",
                "cash_flow": "公司现金流",
                "valuation": "估值指标",
                "news": "公司财经新闻",
                "catalyst": "公告或新闻催化剂",
                "macro": "宏观经济指标",
                "industry": "行业景气或供需",
                "fund_flow": "资金流或盘口",
                "non_quote_2": "至少两类非行情研究证据",
                "non_quote_results_2": "至少两次非行情研究工具调用",
            }
            readable = [
                category_labels.get(item, item)
                for item in raw_missing if item
            ]
            labels[reason] = (
                "建仓研究不完整，订单未成交。仍缺少："
                + "、".join(readable)
                + "。请继续调用对应研究工具，并引用可验证结果后再下单"
            )
        return SettlementRecord(
            settlement_id=f"capital_market:{event.actor_id}:order_rejected:{context.world_tick}",
            run_id=context.run_id,
            scenario_id=context.scenario_id,
            world_tick=context.world_tick,
            evaluator_id=self.plugin_id,
            authority=SettlementAuthority(
                mode="deterministic_verifier",
                provider_id="portfolio_order_validator",
                verifier_id="portfolio_order_validator",
                rule_version="capital_market.order_validation.v1",
                reproducible=True,
                deterministic=True,
            ),
            kind="deterministic",
            subject_ids=[str(event.actor_id)],
            source_event_refs=[event.event_id],
            rule_refs=["capital_market.order_validation.v1"],
            outcome="order_rejected",
            values={"accepted": 0.0},
            details={
                "reason_code": reason,
                "requested_order": order,
            },
            explanation=labels.get(reason, f"订单未成交：{reason}"),
            affects_world=False,
            affects_victory=False,
        )

    @staticmethod
    def _normalize_ticker(code: object) -> Tuple[str, str]:
        """把 A股/港股代码归一为 (数字主体, 市场)，便于容错匹配。

        A股上海：600036.SH ≡ 600036.SS ≡ 600036 → ('600036','SH')
        A股深圳：000858.SZ → ('858','SZ')（去前导零）
        港股：   00700.HK ≡ 0700.HK → ('700','HK')
        """
        s = str(code or "").strip().upper()
        if not s:
            return ("", "")
        num, _, suf = s.partition(".")
        num = num.lstrip("0") or "0"
        market = {"SS": "SH", "SH": "SH", "SZ": "SZ", "HK": "HK"}.get(suf, suf)
        return (num, market)

    @classmethod
    def _ticker_matches(cls, a: object, b: object) -> bool:
        """两个代码是否指同一标的（容错 .SH/.SS、港股前导零等格式差异）。"""
        (na, ma), (nb, mb) = cls._normalize_ticker(a), cls._normalize_ticker(b)
        if not na or not nb or na != nb:
            return False
        if ma and mb and ma != mb:
            return False
        return True

    @staticmethod
    def _row_price(row: Dict[str, object]) -> object:
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
    def _row_asset(row: Dict[str, object], fallback: str = "") -> str:
        return str(
            row.get("asset_id")
            or row.get("symbol")
            or row.get("id")
            or fallback
            or ""
        )

    @classmethod
    def _identity_matches(
        cls, identity: object, requested_asset: str
    ) -> bool:
        if not requested_asset or identity in (None, ""):
            return False
        if cls._ticker_matches(identity, requested_asset):
            return True
        return str(identity).strip().lower() == requested_asset.strip().lower()

    @classmethod
    def _names_compatible(cls, claimed: object, verified: object) -> bool:
        """中文公司名是否同指一家（子串或去掉公司形态后缀后仍重合）。"""
        left = str(claimed or "").strip()
        right = str(verified or "").strip()
        if not left or not right:
            return True
        if left == right or left in right or right in left:
            return True
        # 只剥公司形态后缀，保留「科技/光电/银行」等行业词以免误判
        suffixes = ("股份有限公司", "有限公司", "股份公司", "股份", "集团", "控股")
        a, b = left, right
        for suffix in suffixes:
            if a.endswith(suffix):
                a = a[: -len(suffix)]
            if b.endswith(suffix):
                b = b[: -len(suffix)]
        a, b = a.strip(), b.strip()
        if not a or not b:
            return False
        return a == b or a in b or b in a

    def _claimed_asset_name(self, parameters: Dict[str, Any]) -> str:
        for key in (
            "asset_name", "name", "name_cn", "display_name", "security_name",
        ):
            cleaned = self._clean_asset_name(parameters.get(key))
            if cleaned:
                return cleaned
        return ""

    def _asset_identity_mismatch(
        self,
        parameters: Dict[str, Any],
        selected_quote: Dict[str, object],
        asset_id: str,
    ) -> str:
        """订单声称的名称/预估价与已验证行情不一致时拒单。"""
        verified_name = self._clean_asset_name(
            selected_quote.get("name"), asset_id,
        ) or self._lookup_asset_name(asset_id)
        claimed_name = self._claimed_asset_name(parameters)
        if (
            claimed_name
            and verified_name
            and not self._names_compatible(claimed_name, verified_name)
        ):
            return "asset_identity_mismatch"
        expected_price = None
        for key in ("expected_price", "limit_price", "reference_price"):
            raw = parameters.get(key)
            if raw in (None, ""):
                continue
            try:
                expected_price = float(raw)
            except (TypeError, ValueError):
                continue
            break
        quote_price = selected_quote.get("price")
        if expected_price is not None and quote_price is not None:
            try:
                verified = float(quote_price)
            except (TypeError, ValueError):
                verified = 0.0
            # Keep settlement aligned with the Agent Loop preflight: a
            # same-tick quote anchors the claimed order price, with only a
            # modest rounding/slippage tolerance.
            if verified > 0 and abs(expected_price - verified) / verified > 0.08:
                return "asset_price_identity_mismatch"
        return ""

    @classmethod
    def _extract_quotes(
        cls, payload: Dict[str, object], requested_asset: str = ""
    ) -> List[Dict[str, object]]:
        """从常见行情 JSON（含长桥 quote/K 线）抽出全部 {asset_id, price, name?}。"""
        if not isinstance(payload, dict):
            return []
        found: List[Dict[str, object]] = []

        def add(asset_id: object, price: object, name: object = None) -> None:
            if price is None:
                return
            aid = str(asset_id or "")
            if requested_asset:
                if aid and not cls._identity_matches(aid, requested_asset):
                    return
                if not aid:
                    aid = requested_asset
            if not aid and not requested_asset:
                return
            entry: Dict[str, object] = {
                "asset_id": aid or requested_asset,
                "price": price,
            }
            cleaned = cls._clean_asset_name(name, aid or requested_asset)
            if cleaned:
                entry["name"] = cleaned
            found.append(entry)

        flat_price = payload.get("price")
        if flat_price is None:
            flat_price = payload.get("last_done")
        if flat_price is not None:
            add(
                payload.get("asset_id") or payload.get("symbol"),
                flat_price,
                payload.get("name_cn") or payload.get("name"),
            )

        # 长桥 longport_quote：{symbols, quotes:[{symbol, last_done, name, ...}]}
        quotes = payload.get("quotes")
        if isinstance(quotes, list):
            for row in quotes:
                if isinstance(row, dict):
                    add(cls._row_asset(row), cls._row_price(row), cls._row_name(row))

        # 长桥 longport_candlesticks：{symbol, candlesticks:[{close, ...}]}
        sticks = payload.get("candlesticks")
        if isinstance(sticks, list) and sticks:
            symbol = payload.get("symbol") or requested_asset
            last = next(
                (item for item in reversed(sticks) if isinstance(item, dict)),
                None,
            )
            if last is not None:
                add(
                    symbol,
                    cls._row_price(last),
                    payload.get("name_cn") or payload.get("name"),
                )

        data = payload.get("data")
        rows = data if isinstance(data, list) else []
        for row in rows:
            if not isinstance(row, dict):
                continue
            identities = [
                row.get("id"),
                row.get("symbol"),
                row.get("name"),
                row.get("asset_id"),
            ]
            if requested_asset and not any(
                cls._identity_matches(ident, requested_asset)
                for ident in identities if ident not in (None, "")
            ):
                continue
            price = row.get("current_price")
            if price is None:
                price = cls._row_price(row)
            add(
                row.get("symbol") or row.get("id") or requested_asset,
                price,
                cls._row_name(row),
            )

        quote = data.get("Global Quote") if isinstance(data, dict) else None
        if isinstance(quote, dict) and quote.get("05. price") is not None:
            add(quote.get("01. symbol") or requested_asset, quote.get("05. price"))

        for chart in (
            data.get("chart") if isinstance(data, dict) else None,
            payload.get("chart"),
        ):
            if not isinstance(chart, dict):
                continue
            for result in chart.get("result") or []:
                if not isinstance(result, dict):
                    continue
                meta = result.get("meta") or {}
                if not isinstance(meta, dict):
                    meta = {}
                symbol = str(meta.get("symbol") or "")
                if (
                    requested_asset
                    and symbol
                    and not cls._identity_matches(symbol, requested_asset)
                ):
                    continue
                price = meta.get("regularMarketPrice")
                if price is None:
                    qlist = ((result.get("indicators") or {}).get("quote") or [])
                    closes = (qlist[0].get("close") or []) if qlist else []
                    price = next(
                        (item for item in reversed(closes) if item is not None),
                        None,
                    )
                if price is not None:
                    add(symbol or requested_asset, price, cls._row_name(meta))
        return found

    @classmethod
    def _select_quote(cls, payload: Dict[str, object], requested_asset: str) -> Dict[str, object]:
        """Normalize common public API quote shapes inside the scene plugin.

        标的匹配用 _ticker_matches 容错 A股/港股代码格式差异（.SH/.SS、前导零）。
        支持长桥 quotes[].last_done / candlesticks[].close，以及 Yahoo / AV / CoinGecko。
        """
        matched = cls._extract_quotes(payload, requested_asset)
        if matched:
            return matched[0]
        if requested_asset:
            for quote in cls._extract_quotes(payload, ""):
                asset_id = str(quote.get("asset_id") or "")
                if asset_id and cls._identity_matches(asset_id, requested_asset):
                    return quote
                if not asset_id:
                    return {
                        "asset_id": requested_asset,
                        "price": quote.get("price"),
                    }
        return {}

    def finalize(self, context: SettlementContext) -> List[SettlementRecord]:
        if not self._accounts or not self._last_event_refs:
            return []
        return [
            self._record(agent_id, self._last_event_refs, context, final=True)
            for agent_id in sorted(self._accounts)
        ]

    def _ensure_accounts(self, context: SettlementContext) -> None:
        initial_cash = float(context.world_state.get("initial_cash", 1000.0))
        for agent_id in context.world_state.get("agent_ids", []):
            if agent_id not in self._accounts:
                self._accounts[agent_id] = PortfolioAccount(
                    cash=initial_cash,
                    initial_value=initial_cash,
                    peak_value=initial_cash,
                )

    def _fx_multiplier(
        self, asset_id: str, context: SettlementContext
    ) -> float:
        """把标的成交货币折算为组合记账货币（默认 CNY）。

        港股报价为港币；若不折算，00700 一股 ~490「元」会与 A 股现金账严重失真。
        汇率来自结算上下文 fx_rates（场景/引擎注入），缺省用保守近似。
        """
        code = str(asset_id or "").upper()
        rates = dict(context.world_state.get("fx_rates") or {})
        if code.endswith(".HK") or code.endswith(".HKG"):
            try:
                return float(rates.get("HKD") or rates.get("HKD_CNY") or 0.92)
            except (TypeError, ValueError):
                return 0.92
        return 1.0

    def _apply_trade(self, event: WorldEvent) -> None:
        account = self._accounts.get(str(event.actor_id))
        if account is None:
            return
        asset_id = str(
            event.deltas.get("asset_id")
            or (event.target_ids[0] if event.target_ids else "")
        )
        if not asset_id:
            return
        quantity_change = float(event.deltas.get("quantity_change", 0.0))
        price = float(event.deltas.get("price", self._prices.get(asset_id, 0.0)))
        mark_price = float(event.deltas.get("mark_price", price))
        cash_change = event.deltas.get("cash_change")
        if cash_change is None:
            cash_change = -(quantity_change * price)
        account.cash += float(cash_change)
        account.positions[asset_id] = (
            account.positions.get(asset_id, 0.0) + quantity_change
        )
        self._prices[asset_id] = mark_price
        account.orders.append({
            "tick": event.world_tick,
            "asset_id": asset_id,
            "side": "buy" if quantity_change > 0 else "sell",
            "quantity": abs(quantity_change),
            "price": price,
            "fill_price": price,
            "reference_price": float(event.deltas.get("reference_price", price)),
            "mark_price": mark_price,
            "cash_change": float(cash_change),
            "gross_notional": float(event.deltas.get(
                "gross_notional", abs(quantity_change * price)
            )),
            "notional": float(event.deltas.get(
                "gross_notional", abs(quantity_change * price)
            )),
            "commission": float(event.deltas.get("commission", 0.0)),
            "slippage_cost": float(event.deltas.get("slippage_cost", 0.0)),
            "slippage_bps": float(event.deltas.get("slippage_bps", 0.0)),
            "price_evidence_ref": event.deltas.get("price_evidence_ref"),
            "market_phase": event.deltas.get("market_phase"),
        })

    def _apply_market_close(self, event: WorldEvent) -> None:
        asset_id = str(
            event.deltas.get("asset_id")
            or (event.target_ids[0] if event.target_ids else "")
        )
        price = event.state_after.get("price", event.deltas.get("price"))
        if asset_id and price is not None:
            self._prices[asset_id] = float(price)

    def _record(
        self,
        agent_id: str,
        refs: List[str],
        context: SettlementContext,
        *,
        final: bool,
        had_fill: bool = False,
    ) -> SettlementRecord:
        account = self._accounts[agent_id]
        market_value = sum(
            quantity
            * self._prices.get(asset_id, 0.0)
            * self._fx_multiplier(asset_id, context)
            for asset_id, quantity in account.positions.items()
        )
        portfolio_value = account.cash + market_value
        account.peak_value = max(account.peak_value, portfolio_value)
        current_drawdown_pct = (
            (account.peak_value - portfolio_value) / account.peak_value * 100.0
            if account.peak_value else 0.0
        )
        account.max_drawdown_pct = max(
            account.max_drawdown_pct, current_drawdown_pct
        )
        drawdown_pct = account.max_drawdown_pct
        pnl = portfolio_value - account.initial_value
        return_pct = (
            pnl / account.initial_value * 100.0 if account.initial_value else 0.0
        )
        benchmark = dict(context.world_state.get("benchmark") or {})
        benchmark_return_pct = float(benchmark.get("return_pct", 0.0) or 0.0)
        excess_return_pct = return_pct - benchmark_return_pct
        risk_adjustment = dict(context.world_state.get("risk_adjustment") or {})
        drawdown_penalty = float(
            risk_adjustment.get("drawdown_penalty", 0.5) or 0.0
        )
        risk_adjusted_excess_return = (
            excess_return_pct - drawdown_penalty * drawdown_pct
        )
        gross_turnover = sum(
            abs(float(order.get("gross_notional", 0.0) or 0.0))
            for order in account.orders
        )
        turnover_pct = (
            gross_turnover / account.initial_value * 100.0
            if account.initial_value else 0.0
        )
        total_commission = sum(
            float(order.get("commission", 0.0) or 0.0)
            for order in account.orders
        )
        total_slippage_cost = sum(
            float(order.get("slippage_cost", 0.0) or 0.0)
            for order in account.orders
        )
        total_transaction_cost = total_commission + total_slippage_cost
        cash_ratio_pct = (
            account.cash / portfolio_value * 100.0 if portfolio_value else 0.0
        )
        display_name = str(
            (context.world_state.get("agent_names", {}) or {}).get(agent_id)
            or agent_id
        )
        suffix = "final" if final else f"tick_{context.world_tick}"
        external_records = context.world_state.get("external_observations")
        verified_ids = (
            {
                str(item.get("observation_id") or "")
                for item in external_records or []
                if isinstance(item, dict)
                and item.get("verification_status") == "verified"
            }
            if external_records is not None else {
                observation_ref
                for event_ref in refs
                for observation_ref in self._event_observations.get(event_ref, [])
            }
        )
        observation_refs = list(dict.fromkeys(
            observation_ref
            for event_ref in refs
            for observation_ref in self._event_observations.get(event_ref, [])
            if observation_ref in verified_ids
        ))
        has_external_price = bool(observation_refs)
        has_positions = any(
            abs(quantity) > 1e-12 for quantity in account.positions.values()
        )
        snapshot = self._presentation_snapshot(
            account, market_value=market_value, pnl=pnl
        )
        previous = self._last_presentation_snapshot.get(agent_id)
        ledger_changed = previous is None or previous != snapshot
        material = bool(
            final
            or had_fill
            or (ledger_changed and (has_positions or abs(pnl) > 1e-9
                                    or abs(account.cash - account.initial_value) > 1e-9))
        )
        # 纯现金开局、无成交、无持仓、盈亏为零：内部仍记账，观众端静默
        silent = not material
        self._last_presentation_snapshot[agent_id] = snapshot
        if silent:
            explanation = ""
        elif final:
            explanation = (
                f"{display_name}终局结算："
                f"当前资产 {portfolio_value:.2f} 元，"
                f"累计盈亏 {pnl:+.2f} 元，收益率 {return_pct:+.2f}%，"
                f"基准超额 {excess_return_pct:+.2f}%，最大回撤 {drawdown_pct:.2f}%，"
                f"风险调整超额 {risk_adjusted_excess_return:+.2f}，"
                f"现金 {account.cash:.2f} 元，持仓市值 {market_value:.2f} 元。"
            )
        elif had_fill:
            explanation = (
                f"{display_name}成交后更新账本："
                f"当前资产 {portfolio_value:.2f} 元，"
                f"累计盈亏 {pnl:+.2f} 元，收益率 {return_pct:+.2f}%，"
                f"现金 {account.cash:.2f} 元，持仓市值 {market_value:.2f} 元。"
            )
        elif has_positions:
            explanation = (
                f"{display_name}按已验证行情更新持仓市值："
                f"当前资产 {portfolio_value:.2f} 元，"
                f"累计盈亏 {pnl:+.2f} 元，收益率 {return_pct:+.2f}%，"
                f"现金 {account.cash:.2f} 元，持仓市值 {market_value:.2f} 元。"
            )
        else:
            explanation = (
                f"{display_name}组合状态已更新："
                f"当前资产 {portfolio_value:.2f} 元，"
                f"累计盈亏 {pnl:+.2f} 元，现金 {account.cash:.2f} 元。"
            )
        return SettlementRecord(
            settlement_id=f"capital_market:{agent_id}:{suffix}",
            run_id=context.run_id,
            scenario_id=context.scenario_id,
            world_tick=context.world_tick,
            evaluator_id=self.plugin_id,
            authority=SettlementAuthority(
                mode="hybrid" if has_external_price else "deterministic_verifier",
                provider_id=(
                    "portfolio_mark_to_market"
                    if has_external_price else "portfolio_cash_ledger"
                ),
                verifier_id="portfolio_ledger",
                rule_version="capital_market.portfolio_mark_to_market.v2",
                observation_refs=observation_refs,
                component_modes=(
                    ["external_reality", "deterministic_verifier"]
                    if has_external_price else ["deterministic_verifier"]
                ),
                reproducible=True,
                deterministic=True,
            ),
            kind="scenario_outcome",
            subject_ids=[agent_id],
            source_event_refs=list(refs),
            rule_refs=["capital_market.portfolio_mark_to_market.v2"],
            outcome="portfolio_marked_to_market",
            values={
                "cash": round(account.cash, 6),
                "market_value": round(market_value, 6),
                "portfolio_value": round(portfolio_value, 6),
                "pnl": round(pnl, 6),
                "return_pct": round(return_pct, 6),
                "drawdown_pct": round(drawdown_pct, 6),
                "cash_ratio_pct": round(cash_ratio_pct, 6),
                "benchmark_return_pct": round(benchmark_return_pct, 6),
                "excess_return_pct": round(excess_return_pct, 6),
                "risk_adjusted_excess_return": round(
                    risk_adjusted_excess_return, 6
                ),
                "turnover_pct": round(turnover_pct, 6),
                "total_commission": round(total_commission, 6),
                "total_slippage_cost": round(total_slippage_cost, 6),
                "total_transaction_cost": round(total_transaction_cost, 6),
                "position_count": float(sum(
                    1 for quantity in account.positions.values() if quantity > 0
                )),
            },
            details={
                "positions": {
                    asset_id: round(quantity, 8)
                    for asset_id, quantity in account.positions.items()
                    if abs(quantity) > 1e-12
                },
                "prices": {
                    asset_id: round(self._prices.get(asset_id, 0.0), 8)
                    for asset_id in account.positions
                },
                "avg_costs": self._position_avg_costs(account),
                "holdings": self._holdings_rows(account),
                "asset_names": {
                    asset_id: name
                    for asset_id, name in self._asset_names.items()
                    if asset_id in account.positions
                    and abs(account.positions.get(asset_id, 0.0)) > 1e-12
                },
                "orders": list(account.orders[-10:]),
                "market_phase": self._market_phase(context),
                "evaluation": {
                    "benchmark_id": str(benchmark.get("id") or "cash"),
                    "benchmark_name": str(benchmark.get("name") or "现金基准"),
                    "benchmark_return_pct": round(benchmark_return_pct, 6),
                    "drawdown_penalty": round(drawdown_penalty, 6),
                    "primary_metric_formula": (
                        "excess_return_pct - drawdown_penalty * max_drawdown_pct"
                    ),
                },
                # 给 Agent 看的可读状态文案（场景自己表达业务含义，OS 只透传）
                "display_text": self._holdings_display_text(account, market_value, pnl),
                "silent": silent,
                "presentation_silent": silent,
            },
            explanation=explanation,
            affects_world=True,
            affects_victory=final,
        )

    @staticmethod
    def _presentation_snapshot(
        account: PortfolioAccount,
        *,
        market_value: float,
        pnl: float,
    ) -> Tuple[Any, ...]:
        positions = tuple(sorted(
            (asset_id, round(float(quantity), 8))
            for asset_id, quantity in account.positions.items()
            if abs(float(quantity)) > 1e-12
        ))
        return (
            round(float(account.cash), 6),
            round(float(market_value), 6),
            round(float(pnl), 6),
            round(float(account.max_drawdown_pct), 6),
            positions,
        )

    @staticmethod
    def _position_avg_costs(account: "PortfolioAccount") -> Dict[str, float]:
        """按成交流水估算各标的剩余持仓的加权平均买入价。"""
        qty: Dict[str, float] = {}
        cost: Dict[str, float] = {}
        for order in account.orders:
            if not isinstance(order, dict):
                continue
            asset_id = str(order.get("asset_id") or "")
            if not asset_id:
                continue
            try:
                quantity = float(order.get("quantity") or 0.0)
                price = float(order.get("price") or 0.0)
            except (TypeError, ValueError):
                continue
            if quantity <= 0 or price < 0:
                continue
            side = str(order.get("side") or "")
            if side == "buy":
                prev_q = qty.get(asset_id, 0.0)
                prev_c = cost.get(asset_id, 0.0)
                qty[asset_id] = prev_q + quantity
                cost[asset_id] = prev_c + quantity * price
            elif side == "sell":
                prev_q = qty.get(asset_id, 0.0)
                if prev_q <= 1e-12:
                    continue
                avg = cost.get(asset_id, 0.0) / prev_q
                sell_q = min(quantity, prev_q)
                remain = prev_q - sell_q
                if remain <= 1e-12:
                    qty[asset_id] = 0.0
                    cost[asset_id] = 0.0
                else:
                    qty[asset_id] = remain
                    cost[asset_id] = max(0.0, cost.get(asset_id, 0.0) - sell_q * avg)
        return {
            asset_id: round(cost[asset_id] / quantity, 6)
            for asset_id, quantity in qty.items()
            if quantity > 1e-12 and cost.get(asset_id, 0.0) > 0
        }

    def _holdings_rows(self, account: "PortfolioAccount") -> List[Dict[str, object]]:
        """观众端持仓行：名称、标的代码、数量、现价、买入均价。"""
        avg_costs = self._position_avg_costs(account)
        rows: List[Dict[str, object]] = []
        for asset_id, quantity in account.positions.items():
            if abs(quantity) <= 1e-12:
                continue
            mark = float(self._prices.get(asset_id, 0.0) or 0.0)
            avg = float(avg_costs.get(asset_id, mark) or 0.0)
            name = self._lookup_asset_name(asset_id)
            rows.append({
                "asset_id": asset_id,
                "name": name,
                "display_name": name or asset_id,
                "quantity": round(float(quantity), 8),
                "mark_price": round(mark, 8),
                "avg_cost": round(avg, 8),
            })
        rows.sort(key=lambda item: abs(float(item.get("quantity") or 0.0)), reverse=True)
        return rows

    def _holdings_display_text(self, account, market_value: float, pnl: float) -> str:
        """给 Agent 看的可读持仓/盈亏文案（本场景业务表达，OS 不认识）。"""
        dd = (
            (account.peak_value - (account.cash + market_value)) / account.peak_value * 100.0
            if account.peak_value else 0.0
        )
        lines = [
            f"- 现金 {account.cash:.0f}，持仓市值 {market_value:.0f}，"
            f"累计盈亏 {pnl:+.0f}，当前回撤 {dd:.1f}%"
        ]
        transaction_cost = sum(
            float(order.get("commission", 0.0) or 0.0)
            + float(order.get("slippage_cost", 0.0) or 0.0)
            for order in account.orders
        )
        lines.append(f"- 累计交易成本 {transaction_cost:.2f} 元")
        holds = [(a, q) for a, q in account.positions.items() if abs(q) > 1e-9]
        if holds:
            bits = []
            for asset_id, qty in holds[:6]:
                label = self._lookup_asset_name(asset_id) or asset_id
                bits.append(f"{label}({asset_id}) {qty:.0f}股")
            lines.append("- 持仓：" + "，".join(bits))
        else:
            lines.append("- 当前无持仓")
        if account.orders:
            order_bits = []
            for o in account.orders[-3:]:
                aid = str(o.get("asset_id") or "")
                label = self._lookup_asset_name(aid) or aid
                order_bits.append(
                    f"T{o.get('tick')} "
                    f"{'买入' if o.get('side') == 'buy' else '卖出'} "
                    f"{label} {o.get('quantity')}股@{o.get('price')}"
                )
            lines.append("- 最近成交：" + "；".join(order_bits))
        return "\n".join(lines)

    @staticmethod
    def _market_phase(context: SettlementContext) -> Dict[str, object]:
        # 当前阶段由 OS 从 world/clock.yaml 用 RoundModel 统一算好并注入
        # round_phase；场景插件直接读取，不再自己对 tick 取模。
        phase = context.world_state.get("round_phase")
        return dict(phase) if isinstance(phase, dict) else {}

    def _latest_verified_quote_for_asset(
        self,
        context: SettlementContext,
        requested_asset: str,
    ) -> Tuple[str, Optional[Dict[str, object]]]:
        validity_ticks = int(context.world_state.get("evidence_validity_ticks", 0) or 0)
        needle = str(requested_asset or "").lower()
        candidates: List[Tuple[int, str, Dict[str, object]]] = []
        for observation in context.world_state.get("external_observations", []) or []:
            if not isinstance(observation, dict):
                continue
            if observation.get("verification_status") != "verified":
                continue
            observed_tick = int(observation.get("world_tick", -1) or -1)
            if validity_ticks > 0:
                if observed_tick < context.world_tick - validity_ticks:
                    continue
                if observed_tick > context.world_tick:
                    continue
            elif observed_tick != context.world_tick:
                continue
            normalized = observation.get("normalized_value") or {}
            if not isinstance(normalized, dict):
                continue
            quote = self._select_quote(normalized, requested_asset)
            asset_id = str(quote.get("asset_id") or "")
            if requested_asset and asset_id and not self._ticker_matches(asset_id, requested_asset):
                continue
            if quote.get("price") is None:
                continue
            candidates.append((
                observed_tick,
                str(observation.get("observation_id") or ""),
                normalized,
            ))
        if not candidates:
            return "", None
        candidates.sort(key=lambda item: item[0], reverse=True)
        _, observation_id, normalized = candidates[0]
        return observation_id, normalized


def create_plugin() -> CapitalMarketSettlementPlugin:
    return CapitalMarketSettlementPlugin()
