# 附录 B：核心 Skill 清单与工程契约

> Skill 是本参赛方案的能力抽象层；MCP/受控工具是连接层；TraceArena 世界是验证、审批和结算层。

## 1. 核心 Skill

| Skill / 类型 | 用途 | 输入 → 输出 | 调用条件 | 依赖工具 | 失败处理与安全边界 | 复用价值 |
|---|---|---|---|---|---|---|
| `incident_triage` / 自定义 | 将告警、日志、Trace 收敛为有证据的事件范围与根因假设 | 告警、指标、日志/Trace 引用、时间预算 → 事件等级、影响面、假设排序、证据引用、下一步诊断 | 世界接受告警或健康阈值触发后 | 监控、日志、Trace、变更记录工具/MCP | 证据不足返回 `needs_more_evidence`；只读，不能改代码或配置 | 可用于运维、安全、客服工单等“信号→证据→研判”场景 |
| `incident_validation` / 自定义 | 在隔离环境验证候选修复是否达标 | 补丁、测试结果、健康指标、阈值 → `pass` / `fail` / `needs_approval`、失败检查、回滚建议 | 修复 Agent 产生候选变更后 | 测试、负载、SLO、策略工具 | 单测通过不等于恢复；失败保留证据并驱动下一轮；不得放行生产 | 可用于发布验证、配置变更、理赔/风控的独立核验 |
| `change_plan` / 自定义 | 把根因证据转为最小风险变更计划 | 证据、快照、变更预算、权限 → 变更步骤、风险级别、审批请求、回滚点 | 根因假设达到场景定义的证据门槛后 | 代码库、配置库、沙箱执行器 | 无快照/无证据拒绝计划；高风险一律转审批 | 可用于所有需要“先计划、再受控执行”的企业变更 |
| `evidence_audit` / 自定义 | 判断结论与行动是否可由证据支撑 | Trace、工具回执、策略、审批历史 → 审计意见、缺失证据、准入/回滚决定 | 验证完成或高风险动作申请审批时 | Trace 查询、策略引擎、运行归档 | 缺少来源不可通过；审计 Agent 不得篡改原始证据 | 可用于高风险业务、科研、公共治理的可解释治理 |
| `grid_observation_assessment` / 可执行自定义 | 将 Grid2Op 观测转为风险等级与下一步建议 | 仿真指标、证据引用 → 风险等级、风险因素、建议动作、证据引用 | 电网世界产生适配器观测后 | World Adapter 观测账本 | 只读，不改变拓扑或调度 | 可复用于电网、能源调度、设施恢复等场景 |
| `grid_restoration_plan` / 可执行自定义 | 生成最小恢复方案并给出风险/回滚/审批要求 | 观测评估、快照、证据 → 行动步骤、风险等级、回滚点、审批要求 | 观测评估完成后 | 场景审批策略、动作映射 | `restore_fault_line` 被识别为高风险并返回 `needs_approval` | 展示“专家规则 + Agent 计划 + 世界验证”的闭环 |
| `grid_safety_validation` / 可执行自定义 | 校验恢复方案是否具备证据、审批和回滚条件 | 计划、审批 ID、指标变化、证据 → `pass` / `fail` / `needs_approval` | 高风险动作执行前 | 审批账本、策略规则 | 无审批不得放行高风险恢复动作 | 可用于公共设施、工业控制、应急处置前置校验 |
| `grid_evidence_audit` / 可执行自定义 | 审计高风险动作是否有证据链和审批历史 | Trace、证据、审批历史 → 审计结论、缺失证据、决定 | 高风险动作或最终结果审计时 | Trace、审批、适配器回执 | 不得伪造证据或改变结算 | 可用于复赛的可解释治理与合规展示 |

## 2. 当前代码与交付边界

| 项目 | 当前状态 | 位置 / 说明 |
|---|---|---|
| `incident_triage` | 已实现为可发现、可安装的 Skill 清单 | `backend/skills/incident_triage/skill.yaml` |
| `incident_validation` | 已实现为可发现、可安装的 Skill 清单 | `backend/skills/incident_validation/skill.yaml` |
| `change_plan` | 已实现为可发现、可安装的 Skill 清单 | `backend/skills/change_plan/skill.yaml`；真实企业工具适配留在复赛 |
| `evidence_audit` | 已实现为可发现、可安装的 Skill 清单 | `backend/skills/evidence_audit/skill.yaml`；真实企业证据源适配留在复赛 |
| `grid_observation_assessment` | 已实现为可发现、可执行 Skill | `backend/skills/grid_observation_assessment/skill.yaml`；`execute_skill()` 产出结构化 receipt |
| `grid_restoration_plan` | 已实现为可发现、可执行 Skill | `backend/skills/grid_restoration_plan/skill.yaml`；高风险恢复计划返回 `needs_approval` |
| `grid_safety_validation` | 已实现为可发现、可执行 Skill | `backend/skills/grid_safety_validation/skill.yaml`；无审批 ID 时阻断高风险动作 |
| `grid_evidence_audit` | 已实现为可发现、可执行 Skill | `backend/skills/grid_evidence_audit/skill.yaml`；审计证据链和审批历史 |
| MCP | 推荐项，不作为初赛已完成的企业 MCP Server 宣称 | 复赛可接入监控、日志、代码库等系统；接口使用稳定工具契约，后续仅需协议适配 |

## 3. 版本、质量与分发

- 每个 Skill 以 `skill_id`、说明、输入/输出、调用条件、依赖、失败处理和安全边界进入注册表；版本变化必须与场景包/运行记录绑定。
- 验证质量不由 LLM 自评：Skill 的输出必须经场景规则、测试、健康指标或审批策略复核。
- 因为 Skill 与场景解耦，同一能力可被不同 Agent、不同 Team 和不同行业场景复用。
- 初赛开源交付：Skill 清单、适配契约、场景设计和运行时源码。2026-07-22 已补齐电网应急世界的本地可执行 Skill receipt、审批门、Grid2Op 端到端 Demo，以及受 token 保护的 AgentTeams HTTP/Webhook transport；AgentTeams 官方云端导入/审核/发布和阿里云官方用云 Skill 仍需在拥有账号实例后接入并如实披露。
