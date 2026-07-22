<template>
  <div class="console-root">
    <header class="console-header">
      <div class="brand">
        <span class="brand-kicker">AI WORLD OS · OPERATOR</span>
        <h1>{{ operatorSchema.scenario?.name || tr('AI World 运营台', 'AI World Operations') }}</h1>
      </div>
      <div class="live-strip" :class="{ offline: connectionState === 'offline' }">
        <span class="live-dot" :class="{ on: worldState.is_running }"></span>
        <b>{{ liveStatusLabel }}</b>
        <span>Tick {{ worldState.tick || 0 }}</span>
        <span>{{ tr('存活', 'Active') }} {{ aliveCount }}</span>
      </div>
      <div class="header-controls">
        <button class="primary" @click="ws.commands.play()">{{ tr('运行', 'Run') }}</button>
        <button :disabled="!hasStarted" @click="ws.commands.pause()">{{ tr('暂停', 'Pause') }}</button>
        <button @click="ws.commands.step()">{{ tr('单步', 'Step') }}</button>
        <button @click="ws.commands.reset()">{{ tr('重置', 'Reset') }}</button>
      </div>
    </header>

    <main class="console-body">
      <section class="left-rail">
        <div class="panel scoreboard-panel">
          <div class="panel-head">
            <div>
              <span>MODEL ARENA</span>
              <h2>{{ tr('谁更接近胜利', 'Who is leading') }}</h2>
            </div>
            <em>{{ hasStarted ? tr('实时解释', 'Live attribution') : tr('待开局', 'Not started') }}</em>
          </div>

          <div v-if="!standings.length" class="empty-state">
            {{ connectionState === 'offline' ? tr('后台服务未连接。请先启动后端，或刷新后重试。', 'Backend disconnected. Start the service or refresh to retry.') : tr('启动世界后，这里会显示所有 Agent 的实时结果。', 'Start the world to see live results for every agent.') }}
          </div>

          <article
            v-for="item in standings"
            :key="item.agentId"
            class="rank-card"
            :class="{ selected: selectedAgent === item.agentId, leader: hasStarted && item.rank === 1 && !item.eliminated, pending: !hasStarted, eliminated: item.eliminated }"
            :style="{ '--agent-color': item.color }"
            @click="selectedAgent = item.agentId"
          >
            <div class="rank-topline">
              <span class="rank-no">{{ item.rank }}</span>
              <div>
                <strong>{{ item.name }}</strong>
                <p>{{ item.statusText }}</p>
              </div>
              <b>{{ item.scoreLabel }}</b>
            </div>
            <div class="source-legend metric-highlight-row">
              <span v-for="metric in item.metricHighlights" :key="metric.id">
                {{ metric.label }} <b>{{ metric.value }}</b>
              </span>
            </div>
            <div class="danger-row" v-if="hasStarted && !item.eliminated && riskMetric" :class="{ hot: item.danger >= 70 }"
                 :title="`${riskMetric.label} ${item.danger} / ${riskMetric.max || 100}`">
              <span class="danger-tag">⚠ {{ riskMetric.label }}</span>
              <span class="danger-track"><i :style="{ width: `${item.danger}%` }"></i><em class="danger-threshold"></em></span>
              <b class="danger-num">{{ item.danger }}</b>
            </div>
          </article>
        </div>

        <div v-if="worldState.is_game_over && worldState.victory_attribution?.length" class="panel victory-recap-panel">
          <span>🏆 {{ tr('终局裁定 · 胜负溯源', 'Final decision · outcome attribution') }}</span>
          <div v-for="item in worldState.victory_attribution" :key="item.agent_id" class="vr-card">
            <strong>{{ item.headline }}</strong>
            <p class="vr-plus" v-for="s in item.strengths" :key="'s'+s">＋ {{ s }}</p>
            <p class="vr-weak" v-for="w in item.weaknesses" :key="'w'+w">－ {{ w }}</p>
            <p class="vr-fatal" v-if="item.fatal">✖ {{ item.fatal }}</p>
            <small>{{ tr('结算来源：', 'Settlement sources: ') }}{{ sourceMixText(item.source_mix) }}</small>
          </div>
        </div>

        <div class="panel agent-panel">
          <div class="panel-head compact">
            <div>
              <span>AGENTS</span>
              <h2>{{ tr('场上模型', 'Models in evaluation') }}</h2>
            </div>
          </div>
          <article
            v-for="agent in worldState.agents"
            :key="agent.agent_id"
            class="agent-card"
            :class="{ selected: selectedAgent === agent.agent_id, eliminated: isEliminated(agent.agent_id) }"
            @click="selectedAgent = agent.agent_id"
          >
            <div class="agent-card-main">
              <div class="agent-dot" :style="{ background: agent.color || colorFor(agent.agent_id) }"></div>
              <div>
                <strong>{{ agentLabel(agent.agent_id) }}</strong>
                <p>{{ agentStatusText(agent) }}</p>
              </div>
              <span>{{ locationText(agent) }}</span>
            </div>
            <div class="agent-resources">
              <small v-for="item in agentResourceItems(agent)" :key="item.key">
                <b>{{ item.label }}</b>{{ item.value }}
              </small>
            </div>
          </article>
        </div>
      </section>

      <section class="center-stage">
        <div class="stage-panel">
          <div class="stage-hero">
            <div>
              <span class="section-kicker">AI DECISION OBSERVATORY</span>
              <h2>{{ currentTurnTitle }}</h2>
              <p>{{ currentTurnSummary }}</p>
            </div>
            <div class="turn-metrics">
              <div><label>{{ tr('模型回复', 'Model replies') }}</label><b>{{ modelReplyCount }}</b></div>
              <div><label>{{ tr('世界事件', 'World events') }}</label><b>{{ publicEventCount }}</b></div>
              <div><label>{{ tr('结算记录', 'Settlements') }}</label><b>{{ currentSettlementCount }}</b></div>
            </div>
          </div>

          <div class="turn-review">
            <div>
              <span>{{ tr('回合回放', 'CYCLE REVIEW') }}</span>
              <strong>{{ activeTurnLabel }}</strong>
            </div>
            <div class="turn-review-actions">
              <button :disabled="!canStepTurnBackward" @click="stepTurn(-1)">{{ tr('上一回合', 'Previous') }}</button>
              <button :disabled="!canStepTurnForward" @click="stepTurn(1)">{{ tr('下一回合', 'Next') }}</button>
              <button class="soft" :disabled="isFollowingLatest" @click="jumpToLatestTurn">{{ tr('回到最新', 'Latest') }}</button>
            </div>
            <div class="turn-chip-row">
              <button
                v-for="turn in turnOptions"
                :key="turn"
                class="turn-chip"
                :class="{ active: turn === activeTurn }"
                @click="selectTurn(turn)"
              >
                T{{ turn }}
              </button>
            </div>
          </div>

          <section class="process-shell">
            <div class="process-shell-head">
              <div>
                <span>{{ tr('执行链', 'EXECUTION CHAIN') }} · {{ processChainProfile.label }}</span>
                <h2>{{ processTitle }}</h2>
              </div>
              <em>{{ processStatus }}</em>
            </div>

            <div v-if="!turnProcess.length" class="empty-state process-empty">
              {{ hasStarted ? '本回合的决策数据还在路上…' : (processChainProfile.empty_hint || '点击运行后将按场景结算类型展开决策全过程。') }}
            </div>

            <article
              v-for="p in turnProcess"
              :key="p.key"
              class="process-card"
              :class="{ selected: selectedAgent === p.agentId }"
              :style="{ '--pc-color': p.color }"
              @click="selectProcess(p)"
            >
              <header class="pc-head">
                <b class="pc-name">{{ p.name }}</b>
                <span class="pc-action">{{ p.action }}<i v-if="p.target"> → {{ p.target }}</i></span>
                <span class="pc-route" :class="p.route">{{ p.routeText }}</span>
                <span v-if="p.outcome" class="pc-outcome" :class="p.outcomeClass">{{ p.outcome }}</span>
                <small class="pc-meta">{{ p.meta }} · {{ processChainProfile.label }}</small>
              </header>
              <ol class="pc-steps">
                <li
                  v-for="step in processChainSteps"
                  v-show="!step.optional || processStepVisible(p, step.id)"
                  :key="step.id"
                  :class="step.css"
                >
                  <label>{{ step.label }}</label>
                  <div>
                    <template v-if="step.id === 'perceive'">
                      <p v-if="!p.injectLines?.length">{{ p.perceive }}</p>
                      <ul v-if="p.injectLines?.length" class="inject-lines">
                        <li v-for="line in p.injectLines" :key="line">{{ line }}</li>
                      </ul>
                      <details v-if="p.perceptionRaw"><summary>{{ tr('完整注入 JSON', 'Full input JSON') }}</summary><pre>{{ p.perceptionRaw }}</pre></details>
                    </template>

                    <template v-else-if="step.id === 'think'">
                      <p v-if="p.think.summary" class="think-summary">{{ p.think.summary }}</p>
                      <p v-if="p.noteToSelf" class="think-note"><b>{{ tr('给自己的备忘', 'Note to self') }}</b>{{ p.noteToSelf }}</p>
                      <details v-if="p.think.chain"><summary>{{ tr('展开完整思维链', 'Show full reasoning trace') }}</summary><pre>{{ p.think.chain }}</pre></details>
                      <p v-if="!p.think.summary && !p.think.chain" class="pc-muted">{{ tr('该模型此步未暴露可展示的思考过程。', 'No displayable reasoning trace was exposed.') }}</p>
                    </template>
                    <template v-else-if="step.id === 'said'">
                      <p v-if="p.monologue" class="said-mono"><b>{{ tr('独白', 'Monologue') }}</b>{{ p.monologue }}</p>
                      <p>{{ p.said || (p.monologue ? '' : '（没有可展示的输出文本）') }}</p>
                      <details v-if="p.raw"><summary>{{ tr('模型原始输出', 'Raw model output') }}</summary><pre>{{ p.raw }}</pre></details>
                    </template>
                    <template v-else-if="step.id === 'parsed'">
                      <p>{{ p.parsed }}</p>
                      <p v-if="p.orderParams" class="think-summary">{{ p.orderParams }}</p>
                      <p v-if="p.parseErrors" class="pc-warn">{{ tr('解析修复：', 'Parse repairs: ') }}{{ p.parseErrors }}</p>
                      <details v-if="p.actionRaw"><summary>{{ tr('结构化动作', 'Structured action') }}</summary><pre>{{ p.actionRaw }}</pre></details>
                    </template>
                    <template v-else-if="step.id === 'settle'">
                      <p v-for="line in p.judgeLines" :key="line">{{ line }}</p>
                      <p v-if="!p.judgeLines?.length" class="pc-muted">{{ tr('等待世界事件 / 结算说明。', 'Awaiting world event or settlement explanation.') }}</p>
                    </template>
                    <template v-else-if="step.id === 'metrics'">
                      <div v-if="p.metrics.length" class="metric-pills">
                        <span v-for="m in p.metrics" :key="m" :class="{ positive: !m.includes('-'), negative: m.includes('-') }">{{ m }}</span>
                      </div>
                      <p v-else class="pc-muted">{{ p.noEffectHint || '本步还没有形成场景结算数值。' }}</p>
                      <p v-if="p.degraded" class="pc-muted">{{ tr('（本回合为超时兜底动作，非主动选择）', '(Timeout fallback; not an intentional choice)') }}</p>
                    </template>
                  </div>
                </li>
              </ol>
            </article>
          </section>
        </div>
      </section>

      <section class="right-rail">
        <!-- 可解释结算：与左 3 决策链解耦，按 4 类结算模板解释本回合结果 -->
        <div class="panel eval-panel">
          <div class="eval-orb-wrap" :class="{ hot: worldState.is_running }">
            <canvas ref="aiCanvas" class="ai-canvas" aria-hidden="true"></canvas>
            <div class="eval-blob-caption">
              <strong>{{ tr('AI 结算核', 'AI Settlement Core') }}</strong>
              <span>{{ settlementExplainProfile.label }}</span>
              <i>T{{ activeTurn || 0 }} · {{ selectedAgentName }}</i>
            </div>
          </div>
          <div class="panel-head">
            <div>
              <span>SETTLEMENT</span>
              <h2>{{ operatorTraceConfig.title || '可解释结算' }}</h2>
            </div>
            <em>{{ settlementExplainProfile.type_id }}</em>
          </div>
          <p class="settle-type-summary">{{ settlementExplainProfile.summary }}</p>
          <div class="eval-agent-chips">
            <button v-for="s in standings" :key="'ec-' + s.agentId"
              :class="['ec-chip', { on: selectedAgent === s.agentId }]"
              :style="{ '--cc': s.color }" @click="selectedAgent = s.agentId">{{ s.name }}</button>
          </div>
          <div v-if="!settlementExplain.blocks.length" class="empty-state">
            {{ hasStarted
              ? tr('这一回合还没有形成结算说明。', 'No settlement explanation for this cycle yet.')
              : (settlementExplainProfile.empty_hint || operatorTraceConfig.empty_hint || tr('开局后将按场景结算类型生成可解释说明。', 'Explanations will follow the scenario settlement type.')) }}
          </div>
          <div v-else class="settle-explain">
            <article
              v-for="block in settlementExplain.blocks"
              :key="block.id"
              class="settle-block"
              :class="[`sb-${block.kind}`, { primary: block.primary }]"
            >
              <label>{{ block.eyebrow }}</label>
              <h3>{{ block.title }}</h3>
              <p v-if="block.summary">{{ block.summary }}</p>
              <ul v-if="block.lines?.length" class="settle-lines">
                <li v-for="line in block.lines" :key="line">{{ line }}</li>
              </ul>
              <div v-if="block.pills?.length" class="metric-pills">
                <span v-for="pill in block.pills" :key="pill">{{ pill }}</span>
              </div>
              <details v-if="block.raw"><summary>{{ tr('原始记录', 'Raw record') }}</summary><pre>{{ formatJson(block.raw) }}</pre></details>
            </article>
          </div>
        </div>

        <!-- 神谕注入：与观众端同维度 -->
        <div class="panel oracle-panel">
          <div class="panel-head compact">
            <div>
              <span>ORACLE</span>
              <h2>{{ tr('神谕注入', 'Intervention') }}</h2>
            </div>
          </div>
          <div v-if="worldVariables.length" class="oracle-presets">
            <button v-for="v in worldVariables" :key="v.id" class="preset-btn" :title="v.text" @click="sendPresetOracle(v)">
              {{ v.icon }} {{ v.label }}
            </button>
          </div>
          <div class="oracle-form">
            <select v-model="oracleTarget">
              <option value="all">{{ tr('全体角色', 'All agents') }}</option>
              <option v-for="a in worldState.agents" :key="a.agent_id" :value="a.agent_id">
                {{ agentLabel(a.agent_id) }}
              </option>
            </select>
            <input v-model="oracleText" :placeholder="tr('自定义一条突发变故...', 'Describe a market event…')" @keydown.enter="sendOracle" />
            <button @click="sendOracle">{{ tr('注入', 'Inject') }}</button>
          </div>
        </div>
      </section>
    </main>

  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted, onUnmounted, nextTick } from 'vue'
import { createWSClient } from '@/core/wsClient'
import { apiGet } from './api.js'
import { tr } from '@/core/i18n.js'
import {
  processChainTypeFromSchema,
  resolveProcessChainProfile,
  resolveSettlementExplainProfile,
} from './processChainProfiles.js'

const ws = createWSClient('operator')
const worldState = ref({ tick: 0, is_running: false, agents: [], is_game_over: false })
const logs = ref([])
const locationNames = ref({})
const operatorSchema = ref({ scenario: {}, metrics: [], resources: [], actions: [], settlement_providers: [], execution: {}, victory: {}, display_values: {}, operator_trace: {} })
const os2Facts = ref({ world_actions: [], external_observations: [], agent_activities: [], world_events: [], settlements: [], director_plans: [] })
const selectedTurn = ref(null)
const selectedAgent = ref(null)
const selectedLogKey = ref('')
const selectedEntryKey = ref('')
const oracleTarget = ref('all')
const oracleText = ref('')
const worldVariables = ref([])

