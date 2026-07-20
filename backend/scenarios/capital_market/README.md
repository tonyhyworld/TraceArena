# 资本市场投资模拟 Public Edition v0.2

两位投资 Agent 在相同本金与工具权限下对决：**可选市场研究 + 模拟成交**，限时 **1 小时墙钟**，按终局组合总资产分胜负。

这是一个可公开运行的投资决策博弈场景包，不是自动交易系统。默认配置使用 Mock Agent、无 Key 回放和模拟账本；用户可以自行配置模型 Provider，并在合法授权下启用只读市场研究工具。场景不会连接券商，也不会提交真实订单。

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

无 Key 验证请从仓库根目录运行：

```bash
PYTHONPATH=backend python backend/scripts/market_replay.py \
  --fixture examples/market_replay/fixture.json \
  --output ./runs/market_replay_demo
```

要启动完整前端，请使用公开无 Key 配置 `backend/framework.public.yaml`；要接入自己的模型或只读研究工具，请复制 `backend/framework.example.yaml` 并仅在本地填写 Provider 配置和授权凭证。

或使用根目录 `framework.yaml`（已指向本场景）。

## 边界

本场景仅用于模拟、Agent 评测和决策流程研究，不构成现实投资建议，不连接券商，不执行真实订单。行情、公告和财务数据的使用必须遵守相应数据源的服务条款与再分发限制。
