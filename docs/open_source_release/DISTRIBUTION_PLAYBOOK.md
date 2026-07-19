# TraceArena 外部分发作战手册

> 目的：把真实可运行的 Physical World OS 交给能试用、能复盘、能贡献的人。每个渠道只使用一个主要 CTA，不购买流量，不请求刷票。

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
Show HN: TraceArena – an open-source Physical World OS for comparing agent paths
```

首帖只讲一个可验证事实：从干净检出开始，一条安装命令运行无 Key Replay，两次运行产生相同的确定性摘要。CTA 只指向 [Quickstart](https://github.com/tonyhyworld/TraceArena/blob/main/docs/quickstart.md)。

发布前必须人工撰写标题和评论；不要请求朋友投票、不要重复发布、不要把帖子写成广告。Show HN 要求项目可直接试用，并且作者本人能参与讨论。规则见 <https://news.ycombinator.com/showhn.html> 和 <https://news.ycombinator.com/newsguidelines.html>。

### 2. Product Hunt

适合条件：在线 Demo、产品说明、首条评论和创始人故事已经准备好。

产品描述（可作为草稿，发布前由创始人按实际情况修改）：

```text
TraceArena is an open-source Physical World OS for multi-agent decision worlds. Load resources, goals, rules, tools, and outcomes; let agents compete under shared constraints; compare paths before controlled execution.
```

主要链接应直接指向可体验的 Demo 或 GitHub，而不是只指向邮箱收集页。Product Hunt 要求个人账号发布，建议由创始人本人提交；新账号可能需要完成 onboarding 或等待一周。官方说明：<https://help.producthunt.com/en/articles/479557-how-to-post-a-product>。

CTA：在线 Demo。不要在同一帖里同时要求 Star、贡献代码和购买服务。

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
