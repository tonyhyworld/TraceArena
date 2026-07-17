"""回合 / 时钟模型契约（P1 契约层，纯新增，尚未接线）。

对应 docs/OS层与场景包边界约定.md 第 2 节"业务回合"行 + 第 9 节技术债 #6：
**执行节拍（tick）归 OS；回合的定义（单位/阶段/每阶段谁行动/推进条件）
归场景包声明，OS 只执行。**

现状问题：OS 只有裸整数 tick，并隐含假设"1 tick = 1 个全员同步回合、
每拍所有存活 agent 都行动"（同步回合制的形状）。有的场景需要定义自己的
回合结构（如多个阶段循环成一个业务周期），此前只能把时钟声明塞进
settlement blob + 在插件里对 tick 取模。本契约把它正规化为 world/clock.yaml。

P1 只定义契约 + 加载器；加载器在文件缺失时返回"默认同步回合模型"，
等价于当前行为，因此零回归。P2 才让 tick 管线消费本模型。
"""
from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Dict, List, Literal, Optional, Tuple

import yaml

# 谁在某阶段行动：
#   "all"          全部存活 agent（当前 OS 的唯一模式）
#   role 列表      仅这些 agent_slot_id / 角色（如狼人杀夜晚仅狼人）
Actors = Any  # "all" | List[str]

# 回合如何推进：
#   every_tick     每个执行节拍推进一个阶段（当前隐含行为）
#   all_submitted  当本阶段所有应行动者都提交后推进
#   timeout        固定节拍数后推进
AdvanceMode = Literal["every_tick", "all_submitted", "timeout"]


@dataclass(frozen=True)
class PhaseSpec:
    """回合内的一个阶段。"""

    id: str
    name: str = ""
    actors: Actors = "all"
    # 阶段级布尔/枚举标志，语义由场景解释（如 {tradable: true}）。OS 不解释。
    flags: Dict[str, Any] = field(default_factory=dict)
    description: str = ""


@dataclass(frozen=True)
class AdvanceRule:
    mode: AdvanceMode = "every_tick"
    timeout_ticks: Optional[int] = None


@dataclass(frozen=True)
class PacingSpec:
    """相邻 tick 之间的真实时间节奏（OS 通用，不认识业务含义）。

    - buffer_backpressure（默认，当前行为）：tick 尽快计算，节奏只由播放缓冲
      背压控制，一局在几秒内算完。
    - wall_clock：相邻 tick 的起点至少间隔 ``tick_seconds`` 真实秒，让"实时数据"
      在 tick 之间真正发生变化（实时场景需要）。OS 只按声明执行真实时间间隔。

    未声明 pacing 时回退到 buffer_backpressure，保证对既有场景零回归。
    """

    mode: str = "buffer_backpressure"
    tick_seconds: float = 0.0

    @property
    def is_wall_clock(self) -> bool:
        return self.mode == "wall_clock" and self.tick_seconds > 0


@dataclass(frozen=True)
class LiveWindowSpec:
    """实时场景允许交易的时间窗（通用：时区 + 星期 + 每日时间段）。

    OS 只做"现在是否落在任一时段内"的通用判断，不认识它是不是股市交易时段。
    未声明（空）= 永远开放，保证对既有场景零回归。

    注意：本窗口用于约束「此刻能否成交」(tradable)，默认不拦截开局。
    盘前开局后，到窗口开放时刻即可下单。
    """

    timezone: str = ""
    weekdays: Tuple[int, ...] = ()          # 1=周一 .. 7=周日；空=不限
    ranges: Tuple[str, ...] = ()            # ("09:30-11:30", ...)；空=不限
    closed_message: str = "当前不在允许的交易时段"

    def is_open(self, now: Optional[datetime] = None) -> Tuple[bool, str]:
        """现在是否可交易；返回 (是否开放, 关闭原因文案)。"""
        if not self.ranges and not self.weekdays:
            return True, ""
        tz = None
        if self.timezone:
            try:
                from zoneinfo import ZoneInfo
                tz = ZoneInfo(self.timezone)
            except Exception:
                tz = None
        current = now or datetime.now(tz)
        if tz is not None and current.tzinfo is None:
            current = current.replace(tzinfo=tz)
        if self.weekdays and current.isoweekday() not in self.weekdays:
            return False, self.closed_message
        if self.ranges:
            minute_of_day = current.hour * 60 + current.minute
            for window in self.ranges:
                start_raw, _, end_raw = str(window).partition("-")
                try:
                    sh, sm = (int(part) for part in start_raw.split(":"))
                    eh, em = (int(part) for part in end_raw.split(":"))
                except ValueError:
                    continue
                if sh * 60 + sm <= minute_of_day <= eh * 60 + em:
                    return True, ""
            return False, self.closed_message
        return True, ""


