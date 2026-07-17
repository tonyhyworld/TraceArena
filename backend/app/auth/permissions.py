"""
账户体系 · 功能权限清单

固定的 7 个权限 key(细粒度勾选,不是预设角色)。前端管理页面、CLI 建号脚本、
后端依赖注入全部从这一份引用，不会出现前后端权限清单失步的问题。

数据权限(普通用户只能看自己的数据)不在这里管——那是阶段3已经靠 user_id
路径隔离实现的固定规则，不需要额外的 key。
"""
from __future__ import annotations

from enum import Enum
from typing import Any, Dict, List


class Permission(str, Enum):
    ACCESS_VIEWER = "access_viewer"
    ACCESS_OPERATOR = "access_operator"
    CONTROL_GAME = "control_game"
    INJECT_ORACLE = "inject_oracle"
    EDIT_MODEL_CONFIG = "edit_model_config"
    MANAGE_SCENARIO = "manage_scenario"
    RUN_BENCHMARK = "run_benchmark"
    EXPORT_DATA = "export_data"


PERMISSION_CATALOG: List[Dict[str, Any]] = [
    {"key": Permission.ACCESS_VIEWER.value, "label": "使用观众端", "group": "总闸"},
    {"key": Permission.ACCESS_OPERATOR.value, "label": "使用运营台", "group": "总闸"},
    {"key": Permission.CONTROL_GAME.value, "label": "对局控制(播放/暂停/单步/重置/回放)", "group": "动作"},
    {"key": Permission.INJECT_ORACLE.value, "label": "神谕注入", "group": "动作"},
    {"key": Permission.EDIT_MODEL_CONFIG.value, "label": "修改模型配置(BYOK)", "group": "动作"},
    {"key": Permission.MANAGE_SCENARIO.value, "label": "上传/切换场景包", "group": "动作"},
    {"key": Permission.RUN_BENCHMARK.value, "label": "运行基准测试", "group": "动作"},
    {"key": Permission.EXPORT_DATA.value, "label": "导出训练数据", "group": "动作"},
]

ALL_PERMISSION_KEYS: List[str] = [item["key"] for item in PERMISSION_CATALOG]
