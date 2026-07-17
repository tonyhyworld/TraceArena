<template>
  <div class="analysis-root">
    <header class="analysis-hero">
      <div>
        <span class="kicker">跨局模型表现</span>
        <h1>模型分析</h1>
        <p>把多局对战整理成普通人能看懂的结论：模型强在哪里、喜欢怎么行动、风险偏高还是偏稳。</p>
      </div>
      <div class="hero-actions">
        <select v-model="selectedModelKey">
          <option v-for="m in models" :key="m.model_key" :value="m.model_key">{{ m.model_key }}</option>
        </select>
        <button @click="loadAnalysis">刷新</button>
      </div>
    </header>

    <div v-if="loading" class="state">正在聚合历史对局...</div>
    <div v-else-if="error" class="state err">加载失败：{{ error }}</div>
    <div v-else-if="!models.length" class="state">暂无可分析模型。跑完至少一局后这里会出现模型画像。</div>

    <template v-else>
      <section class="summary-grid">
        <article class="summary-card main">
          <label>当前模型</label>
          <h2>{{ selectedModel.model_key }}</h2>
          <p>参与 {{ selectedModel.run_count }} 局 · 扮演过 {{ selectedModel.agent_samples }} 次角色</p>
        </article>
        <article class="summary-card">
          <label>胜率</label>
          <strong>{{ pct(selectedModel.win_rate) }}</strong>
          <p>{{ selectedModel.win_count }} 次胜出</p>
        </article>
        <article class="summary-card">
          <label>平均名次</label>
          <strong>{{ selectedModel.avg_victory_rank == null ? '-' : fmt(selectedModel.avg_victory_rank) }}</strong>
          <p>按各场景自己的胜负口径统计</p>
        </article>
        <article class="summary-card">
          <label>行为样本</label>
          <strong>{{ selectedModel.turns }}</strong>
          <p>做过的选择</p>
        </article>
      </section>

      <section class="plain-insights">
        <article>
          <div class="insight-icon brain"></div>
          <label>一句话能力结论</label>
          <h3>{{ plainStrength }}</h3>
          <p>根据跨场景能力旁路和世界结算样本归纳。</p>
        </article>
        <article>
          <div class="insight-icon style"></div>
          <label>常见打法</label>
          <h3>{{ playStyle }}</h3>
          <p>来自它在对局中最常选择的动作。</p>
        </article>
        <article>
          <div class="insight-icon risk"></div>
          <label>风险气质</label>
          <h3>{{ riskTone }}</h3>
          <p>根据高风险动作和等待频率判断。</p>
        </article>
      </section>

      <section class="reading-guide">
        <article>
          <span class="guide-dot brain"></span>
          <div><strong>先看能力</strong><p>分越高，说明这个模型在对应任务上越稳定。</p></div>
        </article>
        <article>
          <span class="guide-dot style"></span>
          <div><strong>再看打法</strong><p>动作分布能看出它偏调查、表态、合作还是冒险。</p></div>
        </article>
        <article>
          <span class="guide-dot proof"></span>
          <div><strong>最后看证据</strong><p>每个分数都能点到原始题目和模型输出。</p></div>
        </article>
      </section>

      <section class="analysis-grid">
        <article class="panel capability-panel">
          <div class="panel-head">
            <div>
              <span class="kicker">它擅长什么</span>
              <h2>能力画像</h2>
            </div>
            <em>{{ selectedModel.capabilities.length }} 项能力</em>
          </div>
          <div class="radar-wrap">
            <svg viewBox="-140 -140 280 280" class="radar">
              <polygon points="0,-116 100,-58 100,58 0,116 -100,58 -100,-58" class="radar-grid" />
              <polygon points="0,-78 68,-39 68,39 0,78 -68,39 -68,-39" class="radar-grid inner" />
              <polygon :points="radarPoints" class="radar-fill" />
              <circle v-for="pt in radarDots" :key="pt.label" :cx="pt.x" :cy="pt.y" r="4" />
            </svg>
            <div class="radar-list">
              <button
                v-for="cap in topCapabilities"
                :key="cap.capability"
                :class="{ active: selectedCapability === cap.capability }"
                @click="selectedCapability = cap.capability"
              >
                <span>{{ cap.label }}</span>
                <em>{{ capabilityCaseCounts[cap.capability] || 0 }} 例</em>
                <b>{{ fmt(cap.score, 0) }}</b>
                <i :style="{ width: `${Math.max(3, cap.score)}%` }"></i>
              </button>
            </div>
          </div>
        </article>

        <article class="panel behavior-panel">
          <div class="panel-head">
            <div>
              <span class="kicker">它怎么行动</span>
              <h2>跨场景行为画像</h2>
            </div>
          </div>
          <div class="behavior-stats">
            <div><label>覆盖场景</label><strong>{{ selectedModel.scenarios?.length || 0 }}</strong></div>
            <div><label>可验证外部事实</label><strong>{{ selectedModel.verified_observations || 0 }}</strong></div>
            <div><label>结算权限类型</label><strong>{{ authorityCount }}</strong></div>
          </div>
          <div class="action-list">
            <article v-for="action in selectedModel.actions.slice(0, 10)" :key="action.action_id">
              <div>
                <strong>{{ action.label }}</strong>
                <span>{{ action.count }} 次 · {{ pct(action.ratio) }}</span>
              </div>
              <i :style="{ width: `${Math.max(3, action.ratio * 100)}%` }"></i>
            </article>
          </div>
        </article>
      </section>

      <section class="panel authority-panel">
        <div class="panel-head"><div><span class="kicker">结果怎么得出</span><h2>场景与结算覆盖</h2></div></div>
        <div class="coverage-grid">
          <article><label>参与过的场景</label><p v-for="item in selectedModel.scenarios || []" :key="item.name"><b>{{ item.name }}</b><span>{{ item.samples }} 个角色样本</span></p></article>
          <article><label>结算权限</label><p v-for="(count, mode) in selectedModel.settlement_authorities || {}" :key="mode"><b>{{ authorityLabel(mode) }}</b><span>{{ count }} 条结算</span></p><p v-if="!authorityCount">暂无 OS 2.0 结算样本</p></article>
        </div>
      </section>

      <section class="panel compare-panel">
        <div class="panel-head">
          <div>
            <span class="kicker">模型对比</span>
            <h2>不同模型谁更强</h2>
          </div>
          <em>{{ aggregate.total_runs }} 局历史样本</em>
        </div>
        <div class="compare-table">
          <div class="compare-row head">
            <span>模型</span>
            <span>参与局数</span>
            <span>胜率</span>
            <span>平均名次</span>
            <span>最强项</span>
            <span>最常做</span>
          </div>
          <button
            v-for="m in models"
            :key="m.model_key"
            class="compare-row"
            :class="{ active: selectedModelKey === m.model_key }"
            @click="selectedModelKey = m.model_key"
          >
            <span>{{ m.model_key }}</span>
            <span>{{ m.run_count }}</span>
            <span>{{ pct(m.win_rate) }}</span>
            <span>{{ m.avg_victory_rank == null ? '-' : fmt(m.avg_victory_rank) }}</span>
            <span>{{ bestCapability(m) }}</span>
            <span>{{ m.actions[0]?.label || '-' }}</span>
          </button>
        </div>
      </section>

      <section class="panel cases-panel">
        <div class="panel-head">
          <div>
            <span class="kicker">原始证据</span>
            <h2>{{ selectedCapabilityLabel }} · 验证任务与模型输出</h2>
          </div>
          <em>{{ filteredCases.length }} 条</em>
        </div>
        <div class="case-list">
          <details v-for="item in filteredCases.slice(0, 12)" :key="`${item.run_id}-${item.case_id}`" class="case-item">
            <summary>
              <span>{{ item.agent_name }} · {{ item.run_id }} · T{{ item.tick }}</span>
              <b>{{ fmt(Number(item.score || 0) * 100, 0) }}</b>
              <em>{{ item.status }}</em>
            </summary>
            <div class="case-body">
              <div><label>题目</label><p>{{ item.instruction || '-' }}</p></div>
              <div><label>判定依据</label><p>{{ item.rationale || '-' }}</p></div>
              <div><label>模型原始输出</label><pre>{{ item.raw_output || '-' }}</pre></div>
            </div>
          </details>
          <div v-if="!filteredCases.length" class="state small">这个维度暂无可下钻案例。</div>
        </div>
      </section>
    </template>
  </div>
