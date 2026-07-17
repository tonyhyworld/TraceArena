"""
验证器框架与注册表（P0-3）

三级验证（可信度由高到低）：
  一级 DETERMINISTIC  确定性对答案——代码测试/JSON/数学/事实/引用/权限
  二级 RUBRIC         结构化评分点——每点一个确定性检查
  三级 BLIND_JUDGE    盲评 LLM 裁判——隐藏被测身份 + 固定 rubric，裁判无权改世界

关键纪律：
  - 验证器不依赖任何具体场景。判定规则由 ground_truth 里的 check spec 驱动，
    场景包只提供数据，不在验证器里硬编码场景名/节点名。
  - 隐藏答案分离：ground_truth 由引擎从隐藏答案库按 probe.ground_truth_ref 解析后
    传入，绝不经由下发给模型的 Probe 暴露。
  - 盲评裁判通过依赖注入提供 judge_fn，验证器本身不直接调用 LLM、不触碰世界状态。

注册表用法（插件式，无场景硬编码）：
    register_validator(MyValidator())
    v = get_validator("det.spec")
    result = v.validate(probe, response, ground_truth)
"""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable, Dict, List, Optional, Tuple

from app.framework.capability.assessment import (
    CapabilityProbe,
    ProbeResponse,
    RubricPoint,
    VerificationResult,
)
from app.framework.capability.general_capabilities import VerificationTier


# ---------------------------------------------------------------------------
# 验证器基类
# ---------------------------------------------------------------------------

class Validator(ABC):
    """验证器接口：给定探针 + 作答 + 解析后的隐藏答案，产出判定。"""

    #: 全局唯一标识，写入 VerificationResult.verifier_id
    validator_id: str = ""
    tier: VerificationTier = VerificationTier.DETERMINISTIC

    @abstractmethod
    def validate(
        self,
        probe: CapabilityProbe,
        response: ProbeResponse,
        ground_truth: Dict[str, Any],
    ) -> VerificationResult:
        ...


# ---------------------------------------------------------------------------
# 一级：确定性对答案
# ---------------------------------------------------------------------------

def _check_one(mode: str, answer: Any, expected: Any, tol: float = 0.0) -> bool:
    """单条确定性检查；mode 由 ground_truth 提供，与场景无关。"""
    if mode == "exact":
        return answer == expected
    if mode == "iexact":
        return str(answer).strip().lower() == str(expected).strip().lower()
    if mode == "numeric":
        try:
            return abs(float(answer) - float(expected)) <= tol
        except (TypeError, ValueError):
            return False
    if mode == "contains":
        return str(expected) in str(answer)
    if mode == "set_subset":   # 必需项全部出现（如引用/权限齐备）
        try:
            return set(expected) <= set(answer)
        except TypeError:
            return False
    if mode == "set_equal":
        try:
            return set(answer) == set(expected)
        except TypeError:
            return False
    raise ValueError(f"未知确定性检查 mode: {mode}")


class DeterministicValidator(Validator):
    """
    确定性验证器。ground_truth 形如：
        {"checks": [
            {"field": "verdict", "mode": "iexact", "expected": "authentic"},
            {"field": "citations", "mode": "set_subset", "expected": ["a","b"]},
        ]}
    全部 check 通过即 passed；score = 通过数 / 总数。
    """
    validator_id = "det.spec"
    tier = VerificationTier.DETERMINISTIC

    def validate(self, probe, response, ground_truth):
        checks: List[Dict[str, Any]] = list(ground_truth.get("checks", []))
        answer = response.structured_answer or {}
        if not checks:
            return VerificationResult(
                probe_id=probe.probe_id, capability=probe.capability, tier_used=self.tier,
                verifier_id=self.validator_id, passed=False, score=0.0,
                rationale="ground_truth 未提供 checks，无法确定性判定。",
            )
        passed_n = 0
        details: List[str] = []
        for c in checks:
            field = c.get("field", "")
            mode = c.get("mode", "exact")
            ok = _check_one(mode, answer.get(field), c.get("expected"), float(c.get("tol", 0.0)))
            passed_n += int(ok)
            details.append(f"{field}[{mode}]={'✓' if ok else '✗'}")
        total = len(checks)
        required_tool = ground_truth.get("required_tool_id")
        if required_tool:
            tool_ok = any(
                call.tool_id == required_tool and call.ok
                for call in response.tool_calls
            )
            # C方案兜底：无实际执行记录时，检查 structured_answer["tool_calls"] 中的声明
            if not tool_ok:
                for tc in (answer.get("tool_calls") or []):
                    if isinstance(tc, dict) and tc.get("tool") == required_tool:
                        tool_ok = True
                        break
            total += 1
            passed_n += int(tool_ok)
            details.append(f"tool[{required_tool}]={'✓' if tool_ok else '✗'}")
        score = passed_n / total if total else 0.0
        return VerificationResult(
            probe_id=probe.probe_id, capability=probe.capability, tier_used=self.tier,
            verifier_id=self.validator_id, passed=(passed_n == total),
            score=score, rationale="; ".join(details),
            evidence_refs=[tc.result_ref for tc in response.tool_calls if tc.result_ref],
        )


