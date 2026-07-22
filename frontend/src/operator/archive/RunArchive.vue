<template>
  <div class="ra-root">
    <!-- 左栏：对局列表 -->
    <aside class="ra-list">
      <div class="ra-list-head">
        <div class="ra-list-title">
          <span>EVALUATION ARCHIVE</span>
          <h2>{{ tr('评测档案', 'Evaluation archive') }}</h2>
          <small>{{ runs.length }} {{ tr('条可审计记录', 'auditable records') }}</small>
        </div>
        <button class="ra-refresh" :title="tr('刷新评测档案', 'Refresh archive')" @click="loadRuns">↻</button>
      </div>
      <div v-if="loadingRuns" class="ra-empty">{{ tr('载入对局列表…', 'Loading evaluations…') }}</div>
      <div v-else-if="!runs.length" class="ra-empty">{{ tr('还没有已存档的对局。跑完一局（终局或重置）后会自动落盘到这里。', 'No archived evaluations yet. A completed or reset run will be saved here automatically.') }}</div>
      <article
        v-for="run in runs"
        :key="run.run_id"
        class="ra-run-card"
        :class="{ active: run.run_id === activeRunId }"
        @click="selectRun(run.run_id)"
      >
        <div class="ra-run-top">
          <b>{{ run.scenario || run.run_id }}</b>
          <em v-if="run.finalized" class="ra-badge done">{{ tr('已完成', 'Completed') }}</em>
          <em v-else class="ra-badge">{{ tr('未完成', 'Incomplete') }}</em>
        </div>
        <p class="ra-run-time">{{ formatTime(run.created_at) }} · {{ run.run_id }}</p>
        <p v-if="run.winner" class="ra-run-winner"><span>{{ tr('领先', 'LEAD') }}</span>{{ agentNameOf(run, run.winner) }}</p>
        <small class="ra-run-models">{{ modelsLine(run) }}</small>
      </article>
    </aside>

    <!-- 主区：单局回顾（实时对局同款） -->
    <section class="ra-main">
      <div v-if="!activeRunId" class="ra-empty big">{{ tr('从左侧选择一条评测记录开始回顾。', 'Select an evaluation on the left to begin the review.') }}</div>
      <div v-else-if="loadingTimeline" class="ra-empty big">{{ tr('载入评测数据…', 'Loading evaluation data…') }}</div>

      <template v-else-if="timeline && timeline.available">
        <!-- 局头 -->
        <header class="ra-head">
          <div>
            <span class="ra-kicker">EVALUATION REVIEW</span>
            <h2>{{ timeline.summary?.scenario || activeRunId }}</h2>
            <div class="ra-head-meta">
              <span>{{ formatTime(timeline.summary?.created_at) }}</span>
              <span>{{ ticks.length }} {{ tr('个评测周期', 'evaluation cycles') }}</span>
              <span>{{ agentsLine }}</span>
            </div>
          </div>
          <div v-if="winnerName" class="ra-winner-pill"><small>{{ tr('领先策略', 'Leading strategy') }}</small><strong>{{ winnerName }}</strong></div>
          <div v-else class="ra-winner-pill muted"><small>{{ tr('评测状态', 'Evaluation status') }}</small><strong>{{ tr('尚未完成', 'In progress') }}</strong></div>
        </header>

        <!-- 专业评测结论 -->
        <div v-if="finalAttribution.length" class="ra-final">
          <div class="ra-section-head">
            <span class="ra-sec-title">{{ tr('评测结论与指标归因', 'Evaluation findings and attribution') }}</span>
            <small>{{ tr('基于场景结算记录生成', 'Generated from scenario settlement records') }}</small>
          </div>
          <div class="ra-final-grid">
            <div v-for="item in finalAttribution" :key="item.agent_id" class="ra-vr-card" :class="{ champ: item.rank === 1 }">
              <span class="ra-rank">{{ item.rank === 1 ? 'LEAD' : `#${item.rank}` }}</span>
              <strong>{{ item.headline }}</strong>
              <p class="vr-plus" v-for="s in item.strengths" :key="'s'+s">＋ {{ s }}</p>
              <p class="vr-weak" v-for="w in item.weaknesses" :key="'w'+w">－ {{ w }}</p>
              <p class="vr-fatal" v-if="item.fatal">✖ {{ item.fatal }}</p>
              <small>{{ tr('评测结果以场景结算记录和专业指标规则为准', 'Results follow the scenario ledger and professional metric rules.') }}</small>
            </div>
          </div>
        </div>

        <!-- 回合导航 -->
        <div class="ra-nav">
          <div class="ra-nav-info">
            <span>{{ tr('评测周期', 'EVALUATION CYCLE') }}</span>
            <strong>{{ tr('正在查看', 'Reviewing') }} T{{ activeTick }}</strong>
          </div>
          <div class="ra-nav-btns">
            <button :disabled="tickIndex <= 0" @click="stepTick(-1)">{{ tr('上一回合', 'Previous') }}</button>
            <button :disabled="tickIndex >= ticks.length - 1" @click="stepTick(1)">{{ tr('下一回合', 'Next') }}</button>
          </div>
          <div class="ra-chip-row">
            <button
              v-for="t in ticks" :key="t.tick"
              class="ra-chip" :class="{ active: t.tick === activeTick }"
              @click="activeTick = t.tick"
            >T{{ t.tick }}</button>
          </div>
        </div>

        <div class="ra-trace">
          <div class="ra-section-head">
            <span class="ra-sec-title">{{ tr('本周期证据链', 'Evidence chain for this cycle') }}</span>
            <small>{{ tr('证据 → 动作 → 事件 → 结算', 'Evidence → action → event → settlement') }}</small>
          </div>
          <div v-if="!traceNodes.length" class="ra-empty">{{ tr('该回合是旧版存档，或尚未写入 OS 2.0 契约记录。', 'This is a legacy cycle or it has no OS 2.0 contract records.') }}</div>
          <div v-else class="trace-flow">
            <template v-for="(node, index) in traceNodes" :key="node.id">
              <details class="trace-node" :class="`trace-${node.kind}`">
                <summary><span>{{ node.label }}</span><b>{{ node.title }}</b><p>{{ node.summary }}</p></summary>
                <pre>{{ pretty(node.raw) }}</pre>
              </details>
              <i v-if="index < traceNodes.length - 1" class="trace-edge"></i>
            </template>
          </div>
        </div>

        <!-- 本回合全过程（按场景结算类型动态套用 OS 链路模型） -->
        <div class="ra-process">
          <div class="ra-section-head">
            <span class="ra-sec-title">{{ tr('策略决策全过程', 'Complete strategy decision process') }}</span>
            <small>{{ processChainProfile.label }} · {{ turnProcess.length }} {{ tr('个模型', 'models') }}</small>
          </div>
          <div v-if="!turnProcess.length" class="ra-empty">{{ tr('本回合没有模型决策记录（可能是开场或收尾帧）。', 'No model decision was recorded in this cycle.') }}</div>
          <article
            v-for="p in turnProcess" :key="p.key"
            class="process-card" :style="{ '--pc-color': p.color }"
          >
            <header class="pc-head">
              <b class="pc-name">{{ p.name }}</b>
              <span class="pc-action">{{ p.action }}<i v-if="p.target"> → {{ p.target }}</i></span>
              <span v-if="p.outcome" class="pc-outcome" :class="p.outcomeClass">{{ p.outcome }}</span>
              <small class="pc-meta">{{ p.meta }}</small>
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
                    <p>{{ p.perceive }}</p>
                    <details v-if="p.perceptionRaw"><summary>{{ tr('完整输入', 'Full input') }}</summary><pre>{{ p.perceptionRaw }}</pre></details>
                  </template>
                  <template v-else-if="step.id === 'loop'">
                    <p v-if="p.loop.summary" class="think-summary">{{ p.loop.summary }}</p>
                    <ol v-if="p.loop.steps.length" class="loop-steps">
                      <li v-for="hs in p.loop.steps" :key="hs.key">
                        <b>{{ hs.label }}</b>
                        <em v-if="hs.status" :class="['loop-st', hs.status]">{{ hs.status }}</em>
                        <span v-if="hs.duration_ms">{{ hs.duration_ms }}ms</span>
                        <p v-if="hs.text">{{ hs.text }}</p>
                      </li>
                    </ol>
                    <p v-else class="pc-muted">{{ tr('本回合没有记录到 Agent Loop / 工具取证步骤。', 'No agent-loop or tool-evidence steps were recorded.') }}</p>
                    <details v-if="p.loop.raw"><summary>{{ tr('Harness 轨迹原文', 'Raw harness trace') }}</summary><pre>{{ pretty(p.loop.raw) }}</pre></details>
                  </template>
                  <template v-else-if="step.id === 'think'">
                    <p v-if="p.think.summary" class="think-summary">{{ p.think.summary }}</p>
                    <details v-if="p.think.chain"><summary>{{ tr('展开完整思维链', 'Show full reasoning trace') }}</summary><pre>{{ p.think.chain }}</pre></details>
                    <p v-if="!p.think.summary && !p.think.chain" class="pc-muted">{{ tr('该模型此局未捕获思维链（旧对局，或模型未暴露思考过程）。', 'No reasoning trace was captured for this model.') }}</p>
                  </template>
                  <template v-else-if="step.id === 'said'">
                    <p>{{ p.said || '（没有可展示的输出文本）' }}</p>
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
                  </template>
                  <template v-else-if="step.id === 'metrics'">
                    <div v-if="p.metrics.length" class="ra-metric-pills">
                      <span v-for="m in p.metrics" :key="m" :class="{ neg: m.includes('-') }">{{ m }}</span>
                    </div>
                    <p v-else class="pc-muted">{{ tr('本步没有引起指标变化', 'No metric changes in this step') }}</p>
                    <p v-if="p.degraded" class="pc-muted">{{ tr('（本回合为超时兜底动作，非主动选择）', '(Timeout fallback; not an intentional choice)') }}</p>
                  </template>
                </div>
              </li>
            </ol>
          </article>
        </div>
      </template>

      <div v-else class="ra-empty big">
        {{ tr('本局没有留存演绎档案（可能是进程被强制中断，未走正常终局/重置流程）。', 'This run has no presentation archive, likely because it ended unexpectedly.') }}<br />
        {{ tr('仅有账本与诊断数据，可在服务器查看原始文件。', 'Ledger and diagnostic files remain available on the server.') }} runs/{{ activeRunId }}/
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { apiGet } from '../api.js'
import { locale, tr } from '../../core/i18n.js'
import {
  processChainTypeFromSchema,
  resolveProcessChainProfile,
  summarizeHarnessLoop,
} from '../processChainProfiles.js'

