<template>
  <div class="pc-overlay" @click.self="$emit('close')">
    <div class="pc-dialog">
      <header class="pc-head">
        <h2>个人中心</h2>
        <button class="pc-close" @click="$emit('close')" aria-label="关闭">×</button>
      </header>

      <div class="pc-body">
        <section class="pc-profile">
          <div class="pc-avatar">{{ avatarLetter }}</div>
          <div class="pc-meta">
            <div class="pc-name">{{ user.display_name || user.username }}</div>
            <div class="pc-username">@{{ user.username }}</div>
            <span v-if="user.is_admin" class="pc-badge admin">超级管理员</span>
            <span v-else class="pc-badge">普通用户</span>
          </div>
        </section>

        <section class="pc-section">
          <h3>账号信息</h3>
          <dl class="pc-dl">
            <dt>用户 ID</dt>
            <dd>{{ user.user_id }}</dd>
            <dt>数据权限</dt>
            <dd>仅可查看本人对局数据</dd>
          </dl>
        </section>

        <section class="pc-section">
          <h3>功能权限</h3>
          <p v-if="user.is_admin" class="pc-hint">超级管理员拥有全部功能权限。</p>
          <div v-else-if="permLabels.length" class="pc-tags">
            <span v-for="label in permLabels" :key="label" class="pc-tag">{{ label }}</span>
          </div>
          <p v-else class="pc-hint">暂未分配功能权限，请联系管理员。</p>
        </section>

        <section class="pc-section">
          <h3>修改密码</h3>
          <div class="pc-form">
            <input v-model="newPassword" type="password" placeholder="新密码（至少 6 位）" />
            <input v-model="confirmPassword" type="password" placeholder="确认新密码" />
          </div>
          <p v-if="pwdMsg" class="pc-msg" :class="{ err: pwdErr }">{{ pwdMsg }}</p>
          <button class="pc-btn primary" :disabled="pwdSaving" @click="submitPassword">
            {{ pwdSaving ? '保存中…' : '更新密码' }}
          </button>
        </section>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, computed, onMounted } from 'vue'
import { authedFetch, getCurrentUser, refreshCurrentUser } from '../core/authStore.js'

defineEmits(['close'])

const API_BASE = import.meta.env.VITE_API_BASE || import.meta.env.VITE_API_URL || 'http://localhost:8001'

const user = ref(getCurrentUser() || {})
const catalog = ref([])
const newPassword = ref('')
const confirmPassword = ref('')
const pwdMsg = ref('')
const pwdErr = ref(false)
const pwdSaving = ref(false)

const avatarLetter = computed(() => {
  const name = user.value.display_name || user.value.username || '?'
  return name.charAt(0).toUpperCase()
})

const permLabelMap = computed(() => {
  const map = {}
  for (const item of catalog.value) map[item.key] = item.label
  return map
})

const permLabels = computed(() => {
  if (user.value.is_admin) return []
  return (user.value.permissions || []).map(k => permLabelMap.value[k] || k)
})

async function load() {
  const fresh = await refreshCurrentUser()
  if (fresh) user.value = fresh
  try {
    const resp = await authedFetch(`${API_BASE}/admin/permissions/catalog`)
    if (resp.ok) catalog.value = await resp.json()
  } catch (_) { /* 非关键 */ }
}

async function submitPassword() {
  pwdMsg.value = ''
  pwdErr.value = false
  if (newPassword.value.length < 6) {
    pwdMsg.value = '密码至少 6 位'
    pwdErr.value = true
    return
  }
  if (newPassword.value !== confirmPassword.value) {
    pwdMsg.value = '两次输入的密码不一致'
    pwdErr.value = true
    return
  }
  pwdSaving.value = true
  try {
    const resp = await authedFetch(`${API_BASE}/auth/me/password`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_password: newPassword.value }),
    })
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) throw new Error(data.detail || `修改失败(${resp.status})`)
    pwdMsg.value = '密码已更新'
    newPassword.value = ''
    confirmPassword.value = ''
  } catch (e) {
    pwdMsg.value = e.message
    pwdErr.value = true
  } finally {
    pwdSaving.value = false
  }
}

onMounted(load)
</script>

<style scoped>
.pc-overlay {
  position: fixed;
  inset: 0;
  z-index: 2000;
  background: rgba(6, 4, 18, 0.72);
  display: flex;
  align-items: center;
  justify-content: center;
  padding: 24px;
}

.pc-dialog {
  width: 100%;
  max-width: 480px;
  max-height: 90vh;
  overflow-y: auto;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: #16102c;
  color: #e8e4f4;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.45);
}

.pc-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 20px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.pc-head h2 {
  margin: 0;
  font-size: 18px;
}

.pc-close {
  border: none;
  background: none;
  color: #9b93b8;
  font-size: 24px;
  cursor: pointer;
  line-height: 1;
}

.pc-body { padding: 16px 20px 22px; }

.pc-profile {
  display: flex;
  align-items: center;
  gap: 14px;
  margin-bottom: 20px;
}

.pc-avatar {
  width: 52px;
  height: 52px;
  border-radius: 50%;
  background: linear-gradient(135deg, #69dcff, #8b5bff);
  color: #06121f;
  font-size: 22px;
  font-weight: 800;
  display: flex;
  align-items: center;
  justify-content: center;
}

.pc-name { font-size: 16px; font-weight: 700; color: #f5f2ff; }
.pc-username { font-size: 12px; color: #8a82a6; margin: 2px 0 6px; }

.pc-badge {
  display: inline-block;
  font-size: 11px;
  padding: 2px 8px;
  border-radius: 999px;
  background: rgba(255, 255, 255, 0.08);
  color: #c5bddf;
}

.pc-badge.admin {
  background: rgba(255, 196, 87, 0.14);
  color: #ffd060;
}

.pc-section {
  margin-bottom: 18px;
  padding-top: 4px;
}

.pc-section h3 {
  margin: 0 0 10px;
  font-size: 13px;
  color: #a59dc4;
  font-weight: 700;
}

.pc-dl {
  margin: 0;
  display: grid;
  grid-template-columns: 88px 1fr;
  gap: 8px 12px;
  font-size: 13px;
}

.pc-dl dt { color: #7d759c; }
.pc-dl dd { margin: 0; color: #e0daf0; word-break: break-all; }

.pc-hint { margin: 0; font-size: 12px; color: #8a82a6; line-height: 1.5; }

.pc-tags { display: flex; flex-wrap: wrap; gap: 6px; }

.pc-tag {
  font-size: 11px;
  padding: 3px 8px;
  border-radius: 6px;
  background: rgba(105, 220, 255, 0.1);
  color: #8edfff;
}

.pc-form {
  display: flex;
  flex-direction: column;
  gap: 8px;
  margin-bottom: 10px;
}

.pc-form input {
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.28);
  color: #edf0ff;
  padding: 9px 11px;
  font-size: 13px;
  outline: none;
}

.pc-form input:focus { border-color: rgba(105, 220, 255, 0.45); }

.pc-msg { margin: 0 0 8px; font-size: 12px; color: #8be28b; }
.pc-msg.err { color: #ff7b72; }

.pc-btn {
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(255, 255, 255, 0.04);
  color: #d8d2ef;
  font-size: 13px;
  padding: 8px 16px;
  border-radius: 8px;
  cursor: pointer;
}

.pc-btn.primary {
  background: linear-gradient(135deg, #69dcff, #5b8bff);
  color: #06121f;
  font-weight: 700;
  border: none;
}

.pc-btn:disabled { opacity: 0.5; cursor: not-allowed; }
</style>
