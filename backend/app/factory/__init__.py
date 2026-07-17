"""
app.factory — Agent 训练数据工厂(旁路产线)

只读 Run 档案与账本,把对局轨迹归一化 → 质检 → 去重 → 导出为训练数据。
不依赖、不修改对局引擎(app.engine)——零对局链路回归风险。

模块顺序(数据流):
  trajectory(归一化,唯一真相源) → quality(质检) / dedup(去重)
    → exporters(导出,双视图) → sanitizer(脱敏) → packager(封装)
  orchestrator(批量编排,可并行)
"""
from app.factory.trajectory import (
    Trajectory,
    TrajectoryStep,
    load_trajectory,
    iter_trajectories,
)
from app.factory.quality import (
    StepQuality,
    TrajectoryQuality,
    score_step,
    score_trajectory,
)
from app.factory.dedup import (
    DedupResult,
    DupCluster,
    dedup_steps,
)
from app.factory.exporters import (
    ExportBundle,
    export_all,
)
from app.factory.sanitizer import (
    SanitizeReport,
    sanitize_rows,
)
from app.factory.packager import (
    Dataset,
    package_dataset,
    EXPORTER_VERSION,
)
from app.factory.orchestrator import (
    ProductionOrder,
    ProductionJob,
    build_order,
    run_order,
    run_order_and_package,
)

__all__ = [
    "Trajectory",
    "TrajectoryStep",
    "load_trajectory",
    "iter_trajectories",
    "StepQuality",
    "TrajectoryQuality",
    "score_step",
    "score_trajectory",
    "DedupResult",
    "DupCluster",
    "dedup_steps",
    "ExportBundle",
    "export_all",
    "SanitizeReport",
    "sanitize_rows",
    "Dataset",
    "package_dataset",
    "EXPORTER_VERSION",
    "ProductionOrder",
    "ProductionJob",
    "build_order",
    "run_order",
    "run_order_and_package",
]