# ---------------------------------------------------------------------------
# 二级：Rubric 评分点
# ---------------------------------------------------------------------------

class RubricValidator(Validator):
    """
    Rubric 验证器。ground_truth 形如：
        {"rubric": [
            {"key": "stated_basis", "weight": 2.0,
             "check": {"field": "basis", "mode": "contains", "expected": "印信"}},
            {"key": "correct_verdict", "weight": 3.0,
             "check": {"field": "verdict", "mode": "iexact", "expected": "forged"}},
        ]}
    score = Σawarded / Σweight；passed 阈值默认 0.6（可被 ground_truth["pass_threshold"] 覆盖）。
    """
    validator_id = "rubric.spec"
    tier = VerificationTier.RUBRIC

    def validate(self, probe, response, ground_truth):
        spec: List[Dict[str, Any]] = list(ground_truth.get("rubric", []))
        answer = response.structured_answer or {}
        if not spec:
            return VerificationResult(
                probe_id=probe.probe_id, capability=probe.capability, tier_used=self.tier,
                verifier_id=self.validator_id, passed=False, score=0.0,
                rationale="ground_truth 未提供 rubric。",
            )
        points: List[RubricPoint] = []
        total_w = 0.0
        got_w = 0.0
        for item in spec:
            w = float(item.get("weight", 1.0))
            chk = item.get("check", {})
            ok = _check_one(
                chk.get("mode", "exact"),
                answer.get(chk.get("field", "")),
                chk.get("expected"),
                float(chk.get("tol", 0.0)),
            )
            awarded = w if ok else 0.0
            total_w += w
            got_w += awarded
            points.append(RubricPoint(
                key=item.get("key", ""), description=item.get("description", ""),
                weight=w, awarded=awarded,
            ))
        score = (got_w / total_w) if total_w > 0 else 0.0
        threshold = float(ground_truth.get("pass_threshold", 0.6))
        return VerificationResult(
            probe_id=probe.probe_id, capability=probe.capability, tier_used=self.tier,
            verifier_id=self.validator_id, passed=(score >= threshold),
            score=score, rubric=points,
            rationale=f"rubric {got_w:.1f}/{total_w:.1f} (阈值 {threshold}).",
        )


# ---------------------------------------------------------------------------
# 三级：盲评 LLM 裁判（依赖注入，不在此直接调用 LLM）
# ---------------------------------------------------------------------------

# judge_fn 签名：给定（探针、作答、rubric 规格、隐藏参考），返回 (score[0,1], rationale, rubric_points)
JudgeFn = Callable[
    [CapabilityProbe, ProbeResponse, List[Dict[str, Any]], Dict[str, Any]],
    Tuple[float, str, List[RubricPoint]],
]


class BlindJudgeValidator(Validator):
    """
    盲评裁判验证器。裁判逻辑由外部注入的 judge_fn 提供（引擎启动时绑定真正的 LLM 裁判）。
    本类只负责：剥离被测身份（blind）、组织 rubric 规格、把裁判输出包装成 VerificationResult。
    裁判无权改世界——它只读 probe/response，不接触世界状态句柄。
    """
    validator_id = "judge.blind"
    tier = VerificationTier.BLIND_JUDGE

    def __init__(self, judge_fn: JudgeFn):
        self._judge = judge_fn

    def validate(self, probe, response, ground_truth):
        rubric_spec = list(ground_truth.get("rubric", []))
        threshold = float(ground_truth.get("pass_threshold", 0.6))
        score, rationale, points = self._judge(probe, response, rubric_spec, ground_truth)
        score = max(0.0, min(1.0, float(score)))
        return VerificationResult(
            probe_id=probe.probe_id, capability=probe.capability, tier_used=self.tier,
            verifier_id=self.validator_id, passed=(score >= threshold),
            score=score, rubric=points, rationale=rationale, blind=True,
        )


# ---------------------------------------------------------------------------
# 注册表
# ---------------------------------------------------------------------------

_REGISTRY: Dict[str, Validator] = {}


def register_validator(validator: Validator, *, replace: bool = False) -> None:
    """注册一个验证器。重复注册需显式 replace=True，避免静默覆盖。"""
    vid = validator.validator_id
    if not vid:
        raise ValueError("验证器必须有非空 validator_id")
    if vid in _REGISTRY and not replace:
        raise ValueError(f"验证器 {vid} 已注册；如需覆盖请传 replace=True")
    _REGISTRY[vid] = validator


def get_validator(validator_id: str) -> Optional[Validator]:
    return _REGISTRY.get(validator_id)


def list_validators() -> List[str]:
    return sorted(_REGISTRY)


def _register_builtins() -> None:
    """注册内置的一/二级验证器。三级盲评需注入 judge_fn，由引擎按需注册。"""
    register_validator(DeterministicValidator(), replace=True)
    register_validator(RubricValidator(), replace=True)


_register_builtins()


__all__ = [
    "Validator",
    "DeterministicValidator",
    "RubricValidator",
    "BlindJudgeValidator",
    "JudgeFn",
    "register_validator",
    "get_validator",
    "list_validators",
]
