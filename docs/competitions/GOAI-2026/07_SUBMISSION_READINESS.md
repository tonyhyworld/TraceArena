# GOAI 2026 初赛提交核对单

更新：2026-07-22
赛道：Agent Infra 新智基座
提交截止：以官网最终通知为准（当前官网标示 2026-08-16）

## 必交项

| 要求 | 准备状态 | 提交物 / 证据 |
|---|---|---|
| 项目名称（约 20 字） | 已备 | `TraceArena AI World OS`；表单副标题使用“面向可运行行业世界的多 Agent 运行与验证基础设施” |
| 500 字以内作品简介 | 已备，待贴入表单 | `02_INITIAL_SUBMISSION_COPY.zh-CN.md`（提交时使用其中“赛道强化版”） |
| 方案 PPT/PDF | 已备，需使用提交版 | `TraceArena_GOAI_2026_初赛方案_提交版.pptx`（生成后在此更新） |

## 赛道核心核对

| 规则 | 现有材料位置 | 结论 |
|---|---|---|
| 企业复杂任务与端到端闭环 | `04_ENTERPRISE_INCIDENT_SCENARIO.md` | 已明确为隔离、可回滚的企业软件故障处置场景 |
| 至少 3 类 Agent | `05_AGENT_IDENTITY_LIST.md` | 已定义 5 类 Worker + Manager，职责、边界与协作关系完整 |
| AgentTeams 为协同设计基点 | `03_AGENTTEAMS_ADAPTER_DESIGN.md`、`05_AGENT_IDENTITY_LIST.md`、桥接代码 | 已用 Manager–Workers、任务拆解、共享状态、人机审批和桥接契约逐项映射；不夸大为官方运行时已内置 |
| AgentTeams Skill 导入准备 | `backend/integrations/agentteams_skills/tracearena-incident-world/SKILL.md`、`tracearena-incident-world-agentteams-skill.zip` | 已提供并验证可解压的上传 ZIP；未声明已在官方控制台审核或发布 |
| 核心 Skill（必选） | `06_SKILL_CATALOG.md`、`backend/skills/{incident_triage,change_plan,incident_validation,evidence_audit}` | 已有 4 个可发现、可安装的 Skill manifest；每个包含版本、输入输出、调用条件、依赖、失败、安全、权限与评估契约 |
| 结果验证与异常分支 | `04_ENTERPRISE_INCIDENT_SCENARIO.md` | 测试、SLO、安全规则；审批、拒绝、回滚、重试均明确 |
| 上下文 / 记忆 / 共享状态 / 轨迹 | 角色清单、桥接代码、现有运行时 | 已覆盖共享状态与轨迹可观测；初赛不宣称生产级 RAG |
| 开放/开源价值 | Apache-2.0、README、适配器、Skill、场景包规范 | 已具备；提交时附 GitHub 公开仓链接 |
| License / API / 数据 / 复现披露 | `08_OPEN_SOURCE_AND_COMPLIANCE_DISCLOSURE.md` | 已补齐；明确无密钥回放、可选模型 API、合成/脱敏数据及安全边界 |

## P0/P1 修复后新增工程证据

| 能力 | 当前证据 | 结论 |
|---|---|---|
| 3 个 Agent 协作闭环 | `backend/scripts/goai_grid_agentteams_demo.py` 使用 `grid_safety_dispatcher`、`restoration_planner`、`resilience_operator` 建队运行 | 已形成可执行协作 Demo |
| Skill 实执行 | `execute_skill()` 可执行 `grid_observation_assessment`、`grid_restoration_plan`、`grid_safety_validation`、`grid_evidence_audit` 并输出 receipt | 不再只是 manifest |
| 高风险审批门 | `restore_fault_line` 在场景包中声明 high risk；未批准返回 `needs_approval`，批准后才进入 Grid2Op | 已有可验证审批/回滚引用 |
| 观测指标 | `AgentTeamsWorldBridge.status()` 输出 event_counts、duration_ms、skill_success_count、approval_count、action_count | Trace/Log/Metrics 有结构化证据 |
| 外部世界反馈 | Grid2Op `l2rpn_case14_sandbox` 返回 reward、max_rho、断线数、provenance、seed 和 transition | 支撑“世界反馈选择路径” |
| AgentTeams HTTP/Webhook transport | `backend/app/api/agentteams_routes.py` 暴露建队、观察、证据、行动、审批、Skill 执行、状态接口；用 `X-AgentTeams-Token` 保护 | 已具备官方运行时可调用入口，官方云端配置仍需账号 |

## 不能在初赛中夸大的事项

1. AgentTeams HTTP/Webhook transport 已在本地实现并验证；但尚未在官方 AgentTeams 云端实例完成导入、审核、发布和实际绑定。
2. AgentTeams `SKILL.md` 导入包已经准备，但尚未由拥有实例权限的人员导入、审核或发布。
3. 阿里云官方用云 Skill 尚未作为当前原型硬依赖接入；初赛如实披露，复赛前须完成最少一个必要 Skill 的集成。
4. 企业故障场景当前是可验证的设计与适配目标，不应写成已经接管真实生产系统。
5. RAG、向量记忆、生产监控 MCP、真实系统写操作不能写成现有成品。
6. “最优路径”限定为场景目标、规则、压力、反馈和评价标准下的综合更优，不写成普适真理。

## 表单提交前的最后检查

- [ ] 上传 `TraceArena_GOAI_2026_初赛方案_提交版.pptx` 或导出的 PDF。
- [ ] 粘贴不超过 500 字的“赛道强化版”简介（`10_SUBMISSION_FIELD_COPY.zh-CN.md`）。
- [ ] 选择 `Agent Infra 新智基座` 与开放式选题。
- [ ] 填写 GitHub 项目链接、开源许可证 Apache-2.0、可运行 Demo（如表单提供字段）。
- [ ] 对外链接只填公开、可访问且不暴露密钥或私有场景的数据。
