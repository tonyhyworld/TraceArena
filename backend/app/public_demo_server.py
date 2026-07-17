"""Public, replay-only TraceArena demo.

This application is intentionally separate from ``demo_server``.  It accepts
no provider, model, API key, tool configuration, uploads, or arbitrary paths.
It is safe to publish as a bounded demonstration of the deterministic replay
pipeline; it is not the production operations console.
"""
from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
import tempfile
import time
import uuid
from collections import deque
from pathlib import Path
from typing import Any, Literal

from fastapi import FastAPI, HTTPException, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse
from fastapi.responses import JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict

ROOT = Path(__file__).resolve().parents[2]
WEB = ROOT / "frontend" / "public_demo"
SCENARIO = ROOT / "backend" / "scenarios" / "capital_market"
FIXTURE = ROOT / "examples" / "market_replay" / "fixture.json"

MAX_REQUEST_BYTES = 4096
MAX_RUNS_PER_WINDOW = 12
RATE_WINDOW_SECONDS = 60.0
RUN_TIMEOUT_SECONDS = 60.0

app = FastAPI(
    title="TraceArena Public Replay Demo",
    docs_url=None,
    redoc_url=None,
    openapi_url=None,
)
app.mount("/assets", StaticFiles(directory=WEB), name="assets")

_run_gate = asyncio.Semaphore(1)
_recent_runs: deque[float] = deque()


class PublicRunRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    locale: Literal["zh-CN", "en-US"] = "en-US"


@app.exception_handler(RequestValidationError)
async def sanitized_validation_error(
    _request: Request, exc: RequestValidationError
) -> JSONResponse:
    """Return field errors without echoing rejected request values."""
    errors = [
        {
            "loc": list(item.get("loc") or ()),
            "type": str(item.get("type") or "validation_error"),
            "msg": str(item.get("msg") or "Invalid request"),
        }
        for item in exc.errors()
    ]
    return JSONResponse(status_code=422, content={"detail": errors})


def _admit_run(now: float) -> bool:
    while _recent_runs and now - _recent_runs[0] >= RATE_WINDOW_SECONDS:
        _recent_runs.popleft()
    if len(_recent_runs) >= MAX_RUNS_PER_WINDOW:
        return False
    _recent_runs.append(now)
    return True


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _execute_replay(locale: str) -> dict[str, Any]:
    with tempfile.TemporaryDirectory(prefix="tracearena-public-demo-") as temp:
        output = Path(temp) / "replay"
        command = [
            sys.executable,
            str(ROOT / "backend" / "scripts" / "market_replay.py"),
            "--scenario",
            str(SCENARIO),
            "--fixture",
            str(FIXTURE),
            "--output",
            str(output),
            "--locale",
            locale,
        ]
        completed = subprocess.run(
            command,
            cwd=ROOT,
            env={**os.environ, "PYTHONPATH": str(ROOT / "backend")},
            capture_output=True,
            text=True,
            timeout=45,
            check=False,
        )
        if completed.returncode:
            raise RuntimeError("deterministic replay failed")
        return {
            "run_id": uuid.uuid4().hex,
            "mode": "deterministic-replay",
            "manifest": _read_json(output / "run_manifest.json"),
            "replay": _read_json(output / "replay_deterministic.json"),
        }


@app.middleware("http")
async def public_security_boundary(request: Request, call_next: Any) -> Response:
    content_length = request.headers.get("content-length")
    if content_length:
        try:
            if int(content_length) > MAX_REQUEST_BYTES:
                return Response("Request too large", status_code=413)
        except ValueError:
            return Response("Invalid Content-Length", status_code=400)
    response = await call_next(request)
    response.headers["Cache-Control"] = "no-store"
    response.headers["Content-Security-Policy"] = (
        "default-src 'self'; script-src 'self'; style-src 'self'; "
        "img-src 'self' data:; connect-src 'self'; object-src 'none'; "
        "base-uri 'none'; form-action 'self'; frame-ancestors 'self' "
        "https://huggingface.co https://*.huggingface.co"
    )
    response.headers["Permissions-Policy"] = "camera=(), microphone=(), geolocation=()"
    response.headers["Referrer-Policy"] = "no-referrer"
    response.headers["X-Content-Type-Options"] = "nosniff"
    return response


@app.get("/")
async def index() -> FileResponse:
    return FileResponse(WEB / "index.html")


@app.get("/api/health")
async def health() -> dict[str, Any]:
    return {
        "status": "ok",
        "mode": "public-replay-only",
        "llm": "disabled",
        "api_keys": "not-accepted",
        "brokerage": "disabled",
        "network_tools": "disabled",
    }


@app.get("/api/scenarios")
async def scenarios() -> list[dict[str, Any]]:
    return [{
        "id": "capital_market",
        "type": "simulation",
        "data": "synthetic-fixture",
        "locales": ["zh-CN", "en-US"],
    }]


@app.post("/api/runs")
async def create_run(payload: PublicRunRequest) -> dict[str, Any]:
    if not _admit_run(time.monotonic()):
        raise HTTPException(429, "Public demo rate limit reached. Try again in one minute.")
    try:
        await asyncio.wait_for(_run_gate.acquire(), timeout=2.0)
    except TimeoutError as exc:
        raise HTTPException(503, "The public demo is busy. Try again shortly.") from exc
    try:
        return await asyncio.wait_for(
            asyncio.to_thread(_execute_replay, payload.locale),
            timeout=RUN_TIMEOUT_SECONDS,
        )
    except TimeoutError as exc:
        raise HTTPException(504, "The bounded replay timed out.") from exc
    except RuntimeError as exc:
        raise HTTPException(500, "The deterministic replay could not be completed.") from exc
    finally:
        _run_gate.release()
