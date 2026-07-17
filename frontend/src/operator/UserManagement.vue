<template>
  <div class="um-page">
    <header class="um-page-head">
      <div>
        <h1>用户管理</h1>
        <p>管理系统账号与功能权限。数据权限固定为「仅查看本人对局」，不在此配置。</p>
      </div>
      <button class="um-btn um-btn-primary" @click="openCreate">+ 新增用户</button>
    </header>

    <section class="um-toolbar">
      <div class="um-search">
        <svg viewBox="0 0 20 20" width="16" height="16" aria-hidden="true">
          <circle cx="8.5" cy="8.5" r="5.5" stroke="currentColor" stroke-width="1.5" fill="none"/>
          <path d="M13 13l4 4" stroke="currentColor" stroke-width="1.5" stroke-linecap="round"/>
        </svg>
        <input v-model="keyword" type="search" placeholder="搜索用户名或显示名…" />
      </div>
      <span class="um-count">共 {{ filteredUsers.length }} 人</span>
    </section>

    <section class="um-table-wrap">
      <table class="um-table">
        <thead>
          <tr>
            <th>用户名</th>
            <th>显示名</th>
            <th>角色</th>
            <th>功能权限</th>
            <th>创建时间</th>
            <th class="col-actions">操作</th>
          </tr>
        </thead>
        <tbody>
          <tr v-if="loading">
            <td colspan="6" class="um-empty-cell">加载中…</td>
          </tr>
          <tr v-else-if="!filteredUsers.length">
            <td colspan="6" class="um-empty-cell">暂无匹配用户</td>
          </tr>
          <tr v-for="u in filteredUsers" :key="u.user_id">
            <td>
              <span class="um-username">{{ u.username }}</span>
            </td>
            <td>{{ u.display_name || '—' }}</td>
            <td>
              <span v-if="u.is_admin" class="um-tag um-tag-admin">超级管理员</span>
              <span v-else class="um-tag">普通用户</span>
            </td>
            <td>
              <span v-if="u.is_admin" class="um-perm-hint">全部权限</span>
              <div v-else class="um-perm-tags">
                <span
                  v-for="label in permLabels(u.permissions).slice(0, 3)"
                  :key="label"
                  class="um-tag um-tag-perm"
                >{{ label }}</span>
                <span
                  v-if="(u.permissions || []).length > 3"
                  class="um-tag um-tag-more"
                >+{{ u.permissions.length - 3 }}</span>
                <span v-if="!(u.permissions || []).length" class="um-perm-hint">未授权</span>
              </div>
            </td>
            <td class="um-muted">{{ formatDate(u.created_at) }}</td>
            <td class="col-actions">
              <div class="um-row-actions">
                <button
                  class="um-link"
                  :disabled="u.is_admin"
                  :title="u.is_admin ? '超级管理员不可编辑' : '编辑'"
                  @click="openEdit(u)"
                >编辑</button>
                <button class="um-link" @click="openResetPassword(u)">重置密码</button>
                <button
                  class="um-link um-link-danger"
                  :disabled="u.is_admin || u.user_id === currentUserId"
                  :title="deleteHint(u)"
                  @click="openDelete(u)"
                >删除</button>
              </div>
            </td>
          </tr>
        </tbody>
      </table>
    </section>

    <!-- 新增 -->
    <div v-if="modal === 'create'" class="um-overlay" @click.self="closeModal">
      <div class="um-dialog um-dialog-lg">
        <header class="um-dialog-head">
          <h3>新增用户</h3>
          <button class="um-icon-btn" @click="closeModal" aria-label="关闭">×</button>
        </header>
        <div class="um-dialog-body">
          <div class="um-form-grid">
            <label class="um-field">
              <span>用户名 <em>*</em></span>
              <input v-model="form.username" placeholder="字母/数字/下划线/横杠，3-32 位" />
            </label>
            <label class="um-field">
              <span>显示名</span>
              <input v-model="form.display_name" placeholder="可选，默认同用户名" />
            </label>
            <label class="um-field um-field-full">
              <span>初始密码 <em>*</em></span>
              <input v-model="form.password" type="password" placeholder="至少 6 位" />
            </label>
          </div>
          <PermissionPicker v-model="form.permissions" :groups="groupedCatalog" />
        </div>
        <p v-if="formMsg" class="um-form-msg" :class="{ err: formErr }">{{ formMsg }}</p>
        <footer class="um-dialog-foot">
          <button class="um-btn" @click="closeModal">取消</button>
          <button class="um-btn um-btn-primary" :disabled="submitting" @click="submitCreate">
            {{ submitting ? '创建中…' : '创建' }}
          </button>
        </footer>
      </div>
    </div>

    <!-- 编辑 -->
    <div v-if="modal === 'edit' && editTarget" class="um-overlay" @click.self="closeModal">
      <div class="um-dialog um-dialog-lg">
        <header class="um-dialog-head">
          <h3>编辑用户 · {{ editTarget.username }}</h3>
          <button class="um-icon-btn" @click="closeModal" aria-label="关闭">×</button>
        </header>
        <div class="um-dialog-body">
          <div class="um-form-grid">
            <label class="um-field">
              <span>用户名</span>
              <input :value="editTarget.username" disabled />
            </label>
            <label class="um-field">
              <span>显示名</span>
              <input v-model="form.display_name" placeholder="显示名称" />
            </label>
          </div>
          <PermissionPicker v-model="form.permissions" :groups="groupedCatalog" />
        </div>
        <p v-if="formMsg" class="um-form-msg" :class="{ err: formErr }">{{ formMsg }}</p>
        <footer class="um-dialog-foot">
          <button class="um-btn" @click="closeModal">取消</button>
          <button class="um-btn um-btn-primary" :disabled="submitting" @click="submitEdit">
            {{ submitting ? '保存中…' : '保存' }}
          </button>
        </footer>
      </div>
    </div>

    <!-- 删除确认 -->
    <div v-if="modal === 'delete' && deleteTarget" class="um-overlay" @click.self="closeModal">
      <div class="um-dialog um-dialog-sm">
        <header class="um-dialog-head">
          <h3>删除用户</h3>
          <button class="um-icon-btn" @click="closeModal" aria-label="关闭">×</button>
        </header>
        <div class="um-dialog-body">
          <p class="um-confirm-text">
            确定删除用户 <strong>{{ deleteTarget.username }}</strong>？
            该操作不可恢复，其对局数据目录仍保留在服务器上。
          </p>
        </div>
        <p v-if="formMsg" class="um-form-msg" :class="{ err: formErr }">{{ formMsg }}</p>
        <footer class="um-dialog-foot">
          <button class="um-btn" @click="closeModal">取消</button>
          <button class="um-btn um-btn-danger" :disabled="submitting" @click="submitDelete">
            {{ submitting ? '删除中…' : '确认删除' }}
          </button>
        </footer>
      </div>
    </div>

    <!-- 重置密码 -->
    <div v-if="modal === 'reset' && resetTarget" class="um-overlay" @click.self="closeModal">
      <div class="um-dialog um-dialog-sm">
        <header class="um-dialog-head">
          <h3>重置密码 · {{ resetTarget.username }}</h3>
          <button class="um-icon-btn" @click="closeModal" aria-label="关闭">×</button>
        </header>
        <div class="um-dialog-body">
          <label class="um-field um-field-full">
            <span>新密码 <em>*</em></span>
            <input v-model="resetPassword" type="password" placeholder="至少 6 位" />
          </label>
        </div>
        <p v-if="formMsg" class="um-form-msg" :class="{ err: formErr }">{{ formMsg }}</p>
        <footer class="um-dialog-foot">
          <button class="um-btn" @click="closeModal">取消</button>
          <button class="um-btn um-btn-primary" :disabled="submitting" @click="submitResetPassword">
            {{ submitting ? '提交中…' : '确认重置' }}
          </button>
        </footer>
      </div>
    </div>
  </div>
