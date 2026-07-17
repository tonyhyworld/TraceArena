"""
挑战内容加载器（P1-6 配套底座）

把场景包里的「挑战内容 YAML」加载成两份彻底分离的数据：
  - 下发面：ChallengeVariant.materials / instruction / output_schema —— 会进入 Probe，下发给模型。
  - 隐藏面：ground_truth + validator_id —— 只存入隐藏答案库，按 ground_truth_ref 供验证器取用，
    绝不进入下发给模型的 Probe。

ground_truth_ref 形如 "<node_id>:<probe_key>:<variant_id>"，按变体稳定；同一变体被多个
角色作答时共用同一隐藏答案（只读）。

加载器只识别能力任务结构；具体材料与任务主题全部来自场景包。
"""
from __future__ import annotations

import uuid
from pathlib import Path
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import yaml

from app.framework.capability.assessment import CapabilityProbe
from app.framework.capability.general_capabilities import (
    CapabilityAxis,
    VerificationTier,
    is_general_capability,
)

# 下发材料中禁止出现的答案键（与 ProbeExecutor 的防泄漏一致）
_BANNED_MATERIAL_KEYS = {"ground_truth", "answer_key", "expected", "checks", "rubric"}


class ChallengeContentError(Exception):
    """挑战内容结构非法（缺字段/答案泄漏/未知能力等）。"""


@dataclass(frozen=True)
class ChallengeVariant:
    node_id: str
    probe_key: str
    variant_id: str
    capability: str
    instruction: str
    materials: Dict[str, Any]
    output_schema: Dict[str, Any]
    available_tool_ids: List[str]
    expected_tier: VerificationTier
    axis: CapabilityAxis
    weight: float
    validator_id: str
    ground_truth: Dict[str, Any]   # 隐藏，不下发
    world_effects: Dict[str, List[Dict[str, Any]]] = field(default_factory=dict)

    @property
    def ground_truth_ref(self) -> str:
        return f"{self.node_id}:{self.probe_key}:{self.variant_id}"


