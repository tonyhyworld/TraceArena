"""L0 Scenario Compiler — 把已加载场景编译为可索引、可审计的运行契约。"""
from __future__ import annotations

from pathlib import Path
from typing import Any, Dict, List, Set, Tuple, Union

from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import ScenarioLoadError
from app.engine.effects.dsl import EffectDSL


class ConsumptionReport(BaseModel):
    """场景声明到 OS 消费者的覆盖报告。"""
    consumers: Dict[str, List[str]] = Field(default_factory=dict)
    required_sections: List[str] = Field(default_factory=list)
    missing_consumers: List[str] = Field(default_factory=list)
    unconsumed_declared_sections: List[str] = Field(default_factory=list)

    @property
    def passed(self) -> bool:
        return not self.missing_consumers


class MeasurementContractReport(BaseModel):
    """场景动作对抽象能力维度的声明索引。"""
    capability_actions: Dict[str, List[str]] = Field(default_factory=dict)
    action_intents: Dict[str, str] = Field(default_factory=dict)


class CompiledScenario(BaseModel):
    """L0 编译产物：静态定义、索引与消费覆盖，不含运行状态。"""
    source: Any
    role_index: Dict[str, Any] = Field(default_factory=dict)
    action_index: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    object_index: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    tool_index: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    location_index: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    resource_index: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    metric_index: Dict[str, Dict[str, Any]] = Field(default_factory=dict)
    render_action_index: Dict[str, Any] = Field(default_factory=dict)
    render_object_index: Dict[str, Any] = Field(default_factory=dict)
    render_location_index: Dict[str, Any] = Field(default_factory=dict)
    consumption: ConsumptionReport = Field(default_factory=ConsumptionReport)
    measurement: MeasurementContractReport = Field(
        default_factory=MeasurementContractReport
    )

    model_config = ConfigDict(arbitrary_types_allowed=True)


SECTION_CONSUMERS: Dict[str, List[str]] = {
    "roles": ["L3.AgentRuntime", "L2.Perception", "L6.Presentation"],
    "characters": ["API.ScenarioCharacterBinding"],
    "objects": ["L2.Perception", "L5.CausalPhysics"],
    "actions": ["L2.Perception", "L4.ActionRuntime", "L5.Evaluation"],
    "metrics": ["L5.SimulationMetrics", "Scenario.Settlement", "Frontend.Renderer"],
    "tools": ["L2.Perception", "L4.Sandbox"],
    "audit": ["TerminalStrategy", "Trace.Report"],
    "settlement": ["SettlementRuntime", "Operator.Provenance"],
    "locations": ["L1.WorldState", "L2.Perception", "Frontend.Renderer"],
    "resources": ["L1.ResourceLifecycle", "L4.ActionRuntime"],
    "permissions": ["L2.AccessControl", "L4.Preconditions"],
    "visibility": ["L2.PerceptionProjection"],
    "causal_physics": ["L5.CausalPhysics"],
    "measurement_opportunities": [
        "L2.MeasurementOpportunityCoordinator",
        "Benchmark.ValidityLedger",
    ],
    "prompt_contract": ["L3.PromptAssembler", "L3.ActionParser"],
    "playback_policy": ["PresentationBuffer"],
    "director": ["L6.Director"],
    "thought_display": ["L3.PublicReasoning", "Frontend.Renderer"],
    "render": ["API.Scenario", "Frontend.Renderer"],
    "scene": ["API.Scenario", "L6.Intro"],
    "assets": ["StaticAssets", "Frontend.Renderer"],
    "validation_spec": ["L0.ScenarioCompiler"],
    "sample_run_spec": ["L0.SampleRunCompiler", "TestHarness"],
    "replay_expectation": ["L0.ReplayContractCompiler"],
}


