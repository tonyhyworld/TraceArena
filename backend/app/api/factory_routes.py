"""
数据工厂 · 运营台 API

把 app.factory 的能力(轨迹归一化 → 质检 → 去重 → 导出 → 封装)以安全
REST 接口暴露给运营台"训练数据"板块。只读用户自己的 runs,导出物落到
用户 exports 目录。全部需 export_data 权限(is_admin 绕过)。

  GET  /factory/runs                 列可用对局(带质量摘要)
  POST /factory/preview              按筛选条件预览决策卡样本(不落盘)
  POST /factory/export               导出+封装成数据集(落盘,返回汇总)
  GET  /factory/datasets             列已导出数据集
  GET  /factory/datasets/{id}/card   读数据卡(markdown)
  GET  /factory/datasets/{id}/file   下载导出文件(白名单)
"""
from __future__ import annotations

import os
import re
import uuid
from pathlib import Path
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse
from pydantic import BaseModel, Field

from app.auth.dependencies import require_permission
from app.auth.models import User
from app.auth.permissions import Permission
from app.core.path_safety import path_beneath

router = APIRouter(prefix="/factory")

_RUN_ID_RE = re.compile(r"^run_[A-Za-z0-9]+$")
_DATASET_ID_RE = re.compile(r"^ds_[A-Za-z0-9]+$")
# 导出物文件名白名单(五类双视图 + 封装产物)
_EXPORT_FILES = {
    "sft_train.jsonl", "sft_cards.jsonl",
    "dpo_train.jsonl", "dpo_cards.jsonl",
    "rl_episodes.jsonl", "rl_episodes_cards.jsonl",
    "eval_train.jsonl", "eval_cards.jsonl",
    "os2_traces.jsonl", "os2_trace_cards.jsonl",
    "dataset_manifest.json", "data_card.md", "export_summary.json",
}

_dep = Depends(require_permission(Permission.EXPORT_DATA.value))


def _runs_base(user_id: str) -> Path:
    return path_beneath(
        Path(os.environ.get("AIWORLD_LOG_DIR", "./runs")), user_id
    )


def _exports_base(user_id: str) -> Path:
    base = path_beneath(_runs_base(user_id).parent, "exports", user_id)
    base.mkdir(parents=True, exist_ok=True)
    return base


def _safe_run_dir(run_id: str, user_id: str) -> Path:
    if not _RUN_ID_RE.match(run_id):
        raise HTTPException(400, "非法 run_id")
    base = _runs_base(user_id)
    try:
        run_dir = path_beneath(base, run_id)
    except ValueError as exc:
        raise HTTPException(400, "非法 run_id") from exc
    if base not in run_dir.parents:
        raise HTTPException(400, "非法 run_id")
    if not run_dir.is_dir():
        raise HTTPException(404, f"run 不存在: {run_id}")
    return run_dir


def _safe_dataset_dir(dataset_id: str, user_id: str) -> Path:
    if not _DATASET_ID_RE.match(dataset_id):
        raise HTTPException(400, "非法 dataset_id")
    base = _exports_base(user_id)
    try:
        ds_dir = path_beneath(base, dataset_id)
    except ValueError as exc:
        raise HTTPException(400, "非法路径") from exc
    if base not in ds_dir.parents:
        raise HTTPException(400, "非法路径")
    if not ds_dir.is_dir():
        raise HTTPException(404, f"数据集不存在: {dataset_id}")
    return ds_dir


# ---------------------------------------------------------------------------
# 请求模型
# ---------------------------------------------------------------------------

class PreviewRequest(BaseModel):
    run_ids: List[str] = Field(default_factory=list)
    fmt: str = "sft"                  # sft / dpo / episodes / eval
    limit: int = 20


class ExportRequest(BaseModel):
    run_ids: List[str] = Field(default_factory=list)
    formats: Optional[List[str]] = None
    name: str = "ai-world-dataset"


# ---------------------------------------------------------------------------
# 列对局(带质量摘要,让筛选前先看到哪些局值得导)
# ---------------------------------------------------------------------------

@router.get("/runs")
async def list_factory_runs(user: User = _dep) -> Dict[str, Any]:
    from app.factory import iter_trajectories, score_trajectory

    base = _runs_base(user.user_id)
    if not base.is_dir():
        return {"count": 0, "runs": []}
    out: List[Dict[str, Any]] = []
    for run_dir in sorted(base.glob("run_*"), key=lambda p: p.stat().st_mtime, reverse=True):
        if not (run_dir / "meta.json").exists():
            continue
        clean = 0
        total = 0
        agents = []
        try:
            for traj in iter_trajectories(run_dir):
                total += 1
                q = score_trajectory(traj)
                if q.is_clean:
                    clean += 1
                agents.append({
                    "agent_id": traj.agent_id,
                    "model": f"{traj.provider}/{traj.model}",
                    "is_clean": q.is_clean,
                    "overall": q.overall_score,
                    "valid_ratio": q.valid_step_ratio,
                })
        except Exception:
            continue
        out.append({
            "run_id": run_dir.name,
            "clean_agents": clean,
            "total_agents": total,
            "good_rate": round(clean / total, 3) if total else 0.0,
            "agents": agents,
        })
    return {"count": len(out), "runs": out}


