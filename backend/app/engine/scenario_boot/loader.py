"""
L0 Scenario Boot Kernel — 场景包加载器

职责：将静态场景包目录加载、校验、装配为可运行的 ScenarioRuntime。
引擎层不知道任何场景内容（角色名、指标名、剧情术语），一切都从这里进入。

场景包标准目录结构：
    scenarios/<name>/
    ├── manifest.json           # 元信息
    ├── world/
    │   ├── intro.txt           # 开场旁白
    │   ├── goal.txt            # Agent 终局目标（自然语言）
    │   ├── rules.yaml          # 世界规则配置
    │   ├── rules_for_agent.txt # 给模型的规则摘要
    │   ├── objects.yaml        # 世界对象定义
    │   ├── actions.yaml        # 场景动作定义
    │   ├── metrics.yaml        # 指标定义 + 派生规则
    │   ├── tools.yaml          # 工具定义
    │   ├── variables.yaml      # 观察者可触发变量
    │   └── audit.yaml          # 终局审计配置
    ├── agents/
    │   ├── roles.yaml          # 角色定义
    │   └── judge_prompt.txt    # 裁判/导演口径
    ├── director.yaml           # 导演词汇表
    ├── presentation.yaml       # 渲染配置
    └── assets/                 # 3D/2.5D 资源
"""
from __future__ import annotations

import json
import logging
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, ConfigDict, Field

from app.core.exceptions import ScenarioLoadError

logger = logging.getLogger(__name__)

SUPPORTED_SCENARIO_API_VERSIONS = {"1.0"}
OS_CAPABILITIES = {
    "transactional_action_commit",
    "causal_physics",
    "visibility_rules",
    "resource_lifecycle",
    "cooldown_lifecycle",
    "settlement_runtime",
    "world_adapter",
    "director_plan",
    "render_commands",
    "trace_export",
    "deterministic_replay",
    "presentation_buffer",
    "prompt_contract",
}


# ---------------------------------------------------------------------------
# 场景包配置模型（从 YAML/JSON 加载的结构化定义）
# ---------------------------------------------------------------------------

class AgentRoleConfig(BaseModel):
    """角色定义（场景包 agents/roles.yaml）"""
    agent_slot_id: str
    display_name: str
    color: str = "#ffffff"             # 渲染颜色（场景包定义，framework.yaml 为 fallback）
    role_title: str = ""
    public_persona: str = ""
    hidden_goal: str = ""
    capability_profile: Dict[str, Any] = Field(default_factory=dict)
    system_prompt_extra: str = ""
    sprite_image: Optional[str] = None
    model_glb: Optional[str] = None
    # P0 底座协议扩展
    start_location: Optional[str] = None
    permissions: List[str] = Field(default_factory=list)


class WorldVariable(BaseModel):
    """观察者可触发的世界变量"""
    id: str
    label: str
    icon: str = ""
    text: str
    # 结构化效果（可选）：[{type: metric_delta, metric: ..., value: ..., target: actor|all}]
    effects: List[Dict[str, Any]] = Field(default_factory=list)


class ScenePropConfig(BaseModel):
    """场景装饰物 — 通用 primitive + GLB asset 驱动，OS层不写死任何类型名"""
    name: str = ""
    type: str = ""           # 向后兼容，新配置用 name
    asset: str = ""          # GLB 模型路径（优先加载）
    position: List[float] = [0.0, 0.0, 0.0]
    rotation: float = 0.0
    scale: float = 1.0
    params: Dict[str, Any] = Field(default_factory=dict)
    primitives: List[Dict[str, Any]] = Field(default_factory=list)  # 通用图元列表
    repeat: Optional[Dict[str, Any]] = None  # 沿圆环重复排列
    light: Optional[Dict[str, Any]] = None   # 附带光源


class LightingConfig(BaseModel):
    """灯光配置 — 由场景包配置驱动"""
    type: str  # directional / hemisphere / ambient / point
    color: str = "#ffffff"
    intensity: float = 1.0
    position: List[float] = Field(default_factory=lambda: [0, 0, 0])
    cast_shadow: bool = False
    shadow_map_size: int = 2048
    shadow_camera: List[float] = Field(default_factory=lambda: [-25, 25, 25, -25])
    sky_color: str = "#ffffff"
    ground_color: str = "#000000"
    distance: float = 0.0
    decay: float = 2.0


class GroundConfig(BaseModel):
    """地面配置 — 由场景包配置驱动"""
    shape: str = "circle"
    radius: float = 50.0
    color: str = "#07111f"
    roughness: float = 1.0
    detail: Optional[Dict[str, Any]] = None


class CameraConfig(BaseModel):
    """2.5D 固定相机"""
    position: List[float] = [0.0, 22.0, 16.0]
    look_at: List[float] = [0.0, 0.0, 0.0]
    fov: float = 45.0


class StageConfig(BaseModel):
    """2.5D 舞台"""
    background_image: str = ""
    background_color: str = "#030711"
    width: float = 22.0
    depth: float = 14.0
    props: List[ScenePropConfig] = []


class EnvironmentConfig(BaseModel):
    """3D 环境 — 全部由场景包配置驱动"""
    sky_gradient: List[str] = []
    fog_color: str = "#071522"
    fog_density: float = 0.008
    environment_glb: Optional[str] = None
    lighting: List[Dict[str, Any]] = Field(default_factory=list)
    ground: Optional[Dict[str, Any]] = None
    # 大气层（星空/月亮/烛烬），由前端 buildAtmosphere 渲染
    atmosphere: Dict[str, Any] = Field(default_factory=dict)
    props: List[ScenePropConfig] = []
    # 向后兼容
    ground_color: str = "#07111f"
    ground_detail_color: str = "#102638"


class RenderLocationConfig(BaseModel):
    """render/locations.yaml 中单个地点的渲染配置"""
    scene_asset: str = ""
    format: str = "glb"
    world_position: Dict[str, float] = Field(default_factory=dict)
    size: Dict[str, float] = Field(default_factory=dict)
    spawn_points: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    anchors: Dict[str, Dict[str, float]] = Field(default_factory=dict)
    camera: Dict[str, str] = Field(default_factory=dict)
    lighting: Dict[str, Any] = Field(default_factory=dict)
    background_audio: Dict[str, Any] = Field(default_factory=dict)


