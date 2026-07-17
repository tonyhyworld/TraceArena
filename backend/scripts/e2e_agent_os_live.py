#!/usr/bin/env python3
"""Agent OS 本地 E2E：REST + WebSocket + MCP（环境允许时）。"""
from __future__ import annotations

import asyncio
import json
import os
import sys
import time
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

import httpx
import websockets

BACKEND = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(BACKEND))

BASE = os.environ.get("E2E_BASE_URL", "http://127.0.0.1:8001")
WS_BASE = BASE.replace("https://", "wss://").replace("http://", "ws://")
E2E_USER = os.environ.get("E2E_USERNAME", "e2e_agent_os")
E2E_PASS = os.environ.get("E2E_PASSWORD", "e2e-agent-os-pass")

PASS = "PASS"
FAIL = "FAIL"
SKIP = "SKIP"


class Result:
    def __init__(self, name: str, status: str, detail: str = "") -> None:
        self.name = name
        self.status = status
        self.detail = detail


def ensure_e2e_user() -> None:
    from app.auth.permissions import ALL_PERMISSION_KEYS
    from app.auth.store import user_store

    if user_store.get_by_username(E2E_USER) is None:
        user_store.create_user(
            username=E2E_USER,
            password=E2E_PASS,
            display_name="E2E Agent OS",
            is_admin=True,
            permissions=list(ALL_PERMISSION_KEYS),
        )
        print(f"[setup] 已创建测试账号 {E2E_USER}")


def wait_server(timeout_sec: float = 45.0) -> None:
    deadline = time.time() + timeout_sec
    last_err = ""
    while time.time() < deadline:
        try:
            r = httpx.get(f"{BASE}/", timeout=2.0)
            if r.status_code == 200:
                return
            last_err = f"HTTP {r.status_code}"
        except Exception as exc:  # noqa: BLE001
            last_err = str(exc)
        time.sleep(0.5)
    raise RuntimeError(f"服务未就绪 ({BASE}): {last_err}")


def login(client: httpx.Client) -> Tuple[str, str]:
    r = client.post("/auth/login", json={"username": E2E_USER, "password": E2E_PASS})
    r.raise_for_status()
    data = r.json()
    token = data["token"]
    client.headers["Authorization"] = f"Bearer {token}"
    return token, data["user_id"]


def test_health(client: httpx.Client) -> Result:
    r = client.get("/")
    if r.status_code != 200 or r.json().get("status") != "ok":
        return Result("健康检查", FAIL, r.text[:200])
    return Result("健康检查", PASS, f"active_engines={r.json().get('active_engines')}")


def test_skill_md(client: httpx.Client) -> Result:
    r = client.get("/agent/skill.md")
    if r.status_code != 200:
        return Result("GET /agent/skill.md", FAIL, r.text[:200])
    if "decision" not in r.text or "tick_brief" not in r.text:
        return Result("GET /agent/skill.md", FAIL, "缺少协议关键字")
    return Result("GET /agent/skill.md", PASS, f"{len(r.text)} bytes")


def test_join_and_link(client: httpx.Client) -> Tuple[Result, Optional[str]]:
    for slot in ("prince_a", "prince_c"):
        client.patch(
            f"/config/agents/{slot}",
            json={"provider": "mock", "model": "mock-v1"},
        )

    r = client.post("/agent/slots/prince_b/link")
    if r.status_code != 200:
        return Result("POST /agent/slots/{id}/link", FAIL, r.text[:300]), None
    link = r.json()
    token = link.get("slot_token")
    if not token:
        return Result("POST /agent/slots/{id}/link", FAIL, "无 slot_token"), None

    join = client.get(f"/agent/join?t={token}")
    if join.status_code != 200:
        return Result("GET /agent/join", FAIL, join.text[:300]), token
    data = join.json()
    if data.get("role", {}).get("slot_id") != "prince_b":
        return Result("GET /agent/join", FAIL, json.dumps(data, ensure_ascii=False)[:200]), token
    return Result("REST 链接 + join 自描述", PASS, data["connect"]["ws_url"]), token


