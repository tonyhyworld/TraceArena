# TraceArena 增长执行板

> 目的：把“有人看到”转化为“有人运行、有人贡献、有人提出试点”。
> 这是一份内部运营工作板，不把 Star、浏览量或群人数单独当作成功。

## 当前基线

记录日期：2026-07-18

| 指标 | 当前值 | 目标定义 | 证据来源 |
| --- | ---: | --- | --- |
| GitHub stars | 2 | 真实开发者认可 | GitHub repository |
| GitHub forks | 0 | 有人开始改造 | GitHub repository |
| Hugging Face likes | 0 | Demo 被收藏 | HF Space |
| 首次成功运行 | 待记录 | 跑完 replay 并看到结果 | first-run issue / 本地反馈 |
| 外部场景包 | 0 | 非维护者提交并通过审阅 | GitHub PR |
| 合格试点线索 | 0 | 有明确工作流、验收口径和时间窗 | pilot issue |
| 付费收入 | 0 | 已收款的授权服务 | 合同/发票，不公开个人信息 |

基线只用于比较变化，不能包装成用户数量、客户数量或性能指标。

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