</template>

<script setup>
import { computed, onMounted, ref, watch } from 'vue'
import { apiGet } from '../api.js'

const aggregate = ref({ models: [], total_runs: 0 })
const loading = ref(false)
const error = ref('')
const selectedModelKey = ref('')
const selectedCapability = ref('')
const authorityCount = computed(() => Object.keys(selectedModel.value.settlement_authorities || {}).length)

const models = computed(() => aggregate.value.models || [])
const selectedModel = computed(() => (
  models.value.find(m => m.model_key === selectedModelKey.value) || models.value[0] || {}
))
const topCapabilities = computed(() => (selectedModel.value.capabilities || []).slice(0, 10))
const selectedCapabilityLabel = computed(() => (
  topCapabilities.value.find(c => c.capability === selectedCapability.value)?.label
  || selectedCapability.value
  || '能力'
))
const filteredCases = computed(() => (
  (selectedModel.value.cases || []).filter(item => !selectedCapability.value || item.capability === selectedCapability.value)
))
const capabilityCaseCounts = computed(() => {
  const counts = {}
  for (const item of selectedModel.value.cases || []) {
    if (!item.capability) continue
    counts[item.capability] = (counts[item.capability] || 0) + 1
  }
  return counts
})
const plainStrength = computed(() => {
  const top = selectedModel.value.capabilities?.[0]
  const weak = [...(selectedModel.value.capabilities || [])].reverse().find(item => Number.isFinite(Number(item.score)))
  if (!top) return '样本还不够，暂时无法判断。'
  if (weak && Number(top.score) - Number(weak.score) >= 35) {
    return `最强项是「${top.label}」，短板可能在「${weak.label}」。`
  }
  return `整体表现比较均衡，当前最突出的是「${top.label}」。`
})
const playStyle = computed(() => {
  const top = selectedModel.value.actions?.[0]
  if (!top) return '还没有足够行动记录。'
  return `在已参与场景中，最常选择「${top.label}」，占 ${pct(top.ratio)}。`
})
const riskTone = computed(() => {
  const risk = Number(selectedModel.value.risk_action_ratio || 0)
  const wait = Number(selectedModel.value.wait_ratio || 0)
  if (risk >= 0.18) return '偏激进，愿意使用有风险的动作。'
  if (wait >= 0.18) return '偏保守，观望和等待较多。'
  return '风险控制相对稳定，进攻和保守较均衡。'
})
function authorityLabel(mode) {
  return { simulation: '模拟世界规则', external_reality: '外部真实数据', deterministic_verifier: '确定性验证器', hybrid: '真实数据 + 确定性规则' }[mode] || mode
}
const radarItems = computed(() => topCapabilities.value.slice(0, 6))
const radarPoints = computed(() => radarDots.value.map(pt => `${pt.x},${pt.y}`).join(' '))
const radarDots = computed(() => {
  const items = radarItems.value
  const count = Math.max(items.length, 3)
  return items.map((item, index) => {
    const angle = -Math.PI / 2 + index / count * Math.PI * 2
    const radius = Math.max(0, Math.min(116, Number(item.score || 0) / 100 * 116))
    return {
      label: item.label,
      x: Math.cos(angle) * radius,
      y: Math.sin(angle) * radius,
    }
  })
})

