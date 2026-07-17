"""
PresentationBuffer — 计算-表现分离的缓冲队列模块

计算循环（Engine tick）产出的表现数据通过 push() 推入有界队列，
播放循环按 DirectorPlan segment 的 duration_ms 消费并广播到 WebSocket，
实现计算与呈现的异步解耦，支持暂停/恢复/单步调试。
"""
from __future__ import annotations

import asyncio
import logging
import random
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Callable, Coroutine, Dict, List, Optional

logger = logging.getLogger(__name__)

BroadcastFn = Callable[[str, Dict[str, Any]], Coroutine]


class BufferHealth(str, Enum):
    """PresentationBuffer 健康度 6 级状态"""

    EXCELLENT = "excellent"  # buffer >= 80% 满
    GOOD = "good"            # buffer 50-79%
    WARNING = "warning"      # buffer 25-49%
    CRITICAL = "critical"    # buffer 只剩 1 个
    EMPTY = "empty"          # buffer 空，正在等待
    OVERFLOW = "overflow"    # push 被阻塞（背压触发）


@dataclass
class PresentationSegment:
    """一段可顺序执行的舞台指令。"""
    kind: str
    duration_ms: int
    payload: Dict[str, Any] = field(default_factory=dict)


@dataclass
class PresentationPlan:
    """CommittedTick 对应的不可变播放计划。"""
    tick: int
    segments: List[PresentationSegment] = field(default_factory=list)
    estimated_duration_ms: int = 0


@dataclass
class TickPackage:
    """兼容名称：一个已提交 Tick 及其完整播放计划。"""

    tick: int
    world_snapshot: Dict[str, Any]  # 世界快照（已序列化的 dict）
    audio_b64: Optional[str] = None  # TTS 音频 base64
    audio_chunks: List[Dict[str, Any]] = field(default_factory=list)
    agent_logs: List[Dict[str, Any]] = field(default_factory=list)
    ledger_snapshot: Optional[Dict[str, Any]] = None
    narration_comment: str = ""  # TTS 对应的字幕文本
    director_plan: Optional[Dict[str, Any]] = None
    director_harness_trace: Optional[Dict[str, Any]] = None
    presentation_plan: Optional[PresentationPlan] = None
    committed_at_ms: int = 0
    # 运行时门控：后台"导演润色 + 分块 TTS"完成后置位。
    # 未完成前 plan 里是 challenge_per_agent 原始帧（含 JSON/字段、无音频），
    # 播放侧必须等它就绪再呈现，否则字幕是机器文本且无 TTS。不参与序列化。
    enriched_ready: Optional[Any] = field(default=None, compare=False, repr=False)

    @property
    def estimated_duration_ms(self) -> int:
        if self.presentation_plan is None:
            return 0
        return max(1, self.presentation_plan.estimated_duration_ms)

    def to_dict(self) -> Dict[str, Any]:
        plan = self.presentation_plan
        return {
            "tick": self.tick,
            "world_snapshot": self.world_snapshot,
            "audio_b64": self.audio_b64,
            "audio_chunks": self.audio_chunks,
            "agent_logs": self.agent_logs,
            "ledger_snapshot": self.ledger_snapshot,
            "narration_comment": self.narration_comment,
            "director_plan": self.director_plan,
            "director_harness_trace": self.director_harness_trace,
            "presentation_plan": {
                "tick": plan.tick,
                "estimated_duration_ms": plan.estimated_duration_ms,
                "segments": [
                    {
                        "kind": segment.kind,
                        "duration_ms": segment.duration_ms,
                        "payload": segment.payload,
                    }
                    for segment in plan.segments
                ],
            } if plan else None,
            "committed_at_ms": self.committed_at_ms,
        }

    @classmethod
    def from_dict(cls, data: Dict[str, Any]) -> "TickPackage":
        raw_plan = data.get("presentation_plan")
        plan = None
        if raw_plan:
            plan = PresentationPlan(
                tick=int(raw_plan.get("tick", data.get("tick", 0))),
                estimated_duration_ms=int(
                    raw_plan.get("estimated_duration_ms", 0) or 0
                ),
                segments=[
                    PresentationSegment(
                        kind=str(item.get("kind", "")),
                        duration_ms=max(
                            1, int(item.get("duration_ms", 1) or 1)
                        ),
                        payload=dict(item.get("payload") or {}),
                    )
                    for item in raw_plan.get("segments", [])
                ],
            )
        return cls(
            tick=int(data.get("tick", 0)),
            world_snapshot=dict(data.get("world_snapshot") or {}),
            audio_b64=data.get("audio_b64"),
            audio_chunks=list(data.get("audio_chunks") or []),
            agent_logs=list(data.get("agent_logs") or []),
            ledger_snapshot=data.get("ledger_snapshot"),
            narration_comment=str(data.get("narration_comment", "")),
            director_plan=(
                dict(data.get("director_plan") or {})
                if data.get("director_plan") else None
            ),
            director_harness_trace=(
                dict(data.get("director_harness_trace") or {})
                if data.get("director_harness_trace") else None
            ),
            presentation_plan=plan,
            committed_at_ms=int(data.get("committed_at_ms", 0) or 0),
        )


