<template>
  <div class="df-root">
    <header class="df-hero">
      <div>
        <span class="kicker">{{ tr('Agent 训练数据工厂', 'AGENT TRAINING DATA FACTORY') }}</span>
        <h1>{{ tr('训练数据导出', 'Training data export') }}</h1>
        <p>{{ tr('把对局沉淀成优秀轨迹、偏好对、完整对局、能力样本和 OS 2.0 可追溯因果链。', 'Convert evaluations into high-quality trajectories, preference pairs, episodes, capability samples, and OS 2.0 causal traces.') }}</p>
      </div>
      <button class="df-refresh" @click="loadRuns" :disabled="loadingRuns">
        {{ loadingRuns ? tr('加载中…', 'Loading…') : tr('刷新对局', 'Refresh runs') }}
      </button>
    </header>

    <div v-if="error" class="df-state err">{{ error }}</div>

    <div class="df-grid">
      <!-- 左：选对局 -->
      <section class="df-panel">
        <h2>1 · {{ tr('选择对局', 'Select runs') }}</h2>
        <p class="df-hint">{{ tr('勾选要导出的对局。良品率低的局（大量失败/兜底）建议不选。', 'Select runs to export. Exclude low-quality runs with frequent failures or fallbacks.') }}</p>
        <div v-if="!runs.length" class="df-empty">{{ tr('暂无对局，跑完至少一局后出现。', 'No runs yet. Complete at least one evaluation.') }}</div>
        <label v-for="r in runs" :key="r.run_id" class="df-run"
               :class="{ dim: r.good_rate === 0 }">
          <input type="checkbox" :value="r.run_id" v-model="selected" />
          <span class="df-run-id">{{ r.run_id }}</span>
          <span class="df-run-rate" :class="rateClass(r.good_rate)">
            {{ tr('良品', 'Clean') }} {{ r.clean_agents }}/{{ r.total_agents }}
          </span>
        </label>
      </section>

      <!-- 中：筛选 + 预览 -->
      <section class="df-panel wide">
        <h2>2 · {{ tr('预览样本（决策卡）', 'Preview samples') }}</h2>
        <div class="df-filters">
          <label>{{ tr('数据类型', 'Data type') }}
            <select v-model="fmt">
              <option value="sft">{{ tr('优秀轨迹（SFT）', 'High-quality trajectories (SFT)') }}</option>
              <option value="dpo">{{ tr('偏好对（DPO）', 'Preference pairs (DPO)') }}</option>
              <option value="episodes">{{ tr('完整对局（RL）', 'Complete episodes (RL)') }}</option>
              <option value="eval">{{ tr('能力评测', 'Capability evaluation') }}</option>
              <option value="trace">{{ tr('OS 2.0 可追溯链路', 'OS 2.0 trace chain') }}</option>
            </select>
          </label>
          <button class="df-btn" @click="doPreview" :disabled="!selected.length || previewing">
            {{ previewing ? tr('预览中…', 'Loading preview…') : tr('预览', 'Preview') }}
          </button>
          <span v-if="previewTotal !== null" class="df-count">{{ previewTotal }} {{ tr('条', 'samples') }}</span>
        </div>

        <div v-if="!cards.length" class="df-empty">{{ tr('选好对局与类型后点“预览”，这里会列出决策卡。', 'Select runs and a data type, then preview the decision cards.') }}</div>
        <div v-else class="df-cards">
          <article v-for="c in cards" :key="c.sample_id" class="df-card">
            <template v-if="c.类型 === 'OS2可追溯链路'">
              <div class="df-card-tag trace">OS 2.0 TRACE</div>
              <p class="df-sit">{{ tr('第', 'Cycle') }} {{ c.回合 }}: {{ c.世界行动 }} {{ tr('个行动', 'actions') }} → {{ c.世界事件 }} {{ tr('个事件', 'events') }} → {{ c.结算记录 }} {{ tr('条结算', 'settlements') }}</p>
              <p class="df-why">{{ tr('外部事实', 'External facts') }} {{ c.外部事实 }} · {{ tr('结算权限', 'Authority') }} {{ (c.结算权限 || []).join(' / ') || tr('无', 'None') }} · {{ tr('导演计划', 'Director plan') }} {{ c.导演计划 ? tr('已生成', 'Generated') : tr('无', 'None') }}</p>
            </template>
            <template v-else-if="c.对照类型">
              <div class="df-card-tag contrast">{{ c.对照类型 }}</div>
              <div class="df-vs">
                <div class="vs-good"><b>{{ tr('更优', 'Preferred') }}</b> {{ c['更好(chosen)'] }}</div>
                <div class="vs-bad"><b>{{ tr('更差', 'Rejected') }}</b> {{ c['更差(rejected)'] }}</div>
              </div>
              <p class="df-why">{{ c['为什么更好'] }}</p>
            </template>
            <template v-else-if="c.整局概述">
              <div class="df-card-tag ep">{{ tr('完整对局', 'Complete episode') }}</div>
              <p class="df-sit">{{ c.整局概述 }}</p>
              <p class="df-why">{{ c.终局 }} · {{ tr('客观奖励', 'Objective reward') }} {{ c['客观奖励占比'] }} · {{ c.步数 }} {{ tr('步', 'steps') }}</p>
            </template>
            <template v-else-if="c.类型 === '能力探针作答'">
              <div class="df-card-tag eval">{{ tr('能力评测', 'Capability evaluation') }}</div>
              <p class="df-sit">{{ c.作答摘要 }}</p>
              <p class="df-why">{{ tr('模型：', 'Model: ') }}{{ c.模型 }}</p>
            </template>
            <template v-else>
              <div class="df-card-head">
                <span class="df-card-tag sft">{{ tr('优秀轨迹', 'High-quality trajectory') }}</span>
                <span class="df-card-meta">{{ tr('契合度', 'Fit') }} {{ pct(c.元信息?.situational_fit) }} · {{ c.元信息?.reward_purity }}</span>
              </div>
              <p class="df-sit">📍 {{ c.局面 }}</p>
              <p class="df-dec">🎯 {{ c.决策 }}</p>
              <ul class="df-reasons">
                <li v-for="(r, i) in c.为什么" :key="i">{{ r }}</li>
              </ul>
              <p v-if="c.证据?.length" class="df-evi">{{ tr('证据：', 'Evidence: ') }}{{ c.证据.join('；') }}</p>
            </template>
          </article>
        </div>
      </section>

      <!-- 右：导出 + 数据集 -->
      <section class="df-panel">
        <h2>3 · {{ tr('导出数据集', 'Export dataset') }}</h2>
        <label class="df-name">{{ tr('数据集名称', 'Dataset name') }}
          <input v-model="datasetName" :placeholder="tr('如：AI World 跨场景轨迹 v1', 'e.g. AI World cross-scenario traces v1')" />
        </label>
        <button class="df-btn primary" @click="doExport" :disabled="!selected.length || exporting">
          {{ exporting ? tr('导出封装中…', 'Packaging…') : tr('导出 + 封装', 'Export + package') }}
        </button>
        <p v-if="exportResult" class="df-export-ok">
          ✅ {{ exportResult.total_samples }} {{ tr('条', 'samples') }} · {{ tr('良品率', 'clean rate') }} {{ pct(exportResult.good_rate) }}
        </p>

        <h3>{{ tr('已导出数据集', 'Exported datasets') }}</h3>
        <div v-if="!datasets.length" class="df-empty sm">{{ tr('还没有数据集。', 'No datasets yet.') }}</div>
        <article v-for="d in datasets" :key="d.dataset_id" class="df-dataset">
          <div class="df-ds-head">
            <b>{{ d.name }}</b>
            <span>{{ d.total_samples }} {{ tr('条', 'samples') }} · {{ tr('良品', 'clean') }} {{ pct(d.good_rate) }}</span>
          </div>
          <div class="df-ds-actions">
            <button class="df-link" @click="viewCard(d.dataset_id)">{{ tr('数据卡', 'Data card') }}</button>
            <a class="df-link" :href="fileUrl(d.dataset_id, 'sft_train.jsonl')" target="_blank">SFT</a>
            <a class="df-link" :href="fileUrl(d.dataset_id, 'dpo_train.jsonl')" target="_blank">DPO</a>
            <a class="df-link" :href="fileUrl(d.dataset_id, 'os2_traces.jsonl')" target="_blank">OS2 Trace</a>
            <a class="df-link" :href="fileUrl(d.dataset_id, 'dataset_manifest.json')" target="_blank">manifest</a>
          </div>
        </article>
      </section>
    </div>

    <!-- 数据卡弹层 -->
    <div v-if="cardMarkdown" class="df-modal" @click.self="cardMarkdown = ''">
      <div class="df-modal-body">
        <button class="df-modal-close" @click="cardMarkdown = ''">×</button>
        <pre>{{ cardMarkdown }}</pre>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, onMounted } from 'vue'