async function loadAnalysis() {
  loading.value = true
  error.value = ''
  try {
    aggregate.value = await apiGet('/operator/models/analysis', { limit_runs: 300 })
    if (!selectedModelKey.value && models.value.length) selectedModelKey.value = models.value[0].model_key
  } catch (e) {
    error.value = e.message
  } finally {
    loading.value = false
  }
}
function pct(value) {
  const n = Number(value || 0)
  return `${Math.round(n * 100)}%`
}
function fmt(value, digits = 2) {
  const n = Number(value)
  if (!Number.isFinite(n)) return '-'
  return n.toFixed(digits).replace(/\.?0+$/, '')
}
function bestCapability(model) {
  return model.capabilities?.[0] ? `${model.capabilities[0].label} ${fmt(model.capabilities[0].score, 0)}` : '-'
}
function defaultCapabilityFor(model) {
  const capabilities = model?.capabilities || []
  const cases = model?.cases || []
  const caseCounts = {}
  for (const item of cases) {
    if (!item.capability) continue
    caseCounts[item.capability] = (caseCounts[item.capability] || 0) + 1
  }
  const withEvidence = capabilities.find(item => caseCounts[item.capability] > 0)
  return withEvidence?.capability || capabilities[0]?.capability || ''
}

watch(selectedModel, model => {
  selectedCapability.value = defaultCapabilityFor(model)
}, { immediate: true })