FEATURE_REQUIREMENTS: Dict[str, Set[str]] = {
    "map": {"locations"},
    "resources": {"resources"},
    "cooldown": {"actions"},
    "permissions": {"permissions"},
    "visibility": {"visibility"},
    "tools": {"tools"},
    "evidence": {"tools", "objects"},
    "delayed_events": {"causal_physics"},
    "director": {"director"},
    "thought_display": {"thought_display", "prompt_contract"},
    "camera_control": {"render"},
    "capability_evaluation": {"actions", "objects"},
    "terminal_settlement": {"settlement"},
    "replay": {"replay_expectation"},
    "presentation_buffer": {"playback_policy"},
}

FEATURE_CONSUMERS: Dict[str, List[str]] = {
    "map": ["L1.Location", "L2.Perception"],
    "resources": ["L1.ResourceLifecycle"],
    "cooldown": ["L1.CooldownLifecycle", "L4.Preconditions"],
    "permissions": ["L2.AccessControl"],
    "visibility": ["L2.PerceptionProjection"],
    "memory": ["L3.AgentMemory"],
    "tools": ["L4.Sandbox"],
    "scripts": ["L4.Sandbox"],
    "evidence": ["L4.Evidence", "L5.Evaluation"],
    "delayed_events": ["L1.DelayedEvents"],
    "director": ["L6.Director"],
    "thought_display": ["L3.PublicReasoning", "L6.Presentation"],
    "camera_control": ["DirectorRuntime", "Frontend.Renderer"],
    "capability_evaluation": ["L5.ChallengeAssessment"],
    "terminal_settlement": ["SettlementRuntime"],
    "replay": ["Trace.Replay"],
    "presentation_buffer": ["PresentationBuffer"],
}