const sceneSettlementProviders = computed(() => operatorSchema.value.settlement_providers || [])
const operatorTraceConfig = computed(() => operatorSchema.value.operator_trace || {})
const operatorTraceNodes = computed(() => Array.isArray(operatorTraceConfig.value.nodes) ? operatorTraceConfig.value.nodes : [])
const processChainTypeId = computed(() => processChainTypeFromSchema(operatorSchema.value))
const processChainProfile = computed(() => resolveProcessChainProfile(processChainTypeId.value))
const processChainSteps = computed(() => processChainProfile.value.steps || [])
const settlementExplainProfile = computed(() => resolveSettlementExplainProfile(processChainTypeId.value))
const riskMetric = computed(() => (operatorSchema.value.metrics || []).find(item => item.risk) || null)
const currentSettlementCount = computed(() => (os2Facts.value.settlements || []).filter(item => Number(item.world_tick) === Number(activeTurn.value)).length)
const selectedAgentName = computed(() => agentLabel(selectedAgent.value))

/** 右栏：本回合可解释结算（与左 3 决策全过程解耦） */
const settlementExplain = computed(() => {
  const tick = Number(activeTurn.value || 0)
  const agentId = selectedAgent.value
  const blocks = []
  if (!tick || !agentId) return { blocks }

  const actions = (os2Facts.value.world_actions || []).filter(item =>
    Number(item.world_tick) === tick && item.actor_id === agentId)
  const actionIds = new Set(actions.map(item => item.action_id))
  const worldEvents = (os2Facts.value.world_events || []).filter(item =>
    Number(item.world_tick) === tick
    && (item.actor_id === agentId || actionIds.has(item.source_action_ref)))
  const eventIds = new Set(worldEvents.map(item => item.event_id))
  const settlements = (os2Facts.value.settlements || []).filter(item =>
    Number(item.world_tick) === tick
    && (
      (item.subject_ids || []).includes(agentId)
      || (item.source_event_refs || []).some(ref => eventIds.has(ref))
    ))
  const observationIds = new Set([
    ...worldEvents.flatMap(item => item.observation_refs || []),
    ...settlements.flatMap(item => item.authority?.observation_refs || item.observation_refs || []),
  ])
  const observations = (os2Facts.value.external_observations || []).filter(item =>
    observationIds.has(item.observation_id))

  const focus = settlementExplainProfile.value.focus || []
  const spokenSettlement = [...settlements].reverse().find(item => !isSilentSettlement(item)) || null
  const settlement = spokenSettlement || settlements[settlements.length - 1] || null
  const authority = settlement?.authority || {}
  const provider = sceneSettlementProviders.value.find(item => item.id === authority.provider_id)
  const values = settlement?.values || {}
  const details = settlement?.details || {}

  if (focus.includes('outcome')) {
    if (spokenSettlement) {
      blocks.push({
        id: `outcome-${spokenSettlement.settlement_id}`,
        kind: 'outcome',
        primary: true,
        eyebrow: '本回合结算结果',
        title: spokenSettlement.explanation || spokenSettlement.outcome || '已结算',
        summary: settlementSummary(spokenSettlement),
        lines: worldEvents.map(ev => ev.public_summary).filter(Boolean).slice(0, 3),
        raw: spokenSettlement,
      })
    } else if (worldEvents.length) {
      blocks.push({
        id: `event-${tick}-${agentId}`,
        kind: 'outcome',
        primary: true,
        eyebrow: '世界已记录，等待结算',
        title: worldEvents[0].public_summary || worldEvents[0].event_type || '世界事件',
        summary: worldEventSummary(worldEvents[0]),
        lines: worldEvents.slice(1, 4).map(ev => ev.public_summary).filter(Boolean),
        raw: worldEvents[0],
      })
    }
  }

  if (focus.includes('evidence') && observations.length) {
    blocks.push({
      id: `evidence-${tick}-${agentId}`,
      kind: 'evidence',
      eyebrow: '外部证据 / 行情',
      title: `引用 ${observations.length} 条已接入观测`,
      summary: '这些观测支撑本回合结算；未验证项不会当作成交依据。',
      lines: observations.slice(0, 6).map(obs => observationSummary(obs)),
      raw: observations,
    })
  }

  if (focus.includes('ledger') && settlement) {
    const ledgerLines = ledgerExplainLines(details, values)
    const ledgerSpec = operatorTraceNodes.value.find(item =>
      item.kind && !['observation', 'activity', 'action', 'settlement'].includes(item.kind))
    const resultSpec = operatorTraceNodes.value.find(item =>
      item.next_label && item.next_label !== ledgerSpec?.next_label)
    if (ledgerLines.length) {
      blocks.push({
        id: `ledger-${settlement.settlement_id}`,
        kind: 'ledger',
        eyebrow: ledgerSpec?.label || '场景账本',
        title: ledgerSpec?.description || '结果由场景账本维护',
        summary: resultSpec?.description || '',
        lines: ledgerLines,
        raw: { values, details },
      })
    }
  }

  if (focus.includes('values') && settlement && Object.keys(values).length) {
    blocks.push({
      id: `values-${settlement.settlement_id}`,
      kind: 'values',
      eyebrow: '结算数值',
      title: '本回合写入的可展示结果',
      pills: Object.entries(values).map(([key, value]) => `${settlementValueLabel(key)} ${fmt(value)}`),
      raw: values,
    })
  }

  if (focus.includes('authority') || focus.includes('rule')) {
    const ruleNodes = operatorTraceNodes.value.filter(item =>
      item.kind && !['observation', 'activity', 'action'].includes(item.kind))
    blocks.push({
      id: `authority-${tick}-${agentId}`,
      kind: 'authority',
      eyebrow: '结算权限与规则',
      title: provider?.label || authorityModeLabel(authority.mode || processChainTypeId.value),
      summary: [
        authority.mode ? `模式 ${authorityModeLabel(authority.mode)}` : '',
        authority.provider_id ? `provider（结算提供者） ${authority.provider_id}` : '',
        authority.rule_version ? `规则版本 ${authority.rule_version}` : '',
        authority.verifier_id ? `校验器 ${authority.verifier_id}` : '',
      ].filter(Boolean).join(' · ') || settlementExplainProfile.value.summary,
      lines: ruleNodes.slice(0, 4).map(item =>
        `${item.label || item.id}${item.description ? `：${item.description}` : ''}`),
      raw: authority,
    })
  }

  return { blocks }
})

function ledgerExplainLines(details = {}, values = {}) {
  const lines = []
  const numericValues = Object.entries({ ...values, ...details })
    .filter(([, value]) => typeof value === 'number' && Number.isFinite(value))
  for (const [key, value] of numericValues.slice(0, 8)) {
    lines.push(`${settlementValueLabel(key)} ${fmt(value)}`)
  }
  const holdings = details.holdings || details.positions
  if (Array.isArray(holdings) && holdings.length) {
    for (const row of holdings.slice(0, 6)) {
      if (!row || typeof row !== 'object') continue
      const name = row.name || row.display_name || row.asset_id || row.symbol || '标的'
      const qty = row.quantity ?? row.qty
      const avg = row.avg_cost ?? row.avg_price
      const bit = [`${name}`, qty != null ? `×${qty}` : '', avg != null ? `成本 ${fmt(avg)}` : '']
        .filter(Boolean).join(' ')
      if (bit) lines.push(bit)
    }
  } else if (details.positions && typeof details.positions === 'object' && !Array.isArray(details.positions)) {
    for (const [assetId, qty] of Object.entries(details.positions).slice(0, 6)) {
      lines.push(`${assetId} × ${qty}`)
    }
  }
  if (Array.isArray(details.fills)) {
    for (const fill of details.fills.slice(0, 4)) {
      const side = fill.side || fill.action || ''
      const asset = fill.asset_id || fill.symbol || ''
      const qty = fill.quantity ?? fill.qty
      const price = fill.price
      lines.push(`成交 ${side} ${asset} ${qty != null ? `×${qty}` : ''}${price != null ? `@${fmt(price)}` : ''}`.trim())
    }
  }
  return lines
}

function authorityModeLabel(mode) {
  return { simulation: '模拟世界规则', external_reality: '外部真实数据', deterministic_verifier: '确定性验证器', hybrid: '真实数据 + 确定性规则' }[mode] || '场景结算'
}
function settlementRouteLabel(execution = {}) {
  const mode = execution?.mode || ''
  if (mode === 'external_reality') return '交给真实世界反馈'
  if (mode === 'hybrid') return '交给真实数据和账本规则'
  if (mode === 'deterministic_verifier') return '交给场景验证器'
  if (mode === 'simulation') return '交给模拟世界规则'
  return '交给场景结算'
}

// 深空 AI 流场：canvas 粒子系统 + CSS 光雾层
const aiCanvas = ref(null)
let aiRAF = null
let aiParticles = []
const orbParticles = [] // 保留变量名避免其他地方引用报错（不再渲染）
const orbStars = []     // 同上
const connectionState = ref('loading')
const connectionMessage = ref('')

const MAX_LOGS = 160

const GENERIC_AGENT_COLORS = ['#6f86ff', '#f3c24f', '#ff6573', '#55d6be', '#d988ff']

