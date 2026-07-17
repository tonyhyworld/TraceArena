"""
剧情节点协调器（P1-8）

把能力组件串成完整链路：任务节点触发 → 给所有角色下发等价探针（防串题）
→ 专用子回合作答 → 验证 → 对抗归因 → 原子提交（世界事件 + 不可变案例）。

触发方式：fire_tick 到达时，对全体在场角色一次性发放探针。
归因纪律：被投毒且未识破 → 作废重测，绝不算在被测者头上；识破 → 守方记功、测量有效。

本协调器对引擎主循环只暴露一个 async 入口 run(...)，可用假 provider 完全独立测试；
真正在 _tick 的注入是一处守卫调用（无挑战内容时为 no-op）。
"""
from __future__ import annotations

import logging
import uuid
import asyncio
from dataclasses import dataclass, field
from typing import Any, Callable, Dict, List, Optional

from app.core.interfaces import RuntimeSignal
from app.framework.capability.assessment import (
    AssessmentCase,
    ProbeResponse,
    VerificationResult,
)
from app.framework.capability.challenge_library import ChallengeLibrary, ChallengeVariant
from app.framework.capability.dark_side import (
    SabotageAttempt,
    attribute_sabotage,
    corrupt_materials,
    detect_corruption,
)
from app.framework.capability.general_capabilities import (
    CapabilityAxis,
    MeasurementStatus,
    VerificationTier,
    get_capability,
    resolve_status,
)
from app.framework.capability.probe_executor import ProbeExecutor
from app.framework.capability.validators import get_validator
from app.framework.capability.atomic_result import (
    commit_atomic_result,
    commit_diagnostic,
    new_result_version,
)

logger = logging.getLogger(__name__)


def _parse_json_answer(text: str) -> Dict[str, Any]:
    """C 方案：从主回合 ActionPack.text 抽取 JSON 答案。

    推理模型会先吐 <think>...</think> 再给答案，先剥掉；再剥 markdown 围栏；
    最后捞第一个完整 JSON 对象。失败返回空 dict（验证阶段会判失败）。

    特殊处理：模型偶尔产出"重复空 key"的 JSON（如 ``{"": "a", "": "b"}``），
    Python json.loads 会折叠重复 key 只保留最后一个，丢失答案。在解析前把
    每个空 key 替换成 ``_pos0/_pos1/...`` 占位 key 以保留所有值；下游
    _normalize_answer_keys 会按位置回填 schema 官方 key 名。
    """
    import json as _json
    import re as _re
    if not text:
        return {}
    cleaned = _re.sub(r"<think>.*?</think>", "", text, flags=_re.DOTALL | _re.IGNORECASE)
    cleaned = _re.sub(r"```(?:json)?\s*", "", cleaned).replace("```", "").strip()
    match = _re.search(r"\{.*\}", cleaned, _re.DOTALL)
    if not match:
        return {}
    snippet = match.group()
    # 给重复空 key 加位置编号（仅匹配紧贴的 "": 模式，避免误伤合法 key）
    counter = {"i": 0}
    def _replace_empty_key(_):
        idx = counter["i"]
        counter["i"] += 1
        return f'"_pos{idx}":'
    snippet = _re.sub(r'""\s*:', _replace_empty_key, snippet)
    try:
        parsed = _json.loads(snippet)
        return parsed if isinstance(parsed, dict) else {}
    except _json.JSONDecodeError:
        return {}