import { apiGet, apiPost, API_BASE } from '../api.js'
import { getToken } from '../../core/authStore.js'
import { tr } from '../../core/i18n.js'

const runs = ref([])
const datasets = ref([])
const selected = ref([])
const fmt = ref('sft')
const cards = ref([])
const previewTotal = ref(null)
const datasetName = ref('')
const exportResult = ref(null)
const cardMarkdown = ref('')

const loadingRuns = ref(false)
const previewing = ref(false)
const exporting = ref(false)
const error = ref('')

function pct(v) { return v == null ? '—' : Math.round(v * 100) + '%' }
function rateClass(r) { return r >= 0.6 ? 'good' : r > 0 ? 'mid' : 'bad' }

async function loadRuns() {
  loadingRuns.value = true; error.value = ''
  try {
    const d = await apiGet('/factory/runs')
    runs.value = d.runs || []
    await loadDatasets()
  } catch (e) { error.value = e.message } finally { loadingRuns.value = false }
}

async function loadDatasets() {
  try { datasets.value = (await apiGet('/factory/datasets')).datasets || [] }
  catch (_) { /* ignore */ }
}

async function doPreview() {
  previewing.value = true; error.value = ''; cards.value = []
  try {
    const d = await apiPost('/factory/preview', {
      run_ids: selected.value, fmt: fmt.value, limit: 30,
    })
    cards.value = d.cards || []
    previewTotal.value = d.total
  } catch (e) { error.value = e.message } finally { previewing.value = false }
}