</template>

<script setup>
import { ref, reactive, computed, onMounted, defineComponent, h } from 'vue'
import { API_BASE } from './api.js'
import { authedFetch, getCurrentUser } from '../core/authStore.js'

const PermissionPicker = defineComponent({
  name: 'PermissionPicker',
  props: {
    modelValue: { type: Array, default: () => [] },
    groups: { type: Array, default: () => [] },
  },
  emits: ['update:modelValue'],
  setup(props, { emit }) {
    function toggle(key, checked) {
      const set = new Set(props.modelValue)
      if (checked) set.add(key)
      else set.delete(key)
      emit('update:modelValue', [...set])
    }
    return () => h('div', { class: 'um-perm-picker' }, [
      h('div', { class: 'um-perm-picker-title' }, '功能权限'),
      ...props.groups.map(group => h('div', { class: 'um-perm-group', key: group.name }, [
        h('div', { class: 'um-perm-group-label' }, group.name),
        ...group.items.map(item => h('label', { class: 'um-check', key: item.key }, [
          h('input', {
            type: 'checkbox',
            checked: props.modelValue.includes(item.key),
            onChange: (e) => toggle(item.key, e.target.checked),
          }),
          h('span', null, item.label),
        ])),
      ])),
    ])
  },
})

const catalog = ref([])
const users = ref([])
const loading = ref(true)
const keyword = ref('')
const modal = ref(null)
const submitting = ref(false)
const formMsg = ref('')
const formErr = ref(false)

