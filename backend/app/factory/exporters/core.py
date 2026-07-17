"""
五类导出器 + 编排。

输入:一批 run 目录。内部流程 = 模块1归一化 → 模块2质检(硬闸+分数) →
模块3去重 → 本模块按类抽取样本 → 双视图落盘。

五类(覆盖四种训练范式):
  1. SFT        优秀轨迹:高质量单步 (prompt→completion)
  2. DPO        偏好对:①失败修正(时序) ②同拍对照(情境),chosen/rejected
  3. RL Episode 整局 (obs, action, reward) 序列 + terminal
  4. Eval Set   能力评测集：挑战材料 + 确定答案 + 响应（验货锚）

每类产:
  <name>_train.jsonl  机器视图(纯技术,喂训练)
  <name>_cards.jsonl  人类视图(决策卡,验货)
两文件按 sample_id 对齐。
"""
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Dict, Iterable, List, Optional, Tuple

from app.factory.trajectory import Trajectory, TrajectoryStep, iter_trajectories
from app.factory.quality import TrajectoryQuality, score_trajectory
from app.factory.dedup import dedup_steps
from app.factory.sanitizer import sanitize_rows, SanitizeReport
from app.factory.exporters.cards import build_decision_card

logger = logging.getLogger(__name__)

# SFT 收样门槛:只学"做对且切中局面"的决策
SFT_MIN_SITUATIONAL_FIT = 0.6
SFT_MIN_STEP_SCORE = 0.55
# DPO 情境对照:同拍两 agent 的 situational_fit 差 ≥ 此值才成对
DPO_CONTRAST_MIN_GAP = 0.25


@dataclass
class ExportBundle:
    """一次导出的产物汇总(供 packager/UI 消费)。"""
    out_dir: str
    files: Dict[str, str] = field(default_factory=dict)   # 逻辑名 → 路径
    counts: Dict[str, int] = field(default_factory=dict)  # 逻辑名 → 样本数
    provenance: Dict[str, Any] = field(default_factory=dict)
    notes: List[str] = field(default_factory=list)
    sanitize: Dict[str, Any] = field(default_factory=dict)  # 模块5 脱敏审计


# ---------------------------------------------------------------------------
# 数据准备:归一化 + 质检 + 去重,一次算好供五类复用
# ---------------------------------------------------------------------------

@dataclass
class _PreparedRun:
    run_dirs: List[Path]
    traj_by_agent: Dict[str, Trajectory]
    quality_by_agent: Dict[str, TrajectoryQuality]
    step_quality: Dict[str, Any]          # sample_id → StepQuality
    clean_steps: List[TrajectoryStep]     # 全部干净局的干净步
    kept_ids: set                         # 去重后保留的 sample_id


def _prepare(run_dirs: Iterable[Path]) -> Tuple[_PreparedRun, Dict[str, Any]]:
    traj_by_agent: Dict[str, Trajectory] = {}
    quality_by_agent: Dict[str, TrajectoryQuality] = {}
    step_quality: Dict[str, Any] = {}
    clean_steps: List[TrajectoryStep] = []
    prov_runs: List[str] = []
    scenario_versions: set = set()
    engine_versions: set = set()

    normalized_run_dirs = [Path(item) for item in run_dirs]
    for run_dir in normalized_run_dirs:
        run_dir = Path(run_dir)
        prov_runs.append(run_dir.name)
        for traj in iter_trajectories(run_dir):
            key = f"{traj.run_id}:{traj.agent_id}"
            traj_by_agent[key] = traj
            q = score_trajectory(traj)
            quality_by_agent[key] = q
            for sq in q.step_quality:
                step_quality[sq.sample_id] = sq
            if traj.scenario_version:
                scenario_versions.add(traj.scenario_version)
            if traj.engine_version:
                engine_versions.add(traj.engine_version)
            if not q.is_clean:
                continue
            for s in traj.steps:
                if s.is_empty_action or s.is_fallback or not s.parsed_ok:
                    continue
                clean_steps.append(s)

    qmap = {sid: sq.score for sid, sq in step_quality.items()}
    dedup = dedup_steps(clean_steps, quality_by_id=qmap)

    prepared = _PreparedRun(
        run_dirs=normalized_run_dirs,
        traj_by_agent=traj_by_agent,
        quality_by_agent=quality_by_agent,
        step_quality=step_quality,
        clean_steps=clean_steps,
        kept_ids=set(dedup.kept_ids),
    )
    provenance = {
        "runs": prov_runs,
        "scenario_versions": sorted(scenario_versions),
        "engine_versions": sorted(engine_versions),
        "clean_steps": len(clean_steps),
        "dedup": {
            "kept": dedup.total_kept,
            "dropped": dedup.total_dropped,
            "dup_ratio": dedup.dup_ratio,
        },
    }
    return prepared, provenance


