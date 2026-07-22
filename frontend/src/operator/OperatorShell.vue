<template>
  <div class="op-shell">
    <aside class="op-sidebar">
      <div class="op-brand">
        <div class="op-logo">AI</div>
        <div>
          <div class="op-title">AI World</div>
          <div class="op-subtitle">{{ tr('运营后台', 'OPERATIONS') }}</div>
        </div>
      </div>
      <button
        v-if="canAccessViewer"
        class="op-switch-btn"
        :title="tr('切换到观众端（无需重新登录）', 'Switch to viewer without signing in again')"
        @click="goToViewer"
      >
        <svg viewBox="0 0 20 20" width="14" height="14" aria-hidden="true">
          <path d="M12 4L6 10L12 16" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round" fill="none"/>
        </svg>
        <span class="op-switch-icon" aria-hidden="true">
          <svg viewBox="0 0 24 24" width="16" height="16"><path d="M2 12s3.5-7 10-7 10 7 10 7-3.5 7-10 7S2 12 2 12z" stroke="currentColor" stroke-width="1.5" fill="none"/><circle cx="12" cy="12" r="3" fill="currentColor" opacity=".7"/></svg>
        </span>
        <span class="op-switch-label">{{ tr('观众端', 'Viewer') }}</span>
        <span class="op-switch-shine"></span>
      </button>
      <nav class="op-nav">
        <template v-for="group in NAV" :key="group.label">
          <div class="op-nav-group">{{ group.label }}</div>
          <button
            v-for="item in group.items"
            :key="item.key"
            class="op-nav-item"
            :class="{ active: section === item.key, disabled: !item.ready }"
            @click="item.ready && go(item.key)"
          >
            <span>{{ item.label }}</span>
            <span v-if="!item.ready" class="op-soon">{{ tr('即将上线', 'Soon') }}</span>
          </button>
        </template>
      </nav>
      <div class="op-sidebar-foot">
        <UserAccountMenu variant="sidebar" />
      </div>
    </aside>

    <main class="op-main">
      <Console v-if="section === 'live'" />
      <RunArchive v-else-if="section === 'archive'" :run-id="runId" />
      <ModelAssessment v-else-if="section === 'assessment'" />
      <DataFactory v-else-if="section === 'factory'" />
      <UserManagement v-else-if="section === 'users'" />
      <div v-else class="op-placeholder">
        <h2>{{ currentLabel }}</h2>
        <p>{{ tr('该模块尚未实现，将在后续迭代上线。', 'This module is planned for a future release.') }}</p>
      </div>
    </main>
  </div>
</template>

<script setup>
import { ref, computed, onMounted, onUnmounted } from 'vue'
import Console from './Console.vue'
import RunArchive from './archive/RunArchive.vue'
import ModelAssessment from './analysis/ModelAssessment.vue'
import DataFactory from './factory/DataFactory.vue'
import UserManagement from './UserManagement.vue'
import UserAccountMenu from '../components/UserAccountMenu.vue'
import { getCurrentUser, hasPermission } from '../core/authStore.js'
import { navigateView } from '../core/viewNav.js'
import { tr } from '../core/i18n.js'

defineOptions({ name: 'OperatorShell' })

// 有观众端权限时，运营台露出一个直达入口——同源共享登录态，切换不用重新登录
const canAccessViewer = hasPermission('access_viewer')
function goToViewer() {
  navigateView('viewer')
}

const NAV = computed(() => [
  { label: tr('实时', 'LIVE'), items: [
    { key: 'live', label: tr('实时评测', 'Live evaluation'), ready: true },
  ] },
  { label: tr('档案', 'ARCHIVE'), items: [
    { key: 'archive', label: tr('评测档案', 'Evaluation archive'), ready: true },
  ] },
  { label: tr('分析', 'ANALYSIS'), items: [
    { key: 'assessment', label: tr('模型分析', 'Model analysis'), ready: true },
  ] },
  // 训练数据工厂：有 export_data 权限或超管可见
  ...((hasPermission('export_data') || getCurrentUser()?.is_admin) ? [{ label: tr('数据', 'DATA'), items: [
    { key: 'factory', label: tr('训练数据', 'Training data'), ready: true },
  ] }] : []),
  // 用户管理仅超管可见——is_admin 之外没有任何权限能打开这一入口
  ...(getCurrentUser()?.is_admin ? [{ label: tr('系统', 'SYSTEM'), items: [
    { key: 'users', label: tr('用户管理', 'User management'), ready: true },
  ] }] : []),
])

const section = ref('live')
const runId = ref(null)