class RenderCharacterConfig(BaseModel):
    """render/characters.yaml 中单个角色的渲染配置"""
    asset: str = ""
    format: str = "glb"
    scale: float = 1.0
    default_animation: str = "idle"
    animations: Dict[str, str] = Field(default_factory=dict)
    labels: Dict[str, str] = Field(default_factory=dict)
    fallback: Dict[str, str] = Field(default_factory=dict)


class RenderActionConfig(BaseModel):
    """render/actions.yaml 中单个动作的渲染配置"""
    animation: str = "idle"
    camera: str = ""
    effect: str = "none"
    sound: str = ""
    music: str = ""
    ui_panel: str = ""
    duration_ms: int = 2000
    fallback: Dict[str, str] = Field(default_factory=dict)


class RenderObjectConfig(BaseModel):
    """render/objects.yaml 中单个物体的渲染配置"""
    display_mode: str = "ui_card"
    asset: str = ""
    format: str = "glb"
    icon: str = ""
    position: Dict[str, Any] = Field(default_factory=dict)
    effects: Dict[str, str] = Field(default_factory=dict)
    ui: Dict[str, Any] = Field(default_factory=dict)
    fallback: Dict[str, str] = Field(default_factory=dict)


class RenderUIConfig(BaseModel):
    """render/ui.yaml 配置"""
    metrics: Dict[str, Any] = Field(default_factory=dict)
    resources: Dict[str, Any] = Field(default_factory=dict)
    panels: Dict[str, Any] = Field(default_factory=dict)
    status_labels: Dict[str, str] = Field(default_factory=dict)
    milestone_banner: Dict[str, str] = Field(default_factory=dict)
    thought_display_policy: Dict[str, Any] = Field(default_factory=dict)


class RenderCameraConfig(BaseModel):
    """render/cameras.yaml 中单个相机配置"""
    type: str = "orbit"
    position: Dict[str, float] = Field(default_factory=dict)
    look_at: Dict[str, float] = Field(default_factory=dict)
    distance: float = 5.0
    height: float = 3.0
    smoothing: float = 0.8


class RenderEffectConfig(BaseModel):
    """render/effects.yaml 中单个特效配置"""
    type: str = ""
    color: str = ""
    duration_ms: int = 1000


class RenderConfig(BaseModel):
    """完整的 render/ 目录渲染配置"""
    bindings: Dict[str, Any] = Field(default_factory=dict)
    locations: Dict[str, RenderLocationConfig] = Field(default_factory=dict)
    characters: Dict[str, RenderCharacterConfig] = Field(default_factory=dict)
    actions: Dict[str, RenderActionConfig] = Field(default_factory=dict)
    objects: Dict[str, RenderObjectConfig] = Field(default_factory=dict)
    ui: RenderUIConfig = Field(default_factory=RenderUIConfig)
    cameras: Dict[str, RenderCameraConfig] = Field(default_factory=dict)
    effects: Dict[str, RenderEffectConfig] = Field(default_factory=dict)
    audio: Dict[str, Any] = Field(default_factory=dict)
    # world/locations.yaml 的网格地图（逻辑层地点定义）
    world_locations: List[Dict[str, Any]] = Field(default_factory=list)


class PresentationConfig(BaseModel):
    """渲染层配置（前端据此渲染，引擎不关心内容）"""
    # 演绎形态：scene_3d(3D角色场景,默认) | dashboard(数据仪表盘)。
    # 由场景包声明，OS 前端据此选择渲染形态。引擎不解释其含义。
    render_mode: str = "scene_3d"
    camera: CameraConfig = Field(default_factory=CameraConfig)
    stage: StageConfig = Field(default_factory=StageConfig)
    spawns: List[List[float]] = []
    ui_text: Dict[str, str] = Field(default_factory=dict)
    environment: EnvironmentConfig = Field(default_factory=EnvironmentConfig)
    default_character_glb: str = ""
    # 新增：完整的 render/ 目录配置
    render: RenderConfig = Field(default_factory=RenderConfig)
    # agent fallback 模型配置（GLB为空时程序化构建）
    agent_fallback: Dict[str, Any] = Field(default_factory=dict)
    # 地点标记颜色配置
    location_marker: Dict[str, Any] = Field(default_factory=dict)
    # UI 主题色配置
    ui_theme: Dict[str, Any] = Field(default_factory=dict)


class AnimSpec(BaseModel):
    """事件 → 角色动作编排"""
    actor_clip: str = "Idle"
    duration: float = 1.0
    effect: Optional[str] = None
    camera: Optional[str] = None
    choreography: str = "none"


class DirectorVocabulary(BaseModel):
    """导演词汇表：事件→分镜风格、术语、镜头映射"""
    style_name: str = "default"
    event_mappings: Dict[str, str] = Field(default_factory=dict)
    anim_mappings: Dict[str, AnimSpec] = Field(default_factory=dict)
    overall_tone: str = ""
    style: Dict[str, Any] = Field(default_factory=dict)
    terminology: Dict[str, str] = Field(default_factory=dict)
    shot_mapping: Dict[str, Any] = Field(default_factory=dict)
    narration_templates: Dict[str, List[str]] = Field(default_factory=dict)
    truth_policy: Dict[str, Any] = Field(default_factory=dict)
    forbid_phrases: List[str] = Field(default_factory=list)
    neutral_subtitle: str = ""
    suspense_subtitles: List[str] = Field(default_factory=list)
    narrative_props: List[str] = Field(default_factory=list)


class ScenarioManifest(BaseModel):
    """manifest.json"""
    scenario_id: str = ""
    name: str
    version: str = "0.1.0"
    description: str = ""
    author: str = ""
    min_agents: int = 2
    max_agents: int = 8
    sandbox_api_extensions: List[str] = []
    scenario_api_version: str = "1.0"
    required_os_capabilities: List[str] = Field(default_factory=list)
    optional_os_capabilities: List[str] = Field(default_factory=list)
    enabled_features: Dict[str, bool] = Field(default_factory=dict)
    entry_files: Dict[str, str] = Field(default_factory=dict)
    required_sections: List[str] = Field(default_factory=list)


# ---------------------------------------------------------------------------
# L0 核心输出：LoadedScenario（加载完成但未装配的静态数据）
# ---------------------------------------------------------------------------

