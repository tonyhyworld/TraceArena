"""
模块6:数据集封装 + 数据卡(Packager)

把模块4的散 JSONL 打成"数据集"实体——可复现、可交付、可验货的单元。
双视图(蓝图约束0):
  - 机器视图 dataset_manifest.json:纯元数据 + 版本三元组(可复现锁)
  - 人类视图 data_card.md:给采购决策者的一页纸(教什么能力/良品率/一句话结论)

版本三元组(可复现的物理保证):
  scenario_version(场景包)+ engine_commit(引擎)+ exporter_version(导出器)
  三者锁定 → 买方能用同样输入重跑出同样数据集。
"""
from __future__ import annotations

import json
import subprocess
from collections import Counter
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Dict, List, Optional

from app.factory.exporters.core import ExportBundle
from app.factory.trajectory import iter_trajectories
from app.factory.quality import score_trajectory

# 导出器版本:导出格式契约变动时手动 +1,进版本三元组
EXPORTER_VERSION = "1.0.0"

# 十维能力中文名(数据卡"教什么能力"画像用)
_DIM_ZH = {
    "understanding": "理解局势", "memory": "运用历史", "reasoning": "因果推理",
    "planning": "分阶段规划", "judgment": "权衡取舍", "selection": "目标选择",
    "execution": "执行落地", "risk_control": "风险控制", "tool_use": "工具运用",
    "recovery": "止损修复",
}


def _engine_commit() -> str:
    try:
        return subprocess.check_output(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=Path(__file__).resolve().parents[3],
            stderr=subprocess.DEVNULL,
        ).decode().strip()
    except Exception:
        return "unknown"


@dataclass
class Dataset:
    manifest_path: str
    card_path: str
    manifest: Dict[str, Any]


def _capability_profile(run_dirs: List[Path]) -> Dict[str, float]:
    """聚合十维能力画像:所有干净步的 judge 十维均值,归一到 [0,1]。
    回答数据卡"这批数据教什么能力"。"""
    dim_sum: Counter = Counter()
    dim_cnt: Counter = Counter()
    for rd in run_dirs:
        for traj in iter_trajectories(rd):
            q = score_trajectory(traj)
            if not q.is_clean:
                continue
            for s in traj.steps:
                if s.is_empty_action or s.is_fallback:
                    continue
                for dim, val in (s.judge_ten_dim or {}).items():
                    dim_sum[dim] += float(val)
                    dim_cnt[dim] += 1
    profile: Dict[str, float] = {}
    for dim in _DIM_ZH:
        if dim_cnt[dim]:
            profile[dim] = round(dim_sum[dim] / dim_cnt[dim] / 100.0, 3)
    return profile


def _dataset_verdict(counts: Dict[str, int], profile: Dict[str, float],
                     dedup_ratio: float) -> str:
    """一句话结论:这批数据适合训什么。"""
    if not profile:
        return "样本不足,暂无法给出能力画像结论。"
    top = sorted(profile.items(), key=lambda kv: kv[1], reverse=True)[:2]
    weak = min(profile.items(), key=lambda kv: kv[1])
    top_zh = "、".join(_DIM_ZH.get(d, d) for d, _ in top)
    weak_zh = _DIM_ZH.get(weak[0], weak[0])
    total = sum(counts.values())
    return (
        f"本数据集共 {total} 条样本,能力偏向【{top_zh}】,"
        f"适合训练侧重这些能力的领域 agent;"
        f"【{weak_zh}】维度样本相对较弱,如需强化建议补充对应场景。"
        + (f"(去重率 {dedup_ratio:.0%},多样性良好)" if dedup_ratio < 0.15
           else f"(去重率 {dedup_ratio:.0%},存在一定模板化)")
    )


