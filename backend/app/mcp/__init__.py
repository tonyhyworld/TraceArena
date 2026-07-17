"""MCP（Model Context Protocol，模型上下文协议）客户端 — OS 级外部工具接入。"""

from app.mcp.client import MCPClientManager, get_mcp_manager, set_mcp_manager
from app.mcp.config import McpConfig, McpServerAuthConfig, McpServerConfig, McpServersConfig
from app.mcp.registry import load_mcp_servers

__all__ = [
    "MCPClientManager",
    "McpConfig",
    "McpServerAuthConfig",
    "McpServerConfig",
    "McpServersConfig",
    "get_mcp_manager",
    "load_mcp_servers",
    "set_mcp_manager",
]
