"""轻量级 Autonomous Scheduler。

它只负责可靠地触发目标任务，不把具体领域逻辑写进 OS。调用方注册一个
异步 handler（通常由宿主把 goal 注入场景并启动 EngineOS），任务状态和下次
执行时间落盘，进程重启后仍能恢复启用任务。
"""
from __future__ import annotations

import asyncio
import datetime as dt
import json
import logging
import uuid
from pathlib import Path
from typing import Any, Awaitable, Callable, Dict, Optional

logger = logging.getLogger(__name__)
TaskHandler = Callable[[Dict[str, Any]], Awaitable[Optional[Dict[str, Any]]]]


class AutonomousScheduler:
    def __init__(self, path: str | Path, handler: Optional[TaskHandler] = None, poll_sec: float = 1.0):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)
        self.handler = handler
        self.poll_sec = max(0.2, float(poll_sec))
        self.tasks: Dict[str, Dict[str, Any]] = self._load()
        self._runner: Optional[asyncio.Task] = None
        self._lock = asyncio.Lock()

    def _load(self) -> Dict[str, Dict[str, Any]]:
        if not self.path.is_file():
            return {}
        try:
            payload = json.loads(self.path.read_text(encoding="utf-8"))
            return dict(payload.get("tasks", payload) or {})
        except Exception:
            return {}

    def _save(self) -> None:
        tmp = self.path.with_suffix(".tmp")
        tmp.write_text(json.dumps({"tasks": self.tasks}, ensure_ascii=False, indent=2, default=str), encoding="utf-8")
        tmp.replace(self.path)

    async def create(self, *, user_id: str, goal: str, interval_sec: float = 3600, scenario_id: str = "", metadata: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
        if not str(goal or "").strip():
            raise ValueError("goal_empty")
        now = dt.datetime.now(dt.timezone.utc)
        item = {"task_id": f"task_{uuid.uuid4().hex[:12]}", "user_id": user_id, "goal": str(goal).strip()[:20_000], "scenario_id": scenario_id, "interval_sec": max(10.0, min(31_536_000.0, float(interval_sec))), "enabled": True, "created_at": now.isoformat(), "next_run_at": now.isoformat(), "last_run_at": None, "last_result": None, "last_error": None, "metadata": dict(metadata or {})}
        async with self._lock:
            self.tasks[item["task_id"]] = item
            self._save()
        return item

    async def cancel(self, task_id: str, user_id: str, *, delete: bool = False) -> bool:
        async with self._lock:
            item = self.tasks.get(task_id)
            if not item or item.get("user_id") != user_id:
                return False
            if delete:
                self.tasks.pop(task_id, None)
            else:
                item["enabled"] = False
            self._save()
        return True

    def list(self, user_id: str) -> list[Dict[str, Any]]:
        return [dict(item) for item in self.tasks.values() if item.get("user_id") == user_id]

    async def run_once(self, item: Dict[str, Any]) -> None:
        if self.handler is None:
            item["last_error"] = "scheduler_handler_not_configured"
            return
        try:
            result = await self.handler(dict(item))
            item["last_result"] = result or {"status": "completed"}
            item["last_error"] = None
        except Exception as exc:
            logger.exception("autonomous task failed: %s", item.get("task_id"))
            item["last_error"] = str(exc)
        item["last_run_at"] = dt.datetime.now(dt.timezone.utc).isoformat()
        item["next_run_at"] = (dt.datetime.now(dt.timezone.utc) + dt.timedelta(seconds=float(item["interval_sec"]))).isoformat()
        self._save()

    async def _loop(self) -> None:
        while True:
            now = dt.datetime.now(dt.timezone.utc)
            changed = False
            for item in list(self.tasks.values()):
                if not item.get("enabled"):
                    continue
                try:
                    due = dt.datetime.fromisoformat(str(item.get("next_run_at")).replace("Z", "+00:00")) <= now
                except Exception:
                    due = True
                if due:
                    await self.run_once(item)
                    changed = True
            if changed:
                async with self._lock:
                    self._save()
            await asyncio.sleep(self.poll_sec)

    def start(self) -> None:
        if self._runner is None or self._runner.done():
            self._runner = asyncio.create_task(self._loop())

    async def stop(self) -> None:
        if self._runner is not None:
            self._runner.cancel()
            try:
                await self._runner
            except asyncio.CancelledError:
                pass
            self._runner = None