const props = defineProps({ runId: { type: String, default: null } })

const runs = ref([])
const loadingRuns = ref(false)
const activeRunId = ref(null)
const timeline = ref(null)
const loadingTimeline = ref(false)
const activeTick = ref(null)

const FALLBACK_COLORS = ['#6b7cff', '#d6a23a', '#3ac48a', '#d65a5a']
// 旧存档里可能还有英文字段名/动作 id，回顾时统一翻译
const FIELD_ZH = {
  intent: '行动意图', target_object_id: '目标对象', target_agent_id: '目标角色',
  action_id: '动作类型', action_name: '动作名称', plan: '行动计划',
  resource_commitment: '资源投入', risk_control: '风险控制',
  expected_effect: '预期效果', text: '正文',
}
const actionLabels = computed(() => timeline.value?.terminology?.action_labels || {})

const ticks = computed(() => timeline.value?.ticks || [])
const tickIndex = computed(() => ticks.value.findIndex(t => t.tick === activeTick.value))
const currentTick = computed(() => ticks.value.find(t => t.tick === activeTick.value) || null)
const traceNodes = computed(() => {
  const os2 = currentTick.value?.os2 || {}
  const nodes = []
  for (const item of os2.world_actions || []) nodes.push({ id: item.action_id, kind: 'action', label: 'WorldAction', title: actionLabels.value[item.action_type] || item.action_type, summary: item.status || '已提交世界', raw: item })
  for (const item of os2.external_observations || []) nodes.push({ id: item.observation_id, kind: 'observation', label: 'ExternalObservation', title: `${item.observation_type} · ${item.subject_id}`, summary: `${item.provider_id} · ${item.verification_status}`, raw: item })
  for (const item of os2.world_events || []) nodes.push({ id: item.event_id, kind: 'event', label: 'WorldEvent', title: item.public_summary || item.event_type, summary: item.event_type, raw: item })
  for (const item of os2.settlements || []) nodes.push({ id: item.settlement_id, kind: 'settlement', label: authorityLabel(item.authority?.mode), title: item.explanation || item.outcome, summary: item.authority?.rule_version || item.evaluator_id, raw: item })
  if (os2.director_plan) nodes.push({ id: os2.director_plan.plan_id || 'director', kind: 'director', label: 'DirectorPlan', title: '可验证演绎计划', summary: `${(os2.director_plan.commands || []).length} 条渲染命令`, raw: os2.director_plan })
  return nodes
})
function authorityLabel(mode) {
  return { simulation: '模拟世界规则', external_reality: '外部真实数据', deterministic_verifier: '确定性验证器', hybrid: '真实数据 + 确定性规则' }[mode] || '场景结算'
}