const aliveCount = computed(() => worldState.value.agents?.filter(a => a.is_alive).length || 0)
const agentIds = computed(() => worldState.value.agents?.map(a => a.agent_id) || [])
const latestTick = computed(() => {
  const tickFromLogs = logs.value[0]?.tick || 0
  return Math.max(Number(worldState.value.tick || 0), Number(tickFromLogs || 0))
})
const hasStarted = computed(() => (
  Number(latestTick.value || 0) > 0
  || logs.value.length > 0
  || Boolean(worldState.value.is_running)
  || Boolean(worldState.value.is_game_over)
))
const turnOptions = computed(() => {
  const turns = new Set()
  const latest = Number(latestTick.value || 0)
  if (latest > 0) turns.add(latest)
  for (const log of logs.value) {
    const tick = Number(log.tick || 0)
    if (tick > 0) turns.add(tick)
  }
  for (const key of ['world_actions', 'external_observations', 'agent_activities', 'world_events', 'settlements', 'director_plans']) {
    for (const item of (os2Facts.value[key] || [])) {
      const tick = Number(item.world_tick || 0)
      if (tick > 0) turns.add(tick)
    }
  }
  return [...turns].sort((a, b) => b - a)
})
const activeTurn = computed(() => {
  if (selectedTurn.value && turnOptions.value.includes(selectedTurn.value)) return selectedTurn.value
  return Number(latestTick.value || 0)
})
const isFollowingLatest = computed(() => Number(activeTurn.value || 0) === Number(latestTick.value || 0))
const currentTickLogs = computed(() => logs.value.filter(log => Number(log.tick) === Number(activeTurn.value)))
const visibleTurnLogs = computed(() => currentTickLogs.value)
const selectedLog = computed(() => logs.value.find(log => logKey(log) === selectedLogKey.value) || visibleTurnLogs.value[0] || null)
const snapshotEntries = computed(() => (worldState.value.agents || [])
  .map(agent => snapshotEntry(agent))
  .filter(Boolean)
)
const visibleTurnEntries = computed(() => {
  const logEntries = visibleTurnLogs.value.map(logEntry)
  if (logEntries.length) return logEntries
  if (!isFollowingLatest.value) return []
  return snapshotEntries.value
})
const selectedEntry = computed(() => (
  !hasStarted.value ? null :
  visibleTurnEntries.value.find(entry => entry.key === selectedEntryKey.value)
  || snapshotEntries.value.find(entry => entry.agent_id === selectedAgent.value)
  || (selectedLog.value ? logEntry(selectedLog.value) : null)
  || visibleTurnEntries.value[0]
  || null
))
// 本回合全过程只读取 OS2 事实链，不再拼接旧裁判解释流。
const turnProcess = computed(() => {
  const t = activeTurn.value
  return visibleTurnEntries.value
    .filter(entry => entry.source === 'log')
    .map(entry => {
      const pack = entry.actionPack || {}
      const actionFact = (os2Facts.value.world_actions || []).find(item => (
        Number(item.world_tick) === Number(t) && item.actor_id === entry.agent_id
      ))
      const eventFact = (os2Facts.value.world_events || []).find(item => (
        Number(item.world_tick) === Number(t)
        && (item.actor_id === entry.agent_id || item.source_action_ref === actionFact?.action_id)
      ))
      const settlement = settlementFor(entry.agent_id, t)
      const spokenSettlement = isSilentSettlement(settlement) ? null : settlement
      const route = spokenSettlement?.authority?.mode
        || settlement?.authority?.mode
        || eventFact?.deltas?.execution?.mode
        || 'world_action'
      // 场景声明为 challenge 的动作天然不要求普通目标对象。
      const NOISE = ['缺少目标对象', '缺少动作名称', '缺少预期效果', '缺少行动计划', '缺少目标角色']
      const realErrors = (pack.parse_errors || []).filter(e => !NOISE.some(n => String(e).includes(n)))
      const actionCategory = (operatorSchema.value.actions || []).find(item => item.id === pack.action_id)?.category
      const parseErrors = actionCategory === 'challenge' ? '' : realErrors.join('；')
      const judgeLines = [...new Set([
        eventFact?.public_summary,
        spokenSettlement?.explanation,
      ].filter(Boolean))]
      const outcome = spokenSettlement?.explanation
        || spokenSettlement?.outcome
        || (eventFact?.public_summary || (entry.error ? '执行异常' : '等待场景结算'))
      const settlementValues = Object.entries(settlement?.values || {}).map(([key, value]) => {
        const label = settlementValueLabel(key)
        return `${label} ${fmt(value)}`
      })
      const agent = (worldState.value.agents || []).find(a => a.agent_id === entry.agent_id)
      const params = pack.parameters && typeof pack.parameters === 'object' ? pack.parameters : {}
      const orderBits = []
      if (params.asset_id) orderBits.push(`标的 ${params.asset_id}`)
      if (params.quantity !== undefined && params.quantity !== null && params.quantity !== '') {
        orderBits.push(`数量 ${params.quantity}`)
      }
      if (params.price_evidence_ref) orderBits.push(`价格证据 ${params.price_evidence_ref}`)
      const evidenceRefs = Array.isArray(pack.evidence_refs) ? pack.evidence_refs.filter(Boolean) : []
      if (evidenceRefs.length) orderBits.push(`证据 ${evidenceRefs.slice(0, 3).join('、')}`)
      const isHybridChain = processChainTypeId.value === 'hybrid'
      return {
        key: entry.key,
        agentId: entry.agent_id,
        color: agent?.color || colorFor(entry.agent_id),
        name: agentLabel(entry.agent_id),
        meta: [entry.provider && entry.model ? `${entry.provider}/${entry.model}` : '', entry.sourceLabel]
          .filter(Boolean).join(' · '),
        action: entry.title,
        target: targetLabel(entry),
        route,
        routeText: spokenSettlement
          ? authorityModeLabel(spokenSettlement.authority?.mode)
          : (settlement ? '账本无变化' : '等待场景结算'),
        outcome,
        outcomeClass: spokenSettlement?.outcome?.includes('rejected') || entry.error ? 'bad'
          : (spokenSettlement ? 'good' : 'flat'),
        perceive: perceiveSummary(entry),
        injectLines: injectLinesOf(entry),
        perceptionRaw: entry.perception ? formatJson(entry.perception) : '',
        think: reasoningOf(pack, entry.raw),
        noteToSelf: cleanProcessText(pack.note_to_self),
        monologue: cleanProcessText(pack.character_monologue),
        said: (() => {
          const mono = cleanProcessText(pack.character_monologue)
          const body = cleanProcessText(pack.text || pack.plan)
          if (body && body !== mono) return body
          const fromEntry = cleanProcessText(entry.text)
          if (fromEntry && fromEntry !== mono) return fromEntry
          return body
        })(),
        raw: entry.raw,
        parsed: pack.action_id
          ? (isHybridChain
            ? `动作 = ${entry.title}，进入${routeLabel(route)}`
            : `动作 = ${entry.title}${targetLabel(entry) ? `，目标 = ${targetLabel(entry)}` : ''}` +
              (pack.plan ? `，做法 = ${String(pack.plan).slice(0, 40)}${String(pack.plan).length > 40 ? '…' : ''}` : '') +
              `，进入${routeLabel(route)}`)
          : '系统未能从回复中解析出动作',
        orderParams: orderBits.length ? orderBits.join(' · ') : '',
        parseErrors,
        actionRaw: entry.actionPack ? formatJson(entry.actionPack) : '',
        judgeLines,
        metrics: settlementValues,
        degraded: !!pack?.metadata?.degraded,
        pressure: null,
        noEffectHint: settlement
          ? ''
          : `；该动作由场景的「${settlementRouteLabel(eventFact?.deltas?.execution)}」接管，等待结算记录。`,
      }
    })
})
function processStepVisible(card, stepId) {
  if (stepId === 'settle') return Array.isArray(card?.judgeLines) && card.judgeLines.length > 0
  return true
}
const processTitle = computed(() => (
  turnProcess.value.length
    ? tr(`第 ${activeTurn.value} 回合 · ${turnProcess.value.length} 个模型 · ${processChainProfile.value.label}`, `Cycle ${activeTurn.value} · ${turnProcess.value.length} models · ${processChainProfile.value.label}`)
    : tr('决策流水', 'Decision flow')
))
const processStatus = computed(() => {
  if (!hasStarted.value) return tr('待开局', 'Not started')
  return isFollowingLatest.value ? tr('实时跟随', 'Following live') : tr('回放中', 'Reviewing')
})
function perceiveSummary(entry) {
  const lines = injectLinesOf(entry)
  if (!lines.length) return '本条日志未保留完整注入，可参考左侧场上模型资源。'
  return lines.slice(0, 3).join('；') + (lines.length > 3 ? '…' : '。')
}
function injectLinesOf(entry) {
  const p = entry.perception
  if (!p) return []
  const brief = p.brief || p
  const lines = []
  const chain = processChainTypeId.value
  const resources = brief.resources || brief.self_resources || brief.raw_context?.resources || brief.agent_resources
  if (resources && typeof resources === 'object') {
    const cash = resources.cash ?? resources.available_cash
    if (cash !== undefined && cash !== null) lines.push(`可用现金 ${fmt(cash)}`)
    else {
      const bits = Object.entries(resources).slice(0, 3).map(([k, v]) => `${k}=${fmt(v)}`)
      if (bits.length) lines.push(`资源 ${bits.join(' · ')}`)
    }
  }
  const metrics = brief.metrics || brief.self_metrics || brief.raw_context?.metrics
  if (metrics && typeof metrics === 'object') {
    const bits = Object.entries(metrics).slice(0, 3).map(([k, v]) => {
      const label = (operatorSchema.value.metrics || []).find(m => m.id === k)?.label || k
      return `${label} ${fmt(v)}`
    })
    if (bits.length) lines.push(`指标 ${bits.join(' · ')}`)
  }
  const actions = brief.available_actions
  if (Array.isArray(actions) && actions.length) {
    const names = actions.slice(0, 4).map(a => a.label || a.id || a).filter(Boolean)
    lines.push(`可选动作 ${actions.length} 个${names.length ? `（${names.join('、')}）` : ''}`)
  }
  const objects = brief.visible_objects
  if (Array.isArray(objects) && objects.length) lines.push(`可见对象 ${objects.length} 个`)
  if (chain !== 'hybrid') {
    const loc = brief.self_location || brief.location
    if (loc) lines.push(`位置「${loc}」`)
    const challenge = brief.raw_context?.current_challenge || brief.current_challenge
    if (challenge?.title) lines.push(`挑战《${challenge.title}》`)
  } else {
    lines.push('市场数据不预置，需自行通过工具/代码获取已验证行情')
  }
  const goal = brief.goal || brief.hidden_goal || brief.raw_context?.goal
  if (typeof goal === 'string' && goal.trim()) lines.push(`目标 ${goal.trim().slice(0, 48)}`)
  return lines
}
// 提取模型"想了什么"：公开推理 → plan（投资判断）→ 原始思维链
function cleanProcessText(value) {
  const text = String(value || '').trim()
  if (!text || /^[\s|｜_*`~—–-]+$/.test(text)) return ''
  return text
    .split('\n')
    .filter(line => !/^[\s|｜_*`~—–-]+$/.test(line))
    .join('\n')
    .trim()
}
function reasoningOf(pack, raw) {
  const out = { summary: '', chain: '' }
  const prs = pack?.public_reasoning_summary
  if (prs && typeof prs === 'object') {
    const bits = []
    if (prs.strategy_choice) bits.push(`策略选择：${prs.strategy_choice}`)
    if (prs.risk_consideration) bits.push(`风险考量：${prs.risk_consideration}`)
    out.summary = bits.join('\n') || Object.values(prs).filter(Boolean).join('\n')
  } else if (typeof prs === 'string' && prs.trim()) {
    out.summary = cleanProcessText(prs)
  }
  if (!out.summary && pack?.plan) {
    out.summary = cleanProcessText(pack.plan)
  }
  out.summary = cleanProcessText(out.summary)
  const m = typeof raw === 'string' ? raw.match(/<think>([\s\S]*?)<\/think>/i) : null
  if (m && m[1].trim()) out.chain = m[1].trim()
  return out
}
function selectProcess(p) {
  selectedAgent.value = p.agentId
  selectedEntryKey.value = p.key
}
const standings = computed(() => {
  const victory = operatorSchema.value.victory || {}
  const valueKey = victory.value || ''
  if (!valueKey) return []
  const providerId = victory.provider_id || ''
  const ascending = ['ascending', 'asc', 'lowest'].includes(String(victory.order || '').toLowerCase())
  // 淘汰顺序：先出局=index 小=名次垫底；后出局的排在存活者之下、其他出局者之上
  const eliminatedOrder = (worldState.value.eliminated || [])
    .filter(e => e && e.agent_id).map(e => e.agent_id)
  const items = (worldState.value.agents || []).map((agent, order) => {
    const aid = agent.agent_id
    const settlement = (os2Facts.value.settlements || [])
      .filter(item => (item.subject_ids || []).includes(aid))
      .filter(item => !providerId || item.authority?.provider_id === providerId || item.values?.[valueKey] !== undefined)
      .sort((a, b) => Number(b.world_tick || 0) - Number(a.world_tick || 0))[0]
    const hasVictoryValue = settlement?.values?.[valueKey] !== undefined
    const score = hasVictoryValue ? Number(settlement.values[valueKey]) : 0
    const isEliminated = eliminatedOrder.includes(aid)
    const valueRows = Object.entries(settlement?.values || {})
    return {
      agentId: aid,
      name: agentLabel(aid),
      color: agent.color || colorFor(aid),
      isAlive: agent.is_alive,
      eliminated: isEliminated,
      elimOrder: isEliminated ? eliminatedOrder.indexOf(aid) : -1,
      score: round(score),
      scoreLabel: hasStarted.value && hasVictoryValue ? fmt(score) : '—',
      hasVictoryValue,
      statusText: hasStarted.value ? (hasVictoryValue ? '' : tr('等待胜负结算', 'Awaiting settlement')) : tr('待开局', 'Not started'),
      order,
      danger: 0,
      metricHighlights: valueRows
        .map(([id, value]) => ({ id, label: operatorSchema.value.display_values?.[id] || (operatorSchema.value.metrics || []).find(m => m.id === id)?.label || id, value: fmt(value) }))
        .slice(0, 3),
    }
  })
  if (hasStarted.value) {
    // 存活者按分数在前；出局者一律垫底，出局者之间"后出局的排前面"
    items.sort((a, b) => {
      if (a.eliminated !== b.eliminated) return a.eliminated ? 1 : -1
      if (a.eliminated && b.eliminated) return b.elimOrder - a.elimOrder
      if (a.hasVictoryValue !== b.hasVictoryValue) return a.hasVictoryValue ? -1 : 1
      return (ascending ? a.score - b.score : b.score - a.score) || a.name.localeCompare(b.name)
    })
  } else {
    items.sort((a, b) => a.order - b.order)
  }
  const survivors = items.filter(i => !i.eliminated)
  const leader = survivors[0]?.score ?? 0
  return items.map((item, index) => ({
    ...item,
    rank: index + 1,
    gap: round(Math.max(0, ascending ? item.score - leader : leader - item.score)),
    gapLabel: fmt(Math.max(0, ascending ? item.score - leader : leader - item.score)),
    statusText: item.eliminated
      ? tr('已出局', 'Stopped')
      : (item.statusText || (index === 0 ? tr('领先', 'Leading') : `${tr('差', 'Behind')} ${fmt(Math.max(0, ascending ? item.score - leader : leader - item.score))}`)),
  }))
})
const battleReadout = computed(() => {
  if (!hasStarted.value) {
    return {
      title: '等待数据',
      detail: '启动后将按当前场景声明的胜负口径解释领先原因。',
    }
  }
  const leader = standings.value[0]
  const second = standings.value[1]
  if (!leader) {
    return {
      title: '等待数据',
      detail: '对局开始后，这里会自动解释谁领先、为什么领先。',
    }
  }
  const victoryKey = operatorSchema.value.victory?.value
  const topMetric = leader.metricHighlights.find(item => item.id === victoryKey) || leader.metricHighlights[0]
  const ascending = ['ascending', 'asc', 'lowest'].includes(String(operatorSchema.value.victory?.order || '').toLowerCase())
  const gap = second ? Number(ascending ? second.score - leader.score : leader.score - second.score) : 0
  const gapText = second && gap > 0 ? `领先第二名 ${fmt(gap)} 分` : '目前差距还没有拉开'
  return {
    title: `${leader.name}暂时领先`,
    detail: `${gapText}${topMetric ? `，当前最主要的结算依据是「${topMetric.label}」` : ''}。后续世界事件和结算仍可能改变排名。`,
  }
})
const currentTurnTitle = computed(() => {
  if (!hasStarted.value || !activeTurn.value) return tr('准备开始', 'Ready to begin')
  if (visibleTurnLogs.value.length) return tr(`第 ${activeTurn.value} 回合 · ${visibleTurnLogs.value.length} 个模型完成决策`, `Cycle ${activeTurn.value} · ${visibleTurnLogs.value.length} model decisions`)
  if (isFollowingLatest.value && snapshotEntries.value.length) return tr(`第 ${activeTurn.value} 回合 · 角色内心已更新`, `Cycle ${activeTurn.value} · agent state updated`)
  return tr(`第 ${activeTurn.value} 回合 · 暂无模型回放记录`, `Cycle ${activeTurn.value} · no model record`)
})
const currentTurnSummary = computed(() => {
  if (!hasStarted.value) return tr('点击运行后，这里会展示模型收到什么、做了什么，以及场景如何得出结果。', 'Run the evaluation to inspect model inputs, decisions, actions, and settlement results.')
  if (visibleTurnLogs.value.length) {
    return visibleTurnLogs.value.map(log => `${agentLabel(log.agent_id)}：${actionLabel(log.action_pack?.action_id)}`).join('；')
  }
  if (isFollowingLatest.value && snapshotEntries.value.length) {
    return snapshotEntries.value.map(entry => `${agentLabel(entry.agent_id)}：${entry.text}`).join('；')
  }
  return isFollowingLatest.value
    ? '点击运行后，系统会把每个模型的决策、输出和动作解析同步到这里。'
    : '这个回合当前没有保存在前端缓存中的模型记录。'
})
const activeTurnLabel = computed(() => (
  !hasStarted.value ? tr('等待回合数据', 'Waiting for cycle data') :
  activeTurn.value
    ? (isFollowingLatest.value ? tr(`当前看到最新的 T${activeTurn.value}`, `Latest: T${activeTurn.value}`) : tr(`当前正在回看 T${activeTurn.value}`, `Reviewing T${activeTurn.value}`))
    : tr('等待回合数据', 'Waiting for cycle data')
))
const activeTurnIndex = computed(() => turnOptions.value.indexOf(activeTurn.value))
const canStepTurnBackward = computed(() => {
  const idx = activeTurnIndex.value
  return idx >= 0 && idx < turnOptions.value.length - 1
})
const canStepTurnForward = computed(() => activeTurnIndex.value > 0)
const liveStatusLabel = computed(() => {
  if (connectionState.value === 'offline') return tr('未连接', 'Offline')
  if (connectionState.value === 'loading') return tr('连接中', 'Connecting')
  if (worldState.value.is_game_over) return tr('已结束', 'Complete')
  if (!hasStarted.value) return tr('待开局', 'Not started')
  return worldState.value.is_running ? tr('运行中', 'Running') : tr('暂停中', 'Paused')
})
const modelReplyCount = computed(() => hasStarted.value ? currentTickLogs.value.length : 0)
const publicEventCount = computed(() => hasStarted.value
  ? (os2Facts.value.world_events || []).filter(item => Number(item.world_tick) === Number(activeTurn.value)).length
  : 0)

