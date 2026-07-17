"""
P0-1 LocationRegistry — 地点注册表

加载并注册场景包中定义的地点，提供查询接口。
"""
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

from app.core.interfaces import LocationConfig

logger = logging.getLogger(__name__)


class LocationRegistry:
    """地点注册表：管理所有地点配置"""

    def __init__(self):
        self._locations: Dict[str, LocationConfig] = {}

    def load_from_config(self, locations_cfg: List[Dict[str, Any]]) -> None:
        """从 locations.yaml 配置加载地点"""
        for item in locations_cfg:
            if not isinstance(item, dict):
                continue
            loc = LocationConfig(**item)
            self._locations[loc.location_id] = loc
        logger.info(f"[LocationRegistry] 加载 {len(self._locations)} 个地点")

    def get(self, location_id: str) -> Optional[LocationConfig]:
        return self._locations.get(location_id)

    def exists(self, location_id: str) -> bool:
        return location_id in self._locations

    def all_ids(self) -> List[str]:
        return list(self._locations.keys())

    @property
    def locations(self) -> Dict[str, LocationConfig]:
        return dict(self._locations)