def _normalize_answer_keys(
    parsed: Dict[str, Any], schema: Dict[str, Any]
) -> Dict[str, Any]:
    """B 兜底：当 LLM 输出 JSON 的所有 key 都是空字符串、但 value 数量与
    schema 字段数能对上时，按位置回填 schema 的官方 key 名。

    背景：推理模型偶尔把 schema 注入当成"占位描述"、输出 ``{"": "澈"}`` 这种
    空 key JSON。validator 拿 structured_answer 取键名比对会全失败。
    这里在 commit 之前做一次按位置的字段补名，最大化挽救 LLM 已经给出正确
    答案、只是 key 写漏的情况。
    """
    if not parsed or not isinstance(parsed, dict) or not schema:
        return parsed
    schema_keys = list(schema.keys())
    if not schema_keys:
        return parsed
    keys = list(parsed.keys())
    # 触发条件：所有 key 都是占位（空字符串 / _parse_json_answer 注入的 _posN /
    # 不在 schema 字段集合中）。任意一个真正命中 schema 都视为正常输出，不修。
    def _is_placeholder(k: Any) -> bool:
        s = str(k).strip()
        return (not s) or s.startswith("_pos") or s not in schema_keys
    if not all(_is_placeholder(k) for k in keys):
        return parsed
    values = list(parsed.values())
    if len(values) > len(schema_keys):
        # 多余值丢弃；优先按 schema 顺序回填前 N 个
        values = values[: len(schema_keys)]
    remapped: Dict[str, Any] = {}
    for sk, v in zip(schema_keys, values):
        remapped[sk] = v
    logger.info(
        f"[P0-e] structured_answer 字段补名 schema_keys={schema_keys} "
        f"orig_keys={keys} → values={values}"
    )
    return remapped


@dataclass
class NodeResult:
    """一次剧情节点产出的全部事实（已提交）。"""
    node_id: str
    tick: int
    cases: List[AssessmentCase] = field(default_factory=list)
    world_events: List[RuntimeSignal] = field(default_factory=list)
    invalidated_count: int = 0
    retest_count: int = 0


