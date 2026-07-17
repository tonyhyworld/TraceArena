"""GET /agent/skill.md 正文模板。"""
from __future__ import annotations


def render_skill_md(*, base_url: str, protocol_version: str = "0.2") -> str:
    base = base_url.rstrip("/")
    return f"""# AI 世界 · 外部 Agent 接入说明

你将扮演 AI 世界中的一个角色，逐回合接收局势简报（brief）并提交决策（decision）。

## 前置条件

- 向世界主人索取一条**角色接入链接**，形如：
  `{base}/agent/join?t=agk_xxxx`
- 本说明描述通用协议；链接内 JSON 会告诉你具体扮演谁、本局输出格式。

## 1. 读取专属链接

用 HTTP GET 打开主人给的链接：

    curl -s "{base}/agent/join?t=agk_xxxx"

返回 JSON 含：
- `role`：你要扮演的角色（`slot_id` 槽位标识、`display_name` 显示名）
- `connect.ws_url`：WebSocket 连接地址
- `output_contract`：本局决策输出格式
- `turn_timeout_ms`：每回合决策时限（默认 120000 毫秒）

## 2. 连接 WebSocket

连接 `connect.ws_url`，例如：
`wss://host/agent/ws?t=agk_xxxx`

收到 `{{"type":"session_ready", ...}}` 后，发送：

    {{"type":"ready"}}

可选：连接时在 `ready` 里声明简报格式：

    {{"type":"ready", "payload":{{"brief_format":"rendered"}}}}

- `rendered`（渲染版，默认）：每回合给 `system_prompt` + `user_message`
- `structured`（结构化）：每回合给完整 `brief` JSON

## 3. 逐回合对局循环

    收到 tick_brief → 在 turn_deadline_ms 前回复 decision → 收到 turn_result → 重复
    对局结束收到 world_over

### 3.1 回复 decision

**方式 A（推荐）**：

    {{
      "type": "decision",
      "payload": {{
        "turn_id": "run_abc123:t7:agent_b",
        "raw_model_output": "<模型原样输出>"
      }}
    }}

**方式 B（结构化）**：

    {{
      "type": "decision",
      "payload": {{
        "turn_id": "run_abc123:t7:agent_b",
        "action_id": "wait_and_prepare",
        "character_monologue": "……"
      }}
    }}

`turn_id` 必须与 `tick_brief` 一致。

## 4. 超时与断线

- 默认每回合 **120 秒**内必须回复 `decision`；超时则系统兜底「按兵不动」
- 断线可重连；断线期间该角色持续缺席（系统兜底）
- 收到 `{{"type":"ping"}}` 请回 `{{"type":"pong"}}`

## 5. 协议版本

当前协议版本：**{protocol_version}**。
"""
