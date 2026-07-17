"""
WorldObjectRegistry：世界对象注册表

基于 app/framework/objects.py 的 WorldObjectRuntime，
提供统一的注册、查询、快照接口供 RuleWorldContext 使用。
"""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.framework.objects import WorldObjectRuntime


class WorldObjectRegistry:
    """管理所有世界对象的注册表。由 RuleWorldContext 持有。"""

    def __init__(self, objects_cfg: List[Dict[str, Any]]):
        self._objects: Dict[str, WorldObjectRuntime] = {}
        for cfg in (objects_cfg or []):
            obj = WorldObjectRuntime(cfg)
            self._objects[obj.id] = obj

    def get(self, object_id: str) -> WorldObjectRuntime:
        if object_id not in self._objects:
            raise KeyError(f"WorldObject '{object_id}' 不存在")
        return self._objects[object_id]

    def all_ids(self) -> List[str]:
        return list(self._objects.keys())

    def public_snapshot(self) -> List[Dict[str, Any]]:
        """返回所有 public=True 对象的公开视图，供 WorldSnapshot.world_objects 用。"""
        result = []
        for obj in self._objects.values():
            if obj.public:
                result.append(obj.public_view())
        return result
