# 资本市场投资模拟 v0.2

两位投资 Agent 在相同本金与工具权限下对决：**真实行情 + 模拟成交**，限时 **1 小时墙钟**，按终局组合总资产分胜负。

## 角色

- `investor_a` 陈稳：价值派（宪章见 `agents/investor_a/AGENT.md`）
- `investor_b` 林锋：成长派（宪章见 `agents/investor_b/AGENT.md`）

## 世界模型

- **无地图**：不是地点走动场景，是信息 → Harness → 账本。
- **行动**：`buy_asset` / `sell_asset` / `wait_and_review`；真实标的在 `parameters.asset_id`。
- **对象**：`portfolio_book`（账本）+ `risk_dashboard`（风险锚点）。
- **能力**：不预置行情；Agent 在循环中发现 MCP / 技能 / 写代码。
- **结算**：`evaluation/plugin.py` 维护组合账本；OS 只做调度与追溯。

## 时钟与终局

- 1 tick ≈ 60 真实秒（见 `world/clock.yaml`）
- 主终局：墙钟 3600 秒；安全帽 `tick_limit: 120`
- 清盘线：组合总资产 < 700

## 运行

```bash
cd backend
AIWORLD_CONFIG=framework.capital_market.yaml SMOKE_TICKS=2 PYTHONPATH=. python3 smoke_run.py
```

或使用根目录 `framework.yaml`（已指向本场景）。

## 边界

本场景仅用于模拟与模型评测，不构成现实投资建议。
