"""
框架配置系统

从 framework.yaml 加载，支持环境变量覆盖（AIWORLD_ 前缀）。
换场景 = 改 scenario_path；换模型 = 改 agents 列表。
"""
from __future__ import annotations

import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field, field_validator


class AgentSlotConfig(BaseModel):
    """单个 Agent 插槽配置"""
    id: str                          # 唯一标识，如 a1 / a2
    name: str                        # 角色显示名
    provider: str                    # openai / deepseek / anthropic / mock
    model: str                       # 模型版本
    color: str = "#ffffff"           # 渲染层颜色
    driver: str = "llm"              # llm（内置大模型） / agent（外部 Agent 驱动）
    extra: Dict[str, Any] = Field(default_factory=dict)  # Provider 额外参数
    api_key_override: Optional[str] = None  # 前端运行时覆盖 API Key（优先于 .env）


class DirectorConfig(BaseModel):
    """OS2 Director Agent provider settings."""
    enabled: bool = True
    provider: str = "mock"
    model: str = "mock"
    temperature: float = 0.72
    max_tokens: int = 800
    timeout_seconds: int = 20


class JudgeConfig(BaseModel):
    """L5 行动评价 LLM Judge 配置。

    Judge 是中立第三方裁判，将自然语言行动评成可计算的能力向量与质量参数，
    替代原来的常量启发式（会导致世界死寂 + 模型分数无差异）。
    provider/model 留空时复用导演 provider（中立系统模型，非参赛模型，避免偏袒）。
    """
    enabled: bool = True
    provider: str = ""               # 留空 = 复用导演 provider
    model: str = ""
    temperature: float = 0.3         # 评分应低温稳定
    max_tokens: int = 700
    timeout_seconds: int = 20


class SandboxConfig(BaseModel):
    """工具沙盒配置"""
    enabled: bool = True
    timeout_sec: float = 5.0        # 单次代码执行超时
    max_artifacts_per_agent: int = 3
    max_code_lines: int = 50
    code_workspace_max_bytes: int = 32768   # 工作区单文件上限
    code_workspace_max_files: int = 20        # 每 agent 工作区文件数上限
    process_backend: str = "auto"             # auto / sandbox_exec / process
    allow_network: bool = False                # Agent 研究代码是否可经受控网络出口访问外部
    allow_package_install: bool = False        # 是否允许 Agent 在自己的虚拟环境安装依赖
    process_timeout_sec: float = 30.0
    package_install_timeout_sec: float = 120.0
    max_process_output_bytes: int = 131072


class McpConfig(BaseModel):
    """MCP（Model Context Protocol，模型上下文协议）客户端配置"""
    enabled: bool = True
    servers_path: str = "./mcp_servers.yaml"


class TtsConfig(BaseModel):
    """语音合成配置（MiniMax T2A v2）"""
    enabled: bool = False
    voice_id: str = "presenter_male"   # MiniMax 音色 ID
    speed: float = 1.0
    timeout_sec: float = 15.0


class AgentBriefingConfig(BaseModel):
    """P0 模型简报注入配置"""
    enabled: bool = True
    record_prompt: bool = False                # 是否完整记录 prompt（token 敏感可关）
    require_structured_output: bool = False    # 是否要求模型必须返回结构化输出


class AgentLoopConfig(BaseModel):
    """D 轨：单 tick 内 Agent 多步循环（调工具 → 看结果 → 再决策）。"""
    enabled: bool = False
    max_steps: int = 5
    session_timeout_sec: float = 60.0


class ExternalAgentConfig(BaseModel):
    """B 轨：外部 Agent 接入默认参数。"""
    turn_timeout_ms: int = 120_000
    protocol_version: str = "0.2"


class FrameworkConfig(BaseModel):
    """完整框架配置"""
    # 场景包路径（换场景只改这一行）
    scenario_path: str = "./scenarios/example"
    scenario_locale: str = "zh-CN"

    # Agent 插槽列表（可插拔，数量由场景包声明支持多少）
    agents: List[AgentSlotConfig] = Field(default_factory=list)

    # 时间控制
    tick_interval_sec: float = 10.0    # 世界推进节拍（秒）
    agent_timeout_sec: float = 8.0     # Agent 每回合最长思考时间
    runtime_mode: str = "story"  # story / replay / benchmark / data_factory（兼容旧 entertainment）
    random_seed: Optional[int] = None
    headless: bool = False
    provider_health_check: bool = True

    # 子系统配置
    director: DirectorConfig = Field(default_factory=DirectorConfig)
    judge: JudgeConfig = Field(default_factory=JudgeConfig)
    sandbox: SandboxConfig = Field(default_factory=SandboxConfig)
    mcp: McpConfig = Field(default_factory=McpConfig)
    tts: TtsConfig = Field(default_factory=TtsConfig)
    agent_briefing: AgentBriefingConfig = Field(default_factory=AgentBriefingConfig)
    agent_loop: AgentLoopConfig = Field(default_factory=AgentLoopConfig)
    external_agent: ExternalAgentConfig = Field(default_factory=ExternalAgentConfig)

    # 日志
    log_dir: str = "./runs"
    # 跨局持久记忆根目录（账户体系：每用户一份，见 EngineManager._build_context）
    persistent_memory_root: str = "./agents_persistent"

    @field_validator("scenario_path")
    @classmethod
    def scenario_must_exist(cls, v: str) -> str:
        p = Path(v)
        if not p.exists():
            raise ValueError(f"场景包路径不存在: {v}")
        return v


def load_config(path: str = "./framework.yaml") -> FrameworkConfig:
    """加载 framework.yaml，环境变量可覆盖顶层字段（AIWORLD_前缀）"""
    cfg_path = Path(path)
    if not cfg_path.exists():
        raise FileNotFoundError(f"框架配置文件不存在: {path}")

    with open(cfg_path, encoding="utf-8") as f:
        data: Dict[str, Any] = yaml.safe_load(f) or {}

    # 环境变量覆盖（AIWORLD_TICK_INTERVAL_SEC=5 等）
    for key in [
        "tick_interval_sec", "agent_timeout_sec", "log_dir",
        "scenario_path", "scenario_locale", "runtime_mode", "random_seed",
    ]:
        env_key = f"AIWORLD_{key.upper()}"
        if env_key in os.environ:
            data[key] = os.environ[env_key]

    scenario_path = data.get("scenario_path")
    if scenario_path and not Path(str(scenario_path)).is_absolute():
        relative = Path(str(scenario_path))
        candidates = [Path.cwd() / relative]
        candidates.extend(parent / relative for parent in cfg_path.resolve().parents)
        resolved = next((item.resolve() for item in candidates if item.exists()), None)
        if resolved is not None:
            data["scenario_path"] = str(resolved)

    mcp = data.get("mcp")
    if isinstance(mcp, dict) and mcp.get("servers_path"):
        relative = Path(str(mcp["servers_path"]))
        if not relative.is_absolute():
            candidates = [Path.cwd() / relative]
            candidates.extend(parent / relative for parent in cfg_path.resolve().parents)
            resolved = next((item.resolve() for item in candidates if item.exists()), None)
            if resolved is not None:
                mcp["servers_path"] = str(resolved)

    return FrameworkConfig(**data)