def _prov(step: TrajectoryStep, traj: Trajectory) -> Dict[str, Any]:
    return {
        "run_id": traj.run_id,
        "tick": step.tick,
        "agent_id": step.agent_id,
        "scenario_version": traj.scenario_version,
        "engine_version": traj.engine_version,
        "model": traj.model,
        "provider": traj.provider,
        "delta_ids": list(dict.fromkeys(step.delta_ids)),
    }


# 导出期共享的脱敏审计 + 领域规则(由 export_all 设置,exporter 落盘时消费)。
# 用模块级变量避免改动全部 exporter 签名——export_all 串行调用,无并发问题。
_SANITIZE_REPORT: SanitizeReport = SanitizeReport()
_DOMAIN_RULES: List[Dict[str, Any]] = []


def _write_jsonl(path: Path, rows: List[Dict[str, Any]]) -> None:
    """落盘前强制过模块5脱敏闸——凭证/身份不进任何训练文件。"""
    clean, rep = sanitize_rows(rows, _DOMAIN_RULES)
    _SANITIZE_REPORT.credential_hits += rep.credential_hits
    _SANITIZE_REPORT.dropped_keys += rep.dropped_keys
    _SANITIZE_REPORT.domain_transforms += rep.domain_transforms
    _SANITIZE_REPORT.samples_scanned += rep.samples_scanned
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8") as f:
        for r in clean:
            f.write(json.dumps(r, ensure_ascii=False) + "\n")


# ---------------------------------------------------------------------------
# 1. SFT
# ---------------------------------------------------------------------------

def export_sft(prepared: _PreparedRun, out_dir: Path) -> Tuple[List[Dict], List[Dict]]:
    """Export clean steps supported by positive scene settlement."""
    train: List[Dict] = []
    cards: List[Dict] = []
    for s in prepared.clean_steps:
        if s.sample_id not in prepared.kept_ids:
            continue  # 去重丢弃
        sq = prepared.step_quality.get(s.sample_id)
        if sq is not None and sq.score < SFT_MIN_STEP_SCORE:
            continue
        if s.reward < 0:
            continue
        traj = prepared.traj_by_agent[f"{s.sample_id.split(':')[0]}:{s.agent_id}"]
        train.append({
            "sample_id": s.sample_id,
            "messages": [
                {"role": "system", "content": s.system_prompt},
                {"role": "user", "content": s.user_brief},
            ],
            "completion": s.raw_response,
            "reward": s.reward,
            "quality_score": sq.score if sq else None,
            "settlement_authority": {
                "mode": s.authority_mode,
                "provider_id": s.authority_provider,
            },
            "reward_purity": s.reward_purity,
            "provenance": _prov(s, traj),
        })
        cards.append(build_decision_card(s, sq))
    _write_jsonl(out_dir / "sft_train.jsonl", train)
    _write_jsonl(out_dir / "sft_cards.jsonl", cards)
    return train, cards


# ---------------------------------------------------------------------------
# 2. DPO(两种来源:时序修正 + 同拍情境对照)
# ---------------------------------------------------------------------------