class LoadedScenario(BaseModel):
    """
    L0 输出：加载完成的场景包。
    包含场景的全部静态定义，但不包含运行时状态。
    由 ScenarioBootKernel.assemble() 转化为 ScenarioRuntime。
    """
    manifest: ScenarioManifest
    # 世界定义
    world_config: Dict[str, Any] = Field(default_factory=dict)
    objects_cfg: List[Dict[str, Any]] = Field(default_factory=list)
    actions_cfg: List[Dict[str, Any]] = Field(default_factory=list)
    metrics_cfg: Dict[str, Any] = Field(default_factory=dict)
    tools_cfg: List[Dict[str, Any]] = Field(default_factory=list)
    audit_cfg: Dict[str, Any] = Field(default_factory=dict)
    # Agent
    agent_roles: List[AgentRoleConfig] = Field(default_factory=list)
    judge_prompt: str = ""
    prompt_contract: Dict[str, Any] = Field(default_factory=dict)
    characters_cfg: List[Dict[str, Any]] = Field(default_factory=list)
    # 文本资源
    intro: str = ""
    goal_text: str = ""
    rule_text: str = ""
    background_text: str = ""
    # OS2 导演场景输入
    vocabulary: DirectorVocabulary = Field(default_factory=DirectorVocabulary)
    director_cfg: Dict[str, Any] = Field(default_factory=dict)
    # 渲染
    presentation: PresentationConfig = Field(default_factory=PresentationConfig)
    world_variables: List[WorldVariable] = Field(default_factory=list)
    # 可执行世界适配器。它只负责环境状态转移，不拥有结算权威。
    world_adapter_cfg: Dict[str, Any] = Field(default_factory=dict)
    # 场景结算权限、Provider 与胜负口径
    settlement_cfg: Dict[str, Any] = Field(default_factory=dict)
    # 场景
    scene_config: Dict[str, Any] = Field(default_factory=dict)
    scene_theme: Dict[str, Any] = Field(default_factory=dict)
    # 播放策略
    playback_policy: Dict[str, Any] = Field(default_factory=dict)
    # 世界规则扩展
    visibility_rules: List[Dict[str, Any]] = Field(default_factory=list)
    causal_physics_config: Dict[str, Any] = Field(default_factory=dict)
    measurement_opportunities: Dict[str, Any] = Field(default_factory=dict)
    challenge_paths: List[Path] = Field(default_factory=list)
    # P0 底座协议扩展配置
    locations_cfg: List[Dict[str, Any]] = Field(default_factory=list)
    resources_cfg: List[Dict[str, Any]] = Field(default_factory=list)
    permissions_cfg: Dict[str, Any] = Field(default_factory=dict)
    permission_definitions: List[Dict[str, Any]] = Field(default_factory=list)
    assets_manifest: Dict[str, Any] = Field(default_factory=dict)
    validation_spec: Dict[str, Any] = Field(default_factory=dict)
    sample_run_spec: Dict[str, Any] = Field(default_factory=dict)
    replay_expectation: Dict[str, Any] = Field(default_factory=dict)
    # 路径
    assets_dir: Path = Path(".")
    scenario_dir: Path = Path(".")
    locale: str = "zh-CN"

    model_config = ConfigDict(arbitrary_types_allowed=True)


# ---------------------------------------------------------------------------
# L0 加载入口
# ---------------------------------------------------------------------------

