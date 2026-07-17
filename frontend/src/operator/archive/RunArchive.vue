<template>
  <div class="ra-root">
    <!-- 左栏：对局列表 -->
    <aside class="ra-list">
      <div class="ra-list-head">
        <div>
          <span>RUN ARCHIVE</span>
          <h2>对局档案</h2>
        </div>
        <button class="ra-refresh" @click="loadRuns">刷新</button>
      </div>
      <div v-if="loadingRuns" class="ra-empty">载入对局列表…</div>
      <div v-else-if="!runs.length" class="ra-empty">还没有已存档的对局。跑完一局（终局或重置）后会自动落盘到这里。</div>
      <article
        v-for="run in runs"
        :key="run.run_id"
        class="ra-run-card"
        :class="{ active: run.run_id === activeRunId }"
        @click="selectRun(run.run_id)"
      >
        <div class="ra-run-top">
          <b>{{ run.scenario || run.run_id }}</b>
          <em v-if="run.finalized" class="ra-badge done">已终局</em>
          <em v-else class="ra-badge">中断局</em>
        </div>
        <p class="ra-run-time">{{ formatTime(run.created_at) }} · {{ run.run_id }}</p>
        <p v-if="run.winner" class="ra-run-winner">🏆 {{ agentNameOf(run, run.winner) }} 胜出</p>
        <small class="ra-run-models">{{ modelsLine(run) }}</small>
      </article>
    </aside>

    <!-- 主区：单局回顾（实时对局同款） -->
    <section class="ra-main">
      <div v-if="!activeRunId" class="ra-empty big">从左侧选择一局开始回顾。</div>
      <div v-else-if="loadingTimeline" class="ra-empty big">载入对局数据…</div>

      <template v-else-if="timeline && timeline.available">
        <!-- 局头 -->
        <header class="ra-head">
          <div>
            <span class="ra-kicker">MATCH REVIEW</span>
            <h2>{{ timeline.summary?.scenario || activeRunId }}</h2>
            <p>{{ formatTime(timeline.summary?.created_at) }} · 共 {{ ticks.length }} 回合 · {{ agentsLine }}</p>
          </div>
          <div v-if="winnerName" class="ra-winner-pill">🏆 {{ winnerName }} 胜出</div>
          <div v-else class="ra-winner-pill muted">本局未走到终局</div>
        </header>

        <!-- 终局裁定·胜负溯源 -->
        <div v-if="finalAttribution.length" class="ra-final">
          <span class="ra-sec-title">🏆 终局裁定 · 胜负溯源</span>
          <div class="ra-final-grid">
            <div v-for="item in finalAttribution" :key="item.agent_id" class="ra-vr-card" :class="{ champ: item.rank === 1 }">
              <strong>{{ item.headline }}</strong>
              <p class="vr-plus" v-for="s in item.strengths" :key="'s'+s">＋ {{ s }}</p>
              <p class="vr-weak" v-for="w in item.weaknesses" :key="'w'+w">－ {{ w }}</p>
              <p class="vr-fatal" v-if="item.fatal">✖ {{ item.fatal }}</p>
              <small>终局结果以本场景结算记录和胜负规则为准</small>
            </div>
          </div>
        </div>

        <!-- 回合导航 -->
        <div class="ra-nav">
          <div class="ra-nav-info">
            <span>回合回放</span>
            <strong>正在回看 T{{ activeTick }}</strong>
          </div>
          <div class="ra-nav-btns">
            <button :disabled="tickIndex <= 0" @click="stepTick(-1)">上一回合</button>
            <button :disabled="tickIndex >= ticks.length - 1" @click="stepTick(1)">下一回合</button>
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
          <span class="ra-sec-title">本回合可追溯链路</span>
          <div v-if="!traceNodes.length" class="ra-empty">该回合是旧版存档，或尚未写入 OS 2.0 契约记录。</div>
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
          <span class="ra-sec-title">本回合全过程 · {{ processChainProfile.label }} · {{ turnProcess.length }} 个模型</span>
          <div v-if="!turnProcess.length" class="ra-empty">本回合没有模型决策记录（可能是开场或收尾帧）。</div>
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
                    <details v-if="p.perceptionRaw"><summary>完整输入</summary><pre>{{ p.perceptionRaw }}</pre></details>
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
                    <p v-else class="pc-muted">本回合没有记录到 Agent Loop / 工具取证步骤。</p>
                    <details v-if="p.loop.raw"><summary>Harness 轨迹原文</summary><pre>{{ pretty(p.loop.raw) }}</pre></details>
                  </template>
                  <template v-else-if="step.id === 'think'">
                    <p v-if="p.think.summary" class="think-summary">{{ p.think.summary }}</p>
                    <details v-if="p.think.chain"><summary>展开完整思维链</summary><pre>{{ p.think.chain }}</pre></details>
                    <p v-if="!p.think.summary && !p.think.chain" class="pc-muted">该模型此局未捕获思维链（旧对局，或模型未暴露思考过程）。</p>
                  </template>
                  <template v-else-if="step.id === 'said'">
                    <p>{{ p.said || '（没有可展示的输出文本）' }}</p>
                    <details v-if="p.raw"><summary>模型原始输出</summary><pre>{{ p.raw }}</pre></details>
                  </template>
                  <template v-else-if="step.id === 'parsed'">
                    <p>{{ p.parsed }}</p>
                    <p v-if="p.orderParams" class="think-summary">{{ p.orderParams }}</p>
                    <p v-if="p.parseErrors" class="pc-warn">解析修复：{{ p.parseErrors }}</p>
                    <details v-if="p.actionRaw"><summary>结构化动作</summary><pre>{{ p.actionRaw }}</pre></details>
                  </template>
                  <template v-else-if="step.id === 'settle'">
                    <p v-for="line in p.judgeLines" :key="line">{{ line }}</p>
                  </template>
                  <template v-else-if="step.id === 'metrics'">
                    <div v-if="p.metrics.length" class="ra-metric-pills">
                      <span v-for="m in p.metrics" :key="m" :class="{ neg: m.includes('-') }">{{ m }}</span>
                    </div>
                    <p v-else class="pc-muted">本步没有引起指标变化</p>
                    <p v-if="p.degraded" class="pc-muted">（本回合为超时兜底动作，非主动选择）</p>
                  </template>
                </div>
              </li>
            </ol>
          </article>
        </div>
      </template>

      <div v-else class="ra-empty big">
        本局没有留存演绎档案（可能是进程被强制中断，未走正常终局/重置流程）。<br />
        仅有账本与诊断数据，可在服务器 runs/{{ activeRunId }}/ 下查看原始文件。
      </div>
    </section>
  </div>
