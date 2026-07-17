"""框架级异常定义"""
from __future__ import annotations


class AIWorldError(Exception):
    """框架基础异常"""


class ScenarioLoadError(AIWorldError):
    """场景包加载失败"""


class ProviderError(AIWorldError):
    """LLM Provider 调用失败"""


class AgentTimeoutError(AIWorldError):
    """Agent 超时未提交动作"""
    def __init__(self, agent_id: str, timeout: float):
        self.agent_id = agent_id
        self.timeout = timeout
        super().__init__(f"Agent {agent_id} 超时（{timeout}s）")


class SandboxError(AIWorldError):
    """宝器代码执行错误"""


class ArtifactPermissionError(SandboxError):
    """宝器代码试图访问禁止的 API"""