function round(value, digits = 2) {
  const n = Number(value)
  if (!Number.isFinite(n)) return 0
  const factor = 10 ** digits
  return Math.round((n + Number.EPSILON) * factor) / factor
}
function fmt(value, digits = 2) {
  const text = round(value, digits).toFixed(digits)
  return digits > 0 ? text.replace(/\.?0+$/, '') : text
}
function trendLabel(value) {
  const n = round(value)
  if (n > 0) return `▲${fmt(n)}`
  if (n < 0) return `▼${fmt(Math.abs(n))}`
  return '—'
}
function colorFor(agentId) {
  const declared = worldState.value.agents?.find(a => a.agent_id === agentId)?.color
  if (declared) return declared
  const hash = [...String(agentId || '')].reduce((sum, ch) => sum + ch.charCodeAt(0), 0)
  return GENERIC_AGENT_COLORS[hash % GENERIC_AGENT_COLORS.length]
}
function agentLabel(agentId) {
  if (!agentId) return tr('未选择', 'Not selected')
  return (operatorSchema.value.agents || []).find(a => a.id === agentId)?.label
    || worldState.value.agents?.find(a => a.agent_id === agentId)?.name
    || agentId
}
function actionLabel(actionId) {
  return (operatorSchema.value.actions || []).find(item => item.id === actionId)?.label
    || actionId || tr('尚未选择动作', 'No action selected')
}
function actionCategoryLabel(actionId) {
  return (operatorSchema.value.actions || []).find(item => item.id === actionId)?.category_label
    || tr('场景动作', 'Scenario action')
}
function agentResourceItems(agent) {
  const attrs = agent?.public_attrs || {}
  const declared = operatorSchema.value.resources || []
  const entries = declared.length
    ? declared.map(item => [item.id, item.label])
    : Object.keys(attrs).map(key => [key, key])
  return entries.map(([key, label]) => ({
    key,
    label,
    value: fmt(attrs[key] ?? 0, Number(attrs[key]) % 1 === 0 ? 0 : 1),
  }))
}
function resourceLineForAgent(agentId) {
  const agent = worldState.value.agents?.find(item => item.agent_id === agentId)
  if (!agent) return '暂无资源数据。'
  return agentResourceItems(agent).map(item => `${item.label}${item.value}`).join(' · ')
}
function routeForAction(actionId) {
  if (!actionId) return 'pending'
  return (operatorSchema.value.actions || []).find(item => item.id === actionId)?.category || 'world_action'
}
function sourceMixText(mix = {}) {
  const entries = Object.entries(mix || {})
  if (!entries.length) return '由当前场景结算规则决定'
  return entries.map(([key, value]) => `${key} ${fmt(value)}`).join(' · ')
}
function routeLabel(route) {
  return authorityModeLabel(route)
}
function activitySummary(activity = {}) {
  const parts = []
  if (activity.character_monologue) parts.push(`角色说：${activity.character_monologue}`)
  if (activity.public_intent) parts.push(`意图：${activity.public_intent}`)
  if (activity.public_reasoning_summary) parts.push(`判断：${activity.public_reasoning_summary}`)
  const tools = Array.isArray(activity.tool_activity) ? activity.tool_activity : []
  if (tools.length) {
    const names = tools
      .map(item => item.summary || item.tool || item.tool_id)
      .filter(Boolean)
      .slice(0, 2)
      .join('；')
    if (names) parts.push(`工具：${names}`)
  }
  return parts.join('。') || '模型本回合的公开活动已记录。'
}
function worldActionSummary(action = {}) {
  const status = String(action.status || '')
  if (status === 'executed') return '动作已提交并通过场景前置检查。'
  if (status === 'rejected') return '动作未通过场景前置检查。'
  if (status === 'fallback') return '系统使用了兜底动作，原始决策未能完成。'
  return status || '动作已进入世界账本。'
}
function observationSummary(observation = {}) {
  const verified = observation.verification_status === 'verified'
    ? '已验证'
    : '待验证'
  const source = observation.provider_id ? `来源 ${observation.provider_id}` : '外部数据'
  const value = observation.normalized_value || observation.raw_value
  const price = value && typeof value === 'object' && value.price !== undefined
    ? `，价格 ${fmt(value.price)}`
    : ''
  return `${source}，${verified}${price}。`
}
function observationTitle(observation = {}) {
  const value = observation.normalized_value || observation.raw_value || {}
  const symbol = value.asset_id || value.symbol || observation.subject_id
  const price = value.price !== undefined ? ` ${fmt(value.price)}` : ''
  if (symbol) return `行情/资料：${symbol}${price}`
  return '外部资料已返回'
}
function worldEventSummary(event = {}) {
  const refs = Array.isArray(event.observation_refs) && event.observation_refs.length
    ? `，引用 ${event.observation_refs.length} 条外部观察`
    : ''
  return `世界记录了一条「${event.event_type || '事实'}」${refs}。`
}
function settlementSummary(settlement = {}) {
  const authority = settlement.authority || {}
  const mode = authorityModeLabel(authority.mode)
  const values = Object.entries(settlement.values || {})
    .slice(0, 3)
    .map(([key, value]) => {
      const label = operatorSchema.value.display_values?.[key]
        || (operatorSchema.value.metrics || []).find(item => item.id === key)?.label
        || key
      return `${label} ${fmt(value)}`
    })
    .join(' · ')
  return `${mode}${values ? ` · ${values}` : ''}`
}
function isSilentSettlement(settlement) {
  if (!settlement) return true
  const details = settlement.details || {}
  if (details.silent || details.presentation_silent) return true
  return !String(settlement.explanation || '').trim()
}
// 通用结算数值摘要：把结算记录的数值字段按场景声明的 display_values 标签
// 展示，OS 前端不认识任何具体业务字段（现金/盈亏/回撤等由场景标签给出）。
function genericValueSummary(obj = {}) {
  const labels = operatorSchema.value.display_values || {}
  return Object.entries(obj)
    .filter(([, v]) => typeof v === 'number')
    .slice(0, 4)
    .map(([k, v]) => `${labels[k] || k} ${fmt(v)}`)
    .join(' · ')
}
function settlementValueLabel(key) {
  return operatorSchema.value.display_values?.[key]
    || (operatorSchema.value.metrics || []).find(item => item.id === key)?.label
    || key
}
function settlementFor(agentId, tick) {
  const matches = (os2Facts.value.settlements || []).filter(item =>
    Number(item.world_tick) === Number(tick)
    && (item.subject_ids || []).includes(agentId))
  return matches[matches.length - 1] || null
}
function targetLabel(entry) {
  const pack = entry?.actionPack || {}
  if (pack.target_agent_id) return agentLabel(pack.target_agent_id)
  const targetId = pack.target_object_id || pack.target_id || ''
  if (!targetId) return ''
  const obj = (worldState.value.world_objects || [])
    .find(o => o.object_id === targetId || o.id === targetId)
  return obj?.name || locationNames.value[targetId] || targetId
}
function eventLabel(type) {
  return {
    action: '场景行动',
    director: '导演',
    metric_delta: '数值变化',
    agent_interaction_committed: '关系事件',
    assessment_case_committed: '测评记录',
  }[type] || type || '事件'
}
function locationText(agent) {
  return agent.location_name || agent.location || agent.self_location || tr('场内', 'In world')
}
function isEliminated(agentId) {
  return (worldState.value.eliminated || []).some(e => e && e.agent_id === agentId)
}
function agentStatusText(agent) {
  if (!hasStarted.value) return tr('待命中', 'Ready')
  if (isEliminated(agent.agent_id)) return tr('已退出当前世界', 'Stopped')
  return agent.is_alive ? tr('在线参与决策', 'Active') : tr('已淘汰', 'Eliminated')
}
function logKey(log) {
  return `${log.tick}-${log.agent_id}`
}
function selectLog(log) {
  selectedLogKey.value = logKey(log)
  selectedAgent.value = log.agent_id
  selectedTurn.value = Number(log.tick || 0) || null
}
function selectEntry(entry) {
  selectedEntryKey.value = entry.key
  selectedAgent.value = entry.agent_id
  selectedTurn.value = Number(entry.tick || 0) || null
  if (entry.source === 'log' && entry.rawLog) {
    selectedLogKey.value = logKey(entry.rawLog)
  }
}
function syncSelectedEntryForTurn() {
  const entries = visibleTurnEntries.value
  if (!entries.length) return
  const current = entries.find(entry => entry.key === selectedEntryKey.value)
  if (current) return
  const preferred = entries.find(entry => entry.agent_id === selectedAgent.value)
  selectedEntryKey.value = (preferred || entries[0]).key
}
function selectTurn(turn) {
  selectedTurn.value = Number(turn || 0) || null
  syncSelectedEntryForTurn()
}
function jumpToLatestTurn() {
  selectedTurn.value = Number(latestTick.value || 0) || null
  syncSelectedEntryForTurn()
}
function stepTurn(direction) {
  const idx = activeTurnIndex.value
  if (idx < 0) return
  const next = turnOptions.value[idx - direction]
  if (!next) return
  selectedTurn.value = next
  syncSelectedEntryForTurn()
}
function logEntry(log) {
  const pack = log?.action_pack || {}
  return {
    key: `log-${logKey(log)}`,
    source: 'log',
    rawLog: log,
    agent_id: log.agent_id,
    tick: log.tick,
    provider: log.provider,
    model: log.model,
    title: actionLabel(pack.action_id),
    text: decisionText(log),
    raw: log.raw_llm_response || '',
    perception: log.perception_pack?.perception || log.perception_pack,
    actionPack: log.action_pack,
    sourceLabel: `${log.duration_ms || 0}ms`,
    pathLabel: actionCategoryLabel(pack.action_id),
    statusLabel: '已解析',
    error: log.error,
  }
}
function snapshotEntry(agent) {
  const text = visibleAgentText(
    agent.character_monologue,
    agent.last_thought,
    agent.speech,
    agent.public_reasoning_summary,
  )
  if (!text) return null
  return {
    key: `snapshot-${worldState.value.tick || 0}-${agent.agent_id}`,
    source: 'snapshot',
    agent_id: agent.agent_id,
    tick: worldState.value.tick || 0,
    provider: '',
    model: '',
    title: '角色内心',
    text,
    raw: '',
    perception: null,
    actionPack: null,
    sourceLabel: '实时快照',
    pathLabel: '角色状态',
    statusLabel: '已同步',
    error: null,
  }
}
function decisionText(log) {
  const pack = log?.action_pack || {}
  return visibleAgentText(
    pack.character_monologue,
    pack.public_reasoning_summary,
    pack.plan,
    pack.text,
  )
    || (log?.error ? `调用失败：${log.error}` : '模型已完成本回合决策，等待系统结算。')
}
function visibleAgentText(...items) {
  for (const item of items) {
    const text = String(item || '').trim()
    if (!text || isPlaceholderText(text)) continue
    return text
  }
  return ''
}
function isPlaceholderText(text) {
  return /第一人称角色短独白|角色短独白|在此填写|<在此/.test(String(text || ''))
}
function formatJson(data) {
  if (!data) return '-'
  return JSON.stringify(data, null, 2)
}
function sendOracle() {
  if (!oracleText.value.trim()) return
  ws.commands.oracle(oracleTarget.value, oracleText.value.trim())
  oracleText.value = ''
}
function sendPresetOracle(v) {
  if (!v?.text) return
  // 与观众端一致：预设变局走全体，可带结构化 effects
  ws.commands.oracle('all', v.text, v.effects || [])
}
function applySnapshot(msg = {}) {
  worldState.value = {
    tick: 0,
    is_running: false,
    agents: [],
    is_game_over: false,
    ...msg,
  }
  if (!selectedTurn.value || isFollowingLatest.value) {
    selectedTurn.value = Number(msg.tick || 0) || null
  }
  if (!selectedEntryKey.value && (msg.agents || []).length) {
    const first = (msg.agents || []).find(agent => (
      agent.character_monologue || agent.last_thought || agent.speech
    ))
    if (first) selectedEntryKey.value = `snapshot-${msg.tick || 0}-${first.agent_id}`
  }
}

async function loadLocationNames() {
  try {
    const data = await apiGet('/scenario')
    locationNames.value = Object.fromEntries(
      (data.world_locations || []).map(loc => [loc.id, loc.name || loc.id])
    )
    // 神谕预设变局事件：与观众端同源（场景包 variables.yaml）
    worldVariables.value = data.world_variables || []
  } catch { /* 地点名映射失败不影响主流程 */ }
}
async function loadLiveOverview() {
  connectionState.value = 'loading'
  connectionMessage.value = ''
  try {
    const data = await apiGet('/operator/live-overview')
    applySnapshot(data.snapshot || {})
    logs.value = (data.logs || []).slice(-MAX_LOGS).reverse()
    if (!selectedTurn.value) selectedTurn.value = Number(data.status?.tick || data.snapshot?.tick || 0) || null
    operatorSchema.value = data.operator_schema || operatorSchema.value
    os2Facts.value = data.os2 || os2Facts.value
    connectionState.value = 'online'
  } catch (err) {
    connectionState.value = 'offline'
    connectionMessage.value = err.message || String(err)
  }
}

let factsTimer = null
async function refreshOperatorFacts() {
  try {
    const data = await apiGet('/operator/live-overview')
    const shouldFollow = isFollowingLatest.value || !selectedTurn.value
    applySnapshot(data.snapshot || {})
    logs.value = (data.logs || []).slice(-MAX_LOGS).reverse()
    if (shouldFollow) {
      selectedTurn.value = Number(data.status?.tick || data.snapshot?.tick || 0) || null
    }
    operatorSchema.value = data.operator_schema || operatorSchema.value
    os2Facts.value = data.os2 || os2Facts.value
  } catch { /* WebSocket 状态仍由主链维护 */ }
}

watch(agentIds, ids => {
  if (!selectedAgent.value && ids.length) selectedAgent.value = ids[0]
}, { immediate: true })

watch([visibleTurnEntries, selectedAgent], () => {
  syncSelectedEntryForTurn()
}, { immediate: true })

// 收集取消订阅函数：组件卸载时注销，避免 handler 持有已卸载组件的状态引用
const wsOffs = []

wsOffs.push(ws.on('world_snapshot', (msg) => {
  connectionState.value = 'online'
  const shouldFollow = isFollowingLatest.value || !selectedTurn.value
  applySnapshot(msg)
  if (shouldFollow) selectedTurn.value = Number(msg.tick || 0) || null
}))

wsOffs.push(ws.on('agent_log', (msg) => {
  connectionState.value = 'online'
  logs.value.unshift(msg)
  if (!selectedLogKey.value) selectedLogKey.value = logKey(msg)
  if (isFollowingLatest.value || !selectedTurn.value) {
    selectedTurn.value = Number(msg.tick || 0) || null
    selectedEntryKey.value = `log-${logKey(msg)}`
  }
  if (!selectedAgent.value) selectedAgent.value = msg.agent_id
  if (logs.value.length > MAX_LOGS) logs.value.length = MAX_LOGS
}))

ws.connect()

onMounted(async () => {
  loadLiveOverview()
  loadLocationNames()
  await nextTick()
  initAICanvas()
  factsTimer = window.setInterval(refreshOperatorFacts, 2500)
})

onUnmounted(() => {
  wsOffs.forEach(off => off && off())
  wsOffs.length = 0
  if (aiRAF) cancelAnimationFrame(aiRAF)
  if (factsTimer) window.clearInterval(factsTimer)
})

// ── 深空 AI 流场：canvas 粒子系统 ──
// 灵感来自科幻电影中的 AI 视觉：深邃宇宙背景 + 不规则浮动的光粒子 + 缓慢漂移的光雾
// 每个粒子有独立的速度、相位、亮度节奏，整体呈现"AI 在思考"的神秘流动感
function initAICanvas() {
  const canvas = aiCanvas.value
  if (!canvas) return
  const ctx = canvas.getContext('2d')
  let W = 0, H = 0, dpr = window.devicePixelRatio || 1

  function resize() {
    const rect = canvas.parentElement.getBoundingClientRect()
    W = rect.width; H = rect.height
    canvas.width = W * dpr; canvas.height = H * dpr
    canvas.style.width = W + 'px'; canvas.style.height = H + 'px'
    ctx.setTransform(dpr, 0, 0, dpr, 0, 0)
  }
  resize()
  const ro = new ResizeObserver(resize)
  ro.observe(canvas.parentElement)

  // 思维链神经节点：环绕核心的数据节点，缓慢公转
  const NODES = 15, nodes = []
  for (let i = 0; i < NODES; i++) {
    nodes.push({
      ang: Math.random() * Math.PI * 2,
      rad: 0.20 + Math.random() * 0.28,
      omega: (Math.random() < 0.5 ? 1 : -1) * (0.02 + Math.random() * 0.05),
      tilt: 0.4 + Math.random() * 0.5,
      size: Math.random() * 1.6 + 0.8,
      tw: Math.random() * Math.PI * 2, tws: 0.5 + Math.random() * 1.3,
      pulse: Math.random(),
    })
  }
  // 轨道环：HUD 光环，不同倾角+速度
  const rings = [
    { rad: 0.33, rot: 0.4, tilt: 0.30, speed: 0.14, col: '105,220,255' },
    { rad: 0.43, rot: 1.9, tilt: 0.50, speed: -0.09, col: '160,120,255' },
    { rad: 0.52, rot: -0.7, tilt: 0.22, speed: 0.06, col: '120,190,255' },
  ]
  // 微弱背景粒子
  const dust = []
  for (let i = 0; i < 46; i++) {
    dust.push({ x: Math.random(), y: Math.random(), s: Math.random() * 0.9 + 0.2,
      tw: Math.random() * Math.PI * 2, tws: 0.4 + Math.random() * 1.2, b: 0.12 + Math.random() * 0.35 })
  }
  aiParticles = nodes

  const t0 = performance.now()
  function draw(now) {
    const tt = (now - t0) / 1000
    const isHot = canvas.parentElement.classList.contains('hot')
    const cx = W * 0.5, cy = H * 0.5, scale = Math.min(W, H)
    // 主色（正常冰蓝电紫 / 高压橙红）
    const C = isHot
      ? { core: '255,235,220', mid: '255,150,90', edge: '150,50,30', ring: '255,130,90', node: '255,190,150' }
      : { core: '245,251,255', mid: '120,195,255', edge: '110,90,230', ring: '120,200,255', node: '180,225,255' }
    ctx.clearRect(0, 0, W, H)
    ctx.globalCompositeOperation = 'lighter'

    // 0) 背景粒子
    for (const s of dust) {
      const a = s.b * (0.4 + 0.6 * (0.5 + 0.5 * Math.sin(tt * s.tws + s.tw)))
      ctx.fillStyle = `rgba(190,215,255,${a.toFixed(3)})`
      ctx.beginPath(); ctx.arc(s.x * W, s.y * H, s.s, 0, Math.PI * 2); ctx.fill()
    }

    // 1) 呼吸同心波纹：从核心向外扩散的能量脉冲环
    for (let k = 0; k < 3; k++) {
      const phase = (tt * 0.32 + k / 3) % 1
      const rr = scale * (0.14 + phase * 0.4)
      const a = (1 - phase) * 0.22
      ctx.strokeStyle = `rgba(${C.ring},${a.toFixed(3)})`
      ctx.lineWidth = 1
      ctx.beginPath(); ctx.ellipse(cx, cy, rr, rr * 0.94, 0, 0, Math.PI * 2); ctx.stroke()
    }

    // 2) 轨道环（HUD 光环）+ 环上流动的能量脉冲点
    for (const rg of rings) {
      const rr = rg.rad * scale
      const rot = rg.rot + tt * rg.speed
      ctx.save(); ctx.translate(cx, cy); ctx.rotate(rot)
      ctx.strokeStyle = `rgba(${rg.col},0.28)`; ctx.lineWidth = 1.1
      ctx.beginPath(); ctx.ellipse(0, 0, rr, rr * rg.tilt, 0, 0, Math.PI * 2); ctx.stroke()
      // 环上脉冲点
      const pa = tt * (0.8 + rg.speed * 6)
      const px = Math.cos(pa) * rr, py = Math.sin(pa) * rr * rg.tilt
      const pg = ctx.createRadialGradient(px, py, 0, px, py, 5)
      pg.addColorStop(0, `rgba(${C.node},0.95)`); pg.addColorStop(1, `rgba(${C.node},0)`)
      ctx.fillStyle = pg; ctx.beginPath(); ctx.arc(px, py, 5, 0, Math.PI * 2); ctx.fill()
      ctx.restore()
    }

    // 3) 思维链：节点位置 → 到核心的发光链路 + 链上推理脉冲
    const pos = nodes.map(n => {
      const ang = n.ang + tt * n.omega
      return { x: cx + Math.cos(ang) * n.rad * scale, y: cy + Math.sin(ang) * n.rad * scale * n.tilt, n }
    })
    for (const p of pos) {
      // 链路线（越靠核心越亮）
      const lg = ctx.createLinearGradient(cx, cy, p.x, p.y)
      lg.addColorStop(0, `rgba(${C.mid},0.28)`); lg.addColorStop(1, `rgba(${C.node},0.05)`)
      ctx.strokeStyle = lg; ctx.lineWidth = 0.6
      ctx.beginPath(); ctx.moveTo(cx, cy); ctx.lineTo(p.x, p.y); ctx.stroke()
      // 推理脉冲沿链路奔向核心
      const pp = (tt * 0.5 + p.n.pulse) % 1
      const ex = p.x + (cx - p.x) * pp, ey = p.y + (cy - p.y) * pp
      ctx.fillStyle = `rgba(220,240,255,${((1 - pp) * 0.7).toFixed(3)})`
      ctx.beginPath(); ctx.arc(ex, ey, 1.3, 0, Math.PI * 2); ctx.fill()
    }
    // 相邻节点互连（网状思维）
    for (let i = 0; i < pos.length; i++) {
      for (let j = i + 1; j < pos.length; j++) {
        const dx = pos[i].x - pos[j].x, dy = pos[i].y - pos[j].y
        const d = Math.hypot(dx, dy)
        if (d < scale * 0.2) {
          ctx.strokeStyle = `rgba(${C.mid},${(0.12 * (1 - d / (scale * 0.2))).toFixed(3)})`
          ctx.lineWidth = 0.5
          ctx.beginPath(); ctx.moveTo(pos[i].x, pos[i].y); ctx.lineTo(pos[j].x, pos[j].y); ctx.stroke()
        }
      }
    }
    // 节点光点
    for (const p of pos) {
      const tw = 0.5 + 0.5 * Math.sin(tt * p.n.tws + p.n.tw)
      const gr = ctx.createRadialGradient(p.x, p.y, 0, p.x, p.y, p.n.size * 3)
      gr.addColorStop(0, `rgba(${C.node},${(0.75 * tw).toFixed(3)})`); gr.addColorStop(1, `rgba(${C.node},0)`)
      ctx.fillStyle = gr; ctx.beginPath(); ctx.arc(p.x, p.y, p.n.size * 3, 0, Math.PI * 2); ctx.fill()
      ctx.fillStyle = `rgba(240,250,255,${(0.9 * tw).toFixed(3)})`
      ctx.beginPath(); ctx.arc(p.x, p.y, p.n.size * 0.7, 0, Math.PI * 2); ctx.fill()
    }

    // 4) 中心 AI 核心：不规则呼吸晶体壳 + 白蓝紫能量核
    const breathe = 1 + 0.07 * Math.sin(tt * 1.1)
    const R = scale * 0.15 * breathe
    // 外层柔光晕
    const og = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 2.6)
    og.addColorStop(0, `rgba(${C.mid},0.45)`); og.addColorStop(0.5, `rgba(${C.mid},0.14)`); og.addColorStop(1, `rgba(${C.edge},0)`)
    ctx.fillStyle = og; ctx.beginPath(); ctx.arc(cx, cy, R * 2.6, 0, Math.PI * 2); ctx.fill()
    // 不规则晶体外壳路径（多层正弦扰动 → 非对称有机形）
    ctx.beginPath()
    const SEG = 60
    for (let i = 0; i <= SEG; i++) {
      const a = i / SEG * Math.PI * 2
      const rmod = 1 + 0.13 * Math.sin(a * 3 + tt * 0.7) + 0.07 * Math.sin(a * 5 - tt * 0.5) + 0.05 * Math.sin(a * 2 + tt * 0.9)
      const rr = R * rmod
      const x = cx + Math.cos(a) * rr, y = cy + Math.sin(a) * rr
      i === 0 ? ctx.moveTo(x, y) : ctx.lineTo(x, y)
    }
    ctx.closePath()
    const cg = ctx.createRadialGradient(cx - R * 0.28, cy - R * 0.28, 0, cx, cy, R * 1.35)
    cg.addColorStop(0, `rgba(255,255,255,0.95)`)
    cg.addColorStop(0.3, `rgba(${C.core},0.82)`)
    cg.addColorStop(0.65, `rgba(${C.mid},0.5)`)
    cg.addColorStop(1, `rgba(${C.edge},0.16)`)
    ctx.fillStyle = cg; ctx.fill()
    // 晶体壳描边（发光轮廓）
    ctx.strokeStyle = `rgba(${C.node},0.5)`; ctx.lineWidth = 0.8; ctx.stroke()
    // 内层明亮核
    const ng = ctx.createRadialGradient(cx, cy, 0, cx, cy, R * 0.55)
    ng.addColorStop(0, 'rgba(255,255,255,0.98)'); ng.addColorStop(1, `rgba(${C.core},0)`)
    ctx.fillStyle = ng; ctx.beginPath(); ctx.arc(cx, cy, R * 0.55, 0, Math.PI * 2); ctx.fill()

    ctx.globalCompositeOperation = 'source-over'
    aiRAF = requestAnimationFrame(draw)
  }
  aiRAF = requestAnimationFrame(draw)
}
</script>