const editTarget = ref(null)
const deleteTarget = ref(null)
const resetTarget = ref(null)
const resetPassword = ref('')

const form = reactive({
  username: '',
  display_name: '',
  password: '',
  permissions: [],
})

const currentUserId = computed(() => getCurrentUser()?.user_id || '')

const permLabelMap = computed(() => {
  const map = {}
  for (const item of catalog.value) map[item.key] = item.label
  return map
})

const groupedCatalog = computed(() => {
  const groups = {}
  for (const item of catalog.value) {
    if (!groups[item.group]) groups[item.group] = []
    groups[item.group].push(item)
  }
  return Object.entries(groups).map(([name, items]) => ({ name, items }))
})

const filteredUsers = computed(() => {
  const q = keyword.value.trim().toLowerCase()
  const list = [...users.value].sort((a, b) => {
    if (a.is_admin !== b.is_admin) return a.is_admin ? -1 : 1
    return (a.username || '').localeCompare(b.username || '')
  })
  if (!q) return list
  return list.filter(u =>
    (u.username || '').toLowerCase().includes(q)
    || (u.display_name || '').toLowerCase().includes(q),
  )
})

function permLabels(keys = []) {
  return keys.map(k => permLabelMap.value[k] || k)
}

function formatDate(ts) {
  if (!ts) return '—'
  const d = new Date(ts * 1000)
  if (Number.isNaN(d.getTime())) return '—'
  return d.toLocaleDateString('zh-CN', { year: 'numeric', month: '2-digit', day: '2-digit' })
}

function deleteHint(u) {
  if (u.is_admin) return '不能删除超级管理员'
  if (u.user_id === currentUserId.value) return '不能删除当前登录账号'
  return '删除'
}

function resetForm() {
  form.username = ''
  form.display_name = ''
  form.password = ''
  form.permissions = []
  resetPassword.value = ''
  formMsg.value = ''
  formErr.value = false
}

function closeModal() {
  modal.value = null
  editTarget.value = null
  deleteTarget.value = null
  resetTarget.value = null
  resetForm()
}

function openCreate() {
  resetForm()
  modal.value = 'create'
}

function openEdit(u) {
  if (u.is_admin) return
  resetForm()
  editTarget.value = u
  form.display_name = u.display_name || ''
  form.permissions = [...(u.permissions || [])]
  modal.value = 'edit'
}