def export_dpo(prepared: _PreparedRun, out_dir: Path) -> Tuple[List[Dict], List[Dict]]:
    train: List[Dict] = []
    cards: List[Dict] = []

    # ── 来源A:时序修正对(失败反馈闭环)──
    # 某 agent 在 T 拍失败(invalid/no_effect/backlash),T+1 拍换了打法。
    # 语义:给定"刚刚用A失败了"的处境,应偏好新动作B而非重复A。
    for key, traj in prepared.traj_by_agent.items():
        q = prepared.quality_by_agent.get(key)
        if q is None or not q.is_clean:
            continue
        steps = [s for s in traj.steps if not s.is_empty_action]
        for i in range(len(steps) - 1):
            cur, nxt = steps[i], steps[i + 1]
            # 只认真正的失败信号(判无效/打水漂/反噬),不含"低 sf 导致的轻微
            # 负 reward"——那不是失败,只是决策平庸,不构成修正对的反面。
            failed = cur.outcome in (
                "invalid", "no_effect", "negative", "order_rejected", "failed"
            )
            if not failed or nxt.is_fallback or not nxt.parsed_ok:
                continue
            if cur.action_id == nxt.action_id:
                continue  # 换了打法才算修正
            train.append({
                "sample_id": f"{nxt.sample_id}#fix",
                "pair_type": "temporal_correction",
                "prompt": {
                    "system": nxt.system_prompt,
                    "user": nxt.user_brief,   # 含"上一拍复盘"反馈
                },
                "chosen": {"completion": nxt.raw_response,
                           "action_id": nxt.action_id, "reward": nxt.reward},
                "rejected": {"completion": cur.raw_response,
                             "action_id": cur.action_id, "reward": cur.reward,
                             "failure": cur.outcome},
                "provenance": _prov(nxt, traj),
            })
            cards.append({
                "sample_id": f"{nxt.sample_id}#fix",
                "对照类型": "失败后的修正",
                "更差(rejected)": f"第{cur.tick}拍 {cur.action_id}：{_short(cur.plan)}"
                                   f" → {cur.outcome or '负收益'}",
                "更好(chosen)": f"第{nxt.tick}拍 {nxt.action_id}：{_short(nxt.plan)}",
                "为什么更好": _fix_reason(cur, nxt),
            })

    # ── 来源B:同拍场景结算对照 ──
    by_tick: Dict[int, List[TrajectoryStep]] = {}
    for s in prepared.clean_steps:
        by_tick.setdefault(s.tick, []).append(s)
    for tick, group in by_tick.items():
        if len(group) < 2:
            continue
        group.sort(key=lambda x: x.reward, reverse=True)
        hi, lo = group[0], group[-1]
        gap = hi.reward - lo.reward
        if gap < DPO_CONTRAST_MIN_GAP or hi.agent_id == lo.agent_id:
            continue
        hi_traj = prepared.traj_by_agent[f"{hi.sample_id.split(':')[0]}:{hi.agent_id}"]
        train.append({
            "sample_id": f"{hi.sample_id}#vs#{lo.agent_id}",
            "pair_type": "situational_contrast",
            "chosen": {"system": hi.system_prompt, "user": hi.user_brief,
                       "completion": hi.raw_response, "action_id": hi.action_id,
                       "reward": hi.reward},
            "rejected": {"system": lo.system_prompt, "user": lo.user_brief,
                         "completion": lo.raw_response, "action_id": lo.action_id,
                         "reward": lo.reward},
            "reward_gap": round(gap, 3),
            "provenance": _prov(hi, hi_traj),
        })
        cards.append({
            "sample_id": f"{hi.sample_id}#vs#{lo.agent_id}",
            "对照类型": "同一局面下的高下之分",
            "更好(chosen)": f"{hi.agent_id} {hi.action_id}：结算奖励 {hi.reward:+.3f}",
            "更差(rejected)": f"{lo.agent_id} {lo.action_id}：结算奖励 {lo.reward:+.3f}",
            "为什么更好": "同一回合中，场景权威结算给出了更高结果",
        })

    _write_jsonl(out_dir / "dpo_train.jsonl", train)
    _write_jsonl(out_dir / "dpo_cards.jsonl", cards)
    return train, cards


def _fix_reason(cur: TrajectoryStep, nxt: TrajectoryStep) -> str:
    if cur.outcome == "invalid":
        return f"原动作被判无效,改用 {nxt.action_id} 后避免了空耗"
    if cur.outcome == "no_effect":
        return f"原动作打了水漂,改用 {nxt.action_id} 转向更有效的路径"
    if cur.outcome == "order_rejected":
        return f"原订单被确定性验证器拒绝，随后改用 {nxt.action_id}"
    return f"原动作收益为负,{nxt.action_id} 是修正后的选择"


