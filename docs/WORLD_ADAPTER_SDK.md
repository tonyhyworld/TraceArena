# TraceArena World Model / Adapter SDK

> 状态：首版已接线
> 适用基线：`master` / 2026-07-21
> 目标：用一个稳定契约接入专家规则、算法、训练模型、外部模拟器、真实系统及混合世界，同时保留环境回执、可信边界与来源证明

## 1. 它与四种结算类型不是一回事

TraceArena 现有四种结算类型回答“谁有权证明结果”：

- `simulation`
- `external_reality`
- `deterministic_verifier`
- `hybrid`

World Adapter 回答“世界如何接收动作并推进状态”。它不是“外部模拟器专用接口”，而是所有世界模型实现共用的执行边界。两者是正交关系：

```text
Agent Action
  → World Adapter（执行与状态转移）
  → WorldTransition（环境事实）
  → SettlementRuntime（按四种权威类型结算）
```

因此外部模拟器不是第五种结算类型。一个 Grid2Op 环境通常采用
`simulation`；如果同时用真实电网数据校准或验证，则场景最终可以采用
`hybrid` 结算。

## 2. 六种世界模型实现

`world/adapter.yaml.model_kind` 支持：

| ID | 世界如何产生反馈 | 典型实现 |
|---|---|---|
| `rule_based` | 执行专家声明的规则与状态机 | 制度流程、谈判、经营规则 |
| `algorithmic` | 执行确定性或随机算法 | 优化器、排程器、虚拟账本 |
| `learned` | 由固定版本的训练模型或 World Agent 预测状态变化 | 复杂经验判断、学习型动力学 |
| `simulator` | 调用专业模拟器推进环境 | Grid2Op、SUMO、EnergyPlus、Gymnasium |
| `reality` | 从真实系统读取事实或安全执行动作 | 市场、业务系统、实验设备 |
| `hybrid` | 组合以上两种或更多实现 | 真实行情 + 虚拟交易账本 |

`model_kind` 描述实现方式，不代表质量等级。每次 transition 还必须携带 `WorldModelAssurance`，说明可信等级、置信度、证据、验证依据、假设与局限。一个 `learned` 模型可以经过严格校准，一个 `rule_based` 模型也可能只是探索性假设；TraceArena 记录区别，不替场景作虚假背书。

## 3. 场景声明

`simulation` 路由必须同时声明；其他结算类型可按需声明：

- `provider_id`：结算权威；
- `world_adapter_id`：执行世界。

```yaml
# settlement/manifest.yaml
execution:
  default:
    mode: simulation
    provider_id: power_grid_settlement
    world_adapter_id: builtin:grid2op

providers:
  - id: power_grid_settlement
    authority: simulation
    rule_version: power-grid-score.v1
```

外部适配器的配置独立放在：

```yaml
# world/adapter.yaml
adapter_id: builtin:grid2op
model_kind: simulator
seed: 42
config:
  environment: l2rpn_case14_sandbox
  make_kwargs: {}
  action_mapping:
    do_nothing: {}
    reconnect_line:
      set_line_status:
        - [0, 1]
```

内置 RuleWorld 也必须显式声明：

```yaml
world_adapter_id: builtin:ruleworld_physics
```

未知适配器、漏写 `world_adapter_id` 或配置 ID 与路由不一致时，场景必须启动失败。系统不再回退到 RuleWorld。

首版运行时限定一个场景只能使用一个 World Adapter；同一适配器内部可以组合规则、算法、模型、模拟器或真实接口，也可以管理多个 Agent 的隔离环境。需要组合多个执行引擎时，应先在一个复合适配器内定义明确的同步时钟、状态交换与来源标注规则。

注册实现声明的 `model_kind`、配置声明以及运行时 provenance 必须一致；不一致时启动失败。旧场景可暂时省略配置中的 `model_kind`，由受信注册表推断，以保持兼容。

## 4. 统一接口

接口定义位于：

```text
backend/app/engine/world_adapter/base.py
```

```python
class WorldAdapter(Protocol):
    def initialize(config, seed): ...
    def reset(): ...
    def observe(actor_id): ...
    def legal_actions(actor_id): ...
    def apply_actions(commands): ...
    def step(world_tick): ...
    def metrics(): ...
    def terminal(): ...
    def snapshot(): ...
    def provenance(): ...
    def close(): ...
```

### 批量动作铁律

`apply_actions()` 只接收和校验同一 tick 的全部 Agent 动作，不得推进模拟时间。`step()` 才能把环境推进一次。

这样可以避免两个 Agent 在同一回合行动时，模拟器被顺序推进两次，导致后行动者看到不同的外生世界。

如果产品目标是比较多个策略，应为每个 Agent 创建相同初态、相同随机种子的隔离环境；Grid2Op 内置适配器采用的就是这一模式。

## 5. 跨层契约

结构化契约位于 `backend/app/contracts/world_adapter.py`。

| 契约 | 含义 |
|---|---|
| `WorldAdapterCommand` | OS 提交给外部世界的结构化命令 |
| `WorldAdapterActionReceipt` | 接受、拒绝、执行或失败回执 |
| `WorldAdapterObservation` | 某个 Agent 可见的环境观察与合法动作 |
| `WorldAdapterTransition` | 一次 tick 的状态前后、差量、指标和回执 |
| `WorldAdapterTerminal` | 环境终止原因及胜者候选 |
| `WorldAdapterProvenance` | 适配器、模拟器、配置哈希、随机种子和来源 |
| `WorldModelAssurance` | 可信等级、置信度、验证依据、假设与局限 |