function openDelete(u) {
  if (u.is_admin || u.user_id === currentUserId.value) return
  resetForm()
  deleteTarget.value = u
  modal.value = 'delete'
}

function openResetPassword(u) {
  resetForm()
  resetTarget.value = u
  modal.value = 'reset'
}

async function loadCatalog() {
  const resp = await authedFetch(`${API_BASE}/admin/permissions/catalog`)
  catalog.value = await resp.json()
}

async function loadUsers() {
  loading.value = true
  try {
    const resp = await authedFetch(`${API_BASE}/admin/users`)
    users.value = await resp.json()
  } finally {
    loading.value = false
  }
}

async function submitCreate() {
  formMsg.value = ''
  formErr.value = false
  if (!form.username.trim() || !form.password) {
    formMsg.value = '用户名和密码不能为空'
    formErr.value = true
    return
  }
  submitting.value = true
  try {
    const resp = await authedFetch(`${API_BASE}/admin/users`, {
      method: 'POST',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        username: form.username.trim(),
        password: form.password,
        display_name: form.display_name.trim(),
        permissions: form.permissions,
      }),
    })
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) throw new Error(data.detail || `创建失败(${resp.status})`)
    closeModal()
    await loadUsers()
  } catch (e) {
    formMsg.value = e.message
    formErr.value = true
  } finally {
    submitting.value = false
  }
}

async function submitEdit() {
  if (!editTarget.value) return
  formMsg.value = ''
  formErr.value = false
  submitting.value = true
  try {
    const resp = await authedFetch(`${API_BASE}/admin/users/${editTarget.value.user_id}`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({
        display_name: form.display_name.trim(),
        permissions: form.permissions,
      }),
    })
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) throw new Error(data.detail || `保存失败(${resp.status})`)
    closeModal()
    await loadUsers()
  } catch (e) {
    formMsg.value = e.message
    formErr.value = true
  } finally {
    submitting.value = false
  }
}

async function submitDelete() {
  if (!deleteTarget.value) return
  formMsg.value = ''
  formErr.value = false
  submitting.value = true
  try {
    const resp = await authedFetch(`${API_BASE}/admin/users/${deleteTarget.value.user_id}`, {
      method: 'DELETE',
    })
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) throw new Error(data.detail || `删除失败(${resp.status})`)
    closeModal()
    await loadUsers()
  } catch (e) {
    formMsg.value = e.message
    formErr.value = true
  } finally {
    submitting.value = false
  }
}

async function submitResetPassword() {
  if (!resetTarget.value) return
  formMsg.value = ''
  formErr.value = false
  if (resetPassword.value.length < 6) {
    formMsg.value = '密码至少 6 位'
    formErr.value = true
    return
  }
  submitting.value = true
  try {
    const resp = await authedFetch(`${API_BASE}/admin/users/${resetTarget.value.user_id}/password`, {
      method: 'PATCH',
      headers: { 'Content-Type': 'application/json' },
      body: JSON.stringify({ new_password: resetPassword.value }),
    })
    const data = await resp.json().catch(() => ({}))
    if (!resp.ok) throw new Error(data.detail || `重置失败(${resp.status})`)
    closeModal()
  } catch (e) {
    formMsg.value = e.message
    formErr.value = true
  } finally {
    submitting.value = false
  }
}

onMounted(async () => {
  await Promise.all([loadCatalog(), loadUsers()])
})
</script>

<style scoped>
.um-page {
  height: 100%;
  overflow-y: auto;
  padding: 28px 32px 40px;
  color: #e8e4f4;
  font-size: 13px;
}

.um-page-head {
  display: flex;
  align-items: flex-start;
  justify-content: space-between;
  gap: 16px;
  margin-bottom: 20px;
}

.um-page-head h1 {
  margin: 0 0 6px;
  font-size: 22px;
  font-weight: 700;
  color: #f5f2ff;
}

