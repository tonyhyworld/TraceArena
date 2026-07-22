# 电网极端事件应急恢复世界

这是一个完全由场景包声明的 Grid2Op 电网应急恢复世界。TraceArena OS 不认识电网术语、线路编号或胜负规则；场景包提供角色、动作、资源、压力、世界适配器、结算与呈现配置。

## 运行

```bash
cd backend
pip install -r requirements.txt -r requirements-grid2op.txt
export MINIMAX_API_KEY='...'
AIWORLD_CONFIG=./scenarios/grid_emergency/runtime/framework.yaml \\
  PYTHONPATH=. python3 -m uvicorn app.main:app --host 127.0.0.1 --port 8001
```

该场景从同一公开 Grid2Op 时序的第 24 个时段、0 号线路已经断开的状态开始。三名 Agent 在同一种子、独立环境副本中竞争；Grid2Op 是物理反馈权威，不会连接真实电网或下发生产调度。

也可在不调用 LLM 的前提下验证场景包、物理环境和三条动作链：

```bash
MPLCONFIGDIR=/private/tmp/matplotlib-grid PYTHONPATH=. \\
  python3 scripts/smoke_grid_emergency_scenario.py
```
