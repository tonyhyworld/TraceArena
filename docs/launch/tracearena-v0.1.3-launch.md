# TraceArena public launch kit

This document is the canonical copy for the first public developer outreach.
Keep the claims tied to the public, no-key replay and do not imply that the
demo calls an LLM or produces investment advice.

## One-line description

TraceArena is the open-source runtime for auditable multi-agent worlds: agents
act under real constraints, the world settles consequences, and every run
leaves a watchable, verifiable trajectory.

## Short announcement — English

TraceArena is now open for public developer testing.

It gives agents a shared world, bounded observations, explicit tools and rules,
and an independent settlement layer. The important output is not just a final
answer or a leaderboard score. It is the trajectory: what an agent observed,
which action it requested, what the world accepted, what changed next, and who
had authority to settle the result.

Try the safe three-round AI World demo:
https://tonyworld888-tracearena-demo.static.hf.space/index.html

Then run the no-key replay locally and build your own scenario pack:
https://github.com/tonyhyworld/TraceArena

Scenario packs are welcome for engineering, operations, governance, education,
research, business analysis, and strategy games.

## 短公告 — 中文

TraceArena 现已开放开发者公开体验。

它为智能体提供共同的世界、有限观察、明确工具和可执行规则，再由独立结算层裁定后果。
真正有价值的输出不只是答案或排行榜，而是完整轨迹：智能体看到了什么、请求了什么行动、
世界接受了什么、之后发生了什么变化，以及最终由谁完成结算。

欢迎体验安全的三轮 AI 世界演示：
https://tonyworld888-tracearena-demo.static.hf.space/index.html

然后在本地运行无 Key 回放，并创建你自己的场景包：
https://github.com/tonyhyworld/TraceArena

欢迎贡献软件工程、企业运营、治理、教育、科研、商业分析和策略博弈等场景包。

## Who should try it

- Agent engineers who need more than prompt/answer evaluation.
- Researchers studying tool use, planning, adaptation, or failure recovery.
- Product teams that need replayable evidence for multi-agent decisions.
- Domain experts who can encode a world contract and settlement authority.

## Feedback questions

Ask each early user:

1. What did you think TraceArena was before running the demo?
2. Which part of the decision chain was easiest or hardest to understand?
3. What world would you build first?
4. Would you run it locally, connect a model, or contribute a scenario pack?

## Public-demo boundary

The hosted demo uses deterministic synthetic data in the browser. It does not
call an LLM, connect to real markets or brokerages, accept API keys, or provide
investment advice. Those limits are intentional and should remain explicit in
every launch post.

For follow-up execution, use the [30-day adoption plan](30-day-adoption-plan.md)
and the [Chinese social-post variants](tracearena-social-posts.zh-CN.md).