def _short(text: Optional[str], n: int = 50) -> str:
    if not text:
        return ""
    import re as _re
    return _re.sub(r"\s+", " ", text).strip()[:n]


# ---------------------------------------------------------------------------
# 3. RL Episode
# ---------------------------------------------------------------------------

def export_episodes(prepared: _PreparedRun, out_dir: Path) -> Tuple[List[Dict], List[Dict]]:
    """整局展开为 (obs, action, reward) 序列 + terminal。仅干净局。"""
    train: List[Dict] = []
    cards: List[Dict] = []
    for key, traj in prepared.traj_by_agent.items():
        q = prepared.quality_by_agent.get(key)
        if q is None or not q.is_clean:
            continue
        steps_out = []
        det_steps = 0
        for s in traj.steps:
            if s.is_empty_action:
                continue
            steps_out.append({
                "tick": s.tick,
                "obs": {"system": s.system_prompt, "user": s.user_brief},
                "action": {"action_id": s.action_id, "completion": s.raw_response},
                "reward": s.reward,
                "reward_purity": s.reward_purity,
                "delta_ids": list(dict.fromkeys(s.delta_ids)),
            })
            if s.reward_purity == "deterministic":
                det_steps += 1
        if not steps_out:
            continue
        train.append({
            "episode_id": key,
            "steps": steps_out,
            "terminal_value": traj.final_value,
            "victory_rank": traj.victory_rank,
            "victory_label": traj.victory_label,
            "victory_value_key": traj.victory_value_key,
            "eliminated": traj.eliminated,
            "deterministic_step_ratio": round(det_steps / len(steps_out), 3),
            "provenance": {
                "run_id": traj.run_id, "agent_id": traj.agent_id,
                "scenario_version": traj.scenario_version,
                "engine_version": traj.engine_version,
                "model": traj.model, "provider": traj.provider,
                "random_seed": traj.random_seed,
            },
        })
        cards.append({
            "episode_id": key,
            "整局概述": q.verdict,
            "步数": len(steps_out),
            "终局": f"排名第{traj.victory_rank}" + ("(淘汰)" if traj.eliminated else ""),
            "客观奖励占比": f"{round(det_steps / len(steps_out) * 100)}%",
        })
    _write_jsonl(out_dir / "rl_episodes.jsonl", train)
    _write_jsonl(out_dir / "rl_episodes_cards.jsonl", cards)
    return train, cards


# ---------------------------------------------------------------------------
# 4. Eval Set（场景声明的能力任务 = 确定性判分锚）
# ---------------------------------------------------------------------------

def export_eval_set(prepared: _PreparedRun, out_dir: Path) -> Tuple[List[Dict], List[Dict]]:
    """导出场景声明为 capability/challenge 的客观能力任务样本。"""
    train: List[Dict] = []
    cards: List[Dict] = []
    for key, traj in prepared.traj_by_agent.items():
        for s in traj.steps:
            if s.action_category not in {"capability", "challenge"} or s.is_empty_action:
                continue
            train.append({
                "sample_id": s.sample_id,
                "capability_probe": True,
                "prompt": {"system": s.system_prompt, "user": s.user_brief},
                "answer": s.raw_response,
                "provenance": _prov(s, traj),
            })
            cards.append({
                "sample_id": s.sample_id,
                "类型": "能力探针作答",
                "作答摘要": _short(s.raw_response, 100),
                "模型": f"{traj.provider}/{traj.model}",
            })
    _write_jsonl(out_dir / "eval_train.jsonl", train)
    _write_jsonl(out_dir / "eval_cards.jsonl", cards)
    return train, cards


# ---------------------------------------------------------------------------
# 5. OS 2.0 causal traces
# ---------------------------------------------------------------------------

