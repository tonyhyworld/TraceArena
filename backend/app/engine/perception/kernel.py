"""
L2 Perception Kernel — Agent 局部感知包生成

职责：
- 为每个 Agent 构建隔离的 PerceptionPack / AgentBrief
- 通过 PerceptionProjectionService 按地点/权限过滤可见对象和可用行动
- Agent 只能看到自己有权看到的信息

场景无关：本层不写死任何 action_id / location_id / role_id，
所有过滤逻辑由 PerceptionProjectionService 读场景包配置驱动。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.interfaces import ActionOption, AgentBrief, PerceptionPack

logger = logging.getLogger(__name__)


class PerceptionKernel:
    """
    L2 感知内核。

    每个 Agent 收到的感知包由此层生成，互相隔离，不泄露秘密。
    """

    def __init__(self, scenario_name: str):
        self._scenario_name = scenario_name
        self._brief_builder: Any = None
        self._projection: Any = None        # PerceptionProjectionService
        self._actions_cfg: List[Dict[str, Any]] = []
        self._tools_cfg: List[Dict[str, Any]] = []

    def set_brief_builder(self, builder: Any) -> None:
        self._brief_builder = builder

    def set_terminology(self, terminology: Dict[str, str]) -> None:
        """注入术语表（用于翻译英文 ID 为中文名）"""
        if self._brief_builder and hasattr(self._brief_builder, "set_terminology"):
            self._brief_builder.set_terminology(terminology)

    def set_projection_service(self, projection: Any) -> None:
        """注入 PerceptionProjectionService（由 EngineOS 在初始化时调用）"""
        self._projection = projection

    def set_action_tool_configs(
        self,
        actions_cfg: List[Dict[str, Any]],
        tools_cfg: List[Dict[str, Any]],
    ) -> None:
        """注入场景包的 actions 和 tools 配置"""
        self._actions_cfg = actions_cfg
        self._tools_cfg = tools_cfg
        self._action_index = {
            item.get("id", ""): item
            for item in actions_cfg
            if isinstance(item, dict) and item.get("id")
        }

    def set_evidence_service(self, evidence_service: Any) -> None:
        """注入 EvidenceService（供 build_briefs 获取已知证据）"""
        self._evidence_service = evidence_service

    def build_perception_pack(
        self,
        tick: int,
        agent_id: str,
        perception_data: Dict[str, Any],
        available_actions: List[ActionOption],
        memory_summary: str = "",
    ) -> PerceptionPack:
        """构建单个 Agent 的感知包（旧模式）"""
        return PerceptionPack(
            tick=tick,
            agent_id=agent_id,
            scenario_name=self._scenario_name,
            perception=perception_data,
            available_actions=available_actions,
            memory_summary=memory_summary,
        )

    def build_briefs(
        self,
        state: Any,
        ruleworld_ctx: Any = None,
        agent_roles_map: Optional[Dict[str, Any]] = None,
        agent_names: Optional[Dict[str, str]] = None,
    ) -> Dict[str, AgentBrief]:
        """
        为所有存活 Agent 构建简报，并按地点/权限过滤可用行动和可见对象。

        场景无关：过滤逻辑由 PerceptionProjectionService 读场景包的
        locations[].available_actions / visible_objects 配置驱动。
        """
        if self._brief_builder is None:
            return {}

        from app.framework.prompting.agent_brief_builder import build_briefs

        briefs = build_briefs(
            self._brief_builder,
            state,
            ruleworld_ctx=ruleworld_ctx,
            agent_roles_map=agent_roles_map,
            agent_names=agent_names,
            evidence_service=getattr(self, "_evidence_service", None),
        )

        # 按地点/权限过滤每个 agent 的可用行动和可见对象
        if self._projection:
            from app.engine.perception.projection import ProjectionContext

            alive = getattr(state, "alive_agent_ids", []) or []
            for aid in alive:
                brief = briefs.get(aid)
                if brief is None:
                    continue

                agent_loc = getattr(state, "agent_locations", {}).get(aid)
                agent_perms = getattr(state, "permissions", {}).get(aid, [])
                agent_res = getattr(state, "resources", {}).get(aid, {})
                agent_cd = getattr(state, "cooldowns", {}).get(aid, {})
                discoveries = (
                    getattr(state, "internal", {})
                    .get("discoveries", {})
                    .get(aid, [])
                )

                ctx = ProjectionContext(
                    agent_id=aid,
                    agent_location=agent_loc,
                    agent_permissions=agent_perms,
                    agent_resources=agent_res,
                    agent_cooldowns=agent_cd,
                    discovered_object_ids=discoveries,
                )

                # 过滤可用行动：按地点 available_actions + 权限
                filtered_actions, action_exclusions = self._projection.filter_available_actions(
                    self._actions_cfg, ctx,
                )
                brief.available_actions = [
                    {
                        "id": a.get("id", ""),
                        "name": a.get("name", a.get("id", "")),
                        "description": a.get("description", ""),
                        "requires_target": a.get("requires_target", False),
                        "allows_code": a.get("allows_code", False),
                        "target_kind": a.get("target_kind", ""),
                        "target_types": list(a.get("target_types", []) or []),
                        "parameters_schema": dict(
                            a.get("parameters_schema", {}) or {}
                        ),
                        "target_optional_for_settlement": bool(
                            a.get("target_optional_for_settlement", False)
                        ),
                        "execution_semantics": str(
                            a.get("execution_semantics", "") or ""
                        ),
                    }
                    for a in filtered_actions
                ]

                # 过滤可见对象：按地点 visible_objects + 权限
                all_objects = brief.visible_objects or []
                # visible_objects 可能是 dict 列表
                filtered_objs, obj_exclusions = self._projection.filter_visible_objects(
                    all_objects, ctx,
                )
                brief.visible_objects = filtered_objs

                # 不向模型提供当前没有合法目标的动作。这个过滤只读取场景包
                # 的 target_kind / target_types 和本回合可见对象，不认识任何
                # 具体 action_id 或场景对象。
                visible_types = {
                    str(obj.get("type", ""))
                    for obj in filtered_objs
                    if isinstance(obj, dict)
                }
                # 追踪因 same_location 约束被隐藏的行动（供战略提示使用）
                location_locked_actions: List[Dict[str, Any]] = []
                executable_actions = []
                for act in brief.available_actions:
                    target_kind = act.get("target_kind", "")
                    target_types = set(act.get("target_types", []) or [])
                    raw_cfg = self._action_index.get(act.get("id", ""), {})
                    target_optional_for_settlement = bool(
                        raw_cfg.get("target_optional_for_settlement", False)
                    )
                    needs_typed_target = (
                        act.get("requires_target", False)
                        and not target_optional_for_settlement
                        and target_kind in ("object", "evidence")
                    )
                    if needs_typed_target:
                        eligible_objects = [
                            str(obj.get("id", ""))
                            for obj in filtered_objs
                            if isinstance(obj, dict)
                            and obj.get("id")
                            and (
                                not target_types
                                or str(obj.get("type", "")) in target_types
                                or "object" in target_types
                            )
                        ]
                        if not eligible_objects:
                            action_exclusions.append(
                                f"action:{act.get('id', '')}:no_compatible_target"
                            )
                            continue
                        act["eligible_target_objects"] = eligible_objects
                    elif (
                        act.get("requires_target", False)
                        and target_optional_for_settlement
                        and target_kind in ("object", "evidence")
                    ):
                        eligible_objects = [
                            str(obj.get("id", ""))
                            for obj in filtered_objs
                            if isinstance(obj, dict)
                            and obj.get("id")
                            and (
                                not target_types
                                or str(obj.get("type", "")) in target_types
                                or "object" in target_types
                            )
                        ]
                        if eligible_objects:
                            act["eligible_target_objects"] = eligible_objects
                        act["target_optional_for_settlement"] = True
                        act["description"] = (
                            f"{act.get('description', '')} "
                            "如果真实目标由参数指定，可不选择场景对象目标。"
                        ).strip()
                    if target_kind == "agent":
                        raw_cfg = self._action_index.get(act.get("id", ""), {})
                        target_scope = str(
                            raw_cfg.get("target_scope", "visible") or "visible"
                        )
                        eligible = []
                        # 记录被 same_location 排除的对手及其位置（用于提示）
                        skipped_with_locations: List[Dict[str, str]] = []
                        for other_id in alive:
                            if other_id == aid:
                                continue
                            other_loc = getattr(state, "agent_locations", {}).get(
                                other_id
                            )
                            if (
                                target_scope == "same_location"
                                and other_loc != agent_loc
                            ):
                                if other_loc:
                                    skipped_with_locations.append(
                                        {"agent_id": other_id, "location": other_loc}
                                    )
                                continue
                            eligible.append(other_id)
                        if act.get("requires_target") and not eligible:
                            action_exclusions.append(
                                f"action:{act.get('id', '')}:no_agent_target"
                            )
                            # 如果是因为 same_location 导致无目标，记录下来
                            if target_scope == "same_location" and skipped_with_locations:
                                unique_locs = list({
                                    item["location"] for item in skipped_with_locations
                                })
                                location_locked_actions.append({
                                    "action_id": act.get("id", ""),
                                    "action_name": act.get("name", act.get("id", "")),
                                    "description": act.get("description", ""),
                                    "required_locations": unique_locs,
                                })
                            continue
                        act["eligible_target_agents"] = eligible
                    executable_actions.append(act)
                brief.available_actions = executable_actions
                brief.location_locked_actions = location_locked_actions

                # 过滤可用工具：按地点 available_tools + 权限
                filtered_tools, _ = self._projection.filter_available_tools(
                    self._tools_cfg, ctx,
                )
                brief.available_tools = filtered_tools

                # 填充当前位置和可达地点（供 prompt 告知 agent 移动选项）
                brief.self_location = agent_loc
                brief.reachable_locations = self._projection.get_reachable_locations(ctx)

                # 补充 target_kind；任何地点目标动作都由配置声明，不识别具体 action_id。
                reachable_ids = [r.get("location_id", "") for r in brief.reachable_locations]
                for act in brief.available_actions:
                    # 从原始配置中查找对应的 target_kind
                    raw_cfg = self._action_index.get(act.get("id", ""))
                    if raw_cfg:
                        act["target_kind"] = raw_cfg.get("target_kind", "")
                        act["target_types"] = list(
                            raw_cfg.get("target_types", []) or []
                        )
                    # 如果是移动类行动，在描述中补充可达地点
                    if act.get("target_kind") == "location" and reachable_ids:
                        act["description"] = f"{act.get('description', '')} 可移动到：{', '.join(reachable_ids)}"

                # 记录被过滤的内容（供调试/审计，不泄露给 agent）
                if action_exclusions or obj_exclusions:
                    existing = brief.hidden_info_exclusions or []
                    brief.hidden_info_exclusions = existing + action_exclusions + obj_exclusions

                logger.debug(
                    f"[L2] agent={aid} loc={agent_loc} "
                    f"actions={len(filtered_actions)}/{len(self._actions_cfg)} "
                    f"objects={len(filtered_objs)}/{len(all_objects)} "
                    f"tools={len(filtered_tools)}/{len(self._tools_cfg)}"
                )

        return briefs
