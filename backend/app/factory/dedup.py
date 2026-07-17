"""
模块3:去重器(Deduplicator)

模板化轨迹(一千条"查档案,低风险收集情报"的雷同 plan)会稀释数据集价值——
买方付钱买的是多样的决策样本,不是同一句话的复读。本模块在样本进导出前
折叠近重复,每个重复簇只保留质量最高的代表。

技术选型(刻意不用 embedding):
  - 环境无 sklearn/sentence-transformers,且本产品主打"可解释"——embedding
    相似度是黑盒数字,词级 Jaccard 能明确说"这两条 plan 共享 85% 的词",
    解释力更强,且零新依赖、确定性可复现(符合蓝图版本三元组要求)。
  - 粗桶分组:只有 (action_id, intent, outcome) 相同的样本才可能是重复,
    先按签名分桶,桶内才两两比 Jaccard——把 O(n²) 压到每桶内小规模。
  - 桶内 Jaccard(词 2-shingle)≥ 阈值 → 判近重复,并查 union-find 成簇。

输出 DedupResult(双视图):
  - 机器视图:kept_ids / dropped(dropped_id → representative_id 映射)/ 统计
  - 人类视图:每个折叠簇一句人话("折叠了 12 条与 X 高度相似的'查档案'样本")
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field, asdict
from typing import Any, Dict, List, Optional, Tuple

from app.factory.trajectory import TrajectoryStep


# 近重复判定阈值:桶内两样本 plan 的词 Jaccard ≥ 此值 → 视为重复。
# 0.7 = 共享 70% 的词,足够宽以抓住模板复读,又不至于误折叠真正不同的策略。
DEFAULT_JACCARD_THRESHOLD = 0.7
_SHINGLE_K = 2  # 词 n-gram 长度


@dataclass
class DupCluster:
    """一个近重复簇。"""
    representative_id: str            # 保留的代表(质量最高)
    dropped_ids: List[str] = field(default_factory=list)
    signature: str = ""              # 粗桶签名(action|intent|outcome)
    reason: str = ""                 # 人话:为什么折叠

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


@dataclass
class DedupResult:
    """去重结果(双视图)。"""
    total_in: int = 0
    total_kept: int = 0
    total_dropped: int = 0
    dup_ratio: float = 0.0
    kept_ids: List[str] = field(default_factory=list)
    # dropped_id → representative_id
    drop_map: Dict[str, str] = field(default_factory=dict)
    clusters: List[DupCluster] = field(default_factory=list)  # 仅含发生折叠的簇
    # 人类视图
    summary: str = ""

    def to_dict(self) -> Dict[str, Any]:
        d = asdict(self)
        d["clusters"] = [c.to_dict() for c in self.clusters]
        return d


# ---------------------------------------------------------------------------
# 文本相似度(纯 Python,确定性)
# ---------------------------------------------------------------------------

_WORD_RE = re.compile(r"[\w一-鿿]+")


def _shingles(text: str, k: int = _SHINGLE_K) -> frozenset:
    """把文本切成词 k-gram 集合。中文按字、英文按词(粗粒度,确定性)。"""
    if not text:
        return frozenset()
    tokens = _WORD_RE.findall(text.lower())
    # 中文连续字拆成单字参与 shingle(粗匹配足够)
    expanded: List[str] = []
    for t in tokens:
        if re.fullmatch(r"[一-鿿]+", t) and len(t) > 1:
            expanded.extend(list(t))
        else:
            expanded.append(t)
    if len(expanded) < k:
        return frozenset(expanded)
    return frozenset(
        " ".join(expanded[i:i + k]) for i in range(len(expanded) - k + 1)
    )


def _jaccard(a: frozenset, b: frozenset) -> float:
    if not a and not b:
        return 1.0
    if not a or not b:
        return 0.0
    inter = len(a & b)
    union = len(a | b)
    return inter / union if union else 0.0


# ---------------------------------------------------------------------------
# Union-Find(成簇)
# ---------------------------------------------------------------------------

class _UF:
    def __init__(self, ids: List[str]):
        self.parent = {i: i for i in ids}

    def find(self, x: str) -> str:
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a: str, b: str) -> None:
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


# ---------------------------------------------------------------------------
# 主入口
# ---------------------------------------------------------------------------

def _dedup_text(step: TrajectoryStep) -> str:
    """去重比对用的文本:plan 为主,空则退回 raw_response 摘要。"""
    return step.plan or step.character_monologue or step.raw_response[:200] or ""


def _bucket_signature(step: TrajectoryStep) -> str:
    return f"{step.action_id}|{step.intent}|{step.outcome}"


def dedup_steps(
    steps: List[TrajectoryStep],
    quality_by_id: Optional[Dict[str, float]] = None,
    *,
    threshold: float = DEFAULT_JACCARD_THRESHOLD,
) -> DedupResult:
    """对一批(可跨多局)步样本去重。

    quality_by_id: sample_id → 质量分(来自模块2),用于在重复簇里挑代表。
                   缺省时按出现顺序保留第一个。
    只处理"可用"样本(空动作/兜底不应进这里,调用方应先过质量硬闸)。
    """
    quality_by_id = quality_by_id or {}
    result = DedupResult(total_in=len(steps))
    if not steps:
        result.summary = "无样本"
        return result

    # 1) 粗桶分组
    buckets: Dict[str, List[TrajectoryStep]] = {}
    for s in steps:
        buckets.setdefault(_bucket_signature(s), []).append(s)

    all_ids = [s.sample_id for s in steps]
    uf = _UF(all_ids)
    shingle_cache: Dict[str, frozenset] = {}

    # 2) 桶内两两 Jaccard,近重复 union
    for sig, bucket in buckets.items():
        if len(bucket) < 2:
            continue
        for s in bucket:
            shingle_cache[s.sample_id] = _shingles(_dedup_text(s))
        for i in range(len(bucket)):
            si = bucket[i]
            for j in range(i + 1, len(bucket)):
                sj = bucket[j]
                sim = _jaccard(
                    shingle_cache[si.sample_id], shingle_cache[sj.sample_id]
                )
                if sim >= threshold:
                    uf.union(si.sample_id, sj.sample_id)

    # 3) 成簇 → 每簇挑代表(质量最高)
    clusters_map: Dict[str, List[str]] = {}
    for sid in all_ids:
        clusters_map.setdefault(uf.find(sid), []).append(sid)

    step_by_id = {s.sample_id: s for s in steps}
    kept: List[str] = []
    drop_map: Dict[str, str] = {}
    dup_clusters: List[DupCluster] = []

    for members in clusters_map.values():
        if len(members) == 1:
            kept.append(members[0])
            continue
        # 挑代表:质量分最高;并列取 sample_id 字典序最小(确定性)
        rep = max(members, key=lambda m: (quality_by_id.get(m, 0.0), -_str_rank(m)))
        kept.append(rep)
        dropped = [m for m in members if m != rep]
        for m in dropped:
            drop_map[m] = rep
        rep_step = step_by_id[rep]
        dup_clusters.append(DupCluster(
            representative_id=rep,
            dropped_ids=dropped,
            signature=_bucket_signature(rep_step),
            reason=(
                f"折叠了 {len(dropped)} 条与代表样本高度相似的"
                f"「{rep_step.action_id or '同类'}」决策"
                f"(plan 文本重合度 ≥ {threshold:.0%}),只保留质量最高的一条"
            ),
        ))

    result.total_kept = len(kept)
    result.total_dropped = len(drop_map)
    result.dup_ratio = round(len(drop_map) / len(steps), 3) if steps else 0.0
    result.kept_ids = kept
    result.drop_map = drop_map
    result.clusters = dup_clusters
    result.summary = (
        f"输入 {result.total_in} 条,折叠近重复 {result.total_dropped} 条"
        f"({result.dup_ratio:.0%}),保留 {result.total_kept} 条。"
        + (f"最大重复簇折叠 {max(len(c.dropped_ids) for c in dup_clusters)} 条。"
           if dup_clusters else "无明显模板复读。")
    )
    return result


def _str_rank(s: str) -> int:
    """把 sample_id 映射成可比较的稳定序(用于并列时确定性挑选)。"""
    return sum(ord(c) for c in s)
