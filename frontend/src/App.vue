<template>
  <Login v-if="viewMode === 'login'" />
  <KeepAlive v-else>
    <component :is="appView" />
  </KeepAlive>
</template>

<script setup>
import { computed, h, onMounted, onUnmounted, ref, markRaw } from 'vue'
import Renderer from './renderer/Renderer.vue'
import OperatorShell from './operator/OperatorShell.vue'
import Login from './auth/Login.vue'
import { isLoggedIn, hasPermission } from './core/authStore.js'
import { getViewMode, onViewChange } from './core/viewNav.js'
import { t } from './core/i18n.js'

// 权限不足时的简单提示，不必为此新建组件文件
const NoAccess = {
  name: 'NoAccess',
  render: () => h('div', {
    style: 'height:100vh;display:flex;align-items:center;justify-content:center;'
      + 'background:#070510;color:#c7bff0;font-size:15px;'
      + "font-family:'PingFang SC','Microsoft YaHei',system-ui,sans-serif;",
  }, t('app.no_access')),
}

const viewMode = ref(getViewMode())
let stopViewListen = null

function refreshView() {
  viewMode.value = getViewMode()
}

onMounted(() => {
  stopViewListen = onViewChange(refreshView)
})
onUnmounted(() => {
  stopViewListen?.()
})

// KeepAlive 按组件类型缓存：观众端切运营台时不销毁 WebSocket / 盘面演绎
const appView = computed(() => {
  if (!isLoggedIn() || viewMode.value === 'login') return markRaw(Login)
  if (viewMode.value === 'operator') {
    return hasPermission('access_operator') ? markRaw(OperatorShell) : markRaw(NoAccess)
  }
  return hasPermission('access_viewer') ? markRaw(Renderer) : markRaw(NoAccess)
})
</script>

<style>
* { margin: 0; padding: 0; box-sizing: border-box; }
body {
  background: #070510;
  overflow: hidden;
  -webkit-font-smoothing: antialiased;
  -moz-osx-font-smoothing: grayscale;
}
::selection { background: rgba(139,63,251,.3); color: #fff; }
</style>
