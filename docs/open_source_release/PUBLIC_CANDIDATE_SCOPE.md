# 公共候选仓范围（2026-07-17）

本轮公共候选仓只整理可公开发布的通用运行时、验证工具和 Market Replay 示例。

## 纳入范围

- `backend/app/` 中已经通过边界审计的通用运行时模块；
- `backend/app/tools/` 中的场景校验与 OS 纯度工具；
- `examples/market_replay/` 中的无 Key、合成数据、确定性回放示例；
- 发布所需的 README、许可证、社区规范、CI 和安全文档（待最终补齐）。

## 明确排除

- `backend/scenarios/sanzi_duodi/**`：三子夺嫡私有场景包；
- 三子夺嫡的代码、测试、运行数据、音频、图片及其他二进制素材；
- `backend/scenarios/capital_market/**`：作为 Market Replay 所需的公开示例场景包纳入；合成音频带有 CC0 来源记录；
- 认证、控制台、用户数据、后台运营、工厂导出和运行产物；
- external-agent gateway/SDK 与 viewer；本轮公共候选不包含外部 Agent 接入路由或商业运营 viewer，待后续以独立 SDK/viewer 发布。

## 授权边界

三子夺嫡素材不属于本轮公共发布内容，因此本轮不对其商业授权作结论。公共候选自身选中的任何二进制或数据资产，仍必须在发布前完成来源、许可证、哈希和再分发权记录。

## 当前状态

范围已经写入 `export-manifest.yaml` 的默认拒绝策略。通用引擎对认证存储的直接依赖已改为注入式 hosting adapter，外部 Agent gateway 和商业运营 viewer 也未进入候选；source audit 的架构 blocker 已清零，但候选仓仍需完成依赖、许可证、历史安全扫描和干净安装验收。
