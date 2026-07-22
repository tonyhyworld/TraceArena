# 附录 A：Agent Identity 清单

> 适用赛道：GOAI 2026「Agent Infra 新智基座」
> 当前可执行验证场景：电网极端事件应急恢复（Grid2Op 隔离仿真、可审批、可审计）
> 协同基线：AgentTeams / HiClaw；TraceArena 负责世界运行、验证与治理。

> 历史提交材料曾以“企业软件故障处置”说明同一套 OS 能力；P0/P1 修复后的工程证据以电网应急世界为主，因为它已经具备外部仿真器反馈、三角色协作、Skill receipt、审批门和可观测时间线。

## 1. 团队与世界的关系

AgentTeams Manager 接收故障事件，拆解任务、委派 Worker、维护协作消息与人工介入；五类 Worker 通过 `AgentTeamsWorldBridge` 进入同一个 TraceArena 世界。TraceArena 将每次观察、行动、证据、审批与世界反馈写入共享但按角色裁剪的运行状态。

```text
告警 / 工单 / 日志
        ↓
AgentTeams Manager：建队、拆解、委派、汇总
        ↓
监测 ─ 诊断 ─ 修复 ─ 验证 ─ 审计
        ↓              ↑
TraceArena World：状态、约束、工具、验证、审批、回滚、结算
        ↓
证据化结果 / 下一轮任务 / 经验沉淀
```

## 2. 角色清单（对应手册 Agent Identity 模板）

| Name / Role | Capabilities（能做 / 不能做） | Inputs | Outputs | Dependencies | Decision Boundary | Trace |
|---|---|---|---|---|---|---|
| `manager` / Team 编排者 | 建队、拆解、委派、汇总；**不能**改系统、绕过验证或宣布恢复 | 告警、世界目标、团队状态、Worker 结果 | 任务图、优先级、下一轮委派 | AgentTeams Manager、共享状态、审批策略 | 可重排任务；恢复结论必须等验证和审计准入 | 记录任务图版本、委派、重排原因、审批等待 |
| `monitor` / 监测 Worker | 聚合告警、标记影响面、创建事件；**不能**判断根因或改配置 | 告警、指标、服务目录、SLO | 事件范围、严重等级、证据索引 | 告警/指标适配器、`incident_triage` | 可定级和升级；不得提出无证据的修复 | 记录输入告警、阈值、影响面计算和事件 ID |
| `diagnose` / 诊断 Worker | 证据研判、假设排序、补证；**不能**提交生产修复 | 日志、Trace、变更、历史摘要 | 有证据的根因假设、待补证清单 | `incident_triage`、日志/Trace、证据账本 | 无证据返回 `needs_more_evidence`；不进入执行阶段 | 记录检索范围、证据引用、被淘汰假设与原因 |
| `repair` / 修复 Worker | 提出最小变更、隔离执行、申请审批；**不能**无证据变更、覆盖快照或绕过高风险审批 | 已验证假设、代码/配置快照、变更预算 | 补丁候选、风险分级、回滚点、审批请求 | `change_plan`、隔离适配器、策略引擎 | 低风险仅在隔离环境；高风险仅生成 `needs_approval` | 记录补丁/配置 diff、快照、预算和审批 ID |
| `verify` / 验证 Worker | 回归、压力、SLO 验证与否决；**不能**改补丁或放宽阈值 | 补丁、测试回执、健康指标、阈值 | `pass` / `fail` / `needs_approval`、指标差异、回滚建议 | `incident_validation`、测试/健康指标、世界验证器 | 任一强制检查失败即否决；无权提升到生产 | 记录测试版本、阈值、指标窗口、失败检查和回执 |
| `audit` / 审计 Worker | 检查证据/权限/策略、作出审批/拒绝/回滚建议；**不能**伪造证据或执行生产动作 | Trace、证据、权限、策略、审批历史 | 审计结论、缺失证据、准入/拒绝/回滚决定 | `evidence_audit`、Trace/证据账本、策略/审批记录 | 证据缺失则不准入；高风险只经人工/策略批准后推进 | 记录审计范围、引用、策略版本、决定与理由 |

## 3. 任务闭环与状态流转

1. **输入与建队**：监测 Agent 将告警、日志和指标收敛为事件；Manager 根据事件创建 Team，并把世界目标与预算映射到任务图。
2. **拆解与上下文传递**：Manager 向诊断、修复、验证和审计 Worker 分派角色化任务。共享状态只提供必要字段；例如修复 Agent 看不到审计 Agent 的独立结论，避免自证。
3. **工具与 Skill 调用**：诊断使用事件研判 Skill，修复调用受控代码/配置工具，验证调用恢复验证 Skill。每次调用都返回可引用的证据或失败原因。
4. **结果验证**：TraceArena 世界以测试、SLO、错误率、延迟、安全规则和变更预算进行验证，结果返回 Manager 并驱动下一轮。
5. **审批、回滚与审计**：高风险动作只能得到 `needs_approval`，审计 Agent 与人工审批后才可执行；失败或恶化会回滚至上一个快照。
6. **经验沉淀**：结算保存被选择和被淘汰的路径、证据、代价与复盘摘要，作为后续类似事件的受控上下文。

## 4. AgentTeams 映射说明

| AgentTeams 能力 | TraceArena 映射 | 参赛方案中的作用 |
|---|---|---|
| Manager–Workers 编排 | `AgentTeamsTeam`、`AgentTeamsWorker` | 角色身份、任务分解、协作关系 |
| 团队消息与共享文件 | 角色化 Observation / Evidence | 上下文传递、证据引用与最小权限 |
| Worker 运行与产物 | `submit_action` / `submit_evidence` | 结构化行动、工具结果、可追溯产物 |
| 人机协作 | `resolve_approval` | 高风险动作审批、拒绝与回滚 |
| 任务进度 | `status` + world feedback | 协同执行、状态追踪、下一轮重排 |

## 5. 当前电网应急 Demo 的三角色身份

| Worker | 场景角色 | Capabilities | Inputs | Outputs | Decision Boundary | Trace |
|---|---|---|---|---|---|---|
| `grid_safety_dispatcher` | 安全调度官 / 安全校验 | `grid_observation_assessment`、`grid_safety_validation` | Grid2Op 观测、线路状态、max rho、审批策略 | 风险等级、是否需要审批、通过/阻断结论 | 高风险恢复动作无审批不得执行 | 观察、Skill receipt、审批前后校验均进入 timeline |
| `restoration_planner` | 恢复规划师 / 方案提出 | `grid_restoration_plan` | 风险评估、快照引用、证据引用 | 最小恢复动作、风险等级、回滚点、审批请求 | 只能提出计划和提交结构化动作，不能绕过审批 | 提案、被拦截 receipt、审批后执行 receipt 均可追踪 |
| `resilience_operator` | 韧性运营官 / 证据审计 | `grid_evidence_audit` | Trace、证据、审批历史、世界回执 | 审计结论、缺失证据、准入/拒绝决定 | 不改变仿真结果，不伪造证据 | 审计 receipt 绑定证据与审批 ID |

> 代码事实：仓库已包含 `backend/app/integrations/agentteams_adapter.py` 的桥接契约、`backend/app/api/agentteams_routes.py` 的 HTTP/Webhook transport，并新增 observability timeline；`backend/scripts/goai_grid_agentteams_demo.py` 已在本地用 Grid2Op 跑通三角色协作、Skill 执行、审批门与世界反馈。当前不伪称已在官方 AgentTeams 云端实例完成导入、审核或发布；拥有实例权限后，可把官方运行时指向 `/integrations/agentteams/*` 接口做组合部署。
