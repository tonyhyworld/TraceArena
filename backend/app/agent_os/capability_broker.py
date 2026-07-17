"""Runtime capability discovery for Agent Harness.

The broker does not decide which tool an agent should use. It searches the
capabilities currently available to this AI World process, including tools
declared by the scenario and tools discovered live from connected MCP servers.
"""
from __future__ import annotations

import asyncio
import re
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field


class CapabilityCandidate(BaseModel):
    model_config = ConfigDict(extra="forbid")

    capability_id: str
    kind: Literal["scenario_tool", "mcp_tool", "python_package", "skill"]
    name: str
    description: str = ""
    source: str
    invocation: Dict[str, Any] = Field(default_factory=dict)
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    score: float = Field(default=0.0, ge=0.0, le=1.0)


class CapabilityBroker:
    """Search live capability sources without injecting their full catalog."""

    def __init__(
        self,
        scene_tools: Optional[List[Dict[str, Any]]] = None,
        mcp_manager: Any = None,
        skill_registry: Any = None,
    ):
        self._scene_tools = list(scene_tools or [])
        self._mcp_manager = mcp_manager
        self._skill_registry = skill_registry

    async def discover(
        self,
        query: str,
        *,
        max_results: int = 12,
        preferred_tools: Optional[List[str]] = None,
    ) -> List[CapabilityCandidate]:
        query = str(query or "").strip()
        preferred = [
            str(item).strip().lower()
            for item in (preferred_tools or [])
            if str(item).strip()
        ]
        candidates = self._scene_candidates(query)
        candidates.extend(self._skill_candidates(query))
        candidates.extend(await self._mcp_candidates(query))
        # Semantic matching is intentionally lightweight; a Chinese goal may
        # share no literal token with an English capability id. Returning the
        # scoped catalog is safer than falsely claiming that no capability
        # exists, and it still exposes only tools authorized for this scene.
        if query and not candidates:
            candidates = self._scene_candidates("")
            candidates.extend(self._skill_candidates(""))
            candidates.extend(await self._mcp_candidates(""))
        # preferred 工具即使当前 query 分=0 也要入池，否则行情工具会被
        # filings 类查询完全滤掉（真实发生过：整局发现不到 longport_quote）。
        if preferred:
            extras = self._scene_candidates("")
            extras.extend(self._skill_candidates(""))
            extras.extend(await self._mcp_candidates(""))
            for item in extras:
                hay = f"{item.capability_id} {item.name}".lower()
                if any(token in hay for token in preferred):
                    candidates.append(item)

        deduped: Dict[str, CapabilityCandidate] = {}
        for candidate in candidates:
            current = deduped.get(candidate.capability_id)
            if current is None or candidate.score > current.score:
                deduped[candidate.capability_id] = candidate
        # 场景声明的优选工具（如 longport_quote）提权，避免被 filings/skill 盖住。
        if preferred:
            boosted: List[CapabilityCandidate] = []
            for candidate in deduped.values():
                hay = f"{candidate.capability_id} {candidate.name}".lower()
                if any(token in hay for token in preferred):
                    boosted.append(candidate.model_copy(update={
                        "score": max(float(candidate.score), 0.99),
                    }))
                else:
                    boosted.append(candidate)
            deduped = {item.capability_id: item for item in boosted}
        ranked = sorted(
            deduped.values(),
            key=lambda item: (-item.score, item.name.lower()),
        )
        # 优选工具强制入选（即使当前查询分低），再按 limit 裁剪。
        pinned: List[CapabilityCandidate] = []
        if preferred:
            for candidate in ranked:
                hay = f"{candidate.capability_id} {candidate.name}".lower()
                if any(token in hay for token in preferred):
                    pinned.append(candidate)
        limit = max(1, int(max_results))
        selected = list(pinned[:limit])
        for candidate in ranked:
            if len(selected) >= limit:
                break
            if candidate.capability_id in {item.capability_id for item in selected}:
                continue
            selected.append(candidate)
        # 类别保底：每个存在候选的 kind 至少入选一个。否则查询措辞的
        # 偶然性会让某个 agent 只看到 skill、另一个只看到 MCP 工具，
        # 能力路线被运气锁死（真实发生过：一个 agent 全场只发现了
        # 未安装的 skill，从未得知 MCP 行情工具的存在）。
        selected_kinds = {item.kind for item in selected}
        for kind in ("mcp_tool", "scenario_tool", "skill", "python_package"):
            if kind in selected_kinds:
                continue
            best = next((item for item in ranked if item.kind == kind), None)
            if best is None:
                continue
            if len(selected) < limit:
                selected.append(best)
            else:
                # 从尾部找一个"同类冗余"(其 kind 已有≥2席)的席位让出来；
                # 不挤掉 preferred/pinned 行情工具。
                for index in range(len(selected) - 1, -1, -1):
                    victim = selected[index]
                    victim_kind = victim.kind
                    victim_hay = f"{victim.capability_id} {victim.name}".lower()
                    if preferred and any(token in victim_hay for token in preferred):
                        continue
                    if sum(1 for item in selected if item.kind == victim_kind) >= 2:
                        selected[index] = best
                        break
            selected_kinds.add(kind)
        # preferred 置顶：最终排序时给 preferred 稳定最高优先级。
        def _sort_key(item: CapabilityCandidate) -> tuple:
            hay = f"{item.capability_id} {item.name}".lower()
            preferred_rank = 0
            if preferred:
                preferred_rank = 0 if any(token in hay for token in preferred) else 1
            return (preferred_rank, -item.score, item.name.lower())

        return sorted(selected, key=_sort_key)

    def _scene_candidates(self, query: str) -> List[CapabilityCandidate]:
        out: List[CapabilityCandidate] = []
        for item in self._scene_tools:
            if not isinstance(item, dict):
                continue
            tool_id = str(item.get("tool_id") or item.get("id") or "").strip()
            if not tool_id:
                continue
            name = str(item.get("name") or tool_id)
            description = str(item.get("description") or item.get("purpose") or "")
            score = self._match_score(query, f"{tool_id} {name} {description}")
            if query and score <= 0:
                continue
            out.append(CapabilityCandidate(
                capability_id=tool_id,
                kind="scenario_tool",
                name=name,
                description=description,
                source="scenario",
                invocation={"tool_id": tool_id},
                input_schema=dict(item.get("input_schema") or {}),
                score=score if query else 0.5,
            ))
        return out

    def _skill_candidates(self, query: str) -> List[CapabilityCandidate]:
        registry = self._skill_registry
        if registry is None:
            from app.agent_os.skills import get_skill_registry

            registry = get_skill_registry()
        out: List[CapabilityCandidate] = []
        for skill in getattr(registry, "skills", []) or []:
            score = self._match_score(
                query, f"{skill.skill_id} {skill.name} {skill.description}"
            )
            if query and score <= 0:
                continue
            out.append(CapabilityCandidate(
                capability_id=f"skill:{skill.skill_id}",
                kind="skill",
                name=skill.name,
                description=skill.description,
                source="skill",
                invocation={"skill_id": skill.skill_id, "operation": "install_skill"},
                score=score if query else 0.5,
            ))
        return out

    async def _mcp_candidates(self, query: str) -> List[CapabilityCandidate]:
        manager = self._mcp_manager
        if manager is None:
            from app.mcp.client import get_mcp_manager

            manager = get_mcp_manager()
        if manager is None or not getattr(manager, "enabled", False):
            return []

        server_ids = list(getattr(manager, "server_ids", []) or [])
        if not server_ids:
            return []
        listed = await asyncio.gather(
            *(manager.list_tools(server_id) for server_id in server_ids),
            return_exceptions=True,
        )
        out: List[CapabilityCandidate] = []
        for server_id, result in zip(server_ids, listed):
            if isinstance(result, Exception):
                continue
            for tool in result or []:
                name = str(getattr(tool, "name", "") or "").strip()
                if not name:
                    continue
                description = str(getattr(tool, "description", "") or "")
                score = self._match_score(query, f"{server_id} {name} {description}")
                if query and score <= 0:
                    continue
                out.append(CapabilityCandidate(
                    capability_id=f"mcp:{server_id}:{name}",
                    kind="mcp_tool",
                    name=name,
                    description=description,
                    source=f"mcp:{server_id}",
                    invocation={
                        "tool_id": f"mcp:{server_id}:{name}",
                        "mcp_server": server_id,
                        "mcp_tool": name,
                    },
                    input_schema=dict(getattr(tool, "input_schema", {}) or {}),
                    score=score if query else 0.5,
                ))
        return out

    @staticmethod
    def _match_score(query: str, text: str) -> float:
        if not query:
            return 0.5
        query_lower = query.lower()
        text_lower = text.lower()
        if query_lower in text_lower:
            return 1.0
        tokens = {
            token for token in re.split(r"[^\w\u4e00-\u9fff]+", query_lower)
            if token
        }
        if not tokens:
            return 0.0
        matched = sum(1 for token in tokens if token in text_lower)
        return min(1.0, matched / len(tokens))