def export_os2_traces(prepared: _PreparedRun, out_dir: Path) -> Tuple[List[Dict], List[Dict]]:
    """Export authoritative action-to-result chains without scene assumptions."""
    train: List[Dict] = []
    cards: List[Dict] = []
    for run_dir in prepared.run_dirs:
        for tick_path in sorted((run_dir / "ticks").glob("tick_*.json")):
            try:
                record = json.loads(tick_path.read_text(encoding="utf-8"))
            except Exception:
                continue
            actions = record.get("world_actions") or []
            observations = record.get("external_observations") or []
            events = record.get("world_events") or []
            settlements = record.get("settlements") or []
            director_plan = record.get("director_plan")
            if not any((actions, observations, events, settlements, director_plan)):
                continue
            tick = int(record.get("tick") or 0)
            sample_id = f"{run_dir.name}:tick:{tick}:os2"
            authority_modes = sorted({
                str((item.get("authority") or {}).get("mode") or "unknown")
                for item in settlements if isinstance(item, dict)
            })
            train.append({
                "sample_id": sample_id,
                "run_id": run_dir.name,
                "world_tick": tick,
                "world_actions": actions,
                "external_observations": observations,
                "world_events": events,
                "settlements": settlements,
                "director_plan": director_plan,
                "director_harness_trace": record.get("director_harness_trace"),
            })
            cards.append({
                "sample_id": sample_id,
                "类型": "OS2可追溯链路",
                "回合": tick,
                "世界行动": len(actions),
                "外部事实": len(observations),
                "世界事件": len(events),
                "结算记录": len(settlements),
                "结算权限": authority_modes,
                "导演计划": bool(director_plan),
            })
    _write_jsonl(out_dir / "os2_traces.jsonl", train)
    _write_jsonl(out_dir / "os2_trace_cards.jsonl", cards)
    return train, cards


# ---------------------------------------------------------------------------
# 编排
# ---------------------------------------------------------------------------

_EXPORTERS = {
    "sft": export_sft,
    "dpo": export_dpo,
    "episodes": export_episodes,
    "eval": export_eval_set,
    "trace": export_os2_traces,
}


def export_all(
    run_dirs: Iterable[Path | str],
    out_dir: Path | str,
    *,
    formats: Optional[List[str]] = None,
    domain_sanitize_rules: Optional[List[Dict[str, Any]]] = None,
) -> ExportBundle:
    """一次导出选定格式。formats 缺省 = 全部四类。

    domain_sanitize_rules:场景包声明的领域脱敏规则(如投资场景打乱日期),
    每一行落盘前都会过这些规则 + 内建的凭证/身份闸。
    """
    global _SANITIZE_REPORT, _DOMAIN_RULES
    run_dirs = [Path(r) for r in run_dirs]
    out_dir = Path(out_dir)
    formats = formats or list(_EXPORTERS.keys())

    # 重置本次导出的脱敏审计 + 领域规则
    _SANITIZE_REPORT = SanitizeReport()
    _DOMAIN_RULES = domain_sanitize_rules or []

    prepared, provenance = _prepare(run_dirs)
    bundle = ExportBundle(out_dir=str(out_dir), provenance=provenance)

    for fmt in formats:
        exporter = _EXPORTERS.get(fmt)
        if exporter is None:
            bundle.notes.append(f"未知格式,跳过:{fmt}")
            continue
        train, cards = exporter(prepared, out_dir)
        bundle.files[f"{fmt}_train"] = str(out_dir / _train_name(fmt))
        bundle.files[f"{fmt}_cards"] = str(out_dir / _cards_name(fmt))
        bundle.counts[fmt] = len(train)

    bundle.sanitize = _SANITIZE_REPORT.to_dict()
    if provenance["clean_steps"] == 0:
        bundle.notes.append("警告:无任何干净步样本(全部局被质量硬闸拦下)")
    if _SANITIZE_REPORT.credential_hits or _SANITIZE_REPORT.dropped_keys:
        bundle.notes.append(
            f"脱敏:打码凭证 {_SANITIZE_REPORT.credential_hits} 处,"
            f"剔除敏感字段 {_SANITIZE_REPORT.dropped_keys} 处"
        )
    return bundle


def _train_name(fmt: str) -> str:
    return {"sft": "sft_train.jsonl", "dpo": "dpo_train.jsonl",
            "episodes": "rl_episodes.jsonl", "eval": "eval_train.jsonl",
            "trace": "os2_traces.jsonl"}[fmt]


def _cards_name(fmt: str) -> str:
    return {"sft": "sft_cards.jsonl", "dpo": "dpo_cards.jsonl",
            "episodes": "rl_episodes_cards.jsonl", "eval": "eval_cards.jsonl",
            "trace": "os2_trace_cards.jsonl"}[fmt]