# ---------------------------------------------------------------------------
# 预览(按筛选条件抽样决策卡,不落盘——给非技术人员先看货)
# ---------------------------------------------------------------------------

@router.post("/preview")
async def preview_samples(req: PreviewRequest, user: User = _dep) -> Dict[str, Any]:
    from app.factory.exporters.core import _prepare, _EXPORTERS
    import tempfile

    run_dirs = [_safe_run_dir(rid, user.user_id) for rid in req.run_ids]
    if not run_dirs:
        raise HTTPException(400, "未指定对局")
    if req.fmt not in _EXPORTERS:
        raise HTTPException(400, f"未知格式: {req.fmt}")

    prepared, provenance = _prepare(run_dirs)
    # 导出到临时目录,只读 cards 预览(不污染用户 exports)
    with tempfile.TemporaryDirectory() as tmp:
        train, cards = _EXPORTERS[req.fmt](prepared, Path(tmp))
    return {
        "fmt": req.fmt,
        "total": len(cards),
        "provenance": provenance,
        "cards": cards[: max(1, min(req.limit, 100))],
    }


# ---------------------------------------------------------------------------
# 导出 + 封装(落盘到用户 exports/<dataset_id>)
# ---------------------------------------------------------------------------

@router.post("/export")
async def export_dataset(req: ExportRequest, user: User = _dep) -> Dict[str, Any]:
    from app.factory import export_all, package_dataset

    run_dirs = [_safe_run_dir(rid, user.user_id) for rid in req.run_ids]
    if not run_dirs:
        raise HTTPException(400, "未指定对局")

    dataset_id = f"ds_{uuid.uuid4().hex[:10]}"
    out_dir = _exports_base(user.user_id) / dataset_id
    bundle = export_all(run_dirs, out_dir, formats=req.formats)
    ds = package_dataset(bundle, run_dirs, name=req.name)

    return {
        "dataset_id": dataset_id,
        "name": req.name,
        "counts": bundle.counts,
        "total_samples": ds.manifest["total_samples"],
        "good_rate": ds.manifest["good_trajectory_rate"],
        "sanitize": bundle.sanitize,
        "version_triple": ds.manifest["version_triple"],
        "files": list(_EXPORT_FILES & {p.name for p in out_dir.iterdir()}),
        "notes": bundle.notes,
    }


# ---------------------------------------------------------------------------
# 列数据集 / 读数据卡 / 下载文件
# ---------------------------------------------------------------------------

@router.get("/datasets")
async def list_datasets(user: User = _dep) -> Dict[str, Any]:
    import json
    base = _exports_base(user.user_id)
    out: List[Dict[str, Any]] = []
    for ds_dir in sorted(base.glob("ds_*"), key=lambda p: p.stat().st_mtime, reverse=True):
        manifest = ds_dir / "dataset_manifest.json"
        if not manifest.exists():
            continue
        try:
            m = json.loads(manifest.read_text(encoding="utf-8"))
        except Exception:
            continue
        out.append({
            "dataset_id": ds_dir.name,
            "name": m.get("name"),
            "total_samples": m.get("total_samples"),
            "good_rate": m.get("good_trajectory_rate"),
            "counts": m.get("sample_counts"),
            "version_triple": m.get("version_triple"),
        })
    return {"count": len(out), "datasets": out}


@router.get("/datasets/{dataset_id}/card")
async def get_data_card(dataset_id: str, user: User = _dep) -> Dict[str, Any]:
    ds_dir = _safe_dataset_dir(dataset_id, user.user_id)
    card = ds_dir / "data_card.md"
    if not card.exists():
        raise HTTPException(404, "数据卡不存在")
    return {"dataset_id": dataset_id, "card_markdown": card.read_text(encoding="utf-8")}


@router.get("/datasets/{dataset_id}/file")
async def download_file(dataset_id: str, name: str, user: User = _dep) -> FileResponse:
    if name not in _EXPORT_FILES:
        raise HTTPException(400, "非法文件名")
    ds_dir = _safe_dataset_dir(dataset_id, user.user_id)
    target = (ds_dir / name).resolve()
    if ds_dir not in target.parents or not target.is_file():
        raise HTTPException(404, "文件不存在")
    return FileResponse(str(target), filename=name, media_type="application/octet-stream")