// 轻量 hash 路由：#/archive 或 #/archive/run_xxx，刷新/后退可恢复。
function parseHash() {
  const raw = (window.location.hash || '').replace(/^#\/?/, '')
  const [sec, rid] = raw.split('/')
  section.value = sec || 'live'
  runId.value = rid || null
}

function go(key) {
  window.location.hash = `#/${key}`
}

const currentLabel = computed(() => {
  for (const g of NAV.value) {
    const hit = g.items.find(i => i.key === section.value)
    if (hit) return hit.label
  }
  return section.value
})

onMounted(() => {
  parseHash()
  window.addEventListener('hashchange', parseHash)
})
onUnmounted(() => window.removeEventListener('hashchange', parseHash))
</script>

<style scoped>
.op-shell {
  display: flex;
  height: 100vh;
  background: #070a10;
  color: #e8eef7;
  font-family: 'PingFang SC','Microsoft YaHei',system-ui,sans-serif;
  font-size: 13px;
}
.op-sidebar {
  width: 188px;
  flex-shrink: 0;
  background: linear-gradient(180deg,#0d1320,#080c14);
  border-right: 1px solid rgba(148,163,184,.10);
  padding: 20px 12px;
  display: flex;
  flex-direction: column;
  gap: 6px;
  overflow-y: auto;
}
.op-brand { display: flex; align-items: center; gap: 10px; margin-bottom: 24px; padding: 0 6px; }
.op-switch-btn {
  position: relative;
  overflow: hidden;
  width: 100%;
  margin-bottom: 18px;
  padding: 10px 12px;
  border-radius: 10px;
  border: 1px solid rgba(103,232,249,.16);
  background:
    linear-gradient(135deg, rgba(103,232,249,.07) 0%, rgba(94,234,212,.035) 100%);
  color: #94d8e5;
  font-size: 12px; font-weight: 700; letter-spacing: .04em;
  cursor: pointer;
  display: flex; align-items: center; gap: 8px;
  transition: transform .18s, box-shadow .18s, border-color .18s;
  box-shadow: 0 2px 10px rgba(105,220,255,.06);
}
.op-switch-btn svg { flex-shrink: 0; transition: transform .2s; }
.op-switch-btn:hover {
  transform: translateX(-2px);
  border-color: rgba(105,220,255,.5);
  color: #eafaff;
  box-shadow: 0 4px 18px rgba(105,220,255,.22);
}
.op-switch-btn:hover > svg:first-child { transform: translateX(-3px); }
.op-switch-icon { display: inline-flex; opacity: .85; }
.op-switch-label { flex: 1; text-align: left; }
.op-switch-shine {
  position: absolute; top: 0; left: -60%;
  width: 40%; height: 100%;
  background: linear-gradient(90deg, transparent, rgba(255,255,255,.25), transparent);
  transform: skewX(-20deg);
  transition: left .5s ease;
  pointer-events: none;
}
.op-switch-btn:hover .op-switch-shine { left: 120%; }
.op-logo {
  width: 36px; height: 36px; border-radius: 11px;
  background: linear-gradient(145deg,#3d74d8,#46d7dc);
  display: flex; align-items: center; justify-content: center;
  font-weight: 700; color: #fff; letter-spacing: 1px;
}
.op-title { font-size: 14px; font-weight: 680; }
.op-subtitle { margin-top: 2px; font-size: 10px; color: #617087; }
.op-nav-group {
  font-size: 9px; color: #4e5b70; letter-spacing: 2px;
  margin: 14px 8px 4px;
}
.op-nav-item {
  width: 100%; text-align: left;
  display: flex; align-items: center; justify-content: space-between;
  padding: 9px 12px; border-radius: 8px;
  background: transparent; border: 1px solid transparent; color: #9ba8bc;
  cursor: pointer; font-size: 12px; transition: background .15s, border-color .15s;
}
.op-nav-item:hover:not(.disabled) { background: rgba(103,232,249,.045); color: #d5e4ee; }
.op-nav-item.active {
  border-color: rgba(103,232,249,.12);
  background: rgba(103,232,249,.08);
  color: #82e4ef;
  box-shadow: inset 2px 0 0 #67e8f9;
}
.op-nav-item.disabled { color: #5a5378; cursor: default; }
.op-sidebar-foot {
  margin-top: auto;
  padding-top: 12px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}
.op-soon {
  font-size: 10px; color: #6b6190;
  border: 1px solid rgba(107,97,144,.4); border-radius: 4px; padding: 1px 5px;
}
.op-main { flex: 1; min-width: 0; overflow: hidden; }
.op-placeholder {
  height: 100%; display: flex; flex-direction: column;
  align-items: center; justify-content: center; gap: 10px; color: #8b80b0;
}
.op-placeholder h2 { font-size: 22px; color: #c7bff0; }
</style>