const agentNameMap = computed(() => {
  const map = {}
  for (const a of timeline.value?.summary?.agents || []) map[a.id] = a.name || a.id
  // 快照里的名字优先（带中文名）
  for (const t of ticks.value.slice(0, 1)) {
    for (const a of t.snapshot?.agents || []) map[a.agent_id] = a.name || map[a.agent_id]
  }
  return map
})
const agentColorMap = computed(() => {
  const map = {}
  let i = 0
  for (const t of ticks.value.slice(0, 1)) {
    for (const a of t.snapshot?.agents || []) map[a.agent_id] = a.color || FALLBACK_COLORS[i++ % 4]
  }
  return map
})
const agentsLine = computed(() => (
  (timeline.value?.summary?.agents || [])
    .map(a => `${agentNameMap.value[a.id] || a.id}(${a.provider}/${a.model})`)
    .join(' · ')
))
const winnerName = computed(() => {
  const wid = timeline.value?.final?.winner_id
  return wid ? (agentNameMap.value[wid] || wid) : ''
})
const finalAttribution = computed(() => timeline.value?.final?.victory_attribution || [])

const archiveOperatorSchema = computed(() => ({
  operator_trace: timeline.value?.operator_trace || timeline.value?.summary?.operator_trace || {},
  execution: timeline.value?.execution || timeline.value?.summary?.execution || {},
}))
const processChainTypeId = computed(() => {
  const fromSchema = processChainTypeFromSchema(archiveOperatorSchema.value)
  if (fromSchema && fromSchema !== 'simulation') return fromSchema
  // 旧存档无声明时：若本局结算出现 hybrid，套混合链路
  for (const t of ticks.value) {
    for (const s of t.os2?.settlements || []) {
      if (s?.authority?.mode === 'hybrid') return 'hybrid'
    }
  }
  return fromSchema
})
const processChainProfile = computed(() => resolveProcessChainProfile(processChainTypeId.value))
const processChainSteps = computed(() => processChainProfile.value.steps || [])
function processStepVisible(card, stepId) {
  if (stepId === 'settle') return Array.isArray(card?.judgeLines) && card.judgeLines.length > 0
  return true
}

