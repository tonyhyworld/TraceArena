# Founder outreach queue

> 目标：在不刷屏、不购买流量的前提下，获得首批 10 次真实运行、3 个公开反馈、1 个场景包贡献和 1 个评测试点线索。

## 公开入口

- Repository: <https://github.com/tonyhyworld/TraceArena>
- Demo: <https://tonyworld888-tracearena-demo.static.hf.space/index.html>
- Quickstart: <https://github.com/tonyhyworld/TraceArena/blob/main/docs/quickstart.md>
- Clean-room replay evidence: <https://github.com/tonyhyworld/TraceArena/discussions/13>
- Technical discussion: <https://github.com/tonyhyworld/TraceArena/discussions/14>
- Scenario proposal: <https://github.com/tonyhyworld/TraceArena/issues/2>
- Evaluation pilot: <https://github.com/tonyhyworld/TraceArena/issues/new?template=agent-evaluation-pilot.yml>
- Design partner call: <https://github.com/tonyhyworld/TraceArena/issues/7>
- Ready-to-send messages: [OUTREACH_MESSAGES.md](OUTREACH_MESSAGES.md)

## 发送顺序

| 顺序 | 对象 | 目的 | 发送方式 | 完成证据 |
|---|---|---|---|---|
| 1 | 5 位熟悉的 Agent/LLM 开发者 | 验证首次运行是否顺畅 | 一对一私信或邮件 | 运行 ID、耗时、卡点 |
| 2 | 3 位评测/基础设施工程师 | 验证 trace、settlement、replay 价值 | 一对一私信 | 一条技术反馈 |
| 3 | 2 位潜在企业用户 | 验证评测试点需求 | 直接发送 pilot 入口 | 一个明确需求或拒绝原因 |
| 4 | Hacker News / Hugging Face 社区 | 扩大公开触达 | 先贡献讨论，再发布项目帖 | 帖子 URL、评论数 |

## 公开候选短名单（尚未联系）

以下只记录公开项目和公开入口，不代表对方同意合作，也不自动发送消息。创始人联系前应先阅读项目近期活动，针对具体技术交集一对一撰写邀请。

| 项目 | 公开入口 | 可能的技术交集 |
| --- | --- | --- |
| AWS Labs agent-evaluation | <https://github.com/awslabs/agent-evaluation> | 评测框架可对照 TraceArena 的世界结算与路径证据链。 |
| Base Agent Challenge | <https://github.com/BaseIntelligence/agent-challenge> | 竞争式 Agent 运行与隔离环境，适合讨论结果权威和复现。 |
| AgentArk | <https://github.com/P90-RushB/AgentArk> | 可扩展多模态 Agent 评测环境，适合比较 world contract 边界。 |
| AgentScope Runtime | <https://github.com/agentscope-ai/agentscope-runtime> | Agent runtime、工具治理和可观测性，与 OS 层接口有交集。 |
| Google Cloud race-condition | <https://github.com/GoogleCloudPlatform/race-condition> | 多 Agent 竞争/协作示例，适合交流事件、资源和结算模型。 |

### 2026-07-20 新增候选（仅公开入口，尚未联系）

| 项目 | 公开入口 | 可能的技术交集 |
| --- | --- | --- |
| LangChain AgentEvals | <https://github.com/langchain-ai/agentevals> | 已关注 Agent trajectory 评估；可讨论如何从“轨迹评分”扩展到由世界规则裁决的目标、资源和后果。 |
| Snowflake Agent World Model | <https://github.com/Snowflake-Labs/agent-world-model> | 提供可执行工具环境；可交流环境装载、MCP 能力和 TraceArena 场景契约的边界。 |
| AgentClash | <https://www.agentclash.dev/> | 关注受约束沙箱中的多轮 Agent 全轨迹；可讨论把竞争目标、资源消耗和权威结算显式化。 |
| OpenCity | <https://arxiv.org/abs/2410.21286> | 城市活动多 Agent 仿真方向；可作为城市治理世界的潜在技术交流对象。 |

这些对象来自 2026-07-20 的公开资料检索，不代表合作意向、用户关系或背书。第一轮仍只选择 2–3 个高度匹配对象，先阅读其近期活动，再发个性化邀请。

建议第一轮只选择 2–3 个高度匹配对象，并邀请其运行同一个公开 Demo；不要把这张表当作群发名单或客户名单。

## 首次邀请模板（中文）

你好，我在做 AI World / TraceArena：一套任何人都可以加载不同世界的开源 OS。你定义目标、资源和规则，多个 Agent 在同一个世界里竞争完成目标，世界验证事件和结果，并把整条决策链演绎出来。

现在有一个无需 API Key 的离线 Market Replay，能在几分钟内看到完整的 evidence → action → event → settlement → outcome 链路。想请你帮我跑一次，只需要告诉我三件事：

1. 从打开到看到第一个结果花了多久；
2. 哪一步最容易卡住或看不懂；
3. 你认为这对比较 Agent 路径、验证工具或设计领域世界有没有实际价值。

入口：<https://tonyworld888-tracearena-demo.static.hf.space/index.html>

## First-run invitation (English)

I’m building AI World / TraceArena, an open AI World OS where anyone can define a goal, load resources and rules, and let multiple agents compete inside the same world. The world verifies events and outcomes and makes the full decision path visible—not just the final answer.

There is a no-key offline Market Replay that exposes the full evidence → action → event → settlement → outcome chain. Could you run it once and tell me:

1. time to the first result;
2. the first confusing or blocked step;
3. whether this is useful for comparing agent paths, validating tools, or designing a domain world.

Demo: <https://tonyworld888-tracearena-demo.static.hf.space/index.html>

## 渠道纪律

- Hacker News 使用 `Show HN` 标题格式，并把重点放在可运行的技术事实和可验证问题上；遵循其官方发布要求：<https://news.ycombinator.com/showhn.html>。
- Reddit 社区先参与讨论，再考虑发帖；不要把同一内容复制到多个社区。`r/LocalLLaMA` 近期明确收紧自我推广规则，发布前必须核对版规并接受可能需要版主许可的情况。
- Hugging Face 将在线 Demo 作为主要入口，项目帖只补充技术背景；Spaces 是官方支持的可托管 Demo 形态：<https://huggingface.co/docs/hub/spaces>。
- 不购买流量、不伪造用户或收入、不把脚本 Replay Agent 描述成自主大模型。

## 运行记录

公开仓当前基线（2026-07-19）：GitHub stars 2、forks 0；GitHub 近 14 天 views 177（4 个独立访客）、clones 826（186 个独立克隆）。这些是访问信号，不等于外部运行；目前仍无外部运行、场景贡献或试点证据，后续每轮触达后重新记录。

| 编号 | 联系对象 | 渠道 | 首次运行时间 | 首个结果耗时 | 卡点 | 是否愿意贡献 | 是否潜在试点 |
|---|---|---|---|---|---|---|---|
| 01 |  |  |  |  |  |  |  |
| 02 |  |  |  |  |  |  |  |
| 03 |  |  |  |  |  |  |  |
| 04 |  |  |  |  |  |  |  |
| 05 |  |  |  |  |  |  |  |
| 06 |  |  |  |  |  |  |  |
| 07 |  |  |  |  |  |  |  |
| 08 |  |  |  |  |  |  |  |
| 09 |  |  |  |  |  |  |  |
| 10 |  |  |  |  |  |  |  |
