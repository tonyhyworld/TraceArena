"""运营后台 · 只读 Run 档案查询 API（迭代一，P0）。

把 OS 已落盘的 runs/<run_id>/ 产物（manifest / 报告 / 账本 / tick / 诊断）
以安全只读接口暴露给运营后台，不重算、不触发模型、不改动任何状态。

安全前提（本期只读，写/控制接口待鉴权落地后再开）：
  - run_id 仅允许 ^run_[A-Za-z0-9]+$，杜绝路径穿越；
  - 报告/账本/tick 文件名白名单为纯 [A-Za-z0-9_]，禁止 .. 与 /；
  - 所有解析后的绝对路径必须仍落在 runs 基目录内，否则拒绝。
基目录与 app/main.py 的日志目录一致（环境变量 AIWORLD_LOG_DIR，默认 ./runs）。
"""
from __future__ import annotations

import json
import os
import re
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

from fastapi import APIRouter, Depends, HTTPException, Query
from app.auth.dependencies import get_current_user
from app.auth.models import User
from app.core.path_safety import path_beneath, safe_path_component

router = APIRouter(prefix="/operator")

_RUN_ID_RE = re.compile(r"^run_[A-Za-z0-9]+$")
_NAME_RE = re.compile(r"^[A-Za-z0-9_]+$")
_AGENT_ID_RE = re.compile(r"^[A-Za-z0-9_]+$")

# OS 不内置任何场景术语。归档优先读取 run manifest 中冻结的场景声明，
# 旧归档缺少声明时直接展示稳定 ID，避免伪装成另一场景的中文语义。
METRIC_LABELS: Dict[str, str] = {}
ACTION_LABELS: Dict[str, str] = {}
INTERACTION_ACTIONS: set[str] = set()
RISK_ACTIONS: set[str] = set()


def _scenario_label_maps(
    run_dir: Path,
) -> Tuple[Dict[str, str], Dict[str, str], set[str], set[str], set[str]]:
    """只读取归档中冻结的术语，不跟随归档提供的本地文件路径。"""
    action_labels = dict(ACTION_LABELS)
    metric_labels = dict(METRIC_LABELS)
    interaction_actions = set(INTERACTION_ACTIONS)
    risk_actions = set(RISK_ACTIONS)
    wait_actions = {"wait_and_prepare", "wait"}
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        return action_labels, metric_labels, interaction_actions, risk_actions, wait_actions
    try:
        manifest = _read_json(manifest_path)
    except HTTPException:
        return action_labels, metric_labels, interaction_actions, risk_actions, wait_actions
    terminology = (manifest or {}).get("terminology") if isinstance(manifest, dict) else None
    if isinstance(terminology, dict):
        term_action_labels = terminology.get("action_labels")
        term_metric_labels = terminology.get("metric_labels")
        term_interaction = terminology.get("interaction_actions")
        term_risk = terminology.get("risk_actions")
        term_wait = terminology.get("wait_actions")
        if isinstance(term_action_labels, dict):
            action_labels.update({
                str(k): str(v)
                for k, v in term_action_labels.items()
                if str(k).strip()
            })
        if isinstance(term_metric_labels, dict):
            metric_labels.update({
                str(k): str(v)
                for k, v in term_metric_labels.items()
                if str(k).strip()
            })
        if isinstance(term_interaction, list):
            interaction_actions = {str(item) for item in term_interaction if item}
        if isinstance(term_risk, list):
            risk_actions = {str(item) for item in term_risk if item}
        if isinstance(term_wait, list):
            wait_actions = {str(item) for item in term_wait if item}
        fallback_aid = str(terminology.get("fallback_action_id") or "").strip()
        if fallback_aid:
            wait_actions.add(fallback_aid)
    return action_labels, metric_labels, interaction_actions, risk_actions, wait_actions


def _runs_base(user_id: str) -> Path:
    """该用户的 runs 根目录：AIWORLD_LOG_DIR/<user_id>，与 EngineManager 的 log_dir 布局一致。"""
    return path_beneath(
        Path(os.environ.get("AIWORLD_LOG_DIR", "./runs")), user_id
    )


def _safe_run_dir(run_id: str, user_id: str) -> Path:
    if not _RUN_ID_RE.match(run_id):
        raise HTTPException(400, "非法 run_id")
    base = _runs_base(user_id)
    try:
        run_dir = path_beneath(base, run_id)
    except ValueError as exc:
        raise HTTPException(400, "非法 run_id") from exc
    if run_dir != base and base not in run_dir.parents:
        raise HTTPException(400, "非法 run_id")
    if not run_dir.is_dir():
        raise HTTPException(404, f"run 不存在: {run_id}")
    return run_dir


def _safe_file(run_dir: Path, subdir: str, name: str, suffix: str) -> Path:
    if not _NAME_RE.match(name):
        raise HTTPException(400, "非法文件名")
    try:
        target = path_beneath(run_dir, subdir, f"{name}{suffix}")
    except ValueError as exc:
        raise HTTPException(400, "非法路径") from exc
    if run_dir.resolve() not in target.parents:
        raise HTTPException(400, "非法路径")
    if not target.is_file():
        raise HTTPException(404, f"文件不存在: {subdir}/{name}{suffix}")
    return target


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except Exception as exc:
        raise HTTPException(500, f"文件解析失败: {exc}")


