"""Agent 工作区

每个角色在本局拥有独立 workspace：
  runs/<run_id>/agents/<agent_id>/
    ├── charter.md         ← 🔒 不可变：世界宪章 + 角色定位（开局写入，归档审计用）
    ├── memory.md          ← 📝 可累加：本局关键事件记忆
    └── cot/               ← 💬 每 tick 完整思维链
        ├── tick_001_prompt.md
        ├── tick_001_response.txt
        ├── tick_001_decision.json
        └── ...

跨局持久（不在 runs/ 下，所有局共用一份）：
  agents_persistent/<agent_id>/long_term_memory.md
    ← 📜 终局时由 seal_to_long_term() 写入一条"本局总结"。
       下局开局，render_charter() 会把最近若干局的总结拼进 system prompt，
       让 agent 可以"学到上一局的教训"。

设计目标：
  1. 让每个 LLM 角色像独立 agent 存在
  2. 宪章在开局落盘归档；运行时 system prompt 由 PromptAssembler 注入场景 AGENT.md
  3. 全程可追溯：每个决策的 prompt/response/decision 都留底
  4. 调试方便：从文件夹直接看任何 agent 任何 tick 的完整思考链
  5. 跨局学习：long_term_memory 把上一局教训带入新局
"""
from __future__ import annotations

import datetime
import json
import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.core.path_safety import path_beneath, safe_path_component

logger = logging.getLogger(__name__)

# 跨局持久根目录（相对 backend cwd）。所有 agent 的长期记忆都落到这里。
LONG_TERM_ROOT = Path("agents_persistent")
LONG_TERM_RECENT_ENTRIES = 3  # 注入 charter 时最多带几条历史局总结


# 工作区代码文件：仅允许单层 *.py，禁止路径穿越
_CODE_NAME_RE = re.compile(r"^[a-zA-Z0-9][a-zA-Z0-9_.-]*\.py$")