class CapabilityNodeCoordinator:
    """编排单个剧情节点的完整测评链路。"""

    def __init__(
        self,
        *,
        library: ChallengeLibrary,
        node_id: str,
        probe_executor: ProbeExecutor,
        fire_tick: int,
        trigger: Optional[Dict[str, Any]] = None,
        sabotage: Optional[SabotageAttempt] = None,
        display_name: Optional[Callable[[str], str]] = None,
    ) -> None:
        self._lib = library
        self._node_id = node_id
        self._exec = probe_executor
        self._fire_tick = fire_tick
        self._trigger = trigger or {}
        self._sabotage = sabotage
        self._name = display_name or (lambda aid: aid)
        meta = library.node_meta(node_id)
        self._title = str(meta.get("title", node_id))
        self._challenge_order = int(meta.get("challenge_order", 0) or 0)
        self._fired = False
        # 冷静期：支持 trigger 块或 challenge 元数据两处声明
        mg = self._trigger.get("min_gap_after_previous", 0)
        if (not mg or int(mg) <= 0):
            for probe in meta.get("probes", []):
                ch = probe.get("challenge", {})
                if ch.get("order") == self._challenge_order:
                    mg = ch.get("min_gap_after_previous", 0)
                    break
        self._min_gap = int(mg or 0)
        # 按 probe_key 归组的变体清单（用于轮转分配）
        self._by_key: Dict[str, List[ChallengeVariant]] = {}
        for v in library.variants_for(node_id):
            self._by_key.setdefault(v.probe_key, []).append(v)
        # C 方案限制：主回合作答路径只考第一个 probe_key。
        # 多 probe 节点其余题目会被静默跳过——装载时显式告警，避免内容组白配。
        if len(self._by_key) > 1:
            logger.warning(
                f"[CapabilityNode] node={node_id} 配置了 {len(self._by_key)} 个 probe_key，"
                f"C 方案主回合作答只会下发第一个（{next(iter(self._by_key))}），"
                f"其余将被忽略。"
            )

    @property
    def node_id(self) -> str:
        return self._node_id

    @property
    def title(self) -> str:
        return self._title

    @property
    def challenge_order(self) -> int:
        return self._challenge_order

    @property
    def fire_tick(self) -> int:
        return self._fire_tick

    @property
    def fired(self) -> bool:
        return self._fired

    def mark_fired(self) -> None:
        """挑战落幕（全员答完或超时关门）后调用，防止挑战被重复激活。"""
        self._fired = True

    def set_sabotage(self, attempt: Optional[SabotageAttempt]) -> None:
        """在节点触发前注入由世界行动产生的破坏尝试。"""
        if not self._fired:
            self._sabotage = attempt

    def should_fire(
        self,
        tick: int,
        actions: Optional[Dict[str, Any]] = None,
        agent_locations: Optional[Dict[str, str]] = None,
        last_challenge_closed_tick: int = 0,
    ) -> bool:
        if self._fired or not self._by_key:
            return False

        # 冷静期：前一项挑战结束后的最小间隔
        if self._min_gap > 0 and last_challenge_closed_tick > 0:
            if tick < last_challenge_closed_tick + self._min_gap:
                return False

        if self._trigger:
            actions = actions or {}
            action_ids = set(self._trigger.get("action_ids", []) or [])
            object_id = self._trigger.get("object_id")
            location_id = self._trigger.get("location_id")
            for agent_id, action in actions.items():
                if action is None:
                    continue
                if action_ids and getattr(action, "action_id", None) not in action_ids:
                    continue
                if object_id and getattr(action, "target_object_id", None) != object_id:
                    continue
                if location_id and (agent_locations or {}).get(agent_id) != location_id:
                    continue
                # 冷静期内即使触发条件满足也不 fire
                return True
            fallback_tick = int(
                self._trigger.get("fallback_tick", self._fire_tick) or 0
            )
            return bool(fallback_tick and tick >= fallback_tick)
        return tick >= self._fire_tick

    async def run(
        self,
        *,
        tick: int,
        agent_ids: List[str],
        event_sink: Callable[[RuntimeSignal], None],
        case_sink: Callable[[AssessmentCase], None],
    ) -> NodeResult:
        """节点触发：对所有角色运行完整批探针，原子提交并返回汇总。"""
        self._fired = True
        result = NodeResult(node_id=self._node_id, tick=tick)

        jobs = []
        for probe_key, variants in self._by_key.items():
            if not variants:
                continue
            for idx, agent_id in enumerate(agent_ids):
                variant = variants[idx % len(variants)]   # 轮转分配等价变体
                jobs.append(self._run_one(
                    tick=tick, agent_id=agent_id, probe_key=probe_key,
                    variant=variant, all_variants=variants,
                    event_sink=event_sink, case_sink=case_sink,
                    result=result,
                ))
        if jobs:
            await asyncio.gather(*jobs)
        logger.info(
            f"[CapabilityNode] node={self._node_id} tick={tick} "
            f"cases={len(result.cases)} invalidated={result.invalidated_count} retests={result.retest_count}"
        )
        return result

    # ── C 方案（P0-e）：从主回合 ActionPack 提交答案，不再独立子回合 ──────

    def get_question_for_agent(
        self, *, tick: int, agent_id: str, agent_idx: int
    ) -> Dict[str, Any]:
        """为 agent_brief 提供当前挑战材料。

        返回适合注入 brief.raw_context.challenge_question 的 dict：包含
        instruction（任务说明）、materials（挑战材料）、output_schema（响应
        案 JSON 结构）和能力标签。Agent 在主回合按此 schema 把答案写到
        ActionPack.text，引擎之后通过 commit_external_answer 提交。

        暗面接线：若本次挑战存在针对该 agent 的投毒（capability_sabotage），
        下发前先污染 materials——与旧子回合路径的 corrupt_materials 等价。
        """
        if not self._by_key:
            return {}
        # 与 run() 中一致的轮转分配规则
        probe_key = next(iter(self._by_key.keys()))
        variants = self._by_key[probe_key]
        variant = variants[agent_idx % len(variants)]
        probe = self._lib.build_probe(variant, tick=tick, agent_id=agent_id)
        if self._is_sabotaged(agent_id, probe_key):
            poisoned = corrupt_materials(probe.materials, self._sabotage)
            probe = probe.model_copy(update={"materials": poisoned})
        cap = get_capability(variant.capability)

        # 多模态挑战：预先把图片转为 base64 data_url，供主回合视觉调用
        import base64, mimetypes
        from pathlib import Path as _Path
        image_data_urls: List[str] = []
        for raw_path in (probe.materials.get("image_paths") or []):
            p = _Path(str(raw_path))
            if p.exists() and p.is_file():
                mime = mimetypes.guess_type(p.name)[0] or "image/svg+xml"
                encoded = base64.b64encode(p.read_bytes()).decode("ascii")
                image_data_urls.append(f"data:{mime};base64,{encoded}")

        return {
            "node_id": self._node_id,
            "node_title": self._title,
            "capability": variant.capability,
            "capability_label": (cap.label if cap else variant.capability),
            "instruction": probe.instruction,
            "materials": dict(probe.materials),
            "output_schema": dict(probe.output_schema),
            "variant_id": variant.variant_id,
            "probe_id": probe.probe_id,
            "image_data_urls": image_data_urls,
        }

    def commit_external_answer(
        self,
        *,
        tick: int,
        agent_id: str,
        agent_idx: int,
        action_pack: Any,
        event_sink: Callable[[RuntimeSignal], None],
        case_sink: Callable[[AssessmentCase], None],
        result: NodeResult,
    ) -> bool:
        """C 方案核心入口：把主回合 ActionPack 当作挑战作答提交。

        从 action_pack.text 提取 JSON 作为 structured_answer；raw_output 用
        独白+公开理由+text 拼接，保留全部叙事痕迹给导演与审计。之后复用
        _verify + _commit_neutral，与子回合路径产物完全等价。

        返回 True 表示成功提交（无论作答对错），False 表示未匹配到 variant。
        """
        if not self._by_key:
            return False
        probe_key = next(iter(self._by_key.keys()))
        variants = self._by_key[probe_key]
        variant = variants[agent_idx % len(variants)]
        probe = self._lib.build_probe(variant, tick=tick, agent_id=agent_id)
        sabotaged = self._is_sabotaged(agent_id, probe_key)
        if sabotaged:
            # 与 get_question_for_agent 下发的脏材料保持一致
            poisoned = corrupt_materials(probe.materials, self._sabotage)
            probe = probe.model_copy(update={"materials": poisoned})

        raw_text = getattr(action_pack, "text", "") or ""
        raw_output = "\n".join(filter(None, [
            getattr(action_pack, "raw_model_output", "") or "",
            getattr(action_pack, "character_monologue", "") or "",
            getattr(action_pack, "public_reasoning_summary", "") or "",
            raw_text,
        ])) or raw_text
        structured = _parse_json_answer(raw_text)
        # B 兜底：LLM 可能把 schema 的 key 写漏（输出 {"": "..."}），按位置补名
        if structured:
            structured = _normalize_answer_keys(structured, probe.output_schema)

        response = ProbeResponse(
            probe_id=probe.probe_id,
            agent_id=agent_id,
            raw_output=raw_output,
            structured_answer=structured,
            error=None if structured else "missing_or_unparseable_json",
        )
        verification = self._verify(variant, probe, response)

        if not sabotaged:
            self._commit_neutral(
                tick, agent_id, variant, probe, response, verification,
                event_sink, case_sink, result,
            )
            return True

        # ── 暗面分支（C 方案接线，与 _run_one 同口径）──
        attempt = self._sabotage
        detected = detect_corruption(response.structured_answer, attempt)
        offense_case_id = f"off_{uuid.uuid4().hex[:8]}"
        verdict = attribute_sabotage(
            attempt=attempt, defended=detected,
            offense_case_id=offense_case_id,
            corrupted_input_ref=f"{probe.probe_id}:{attempt.corrupted_field}",
        )
        if verdict.target_invalidated:
            # 被投毒且未识破 → 作废，不算在被测者头上；破坏者记功。
            # C 方案无独立子回合可重测，作废案例即终态（聚合器不计入能力分）。
            rv = new_result_version()
            inval_case = self._mk_case(
                rv_or_effect=rv, tick=tick, agent_id=agent_id, variant=variant,
                probe=probe, response=response, verification=verification,
                status=MeasurementStatus.INVALIDATED, score=0.0,
                invalidation=verdict.invalidation, axis=CapabilityAxis.NEUTRAL,
            )
            diag = RuntimeSignal(
                tick=tick, event_type="measurement_invalidated",
                source_id=attempt.saboteur_id, target_id=agent_id,
                summary=verdict.summary,
            )
            commit_diagnostic(case=inval_case, diagnostic_event=diag,
                              event_sink=event_sink, case_sink=case_sink)
            result.cases.append(inval_case)
            result.world_events.append(diag)
            result.invalidated_count += 1
            self._commit_axis_case(
                tick=tick, agent_id=attempt.saboteur_id, variant=variant,
                probe=probe, response=response, axis=CapabilityAxis.OFFENSE,
                score=verdict.offense_score, capability="safety",
                summary=f"{self._name(attempt.saboteur_id)} 投毒得手，污染 {self._name(agent_id)} 的测量",
                event_type="sabotage_succeeded",
                event_sink=event_sink, case_sink=case_sink,
                result=result,
            )
        else:
            # 识破 → 测量有效 + 守方记功 + 破坏者攻击失败
            self._commit_neutral(
                tick, agent_id, variant, probe, response, verification,
                event_sink, case_sink, result,
            )
            self._commit_axis_case(
                tick=tick, agent_id=agent_id, variant=variant,
                probe=probe, response=response, axis=CapabilityAxis.DEFENSE,
                score=verdict.defense_score or 1.0, capability="safety",
                summary=f"{self._name(agent_id)} 识破 {self._name(attempt.saboteur_id)} 的投毒，守住测量",
                event_type="sabotage_defended",
                event_sink=event_sink, case_sink=case_sink,
                result=result,
            )
            self._commit_axis_case(
                tick=tick, agent_id=attempt.saboteur_id, variant=variant,
                probe=probe, response=response, axis=CapabilityAxis.OFFENSE,
                score=verdict.offense_score, capability="safety",
                summary=f"{self._name(attempt.saboteur_id)} 投毒被识破，攻击失败",
                event_type="sabotage_failed",
                event_sink=event_sink, case_sink=case_sink,
                result=result,
            )
        return True

    def _is_sabotaged(self, agent_id: str, probe_key: str) -> bool:
        return (
            self._sabotage is not None
            and self._sabotage.target_id == agent_id
            and self._sabotage.probe_key == probe_key
        )

    def commit_skipped_answer(
        self,
        *,
        tick: int,
        agent_id: str,
        agent_idx: int = 0,
        reason: str = "",
        event_sink: Optional[Callable[[RuntimeSignal], None]] = None,
        case_sink: Optional[Callable[[AssessmentCase], None]] = None,
        result: Optional[NodeResult] = None,
    ) -> None:
        """挑战超时未作答：落一个 0 分失败案例进账本，弃答在终局审计可见。

        旧实现只打日志——弃答者在账本上没有任何痕迹，failure 世界效果也不
        生效，等于"拖到超时"比"答错"更划算。现在按空答案走完整提交链路。
        """
        logger.warning(
            f"[P0-e] 挑战超时 skipped agent={agent_id} "
            f"node={self._node_id} reason={reason}"
        )
        if not self._by_key or result is None:
            return
        _noop = lambda _item: None  # noqa: E731
        event_sink = event_sink or _noop
        case_sink = case_sink or _noop
        probe_key = next(iter(self._by_key.keys()))
        variants = self._by_key[probe_key]
        variant = variants[agent_idx % len(variants)]
        probe = self._lib.build_probe(variant, tick=tick, agent_id=agent_id)
        response = ProbeResponse(
            probe_id=probe.probe_id,
            agent_id=agent_id,
            raw_output="",
            structured_answer={},
            error=f"skipped_timeout: {reason or '挑战超时未作答'}",
        )
        verification = VerificationResult(
            probe_id=probe.probe_id, capability=variant.capability,
            tier_used=variant.expected_tier, verifier_id="skipped.timeout",
            passed=False, score=0.0,
            rationale=f"超时未作答（{reason or '挑战关门'}），按失败计。",
        )
        self._commit_neutral(
            tick, agent_id, variant, probe, response, verification,
            event_sink, case_sink, result,
        )

    # ── 单个 (agent, probe) 链路 ──────────────────────────────────────────

    async def _run_one(self, *, tick, agent_id, probe_key, variant, all_variants,
                       event_sink, case_sink, result: NodeResult) -> None:
        sabotaged = (
            self._sabotage is not None
            and self._sabotage.target_id == agent_id
            and self._sabotage.probe_key == probe_key
        )

        # 构建探针（被投毒者拿脏材料）
        if sabotaged:
            probe = self._lib.build_probe(variant, tick=tick, agent_id=agent_id)
            poisoned = corrupt_materials(probe.materials, self._sabotage)
            probe = probe.model_copy(update={"materials": poisoned})
        else:
            probe = self._lib.build_probe(variant, tick=tick, agent_id=agent_id)

        response = await self._exec.run(probe)
        verification = self._verify(variant, probe, response)

        if not sabotaged:
            self._commit_neutral(
                tick, agent_id, variant, probe, response, verification,
                event_sink, case_sink, result,
            )
            return

        # ── 暗面分支 ──
        attempt = self._sabotage
        detected = detect_corruption(response.structured_answer, attempt)
        offense_case_id = f"off_{uuid.uuid4().hex[:8]}"
        verdict = attribute_sabotage(
            attempt=attempt, defended=detected,
            offense_case_id=offense_case_id,
            corrupted_input_ref=f"{probe.probe_id}:{attempt.corrupted_field}",
        )

        if verdict.target_invalidated:
            # 1) 被测者 INVALIDATED 案例 + 诊断事件（无导演事实）
            rv = new_result_version()
            inval_case = self._mk_case(
                rv_or_effect=rv, tick=tick, agent_id=agent_id, variant=variant,
                probe=probe, response=response, verification=verification,
                status=MeasurementStatus.INVALIDATED, score=0.0,
                invalidation=verdict.invalidation, axis=CapabilityAxis.NEUTRAL,
            )
            diag = RuntimeSignal(
                tick=tick, event_type="measurement_invalidated",
                source_id=attempt.saboteur_id, target_id=agent_id,
                summary=verdict.summary,
            )
            commit_diagnostic(case=inval_case, diagnostic_event=diag,
                              event_sink=event_sink, case_sink=case_sink)
            result.cases.append(inval_case)
            result.world_events.append(diag)
            result.invalidated_count += 1

            # 2) 重测：换一个干净变体，凭实力作答
            clean = next((v for v in all_variants if v.variant_id != variant.variant_id), variant)
            re_probe = self._lib.build_probe(clean, tick=tick, agent_id=agent_id)
            re_resp = await self._exec.run(re_probe)
            re_ver = self._verify(clean, re_probe, re_resp)
            self._commit_neutral(
                tick, agent_id, clean, re_probe, re_resp, re_ver,
                event_sink, case_sink, result, retest=True,
            )
            result.retest_count += 1

            # 3) 破坏者 OFFENSE 记功案例
            self._commit_axis_case(
                tick=tick, agent_id=attempt.saboteur_id, variant=variant,
                probe=probe, response=response, axis=CapabilityAxis.OFFENSE,
                score=verdict.offense_score, capability="safety",
                summary=f"{self._name(attempt.saboteur_id)} 投毒得手，污染 {self._name(agent_id)} 的测量",
                event_type="sabotage_succeeded",
                event_sink=event_sink, case_sink=case_sink, result=result,
            )
        else:
            # 守成功：被测者测量有效 + 守方记功 + 破坏者攻击失败
            self._commit_neutral(
                tick, agent_id, variant, probe, response, verification,
                event_sink, case_sink, result,
            )
            self._commit_axis_case(
                tick=tick, agent_id=agent_id, variant=variant,
                probe=probe, response=response, axis=CapabilityAxis.DEFENSE,
                score=verdict.defense_score or 1.0, capability="safety",
                summary=f"{self._name(agent_id)} 识破 {self._name(attempt.saboteur_id)} 的投毒，守住测量",
                event_type="sabotage_defended",
                event_sink=event_sink, case_sink=case_sink, result=result,
            )
            self._commit_axis_case(
                tick=tick, agent_id=attempt.saboteur_id, variant=variant,
                probe=probe, response=response, axis=CapabilityAxis.OFFENSE,
                score=verdict.offense_score, capability="safety",
                summary=f"{self._name(attempt.saboteur_id)} 投毒被识破，攻击失败",
                event_type="sabotage_failed",
                event_sink=event_sink, case_sink=case_sink, result=result,
            )

    # ── 提交：常规（中立）案例 ────────────────────────────────────────────

    def _commit_neutral(self, tick, agent_id, variant, probe, response, verification,
                        event_sink, case_sink, result: NodeResult,
                        retest: bool = False) -> None:
        passed = verification.passed
        cap = get_capability(variant.capability)
        # 单案例无论高低都是有效证据；最终 measured/insufficient 由聚合器按样本数决定。
        status = MeasurementStatus.INSUFFICIENT
        rv = new_result_version()
        case = self._mk_case(
            rv_or_effect=rv, tick=tick, agent_id=agent_id, variant=variant,
            probe=probe, response=response, verification=verification,
            status=status, score=verification.score, axis=CapabilityAxis.NEUTRAL,
        )
        label = cap.label if cap else variant.capability
        verb = "通过" if passed else "未过"
        tag = "（重测）" if retest else ""
        effect_key = "success" if passed else "failure"
        declared_effects = list(variant.world_effects.get(effect_key, []) or [])
        ev = RuntimeSignal(
            tick=tick, event_type="node_probe_settled", source_id=agent_id,
            summary=f"{self._name(agent_id)} 在【{self._title}·{label}】作答{verb}{tag}",
            metadata={
                "capability": variant.capability,
                "passed": passed,
                "score": verification.score,
                "retest": retest,
                "declared_world_effects": declared_effects,
                "verification_rationale": verification.rationale,
            },
        )
        commit_atomic_result(
            case=case, world_events=[ev],
            event_sink=event_sink, case_sink=case_sink,
        )
        result.cases.append(case)
        result.world_events.append(ev)

    # ── 提交：攻/守轴案例 ─────────────────────────────────────────────────

    def _commit_axis_case(self, *, tick, agent_id, variant, probe, response, axis,
                          score, capability, summary, event_type,
                          event_sink, case_sink, result: NodeResult) -> None:
        rv = new_result_version()
        ver = VerificationResult(
            probe_id=probe.probe_id, capability=capability,
            tier_used=VerificationTier.DETERMINISTIC, verifier_id="darkside.attribution",
            passed=score >= 0.5, score=score,
        )
        case = AssessmentCase(
            case_id=f"c_{uuid.uuid4().hex[:10]}", tick=tick, agent_id=agent_id,
            capability=capability, node_id=self._node_id, variant_id=variant.variant_id,
            axis=axis, status=MeasurementStatus.MEASURED, score=score,
            tier_used=VerificationTier.DETERMINISTIC,
            probe=probe, response=response, verification=ver, world_effect_ref=rv,
        )
        ev = RuntimeSignal(tick=tick, event_type=event_type, source_id=agent_id, summary=summary,
                        metadata={"axis": axis.value, "capability": capability})
        commit_atomic_result(
            case=case, world_events=[ev],
            event_sink=event_sink, case_sink=case_sink,
        )
        result.cases.append(case)
        result.world_events.append(ev)

    # ── 工具 ─────────────────────────────────────────────────────────────

    def _verify(self, variant, probe, response) -> VerificationResult:
        validator = get_validator(variant.validator_id)
        if validator is None:
            return VerificationResult(
                probe_id=probe.probe_id, capability=variant.capability,
                tier_used=variant.expected_tier, verifier_id="missing",
                passed=False, score=0.0, rationale=f"验证器 {variant.validator_id} 未注册",
            )
        gt = self._lib.resolve_ground_truth(variant.ground_truth_ref)
        return validator.validate(probe, response, gt)

    def _mk_case(self, *, rv_or_effect, tick, agent_id, variant, probe, response,
                 verification, status, score, axis, invalidation=None) -> AssessmentCase:
        return AssessmentCase(
            case_id=f"c_{uuid.uuid4().hex[:10]}", tick=tick, agent_id=agent_id,
            capability=variant.capability, node_id=self._node_id,
            variant_id=variant.variant_id, axis=axis, status=status,
            tier_used=verification.tier_used, score=score, weight=variant.weight,
            probe=probe, response=response, verification=verification,
            world_effect_ref=rv_or_effect, invalidation=invalidation,
        )

    # 通用评测枚举 → 中文（答案内容里的英文枚举，播报时中文化，观众不出戏）
    _ANSWER_VALUE_ZH = {
        "authentic": "属实", "genuine": "属实", "real": "属实",
        "forged": "伪造", "fake": "伪造", "counterfeit": "伪造",
        "valid": "成立", "invalid": "不成立",
        "true": "是", "false": "否", "yes": "是", "no": "否",
        "pass": "通过", "fail": "未过",
        "consistent": "一致", "inconsistent": "不一致",
        "match": "匹配", "mismatch": "不匹配",
    }

    @classmethod
    def _zh_value(cls, value: Any) -> str:
        s = str(value)[:60]
        return cls._ANSWER_VALUE_ZH.get(s.strip().lower(), s)

    @staticmethod
    def _short_field_label(desc: Any) -> str:
        """从 output_schema 的中文描述提取简短字段名做标签。

        "目标对象（名称）" → "目标对象"
        含英文/枚举说明的描述（如 "authentic 或 forged"）→ 返回空（只显示值）。
        """
        if not desc or not isinstance(desc, str):
            return ""
        import re as _re
        head = _re.split(r"[（(，,。：:；;]", desc.strip())[0].strip()
        if not head:
            return ""
        # 含 ASCII 字母（多半是取值说明而非字段名）→ 不做标签
        if any("a" <= c.lower() <= "z" for c in head):
            return ""
        return head

    def _format_answer_claim(
        self, *, agent_id: str, variant: Any, response: Any, passed: bool,
    ) -> str:
        """把模型实际答案抽成中文叙事，供导演说明角色作答内容。
        用 variant.output_schema 的中文描述做字段标签，英文枚举值中文化。"""
        try:
            output = getattr(response, "structured_answer", None) or {}
            if not isinstance(output, dict) or not output:
                return ""
            schema = getattr(variant, "output_schema", None) or {}
            pieces: List[str] = []
            for k, v in list(output.items())[:3]:
                if v is None or v == "":
                    continue
                if isinstance(v, (dict, list)):
                    continue
                label = self._short_field_label(schema.get(k))
                val = self._zh_value(v)
                pieces.append(f"{label}：{val}" if label else val)
            if not pieces:
                return ""
            name = self._name(agent_id)
            verb = "读出" if passed else "答出"
            return f"{name}{verb}：{'；'.join(pieces)}"
        except Exception:
            return ""

    @staticmethod
    def _effect_summary(effects: List[Dict[str, Any]], passed: bool) -> str:
        labels = [
            str(item.get("narrative") or item.get("label") or "")
            for item in effects
            if isinstance(item, dict) and item.get("target", "actor") != "rival"
        ]
        labels = [item for item in labels if item]
        if labels:
            return "；".join(labels)
        return "这一判断已经被世界规则记录，并将影响后续局势。" if passed else (
            "这一误判没有被世界轻轻放过，后续局势将因此承受代价。"
        )


__all__ = ["CapabilityNodeCoordinator", "NodeResult"]