def package_dataset(
    bundle: ExportBundle,
    run_dirs: List[Path | str],
    *,
    name: str = "ai-world-dataset",
    license_note: str = "仅限约定用途;第三方模型输出的训练使用须遵循各 provider ToS",
) -> Dataset:
    """把一次导出封装成数据集(manifest + data card)。"""
    run_dirs = [Path(r) for r in run_dirs]
    out_dir = Path(bundle.out_dir)
    prov = bundle.provenance

    profile = _capability_profile(run_dirs)
    dedup_ratio = prov.get("dedup", {}).get("dup_ratio", 0.0)
    total = sum(bundle.counts.values())

    # 良品率:干净步 / (干净步 + 被硬闸拦下的局的步)——用 quality 重算
    n_clean_traj = 0
    n_total_traj = 0
    for rd in run_dirs:
        for traj in iter_trajectories(rd):
            n_total_traj += 1
            if score_trajectory(traj).is_clean:
                n_clean_traj += 1
    good_rate = round(n_clean_traj / n_total_traj, 3) if n_total_traj else 0.0

    version_triple = {
        "scenario_versions": prov.get("scenario_versions", []),
        "engine_commit": _engine_commit(),
        "exporter_version": EXPORTER_VERSION,
    }

    manifest = {
        "name": name,
        "created_from_runs": prov.get("runs", []),
        "version_triple": version_triple,
        "sample_counts": bundle.counts,
        "total_samples": total,
        "good_trajectory_rate": good_rate,
        "dedup": prov.get("dedup", {}),
        "capability_profile": profile,
        "sanitize": bundle.sanitize,
        "files": bundle.files,
        "license": license_note,
        "notes": bundle.notes,
    }
    manifest_path = out_dir / "dataset_manifest.json"
    manifest_path.write_text(
        json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8"
    )

    card_path = out_dir / "data_card.md"
    card_path.write_text(
        _render_data_card(name, manifest, profile, dedup_ratio, good_rate),
        encoding="utf-8",
    )
    return Dataset(str(manifest_path), str(card_path), manifest)


def _bar(v: float, width: int = 20) -> str:
    filled = int(round(v * width))
    return "█" * filled + "░" * (width - filled)


def _render_data_card(
    name: str, manifest: Dict[str, Any], profile: Dict[str, float],
    dedup_ratio: float, good_rate: float,
) -> str:
    counts = manifest["sample_counts"]
    vt = manifest["version_triple"]
    lines: List[str] = []
    lines.append(f"# 数据卡 · {name}\n")
    lines.append("> 给采购决策者的一页纸。技术细节见 dataset_manifest.json。\n")

    lines.append("## 一句话结论")
    lines.append(_dataset_verdict(counts, profile, dedup_ratio) + "\n")

    lines.append("## 数据构成")
    label = {"sft": "SFT 指令微调", "dpo": "DPO 偏好对",
             "episodes": "RL 完整对局", "eval": "能力评测集"}
    for fmt, n in counts.items():
        lines.append(f"- {label.get(fmt, fmt)}：{n} 条")
    lines.append(f"- **合计**：{manifest['total_samples']} 条\n")

    lines.append("## 教什么能力(十维画像)")
    if profile:
        for dim, v in sorted(profile.items(), key=lambda kv: kv[1], reverse=True):
            lines.append(f"- {_DIM_ZH.get(dim, dim):<6} `{_bar(v)}` {v:.2f}")
    else:
        lines.append("- (样本不足)")
    lines.append("")

    lines.append("## 质量画像")
    lines.append(f"- 良品率(合格轨迹占比)：**{good_rate:.0%}**")
    lines.append(f"- 去重率：{dedup_ratio:.0%}"
                 + ("(多样性良好)" if dedup_ratio < 0.15 else "(有一定模板化)"))
    san = manifest.get("sanitize", {})
    lines.append(f"- 脱敏：打码凭证 {san.get('credential_hits', 0)} 处，"
                 f"剔除敏感字段 {san.get('dropped_keys', 0)} 处")
    lines.append("")

    lines.append("## 可复现(版本三元组)")
    lines.append(f"- 场景包版本：{', '.join(vt['scenario_versions']) or '—'}")
    lines.append(f"- 引擎 commit：`{vt['engine_commit']}`")
    lines.append(f"- 导出器版本：{vt['exporter_version']}")
    lines.append("> 三者锁定即可用同样输入重跑出同样数据集。\n")

    lines.append("## 许可与边界")
    lines.append(f"- {manifest['license']}")
    if manifest.get("notes"):
        lines.append("\n## 备注")
        for n in manifest["notes"]:
            lines.append(f"- {n}")
    return "\n".join(lines) + "\n"