class AgentWorkspace:
    """单个 agent 的工作区。"""

    def __init__(
        self, run_dir: Path, agent_id: str, agent_name: str,
        long_term_root: Path = LONG_TERM_ROOT,
    ):
        self.agent_id = safe_path_component(agent_id, label="agent_id")
        self.agent_name = agent_name
        self.dir = path_beneath(run_dir, "agents", self.agent_id)
        self.cot_dir = self.dir / "cot"
        self.harness_dir = self.dir / "harness"
        self.dir.mkdir(parents=True, exist_ok=True)
        self.cot_dir.mkdir(parents=True, exist_ok=True)
        self.harness_dir.mkdir(parents=True, exist_ok=True)
        (self.dir / "code").mkdir(parents=True, exist_ok=True)
        self._charter_cached: Optional[str] = None
        # 账户体系：每用户一份跨局记忆，默认值保持向后兼容（不传则用全局根目录）
        self._long_term_root = long_term_root

    @property
    def code_dir(self) -> Path:
        """本局可编辑 Python 脚本目录（code/）。"""
        return self.dir / "code"

    # ── Code Workspace（C-PR1）────────────────────────────────────────

    @staticmethod
    def _normalize_code_filename(filename: str) -> str:
        name = str(filename or "").strip().replace("\\", "/").lstrip("/")
        if not name or "/" in name or ".." in name:
            raise ValueError(f"非法代码路径: {filename}")
        if not name.endswith(".py"):
            if "." in name:
                raise ValueError(f"仅支持 .py 文件: {filename}")
            name = f"{name}.py"
        if not _CODE_NAME_RE.match(name):
            raise ValueError(f"非法代码文件名: {filename}")
        return name

    def list_code_files(self) -> List[str]:
        if not self.code_dir.is_dir():
            return []
        return sorted(p.name for p in self.code_dir.glob("*.py") if p.is_file())

    def write_code_file(
        self,
        filename: str,
        content: str,
        *,
        max_bytes: int = 32768,
        max_files: int = 20,
    ) -> str:
        """写入或覆盖 code/ 下的脚本，返回规范化文件名。"""
        name = self._normalize_code_filename(filename)
        data = (content or "").encode("utf-8")
        if len(data) > max_bytes:
            raise ValueError(f"代码文件超过大小限制 {max_bytes} 字节")
        path = path_beneath(self.code_dir, name)
        if not path.is_file():
            existing = self.list_code_files()
            if len(existing) >= max_files:
                raise ValueError(f"代码文件数量已达上限 {max_files}")
        path.write_text(content or "", encoding="utf-8")
        return name

    def read_code_file(self, filename: str) -> str:
        name = self._normalize_code_filename(filename)
        path = path_beneath(self.code_dir, name)
        if not path.is_file():
            raise FileNotFoundError(name)
        return path.read_text(encoding="utf-8")

    def delete_code_file(self, filename: str) -> None:
        name = self._normalize_code_filename(filename)
        path = path_beneath(self.code_dir, name)
        if path.is_file():
            path.unlink()

    def workspace_summary(self) -> Dict[str, Any]:
        files = self.list_code_files()
        return {
            "root": "code/",
            "files": files,
            "hint": "可用 workspace_write 写入、workspace_run 试跑 .py 脚本",
        }

    # ── Charter ────────────────────────────────────────────────────────

    def write_charter(self, content: str) -> None:
        """开局写一次宪章；之后只读不改。"""
        path = self.dir / "charter.md"
        path.write_text(content, encoding="utf-8")
        self._charter_cached = content

    def read_charter(self) -> str:
        if self._charter_cached is not None:
            return self._charter_cached
        path = self.dir / "charter.md"
        if path.is_file():
            self._charter_cached = path.read_text(encoding="utf-8")
            return self._charter_cached
        return ""

    # ── Memory ─────────────────────────────────────────────────────────

    def append_memory(self, tick: int, event_summary: str) -> None:
        """OS 自动追加场景声明的关键事件到角色记忆。"""
        path = self.dir / "memory.md"
        header_needed = not path.is_file()
        with path.open("a", encoding="utf-8") as f:
            if header_needed:
                f.write(f"# {self.agent_name} 本局记忆\n\n")
            f.write(f"- **Tick {tick}**：{event_summary}\n")

    def read_memory(self) -> str:
        path = self.dir / "memory.md"
        return path.read_text(encoding="utf-8") if path.is_file() else ""

    # ── Long-term Memory（跨局持久） ─────────────────────────────────────

    @property
    def long_term_path(self) -> Path:
        return path_beneath(
            self._long_term_root, self.agent_id, "long_term_memory.md"
        )

    def read_long_term(self) -> str:
        """读取本 agent 在所有过往局的总结记忆。新 agent 返回空串。"""
        p = self.long_term_path
        return p.read_text(encoding="utf-8") if p.is_file() else ""

    def read_recent_long_term(
        self, n: int = LONG_TERM_RECENT_ENTRIES
    ) -> str:
        """读取最近 n 局的总结，用于注入 charter system prompt。"""
        text = self.read_long_term()
        if not text:
            return ""
        # 按 "## 局 " 分块（与 seal_to_long_term 写入的 header 对齐）
        blocks = [b for b in text.split("\n## 局 ") if b.strip()]
        # 第一个块通常是文件总 header，先剥掉；从倒数 n 个取
        if blocks and not blocks[0].startswith("局 ") and "局 " not in blocks[0][:30]:
            blocks = blocks[1:]
        if not blocks:
            return ""
        tail = blocks[-n:]
        # 恢复 "## 局 " 前缀（第一个除外可能保留 file header）
        return "\n## 局 ".join(["## 局 " + b for b in tail])

    def seal_to_long_term(
        self,
        *,
        run_id: str,
        victory_rank: Optional[int] = None,
        final_metrics: Optional[Dict[str, float]] = None,
        outcome_note: str = "",
    ) -> None:
        """终局时把本局 memory 提炼成一条总结写入 long_term_memory。

        失败不抛——长期记忆失败不应影响主流程结束。
        """
        try:
            mem = self.read_memory().strip()
            if not mem:
                return
            ts = datetime.datetime.now().strftime("%Y-%m-%d %H:%M")
            p = self.long_term_path
            p.parent.mkdir(parents=True, exist_ok=True)
            header_needed = not p.is_file()
            with p.open("a", encoding="utf-8") as f:
                if header_needed:
                    f.write(f"# {self.agent_name} 跨局长期记忆\n\n")
                f.write(f"\n## 局 {run_id}（{ts}）\n")
                if victory_rank is not None:
                    f.write(f"- 最终名次：第 {victory_rank} 位\n")
                if final_metrics:
                    parts = ", ".join(
                        f"{k}={round(float(v),1)}"
                        for k, v in final_metrics.items()
                        if isinstance(v, (int, float))
                    )
                    f.write(f"- 终局指标：{parts}\n")
                if outcome_note:
                    f.write(f"- 总结：{outcome_note}\n")
                # 截取本局 memory 头部若干条作为关键事件回顾
                lines = [l for l in mem.splitlines() if l.startswith("- ")]
                if lines:
                    f.write("- 关键事件（本局摘要）：\n")
                    for ln in lines[: 8]:
                        f.write(f"  {ln}\n")
        except Exception as exc:
            logger.warning(
                f"[AgentWorkspace] long_term_memory 写入失败 {self.agent_id}: {exc}"
            )

    # ── CoT 落盘 ────────────────────────────────────────────────────────

    def save_cot(
        self,
        tick: int,
        *,
        system_prompt: str,
        user_message: str,
        raw_response: str,
        decision: Optional[Dict[str, Any]] = None,
    ) -> None:
        """每个 LLM 调用后，把 prompt/response/decision 三件套落盘。

        失败不抛——不能因为日志失败拖垮主循环。
        """
        try:
            stem = f"tick_{tick:03d}"
            (self.cot_dir / f"{stem}_prompt.md").write_text(
                f"# Tick {tick} · {self.agent_name} · 注入的 Prompt\n\n"
                f"## System Prompt\n\n```\n{system_prompt}\n```\n\n"
                f"## User Message\n\n```\n{user_message}\n```\n",
                encoding="utf-8",
            )
            (self.cot_dir / f"{stem}_response.txt").write_text(
                raw_response or "(空响应)",
                encoding="utf-8",
            )
            if decision is not None:
                (self.cot_dir / f"{stem}_decision.json").write_text(
                    json.dumps(decision, ensure_ascii=False, indent=2, default=str),
                    encoding="utf-8",
                )
        except Exception as exc:
            logger.warning(f"[AgentWorkspace] CoT 落盘失败 {self.agent_id} tick={tick}: {exc}")

    def save_harness_trace(self, tick: int, trace: Any) -> Path:
        """Persist the versioned HarnessTrace in this agent's own workspace."""
        if hasattr(trace, "model_dump"):
            payload = trace.model_dump(mode="json")
        elif isinstance(trace, dict):
            payload = dict(trace)
        else:
            raise TypeError("trace must be a HarnessTrace or dict")
        path = self.harness_dir / f"tick_{tick:03d}.json"
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, default=str),
            encoding="utf-8",
        )
        return path