.um-page-head p {
  margin: 0;
  font-size: 13px;
  color: #9b93b8;
  max-width: 520px;
  line-height: 1.5;
}

.um-toolbar {
  display: flex;
  align-items: center;
  justify-content: space-between;
  gap: 12px;
  margin-bottom: 14px;
}

.um-search {
  display: flex;
  align-items: center;
  gap: 8px;
  flex: 1;
  max-width: 320px;
  padding: 0 12px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.22);
  color: #8f86ad;
}

.um-search input {
  flex: 1;
  border: none;
  background: transparent;
  color: #edf0ff;
  padding: 9px 0;
  font-size: 13px;
  outline: none;
}

.um-search input::placeholder { color: #6f678a; }

.um-count {
  font-size: 12px;
  color: #7d759c;
}

.um-table-wrap {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 12px;
  background: rgba(255, 255, 255, 0.02);
  overflow: hidden;
}

.um-table {
  width: 100%;
  border-collapse: collapse;
}

.um-table th,
.um-table td {
  padding: 12px 16px;
  text-align: left;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
  vertical-align: middle;
}

.um-table th {
  font-size: 11px;
  font-weight: 700;
  letter-spacing: 0.04em;
  color: #8c84a8;
  background: rgba(0, 0, 0, 0.18);
  white-space: nowrap;
}

.um-table tbody tr:hover {
  background: rgba(105, 220, 255, 0.04);
}

.um-table tbody tr:last-child td {
  border-bottom: none;
}

.col-actions { width: 200px; text-align: right; }

.um-username {
  font-weight: 600;
  color: #f0ecff;
}

.um-muted { color: #8a82a6; font-size: 12px; white-space: nowrap; }

.um-empty-cell {
  text-align: center;
  color: #7a7396;
  padding: 36px 16px !important;
}

.um-tag {
  display: inline-flex;
  align-items: center;
  padding: 2px 8px;
  border-radius: 999px;
  font-size: 11px;
  font-weight: 600;
  background: rgba(255, 255, 255, 0.06);
  color: #c5bddf;
}

.um-tag-admin {
  background: rgba(255, 196, 87, 0.14);
  color: #ffd060;
}

.um-tag-perm {
  background: rgba(105, 220, 255, 0.1);
  color: #8edfff;
  margin: 2px 4px 2px 0;
}

.um-tag-more {
  background: rgba(255, 255, 255, 0.05);
  color: #9b93b8;
}

.um-perm-tags {
  display: flex;
  flex-wrap: wrap;
  gap: 2px;
}

.um-perm-hint {
  font-size: 12px;
  color: #7d759c;
}

.um-row-actions {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
}

.um-link {
  border: none;
  background: none;
  padding: 0;
  font-size: 12px;
  color: #69dcff;
  cursor: pointer;
}

.um-link:hover:not(:disabled) { text-decoration: underline; }

.um-link:disabled {
  color: #5c5678;
  cursor: not-allowed;
}

.um-link-danger { color: #ff7b72; }

.um-btn {
  border: 1px solid rgba(255, 255, 255, 0.14);
  background: rgba(255, 255, 255, 0.04);
  color: #d8d2ef;
  font-size: 13px;
  padding: 8px 16px;
  border-radius: 8px;
  cursor: pointer;
  white-space: nowrap;
}

.um-btn:hover:not(:disabled) {
  background: rgba(255, 255, 255, 0.08);
}

.um-btn:disabled {
  opacity: 0.5;
  cursor: not-allowed;
}

.um-btn-primary {
  background: linear-gradient(135deg, #69dcff, #5b8bff);
  color: #06121f;
  font-weight: 700;
  border: none;
}

.um-btn-danger {
  background: rgba(255, 95, 82, 0.16);
  color: #ff8a80;
  border-color: rgba(255, 95, 82, 0.35);
}

.um-overlay {
  position: fixed;
  inset: 0;
  background: rgba(6, 4, 18, 0.72);
  display: flex;
  align-items: center;
  justify-content: center;
  z-index: 1000;
  padding: 24px;
}

.um-dialog {
  width: 100%;
  max-height: 90vh;
  display: flex;
  flex-direction: column;
  border-radius: 14px;
  border: 1px solid rgba(255, 255, 255, 0.1);
  background: #16102c;
  box-shadow: 0 24px 64px rgba(0, 0, 0, 0.45);
}

.um-dialog-sm { max-width: 420px; }
.um-dialog-lg { max-width: 640px; }

.um-dialog-head {
  display: flex;
  align-items: center;
  justify-content: space-between;
  padding: 18px 20px 12px;
  border-bottom: 1px solid rgba(255, 255, 255, 0.06);
}

.um-dialog-head h3 {
  margin: 0;
  font-size: 16px;
  font-weight: 700;
}

.um-dialog-body {
  padding: 16px 20px;
  overflow-y: auto;
}

.um-dialog-foot {
  display: flex;
  justify-content: flex-end;
  gap: 10px;
  padding: 12px 20px 18px;
  border-top: 1px solid rgba(255, 255, 255, 0.06);
}

.um-icon-btn {
  border: none;
  background: none;
  color: #9b93b8;
  font-size: 22px;
  line-height: 1;
  cursor: pointer;
  padding: 0 4px;
}

.um-form-grid {
  display: grid;
  grid-template-columns: 1fr 1fr;
  gap: 14px;
  margin-bottom: 16px;
}

.um-field {
  display: flex;
  flex-direction: column;
  gap: 6px;
}

.um-field-full { grid-column: 1 / -1; }

.um-field span {
  font-size: 12px;
  color: #a59dc4;
  font-weight: 600;
}

.um-field span em {
  color: #ff8a80;
  font-style: normal;
}

.um-field input {
  border: 1px solid rgba(255, 255, 255, 0.12);
  border-radius: 8px;
  background: rgba(0, 0, 0, 0.28);
  color: #edf0ff;
  padding: 9px 11px;
  font-size: 13px;
  outline: none;
}

.um-field input:focus {
  border-color: rgba(105, 220, 255, 0.45);
}

.um-field input:disabled {
  opacity: 0.55;
  cursor: not-allowed;
}

.um-form-msg {
  margin: 0 20px 8px;
  font-size: 12px;
  color: #8be28b;
}

.um-form-msg.err { color: #ff7b72; }

.um-confirm-text {
  margin: 0;
  line-height: 1.6;
  color: #c8c0e0;
}

.um-confirm-text strong { color: #f5f2ff; }

:deep(.um-perm-picker) {
  border: 1px solid rgba(255, 255, 255, 0.08);
  border-radius: 10px;
  padding: 14px 16px;
  background: rgba(0, 0, 0, 0.15);
}

:deep(.um-perm-picker-title) {
  font-size: 12px;
  font-weight: 700;
  color: #a59dc4;
  margin-bottom: 12px;
}

:deep(.um-perm-group) {
  margin-bottom: 12px;
}

:deep(.um-perm-group:last-child) {
  margin-bottom: 0;
}

:deep(.um-perm-group-label) {
  font-size: 11px;
  font-weight: 700;
  color: #69dcff;
  margin-bottom: 8px;
}

:deep(.um-check) {
  display: flex;
  align-items: flex-start;
  gap: 8px;
  font-size: 12px;
  color: #cdd6ee;
  margin-bottom: 6px;
  cursor: pointer;
  line-height: 1.45;
}

:deep(.um-check input) {
  margin-top: 2px;
  flex-shrink: 0;
}

@media (max-width: 900px) {
  .um-page { padding: 20px 16px; }
  .um-page-head { flex-direction: column; }
  .um-form-grid { grid-template-columns: 1fr; }
  .um-table-wrap { overflow-x: auto; }
  .um-table { min-width: 720px; }
}
</style>
