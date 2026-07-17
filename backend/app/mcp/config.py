"""MCP 服务端注册配置模型。"""
from __future__ import annotations

from typing import Dict, List, Literal, Optional

from pydantic import BaseModel, Field, model_validator


class McpServerAuthConfig(BaseModel):
    """MCP Server 鉴权配置。"""

    type: Literal["none", "bearer"] = "none"
    token_env: Optional[str] = None


class McpServerConfig(BaseModel):
    """单个 MCP Server 声明。"""

    id: str
    transport: Literal["stdio", "http", "sse"] = "stdio"
    enabled: bool = True
    timeout_sec: float = 20.0
    command: Optional[str] = None
    args: List[str] = Field(default_factory=list)
    env: Dict[str, str] = Field(default_factory=dict)
    endpoint: Optional[str] = None
    auth: McpServerAuthConfig = Field(default_factory=McpServerAuthConfig)

    @model_validator(mode="after")
    def _validate_transport_fields(self) -> "McpServerConfig":
        if self.transport == "stdio":
            if not self.command:
                raise ValueError(f"MCP server '{self.id}': stdio 传输需要 command")
        elif self.transport in ("http", "sse"):
            if not self.endpoint:
                raise ValueError(
                    f"MCP server '{self.id}': {self.transport} 传输需要 endpoint"
                )
        return self


class McpServersConfig(BaseModel):
    """mcp_servers.yaml 根结构。"""

    servers: List[McpServerConfig] = Field(default_factory=list)

    def server_index(self) -> Dict[str, McpServerConfig]:
        return {s.id: s for s in self.servers if s.id}


class McpConfig(BaseModel):
    """框架级 MCP 开关（写入 framework.yaml 可选块）。"""

    enabled: bool = True
    servers_path: str = "./mcp_servers.yaml"