const turnProcess = computed(() => {
  const t = currentTick.value
  if (!t) return []
  const os2 = t.os2 || {}
  const isHybridChain = processChainTypeId.value === 'hybrid'
  return (t.logs || []).map(log => {
    const pack = log.action_pack || {}
    const actionId = pack.action_id || ''
    const actionFact = (os2.world_actions || []).find(item => item.actor_id === log.agent_id)
    const eventFact = (os2.world_events || []).find(item => (
      item.actor_id === log.agent_id || item.source_action_ref === actionFact?.action_id
    ))
    const eventId = eventFact?.event_id
    const settlement = (os2.settlements || []).find(item => (
      (item.subject_ids || []).includes(log.agent_id)
      || (item.source_event_refs || []).includes(eventId)
    ))
    const action = actionLabels.value[actionId] || pack.action_name || actionId || '（未解析出动作）'
    const target = pack.target_agent_id
      ? (agentNameMap.value[pack.target_agent_id] || pack.target_agent_id)
      : String(pack.target_object_id || pack.target_id || '')
    const outcome = settlement?.explanation || eventFact?.public_summary || (log.error ? '执行异常' : '等待场景结算')
    const parseErrors = (pack.parse_errors || []).map(zhFields).join('；')
    const params = pack.parameters && typeof pack.parameters === 'object' ? pack.parameters : {}
    const orderBits = []
    if (params.asset_id) orderBits.push(`标的 ${params.asset_id}`)
    if (params.quantity !== undefined && params.quantity !== null && params.quantity !== '') {
      orderBits.push(`数量 ${params.quantity}`)
    }
    if (params.price_evidence_ref) orderBits.push(`价格证据 ${params.price_evidence_ref}`)
    const activity = (os2.agent_activities || []).find(item => item.agent_id === log.agent_id)
    const loop = summarizeHarnessLoop(
      log.harness_trace,
      activity?.tool_activity || [],
    )
    return {
      key: `${t.tick}-${log.agent_id}`,
      agentId: log.agent_id,
      color: agentColorMap.value[log.agent_id] || '#69dcff',
      name: agentNameMap.value[log.agent_id] || log.agent_id,
      meta: [log.provider && log.model ? `${log.provider}/${log.model}` : '', log.duration_ms ? `${log.duration_ms}ms` : '']
        .filter(Boolean).join(' · '),
      action,
      target,
      outcome,
      outcomeClass: settlement?.outcome?.includes('rejected') || log.error ? 'bad' : (settlement ? 'good' : 'flat'),
      perceive: perceiveSummary(log),
      perceptionRaw: log.perception ? pretty(log.perception) : '',
      loop,
      think: reasoningOf(pack, log.raw_llm_response),
      said: saidText(log),
      raw: log.raw_llm_response || '',
      parsed: actionId
        ? (isHybridChain
          ? `动作 = ${action}`
          : `动作 = ${action}${target ? `，目标 = ${target}` : ''}`)
        : '系统未能从回复中解析出动作',
      orderParams: orderBits.length ? orderBits.join(' · ') : '',
      parseErrors,
      actionRaw: log.action_pack ? pretty(log.action_pack) : '',
      judgeLines: [...new Set([eventFact?.public_summary, settlement?.explanation].filter(Boolean))],
      metrics: Object.entries(settlement?.values || {}).map(([key, value]) => `${key} ${value}`),
      degraded: !!pack?.metadata?.degraded,
    }
  })
})

function zhFields(msg) {
  let out = String(msg || '')
  for (const [en, zh] of Object.entries(FIELD_ZH)) out = out.replaceAll(en, zh)
  return out.replace(/缺少字段:\s*/g, '缺少')
}
// 提取模型"想了什么"：公开推理 → plan → 思维链
function reasoningOf(pack, raw) {
  const out = { summary: '', chain: '' }
  const prs = pack?.public_reasoning_summary
  if (prs && typeof prs === 'object') {
    const bits = []
    if (prs.strategy_choice) bits.push(`策略选择：${prs.strategy_choice}`)
    if (prs.risk_consideration) bits.push(`风险考量：${prs.risk_consideration}`)
    out.summary = bits.join('\n') || Object.values(prs).filter(Boolean).join('\n')
  } else if (typeof prs === 'string' && prs.trim()) {
    out.summary = prs.trim()
  }
  if (!out.summary && pack?.plan) out.summary = String(pack.plan).trim()
  const m = typeof raw === 'string' ? raw.match(/<think>([\s\S]*?)<\/think>/i) : null
  if (m && m[1].trim()) out.chain = m[1].trim()
  return out
}
function saidText(log) {
  const pack = log.action_pack || {}
  const mono = pack.character_monologue
    || (typeof pack.public_reasoning_summary === 'object' ? pack.public_reasoning_summary?.strategy_choice : pack.public_reasoning_summary)
  if (typeof mono === 'string' && mono.trim()) return mono
  const plan = pack.plan || pack.declared_intent
  if (typeof plan === 'string' && plan.trim()) return plan
  return ''
}
function perceiveSummary(log) {
  const p = log.perception
  if (!p) return '本条日志未保留完整输入。'
  const brief = p.brief || p
  const parts = []
  const loc = brief.self_location || brief.location
  if (loc) parts.push(`身处「${loc}」`)
  const challenge = brief.raw_context?.current_challenge || brief.current_challenge
  if (challenge?.title) parts.push(`挑战《${challenge.title}》待应对`)
  const actions = brief.available_actions
  if (Array.isArray(actions) && actions.length) parts.push(`${actions.length} 个可选动作`)
  const objects = brief.visible_objects
  if (Array.isArray(objects) && objects.length) parts.push(`${objects.length} 个可见对象`)
  if (!parts.length) return '世界层已注入场景、资源、可见对象与约束（点开完整输入查看）。'
  return parts.join('，') + '。'
}
function pretty(v) { try { return JSON.stringify(v, null, 2) } catch { return String(v) } }
function formatTime(ts) {
  if (!ts) return tr('时间未知', 'Unknown time')
  try {
    const d = new Date(typeof ts === 'number' ? ts * 1000 : ts)
    return d.toLocaleString(locale.value, { hour12: false })
  } catch { return String(ts) }
}
function modelsLine(run) {
  return (run.agents || []).map(a => `${a.name || a.id}:${a.model || a.provider || '?'}`).join(' · ')
}
function agentNameOf(run, aid) {
  const hit = (run.agents || []).find(a => a.id === aid)
  return hit?.name || aid
}
function stepTick(dir) {
  const next = ticks.value[tickIndex.value + dir]
  if (next) activeTick.value = next.tick
}

