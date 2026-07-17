# 离线 Market Replay

[English](README.md) | [简体中文](README.zh-CN.md)

这是 AI 世界行动流水线的确定性、无 Key 证明。它使用合成 fixture，不连接券商，也不调用 LLM 或 MCP 服务。

在仓库根目录运行：

```bash
PYTHONPATH=backend python backend/scripts/market_replay.py \
  --fixture examples/market_replay/fixture.json \
  --output ./runs/market_replay_demo \
  --locale zh-CN
```

命令执行正式的 EngineOS 路径：

```text
ReplayProvider → ActionPack → WorldAction → WorldEvent
              → ExternalObservation → SettlementRecord → replay_deterministic.json
```

使用 `--locale en-US` 可生成英文 CLI 输出、摘要和固定行动理由。语言不会改变 fixture、证据 ID、结算或回放结果。

fixture 标记为 `internal_synthetic_pending_approval`：它是工程验证数据，不是公开金融数据集。该示例不构成投资建议，也不代表未来收益。
