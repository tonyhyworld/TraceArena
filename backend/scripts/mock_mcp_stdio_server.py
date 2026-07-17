#!/usr/bin/env python3
"""最小 MCP stdio 服务端，供 Agent OS E2E 联调（无需额外依赖）。"""
from __future__ import annotations

import json
import sys
from typing import Any, Dict, Optional


def _send(msg: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(msg, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _ok(req_id: Any, result: Dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _err(req_id: Any, code: int, message: str) -> None:
    _send({
        "jsonrpc": "2.0",
        "id": req_id,
        "error": {"code": code, "message": message},
    })


def _handle(req: Dict[str, Any]) -> None:
    method = str(req.get("method") or "")
    req_id = req.get("id")
    params = req.get("params") or {}

    if method == "initialize":
        _ok(req_id, {
            "protocolVersion": params.get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "e2e-echo-mcp", "version": "0.1.0"},
        })
        return

    if method == "notifications/initialized":
        return

    if method == "tools/list":
        _ok(req_id, {
            "tools": [{
                "name": "echo",
                "description": "回显 query 参数，用于 E2E 验证",
                "inputSchema": {
                    "type": "object",
                    "properties": {"query": {"type": "string"}},
                    "required": ["query"],
                },
            }],
        })
        return

    if method == "tools/call":
        name = str((params.get("name") or ""))
        arguments = params.get("arguments") or {}
        if name != "echo":
            _ok(req_id, {
                "content": [{"type": "text", "text": f"unknown tool: {name}"}],
                "isError": True,
            })
            return
        query = str(arguments.get("query") or "")
        _ok(req_id, {
            "content": [{"type": "text", "text": f"echo:{query}"}],
            "isError": False,
        })
        return

    if req_id is not None:
        _err(req_id, -32601, f"Method not found: {method}")


def main() -> None:
    for line in sys.stdin:
        line = line.strip()
        if not line:
            continue
        try:
            req = json.loads(line)
        except json.JSONDecodeError:
            continue
        if isinstance(req, dict):
            _handle(req)


if __name__ == "__main__":
    main()
