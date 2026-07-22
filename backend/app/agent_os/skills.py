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
import time
from typing import Any, Dict, List, Optional

import yaml
from pydantic import BaseModel, Field


class SkillConfig(BaseModel):
    """单个 skill 声明（skills/<id>/skill.yaml）。"""

    skill_id: str
    name: str
    description: str = ""
    instructions: str = ""
    # Engineering metadata is intentionally part of the runtime manifest rather
    # than only a competition document.  A caller can inspect the contract
    # before installation and an audit record can bind a run to a Skill version.
    version: str = "0.1.0"
    skill_type: str = "custom"
    input_schema: Dict[str, Any] = Field(default_factory=dict)
    output_schema: Dict[str, Any] = Field(default_factory=dict)
    invocation_conditions: List[str] = Field(default_factory=list)
    dependencies: List[str] = Field(default_factory=list)
    failure_handling: List[str] = Field(default_factory=list)
    permissions: List[str] = Field(default_factory=list)
    safety_boundary: str = ""
    evaluation: List[str] = Field(default_factory=list)
    release_policy: str = ""
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


class SkillExecutionReceipt(BaseModel):
    """Structured receipt produced by an executable Skill invocation."""

    receipt_id: str
    skill_id: str
    status: str
    output: Dict[str, Any] = Field(default_factory=dict)
    errors: List[str] = Field(default_factory=list)
    evidence_refs: List[str] = Field(default_factory=list)
    started_at: float = Field(default_factory=time.time)
    completed_at: float = Field(default_factory=time.time)


def execute_skill(
    skill_id: str,
    payload: Dict[str, Any],
    *,
    registry: Optional[SkillRegistry] = None,
) -> SkillExecutionReceipt:
    """Execute a first-party deterministic Skill adapter.

    Skills remain pluggable capability packages.  This helper provides a local
    executable path for GOAI/demo scenarios so a Skill is not merely a manifest.
    External Skills can still be installed into the agent sandbox through the
    existing registry mechanism.
    """
    started_at = time.time()
    reg = registry or get_skill_registry()
    if skill_id not in reg.index():
        return SkillExecutionReceipt(
            receipt_id=f"skill:{skill_id}:{int(started_at * 1000)}",
            skill_id=skill_id,
            status="error",
            errors=["unknown_skill"],
            started_at=started_at,
            completed_at=time.time(),
        )
    try:
        output = _execute_builtin_skill(skill_id, dict(payload or {}))
        status = str(output.get("status") or "ok")
        evidence_refs = [
            str(item)
            for item in output.get("evidence_refs", []) or []
            if str(item).strip()
        ]
        return SkillExecutionReceipt(
            receipt_id=f"skill:{skill_id}:{int(started_at * 1000)}",
            skill_id=skill_id,
            status=status,
            output=output,
            evidence_refs=evidence_refs,
            started_at=started_at,
            completed_at=time.time(),
        )
    except Exception as exc:
        return SkillExecutionReceipt(
            receipt_id=f"skill:{skill_id}:{int(started_at * 1000)}",
            skill_id=skill_id,
            status="error",
            errors=[str(exc)],
            started_at=started_at,
            completed_at=time.time(),
        )


def _execute_builtin_skill(skill_id: str, payload: Dict[str, Any]) -> Dict[str, Any]:
    if skill_id == "grid_observation_assessment":
        metrics = dict(payload.get("metrics") or {})
        max_rho = float(metrics.get("max_rho", 0.0) or 0.0)
        disconnected = int(metrics.get("disconnected_lines", 0) or 0)
        severity = "critical" if max_rho >= 1.0 else "warning" if disconnected else "stable"
        return {
            "status": "ready",
            "severity": severity,
            "risk_factors": [
                item for item in [
                    "thermal_overload" if max_rho >= 1.0 else "",
                    "line_outage" if disconnected else "",
                ] if item
            ],
            "recommended_next_action": (
                "maintain_safe_isolation"
                if severity == "critical"
                else "restore_fault_line"
                if disconnected
                else "deploy_reserve_redispatch"
            ),
            "evidence_refs": list(payload.get("evidence_refs") or []),
        }
    if skill_id == "grid_restoration_plan":
        assessment = dict(payload.get("assessment") or {})
        action = str(
            payload.get("preferred_action")
            or assessment.get("recommended_next_action")
            or "maintain_safe_isolation"
        )
        risk_level = "high" if action == "restore_fault_line" else "medium" if action == "deploy_reserve_redispatch" else "low"
        return {
            "status": "needs_approval" if risk_level == "high" else "ready",
            "change_steps": [action],
            "risk_level": risk_level,
            "rollback_ref": payload.get("snapshot_ref") or "snapshot:current",
            "approval_requirement": "human_or_policy_approval" if risk_level == "high" else "none",
            "evidence_refs": list(payload.get("evidence_refs") or []),
        }
    if skill_id == "grid_safety_validation":
        plan = dict(payload.get("plan") or {})
        risk_level = str(plan.get("risk_level") or "low")
        evidence_refs = list(payload.get("evidence_refs") or plan.get("evidence_refs") or [])
        missing = []
        if not evidence_refs:
            missing.append("evidence_refs")
        if risk_level in {"high", "critical"} and not payload.get("approval_id"):
            return {
                "status": "needs_approval",
                "failed_checks": missing,
                "metric_deltas": dict(payload.get("metric_deltas") or {}),
                "rollback_recommendation": "hold_action_until_approved",
                "evidence_refs": evidence_refs,
            }
        return {
            "status": "pass" if not missing else "fail",
            "failed_checks": missing,
            "metric_deltas": dict(payload.get("metric_deltas") or {}),
            "rollback_recommendation": "rollback_on_overload_or_terminal_failure",
            "evidence_refs": evidence_refs,
        }
    if skill_id == "grid_evidence_audit":
        evidence_refs = list(payload.get("evidence_refs") or [])
        approval_history = list(payload.get("approval_history") or [])
        high_risk = bool(payload.get("high_risk"))
        if high_risk and not approval_history:
            return {
                "status": "needs_more_evidence",
                "audit_findings": ["high_risk_action_without_approval_history"],
                "missing_evidence": ["approval_history"],
                "decision": "rejected",
                "evidence_refs": evidence_refs,
            }
        return {
            "status": "approved",
            "audit_findings": ["evidence_chain_present"],
            "missing_evidence": [],
            "decision": "approved",
            "evidence_refs": evidence_refs,
        }
    return {
        "status": "ready",
        "evidence_refs": list(payload.get("evidence_refs") or []),
    }
