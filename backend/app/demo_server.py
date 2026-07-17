"""Local-only, unauthenticated TraceArena Demo Console.

This module is intentionally for trusted localhost development.  It keeps API
keys in process memory only and must not be exposed directly to the internet.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import uuid
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, Field

ROOT = Path(os.environ.get("TRACEARENA_ROOT", Path(__file__).resolve().parents[2])).resolve()
WEB = ROOT / "frontend" / "demo_web"
SCENARIO = ROOT / "backend" / "scenarios" / "capital_market"

app = FastAPI(title="TraceArena Local Demo", docs_url=None, redoc_url=None)
app.mount("/assets", StaticFiles(directory=WEB), name="assets")


class RunRequest(BaseModel):
    mode: Literal["replay", "llm"] = "replay"
    locale: Literal["zh-CN", "en-US"] = "zh-CN"
    provider: Literal["mock", "openai", "deepseek", "anthropic", "minimax", "ark"] = "mock"
    model: str = "mock-v1"
    api_key: str = Field(default="", repr=False)
    ticks: int = Field(default=2, ge=1, le=10)


_runs: dict[str, dict[str, Any]] = {}


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {"status": "ok", "mode": "localhost-only", "key_persistence": "none"}


@app.get("/api/scenarios")
async def scenarios() -> list[dict[str, Any]]:
    return [{"id": "capital_market", "path": str(SCENARIO), "locales": ["zh-CN", "en-US"]}]


@app.post("/api/runs")
async def create_run(request: RunRequest) -> dict[str, Any]:
    if request.mode == "llm" and not request.api_key:
        raise HTTPException(400, "A real LLM run requires an API key for this request.")
    run_id = uuid.uuid4().hex
    with tempfile.TemporaryDirectory(prefix="tracearena-demo-") as temp:
        output = Path(temp) / "replay"
        if request.mode == "replay":
            command = [sys.executable, str(ROOT / "backend" / "scripts" / "market_replay.py"), "--scenario", str(SCENARIO), "--fixture", str(ROOT / "examples" / "market_replay" / "fixture.json"), "--output", str(output), "--locale", request.locale]
            completed = await asyncio.to_thread(subprocess.run, command, cwd=ROOT, env={**dict(__import__("os").environ), "PYTHONPATH": str(ROOT / "backend")}, capture_output=True, text=True, timeout=45)
            if completed.returncode:
                raise HTTPException(500, completed.stderr[-1200:] or "Replay failed")
            manifest, replay, stdout = _read_json(output / "run_manifest.json"), _read_json(output / "replay_deterministic.json"), completed.stdout
        else:
            from app.config import AgentSlotConfig, FrameworkConfig
            from app.engine.main import EngineOS
            from app.engine.scenario_boot.loader import ScenarioBootKernel
            scenario = ScenarioBootKernel.load(str(SCENARIO), locale=request.locale)
            agents = [AgentSlotConfig(id=role.agent_slot_id, name=role.display_name, color=role.color, provider=request.provider, model=request.model, api_key_override=request.api_key) for role in scenario.agent_roles]
            cfg = FrameworkConfig(scenario_path=str(SCENARIO), scenario_locale=request.locale, runtime_mode="story", agents=agents, director={"enabled": False, "provider": "mock", "model": "mock"}, judge={"enabled": False}, sandbox={"enabled": False}, mcp={"enabled": False}, tts={"enabled": False}, agent_loop={"enabled": False}, headless=True, provider_health_check=False, log_dir=str(output / "runs"))
            engine = EngineOS(cfg, scenario)
            await engine.initialize()
            ticks = []
            for _ in range(request.ticks):
                await engine.step()
                ticks.append({"tick": engine.state.tick if engine.state else 0, "actions": [item.model_dump() if hasattr(item, "model_dump") else {} for item in getattr(engine, "_last_os2_actions", []) or []], "events": [item.model_dump() if hasattr(item, "model_dump") else {} for item in getattr(engine, "_last_os2_events", []) or []], "settlements": [item.model_dump() if hasattr(item, "model_dump") else {} for item in getattr(engine, "_last_os2_settlements", []) or []]})
            manifest, replay, stdout = {"provider": request.provider, "model": request.model, "locale": request.locale, "key_persistence": "none"}, {"ticks": ticks}, "Real LLM run completed"
        _runs[run_id] = {"run_id": run_id, "mode": request.mode, "provider": request.provider, "model": request.model, "locale": request.locale, "manifest": manifest, "replay": replay, "stdout": stdout}
    return _runs[run_id]


@app.get("/api/runs/{run_id}")
async def get_run(run_id: str) -> dict[str, Any]:
    if run_id not in _runs:
        raise HTTPException(404, "Run not found")
    return _runs[run_id]
