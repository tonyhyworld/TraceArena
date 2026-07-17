#!/usr/bin/env python3
"""OS 纯度守卫（check_os_purity.py）

强制执行 docs/OS层与场景包边界约定.md 的红线：
**OS 层（engine / framework / 前端通用渲染器）不得出现场景专有名词或场景分流。**

设计：基线抑制（baseline suppression）
  - 扫描 OS 层目录，命中"场景专有名词黑名单"或"场景分流模式"即为违规。
  - 当前已知存量违规记录在 os_purity_baseline.tsv（技术债）。
  - 守卫只在**新增**违规（超过基线计数）时 fail，从而：
      * CI 现在是绿的（接受既有技术债），
      * 任何新引入的场景耦合立即变红，
      * 基线随 P2/P3 清理**只减不增**（回退会被守卫拦下）。

黑名单规则（见边界文档第 10 节）：随每个新场景包的专有名词**只增不减**。

用法：
  python -m app.tools.check_os_purity                  # 检查；新增违规则 exit 1
  python -m app.tools.check_os_purity --update-baseline # 用当前违规重建基线（仅在有意登记新债时用）
  python -m app.tools.check_os_purity --list           # 列出全部当前违规（含基线内的）
"""
from __future__ import annotations

import argparse
import re
import sys
from collections import Counter
from pathlib import Path
from typing import Dict, List, Tuple

# ── 路径 ────────────────────────────────────────────────────────────────
# 本文件位于 backend/app/tools/，仓库根 = parents[3]
REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_PATH = Path(__file__).resolve().parent / "os_purity_baseline.tsv"

# 扫描的 OS 层目录（相对仓库根）——这些目录必须与具体场景无关
SCAN_ROOTS = [
    "backend/app/contracts",
    "backend/app/engine",
    "backend/app/framework",
    "frontend/src/renderer",
    "frontend/src/operator",
]

SCAN_SUFFIXES = {".py", ".js", ".ts", ".vue"}
SKIP_DIR_PARTS = {"__pycache__", ".venv", "node_modules", ".pytest_cache"}

# ── 场景专有名词黑名单（只增不减）────────────────────────────────────────
# key = 类别（供报告归因），value = 该场景的高信号专有词（正则，大小写不敏感）。
# 只放"在通用 OS 层里绝不该出现"的高信号词，避免误伤通用词。
SCENARIO_TERMS: Dict[str, List[str]] = {
    "sanzi_duodi": [
        r"皇子", r"夺嫡", r"遗诏", r"朝堂", r"民望", r"危险值",
        r"\bprince\b", r"\bsanzi\b", r"dark_strategy",
    ],
    "capital_market": [
        r"portfolio", r"持仓", r"仓位", r"券商", r"投研", r"组合账本",
        r"market_clock", r"\bcapital_market\b",
    ],
}

# ── 场景分流模式（永远 fail，不进基线；这是硬红线）────────────────────────
# 只拦"与字符串字面量比较"（按具体场景名分流）；
# 与另一个变量比较（如 a.scenario_id == b.scenario_id 的相等性校验）是合法的，不拦。
DISPATCH_PATTERNS: List[str] = [
    r"scenario_name\s*==\s*[\"']",
    r"scenario_id\s*==\s*[\"']",
    r"==\s*[\"']sanzi",
    r"==\s*[\"']capital_market",
    r"\.startswith\(\s*[\"'](?:sanzi|capital_market)",
]

_TERM_RES: List[Tuple[str, str, "re.Pattern[str]"]] = [
    (category, term, re.compile(term, re.IGNORECASE))
    for category, terms in SCENARIO_TERMS.items()
    for term in terms
]
_DISPATCH_RES = [re.compile(p) for p in DISPATCH_PATTERNS]


class Violation:
    __slots__ = ("relpath", "lineno", "kind", "term", "category", "text")

    def __init__(self, relpath, lineno, kind, term, category, text):
        self.relpath = relpath
        self.lineno = lineno
        self.kind = kind            # "term" | "dispatch"
        self.term = term
        self.category = category
        self.text = text

    @property
    def baseline_key(self) -> str:
        # 基线按 (文件, 词) 计数，对行号移动鲁棒；分流类不进基线。
        return f"{self.relpath}\t{self.term}"


def _iter_files():
    for root in SCAN_ROOTS:
        base = REPO_ROOT / root
        if not base.exists():
            continue
        for path in base.rglob("*"):
            if path.suffix not in SCAN_SUFFIXES:
                continue
            if any(part in SKIP_DIR_PARTS for part in path.parts):
                continue
            yield path