class ChallengeLibrary:
    """挑战内容库：装载节点内容，产出 Probe 与隐藏答案。"""

    def __init__(self) -> None:
        self._variants: Dict[str, ChallengeVariant] = {}   # ref -> variant
        self._node_index: Dict[str, List[str]] = {}        # node_id -> [ref]
        self._node_meta: Dict[str, Dict[str, Any]] = {}
        self._alias_index: Dict[str, List[str]] = {}

    # ── 装载 ─────────────────────────────────────────────────────────────

    @classmethod
    def from_yaml(cls, path: str) -> "ChallengeLibrary":
        with open(path, "r", encoding="utf-8") as f:
            data = yaml.safe_load(f) or {}
        lib = cls()
        lib.load_node(data)
        base_dir = Path(path).resolve().parent
        for ref, variant in list(lib._variants.items()):
            image_paths = list(variant.materials.get("image_paths", []) or [])
            if not image_paths:
                continue
            normalized = [
                str((base_dir / item).resolve()) if not Path(item).is_absolute()
                else str(Path(item))
                for item in image_paths
            ]
            materials = dict(variant.materials)
            materials["image_paths"] = normalized
            lib._variants[ref] = ChallengeVariant(
                **{
                    **variant.__dict__,
                    "materials": materials,
                }
            )
        return lib

    def load_node(self, data: Dict[str, Any]) -> None:
        node_id = data.get("node_id")
        if not node_id:
            raise ChallengeContentError("节点缺少 node_id")
        if data.get("split_probes_into_nodes"):
            alias_refs: List[str] = []
            for probe in data.get("probes", []):
                challenge = dict(probe.get("challenge", {}) or {})
                child_id = str(
                    challenge.get("id")
                    or f"{node_id}_{probe.get('probe_key', 'probe')}"
                )
                self._node_meta[child_id] = {
                    "fire_tick": int(
                        challenge.get(
                            "fire_tick", data.get("fire_tick", 0)
                        ) or 0
                    ),
                    "trigger": dict(
                        challenge.get(
                            "trigger", data.get("trigger", {})
                        ) or {}
                    ),
                    "title": str(
                        challenge.get(
                            "title", probe.get("probe_key", child_id)
                        )
                    ),
                    "challenge_order": int(
                        challenge.get("order", len(self._node_meta) + 1)
                    ),
                }
                before = set(self._variants)
                self._load_probe(child_id, probe)
                alias_refs.extend(
                    ref for ref in self._variants if ref not in before
                )
            self._alias_index[node_id] = alias_refs
            return
        self._node_meta[node_id] = {
            "fire_tick": int(data.get("fire_tick", 0) or 0),
            "trigger": dict(data.get("trigger", {}) or {}),
            "title": str(data.get("title", node_id)),
        }
        for probe in data.get("probes", []):
            self._load_probe(node_id, probe)

    def _load_probe(self, node_id: str, probe: Dict[str, Any]) -> None:
        probe_key = probe.get("probe_key")
        capability = probe.get("capability")
        if not probe_key or not capability:
            raise ChallengeContentError(f"{node_id} 的 probe 缺 probe_key/capability")
        if not is_general_capability(capability):
            raise ChallengeContentError(f"{node_id}:{probe_key} 未知能力 {capability}")

        tier = VerificationTier(probe.get("expected_tier", "deterministic"))
        axis = CapabilityAxis(probe.get("axis", "neutral"))
        tools = list(probe.get("available_tool_ids", []))
        weight_default = float(probe.get("weight", 1.0))
        validator_default = probe.get("validator_id", "det.spec")
        effects_default = dict(probe.get("world_effects", {}) or {})

        variants = probe.get("variants", [])
        if not variants:
            raise ChallengeContentError(f"{node_id}:{probe_key} 无 variants")

        for v in variants:
            vid = v.get("variant_id")
            if not vid:
                raise ChallengeContentError(f"{node_id}:{probe_key} 变体缺 variant_id")
            materials = dict(v.get("materials", {}))
            leaked = _BANNED_MATERIAL_KEYS & set(materials.keys())
            if leaked:
                raise ChallengeContentError(
                    f"{node_id}:{probe_key}:{vid} 材料含答案键 {sorted(leaked)}，禁止下发。"
                )
            gt = dict(v.get("ground_truth", {}))
            if not gt:
                raise ChallengeContentError(
                    f"{node_id}:{probe_key}:{vid} 缺 ground_truth，无法验证。"
                )
            variant = ChallengeVariant(
                node_id=node_id, probe_key=probe_key, variant_id=vid,
                capability=capability,
                instruction=str(v.get("instruction", probe.get("instruction", ""))),
                materials=materials,
                output_schema=dict(v.get("output_schema", probe.get("output_schema", {}))),
                available_tool_ids=list(v.get("available_tool_ids", tools)),
                expected_tier=tier, axis=axis,
                weight=float(v.get("weight", weight_default)),
                validator_id=str(v.get("validator_id", validator_default)),
                ground_truth=gt,
                world_effects=dict(v.get("world_effects", effects_default) or {}),
            )
            self._variants[variant.ground_truth_ref] = variant
            self._node_index.setdefault(node_id, []).append(variant.ground_truth_ref)

    # ── 查询 ─────────────────────────────────────────────────────────────

    def variants_for(self, node_id: str, capability: Optional[str] = None) -> List[ChallengeVariant]:
        refs = self._node_index.get(
            node_id, self._alias_index.get(node_id, [])
        )
        out = [self._variants[r] for r in refs]
        if capability:
            out = [v for v in out if v.capability == capability]
        return out

    def get_variant(self, ref: str) -> Optional[ChallengeVariant]:
        return self._variants.get(ref)

    def resolve_ground_truth(self, ref: str) -> Dict[str, Any]:
        v = self._variants.get(ref)
        if v is None:
            raise ChallengeContentError(f"未知 ground_truth_ref: {ref}")
        return dict(v.ground_truth)

    def validator_id_for(self, ref: str) -> str:
        v = self._variants.get(ref)
        if v is None:
            raise ChallengeContentError(f"未知 ground_truth_ref: {ref}")
        return v.validator_id

    def node_meta(self, node_id: str) -> Dict[str, Any]:
        return dict(self._node_meta.get(node_id, {}))

    # ── 产出 Probe（隐藏答案只留引用）──────────────────────────────────────

    def build_probe(
        self, variant: ChallengeVariant, *, tick: int, agent_id: str,
        probe_id: Optional[str] = None,
    ) -> CapabilityProbe:
        return CapabilityProbe(
            probe_id=probe_id or f"pb_{uuid.uuid4().hex[:10]}",
            tick=tick,
            agent_id=agent_id,
            capability=variant.capability,
            node_id=variant.node_id,
            variant_id=variant.variant_id,
            axis=variant.axis,
            expected_tier=variant.expected_tier,
            instruction=variant.instruction,
            materials=variant.materials,          # 已保证不含答案键
            output_schema=variant.output_schema,
            available_tool_ids=variant.available_tool_ids,
            ground_truth_ref=variant.ground_truth_ref,   # 仅引用，无明文
        )


__all__ = ["ChallengeLibrary", "ChallengeVariant", "ChallengeContentError"]