def _read_jsonl(path: Path) -> List[Dict[str, Any]]:
    rows: List[Dict[str, Any]] = []
    if not path.is_file():
        return rows
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if isinstance(row, dict):
                rows.append(row)
    return rows


def _round_value(value: Any, digits: int = 3) -> Any:
    if isinstance(value, (int, float)):
        return round(float(value), digits)
    return value


def _agent_map(run_dir: Path) -> Dict[str, Dict[str, Any]]:
    manifest_path = run_dir / "run_manifest.json"
    if not manifest_path.is_file():
        return {}
    manifest = _read_json(manifest_path)
    agents = manifest.get("agents", []) if isinstance(manifest, dict) else []
    return {
        str(agent.get("id")): dict(agent)
        for agent in agents
        if isinstance(agent, dict) and agent.get("id")
    }


def _validated_agent_id(agent_id: str) -> str:
    if not _AGENT_ID_RE.match(agent_id):
        raise HTTPException(400, "非法 agent_id")
    try:
        return safe_path_component(agent_id, label="agent_id")
    except ValueError as exc:
        raise HTTPException(400, "非法 agent_id") from exc


def _model_key(agent: Dict[str, Any]) -> str:
    provider = agent.get("provider") or "unknown"
    model = agent.get("model") or "unknown"
    return f"{provider}/{model}"


def _empty_model_bucket(key: str, agent: Dict[str, Any]) -> Dict[str, Any]:
    provider, _, model = key.partition("/")
    return {
        "model_key": key,
        "provider": provider,
        "model": model,
        "sample_runs": set(),
        "agent_samples": 0,
        "wins": 0,
        "victory_ranks": [],
        "capability_acc": {},
        "capability_cases": [],
        "actions": {},
        "interaction_actions": 0,
        "risk_actions": 0,
        "wait_actions": 0,
        "turns": 0,
        "recent_runs": [],
        "scenario_runs": {},
        "settlement_authorities": {},
        "verified_observations": 0,
    }


def _capability_label(capability: str, item: Dict[str, Any]) -> str:
    labels = {
        "language_understanding": "语言理解",
        "long_context": "长上下文",
        "reasoning": "推理",
        "knowledge": "知识问答",
        "instruction_following": "指令遵循",
        "writing": "写作表达",
        "multimodal": "多模态",
        "coding": "Coding",
        "tool_use": "工具调用",
        "safety": "安全稳健",
        "understanding": "理解",
        "memory": "记忆",
        "planning": "规划",
        "judgment": "判断",
        "execution": "执行",
        "risk_control": "风险控制",
    }
    return item.get("label") or labels.get(capability) or capability


def _add_capability(bucket: Dict[str, Any], capability: str, item: Dict[str, Any]) -> None:
    if not isinstance(item, dict):
        return
    score = item.get("score")
    if not isinstance(score, (int, float)):
        return
    sample = float(item.get("sample_count") or item.get("effective_sample_size") or 1)
    confidence = float(item.get("confidence") or 0)
    weight = max(sample, 1.0)
    acc = bucket["capability_acc"].setdefault(capability, {
        "capability": capability,
        "label": _capability_label(capability, item),
        "score_sum": 0.0,
        "confidence_sum": 0.0,
        "sample_count": 0.0,
        "observations": 0,
        "measured": 0,
    })
    acc["score_sum"] += float(score) * weight
    acc["confidence_sum"] += confidence * weight
    acc["sample_count"] += sample
    acc["observations"] += 1
    if item.get("status") == "measured":
        acc["measured"] += 1


def _list_names(directory: Path, suffix: str) -> List[str]:
    if not directory.is_dir():
        return []
    return sorted(
        p.name[: -len(suffix)] for p in directory.glob(f"*{suffix}")
    )


def _run_summary(run_dir: Path) -> Dict[str, Any]:
    """从 manifest 和 OS2 终局排名拼一份轻量摘要。"""
    summary: Dict[str, Any] = {"run_id": run_dir.name}
    manifest_path = run_dir / "run_manifest.json"
    meta_path = run_dir / "meta.json"
    if manifest_path.is_file():
        m = _read_json(manifest_path)
        summary.update({
            "created_at": m.get("created_at"),
            "scenario": (m.get("scenario") or {}).get("name"),
            "scenario_version": (m.get("scenario") or {}).get("version"),
            "agents": [
                {
                    "id": a.get("id"),
                    "name": a.get("name"),
                    "provider": a.get("provider"),
                    "model": a.get("model"),
                }
                for a in m.get("agents", [])
            ],
            "director_enabled": (m.get("director") or {}).get("enabled"),
        })
    elif meta_path.is_file():
        meta = _read_json(meta_path)
        summary["scenario"] = meta.get("scenario_name") or meta.get("scenario")
    # 终局产物存在性 → 状态提示
    standings_path = run_dir / "reports" / "victory_standings.json"
    summary["finalized"] = standings_path.is_file()
    if standings_path.is_file():
        summary["winner"] = None
        try:
            standings = _read_json(standings_path)
            if isinstance(standings, list):
                winner = next(
                    (item for item in standings if item.get("rank") == 1),
                    None,
                )
                summary["winner"] = (winner or {}).get("agent_id")
        except HTTPException:
            pass
    summary["has_replay"] = (run_dir / "replay.json").is_file()
    summary["has_presentation_timeline"] = (
        run_dir / "presentation_timeline.json"
    ).is_file()
    return summary