class ScenarioCompiler:
    """把 LoadedScenario 编译成唯一的静态运行契约。"""

    @classmethod
    def compile(cls, scenario: Any) -> CompiledScenario:
        cls._validate_declared_files(scenario)
        role_index = cls._index_models(
            scenario.agent_roles, "agent_slot_id", "role"
        )
        action_index = cls._index_dicts(scenario.actions_cfg, "id", "action")
        cls._validate_action_measurement_contract(action_index)
        object_index = cls._index_dicts(
            scenario.objects_cfg, ("object_id", "id"), "object"
        )
        tool_index = cls._index_dicts(
            scenario.tools_cfg, ("tool_id", "id"), "tool"
        )
        cls._validate_measurement_opportunities(
            scenario.measurement_opportunities,
            action_index=action_index,
            tool_index=tool_index,
        )
        location_index = cls._index_dicts(
            scenario.locations_cfg, ("location_id", "id"), "location"
        )
        resource_index = cls._index_dicts(
            scenario.resources_cfg, ("resource_id", "id"), "resource"
        )
        metric_defs = (
            scenario.metrics_cfg.get("metrics", [])
            if isinstance(scenario.metrics_cfg, dict)
            else []
        )
        metric_index = cls._index_dicts(
            metric_defs, ("metric_id", "id"), "metric"
        )

        cls._validate_references(
            scenario=scenario,
            role_index=role_index,
            action_index=action_index,
            object_index=object_index,
            tool_index=tool_index,
            location_index=location_index,
            resource_index=resource_index,
            metric_index=metric_index,
        )
        cls._validate_render_bindings(
            scenario,
            role_index=role_index,
            action_index=action_index,
            object_index=object_index,
            tool_index=tool_index,
            location_index=location_index,
            metric_index=metric_index,
        )
        cls._validate_embedded_spec(
            scenario,
            action_index=action_index,
            object_index=object_index,
            tool_index=tool_index,
            location_index=location_index,
            metric_index=metric_index,
        )
        cls._validate_sample_run(
            scenario,
            role_index=role_index,
            action_index=action_index,
            object_index=object_index,
            location_index=location_index,
        )
        cls._validate_replay_contract(scenario)
        cls._validate_settlement_contract(scenario)
        cls._validate_assets(scenario)
        consumption = cls._build_consumption_report(scenario)
        measurement = cls._build_measurement_contract(action_index)
        if not consumption.passed:
            raise ScenarioLoadError(
                "场景声明缺少运行时消费者:\n- "
                + "\n- ".join(consumption.missing_consumers)
            )

        render = scenario.presentation.render
        return CompiledScenario(
            source=scenario,
            role_index=role_index,
            action_index=action_index,
            object_index=object_index,
            tool_index=tool_index,
            location_index=location_index,
            resource_index=resource_index,
            metric_index=metric_index,
            render_action_index=dict(render.actions),
            render_object_index=dict(render.objects),
            render_location_index=dict(render.locations),
            consumption=consumption,
            measurement=measurement,
        )

    @staticmethod
    def _validate_settlement_contract(scenario: Any) -> None:
        config = getattr(scenario, "settlement_cfg", {}) or {}
        providers = config.get("providers", []) or []
        observations = config.get("observations", []) or []
        valid_modes = {
            "simulation", "external_reality",
            "deterministic_verifier", "hybrid",
        }
        errors: List[str] = []
        provider_ids: Set[str] = set()
        provider_modes: Dict[str, str] = {}
        for provider in providers:
            if not isinstance(provider, dict):
                errors.append("settlement provider 必须是对象")
                continue
            provider_id = str(provider.get("id") or "")
            mode = str(provider.get("authority") or provider.get("mode") or "")
            if not provider_id:
                errors.append("settlement provider 缺少 id")
            elif provider_id in provider_ids:
                errors.append(f"settlement provider id 重复: {provider_id}")
            provider_ids.add(provider_id)
            if provider_id:
                provider_modes[provider_id] = mode
            if mode not in valid_modes:
                errors.append(f"{provider_id or 'provider'} authority 不支持: {mode}")
            if not provider.get("rule_version"):
                errors.append(f"{provider_id or 'provider'} 缺少 rule_version")
            if mode == "deterministic_verifier" and not provider.get("verifier_id"):
                errors.append(f"{provider_id} 缺少 verifier_id")
            if mode == "hybrid":
                components = set(provider.get("component_modes", []) or [])
                if len(components) < 2 or not components.issubset(
                    valid_modes - {"hybrid"}
                ):
                    errors.append(f"{provider_id} component_modes 无效")
        execution = config.get("execution") or {}
        default_route = execution.get("default") if isinstance(execution, dict) else None
        routes = execution.get("routes", {}) if isinstance(execution, dict) else {}
        if not isinstance(default_route, dict):
            errors.append("execution.default 必须声明场景默认执行路由")
        route_items = [("default", default_route)] + list(
            (routes or {}).items() if isinstance(routes, dict) else []
        )
        for action_id, route in route_items:
            if not isinstance(route, dict):
                if action_id != "default" or default_route is not None:
                    errors.append(f"execution route {action_id} 必须是对象")
                continue
            mode = str(route.get("mode") or "")
            provider_id = str(route.get("provider_id") or "")
            if mode not in valid_modes:
                errors.append(f"execution route {action_id} mode 不支持: {mode}")
            if provider_id not in provider_ids:
                errors.append(
                    f"execution route {action_id} 引用了未声明 provider: {provider_id}"
                )
            elif provider_modes.get(provider_id) != mode:
                errors.append(
                    f"execution route {action_id} mode 与 provider {provider_id} 权限不一致"
                )
        observation_ids: Set[str] = set()
        for observation in observations:
            if not isinstance(observation, dict):
                errors.append("observation 声明必须是对象")
                continue
            observation_id = str(observation.get("id") or "")
            if not observation_id:
                errors.append("observation 缺少 id")
            elif observation_id in observation_ids:
                errors.append(f"observation id 重复: {observation_id}")
            observation_ids.add(observation_id)
            for field in (
                "provider_id", "observation_type", "registry_path"
            ):
                if not observation.get(field):
                    errors.append(f"{observation_id or 'observation'} 缺少 {field}")
        if errors:
            raise ScenarioLoadError(
                "结算权限契约编译失败:\n- " + "\n- ".join(errors)
            )

    @staticmethod
    def _validate_action_measurement_contract(
        action_index: Dict[str, Dict[str, Any]]
    ) -> None:
        valid_intents = {
            "improve", "reduce", "attack", "defend", "investigate",
            "build", "repair", "negotiate", "optimize", "wait", "unknown",
        }
        errors = []
        for action_id, action in action_index.items():
            intent = action.get("intent")
            if intent and intent not in valid_intents:
                errors.append(
                    f"action {action_id} intent 不支持: {intent}"
                )
            if (action.get("suitable_needs", []) or []) and not intent:
                errors.append(
                    f"action {action_id} 声明 suitable_needs 但缺少通用 intent"
                )
        if errors:
            raise ScenarioLoadError(
                "动作测量契约编译失败:\n- " + "\n- ".join(errors)
            )

    @staticmethod
    def _build_measurement_contract(
        action_index: Dict[str, Dict[str, Any]]
    ) -> MeasurementContractReport:
        capability_actions: Dict[str, List[str]] = {}
        action_intents = {}
        for action_id, action in action_index.items():
            if action.get("intent"):
                action_intents[action_id] = str(action["intent"])
            for capability in action.get("suitable_needs", []) or []:
                capability_actions.setdefault(str(capability), []).append(
                    action_id
                )
        return MeasurementContractReport(
            capability_actions={
                name: sorted(action_ids)
                for name, action_ids in sorted(capability_actions.items())
            },
            action_intents=action_intents,
        )

    @staticmethod
    def _validate_measurement_opportunities(
        config: Dict[str, Any],
        *,
        action_index: Dict[str, Dict[str, Any]],
        tool_index: Dict[str, Dict[str, Any]],
    ) -> None:
        raw = config.get("measurement_opportunities", config) or {}
        dimensions = raw.get("dimensions", {}) or {}
        valid_dimensions = {
            "understanding", "memory", "reasoning", "planning", "judgment",
            "selection", "execution", "risk_control", "tool_use", "recovery",
        }
        errors = []
        for capability, spec in dimensions.items():
            if capability not in valid_dimensions:
                errors.append(f"未知能力维度: {capability}")
                continue
            unknown_actions = sorted(
                set(spec.get("eligible_actions", []) or []) - set(action_index)
            )
            unknown_tools = sorted(
                set(spec.get("eligible_tools", []) or []) - set(tool_index)
            )
            if unknown_actions:
                errors.append(
                    f"{capability} 引用不存在 actions: {unknown_actions}"
                )
            if unknown_tools:
                errors.append(
                    f"{capability} 引用不存在 tools: {unknown_tools}"
                )
            if not spec.get("eligible_actions") and not spec.get("eligible_tools"):
                errors.append(f"{capability} 没有声明任何测评机会入口")
        if errors:
            raise ScenarioLoadError(
                "测评机会协议编译失败:\n- " + "\n- ".join(errors)
            )

    @staticmethod
    def _validate_declared_files(scenario: Any) -> None:
        errors = []
        root = scenario.scenario_dir
        for logical_name, relative_path in scenario.manifest.entry_files.items():
            if not (root / relative_path).exists():
                errors.append(
                    f"manifest entry_files.{logical_name} 不存在: {relative_path}"
                )
        validation = scenario.validation_spec.get("validation", {})
        for relative_path in validation.get("required_files", []) or []:
            if not (root / relative_path).exists():
                errors.append(f"validation.required_files 不存在: {relative_path}")
        if errors:
            raise ScenarioLoadError(
                "场景文件编译失败:\n- " + "\n- ".join(errors)
            )

    @staticmethod
    def _index_models(items: List[Any], key: str, label: str) -> Dict[str, Any]:
        result: Dict[str, Any] = {}
        for item in items:
            item_id = getattr(item, key, "")
            if not item_id:
                raise ScenarioLoadError(f"{label} 缺少 {key}")
            if item_id in result:
                raise ScenarioLoadError(f"{label} ID 重复: {item_id}")
            result[item_id] = item
        return result

    @staticmethod
    def _index_dicts(
        items: List[Dict[str, Any]],
        keys: Union[str, Tuple[str, ...]],
        label: str,
    ) -> Dict[str, Dict[str, Any]]:
        lookup_keys = (keys,) if isinstance(keys, str) else keys
        result: Dict[str, Dict[str, Any]] = {}
        for item in items:
            if not isinstance(item, dict):
                raise ScenarioLoadError(f"{label} 定义必须是对象")
            item_id = next((item.get(key) for key in lookup_keys if item.get(key)), "")
            if not item_id:
                raise ScenarioLoadError(f"{label} 缺少 ID")
            if item_id in result:
                raise ScenarioLoadError(f"{label} ID 重复: {item_id}")
            result[str(item_id)] = item
        return result

    @classmethod
    def _validate_references(
        cls,
        *,
        scenario: Any,
        role_index: Dict[str, Any],
        action_index: Dict[str, Dict[str, Any]],
        object_index: Dict[str, Dict[str, Any]],
        tool_index: Dict[str, Dict[str, Any]],
        location_index: Dict[str, Dict[str, Any]],
        resource_index: Dict[str, Dict[str, Any]],
        metric_index: Dict[str, Dict[str, Any]],
    ) -> None:
        errors: List[str] = []

        for role_id, role in role_index.items():
            start = getattr(role, "start_location", None)
            if start and start not in location_index:
                errors.append(f"role {role_id} 引用不存在地点: {start}")
            known_permissions = {
                item.get("id")
                for item in scenario.permission_definitions
                if isinstance(item, dict) and item.get("id")
            }
            for permission_id in getattr(role, "permissions", []) or []:
                if known_permissions and permission_id not in known_permissions:
                    errors.append(
                        f"role {role_id} 引用不存在 permission: {permission_id}"
                    )

        for action_id, action in action_index.items():
            for resource_id in (action.get("cost", {}) or {}):
                if resource_id not in resource_index:
                    errors.append(
                        f"action {action_id} 引用不存在资源: {resource_id}"
                    )

        for location_id, location in location_index.items():
            for target in location.get("connected_to", []) or []:
                if target not in location_index:
                    errors.append(
                        f"location {location_id} connected_to 不存在: {target}"
                    )
            for action_id in location.get("available_actions", []) or []:
                if action_id not in action_index:
                    errors.append(
                        f"location {location_id} 引用不存在 action: {action_id}"
                    )
            for tool_id in location.get("available_tools", []) or []:
                if tool_id not in tool_index:
                    errors.append(
                        f"location {location_id} 引用不存在 tool: {tool_id}"
                    )
            for object_id in location.get("visible_objects", []) or []:
                if object_id not in object_index:
                    errors.append(
                        f"location {location_id} 引用不存在 object: {object_id}"
                    )

        derivations = (
            scenario.metrics_cfg.get("metric_derivations", [])
            if isinstance(scenario.metrics_cfg, dict)
            else []
        )
        for rule in derivations:
            object_id = rule.get("object_id")
            metric_id = rule.get("metric")
            if object_id and object_id not in object_index:
                errors.append(f"metric derivation 引用不存在 object: {object_id}")
            if metric_id and metric_id not in metric_index:
                errors.append(f"metric derivation 引用不存在 metric: {metric_id}")

        if errors:
            raise ScenarioLoadError(
                "场景引用编译失败:\n- " + "\n- ".join(errors)
            )

    @staticmethod
    def _validate_render_bindings(
        scenario: Any,
        *,
        role_index: Dict[str, Any],
        action_index: Dict[str, Dict[str, Any]],
        object_index: Dict[str, Dict[str, Any]],
        tool_index: Dict[str, Dict[str, Any]],
        location_index: Dict[str, Dict[str, Any]],
        metric_index: Dict[str, Dict[str, Any]],
    ) -> None:
        bindings = scenario.presentation.render.bindings or {}
        render = scenario.presentation.render
        if not bindings and not (
            render.actions or render.objects or render.locations
        ):
            return
        errors: List[str] = []
        checks = [
            ("actions", action_index, render.actions),
            ("objects", object_index, render.objects),
            ("locations", location_index, render.locations),
        ]
        for section, domain_index, render_index in checks:
            section_bindings = bindings.get(section, {}) or {}
            for domain_id in domain_index:
                binding_id = section_bindings.get(domain_id)
                if not binding_id:
                    errors.append(f"render binding 缺少 {section}.{domain_id}")
                elif binding_id not in render_index:
                    errors.append(
                        f"render binding {section}.{domain_id} "
                        f"引用不存在渲染定义: {binding_id}"
                    )

        for section, domain_index in (
            ("tools", tool_index),
            ("metrics", metric_index),
        ):
            section_bindings = bindings.get(section, {}) or {}
            for domain_id in domain_index:
                if domain_id not in section_bindings:
                    errors.append(f"render binding 缺少 {section}.{domain_id}")

        for outcome, binding_id in (bindings.get("outcomes", {}) or {}).items():
            if binding_id not in render.actions:
                errors.append(
                    f"render binding outcomes.{outcome} "
                    f"引用不存在渲染定义: {binding_id}"
                )

        character_ids = {
            item.get("id")
            for item in scenario.characters_cfg
            if isinstance(item, dict) and item.get("id")
        }
        char_bindings = bindings.get("characters", {}) or {}
        for role_id, role in role_index.items():
            profile = getattr(role, "capability_profile", {}) or {}
            character_id = profile.get("character_id")
            if character_id and character_id not in character_ids:
                errors.append(
                    f"role {role_id} 引用不存在 character: {character_id}"
                )
            if character_id and character_id not in char_bindings:
                errors.append(
                    f"render binding 缺少 characters.{character_id}"
                )

        camera_ids = set(render.cameras)
        effect_ids = set(render.effects)
        errors.extend(EffectDSL.validate(render.effects))
        for binding_id, action_render in render.actions.items():
            camera = getattr(action_render, "camera", "")
            effect = getattr(action_render, "effect", "")
            if camera and camera not in camera_ids:
                errors.append(
                    f"render action {binding_id} 引用不存在 camera: {camera}"
                )
            if effect and effect != "none" and effect not in effect_ids:
                errors.append(
                    f"render action {binding_id} 引用不存在 effect: {effect}"
                )
        for binding_id, location_render in render.locations.items():
            for camera in (getattr(location_render, "camera", {}) or {}).values():
                if camera and camera not in camera_ids:
                    errors.append(
                        f"render location {binding_id} 引用不存在 camera: {camera}"
                    )
        for binding_id, object_render in render.objects.items():
            for effect in (getattr(object_render, "effects", {}) or {}).values():
                if effect and effect != "none" and effect not in effect_ids:
                    errors.append(
                        f"render object {binding_id} 引用不存在 effect: {effect}"
                    )

        if errors:
            raise ScenarioLoadError(
                "渲染引用编译失败:\n- " + "\n- ".join(errors)
            )

    @staticmethod
    def _validate_embedded_spec(
        scenario: Any,
        *,
        action_index: Dict[str, Dict[str, Any]],
        object_index: Dict[str, Dict[str, Any]],
        tool_index: Dict[str, Dict[str, Any]],
        location_index: Dict[str, Dict[str, Any]],
        metric_index: Dict[str, Dict[str, Any]],
    ) -> None:
        spec = scenario.validation_spec.get("validation", {})
        if not spec:
            return
        errors: List[str] = []
        indexes = {
            "locations": location_index,
            "objects": object_index,
            "actions": action_index,
            "tools": tool_index,
            "metrics": metric_index,
            "cameras": scenario.presentation.render.cameras,
        }
        for section, expected_ids in (spec.get("expected_ids", {}) or {}).items():
            if section not in indexes:
                continue
            missing = sorted(set(expected_ids or []) - set(indexes[section]))
            if missing:
                errors.append(f"validation expected_ids.{section} 缺少: {missing}")
        minimums = spec.get("minimum_counts", {}) or {}
        for section, minimum in minimums.items():
            if section in indexes:
                actual = len(indexes[section])
            else:
                continue
            if actual < int(minimum):
                errors.append(
                    f"validation minimum_counts.{section}: "
                    f"{actual} < {minimum}"
                )
        if errors:
            raise ScenarioLoadError(
                "场景内置验证规范失败:\n- " + "\n- ".join(errors)
            )

    @staticmethod
    def _validate_assets(scenario: Any) -> None:
        manifest = scenario.assets_manifest.get("assets", {})
        if not isinstance(manifest, dict):
            return
        errors: List[str] = []
        seen_ids: Set[str] = set()
        for items in manifest.values():
            if not isinstance(items, list):
                continue
            for item in items:
                if not isinstance(item, dict):
                    continue
                asset_id = item.get("id")
                path = item.get("path")
                if asset_id:
                    if asset_id in seen_ids:
                        errors.append(f"asset ID 重复: {asset_id}")
                    seen_ids.add(asset_id)
                if path and not (scenario.scenario_dir / path).exists():
                    errors.append(f"asset 路径不存在: {path}")
                if path and item.get("format"):
                    suffix = Path(str(path)).suffix.lower().lstrip(".")
                    declared = str(item["format"]).lower().lstrip(".")
                    if suffix and declared != suffix:
                        errors.append(
                            f"asset {asset_id or path} 格式声明为 {declared}，"
                            f"但文件是 {suffix}"
                        )

        render = scenario.presentation.render
        render_assets: List[tuple[str, str, str]] = []
        for render_id, item in (render.characters or {}).items():
            render_assets.append((f"characters.{render_id}", item.asset, item.format))
        for render_id, item in (render.locations or {}).items():
            render_assets.append((f"locations.{render_id}", item.scene_asset, item.format))
        for render_id, item in (render.objects or {}).items():
            render_assets.append((f"objects.{render_id}", item.asset, item.format))
            if item.icon:
                render_assets.append((f"objects.{render_id}.icon", item.icon, ""))
        for index, item in enumerate(
            scenario.presentation.environment.props or []
        ):
            if item.asset:
                render_assets.append((f"environment.props[{index}]", item.asset, ""))
        for owner, relative, declared_format in render_assets:
            if not relative or str(relative).startswith(("http://", "https://", "data:")):
                continue
            path = scenario.scenario_dir / relative
            if not path.is_file():
                errors.append(f"render asset {owner} 不存在: {relative}")
                continue
            suffix = path.suffix.lower().lstrip(".")
            declared = str(declared_format or "").lower().lstrip(".")
            if declared and suffix and declared != suffix:
                errors.append(
                    f"render asset {owner} 格式声明为 {declared}，"
                    f"但文件是 {suffix}: {relative}"
                )
        if errors:
            raise ScenarioLoadError(
                "资产清单编译失败:\n- " + "\n- ".join(errors)
            )

    @staticmethod
    def _validate_sample_run(
        scenario: Any,
        *,
        role_index: Dict[str, Any],
        action_index: Dict[str, Dict[str, Any]],
        object_index: Dict[str, Dict[str, Any]],
        location_index: Dict[str, Dict[str, Any]],
    ) -> None:
        spec = scenario.sample_run_spec.get("sample_run", {})
        if not spec:
            return
        errors: List[str] = []
        for agent in spec.get("agents", []) or []:
            role_id = agent.get("role_id")
            if role_id and role_id not in role_index:
                errors.append(f"sample_run 引用不存在 role: {role_id}")
        targets = set(object_index) | set(location_index)
        for path in spec.get("scripted_mock_paths", []) or []:
            for step in path.get("steps", []) or []:
                action_id = step.get("action_id")
                target_id = step.get("target_id")
                if action_id and action_id not in action_index:
                    errors.append(
                        f"sample_run 引用不存在 action: {action_id}"
                    )
                if target_id and target_id not in targets:
                    errors.append(
                        f"sample_run 引用不存在 target: {target_id}"
                    )
        if errors:
            raise ScenarioLoadError(
                "sample_run 编译失败:\n- " + "\n- ".join(errors)
            )

    @staticmethod
    def _validate_replay_contract(scenario: Any) -> None:
        contract = scenario.replay_expectation.get("replay_expectation", {})
        if not contract:
            return
        supported_artifacts = {
            "initial_world_state", "perception_packets", "harness_traces",
            "world_actions", "tool_run_results", "external_observations",
            "world_events", "settlements", "director_plans",
            "render_commands", "final_settlement_records",
        }
        supported_invariants = {
            "world_event_must_reference_world_action_or_system_origin",
            "external_observation_must_have_provenance",
            "settlement_must_reference_world_event",
            "director_plan_must_reference_trusted_facts",
            "winner_only_from_scene_settlement",
        }
        unknown_artifacts = sorted(
            set(contract.get("expected_reconstructable_artifacts", []))
            - supported_artifacts
        )
        unknown_invariants = sorted(
            set(contract.get("invariants", [])) - supported_invariants
        )
        errors = []
        if unknown_artifacts:
            errors.append(f"Replay 不支持产物: {unknown_artifacts}")
        if unknown_invariants:
            errors.append(f"Replay 不支持约束: {unknown_invariants}")
        if errors:
            raise ScenarioLoadError(
                "replay_expectation 编译失败:\n- " + "\n- ".join(errors)
            )

    @classmethod
    def _build_consumption_report(cls, scenario: Any) -> ConsumptionReport:
        declared = cls._declared_sections(scenario)
        required: Set[str] = set()
        unknown_features = []
        for feature, enabled in scenario.manifest.enabled_features.items():
            if enabled:
                if feature not in FEATURE_CONSUMERS:
                    unknown_features.append(feature)
                required.update(FEATURE_REQUIREMENTS.get(feature, set()))
        required.update(scenario.manifest.required_sections)

        missing_consumers = [
            section
            for section in sorted(required)
            if section not in declared or not SECTION_CONSUMERS.get(section)
        ]
        missing_consumers.extend(
            f"enabled_feature:{feature}" for feature in sorted(unknown_features)
        )
        unconsumed = [
            section
            for section in sorted(declared)
            if not SECTION_CONSUMERS.get(section)
        ]
        return ConsumptionReport(
            consumers={
                section: list(SECTION_CONSUMERS.get(section, []))
                for section in sorted(declared)
            },
            required_sections=sorted(required),
            missing_consumers=missing_consumers,
            unconsumed_declared_sections=unconsumed,
        )

    @staticmethod
    def _declared_sections(scenario: Any) -> Set[str]:
        sections: Set[str] = set()
        presence = {
            "roles": bool(scenario.agent_roles),
            "characters": bool(scenario.characters_cfg),
            "objects": bool(scenario.objects_cfg),
            "actions": bool(scenario.actions_cfg),
            "metrics": bool(scenario.metrics_cfg),
            "tools": bool(scenario.tools_cfg),
            "audit": bool(scenario.audit_cfg),
            "settlement": bool(scenario.settlement_cfg),
            "locations": bool(scenario.locations_cfg),
            "resources": bool(scenario.resources_cfg),
            "permissions": bool(
                scenario.permissions_cfg or scenario.permission_definitions
            ),
            "visibility": bool(scenario.visibility_rules),
            "causal_physics": bool(scenario.causal_physics_config),
            "measurement_opportunities": bool(
                scenario.measurement_opportunities
            ),
            "prompt_contract": bool(scenario.prompt_contract),
            "playback_policy": bool(scenario.playback_policy),
            "director": bool(scenario.director_cfg),
            "thought_display": bool(
                scenario.presentation.render.ui.thought_display_policy
            ),
            "render": bool(
                scenario.presentation.render.locations
                or scenario.presentation.render.actions
                or scenario.presentation.render.objects
            ),
            "scene": bool(scenario.scene_config or scenario.background_text),
            "assets": bool(scenario.assets_manifest),
            "validation_spec": bool(scenario.validation_spec),
            "sample_run_spec": bool(scenario.sample_run_spec),
            "replay_expectation": bool(scenario.replay_expectation),
        }
        sections.update(key for key, value in presence.items() if value)
        return sections