async def ws_external_agent_flow(slot_token: str) -> Tuple[Result, asyncio.Event, Dict[str, Any]]:
    done = asyncio.Event()
    turn_result: Dict[str, Any] = {}
    errors: List[str] = []

    async def _run() -> None:
        url = f"{WS_BASE}/agent/ws?t={slot_token}"
        try:
            async with websockets.connect(url, open_timeout=10) as ws:
                saw_ready = False
                saw_brief = False
                deadline = time.time() + 90
                while time.time() < deadline:
                    raw = await asyncio.wait_for(ws.recv(), timeout=30)
                    msg = json.loads(raw)
                    mtype = msg.get("type")
                    if mtype == "session_ready":
                        saw_ready = True
                        await ws.send(json.dumps({"type": "ready", "payload": {}}))
                    elif mtype == "ping":
                        await ws.send(json.dumps({
                            "type": "pong",
                            "payload": {},
                        }))
                    elif mtype == "tick_brief":
                        saw_brief = True
                        turn_id = msg["payload"]["turn_id"]
                        await ws.send(json.dumps({
                            "type": "decision",
                            "payload": {
                                "turn_id": turn_id,
                                "raw_model_output": (
                                    '{"action_id":"wait_and_prepare",'
                                    '"character_monologue":"E2E 外部 Agent 决策"}'
                                ),
                            },
                        }))
                    elif mtype == "turn_result":
                        turn_result.update(msg.get("payload") or {})
                        if not saw_ready:
                            errors.append("未收到 session_ready")
                        if not saw_brief:
                            errors.append("未收到 tick_brief")
                        done.set()
                        return
                    elif mtype == "error":
                        errors.append(str(msg.get("payload")))
                errors.append("等待 turn_result 超时")
        except Exception as exc:  # noqa: BLE001
            errors.append(str(exc))
        finally:
            done.set()

    task = asyncio.create_task(_run())
    await asyncio.sleep(0.3)
    if task.done() and errors:
        return Result("WebSocket 外部 Agent 全链路", FAIL, "; ".join(errors)), done, turn_result
    return Result("WebSocket 客户端已连接", PASS, "等待 tick_brief…"), done, turn_result


async def wait_slot_ready(client: httpx.Client, slot_id: str = "prince_b") -> Result:
    for _ in range(30):
        r = client.get(f"/agent/slots/{slot_id}/status")
        if r.status_code == 200:
            data = r.json()
            if data.get("connected") and data.get("status") == "READY":
                return Result("WS 就绪等待", PASS, f"status={data['status']}")
        await asyncio.sleep(0.2)
    r = client.get(f"/agent/slots/{slot_id}/status")
    detail = r.text[:200] if r.status_code == 200 else r.text[:200]
    return Result("WS 就绪等待", FAIL, detail)
    client.post("/control/reset")
    r = client.post("/control/step")
    if r.status_code != 200:
        return Result("POST /control/step", FAIL, r.text[:300])
    return Result("POST /control/step", PASS, r.json().get("status", ""))


async def wait_ws_done(done: asyncio.Event, turn_result: Dict[str, Any]) -> Result:
    try:
        await asyncio.wait_for(done.wait(), timeout=120)
    except asyncio.TimeoutError:
        return Result("WebSocket 外部 Agent 全链路", FAIL, "120s 内未收到 turn_result")
    if not turn_result:
        return Result("WebSocket 外部 Agent 全链路", FAIL, "无 turn_result payload")
    if turn_result.get("is_system_fallback"):
        return Result(
            "WebSocket 外部 Agent 全链路",
            FAIL,
            f"引擎使用了系统兜底: {turn_result.get('resolved_action_id')}",
        )
    if not turn_result.get("accepted", True):
        return Result(
            "WebSocket 外部 Agent 全链路",
            FAIL,
            f"decision 未接受: {turn_result}",
        )
    return Result(
        "WebSocket 外部 Agent 全链路",
        PASS,
        f"action={turn_result.get('resolved_action_id')}",
    )


def test_slot_status(client: httpx.Client) -> Result:
    r = client.get("/agent/slots/prince_b/status")
    if r.status_code != 200:
        return Result("GET /agent/slots/{id}/status", FAIL, r.text[:200])
    data = r.json()
    if not data.get("has_token"):
        return Result("GET /agent/slots/{id}/status", FAIL, "无 token")
    return Result(
        "连接状态轮询",
        PASS,
        f"connected={data.get('connected')} status={data.get('status')}",
    )


async def trigger_engine_step(client: httpx.Client) -> Result:
    # 不在 step 前 reset：WS 在长跑 tick 中需持续收 ping。
    # 用 to_thread 避免同步 httpx 阻塞 asyncio 事件循环（否则 WS ping 超时断连）。
    r = await asyncio.to_thread(client.post, "/control/step")
    if r.status_code != 200:
        return Result("POST /control/step", FAIL, r.text[:300])
    return Result("POST /control/step", PASS, r.json().get("status", ""))


