# 场景包贡献指南

[English](scenario-pack-guide.md)

场景包提供领域契约，TraceArena 提供通用运行时。一个场景包应能描述：什么行动不被
世界接受、什么行动可以结算，以及如何保留足以解释结果的证据。

## 从参考场景包开始

请阅读或复制 [`backend/scenarios/capital_market`](../backend/scenarios/capital_market)。
它是当前支持的场景 API（`1.0`）参考实现。请保持运行时通用：只对你的世界有意义的
规则，应放在场景包中，而不是放进 `backend/app/engine`。

## 最小创作清单

1. 编写 `manifest.json`：稳定的 `scenario_id`、API 版本、所需 OS 能力和入口文件映射；
2. 在 `agents/` 定义角色，在 `world/actions.yaml` 定义带明确参数结构的行动；
3. 在 `world/` 定义可见性、权限、资源与指标，让运行时可判断各角色能看见和能做什么；
4. 在 `settlement/` 选择结算权威：确定性校验器、场景规则、可验证外部事实，或明确的混合；
5. 在 `tests/` 中补齐校验、示例运行和回放预期；
6. 只添加拥有再分发权的素材，并在相邻的 `PROVENANCE.md` 中记录来源。

## 为可审计性而设计

审阅者应能为每个重要行动回答：

```text
谁行动？→ 看到了什么？→ 请求了什么行动？
→ 哪条规则/证据接受或拒绝了它？→ 世界状态发生了什么变化？
```

不要把自然语言旁白作为唯一的裁决依据。决定性的约束应进入结构化校验或结算规则；
相关证据引用应被记录；失败/拒绝理由也应进入轨迹。

## 提交 PR 前验证

在项目根目录运行确定性示例和测试：

```bash
PYTHONPATH=backend python backend/scripts/market_replay.py \
  --fixture examples/market_replay/fixture.json \
  --output ./runs/market_replay_demo
PYTHONPATH=backend pytest backend/tests -q
```

然后发起 PR，说明你的结算权威、证明它的 fixture、哪些内容可公开，以及外部数据/素材的
许可证。DCO 和安全要求见[贡献指南](../CONTRIBUTING.zh-CN.md)。
