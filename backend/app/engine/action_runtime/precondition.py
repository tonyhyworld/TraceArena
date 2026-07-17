"""
P0-5 ActionPreconditionValidator — 动作前置条件校验器

在 L4 执行动作前进行硬校验，非法动作不进入 L5。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.interfaces import ActionPack, ActionPreconditionResult

logger = logging.getLogger(__name__)


class ActionPreconditionValidator:
    """动作前置条件校验器"""

    def __init__(
        self,
        actions_cfg: List[Dict[str, Any]],
        location_registry: Any = None,
        resource_service: Any = None,
        cooldown_service: Any = None,
        access_control: Any = None,
    ):
        self._actions_map: Dict[str, Dict[str, Any]] = {
            a.get("id", ""): a for a in actions_cfg if isinstance(a, dict)
        }
        self._loc_reg = location_registry
        self._res_svc = resource_service
        self._cd_svc = cooldown_service
        self._access = access_control

    def validate(
        self,
        action: ActionPack,
        agent_location: Optional[str] = None,
        visible_object_ids: Optional[List[str]] = None,
        visible_agent_ids: Optional[List[str]] = None,
        reachable_location_ids: Optional[List[str]] = None,
    ) -> ActionPreconditionResult:
        """校验动作前置条件，返回 ActionPreconditionResult"""
        aid = action.action_id
        agent = action.agent_id
        cfg = self._actions_map.get(aid)

        # 1. action_id 存在
        if cfg is None:
            return ActionPreconditionResult(
                valid=False, status="invalid",
                reason_code="unknown_action", reason_detail=f"动作 {aid} 不存在",
                action_id=aid, agent_id=agent,
            )

        # 2. requires_target
        if not cfg.get("requires_target", False):
            # Some model outputs carry a stale target from a previous schema or
            # a natural-language parser guess. Untargeted actions are global to
            # the actor, so stale targets must not make them fail visibility.
            action.target_object_id = None
            action.target_agent_id = None
        target_optional_for_settlement = bool(
            cfg.get("target_optional_for_settlement", False)
        )
        if (
            cfg.get("requires_target", False)
            and not target_optional_for_settlement
            and not action.target_object_id
            and not action.target_agent_id
        ):
            return ActionPreconditionResult(
                valid=False, status="invalid",
                reason_code="missing_target", reason_detail=f"动作 {aid} 需要目标但未指定",
                action_id=aid, agent_id=agent,
            )

        # 3. target 可见可访问
        target_accessible = True
        target_kind = cfg.get("target_kind", "")
        if target_kind == "agent" and action.target_agent_id:
            if action.target_agent_id == agent:
                target_accessible = False
            elif (
                visible_agent_ids is not None
                and action.target_agent_id not in visible_agent_ids
            ):
                target_accessible = False
        # 挑战应答类动作不检查对象可见性——它是全局应答，不受地点限制
        if (
            action.target_object_id
            and visible_object_ids is not None
            and not target_optional_for_settlement
            and target_kind not in ("location", "agent", "challenge")
            and cfg.get("category") != "challenge"
        ):
            if action.target_object_id not in visible_object_ids:
                target_accessible = False
        if target_kind == "location" and action.target_object_id:
            if self._loc_reg and not self._loc_reg.exists(action.target_object_id):
                target_accessible = False
            elif (
                reachable_location_ids is not None
                and action.target_object_id not in reachable_location_ids
            ):
                target_accessible = False

        # 4. location 允许
        # P0-e（C方案）：category=challenge 的全局应答类动作（如 submit_challenge_response）
        # 不应被地点白名单拦截——挑战是世界级冲突，无论 agent 当下身在何处都
        # 应当能应答。
        location_allowed = True
        if cfg.get("category") == "challenge":
            location_allowed = True
        elif agent_location and self._loc_reg:
            loc = self._loc_reg.get(agent_location)
            if loc and loc.available_actions and aid not in loc.available_actions:
                location_allowed = False

        # 5. 权限
        permission_allowed = True
        if self._access:
            ok, _ = self._access.can_execute_action(agent, cfg)
            permission_allowed = ok

        # 6. 资源
        resource_sufficient = True
        if self._res_svc:
            cost = cfg.get("cost", {})
            if cost:
                resource_sufficient = self._res_svc.can_afford(agent, cost)

        # 7. 冷却
        cooldown_allowed = True
        if self._cd_svc:
            cooling, _ = self._cd_svc.is_cooling(agent, aid)
            cooldown_allowed = not cooling

        valid = all([target_accessible, location_allowed, permission_allowed, resource_sufficient, cooldown_allowed])
        reasons = []
        if not target_accessible:
            reasons.append("target_not_accessible")
        if not location_allowed:
            reasons.append("location_not_allowed")
        if not permission_allowed:
            reasons.append("permission_denied")
        if not resource_sufficient:
            reasons.append("insufficient_resources")
        if not cooldown_allowed:
            reasons.append("cooldown_active")

        return ActionPreconditionResult(
            valid=valid,
            status="valid" if valid else "invalid",
            reason_code=",".join(reasons) if reasons else "",
            reason_detail="; ".join(reasons) if reasons else "",
            action_id=aid, agent_id=agent,
            resource_sufficient=resource_sufficient,
            cooldown_allowed=cooldown_allowed,
            location_allowed=location_allowed,
            permission_allowed=permission_allowed,
            target_accessible=target_accessible,
        )
