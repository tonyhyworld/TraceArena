"""Agent 可自行安装的 Skill —— 除 MCP 工具外的第二类能力来源。

一个 skill = 自包含能力包：说明书(instructions) + 可选 Python 依赖 + 可选起始
代码文件。Agent 在 Harness 循环里通过能力发现找到 skill，安装后：
  - python_packages 装进该 agent 的私有沙箱
  - files 写入沙箱工作区（起始代码）
  - instructions 作为工具结果回流上下文，告诉 agent 怎么用
即可在后续步骤中调用。这与 MCP 工具、场景工具并列为通用能力来源。

注册表：backend/skills/<skill_id>/skill.yaml
本模块是通用 Harness 机制，与任何具体场景无关。
"""
from __future__ import annotations

from pathlib import Path
from typing import Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class SkillConfig(BaseModel):
    """单个 skill 声明（skills/<id>/skill.yaml）。"""

    skill_id: str
    name: str
    description: str = ""
    instructions: str = ""
    python_packages: List[str] = Field(default_factory=list)
    # 相对路径 -> 文件内容，安装时写入 agent 沙箱工作区。
    files: Dict[str, str] = Field(default_factory=dict)


class SkillRegistry(BaseModel):
    skills: List[SkillConfig] = Field(default_factory=list)

    def index(self) -> Dict[str, SkillConfig]:
        return {s.skill_id: s for s in self.skills if s.skill_id}


def resolve_skills_dir() -> Path:
    """backend/skills（本文件位于 backend/app/agent_os/skills.py）。"""
    return Path(__file__).resolve().parents[2] / "skills"


def load_skills(skills_dir: str | Path) -> SkillRegistry:
    """扫描 skills 目录，加载每个 <id>/skill.yaml。目录不存在则返回空注册表。"""
    root = Path(skills_dir)
    if not root.is_dir():
        return SkillRegistry()
    skills: List[SkillConfig] = []
    seen: set = set()
    for sub in sorted(root.iterdir()):
        manifest = sub / "skill.yaml"
        if not manifest.is_file():
            continue
        try:
            raw = yaml.safe_load(manifest.read_text(encoding="utf-8")) or {}
            skill = SkillConfig(**raw)
        except Exception:
            continue
        if skill.skill_id in seen:
            continue
        seen.add(skill.skill_id)
        skills.append(skill)
    return SkillRegistry(skills=skills)


_REGISTRY: Optional[SkillRegistry] = None


def get_skill_registry() -> SkillRegistry:
    global _REGISTRY
    if _REGISTRY is None:
        _REGISTRY = load_skills(resolve_skills_dir())
    return _REGISTRY


def set_skill_registry(registry: Optional[SkillRegistry]) -> None:
    global _REGISTRY
    _REGISTRY = registry
