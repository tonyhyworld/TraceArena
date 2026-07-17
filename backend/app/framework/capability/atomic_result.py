"""
原子结果事务（P0-4）

一次能力探针裁决会产出两类事实，它们必须作为同一版本一次性提交：
  ① 运行时诊断信号 —— RuntimeSignal
  ② 评测证据   —— AssessmentCase

铁律：
  - 同一 result_version 串起事件和案例；OS2 导演只消费转换后的可信账本。
  - 全有或全无：纯装配 + 一致性校验在「写任何 sink 之前」完成；校验失败 → 一条都不写。
  - 不静默吞掉失败：失败 / 被污染走 commit_diagnostic —— 写 invalidated 案例 + 诊断事件，
    且不产出导演事实包（导演无可讲述）。

本模块是与引擎解耦的提交原语：真正的 sink（world_state.add_event / 案例账本 / 事实包账本）
由调用方在 P1-8 注入。这样底座可独立测试，接线时零返工。
"""
from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from typing import Callable, List, Optional

from app.core.interfaces import RuntimeSignal
from app.framework.capability.assessment import AssessmentCase
from app.framework.capability.general_capabilities import MeasurementStatus


class ResultConsistencyError(Exception):
    """装配后一致性校验失败——事务中止，未写入任何 sink。"""


# sink 签名（由 P1-8 注入真实实现）
EventSink = Callable[[RuntimeSignal], None]
CaseSink = Callable[[AssessmentCase], None]


@dataclass(frozen=True)
class ResultReceipt:
    """一次原子提交的回执。"""
    result_version: str
    committed: bool
    case_id: str
    status: MeasurementStatus
    world_event_count: int = 0
    diagnostic: Optional[str] = None


def new_result_version() -> str:
    """铸造一个事务版本号。调用方应在构建 AssessmentCase 前先取版本，
    并把它写入 case.world_effect_ref 完成链接。"""
    return f"rv_{uuid.uuid4().hex[:12]}"


def _stamp_event(ev: RuntimeSignal, version: str, case_id: str, seq: int) -> RuntimeSignal:
    """给世界事件盖上版本与案例链接（返回新副本，不改原对象）。"""
    md = dict(ev.metadata)
    md["result_version"] = version
    md["linked_case_id"] = case_id
    md["event_id"] = f"{version}:{seq}"
    return ev.model_copy(update={"metadata": md})


def commit_atomic_result(
    *,
    case: AssessmentCase,
    world_events: List[RuntimeSignal],
    event_sink: EventSink,
    case_sink: CaseSink,
) -> ResultReceipt:
    """
    成功路径：把世界事件和案例作为同一版本原子提交。

    version 取自 case.world_effect_ref（调用方先 new_result_version() 再建 case）。
    任何一致性问题在写 sink 之前抛 ResultConsistencyError——保证全有或全无。
    """
    version = case.world_effect_ref
    if not version:
        raise ResultConsistencyError("case.world_effect_ref 为空，未与事务版本链接。")
    if case.status == MeasurementStatus.INVALIDATED:
        raise ResultConsistencyError("INVALIDATED 案例不得走成功提交，请用 commit_diagnostic。")
    # —— 纯装配（不触碰任何 sink）——
    stamped_events = [_stamp_event(ev, version, case.case_id, i)
                      for i, ev in enumerate(world_events)]

    # —— 提交块（单线程、无 await、纯 append，实际原子）——
    for ev in stamped_events:
        event_sink(ev)
    case_sink(case)
    return ResultReceipt(
        result_version=version, committed=True, case_id=case.case_id,
        status=case.status, world_event_count=len(stamped_events),
    )


def commit_diagnostic(
    *,
    case: AssessmentCase,
    diagnostic_event: RuntimeSignal,
    event_sink: EventSink,
    case_sink: CaseSink,
    diagnostic: str = "",
) -> ResultReceipt:
    """
    失败 / 被污染路径：写入 invalidated（或部分）案例 + 一条诊断世界事件，
    不产出任何导演事实包——导演无可讲述，杜绝凭空叙事。
    """
    version = case.world_effect_ref or new_result_version()
    stamped = _stamp_event(diagnostic_event, version, case.case_id, 0)
    event_sink(stamped)
    case_sink(case)
    return ResultReceipt(
        result_version=version, committed=True, case_id=case.case_id,
        status=case.status, world_event_count=1,
        diagnostic=diagnostic or stamped.summary,
    )


__all__ = [
    "ResultConsistencyError",
    "ResultReceipt",
    "EventSink",
    "CaseSink",
    "new_result_version",
    "commit_atomic_result",
    "commit_diagnostic",
]