def scan() -> List[Violation]:
    violations: List[Violation] = []
    for path in _iter_files():
        relpath = str(path.relative_to(REPO_ROOT))
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(lines, start=1):
            for pattern in _DISPATCH_RES:
                if pattern.search(line):
                    violations.append(Violation(
                        relpath, lineno, "dispatch", pattern.pattern,
                        "scenario_dispatch", line.strip()[:160],
                    ))
            for category, term, regex in _TERM_RES:
                if regex.search(line):
                    violations.append(Violation(
                        relpath, lineno, "term", term, category,
                        line.strip()[:160],
                    ))
    return violations


def load_baseline() -> Counter:
    counts: Counter = Counter()
    if not BASELINE_PATH.exists():
        return counts
    for raw in BASELINE_PATH.read_text(encoding="utf-8").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        parts = line.split("\t")
        if len(parts) < 3:
            continue
        relpath, term, count = parts[0], parts[1], parts[2]
        try:
            counts[f"{relpath}\t{term}"] = int(count)
        except ValueError:
            continue
    return counts


def write_baseline(term_violations: List[Violation]) -> None:
    counts: Counter = Counter(v.baseline_key for v in term_violations)
    header = (
        "# OS 纯度守卫基线（技术债）— 由 check_os_purity.py --update-baseline 生成\n"
        "# 每行：<文件>\\t<场景专有词>\\t<当前出现次数>\n"
        "# 这些是已知存量违规，随 P2/P3 清理**只减不增**；守卫只拦新增。\n"
        "# 场景分流（dispatch）类违规不进基线——那是硬红线，永远 fail。\n"
    )
    body = "\n".join(
        f"{key}\t{count}"
        for key, count in sorted(counts.items())
    )
    BASELINE_PATH.write_text(header + body + "\n", encoding="utf-8")


def main() -> int:
    parser = argparse.ArgumentParser(description="OS 纯度守卫")
    parser.add_argument("--update-baseline", action="store_true",
                        help="用当前违规重建基线（仅在有意登记新债时用）")
    parser.add_argument("--list", action="store_true",
                        help="列出全部当前违规")
    args = parser.parse_args()

    violations = scan()
    term_violations = [v for v in violations if v.kind == "term"]
    dispatch_violations = [v for v in violations if v.kind == "dispatch"]

    if args.update_baseline:
        write_baseline(term_violations)
        print(f"✅ 已重建基线：{BASELINE_PATH.relative_to(REPO_ROOT)}")
        print(f"   登记 {len(term_violations)} 处存量场景专有词违规。")
        if dispatch_violations:
            print(f"⚠️  另有 {len(dispatch_violations)} 处场景分流违规——"
                  "不进基线，必须修掉。")
        return 0

    if args.list:
        for v in sorted(violations, key=lambda x: (x.relpath, x.lineno)):
            print(f"  {v.relpath}:{v.lineno} [{v.category}:{v.term}] {v.text}")
        print(f"\n共 {len(violations)} 处（term={len(term_violations)}, "
              f"dispatch={len(dispatch_violations)}）")
        return 0

    baseline = load_baseline()
    current = Counter(v.baseline_key for v in term_violations)

    new_term_offenders: List[str] = []
    for key, count in current.items():
        allowed = baseline.get(key, 0)
        if count > allowed:
            new_term_offenders.append(
                f"{key.replace(chr(9), '  →  ')}：当前 {count} 次 > 基线 {allowed} 次"
            )

    failed = bool(new_term_offenders or dispatch_violations)

    if not failed:
        debt = sum(baseline.values())
        print("✅ OS 纯度守卫通过。")
        if debt:
            print(f"   （基线登记的存量技术债：{debt} 处，"
                  "见 os_purity_baseline.tsv，应随重构递减）")
        return 0

    print("❌ OS 纯度守卫失败——OS 层被场景内容污染。")
    print("   参见 docs/OS层与场景包边界约定.md 第 3/8/10 节。\n")

    if dispatch_violations:
        print("【硬红线】场景分流（scenario_name==/== \"sanzi\" 等），必须删除：")
        for v in dispatch_violations:
            print(f"  {v.relpath}:{v.lineno}  {v.text}")
        print()

    if new_term_offenders:
        print("【新增场景专有名词】超过基线，把逻辑下沉到场景包，或（确属通用时）"
              "说明理由后 --update-baseline：")
        for line in new_term_offenders:
            print(f"  {line}")
        # 展示新增词的具体位置，便于定位
        offending_keys = {
            key for key, count in current.items()
            if count > baseline.get(key, 0)
        }
        print()
        for v in term_violations:
            if v.baseline_key in offending_keys:
                print(f"    {v.relpath}:{v.lineno} [{v.term}] {v.text}")
    return 1


if __name__ == "__main__":
    sys.exit(main())