def _aggregate_model_analysis(user_id: str, limit_runs: int = 200) -> Dict[str, Any]:
    base = _runs_base(user_id)
    if not base.is_dir():
        return {"models": [], "total_runs": 0, "capability_labels": {}, "action_labels": ACTION_LABELS}

    run_dirs = [
        d for d in base.iterdir()
        if d.is_dir() and _RUN_ID_RE.match(d.name) and (d / "run_manifest.json").is_file()
    ]
    run_dirs.sort(key=lambda d: (d / "run_manifest.json").stat().st_mtime, reverse=True)
    run_dirs = run_dirs[:limit_runs]

    buckets: Dict[str, Dict[str, Any]] = {}
    merged_action_labels = dict(ACTION_LABELS)
    total_finalized = 0

    for run_dir in run_dirs:
        try:
            manifest = _read_json(run_dir / "run_manifest.json")
        except HTTPException:
            continue
        agents = {
            str(agent.get("id")): dict(agent)
            for agent in (manifest.get("agents") or [])
            if isinstance(agent, dict) and agent.get("id")
        }
        if not agents:
            continue
        action_labels, _metric_labels, interaction_actions, risk_actions, wait_actions = (
            _scenario_label_maps(run_dir)
        )
        merged_action_labels.update(action_labels)
        agent_to_model = {}
        for aid, agent in agents.items():
            key = _model_key(agent)
            agent_to_model[aid] = key
            bucket = buckets.setdefault(key, _empty_model_bucket(key, agent))
            bucket["sample_runs"].add(run_dir.name)
            bucket["agent_samples"] += 1
            bucket["recent_runs"].append({
                "run_id": run_dir.name,
                "agent_id": aid,
                "agent_name": agent.get("name") or aid,
                "created_at": manifest.get("created_at"),
            })
            scenario_name = str((manifest.get("scenario") or {}).get("name") or "未命名场景")
            bucket["scenario_runs"][scenario_name] = (
                bucket["scenario_runs"].get(scenario_name, 0) + 1
            )

        for tick_path in sorted((run_dir / "ticks").glob("tick_*.json")):
            try:
                tick_record = _read_json(tick_path)
            except HTTPException:
                continue
            observations = tick_record.get("os2_external_observations") or []
            for observation in observations:
                if not isinstance(observation, dict) or observation.get("verification_status") != "verified":
                    continue
                # External observations are world-level evidence. Attribute one
                # verified source to every participating model for coverage,
                # not as a reward or score.
                for key in set(agent_to_model.values()):
                    buckets[key]["verified_observations"] += 1
            for settlement in tick_record.get("settlements") or []:
                if not isinstance(settlement, dict):
                    continue
                authority = (settlement.get("authority") or {}).get("mode") or "unknown"
                subjects = settlement.get("subject_ids") or []
                for aid in subjects:
                    key = agent_to_model.get(str(aid))
                    if not key:
                        continue
                    target = buckets[key]["settlement_authorities"]
                    target[authority] = target.get(authority, 0) + 1

        standings_path = run_dir / "reports" / "victory_standings.json"
        if standings_path.is_file():
            total_finalized += 1
            try:
                standings = _read_json(standings_path)
            except HTTPException:
                standings = []
            if isinstance(standings, list):
                for item in standings:
                    if not isinstance(item, dict):
                        continue
                    aid = item.get("agent_id")
                    key = agent_to_model.get(aid)
                    if not key:
                        continue
                    rank = item.get("rank")
                    if isinstance(rank, (int, float)):
                        buckets[key]["victory_ranks"].append(float(rank))
                    if rank == 1:
                        buckets[key]["wins"] += 1

        profiles_path = run_dir / "reports" / "general_capability_profiles.json"
        if profiles_path.is_file():
            try:
                profiles = _read_json(profiles_path).get("profiles") or {}
            except HTTPException:
                profiles = {}
            for aid, profile in profiles.items():
                key = agent_to_model.get(aid)
                dims = profile.get("dimensions") if isinstance(profile, dict) else None
                if not key or not isinstance(dims, dict):
                    continue
                for capability, item in dims.items():
                    _add_capability(buckets[key], capability, item)

        cases_path = run_dir / "reports" / "assessment_cases.json"
        cases: List[Dict[str, Any]] = []
        if cases_path.is_file():
            try:
                raw_cases = _read_json(cases_path)
                if isinstance(raw_cases, list):
                    cases = [item for item in raw_cases if isinstance(item, dict)]
            except HTTPException:
                cases = []
        for case in cases:
            aid = case.get("agent_id")
            key = agent_to_model.get(aid)
            if not key:
                continue
            buckets[key]["capability_cases"].append({
                "run_id": run_dir.name,
                "tick": case.get("tick"),
                "agent_id": aid,
                "agent_name": (agents.get(aid) or {}).get("name") or aid,
                "case_id": case.get("case_id"),
                "capability": case.get("capability"),
                "score": case.get("score"),
                "status": case.get("status"),
                "instruction": ((case.get("probe") or {}).get("instruction")),
                "raw_output": ((case.get("response") or {}).get("raw_output")),
                "rationale": ((case.get("verification") or {}).get("rationale")),
            })

        for row in _read_jsonl(run_dir / "diagnostics.jsonl"):
            if row.get("event_type") != "agent_turn_completed":
                continue
            aid = row.get("agent_id")
            key = agent_to_model.get(aid)
            if not key:
                continue
            action = ((row.get("action_pack") or {}).get("action_id") if isinstance(row.get("action_pack"), dict) else None) or "unknown"
            bucket = buckets[key]
            bucket["turns"] += 1
            bucket["actions"][action] = bucket["actions"].get(action, 0) + 1
            if action in interaction_actions:
                bucket["interaction_actions"] += 1
            if action in risk_actions:
                bucket["risk_actions"] += 1
            # 统计场景中 intent=wait（等待意图）或名称含「等待」的待命类动作
            if action in wait_actions:
                bucket["wait_actions"] += 1

    models: List[Dict[str, Any]] = []
    capability_labels: Dict[str, str] = {}
    for key, bucket in buckets.items():
        caps = []
        for capability, acc in bucket["capability_acc"].items():
            sample = acc["sample_count"] or acc["observations"] or 1
            label = acc["label"]
            capability_labels[capability] = label
            caps.append({
                "capability": capability,
                "label": label,
                "score": round(acc["score_sum"] / sample, 2),
                "confidence": round(acc["confidence_sum"] / sample, 3),
                "sample_count": round(acc["sample_count"], 1),
                "observations": acc["observations"],
                "measured": acc["measured"],
            })
        caps.sort(key=lambda item: item["score"], reverse=True)
        action_total = bucket["turns"] or 1
        actions = [
            {
                "action_id": action,
                "label": merged_action_labels.get(action, action),
                "count": count,
                "ratio": round(count / action_total, 3),
            }
            for action, count in sorted(bucket["actions"].items(), key=lambda kv: kv[1], reverse=True)
        ]
        ranks = bucket["victory_ranks"]
        models.append({
            "model_key": key,
            "provider": bucket["provider"],
            "model": bucket["model"],
            "run_count": len(bucket["sample_runs"]),
            "agent_samples": bucket["agent_samples"],
            "win_count": bucket["wins"],
            "win_rate": round(bucket["wins"] / max(len(bucket["sample_runs"]), 1), 3),
            "avg_victory_rank": round(sum(ranks) / len(ranks), 3) if ranks else None,
            "capabilities": caps,
            "actions": actions,
            "turns": bucket["turns"],
            "interaction_ratio": round(bucket["interaction_actions"] / action_total, 3),
            "risk_action_ratio": round(bucket["risk_actions"] / action_total, 3),
            "wait_ratio": round(bucket["wait_actions"] / action_total, 3),
            "recent_runs": bucket["recent_runs"][:12],
            "cases": bucket["capability_cases"][:80],
            "scenarios": [
                {"name": name, "samples": count}
                for name, count in sorted(
                    bucket["scenario_runs"].items(),
                    key=lambda item: item[1], reverse=True,
                )
            ],
            "settlement_authorities": bucket["settlement_authorities"],
            "verified_observations": bucket["verified_observations"],
        })
    models.sort(key=lambda item: (
        item["run_count"],
        -(item["avg_victory_rank"] if item["avg_victory_rank"] is not None else 999),
    ), reverse=True)
    return {
        "total_runs": len(run_dirs),
        "finalized_runs": total_finalized,
        "models": models,
        "capability_labels": capability_labels,
        "action_labels": merged_action_labels,
    }


