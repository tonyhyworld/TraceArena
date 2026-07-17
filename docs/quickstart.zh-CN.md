# 五分钟上手 TraceArena

[English](quickstart.md)

TraceArena 是一个让智能体在规则、资源和时间约束下行动，并由独立世界验证结果的运行时。
你可以先看在线演示，再在本地运行一个不需要 API Key 的确定性世界。

## 1. 先看在线演示

打开 [TraceArena AI 世界 Demo](https://tonyworld888-tracearena-demo.static.hf.space/index.html)。
它回放的是 NOVA-7 市场挑战：

- Astra 和 Vector 获得相同的合成证据；
- 两个智能体采用不同的决策策略；
- AI 世界施加市场事件和风险规则；
- 验证器独立完成最终评分。

演示不调用 LLM、不连接券商，也不接收用户数据。

## 2. 在本地运行确定性世界

前置条件：Python 3.10 以上版本和 Git。

```bash
git clone https://github.com/tonyhyworld/TraceArena.git
cd TraceArena
python3 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev]"
PYTHONPATH=backend python backend/scripts/market_replay.py \
  --fixture examples/market_replay/fixture.json \
  --output ./runs/market_replay_demo \
  --locale zh-CN
```

回放使用合成 fixture 和模拟账本，不调用模型、不执行真实下单。

## 3. 查看运行结果

用现代浏览器打开 `frontend/public_viewer/index.html`，或直接查看生成文件：

```text
runs/market_replay_demo/
├── replay_deterministic.json   # 有序的行动、事件和结算
└── run_manifest.json           # 运行身份、语言和来源
```

真正需要追问的不只是“谁赢了”，还包括：

```text
智能体看到了什么？
→ 它请求了什么行动？
→ 哪条规则接受或拒绝了行动？
→ 世界发生了什么变化？
→ 由谁完成了结果结算？
```

## 4. 构建场景包

复制 [`examples/scenario_pack_template`](../examples/scenario_pack_template/)，并阅读[场景包开发指南](scenario-pack-development-guide.zh-CN.md)。
场景包负责领域规则，通用运行时负责执行、证据、回放和结算基础设施。

提交 PR 前，请提供可复现 fixture、校验预期、结算权威，以及所有非代码素材的来源与再分发权。

## 5. 获取帮助

- 可复现的程序问题请使用 [Bug 模板](https://github.com/tonyhyworld/TraceArena/issues/new?template=bug.yml)。
- 新世界提议请使用 [场景包模板](https://github.com/tonyhyworld/TraceArena/issues/new?template=scenario-pack.yml)。
- 提交 PR 前请阅读[贡献指南](../CONTRIBUTING.zh-CN.md)。

TraceArena 采用 Apache-2.0 许可证。公开 Demo 仅用于评测与教学，不构成投资建议。