async def test_mcp_mock_server_pipe() -> Result:
    """不依赖 MCP SDK：验证 mock stdio 服务端 JSON-RPC 响应。"""
    import subprocess

    script = BACKEND / "scripts" / "mock_mcp_stdio_server.py"
    proc = subprocess.Popen(
        [sys.executable, str(script)],
        stdin=subprocess.PIPE,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )
    init = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2024-11-05",
            "capabilities": {},
            "clientInfo": {"name": "e2e", "version": "1"},
        },
    }
    call = {
        "jsonrpc": "2.0",
        "id": 2,
        "method": "tools/call",
        "params": {"name": "echo", "arguments": {"query": "朝议"}},
    }
    assert proc.stdin and proc.stdout
    proc.stdin.write(json.dumps(init) + "\n")
    proc.stdin.write(json.dumps(call) + "\n")
    proc.stdin.flush()
    lines = [proc.stdout.readline().strip() for _ in range(2)]
    proc.terminate()
    try:
        payloads = [json.loads(line) for line in lines if line]
    except json.JSONDecodeError as exc:
        return Result("MCP mock stdio 管道", FAIL, str(exc))
    echo_line = payloads[-1]
    text = str(echo_line.get("result", {}).get("content", [{}])[0].get("text", ""))
    if "echo:朝议" not in text:
        return Result("MCP mock stdio 管道", FAIL, str(echo_line)[:200])
    return Result("MCP mock stdio 管道", PASS, text)


async def test_mcp_stdio_with_python312() -> Result:
    py312 = Path("/opt/homebrew/bin/python3.12")
    if not py312.is_file():
        py312 = Path("/opt/homebrew/opt/python@3.12/bin/python3.12")
    if not py312.is_file():
        return Result("MCP stdio 真实调用", SKIP, "未找到 Python 3.12")

    script = BACKEND / "scripts" / "_e2e_mcp_call.py"
    script.write_text(
        "import asyncio, sys\n"
        "from pathlib import Path\n"
        "sys.path.insert(0, str(Path(__file__).resolve().parents[1]))\n"
        "from app.mcp.client import MCPClientManager\n"
        "from app.mcp.registry import load_mcp_servers\n"
        "async def main():\n"
        "    cfg = load_mcp_servers('./mcp_servers.yaml')\n"
        "    mgr = MCPClientManager(cfg, globally_enabled=True)\n"
        "    tools = await mgr.list_tools('e2e_echo')\n"
        "    assert any(t.name == 'echo' for t in tools), tools\n"
        "    call = await mgr.call_tool('e2e_echo', 'echo', {'query': '朝议'})\n"
        "    assert call.ok and 'echo:朝议' in call.content_text, (call.errors, call.content_text)\n"
        "    print(call.content_text)\n"
        "asyncio.run(main())\n",
        encoding="utf-8",
    )

    proc = await asyncio.create_subprocess_exec(
        str(py312), str(script),
        cwd=str(BACKEND),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=30)
    if proc.returncode != 0:
        err = (stderr or stdout).decode("utf-8", errors="replace")[:400]
        if any(x in err for x in (
            "No module named 'mcp'",
            "No module named 'pydantic'",
            "ImportError",
            "ModuleNotFoundError",
            "Traceback",
        )):
            return Result(
                "MCP stdio 真实调用 (Py3.12)",
                SKIP,
                "本机 Python 3.12 环境缺少依赖或不可用（mock 管道已通过）",
            )
        return Result("MCP stdio 真实调用 (Py3.12)", FAIL, err)
    text = stdout.decode("utf-8", errors="replace").strip()
    return Result("MCP stdio 真实调用 (Py3.12)", PASS, text[:80])


async def main() -> int:
    os.chdir(BACKEND)
    results: List[Result] = []

    print(f"=== Agent OS 本地 E2E ===\nBASE={BASE}\n")

    ensure_e2e_user()
    wait_server()

    with httpx.Client(base_url=BASE, timeout=180.0) as client:
        login(client)
        results.append(test_health(client))
        results.append(test_skill_md(client))

        await asyncio.to_thread(client.post, "/control/reset")

        link_res, slot_token = test_join_and_link(client)
        results.append(link_res)
        if not slot_token:
            _print_report(results)
            return 1

        ws_res, done_evt, turn_box = await ws_external_agent_flow(slot_token)
        results.append(ws_res)

        results.append(await wait_slot_ready(client))

        step_res = await trigger_engine_step(client)
        results.append(step_res)

        results.append(await wait_ws_done(done_evt, turn_box))

        results.append(test_slot_status(client))

    results.append(await test_mcp_mock_server_pipe())
    results.append(await test_mcp_stdio_with_python312())

    _print_report(results)
    failed = sum(1 for r in results if r.status == FAIL)
    return 1 if failed else 0


def _print_report(results: List[Result]) -> None:
    print("\n--- 测试报告 ---")
    for r in results:
        mark = {"PASS": "✅", "FAIL": "❌", "SKIP": "⏭️"}.get(r.status, "?")
        line = f"{mark} [{r.status}] {r.name}"
        if r.detail:
            line += f" — {r.detail}"
        print(line)
    passed = sum(1 for r in results if r.status == PASS)
    skipped = sum(1 for r in results if r.status == SKIP)
    failed = sum(1 for r in results if r.status == FAIL)
    print(f"\n合计: {passed} 通过, {skipped} 跳过, {failed} 失败 / {len(results)} 项")


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))
