"""
P1-5 RunSeedManager — 统一随机种子管理

确保所有随机行为从统一 seed 生成，支持可复现回放。
"""
from __future__ import annotations

import hashlib
import logging
import random
from typing import Optional

logger = logging.getLogger(__name__)


class RunSeedManager:
    """统一随机种子管理器"""

    def __init__(self, seed: Optional[int] = None):
        self._seed = seed if seed is not None else random.randint(0, 2**31 - 1)
        self._rng = random.Random(self._seed)
        logger.info(f"[RunSeed] 初始化种子: {self._seed}")

    @property
    def seed(self) -> int:
        return self._seed

    def next_int(self, low: int = 0, high: int = 2**31) -> int:
        return self._rng.randint(low, high)

    def next_float(self) -> float:
        return self._rng.random()

    def choice(self, seq):
        return self._rng.choice(seq)

    def shuffle(self, seq):
        self._rng.shuffle(seq)

    def state_hash(self, state_dict: dict) -> str:
        """计算状态哈希（用于回放校验）"""
        raw = str(sorted(state_dict.items()))
        return hashlib.sha256(raw.encode()).hexdigest()[:16]
