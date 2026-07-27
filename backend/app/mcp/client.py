"""MCP Client 管理器：连接、发现工具、调用工具。"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import time
from types import SimpleNamespace
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from app.mcp.config import McpServerConfig, McpServersConfig

logger = logging.getLogger(__name__)

_manager: Optional["MCPClientManager"] = None


class MCPUnavailableError(RuntimeError):
    """MCP Python SDK 未安装或 Python 版本不满足（需 >=3.10）。"""


class MCPTransportError(RuntimeError):
    """不支持的传输或连接失败。"""


class _RawStdioSession:
    """Small MCP stdio client used when the optional SDK is unavailable."""

    def __init__(self, process: asyncio.subprocess.Process):
        self._process = process
        self._seq = 0

    async def _request(self, method: str, params: Dict[str, Any]) -> Any:
        self._seq += 1
        payload = {
            "jsonrpc": "2.0", "id": self._seq,
            "method": method, "params": params,
        }
        assert self._process.stdin is not None
        assert self._process.stdout is not None
        self._process.stdin.write(
            (json.dumps(payload, ensure_ascii=False) + "\n").encode("utf-8")
        )
        await self._process.stdin.drain()
        while True:
            line = await self._process.stdout.readline()
            if not line:
                stderr = ""
                if self._process.stderr is not None:
                    stderr = (await self._process.stderr.read()).decode(
                        "utf-8", errors="replace"
                    )
                raise MCPTransportError(f"stdio_server_closed:{stderr[-1000:]}")
            response = json.loads(line.decode("utf-8"))
            if response.get("id") != self._seq:
                continue
            if response.get("error"):
                raise MCPTransportError(str(response["error"]))
            return response.get("result") or {}

    async def initialize(self) -> Any:
        result = await self._request("initialize", {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "aiworld-raw-mcp", "version": "1.0"},
        })
        assert self._process.stdin is not None
        self._process.stdin.write((json.dumps({
            "jsonrpc": "2.0", "method": "notifications/initialized",
            "params": {},
        }) + "\n").encode("utf-8"))
        await self._process.stdin.drain()
        return result

    async def list_tools(self) -> Any:
        result = await self._request("tools/list", {})
        return SimpleNamespace(tools=result.get("tools", []))

    async def call_tool(self, name: str, arguments: Dict[str, Any]) -> Any:
        result = await self._request(
            "tools/call", {"name": name, "arguments": arguments}
        )
        return SimpleNamespace(
            content=result.get("content", []),
            structuredContent=result.get("structuredContent"),
            structured_content=result.get("structuredContent"),
            isError=bool(result.get("isError", False)),
            is_error=bool(result.get("isError", False)),
        )


@dataclass
class MCPToolDescriptor:
    """从 MCP Server 发现的工具描述。"""

    name: str
    description: str = ""
    input_schema: Dict[str, Any] = field(default_factory=dict)


@dataclass
class MCPToolCallResult:
    """单次 MCP 工具调用结果。"""

    ok: bool
    server_id: str
    tool_name: str
    content_text: str = ""
    structured: Any = None
    duration_ms: float = 0.0
    errors: List[str] = field(default_factory=list)


def _import_mcp_stdio():
    try:
        from mcp import ClientSession, StdioServerParameters
        from mcp.client.stdio import stdio_client
    except ImportError as exc:
        raise MCPUnavailableError(
            "未安装 MCP SDK 或 Python 版本过低（需要 Python>=3.10 且 pip install 'mcp>=1.27,<2'）"
        ) from exc
    return ClientSession, StdioServerParameters, stdio_client


def _content_blocks_to_text(content: Any) -> str:
    if content is None:
        return ""
    parts: List[str] = []
    for block in content:
        text = getattr(block, "text", None)
        if text is not None:
            parts.append(str(text))
        elif isinstance(block, dict) and block.get("text") is not None:
            parts.append(str(block["text"]))
    return "\n".join(parts).strip()


class MCPClientManager:
    """管理多个 MCP Server 的发现与调用。"""

    def __init__(self, cfg: McpServersConfig, *, globally_enabled: bool = True):
        self._cfg = cfg
        self._globally_enabled = globally_enabled
        self._index = cfg.server_index()
        self._locks: Dict[str, asyncio.Lock] = {
            sid: asyncio.Lock() for sid in self._index
        }

    @property
    def enabled(self) -> bool:
        return self._globally_enabled

    @property
    def server_ids(self) -> List[str]:
        return [
            s.id
            for s in self._cfg.servers
            if s.enabled and self._globally_enabled
        ]

    def get_server(self, server_id: str) -> Optional[McpServerConfig]:
        srv = self._index.get(server_id)
        if not srv or not srv.enabled or not self._globally_enabled:
            return None
        return srv

    async def list_tools(self, server_id: str) -> List[MCPToolDescriptor]:
        srv = self.get_server(server_id)
        if not srv:
            return []
        if srv.transport != "stdio":
            raise MCPTransportError(
                f"MCP server '{server_id}': A-PR1 仅实现 stdio，"
                f"当前 transport={srv.transport}"
            )
        return await self._with_stdio_session(srv, self._list_tools_in_session)

    async def call_tool(
        self,
        server_id: str,
        tool_name: str,
        arguments: Optional[Dict[str, Any]] = None,
        *,
        timeout_sec: Optional[float] = None,
    ) -> MCPToolCallResult:
        srv = self.get_server(server_id)
        if not srv:
            return MCPToolCallResult(
                ok=False,
                server_id=server_id,
                tool_name=tool_name,
                errors=[f"unknown_or_disabled_server:{server_id}"],
            )
        if srv.transport != "stdio":
            return MCPToolCallResult(
                ok=False,
                server_id=server_id,
                tool_name=tool_name,
                errors=[
                    f"unsupported_transport:{srv.transport} "
                    "(A-PR1 仅 stdio)"
                ],
            )

        t0 = time.perf_counter()
        try:
            result = await asyncio.wait_for(
                self._with_stdio_session(
                    srv,
                    lambda session: self._call_tool_in_session(
                        session, srv.id, tool_name, arguments or {}
                    ),
                ),
                timeout=timeout_sec or srv.timeout_sec,
            )
            result.duration_ms = (time.perf_counter() - t0) * 1000.0
            return result
        except asyncio.TimeoutError:
            return MCPToolCallResult(
                ok=False,
                server_id=server_id,
                tool_name=tool_name,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                errors=[f"timeout>{timeout_sec or srv.timeout_sec}s"],
            )
        except MCPUnavailableError as exc:
            return MCPToolCallResult(
                ok=False,
                server_id=server_id,
                tool_name=tool_name,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                errors=[str(exc)],
            )
        except Exception as exc:  # noqa: BLE001 — 外部 MCP 边界
            logger.warning("[mcp] call_tool 失败 server=%s tool=%s: %s", server_id, tool_name, exc)
            return MCPToolCallResult(
                ok=False,
                server_id=server_id,
                tool_name=tool_name,
                duration_ms=(time.perf_counter() - t0) * 1000.0,
                errors=[str(exc)],
            )

    async def _with_stdio_session(self, srv: McpServerConfig, fn):
        lock = self._locks.setdefault(srv.id, asyncio.Lock())
        async with lock:
            env = {**os.environ, **(srv.env or {})}
            try:
                ClientSession, StdioServerParameters, stdio_client = _import_mcp_stdio()
            except MCPUnavailableError:
                process = await asyncio.create_subprocess_exec(
                    srv.command or "", *(srv.args or []),
                    stdin=asyncio.subprocess.PIPE,
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                    env=env,
                )
                session = _RawStdioSession(process)
                try:
                    await session.initialize()
                    return await fn(session)
                finally:
                    if process.stdin is not None:
                        process.stdin.close()
                    try:
                        await asyncio.wait_for(process.wait(), timeout=2)
                    except asyncio.TimeoutError:
                        process.kill()
                        await process.wait()
            params = StdioServerParameters(
                command=srv.command or "",
                args=list(srv.args or []),
                env=env,
            )
            async with stdio_client(params) as (read, write):
                async with ClientSession(read, write) as session:
                    await session.initialize()
                    return await fn(session)

    @staticmethod
    async def _list_tools_in_session(session) -> List[MCPToolDescriptor]:
        listed = await session.list_tools()
        tools = getattr(listed, "tools", listed) or []
        out: List[MCPToolDescriptor] = []
        for t in tools:
            name = getattr(t, "name", None) or (t.get("name") if isinstance(t, dict) else "")
            if not name:
                continue
            desc = getattr(t, "description", None) or (
                t.get("description", "") if isinstance(t, dict) else ""
            )
            schema = getattr(t, "inputSchema", None) or getattr(t, "input_schema", None)
            if schema is None and isinstance(t, dict):
                schema = t.get("inputSchema") or t.get("input_schema") or {}
            out.append(
                MCPToolDescriptor(
                    name=str(name),
                    description=str(desc or ""),
                    input_schema=dict(schema or {}),
                )
            )
        return out

    @staticmethod
    async def _call_tool_in_session(
        session,
        server_id: str,
        tool_name: str,
        arguments: Dict[str, Any],
    ) -> MCPToolCallResult:
        result = await session.call_tool(tool_name, arguments=arguments)
        text = _content_blocks_to_text(getattr(result, "content", None))
        structured = getattr(result, "structuredContent", None) or getattr(
            result, "structured_content", None
        )
        is_error = bool(getattr(result, "isError", False) or getattr(result, "is_error", False))
        return MCPToolCallResult(
            ok=not is_error,
            server_id=server_id,
            tool_name=tool_name,
            content_text=text,
            structured=structured,
            errors=[text] if is_error and text else [],
        )

    async def close(self) -> None:
        """预留：后续可关闭长连接池。A-PR1 每次 call 短连接，无需操作。"""
        return None


async def init_mcp_manager(
    servers_path: str,
    *,
    enabled: bool = True,
) -> MCPClientManager:
    from app.mcp.registry import load_mcp_servers

    cfg = load_mcp_servers(servers_path)
    manager = MCPClientManager(cfg, globally_enabled=enabled)
    logger.info(
        "[mcp] MCPClientManager 就绪 enabled=%s servers=%s",
        enabled,
        manager.server_ids,
    )
    return manager


def get_mcp_manager() -> Optional[MCPClientManager]:
    return _manager


def set_mcp_manager(manager: Optional[MCPClientManager]) -> None:
    global _manager
    _manager = manager
