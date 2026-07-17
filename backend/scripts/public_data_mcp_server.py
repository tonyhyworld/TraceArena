#!/usr/bin/env python3
"""Restricted public JSON MCP server for Agent Harness research.

This is a generic transport capability. Scenarios and agents decide which
public API to query and how to interpret it. The server only enforces network
boundaries and returns provenance-rich immutable data.
"""
from __future__ import annotations

import hashlib
import json
import os
import sys
import time
from typing import Any, Dict
from urllib.parse import urlparse
from urllib.request import Request, urlopen


DEFAULT_ALLOWED_HOSTS = {
    # 通用/美股/加密（原有）
    "www.alphavantage.co",
    "query1.finance.yahoo.com",
    "query2.finance.yahoo.com",
    "api.coingecko.com",
    "data.sec.gov",
    # 注：东方财富（eastmoney.com）系列、GDELT（api.gdeltproject.org）曾在此列，
    # 均实测在用户网络环境下 TLS 连接失败（不可达），已移除。A股/港股数据改由
    # Longport MCP（官方券商 SDK，见 longport_mcp_server.py）与 akshare_data
    # skill（新浪源）承担；全球新闻暂无已验证可用的免费无 key 数据源。
}


def _send(payload: Dict[str, Any]) -> None:
    sys.stdout.write(json.dumps(payload, ensure_ascii=False) + "\n")
    sys.stdout.flush()


def _ok(req_id: Any, result: Dict[str, Any]) -> None:
    _send({"jsonrpc": "2.0", "id": req_id, "result": result})


def _error_content(req_id: Any, message: str) -> None:
    _ok(req_id, {
        "content": [{"type": "text", "text": message}],
        "isError": True,
    })


def _allowed_hosts() -> set[str]:
    configured = {
        value.strip().lower()
        for value in os.getenv("AIWORLD_PUBLIC_DATA_HOSTS", "").split(",")
        if value.strip()
    }
    return configured or DEFAULT_ALLOWED_HOSTS


def _fetch_json(arguments: Dict[str, Any]) -> Dict[str, Any]:
    url = str(arguments.get("url") or "").strip()
    parsed = urlparse(url)
    if parsed.scheme != "https" or parsed.hostname not in _allowed_hosts():
        raise ValueError("url_not_allowed: only approved HTTPS public-data hosts")
    timeout = max(2.0, min(20.0, float(arguments.get("timeout_sec") or 12.0)))
    request = Request(
        url,
        headers={
            "Accept": "application/json",
            "User-Agent": "AIWorld-AgentHarness/2.0 contact=local-testing",
        },
    )
    with urlopen(request, timeout=timeout) as response:
        raw = response.read(1_000_001)
        if len(raw) > 1_000_000:
            raise ValueError("response_too_large")
        charset = response.headers.get_content_charset() or "utf-8"
        text = raw.decode(charset, errors="replace")
        data = json.loads(text)
    fetched_at = time.time()
    return {
        "source_uri": url,
        "fetched_at": fetched_at,
        "source_hash": hashlib.sha256(raw).hexdigest(),
        "content_type": "application/json",
        "data": data,
    }


def _handle(req: Dict[str, Any]) -> None:
    method = str(req.get("method") or "")
    req_id = req.get("id")
    params = req.get("params") or {}
    if method == "initialize":
        _ok(req_id, {
            "protocolVersion": params.get("protocolVersion", "2024-11-05"),
            "capabilities": {"tools": {}},
            "serverInfo": {"name": "aiworld-public-data", "version": "1.0.0"},
        })
    elif method == "notifications/initialized":
        return
    elif method == "tools/list":
        allowed = sorted(_allowed_hosts())
        _ok(req_id, {"tools": [{
            "name": "public_json_get",
            "description": (
                "读取获准公开数据源的 HTTPS JSON API，适合美股行情、公司披露、"
                "全球新闻/地缘政治和加密资产研究。调用者自行选择数据源并构造 URL。"
                "A股/港股行情与财报请改用 longport_* 工具或 akshare_data skill。"
                f"当前允许域名：{', '.join(allowed)}。"
            ),
            "inputSchema": {
                "type": "object",
                "properties": {
                    "url": {
                        "type": "string",
                        "description": (
                            "完整 HTTPS API URL；域名只能是："
                            + ", ".join(allowed)
                        ),
                    },
                    "timeout_sec": {"type": "number"},
                },
                "required": ["url"],
            },
        }]})
    elif method == "tools/call":
        if str(params.get("name") or "") != "public_json_get":
            _error_content(req_id, "unknown_tool")
            return
        try:
            result = _fetch_json(params.get("arguments") or {})
        except Exception as exc:
            _error_content(req_id, str(exc))
            return
        _ok(req_id, {
            "content": [{"type": "text", "text": "公开 JSON 数据读取成功"}],
            "structuredContent": result,
            "isError": False,
        })
    elif req_id is not None:
        _send({
            "jsonrpc": "2.0", "id": req_id,
            "error": {"code": -32601, "message": f"Method not found: {method}"},
        })


def main() -> None:
    for line in sys.stdin:
        try:
            request = json.loads(line)
        except (json.JSONDecodeError, TypeError):
            continue
        if isinstance(request, dict):
            _handle(request)


if __name__ == "__main__":
    main()