失败或拒绝回执必须给出原因。环境变化必须来自 `WorldAdapterTransition`，不得由参赛 Agent、导演或结算插件根据自然语言补写。若由独立 World Agent 生成，仍必须经过适配器输出结构化 transition，并记录模型与可信边界。

## 6. 注册适配器

OS 只加载显式注册的代码，不允许场景 YAML 任意导入 Python 模块。

```python
from app.engine.world_adapter import register_world_adapter

register_world_adapter(
    "company:factory_twin",
    FactoryTwinAdapter,
    model_kind="simulator",
    capabilities=frozenset({"seeded_replay"}),
)
```

注册 ID 必须与 `world/adapter.yaml.adapter_id` 及 simulation 路由的 `world_adapter_id` 一致。

当前内置注册：

- `builtin:deterministic_counter`：确定性 SDK 示例和契约测试环境；
- `builtin:grid2op`：可选 Grid2Op 电网环境；
- `builtin:ruleworld_physics`：原有规则世界执行 provider，由 simulation 路由显式选择。

新增训练后的 World Agent 时，应以 `model_kind="learned"` 注册。运行 provenance 必须在 `metadata` 中提供 `model_id`、`model_version`，并在 assurance 中至少声明局限；该 Agent 必须与参赛 Agent 身份隔离，只接受结构化命令并返回结构化 transition；固定模型、提示词与采样配置；记录置信度和验证依据；先经过确定性合法性门禁。除非场景另有独立权威证据，学习型世界模型不应同时担任唯一胜负裁判。

混合实现必须在 provenance 的 `metadata.components` 中声明至少两个组成部分，并分别保留来源。`calibrated` 或 `authoritative` 可信等级必须给出 `validation_refs`，不能只靠配置自称。

## 7. Grid2Op

### 安装

```bash
cd backend
pip install -r requirements.txt
pip install -r requirements-grid2op.txt
```

`grid2op` 采用延迟导入。未安装依赖时，普通资本市场和 RuleWorld 场景不受影响；只有真正启动 `builtin:grid2op` 时才会给出明确错误。

真实环境冒烟验证：

```bash
cd backend
python scripts/smoke_grid2op_adapter.py
```

Grid2Op 首次使用该环境时会下载官方数据集，后续运行复用本地数据。

### 公平比较

Grid2Op 适配器为每个 Agent 创建独立环境，并使用相同配置和相同随机种子。每个 Agent 的动作只影响自己的环境副本，避免策略竞争被环境先后顺序污染。

### 动作

场景可以通过 `action_mapping` 把 TraceArena 动作映射为 Grid2Op action dictionary，也可以让动作参数显式携带：

```json
{
  "grid2op_action": {
    "redispatch": [[0, 1.5]]
  }
}
```

未声明映射且不是 `wait` 的动作会被确定性拒绝，不会自动猜测控制指令。

### 当前输出

适配器记录 `rho`、`line_status`、`topo_vect`、发电、负荷、调度和冷却时间等常用观察，并计算每个 Agent 的累计 reward、最大线路负载率、断线数量和终止状态。

## 8. Agent 感知与事实链

适配器观察会进入 Agent 私有简报：

```text
raw_context.world_adapter_observation
```

执行后产生：

```text
CausalPipelineResult.world_action_receipt
CausalPipelineResult.world_transition
WorldEvent.deltas.world_action_receipt
WorldEvent.deltas.world_transition
state.internal.world_adapter
```

运营诊断日志和 Trace 账本会保留完整回执。观众端仍只消费导演根据已提交事实生成的内容。

## 9. 适配器验收清单

一个适配器合入前必须证明：

1. 固定配置和种子可复现；
2. 同一 tick 只推进一次环境；
3. 非法动作有结构化拒绝原因；
4. 每次状态变化均有 before、after、delta 和 provenance；
5. 多 Agent 比较时不存在先后顺序污染；
6. reset 后没有旧状态泄漏；
7. close 能释放进程、socket、文件和内存；
8. 模拟器异常不会被伪装成成功；
9. 场景结算只消费适配器事实，不自行编造缺失后果；
10. README 明确模拟器假设、适用范围和不能外推的结论。
11. registry、配置和 provenance 的 `model_kind` 一致；
12. learned/hybrid 实现记录模型、提示词、规则、算法或数据的版本；
13. 不把探索性或预测性反馈展示成真实物理事实。

## 10. 当前边界

首版 SDK 已完成协议、注册、生命周期、批量动作、感知注入、事实记录、严格路由、确定性参考适配器和 Grid2Op 可选适配器。

2026-07-20 已在本机使用 Grid2Op `1.12.5` 与官方
`l2rpn_case14_sandbox` 数据集完成真实双 Agent 冒烟验证：两个隔离环境采用
相同种子 `42`，同一 TraceArena tick 的两个空动作均得到 `executed` 回执，
并产生统一的 `grid2op-transition:1`、分 Agent 指标和来源记录。

它尚不代表已经完成一个可对外演示的电网场景包。下一阶段仍需提供：

- 电网角色和目标；
- 有界动作映射；
- Grid2Op 指标到场景结算的明确公式；
- 规则基线、单 Agent和多 Agent 对照实验；
- 前端电网状态的领域化展示；
- 固定数据集上的可复现实验报告。