class ScenarioBootKernel:
    """
    L0 Scenario Boot Kernel

    职责：
    1. load()     — 从目录加载场景包为 LoadedScenario
    2. validate() — 校验完整性（ID引用、依赖）
    3. assemble() — 装配为 ScenarioRuntime（L1-L6 服务容器）
    """

    @staticmethod
    def load(scenario_path: str, *, locale: str = "zh-CN") -> LoadedScenario:
        """加载场景包目录，返回 LoadedScenario"""
        root = Path(scenario_path).resolve()
        if not root.exists():
            raise ScenarioLoadError(f"场景包目录不存在: {root}")

        # manifest.json
        manifest_path = root / "manifest.json"
        if not manifest_path.exists():
            raise ScenarioLoadError(f"缺少 manifest.json: {manifest_path}")
        try:
            manifest = ScenarioManifest(**json.loads(manifest_path.read_text(encoding="utf-8")))
        except Exception as e:
            raise ScenarioLoadError(f"manifest.json 解析失败: {e}") from e

        # world/rules.yaml
        world_config: Dict[str, Any] = {}
        rules_path = root / "world" / "rules.yaml"
        if rules_path.exists():
            world_config = yaml.safe_load(rules_path.read_text(encoding="utf-8")) or {}

        # world/pressure.yaml（压力模型配置）
        pressure_path = root / "world" / "pressure.yaml"
        if pressure_path.exists():
            pressure_data = yaml.safe_load(pressure_path.read_text(encoding="utf-8")) or {}
            world_config["pressure_cfg"] = pressure_data.get("pressure", pressure_data)

        # 规则世界配置文件
        objects_cfg: List[Dict[str, Any]] = []
        actions_cfg: List[Dict[str, Any]] = []
        metrics_cfg: Dict[str, Any] = {}
        for fname, attr in [("objects.yaml", "objects_cfg"), ("actions.yaml", "actions_cfg")]:
            fpath = root / "world" / fname
            if fpath.exists():
                data = yaml.safe_load(fpath.read_text(encoding="utf-8"))
                # 兼容两种格式：顶层 list 或 {key: [...]} dict
                if isinstance(data, dict):
                    # 尝试从 dict 中提取 list（key 为复数形式）
                    for v in data.values():
                        if isinstance(v, list):
                            data = v
                            break
                if isinstance(data, list):
                    if attr == "objects_cfg":
                        objects_cfg = data
                    elif attr == "actions_cfg":
                        actions_cfg = data
                # 也放入 world_config 兼容旧代码
                world_config[attr.replace("_cfg", "")] = data

        metrics_path = root / "world" / "metrics.yaml"
        if metrics_path.exists():
            metrics_cfg = yaml.safe_load(metrics_path.read_text(encoding="utf-8")) or {}
            world_config["metrics_cfg"] = metrics_cfg

        # tools.yaml
        tools_cfg: List[Dict[str, Any]] = []
        tools_path = root / "world" / "tools.yaml"
        if tools_path.exists():
            raw = yaml.safe_load(tools_path.read_text(encoding="utf-8")) or {}
            tools_cfg = raw.get("tools", []) if isinstance(raw, dict) else []

        # audit.yaml
        audit_cfg: Dict[str, Any] = {}
        audit_path = root / "world" / "audit.yaml"
        if audit_path.exists():
            raw_audit = yaml.safe_load(audit_path.read_text(encoding="utf-8")) or {}
            audit_cfg = dict(raw_audit.get("audit", raw_audit) or {})

        # agents/roles.yaml
        agent_roles: List[AgentRoleConfig] = []
        roles_path = root / "agents" / "roles.yaml"
        if roles_path.exists():
            raw_roles = yaml.safe_load(roles_path.read_text(encoding="utf-8")) or []
            agent_roles = [AgentRoleConfig(**r) for r in raw_roles]

        characters_cfg: List[Dict[str, Any]] = []
        characters_path = root / "agents" / "characters.yaml"
        if characters_path.exists():
            raw = yaml.safe_load(characters_path.read_text(encoding="utf-8")) or {}
            characters_cfg = raw.get("characters", raw) if isinstance(raw, dict) else raw
            if not isinstance(characters_cfg, list):
                raise ScenarioLoadError("agents/characters.yaml 必须包含 characters 列表")

        # 文本资源
        def _read_text(rel: str) -> str:
            p = root / rel
            return p.read_text(encoding="utf-8").strip() if p.exists() else ""

        judge_prompt = _read_text("agents/judge_prompt.txt")
        intro = _read_text("world/intro.txt")
        goal_text = _read_text("world/goal.txt")
        rule_text = _read_text("world/rules_for_agent.txt")

        # 导演配置
        director_cfg: Dict[str, Any] = {}
        vocabulary = DirectorVocabulary()
        # 优先 root/director.yaml，其次 director/director.yaml
        director_yaml = root / "director.yaml"
        if not director_yaml.exists():
            director_yaml = root / "director" / "director.yaml"
        if director_yaml.exists():
            raw = yaml.safe_load(director_yaml.read_text(encoding="utf-8")) or {}
            director_cfg = raw.get("director", raw)
            _style = director_cfg.get("style", {})
            vocabulary = DirectorVocabulary(
                style_name=_style.get("tone", "default"),
                overall_tone=_style.get("tone", ""),
                terminology=director_cfg.get("terminology", {}),
                style=_style,
                shot_mapping=director_cfg.get("shot_mapping", {}),
                narration_templates=director_cfg.get("narration_templates", {}),
                truth_policy=director_cfg.get("truth_policy", {}),
                forbid_phrases=director_cfg.get("forbid_phrases", []),
                neutral_subtitle=str(director_cfg.get("neutral_subtitle", "") or ""),
                suspense_subtitles=list(director_cfg.get("suspense_subtitles", []) or []),
                narrative_props=list(director_cfg.get("narrative_props", []) or []),
            )
        vocab_path = root / "director" / "vocabulary.yaml"
        if vocab_path.exists():
            vocab_data = yaml.safe_load(vocab_path.read_text(encoding="utf-8")) or {}
            anim_raw = vocab_data.pop("anim_mappings", {})
            anim_mappings = dict(vocabulary.anim_mappings or {})
            for etype, spec in (anim_raw or {}).items():
                try:
                    anim_mappings[etype] = AnimSpec(**spec)
                except Exception:
                    pass
            merged_vocab = vocabulary.model_dump()
            for key, value in vocab_data.items():
                if key == "anim_mappings":
                    continue
                if isinstance(value, dict) and isinstance(merged_vocab.get(key), dict):
                    merged = dict(merged_vocab.get(key) or {})
                    merged.update(value)
                    merged_vocab[key] = merged
                elif isinstance(value, list) and isinstance(merged_vocab.get(key), list):
                    merged_vocab[key] = [*merged_vocab.get(key, []), *value]
                elif value not in (None, "", {}, []):
                    merged_vocab[key] = value
            merged_vocab["anim_mappings"] = anim_mappings
            vocabulary = DirectorVocabulary(**merged_vocab)

        # world/variables.yaml
        world_variables: List[WorldVariable] = []
        vars_path = root / "world" / "variables.yaml"
        if vars_path.exists():
            raw_vars = yaml.safe_load(vars_path.read_text(encoding="utf-8")) or []
            world_variables = [WorldVariable(**v) for v in raw_vars]

        world_adapter_cfg: Dict[str, Any] = {}
        adapter_path = root / "world" / "adapter.yaml"
        if adapter_path.exists():
            world_adapter_cfg = yaml.safe_load(
                adapter_path.read_text(encoding="utf-8")
            ) or {}
            if not isinstance(world_adapter_cfg, dict):
                raise ScenarioLoadError("world/adapter.yaml 必须是对象")

        settlement_cfg: Dict[str, Any] = {}
        settlement_path = root / "settlement" / "manifest.yaml"
        if settlement_path.exists():
            settlement_cfg = yaml.safe_load(
                settlement_path.read_text(encoding="utf-8")
            ) or {}

        # presentation.yaml
        presentation = PresentationConfig()
        pres_path = root / "presentation.yaml"
        if pres_path.exists():
            pres_data = yaml.safe_load(pres_path.read_text(encoding="utf-8")) or {}
            presentation = PresentationConfig(**pres_data)

        # render/ 目录：加载完整渲染配置
        render_cfg = RenderConfig()

        # render/bindings.yaml
        bindings_path = root / "render" / "bindings.yaml"
        if bindings_path.exists():
            raw = yaml.safe_load(bindings_path.read_text(encoding="utf-8")) or {}
            render_cfg.bindings = raw.get("bindings", raw)

        # render/locations.yaml
        render_locs_path = root / "render" / "locations.yaml"
        if render_locs_path.exists():
            raw = yaml.safe_load(render_locs_path.read_text(encoding="utf-8")) or {}
            locs_data = raw.get("locations", raw)
            render_cfg.locations = {
                k: RenderLocationConfig(**v) for k, v in locs_data.items()
            }

        # render/characters.yaml
        chars_path = root / "render" / "characters.yaml"
        if chars_path.exists():
            raw = yaml.safe_load(chars_path.read_text(encoding="utf-8")) or {}
            chars_data = raw.get("characters", raw)
            render_cfg.characters = {
                k: RenderCharacterConfig(**v) for k, v in chars_data.items()
            }

        # render/actions.yaml
        ractions_path = root / "render" / "actions.yaml"
        if ractions_path.exists():
            raw = yaml.safe_load(ractions_path.read_text(encoding="utf-8")) or {}
            acts_data = raw.get("actions", raw)
            render_cfg.actions = {
                k: RenderActionConfig(**v) for k, v in acts_data.items()
            }

        # render/objects.yaml
        robjects_path = root / "render" / "objects.yaml"
        if robjects_path.exists():
            raw = yaml.safe_load(robjects_path.read_text(encoding="utf-8")) or {}
            objs_data = raw.get("objects", raw)
            render_cfg.objects = {
                k: RenderObjectConfig(**v) for k, v in objs_data.items()
            }

        # render/ui.yaml
        rui_path = root / "render" / "ui.yaml"
        if rui_path.exists():
            raw = yaml.safe_load(rui_path.read_text(encoding="utf-8")) or {}
            render_cfg.ui = RenderUIConfig(**raw)

        # render/cameras.yaml
        rcams_path = root / "render" / "cameras.yaml"
        if rcams_path.exists():
            raw = yaml.safe_load(rcams_path.read_text(encoding="utf-8")) or {}
            cams_data = raw.get("cameras", raw)
            render_cfg.cameras = {
                k: RenderCameraConfig(**v) for k, v in cams_data.items()
                if isinstance(v, dict)
            }

        # render/effects.yaml
        reffects_path = root / "render" / "effects.yaml"
        if reffects_path.exists():
            raw = yaml.safe_load(reffects_path.read_text(encoding="utf-8")) or {}
            eff_data = raw.get("effects", raw)
            render_cfg.effects = {
                k: RenderEffectConfig(**v) for k, v in eff_data.items()
                if isinstance(v, dict)
            }

        audio_path = root / "render" / "audio.yaml"
        if audio_path.exists():
            raw = yaml.safe_load(audio_path.read_text(encoding="utf-8")) or {}
            render_cfg.audio = raw if isinstance(raw, dict) else {}

        # world/locations.yaml：逻辑层地点定义（网格地图）
        world_locs_path = root / "world" / "locations.yaml"
        if world_locs_path.exists():
            raw_locs = yaml.safe_load(world_locs_path.read_text(encoding="utf-8")) or {}
            # world/locations.yaml 格式: {locations: [...]}
            if isinstance(raw_locs, dict):
                render_cfg.world_locations = raw_locs.get("locations", [])
            elif isinstance(raw_locs, list):
                render_cfg.world_locations = raw_locs

        presentation.render = render_cfg

        # 从 render/locations.yaml 的 spawn_points 生成 spawns（如果 presentation.spawns 为空）
        if not presentation.spawns and render_cfg.locations:
            # 起点完全由角色/场景声明决定，OS 不认识任何具体地点或角色 ID。
            default_loc_id = next(
                (
                    getattr(role, "start_location", None)
                    for role in agent_roles
                    if getattr(role, "start_location", None)
                ),
                None,
            )
            if not default_loc_id:
                default_loc_id = next(iter(render_cfg.locations.keys()), "")
            loc_render = None
            for key, lr in render_cfg.locations.items():
                if default_loc_id in key or key.startswith(default_loc_id):
                    loc_render = lr
                    break
            if loc_render and loc_render.spawn_points:
                for role in agent_roles:
                    sp = loc_render.spawn_points.get(role.agent_slot_id)
                    if not sp:
                        sp = loc_render.spawn_points.get("default")
                    if sp:
                        presentation.spawns.append([sp.get("x", 0), sp.get("y", 0), sp.get("z", 0)])

        # 从 render/characters.yaml 提取 default_character_glb
        if not presentation.default_character_glb and render_cfg.characters:
            for key, ch in render_cfg.characters.items():
                if ch.asset:
                    presentation.default_character_glb = ch.asset
                    break

        # 从 render/locations.yaml 提取 environment 配置（如果 environment 为空）
        if not presentation.environment.props and render_cfg.locations:
            env_props = []
            for key, lr in render_cfg.locations.items():
                pos = lr.world_position
                if pos:
                    env_props.append(ScenePropConfig(
                        type="location_stage",
                        position=[pos.get("x", 0), pos.get("y", 0), pos.get("z", 0)],
                        scale=lr.size.get("width", 10) / 10.0,
                    ))
            presentation.environment.props = env_props

        logger.info(f"[L0] render/ 目录加载完成: {len(render_cfg.locations)} 地点, "
                    f"{len(render_cfg.characters)} 角色, {len(render_cfg.actions)} 动作, "
                    f"{len(render_cfg.objects)} 物体, {len(render_cfg.cameras)} 相机, "
                    f"{len(render_cfg.effects)} 特效, {len(render_cfg.world_locations)} 逻辑地点")

        # P0 底座协议：locations.yaml
        locations_cfg: List[Dict[str, Any]] = []
        locations_path = root / "world" / "locations.yaml"
        if locations_path.exists():
            raw_locs = yaml.safe_load(locations_path.read_text(encoding="utf-8")) or []
            # 兼容 {locations: [...]} dict 格式
            if isinstance(raw_locs, dict):
                for v in raw_locs.values():
                    if isinstance(v, list):
                        raw_locs = v
                        break
            if isinstance(raw_locs, list):
                # id → location_id 字段名映射
                for item in raw_locs:
                    if isinstance(item, dict) and "id" in item and "location_id" not in item:
                        item = {**item, "location_id": item["id"]}
                    if isinstance(item, dict):
                        locations_cfg.append(item)

        # P0 底座协议：resources.yaml
        resources_cfg: List[Dict[str, Any]] = []
        resources_path = root / "world" / "resources.yaml"
        if resources_path.exists():
            raw_res = yaml.safe_load(resources_path.read_text(encoding="utf-8")) or []
            # 兼容 {resources: [...]} dict 格式
            if isinstance(raw_res, dict):
                for v in raw_res.values():
                    if isinstance(v, list):
                        raw_res = v
                        break
            if isinstance(raw_res, list):
                resources_cfg = raw_res

        # P0 底座协议：permissions（从 roles.yaml 中提取）
        permissions_cfg: Dict[str, Any] = {}
        permission_definitions: List[Dict[str, Any]] = []
        permissions_path = root / "world" / "permissions.yaml"
        if permissions_path.exists():
            raw_permissions = yaml.safe_load(
                permissions_path.read_text(encoding="utf-8")
            ) or {}
            permission_definitions = (
                raw_permissions.get("permissions", [])
                if isinstance(raw_permissions, dict)
                else raw_permissions
            )
            if isinstance(raw_permissions, dict):
                fairness_declarations = raw_permissions.get(
                    "_fairness_declarations"
                )
                if isinstance(fairness_declarations, dict):
                    permissions_cfg["_fairness_declarations"] = dict(
                        fairness_declarations
                    )
            if not isinstance(permission_definitions, list):
                raise ScenarioLoadError(
                    "world/permissions.yaml 必须包含 permissions 列表"
                )
        for role in agent_roles:
            perms = getattr(role, "permissions", None)
            if perms:
                permissions_cfg[role.agent_slot_id] = perms if isinstance(perms, list) else []
            start_loc = getattr(role, "start_location", None)
            if start_loc:
                permissions_cfg.setdefault("_start_locations", {})[role.agent_slot_id] = start_loc

        # assets/
        assets_dir = root / "assets"
        assets_dir.mkdir(exist_ok=True)

        # ── 场景配置（scene/ 目录）──
        scene_config: Dict[str, Any] = {}
        _p = root / "scene" / "scene.yaml"
        if _p.exists():
            raw = yaml.safe_load(_p.read_text(encoding="utf-8")) or {}
            scene_config = raw.get("scene", raw)

        scene_theme: Dict[str, Any] = {}
        _p = root / "scene" / "theme.yaml"
        if _p.exists():
            raw = yaml.safe_load(_p.read_text(encoding="utf-8")) or {}
            scene_theme = raw.get("theme", raw)

        background_text = _read_text("scene/background.md")

        # ── 播放策略 ──
        playback_policy: Dict[str, Any] = {}
        _p = root / "playback" / "playback_policy.yaml"
        if _p.exists():
            raw = yaml.safe_load(_p.read_text(encoding="utf-8")) or {}
            playback_policy = raw.get("playback_policy", raw)

        # ── 世界规则扩展 ──
        visibility_rules: List[Dict[str, Any]] = []
        _p = root / "world" / "visibility.yaml"
        if _p.exists():
            raw = yaml.safe_load(_p.read_text(encoding="utf-8")) or {}
            if isinstance(raw, dict):
                visibility_rules = raw.get("visibility_rules", [])
            elif isinstance(raw, list):
                visibility_rules = raw

        causal_physics_config: Dict[str, Any] = {}
        _p = root / "world" / "causal_physics.yaml"
        if _p.exists():
            raw = yaml.safe_load(_p.read_text(encoding="utf-8")) or {}
            causal_physics_config = raw.get("causal_physics", raw)

        # ── Agent prompt 契约 ──
        prompt_contract: Dict[str, Any] = {}
        _p = root / "agents" / "prompts.yaml"
        if _p.exists():
            prompt_contract = yaml.safe_load(_p.read_text(encoding="utf-8")) or {}

        # ── 资产清单 ──
        _p = root / "assets" / "manifest.yaml"
        if _p.exists():
            assets_manifest = yaml.safe_load(_p.read_text(encoding="utf-8")) or {}
        else:
            assets_manifest = {}

        def _read_yaml_dict(rel: str) -> Dict[str, Any]:
            path = root / rel
            if not path.exists():
                return {}
            data = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
            return data if isinstance(data, dict) else {}

        validation_spec = _read_yaml_dict("tests/validation.yaml")
        sample_run_spec = _read_yaml_dict("tests/sample_run.yaml")
        replay_expectation = _read_yaml_dict("tests/replay_expectation.yaml")
        measurement_opportunities = _read_yaml_dict(
            "world/measurement_opportunities.yaml"
        )
        challenge_paths = sorted((root / "world" / "challenges").glob("*.yaml"))

        logger.info(f"[L0] 场景包加载完成: {manifest.name} v{manifest.version}")

        scenario = LoadedScenario(
            manifest=manifest,
            world_config=world_config,
            objects_cfg=objects_cfg,
            actions_cfg=actions_cfg,
            metrics_cfg=metrics_cfg,
            tools_cfg=tools_cfg,
            audit_cfg=audit_cfg,
            agent_roles=agent_roles,
            characters_cfg=characters_cfg,
            judge_prompt=judge_prompt,
            prompt_contract=prompt_contract,
            intro=intro,
            goal_text=goal_text,
            rule_text=rule_text,
            background_text=background_text,
            vocabulary=vocabulary,
            director_cfg=director_cfg,
            presentation=presentation,
            world_variables=world_variables,
            world_adapter_cfg=world_adapter_cfg,
            settlement_cfg=settlement_cfg,
            scene_config=scene_config,
            scene_theme=scene_theme,
            playback_policy=playback_policy,
            visibility_rules=visibility_rules,
            causal_physics_config=causal_physics_config,
            measurement_opportunities=measurement_opportunities,
            challenge_paths=challenge_paths,
            locations_cfg=locations_cfg,
            resources_cfg=resources_cfg,
            permissions_cfg=permissions_cfg,
            permission_definitions=permission_definitions,
            assets_manifest=assets_manifest,
            validation_spec=validation_spec,
            sample_run_spec=sample_run_spec,
            replay_expectation=replay_expectation,
            assets_dir=assets_dir,
            scenario_dir=root,
            locale=locale,
        )
        ScenarioBootKernel._apply_locale_overlay(scenario, locale)
        return scenario

    @staticmethod
    def _apply_locale_overlay(scenario: LoadedScenario, locale: str) -> None:
        """Apply optional presentation text without changing scenario semantics.

        A language pack lives at ``locales/<BCP47>.yaml``.  It may override
        user-facing labels and prose only; stable IDs, action intent, metric
        values, provider configuration and settlement rules stay canonical.
        """
        if locale == "zh-CN":
            return
        path = scenario.scenario_dir / "locales" / f"{locale}.yaml"
        if not path.is_file():
            logger.warning("[L0] scenario locale %s unavailable; using canonical text", locale)
            return
        raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
        if not isinstance(raw, dict):
            raise ScenarioLoadError(f"场景语言包必须是对象: {path}")

        manifest = raw.get("manifest") or {}
        if isinstance(manifest, dict):
            for field in ("name", "description"):
                if isinstance(manifest.get(field), str):
                    setattr(scenario.manifest, field, manifest[field])
        for field in ("intro", "goal_text", "background_text"):
            if isinstance(raw.get(field), str):
                setattr(scenario, field, raw[field])

        role_text = raw.get("roles") or {}
        if isinstance(role_text, dict):
            for role in scenario.agent_roles:
                values = role_text.get(role.agent_slot_id)
                if isinstance(values, dict):
                    for field in ("display_name", "role_title", "public_persona", "hidden_goal", "system_prompt_extra"):
                        if isinstance(values.get(field), str):
                            setattr(role, field, values[field])

        for items, key in ((scenario.actions_cfg, "actions"),):
            labels = raw.get(key) or {}
            if isinstance(labels, dict):
                for item in items:
                    values = labels.get(str(item.get("id") or ""))
                    if isinstance(values, dict):
                        for field in ("name", "description"):
                            if isinstance(values.get(field), str):
                                item[field] = values[field]
        metrics = raw.get("metrics") or {}
        if isinstance(metrics, dict):
            for item in scenario.metrics_cfg.get("metrics", []) if isinstance(scenario.metrics_cfg, dict) else []:
                value = metrics.get(str(item.get("id") or ""))
                if isinstance(value, str):
                    item["name"] = value

        ui_text = raw.get("ui_text") or {}
        if isinstance(ui_text, dict):
            scenario.presentation.ui_text.update({
                key: value for key, value in ui_text.items() if isinstance(value, str)
            })
        logger.info("[L0] applied scenario locale %s from %s", locale, path)

    # 通用 Agent 能力维度，仅用于校验场景声明。
    _STANDARD_DIMENSIONS = {
        "understanding", "memory", "reasoning", "planning", "judgment",
        "selection", "execution", "risk_control", "tool_use", "recovery",
    }
    _FORBIDDEN_ACTION_FIELDS = {"effects", "direct_metric", "score_delta"}
    _FORBIDDEN_TOOL_FIELDS = {"direct_state", "direct_metric"}

    @staticmethod
    def validate(scenario: LoadedScenario) -> List[str]:
        """校验场景包完整性，返回警告列表（不阻断加载）。

        校验项：
        - 基础存在性（角色/对象/动作）
        - ID 唯一性（action / object / metric / tool / agent）
        - 引用完整性（metrics→object_id / audit→metric）
        - 维度合法性（needs / suitable_needs 必须在 10 维标准内）
        - 禁止字段（action 不得有 effects/direct_metric/score_delta；tool 不得有 direct_state/direct_metric）
        """
        warnings: List[str] = []

        def _warn(msg: str) -> None:
            logger.error(f"[L0 validate] {msg}")
            warnings.append(msg)

        # ── 基础存在性 ──
        if scenario.manifest.scenario_api_version not in SUPPORTED_SCENARIO_API_VERSIONS:
            _warn(
                f"不支持的 scenario_api_version: "
                f"{scenario.manifest.scenario_api_version}"
            )
        missing_capabilities = sorted(
            set(scenario.manifest.required_os_capabilities) - OS_CAPABILITIES
        )
        if missing_capabilities:
            _warn(f"OS 缺少场景必需能力: {missing_capabilities}")
        if not scenario.agent_roles:
            _warn("场景包没有定义任何角色 (agents/roles.yaml)")
        if not scenario.objects_cfg:
            _warn("场景包没有定义世界对象 (world/objects.yaml)")
        if not scenario.actions_cfg:
            _warn("场景包没有定义动作 (world/actions.yaml)")
        if scenario.manifest.min_agents > len(scenario.agent_roles):
            _warn(f"角色数({len(scenario.agent_roles)})少于最小Agent数({scenario.manifest.min_agents})")

        # ── ID 唯一性 ──
        def _check_unique(items: list, id_key: str, label: str) -> None:
            seen: set = set()
            for item in items:
                if isinstance(item, dict):
                    _id = item.get(id_key, item.get("id"))
                else:
                    _id = getattr(item, id_key, getattr(item, "id", None))
                if _id and _id in seen:
                    _warn(f"{label} ID 重复: {_id}")
                if _id:
                    seen.add(_id)

        _check_unique(scenario.actions_cfg, "id", "action")
        _check_unique(scenario.objects_cfg, "object_id", "object")
        _check_unique(scenario.tools_cfg, "tool_id", "tool")
        _check_unique(scenario.agent_roles, "agent_slot_id", "agent")

        # metric ID 唯一性
        if isinstance(scenario.metrics_cfg, dict):
            _metrics_list = scenario.metrics_cfg.get("metrics", [])
            if isinstance(_metrics_list, list):
                _check_unique(_metrics_list, "metric_id", "metric")

        # ── 引用完整性：metrics.yaml 中 object_id 引用存在 ──
        object_ids = set()
        for obj in scenario.objects_cfg:
            if isinstance(obj, dict):
                oid = obj.get("object_id", obj.get("id"))
                if oid:
                    object_ids.add(oid)

        if isinstance(scenario.metrics_cfg, dict):
            _metrics_list = scenario.metrics_cfg.get("metrics", [])
            if isinstance(_metrics_list, list):
                for m in _metrics_list:
                    if isinstance(m, dict):
                        ref_obj = m.get("object_id")
                        if ref_obj and ref_obj not in object_ids:
                            _warn(f"metrics.yaml 引用不存在的 object_id: {ref_obj}")

        # ── 引用完整性：audit.yaml 中 metric 引用存在 ──
        metric_ids = set()
        if isinstance(scenario.metrics_cfg, dict):
            _metrics_list = scenario.metrics_cfg.get("metrics", [])
            if isinstance(_metrics_list, list):
                for m in _metrics_list:
                    if isinstance(m, dict):
                        mid = m.get("metric_id", m.get("id"))
                        if mid:
                            metric_ids.add(mid)

        if isinstance(scenario.audit_cfg, dict):
            audit_rules = scenario.audit_cfg.get("rules", [])
            if isinstance(audit_rules, list):
                for rule in audit_rules:
                    if isinstance(rule, dict):
                        ref_metric = rule.get("metric")
                        if ref_metric and metric_ids and ref_metric not in metric_ids:
                            _warn(f"audit.yaml 引用不存在的 metric: {ref_metric}")

            # ── 引用完整性：fallback_action_id 必须落在 actions.yaml ──
            action_ids = {
                str(a.get("id") or "")
                for a in scenario.actions_cfg
                if isinstance(a, dict) and a.get("id")
            }
            fallback_aid = str(
                scenario.audit_cfg.get("fallback_action_id") or ""
            ).strip()
            if fallback_aid and action_ids and fallback_aid not in action_ids:
                _warn(
                    f"audit.yaml fallback_action_id 引用不存在的动作: {fallback_aid}"
                )
            elif not fallback_aid and action_ids:
                has_wait_intent = any(
                    isinstance(a, dict) and str(a.get("intent") or "") == "wait"
                    for a in scenario.actions_cfg
                )
                if not has_wait_intent:
                    _warn(
                        "audit.yaml 未声明 fallback_action_id，"
                        "且 actions.yaml 中无 intent=wait 的待命动作"
                    )

        # ── 维度合法性：objects.yaml needs / actions.yaml suitable_needs ──
        dims = ScenarioBootKernel._STANDARD_DIMENSIONS
        for obj in scenario.objects_cfg:
            if isinstance(obj, dict):
                needs = obj.get("needs")
                if isinstance(needs, dict):
                    for k in needs:
                        if k not in dims:
                            _warn(f"objects.yaml 对象 {obj.get('object_id', obj.get('id', '?'))} 非法维度: {k}")
                elif isinstance(needs, list):
                    for k in needs:
                        if isinstance(k, str) and k not in dims:
                            _warn(f"objects.yaml 对象 {obj.get('object_id', obj.get('id', '?'))} 非法维度: {k}")

        for act in scenario.actions_cfg:
            if isinstance(act, dict):
                sn = act.get("suitable_needs")
                if isinstance(sn, dict):
                    for k in sn:
                        if k not in dims:
                            _warn(f"actions.yaml 动作 {act.get('id', '?')} 非法 suitable_needs 维度: {k}")
                elif isinstance(sn, list):
                    for k in sn:
                        if isinstance(k, str) and k not in dims:
                            _warn(f"actions.yaml 动作 {act.get('id', '?')} 非法 suitable_needs 维度: {k}")

                # requires_target=true 时必须有 target_types 或说明
                if act.get("requires_target") is True:
                    if not act.get("target_types") and not act.get("target_description"):
                        _warn(f"actions.yaml 动作 {act.get('id', '?')} requires_target=true 但缺少 target_types/target_description")

        # ── 禁止字段检查 ──
        forbidden_act = ScenarioBootKernel._FORBIDDEN_ACTION_FIELDS
        for act in scenario.actions_cfg:
            if isinstance(act, dict):
                for f in forbidden_act:
                    if f in act:
                        _warn(f"actions.yaml 动作 {act.get('id', '?')} 包含禁止字段: {f}")

        forbidden_tool = ScenarioBootKernel._FORBIDDEN_TOOL_FIELDS
        mcp_server_ids: set[str] = set()
        try:
            from app.mcp.registry import load_mcp_servers, resolve_mcp_servers_path

            mcp_cfg = load_mcp_servers(resolve_mcp_servers_path())
            mcp_server_ids = set(mcp_cfg.server_index().keys())
        except Exception:
            pass

        for tool in scenario.tools_cfg:
            if isinstance(tool, dict):
                for f in forbidden_tool:
                    if f in tool:
                        _warn(f"tools.yaml 工具 {tool.get('tool_id', tool.get('id', '?'))} 包含禁止字段: {f}")
                tid = str(tool.get("tool_id") or tool.get("id") or "?")
                tool_type = str(tool.get("type") or "sandbox").strip().lower()
                if tool_type == "mcp":
                    ms = str(tool.get("mcp_server") or "").strip()
                    mt = str(tool.get("mcp_tool") or "").strip()
                    if not ms or not mt:
                        _warn(
                            f"tools.yaml 工具 {tid} type=mcp 缺少 mcp_server 或 mcp_tool"
                        )
                    elif mcp_server_ids and ms not in mcp_server_ids:
                        _warn(
                            f"tools.yaml 工具 {tid} 引用的 mcp_server 未注册: {ms}"
                        )

        return warnings

    @staticmethod
    def assemble(scenario: LoadedScenario) -> "ScenarioRuntime":
        """装配为可运行的 ScenarioRuntime（L1-L6 服务容器）"""
        from app.engine.scenario_boot.compiler import ScenarioCompiler
        from app.engine.scenario_boot.registry import ScenarioRuntime
        issues = ScenarioBootKernel.validate(scenario)
        if issues:
            raise ScenarioLoadError(
                "场景包未通过装配前校验:\n- " + "\n- ".join(issues)
            )
        compiled = ScenarioCompiler.compile(scenario)
        return ScenarioRuntime.from_compiled(compiled)

    @staticmethod
    def validate_runtime_bindings(
        scenario: LoadedScenario,
        agent_slot_ids: List[str],
    ) -> List[str]:
        """校验框架 Agent 插槽与场景角色声明的装配关系。"""
        errors: List[str] = []
        if len(agent_slot_ids) != len(set(agent_slot_ids)):
            errors.append("framework agents 中存在重复 id")

        count = len(agent_slot_ids)
        if count < scenario.manifest.min_agents:
            errors.append(
                f"Agent 数量 {count} 小于场景最小值 "
                f"{scenario.manifest.min_agents}"
            )
        if count > scenario.manifest.max_agents:
            errors.append(
                f"Agent 数量 {count} 大于场景最大值 "
                f"{scenario.manifest.max_agents}"
            )

        role_ids = {role.agent_slot_id for role in scenario.agent_roles}
        slot_ids = set(agent_slot_ids)
        missing_slots = sorted(role_ids - slot_ids)
        unknown_slots = sorted(slot_ids - role_ids)
        if missing_slots:
            errors.append(f"场景角色缺少模型插槽: {missing_slots}")
        if unknown_slots:
            errors.append(f"模型插槽未绑定场景角色: {unknown_slots}")
        return errors


# 便捷函数
def load_scenario(scenario_path: str, *, locale: str = "zh-CN") -> LoadedScenario:
    """加载场景包（L0 入口）"""
    return ScenarioBootKernel.load(scenario_path, locale=locale)
