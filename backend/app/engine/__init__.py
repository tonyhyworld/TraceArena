"""
AI 引擎 OS 层

七层架构：
  L0 Scenario Boot Kernel   — 场景包加载/校验/注册/装配
  L1 World State Kernel      — 运行时世界状态唯一来源
  L2 Perception Kernel       — Agent 局部感知包生成
  L3 Agent Runtime           — 大模型调用与决策
  L4 Action/Sandbox Runtime  — 动作/工具/脚本执行
  L5 Evaluation & Causal Physics — 双轨评价与因果物理裁决
  L6 Presentation/Render Kernel  — 导演叙事与渲染协议
  横切 Trace/Recorder/Audit  — 全链路记录、审计、回放
"""
from app.engine.main import EngineOS
from app.engine.scenario_boot.loader import ScenarioBootKernel, load_scenario
from app.engine.scenario_boot.registry import ScenarioRuntime

__all__ = [
    "EngineOS",
    "ScenarioBootKernel",
    "load_scenario",
    "ScenarioRuntime",
]
