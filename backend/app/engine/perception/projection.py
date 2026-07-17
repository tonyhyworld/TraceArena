"""
P0-4 PerceptionProjectionService — 感知投影服务

将 WorldState 投影为 Agent 可见的 AgentView。
集成 LocationRegistry / AccessControlService / ResourceService / CooldownService / MemoryService。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class ProjectionContext:
    """投影上下文：单次投影的所有输入"""

    def __init__(
        self,
        agent_id: str,
        agent_location: Optional[str] = None,
        agent_permissions: Optional[List[str]] = None,
        agent_resources: Optional[Dict[str, float]] = None,
        agent_cooldowns: Optional[Dict[str, int]] = None,
        discovered_object_ids: Optional[List[str]] = None,
    ):
        self.agent_id = agent_id
        self.agent_location = agent_location
        self.agent_permissions = agent_permissions or []
        self.agent_resources = agent_resources or {}
        self.agent_cooldowns = agent_cooldowns or {}
        self.discovered_object_ids = set(discovered_object_ids or [])


class PerceptionProjectionService:
    """感知投影：基于地点/权限/资源过滤 Agent 可见信息"""

    def __init__(
        self,
        location_registry: Any = None,
        reachability: Any = None,
        access_control: Any = None,
        evidence_service: Any = None,
        visibility_rules: Optional[List[Dict[str, Any]]] = None,
    ):
        self._loc_reg = location_registry
        self._reach = reachability
        self._access = access_control
        self._evidence = evidence_service
        self._visibility_rule_types = {
            rule.get("type")
            for rule in (visibility_rules or [])
            if isinstance(rule, dict) and rule.get("type")
        }

    def filter_visible_objects(
        self, objects: List[Dict[str, Any]], ctx: ProjectionContext
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """过滤可见对象，返回 (visible_objects, hidden_exclusions)"""
        visible = []
        hidden = []
        location_visible_ids = None
        use_location_rule = (
            not self._visibility_rule_types
            or "location_based" in self._visibility_rule_types
        )
        if use_location_rule and ctx.agent_location and self._loc_reg:
            loc = self._loc_reg.get(ctx.agent_location)
            if loc and loc.visible_objects:
                location_visible_ids = set(loc.visible_objects)

        for obj in objects:
            obj_id = obj.get("id", obj.get("object_id", ""))
            visibility = obj.get("visibility", {})
            if (
                "discovery_based" in self._visibility_rule_types
                and isinstance(visibility, dict)
                and visibility.get("requires_discovery", False)
                and obj_id not in ctx.discovered_object_ids
            ):
                hidden.append(f"object:{obj_id}:not_discovered")
                continue
            # 地点过滤
            if location_visible_ids is not None and obj_id not in location_visible_ids:
                hidden.append(f"object:{obj_id}:not_visible_from_location")
                continue
            # 权限过滤
            if self._access:
                ok, reason = self._access.can_view_object(ctx.agent_id, obj)
                if not ok:
                    hidden.append(f"object:{obj_id}:{reason}")
                    continue
            visible.append(obj)
        return visible, hidden

    def filter_available_actions(
        self, actions: List[Dict[str, Any]], ctx: ProjectionContext
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """过滤可用动作"""
        visible = []
        hidden = []
        location_actions = None
        if ctx.agent_location and self._loc_reg:
            loc = self._loc_reg.get(ctx.agent_location)
            if loc and loc.available_actions:
                location_actions = set(loc.available_actions)

        for act in actions:
            act_id = act.get("id", "")
            if location_actions is not None and act_id not in location_actions:
                hidden.append(f"action:{act_id}:not_available_in_location")
                continue
            if self._access:
                ok, reason = self._access.can_execute_action(ctx.agent_id, act)
                if not ok:
                    hidden.append(f"action:{act_id}:{reason}")
                    continue
            cooldown_remaining = int(ctx.agent_cooldowns.get(act_id, 0) or 0)
            if cooldown_remaining > 0:
                hidden.append(
                    f"action:{act_id}:cooldown:{cooldown_remaining}"
                )
                continue
            cost = act.get("cost", {}) or {}
            if isinstance(cost, dict):
                insufficient = [
                    resource_id
                    for resource_id, amount in cost.items()
                    if float(ctx.agent_resources.get(resource_id, 0.0))
                    < float(amount)
                ]
                if insufficient:
                    hidden.append(
                        f"action:{act_id}:insufficient_resources:"
                        + ",".join(insufficient)
                    )
                    continue
            visible.append(act)
        return visible, hidden

    def filter_available_tools(
        self, tools: List[Dict[str, Any]], ctx: ProjectionContext
    ) -> Tuple[List[Dict[str, Any]], List[str]]:
        """过滤可用工具"""
        visible = []
        hidden = []
        location_tools = None
        if ctx.agent_location and self._loc_reg:
            loc = self._loc_reg.get(ctx.agent_location)
            if loc and loc.available_tools:
                location_tools = set(loc.available_tools)

        for tool in tools:
            tool_id = tool.get("tool_id", tool.get("id", ""))
            if location_tools is not None and tool_id not in location_tools:
                hidden.append(f"tool:{tool_id}:not_available_in_location")
                continue
            if self._access:
                ok, reason = self._access.can_use_tool(ctx.agent_id, tool)
                if not ok:
                    hidden.append(f"tool:{tool_id}:{reason}")
                    continue
            cooldown_remaining = int(ctx.agent_cooldowns.get(tool_id, 0) or 0)
            if cooldown_remaining > 0:
                hidden.append(
                    f"tool:{tool_id}:cooldown:{cooldown_remaining}"
                )
                continue
            cost = tool.get("cost", {}) or {}
            if isinstance(cost, dict):
                insufficient = [
                    resource_id
                    for resource_id, amount in cost.items()
                    if float(ctx.agent_resources.get(resource_id, 0.0))
                    < float(amount)
                ]
                if insufficient:
                    hidden.append(
                        f"tool:{tool_id}:insufficient_resources:"
                        + ",".join(insufficient)
                    )
                    continue
            visible.append(tool)
        return visible, hidden

    def get_reachable_locations(self, ctx: ProjectionContext) -> List[Dict[str, Any]]:
        """获取可达地点列表，含该地点的可见对象（供 agent 决策是否值得移动）"""
        if not ctx.agent_location or not self._reach:
            return []
        result = []
        for loc_id, cost in self._reach.reachable_locations(ctx.agent_location):
            loc = self._loc_reg.get(loc_id) if self._loc_reg else None
            entry = {
                "location_id": loc_id,
                "name": loc.name if loc else loc_id,
                "travel_cost": cost,
            }
            if loc:
                entry["risk_level"] = loc.risk_level
                # 附上该地点的可见对象列表（给 agent 移动作参考）
                if loc.visible_objects:
                    entry["visible_objects"] = loc.visible_objects
            result.append(entry)
        return result

    def get_risk_hints(self, ctx: ProjectionContext) -> List[str]:
        """获取风险提示"""
        hints = []
        if ctx.agent_location and self._loc_reg:
            loc = self._loc_reg.get(ctx.agent_location)
            if loc and loc.risk_level in ("medium", "high"):
                hints.append(f"当前地点风险等级: {loc.risk_level}")
        return hints

    def get_visible_evidence(self, ctx: ProjectionContext) -> List[str]:
        """获取可见证据 ID 列表"""
        if not self._evidence:
            return []
        if hasattr(self._evidence, "get_visible_evidence"):
            return self._evidence.get_visible_evidence(ctx.agent_id)
        return []