# ── Charter 渲染 ───────────────────────────────────────────────────────


def render_charter(
    template_text: str,
    *,
    agent_id: str,
    agent_name: str,
    hidden_goal: str,
    other_agents: List[str],
    scenario_name: str,
    scenario_version: str,
    tick_limit: int,
    locations_count: int,
    objects_count: int,
    long_term_excerpt: str = "",
) -> str:
    """把 charter_template.md 里的 {placeholder} 填实。

    long_term_excerpt：跨局长期记忆摘录。如果不为空，渲染完模板后会在末尾
    追加一段"过往对局"，让 agent 带着前几局的教训进新局。
    """
    rendered = template_text.format(
        agent_id=agent_id,
        agent_name=agent_name,
        hidden_goal=hidden_goal or "遵守当前世界规则，利用可验证信息推进角色目标。",
        other_agents="、".join(other_agents) if other_agents else "（无对手）",
        scenario_name=scenario_name,
        scenario_version=scenario_version,
        tick_limit=tick_limit,
        locations_count=locations_count,
        objects_count=objects_count,
    )
    if long_term_excerpt.strip():
        rendered = (
            rendered.rstrip()
            + "\n\n## 过往对局（你之前的几局）\n\n"
            + long_term_excerpt.strip()
            + "\n\n（这些是你过往局的经历与教训。本局是新的局，"
            "对手与开局可能不同，请把过往经验用在判断上。）\n"
        )
    return rendered


class AgentWorkspaceRegistry:
    """所有 agent workspace 的注册中心；EngineOS 持一个。"""

    def __init__(self):
        self._workspaces: Dict[str, AgentWorkspace] = {}

    def register(self, ws: AgentWorkspace) -> None:
        self._workspaces[ws.agent_id] = ws

    def get(self, agent_id: str) -> Optional[AgentWorkspace]:
        return self._workspaces.get(agent_id)

    def get_charter(self, agent_id: str) -> str:
        ws = self.get(agent_id)
        return ws.read_charter() if ws else ""

    def all(self) -> List[AgentWorkspace]:
        return list(self._workspaces.values())
