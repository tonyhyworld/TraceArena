"""
P0-7 ScenarioValidator — 场景包强校验器

独立于 loader 的验证模块，在 L0 启动时拦截所有不合法场景包。
"""
from __future__ import annotations

import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

STANDARD_DIMENSIONS = {
    "understanding", "memory", "reasoning", "planning", "judgment",
    "selection", "execution", "risk_control", "tool_use", "recovery",
}

FORBIDDEN_ACTION_FIELDS = {"effects", "direct_metric", "score_delta"}
FORBIDDEN_TOOL_FIELDS = {"direct_state", "direct_metric"}
FORBIDDEN_NESTED = {
    "action": ["effects.metric", "metric_delta"],
    "tool": ["effects.metric", "metric_delta"],
    "claim": ["effects.win"],
    "director": ["effects.state"],
}

REQUIRED_FILES = [
    "manifest.json",
    "agents/roles.yaml",
    "world/objects.yaml",
    "world/actions.yaml",
    "world/metrics.yaml",
    "world/audit.yaml",
]


class ValidationResult:
    """场景包校验结果"""

    def __init__(self):
        self.errors: List[str] = []
        self.warnings: List[str] = []

    @property
    def passed(self) -> bool:
        return len(self.errors) == 0

    def error(self, msg: str) -> None:
        logger.error(f"[ScenarioValidator] ERROR: {msg}")
        self.errors.append(msg)

    def warn(self, msg: str) -> None:
        logger.warning(f"[ScenarioValidator] WARN: {msg}")
        self.warnings.append(msg)

    def summary(self) -> Dict[str, Any]:
        return {
            "passed": self.passed,
            "errors": self.errors,
            "warnings": self.warnings,
            "error_count": len(self.errors),
            "warning_count": len(self.warnings),
        }