async function doExport() {
  exporting.value = true; error.value = ''; exportResult.value = null
  try {
    const d = await apiPost('/factory/export', {
      run_ids: selected.value,
      name: datasetName.value || 'ai-world-dataset',
    })
    exportResult.value = d
    await loadDatasets()
  } catch (e) { error.value = e.message } finally { exporting.value = false }
}

async function viewCard(dsId) {
  try {
    const d = await apiGet(`/factory/datasets/${dsId}/card`)
    cardMarkdown.value = d.card_markdown
  } catch (e) { error.value = e.message }
}

function fileUrl(dsId, name) {
  const t = getToken()
  return `${API_BASE}/factory/datasets/${dsId}/file?name=${encodeURIComponent(name)}&token=${encodeURIComponent(t)}`
}

onMounted(loadRuns)
</script>

<style scoped>
.df-root { padding: 24px 28px; color: #dbe2f0; font-family: 'PingFang SC', system-ui, sans-serif; }
.df-hero { display: flex; justify-content: space-between; align-items: flex-start; margin-bottom: 20px; gap: 16px; }
.kicker { font-size: 11px; letter-spacing: .2em; color: #69dcff; font-weight: 800; }
.df-hero h1 { margin: 6px 0 6px; font-size: 22px; color: #eef3ff; }
.df-hero p { margin: 0; font-size: 13px; color: #93a0bd; max-width: 640px; line-height: 1.6; }
.df-refresh { padding: 8px 16px; border-radius: 8px; border: 1px solid rgba(105,220,255,.3);
  background: rgba(105,220,255,.08); color: #8cecff; cursor: pointer; font-weight: 600; height: fit-content; }
.df-refresh:disabled { opacity: .5; }

.df-state.err { padding: 10px 14px; background: rgba(255,95,82,.1); border: 1px solid rgba(255,95,82,.3);
  border-radius: 8px; color: #ff8a80; margin-bottom: 16px; font-size: 13px; }

.df-grid { display: grid; grid-template-columns: 260px 1fr 300px; gap: 18px; align-items: start; }
@media (max-width: 1200px) { .df-grid { grid-template-columns: 1fr; } }

.df-panel { background: rgba(255,255,255,.03); border: 1px solid rgba(255,255,255,.07);
  border-radius: 14px; padding: 18px; }
.df-panel h2 { margin: 0 0 4px; font-size: 15px; color: #eef3ff; }
.df-panel h3 { margin: 20px 0 8px; font-size: 13px; color: #b9c4dd; }
.df-hint { margin: 0 0 12px; font-size: 12px; color: #7d8aa8; line-height: 1.5; }
.df-empty { font-size: 12px; color: #6b7695; padding: 14px 0; }
.df-empty.sm { padding: 6px 0; }

.df-run { display: flex; align-items: center; gap: 8px; padding: 8px 6px; border-radius: 7px;
  cursor: pointer; font-size: 12px; }
.df-run:hover { background: rgba(255,255,255,.04); }
.df-run.dim { opacity: .5; }
.df-run-id { flex: 1; font-family: ui-monospace, monospace; color: #c3ccdf; }
.df-run-rate { font-size: 11px; padding: 2px 7px; border-radius: 10px; }
.df-run-rate.good { background: rgba(86,211,100,.16); color: #7ee08a; }
.df-run-rate.mid { background: rgba(240,180,60,.16); color: #f0c674; }
.df-run-rate.bad { background: rgba(255,95,82,.14); color: #ff8a80; }

.df-filters { display: flex; gap: 10px; align-items: center; margin-bottom: 14px; flex-wrap: wrap; }
.df-filters label { font-size: 12px; color: #93a0bd; display: flex; flex-direction: column; gap: 4px; }
.df-filters select, .df-name input { background: rgba(0,0,0,.3); border: 1px solid rgba(255,255,255,.12);
  border-radius: 7px; color: #eef3ff; padding: 7px 10px; font-size: 13px; }
.df-count { font-size: 12px; color: #69dcff; }

.df-btn { padding: 8px 16px; border-radius: 8px; border: 1px solid rgba(105,220,255,.3);
  background: rgba(105,220,255,.08); color: #8cecff; cursor: pointer; font-weight: 600; font-size: 13px; }
.df-btn.primary { width: 100%; margin-top: 10px; background: linear-gradient(135deg,#69dcff,#5b8bff);
  color: #06121f; border: none; }
.df-btn:disabled { opacity: .45; cursor: default; }

.df-cards { display: flex; flex-direction: column; gap: 12px; max-height: 620px; overflow-y: auto; }
.df-card { background: rgba(0,0,0,.22); border: 1px solid rgba(255,255,255,.06);
  border-radius: 10px; padding: 13px 15px; }
.df-card-head { display: flex; justify-content: space-between; align-items: center; margin-bottom: 8px; }
.df-card-tag { font-size: 10px; font-weight: 700; padding: 2px 8px; border-radius: 8px; letter-spacing: .04em; }
.df-card-tag.sft { background: rgba(105,220,255,.16); color: #8cecff; }
.df-card-tag.contrast { background: rgba(180,120,255,.16); color: #c9a8ff; margin-bottom: 8px; display: inline-block; }
.df-card-tag.ep { background: rgba(86,211,100,.16); color: #7ee08a; margin-bottom: 8px; display: inline-block; }
.df-card-tag.eval { background: rgba(240,180,60,.16); color: #f0c674; margin-bottom: 8px; display: inline-block; }
.df-card-tag.trace { background: rgba(80,225,177,.16); color: #77e8bf; margin-bottom:8px; display:inline-block; }
.df-card-meta { font-size: 11px; color: #7d8aa8; }
.df-sit { margin: 4px 0; font-size: 13px; color: #d5deef; line-height: 1.5; }
.df-dec { margin: 6px 0; font-size: 12px; color: #a9b5d0; line-height: 1.5; }
.df-reasons { margin: 8px 0 0; padding-left: 16px; }
.df-reasons li { font-size: 12px; color: #93a0bd; line-height: 1.6; }
.df-evi { margin: 8px 0 0; font-size: 11px; color: #69dcff; }
.df-vs { display: flex; flex-direction: column; gap: 5px; }
.vs-good { font-size: 12px; color: #7ee08a; }
.vs-bad { font-size: 12px; color: #ff8a80; }
.df-vs b { margin-right: 6px; opacity: .8; }
.df-why { margin: 8px 0 0; font-size: 12px; color: #a9b5d0; line-height: 1.5; }

.df-name { display: flex; flex-direction: column; gap: 5px; font-size: 12px; color: #93a0bd; }
.df-export-ok { margin: 10px 0 0; font-size: 12px; color: #7ee08a; }

.df-dataset { background: rgba(0,0,0,.2); border: 1px solid rgba(255,255,255,.06);
  border-radius: 9px; padding: 11px 13px; margin-bottom: 9px; }
.df-ds-head { display: flex; justify-content: space-between; align-items: baseline; margin-bottom: 8px; }
.df-ds-head b { font-size: 13px; color: #eef3ff; }
.df-ds-head span { font-size: 11px; color: #7d8aa8; }
.df-ds-actions { display: flex; gap: 8px; flex-wrap: wrap; }
.df-link { font-size: 11px; color: #8cecff; text-decoration: none; background: rgba(105,220,255,.1);
  padding: 3px 9px; border-radius: 6px; border: none; cursor: pointer; }
.df-link:hover { background: rgba(105,220,255,.2); }

.df-modal { position: fixed; inset: 0; background: rgba(0,0,0,.6); display: flex;
  align-items: center; justify-content: center; z-index: 50; }
.df-modal-body { position: relative; background: #0f1428; border: 1px solid rgba(255,255,255,.12);
  border-radius: 14px; padding: 24px; max-width: 720px; max-height: 80vh; overflow-y: auto; }
.df-modal-body pre { margin: 0; white-space: pre-wrap; font-size: 13px; color: #d5deef; line-height: 1.6;
  font-family: 'PingFang SC', system-ui, sans-serif; }
.df-modal-close { position: absolute; top: 12px; right: 16px; background: none; border: none;
  color: #93a0bd; font-size: 24px; cursor: pointer; }
</style>