@router.get("/models/analysis")
async def get_model_analysis(
    limit_runs: int = Query(200, ge=1, le=1000),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """聚合历史 runs，生成模型能力画像和行为画像。"""
    return _aggregate_model_analysis(user.user_id, limit_runs=limit_runs)


@router.get("/capability-assessment/latest")
async def get_latest_capability_assessment(user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """读取最近一局已落盘的十大能力画像，供实时台空态兜底。"""
    base = _runs_base(user.user_id)
    if not base.is_dir():
        return {
            "run_id": None,
            "source": "none",
            "profiles": {"profiles": {}},
            "cases": [],
        }
    run_dirs = [
        d for d in base.iterdir()
        if d.is_dir() and _RUN_ID_RE.match(d.name)
    ]
    run_dirs.sort(key=lambda d: d.stat().st_mtime, reverse=True)
    for run_dir in run_dirs:
        profiles_path = run_dir / "reports" / "general_capability_profiles.json"
        cases_path = run_dir / "reports" / "assessment_cases.json"
        if not profiles_path.is_file() or not cases_path.is_file():
            continue
        try:
            profiles = _read_json(profiles_path)
            cases = _read_json(cases_path)
        except HTTPException:
            continue
        if not isinstance(profiles, dict) or not isinstance(cases, list):
            continue
        if not cases:
            continue
        return {
            "run_id": run_dir.name,
            "source": "latest_run",
            "profiles": profiles,
            "cases": cases,
        }
    return {
        "run_id": None,
        "source": "none",
        "profiles": {"profiles": {}},
        "cases": [],
    }


@router.get("/runs")
async def list_runs(
    scenario: Optional[str] = None,
    finalized: Optional[bool] = None,
    limit: int = Query(50, ge=1, le=500),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """历史 Run 列表，按 created_at 倒序，支持场景/终局态筛选与分页。"""
    base = _runs_base(user.user_id)
    if not base.is_dir():
        return {"total": 0, "limit": limit, "offset": offset, "runs": []}
    summaries = [
        _run_summary(d)
        for d in base.iterdir()
        if d.is_dir() and _RUN_ID_RE.match(d.name)
    ]
    if scenario is not None:
        summaries = [s for s in summaries if s.get("scenario") == scenario]
    if finalized is not None:
        summaries = [s for s in summaries if bool(s.get("finalized")) == finalized]
    summaries.sort(key=lambda s: s.get("created_at") or 0, reverse=True)
    total = len(summaries)
    page = summaries[offset: offset + limit]
    return {"total": total, "limit": limit, "offset": offset, "runs": page}


@router.get("/runs/{run_id}")
async def get_run(run_id: str, user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """单个 Run 详情：摘要 + 产物清单（哪些报告/账本/tick/诊断存在）。"""
    run_dir = _safe_run_dir(run_id, user.user_id)
    return {
        **_run_summary(run_dir),
        "reports": _list_names(run_dir / "reports", ".json"),
        "ledgers": _list_names(run_dir / "ledgers", ".jsonl"),
        "ticks": sorted(
            int(p.stem.split("_")[-1])
            for p in (run_dir / "ticks").glob("tick_*.json")
        ) if (run_dir / "ticks").is_dir() else [],
        "has_diagnostics": (run_dir / "diagnostics.jsonl").is_file(),
        "has_runtime_log": (run_dir / "runtime.log").is_file(),
        "has_presentation_timeline": (run_dir / "presentation_timeline.json").is_file(),
    }


@router.get("/runs/{run_id}/timeline")
async def get_run_timeline(run_id: str, user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """对局回顾时间线：把 presentation_timeline.json 整理成"实时对局同款"的
    逐回合回顾数据（剥掉音频/播放计划等重负载），供对局档案页复盘。"""
    run_dir = _safe_run_dir(run_id, user.user_id)
    tl_path = run_dir / "presentation_timeline.json"
    if not tl_path.is_file():
        return {"available": False, "run_id": run_id, "ticks": []}
    data = _read_json(tl_path) or {}
    action_labels, metric_labels, _, _, _ = _scenario_label_maps(run_dir)

    def _slim_log(log: Dict[str, Any]) -> Dict[str, Any]:
        pp = log.get("perception_pack") or {}
        harness = log.get("harness_trace")
        # 存档侧保留 Harness 步骤摘要，供 hybrid 左侧「Harness Loop」回放
        slim_harness = None
        if isinstance(harness, dict) and harness.get("steps") is not None:
            slim_harness = {
                "trace_id": harness.get("trace_id"),
                "world_tick": harness.get("world_tick"),
                "agent_id": harness.get("agent_id"),
                "status": harness.get("status"),
                "steps": [
                    {
                        "step_id": s.get("step_id"),
                        "index": s.get("index"),
                        "kind": s.get("kind"),
                        "status": s.get("status"),
                        "public_summary": s.get("public_summary") or "",
                        "duration_ms": s.get("duration_ms") or 0,
                    }
                    for s in (harness.get("steps") or [])
                    if isinstance(s, dict)
                ],
            }
        return {
            "tick": log.get("tick"),
            "agent_id": log.get("agent_id"),
            "provider": log.get("provider"),
            "model": log.get("model"),
            "duration_ms": log.get("duration_ms"),
            "raw_llm_response": log.get("raw_llm_response") or "",
            "action_pack": log.get("action_pack"),
            "perception": pp.get("perception") or pp or None,
            "error": log.get("error"),
            "harness_trace": slim_harness,
        }

    snap_keys = (
        "tick", "agents", "agent_metrics",
        "eliminated", "is_game_over", "winner_id", "victory_attribution",
    )
    ticks: List[Dict[str, Any]] = []
    for pkg in data.get("packages", []):
        snap = pkg.get("world_snapshot") or {}
        tick_number = int(pkg.get("tick") or 0)
        tick_path = run_dir / "ticks" / f"tick_{tick_number:03d}.json"
        tick_record = _read_json(tick_path) if tick_path.is_file() else {}
        ticks.append({
            "tick": tick_number,
            "logs": [_slim_log(l) for l in (pkg.get("agent_logs") or [])],
            "snapshot": {k: snap.get(k) for k in snap_keys},
            "os2": {
                "world_actions": tick_record.get("world_actions") or [],
                "external_observations": tick_record.get("external_observations") or [],
                "agent_activities": tick_record.get("agent_activities") or [],
                "world_events": tick_record.get("world_events") or [],
                "settlements": tick_record.get("settlements") or [],
                "director_plan": (
                    tick_record.get("director_plan")
                    or pkg.get("director_plan")
                ),
                "director_harness_trace": tick_record.get("director_harness_trace"),
            },
        })
    ticks.sort(key=lambda t: t.get("tick") or 0)
    last_snap = ticks[-1]["snapshot"] if ticks else {}
    # 胜负溯源：优先末帧快照；重置关局的场次快照里没有 → 回退 reports 落盘版
    victory_attribution = last_snap.get("victory_attribution") or []
    if not victory_attribution:
        va_path = run_dir / "reports" / "victory_attribution.json"
        if va_path.is_file():
            victory_attribution = _read_json(va_path) or []
    return {
        "available": True,
        "run_id": run_id,
        "summary": _run_summary(run_dir),
        "terminology": {
            "action_labels": action_labels,
            "metric_labels": metric_labels,
        },
        "final": {
            "winner_id": last_snap.get("winner_id"),
            "is_game_over": last_snap.get("is_game_over"),
            "victory_attribution": victory_attribution,
            "eliminated": last_snap.get("eliminated") or [],
            "agent_metrics": last_snap.get("agent_metrics") or {},
            "victory_standings": (
                _read_json(run_dir / "reports" / "victory_standings.json")
                if (run_dir / "reports" / "victory_standings.json").is_file()
                else None
            ),
        },
        "ticks": ticks,
    }


@router.get("/runs/{run_id}/reports/{report_name}")
async def get_run_report(run_id: str, report_name: str, user: User = Depends(get_current_user)) -> Any:
    """读取 reports/<name>.json。老版本 run 可能缺某些报告 → 404，前端需容错。"""
    run_dir = _safe_run_dir(run_id, user.user_id)
    return _read_json(_safe_file(run_dir, "reports", report_name, ".json"))


@router.get("/runs/{run_id}/ledgers/{ledger_name}")
async def get_run_ledger(
    run_id: str,
    ledger_name: str,
    tick: Optional[int] = None,
    agent: Optional[str] = None,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """读取 ledgers/<name>.jsonl，支持 tick/agent 过滤与分页（JSONL 可能很大）。"""
    run_dir = _safe_run_dir(run_id, user.user_id)
    path = _safe_file(run_dir, "ledgers", ledger_name, ".jsonl")
    rows: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if tick is not None and row.get("tick") != tick:
                continue
            if agent is not None and row.get("agent_id") != agent:
                continue
            rows.append(row)
    total = len(rows)
    page = rows[offset: offset + limit]
    return {"ledger": ledger_name, "total": total, "limit": limit, "offset": offset, "entries": page}


@router.get("/runs/{run_id}/ticks/{tick}")
async def get_run_tick(run_id: str, tick: int, user: User = Depends(get_current_user)) -> Any:
    """读取 ticks/tick_NNN.json 的完整单 tick 记录。"""
    if tick < 0:
        raise HTTPException(400, "非法 tick")
    run_dir = _safe_run_dir(run_id, user.user_id)
    return _read_json(_safe_file(run_dir, "ticks", f"tick_{tick:03d}", ".json"))


@router.get("/runs/{run_id}/diagnostics")
async def get_run_diagnostics(
    run_id: str,
    event_type: Optional[str] = None,
    tick: Optional[int] = None,
    limit: int = Query(200, ge=1, le=2000),
    offset: int = Query(0, ge=0),
    user: User = Depends(get_current_user),
) -> Dict[str, Any]:
    """读取 diagnostics.jsonl，支持 event_type/tick 过滤与分页。"""
    run_dir = _safe_run_dir(run_id, user.user_id)
    path = run_dir / "diagnostics.jsonl"
    if not path.is_file():
        raise HTTPException(404, "该 run 无 diagnostics.jsonl")
    rows: List[Dict[str, Any]] = []
    with path.open(encoding="utf-8") as handle:
        for line in handle:
            line = line.strip()
            if not line:
                continue
            try:
                row = json.loads(line)
            except Exception:
                continue
            if event_type is not None and row.get("event_type") != event_type:
                continue
            if tick is not None and row.get("tick") != tick:
                continue
            rows.append(row)
    total = len(rows)
    page = rows[offset: offset + limit]
    return {"total": total, "limit": limit, "offset": offset, "events": page}


def _collect_metric_timeline_from_ticks(run_dir: Path) -> List[Dict[str, Any]]:
    ticks_dir = run_dir / "ticks"
    if not ticks_dir.is_dir():
        return []
    timeline: List[Dict[str, Any]] = []
    for path in sorted(ticks_dir.glob("tick_*.json")):
        try:
            tick = int(path.stem.split("_")[-1])
        except Exception:
            continue
        data = _read_json(path)
        snapshot = data.get("world_snapshot") if isinstance(data, dict) else None
        if not isinstance(snapshot, dict):
            continue
        metrics = (
            snapshot.get("agent_metrics")
            or snapshot.get("metrics")
            or {}
        )
        agents = snapshot.get("agents") or []
        timeline.append({
            "tick": tick,
            "agent_metrics": metrics,
            "agents": agents,
        })
    return timeline


def _collect_metric_timeline_from_diagnostics(
    run_dir: Path,
    metric_labels: Dict[str, str],
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    rows = _read_jsonl(run_dir / "diagnostics.jsonl")
    agent_names = _agent_map(run_dir)
    agent_metrics: Dict[str, Dict[str, float]] = {
        aid: {metric: 0.0 for metric in metric_labels}
        for aid in agent_names.keys()
    }
    events: List[Dict[str, Any]] = []
    timeline_by_tick: Dict[int, Dict[str, Any]] = {}

    def ensure_agent(agent_id: str) -> Dict[str, float]:
        return agent_metrics.setdefault(
            agent_id,
            {metric: 0.0 for metric in metric_labels},
        )

    def commit_tick(tick: int) -> None:
        timeline_by_tick[tick] = {
            "tick": tick,
            "agent_metrics": {
                aid: {metric: _round_value(value) for metric, value in metrics.items()}
                for aid, metrics in agent_metrics.items()
            },
            "agents": [
                {
                    "agent_id": aid,
                    "name": (agent_names.get(aid) or {}).get("name") or aid,
                    "model": (agent_names.get(aid) or {}).get("model"),
                    "provider": (agent_names.get(aid) or {}).get("provider"),
                }
                for aid in sorted(agent_metrics)
            ],
        }

    for row in rows:
        tick = int(row.get("tick") or 0)
        effects = row.get("effects")
        if not isinstance(effects, list):
            effects = []
        for effect in effects:
            if not isinstance(effect, dict) or effect.get("type") != "metric_delta":
                continue
            target = effect.get("target") or effect.get("agent_id")
            metric = effect.get("metric")
            if not target or not metric:
                continue
            delta = effect.get("delta", effect.get("value", 0))
            try:
                delta_f = float(delta or 0)
            except Exception:
                delta_f = 0.0
            metrics = ensure_agent(str(target))
            before = effect.get("before", metrics.get(metric, 0.0))
            after = effect.get("after")
            try:
                after_f = float(after) if after is not None else float(before or 0) + delta_f
            except Exception:
                after_f = metrics.get(metric, 0.0) + delta_f
            metrics[metric] = after_f
            events.append({
                "tick": tick,
                "agent_id": str(target),
                "agent_name": (agent_names.get(str(target)) or {}).get("name") or str(target),
                "metric": metric,
                "metric_label": metric_labels.get(metric, metric),
                "delta": _round_value(delta_f, 2),
                "before": _round_value(before, 2),
                "after": _round_value(after_f, 2),
                "source_event_type": row.get("event_type"),
                "action_id": row.get("action_id"),
                "summary": row.get("summary") or "",
                "impact": abs(delta_f),
            })
        if tick:
            commit_tick(tick)

    return [timeline_by_tick[t] for t in sorted(timeline_by_tick)], sorted(
        events, key=lambda item: (item.get("impact") or 0, item.get("tick") or 0), reverse=True
    )


@router.get("/runs/{run_id}/metrics-timeline")
async def get_metrics_timeline(run_id: str, user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """按 Tick 返回指标时间线；优先读完整 tick 快照，缺失时从 diagnostics 的 metric_delta 还原。"""
    run_dir = _safe_run_dir(run_id, user.user_id)
    _action_labels, metric_labels, _interaction_actions, _risk_actions, _wait_actions = (
        _scenario_label_maps(run_dir)
    )
    timeline = _collect_metric_timeline_from_ticks(run_dir)
    key_events: List[Dict[str, Any]] = []
    source = "ticks"
    if not timeline:
        timeline, key_events = _collect_metric_timeline_from_diagnostics(run_dir, metric_labels)
        source = "diagnostics"
    agents = _agent_map(run_dir)
    return {
        "run_id": run_id,
        "source": source,
        "metric_labels": metric_labels,
        "agents": [
            {
                "agent_id": aid,
                "name": agent.get("name") or aid,
                "provider": agent.get("provider"),
                "model": agent.get("model"),
            }
            for aid, agent in agents.items()
        ],
        "timeline": timeline,
        "key_events": key_events[:20],
    }


def _cot_ticks_from_files(run_dir: Path, agent_id: str) -> List[Dict[str, Any]]:
    safe_agent_id = _validated_agent_id(agent_id)
    cot_dir = path_beneath(run_dir, "agents", safe_agent_id, "cot")
    if not cot_dir.is_dir():
        return []
    ticks: Dict[int, Dict[str, Any]] = {}
    for path in cot_dir.glob("tick_*_*"):
        parts = path.stem.split("_")
        if len(parts) < 3:
            continue
        try:
            tick = int(parts[1])
        except Exception:
            continue
        item = ticks.setdefault(tick, {"tick": tick})
        if path.name.endswith("_prompt.md"):
            item["has_prompt"] = True
        elif path.name.endswith("_response.txt"):
            item["has_response"] = True
        elif path.name.endswith("_decision.json"):
            item["has_decision"] = True
    return [ticks[t] for t in sorted(ticks)]


def _cot_ticks_from_diagnostics(run_dir: Path, agent_id: str) -> List[Dict[str, Any]]:
    rows = [
        row for row in _read_jsonl(run_dir / "diagnostics.jsonl")
        if row.get("event_type") == "agent_turn_completed"
        and row.get("agent_id") == agent_id
    ]
    return [
        {
            "tick": int(row.get("tick") or 0),
            "provider": row.get("provider"),
            "model": row.get("model"),
            "duration_ms": row.get("duration_ms"),
            "action_id": ((row.get("action_pack") or {}).get("action_id") if isinstance(row.get("action_pack"), dict) else None),
            "has_prompt": False,
            "has_response": bool(row.get("raw_llm_response")),
            "has_decision": bool(row.get("action_pack")),
            "source": "diagnostics",
        }
        for row in rows
    ]


@router.get("/runs/{run_id}/agent/{agent_id}/cot")
async def list_agent_cot(run_id: str, agent_id: str, user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """列出某 Agent 可追溯的决策 Tick。"""
    agent_id = _validated_agent_id(agent_id)
    run_dir = _safe_run_dir(run_id, user.user_id)
    agents = _agent_map(run_dir)
    ticks = _cot_ticks_from_files(run_dir, agent_id)
    source = "files"
    if not ticks:
        ticks = _cot_ticks_from_diagnostics(run_dir, agent_id)
        source = "diagnostics"
    charter_path = path_beneath(run_dir, "agents", agent_id, "charter.md")
    return {
        "run_id": run_id,
        "agent_id": agent_id,
        "agent": agents.get(agent_id) or {"id": agent_id, "name": agent_id},
        "source": source,
        "has_charter": charter_path.is_file(),
        "ticks": ticks,
    }


@router.get("/runs/{run_id}/agent/{agent_id}/cot/{tick}")
async def get_agent_cot_tick(run_id: str, agent_id: str, tick: int, user: User = Depends(get_current_user)) -> Dict[str, Any]:
    """读取某 Agent 某 Tick 的 prompt / response / decision；缺文件时从 diagnostics 尽量还原。"""
    agent_id = _validated_agent_id(agent_id)
    if tick < 0:
        raise HTTPException(400, "非法 tick")
    run_dir = _safe_run_dir(run_id, user.user_id)
    cot_dir = path_beneath(run_dir, "agents", agent_id, "cot")
    stem = f"tick_{tick:03d}"
    prompt_path = path_beneath(cot_dir, f"{stem}_prompt.md")
    response_path = path_beneath(cot_dir, f"{stem}_response.txt")
    decision_path = path_beneath(cot_dir, f"{stem}_decision.json")
    charter_path = path_beneath(run_dir, "agents", agent_id, "charter.md")

    result: Dict[str, Any] = {
        "run_id": run_id,
        "agent_id": agent_id,
        "tick": tick,
        "source": "files",
        "charter": charter_path.read_text(encoding="utf-8") if charter_path.is_file() else "",
        "prompt": prompt_path.read_text(encoding="utf-8") if prompt_path.is_file() else "",
        "response": response_path.read_text(encoding="utf-8") if response_path.is_file() else "",
        "decision": _read_json(decision_path) if decision_path.is_file() else None,
        "perception": None,
        "metadata": {},
    }
    if result["prompt"] or result["response"] or result["decision"]:
        return result

    rows = [
        row for row in _read_jsonl(run_dir / "diagnostics.jsonl")
        if row.get("event_type") == "agent_turn_completed"
        and row.get("agent_id") == agent_id
        and int(row.get("tick") or 0) == tick
    ]
    if not rows:
        raise HTTPException(404, "该 Tick 无 Agent 上下文记录")
    row = rows[-1]
    result.update({
        "source": "diagnostics",
        "response": row.get("raw_llm_response") or "",
        "decision": row.get("action_pack"),
        "perception": row.get("perception_pack"),
        "metadata": {
            "provider": row.get("provider"),
            "model": row.get("model"),
            "duration_ms": row.get("duration_ms"),
            "tokens_used": row.get("tokens_used"),
            "error": row.get("error"),
        },
    })
    return result