class ScenarioValidator:
    """场景包强校验器（P0-7）"""

    @staticmethod
    def validate(scenario_dir: str, scenario: Any = None) -> ValidationResult:
        """校验场景包，返回 ValidationResult。scenario 为 LoadedScenario（可选）。"""
        result = ValidationResult()
        root = Path(scenario_dir)

        # 1. 文件完整性
        ScenarioValidator._check_files(root, result)

        if scenario is None:
            return result

        # 2. ID 唯一性
        ScenarioValidator._check_id_uniqueness(scenario, result)

        # 3. 引用完整性
        ScenarioValidator._check_references(scenario, result)

        # 4. 禁止字段
        ScenarioValidator._check_forbidden_fields(scenario, result)

        # 5. 维度合法性
        ScenarioValidator._check_dimensions(scenario, result)

        # 6. 通用能力挑战内容与引用
        ScenarioValidator._check_challenges(root, scenario, result)

        return result

    @staticmethod
    def _check_files(root: Path, result: ValidationResult) -> None:
        for f in REQUIRED_FILES:
            if not (root / f).exists():
                result.error(f"缺少必需文件: {f}")
        # 可选文件警告
        for f in ["world/locations.yaml", "world/resources.yaml", "world/tools.yaml"]:
            if not (root / f).exists():
                result.warn(f"可选文件不存在: {f}")

    @staticmethod
    def _check_id_uniqueness(scenario: Any, result: ValidationResult) -> None:
        def _unique(items: list, id_key: str, label: str) -> None:
            seen = set()
            for item in items:
                _id = item.get(id_key, item.get("id")) if isinstance(item, dict) else getattr(item, id_key, getattr(item, "id", None))
                if _id and _id in seen:
                    result.error(f"{label} ID 重复: {_id}")
                if _id:
                    seen.add(_id)

        _unique(getattr(scenario, "actions_cfg", []), "id", "action")
        _unique(getattr(scenario, "objects_cfg", []), "object_id", "object")
        _unique(getattr(scenario, "tools_cfg", []), "tool_id", "tool")
        _unique(getattr(scenario, "agent_roles", []), "agent_slot_id", "agent")
        _unique(getattr(scenario, "locations_cfg", []), "location_id", "location")
        _unique(getattr(scenario, "resources_cfg", []), "resource_id", "resource")

        metrics_cfg = getattr(scenario, "metrics_cfg", {})
        if isinstance(metrics_cfg, dict):
            _unique(metrics_cfg.get("metrics", []), "metric_id", "metric")

    @staticmethod
    def _check_references(scenario: Any, result: ValidationResult) -> None:
        object_ids = set()
        for obj in getattr(scenario, "objects_cfg", []):
            if isinstance(obj, dict):
                oid = obj.get("object_id", obj.get("id"))
                if oid:
                    object_ids.add(oid)

        location_ids = set()
        for loc in getattr(scenario, "locations_cfg", []):
            if isinstance(loc, dict):
                lid = loc.get("location_id", loc.get("id"))
                if lid:
                    location_ids.add(lid)

        resource_ids = set()
        for res in getattr(scenario, "resources_cfg", []):
            if isinstance(res, dict):
                rid = res.get("resource_id", res.get("id"))
                if rid:
                    resource_ids.add(rid)

        # metrics -> object_id
        metrics_cfg = getattr(scenario, "metrics_cfg", {})
        if isinstance(metrics_cfg, dict):
            for m in metrics_cfg.get("metrics", []):
                if isinstance(m, dict):
                    ref = m.get("object_id")
                    if ref and ref not in object_ids:
                        result.error(f"metrics 引用不存在的 object_id: {ref}")

        # locations -> connected_to
        for loc in getattr(scenario, "locations_cfg", []):
            if isinstance(loc, dict):
                for conn in loc.get("connected_to", []):
                    if conn not in location_ids:
                        result.error(f"location {loc.get('location_id', '?')} connected_to 引用不存在: {conn}")
                for vo in loc.get("visible_objects", []):
                    if vo not in object_ids:
                        result.warn(f"location {loc.get('location_id', '?')} visible_objects 引用不存在: {vo}")

        # roles -> start_location
        for role in getattr(scenario, "agent_roles", []):
            sl = getattr(role, "start_location", None) or (role.get("start_location") if isinstance(role, dict) else None)
            if sl and location_ids and sl not in location_ids:
                result.error(f"角色 {getattr(role, 'agent_slot_id', '?')} start_location 引用不存在: {sl}")

        # actions -> cost.resource_id
        for act in getattr(scenario, "actions_cfg", []):
            if isinstance(act, dict):
                cost = act.get("cost", {})
                if isinstance(cost, dict):
                    for rid in cost:
                        if resource_ids and rid not in resource_ids:
                            result.error(f"action {act.get('id', '?')} cost 引用不存在的 resource_id: {rid}")

        # audit -> metric
        metric_ids = set()
        if isinstance(metrics_cfg, dict):
            for m in metrics_cfg.get("metrics", []):
                if isinstance(m, dict):
                    mid = m.get("metric_id", m.get("id"))
                    if mid:
                        metric_ids.add(mid)
        audit_cfg = getattr(scenario, "audit_cfg", {})
        if isinstance(audit_cfg, dict):
            for rule in audit_cfg.get("rules", []):
                if isinstance(rule, dict):
                    ref = rule.get("metric")
                    if ref and metric_ids and ref not in metric_ids:
                        result.error(f"audit 引用不存在的 metric: {ref}")

    @staticmethod
    def _check_forbidden_fields(scenario: Any, result: ValidationResult) -> None:
        for act in getattr(scenario, "actions_cfg", []):
            if isinstance(act, dict):
                for f in FORBIDDEN_ACTION_FIELDS:
                    if f in act:
                        result.error(f"action {act.get('id', '?')} 包含禁止字段: {f}")

        for tool in getattr(scenario, "tools_cfg", []):
            if isinstance(tool, dict):
                for f in FORBIDDEN_TOOL_FIELDS:
                    if f in tool:
                        result.error(f"tool {tool.get('tool_id', tool.get('id', '?'))} 包含禁止字段: {f}")

    @staticmethod
    def _check_dimensions(scenario: Any, result: ValidationResult) -> None:
        for obj in getattr(scenario, "objects_cfg", []):
            if isinstance(obj, dict):
                needs = obj.get("needs")
                if isinstance(needs, (dict, list)):
                    keys = needs.keys() if isinstance(needs, dict) else [k for k in needs if isinstance(k, str)]
                    for k in keys:
                        if k not in STANDARD_DIMENSIONS:
                            result.error(f"object {obj.get('object_id', obj.get('id', '?'))} 非法维度: {k}")

        for act in getattr(scenario, "actions_cfg", []):
            if isinstance(act, dict):
                sn = act.get("suitable_needs")
                if isinstance(sn, (dict, list)):
                    keys = sn.keys() if isinstance(sn, dict) else [k for k in sn if isinstance(k, str)]
                    for k in keys:
                        if k not in STANDARD_DIMENSIONS:
                            result.error(f"action {act.get('id', '?')} 非法 suitable_needs 维度: {k}")

    @staticmethod
    def _check_challenges(root: Path, scenario: Any, result: ValidationResult) -> None:
        challenges_dir = root / "world" / "challenges"
        if not challenges_dir.exists():
            return
        action_ids = {
            item.get("id") for item in getattr(scenario, "actions_cfg", [])
            if isinstance(item, dict) and item.get("id")
        }
        object_ids = {
            item.get("object_id", item.get("id"))
            for item in getattr(scenario, "objects_cfg", [])
            if isinstance(item, dict)
        }
        metrics_cfg = getattr(scenario, "metrics_cfg", {}) or {}
        metric_ids = {
            item.get("id", item.get("metric_id"))
            for item in metrics_cfg.get("metrics", [])
            if isinstance(item, dict)
        }
        try:
            from app.framework.capability.challenge_library import ChallengeLibrary
            for path in sorted(challenges_dir.glob("*.yaml")):
                try:
                    lib = ChallengeLibrary.from_yaml(str(path))
                except Exception as exc:
                    result.error(f"挑战文件 {path.name} 非法: {exc}")
                    continue
                for node_id in lib._node_index:  # noqa: SLF001
                    meta = lib.node_meta(node_id)
                    trigger = meta.get("trigger", {})
                    for action_id in trigger.get("action_ids", []) or []:
                        if action_id not in action_ids:
                            result.error(
                                f"挑战 {node_id} trigger 引用不存在 action: {action_id}"
                            )
                    object_id = trigger.get("object_id")
                    if object_id and object_id not in object_ids:
                        result.error(
                            f"挑战 {node_id} trigger 引用不存在 object: {object_id}"
                        )
                    for variant in lib.variants_for(node_id):
                        for effects in variant.world_effects.values():
                            for effect in effects:
                                if effect.get("type") == "metric_delta":
                                    metric = effect.get("metric")
                                    if metric not in metric_ids:
                                        result.error(
                                            f"挑战 {node_id}:{variant.probe_key} "
                                            f"引用不存在 metric: {metric}"
                                        )
        except Exception as exc:
            result.error(f"挑战内容校验异常: {exc}")