</template>

<script setup>
import { ref, computed, watch, onMounted } from 'vue'
import { apiGet } from '../api.js'
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
  if (!ts) return '时间未知'
  try {
    const d = new Date(typeof ts === 'number' ? ts * 1000 : ts)
    return d.toLocaleString('zh-CN', { hour12: false })
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
.ra-root { display: flex; height: 100%; min-height: 0; gap: 0; }
.ra-empty { padding: 20px; color: #8a93ad; font-size: 12px; line-height: 1.8; }
.ra-empty.big { padding: 60px 40px; font-size: 13px; }
.ra-sec-title { display: block; font-size: 11px; font-weight: 800; letter-spacing: .12em; color: #ffd060; margin-bottom: 10px; }

/* 左栏 */
.ra-list { width: 300px; flex-shrink: 0; overflow-y: auto; border-right: 1px solid rgba(255,255,255,.06); padding: 16px 12px; }
.ra-list-head { display: flex; align-items: center; justify-content: space-between; margin-bottom: 12px; }
.ra-list-head span { font-size: 10px; letter-spacing: .16em; color: #69dcff; font-weight: 800; }
.ra-list-head h2 { margin: 4px 0 0; font-size: 16px; }
.ra-refresh { border: 1px solid rgba(255,255,255,.14); background: transparent; color: #aeb8d3; font-size: 11px; padding: 5px 12px; border-radius: 8px; cursor: pointer; }
.ra-refresh:hover { color: #fff; border-color: rgba(105,220,255,.4); }
.ra-run-card { border: 1px solid rgba(255,255,255,.07); border-radius: 10px; padding: 10px 12px; margin-bottom: 8px; cursor: pointer; transition: all .15s ease; }
.ra-run-card:hover { background: rgba(255,255,255,.04); }
.ra-run-card.active { border-color: rgba(105,220,255,.45); background: rgba(105,220,255,.06); }
.ra-run-top { display: flex; align-items: center; gap: 8px; }
.ra-run-top b { font-size: 12.5px; flex: 1; min-width: 0; overflow: hidden; text-overflow: ellipsis; white-space: nowrap; }
.ra-badge { font-size: 9px; font-weight: 800; padding: 2px 7px; border-radius: 999px; background: rgba(255,255,255,.08); color: #8a93ad; font-style: normal; }
.ra-badge.done { background: rgba(139,226,139,.14); color: #8be28b; }
.ra-run-time { margin: 5px 0 0; font-size: 10.5px; color: #6b7690; }
.ra-run-winner { margin: 4px 0 0; font-size: 11px; color: #ffd060; }
.ra-run-models { display: block; margin-top: 4px; font-size: 10px; color: #6b7690; }

/* 主区 */
.ra-main { flex: 1; min-width: 0; overflow-y: auto; padding: 18px 22px; }
.ra-head { display: flex; align-items: flex-start; justify-content: space-between; gap: 16px; margin-bottom: 16px; }
.ra-kicker { font-size: 10px; letter-spacing: .16em; color: #69dcff; font-weight: 800; }
.ra-head h2 { margin: 6px 0 4px; font-size: 20px; }
.ra-head p { margin: 0; font-size: 11.5px; color: #8a93ad; }
.ra-winner-pill { flex-shrink: 0; font-size: 13px; font-weight: 800; color: #1a1206; background: linear-gradient(135deg, #ffe39a, #ffc24d); padding: 8px 16px; border-radius: 10px; }
.ra-winner-pill.muted { background: rgba(255,255,255,.08); color: #8a93ad; }
.ra-trace { margin:16px 0; padding:15px; border:1px solid rgba(105,220,255,.16); border-radius:12px; background:rgba(8,14,23,.46); }
.trace-flow { display:grid; grid-template-columns:repeat(auto-fit,minmax(180px,1fr)); gap:20px; align-items:start; }
.trace-node { position:relative; min-width:0; border:1px solid rgba(255,255,255,.1); border-radius:9px; background:rgba(255,255,255,.03); overflow:hidden; }
.trace-node summary { cursor:pointer; list-style:none; padding:11px; }
.trace-node summary span { display:block; color:#69dcff; font-size:9px; letter-spacing:.1em; }
.trace-node summary b { display:block; margin-top:5px; color:#eef3ff; font-size:12px; line-height:1.4; }
.trace-node summary p { margin:4px 0 0; color:#7f8ba3; font-size:10px; }
.trace-node pre { max-height:240px; overflow:auto; margin:0; padding:10px; background:#080d15; color:#b8c5d8; font-size:9px; white-space:pre-wrap; word-break:break-word; }
.trace-observation { border-color:rgba(80,225,177,.3); }
.trace-settlement { border-color:rgba(255,208,96,.35); }
.trace-director { border-color:rgba(183,126,255,.3); }
.trace-edge { display:none; }

/* 终局溯源 */
.ra-final { border: 1px solid rgba(255,208,96,.3); border-radius: 12px; padding: 14px 16px; margin-bottom: 16px; }
.ra-final-grid { display: grid; grid-template-columns: repeat(auto-fit, minmax(260px, 1fr)); gap: 10px; }
.ra-vr-card { border: 1px solid rgba(255,255,255,.08); border-radius: 10px; padding: 10px 12px; background: rgba(255,255,255,.03); }
.ra-vr-card.champ { border-color: rgba(255,208,96,.45); background: rgba(255,208,96,.06); }
.ra-vr-card strong { display: block; font-size: 12.5px; margin-bottom: 5px; }
.ra-vr-card p { margin: 2px 0; font-size: 11px; line-height: 1.6; }
.vr-plus { color: #8be28b; }
.vr-weak { color: #e0b36a; }
.vr-fatal { color: #ff5f52; font-weight: 700; }
.ra-vr-card small { color: #6b7690; font-size: 10px; }

/* 回合导航 */
.ra-nav { border: 1px solid rgba(255,255,255,.07); border-radius: 12px; padding: 12px 14px; margin-bottom: 14px; }
.ra-nav-info span { font-size: 10px; letter-spacing: .12em; color: #69dcff; font-weight: 800; display: block; }
.ra-nav-info strong { font-size: 14px; }
.ra-nav-btns { display: inline-flex; gap: 8px; margin-top: 8px; }
.ra-nav-btns button { border: 1px solid rgba(255,255,255,.14); background: transparent; color: #cdd6ee; font-size: 11px; padding: 5px 14px; border-radius: 8px; cursor: pointer; }
.ra-nav-btns button:disabled { opacity: .35; cursor: default; }
.ra-nav-btns button:not(:disabled):hover { border-color: rgba(105,220,255,.4); color: #fff; }
.ra-chip-row { display: flex; flex-wrap: wrap; gap: 6px; margin-top: 10px; }
.ra-chip { border: 1px solid rgba(255,255,255,.1); background: transparent; color: #8a93ad; font-size: 11px; padding: 4px 10px; border-radius: 999px; cursor: pointer; }
.ra-chip.active { border-color: rgba(105,220,255,.55); color: #69dcff; background: rgba(105,220,255,.08); }

/* 导演旁白 */
.ra-frames { border: 1px solid rgba(255,255,255,.07); border-radius: 12px; padding: 12px 16px; margin-bottom: 14px; }
.ra-frames p { margin: 6px 0; font-size: 12px; line-height: 1.75; color: #c3cbe0; }
.ra-frames p b { display: block; color: #ffd060; font-size: 11.5px; margin-bottom: 2px; }
.ra-frames p.oracle b { color: #b48bff; }
.ra-frames p.elim b { color: #ff5f52; }

/* 流水卡（实时对局同款） */
.ra-process { display: flex; flex-direction: column; gap: 12px; }
.process-card { border: 1px solid rgba(255,255,255,.07); border-left: 3px solid var(--pc-color, #69dcff); border-radius: 12px; background: rgba(255,255,255,.025); padding: 12px 14px; }
.pc-head { display: flex; align-items: center; flex-wrap: wrap; gap: 8px; margin-bottom: 10px; }
.pc-name { color: var(--pc-color, #fff); font-size: 14px; }
.pc-action { font-size: 13px; font-weight: 700; color: #e6ecff; }
.pc-action i { font-style: normal; color: #ffd66b; }
.pc-outcome { font-size: 10px; font-weight: 800; padding: 2px 8px; border-radius: 999px; background: rgba(255,255,255,.08); color: #9aa6c0; }
.pc-outcome.good { background: rgba(139,226,139,.16); color: #8be28b; }
.pc-outcome.bad { background: rgba(255,95,82,.16); color: #ff5f52; }
.pc-meta { margin-left: auto; font-size: 10px; color: #6b7690; }
.pc-steps { list-style: none; margin: 0; padding: 0; display: flex; flex-direction: column; }
.pc-steps li { position: relative; display: grid; grid-template-columns: 52px 1fr; gap: 10px; padding: 6px 0 6px 14px; }
.pc-steps li::before { content: ''; position: absolute; left: 3px; top: 0; bottom: 0; width: 1px; background: rgba(255,255,255,.1); }
.pc-steps li:first-child::before { top: 14px; }
.pc-steps li:last-child::before { bottom: auto; height: 14px; }
.pc-steps li::after { content: ''; position: absolute; left: 0; top: 11px; width: 7px; height: 7px; border-radius: 50%; background: var(--step-color, #69dcff); box-shadow: 0 0 6px var(--step-color, #69dcff); }
.pc-steps li.step-see { --step-color: #69dcff; }
.pc-steps li.step-loop { --step-color: #5eead4; }
.pc-steps li.step-think { --step-color: #c48bff; }
.pc-steps li.step-say { --step-color: #b48bff; }
.think-summary { white-space: pre-line; color: #d9c8ff !important; }
.pc-steps li.step-parse { --step-color: #ffd66b; }
.pc-steps li.step-judge { --step-color: #8be28b; }
.pc-steps li.step-metric { --step-color: #ff6fa7; }
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
.loop-steps b { font-size: 11px; color: #9ff0e0; margin-right: 6px; }
.loop-steps em { font-style: normal; font-size: 10px; opacity: 0.75; margin-right: 6px; }
.loop-steps span { font-size: 10px; color: #7a8aa8; }
.loop-steps p { margin: 4px 0 0 !important; font-size: 11px !important; color: #c5d0e4 !important; }
.loop-st.failed,
.loop-st.blocked { color: #ff8f8f; }
.loop-st.succeeded { color: #8be28b; }
.pc-steps label { font-size: 11px; font-weight: 800; color: var(--step-color, #9aa6c0); padding-top: 3px; letter-spacing: .08em; }
.pc-steps li > div { min-width: 0; }
.pc-steps p { margin: 2px 0; font-size: 12px; line-height: 1.7; color: #c3cbe0; word-break: break-word; }
.pc-warn { color: #ffd66b !important; font-size: 11px !important; }
.pc-muted { color: #6b7690 !important; }
.pc-steps details { margin-top: 4px; }
.pc-steps summary { font-size: 10.5px; color: #5b8bff; cursor: pointer; user-select: none; }
.pc-steps details pre { margin: 6px 0 0; max-height: 300px; overflow: auto; padding: 10px; border-radius: 8px; background: rgba(0,0,0,.35); border: 1px solid rgba(255,255,255,.06); font-size: 10.5px; line-height: 1.6; color: #9fb0d0; white-space: pre-wrap; word-break: break-all; }
.ra-metric-pills { display: flex; flex-wrap: wrap; gap: 6px; }
.ra-metric-pills span { font-size: 10.5px; font-weight: 700; padding: 2px 9px; border-radius: 999px; background: rgba(139,226,139,.12); color: #8be28b; }
.ra-metric-pills span.neg { background: rgba(255,95,82,.12); color: #ff5f52; }
</style>
