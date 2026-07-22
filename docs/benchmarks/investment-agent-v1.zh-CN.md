# 投资智能体基准 v1

## 评测目标

TraceArena 评测投资智能体能否把有引用的研究证据转化为合法的模拟订单，并留下可回放的“证据 → 决策 → 订单 → 结算”链路。确定性组合校验器计算收益率、超额收益率、最大回撤、换手率和交易成本。

主指标为：

`风险调整后超额收益 = 超额收益率 - 0.5 × 最大回撤率`

## 当前发布状态

仓库内结果是**协议基线**，不是模型排行榜。两个参赛者都是确定性脚本控制组：证据优先买入策略与现金对照策略。它只证明相同 fixture 在无 API Key、无网络、无券商连接时可以生成相同语义回放和评分。

内置合成 fixture 的来源状态仍为 `internal_synthetic_pending_approval`，拟采用的 CC0-1.0 授权也仍待维护者确认。报告会如实暴露这一状态，不把它包装成已经批准的公开金融数据集。

只有当每个结果都包含模型与服务商身份、场景和 fixture 摘要、角色轮换、随机种子、完整回放与校验器输出时，我们才会把它标为模型对比。不能独立复现的社区提交会明确标记为“未验证”。

## 复现方法

最快方式：[打开固定版本的 Colab Notebook](https://colab.research.google.com/github/tonyhyworld/TraceArena/blob/main/examples/investment_benchmark/TraceArena_Investment_Benchmark_v1.ipynb)。它会克隆 v0.1.12、运行无 Key 基准，并把生成报告与已发布基线进行核对。

```bash
python backend/scripts/investment_benchmark.py \
  --output runs/investment_agent_benchmark_v1
```

查看 `benchmark_report.json`、`LEADERBOARD.md` 和 `replay/` 下的回放文件。如果回放被修改，完整性或语义摘要与运行清单不一致，命令会拒绝生成报告。

## 评测契约

| 层级 | 规则 |
| --- | --- |
| 研究 | 新建仓必须引用已验证行情和至少两条非行情研究结果，同时满足角色专属证据规则。 |
| 标的 | 仅允许 A 股和港股的内部模拟交易。 |
| 执行 | 固定佣金 3 bps、滑点 5 bps；现金不足、持仓不足、证据过期和非交易窗口均拒单。 |
| 账本 | 现金、持仓、成交、盯市、回撤、换手率和成本由场景确定性代码维护。 |
| 排名 | 风险调整后超额收益降序；分数完全相同时以交易成本升序打破平局。 |
| 安全 | 合成 fixture、无网络、无券商、不构成投资建议，也不代表未来收益。 |

## 局限与下一步

当前两回合小样本只验证机制，不代表投资能力或统计显著性。下一版合格模型榜单需要多个隐藏市场环境、更长决策窗口、角色轮换、重复种子，以及在相同数据和成本边界下运行的真实模型智能体。

参考结果：[`benchmarks/investment-agent-v1/LEADERBOARD.md`](../../benchmarks/investment-agent-v1/LEADERBOARD.md)。
