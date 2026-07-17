"""
模块7:批量生产编排(Orchestrator)

把"跑一次实验"升级成"下一张生产订单"。一张订单 = N局 × M模型 × K场景
× R重复,排队跑、失败自动重跑、进度可查,跑完可一条龙接到导出+封装。

复用 BenchmarkRunner(它已处理单场景的 R重复×轮换×M模型),编排层只负责:
  - 跨场景循环(BenchmarkSpec 是单场景的)
  - 作业级 try/except + 有限重跑
  - 进度/状态跟踪(可查)
  - 收集全部产出 run 目录 → export_all → package_dataset 一条龙
"""
from __future__ import annotations

import asyncio
import logging
import time
import uuid
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass
class ProductionJob:
    """订单里的一个作业 = 一个场景 × 一组模型 × R重复(交给 BenchmarkRunner)。"""
    job_id: str
    scenario_path: str
    competitors: List[Dict[str, Any]]   # [{id, provider, model}, ...] 即 CompetitorSpec 字段
    repeats: int = 3
    status: str = "pending"             # pending/running/done/failed
    attempts: int = 0
    run_dirs: List[str] = field(default_factory=list)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "job_id": self.job_id, "scenario_path": self.scenario_path,
            "competitors": self.competitors, "repeats": self.repeats,
            "status": self.status, "attempts": self.attempts,
            "run_dirs": self.run_dirs, "error": self.error,
        }


@dataclass
class ProductionOrder:
    """一张生产订单。"""
    order_id: str
    jobs: List[ProductionJob]
    output_root: str
    max_retries: int = 1
    created_at: float = field(default_factory=time.time)
    status: str = "pending"             # pending/running/done/partial/failed

    def progress(self) -> Dict[str, Any]:
        by_status: Dict[str, int] = {}
        for j in self.jobs:
            by_status[j.status] = by_status.get(j.status, 0) + 1
        done = by_status.get("done", 0)
        return {
            "order_id": self.order_id,
            "status": self.status,
            "total_jobs": len(self.jobs),
            "by_status": by_status,
            "percent": round(100.0 * done / len(self.jobs), 1) if self.jobs else 0.0,
            "run_dirs": [rd for j in self.jobs for rd in j.run_dirs],
        }

    def to_dict(self) -> Dict[str, Any]:
        return {
            "order_id": self.order_id, "output_root": self.output_root,
            "max_retries": self.max_retries, "created_at": self.created_at,
            "status": self.status,
            "jobs": [j.to_dict() for j in self.jobs],
        }


def build_order(
    scenarios: List[str],
    competitor_sets: List[List[Dict[str, Any]]],
    *,
    repeats: int = 3,
    output_root: str = "./factory_runs",
    max_retries: int = 1,
) -> ProductionOrder:
    """生成订单:每个场景 × 每组模型 = 一个作业。

    scenarios: 场景包路径列表(K个)
    competitor_sets: 模型组合列表,每组是一个 competitor 列表(M个模型的组合)
    """
    order_id = f"order_{uuid.uuid4().hex[:8]}"
    jobs: List[ProductionJob] = []
    for si, scenario in enumerate(scenarios):
        for ci, competitors in enumerate(competitor_sets):
            jobs.append(ProductionJob(
                job_id=f"{order_id}_s{si}_c{ci}",
                scenario_path=scenario,
                competitors=list(competitors),
                repeats=repeats,
            ))
    return ProductionOrder(
        order_id=order_id, jobs=jobs,
        output_root=str(Path(output_root) / order_id),
        max_retries=max_retries,
    )


async def _run_job(job: ProductionJob, output_root: str) -> None:
    """跑一个作业(委托 BenchmarkRunner)。失败抛出,由上层决定重跑。"""
    from app.benchmark.models import BenchmarkSpec, CompetitorSpec
    from app.benchmark.runner import BenchmarkRunner

    job.attempts += 1
    job.status = "running"
    spec = BenchmarkSpec(
        scenario_path=job.scenario_path,
        competitors=[CompetitorSpec(**c) for c in job.competitors],
        repeats=job.repeats,
        output_dir=str(Path(output_root) / job.job_id),
    )
    report = await BenchmarkRunner(spec).run()
    # 收集本作业产出的 run 目录。BenchmarkRunner 实际落盘结构是
    # output_dir/<benchmark_id>/runs/run_xxx(多一层 runs/,真实跑单验出),
    # 兼容两种布局都查;都没有则报错——绝不把 bench 目录误当 run 目录
    # 传给导出器(那会静默产出空数据集)。
    bench_dir = Path(report.output_dir)
    run_dirs = [str(p) for p in (bench_dir / "runs").glob("run_*") if p.is_dir()]
    if not run_dirs:
        run_dirs = [str(p) for p in bench_dir.glob("run_*") if p.is_dir()]
    if not run_dirs:
        raise RuntimeError(f"作业完成但未找到任何 run 目录: {bench_dir}")
    job.run_dirs = run_dirs
    job.status = "done"
    job.error = None


async def run_order(
    order: ProductionOrder,
    *,
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> ProductionOrder:
    """串行跑完订单(对局本身已是重 IO,串行避免 provider 限流雪崩)。
    失败作业自动重跑至 max_retries;进度通过 on_progress 回调外露。"""
    order.status = "running"
    for job in order.jobs:
        while True:
            try:
                await _run_job(job, order.output_root)
                break
            except Exception as e:
                job.error = str(e)
                logger.warning("[factory] 作业 %s 失败(第%d次): %s",
                               job.job_id, job.attempts, e)
                if job.attempts > order.max_retries:
                    job.status = "failed"
                    break
        if on_progress:
            try:
                on_progress(order.progress())
            except Exception:
                pass

    done = sum(1 for j in order.jobs if j.status == "done")
    if done == len(order.jobs):
        order.status = "done"
    elif done == 0:
        order.status = "failed"
    else:
        order.status = "partial"
    return order


async def run_order_and_package(
    order: ProductionOrder,
    dataset_out: str,
    *,
    formats: Optional[List[str]] = None,
    dataset_name: str = "ai-world-dataset",
    on_progress: Optional[Callable[[Dict[str, Any]], None]] = None,
) -> Dict[str, Any]:
    """一条龙:跑订单 → 导出 → 封装数据集。返回汇总。"""
    from app.factory.exporters import export_all
    from app.factory.packager import package_dataset

    await run_order(order, on_progress=on_progress)
    all_runs = [rd for j in order.jobs for rd in j.run_dirs]
    if not all_runs:
        return {"order": order.progress(), "dataset": None,
                "error": "订单未产出任何对局"}

    bundle = export_all(all_runs, dataset_out, formats=formats)
    dataset = package_dataset(bundle, all_runs, name=dataset_name)
    return {
        "order": order.progress(),
        "export": {"counts": bundle.counts, "sanitize": bundle.sanitize},
        "dataset": {
            "manifest": dataset.manifest_path,
            "card": dataset.card_path,
            "total_samples": dataset.manifest["total_samples"],
            "good_rate": dataset.manifest["good_trajectory_rate"],
        },
    }
