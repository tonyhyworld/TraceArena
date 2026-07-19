# 公共发布范围（v0.1.9，2026-07-19）

本文件记录 TraceArena 当前公开仓库的实际边界。它不把“候选”描述成尚未完成的内部导出任务；公开仓库、在线 Demo 和 v0.1.9 Release 均已对外可用，但运行时和场景包 API 仍属于 public preview，会随社区反馈演进。

## 纳入范围

- `backend/app/` 中的通用运行时、契约、工具、Agent gateway、API 和校验模块；
- `frontend/` 中的可本地运行的 Vue 前端、Operator Console、viewer 和 i18n 基础设施；
- `deploy/huggingface-static/` 中的无 Key、浏览器本地、可观看在线 Demo；
- `examples/market_replay/` 和 `examples/incident_response_world/` 中的无 Key、合成数据、可回放示例；
- README、许可证、贡献指南、场景包指南、CI、安全文档、发布记录和商业试点说明。

## 明确排除

- `backend/scenarios/sanzi_duodi/**`：三子夺嫡私有场景包；
- 三子夺嫡的代码、测试、运行数据、音频、图片及其他二进制素材；
- `backend/scenarios/capital_market/**`：作为 Market Replay 所需的公开示例场景包纳入；合成音频带有 CC0 来源记录；
- 真实客户数据、凭据、生产系统写入、真实券商下单和未获再分发授权的媒体/数据；
- 由部署方注入的私有模型密钥、私有场景资产和客户专属适配器；
- 公开 Demo 中未启用的生产级外部 Agent/工具连接能力。公开仓提供接口和边界，但不把第三方凭据或生产权限打包进发布物。

## 授权边界

三子夺嫡素材不属于公开发布内容，因此本项目不对其商业授权作结论。公开发布自身选中的任何二进制或数据资产，仍必须完成来源、许可证、哈希和再分发权记录。

## 当前状态

当前公开仓已完成清洁检出安装、确定性回放、前端生产构建、Ubuntu/macOS 公共运行时 smoke test 和 OpenSSF Scorecard 验证；最新主分支验证记录见 [增长执行板](GROWTH_EXECUTION_BOARD.md)。公开 Demo 使用合成数据、浏览器本地回放，不调用模型、不接收 API Key、不连接券商，也不构成投资建议。

公开边界仍然遵循最小权限原则：场景包定义领域规则，通用 OS 负责装载、调度、行动校验、结算路由和回放。任何真实外部工具写入、客户数据处理或生产部署，都必须在独立权限、数据处理和验收协议中明确约束。
