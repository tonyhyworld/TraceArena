"""Victory and terminal-condition strategy contracts."""
from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Dict, List, Optional


@dataclass(frozen=True)
class VictoryDecision:
    should_end: bool
    reason: str = ""


class VictoryStrategy:
    """Generic scene termination strategy.

    This class decides *when* a world ends.  Final scoring is still performed by
    the configured audit service so the strategy can be reused across domains.
    """

    def should_end(
        self,
        *,
        state: Any,
        tick: int,
        audit_cfg: Dict[str, Any],
        capability_coordinators: List[Any],
        all_challenges_done_tick: Optional[int],
        elapsed_seconds: Optional[float] = None,
    ) -> VictoryDecision:
        if state.is_game_over:
            return VictoryDecision(False)

        termination = audit_cfg.get("termination", {})
        if not isinstance(termination, dict):
            termination = {}

        # 墙钟终局：实时场景按真实经过秒数结束（如"1 小时内分胜负"）。
        # tick_limit 仍保留为安全帽。elapsed_seconds 为 None 时（非实时局）跳过。
        if elapsed_seconds is not None:
            for condition in termination.get("any", []) or []:
                if (
                    isinstance(condition, dict)
                    and condition.get("type") == "wall_clock_seconds"
                ):
                    limit = float(condition.get("value", 0) or 0)
                    if limit > 0 and elapsed_seconds >= limit:
                        return VictoryDecision(
                            True, f"wall_clock_seconds={limit:.0f}"
                        )

        eliminated_ids = {
            e.get("agent_id") for e in getattr(state, "eliminated", [])
            if isinstance(e, dict)
        }
        survivors = [
            agent_id for agent_id in state.alive_agent_ids
            if agent_id not in eliminated_ids
        ]
        if (
            termination.get("end_when_one_survivor", False)
            and len(state.alive_agent_ids) >= 2
            and len(survivors) <= 1
        ):
            return VictoryDecision(True, f"one_survivor:{survivors}")

        if termination.get("end_after_all_challenges", False) and capability_coordinators:
            if all(getattr(c, "fired", False) for c in capability_coordinators):
                done_tick = tick if all_challenges_done_tick is None else all_challenges_done_tick
                grace = int(termination.get("challenge_end_grace_ticks", 2) or 0)
                if tick >= done_tick + grace:
                    return VictoryDecision(True, "all_challenges_completed")

        tick_limit = int(audit_cfg.get("tick_limit", 0) or 0)
        for condition in termination.get("any", []) or []:
            if (
                isinstance(condition, dict)
                and condition.get("type") == "tick_limit"
            ):
                tick_limit = int(condition.get("value", tick_limit) or 0)
        if tick_limit > 0 and tick >= tick_limit:
            return VictoryDecision(True, f"tick_limit={tick_limit}")

        victory_rule = audit_cfg.get("victory_rule", {})
        if isinstance(victory_rule, dict) and victory_rule:
            metric = victory_rule.get("metric", "")
            condition = victory_rule.get("condition", "")
            threshold = victory_rule.get("threshold", None)
            if metric and condition == "threshold" and threshold is not None:
                metrics = state.internal.get("metrics", {})
                for agent_id, agent_metrics in metrics.items():
                    val = float(agent_metrics.get(metric, 0.0))
                    if val >= float(threshold):
                        return VictoryDecision(
                            True,
                            f"victory_rule: {metric}>={threshold} by {agent_id}",
                        )

        return VictoryDecision(False)
