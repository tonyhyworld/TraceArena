# TraceArena 开源首发内容包（可直接发布）

> 状态：v0.1.10 对外分发稿（2026-07-20）。已替换为真实公开链接。发布前只需补充实际运行统计，不得编造用户、收入或性能数字。

## 统一定位

**中文**：TraceArena 是面向物理世界问题的开源 AI World OS：把资源、目标、规则、工具和结果权威加载进可运行的世界，让多个 Agent 通过博弈比较路径、持续执行并接受后果，而不只是回答问题。

**English**: TraceArena is an open runtime for auditable agent worlds with real tools, enforceable rules, and verifiable outcomes.

核心链路：

```text
evidence → structured action → world event → authoritative settlement → outcome → replay
```

世界而不是模型决定“实际上发生了什么”。结算权威可以是模拟规则、外部事实、确定性验证器，或明确声明的混合机制。

## 真实入口

- 仓库：[github.com/tonyhyworld/TraceArena](https://github.com/tonyhyworld/TraceArena)
- 在线演示：[TraceArena Demo](https://tonyworld888-tracearena-demo.static.hf.space/index.html)
- 快速开始：[docs/quickstart.md](https://github.com/tonyhyworld/TraceArena/blob/main/docs/quickstart.md)
- Market Replay：[examples/market_replay](https://github.com/tonyhyworld/TraceArena/tree/main/examples/market_replay)
- 提议场景包：[Issue #2](https://github.com/tonyhyworld/TraceArena/issues/2)
- 评测试点：[申请表](https://github.com/tonyhyworld/TraceArena/issues/new?template=agent-evaluation-pilot.yml)
- 设计合作伙伴：[公开试点招募议题](https://github.com/tonyhyworld/TraceArena/issues/7)
- 试点范围与验收：[Agent Evaluation Pilot one-pager](https://github.com/tonyhyworld/TraceArena/blob/main/docs/open_source_release/PILOT_ONE_PAGER.md)
- 商业支持：[commercial-support.md](https://github.com/tonyhyworld/TraceArena/blob/main/docs/commercial-support.md)
- 最新发布：[v0.1.10](https://github.com/tonyhyworld/TraceArena/releases/tag/v0.1.10)

## Product Hunt 草稿

Product Hunt 草稿已创建并保存，当前尚未排期、尚未公开发布：

- 草稿管理页：[TraceArena](https://www.producthunt.com/products/tracearena)
- 发布前检查：确认 Demo、仓库、首条评论和缩略图仍可访问；不要在未获得真实运行反馈前宣传用户数、收入或性能结论。
- 正式上线后唯一首要 CTA：打开无 API Key 的在线回放；评论区再引导技术反馈和场景提案。

已验证的最短路径：

```bash
git clone https://github.com/tonyhyworld/TraceArena.git
cd TraceArena
./scripts/install.sh
```

首个 Replay 不需要 API Key，不连接券商，使用版本化 fixture、离线 replay provider 和模拟账本；它用于检查运行时与证据链，不代表真实投资能力，也不构成投资建议。

## 中文创始人长文

### Agent 会调用工具，不等于它能对结果负责

过去两个月，我一直在开发一个叫“AI世界”的系统。真正做下去后，我发现最难的问题不是让 Agent 说得像一个角色，而是把它的语言变成可以核验的行动。

Agent 可以声称“我研究过了”“我已经下单”“风险已经控制”。如果系统没有核验数据来源、验证行动参数、扣减资源、产生世界事件并由独立规则结算，这些仍然只是文本。

TraceArena 因此把连续行动拆成严格链路：

```text
感知 → 研究与工具 → 结构化行动 → 世界事实 → 权威结算 → 结果 → 恢复
```

每个结果都能追问：谁在何时提交了什么行动？引用了哪些证据？世界产生了什么事件？哪个规则决定了结算？状态、资源或胜负为什么变化？

这让多智能体竞争不再只是“谁的回答更像人”，而是把资源、目标、规则和结果权威装载进一个 AI World，让不同路径在相同约束下博弈、接受后果并被比较。回放和证据因此成为帮助人类在真实执行前检查方案的依据，而不是脱离问题本身的训练数据产品。

第一版开源聚焦场景包规范、工具与代码接口、证据/事件/结算契约、确定性回放和审计导出。欢迎贡献新的世界、验证器、工具适配器、回放可视化和可复现失败案例。

仓库：[TraceArena](https://github.com/tonyhyworld/TraceArena)；五分钟入口：[Quickstart](https://github.com/tonyhyworld/TraceArena/blob/main/docs/quickstart.md)；场景提议：[Issue #2](https://github.com/tonyhyworld/TraceArena/issues/2)。

—— 张诺亚，AI世界创建者

## English developer launch post

### TraceArena: the open-source Physical World OS for multi-agent path selection

Most agent demos end when a model emits an answer. Real systems begin there.

An agent may claim that it researched a fact, called a tool, placed an order, or changed a resource. Unless another system verifies the evidence, validates the action, applies the rules, and records the outcome, that claim is still text.

TraceArena loads resources, goals, rules, tools and authoritative outcomes into the same stateful world. Multiple agents can inspect evidence, use tools, run code, submit structured actions, receive world feedback, and recover from failure. The world—not the model—decides what actually happened and which path performed better under the declared constraints.

Every material result is traceable through:

```text
evidence → action → world event → settlement → outcome
```

The first public example is a no-key, offline Market Replay with simulated portfolios and no brokerage connection.

Try it:

```bash
git clone https://github.com/tonyhyworld/TraceArena.git
cd TraceArena
./scripts/install.sh
```

Repository: https://github.com/tonyhyworld/TraceArena  
Replay: https://github.com/tonyhyworld/TraceArena/tree/main/examples/market_replay  
Scenario proposal: https://github.com/tonyhyworld/TraceArena/issues/2  
Pilot: https://github.com/tonyhyworld/TraceArena/issues/new?template=agent-evaluation-pilot.yml
Design partner call: https://github.com/tonyhyworld/TraceArena/issues/7

For a bounded enterprise workflow, the standard evaluation pilot starts at RMB
29,800 and is scoped around an agreed world contract, 10 replayable episodes,
and a comparison report. Details: https://github.com/tonyhyworld/TraceArena/blob/main/docs/open_source_release/PILOT_ONE_PAGER.md

We are looking for world builders, settlement-verifier authors, tool-adapter maintainers, replay engineers, and reproducible failure cases.

## 社区短帖

> Agent 说“我做了”，不等于世界里真的发生了。TraceArena 把证据、行动、世界事件和结算拆成独立契约：模型负责决策，世界负责判定后果。开源仓库：https://github.com/tonyhyworld/TraceArena

## HN / developer community

**Title:** Show HN: TraceArena – auditable worlds for agents with verifiable outcomes

```text
Hi HN,

I built TraceArena after repeatedly hitting the same gap in agent demos: a model
can say it used a tool or completed an action, but the model should not be the
authority on whether that action changed the world.

TraceArena runs multiple agents in a shared stateful world and records a typed
chain from evidence and structured actions to world events and scenario-owned
settlement. The repository includes a no-key Market Replay: all orders are
simulated, no brokerage is connected, and scripted replay providers are labeled
as such.

Quickstart: https://github.com/tonyhyworld/TraceArena/blob/main/docs/quickstart.md
Replay: https://github.com/tonyhyworld/TraceArena/tree/main/examples/market_replay
I would value feedback on settlement contracts, deterministic replay, scenario
package boundaries, and interoperability with other environment APIs.
```

## English developer post: a non-financial benchmark

### A rejected action is part of the result

Most agent evaluations report whether the final answer looks correct. That
misses an important signal: did the agent respect the world's dependencies,
and can we explain why an unsafe action was rejected?

TraceArena's public Incident Response World is a small, synthetic benchmark for
that question. Two roles share the same evidence and must move through:

```text
acknowledge → mitigate → health check → resolve
```

The reference fixture deliberately tries to declare the incident resolved too
early. The world rejects it with `passing_health_check_required`, records the
reason, and only settles the incident after a passing health check. The replay
is deterministic, requires no API key, and does not connect to production
systems.

Benchmark card:
https://github.com/tonyhyworld/TraceArena/blob/main/docs/benchmarks/incident-response-v0.md

Runnable example:
https://github.com/tonyhyworld/TraceArena/tree/main/examples/incident_response_world

I would value one technical response: which dependency, evidence rule, or
failure category should a long-horizon agent benchmark make explicit next?

## 中文技术短帖：被拒绝的行动也是评测结果

很多 Agent 评测只看最后答案是否像正确答案，却忽略了一个关键问题：Agent 是否遵守了世界中的依赖关系？一次不安全的行动为什么被拒绝？

TraceArena 新增了一个合成应急响应 Benchmark。两个角色共享同一组证据，必须按顺序完成：

```text
确认事件 → 提出缓解 → 健康检查 → 宣布恢复
```

fixture 故意尝试提前宣布恢复，世界会记录并拒绝该行动，原因是
`passing_health_check_required`；只有健康检查通过后，结算才会将事件标记为 resolved。整个示例不需要 API Key，不连接生产系统。

Benchmark Card：
https://github.com/tonyhyworld/TraceArena/blob/main/docs/benchmarks/incident-response-v0.md

欢迎讨论：长程 Agent 评测还应该把哪些依赖、证据规则或失败类型显式化？

## 发布与证据纪律

- 不使用“全球首个”“行业唯一”等无法证明的表述。
- 不把脚本 Replay Agent 描述成自主大模型。
- 不承诺盈利、准确率或客户结果；资本市场示例始终附免责声明。
- 首发前才填写安装耗时、外部运行数、贡献者数等统计，并注明采集日期、commit 和环境。
- 只引用匿名且获授权的客户反馈；不在公开日志记录个人邮箱、API Key 或未公开业务细节。
- 每条内容统一指向 Demo、Quickstart、Replay、场景提议或试点申请中的一个明确 CTA。

## 首月内容节奏

| 时点 | 主题 | 证据资产 | CTA |
|---|---|---|---|
| D1 | 开源首发 | Quickstart、Replay、在线 Demo | 跑示例 |
| D3 | 模型不能宣布自己成功 | Action/Event/Settlement 契约 | 阅读文档 |
| D5 | 拒单与失败恢复 | 可复现运行记录 | 提交失败案例 |
| D8 | 第一个场景包 | 场景包开发指南 | 提交 Issue/PR |
| D15 | Run of the Week | 带 digest 的回放 | 参与讨论 |
| D22 | Agent 评测试点 | 匿名评测模板 | 申请试点 |
| D30 | 透明月报 | 运行、贡献、失败和线索汇总 | 查看路线图 |

商业支持入口：[commercial-support.md](https://github.com/tonyhyworld/TraceArena/blob/main/docs/commercial-support.md)。公开指标只用于生态透明度，不能推导收入或客户承诺。
