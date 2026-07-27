"""Authoritative investment-strategy ledger for the capital-market scenario."""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, Optional, Tuple


PLAN_REQUIRED_FIELDS = (
    "thesis",
    "counter_evidence",
    "target_weight_pct",
    "entry_trigger",
    "exit_condition",
    "style_alignment",
)

CANONICAL_PLAN_STATUSES = {
    "candidate", "active", "monitoring", "invalidated", "closed",
}

PLAN_STATUS_ALIASES = {
    "候选": "candidate",
    "备选": "candidate",
    "研究": "candidate",
    "研究中": "candidate",
    "research": "candidate",
    "researching": "candidate",
    "watch": "monitoring",
    "watching": "monitoring",
    "observe": "monitoring",
    "观望": "monitoring",
    "观察": "monitoring",
    "跟踪": "monitoring",
    "monitor": "monitoring",
    "monitoring": "monitoring",
    "prepare_buy": "active",
    "prepared": "active",
    "planned": "active",
    "planned_buy": "active",
    "plan_to_buy": "active",
    "preparing_buy": "active",
    "ready_to_buy": "active",
    "ready_for_entry": "active",
    "ready_to_enter": "active",
    "entry_ready": "active",
    "open_position": "active",
    "entry": "active",
    "ready": "active",
    "buy": "active",
    "hold": "active",
    "持有": "active",
    "准备买入": "active",
    "准备建仓": "active",
    "待买入": "active",
    "待建仓": "active",
    "可买入": "active",
    "active": "active",
    "invalid": "invalidated",
    "invalidate": "invalidated",
    "invalidated": "invalidated",
    "失效": "invalidated",
    "关闭": "closed",
    "closed": "closed",
    "sold": "closed",
}

STYLE_ALIGNMENT_TOKENS = {
    "value": (
        "价值",
        "估值",
        "安全边际",
        "股息",
        "现金流",
        "防守",
        "value",
        "valuation",
        "margin of safety",
        "book",
        "below book",
        "price-to-book",
        "pb",
        "p/b",
        "pe",
        "p/e",
        "dividend",
        "yield",
        "cash flow",
        "defensive",
        "undervalued",
        "low multiple",
        "state-owned",
        "soe",
        "income",
        "capital preservation",
    ),
    "growth": (
        "成长",
        "景气",
        "催化",
        "订单",
        "产品周期",
        "资金流",
        "growth",
        "catalyst",
        "upcycle",
        "industry cycle",
        "product cycle",
        "innovation",
        "revenue growth",
        "earnings growth",
        "order book",
        "capital flow",
        "fund flow",
        "momentum",
        "demand recovery",
        "subsidy",
        "expansion",
    ),
}


@dataclass
class InvestmentThesis:
    asset_id: str
    asset_name: str = ""
    status: str = "candidate"
    thesis: str = ""
    counter_evidence: str = ""
    conviction: float = 0.5
    expected_return_pct: Optional[float] = None
    entry_price_max: Optional[float] = None
    stop_loss_price: Optional[float] = None
    take_profit_price: Optional[float] = None
    thesis_expiry_tick: Optional[int] = None
    risk_budget_pct: Optional[float] = None
    target_weight_pct: float = 0.0
    entry_trigger: str = ""
    exit_condition: str = ""
    style_alignment: str = ""
    evidence_refs: list[str] = field(default_factory=list)
    created_tick: int = 0
    updated_tick: int = 0
    last_decision: str = "research"
    last_trade_side: str = ""
    last_trade_tick: int = -1
    actual_quantity: float = 0.0
    actual_weight_pct: float = 0.0
    trigger_state: str = "researching"
    last_mark_price: float = 0.0
    avg_cost: float = 0.0
    invested_cost: float = 0.0
    realized_pnl: float = 0.0
    unrealized_pnl: float = 0.0
    revision: int = 1

    def to_dict(self) -> Dict[str, Any]:
        return {
            "asset_id": self.asset_id,
            "asset_name": self.asset_name,
            "status": self.status,
            "thesis": self.thesis,
            "counter_evidence": self.counter_evidence,
            "conviction": round(self.conviction, 4),
            "expected_return_pct": self.expected_return_pct,
            "entry_price_max": self.entry_price_max,
            "stop_loss_price": self.stop_loss_price,
            "take_profit_price": self.take_profit_price,
            "thesis_expiry_tick": self.thesis_expiry_tick,
            "risk_budget_pct": self.risk_budget_pct,
            "target_weight_pct": round(self.target_weight_pct, 4),
            "entry_trigger": self.entry_trigger,
            "exit_condition": self.exit_condition,
            "style_alignment": self.style_alignment,
            "evidence_refs": list(self.evidence_refs),
            "created_tick": self.created_tick,
            "updated_tick": self.updated_tick,
            "last_decision": self.last_decision,
            "last_trade_side": self.last_trade_side,
            "last_trade_tick": self.last_trade_tick,
            "actual_quantity": round(self.actual_quantity, 8),
            "actual_weight_pct": round(self.actual_weight_pct, 4),
            "trigger_state": self.trigger_state,
            "last_mark_price": round(self.last_mark_price, 8),
            "avg_cost": round(self.avg_cost, 8),
            "realized_pnl": round(self.realized_pnl, 6),
            "unrealized_pnl": round(self.unrealized_pnl, 6),
            "total_attributed_pnl": round(
                self.realized_pnl + self.unrealized_pnl, 6
            ),
            "revision": self.revision,
        }


