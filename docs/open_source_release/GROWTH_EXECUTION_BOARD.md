# TraceArena 增长执行板

> 目的：把“有人看到”转化为“有人运行、有人贡献、有人提出试点”。
> 这是一份内部运营工作板，不把 Star、浏览量或群人数单独当作成功。

## 当前基线

记录日期：2026-07-20

## 最新核验（2026-07-20）

维护者在公开仓库清洁副本完成了从安装到回放的验证：

- `PYTHON_BIN=.../python3 ./scripts/install.sh` 成功安装后端与 Vue 前端依赖；
- 同一 Market Replay fixture 连续运行两次，均通过验证；
- 两次 `deterministic_replay_sha256` 均为 `3250361a904b73688ebebc8a4ef04efb74f312b7f665a82f0224f7f7ccb588cb`；
- 公开证据：[Run of the Week #3](https://github.com/tonyhyworld/TraceArena/discussions/13)。
- Hugging Face 社区入口：[下一类物理世界问题讨论](https://huggingface.co/spaces/tonyworld888/tracearena-demo/discussions/1)。
- 最新主分支的 CI、前端生产构建、Ubuntu/macOS 公共运行时 smoke test 和 OpenSSF Scorecard 均通过（当前公开分发基线为 [v0.1.10](https://github.com/tonyhyworld/TraceArena/releases/tag/v0.1.10)）。

本次维护者复核（公开仓库 `main`，2026-07-20）：

- `PYTHONPATH=backend python3 backend/scripts/market_replay.py --fixture examples/market_replay/fixture.json` 通过，显示 `brokerage: disabled`、`network: disabled`，semantic digest 为 `3250361a904b73688ebebc8a4ef04efb74f312b7f665a82f0224f7f7ccb588cb`；
- 同一命令运行两次，`deterministic_replay_sha256` 完全一致；
- `frontend/npm run build` 通过。Vite 仅报告既有的 bundle 大小优化提示，不影响构建成功。

这证明公开首跑路径可复现，但**不等于外部采用**。截至本次记录，外部场景包、合格试点线索和付费收入仍按下表如实记录为 0。

| 指标 | 当前值 | 目标定义 | 证据来源 |
| --- | ---: | --- | --- |
| GitHub stars | 2 | 真实开发者认可 | GitHub repository（2026-07-20） |
| GitHub forks | 0 | 有人开始改造 | GitHub repository（2026-07-20） |
| GitHub views（近 14 天） | 177 / 4 uniques | 真实访问与独立访客 | GitHub traffic API（截至 2026-07-18） |
| GitHub clones（近 14 天） | 826 / 186 uniques | 代码被取用；需结合外部反馈判定有效采用 | GitHub traffic API（截至 2026-07-18） |
| Hugging Face likes | 0 | Demo 被收藏 | HF Space API（2026-07-20） |
| Hugging Face Demo | RUNNING；讨论 1 个、维护者跟进 1 条、外部评论 0 | 在线体验和问题征集入口 | [Space](https://tonyworld888-tracearena-demo.static.hf.space/index.html) / [Discussion #1](https://huggingface.co/spaces/tonyworld888/tracearena-demo/discussions/1) |
| 首次成功运行 | 维护者已验证 | 跑完 replay 并看到结果；外部运行仍待记录 | [Run of the Week #3](https://github.com/tonyhyworld/TraceArena/discussions/13) |
| 外部场景包 | 0 | 非维护者提交并通过审阅 | GitHub PR |
| 合格试点线索 | 0 | 有明确工作流、验收口径和时间窗 | pilot issue |
| 付费收入 | 0 | 已收款的授权服务 | 合同/发票，不公开个人信息 |

基线只用于比较变化，不能包装成用户数量、客户数量或性能指标。

## 已完成的运营动作（截至 2026-07-20）

- Product Hunt 草稿已创建并保存，状态为未排期、未公开发布：[TraceArena 草稿页](https://www.producthunt.com/products/tracearena)。
- 公开落地页已提供在线 Demo、公开版本、场景包指南和企业试点咨询邮件入口：[TraceArena landing page](https://tonyhyworld.github.io/TraceArena/)。
- 公开仓库当前 `main` 已完成无 API Key 回放与前端构建复核；外部运行、外部场景贡献、合格试点线索和付费收入仍为 0，不能提前宣传为已获得。

## 下一步 14 天执行门槛（2026-07-20 起）

这不是继续改文档的待办，而是获得外部证据的顺序。每一阶段没有达到门槛，就先修复卡点，不扩大曝光。

| 阶段 | 具体动作 | 通过门槛 | 负责人/依赖 |
| --- | --- | --- | --- |
| D1 | 创始人完成 GitHub `user` scope 和 Product Hunt 个人账号登录；创建 Product Hunt 草稿，不立即发布 | 账号可用、草稿可保存 | 需要创始人本人完成授权 |
| D2–D4 | 邀请 5 位真实 Agent/LLM 开发者一对一运行 no-key replay | 至少 3 次完成首个结果，并记录耗时/卡点 | 创始人定向发送，不群发 |
| D5 | 发布一篇 Show HN 技术帖，唯一 CTA 指向可直接运行的 Demo/Quickstart | 帖子上线且创始人能回答技术问题 | 需 HN 账号；不请求投票 |
| D6–D8 | 回复反馈并修复一个最高频阻塞点 | 至少 3 条具体技术反馈，修复有 commit | 维护者 |
| D9–D10 | 若 Product Hunt 账号具备发帖资格，发布产品；否则只保留草稿，不绕过平台限制 | 获得真实评论或明确拒绝原因 | Product Hunt 个人账号 |
| D11–D14 | 向 3 个高度匹配团队发送一对一试点评估邀请 | 至少 1 个合格对话（工作流、时间窗、验收标准） | 创始人发送，私有信息走邮箱 |

### 这套顺序为什么重要

- **先外部运行，再公开发布。** 没有第三方运行记录，流量只会放大“看过”，不会产生采用证据。
- **Show HN 只展示可运行的东西。** HN 的规则要求项目是作者亲自制作、访客可以直接试用，并且作者在场回答；不能把它写成 landing page 或募资帖，也不能请求朋友投票。
- **Product Hunt 需要个人账号。** 平台要求个人账号发布，新的个人账号可能需要完成 onboarding 并等待一周；因此先保存草稿，不把账号限制误判成产品失败。
- **企业触达只在有运行证据后进行。** 试点销售需要谈具体工作流和验收标准，不用 Star 或流量替代客户信号。

## 唯一增长漏斗

```text
技术内容曝光
    ↓
打开 Demo / README
    ↓
完成一次 no-key replay
    ↓
提交反馈或复现问题
    ↓
提出/贡献场景包、适配器或验证器
    ↓
申请评测试点
    ↓
付费范围与验收确认
```

每一条外部内容只使用一个主要 CTA：

- 入门内容 → [在线 Demo](https://tonyworld888-tracearena-demo.static.hf.space/index.html)
- 工程内容 → [Quickstart](https://github.com/tonyhyworld/TraceArena/blob/main/docs/quickstart.md)
- 生态内容 → [场景请求](https://github.com/tonyhyworld/TraceArena/issues/new?template=world-request.yml)
- 商业内容 → [评测试点申请](https://github.com/tonyhyworld/TraceArena/issues/new?template=agent-evaluation-pilot.yml)

各渠道的发布规则、草稿和指标定义见[外部分发作战手册](DISTRIBUTION_PLAYBOOK.md)。

不要在同一条帖子里同时要求 Star、试用、加入群、购买服务和贡献代码。

## 首个 14 天目标

这些是行动目标，不是对外宣传的承诺：

| 结果 | 目标 |
| --- | ---: |
| 完成 no-key replay 的真实外部运行 | 10 次 |
| 有具体内容的公开反馈 | 3 条 |
| 外部场景/验证器/适配器提案 | 1 个 |
| 返跑或二次访问的开发者 | 3 人 |
| 合格试点对话 | 1 个 |

如果 10 次外部运行中有 3 次以上卡在同一步，优先修复路径，不继续扩大曝光。

## 7 天执行节奏

| 天 | 动作 | 交付物 | 主要 CTA |
| --- | --- | --- | --- |
| D1 | 发布“模型不能给自己判分”技术短文 | 一张证据→行动→结算图 | Demo |
| D2 | 录制一段 45–60 秒回放 | 英文字幕 + 中文辅助字幕 | Demo |
| D3 | 邀请 3 位明确匹配的 Agent 开发者试跑 | 个性化邀请，不群发 | Feedback |
| D4 | 发布一次拒绝动作/失败恢复案例 | 脱敏 run 摘要和规则解释 | Quickstart |
| D5 | 发布场景包拆解 | 最小目录树 + 开发指南 | World Request |
| D6 | 回答外部问题并修复一个阻塞点 | issue/commit 链接 | Quickstart |
| D7 | 汇总真实数据 | 一页周报：运行、卡点、贡献、线索 | Roadmap |

每次发布前先确认链接可打开、Demo 可运行、文案没有把 scripted replay 描述成自主模型。

## 内容模板

### 技术问题型

> A model can claim it used a tool. Who decides whether the world actually changed?
> TraceArena separates evidence, structured actions, world events, settlement, and replay.
> The public replay is deterministic and requires no API key. What would you verify first in an agent world?

CTA：在线 Demo 或 Quickstart，二选一。

### 场景贡献型

> We are looking for a small world where agents face the same evidence, different
> incentives, explicit constraints, and an outcome that can be independently settled.
> A proposal can start with a synthetic fixture; no private data is needed.

CTA：World Request Issue。

### 企业评测型

> If your team compares agent workflows, we can model one bounded decision process
> as an auditable world and agree on the authoritative outcome before running it.
> The public replay demonstrates the evidence-to-settlement chain; private data stays private.

CTA：Pilot Issue。

## 触达纪律

- 每天最多主动邀请 3 个高度匹配对象；先读对方近期工作，再写个性化内容。
- 不购买 Star、点赞、评论、群成员或虚假流量。
- 不把同一段广告复制到多个社区；遵守各社区自我推广规则。
- 不公开邮箱、API Key、客户资料或未获授权的运行记录。
- 不声称“行业第一”“准确率提升”“保证收益”或“已有客户”，除非有可公开证据。
- 一次精确发布在 7 天内没有真实反馈，就调整问题、Demo 或 CTA，不靠刷屏补救。

## 每周复盘表

```text
week_start:
posts:
unique_repo_visits:
demo_visits:
successful_replays:
first_run_feedback:
returning_runners:
scenario_proposals:
pilot_requests:
paid_engagements:
top_blocker:
next_experiment:
evidence_links:
```

只记录能追溯到 URL、issue、PR、run manifest 或本地反馈的事实；未知就写 `unknown`，不要估算。

## 本周唯一优先级

不要同时追求十个平台。先完成：

1. 一个可观看的 60 秒决策链素材；
2. 十次真实 no-key replay；
3. 三条具体反馈；
4. 一个外部场景提案或一个合格试点线索。

达到这四个条件后，再决定是扩大开发者生态，还是把试点服务产品化。
