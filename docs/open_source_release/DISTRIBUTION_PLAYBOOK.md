# TraceArena 外部分发作战手册

> 目的：把真实可运行的 AI World OS 交给能加载世界、运行目标、复盘过程并贡献场景的人。每个渠道只使用一个主要 CTA，不购买流量，不请求刷票。

## 当前统一入口

- 主仓库：<https://github.com/tonyhyworld/TraceArena>
- 在线 Demo：<https://tonyworld888-tracearena-demo.static.hf.space/index.html>
- 五分钟上手：<https://github.com/tonyhyworld/TraceArena/blob/main/docs/quickstart.md>
- 清洁环境验证：<https://github.com/tonyhyworld/TraceArena/discussions/13>
- 场景包贡献：<https://github.com/tonyhyworld/TraceArena/issues/2>
- 商业评测试点：<https://github.com/tonyhyworld/TraceArena/issues/7>
- Product Hunt / social thumbnail：[`tracearena-physical-world-os-thumbnail.png`](../../docs/assets/tracearena-physical-world-os-thumbnail.png)

## 渠道优先级

### 1. Hacker News — Show HN

适合条件：用户可以直接运行 Demo 或本地 Replay，作者本人在线回答技术问题。

建议标题：

```text
Show HN: TraceArena – an open-source AI World OS where agents compete to reach a goal
```

首帖只讲一个可验证事实：从干净检出开始，一条安装命令运行无 Key Replay，两次运行产生相同的确定性摘要。CTA 只指向 [Quickstart](https://github.com/tonyhyworld/TraceArena/blob/main/docs/quickstart.md)。

发布前必须人工撰写标题和评论；不要请求朋友投票、不要重复发布、不要把帖子写成广告。Show HN 要求项目可直接试用，并且作者本人能参与讨论。规则见 <https://news.ycombinator.com/showhn.html> 和 <https://news.ycombinator.com/newsguidelines.html>。

### 2. Product Hunt

适合条件：在线 Demo、产品说明、首条评论和创始人故事已经准备好。

产品描述（可作为草稿，发布前由创始人按实际情况修改）：

```text
TraceArena is an open-source AI World OS for everyone. Define a goal, load resources, rules and tools, and let multiple agents compete inside the same world. Capital markets, city governance, drug discovery, logistics—or a problem only you understand—can become a runnable scenario whose full decision path unfolds visibly.
```

首条 Maker 评论草稿：

```text
I built TraceArena around a simple idea: anyone should be able to load a problem as an AI World, define the goal, resources and rules, and let agents work toward it continuously. In a real workflow, the hard question is not whether an answer sounds convincing; it is whether the world accepted the action, applied the consequence, and can show the path to the outcome.

TraceArena loads a concrete problem as an AI World: resources, goals, rules, tools, evidence boundaries, and settlement authority. Multiple agents then compete under the same constraints, while every decision, action, world event and outcome can be watched and replayed. The public demo is synthetic, browser-local, and requires no API key; the open-source runtime includes deterministic replay, a full frontend, and scenario-pack guides.

If you build agents or work on a real domain, I would love to know the first world you would load and the goal you would ask agents to achieve.
```

建议标题：`TraceArena — Load any world, let agents compete to reach the goal`
首图：[`tracearena-physical-world-os-thumbnail.png`](../../docs/assets/tracearena-physical-world-os-thumbnail.png)

主要链接应直接指向可体验的 Demo 或 GitHub，而不是只指向邮箱收集页。Product Hunt 要求个人账号发布，建议由创始人本人提交；新账号可能需要完成 onboarding 或等待一周。官方说明：<https://help.producthunt.com/en/articles/479557-how-to-post-a-product>。

CTA：在线 Demo。不要在同一帖里同时要求 Star、贡献代码和购买服务。

#### Product Hunt 首日回复节奏

| 时段 | 动作 | 唯一 CTA |
| --- | --- | --- |
| 上线前 | 创始人确认 Demo、Quickstart、草稿图片和首条评论均可打开 | 不发布、不提前请求投票 |
| 上线后 0–2 小时 | 回复每一条具体问题，优先解释世界如何定义目标、资源和规则 | 在线 Demo |
| 2–8 小时 | 发布一条真实回放中的决策链截图或摘要，不夸大结果 | 在线 Demo |
| 8–24 小时 | 汇总最常见的场景建议，邀请一位评论者提交 World Request | 场景提案 |

评论回复原则：先回答对方的问题，再给一个下一步；不把维护者自测说成外部采用，不承诺通用最优解、收益或客户结果。

### 3. Hugging Face Spaces

把 Space 当作可运行的第一接触面：首屏说明“加载世界、比较路径、由世界结算”，README 提供 GitHub、清洁 Replay 和场景贡献链接。Space 状态、构建日志和首个交互结果要在发布后核验；不要只以 `RUNNING` 判断成功。

当前 Demo：<https://huggingface.co/spaces/tonyworld888/tracearena-demo>。

### 4. GitHub Discussions / Issues

这里承接已经运行过的人：

- 运行证据 → [Run of the Week](https://github.com/tonyhyworld/TraceArena/discussions/13)
- 新领域问题 → [场景包招募](https://github.com/tonyhyworld/TraceArena/issues/2)
- 企业工作流 → [设计合作伙伴试点](https://github.com/tonyhyworld/TraceArena/issues/7)

每次回复只推进一个下一步：复现、贡献或试点。公开记录应区分维护者验证和外部采用。

## 14 天实验指标

只记录有证据的事实：

```text
unique_repo_visits:
successful_external_replays:
specific_feedback_items:
returning_runners:
scenario_proposals:
qualified_pilot_leads:
paid_engagements:
evidence_links:
```

如果没有外部运行，不要把维护者自测填入 `successful_external_replays`。如果一个渠道连续两次没有具体反馈，调整入口或内容，不靠增加发布频率补救。