async function loadRuns() {
  loadingRuns.value = true
  try {
    const data = await apiGet('/operator/runs', { limit: 100 })
    runs.value = data.runs || []
  } catch (e) { console.warn('[archive] 列表加载失败', e) }
  finally { loadingRuns.value = false }
}
async function selectRun(id) {
  if (!id || id === activeRunId.value) return
  activeRunId.value = id
  window.location.hash = `#/archive/${id}`
  timeline.value = null
  loadingTimeline.value = true
  try {
    timeline.value = await apiGet(`/operator/runs/${id}/timeline`)
    const ts = timeline.value?.ticks || []
    activeTick.value = ts.length ? ts[0].tick : null
  } catch (e) {
    console.warn('[archive] 时间线加载失败', e)
    timeline.value = { available: false, ticks: [] }
  } finally { loadingTimeline.value = false }
}

watch(() => props.runId, id => { if (id) selectRun(id) })
onMounted(async () => {
  await loadRuns()
  const target = props.runId
    || runs.value.find(item => item.has_presentation_timeline)?.run_id
    || runs.value[0]?.run_id
  if (target) selectRun(target)
})
</script>

<style scoped>
.ra-root {
  --ra-cyan: #67e8f9;
  --ra-teal: #5eead4;
  --ra-gold: #f7c96b;
  --ra-text: #e9f0fb;
  --ra-muted: #8190a8;
  display: flex;
  height: 100%;
  min-height: 0;
  background:
    radial-gradient(circle at 74% -20%, rgba(30, 154, 181, .12), transparent 38%),
    #070a10;
}
.ra-empty { padding: 24px; color: var(--ra-muted); font-size: 12px; line-height: 1.8; }
.ra-empty.big { display: grid; min-height: 320px; place-items: center; padding: 60px 40px; font-size: 13px; text-align: center; }
.ra-sec-title { display: block; margin: 0; color: var(--ra-text); font-size: 13px; font-weight: 750; letter-spacing: .02em; }
.ra-section-head { display: flex; align-items: center; justify-content: space-between; gap: 16px; margin-bottom: 14px; }
.ra-section-head small { color: #607089; font-size: 10px; letter-spacing: .05em; }

/* 左侧档案索引 */
.ra-list {
  width: 318px;
  flex-shrink: 0;
  overflow-y: auto;
  border-right: 1px solid rgba(148, 163, 184, .10);
  padding: 24px 16px;
  background: rgba(5, 8, 14, .74);
  scrollbar-width: thin;
  scrollbar-color: rgba(103, 232, 249, .18) transparent;
}
.ra-list-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 12px; margin: 0 4px 18px; }
.ra-list-title > span { color: var(--ra-cyan); font-size: 9px; font-weight: 800; letter-spacing: .19em; }
.ra-list-title h2 { margin: 7px 0 3px; color: #f5f8fd; font-size: 19px; font-weight: 720; letter-spacing: -.02em; }
.ra-list-title small { color: #596981; font-size: 10px; }
.ra-refresh {
  width: 34px; height: 34px; padding: 0;
  border: 1px solid rgba(148, 163, 184, .14); border-radius: 10px;
  background: rgba(255, 255, 255, .025); color: #8fa0b9;
  font-size: 17px; cursor: pointer; transition: .18s ease;
}
.ra-refresh:hover { border-color: rgba(103, 232, 249, .38); color: var(--ra-cyan); background: rgba(103, 232, 249, .06); transform: rotate(20deg); }
.ra-run-card {
  position: relative;
  border: 1px solid rgba(148, 163, 184, .10); border-radius: 14px;
  padding: 13px 14px 13px 16px; margin-bottom: 9px;
  background: rgba(13, 18, 28, .56); cursor: pointer;
  transition: border-color .18s, background .18s, transform .18s;
}
.ra-run-card::before { content: ''; position: absolute; left: -1px; top: 14px; bottom: 14px; width: 2px; border-radius: 2px; background: transparent; }
.ra-run-card:hover { border-color: rgba(103, 232, 249, .22); background: rgba(18, 26, 39, .74); transform: translateX(2px); }
.ra-run-card.active { border-color: rgba(103, 232, 249, .36); background: linear-gradient(110deg, rgba(25, 105, 125, .18), rgba(12, 20, 31, .76)); box-shadow: 0 12px 30px rgba(0, 0, 0, .18); }
.ra-run-card.active::before { background: var(--ra-cyan); box-shadow: 0 0 12px rgba(103, 232, 249, .65); }
.ra-run-top { display: flex; align-items: center; gap: 10px; }
.ra-run-top b { flex: 1; min-width: 0; overflow: hidden; color: #dfe8f5; font-size: 12px; font-weight: 680; text-overflow: ellipsis; white-space: nowrap; }
.ra-badge { padding: 3px 7px; border-radius: 999px; background: rgba(148, 163, 184, .10); color: #78869c; font-size: 9px; font-style: normal; font-weight: 750; }
.ra-badge.done { background: rgba(94, 234, 212, .10); color: #7ce8d7; }
.ra-run-time { margin: 7px 0 0; color: #64738a; font-size: 10px; font-variant-numeric: tabular-nums; }
.ra-run-winner { display: flex; align-items: center; gap: 6px; margin: 7px 0 0; color: #dbc084; font-size: 10.5px; }
.ra-run-winner span { padding: 1px 5px; border: 1px solid rgba(247, 201, 107, .22); border-radius: 4px; color: var(--ra-gold); font-size: 8px; letter-spacing: .08em; }
.ra-run-models { display: -webkit-box; overflow: hidden; margin-top: 6px; color: #526078; font-size: 9.5px; line-height: 1.45; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }

/* 主内容 */
.ra-main { flex: 1; min-width: 0; overflow-y: auto; padding: 30px 34px 52px; scrollbar-width: thin; scrollbar-color: rgba(103, 232, 249, .16) transparent; }
.ra-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 24px; margin-bottom: 24px; }
.ra-kicker { color: var(--ra-cyan); font-size: 9px; font-weight: 800; letter-spacing: .2em; }
.ra-head h2 { margin: 8px 0 10px; color: #f3f6fb; font-size: clamp(22px, 2vw, 30px); font-weight: 720; letter-spacing: -.035em; }
.ra-head-meta { display: flex; flex-wrap: wrap; gap: 7px; }
.ra-head-meta span { padding: 4px 8px; border: 1px solid rgba(148, 163, 184, .10); border-radius: 6px; background: rgba(255, 255, 255, .025); color: #718198; font-size: 10px; }
.ra-winner-pill { display: flex; min-width: 124px; flex-direction: column; flex-shrink: 0; gap: 3px; padding: 11px 16px; border: 1px solid rgba(247, 201, 107, .32); border-radius: 12px; background: linear-gradient(145deg, rgba(247, 201, 107, .16), rgba(247, 201, 107, .06)); color: var(--ra-gold); box-shadow: 0 10px 30px rgba(0, 0, 0, .16); }
.ra-winner-pill small { color: #8f7951; font-size: 8px; font-weight: 800; letter-spacing: .12em; text-transform: uppercase; }
.ra-winner-pill strong { font-size: 13px; font-weight: 760; }
.ra-winner-pill.muted { border-color: rgba(148, 163, 184, .13); background: rgba(255, 255, 255, .03); color: #8290a5; }

/* 评测结论 */
.ra-final { margin-bottom: 18px; padding: 18px; border: 1px solid rgba(247, 201, 107, .18); border-radius: 16px; background: linear-gradient(145deg, rgba(247, 201, 107, .045), rgba(9, 13, 21, .72)); }
.ra-final-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(290px, 1fr)); gap: 12px; }
.ra-vr-card { position: relative; min-height: 124px; padding: 15px 16px; border: 1px solid rgba(148, 163, 184, .10); border-radius: 12px; background: rgba(13, 18, 28, .78); }
.ra-vr-card.champ { border-color: rgba(247, 201, 107, .28); background: linear-gradient(135deg, rgba(247, 201, 107, .09), rgba(13, 18, 28, .82)); }
.ra-rank { position: absolute; top: 13px; right: 14px; color: #6c7c93; font-size: 8px; font-weight: 850; letter-spacing: .14em; }
.ra-vr-card.champ .ra-rank { color: var(--ra-gold); }
.ra-vr-card strong { display: block; max-width: calc(100% - 58px); margin-bottom: 9px; color: #e5ebf5; font-size: 12px; line-height: 1.55; }
.ra-vr-card p { margin: 3px 0; font-size: 10.5px; line-height: 1.6; }
.vr-plus { color: #77d8b5; }
.vr-weak { color: #d7b26d; }
.vr-fatal { color: #ef7f78; font-weight: 700; }
.ra-vr-card small { display: block; margin-top: 9px; color: #536278; font-size: 9px; }

/* 周期导航 */
.ra-nav { position: sticky; top: -18px; z-index: 4; display: grid; grid-template-columns: auto auto; align-items: end; gap: 10px 20px; margin-bottom: 18px; padding: 14px 16px; border: 1px solid rgba(148, 163, 184, .10); border-radius: 14px; background: rgba(8, 12, 19, .92); box-shadow: 0 14px 30px rgba(0, 0, 0, .18); backdrop-filter: blur(14px); }
.ra-nav-info span { display: block; margin-bottom: 3px; color: var(--ra-cyan); font-size: 8px; font-weight: 800; letter-spacing: .15em; }
.ra-nav-info strong { color: #dce6f4; font-size: 12px; }
.ra-nav-btns { display: inline-flex; justify-self: end; gap: 7px; }
.ra-nav-btns button { padding: 6px 12px; border: 1px solid rgba(148, 163, 184, .14); border-radius: 8px; background: rgba(255, 255, 255, .025); color: #9cabc0; font-size: 10px; cursor: pointer; }
.ra-nav-btns button:disabled { opacity: .28; cursor: default; }
.ra-nav-btns button:not(:disabled):hover { border-color: rgba(103, 232, 249, .36); color: var(--ra-cyan); }
.ra-chip-row { grid-column: 1 / -1; display: flex; gap: 5px; overflow-x: auto; padding: 2px 0 3px; scrollbar-width: none; }
.ra-chip { min-width: 34px; padding: 5px 9px; border: 1px solid rgba(148, 163, 184, .09); border-radius: 7px; background: transparent; color: #617087; font-size: 9px; cursor: pointer; font-variant-numeric: tabular-nums; }
.ra-chip:hover { border-color: rgba(103, 232, 249, .22); color: #9eb2ca; }
.ra-chip.active { border-color: rgba(103, 232, 249, .42); background: rgba(103, 232, 249, .09); color: var(--ra-cyan); box-shadow: inset 0 -1px 0 rgba(103, 232, 249, .25); }

/* 可追溯证据链 */
.ra-trace { margin: 18px 0; padding: 18px; border: 1px solid rgba(103, 232, 249, .12); border-radius: 16px; background: rgba(8, 13, 21, .58); }
.trace-flow { display: grid; grid-template-columns: repeat(3, minmax(0, 1fr)); gap: 10px; align-items: start; }
.trace-node { position: relative; min-width: 0; overflow: hidden; border: 1px solid rgba(148, 163, 184, .11); border-radius: 11px; background: rgba(16, 22, 33, .72); transition: border-color .18s, transform .18s; }
.trace-node:hover { border-color: rgba(103, 232, 249, .24); transform: translateY(-1px); }
.trace-node summary { position: relative; min-height: 72px; padding: 12px 34px 12px 13px; cursor: pointer; list-style: none; }
.trace-node summary::-webkit-details-marker { display: none; }
.trace-node summary::after { content: '+'; position: absolute; top: 12px; right: 13px; color: #53647c; font-size: 15px; font-weight: 300; }
.trace-node[open] summary::after { content: '−'; color: var(--ra-cyan); }
.trace-node summary span { display: block; color: #5fc8dd; font-size: 8px; font-weight: 800; letter-spacing: .11em; text-transform: uppercase; }
.trace-node summary b { display: -webkit-box; overflow: hidden; margin-top: 7px; color: #dce5f2; font-size: 11px; line-height: 1.45; -webkit-box-orient: vertical; -webkit-line-clamp: 2; }
.trace-node summary p { margin: 5px 0 0; overflow: hidden; color: #66768e; font-size: 9px; text-overflow: ellipsis; white-space: nowrap; }
.trace-node pre { max-height: 260px; overflow: auto; margin: 0; padding: 13px; border-top: 1px solid rgba(148, 163, 184, .08); background: #090e16; color: #9fb0c6; font-size: 9px; line-height: 1.55; white-space: pre-wrap; word-break: break-word; }
.trace-observation { border-top-color: rgba(94, 234, 212, .34); }
.trace-settlement { border-top-color: rgba(247, 201, 107, .38); }
.trace-director { border-top-color: rgba(192, 132, 252, .34); }
.trace-edge { display: none; }

/* 决策全过程 */
.ra-process { display: flex; flex-direction: column; gap: 12px; padding: 18px; border: 1px solid rgba(148, 163, 184, .09); border-radius: 16px; background: rgba(8, 13, 21, .42); }
.process-card { padding: 0; overflow: hidden; border: 1px solid rgba(148, 163, 184, .10); border-radius: 12px; background: rgba(14, 20, 31, .76); }
.pc-head { display: grid; grid-template-columns: auto minmax(120px, 1fr) auto auto; align-items: center; gap: 9px; margin: 0; padding: 12px 14px; border-left: 3px solid var(--pc-color, var(--ra-cyan)); border-bottom: 1px solid rgba(148, 163, 184, .08); background: rgba(255, 255, 255, .018); }
.pc-name { color: var(--pc-color, #fff); font-size: 12px; }
.pc-action { min-width: 0; overflow: hidden; color: #dce5f2; font-size: 11px; font-weight: 680; text-overflow: ellipsis; white-space: nowrap; }
.pc-action i { color: #c9ad70; font-style: normal; }
.pc-outcome { max-width: 260px; overflow: hidden; padding: 3px 8px; border-radius: 999px; background: rgba(148, 163, 184, .08); color: #8f9db1; font-size: 9px; font-weight: 750; text-overflow: ellipsis; white-space: nowrap; }
.pc-outcome.good { background: rgba(94, 234, 212, .10); color: #72d7c5; }
.pc-outcome.bad { background: rgba(239, 127, 120, .10); color: #ef8b84; }
.pc-meta { color: #596980; font-size: 9px; text-align: right; }
.pc-steps { display: grid; grid-template-columns: repeat(2, minmax(0, 1fr)); gap: 0; margin: 0; padding: 4px 14px 10px; list-style: none; }
.pc-steps > li { --step-color: #67e8f9; position: relative; display: grid; grid-template-columns: 52px 1fr; gap: 9px; min-width: 0; padding: 11px 12px 11px 18px; border-bottom: 1px solid rgba(148, 163, 184, .065); }
.pc-steps > li:nth-child(odd) { border-right: 1px solid rgba(148, 163, 184, .065); }
.pc-steps > li::before { content: ''; position: absolute; left: 5px; top: 0; bottom: 0; width: 1px; background: rgba(148, 163, 184, .10); }
.pc-steps > li::after { content: ''; position: absolute; left: 2px; top: 16px; width: 7px; height: 7px; border-radius: 50%; background: var(--step-color); box-shadow: 0 0 7px color-mix(in srgb, var(--step-color) 55%, transparent); }
.pc-steps li.step-see { --step-color: #67e8f9; }
.pc-steps li.step-loop { --step-color: #5eead4; }
.pc-steps li.step-think, .pc-steps li.step-say { --step-color: #c084fc; }
.pc-steps li.step-parse { --step-color: #f7c96b; }
.pc-steps li.step-judge { --step-color: #79ddb9; }
.pc-steps li.step-metric { --step-color: #f28ab2; }
.pc-steps label { padding-top: 2px; color: var(--step-color); font-size: 9px; font-weight: 800; letter-spacing: .08em; }
.pc-steps li > div { min-width: 0; }
.pc-steps p { margin: 1px 0; color: #aebbd0; font-size: 10.5px; line-height: 1.65; word-break: break-word; }
.think-summary { color: #d2b9ee !important; white-space: pre-line; }
.pc-warn { color: #d9b86f !important; }
.pc-muted { color: #5f6e84 !important; }
.pc-steps details { margin-top: 5px; }
.pc-steps summary { color: #689cc2; font-size: 9.5px; cursor: pointer; user-select: none; }
.pc-steps details pre { max-height: 300px; overflow: auto; margin: 7px 0 0; padding: 11px; border: 1px solid rgba(148, 163, 184, .08); border-radius: 8px; background: #090e16; color: #91a2bb; font-size: 9px; line-height: 1.55; white-space: pre-wrap; word-break: break-all; }
.loop-steps { display: flex; flex-direction: column; gap: 6px; margin: 7px 0 0; padding: 0; list-style: none; }
.loop-steps li { margin: 0; padding: 7px 9px; border: 0; border-left: 2px solid rgba(94, 234, 212, .34); border-radius: 0 6px 6px 0; background: rgba(94, 234, 212, .045); }
.loop-steps li::before, .loop-steps li::after { display: none !important; }
.loop-steps b { margin-right: 6px; color: #86d9cb; font-size: 10px; }
.loop-steps em { margin-right: 6px; color: #76879e; font-size: 9px; font-style: normal; }
.loop-steps span { color: #64748b; font-size: 9px; }
.loop-steps p { margin: 4px 0 0 !important; color: #9eacc0 !important; font-size: 10px !important; }
.loop-st.failed, .loop-st.blocked { color: #ef8b84; }
.loop-st.succeeded { color: #72d7c5; }
.ra-metric-pills { display: flex; flex-wrap: wrap; gap: 5px; }
.ra-metric-pills span { padding: 3px 7px; border-radius: 6px; background: rgba(94, 234, 212, .08); color: #74ccb9; font-size: 9px; font-weight: 700; }
.ra-metric-pills span.neg { background: rgba(239, 127, 120, .08); color: #e58b86; }

@media (max-width: 1280px) {
  .ra-list { width: 276px; }
  .ra-main { padding: 24px; }
  .trace-flow { grid-template-columns: repeat(2, minmax(0, 1fr)); }
  .pc-steps { grid-template-columns: 1fr; }
  .pc-steps > li:nth-child(odd) { border-right: 0; }
}
@media (max-width: 900px) {
  .ra-root { flex-direction: column; overflow-y: auto; }
  .ra-list { width: auto; max-height: 260px; flex-shrink: 0; border-right: 0; border-bottom: 1px solid rgba(148, 163, 184, .10); }
  .ra-main { overflow: visible; padding: 20px 16px 42px; }
  .ra-head { flex-direction: column; }
  .ra-winner-pill { align-self: stretch; }
  .trace-flow { grid-template-columns: 1fr; }
  .pc-head { grid-template-columns: auto 1fr; }
  .pc-outcome, .pc-meta { grid-column: 2; max-width: none; text-align: left; }
}
</style>