@dataclass(frozen=True)
class RoundModel:
    """场景声明的回合/时钟模型。"""

    # 回合单位的业务名（"turn" / "market_phase" / "night_day" …）。OS 只透传。
    unit: str = "tick"
    phases: List[PhaseSpec] = field(default_factory=list)
    advance: AdvanceRule = field(default_factory=AdvanceRule)
    # 循环标签（如"交易日"）；tick→阶段用 (tick-1) % len(phases) 由 OS 统一执行，
    # 取代当前场景插件里各自取模。
    cycle_label: str = ""
    # tick 之间的真实时间节奏（默认 buffer_backpressure = 当前行为）。
    pacing: PacingSpec = field(default_factory=PacingSpec)
    # 允许开局的实时时间窗（默认空 = 永远开放）。
    live_window: LiveWindowSpec = field(default_factory=LiveWindowSpec)
    # 声明式来源标记：True = 用了默认同步模型（无 clock.yaml）。
    is_default_synchronous: bool = False

    def phase_for_tick(self, tick: int) -> Optional[PhaseSpec]:
        """OS 统一的 tick→阶段映射（唯一真相来源，取代插件取模）。"""
        if not self.phases:
            return None
        index = (max(1, int(tick or 1)) - 1) % len(self.phases)
        return self.phases[index]

    def cycle_for_tick(self, tick: int) -> int:
        if not self.phases:
            return 1
        return ((max(1, int(tick or 1)) - 1) // len(self.phases)) + 1


# 默认同步回合模型：单阶段、全员每拍行动、每拍推进。
# 等价于当前 OS 的隐含行为——场景无 clock.yaml 时回退到它，保证零回归。
DEFAULT_SYNCHRONOUS_ROUND_MODEL = RoundModel(
    unit="tick",
    phases=[PhaseSpec(id="act", name="行动", actors="all")],
    advance=AdvanceRule(mode="every_tick"),
    is_default_synchronous=True,
)


def load_round_model(scenario_dir: str | Path) -> RoundModel:
    """从 world/clock.yaml 加载回合模型；缺失则返回默认同步模型（零回归）。"""
    path = Path(scenario_dir) / "world" / "clock.yaml"
    if not path.is_file():
        return DEFAULT_SYNCHRONOUS_ROUND_MODEL
    raw = yaml.safe_load(path.read_text(encoding="utf-8")) or {}
    data = raw.get("clock", raw) if isinstance(raw, dict) else {}
    if not isinstance(data, dict) or not data.get("phases"):
        return DEFAULT_SYNCHRONOUS_ROUND_MODEL

    phases = [
        PhaseSpec(
            id=str(item.get("id") or ""),
            name=str(item.get("name") or item.get("id") or ""),
            actors=item.get("actors", "all"),
            flags=dict(item.get("flags") or {}),
            description=str(item.get("description") or ""),
        )
        for item in data.get("phases", [])
        if isinstance(item, dict) and item.get("id")
    ]
    if not phases:
        return DEFAULT_SYNCHRONOUS_ROUND_MODEL

    advance_raw = data.get("advance") or {}
    if isinstance(advance_raw, str):
        advance = AdvanceRule(mode=advance_raw)  # type: ignore[arg-type]
    else:
        advance = AdvanceRule(
            mode=str(advance_raw.get("mode") or "every_tick"),  # type: ignore[arg-type]
            timeout_ticks=advance_raw.get("timeout_ticks"),
        )

    pacing_raw = data.get("pacing") or {}
    if isinstance(pacing_raw, dict):
        pacing = PacingSpec(
            mode=str(pacing_raw.get("mode") or "buffer_backpressure"),
            tick_seconds=float(pacing_raw.get("tick_seconds") or 0.0),
        )
    else:
        pacing = PacingSpec()

    window_raw = data.get("live_window") or {}
    if isinstance(window_raw, dict) and window_raw:
        live_window = LiveWindowSpec(
            timezone=str(window_raw.get("timezone") or ""),
            weekdays=tuple(int(x) for x in (window_raw.get("weekdays") or [])),
            ranges=tuple(str(x) for x in (window_raw.get("ranges") or [])),
            closed_message=str(
                window_raw.get("closed_message") or "当前不在允许的开局时段"
            ),
        )
    else:
        live_window = LiveWindowSpec()

    return RoundModel(
        unit=str(data.get("unit") or "tick"),
        phases=phases,
        advance=advance,
        cycle_label=str(data.get("cycle_label") or ""),
        pacing=pacing,
        live_window=live_window,
    )
