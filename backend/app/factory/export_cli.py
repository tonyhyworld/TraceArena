"""
数据工厂导出 CLI

用法:
  python -m app.factory.export_cli --runs-dir runs/default --out exports/batch1
  python -m app.factory.export_cli --runs run_a71e9fe6 run_2b4be803 \
      --runs-root runs/default --out exports/batch1 --formats sft dpo

与 Benchmark CLI 同风格。只读档案,产出双视图 JSONL + 一份导出汇总。
"""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from app.factory.exporters import export_all


def main() -> None:
    ap = argparse.ArgumentParser(description="AI世界 数据工厂 · 训练数据导出")
    ap.add_argument("--runs-dir", type=str, default=None,
                    help="包含多个 run_* 子目录的目录(全部导出)")
    ap.add_argument("--runs", nargs="*", default=None,
                    help="指定 run 目录名(配合 --runs-root)")
    ap.add_argument("--runs-root", type=str, default="runs/default",
                    help="--runs 的根目录")
    ap.add_argument("--out", type=str, required=True, help="导出目录")
    ap.add_argument("--formats", nargs="*", default=None,
                    help="sft dpo episodes eval,缺省全部")
    ap.add_argument("--package", action="store_true",
                    help="导出后封装成数据集(manifest+数据卡)")
    ap.add_argument("--name", type=str, default="ai-world-dataset",
                    help="数据集名称(--package 时用)")
    args = ap.parse_args()

    if args.runs_dir:
        root = Path(args.runs_dir)
        run_dirs = sorted(
            p for p in root.iterdir()
            if p.is_dir() and p.name.startswith("run_")
        )
    elif args.runs:
        root = Path(args.runs_root)
        run_dirs = [root / r for r in args.runs]
    else:
        ap.error("需指定 --runs-dir 或 --runs")

    if not run_dirs:
        ap.error("未找到任何 run 目录")

    print(f"[factory] 导出 {len(run_dirs)} 个 run → {args.out}")
    bundle = export_all(run_dirs, args.out, formats=args.formats)

    print(f"[factory] 干净步 {bundle.provenance['clean_steps']} 条,"
          f"去重丢 {bundle.provenance['dedup']['dropped']} 条")
    for fmt, n in bundle.counts.items():
        print(f"  {fmt}: {n} 条(train+cards 双文件)")
    for note in bundle.notes:
        print(f"  ⚠ {note}")

    # 导出汇总落盘(供 packager/UI 消费)
    summary_path = Path(args.out) / "export_summary.json"
    summary_path.write_text(
        json.dumps({
            "files": bundle.files,
            "counts": bundle.counts,
            "provenance": bundle.provenance,
            "notes": bundle.notes,
        }, ensure_ascii=False, indent=2),
        encoding="utf-8",
    )
    # 顺带封装成数据集(manifest + 数据卡),让导出即成品
    if args.package:
        from app.factory.packager import package_dataset
        ds = package_dataset(bundle, run_dirs, name=args.name)
        print(f"[factory] 数据集封装 → {ds.card_path}")
        print(f"           良品率 {ds.manifest['good_trajectory_rate']:.0%},"
              f" 总样本 {ds.manifest['total_samples']} 条")


if __name__ == "__main__":
    main()