class PresentationBuffer:
    """
    缓冲队列 + 播放控制器

    计算循环通过 push() 将 TickPackage 推入队列（队列满时阻塞）。
    播放循环按 DirectorPlan segment 的 duration_ms 消费并广播到 WebSocket。
    """

    def __init__(
        self,
        broadcast_fn: BroadcastFn,
        max_buffer: int = 3,
        max_buffer_ms: int = 90000,
        min_tick_duration: float = 3.0,
        startup_buffer_ms: int = 0,
        startup_buffer_ticks: int = 0,
        resume_buffer_ms: int = 0,
        health_thresholds: Optional[Dict[str, int]] = None,
        speed_policy: Optional[Dict[str, float]] = None,
        playout_delay_ms: int = 0,
    ):
        """
        OBS 推流模型缓冲：
          - 后台无阻塞生产（容量按 max_buffer_ms 时长封顶，不按 tick 数量）
          - 前台等到 startup_buffer_ms 才开播
          - 每个 segment 出库时携带绝对 play_at_ms，前端按时间轴严格同步
        """
        self._queue: asyncio.Queue[TickPackage] = asyncio.Queue(maxsize=max_buffer)
        self._broadcast = broadcast_fn
        self._playing = False
        self._play_task: Optional[asyncio.Task] = None
        self._min_tick_duration = min_tick_duration
        self._startup_buffer_ms = max(0, int(startup_buffer_ms))
        self._startup_buffer_ticks = max(0, int(startup_buffer_ticks))
        self._resume_buffer_ms = max(0, int(resume_buffer_ms))
        self._max_buffer_ms = max(self._startup_buffer_ms, int(max_buffer_ms))
        self._buffered_duration_ms = 0
        self._playback_started = (
            self._startup_buffer_ms == 0 and self._startup_buffer_ticks == 0
        )
        # OBS 时间轴：前台开播时刻（毫秒 epoch），所有 segment 的 play_at_ms 以此为基准累加
        self._playout_started_at_ms: int = 0
        self._next_play_offset_ms: int = 0
        self._source_complete = False
        self._completion_announced = False
        self._watermark_changed = asyncio.Event()
        self._health_thresholds = {
            str(key): max(0, int(value))
            for key, value in (health_thresholds or {}).items()
        }
        self._speed_policy = {
            str(key): max(0.1, float(value))
            for key, value in (speed_policy or {}).items()
        }
        self._playout_delay_ms = max(0, int(playout_delay_ms))
        self._last_commit_ms = 0
        self._producer_interval_ms = 0.0
        self._last_package: Optional[TickPackage] = None
        self._tracked_package_ids: set[int] = set()
        self._paused = asyncio.Event()
        self._paused.set()  # 初始为非暂停（set = 可以继续）

        # 健康度监控 & 动态降级
        self._overflow_flag: bool = False
        self._speed_factor: float = 1.0
        self._empty_wait_count: int = 0

    @property
    def buffer_size(self) -> int:
        return self._queue.qsize()

    @property
    def _natural_lead_floor(self) -> int:
        """缓冲存量达到此 tick 数即视为"领先充足"。

        领先充足时按各 tick 的自然时长密集播放，不再把每个 tick 拉伸到
        （较慢的）生产节拍——这是"播放不流畅/空播"的根因。低于此线时恢复
        生产节拍拉伸，配合健康度降速，防止追平生产侧造成卡顿。
        """
        return max(2, self._queue.maxsize // 2)

    @property
    def maxsize(self) -> int:
        return self._queue.maxsize

    @property
    def buffered_duration_ms(self) -> int:
        return self._buffered_duration_ms

    @property
    def playback_started(self) -> bool:
        return self._playback_started

    @property
    def is_playing(self) -> bool:
        return self._playing

    @property
    def health(self) -> BufferHealth:
        """根据可播放时长而不是 tick 数计算健康度。"""
        if self._overflow_flag:
            return BufferHealth.OVERFLOW
        buffered = self._buffered_duration_ms
        if buffered <= 0:
            return BufferHealth.EMPTY
        if self._health_thresholds:
            empty_at = self._health_thresholds.get("empty", 0)
            critical_at = self._health_thresholds.get(
                "critical", self._resume_buffer_ms
            )
            warning_at = self._health_thresholds.get(
                "warning", self._startup_buffer_ms
            )
            good_at = self._health_thresholds.get("good", warning_at)
            excellent_at = self._health_thresholds.get(
                "excellent", max(self._startup_buffer_ms, 1) * 2
            )
            if buffered <= empty_at:
                return BufferHealth.EMPTY
            if buffered < critical_at:
                return BufferHealth.CRITICAL
            if buffered < warning_at:
                return BufferHealth.CRITICAL
            if buffered < good_at:
                return BufferHealth.WARNING
            if buffered >= excellent_at:
                return BufferHealth.EXCELLENT
            return BufferHealth.GOOD
        if self._resume_buffer_ms and buffered < self._resume_buffer_ms:
            return BufferHealth.CRITICAL
        target = max(self._startup_buffer_ms, self._resume_buffer_ms, 1)
        if buffered >= target * 1.5:
            return BufferHealth.EXCELLENT
        if buffered >= target:
            return BufferHealth.GOOD
        return BufferHealth.WARNING

    def _adjust_speed(self) -> None:
        """根据健康度动态调整播放速度（实时自适应配速）

        核心目标：buffer 将空时自动放慢播放、变深时加快，永不抽干到 0。
        speed_factor 越小 → 每帧 sleep 越长 → 播放越慢 → 给计算侧争取补仓时间。
        """
        h = self.health
        if h == BufferHealth.OVERFLOW:
            self._speed_factor = self._speed_policy.get("overflow", 1.15)
        elif h == BufferHealth.EXCELLENT:
            self._speed_factor = self._speed_policy.get("excellent", 1.1)
        elif h == BufferHealth.GOOD:
            self._speed_factor = self._speed_policy.get("good", 1.0)
        elif h == BufferHealth.WARNING:
            self._speed_factor = self._speed_policy.get("warning", 0.8)
        elif h == BufferHealth.CRITICAL:
            self._speed_factor = self._speed_policy.get("critical", 0.55)
        elif h == BufferHealth.EMPTY:
            self._speed_factor = self._speed_policy.get("empty", 0.55)

    async def push(self, package: TickPackage) -> bool:
        """
        计算循环调用 — 保序推入。

        队列满时施加背压，等待播放侧腾出空间。已经完成计算的 Tick
        绝不允许丢弃，否则表现时间线会与真实世界状态永久分叉。
        
        Returns:
            True: 成功推入
            False: 保留兼容签名，当前实现不会返回 False
        """
        if package.presentation_plan is None:
            raise ValueError(
                f"tick {package.tick} missing authoritative presentation_plan"
            )
        now_ms = int(time.time() * 1000)
        if package.committed_at_ms <= 0:
            package.committed_at_ms = now_ms
        if self._last_commit_ms > 0:
            interval = max(1, package.committed_at_ms - self._last_commit_ms)
            self._producer_interval_ms = (
                interval if self._producer_interval_ms <= 0
                else self._producer_interval_ms * 0.65 + interval * 0.35
            )
            # 领先充足或已接近时长上限时跳过生产节拍拉伸。
            # 此处 buffer_size 尚不含本 package（put 在下方），反映既有领先量。
            near_cap = (
                self._max_buffer_ms > 0
                and self._buffered_duration_ms >= int(self._max_buffer_ms * 0.5)
            )
            healthy_lead = self.buffer_size >= self._natural_lead_floor or near_cap
            if self._last_package is not None and not healthy_lead:
                previous_duration = self._last_package.estimated_duration_ms
                self._stretch_package_to_duration(
                    self._last_package,
                    min(90000, int(interval * 1.0)),
                    mode="commit_bridge",
                )
                self.notify_package_duration_change(
                    self._last_package, previous_duration
                )
            if not healthy_lead:
                self._stretch_plan_to_producer_rate(package)
        self._last_commit_ms = package.committed_at_ms
        self._last_package = package

        # 时长背压：max_buffer_ms 此前只广播不生效，导致引擎可持续领先数分钟。
        while (
            self._playing
            and self._max_buffer_ms > 0
            and self._buffered_duration_ms >= self._max_buffer_ms
        ):
            self._overflow_flag = True
            logger.warning(
                "[Buffer] 演绎缓冲超限，计算侧等待背压释放 "
                "(ahead=%sms/%sms, tick=%s)",
                self._buffered_duration_ms,
                self._max_buffer_ms,
                package.tick,
            )
            self._watermark_changed.clear()
            try:
                await asyncio.wait_for(self._watermark_changed.wait(), timeout=0.5)
            except asyncio.TimeoutError:
                pass

        if self._queue.full():
            self._overflow_flag = True
            logger.warning(
                f"[Buffer] 队列已满，计算侧等待背压释放 "
                f"(size={self._queue.qsize()}/{self._queue.maxsize}, tick={package.tick})"
            )
        await self._queue.put(package)
        self._tracked_package_ids.add(id(package))
        self._buffered_duration_ms += package.estimated_duration_ms
        self._completion_announced = False
        self._watermark_changed.set()
        self._overflow_flag = False
        logger.debug(f"[Buffer] push tick={package.tick}, queue_size={self._queue.qsize()}")
        return True

    def start_playback(self) -> None:
        """启动播放循环"""
        if self._play_task and not self._play_task.done():
            return  # 已在运行
        self._playing = True
        self._paused.set()
        self._play_task = asyncio.create_task(self._play_loop())
        logger.info("[Buffer] 播放循环已启动")

    def mark_source_complete(self) -> None:
        """计算时间线已经结束；允许不足启动水位的尾部计划播完。"""
        self._source_complete = True
        self._watermark_changed.set()

    def pause_playback(self) -> None:
        """暂停播放（完成当前帧后暂停）"""
        self._paused.clear()
        logger.info("[Buffer] 播放已暂停")

    def resume_playback(self) -> None:
        """恢复播放"""
        self._paused.set()
        logger.info("[Buffer] 播放已恢复")

    async def step_one(self) -> bool:
        """单步：播放 buffer 中的下一个包。若 buffer 为空返回 False"""
        if self._queue.empty():
            return False
        package = self._queue.get_nowait()
        self._tracked_package_ids.discard(id(package))
        self._buffered_duration_ms = max(
            0, self._buffered_duration_ms - package.estimated_duration_ms
        )
        await self._present_tick(package)
        return True

    def stop(self) -> None:
        """停止播放循环"""
        self._playing = False
        self._paused.set()  # 确保不卡在 wait
        if self._play_task and not self._play_task.done():
            self._play_task.cancel()
        logger.info("[Buffer] 播放循环已停止")

    def clear(self) -> None:
        """清空队列"""
        while not self._queue.empty():
            try:
                package = self._queue.get_nowait()
                self._buffered_duration_ms = max(
                    0,
                    self._buffered_duration_ms - package.estimated_duration_ms,
                )
            except asyncio.QueueEmpty:
                break
        self._playback_started = (
            self._startup_buffer_ms == 0 and self._startup_buffer_ticks == 0
        )
        self._source_complete = False
        self._completion_announced = False
        self._last_commit_ms = 0
        self._producer_interval_ms = 0.0
        self._last_package = None
        self._tracked_package_ids.clear()
        logger.info("[Buffer] 队列已清空")

    async def _play_loop(self) -> None:
        """
        播放主循环 — 按节奏消费队列。
        
        关键改进：
        1. empty 时不暂停，持续尝试获取（保持播放状态）
        2. 减少 waiting 消息频率（从 1s 改为 3s）
        3. 保持最后一帧的视觉连续性
        """
        try:
            while self._playing:
                # 等待暂停解除
                await self._paused.wait()

                if not self._playing:
                    break

                if not self._playback_started:
                    if self._startup_buffer_ticks > 0:
                        ready = (
                            self._queue.qsize() >= self._startup_buffer_ticks
                            or (
                                self._source_complete
                                and not self._queue.empty()
                            )
                        )
                    else:
                        ready = (
                            self._buffered_duration_ms >= self._startup_buffer_ms
                            or (
                                self._source_complete
                                and self._buffered_duration_ms > 0
                            )
                        )
                    if not ready:
                        await self._broadcast_watermark_status("preparing")
                        self._watermark_changed.clear()
                        try:
                            await asyncio.wait_for(
                                self._watermark_changed.wait(), timeout=0.5
                            )
                        except asyncio.TimeoutError:
                            pass
                        continue
                    self._playback_started = True
                    # OBS 时间轴起点：从这一刻起所有 segment 的 play_at_ms 累加
                    self._playout_started_at_ms = int(time.time() * 1000)
                    self._next_play_offset_ms = 0
                    logger.info(
                        "[Buffer] 预缓冲完成，开播时刻=%s，已蓄水=%sms",
                        self._playout_started_at_ms,
                        self._buffered_duration_ms,
                    )
                    # 通知前端：开播时刻锚点 + 本地时钟同步
                    await self._broadcast("viewer", {
                        "type": "playout_started",
                        "playout_started_at_ms": self._playout_started_at_ms,
                        "server_now_ms": self._playout_started_at_ms,
                        "buffered_ahead_ms": self._buffered_duration_ms,
                    })
                    await self._broadcast_watermark_status("playing")

                if (
                    self._resume_buffer_ms > 0
                    and not self._source_complete
                    and self._buffered_duration_ms < self._resume_buffer_ms
                ):
                    await self._broadcast_watermark_status("rebuffering")
                    self._watermark_changed.clear()
                    try:
                        await asyncio.wait_for(
                            self._watermark_changed.wait(), timeout=1.0
                        )
                    except asyncio.TimeoutError:
                        pass
                    continue

                try:
                    # 等待下一个包（timeout 缩短到 0.3s，更快响应新数据）
                    package = await asyncio.wait_for(self._queue.get(), timeout=0.3)
                except asyncio.TimeoutError:
                    # 已经播完后保持静默，避免结束画面再次出现“思考中”
                    # 或等待动画，让观众误以为时间线正在循环。
                    if self._source_complete and self._queue.empty():
                        self._empty_wait_count = 0
                        self._watermark_changed.clear()
                        try:
                            await asyncio.wait_for(
                                self._watermark_changed.wait(), timeout=1.0
                            )
                        except asyncio.TimeoutError:
                            pass
                        continue
                    # 计算尚未结束且队列为空 — 降低 waiting 消息频率
                    self._empty_wait_count += 1
                    if self._empty_wait_count >= 10:  # 0.3s * 10 = 3s 才发送一次
                        await self._broadcast_waiting_status()
                        self._empty_wait_count = 0
                    # 关键：不 break/continue，继续循环尝试获取
                    continue

                await self._wait_for_playout_time(package)

                # 成功取到包，重置空等计数并调整播放速度
                self._empty_wait_count = 0
                self._adjust_speed()
                self._tracked_package_ids.discard(id(package))
                self._buffered_duration_ms = max(
                    0,
                    self._buffered_duration_ms - package.estimated_duration_ms,
                )

                await self._present_tick(package)
                if (
                    self._source_complete
                    and self._queue.empty()
                    and not self._completion_announced
                ):
                    self._completion_announced = True
                    await self._broadcast("viewer", {
                        "type": "playout_complete",
                        "tick": package.tick,
                    })
        except asyncio.CancelledError:
            logger.info("[Buffer] 播放循环被取消")
        except Exception as e:
            logger.error(f"[Buffer] 播放循环异常: {e}", exc_info=True)

    async def _present_tick(self, pkg: TickPackage) -> None:
        """
        OBS 推流模型：按绝对时间轴广播 segment，画面/字幕/TTS 共享 play_at_ms。
        """
        logger.info("[Buffer] 开始播放 DirectorPlan tick=%s", pkg.tick)
        tick_start = asyncio.get_event_loop().time()

        plan = pkg.presentation_plan
        if plan is None:
            raise RuntimeError(
                f"tick {pkg.tick} has no authoritative presentation plan"
            )
        # tick 起点：当前累计 offset
        tick_play_at_ms = self._playout_started_at_ms + self._next_play_offset_ms
        await self._broadcast("viewer", {
            "type": "presentation_tick_start",
            "tick": pkg.tick,
            "estimated_duration_ms": pkg.estimated_duration_ms,
            "segment_count": len(plan.segments),
            "play_at_ms": tick_play_at_ms,
            "playout_started_at_ms": self._playout_started_at_ms,
        })

        segments = plan.segments

        # tick 末快照：作为本 tick 最后一个 segment 的同锚点画面状态
        final_snapshot = pkg.world_snapshot or {}

        narration_index = 0
        for seg_idx, segment in enumerate(segments):
            await self._paused.wait()
            if self._play_task is not None and not self._playing:
                return

            payload = segment.payload or {}
            is_last_segment = seg_idx == len(segments) - 1
            if self.health in (BufferHealth.CRITICAL, BufferHealth.EMPTY):
                if (
                    not is_last_segment
                    and bool(payload.get("can_skip"))
                ):
                    logger.debug(
                        "[Buffer] 降级跳过 low importance 段 tick=%s kind=%s",
                        pkg.tick,
                        segment.kind,
                    )
                    if (
                        segment.kind == "render_command"
                        and str(payload.get("command_type") or "") in {"subtitle", "ui"}
                        and str((payload.get("parameters") or {}).get("text") or "")
                    ):
                        narration_index += 1
                    continue

            # ━━ 关键：本 segment 的绝对播放时刻 ━━
            seg_play_at_ms = self._playout_started_at_ms + self._next_play_offset_ms

            # 计算本段有效时长（TTS 优先，写死的 duration_ms 兜底）
            narration_text = ""
            tts_chunk_audio = None
            chunk_payload: Optional[Dict[str, Any]] = None
            is_spoken_segment = False
            if segment.kind == "render_command":
                command_type = str(payload.get("command_type") or "")
                command_text = str((payload.get("parameters") or {}).get("text") or "")
                is_spoken_segment = command_type in {"subtitle", "ui"} and bool(command_text)
            if is_spoken_segment:
                narration_text = str((payload.get("parameters") or {}).get("text") or "")
            if is_spoken_segment and narration_index < len(pkg.audio_chunks):
                chunk_payload = pkg.audio_chunks[narration_index]
                tts_chunk_audio = chunk_payload.get("audio_b64")
            tts_estimated_ms = 0
            if tts_chunk_audio and narration_text:
                char_count = len(str(narration_text).strip())
                tts_estimated_ms = max(600, char_count * 210)
            base_ms = max(1, segment.duration_ms)
            effective_ms = max(base_ms, tts_estimated_ms + 150)

            # ━━ 同锚点同步广播：画面+字幕+TTS 共用 play_at_ms ━━
            # 首段即挂上本拍已提交快照，避免导演旁白讲本拍时盘面仍停在上一拍。
            seg_msg = {
                "type": "presentation_segment",
                "tick": pkg.tick,
                "play_at_ms": seg_play_at_ms,
                "segment": {
                    "kind": segment.kind,
                    "duration_ms": effective_ms,
                    "payload": payload,
                },
            }
            if final_snapshot and (seg_idx == 0 or is_last_segment):
                seg_msg["world_snapshot"] = final_snapshot
            await self._broadcast("viewer", seg_msg)

            if chunk_payload is not None:
                public_chunk = dict(chunk_payload)
                if public_chunk.get("text"):
                    from app.engine.presentation.audience_guard import AudienceTextGuard
                    public_chunk["text"] = AudienceTextGuard().clean(
                        public_chunk["text"],
                        fallback="本回合结果已经记录。",
                    )
                await self._broadcast("viewer", {
                    "type": "narration_chunk",
                    "tick": pkg.tick,
                    "index": narration_index,
                    "play_at_ms": seg_play_at_ms,
                    "duration_ms": effective_ms,
                    **public_chunk,
                })
            if is_spoken_segment:
                narration_index += 1

            # ━━ 时间轴推进：累加而非"睡 sleep"，由"睡到绝对时刻"驱动 ━━
            self._next_play_offset_ms += effective_ms
            target_play_at_ms = self._playout_started_at_ms + self._next_play_offset_ms
            await self._sleep_until(target_play_at_ms)

        # 独立快照消息供实时状态消费者使用；与末段共享时间轴。
        if final_snapshot:
            await self._broadcast("viewer", {
                "type": "world_snapshot",
                "tick": pkg.tick,
                "play_at_ms": self._playout_started_at_ms + self._next_play_offset_ms,
                **final_snapshot,
            })

        # tick 末汇总消息
        await self._broadcast("viewer", {
            "type": "presentation_tick_end",
            "tick": pkg.tick,
            "play_at_ms": self._playout_started_at_ms + self._next_play_offset_ms,
        })
        logger.info(
            f"[Buffer] tick={pkg.tick} 已播完 offset={self._next_play_offset_ms}ms "
            f"buffered_ahead={self._buffered_duration_ms}ms"
        )

        # 4. 广播 Agent 日志（给 operator 频道）
        for log in pkg.agent_logs:
            await self._broadcast("operator", {"type": "agent_log", **log})

        # 5. 广播账本摘要（给 operator 频道）
        if pkg.ledger_snapshot:
            await self._broadcast("operator", {
                "type": "ledger_snapshot",
                "tick": pkg.tick,
                **pkg.ledger_snapshot,
            })

        # 6. 确保每个 tick 至少持续 min_tick_duration / speed_factor 秒
        elapsed = asyncio.get_event_loop().time() - tick_start
        remaining = (self._min_tick_duration / self._speed_factor) - elapsed
        if remaining > 0:
            await asyncio.sleep(remaining)

        # 7. 广播 buffer 健康状态
        await self._broadcast("viewer", {
            "type": "buffer_health",
            "health": self.health.value,
            "buffer_size": self.buffer_size,
            "buffer_ahead_ms": self._buffered_duration_ms,
            "speed_factor": self._speed_factor,
        })

        logger.debug(f"[Buffer] 播放完成 tick={pkg.tick}, 耗时={elapsed:.1f}s")

    async def _sleep_until(self, target_ms: int) -> None:
        """
        睡到指定的绝对毫秒时刻。
        相比累加 sleep(duration)，这种方式让 segment 之间漂移不会累积。
        如果已经过点（处理慢了），立刻返回，不阻塞。
        """
        if target_ms <= 0:
            return
        # speed_factor 控制相对节奏（健康度自适应）：>1 加快，<1 放慢
        speed = self._speed_factor if self._speed_factor > 0 else 1.0
        while self._playing:
            now_ms = int(time.time() * 1000)
            remaining_ms = (target_ms - now_ms) / speed
            if remaining_ms <= 0:
                return
            # 切成小片睡，避免暂停指令响应不及时
            await asyncio.sleep(min(0.25, remaining_ms / 1000.0))

    async def _broadcast_watermark_status(self, state: str) -> None:
        # 启动期进度（0-100%）：让前端蒙层显示"已缓冲 N/30 秒"
        startup_progress = 0.0
        if self._startup_buffer_ms > 0:
            startup_progress = min(
                1.0, self._buffered_duration_ms / self._startup_buffer_ms
            )
        await self._broadcast("viewer", {
            "type": "playout_status",
            "state": state,
            "buffer_ahead_ms": self._buffered_duration_ms,
            "buffer_size": self.buffer_size,
            "max_buffer_ms": self._max_buffer_ms,
            "startup_buffer_ms": self._startup_buffer_ms,
            "startup_buffer_ticks": self._startup_buffer_ticks,
            "startup_progress": startup_progress,
            "resume_buffer_ms": self._resume_buffer_ms,
            "playout_delay_ms": self._playout_delay_ms,
            "playout_started_at_ms": self._playout_started_at_ms,
            "producer_interval_ms": round(self._producer_interval_ms),
            "simulation_complete": self._source_complete,
        })

    async def _wait_for_playout_time(self, package: TickPackage) -> None:
        if self._playout_delay_ms <= 0 or package.committed_at_ms <= 0:
            return
        eligible_at = package.committed_at_ms + self._playout_delay_ms
        while self._playing:
            remaining_ms = eligible_at - int(time.time() * 1000)
            if remaining_ms <= 0:
                return
            await self._broadcast_watermark_status("delayed_live")
            await asyncio.sleep(min(0.5, remaining_ms / 1000.0))

    def _stretch_plan_to_producer_rate(self, package: TickPackage) -> None:
        """让故事消费速率略慢于近期世界产出速率，维持时间差。"""
        plan = package.presentation_plan
        if not plan or self._producer_interval_ms <= 0:
            return
        target_ms = min(
            90000,
            max(plan.estimated_duration_ms, int(self._producer_interval_ms * 1.0)),
        )
        self._stretch_package_to_duration(
            package, target_ms, mode="adaptive_bridge"
        )

    def notify_package_duration_change(
        self, package: TickPackage, previous_duration_ms: int
    ) -> None:
        """后期任务修改尚未开播的故事包时，同步修正可播放库存。"""
        if id(package) not in self._tracked_package_ids:
            return
        delta = package.estimated_duration_ms - previous_duration_ms
        if delta:
            self._buffered_duration_ms = max(
                0, self._buffered_duration_ms + delta
            )
            self._watermark_changed.set()

    @staticmethod
    def _stretch_package_to_duration(
        package: TickPackage,
        target_ms: int,
        *,
        mode: str,
    ) -> None:
        plan = package.presentation_plan
        if not plan:
            return
        missing = target_ms - plan.estimated_duration_ms
        if missing <= 0:
            return
        plan.segments.append(PresentationSegment(
            kind="world_observation",
            duration_ms=missing,
            payload={
                "importance": "normal",
                "mode": mode,
            },
        ))
        plan.estimated_duration_ms = target_ms

    async def _broadcast_waiting_status(self) -> None:
        """广播叙事化等待消息"""
        messages = [
            "AI 智能体正在深度推演中...",
            "世界正在运转，请稍候...",
            "智能体们正在思考下一步行动...",
            "因果链正在推导中...",
        ]
        await self._broadcast("viewer", {
            "type": "buffer_waiting",
            "message": random.choice(messages),
            "health": self.health.value,
            "buffer_size": self.buffer_size,
        })