@dataclass
class InvestmentBook:
    agent_id: str
    style: str
    max_single_position_pct: float
    min_cash_pct: float
    reversal_cooldown_ticks: int = 2
    require_numeric_risk_plan: bool = False
    require_sell_reason: bool = False
    max_risk_budget_pct: float = 100.0
    theses: Dict[str, InvestmentThesis] = field(default_factory=dict)
    decision_journal: list[Dict[str, Any]] = field(default_factory=list)
    rejected_decisions: list[Dict[str, Any]] = field(default_factory=list)
    cash: float = 0.0
    portfolio_value: float = 0.0
    cash_ratio_pct: float = 100.0
    last_reconciled_tick: int = 0

    @classmethod
    def from_policy(
        cls, agent_id: str, policy: Dict[str, Any]
    ) -> "InvestmentBook":
        role = dict((policy.get("by_agent") or {}).get(agent_id) or {})
        return cls(
            agent_id=agent_id,
            style=str(role.get("style") or "unclassified"),
            max_single_position_pct=float(
                role.get("max_single_position_pct", 100.0) or 100.0
            ),
            min_cash_pct=float(role.get("min_cash_pct", 0.0) or 0.0),
            reversal_cooldown_ticks=max(
                0, int(policy.get("reversal_cooldown_ticks", 2) or 0)
            ),
            require_numeric_risk_plan=bool(
                policy.get("require_numeric_risk_plan", False)
            ),
            require_sell_reason=bool(
                policy.get("require_sell_reason", False)
            ),
            max_risk_budget_pct=float(
                role.get("max_risk_budget_pct", 100.0) or 100.0
            ),
        )

    @staticmethod
    def _number(value: Any, *, default: Optional[float] = None) -> Optional[float]:
        try:
            return float(value)
        except (TypeError, ValueError):
            return default

    @staticmethod
    def normalize_plan_status(value: Any) -> str:
        raw = str(value or "candidate").strip()
        key = raw.lower().replace("-", "_").replace(" ", "_")
        return PLAN_STATUS_ALIASES.get(key) or PLAN_STATUS_ALIASES.get(raw) or raw

    def normalize_plan_parameters(self, parameters: Dict[str, Any]) -> Dict[str, Any]:
        normalized = dict(parameters or {})
        normalized["status"] = self.normalize_plan_status(
            normalized.get("status") or "candidate"
        )
        return normalized

    def validate_plan(
        self, parameters: Dict[str, Any], *, tick: int = 0
    ) -> Tuple[bool, str]:
        parameters = self.normalize_plan_parameters(parameters)
        asset_id = str(parameters.get("asset_id") or "").strip()
        if not asset_id:
            return False, "strategy_asset_missing"
        status = str(parameters.get("status") or "candidate")
        if status not in CANONICAL_PLAN_STATUSES:
            return False, "strategy_status_invalid"
        missing = [
            key for key in PLAN_REQUIRED_FIELDS
            if parameters.get(key) in (None, "")
        ]
        if missing:
            return False, "strategy_fields_missing:" + ",".join(missing)
        target = self._number(parameters.get("target_weight_pct"))
        conviction = self._number(parameters.get("conviction"), default=0.5)
        if target is None or not 0 < target <= 100:
            return False, "strategy_target_weight_invalid"
        if target > self.max_single_position_pct:
            return False, "strategy_position_limit_exceeded"
        if conviction is None or not 0 <= conviction <= 1:
            return False, "strategy_conviction_invalid"
        numeric_fields = {
            key: self._number(parameters.get(key))
            for key in (
                "entry_price_max",
                "stop_loss_price",
                "take_profit_price",
                "risk_budget_pct",
            )
        }
        if self.require_numeric_risk_plan:
            missing_numeric = [
                key for key in (
                    "entry_price_max", "stop_loss_price", "risk_budget_pct"
                )
                if numeric_fields[key] is None
            ]
            if missing_numeric:
                return (
                    False,
                    "strategy_numeric_risk_fields_missing:"
                    + ",".join(missing_numeric),
                )
        if any(
            value is not None and value <= 0
            for value in numeric_fields.values()
        ):
            return False, "strategy_numeric_trigger_invalid"
        entry_price = numeric_fields["entry_price_max"]
        stop_price = numeric_fields["stop_loss_price"]
        take_price = numeric_fields["take_profit_price"]
        if entry_price and stop_price and stop_price >= entry_price:
            return False, "strategy_stop_not_below_entry"
        if entry_price and take_price and take_price <= entry_price:
            return False, "strategy_take_profit_not_above_entry"
        risk_budget = numeric_fields["risk_budget_pct"]
        if risk_budget and risk_budget > self.max_risk_budget_pct:
            return False, "strategy_risk_budget_exceeded"
        expiry = parameters.get("thesis_expiry_tick")
        if expiry not in (None, ""):
            try:
                expiry = int(expiry)
            except (TypeError, ValueError):
                return False, "strategy_expiry_invalid"
            if expiry <= tick:
                return False, "strategy_expiry_invalid"
        alignment = str(parameters.get("style_alignment") or "").lower()
        tokens = STYLE_ALIGNMENT_TOKENS.get(self.style, ())
        if tokens and not any(str(token).lower() in alignment for token in tokens):
            return False, "strategy_style_mismatch"
        return True, ""

    def update_plan(
        self,
        parameters: Dict[str, Any],
        evidence_refs: Iterable[str],
        tick: int,
    ) -> Tuple[bool, str]:
        parameters = self.normalize_plan_parameters(parameters)
        valid, reason = self.validate_plan(parameters, tick=tick)
        if not valid:
            return False, reason
        asset_id = str(parameters["asset_id"]).strip()
        current = self.theses.get(asset_id)
        refs = list(dict.fromkeys(
            str(item) for item in evidence_refs if str(item)
        ))
        if current is not None:
            material_fields = (
                "status", "thesis", "counter_evidence", "conviction",
                "target_weight_pct", "entry_trigger",
                "exit_condition", "entry_price_max", "stop_loss_price",
                "take_profit_price", "thesis_expiry_tick",
                "risk_budget_pct", "style_alignment",
            )
            materially_changed = any(
                parameters.get(key) not in (None, "")
                and parameters.get(key) != getattr(current, key)
                for key in material_fields
            )
            if (
                current.status == "active"
                and materially_changed
                and not (set(refs) - set(current.evidence_refs))
            ):
                return False, "strategy_revision_without_new_evidence"
        thesis = InvestmentThesis(
            asset_id=asset_id,
            asset_name=str(parameters.get("asset_name") or (
                current.asset_name if current else ""
            )),
            status=str(parameters.get("status") or (
                current.status if current else "candidate"
            )),
            thesis=str(parameters["thesis"]).strip(),
            counter_evidence=str(parameters["counter_evidence"]).strip(),
            conviction=float(self._number(
                parameters.get("conviction"), default=0.5
            ) or 0.0),
            expected_return_pct=self._number(
                parameters.get("expected_return_pct")
            ),
            entry_price_max=self._number(parameters.get("entry_price_max")),
            stop_loss_price=self._number(parameters.get("stop_loss_price")),
            take_profit_price=self._number(parameters.get("take_profit_price")),
            thesis_expiry_tick=(
                int(parameters["thesis_expiry_tick"])
                if parameters.get("thesis_expiry_tick") not in (None, "")
                else None
            ),
            risk_budget_pct=self._number(parameters.get("risk_budget_pct")),
            target_weight_pct=float(parameters["target_weight_pct"]),
            entry_trigger=str(parameters["entry_trigger"]).strip(),
            exit_condition=str(parameters["exit_condition"]).strip(),
            style_alignment=str(parameters["style_alignment"]).strip(),
            evidence_refs=refs,
            created_tick=current.created_tick if current else tick,
            updated_tick=tick,
            last_decision=str(parameters.get("decision") or "research"),
            last_trade_side=current.last_trade_side if current else "",
            last_trade_tick=current.last_trade_tick if current else -1,
            actual_quantity=current.actual_quantity if current else 0.0,
            actual_weight_pct=current.actual_weight_pct if current else 0.0,
            trigger_state=current.trigger_state if current else "researching",
            last_mark_price=current.last_mark_price if current else 0.0,
            avg_cost=current.avg_cost if current else 0.0,
            invested_cost=current.invested_cost if current else 0.0,
            realized_pnl=current.realized_pnl if current else 0.0,
            unrealized_pnl=current.unrealized_pnl if current else 0.0,
            revision=(current.revision + 1) if current else 1,
        )
        self.theses[asset_id] = thesis
        self.decision_journal.append({
            "tick": tick,
            "asset_id": asset_id,
            "event": "plan_revised" if current else "plan_created",
            "revision": thesis.revision,
            "status": thesis.status,
            "evidence_refs": refs,
        })
        return True, ""

    def validate_buy(
        self,
        asset_id: str,
        *,
        post_position_value: float,
        post_cash: float,
        post_portfolio_value: float,
        reference_price: float,
        tick: int,
        evidence_refs: Iterable[str],
    ) -> Tuple[bool, str]:
        thesis = self.theses.get(asset_id)
        if thesis is None:
            return False, "strategy_plan_missing"
        if thesis.status in {"invalidated", "closed"}:
            return False, "strategy_plan_inactive"
        if (
            thesis.thesis_expiry_tick is not None
            and tick > thesis.thesis_expiry_tick
        ):
            return False, "strategy_thesis_expired"
        if (
            thesis.entry_price_max is not None
            and reference_price > thesis.entry_price_max
        ):
            return False, "strategy_entry_trigger_not_met"
        if post_portfolio_value <= 0:
            return False, "strategy_portfolio_value_invalid"
        weight = post_position_value / post_portfolio_value * 100.0
        cash_ratio = post_cash / post_portfolio_value * 100.0
        if weight > self.max_single_position_pct + 1e-6:
            return False, "strategy_position_limit_exceeded"
        if weight > thesis.target_weight_pct + 1.0:
            return False, "strategy_target_weight_exceeded"
        if cash_ratio + 1e-6 < self.min_cash_pct:
            return False, "strategy_cash_floor_breached"
        if (
            thesis.stop_loss_price is not None
            and thesis.risk_budget_pct is not None
            and reference_price > 0
        ):
            downside = max(
                0.0,
                post_position_value
                * (reference_price - thesis.stop_loss_price)
                / reference_price,
            )
            risk_pct = downside / post_portfolio_value * 100.0
            if risk_pct > thesis.risk_budget_pct + 1e-6:
                return False, "strategy_order_risk_budget_exceeded"
        if (
            thesis.last_trade_side == "sell"
            and thesis.last_trade_tick >= 0
            and tick - thesis.last_trade_tick <= self.reversal_cooldown_ticks
            and not (set(evidence_refs) - set(thesis.evidence_refs))
        ):
            return False, "strategy_reversal_without_new_evidence"
        return True, ""

    def validate_sell(
        self,
        asset_id: str,
        *,
        tick: int,
        reference_price: float,
        sell_reason: str,
        evidence_refs: Iterable[str],
    ) -> Tuple[bool, str]:
        thesis = self.theses.get(asset_id)
        if thesis is None:
            return True, ""
        allowed_reasons = {
            "stop_loss", "take_profit", "thesis_invalidated",
            "rebalance", "risk_reduction",
        }
        if self.require_sell_reason and sell_reason not in allowed_reasons:
            return False, "strategy_sell_reason_missing"
        if (
            sell_reason == "stop_loss"
            and thesis.stop_loss_price is not None
            and reference_price > thesis.stop_loss_price
        ):
            return False, "strategy_stop_trigger_not_met"
        if (
            sell_reason == "take_profit"
            and thesis.take_profit_price is not None
            and reference_price < thesis.take_profit_price
        ):
            return False, "strategy_take_profit_trigger_not_met"
        if (
            sell_reason == "thesis_invalidated"
            and thesis.status != "invalidated"
        ):
            return False, "strategy_thesis_not_invalidated"
        if (
            thesis.last_trade_side == "buy"
            and thesis.last_trade_tick >= 0
            and tick - thesis.last_trade_tick <= self.reversal_cooldown_ticks
            and not (set(evidence_refs) - set(thesis.evidence_refs))
        ):
            return False, "strategy_reversal_without_new_evidence"
        return True, ""

    def record_trade(
        self,
        asset_id: str,
        side: str,
        tick: int,
        evidence_refs: Iterable[str],
        *,
        quantity: float,
        gross_notional: float,
        commission: float,
        fill_price: float,
        sell_reason: str = "",
    ) -> None:
        thesis = self.theses.get(asset_id)
        if thesis is None:
            return
        thesis.last_trade_side = side
        thesis.last_trade_tick = tick
        thesis.last_decision = side
        thesis.updated_tick = tick
        thesis.evidence_refs = list(dict.fromkeys(
            [*thesis.evidence_refs, *(str(item) for item in evidence_refs)]
        ))
        if side == "buy":
            thesis.status = "active"
            thesis.invested_cost += gross_notional + commission
            thesis.actual_quantity += quantity
            thesis.avg_cost = (
                thesis.invested_cost / thesis.actual_quantity
                if thesis.actual_quantity else 0.0
            )
        else:
            prior_quantity = max(thesis.actual_quantity, quantity)
            allocated_cost = (
                thesis.invested_cost * min(quantity / prior_quantity, 1.0)
                if prior_quantity else 0.0
            )
            thesis.realized_pnl += (
                gross_notional - commission - allocated_cost
            )
            thesis.invested_cost = max(
                0.0, thesis.invested_cost - allocated_cost
            )
            thesis.actual_quantity = max(
                0.0, thesis.actual_quantity - quantity
            )
        self.decision_journal.append({
            "tick": tick,
            "asset_id": asset_id,
            "event": side,
            "quantity": round(quantity, 8),
            "fill_price": round(fill_price, 8),
            "gross_notional": round(gross_notional, 6),
            "sell_reason": sell_reason,
            "evidence_refs": list(dict.fromkeys(
                str(item) for item in evidence_refs if str(item)
            )),
        })

    def record_rejection(
        self, asset_id: str, reason: str, tick: int
    ) -> None:
        self.rejected_decisions.append({
            "tick": tick,
            "asset_id": asset_id,
            "reason": reason,
        })

    def reconcile(
        self,
        *,
        cash: float,
        positions: Dict[str, float],
        prices: Dict[str, float],
        fx_multipliers: Dict[str, float],
        tick: int,
    ) -> None:
        market_values = {
            asset_id: float(quantity)
            * float(prices.get(asset_id, 0.0) or 0.0)
            * float(fx_multipliers.get(asset_id, 1.0) or 1.0)
            for asset_id, quantity in positions.items()
        }
        portfolio_value = float(cash) + sum(market_values.values())
        self.cash = float(cash)
        self.portfolio_value = portfolio_value
        self.cash_ratio_pct = (
            float(cash) / portfolio_value * 100.0 if portfolio_value else 0.0
        )
        self.last_reconciled_tick = tick
        for asset_id, thesis in self.theses.items():
            thesis.actual_quantity = float(positions.get(asset_id, 0.0) or 0.0)
            thesis.actual_weight_pct = (
                market_values.get(asset_id, 0.0) / portfolio_value * 100.0
                if portfolio_value else 0.0
            )
            thesis.last_mark_price = float(prices.get(asset_id, 0.0) or 0.0)
            thesis.unrealized_pnl = (
                market_values.get(asset_id, 0.0) - thesis.invested_cost
                if thesis.actual_quantity > 1e-12 else 0.0
            )
            if thesis.actual_quantity <= 1e-12 and thesis.last_trade_side == "sell":
                thesis.status = "closed"
                thesis.trigger_state = "closed"
            elif thesis.actual_quantity > 1e-12:
                if (
                    thesis.stop_loss_price is not None
                    and thesis.last_mark_price <= thesis.stop_loss_price
                ):
                    thesis.trigger_state = "exit_required_stop"
                elif (
                    thesis.take_profit_price is not None
                    and thesis.last_mark_price >= thesis.take_profit_price
                ):
                    thesis.trigger_state = "exit_required_take_profit"
                elif (
                    thesis.thesis_expiry_tick is not None
                    and tick > thesis.thesis_expiry_tick
                ):
                    thesis.trigger_state = "review_required"
                else:
                    thesis.trigger_state = "hold"
            elif thesis.status == "closed":
                thesis.trigger_state = "closed"
            elif thesis.status == "invalidated":
                thesis.trigger_state = "invalidated"
            elif (
                thesis.thesis_expiry_tick is not None
                and tick > thesis.thesis_expiry_tick
            ):
                thesis.trigger_state = "expired"
            elif (
                thesis.entry_price_max is not None
                and 0 < thesis.last_mark_price <= thesis.entry_price_max
            ):
                thesis.trigger_state = "ready_to_enter"
            else:
                thesis.trigger_state = "waiting_entry"

    def discipline_metrics(self) -> Dict[str, Any]:
        revisions = sum(
            1 for item in self.decision_journal
            if item.get("event") == "plan_revised"
        )
        trades = sum(
            1 for item in self.decision_journal
            if item.get("event") in {"buy", "sell"}
        )
        rejections = len(self.rejected_decisions)
        score = max(0.0, 100.0 - rejections * 10.0)
        return {
            "strategy_discipline_score": score,
            "plan_revision_count": revisions,
            "planned_trade_count": trades,
            "strategy_rejection_count": rejections,
            "active_thesis_count": sum(
                1 for thesis in self.theses.values()
                if thesis.status == "active"
            ),
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "version": 3,
            "authority": "capital_market_us_settlement",
            "agent_id": self.agent_id,
            "style": self.style,
            "policy": {
                "max_single_position_pct": self.max_single_position_pct,
                "min_cash_pct": self.min_cash_pct,
                "reversal_cooldown_ticks": self.reversal_cooldown_ticks,
                "require_numeric_risk_plan": self.require_numeric_risk_plan,
                "require_sell_reason": self.require_sell_reason,
                "max_risk_budget_pct": self.max_risk_budget_pct,
            },
            "cash": round(self.cash, 6),
            "portfolio_value": round(self.portfolio_value, 6),
            "cash_ratio_pct": round(self.cash_ratio_pct, 4),
            "last_reconciled_tick": self.last_reconciled_tick,
            "theses": {
                asset_id: thesis.to_dict()
                for asset_id, thesis in sorted(self.theses.items())
            },
            "discipline": self.discipline_metrics(),
            "decision_journal": list(self.decision_journal[-30:]),
            "rejected_decisions": list(self.rejected_decisions[-20:]),
        }

    def display_text(self, *, english: bool = False) -> str:
        if not self.theses:
            if english:
                return "- Strategy ledger: no main thesis or candidate thesis yet"
            return "- 策略账本：尚未建立主线或候选论点"
        rows = []
        for thesis in self.theses.values():
            if english:
                rows.append(
                    f"- Strategy ledger {thesis.asset_name or thesis.asset_id}"
                    f" ({thesis.status}): target {thesis.target_weight_pct:.1f}% / "
                    f"actual {thesis.actual_weight_pct:.1f}%, conviction "
                    f"{thesis.conviction:.0%}, signal {thesis.trigger_state}\n"
                    f"  Thesis: {thesis.thesis}\n"
                    f"  Counter-evidence: {thesis.counter_evidence}\n"
                    f"  Entry: {thesis.entry_trigger}; exit: {thesis.exit_condition}\n"
                    f"  Attribution: realized {thesis.realized_pnl:+.2f} / "
                    f"unrealized {thesis.unrealized_pnl:+.2f}"
                )
            else:
                rows.append(
                    f"- 策略账本 {thesis.asset_name or thesis.asset_id}"
                    f"（{thesis.status}）：目标 {thesis.target_weight_pct:.1f}% / "
                    f"实际 {thesis.actual_weight_pct:.1f}%，置信度 "
                    f"{thesis.conviction:.0%}，信号 {thesis.trigger_state}\n"
                    f"  论点：{thesis.thesis}\n"
                    f"  反证：{thesis.counter_evidence}\n"
                    f"  入场：{thesis.entry_trigger}；退出：{thesis.exit_condition}\n"
                    f"  归因：已实现 {thesis.realized_pnl:+.2f} / "
                    f"未实现 {thesis.unrealized_pnl:+.2f}"
                )
        return "\n".join(rows)