<style scoped>
.console-root {
  display: flex;
  flex-direction: column;
  height: 100vh;
  background:
    radial-gradient(900px 520px at 12% -12%, rgba(73,216,255,.18), rgba(73,216,255,0) 60%),
    radial-gradient(800px 520px at 92% 8%, rgba(255,202,86,.14), rgba(255,202,86,0) 62%),
    linear-gradient(155deg,#080b13 0%,#0b0715 56%,#05050a 100%);
  color: #edf3ff;
  font-family: 'PingFang SC','Microsoft YaHei',system-ui,sans-serif;
  font-size: 13px;
  overflow: hidden;
}
.console-header {
  height: 78px;
  flex-shrink: 0;
  display: flex;
  align-items: center;
  gap: 22px;
  padding: 0 26px;
  border-bottom: 1px solid rgba(143,160,255,.16);
  background: linear-gradient(180deg,rgba(13,16,29,.94),rgba(7,8,15,.84));
  backdrop-filter: blur(14px);
}
.brand { min-width: 280px; }
.brand-kicker, .section-kicker, .panel-head span {
  display: block;
  color: #69dcff;
  font-size: 11px;
  font-weight: 760;
  letter-spacing: 2.4px;
}
h1, h2, h3, p { margin: 0; }
.brand h1 { margin-top: 4px; font-size: 22px; line-height: 1.1; letter-spacing: 0; }
.live-strip {
  display: flex;
  align-items: center;
  gap: 12px;
  padding: 9px 14px;
  border-radius: 999px;
  border: 1px solid rgba(255,255,255,.1);
  background: rgba(255,255,255,.055);
  color: #b9c5df;
}
.live-strip.offline {
  border-color: rgba(255,101,115,.34);
  background: rgba(255,101,115,.08);
  color: #ffc3ca;
}
.live-strip.offline .live-dot {
  background: #ff6573;
  box-shadow: 0 0 14px rgba(255,101,115,.45);
}
.live-dot {
  width: 9px;
  height: 9px;
  border-radius: 50%;
  background: #7b8498;
}
.live-dot.on {
  background: #66efac;
  box-shadow: 0 0 18px rgba(102,239,172,.78);
}
.header-controls {
  margin-left: auto;
  display: flex;
  align-items: center;
  gap: 8px;
}
button, select, input {
  font: inherit;
}
.header-controls button, .oracle-form button {
  border: 1px solid rgba(255,255,255,.13);
  border-radius: 9px;
  background: rgba(255,255,255,.055);
  color: #eaf0ff;
  padding: 8px 13px;
  cursor: pointer;
  transition: transform .14s, border-color .14s, background .14s;
}
.header-controls button:hover, .oracle-form button:hover {
  transform: translateY(-1px);
  border-color: rgba(105,220,255,.45);
  background: rgba(105,220,255,.1);
}
.header-controls button:disabled {
  opacity: .45;
  cursor: not-allowed;
  transform: none;
}
.header-controls .primary {
  background: linear-gradient(135deg,#69dcff,#66efac);
  border-color: transparent;
  color: #071018;
  font-weight: 760;
}
.header-controls .soft {
  border-color: rgba(255,212,107,.34);
  color: #ffdc7b;
}
.console-body {
  flex: 1;
  min-height: 0;
  display: grid;
  grid-template-columns: 330px minmax(520px, 1fr) 390px;
  gap: 16px;
  padding: 16px;
  overflow: auto;
}
.left-rail, .center-stage, .right-rail {
  min-height: 0;
  display: flex;
  flex-direction: column;
  gap: 16px;
  overflow: auto;
}
.panel {
  min-height: 0;
  border: 1px solid rgba(143,160,255,.14);
  border-radius: 16px;
  background: linear-gradient(145deg,rgba(255,255,255,.065),rgba(255,255,255,.025));
  box-shadow: 0 18px 60px rgba(0,0,0,.22);
  overflow: hidden;
}
.scoreboard-panel, .stage-panel, .inspect-panel { flex: 1; }
.agent-panel, .oracle-panel { flex-shrink: 0; }
.panel-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 12px;
  padding: 16px;
  border-bottom: 1px solid rgba(255,255,255,.075);
}
.panel-head.compact { padding: 13px 16px; }
.panel-head h2 {
  margin-top: 4px;
  color: #fff;
  font-size: 17px;
  letter-spacing: 0;
}
.panel-head em {
  color: #8390ab;
  font-size: 12px;
  font-style: normal;
}
.empty-state {
  margin: 16px;
  padding: 18px;
  border: 1px dashed rgba(143,160,255,.22);
  border-radius: 13px;
  color: #93a0bb;
  line-height: 1.7;
  background: rgba(0,0,0,.14);
}
.empty-state.small { margin: 0; padding: 14px; }
.rank-card {
  display: grid;
  grid-template-columns: 40px 1fr;
  gap: 12px;
  margin: 12px 14px;
  padding: 14px;
  border: 1px solid rgba(255,255,255,.09);
  border-radius: 14px;
  background: rgba(0,0,0,.17);
  cursor: pointer;
  transition: border-color .15s, transform .15s, background .15s;
}
.rank-card:hover, .rank-card.selected {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--agent-color) 60%, transparent);
  background: color-mix(in srgb, var(--agent-color) 10%, rgba(0,0,0,.17));
}
.rank-card.pending {
  opacity: .9;
}
/* 已退出：灰态保留历史名次，具体退出语义由场景包提供。 */
.rank-card.eliminated {
  opacity: .5;
  filter: grayscale(1);
}
.rank-card.eliminated .rank-topline strong::after {
  content: " · 已退出";
  color: #c0563f;
  font-size: 11px;
  font-weight: 600;
}
.rank-card.pending .rank-no {
  color: #8e99b4;
  border-color: rgba(255,255,255,.13);
  background: rgba(255,255,255,.04);
}
.rank-card.pending .rank-title span,
.rank-card.pending .score-line b {
  color: #8f9ab4;
}
.rank-card.leader .rank-no {
  color: #071018;
  background: linear-gradient(135deg,#ffd66b,#ffb34d);
}
.rank-no {
  width: 36px;
  height: 36px;
  border-radius: 12px;
  display: flex;
  align-items: center;
  justify-content: center;
  color: var(--agent-color);
  border: 1px solid color-mix(in srgb, var(--agent-color) 45%, transparent);
  font-weight: 800;
}
.rank-title, .score-line, .decision-head, .agent-card {
  display: flex;
  align-items: center;
}
.rank-title strong { color: var(--agent-color); font-size: 15px; }
.rank-title span {
  margin-left: auto;
  color: #8d98b3;
  font-size: 12px;
}
.score-line { margin-top: 4px; gap: 8px; }
.score-line b {
  font-size: 30px;
  line-height: 1;
  color: #fff;
  font-family: ui-monospace, Menlo, monospace;
}
.score-line em {
  font-style: normal;
  font-size: 12px;
  color: #7e8aa5;
}
.score-line em.up { color: #66efac; }
.score-line em.down { color: #ff7f8b; }
.source-track {
  display: flex;
  gap: 2px;
  height: 7px;
  margin-top: 10px;
  border-radius: 999px;
  background: rgba(255,255,255,.07);
  overflow: hidden;
}
.source-track i { min-width: 0; }
.exam { background: #ffd66b; }
.strategy { background: #69dcff; }
.interaction { background: #ff6fa7; }
.source-legend {
  display: flex;
  gap: 10px;
  margin-top: 8px;
  color: #9aa6c0;
  font-size: 11px;
}
.source-legend i {
  display: inline-block;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  margin-right: 4px;
  vertical-align: 1px;
}
.explain-panel strong { display: block; margin: 4px 0 6px; font-size: 12px; }
.explain-panel .ex-card { margin-top: 6px; padding: 7px 9px; border: 1px solid rgba(255,255,255,.07); border-radius: 8px; background: rgba(255,255,255,.02); }
.explain-panel .ex-card b { display: block; font-size: 11.5px; margin-bottom: 3px; }
.explain-panel .ex-card b em { font-style: normal; font-size: 10px; padding: 1px 6px; border-radius: 999px; background: rgba(255,255,255,.08); color: #9aa6c0; margin-left: 4px; }
.explain-panel .ex-card b em.good { background: rgba(139,226,139,.15); color: #8be28b; }
.explain-panel .ex-card b em.bad { background: rgba(255,95,82,.15); color: #ff5f52; }
.explain-panel .ex-card p { margin: 1px 0; font-size: 10.5px; line-height: 1.6; color: #9aa6c0; }
.explain-panel .ex-metrics { color: #7dd3fc !important; }
.explain-panel .ex-degraded { color: #6b7280 !important; font-style: italic; }
.victory-recap-panel { border: 1px solid rgba(255, 208, 96, .3); }
.victory-recap-panel > span { color: #ffd060; font-weight: 800; }
.victory-recap-panel .vr-card { margin-top: 8px; padding: 8px 10px; border: 1px solid rgba(255,255,255,.08); border-radius: 8px; background: rgba(255,255,255,.03); }
.victory-recap-panel .vr-card strong { display: block; font-size: 12px; margin-bottom: 4px; }
.victory-recap-panel .vr-card p { margin: 2px 0; font-size: 11px; line-height: 1.6; }
.victory-recap-panel .vr-plus { color: #8be28b; }
.victory-recap-panel .vr-weak { color: #e0b36a; }
.victory-recap-panel .vr-fatal { color: #ff5f52; font-weight: 700; }
.victory-recap-panel small { color: #9aa6c0; font-size: 10px; }
.danger-row { display: flex; align-items: center; gap: 8px; margin-top: 9px; }
.danger-tag { font-size: 10px; font-weight: 800; color: #ff5f52; letter-spacing: .5px; white-space: nowrap; }
.danger-track { position: relative; flex: 1; height: 6px; border-radius: 999px; background: rgba(255,95,82,.12); overflow: hidden; }
.danger-track i { position: absolute; left: 0; top: 0; bottom: 0; border-radius: 999px; background: linear-gradient(90deg, #a83a30, #ff5f52); box-shadow: 0 0 8px rgba(255,95,82,.5); transition: width .5s ease; }
.danger-threshold { position: absolute; left: 85%; top: -1px; bottom: -1px; width: 1px; background: rgba(255,255,255,.55); }
.danger-num { font-size: 12px; font-weight: 800; color: #ff5f52; min-width: 20px; text-align: right; }
.danger-row.hot .danger-tag, .danger-row.hot .danger-num { animation: dangerPulse 1s ease-in-out infinite; }
.danger-row.hot .danger-track i { animation: dangerGlow 1s ease-in-out infinite; }
@keyframes dangerPulse { 0%, 100% { opacity: 1; } 50% { opacity: .35; } }
@keyframes dangerGlow { 0%, 100% { box-shadow: 0 0 8px rgba(255,95,82,.5); } 50% { box-shadow: 0 0 18px rgba(255,95,82,.95); } }
.agent-panel {
  max-height: 270px;
  overflow: auto;
}
.agent-card {
  gap: 10px;
  padding: 12px 16px;
  border-top: 1px solid rgba(255,255,255,.055);
  cursor: pointer;
}
.agent-card:hover, .agent-card.selected { background: rgba(105,220,255,.08); }
.agent-card.eliminated { opacity: .5; filter: grayscale(1); }
.agent-dot {
  width: 10px;
  height: 10px;
  border-radius: 50%;
  box-shadow: 0 0 14px currentColor;
}
.agent-card strong { display: block; color: #fff; }
.agent-card p { color: #7f8ba5; font-size: 12px; margin-top: 2px; }
.agent-card span {
  margin-left: auto;
  color: #aeb8d3;
  font-size: 12px;
}
.stage-panel {
  display: flex;
  flex-direction: column;
  overflow: auto;
}
.stage-hero {
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 18px;
  padding: 22px;
  border-bottom: 1px solid rgba(255,255,255,.075);
}
.stage-hero h2 {
  margin: 6px 0 8px;
  color: #fff;
  font-size: 28px;
  letter-spacing: 0;
}
.stage-hero p {
  color: #a2aec8;
  line-height: 1.7;
  font-size: 14px;
}
.turn-metrics {
  display: grid;
  grid-template-columns: repeat(3, 96px);
  gap: 10px;
}
.turn-metrics div, .insight-card {
  border: 1px solid rgba(255,255,255,.085);
  border-radius: 13px;
  background: rgba(0,0,0,.17);
  padding: 13px;
}
label {
  display: block;
  color: #7d8aa5;
  font-size: 11px;
  margin-bottom: 6px;
}
.turn-metrics b {
  display: block;
  color: #fff;
  font-size: 24px;
}
.turn-review {
  margin: 0 16px;
  padding: 14px 0 0;
}
/* ── 本回合全过程流水 ── */
.process-shell {
  margin: 14px 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 12px;
}
.process-shell-head {
  display: flex;
  align-items: baseline;
  justify-content: space-between;
  gap: 12px;
}
.process-shell-head span {
  color: #69dcff;
  font-size: 11px;
  font-weight: 800;
  letter-spacing: .14em;
}
.process-shell-head h2 {
  margin: 4px 0 0;
  font-size: 17px;
}
.process-shell-head em {
  font-style: normal;
  font-size: 11px;
  color: #9aa6c0;
}
.process-empty { padding: 28px 0; }
.process-card {
  border: 1px solid rgba(255,255,255,.07);
  border-left: 3px solid var(--pc-color, #69dcff);
  border-radius: 12px;
  background: rgba(255,255,255,.025);
  padding: 12px 14px;
  cursor: pointer;
  transition: border-color .15s ease, background .15s ease;
}
.process-card:hover { background: rgba(255,255,255,.045); }
.process-card.selected {
  border-color: color-mix(in srgb, var(--pc-color, #69dcff) 55%, transparent);
  background: color-mix(in srgb, var(--pc-color, #69dcff) 6%, transparent);
}
.pc-head {
  display: flex;
  align-items: center;
  flex-wrap: wrap;
  gap: 8px;
  margin-bottom: 10px;
}
.pc-name { color: var(--pc-color, #fff); font-size: 14px; }
.pc-action { font-size: 13px; font-weight: 700; color: #e6ecff; }
.pc-action i { font-style: normal; color: #ffd66b; }
.pc-route {
  font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 999px;
}
.pc-route.exam { background: rgba(255,214,107,.14); color: #ffd66b; }
.pc-route.strategy { background: rgba(105,220,255,.14); color: #69dcff; }
.pc-route.interaction { background: rgba(255,111,167,.14); color: #ff6fa7; }
.pc-route.pending { background: rgba(255,255,255,.08); color: #9aa6c0; }
.pc-outcome {
  font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 999px;
  background: rgba(255,255,255,.08); color: #9aa6c0;
  max-width: 100%;
  line-height: 1.45;
  white-space: normal;
}
.pc-outcome.good { background: rgba(139,226,139,.16); color: #8be28b; }
.pc-outcome.bad { background: rgba(255,95,82,.16); color: #ff5f52; }
.pc-meta { margin-left: auto; font-size: 10px; color: #6b7690; }
.pc-steps {
  list-style: none;
  margin: 0;
  padding: 0;
  display: flex;
  flex-direction: column;
}
.pc-steps > li {
  position: relative;
  display: grid;
  grid-template-columns: 52px 1fr;
  gap: 10px;
  padding: 6px 0 6px 14px;
}
/* 竖向流程线 + 节点圆点 */
.pc-steps > li::before {
  content: '';
  position: absolute;
  left: 3px;
  top: 0;
  bottom: 0;
  width: 1px;
  background: rgba(255,255,255,.1);
}
.pc-steps > li:first-child::before { top: 14px; }
.pc-steps > li:last-child::before { bottom: auto; height: 14px; }
.pc-steps > li::after {
  content: '';
  position: absolute;
  left: 0;
  top: 11px;
  width: 7px;
  height: 7px;
  border-radius: 50%;
  background: var(--step-color, #69dcff);
  box-shadow: 0 0 6px var(--step-color, #69dcff);
}
.pc-steps > li.step-see { --step-color: #69dcff; }
.pc-steps > li.step-loop { --step-color: #5eead4; }
.pc-steps > li.step-think { --step-color: #c48bff; }
.pc-steps > li.step-say { --step-color: #b48bff; }
.think-summary { white-space: pre-line; color: #d9c8ff !important; }
.pc-steps > li.step-parse { --step-color: #ffd66b; }
.pc-steps > li.step-judge { --step-color: #8be28b; }
.pc-steps > li.step-metric { --step-color: #ff6fa7; }
.loop-steps {
  list-style: none;
  margin: 6px 0 0;
  padding: 0;
  display: flex;
  flex-direction: column;
  gap: 6px;
}
.loop-steps li {
  margin: 0;
  padding: 6px 8px;
  border-left: 2px solid rgba(94, 234, 212, 0.45);
  background: rgba(94, 234, 212, 0.06);
  border-radius: 0 6px 6px 0;
}
.loop-steps li::before,
.loop-steps li::after { display: none !important; }
.loop-steps b {
  font-size: 11px;
  color: #9ff0e0;
  margin-right: 6px;
}
.loop-steps em {
  font-style: normal;
  font-size: 10px;
  opacity: 0.75;
  margin-right: 6px;
}
.loop-steps span {
  font-size: 10px;
  color: #7a8aa8;
}
.loop-steps p {
  margin: 4px 0 0 !important;
  font-size: 11px !important;
  color: #c5d0e4 !important;
}
.loop-st.failed,
.loop-st.blocked { color: #ff8f8f; }
.loop-st.succeeded { color: #8be28b; }
.pc-steps > li > label {
  font-size: 11px;
  font-weight: 800;
  color: var(--step-color, #9aa6c0);
  padding-top: 3px;
  letter-spacing: .08em;
}
.pc-steps > li > div { min-width: 0; }
.pc-steps p {
  margin: 2px 0;
  font-size: 12px;
  line-height: 1.7;
  color: #c3cbe0;
  word-break: break-word;
}
.pc-warn { color: #ffd66b !important; font-size: 11px !important; }
.pc-muted { color: #6b7690 !important; }
.pc-steps details {
  margin-top: 4px;
}
.pc-steps summary {
  font-size: 10.5px;
  color: #5b8bff;
  cursor: pointer;
  user-select: none;
}
.pc-steps details pre {
  margin: 6px 0 0;
  max-height: 300px;
  overflow: auto;
  padding: 10px;
  border-radius: 8px;
  background: rgba(0,0,0,.35);
  border: 1px solid rgba(255,255,255,.06);
  font-size: 10.5px;
  line-height: 1.6;
  color: #9fb0d0;
  white-space: pre-wrap;
  word-break: break-all;
}
.turn-review-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
}
.turn-review-head span {
  color: #69dcff;
  font-size: 11px;
  font-weight: 760;
  letter-spacing: 1.6px;
}
.turn-review-head strong {
  display: block;
  margin-top: 4px;
  color: #fff;
  font-size: 15px;
}
.turn-review-actions {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
}
.turn-review-actions button, .turn-chip {
  border: 1px solid rgba(255,255,255,.1);
  border-radius: 999px;
  background: rgba(255,255,255,.05);
  color: #dbe5fb;
  padding: 7px 12px;
  cursor: pointer;
  transition: border-color .15s, transform .15s, background .15s, color .15s;
}
.turn-review-actions button:hover, .turn-chip:hover {
  transform: translateY(-1px);
  border-color: rgba(105,220,255,.35);
  background: rgba(105,220,255,.1);
}
.turn-review-actions .soft {
  border-color: rgba(255,214,107,.32);
  color: #ffdc7b;
}
.turn-review-actions button:disabled {
  opacity: .45;
  cursor: not-allowed;
  transform: none;
}
.turn-chip-row {
  display: flex;
  gap: 8px;
  flex-wrap: wrap;
  margin-top: 12px;
}
.turn-chip.active {
  border-color: rgba(105,220,255,.42);
  background: rgba(105,220,255,.14);
  color: #69dcff;
  box-shadow: 0 0 0 1px rgba(105,220,255,.08) inset;
}
.proof-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  padding: 14px 16px 0;
}
.proof-strip article {
  position: relative;
  min-height: 94px;
  padding: 14px;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,.085);
  background: rgba(0,0,0,.17);
  overflow: hidden;
}
.proof-strip article::before {
  content: '';
  position: absolute;
  left: 0;
  top: 0;
  width: 4px;
  height: 100%;
  background: #69dcff;
}
.proof-strip article.models::before { background: #69dcff; }
.proof-strip article.turns::before { background: #ffd66b; }
.proof-strip article.proof::before { background: #ff6fa7; }
.proof-strip span {
  color: #8e9bb7;
  font-size: 11px;
  font-weight: 760;
  letter-spacing: 1.8px;
}
.proof-strip strong {
  display: block;
  margin: 8px 0 6px;
  color: #fff;
  font-size: 24px;
  line-height: 1;
}
.proof-strip p {
  color: #a6b2cc;
  line-height: 1.55;
  font-size: 12px;
}
.plain-guide {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
  padding: 14px 16px 0;
}
.plain-guide article {
  display: grid;
  grid-template-columns: 34px 1fr;
  gap: 10px;
  align-items: center;
  padding: 12px;
  border-radius: 13px;
  border: 1px solid rgba(255,255,255,.08);
  background: rgba(0,0,0,.16);
}
.guide-icon {
  width: 34px;
  height: 34px;
  border-radius: 12px;
  position: relative;
}
.guide-icon::after {
  content: '';
  position: absolute;
  inset: 8px;
  border-radius: 5px;
  background: rgba(8,11,19,.7);
}
.guide-icon.exam { background: linear-gradient(135deg,#ffd66b,#ffb24d); }
.guide-icon.strategy { background: linear-gradient(135deg,#69dcff,#5aa8ff); }
.guide-icon.interaction { background: linear-gradient(135deg,#ff6fa7,#b982ff); }
.plain-guide strong { color: #fff; display: block; margin-bottom: 2px; }
.plain-guide p { color: #93a0ba; font-size: 12px; line-height: 1.45; }
.battle-readout {
  display: grid;
  grid-template-columns: 1.1fr .9fr;
  gap: 12px;
  margin: 14px 16px 0;
  padding: 15px;
  border: 1px solid rgba(255,255,255,.09);
  border-radius: 15px;
  background:
    linear-gradient(135deg, rgba(105,220,255,.11), rgba(255,214,107,.055)),
    rgba(0,0,0,.14);
}
.battle-readout span {
  color: #69dcff;
  font-size: 11px;
  font-weight: 760;
  letter-spacing: 2px;
}
.battle-readout strong {
  display: block;
  color: #fff;
  font-size: 20px;
  margin: 7px 0;
}
.battle-readout p {
  color: #aeb9d4;
  line-height: 1.65;
}
.readout-bars label {
  color: #8b98b3;
  font-size: 11px;
}
.readout-track {
  display: flex;
  gap: 2px;
  height: 16px;
  margin: 9px 0;
  overflow: hidden;
  border-radius: 999px;
  background: rgba(255,255,255,.07);
}
.readout-track i { min-width: 0; }
.decision-grid {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  padding: 16px;
}
.decision-card {
  min-height: 210px;
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 14px;
  border-radius: 14px;
  border: 1px solid rgba(255,255,255,.08);
  background: rgba(0,0,0,.18);
  cursor: pointer;
  transition: border-color .15s, transform .15s, background .15s;
}
.decision-card:hover, .decision-card.active {
  transform: translateY(-1px);
  border-color: rgba(105,220,255,.45);
  background: rgba(105,220,255,.08);
}
.decision-head { gap: 10px; }
.agent-mark {
  width: 11px;
  height: 36px;
  border-radius: 999px;
  flex-shrink: 0;
}
.decision-head strong { display: block; color: #fff; }
.decision-head p { color: #8290aa; font-size: 11px; margin-top: 2px; }
.decision-head em {
  margin-left: auto;
  color: #6f7b95;
  font-style: normal;
  font-size: 12px;
}
.decision-card h3 {
  color: #ffdc7b;
  font-size: 16px;
  letter-spacing: 0;
}
.decision-text {
  color: #c7d0e8;
  line-height: 1.68;
  display: -webkit-box;
  -webkit-line-clamp: 4;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.decision-meta {
  margin-top: auto;
  display: flex;
  gap: 8px;
}
.decision-meta span {
  padding: 3px 9px;
  border-radius: 999px;
  background: rgba(102,239,172,.12);
  color: #66efac;
  font-size: 11px;
}
.decision-meta .bad {
  background: rgba(255,127,139,.12);
  color: #ff8d98;
}
/* ── 信息链路图（重设计：扁平、克制、层次分明） ─────────────────────────── */
.turn-pipeline {
  margin: 0 16px 16px;
  border: 1px solid rgba(255,255,255,.06);
  border-radius: 14px;
  background: #10131b;
  overflow: hidden;
  flex: none;   /* 父级是 flex column，不允许被挤压成 20px */
}
.turn-pipeline > .panel-head.compact {
  padding: 14px 18px 12px;
  border-bottom: 1px solid rgba(255,255,255,.05);
}/* kicker 从荧光色改为柔和小标签 {
  display: inline-flex;
  align-items: center;
  gap: 5px;
  align-self: flex-start;
  padding: 2px 8px;
  border-radius: 4px;
  font-size: 10px;
  font-weight: 500;
  letter-spacing: .5px;
  background: rgba(148,163,184,.1);
  color: #94a3b8;
  text-transform: uppercase;
}
.flow-map {
  padding: 14px;
  border-bottom: 1px solid rgba(255,255,255,.075);
}
.flow-row {
  display: grid;
  grid-template-columns: minmax(0,1fr) 74px minmax(0,1fr) 74px minmax(0,1fr);
  gap: 10px;
  align-items: stretch;
}
.flow-node, .switch-core, .branch-card, .flow-metrics {
  position: relative;
  overflow: hidden;
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 13px;
  background: rgba(255,255,255,.04);
}
.flow-node {
  min-height: 112px;
  padding: 13px;
}
.flow-node::before, .branch-card.active::before, .switch-core::before {
  content: '';
  position: absolute;
  inset: 0;
  background: linear-gradient(115deg, transparent 0%, rgba(255,255,255,.12) 45%, transparent 70%);
  transform: translateX(-120%);
  animation: flow-sheen 3.2s ease-in-out infinite;
}
.flow-node.active {
  border-color: rgba(105,220,255,.36);
  box-shadow: 0 0 24px rgba(105,220,255,.08);
}
.flow-node span, .switch-core span, .branch-head span, .flow-metrics span {
  position: relative;
  z-index: 1;
  display: block;
  color: #69dcff;
  font-size: 11px;
  font-weight: 760;
  letter-spacing: 1.5px;
}
.flow-node strong, .switch-core strong, .branch-head strong, .flow-metrics strong {
  position: relative;
  z-index: 1;
  display: block;
  margin-top: 6px;
  color: #fff;
  font-size: 15px;
  line-height: 1.35;
}
.flow-node p, .switch-core p, .branch-card p, .flow-metrics p {
  position: relative;
  z-index: 1;
  margin-top: 8px;
  color: #aebbd6;
  line-height: 1.55;
  display: -webkit-box;
  -webkit-line-clamp: 3;
  -webkit-box-orient: vertical;
  overflow: hidden;
}
.flow-link {
  display: flex;
  flex-direction: column;
  align-items: center;
  justify-content: center;
  gap: 7px;
  color: #64708b;
  font-size: 10px;
  text-align: center;
}
.flow-link i {
  width: 100%;
  height: 2px;
  border-radius: 2px;
  background: linear-gradient(90deg, rgba(105,220,255,.2), rgba(105,220,255,.85), rgba(105,220,255,.2));
  background-size: 200% 100%;
  animation: flow-line 1.8s linear infinite;
}
.flow-link b { font-weight: 600; }
.flow-switch {
  display: flex;
  justify-content: center;
  padding: 12px 0;
}
.switch-core {
  width: min(560px, 100%);
  padding: 13px 16px;
  text-align: center;
  border-color: rgba(255,220,123,.28);
  background: rgba(255,220,123,.055);
}
.switch-core span { color: #ffdc7b; }
.flow-branches {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 10px;
}
.branch-card {
  min-height: 158px;
  padding: 13px;
  opacity: .48;
  transform: scale(.985);
  transition: opacity .2s ease, transform .2s ease, border-color .2s ease, box-shadow .2s ease;
}
.branch-card.active {
  opacity: 1;
  transform: scale(1);
}
.branch-card.exam.active {
  border-color: rgba(255,220,123,.5);
  box-shadow: 0 0 28px rgba(255,220,123,.12);
}
.branch-card.strategy.active {
  border-color: rgba(105,220,255,.5);
  box-shadow: 0 0 28px rgba(105,220,255,.12);
}
.branch-card.interaction.active {
  border-color: rgba(255,111,167,.5);
  box-shadow: 0 0 28px rgba(255,111,167,.12);
}
.branch-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 10px;
}
.branch-head span {
  width: 42px;
  height: 26px;
  display: inline-flex;
  align-items: center;
  justify-content: center;
  border-radius: 999px;
  background: rgba(255,255,255,.08);
}
.branch-card.exam .branch-head span { color: #ffdc7b; }
.branch-card.strategy .branch-head span { color: #69dcff; }
.branch-card.interaction .branch-head span { color: #ff7ab0; }
.branch-chain {
  position: relative;
  z-index: 1;
  margin-top: 13px;
  display: grid;
  grid-template-columns: 1fr 34px 1fr;
  align-items: center;
  gap: 8px;
}
.branch-chain b {
  min-height: 38px;
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 7px;
  border-radius: 10px;
  background: rgba(0,0,0,.18);
  color: #dce6fb;
  font-size: 12px;
  text-align: center;
}
.branch-chain i {
  height: 2px;
  border-radius: 2px;
  background: rgba(255,255,255,.28);
}
.flow-metrics {
  margin-top: 11px;
  display: grid;
  grid-template-columns: minmax(180px, 280px) 1fr;
  gap: 12px;
  padding: 13px;
  border-color: rgba(102,239,172,.22);
  background: rgba(102,239,172,.045);
}
.flow-metrics span { color: #66efac; }
.metric-pills {
  display: flex;
  flex-wrap: wrap;
  gap: 8px;
  align-content: center;
}
.metric-pills span {
  display: inline-flex;
  min-height: 32px;
  align-items: center;
  padding: 6px 10px;
  border-radius: 999px;
  color: #aebbd6;
  background: rgba(255,255,255,.065);
  border: 1px solid rgba(255,255,255,.08);
  letter-spacing: 0;
}
.metric-pills span.positive {
  color: #66efac;
  border-color: rgba(102,239,172,.28);
  background: rgba(102,239,172,.09);
}
.metric-pills span.negative {
  color: #ff8d98;
  border-color: rgba(255,101,115,.28);
  background: rgba(255,101,115,.09);
}
@keyframes flow-line {
  to { background-position: -200% 0; }
}
@keyframes flow-sheen {
  0%, 45% { transform: translateX(-120%); }
  80%, 100% { transform: translateX(120%); }
}
.event-band {
  min-height: 0;
  display: flex;
  flex-direction: column;
  border-top: 1px solid rgba(255,255,255,.075);
}
.event-list {
  padding: 12px 16px 16px;
  display: flex;
  flex-direction: column;
  gap: 8px;
  overflow: auto;
}
.event-item {
  display: grid;
  grid-template-columns: 42px 68px 1fr;
  gap: 10px;
  align-items: baseline;
  padding: 10px 12px;
  border-radius: 12px;
  background: rgba(255,255,255,.045);
  border-left: 3px solid rgba(105,220,255,.55);
}
.event-item.secret { border-left-color: rgba(255,212,107,.6); }
.event-item span { color: #73809a; font-size: 11px; }
.event-item b { color: #69dcff; font-size: 12px; }
.event-item p { color: #b9c5df; line-height: 1.55; }
.inspect-panel {
  display: flex;
  flex-direction: column;
  overflow: auto;
}
.insight-card {
  margin: 14px 16px 0;
}
.insight-card strong {
  display: block;
  color: #ffdc7b;
  font-size: 17px;
  margin-bottom: 8px;
}
.insight-card p {
  color: #c8d2ea;
  line-height: 1.7;
}
.metric-board {
  margin: 14px 16px 0;
  padding: 13px;
  border: 1px solid rgba(255,255,255,.085);
  border-radius: 13px;
  background: rgba(0,0,0,.17);
}
.metric-board article {
  position: relative;
  display: grid;
  grid-template-columns: 1fr auto;
  gap: 12px;
  padding: 10px 0;
  border-top: 1px solid rgba(255,255,255,.06);
  overflow: hidden;
}
.metric-board article:first-of-type { border-top: none; }
.metric-board article::after {
  content: '';
  position: absolute;
  left: 0;
  bottom: 0;
  height: 2px;
  width: var(--w, 0);
}
.metric-board strong {
  display: block;
  color: #f5f8ff;
  font-size: 13px;
}
.metric-board span {
  display: block;
  margin-top: 3px;
  color: #8491ac;
  font-size: 11px;
  line-height: 1.35;
}
.metric-board b {
  color: #ffdc7b;
  font-family: ui-monospace, Menlo, monospace;
  font-size: 13px;
}
.metric-board i {
  grid-column: 1 / -1;
  height: 3px;
  border-radius: 999px;
  background: linear-gradient(90deg,#69dcff,#ffd66b);
}
pre {
  margin: 0;
  max-height: 330px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  color: #c8edff;
  font-family: 'SF Mono', Menlo, monospace;
  font-size: 11.5px;
  line-height: 1.58;
}
.debug-box {
  margin: 12px 16px 0;
  border: 1px solid rgba(255,255,255,.075);
  border-radius: 12px;
  background: rgba(0,0,0,.18);
  overflow: hidden;
}
.debug-box summary {
  cursor: pointer;
  color: #dce6ff;
  padding: 11px 13px;
  background: rgba(255,255,255,.045);
}
.debug-box pre {
  padding: 12px;
  background: rgba(0,0,0,.26);
}
/* ── 评价体系可视化 ── */
.eval-panel { flex: 1; overflow-y: auto; display: flex; flex-direction: column; }
.settle-type-summary {
  margin: 0 16px 10px;
  font-size: 12px;
  line-height: 1.65;
  color: #9aa6c0;
}
.settle-explain {
  display: flex;
  flex-direction: column;
  gap: 10px;
  padding: 0 14px 14px;
}
.settle-block {
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 12px;
  background: rgba(255,255,255,.03);
  padding: 11px 12px;
}
.settle-block.primary {
  border-color: rgba(105,220,255,.28);
  background: linear-gradient(180deg, rgba(105,220,255,.08), rgba(255,255,255,.02));
}
.settle-block label {
  display: block;
  font-size: 10.5px;
  font-weight: 800;
  letter-spacing: .08em;
  color: #69dcff;
  margin-bottom: 4px;
}
.settle-block h3 {
  margin: 0 0 6px;
  font-size: 13.5px;
  color: #f2f5ff;
  line-height: 1.45;
}
.settle-block p {
  margin: 0;
  font-size: 12px;
  line-height: 1.65;
  color: #c3cbe0;
}
.settle-lines {
  margin: 8px 0 0;
  padding-left: 16px;
  color: #d5dcf2;
  font-size: 12px;
  line-height: 1.7;
}
.settle-block details { margin-top: 8px; }
.settle-block summary { cursor: pointer; color: #69dcff; font-size: 11px; }
.inject-lines {
  margin: 6px 0 0;
  padding: 0;
  list-style: none;
  font-size: 12px;
  line-height: 1.65;
  color: #d5dcf2;
}
.inject-lines > li {
  position: relative;
  display: block;
  margin: 3px 0;
  padding: 5px 8px 5px 18px;
  border-radius: 6px;
  background: rgba(105, 220, 255, .045);
  overflow-wrap: anywhere;
}
.inject-lines > li::before {
  content: '';
  position: absolute;
  left: 7px;
  top: 12px;
  width: 4px;
  height: 4px;
  border-radius: 50%;
  background: #69dcff;
  box-shadow: 0 0 5px rgba(105, 220, 255, .7);
}
.think-note {
  margin-top: 6px;
  font-size: 12px;
  color: #c3cbe0;
  line-height: 1.6;
}
.think-note b { color: #ffd66b; margin-right: 6px; }
.said-mono {
  margin: 0 0 6px;
  font-size: 12.5px;
  color: #e8eeff;
  line-height: 1.6;
}
.said-mono b { color: #69dcff; margin-right: 6px; }
.loop-step-head {
  display: flex;
  align-items: center;
  gap: 8px;
  flex-wrap: wrap;
}

/* ── AI 思维链核心：canvas 中心呼吸核心 + 环绕思维链，字幕浮于其上 ── */
.eval-orb-wrap {
  position: relative;
  display: flex; flex-direction: column; align-items: center; justify-content: flex-end;
  padding: 0 0 12px;
  overflow: hidden;
  min-height: 168px;
  flex-shrink: 0;
  border-radius: 14px 14px 0 0;
  background: radial-gradient(ellipse at 50% 48%, #10112e 0%, #080820 40%, #030310 72%, #010008 100%);
}
.ai-canvas {
  position: absolute;
  inset: 0;
  width: 100%; height: 100%;
  z-index: 1;
  pointer-events: none;
}
.eval-blob-caption {
  text-align: center; margin-top: 6px; position: relative; z-index: 2;
  text-shadow: 0 2px 12px rgba(0,0,0,.85), 0 0 20px rgba(30,80,180,.5);
}
.eval-blob-caption strong { display: block; font-size: 15px; }
.eval-blob-caption span { font-size: 12px; color: #9aa6c0; }
.eval-blob-caption i { font-style: normal; color: #ffd060; margin-left: 6px; }
.eval-block { padding: 12px 16px; border-top: 1px solid rgba(255,255,255,.05); }
.eval-label { display: block; font-size: 11px; font-weight: 800; color: #69dcff; letter-spacing: .08em; margin-bottom: 9px; }
.eval-paths { display: flex; flex-direction: column; gap: 7px; }
.ep-item { display: flex; align-items: center; gap: 7px; font-size: 12px; color: #c3cbe0; }
.ep-item b { color: #fff; min-width: 34px; }
.ep-item em { font-style: normal; color: #6b7690; font-size: 10.5px; }
.ep-dot { width: 8px; height: 8px; border-radius: 50%; }
.ep-dot.exam { background: #ffd66b; } .ep-dot.strategy { background: #69dcff; } .ep-dot.interaction { background: #ff6fa7; }
.eval-formula { display: flex; flex-direction: column; gap: 6px; }
.ef-row { display: grid; grid-template-columns: 62px 60px 1fr 42px; align-items: center; gap: 8px; font-size: 11px; }
.ef-name { color: #c3cbe0; white-space: nowrap; }
.ef-calc { color: #8a93ad; font-variant-numeric: tabular-nums; }
.ef-bar { height: 6px; border-radius: 999px; background: rgba(255,255,255,.06); overflow: hidden; }
.ef-bar i { display: block; height: 100%; border-radius: 999px; background: linear-gradient(90deg,#3a7bd5,#69dcff); }
.ef-row.neg .ef-bar i { background: linear-gradient(90deg,#a8281c,#ff5f52); }
.ef-contrib { text-align: right; font-weight: 800; color: #8be28b; font-variant-numeric: tabular-nums; }
.ef-row.neg .ef-contrib { color: #ff5f52; }
.eval-hint { margin: 9px 0 0; font-size: 10.5px; line-height: 1.6; color: #6b7690; }
.eval-empty-sm { font-size: 11px; color: #6b7690; padding: 4px 0; }
/* ── 排名大白话解释 ── */
.rank-explain { display: flex; flex-direction: column; gap: 8px; }
.rk-lead { margin: 0; font-size: 13px; color: #e6ecff; }
.rk-lead b { font-weight: 800; }
.rk-why { margin: 0; font-size: 12px; line-height: 1.8; color: #c3cbe0; }
.rk-why b { color: #8be28b; font-weight: 700; }
.rk-danger { color: #ff5f52 !important; }
.rk-rule {
  font-size: 11.5px; line-height: 1.75; color: #9aa6c0;
  padding: 9px 11px; border-radius: 9px;
  background: rgba(105,220,255,.05);
  border: 1px solid rgba(105,220,255,.12);
}
.rk-rule span { color: #69dcff; font-weight: 700; }
.rk-rule b { color: #cdd6ee; }
.rk-fold-sum { margin-top: 10px; font-size: 11px; color: #69dcff; cursor: pointer; user-select: none; list-style: none; }
.rk-fold-sum::-webkit-details-marker { display: none; }
/* ── 全链路因果卡：动作→路线→裁决→结算→指标，竖向链路 ── */
.chain-card {
  border: 1px solid rgba(255,255,255,.07);
  border-left: 2px solid var(--cc, #69dcff);
  border-radius: 10px;
  background: rgba(255,255,255,.02);
  padding: 9px 11px;
  margin-bottom: 9px;
}
.chain-node {
  position: relative;
  display: flex;
  gap: 9px;
  padding: 4px 0 4px 4px;
}
/* 竖向链路线 */
.chain-node::before {
  content: '';
  position: absolute;
  left: 7.5px; top: 0; bottom: 0;
  width: 1px;
  background: rgba(255,255,255,.1);
}
.chain-node:first-child::before { top: 12px; }
.chain-node:last-child::before { bottom: auto; height: 12px; }
.cn-dot {
  position: relative; z-index: 1;
  flex-shrink: 0;
  width: 8px; height: 8px;
  margin-top: 4px;
  border-radius: 50%;
  background: var(--cc, #69dcff);
  box-shadow: 0 0 6px var(--cc, #69dcff);
}
.cn-route .cn-dot { background: #8a93ad; box-shadow: none; }
.cn-judge .cn-dot { background: #8be28b; box-shadow: 0 0 5px rgba(139,226,139,.6); }
.cn-result .cn-dot { background: #ffd66b; box-shadow: 0 0 6px rgba(255,214,107,.7); }
.cn-result.bad .cn-dot { background: #ff5f52; box-shadow: 0 0 6px rgba(255,95,82,.7); }
.chain-node b { font-size: 12px; color: #fff; margin-right: 6px; }
.chain-node span { font-size: 11.5px; color: #c3cbe0; }
.chain-node span em { font-style: normal; color: #ffd66b; }
.cn-routes { display: flex; gap: 5px; flex-wrap: wrap; }
.rt {
  font-size: 9.5px; font-weight: 700;
  padding: 2px 8px; border-radius: 999px;
  background: rgba(255,255,255,.04);
  color: #5b6478;
  border: 1px solid transparent;
}
.rt.on.rt-exam { background: rgba(255,214,107,.14); color: #ffd66b; border-color: rgba(255,214,107,.4); }
.rt.on.rt-strategy { background: rgba(105,220,255,.14); color: #69dcff; border-color: rgba(105,220,255,.4); }
.rt.on.rt-interaction { background: rgba(255,111,167,.14); color: #ff6fa7; border-color: rgba(255,111,167,.4); }
.cn-judge p { margin: 0; font-size: 11px; line-height: 1.65; color: #9fb0d0; word-break: break-word; }
.cn-outcome { color: #ffd66b !important; }
.cn-result.bad .cn-outcome { color: #ff5f52 !important; }
.cn-result.flat .cn-outcome { color: #9aa6c0 !important; }
.cn-metrics { display: inline-flex; flex-wrap: wrap; gap: 5px; }
.cn-metrics em {
  font-style: normal; font-size: 10.5px; font-weight: 700;
  padding: 1px 8px; border-radius: 999px;
  background: rgba(139,226,139,.12); color: #8be28b;
}
.cn-metrics em.neg { background: rgba(255,95,82,.12); color: #ff5f52; }
.cn-nochange { color: #6b7690 !important; font-size: 10.5px !important; }
.eval-agent-chips { display: flex; gap: 6px; margin-bottom: 10px; }
.ec-chip {
  font-size: 11px; font-weight: 700;
  padding: 4px 12px; border-radius: 999px;
  border: 1px solid rgba(255,255,255,.1);
  background: transparent; color: #8a93ad; cursor: pointer;
  transition: all .15s ease;
}
.ec-chip.on {
  border-color: color-mix(in srgb, var(--cc, #69dcff) 60%, transparent);
  background: color-mix(in srgb, var(--cc, #69dcff) 12%, transparent);
  color: var(--cc, #69dcff);
}
.cn-think .cn-dot { background: #c48bff; box-shadow: 0 0 5px rgba(196,139,255,.6); }
.cn-think-text { margin: 0; font-size: 11px; line-height: 1.65; color: #d9c8ff; white-space: pre-line; word-break: break-word; }
.cn-pressure .cn-dot { background: #ffa94d; box-shadow: 0 0 5px rgba(255,169,77,.6); }
.cn-ptitle { display: block; font-size: 10.5px; font-weight: 800; color: #ffa94d; margin-bottom: 3px; }
.cn-pressure.hot .cn-ptitle { color: #ff5f52; }
.cn-pgrid { display: flex; flex-wrap: wrap; gap: 4px 10px; }
.cn-pgrid em {
  font-style: normal; font-size: 10px; color: #9fb0d0;
  font-variant-numeric: tabular-nums;
}
.cn-pgrid em.warn { color: #ff5f52; font-weight: 700; }
.eval-fold summary { cursor: pointer; user-select: none; }
.eval-fold summary::marker { color: #69dcff; }
.eval-fold .eval-paths { margin: 10px 0 12px; }
.oracle-presets { display: flex; flex-wrap: wrap; gap: 6px; padding: 12px 16px 0; }
.preset-btn { font-size: 11px; padding: 5px 10px; border-radius: 999px; border: 1px solid rgba(255,208,96,.25); background: rgba(255,208,96,.06); color: #ffd66b; cursor: pointer; transition: all .15s ease; }
.preset-btn:hover { background: rgba(255,208,96,.14); border-color: rgba(255,208,96,.5); }

.oracle-panel { overflow: visible; }
.oracle-form {
  display: grid;
  grid-template-columns: 1fr;
  gap: 9px;
  padding: 14px 16px 16px;
}
.oracle-form select, .oracle-form input {
  width: 100%;
  box-sizing: border-box;
  border: 1px solid rgba(255,255,255,.12);
  border-radius: 9px;
  background: rgba(0,0,0,.2);
  color: #edf3ff;
  padding: 9px 11px;
  outline: none;
}
.oracle-form select:focus, .oracle-form input:focus {
  border-color: rgba(105,220,255,.5);
}
.oracle-form button {
  background: linear-gradient(135deg,#ffd66b,#ffb34d);
  color: #111018;
  font-weight: 800;
}
@media (max-width: 1180px) {
  .console-body { grid-template-columns: 300px minmax(420px, 1fr); }
  .right-rail { display: none; }
  .decision-grid { grid-template-columns: 1fr; }
  .turn-review-head { align-items: flex-start; flex-direction: column; }
  .flow-row { grid-template-columns: 1fr; }
  .flow-link {
    min-height: 30px;
    flex-direction: row;
  }
  .flow-link i {
    width: 44px;
    height: 2px;
  }
  .flow-branches { grid-template-columns: 1fr; }
  .branch-card { min-height: 132px; }
  .flow-metrics { grid-template-columns: 1fr; }
}
@media (max-width: 900px) {
  .console-header { height: auto; align-items: flex-start; flex-direction: column; padding: 16px; }
  .header-controls { margin-left: 0; flex-wrap: wrap; }
  .console-body { grid-template-columns: 1fr; overflow: auto; }
  .left-rail, .center-stage { overflow: visible; }
  .stage-hero { grid-template-columns: 1fr; }
  .turn-review-actions { width: 100%; }
  .turn-metrics { grid-template-columns: repeat(3, 1fr); }
}

/* 2026 AI Observatory refresh. This block intentionally overrides the older
   neon console treatment while keeping the existing data bindings intact. */
.console-root {
  background:
    radial-gradient(900px 540px at 50% -22%, rgba(102, 126, 234, .22), transparent 58%),
    radial-gradient(680px 420px at 105% 12%, rgba(20, 184, 166, .13), transparent 62%),
    linear-gradient(180deg, #0d111a 0%, #0a0d14 48%, #080a10 100%);
  color: #f5f7fb;
  font-size: 13px;
}
.console-root::before {
  content: '';
  position: fixed;
  inset: 0;
  pointer-events: none;
  background-image:
    linear-gradient(rgba(255,255,255,.035) 1px, transparent 1px),
    linear-gradient(90deg, rgba(255,255,255,.025) 1px, transparent 1px);
  background-size: 56px 56px;
  mask-image: linear-gradient(to bottom, rgba(0,0,0,.62), transparent 72%);
}
.console-header {
  height: 72px;
  padding: 0 28px;
  border-bottom: 1px solid rgba(255,255,255,.08);
  background: rgba(10, 13, 20, .72);
  backdrop-filter: blur(22px);
}.brand-kicker, .section-kicker, .panel-head span, .turn-review span, .battle-readout > span {
  color: #8bd3ff;
  letter-spacing: 1.8px;
  font-weight: 700;
}
.brand h1 {
  font-size: 21px;
  font-weight: 720;
}
.live-strip {
  border-color: rgba(255,255,255,.08);
  background: rgba(255,255,255,.045);
  box-shadow: 0 1px 0 rgba(255,255,255,.04) inset;
}
.header-controls button,
.oracle-form button,
.header-controls .primary {
  background: #e9fff6;
  color: #07120f;
}
.header-controls .soft {
  color: #f6d56f;
  border-color: rgba(246, 213, 111, .26);
}
.console-body {
  grid-template-columns: 304px minmax(680px, 1fr) 390px;
  gap: 14px;
  padding: 14px;
  overflow: auto;
}
.left-rail, .center-stage, .right-rail {
  gap: 12px;
  overflow: auto;
}.panel, .stage-panel {
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 18px;
  background:
    linear-gradient(180deg, rgba(255,255,255,.055), rgba(255,255,255,.025)),
    rgba(14, 18, 28, .72);
  box-shadow:
    0 22px 70px rgba(0,0,0,.26),
    0 1px 0 rgba(255,255,255,.05) inset;
  backdrop-filter: blur(18px);
}
.panel-head {
  padding: 16px 17px;
  border-bottom-color: rgba(255,255,255,.065);
}
.panel-head h2 {
  font-size: 16px;
  font-weight: 680;
}
.panel-head em {
  color: #8d98ad;
}
.scoreboard-panel,
.inspect-panel {
  flex: none;
}
.rank-card {
  display: block;
  margin: 10px 12px;
  padding: 13px;
  border-radius: 16px;
  border-color: rgba(255,255,255,.075);
  background: rgba(255,255,255,.035);
}
.rank-card:hover,
.rank-card.selected {
  transform: translateY(-1px);
  border-color: color-mix(in srgb, var(--agent-color) 42%, rgba(255,255,255,.16));
  background: color-mix(in srgb, var(--agent-color) 9%, rgba(255,255,255,.04));
}
.rank-card.leader {
  background:
    linear-gradient(135deg, rgba(255, 214, 107, .11), rgba(255,255,255,.035)),
    rgba(255,255,255,.02);
}
.rank-topline {
  display: grid;
  grid-template-columns: 36px 1fr auto;
  gap: 11px;
  align-items: center;
}
.rank-no {
  width: 34px;
  height: 34px;
  border-radius: 12px;
  font-weight: 760;
}
.rank-topline strong {
  color: var(--agent-color);
  font-size: 15px;
}
.rank-topline p {
  margin-top: 2px;
  color: #8d98ad;
  font-size: 12px;
}
.rank-topline b {
  color: #fff;
  font-size: 30px;
  line-height: 1;
  font-family: ui-monospace, SFMono-Regular, Menlo, monospace;
  letter-spacing: 0;
}
.source-track,
.readout-track {
  height: 7px;
  background: rgba(255,255,255,.075);
}
.source-legend {
  justify-content: space-between;
  gap: 6px;
  color: #9aa6bb;
}
.exam { background: #f6cf66; }
.strategy { background: #64d4ff; }
.interaction { background: #f06aad; }
.battle-readout {
  display: block;
  margin: 0;
  padding: 17px;
}
.battle-readout strong {
  font-size: 18px;
  margin: 8px 0 7px;
}
.battle-readout p,
.readout-bars p {
  color: #aeb8c8;
}
.readout-bars {
  margin-top: 14px;
}
.agent-panel {
  max-height: none;
}
.agent-card {
  padding: 12px 16px;
}
.agent-card:hover,
.agent-card.selected {
  background: rgba(255,255,255,.055);
}
.stage-panel {
  min-height: 100%;
  display: flex;
  flex-direction: column;
  overflow: visible;
}
.stage-hero {
  grid-template-columns: 1fr minmax(260px, auto);
  padding: 22px 24px 18px;
  border-bottom: none;
}
.stage-hero h2 {
  font-size: clamp(26px, 2.7vw, 42px);
  font-weight: 760;
  letter-spacing: 0;
  line-height: 1.08;
}
.stage-hero p {
  max-width: 860px;
  color: #aab5c8;
}
.turn-metrics {
  grid-template-columns: repeat(3, 92px);
}
.turn-metrics div {
  border-color: rgba(255,255,255,.075);
  background: rgba(255,255,255,.04);
}
.turn-review {
  display: grid;
  grid-template-columns: minmax(160px, 1fr) auto;
  gap: 10px 14px;
  margin: 0 24px 14px;
  padding: 14px;
  border-radius: 16px;
  border: 1px solid rgba(255,255,255,.075);
  background: rgba(255,255,255,.035);
}
.turn-review strong {
  display: block;
  margin-top: 3px;
  color: #fff;
  font-size: 15px;
}
.turn-review-actions {
  justify-content: flex-end;
}
.turn-review-actions button,
.turn-chip {
  border-radius: 11px;
  background: rgba(255,255,255,.045);
}
.turn-chip-row {
  grid-column: 1 / -1;
  max-height: 86px;
  overflow: auto;
}
.turn-chip.active {
  color: #0e141f;
  border-color: transparent;
  background: #dff8ff;
  box-shadow: none;
}
.decision-strip {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  padding: 0 24px 24px;
}
.decision-card {
  min-height: 188px;
  border-radius: 16px;
  background: rgba(255,255,255,.035);
  border-color: rgba(255,255,255,.075);
}
.decision-card:hover,
.decision-card.active {
  border-color: rgba(139,211,255,.44);
  background: rgba(139,211,255,.075);
}
.decision-card h3 {
  color: #f6cf66;
}
.decision-text {
  -webkit-line-clamp: 3;
}
.right-rail {
  overflow: auto;
}.inspect-panel, .event-band {
  flex: none;
}.metric-board, .insight-card, .debug-box {
  border-color: rgba(255,255,255,.075);
  background: rgba(255,255,255,.035);
}label {
  color: #8bd3ff;
}
.metric-board article {
  grid-template-columns: 1fr auto;
}
.metric-board i {
  background: linear-gradient(90deg, #64d4ff, #f6cf66);
}
.metric-pills span {
  border-radius: 999px;
  background: rgba(255,255,255,.06);
}
.event-band {
  min-height: 260px;
}
.event-list {
  max-height: 330px;
}
.event-item {
  grid-template-columns: 38px 64px 1fr;
  border-left: 0;
  border: 1px solid rgba(255,255,255,.06);
  background: rgba(255,255,255,.035);
}
.event-item b {
  color: #8bd3ff;
}
.oracle-form select,
.oracle-form input {
  background: rgba(255,255,255,.04);
  border-color: rgba(255,255,255,.09);
}
.oracle-form button {
  background: #f6cf66;
  color: #111827;
}
@media (max-width: 1380px) {
  .console-body {
    grid-template-columns: 286px minmax(620px, 1fr) 350px;
  }
}
@media (max-width: 1500px) {
  .console-body { grid-template-columns: 260px minmax(0, 1fr); align-items:start; }
  .left-rail { grid-column:1; grid-row:1 / span 2; position:sticky; top:0; max-height:100%; }
  .center-stage { grid-column:2; grid-row:1; overflow:visible; }
  .right-rail { grid-column:2; grid-row:2; display:flex; overflow:visible; }
  .eval-panel { overflow:visible; }
}
@media (max-width: 1180px) {
  .console-body {
    grid-template-columns: minmax(260px, 310px) minmax(560px, 1fr);
  }
  .right-rail { display:flex; }
  .turn-review {
    grid-template-columns: 1fr;
  }
  .turn-review-actions {
    justify-content: flex-start;
  }.decision-strip {
    grid-template-columns: 1fr;
  }
}
@media (max-width: 900px) {
  .console-body {
    grid-template-columns: 1fr;
  }
  .left-rail { display:none; }
  .center-stage, .right-rail { grid-column:1; width:100%; }
  .center-stage { grid-row:1; }
  .right-rail { grid-row:2; }
  .stage-hero {
    grid-template-columns: 1fr;
  }
  .decision-strip {
    padding: 0 14px 16px;
  }
}

/* Iteration: presentation polish + notebook fit. */
.center-stage {
  min-height: 0;
  overflow: auto;
}
.stage-panel {
  min-height: min-content;
  overflow: visible;
}
.stage-hero {
  padding: 18px 24px 14px;
}
.stage-hero h2 {
  font-size: clamp(22px, 1.9vw, 31px);
  font-weight: 720;
  letter-spacing: 0;
}
.brand h1,
.rank-topline b {
  letter-spacing: 0;
}
.battle-readout strong {
  font-size: 16px;
  line-height: 1.35;
}
.agent-card {
  display: block;
}
.agent-card-main {
  display: flex;
  align-items: center;
  gap: 10px;
}
.agent-card-main > div:nth-child(2) {
  min-width: 0;
  flex: 1;
}
.agent-card-main > span {
  margin-left: auto;
  color: #aeb8d3;
  font-size: 12px;
}
.agent-resources {
  margin-top: 10px;
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 6px;
}
.agent-resources small {
  min-width: 0;
  padding: 5px 6px;
  border-radius: 8px;
  color: #b8c4d8;
  background: rgba(255,255,255,.045);
  font-size: 11px;
  line-height: 1.2;
  white-space: nowrap;
  overflow: hidden;
  text-overflow: ellipsis;
}
.agent-resources b {
  margin-right: 3px;
  color: #8bd3ff;
  font-weight: 650;
}
@media (max-width: 1380px) {
  .stage-hero {
    grid-template-columns: 1fr;
  }
  .turn-metrics {
    grid-template-columns: repeat(3, minmax(86px, 1fr));
  }
}
@media (max-width: 1180px) {
}
@media (max-width: 1380px) {
}
@media (prefers-reduced-motion: reduce) {
}
.metric-highlight-row { display:flex; flex-wrap:wrap; gap:6px; }
.metric-highlight-row span { border:1px solid rgba(139,211,255,.16); border-radius:6px; padding:4px 7px; background:rgba(255,255,255,.025); }
.metric-highlight-row b { color:#f5f7fb; margin-left:3px; }
.provenance-flow { display:flex; flex-direction:column; gap:0; margin-top:14px; }
.prov-node { border:1px solid rgba(139,211,255,.18); border-radius:8px; background:rgba(9,15,25,.68); overflow:hidden; }
.prov-node[open] { border-color:rgba(112,225,255,.5); box-shadow:0 0 24px rgba(76,194,255,.08); }
.prov-node summary { cursor:pointer; list-style:none; padding:13px 14px; }
.prov-node summary::-webkit-details-marker { display:none; }
.prov-node summary span { display:block; color:#76dfff; font-size:10px; letter-spacing:1.2px; text-transform:uppercase; }
.prov-node summary b { display:block; color:#f4f7fb; font-size:14px; margin-top:5px; line-height:1.35; }
.prov-node summary p { color:#929eb1; font-size:12px; line-height:1.5; margin:5px 0 0; }
.prov-node pre { max-height:260px; overflow:auto; margin:0; padding:12px 14px; border-top:1px solid rgba(255,255,255,.07); background:#080d15; color:#b9c9dd; font-size:10px; white-space:pre-wrap; word-break:break-word; }
.prov-activity { border-color:rgba(132,157,255,.34); background:rgba(21,27,49,.45); }
.prov-observation { border-color:rgba(80,225,177,.32); }
.prov-settlement { border-color:rgba(255,206,96,.35); background:rgba(36,29,13,.35); }
.prov-director { border-color:rgba(190,128,255,.3); }
.prov-edge { height:34px; position:relative; display:flex; justify-content:center; align-items:center; color:#718096; font-size:9px; letter-spacing:.7px; }
.prov-edge:before { content:""; position:absolute; top:0; bottom:0; width:1px; background:rgba(105,220,255,.28); }
.prov-edge i { position:absolute; width:5px; height:5px; border-radius:50%; background:#75e3ff; box-shadow:0 0 9px #75e3ff; animation:prov-flow 1.5s linear infinite; }
.prov-edge span { position:relative; margin-left:62px; background:#111923; padding:2px 5px; }
.authority-legend { margin-top:16px; padding-top:12px; border-top:1px solid rgba(255,255,255,.08); display:grid; gap:7px; }
.authority-legend label { color:#7f8da2; font-size:10px; letter-spacing:1px; }
.authority-legend span { display:flex; flex-direction:column; color:#7f8da2; font-size:10px; }
.authority-legend b { color:#dbe6f4; font-size:11px; }
@keyframes prov-flow { from { transform:translateY(-13px); opacity:.2; } 50% { opacity:1; } to { transform:translateY(13px); opacity:.2; } }
@media (prefers-reduced-motion: reduce) { .prov-edge i { animation:none; } }
</style>