onMounted(loadAnalysis)
</script>

<style scoped>
.analysis-root {
  height: 100vh;
  overflow: auto;
  padding: 28px 34px 40px;
  background:
    radial-gradient(900px 520px at 15% -10%, rgba(73,216,255,.16), rgba(73,216,255,0) 60%),
    radial-gradient(760px 500px at 95% 0%, rgba(255,207,90,.13), rgba(255,207,90,0) 62%),
    linear-gradient(155deg,#080b13 0%,#0b0715 56%,#05050a 100%);
  color: #edf3ff;
}
.analysis-hero {
  min-height: 150px;
  display: flex;
  align-items: flex-end;
  justify-content: space-between;
  gap: 20px;
  padding: 24px;
  border: 1px solid rgba(143,160,255,.16);
  border-radius: 18px;
  background: linear-gradient(135deg, rgba(255,255,255,.07), rgba(255,255,255,.025));
  box-shadow: 0 24px 70px rgba(0,0,0,.22);
  margin-bottom: 18px;
}
.kicker {
  color: #69dcff;
  font-size: 11px;
  font-weight: 760;
  letter-spacing: 2.4px;
}
h1, h2, p { margin: 0; }
h1 { margin-top: 6px; font-size: 32px; letter-spacing: 0; }
.analysis-hero p { margin-top: 8px; color: #98a5c0; line-height: 1.7; }
.hero-actions {
  display: flex;
  gap: 10px;
  align-items: center;
}
select, button {
  border: 1px solid rgba(255,255,255,.13);
  border-radius: 9px;
  background: rgba(255,255,255,.06);
  color: #edf3ff;
  padding: 9px 12px;
  cursor: pointer;
}
button:hover { border-color: rgba(105,220,255,.5); }
.state {
  padding: 28px;
  border: 1px dashed rgba(143,160,255,.22);
  border-radius: 14px;
  color: #98a5c0;
  background: rgba(0,0,0,.16);
}
.state.err { color: #ff8d98; }
.state.small { padding: 18px; }
.summary-grid {
  display: grid;
  grid-template-columns: 1.5fr repeat(3, 1fr);
  gap: 14px;
  margin-bottom: 14px;
}
.plain-insights {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 14px;
  margin-bottom: 14px;
}
.reading-guide {
  display: grid;
  grid-template-columns: repeat(3, minmax(0, 1fr));
  gap: 12px;
  margin-bottom: 14px;
}
.reading-guide article {
  display: grid;
  grid-template-columns: 36px 1fr;
  gap: 11px;
  align-items: center;
  padding: 14px;
  border-radius: 15px;
  border: 1px solid rgba(143,160,255,.14);
  background: rgba(0,0,0,.15);
}
.guide-dot {
  width: 36px;
  height: 36px;
  border-radius: 50%;
  position: relative;
}
.guide-dot::after {
  content: '';
  position: absolute;
  inset: 10px;
  border-radius: 50%;
  background: rgba(8,11,19,.72);
}
.guide-dot.brain { background: linear-gradient(135deg,#69dcff,#66efac); }
.guide-dot.style { background: linear-gradient(135deg,#ffd66b,#ffb34d); }
.guide-dot.proof { background: linear-gradient(135deg,#ff6fa7,#b982ff); }
.reading-guide strong { color: #fff; display: block; margin-bottom: 3px; }
.reading-guide p { color: #8f9cb7; line-height: 1.55; }
.plain-insights article {
  position: relative;
  min-height: 126px;
  padding: 18px 18px 18px 70px;
  border: 1px solid rgba(143,160,255,.14);
  border-radius: 16px;
  background: linear-gradient(145deg,rgba(255,255,255,.065),rgba(255,255,255,.025));
  box-shadow: 0 18px 60px rgba(0,0,0,.16);
}
.plain-insights h3 {
  margin: 0;
  color: #fff;
  font-size: 18px;
  line-height: 1.45;
  letter-spacing: 0;
}
.plain-insights p {
  margin-top: 8px;
  color: #8f9cb7;
  line-height: 1.6;
}
.insight-icon {
  position: absolute;
  left: 18px;
  top: 20px;
  width: 36px;
  height: 36px;
  border-radius: 13px;
}
.insight-icon::after {
  content: '';
  position: absolute;
  inset: 9px;
  border-radius: 5px;
  background: rgba(8,11,19,.72);
}
.insight-icon.brain { background: linear-gradient(135deg,#69dcff,#66efac); }
.insight-icon.style { background: linear-gradient(135deg,#ffd66b,#ffb34d); }
.insight-icon.risk { background: linear-gradient(135deg,#ff6fa7,#b982ff); }
.summary-card, .panel {
  border: 1px solid rgba(143,160,255,.14);
  border-radius: 16px;
  background: linear-gradient(145deg,rgba(255,255,255,.065),rgba(255,255,255,.025));
  box-shadow: 0 18px 60px rgba(0,0,0,.18);
}
.summary-card { padding: 18px; }
label {
  display: block;
  color: #7d8aa5;
  font-size: 11px;
  margin-bottom: 7px;
}
.summary-card h2 { color: #fff; font-size: 22px; }
.summary-card strong { display: block; color: #fff; font-size: 34px; line-height: 1; }
.summary-card p { color: #95a1bc; margin-top: 7px; }
.analysis-grid {
  display: grid;
  grid-template-columns: 1.15fr .85fr;
  gap: 14px;
  margin-bottom: 14px;
}
.panel { overflow: hidden; }
.panel-head {
  display: flex;
  justify-content: space-between;
  gap: 12px;
  padding: 18px;
  border-bottom: 1px solid rgba(255,255,255,.075);
}
.panel-head h2 { margin-top: 4px; color: #fff; font-size: 18px; }
.panel-head em { color: #8390ab; font-size: 12px; font-style: normal; }
.radar-wrap {
  display: grid;
  grid-template-columns: 300px 1fr;
  gap: 18px;
  padding: 18px;
}
.radar {
  width: 300px;
  height: 300px;
  border-radius: 16px;
  background: rgba(0,0,0,.18);
}
.radar-grid { fill: none; stroke: rgba(255,255,255,.13); stroke-width: 1; }
.radar-grid.inner { stroke: rgba(255,255,255,.08); }
.radar-fill { fill: rgba(105,220,255,.24); stroke: #69dcff; stroke-width: 3; }
.radar circle { fill: #ffd66b; }
.radar-list {
  display: flex;
  flex-direction: column;
  gap: 9px;
}
.radar-list button {
  position: relative;
  overflow: hidden;
  min-height: 42px;
  display: grid;
  grid-template-columns: 1fr auto auto;
  gap: 10px;
  text-align: left;
  background: rgba(0,0,0,.18);
}
.radar-list button.active { border-color: rgba(105,220,255,.55); }
.radar-list span, .radar-list b, .radar-list em { position: relative; z-index: 1; }
.radar-list em {
  color: #7f8da8;
  font-size: 12px;
  font-style: normal;
}
.radar-list i {
  position: absolute;
  left: 0; top: 0; bottom: 0;
  background: linear-gradient(90deg, rgba(105,220,255,.22), rgba(102,239,172,.08));
}
.behavior-stats {
  display: grid;
  grid-template-columns: repeat(3, 1fr);
  gap: 10px;
  padding: 18px;
}
.behavior-stats div {
  padding: 14px;
  border-radius: 13px;
  border: 1px solid rgba(255,255,255,.08);
  background: rgba(0,0,0,.16);
}
.behavior-stats strong { color: #fff; font-size: 28px; }
.action-list {
  padding: 0 18px 18px;
  display: flex;
  flex-direction: column;
  gap: 10px;
}
.action-list article {
  position: relative;
  overflow: hidden;
  min-height: 48px;
  border: 1px solid rgba(255,255,255,.08);
  border-radius: 12px;
  background: rgba(0,0,0,.15);
}
.action-list article > div {
  position: relative;
  z-index: 1;
  display: flex;
  justify-content: space-between;
  padding: 12px 13px;
}
.action-list strong { color: #fff; }
.action-list span { color: #8d9ab5; }
.action-list i {
  position: absolute;
  inset: 0 auto 0 0;
  background: linear-gradient(90deg, rgba(255,214,107,.24), rgba(255,111,167,.06));
}
.compare-panel { margin-bottom: 14px; }
.authority-panel { margin-bottom:14px; }
.coverage-grid { display:grid; grid-template-columns:repeat(2,minmax(0,1fr)); gap:14px; padding:16px 18px 20px; }
.coverage-grid article { border:1px solid rgba(255,255,255,.07); border-radius:10px; padding:13px; background:rgba(255,255,255,.025); }
.coverage-grid label { color:#69dcff; font-size:10px; letter-spacing:.1em; }
.coverage-grid p { display:flex; justify-content:space-between; gap:12px; margin:9px 0 0; color:#7f8ba4; font-size:11px; }
.coverage-grid b { color:#eaf0fb; font-weight:650; }
.compare-table { padding: 8px 14px 16px; }
.compare-row {
  width: 100%;
  display: grid;
  grid-template-columns: 1.4fr .55fr .55fr .65fr 1fr 1fr;
  gap: 12px;
  align-items: center;
  text-align: left;
  border: none;
  border-bottom: 1px solid rgba(255,255,255,.065);
  border-radius: 0;
  background: transparent;
  color: #ccd6ee;
}
.compare-row.head {
  color: #7d8aa5;
  font-size: 11px;
  padding: 10px 12px;
}
button.compare-row {
  padding: 12px;
}
button.compare-row.active, button.compare-row:hover {
  background: rgba(105,220,255,.08);
  border-radius: 10px;
}
.case-list { padding: 8px 18px 18px; }
.case-item {
  border-bottom: 1px solid rgba(255,255,255,.07);
  padding: 12px 0;
}
.case-item summary {
  cursor: pointer;
  display: grid;
  grid-template-columns: 1fr 56px 110px;
  gap: 12px;
  align-items: center;
}
.case-item summary span { color: #fff; }
.case-item summary b { color: #ffd66b; }
.case-item summary em { color: #8190aa; font-style: normal; }
.case-body {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 12px;
  margin-top: 12px;
}
.case-body div:last-child { grid-column: 1 / -1; }
.case-body p, pre {
  margin: 0;
  padding: 12px;
  border-radius: 10px;
  background: rgba(0,0,0,.22);
  color: #c9d4ee;
  line-height: 1.58;
}
pre {
  max-height: 280px;
  overflow: auto;
  white-space: pre-wrap;
  word-break: break-word;
  font-size: 11.5px;
}
@media (max-width: 1100px) {
  .summary-grid, .plain-insights, .reading-guide, .analysis-grid, .radar-wrap { grid-template-columns: 1fr; }
  .compare-row { grid-template-columns: 1.2fr .5fr .5fr; }
  .compare-row span:nth-child(n+5) { display: none; }
  .case-body { grid-template-columns: 1fr; }
}
</style>
